"""Live ruler, proximity indicator and distance history on Pico Explorer."""
import time
from machine import I2C, Pin
from picographics import PicoGraphics, DISPLAY_PICO_EXPLORER, PEN_RGB332
from pimoroni import Button
from vl53l1x import VL53L1X


def main():
    display = PicoGraphics(display=DISPLAY_PICO_EXPLORER, pen_type=PEN_RGB332)
    display.set_font('bitmap8')
    black = display.create_pen(0, 0, 0)
    white = display.create_pen(255, 255, 255)
    green = display.create_pen(0, 220, 100)
    blue = display.create_pen(30, 90, 230)
    grey = display.create_pen(50, 60, 70)
    yellow = display.create_pen(255, 200, 0)
    buttons = [Button(pin) for pin in (12, 13, 14, 15)]

    def message(text):
        display.set_pen(black)
        display.clear()
        display.set_pen(white)
        display.text(text, 8, 60, 224, 2)
        display.update()

    message('Connecting distance sensor...')
    i2c = I2C(0, sda=Pin(20), scl=Pin(21), freq=400000)
    if 0x29 not in i2c.scan():
        message('No VL53L1X at 0x29. Check Breakout 1 and reset.')
        raise OSError('VL53L1X missing on GP20/GP21')
    sensor = VL53L1X(i2c)
    print('VL53L1X confirmed at 0x29; model:', hex(sensor.read_model_id()))
    history = []
    held = False
    centimetres = True
    threshold_mm = 300
    value = None
    status = None
    last_log = time.ticks_ms()
    samples = 0
    errors = 0
    while True:
        if buttons[0].read():
            held = not held
        if buttons[1].read():
            centimetres = not centimetres
        if buttons[2].read():
            threshold_mm = max(50, threshold_mm - 50)
        if buttons[3].read():
            threshold_mm = min(2000, threshold_mm + 50)
        try:
            distance, raw_status = sensor.read_measurement()
            errors = 0
            # Raw status 9 is a fully valid range; reject other results.
            reading = distance if raw_status == 9 and 0 < distance <= 4000 else None
            if not held:
                value = reading
                status = raw_status
                history.append(reading)
                if len(history) > 56:
                    history.pop(0)
            samples += 1
        except OSError as error:
            errors += 1
            value = None
            status = None
            print('Distance read error:', error)
            if errors >= 3:
                message('Sensor not responding. Check connection and reset.')
                time.sleep_ms(200)
                continue

        near = value is not None and value < threshold_mm
        colour = green if near else blue
        display.set_pen(black)
        display.clear()
        display.set_pen(white)
        display.text('LASER RULER', 8, 6, 224, 2)
        if value is None:
            display.text('--', 8, 36, 170, 5)
        else:
            label = '{:.1f}'.format(value / 10) if centimetres else str(value)
            display.text(label, 8, 36, 170, 5)
        display.text('cm' if centimetres else 'mm', 184, 56, 48, 2)

        display.set_pen(grey if value is None or held else colour)
        display.rectangle(8, 90, 224, 25)
        display.set_pen(white)
        if held:
            label = 'HELD - A to resume'
        elif value is None:
            label = 'No valid target'
        else:
            label = ('NEAR' if near else 'FAR') + '  limit {} cm'.format(threshold_mm // 10)
        display.text(label, 12, 95, 216, 1)

        display.set_pen(grey)
        display.line(8, 124, 8, 183)
        display.line(8, 183, 232, 183)
        display.set_pen(yellow)
        previous = None
        for index, item in enumerate(history):
            if item is None:
                previous = None
                continue
            x = 10 + index * 4
            y = 182 - min(1000, max(0, item)) * 56 // 1000
            if previous is not None:
                display.line(previous[0], previous[1], x, y)
            else:
                display.rectangle(x, y, 2, 2)
            previous = (x, y)
        display.set_pen(white)
        display.text('History: 0-100 cm (clipped)', 8, 187, 224, 1)
        display.set_pen(grey)
        display.rectangle(8, 203, 224, 12)
        if value is not None:
            display.set_pen(colour)
            display.rectangle(8, 203, max(0, 1000 - value) * 224 // 1000, 12)
        display.set_pen(white)
        display.text('A:hold B:units X/Y:limit', 8, 226, 224, 1)
        display.update()
        now = time.ticks_ms()
        if time.ticks_diff(now, last_log) >= 5000:
            print('Distance display samples:', samples, 'mm:', value, 'status:', status,
                  'near:', near, 'held:', held)
            last_log = now
        time.sleep_ms(40)


if __name__ == '__main__':
    main()
