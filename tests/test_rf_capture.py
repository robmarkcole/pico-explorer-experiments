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
                        show_display=True, capture_limit=3)
        ready = [m for m in messages if m['type'] == 'ready']
        ends = [m for m in messages if m['type'] == 'end']
        self.assertEqual([m['capture_id'] for m in ready], [1, 2, 3])
        self.assertEqual([m['starts_in_ms'] for m in ready], [1000, 0, 0])
        self.assertEqual([m['edge_count'] for m in ends], [1, 1, 0])
        self.assertIn((1, 'TRANSFERRING', 1), screen_updates)
        self.assertIn((3, 'TRANSFERRING', 0), screen_updates)
        self.assertEqual(screen_updates[-1], (3, 'STOPPED', None))
