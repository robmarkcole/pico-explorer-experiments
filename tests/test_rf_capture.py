"""Exercise the device acquisition with a simulated clock and GPIO IRQ."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class CaptureTests(unittest.TestCase):
    def load_capture(self, transitions):
        clock = types.SimpleNamespace(us=0)

        class Pin:
            IN, IRQ_RISING, IRQ_FALLING = 0, 1, 2

            def __init__(self, number, mode):
                self.level = 0
                self.handler = None
                self.transitions = list(transitions)
                clock.pin = self

            def value(self):
                return self.level

            def irq(self, handler=None, **kwargs):
                self.handler = handler
                clock.pin = self

        def sleep_ms(ms):
            end = clock.us + ms * 1000
            while clock.pin.transitions and clock.pin.transitions[0][0] <= end:
                instant, level = clock.pin.transitions.pop(0)
                clock.us = instant
                clock.pin.level = level
                if clock.pin.handler:
                    clock.pin.handler(clock.pin)
            clock.us = end

        fake_time = types.SimpleNamespace(ticks_us=lambda: clock.us,
                                          ticks_diff=lambda a, b: a - b,
                                          sleep_ms=sleep_ms)
        spec = importlib.util.spec_from_file_location('rf_capture_test', ROOT / 'rf_capture.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'machine': types.SimpleNamespace(Pin=Pin),
                                     'micropython': types.SimpleNamespace(alloc_emergency_exception_buf=lambda size: None),
                                     'time': fake_time}):
            spec.loader.exec_module(module)
        return module

    def test_preserves_noise_long_gaps_and_polarity(self):
        module = self.load_capture([(20, 1), (370, 0), (5370, 1), (6400, 0)])
        capture = module.RawCapture(0, 20)
        capture.acquire(8)
        self.assertEqual(list(capture.durations[:capture.count]), [20, 350, 5000, 1030])
        self.assertEqual(list(capture.levels[:capture.count]), [1, 0, 1, 0])
        self.assertEqual(capture.initial_level, 0)
        self.assertEqual(capture.end_us - capture.last_us, 1600)
        self.assertFalse(capture.overflow)
        self.assertIsNone(capture.pin.handler)

    def test_overflow_keeps_prefix_and_marks_loss(self):
        module = self.load_capture([(100, 1), (200, 0), (300, 1)])
        capture = module.RawCapture(0, 2)
        capture.acquire(10)
        self.assertEqual(capture.count, 2)
        self.assertEqual(list(capture.durations), [100, 100])
        self.assertTrue(capture.overflow)
        self.assertIsNone(capture.pin.handler)

    def test_no_edges_and_exact_capacity_are_not_loss(self):
        for edges in ([], [(100, 1), (200, 0)]):
            with self.subTest(edges=edges):
                module = self.load_capture(edges)
                capture = module.RawCapture(0, 2)
                capture.acquire(2)
                self.assertEqual(capture.count, len(edges))
                self.assertFalse(capture.overflow)
                self.assertEqual(capture.end_us, 2000)

    def test_continuous_reuses_buffer_and_displays_numbered_captures(self):
        module = self.load_capture([(1000100, 1), (1002200, 0)])
        messages, screen_updates = [], []

        class Screen:
            def __init__(self, pin):
                pass

            def show(self, number, state, capture=None):
                screen_updates.append((number, state, None if capture is None else capture.count))

        with patch.object(module, 'emit', side_effect=messages.append), \
             patch.object(module, 'CaptureDisplay', Screen):
            module.main(duration_ms=2, max_edges=10, continuous=True,
                        show_display=True, capture_limit=3, all_windows=True)
        ready = [m for m in messages if m['type'] == 'ready']
        ends = [m for m in messages if m['type'] == 'end']
        self.assertEqual([m['capture_id'] for m in ready], [1, 2, 3])
        self.assertEqual([m['starts_in_ms'] for m in ready], [1000, 0, 0])
        self.assertEqual([m['edge_count'] for m in ends], [1, 1, 0])
        self.assertIn((1, 'TRANSFERRING', 1), screen_updates)
        self.assertIn((3, 'TRANSFERRING', 0), screen_updates)
        self.assertEqual(screen_updates[-1], (3, 'STOPPED', None))

    def test_burst_gate_rejects_empty_sparse_idle_and_glitches(self):
        module = self.load_capture([])
        capture = module.RawCapture(0, 256)
        for widths in ([], [6000, 14000] * 100, [10, 350, 10, 1000] * 50,
                       [350, 1050] * 5):
            capture.count = len(widths)
            for index, width in enumerate(widths):
                capture.durations[index] = width
                capture.levels[index] = index % 2
            self.assertFalse(module.has_burst(capture))

    def test_burst_gate_accepts_dense_pulses_without_changing_raw_data(self):
        module = self.load_capture([])
        capture = module.RawCapture(0, 256)
        widths = [200000, 10000] + [350, 1050] * 24 + [10000]
        capture.count = len(widths)
        for index, width in enumerate(widths):
            capture.durations[index] = width
            capture.levels[index] = index % 2
        self.assertTrue(module.has_burst(capture))
        self.assertEqual(list(capture.durations[:capture.count]), widths)
        capture.levels[:] = bytes(len(capture.levels))
        self.assertFalse(module.has_burst(capture))

    def test_continuous_idle_does_not_advance_id_or_notify_capture(self):
        module = self.load_capture([(1010100 + 350 * i, (i + 1) % 2) for i in range(24)])
        messages = []
        original = module.RawCapture.acquire
        calls = []

        def bounded(capture, duration_ms):
            calls.append(1)
            if len(calls) > 2:
                raise AssertionError('Expected burst not captured')
            original(capture, duration_ms)

        with patch.object(module, 'emit', side_effect=messages.append), \
             patch.object(module.RawCapture, 'acquire', bounded):
            module.main(duration_ms=10, max_edges=100, continuous=True, capture_limit=1)
        self.assertEqual([m['capture_id'] for m in messages if m['type'] == 'ready'], [1, 1])
        self.assertEqual(len([m for m in messages if m['type'] == 'idle']), 1)
        ends = [m for m in messages if m['type'] == 'end']
        self.assertEqual(len(ends), 1)
        self.assertEqual(ends[0]['capture_id'], 1)
        self.assertEqual(ends[0]['edge_count'], 24)
