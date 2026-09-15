class PCMRecorder extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new ArrayBuffer(1920); // 960 mono samples, about 20 ms at 48 kHz.
    this.view = new DataView(this.buffer);
    this.offset = 0;
    this.gain = 1;
    this.muted = false;
    this.port.onmessage = ({data}) => {
      this.gain = data.gain;
      this.muted = data.muted;
    };
  }
  process(inputs, outputs) {
    for (const channel of outputs[0] || []) channel.fill(0); // Never monitor on iPhone speaker.
    const input = inputs[0]?.[0];
    if (!input) return true;
    for (let i = 0; i < input.length; i++) {
      const value = this.muted ? 0 : Math.max(-1, Math.min(1, input[i] * this.gain));
      this.view.setInt16(this.offset * 2, Math.round(value * 32767), true);
      if (++this.offset === 960) {
        this.port.postMessage({pcm:this.buffer,stamp:currentTime*1000}, [this.buffer]);
        this.buffer = new ArrayBuffer(1920);
        this.view = new DataView(this.buffer);
        this.offset = 0;
      }
    }
    return true;
  }
}
registerProcessor('pcm-recorder', PCMRecorder);
