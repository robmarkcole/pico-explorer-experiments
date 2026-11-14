"""Bounded, unfiltered RF acquisition for MicroPython on the RP2040.

No display updates or USB output occur while the edge IRQ is attached.
The Mac logger executes this module temporarily; main.py is unaffected.
"""
from array import array
import gc
import json
import micropython
import time
from machine import Pin

PREFIX = 'RFRAW '


def emit(record):
    print(PREFIX + json.dumps(record))


class RawCapture:
    def __init__(self, pin, max_edges):
        self.durations = array('I', [0] * max_edges)
        self.levels = bytearray(max_edges)
        self.capacity = max_edges
        self.count = 0
        self.overflow = False
        self.pin = Pin(pin, Pin.IN)

    def edge(self, pin):
        now = time.ticks_us()
        index = self.count
        if index >= self.capacity:
            self.overflow = True
            return
        self.durations[index] = time.ticks_diff(now, self.last_us)
        # Level sampled just AFTER this edge. Interval preceding it starts at
        # initial_level (first interval), or levels[index - 1] thereafter.
        self.levels[index] = pin.value()
        self.last_us = now
        self.count = index + 1

    def acquire(self, duration_ms):
        self.count = 0
        self.overflow = False
        gc.collect()
        self.initial_level = self.pin.value()
        self.start_us = self.last_us = time.ticks_us()
        try:
            self.pin.irq(handler=self.edge,
                         trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, hard=True)
            while not self.overflow:
                if time.ticks_diff(time.ticks_us(), self.start_us) >= duration_ms * 1000:
                    break
                time.sleep_ms(1)
        finally:
            self.pin.irq(handler=None)
            self.end_us = time.ticks_us()


def main(pin=0, duration_ms=3000, max_edges=16384):
    if not 1 <= duration_ms <= 30000:
        raise ValueError('duration_ms must be 1..30000')
    if not 1 <= max_edges <= 32768:
        raise ValueError('max_edges must be 1..32768')
    if not 0 <= pin <= 28:
        raise ValueError('pin must be 0..28')
    micropython.alloc_emergency_exception_buf(100)
    capture = RawCapture(pin, max_edges)
    emit({'type': 'ready', 'schema': 1, 'pin': pin,
          'duration_ms': duration_ms, 'max_edges': max_edges, 'starts_in_ms': 1000})
    time.sleep_ms(1000)
    capture.acquire(duration_ms)
    emit({'type': 'begin', 'schema': 1, 'initial_level': capture.initial_level,
          'pin': pin, 'requested_duration_ms': duration_ms, 'max_edges': max_edges})
    for start in range(0, capture.count, 128):
        end = min(start + 128, capture.count)
        emit({'type': 'edges', 'offset': start,
              'durations_us': list(capture.durations[start:end]),
              'levels_after': list(capture.levels[start:end])})
    emit({'type': 'end', 'edge_count': capture.count,
          'elapsed_us': time.ticks_diff(capture.end_us, capture.start_us),
          'truncated': capture.overflow,
          'end_reason': 'edge_limit' if capture.overflow else 'duration',
          'trailing_us': None if capture.overflow else time.ticks_diff(
              capture.end_us, capture.last_us)})


if __name__ == '__main__':
    main()
