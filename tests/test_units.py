#!/usr/bin/env python3
"""Unit tests — parser + scheduler. No servers, no sleeping (fake clock).

Run:  python3 tests/test_units.py
Exit code 0 = all pass.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.parser import clean, extract_flags  # noqa: E402
from core.scheduler import Scheduler, next_round_index  # noqa: E402

FAILURES = []


def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        print(f"         got:  {got!r}\n         want: {want!r}")
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
print("[parser]")
check("html-wrapped flag",
      extract_flags("<div>LKS{ABC123}</div>"), ["LKS{ABC123}"])
check("LKSMLG2027 format",
      extract_flags("here: LKSMLG2027{hello_world-1} end"),
      ["LKSMLG2027{hello_world-1}"])
check("both formats, longer first",
      extract_flags("LKSMLG2027{AAA} and LKS{BBB}"),
      ["LKSMLG2027{AAA}", "LKS{BBB}"])
check("two flags in adjacent tags are not fused",
      extract_flags("<div>LKS{A}</div><b>LKS{B}</b>"),
      ["LKS{A}", "LKS{B}"])
check("dedupe, order preserved",
      extract_flags("LKS{X} foo LKS{X} bar LKS{Y} LKS{X}"),
      ["LKS{X}", "LKS{Y}"])
check("no flag", extract_flags("nothing here\njust text"), [])
check("empty input", extract_flags(""), [])
check("flag body cannot cross a tag",
      extract_flags("<div>LKS{NOPE</div>}"), [])
check("ANSI colours stripped",
      extract_flags("\x1b[32mLKS{GREEN}\x1b[0m"), ["LKS{GREEN}"])
check("curl progress meter stripped",
      extract_flags("  % Total    % Received % Xferd\n"
                    "100  1234  100  1234    0     0  12345      0 --:--:-- --:--:-- --:--:-- 12345\n"
                    "LKS{AFTER}"),
      ["LKS{AFTER}"])
check("carriage returns in progress output",
      extract_flags("  0% foo\r 50% bar\rLKS{CR}"), ["LKS{CR}"])
check("whitespace around flag",
      extract_flags("   \n\t LKS{WS} \n  "), ["LKS{WS}"])
check("flag with punctuation inside",
      extract_flags("LKS{a-b_c.d:e!f}"), ["LKS{a-b_c.d:e!f}"])
check("clean() keeps text, drops tags",
      clean("<p>hello</p> world"), "hello world")

# ---------------------------------------------------------------------------
# Scheduler (pure function)
# ---------------------------------------------------------------------------
print("[scheduler: next_round_index]")
check("at start -> 0", next_round_index(100.0, 100.0, 5.0), 0)
check("before first slot -> 1", next_round_index(100.0, 103.0, 5.0), 1)
check("exactly on slot -> that slot", next_round_index(100.0, 105.0, 5.0), 1)
check("just past slot -> next", next_round_index(100.0, 105.001, 5.0), 2)
check("overrun 8s, tick 5 -> index 2 (slot 5 skipped)",
      next_round_index(100.0, 108.0, 5.0), 2)
check("overrun 190s, tick 180 -> index 2",
      next_round_index(1000.0, 1190.0, 180.0), 2)
check("tick 180, exactly 180s later -> 1",
      next_round_index(0.0, 180.0, 180.0), 1)

# ---------------------------------------------------------------------------
# Scheduler class with a fake clock (no real sleeping)
# ---------------------------------------------------------------------------
print("[scheduler: class with fake clock]")


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(round(seconds, 3))
        self.now += seconds


fake = FakeClock()
sch = Scheduler(tick=5.0, clock=fake.clock, sleep=fake.sleep)
sch.anchor()
check("anchor = 1000", sch.start_mono, 1000.0)
check("wait_until(0) sleeps 0", (sch.wait_until(0), fake.slept), (1000.0, []))
sch.wait_until(1)
check("wait_until(1) sleeps 5s", fake.slept, [5.0])
check("clock advanced to 1005", fake.now, 1005.0)
# Simulate round index 0 running long: it started at 1000 and ends
# at 1008 (8s with a 5s tick -> the slot at 1005 is missed).
fake.now = 1008.0
nxt, skipped = sch.advance_after_round(0)
check("overrun: next index 2 (slot 1010)", nxt, 2)
check("overrun: 1 round skipped", skipped, 1)
# Round index 2 runs 1010..1011 (fast). Next must be index 3 at 1015.
sch.wait_until(2)
fake.now = 1011.0
nxt, skipped = sch.advance_after_round(2)
check("fast round: next index 3", nxt, 3)
check("fast round: 0 skipped", skipped, 0)
check("wait to index 3 sleeps 4s (1011 -> 1015)",
      (sch.wait_until(3), fake.slept[-1]), (1015.0, 4.0))

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
    sys.exit(1)
print("ALL UNIT TESTS PASSED")
