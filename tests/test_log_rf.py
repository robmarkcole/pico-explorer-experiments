import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('log_rf', ROOT / 'scripts/log_rf.py')
logger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(logger)


def records(truncated=False):
    return [
        {'type': 'ready', 'schema': 1},
        {'type': 'begin', 'schema': 1, 'initial_level': 0},
        {'type': 'edges', 'offset': 0, 'durations_us': [20, 5000], 'levels_after': [1, 0]},
        {'type': 'end', 'edge_count': 2, 'elapsed_us': 6020,
         'truncated': truncated, 'end_reason': 'edge_limit' if truncated else 'duration',
         'trailing_us': None if truncated else 1000},
    ]


class LoggerTests(unittest.TestCase):
    def test_round_trip_and_truncation(self):
        for truncated in (False, True):
            recording = logger.Recording()
            for record in records(truncated):
                recording.accept(json.loads(json.dumps(record)))
            self.assertEqual(recording.complete, not truncated)
            self.assertEqual(recording.durations, [20, 5000])

    def test_rejects_corrupt_or_missing_chunks(self):
        for bad in (
            {'type': 'edges', 'offset': 1, 'durations_us': [5], 'levels_after': [0]},
            {'type': 'edges', 'offset': 0, 'durations_us': [5], 'levels_after': []},
            {'type': 'edges', 'offset': 0, 'durations_us': [-1], 'levels_after': [0]},
        ):
            recording = logger.Recording()
            for record in records()[:2]:
                recording.accept(record)
            with self.assertRaises(ValueError):
                recording.accept(bad)
        recording = logger.Recording()
        for record in records()[:3]:
            recording.accept(record)
        bad_end = dict(records()[-1], elapsed_us=999)
        with self.assertRaises(ValueError):
            recording.accept(bad_end)

    def run_logger(self, directory, wire_records, status=0, extra_args=None):
        class Process:
            stdout = io.StringIO(''.join('RFRAW ' + json.dumps(r) + '\n' for r in wire_records))

            def wait(self, **kwargs):
                return status

            def poll(self):
                return status

            def kill(self):
                pass

        with patch.object(logger.shutil, 'which', return_value='/fake/mpremote'), \
             patch.object(logger.subprocess, 'Popen', return_value=Process()) as popen, \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = logger.main(['--port', '/dev/test', '--button', 'speed/1',
                                  '--supply', '3.3V', '--output-dir', directory] + (extra_args or []))
        command = popen.call_args.args[0]
        self.assertEqual(command[:5], ['/fake/mpremote', 'connect', '/dev/test', 'soft-reset', 'exec'])
        compile(command[-1], '<remote-code>', 'exec')
        self.assertIn("ns['main'](pin=0, duration_ms=3000, max_edges=8192", command[-1])
        return result

    def test_cli_saves_labels_and_transcript_and_unique_files(self):
        with tempfile.TemporaryDirectory() as directory:
            for _ in range(2):
                self.assertEqual(self.run_logger(directory, records()), 0)
            paths = list(Path(directory).glob('*.json'))
            self.assertEqual(len(paths), 2)
            payload = json.loads(paths[0].read_text())
            self.assertTrue(payload['complete'])
            self.assertEqual(payload['metadata']['button'], 'speed/1')
            self.assertEqual(payload['durations_us'], [20, 5000])
            self.assertTrue((Path(directory) / payload['transcript']).exists())

    def test_failed_truncated_and_interrupted_transfers_are_saved_incomplete(self):
        for wire_records, status in ((records(True), 0), (records()[:3], 0), (records(), 1)):
            with self.subTest(status=status, wire_records=wire_records):
                with tempfile.TemporaryDirectory() as directory:
                    self.assertEqual(self.run_logger(directory, wire_records, status), 1)
                    payload = json.loads(next(Path(directory).glob('*.json')).read_text())
                    self.assertFalse(payload['complete'])

    def test_continuous_saves_separate_numbered_recordings(self):
        stream = []
        for number in (1, 2, 3):
            for record in records():
                record = dict(record)
                if record['type'] in ('ready', 'begin', 'end'):
                    record['capture_id'] = number
                stream.append(record)
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self.run_logger(directory, stream,
                             extra_args=['--continuous', '--count', '3']), 0)
            paths = sorted(Path(directory).glob('*.json'))
            self.assertEqual(len(paths), 3)
            payloads = [json.loads(p.read_text()) for p in paths]
            self.assertEqual([p['capture_id'] for p in payloads], [1, 2, 3])
            self.assertTrue(all(p['complete'] for p in payloads))
            self.assertEqual(len({p['session_id'] for p in payloads}), 1)

    def test_continuous_preserves_completed_capture_when_next_is_interrupted(self):
        stream = []
        for number, window in ((1, records()), (2, records()[:3])):
            for record in window:
                record = dict(record)
                if record['type'] in ('ready', 'begin', 'end'):
                    record['capture_id'] = number
                stream.append(record)
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self.run_logger(directory, stream,
                             extra_args=['--continuous', '--count', '2']), 1)
            payloads = [json.loads(p.read_text()) for p in sorted(Path(directory).glob('*.json'))]
            self.assertEqual([p['complete'] for p in payloads], [True, False])

    def test_rejects_mixed_capture_ids(self):
        recording = logger.Recording()
        recording.accept(dict(records()[0], capture_id=1))
        with self.assertRaises(ValueError):
            recording.accept(dict(records()[1], capture_id=2))
