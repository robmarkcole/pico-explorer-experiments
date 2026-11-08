"""Pico Explorer RF input activity and repeated-burst display."""
from array import array
import gc
import micropython
import time
from machine import Pin
from picographics import PicoGraphics, DISPLAY_PICO_EXPLORER, PEN_RGB332
from pimoroni import Button
from rf_detector import RepeatedFrameDetector

class PulseCapture:
    SIZE = 2048
    MASK = SIZE - 1

    def __init__(self):
        self.values = array('I', [0] * self.SIZE)
        self.write = 0
        self.read = 0
        self.dropped = 0
        self.last_us = time.ticks_us()
        self.pin = Pin(0, Pin.IN)
        self.pin.irq(handler=self.edge, trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING,
                     hard=True)

    def edge(self, pin):
        now = time.ticks_us()
        duration = time.ticks_diff(now, self.last_us)
        self.last_us = now
        next_write = (self.write + 1) & self.MASK
        if next_write == self.read:
            self.dropped = (self.dropped + 1) & 0xFFFF
        else:
            self.values[self.write] = max(0, duration)
            self.write = next_write

    def stop(self):
        self.pin.irq(handler=None)


def main():
    micropython.alloc_emergency_exception_buf(100)
    display = PicoGraphics(display=DISPLAY_PICO_EXPLORER, pen_type=PEN_RGB332)
    display.set_font('bitmap8')
    black = display.create_pen(0, 0, 0)
    white = display.create_pen(255, 255, 255)
    green = display.create_pen(0, 220, 100)
    yellow = display.create_pen(255, 200, 0)
    blue = display.create_pen(20, 50, 120)
    reset_button = Button(12)
    detector = RepeatedFrameDetector()
    capture = PulseCapture()
    elapsed = 0
    previous_tick = time.ticks_ms()
    previous_draw = -1000
    previous_log = 0
    previous_rate = 0
    last_event = -10000
    total_edges = rate_edges = edge_rate = events = dropped = 0
    print('RF display: GP0 input; receiver on 3V3; no piezo output.')
    print('Press a fan remote button nearby. A clears counts.')
    try:
        while True:
            tick = time.ticks_ms()
            elapsed += time.ticks_diff(tick, previous_tick)
            previous_tick = tick
            if capture.dropped != dropped:
                dropped = capture.dropped
                detector.discard()
                capture.read = capture.write
            while capture.read != capture.write:
                duration = capture.values[capture.read]
                capture.read = (capture.read + 1) & capture.MASK
                total_edges += 1
                rate_edges += 1
                if detector.feed(duration, elapsed):
                    events += 1
                    last_event = elapsed
                    print('REPEATED BURST', events, 'intervals:', len(detector.latest),
                          'widths us:', detector.latest)
            if elapsed - previous_rate >= 1000:
                edge_rate = int(rate_edges * 1000 / (elapsed - previous_rate))
                rate_edges = 0
                previous_rate = elapsed
            if reset_button.read():
                events = total_edges = 0
                detector = RepeatedFrameDetector()
                last_event = -10000
            if elapsed - previous_draw >= 250:
                previous_draw = elapsed
                display.set_pen(black)
                display.clear()
                display.set_pen(white)
                display.text('433 MHz RF', 8, 8, 224, 3)
                display.text('GP0 / receiver 3V3', 8, 39, 224, 1)
                flash = elapsed - last_event < 1800
                display.set_pen(green if flash else blue)
                display.rectangle(4, 59, 232, 49)
                display.set_pen(black if flash else white)
                display.text('REPEATED RF' if flash else 'LISTENING', 10, 75, 220, 2)
                display.set_pen(white)
                display.text('Bursts: {}'.format(events), 8, 119, 224, 2)
                display.text('Edges/s: {}'.format(edge_rate), 8, 145, 224, 2)
                display.set_pen(yellow if edge_rate else white)
                display.text('Input activity / noise' if edge_rate else 'No input edges',
                             8, 172, 224, 1)
                display.set_pen(white)
                display.text('Frames: {}  drops: {}'.format(detector.candidates, dropped),
                             8, 191, 224, 1)
                display.text('Press fan remote nearby', 8, 210, 224, 1)
                display.text('A: clear counts', 8, 226, 224, 1)
                display.update()
            if elapsed - previous_log >= 5000:
                previous_log = elapsed
                print('RF status edges/s:', edge_rate, 'total:', total_edges,
                      'frames:', detector.candidates, 'events:', events, 'drops:', dropped)
                if detector.latest:
                    print('Latest candidate widths us:', detector.latest)
                if total_edges:
                    end = capture.write
                    recent = [capture.values[(end - i - 1) & capture.MASK]
                              for i in range(min(24, total_edges))]
                    print('Recent raw widths us (newest first):', recent)
                gc.collect()
            time.sleep_ms(2)
    finally:
        capture.stop()

if __name__ == '__main__':
    main()
