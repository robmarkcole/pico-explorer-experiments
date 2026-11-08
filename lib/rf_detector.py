"""Repeated RF pulse patterns, without assuming a particular fan protocol."""

class RepeatedFrameDetector:
    def __init__(self):
        self.frame = []
        self.invalid = False
        self.previous = None
        self.matches = 0
        self.previous_ms = -10000
        self.event_ms = -10000
        self.candidates = 0
        self.latest = []

    def discard(self):
        self.frame = []
        self.invalid = True
        self.previous = None
        self.matches = 0

    def feed(self, duration_us, now_ms):
        # now_ms is elapsed monotonic time, not a wrapping ticks_ms value.
        if duration_us < 4000:
            if duration_us < 60 or len(self.frame) >= 220:
                self.invalid = True
            elif not self.invalid:
                self.frame.append(duration_us)
            return False
        frame = self.frame
        valid = not self.invalid and 20 <= len(frame) <= 220 and sum(frame) >= 6000
        self.frame = []
        self.invalid = False
        if not valid:
            self.previous = None
            self.matches = 0
            return False
        self.candidates += 1
        self.latest = frame
        similar = (self.previous is not None and len(frame) == len(self.previous)
                   and now_ms - self.previous_ms <= 1500 and all(
                       abs(a-b) <= max(80, max(a,b)*0.25)
                       for a,b in zip(frame, self.previous)))
        self.matches = self.matches + 1 if similar else 1
        self.previous = frame
        self.previous_ms = now_ms
        if self.matches < 3 or now_ms - self.event_ms < 1000:
            return False
        self.event_ms = now_ms
        self.matches = 0
        return True
