/* Pure timing/wire helpers shared by Safari and its tests. */
(function(root) {
  class RetryBudget {
    constructor(now = () => performance.now(), random = Math.random) {
      this.now = now; this.random = random; this.reset();
    }
    reset() {this.deadline = null; this.attempt = 0;}
    next() {
      const now = this.now();
      if (this.deadline === null) this.deadline = now + 120000;
      if (now >= this.deadline) return null;
      const delay = Math.min(8000, 500 * 2 ** Math.min(this.attempt++, 4));
      return Math.min(this.deadline-now, Math.round(delay * (.85 + .3*this.random())));
    }
  }
  function frame(pcm, sequence, stamp) {
    const packet = new ArrayBuffer(16 + pcm.byteLength), view = new DataView(packet);
    new Uint8Array(packet).set([80,77,48,50]);
    view.setUint32(4, sequence, true); view.setFloat64(8, stamp, true);
    new Uint8Array(packet,16).set(new Uint8Array(pcm));return packet;
  }
  const api = {RetryBudget, frame, terminal: code => [1008,4000,4001,4003].includes(code)};
  root.PhoneMicPolicy = api;
  if(typeof module !== 'undefined') module.exports=api;
})(globalThis);
