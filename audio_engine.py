"""Bounded live PCM queue; no recording and no global audio device changes."""
import threading
import time
import numpy as np


class Resampler:
    """Streaming linear interpolation for 44.1/48 kHz speech."""
    def __init__(self, source_rate, target_rate):
        self.step = source_rate / target_rate
        self.position = 0.0
        self.tail = np.empty(0, dtype=np.float32)

    def process(self, samples):
        if self.step == 1:
            return samples
        data = np.concatenate((self.tail, samples))
        if len(data) < 2:
            self.tail = data
            return np.empty(0, dtype=np.float32)
        positions = np.arange(self.position, len(data) - 1, self.step)
        result = np.interp(positions, np.arange(len(data)), data).astype(np.float32)
        self.position += len(positions) * self.step - (len(data) - 1)
        self.tail = data[-1:].copy()
        return result


class LiveBuffer:
    def __init__(self, rate=48000):
        self.rate = rate
        self.capacity = int(rate * .25)
        self.prefill = int(rate * .06)
        self.data = np.zeros(self.capacity, dtype=np.float32)
        self.lock = threading.Lock()
        self.read = self.write = self.count = 0
        self.primed = False
        self.overflows = 0
        self.last_push = 0.0

    def clear(self):
        with self.lock:
            self.read = self.write = self.count = 0
            self.primed = False

    def push(self, samples):
        with self.lock:
            now = time.monotonic()
            if self.count and now - self.last_push > .3:
                self.read = self.write = self.count = 0
                self.primed = False
            self.last_push = now
            n = len(samples)
            if self.count + n > self.capacity:
                # Drop delayed speech rather than accumulate seconds of latency.
                samples = samples[-self.prefill:]
                n = len(samples)
                self.read = self.write = self.count = 0
                self.primed = False
                self.overflows += 1
            first = min(n, self.capacity - self.write)
            self.data[self.write:self.write + first] = samples[:first]
            self.data[:n - first] = samples[first:]
            self.write = (self.write + n) % self.capacity
            self.count += n

    def fill(self, out):
        out.fill(0)
        # Audio callback must never wait on a network thread.
        if not self.lock.acquire(blocking=False):
            return
        try:
            # After laptop sleep / stalled network, never play a pre-sleep queue.
            if self.count and time.monotonic() - self.last_push > .3:
                self.read = self.write = self.count = 0
                self.primed = False
                return
            if not self.primed:
                if self.count < self.prefill:
                    return
                self.primed = True
            n = min(len(out), self.count)
            first = min(n, self.capacity - self.read)
            for channel in range(out.shape[1]):
                out[:first, channel] = self.data[self.read:self.read + first]
                out[first:n, channel] = self.data[:n - first]
            self.read = (self.read + n) % self.capacity
            self.count -= n
            if n < len(out):
                self.primed = False
        finally:
            self.lock.release()


class AudioSink:
    def __init__(self, device):
        import sounddevice as sd
        self.sd = sd
        channels = min(2, int(sd.query_devices(device)['max_output_channels']))
        for rate in (48000, 44100):
            try:
                sd.check_output_settings(device=device, samplerate=rate,
                                         channels=channels, dtype='float32')
                break
            except sd.PortAudioError:
                if rate == 44100:
                    raise
        self.rate = rate
        self.buffer = LiveBuffer(rate)
        self.last_callback = time.monotonic()
        self.stream = sd.OutputStream(device=device, samplerate=rate,
            channels=channels, dtype='float32', blocksize=0, latency='low',
            callback=self.callback)
        self.resampler = None
        self.peak = 0.0

    def start(self):
        self.last_callback = time.monotonic()
        self.stream.start()

    def callback(self, out, frames, timing, status):
        self.last_callback = time.monotonic()
        self.buffer.fill(out)

    @property
    def healthy(self):
        return self.stream.active and time.monotonic() - self.last_callback < 2

    def begin(self, rate):
        self.clear()
        self.resampler = Resampler(rate, self.rate)

    def feed(self, packet):
        samples = np.frombuffer(packet, dtype='<i2').astype(np.float32) / 32768
        self.peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
        self.buffer.push(self.resampler.process(samples))

    def clear(self):
        self.buffer.clear()
        self.peak = 0.0

    def close(self):
        self.stream.abort()
        self.stream.close()
        self.clear()
