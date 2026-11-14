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
    result.add_argument('--button', required=True, help='Button label, or idle for a baseline')
    result.add_argument('--press', type=int, default=1, help='Repetition number')
    result.add_argument('--kind', choices=('short', 'held', 'idle'), default='short')
    result.add_argument('--receiver', default='DollaTek (model unverified)')
    result.add_argument('--supply', required=True, help='Actual receiver supply, e.g. 3.3V')
    result.add_argument('--notes', default='', help='Remote model, wiring, distance, etc.')
    result.add_argument('--pin', type=int, default=0)
    result.add_argument('--duration-ms', type=int, default=3000)
    result.add_argument('--max-edges', type=int, default=16384)
    result.add_argument('--output-dir', type=Path, default=ROOT / 'captures/ceiling-fan/local')
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    if not 1 <= args.duration_ms <= 30000 or not 1 <= args.max_edges <= 32768:
        raise SystemExit('duration-ms must be 1..30000; max-edges must be 1..32768')
    if not 0 <= args.pin <= 28 or args.press < 1:
        raise SystemExit('pin must be 0..28; press must be positive')
    executable = shutil.which('mpremote')
    if executable is None:
        raise SystemExit('Install mpremote first: python3 -m pip install mpremote')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    label = re.sub(r'[^A-Za-z0-9_-]+', '-', args.button).strip('-')[:60] or 'capture'
    stem = '{}-{}-{:02d}-{}'.format(now.strftime('%Y%m%dT%H%M%S%fZ'), label,
                                  args.press, uuid.uuid4().hex[:8])
    transcript = args.output_dir / (stem + '.serial.txt')
    destination = args.output_dir / (stem + '.json')
    source = (ROOT / 'rf_capture.py').read_text()
    # Execute the local module in a named namespace without its __main__ guard.
    code = "ns={{'__name__':'rf_capture'}}; exec({!r}, ns); ns['main'](pin={}, duration_ms={}, max_edges={})".format(
        source, args.pin, args.duration_ms, args.max_edges)
    recording = Recording()
    error = None
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
                        recording.accept(record)
                        if record['type'] == 'ready':
                            print('READY: capture starts in 1 second; press during the next {:.1f}s.'.format(
                                args.duration_ms / 1000), flush=True)
                    elif line.strip():
                        error = 'Unexpected device/transport output; inspect transcript'
                        print(line.rstrip(), file=sys.stderr)
                status = process.wait()
                if status:
                    error = 'mpremote exited with status {}'.format(status)
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
        error = '{}: {}'.format(type(exc).__name__, exc)
    if recording.end is None and error is None:
        error = 'Capture ended without an end record'
    payload = {
        'schema': 'pico-rf-capture-v1', 'recorded_at_utc': now.isoformat(),
        'metadata': {'button': args.button, 'press': args.press, 'kind': args.kind,
                     'receiver': args.receiver, 'supply': args.supply, 'notes': args.notes,
                     'port': args.port, 'pin': args.pin,
                     'requested_duration_ms': args.duration_ms, 'max_edges': args.max_edges},
        'complete': recording.complete and error is None, 'error': error,
        'begin': recording.begin, 'end': recording.end,
        'durations_us': recording.durations, 'levels_after': recording.levels,
        'transcript': transcript.name,
    }
    with destination.open('x') as output:
        json.dump(payload, output, indent=2)
        output.write('\n')
    print('Saved {} ({} edges; {})'.format(destination, len(recording.durations),
          'complete' if payload['complete'] else 'INCOMPLETE'))
    if error:
        print(error, file=sys.stderr)
    return 0 if payload['complete'] else 1


if __name__ == '__main__':
    sys.exit(main())
