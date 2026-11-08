import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from rf_detector import RepeatedFrameDetector

class DetectorTests(unittest.TestCase):
    def send(self, detector, widths, now):
        for width in widths:
            self.assertFalse(detector.feed(width, now))
        return detector.feed(10000, now)

    def test_repeated_frames_with_jitter(self):
        d = RepeatedFrameDetector()
        frame = [350, 1050, 1050, 350] * 12
        self.assertFalse(self.send(d, frame, 100))
        self.assertFalse(self.send(d, [x+30 for x in frame], 150))
        self.assertTrue(self.send(d, [x-30 for x in frame], 200))

    def test_noise_changed_commands_and_stale_frames(self):
        d = RepeatedFrameDetector()
        frame = [350, 1050] * 24
        for widths, now in [(frame, 100), (frame[::-1], 150), (frame, 200),
                            (frame, 2000), ([10]+frame, 2050), (frame, 2100)]:
            self.assertFalse(self.send(d, widths, now))

    def test_cooldown_and_capture_overflow(self):
        d = RepeatedFrameDetector()
        frame = [350, 1050] * 24
        self.assertFalse(self.send(d, frame, 100))
        self.assertFalse(self.send(d, frame, 150))
        self.assertTrue(self.send(d, frame, 200))
        for now in (250, 300, 350):
            self.assertFalse(self.send(d, frame, now))
        d.discard()
        d.feed(10000, 1200)
        self.assertFalse(self.send(d, frame, 1250))
        self.assertFalse(self.send(d, frame, 1300))
        self.assertTrue(self.send(d, frame, 1350))

if __name__ == '__main__':
    unittest.main()
