import asyncio
import hmac
import html
import json
from pathlib import Path
import secrets
import ssl
import threading
from urllib.parse import urlencode
from aiohttp import web, WSMsgType
from certificates import prepare, private_write
from session_protocol import FrameWindow

WEB = Path(__file__).parent / 'web'


class MicServer:
    def __init__(self, address, directory, sink, notify=lambda text: None,
                 https_port=8765, setup_port=8766):
        self.address, self.directory, self.sink = address, directory, sink
        self.notify = notify
        self.https_port, self.setup_port = https_port, setup_port
        self.token = secrets.token_urlsafe(24)
        self.setup_token = secrets.token_urlsafe(24)
        self.connection = None
        self.owner_id = None
        self.stopping = False
        self.loop = None
        self.thread = None
        self.ready = threading.Event()
        self.error = None
        self.cert = None

    @property
    def url(self):
        return f'https://{self.address}:{self.https_port}/#' + self.token

    @property
    def setup_url(self):
        return f'http://{self.address}:{self.setup_port}/{self.setup_token}/'

    @property
    def native_url(self):
        return 'phonemic://pair?' + urlencode({'host': self.address, 'port': self.https_port,
            'token': self.token, 'ca': self.cert['fingerprint'].replace(':', '').lower()})

    def make_app(self):
        app = web.Application(client_max_size=16384)
        for filename, route in [('index.html', '/'), ('client.js', '/client.js'),
                                ('pcm-worklet.js', '/pcm-worklet.js'), ('session-policy.js', '/session-policy.js'),
                                ('style.css', '/style.css')]:
            async def serve(request, filename=filename):
                response = web.FileResponse(WEB / filename)
                response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                    'Referrer-Policy': 'no-referrer', 'Permissions-Policy': 'microphone=(self), camera=()',
                    'Content-Security-Policy': "default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
                return response
            app.router.add_get(route, serve)
        app.router.add_get('/audio', self.audio)
        return app

    async def audio(self, request):
        # Reject browsers connecting from unrelated pages.
        if request.headers.get('Origin') != f'https://{self.address}:{self.https_port}':
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse(max_msg_size=8192, heartbeat=5, compress=False, timeout=1)
        await ws.prepare(request)
        owned = False
        try:
            try:
                message = await asyncio.wait_for(ws.receive(), timeout=5)
                hello = json.loads(message.data) if message.type == WSMsgType.TEXT else {}
                if not isinstance(hello, dict):
                    raise ValueError()
            except (ValueError, TypeError, asyncio.TimeoutError):
                await ws.close(code=1008, message=b'Invalid handshake')
                return ws
            if not isinstance(hello.get('token'), str) or not hmac.compare_digest(hello['token'], self.token):
                await ws.close(code=1008, message=b'Wrong pairing token')
                return ws
            rate = hello.get('rate')
            if type(rate) is not int or rate not in (44100, 48000):
                await ws.close(code=1008, message=b'Unsupported sample rate')
                return ws
            version = hello.get('protocol', 1)
            client_id = hello.get('client_id')
            if version not in (1, 2) or (version == 2 and (not isinstance(client_id, str) or not 16 <= len(client_id) <= 80)):
                await ws.close(code=1008, message=b'Invalid protocol or client ID')
                return ws
            if self.stopping:
                await ws.close(code=4000, message=b'Receiver stopped')
                return ws
            old = self.connection
            if old is not None and (version != 2 or self.owner_id != client_id):
                await ws.close(code=4003, message=b'Another phone is connected')
                return ws
            # Claim synchronously before awaiting close: old finally must not clear new audio.
            self.connection = ws
            self.owner_id = client_id if version == 2 else None
            owned = True
            self.sink.begin(rate)
            if old is not None:
                await old.close(code=4001, message=b'Session replaced')
            if self.connection is not ws or self.stopping:
                await ws.close(code=4001, message=b'Session replaced')
                return ws
            self.notify('Đã kết nối iPhone — đang nhận mic')
            await ws.send_json({'type': 'ready', 'protocol': version})
            window_start = asyncio.get_running_loop().time()
            window_bytes = 0
            frames = FrameWindow()
            last_ack = 0
            while True:
                msg = await asyncio.wait_for(ws.receive(), timeout=3)
                if self.connection is not ws:
                    break
                if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                    break
                if msg.type != WSMsgType.BINARY or not 0 < len(msg.data) <= 4112 or len(msg.data) % 2:
                    await ws.close(code=1008, message=b'Invalid PCM packet')
                    break
                now = asyncio.get_running_loop().time()
                if now - window_start >= 1:
                    window_bytes = 0
                    window_start = now
                window_bytes += len(msg.data)
                if window_bytes > rate * 6:
                    await ws.close(code=1008, message=b'Too much audio data')
                    break
                try:
                    pcm = frames.accept(msg.data, now) if version == 2 else msg.data
                except ValueError:
                    await ws.close(code=1008, message=b'Invalid PCM frame')
                    break
                except TimeoutError:
                    self.sink.clear()
                    await ws.close(code=4002, message=b'Stale audio; reconnect')
                    break
                if not getattr(self.sink, 'healthy', True):
                    await ws.close(code=4004, message=b'Windows audio device unavailable')
                    break
                self.sink.feed(pcm)
                if version == 2 and now-last_ack >= .1:
                    await ws.send_json({'type': 'ack', 'seq': frames.sequence})
                    last_ack = now
        except asyncio.TimeoutError:
            await ws.close(code=1001, message=b'Audio stopped. Tap Start again.')
        except Exception:
            self.notify('Lỗi luồng âm thanh. Nhấn Dừng rồi Bắt đầu lại.')
            await ws.close(code=1011, message=b'Audio error')
        finally:
            if owned and self.connection is ws:
                self.connection = None
                self.owner_id = None
                self.sink.clear()
                self.notify('iPhone đã ngắt — quét lại QR hoặc nhấn Bật mic')
        return ws

    def setup_app(self):
        app = web.Application()
        async def page(request):
            name = html.escape(self.cert['name'])
            body = f'''<!doctype html><html lang="vi"><meta charset="utf-8">
            <meta name="viewport" content="width=device-width,initial-scale=1">
            <title>Cài đặt PhoneMic</title><body style="font:18px system-ui;max-width:600px;margin:40px auto;padding:20px;line-height:1.6">
            <h1>Cài đặt iPhone</h1><p>Chỉ cần làm một lần cho laptop này.</p>
            <p>Chứng chỉ: <strong>{name}</strong>. Đối chiếu tên này với cửa sổ PhoneMic trên laptop.</p>
            <p><a href="certificate.mobileconfig">1. Tải hồ sơ chứng chỉ</a></p>
            <p>2. Vào Cài đặt → Cài đặt chung → VPN &amp; Quản lý thiết bị → chọn hồ sơ trên → Cài đặt.</p>
            <p>3. Cài đặt → Cài đặt chung → Giới thiệu → Cài đặt tin cậy chứng nhận → bật tin cậy cho đúng chứng chỉ này.</p>
            <p>4. Quét <strong>QR Bật mic</strong> trên laptop bằng Camera, mở trong Safari.</p>
            <p>Hồ sơ chỉ chứa chứng chỉ HTTPS. Không có VPN hay quản lý thiết bị. Việc bật tin cậy cho phép iPhone tin các chứng chỉ do laptop này ký; chỉ làm trên laptop và Wi-Fi bạn tin cậy. Khi gỡ PhoneMic, xóa hồ sơ này.</p>
            <p>SHA-256:</p><small style="overflow-wrap:anywhere">{self.cert['fingerprint']}</small></body></html>'''
            return web.Response(text=body, content_type='text/html', headers={'Cache-Control': 'no-store'})
        async def profile(request):
            return web.Response(body=self.cert['profile'], content_type='application/x-apple-aspen-config',
                headers={'Content-Disposition': 'attachment; filename="PhoneMic.mobileconfig"', 'Cache-Control': 'no-store'})
        app.router.add_get(f'/{self.setup_token}/', page)
        app.router.add_get(f'/{self.setup_token}/certificate.mobileconfig', profile)
        return app

    async def run(self):
        runners = []
        try:
            self.cert = await asyncio.to_thread(prepare, self.directory, self.address)
            pair_file = Path(self.directory) / 'pairing-token.txt'
            if pair_file.exists():
                stored = pair_file.read_text().strip()
                if len(stored) != 32 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in stored):
                    raise RuntimeError('Pairing data is invalid. Reset pairing in PhoneMic.')
                self.token = stored
            else:
                private_write(pair_file, self.token.encode('ascii'))
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(self.cert['cert'], self.cert['key'])
            for app, port, tls in [(self.make_app(), self.https_port, context),
                                   (self.setup_app(), self.setup_port, None)]:
                runner = web.AppRunner(app, access_log=None, shutdown_timeout=2)
                runners.append(runner)
                await runner.setup()
                await web.TCPSite(runner, self.address, port, ssl_context=tls).start()
            self.stop_event = asyncio.Event()
            self.ready.set()
            await self.stop_event.wait()
        except Exception as e:
            self.error = str(e)
            self.ready.set()
        finally:
            self.stopping = True
            if self.connection is not None:
                await self.connection.close(code=4000, message=b'Receiver stopped')
            for runner in reversed(runners):
                await runner.cleanup()
            self.sink.clear()

    def start(self):
        def worker():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(self.run())
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())
                self.loop.run_until_complete(self.loop.shutdown_default_executor())
            finally:
                self.loop.close()
        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()

    def stop(self):
        if self.loop and self.loop.is_running() and hasattr(self, 'stop_event'):
            self.loop.call_soon_threadsafe(self.stop_event.set)
        if self.thread:
            self.thread.join(timeout=6)
