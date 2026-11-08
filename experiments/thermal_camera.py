"""MLX90640 thermal viewer for the Pimoroni Pico Explorer Base."""

import gc
import math
import time

from machine import I2C, Pin
from picographics import PicoGraphics, DISPLAY_PICO_EXPLORER, PEN_RGB332
from pimoroni import Button
from mlx90640 import MLX90640, RefreshRate, init_float_array


def main():
    display = PicoGraphics(display=DISPLAY_PICO_EXPLORER, pen_type=PEN_RGB332)
    display.set_font("bitmap8")
    black = display.create_pen(0, 0, 0)
    white = display.create_pen(255, 255, 255)

    def message(text):
        display.set_pen(black)
        display.clear()
        display.set_pen(white)
        display.text(text, 8, 60, 224, 2)
        display.update()

    message("Connecting thermal camera...")
    i2c = I2C(0, sda=Pin(20), scl=Pin(21), freq=400_000)
    if 0x33 not in i2c.scan():
        message("No MLX90640 at 0x33. Check Breakout 2, then reset.")
        raise OSError("MLX90640 not detected on GP20/GP21")

    camera = MLX90640(i2c)
    camera.refresh_rate = RefreshRate.REFRESH_2_HZ
    print("MLX90640 detected at 0x33; serial:", camera.serial_number)
    frame = init_float_array(768)
    bad_pixels = camera.broken_pixels | camera.outlier_pixels

    # Blue -> cyan -> yellow -> red -> white, in 64 reusable pens.
    stops = ((0, 0, 100), (0, 180, 255), (255, 220, 0), (255, 40, 0), (255, 255, 255))
    palette = []
    for index in range(64):
        position = index * 4 / 63
        segment = min(3, int(position))
        fraction = position - segment
        rgb = [int(stops[segment][c] * (1 - fraction) + stops[segment + 1][c] * fraction)
               for c in range(3)]
        palette.append(display.create_pen(*rgb))

    pause_button = Button(12)
    scale_button = Button(13)
    paused = False
    automatic = True
    last_log = time.ticks_ms()
    frames = 0
    failures = 0
    gc.collect()

    while True:
        if pause_button.read():
            paused = not paused
        if scale_button.read():
            automatic = not automatic
        if not paused or frames == 0:
            try:
                camera.get_frame(frame)
                failures = 0
            except (OSError, RuntimeError, ValueError) as error:
                failures += 1
                print("Camera read error:", error)
                message("Camera read error. Retrying..." if failures < 5
                        else "Check camera connection. Retrying...")
                time.sleep_ms(250)
                continue

            # Replace factory-marked defective pixels using valid neighbours.
            for pixel in bad_pixels:
                x, y = pixel % 32, pixel // 32
                neighbours = [ny * 32 + nx for nx, ny in
                              ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
                              if 0 <= nx < 32 and 0 <= ny < 24
                              and ny * 32 + nx not in bad_pixels]
                frame[pixel] = sum(frame[p] for p in neighbours) / len(neighbours)
            if not all(math.isfinite(t) for t in frame):
                message("Invalid frame. Retrying...")
                continue
            frames += 1

        low, high = min(frame), max(frame)
        if automatic:
            midpoint = (low + high) / 2
            span = max(5.0, high - low)
            scale_low = midpoint - span / 2
        else:
            scale_low, span = 15.0, 25.0

        display.set_pen(black)
        display.clear()
        display.set_pen(white)
        display.text("MLX90640 " + ("PAUSED" if paused else "LIVE"), 8, 5, 224, 2)
        for y in range(24):
            for x in range(32):
                temperature = frame[y * 32 + x]
                colour = max(0, min(63, int((temperature - scale_low) * 63 / span)))
                display.set_pen(palette[colour])
                display.rectangle(8 + x * 7, 30 + y * 7, 7, 7)
        display.set_pen(white)
        display.text("{:.1f} - {:.1f} C".format(low, high), 8, 202, 224, 2)
        display.text("A:pause B:" + ("auto" if automatic else "15-40C"), 8, 224, 224, 1)
        display.update()

        now = time.ticks_ms()
        if time.ticks_diff(now, last_log) >= 10_000:
            print("Displayed frames:", frames, "range C:", low, high, "free:", gc.mem_free())
            last_log = now
        gc.collect()
        if paused:
            time.sleep_ms(50)


if __name__ == "__main__":
    main()
