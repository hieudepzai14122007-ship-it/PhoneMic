"""Version 2 live frames. Reject replay, malformed data and accumulated delay."""
import math
import struct

HEADER = struct.Struct('<4sId')


class FrameWindow:
    def __init__(self):
        self.sequence = 0
        self.stamp = -1.0
        self.best_offset = None

    def accept(self, frame, now):
        if not HEADER.size < len(frame) <= HEADER.size + 4096 or (len(frame)-HEADER.size) % 2:
            raise ValueError('Invalid PCM frame length')
        magic, sequence, stamp = HEADER.unpack_from(frame)
        if magic != b'PM02' or sequence <= self.sequence or not math.isfinite(stamp) or stamp < 0 or stamp < self.stamp:
            raise ValueError('Invalid or replayed PCM frame')
        offset = now * 1000 - stamp
        self.best_offset = offset if self.best_offset is None else min(self.best_offset, offset)
        self.sequence, self.stamp = sequence, stamp
        if offset - self.best_offset > 200:
            raise TimeoutError('Audio delivery is delayed')
        return frame[HEADER.size:]
