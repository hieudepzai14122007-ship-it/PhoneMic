'use strict';
const $ = id => document.getElementById(id), policy=PhoneMicPolicy;
const token=location.hash.slice(1);
let clientID;
try {clientID=sessionStorage.getItem('phonemic-client') || crypto.randomUUID();sessionStorage.setItem('phonemic-client',clientID);}
catch {clientID=crypto.randomUUID();}
let current=null;
function show(title,detail) {$('status').textContent=title;$('detail').textContent=detail;}
function settings() {
  current?.worklet?.port.postMessage({gain:Number($('gain').value)/100,muted:current.muted});
}
function closeLink(s) {
  ++s.linkGeneration;
  clearTimeout(s.retryTimer);clearTimeout(s.handshakeTimer);
  s.connected=false;
  if(s.ws) {s.ws.onclose=s.ws.onerror=s.ws.onmessage=s.ws.onopen=null;s.ws.close();s.ws=null;}
}
function stop(title='Đã dừng mic', detail='Nhấn Bật mic để bắt đầu.') {
  const s=current;current=null;
  if(s) {
    closeLink(s);clearInterval(s.watchdog);
    s.stream?.getTracks().forEach(t=>t.stop());
    if(s.context) {s.context.onstatechange=null;void s.context.close().catch(()=>{});}
    if(s.wake) void s.wake.release().catch(()=>{});
  }
  $('start').disabled=false;$('start').textContent='Bật mic';$('mute').disabled=true;
  $('mute').textContent='Tắt tiếng';$('level').value=0;$('orb').classList.remove('live');
  show(title,detail);
}
function retry(s, reason) {
  if(current!==s)return;
  closeLink(s);
  if(document.hidden) {stop('Safari đang tạm dừng','Mở Safari rồi nhấn Bật mic.');return;}
  const delay=s.budget.next();
  if(delay===null) {stop('Đã hết thời gian kết nối lại','Kiểm tra laptop và Wi-Fi rồi nhấn Bật mic.');return;}
  $('orb').classList.remove('live');$('level').value=0;
  show('Đang kết nối lại…',reason+' Âm thanh trong lúc mất mạng sẽ bị bỏ.');
  s.retryTimer=setTimeout(()=>connect(s),delay);
}
function connect(s) {
  if(current!==s)return;
  closeLink(s);
  if(document.hidden || s.context.state!=='running') {stop('Cần bật lại mic','Mở Safari rồi nhấn Bật mic.');return;}
  if(s.budget.deadline!==null && performance.now()>=s.budget.deadline) {stop('Đã hết thời gian kết nối lại');return;}
  const generation=s.linkGeneration;
  const valid=()=>current===s && generation===s.linkGeneration;
  const ws=new WebSocket(`wss://${location.host}/audio`);s.ws=ws;
  s.handshakeTimer=setTimeout(()=>{if(valid())retry(s,'Laptop chưa trả lời.');},5000);
  ws.onopen=()=>{if(valid())ws.send(JSON.stringify({token,rate:s.context.sampleRate,protocol:2,client_id:clientID}));};
  ws.onerror=()=>{};
  ws.onclose=event=>{
    if(!valid())return;
    if(policy.terminal(event.code)) {
      const text={4000:'Laptop đã dừng nhận mic.',4001:'Phiên này đã được thay thế.',4003:'Một điện thoại khác đang dùng mic.',1008:'Cần ghép nối lại bằng QR trên laptop.'};
      stop('Phiên đã kết thúc',text[event.code]);
    } else retry(s,'Mất kết nối với laptop.');
  };
  ws.onmessage=event=>{
    if(!valid())return;
    let msg;try{msg=JSON.parse(event.data);}catch{return;}
    if(msg.type==='ready' && !s.connected) {
      clearTimeout(s.handshakeTimer);s.connected=true;s.sequence=0;s.ackSequence=0;
      s.lastAck=performance.now();s.connectedAt=s.lastAck;
      $('orb').classList.add('live');
      show(s.muted?'Đã tắt tiếng':'Mic đang bật','Kết nối tự phục hồi khi Wi-Fi gián đoạn ngắn.');
    } else if(msg.type==='ack' && Number.isInteger(msg.seq) && msg.seq>s.ackSequence && msg.seq<=s.sequence) {
      s.ackSequence=msg.seq;s.lastAck=performance.now();
      if(s.lastAck-s.connectedAt>=10000)s.budget.reset();
    }
  };
}
async function start() {
  if(current) {stop();return;}
  const s={muted:false,linkGeneration:0,connected:false,lastPacket:performance.now(),budget:new policy.RetryBudget()};
  current=s;$('start').textContent='Dừng mic';$('start').disabled=false;
  const valid=()=>current===s;
  try {
    if(!token)throw new Error('Quét QR Bật mic trên laptop.');
    if(!isSecureContext || !navigator.mediaDevices?.getUserMedia)throw new Error('Hoàn tất tin cậy chứng chỉ HTTPS trong hướng dẫn.');
    show('Đang xin quyền mic…','Chọn Cho phép khi Safari hỏi.');
    s.context=new AudioContext({sampleRate:48000,latencyHint:'interactive'});
    const resume=s.context.resume();resume.catch(()=>{});
    const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
    if(!valid()) {stream.getTracks().forEach(t=>t.stop());return;}
    s.stream=stream;await resume;if(!valid())return;
    await s.context.audioWorklet.addModule('/pcm-worklet.js');if(!valid())return;
    s.source=s.context.createMediaStreamSource(stream);
    s.worklet=new AudioWorkletNode(s.context,'pcm-recorder',{numberOfInputs:1,numberOfOutputs:1,outputChannelCount:[1]});
    s.worklet.onprocessorerror=()=>{if(valid())stop('Lỗi thu mic','Nhấn Bật mic để thử lại.');};
    s.worklet.port.onmessage=({data})=>{
      if(!valid())return;
      s.lastPacket=performance.now();
      if(!s.connected || s.ws?.readyState!==WebSocket.OPEN)return;
      if(s.context.currentTime*1000-data.stamp>200 || s.ws.bufferedAmount>16000 || s.sequence-s.ackSequence>=12) {
        retry(s,'Âm thanh bị chậm; đang bỏ hàng đợi cũ.');return;
      }
      s.ws.send(policy.frame(data.pcm,++s.sequence,data.stamp));
      let peak=0;for(const value of new Int16Array(data.pcm))peak=Math.max(peak,Math.abs(value));
      $('level').value=peak/32768*100;
    };
    settings();s.source.connect(s.worklet);s.worklet.connect(s.context.destination);
    s.context.onstatechange=()=>{if(valid() && s.context.state!=='running')stop('Mic bị gián đoạn','Quay lại Safari rồi nhấn Bật mic.');};
    for(const track of stream.getAudioTracks()) {
      track.onended=()=>{if(valid())stop('Mic đã bị ngắt');};
      track.onmute=()=>{if(valid())stop('Mic bị gián đoạn','Kết thúc cuộc gọi rồi nhấn Bật mic.');};
    }
    s.lastPacket=performance.now();
    s.watchdog=setInterval(()=>{
      if(!valid())return;
      const now=performance.now();
      if(now-s.lastPacket>2500)stop('Safari đã ngừng thu mic','Nhấn Bật mic để tiếp tục.');
      else if(s.connected && now-s.lastAck>1500)retry(s,'Laptop không xác nhận âm thanh.');
    },250);
    if(navigator.wakeLock)navigator.wakeLock.request('screen').then(w=>{if(valid())s.wake=w;else void w.release();}).catch(()=>{});
    $('mute').disabled=false;connect(s);
  } catch(error) {if(valid())stop('Chưa bật được mic',error.name==='NotAllowedError'?'Cho phép mic trong cài đặt Safari rồi thử lại.':error.message);}
}
$('start').onclick=()=>void start();
$('mute').onclick=()=>{if(!current)return;current.muted=!current.muted;settings();$('mute').textContent=current.muted?'Bật tiếng':'Tắt tiếng';if(current.connected)$('status').textContent=current.muted?'Đã tắt tiếng':'Mic đang bật';};
$('gain').oninput=()=>{$('gainValue').value=$('gain').value+'%';settings();};
document.addEventListener('visibilitychange',()=>{if(document.hidden && current)stop('Safari đang tạm dừng','Mở lại Safari rồi nhấn Bật mic. Dùng app iPhone native để thử chế độ khóa màn hình.');});
window.addEventListener('pagehide',()=>stop());
window.addEventListener('offline',()=>{if(current)retry(current,'Đã mất mạng.');});
window.addEventListener('online',()=>{if(current && !current.connected)connect(current);});
