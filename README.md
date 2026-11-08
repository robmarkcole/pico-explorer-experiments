# Pico Explorer experiments

Live MLX90640 thermal imaging on a Raspberry Pi Pico (RP2040) with a
Pimoroni Pico Explorer Base. Plug the MLX90640 into **Breakout 2**.
Both breakout sockets share I²C0: SDA **GP20**, SCL **GP21**. The camera
responds at **0x33**.

## Run on the board

Use Pimoroni's **Pico** MicroPython firmware, tested with
[v1.29.0-2](https://github.com/pimoroni/pimoroni-pico/releases/tag/v1.29.0-2).
Hold BOOTSEL while connecting USB and copy the `pico-…-pimoroni-micropython.uf2`
file to the `RPI-RP2` drive. This replaces the installed firmware.

Install [mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html),
then copy the application and driver (back up an existing `main.py` first):

```sh
mpremote fs cp :main.py original-main.py
mpremote fs mkdir :lib
mpremote fs cp lib/mlx90640.py :lib/mlx90640.py
mpremote fs cp main.py :main.py
mpremote reset
```

Skip `mkdir` if `lib` already exists. With several connected boards, add
`connect /dev/cu.usbmodem…` before each command to select the Pico.
The viewer starts automatically at power-on; no computer is needed afterward.

## Display and controls

The 32×24 thermal image is enlarged to 224×168 pixels. Colours run from blue
(cold) through yellow/red to white (hot). The displayed minimum and maximum
are in Celsius. The camera is set to 2 Hz; actual complete-frame display speed
is lower because temperature conversion runs in MicroPython.

- **A:** pause/resume the image.
- **B:** switch between automatic colour scaling and a fixed 15–40 °C scale.

The automatic scale spans at least 5 °C. Calibration assumes 0.95 emissivity;
readings depend on the surface and reflected heat. Camera errors appear on the
screen and are retried. A missing camera at startup requires checking the
connection and resetting the board.

## Driver and licences

`lib/mlx90640.py` derives from the MIT-licensed
[michael-sulyak driver](https://github.com/michael-sulyak/micropython-mlx90640/tree/4ff15dd1da2379039216c5d10c79f80cb22df603),
itself based on Adafruit's MLX90640 driver. Notices are retained in `licenses/`.
Local adaptations remove the unavailable `typing` dependency, fix partial
I²C reads and set iteration, acquire both sensor subpages for a complete frame,
and add timeouts. Factory-marked defective pixels are filled from neighbouring
pixels by the viewer.

Pimoroni documents the Explorer display and pin assignments
[here](https://github.com/pimoroni/pimoroni-pico/blob/main/micropython/modules/pico_explorer/README.md).
