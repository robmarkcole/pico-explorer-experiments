# Capture fan remote pulses on a Mac

This mode records a bounded window of **unfiltered GP0 edges** on the Pico,
then sends each recording over USB after its capture window stops. It does not assume a
frame gap, pulse width, repeated frame count, protocol or button code.

## Recorded results

The [18 November 2026 session report](fan-remote-capture-2026-11-18.md) documents
OFF and speeds 1–6: 27 complete 250 ms windows from 21 reported presses, with no
overflow. It includes the handset photograph, button map and remaining frequency,
electrical-interface and decoding uncertainties. These are raw labelled samples,
not verified command codes. Capture and logging are stopped.

## Wiring and setup

Confirm the actual DollaTek model, frequency, pinout, receiver supply and DATA
logic voltage. The older [wiring guide](rf-receiver-wiring.md) describes an
MX-RM-5V and is not a verified DollaTek pinout. DATA must be safe for a 3.3 V
GPIO; the default input is GP0 with no pull resistor. Connect grounds together.
Record the real supply voltage in `--supply`; this is metadata, not a setting
that changes board power. Record level shifting, antenna, remote model and
receiver distance in `--notes`.

From the repository root, install the Mac dependency:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-rf.txt
mpremote connect list
```

Use the MicroPython board's explicit port. Other attached USB devices may be
ESP32 boards. Close Thonny or other serial monitors before capturing.

The logger soft-resets the interpreter and executes the local `rf_capture.py`
in RAM through `mpremote`. This interrupts the running app, but does not copy
files or change `main.py` on the device. It leaves the board at the REPL after
capture; use `mpremote connect PORT reset` or unplug/reconnect to resume startup.
Existing Pimoroni MicroPython firmware is sufficient; no firmware flash is needed.
See [mpremote's documentation](https://docs.micropython.org/en/latest/reference/mpremote.html).

## Run continuously with the Pico display

After setup, start the logger and leave it running:

```sh
python scripts/log_rf.py --port /dev/cu.usbmodem1401 --continuous
```

After one-second **ARMING**, the Pico shows **LISTENING** and the next capture
number. It examines three-second raw windows, but saves and increments the number
only when a window contains a plausible RF burst. Idle windows, including empty
ones, do not create capture files or change the counter. The last **CAPTURED #N**
remains visible while listening; **TRANSFERRING** indicates a USB transfer and
**TRUNCATED** indicates overflow on a qualifying capture. Press remote buttons
while listening and note the capture number after the press.

The initial gate requires at least 20 consecutive alternating edge intervals
between 60 and 4,000 microseconds, spanning at least 6 ms. This rejects the sparse
5–15 ms idle transitions observed on the bench. It does not identify the fan:
noise or another transmitter can qualify, and a different fan pulse structure
might need different settings. `--burst-min-pulses` and `--burst-max-us` tune the
gate. A qualifying window keeps all raw intervals, including surrounding noise;
no pulse filtering or protocol decoding is applied to the saved data.

Use `--all-windows` with `--continuous` to restore saving every window for raw
diagnostics. Single captures remain ungated. A press can cross a window boundary
or fall in a transfer gap; retry if it does not register.

The Mac saves each qualifying window immediately to a separate `…-capture-000001.json`
file, with `session_id` and `capture_id` matching the screen. IDs restart at 1
for each session; filenames have a unique session prefix. No button label is
required: the default is `unlabelled` and press kind is `unknown`. Afterward, map `(session_id, capture_id)`
to the button pressed in your notes or the JSON `metadata.button` field. Captures
are saved under `captures/ceiling-fan/local/`. The `--supply` default is
`unverified`; supply the real value and hardware notes when known.

Display updates, garbage collection and USB transfers happen **between** windows.
There is a short unrecorded gap: this is continuous operation with repeated
bounded windows, not gapless sampling. The screen confirms acquisition on the
Pico; the terminal's **Saved #N** confirms writing the file on the Mac. The Mac
logger must remain connected; the Pico does not store recordings in flash.

Use `--duration-ms 1000` for shorter windows, or `--count 3` to stop after three
saved captures (idle windows do not count). `--display` adds the same screen feedback to a single capture.
A normal finite run ends with **STOPPED** on the Pico. To end an indefinite
session, press Ctrl-C in the Mac terminal, then reset the Pico to resume its
startup app:

```sh
mpremote connect /dev/cu.usbmodem1401 reset
```

Stopping the host alone does not guarantee the device stops; do not treat later
screen numbers as saved recordings after disconnecting the logger. Completed
files are retained if a subsequent window or USB connection fails. The active
window is marked incomplete where possible.

## Collect individually labelled recordings

First record an idle baseline (replace the example port and supply with yours):

```sh
python scripts/log_rf.py --port /dev/cu.usbmodem1401 \
  --button idle --kind idle --supply 3.3V \
  --notes 'DollaTek model: TODO; DATA to GP0; antenna: TODO'
```

Then capture one button press:

```sh
python scripts/log_rf.py --port /dev/cu.usbmodem1401 \
  --button speed-1 --press 1 --kind short --supply 3.3V \
  --notes 'Remote: Faro Pemba, exact model TODO; distance 0.5 m'
```

Wait for **READY**. Capture starts one second later and runs for three seconds
by default. Press the remote during that window. Without `--display`, a single capture does not update the Pico screen. Repeat at least five times per button, changing `--press`, and
include held presses with `--kind held`. A label does not automatically trigger
or detect a button press.

Options:

- `--duration-ms 3000`: capture window, 1–30000 ms. Actual duration is reported.
- `--max-edges 8192`: preallocated edge capacity, 1–32768. The default uses
  about 40 KiB for pulse/level storage, excluding interpreter overhead.
- `--pin 0`: input GPIO, 0–28. Choose an exposed, unused pin suitable for your
  board; several GPIOs belong to the Explorer display or attached peripherals.
- `--output-dir PATH`: override the default `captures/ceiling-fan/local/`.
- `--receiver TEXT`, `--notes TEXT`: hardware and experiment details.

Each invocation writes a uniquely named JSON recording and `.serial.txt`
transcript. The default local recordings directory is gitignored. Review and
explicitly select recordings before publishing RF addresses or other identifiers.

If the buffer fills and a further edge arrives, acquisition stops early and the
recording is marked `truncated: true`, `complete: false`, with exit status 1.
The stored prefix is retained. No exact count of later lost edges is claimed.
Try a shorter window, a larger buffer if memory allows, or investigate noise.
No pulses are discarded as a noise filter. A recording with zero edges is a
valid baseline, but does not establish that the receiver works.

Connection failures, corrupt chunks, device exceptions, Ctrl-C and missing end
records are saved as incomplete recordings with the transcript where possible.
The host kills a stalled transport after the requested duration plus 30 seconds,
resetting that timeout for each new continuous window.
After interruption the Pico may finish its bounded capture independently; reset
it before retrying. A filesystem failure can prevent saving output.

## Recording format and limits

The JSON `schema` is `pico-rf-capture-v1` and contains:

- `metadata`: label, press number, press kind, port, pin, supply, receiver,
  notes and requested capture settings; `recorded_at_utc` is the host launch time.
- `begin.initial_level`: sampled GPIO level at the start of the window.
- `durations_us[i]`: time from capture start (first edge), or the preceding
  edge (later edges), to edge `i`.
- `levels_after[i]`: GPIO level sampled just after edge `i`. The preceding
  interval's level is `initial_level` for `i=0`, otherwise `levels_after[i-1]`.
- `end.trailing_us`: final interval from the last stored edge (or window start
  with no edges) to capture stop; null when truncation makes it unknown.
- `end.elapsed_us`, `end.edge_count`, `end.end_reason`, `end.truncated`.
- `complete`: all chunks arrived, timings/counts validate, transport succeeded
  and the buffer did not overflow. It does **not** certify RF timing accuracy.

The USB wire format is newline-delimited JSON prefixed with `RFRAW `, containing
`ready`, `begin`, numbered `edges` chunks and `end` records. Chunks are transmitted
only after the GPIO IRQ is detached. Continuous mode repeats the record sequence with a
new `capture_id` in `ready`, `begin` and `end`. Rejected windows emit an `idle`
heartbeat and reuse the same next ID; the host does not save these as captures. Start/stop sampling has a small software
boundary uncertainty. The first and trailing intervals can be partial pulses.
Keep these boundaries when analysing recordings rather than treating them as
complete protocol symbols. Levels are electrical levels; polarity is not assumed.

Python hard IRQs timestamp observed transitions. Very fast transitions can be
missed or delayed without overflowing the array; adjacent identical sampled
levels are a useful warning, but alternating levels do not prove lossless capture.
Compare repeat timings and use a logic analyser or PIO acquisition if accuracy is
insufficient. No fan protocol or checksum is inferred by this mode.

For a standalone default capture without the labelled Mac wrapper, run:

```sh
mpremote connect /dev/cu.usbmodem1401 soft-reset run rf_capture.py
```

Run host and simulated acquisition tests with:

```sh
python -m unittest discover -s tests -v
```

## Bring-up validation

On 14 November 2026, the connected MicroPython board at
`/dev/cu.usbmodem1401` completed a default three-second GP0 idle recording with
300 edges. A separate one-edge-capacity test produced a truncated recording and
exit status 1 as intended. These establish device acquisition and Mac transfer,
not receiver compatibility or fan code recognition. Supply and receiver model
were recorded as unverified; no remote presses were requested. Local smoke-test
recordings are ignored by Git. The board was reset afterward to resume startup.

Display-enabled continuous mode was also exercised on the connected board using
three one-second windows. The same preallocated buffer is reused, and each window
is saved separately. The default buffer is 8,192 edges (about 40 KiB) to leave room for the display;
the temporary initialisation list is collected before allocating level storage.

Continuous capture now gates notifications and saving on dense pulse activity.
Tests cover empty input, sparse idle transitions, short glitches, alternating
bursts, mismatched levels, and idle heartbeats that do not consume a capture ID.
