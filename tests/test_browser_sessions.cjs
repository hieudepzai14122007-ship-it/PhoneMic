const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function environment() {
  let clock=0,next=0;
  const timers=new Map(),sockets=[],tracks=[],worklets=[],elements={},events={};
  const later=(fn,delay,interval=0)=>{const id=++next;timers.set(id,{fn,due:clock+delay,interval});return id;};
  const document={hidden:false,getElementById:id=>elements[id] ||= {value:id==='gain'?100:0,textContent:'',classList:{add(){},remove(){}}},addEventListener:(name,fn)=>events[name]=fn};
  function newStream(){const track={stopped:false,stop(){this.stopped=true;}};tracks.push(track);return {getTracks:()=>[track],getAudioTracks:()=>[track]};}
  const navigator={mediaDevices:{getUserMedia:async()=>newStream()}};
  class Context {
    constructor(){this.state='running';this.sampleRate=48000;this.currentTime=0;this.audioWorklet={addModule:async()=>{}};}
    resume(){return Promise.resolve();}close(){this.state='closed';return Promise.resolve();}
    createMediaStreamSource(){return {connect(){}};}
  }
  class Worklet {constructor(){this.port={postMessage:x=>this.settings=x};worklets.push(this);}connect(){}}
  class Socket {
    static OPEN=1;
    constructor(){this.readyState=0;this.bufferedAmount=0;this.sent=[];sockets.push(this);}
    send(x){this.sent.push(x);}close(){this.readyState=3;}
    open(){this.readyState=1;this.onopen?.();}
    message(msg){this.onmessage?.({data:JSON.stringify(msg)});}
    fail(code){this.readyState=3;this.onclose?.({code});}
  }
  const context=vm.createContext({document,navigator,window:{addEventListener:(name,fn)=>events[name]=fn},
    location:{hash:'#'+'a'.repeat(32),host:'192.168.1.2:8765'},sessionStorage:{getItem:()=>null,setItem(){}},
    crypto:{randomUUID:()=> 'fixed-test-client-id-123'},isSecureContext:true,performance:{now:()=>clock},
    setTimeout:(fn,ms)=>later(fn,ms),clearTimeout:id=>timers.delete(id),setInterval:(fn,ms)=>later(fn,ms,ms),clearInterval:id=>timers.delete(id),
    AudioContext:Context,AudioWorkletNode:Worklet,WebSocket:Socket,console,ArrayBuffer,DataView,Uint8Array,Int16Array,
    Math:Object.assign(Object.create(Math),{random:()=>.5})});
  for(const file of ['session-policy.js','client.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../web',file),'utf8'),context);
  const flush=()=>new Promise(resolve=>setImmediate(resolve));
  async function advance(ms){const until=clock+ms;while(true){const due=[...timers].filter(([id,t])=>t.due<=until).sort((a,b)=>a[1].due-b[1].due)[0];if(!due)break;const [id,t]=due;clock=t.due;if(t.interval)t.due+=t.interval;else timers.delete(id);t.fn();await flush();}clock=until;await flush();}
  return {elements,events,document,navigator,sockets,tracks,worklets,newStream,flush,advance,context};
}
(async()=>{
  // Disconnect -> automatic reconnect -> keep mute -> Stop cancels scheduled retries.
  let e=environment();e.elements.start.onclick();await e.flush();assert.equal(e.sockets.length,1);
  e.sockets[0].open();e.sockets[0].message({type:'ready'});e.elements.mute.onclick();
  assert.equal(e.worklets[0].settings.muted,true);
  const oldClose=e.sockets[0].onclose;e.sockets[0].fail(1006);await e.advance(500);
  assert.equal(e.sockets.length,2);e.sockets[1].open();e.sockets[1].message({type:'ready'});
  assert.equal(e.elements.status.textContent,'Đã tắt tiếng');
  oldClose({code:4000});assert.equal(e.sockets[1].readyState,1,'stale callbacks must not kill new session');
  e.sockets[1].fail(1006);e.elements.start.onclick();await e.advance(10000);
  assert.equal(e.sockets.length,2);assert(e.tracks.every(t=>t.stopped),'Stop releases mic and cancels retry');
  // Stop while permission is pending: late permission must not start capture or connect.
  e=environment();let permission;e.navigator.mediaDevices.getUserMedia=()=>new Promise(r=>permission=r);
  e.elements.start.onclick();e.elements.start.onclick();permission(e.newStream());await e.flush();
  assert.equal(e.sockets.length,0);assert(e.tracks.every(t=>t.stopped));
  // Background/foreground never restarts Safari capture without another tap.
  e=environment();e.elements.start.onclick();await e.flush();e.sockets[0].open();e.sockets[0].message({type:'ready'});
  e.document.hidden=true;e.events.visibilitychange();e.document.hidden=false;e.events.visibilitychange();e.events.online();await e.advance(10000);
  assert.equal(e.sockets.length,1);assert(e.tracks.every(t=>t.stopped));
  // An explicit receiver Stop is terminal.
  e=environment();e.elements.start.onclick();await e.flush();e.sockets[0].open();e.sockets[0].message({type:'ready'});
  e.sockets[0].fail(4000);await e.advance(10000);assert.equal(e.sockets.length,1);assert(e.tracks[0].stopped);
  // Acknowledgements missing while capture continues force a fresh connection, not an expanding queue.
  e=environment();e.elements.start.onclick();await e.flush();e.sockets[0].open();e.sockets[0].message({type:'ready'});
  for(let i=0;i<13;i++)e.worklets[0].port.onmessage({data:{pcm:new ArrayBuffer(1920),stamp:0}});
  assert.equal(e.sockets[0].readyState,3);await e.advance(500);assert.equal(e.sockets.length,2);
  // Retry budget is finite even if connections flap before 10 seconds of stable acknowledgements.
  const {RetryBudget,frame}=require('../web/session-policy.js');let now=0;const b=new RetryBudget(()=>now,()=>.5);
  assert.equal(b.next(),500);now=120000;assert.equal(b.next(),null);b.reset();assert.equal(b.next(),500);
  assert.equal(Buffer.from(frame(Uint8Array.from([0,128,255,127]).buffer,1,1000)).toString('hex'),'504d3032010000000000000000408f400080ff7f');
  console.log('PASS: Safari reconnect, mute preservation, stale callback isolation, Stop cancellation, late permission, background pause, receiver Stop, ACK backpressure, retry deadline, wire parity');
})().catch(e=>{console.error(e);process.exit(1);});
