const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
let Recorder;
const sent = [];
class Base { constructor() {this.port={postMessage: message=>sent.push(message.pcm.slice(0))};} }
vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../web/pcm-worklet.js'),'utf8'),{
  AudioWorkletProcessor:Base, registerProcessor:(name,cls)=>Recorder=cls,
  ArrayBuffer, DataView, Math, currentTime:1
});
const recorder=new Recorder();
const output=[new Float32Array(128).fill(1)];
for(let i=0;i<15;i++) recorder.process([[new Float32Array(128).fill(.5)]],[output]);
assert.equal(sent.length,2);
assert.equal(new DataView(sent[0]).getInt16(0,true),16384);
assert(output[0].every(x=>x===0),'must never play microphone on phone speaker');
sent.length=0;
recorder.port.onmessage({data:{gain:2,muted:true}});
for(let i=0;i<15;i++) recorder.process([[new Float32Array(128).fill(.8)]],[output]);
assert(new Int16Array(sent[0]).every(x=>x===0),'mute must send silence');
sent.length=0;
recorder.port.onmessage({data:{gain:2,muted:false}});
for(let i=0;i<15;i++) recorder.process([[new Float32Array(128).fill(-.8)]],[output]);
assert.equal(new DataView(sent[0]).getInt16(0,true),-32767);
console.log('PASS: PCM framing, little-endian, mute, gain/clipping, silent phone output');
