# Planned RF receiver experiment

Proposed connections for an MX-RM-5V receiver and the existing Pico Explorer
Base. This RF circuit has not yet been assembled or tested.

![MX-RM-5V receiver wiring and Explorer mini breadboard contacts](../assets/rf-receiver-wiring.svg)

## Connections

Disconnect USB before wiring. Looking at the receiver's labelled rear side
with its pins pointing down, the earlier photograph shows **GND, DATA, DATA,
VCC** from left to right. Use either DATA pin and leave the other unconnected.
Follow the actual board labels when connecting power.

| From | To |
| --- | --- |
| Receiver VCC | USB 5 V / Pico VBUS, physical pin 40 |
| Receiver GND | Explorer GND |
| Receiver DATA | SN74LVC1G17 buffer breakout input A |
| Buffer VCC | Explorer 3V3 |
| Buffer GND | Explorer GND |
| Buffer output Y | Explorer GP0 |
| 100 nF capacitor | Between buffer VCC and GND, close to the buffer |

Use a buffer breakout with accessible labelled connections; the diagram uses
signal names, not package pin numbers. The buffer is an additional part required
for this proposed circuit. Its input tolerates 5 V while its output follows
its 3.3 V supply. Do not connect receiver DATA directly to Pico GPIO. Receiver
output levels vary, so check the signal before substituting a resistor divider.

VBUS is available while the Pico is USB-powered. It is **not** the Explorer
3V3 socket. If physical pin 40 is inaccessible with the Pico fitted, arrange
an accessible USB 5 V connection rather than forcing a jumper onto a solder
joint. All circuit grounds must connect together. The Melexis camera can
remain attached: its GP20/GP21 I²C bus is separate from GP0.

## Which way are the breadboard contacts connected?

With **USB to the left, the Pico at the top, and the screen to the right**, as
in the project photos, the mini breadboard's connections run **up and down in
groups of five holes**. Each column has a separate upper group and lower group.

- The five holes in one vertical group connect together.
- Adjacent columns do not connect left to right.
- The horizontal centre gap separates the upper and lower groups.
- This mini breadboard has **no dedicated power rails** and no automatic
  connection to the Explorer's power sockets; add jumper wires as needed.

Place the receiver's four pins left to right in four separate columns, so they
do not short together. With power disconnected, confirm the layout using a
multimeter's continuity mode before wiring the circuit. The diagram shows
electrical connections rather than an exact component placement.

## References

- [Explorer Base](https://shop.pimoroni.com/products/pico-explorer-base?variant=32369514315859)
- [Explorer pin assignments](https://github.com/pimoroni/pimoroni-pico/blob/main/micropython/modules/pico_explorer/README.md)
- [Pico power and pinout](https://datasheets.raspberrypi.com/pico/pico-datasheet.pdf)
- [SN74LVC1G17 datasheet](https://www.ti.com/lit/ds/symlink/sn74lvc1g17.pdf)
- [Mini breadboard contact groups](https://www.microtivity.com/catalog/breadboards/breadboard-170)
- [Original Hackster doorbell project](https://www.hackster.io/robin-cole/pi-camera-doorbell-with-notifications-408d3d)
