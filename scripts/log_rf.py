#!/usr/bin/env python3
"""Run a temporary Pico RF capture via mpremote and save labelled JSON."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import uuid

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'RFRAW '


class Recording:
    def __init__(self):
        self.ready = None
        self.begin = None
        self.end = None
        self.durations = []
        self.levels = []

    def accept(self, record):
        kind = record.get('type')
        if kind == 'ready':
            if self.ready is not None or record.get('schema') != 1:
                raise ValueError('Invalid or duplicate ready record')
            self.ready = record
        elif kind == 'begin':
            if self.ready is None or self.begin is not None or record.get('schema') != 1:
                raise ValueError('Invalid begin record')
            if record.get('capture_id') != self.ready.get('capture_id'):
                raise ValueError('Capture ID mismatch')
            if record.get('initial_level') not in (0, 1):
                raise ValueError('Invalid initial level')
            self.begin = record
        elif kind == 'edges':
            if self.begin is None or self.end is not None:
                raise ValueError('Edges outside capture')
            widths, levels = record['durations_us'], record['levels_after']
            if record['offset'] != len(self.durations) or len(widths) != len(levels):
                raise ValueError('Missing, duplicate or mismatched edge chunk')
            if any(type(w) is not int or w < 0 for w in widths):
                raise ValueError('Invalid pulse duration')
            if any(type(level) is not int or level not in (0, 1) for level in levels):
                raise ValueError('Invalid signal level')
            self.durations.extend(widths)
            self.levels.extend(levels)
        elif kind == 'end':
            if self.begin is None or self.end is not None:
                raise ValueError('Invalid end record')
            if record.get('capture_id') != self.begin.get('capture_id'):
                raise ValueError('Capture ID mismatch')
            if record['edge_count'] != len(self.durations):
                raise ValueError('Edge count mismatch')
            trailing = record['trailing_us']
            if type(record['truncated']) is not bool:
                raise ValueError('Invalid truncation flag')
            if record['truncated']:
                if trailing is not None or record['end_reason'] != 'edge_limit':
                    raise ValueError('Invalid truncated capture')
            elif (type(trailing) is not int or trailing < 0 or
                  record['end_reason'] != 'duration' or
                  sum(self.durations) + trailing != record['elapsed_us']):
                raise ValueError('Invalid capture timing')
            self.end = record
        else:
            raise ValueError('Unknown capture record type')

    @property
    def complete(self):
        return self.end is not None and not self.end['truncated']


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--port', required=True, help='Explicit /dev/cu.usbmodem… port')
    result.add_argument('--button', default='unlabelled', help='Button label, or idle for a baseline')
    result.add_argument('--press', type=int, default=1, help='Repetition number')
    result.add_argument('--kind', choices=('unknown', 'short', 'held', 'idle'), default='unknown')
    result.add_argument('--receiver', default='DollaTek (model unverified)')
    result.add_argument('--supply', default='unverified', help='Actual receiver supply, e.g. 3.3V')
    result.add_argument('--notes', default='', help='Remote model, wiring, distance, etc.')
    result.add_argument('--pin', type=int, default=0)
    result.add_argument('--duration-ms', type=int, default=3000)
    result.add_argument('--max-edges', type=int, default=8192)
    result.add_argument('--continuous', action='store_true', help='Listen continually; save plausible bursts with Pico display feedback')
    result.add_argument('--all-windows', action='store_true', help='Save idle windows too (raw diagnostic mode)')
    result.add_argument('--burst-min-pulses', type=int, default=20)
    result.add_argument('--burst-max-us', type=int, default=4000)
    result.add_argument('--display', action='store_true', help='Show Pico Explorer display for a single window')
    result.add_argument('--count', type=int, default=0, help='Stop after N saved captures; 0 runs until Ctrl-C')
    result.add_argument('--output-dir', type=Path, default=ROOT / 'captures/ceiling-fan/local')
    return result


def save_recording(recording, args, now, stem, transcript, error=None):
    number = recording.ready.get('capture_id', 1) if recording.ready else 1
    suffix = '-capture-{:06d}'.format(number) if args.continuous else ''
    destination = args.output_dir / (stem + suffix + '.json')
    payload = {
        'schema': 'pico-rf-capture-v1', 'recorded_at_utc': now.isoformat(),
        'session_id': stem, 'capture_id': number,
        'metadata': {'button': args.button, 'press': args.press, 'kind': args.kind,
                     'receiver': args.receiver, 'supply': args.supply, 'notes': args.notes,
                     'port': args.port, 'pin': args.pin,
                     'requested_duration_ms': args.duration_ms, 'max_edges': args.max_edges,
                     'burst_gate': args.continuous and not args.all_windows,
                     'burst_min_pulses': args.burst_min_pulses, 'burst_max_us': args.burst_max_us},
        'complete': recording.complete and error is None, 'error': error,
        'begin': recording.begin, 'end': recording.end,
        'durations_us': recording.durations, 'levels_after': recording.levels,
        'transcript': transcript.name,
    }
    with destination.open('x') as output:
        json.dump(payload, output, indent=2)
        output.write('\n')
    print('Saved #{}: {} ({} edges; {})'.format(number, destination,
          len(recording.durations), 'complete' if payload['complete'] else 'INCOMPLETE'), flush=True)
    return payload['complete']


def main(argv=None):
    args = parser().parse_args(argv)
    if not 1 <= args.duration_ms <= 30000 or not 1 <= args.max_edges <= 32768:
        raise SystemExit('duration-ms must be 1..30000; max-edges must be 1..32768')
    if not 0 <= args.pin <= 28 or args.press < 1:
        raise SystemExit('pin must be 0..28; press must be positive')
    if args.count < 0 or (args.count and not args.continuous):
        raise SystemExit('count must be nonnegative and requires --continuous')
    if not 2 <= args.burst_min_pulses <= 1000 or not 60 <= args.burst_max_us <= 30000:
        raise SystemExit('burst-min-pulses must be 2..1000; burst-max-us must be 60..30000')
    executable = shutil.which('mpremote')
    if executable is None:
        raise SystemExit('Install mpremote first: python3 -m pip install mpremote')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    label = re.sub(r'[^A-Za-z0-9_-]+', '-', args.button).strip('-')[:60] or 'capture'
    stem = '{}-{}-{:02d}-{}'.format(now.strftime('%Y%m%dT%H%M%S%fZ'), label,
                                  args.press, uuid.uuid4().hex[:8])
    transcript = args.output_dir / (stem + '.serial.txt')
    source = (ROOT / 'rf_capture.py').read_text()
    options = 'pin={}, duration_ms={}, max_edges={}'.format(args.pin, args.duration_ms, args.max_edges)
    if args.continuous or args.display:
        options += ', continuous={!r}, show_display=True, capture_limit={}'.format(args.continuous, args.count)
    if args.continuous:
        options += ', all_windows={!r}, burst_min_pulses={}, burst_max_us={}'.format(
            args.all_windows, args.burst_min_pulses, args.burst_max_us)
    code = "ns={{'__name__':'rf_capture'}}; exec({!r}, ns); ns['main']({})".format(source, options)
    recording = Recording()
    error = None
    saved = 0
    all_complete = True
    interrupted = False
    window_time = now
    print('Connecting to {}. Wait for READY before pressing the remote.'.format(args.port), flush=True)
    try:
        with transcript.open('x') as log:
            process = subprocess.Popen([executable, 'connect', args.port, 'soft-reset', 'exec', code],
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, bufsize=1)
            watchdog = threading.Timer(args.duration_ms / 1000 + 30, process.kill)
            watchdog.daemon = True
            watchdog.start()
            try:
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    if line.startswith(PREFIX):
                        record = json.loads(line[len(PREFIX):])
                        if args.continuous and record.get('type') == 'idle':
                            if (recording.ready is None or recording.begin is not None or
                                    record.get('capture_id') != recording.ready.get('capture_id')):
                                raise ValueError('Invalid idle record')
                            recording = Recording()
                            continue
                        if args.continuous and record.get('type') == 'ready':
                            if recording.ready is not None:
                                if recording.end is None:
                                    raise ValueError('New window before previous capture completed')
                                recording = Recording()
                            window_time = datetime.now(timezone.utc)
                            watchdog.cancel()
                            watchdog = threading.Timer(args.duration_ms / 1000 + 30, process.kill)
                            watchdog.daemon = True
                            watchdog.start()
                        recording.accept(record)
                        if record['type'] == 'ready':
                            if not args.continuous or args.all_windows or record.get('starts_in_ms'):
                                print('READY #{}: starts in {} ms; recording {:.1f}s.'.format(
                                    record.get('capture_id', 1), record.get('starts_in_ms', 1000),
                                    args.duration_ms / 1000), flush=True)
                        elif args.continuous and record['type'] == 'end':
                            all_complete &= save_recording(recording, args, window_time, stem, transcript, error)
                            saved += 1
                    elif line.strip():
                        error = 'Unexpected device/transport output; inspect transcript'
                        print(line.rstrip(), file=sys.stderr)
                status = process.wait()
                if status:
                    error = 'mpremote exited with status {}'.format(status)
                elif args.continuous and not args.count:
                    error = 'Continuous device capture stopped unexpectedly'
                elif args.continuous and saved != args.count:
                    error = 'Device stopped before requested window count'
            finally:
                watchdog.cancel()
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                process.stdout.close()
    except (OSError, ValueError, KeyError, TypeError, KeyboardInterrupt) as exc:
        interrupted = isinstance(exc, KeyboardInterrupt)
        error = '{}: {}'.format(type(exc).__name__, exc)
    if recording.end is None and error is None:
        error = 'Capture ended without an end record'
    if not args.continuous or recording.end is None:
        all_complete &= save_recording(recording, args, window_time, stem, transcript, error)
    if error:
        print(error, file=sys.stderr)
    if args.continuous and interrupted:
        return 0
    return 0 if all_complete and error is None else 1


if __name__ == '__main__':
    sys.exit(main())
