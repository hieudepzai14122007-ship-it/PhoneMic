"""PhoneMic Wi-Fi 0.2 — Windows 11 receiver UI."""
import ipaddress
import os
from pathlib import Path
import queue
import socket
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser
import qrcode
from PIL import ImageTk
import sounddevice as sd
from audio_engine import AudioSink
from server import MicServer

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'PhoneMic-WiFi' / 'certificates'


def addresses():
    values = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            # A UDP connect chooses a route; it sends no audio or network packet.
            probe.connect(('192.0.2.1', 9))
            values.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        values.extend(x[4][0] for x in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    return list(dict.fromkeys(x for x in values if ipaddress.ip_address(x).is_private
        and not ipaddress.ip_address(x).is_loopback and not ipaddress.ip_address(x).is_link_local))


class App:
    def __init__(self, root):
        self.root = root
        self.server = self.sink = None
        self.events = queue.Queue()
        self.busy = False
        self.closing = False
        self.images = []
        self.stop_reason = ''
        root.title('PhoneMic Wi-Fi · iPhone → Windows 11 · 0.2 thử nghiệm')
        root.geometry(f'850x{min(800, max(600, root.winfo_screenheight()-100))}')
        root.minsize(760, 600)
        root.configure(bg='#f2f6f5')
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10))
        style.configure('TFrame', background='#f2f6f5')
        style.configure('TLabel', background='#f2f6f5')
        style.configure('Title.TLabel', font=('Segoe UI', 25, 'bold'), foreground='#173d36')
        style.configure('TButton', padding=8)
        canvas = tk.Canvas(root, bg='#f2f6f5', highlightthickness=0)
        scrollbar = ttk.Scrollbar(root, orient='vertical', command=canvas.yview)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        body = ttk.Frame(canvas, padding=24)
        window_id = canvas.create_window((0, 0), window=body, anchor='nw')
        body.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(window_id, width=e.width))
        ttk.Label(body, text='PhoneMic Wi-Fi', style='Title.TLabel').pack(anchor='w')
        ttk.Label(body, text='Mic iPhone cho laptop · cùng mạng Wi-Fi · không lưu bản ghi âm').pack(anchor='w', pady=(3,18))
        row = ttk.Frame(body); row.pack(fill='x', pady=5)
        ttk.Label(row, text='IP Wi-Fi của laptop', width=22).pack(side='left')
        ips = addresses()
        self.ip = ttk.Combobox(row, values=ips, width=25)
        self.ip.pack(side='left', fill='x', expand=True)
        if ips: self.ip.set(ips[0])
        row = ttk.Frame(body); row.pack(fill='x', pady=5)
        ttk.Label(row, text='Gửi âm thanh vào', width=22).pack(side='left')
        self.device = ttk.Combobox(row, state='readonly')
        self.device.pack(side='left', fill='x', expand=True)
        self.refresh_button = ttk.Button(row, text='Làm mới', command=self.refresh)
        self.refresh_button.pack(side='left', padx=(6,0))
        row = ttk.Frame(body); row.pack(fill='x', pady=(10,8))
        self.start_button = ttk.Button(row, text='Bắt đầu nhận mic', command=self.start)
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(row, text='Dừng', command=self.stop, state='disabled')
        self.stop_button.pack(side='left', padx=8)
        ttk.Button(row, text='Native iPhone QR', command=self.native_qr).pack(side='left', padx=4)
        ttk.Button(row, text='Tải VB-CABLE', command=lambda:webbrowser.open('https://vb-audio.com/Cable/')).pack(side='right')
        ttk.Button(row, text='Hướng dẫn', command=lambda:webbrowser.open((BASE/'HUONG-DAN.html').as_uri())).pack(side='right',padx=8)
        self.status = tk.StringVar(value='Cài VB-CABLE, chọn CABLE Input rồi nhấn Bắt đầu.')
        ttk.Label(body, textvariable=self.status, wraplength=750, foreground='#195c4b').pack(anchor='w', pady=(8,8))
        self.meter = ttk.Progressbar(body, maximum=100)
        self.meter.pack(fill='x')
        qr_row = ttk.Frame(body); qr_row.pack(fill='x', pady=16)
        self.qr_labels = []
        for title in ['1 · Cài iPhone lần đầu', '2 · Bật mic (mỗi lần dùng)']:
            panel = ttk.Frame(qr_row); panel.pack(side='left',fill='both',expand=True)
            ttk.Label(panel,text=title,font=('Segoe UI',11,'bold')).pack()
            label = ttk.Label(panel, text='QR sẽ hiện sau khi Bắt đầu', anchor='center')
            label.pack(pady=10)
            self.qr_labels.append(label)
        self.setup_url = tk.StringVar()
        self.mic_url = tk.StringVar()
        for title, var in [('Cài iPhone:',self.setup_url), ('Bật mic:',self.mic_url)]:
            row=ttk.Frame(body);row.pack(fill='x',pady=3)
            ttk.Label(row,text=title,width=13).pack(side='left')
            ttk.Entry(row,textvariable=var,state='readonly').pack(side='left',fill='x',expand=True)
            ttk.Button(row,text='Chép',command=lambda v=var:self.copy(v.get())).pack(side='left',padx=(6,0))
        self.cert_info=tk.StringVar(value='Chứng chỉ riêng cho laptop sẽ được tạo khi Bắt đầu.')
        ttk.Label(body,textvariable=self.cert_info,wraplength=750,font=('Segoe UI',9)).pack(anchor='w',pady=10)
        ttk.Label(body,text='Trong Zoom / Discord / Zalo: chọn Microphone = CABLE Output.\nGiữ Safari và màn hình iPhone mở. Cho phép kết nối trên mạng Private nếu Windows hỏi.',
                  wraplength=750).pack(anchor='w',pady=5)
        ttk.Button(body, text='Quên ghép nối (khi đã Dừng)', command=self.reset_pairing).pack(anchor='w', pady=8)
        self.refresh()
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.after(100,self.poll)

    def copy(self,text):
        self.root.clipboard_clear();self.root.clipboard_append(text)

    def native_qr(self):
        if not self.server or self.busy:
            messagebox.showinfo('Native iPhone', 'Nhấn Bắt đầu nhận mic trước.'); return
        dialog = tk.Toplevel(self.root); dialog.title('Pair native iPhone app')
        ttk.Label(dialog, text='Quét trong app PhoneMic iPhone native.\nApp native cần build/ký bằng Xcode; xem ios/README.md.', padding=14).pack()
        qr = qrcode.QRCode(box_size=5, border=4); qr.add_data(self.server.native_url); qr.make(fit=True)
        img = ImageTk.PhotoImage(qr.make_image().convert('RGB'))
        label = ttk.Label(dialog, image=img); label.image = img; label.pack(padx=20)
        url = self.server.native_url
        ttk.Button(dialog, text='Chép link ghép nối', command=lambda: self.copy(url)).pack(pady=10)
        ttk.Label(dialog, text='Không cần cài hồ sơ chứng chỉ cho app native.\nKhông chia sẻ mã QR/link này với người khác.', padding=14).pack()

    def reset_pairing(self):
        if self.server or self.busy:
            messagebox.showinfo('Ghép nối', 'Dừng nhận mic trước khi quên ghép nối.'); return
        if messagebox.askyesno('Quên ghép nối', 'Vô hiệu hóa các QR cũ? iPhone cần quét QR mới ở lần dùng tiếp theo.'):
            (DATA / 'pairing-token.txt').unlink(missing_ok=True)
            self.status.set('Đã quên ghép nối. Bắt đầu lại để có QR mới.')

    def refresh(self):
        if self.server or self.busy: return
        try:
            hosts=sd.query_hostapis()
            devices=[(i,d) for i,d in enumerate(sd.query_devices())
                     if d['max_output_channels'] > 0 and 'cable' in d['name'].lower() and 'input' in d['name'].lower()]
            devices.sort(key=lambda item:('wasapi' not in hosts[item[1]['hostapi']]['name'].lower(),item[0]))
            self.devices=devices
            self.device['values']=[f"{d['name']} · {hosts[d['hostapi']]['name']}" for i,d in devices]
            if devices:self.device.current(0)
            else:self.device.set('Chưa thấy VB-CABLE — cài driver rồi mở lại PhoneMic')
        except Exception as e:
            self.devices=[]
            self.status.set(f'Không đọc được thiết bị âm thanh: {e}')

    def start(self):
        if self.busy or self.server:return
        self.stop_reason = ''
        try:
            address=ipaddress.ip_address(self.ip.get().strip())
            if address.version!=4 or not address.is_private or address.is_loopback or address.is_link_local or address.is_unspecified:
                raise ValueError()
        except ValueError:
            messagebox.showerror('Địa chỉ Wi-Fi','Chọn IPv4 của card Wi-Fi trên laptop, ví dụ 192.168.1.12. Xem ipconfig nếu cần.');return
        selection=self.device.current()
        if selection < 0 or not self.devices:
            messagebox.showinfo('Cần mic ảo','Cài VB-CABLE từ trang chính thức, khởi động lại Windows rồi mở lại PhoneMic.');return
        device_id=self.devices[selection][0]
        self.busy=True
        self.start_button['state']='disabled';self.refresh_button['state']='disabled';self.ip['state']='disabled';self.device['state']='disabled'
        self.status.set('Đang mở mic ảo và tạo kết nối…')
        def worker():
            sink=server=None
            try:
                sink=AudioSink(device_id);sink.start()
                server=MicServer(str(address), DATA, sink, lambda t:self.events.put(('status',t)))
                server.start()
                # Wait for startup; cryptography and bind errors are returned to UI.
                server.ready.wait()
                if server.error:raise RuntimeError(server.error)
                self.events.put(('started',(server,sink)))
            except Exception as e:
                if server:server.stop()
                if sink:sink.close()
                self.events.put(('error',str(e)))
        threading.Thread(target=worker,daemon=True).start()

    def stop(self):
        if self.busy:return
        if not self.server:
            if self.closing:self.root.destroy()
            return
        self.busy=True;self.stop_button['state']='disabled'
        self.status.set('Đang dừng…')
        server,sink=self.server,self.sink
        def worker():
            server.stop();sink.close()
            self.events.put(('stopped',None))
        threading.Thread(target=worker,daemon=True).start()

    def close(self):
        self.closing=True
        if self.busy:
            self.status.set('Đang hoàn tất thao tác và đóng…');return
        self.stop()

    def controls_reset(self):
        self.busy=False;self.start_button['state']='normal';self.stop_button['state']='disabled'
        self.refresh_button['state']='normal';self.ip['state']='normal';self.device['state']='readonly'

    def poll(self):
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='status':self.status.set(value)
                elif kind=='started':
                    self.server,self.sink=value;self.busy=False;self.stop_button['state']='normal'
                    self.status.set('Sẵn sàng. Cài chứng chỉ bằng QR 1, sau đó mở QR 2 bằng Safari.')
                    self.setup_url.set(self.server.setup_url);self.mic_url.set(self.server.url)
                    self.images=[]
                    for label,url in zip(self.qr_labels,[self.server.setup_url,self.server.url]):
                        qr=qrcode.QRCode(box_size=4,border=4);qr.add_data(url);qr.make(fit=True)
                        image=ImageTk.PhotoImage(qr.make_image(fill_color='#173d36',back_color='white').convert('RGB'))
                        self.images.append(image);label.configure(image=image,text='')
                    self.cert_info.set(self.server.cert['name']+'\nSHA-256: '+self.server.cert['fingerprint'])
                    if self.closing:self.stop()
                elif kind=='error':
                    self.controls_reset();self.status.set('Không khởi động được: '+value)
                    if self.closing:self.root.destroy();return
                    messagebox.showerror('PhoneMic',value+'\n\nKiểm tra IP Wi-Fi, driver VB-CABLE và cổng 8765/8766. Xem hướng dẫn kèm theo.')
                elif kind=='stopped':
                    self.server=self.sink=None;self.controls_reset();self.status.set('Đã dừng. Không còn thu hoặc nhận âm thanh.')
                    if self.stop_reason: self.status.set(self.stop_reason)
                    self.setup_url.set('');self.mic_url.set('')
                    for label in self.qr_labels:label.configure(image='',text='QR sẽ hiện sau khi Bắt đầu')
                    self.images=[]
                    if self.closing:self.root.destroy();return
        except queue.Empty:pass
        self.meter['value']=self.sink.peak*100 if self.sink else 0
        if self.server and self.sink and not self.busy:
            try: healthy = self.sink.healthy
            except Exception: healthy = False
            if not healthy:
                self.stop_reason = 'Thiết bị âm thanh đã ngừng. Kiểm tra VB-CABLE, rồi nhấn Bắt đầu lại.'
                self.stop()
        self.root.after(100,self.poll)


if __name__=='__main__':
    root=tk.Tk()
    App(root)
    root.mainloop()
