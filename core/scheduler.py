# core/scheduler.py — 180-second tick scheduler.
"""
The one rule that matters most:

  Round N starts at  (framework start) + N * TICK,  measured with
  time.monotonic(). The interval is counted from each round's START
  time, not from when the previous round finished.

Example (TICK = 180):
  Round 1 starts 18:00:00, finishes 18:02:20 -> Round 2 starts 18:03:00.

If a round overruns its slot (takes longer than TICK):
  * Two rounds NEVER run at the same time (rounds are sequential).
  * The grid slots that fell inside the overrun are SKIPPED.
  * The next round runs at the next grid slot strictly after the
    overrun ended — as soon as possible while staying on the grid,
    so the framework never drifts away from the scoreboard tick.

  Example (TICK = 5): round 1 runs 0s..8s. Slot at 5s is skipped.
  Next round runs at 10s.

time.monotonic() is used on purpose: it is not affected by wall-clock
changes (NTP adjustments, daylight saving, manual date changes).
"""

import math
import time


def next_round_index(start_mono: float, now_mono: float, tick: float) -> int:
    """Smallest round index whose slot is at or after `now_mono`.

    Round index i starts at start_mono + i * tick. Index 0 is the
    first round. If `now_mono` is exactly on a slot, that slot is
    returned (it is due right now, not missed yet).
    """
    if tick <= 0:
        raise ValueError("tick must be > 0")
    if now_mono <= start_mono:
        return 0
    return max(0, math.ceil((now_mono - start_mono) / tick))


class Scheduler:
    """Anchored tick scheduler. Clock and sleep are injectable for tests."""

    def __init__(self, tick: float, clock=time.monotonic, sleep=time.sleep):
        if tick <= 0:
            raise ValueError("tick must be > 0")
        self.tick = float(tick)
        self._clock = clock
        self._sleep = sleep
        self.start_mono: float | None = None

    def anchor(self) -> float:
        """Mark the framework start time. Returns it (monotonic)."""
        self.start_mono = self._clock()
        return self.start_mono

    def slot_time(self, index: int) -> float:
        """Monotonic time at which round `index` is scheduled to start."""
        return self.start_mono + index * self.tick

    def wait_until(self, index: int) -> float:
        """Sleep until round `index`'s slot. Returns the (monotonic) time
        we actually start at. Sleeps 0s if the slot is already due."""
        target = self.slot_time(index)
        delay = target - self._clock()
        if delay > 0:
            self._sleep(delay)
        return self._clock()

    def advance_after_round(self, prev_index: int) -> tuple[int, int]:
        """After round `prev_index` finished, decide what runs next.

        Returns (next_index, skipped_count). skipped_count is how many
        grid slots were missed because the round overran.
        """
        now = self._clock()
        nxt = next_round_index(self.start_mono, now, self.tick)
        # Never go backwards or repeat the round that just ran.
        nxt = max(nxt, prev_index + 1)
        return nxt, max(0, nxt - (prev_index + 1))

    def seconds_until(self, index: int) -> float:
        """Seconds from now until round `index`'s slot (<= 0 if due)."""
        return self.slot_time(index) - self._clock()
