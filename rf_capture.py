"""Bounded RF acquisition, optionally repeated with Pico Explorer feedback.

Display updates and USB transfers happen between capture windows only.
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
        gc.collect()
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


class CaptureDisplay:
    def __init__(self, pin):
        from picographics import PicoGraphics, DISPLAY_PICO_EXPLORER, PEN_RGB332
        self.display = PicoGraphics(display=DISPLAY_PICO_EXPLORER, pen_type=PEN_RGB332)
        self.display.set_font('bitmap8')
        self.black = self.display.create_pen(0, 0, 0)
        self.white = self.display.create_pen(255, 255, 255)
        self.green = self.display.create_pen(0, 220, 100)
        self.yellow = self.display.create_pen(255, 190, 0)
        self.pin = pin
        self.latest = None

    def show(self, capture_id, state, capture=None):
        if capture is not None:
            self.latest = (capture_id, capture.count, capture.overflow)
        display = self.display
        display.set_pen(self.black)
        display.clear()
        display.set_pen(self.white)
        display.text('RF RAW CAPTURE', 8, 8, 224, 2)
        display.text('GP{} / Mac USB log'.format(self.pin), 8, 35, 224, 1)
        display.set_pen(self.yellow if state != 'LISTENING' else self.green)
        display.text(state, 8, 56, 224, 2)
        display.set_pen(self.white)
        display.text('Window #{}'.format(capture_id), 8, 85, 224, 2)
        if self.latest is None:
            display.text('Waiting for first capture', 8, 125, 224, 1)
        else:
            number, edges, truncated = self.latest
            display.set_pen(self.yellow if truncated else self.green)
            display.text('TRUNCATED' if truncated else 'CAPTURED', 8, 119, 224, 2)
            display.text('#{}'.format(number), 8, 144, 224, 3)
            display.set_pen(self.white)
            display.text('{} edges'.format(edges), 8, 178, 224, 2)
        display.text('Note #, label on Mac later', 8, 210, 224, 1)
        display.text('USB logger must stay running', 8, 226, 224, 1)
        display.update()


def transmit(capture, pin, duration_ms, max_edges, capture_id):
    emit({'type': 'begin', 'schema': 1, 'capture_id': capture_id,
          'initial_level': capture.initial_level,
          'pin': pin, 'requested_duration_ms': duration_ms, 'max_edges': max_edges})
    for start in range(0, capture.count, 128):
        end = min(start + 128, capture.count)
        emit({'type': 'edges', 'offset': start,
              'durations_us': list(capture.durations[start:end]),
              'levels_after': list(capture.levels[start:end])})
    emit({'type': 'end', 'capture_id': capture_id, 'edge_count': capture.count,
          'elapsed_us': time.ticks_diff(capture.end_us, capture.start_us),
          'truncated': capture.overflow,
          'end_reason': 'edge_limit' if capture.overflow else 'duration',
          'trailing_us': None if capture.overflow else time.ticks_diff(
              capture.end_us, capture.last_us)})


def main(pin=0, duration_ms=3000, max_edges=8192, continuous=False,
         show_display=False, capture_limit=0):
    if not 1 <= duration_ms <= 30000:
        raise ValueError('duration_ms must be 1..30000')
    if not 1 <= max_edges <= 32768:
        raise ValueError('max_edges must be 1..32768')
    if not 0 <= pin <= 28:
        raise ValueError('pin must be 0..28')
    if capture_limit < 0:
        raise ValueError('capture_limit must be nonnegative')
    micropython.alloc_emergency_exception_buf(100)
    screen = CaptureDisplay(pin) if show_display else None
    capture = RawCapture(pin, max_edges)
    capture_id = 1
    try:
        while True:
            if screen:
                screen.show(capture_id, 'ARMING' if capture_id == 1 else 'LISTENING')
            emit({'type': 'ready', 'schema': 1, 'capture_id': capture_id,
                  'pin': pin, 'duration_ms': duration_ms, 'max_edges': max_edges,
                  'starts_in_ms': 1000 if capture_id == 1 else 0})
            if capture_id == 1:
                time.sleep_ms(1000)
                if screen:
                    screen.show(capture_id, 'LISTENING')
            capture.acquire(duration_ms)
            if screen:
                screen.show(capture_id, 'TRANSFERRING', capture)
            transmit(capture, pin, duration_ms, max_edges, capture_id)
            if not continuous or (capture_limit and capture_id >= capture_limit):
                break
            capture_id += 1
    finally:
        capture.pin.irq(handler=None)
        if screen:
            screen.show(capture_id, 'STOPPED')


if __name__ == '__main__':
    main()
