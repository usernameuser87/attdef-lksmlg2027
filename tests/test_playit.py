#!/usr/bin/env python3
"""Unit tests — PLAYIT PLUS 2026 platform mode. No servers, no network.

Run:  python3 tests/test_playit.py
Exit code 0 = all pass.

Covers: the PLAYIT submit response parser (incl. the non-string-flag
guard), 128-flag chunking through a stub platform client, the
submissions-closed hold, services-map pair building with own-team
exclusion, and PLAYITPLUS flag extraction in platform mode.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from core.loader import Challenge  # noqa: E402
from core.platform import PlatformError  # noqa: E402
from core.submitter import Submitter, _parse_response  # noqa: E402
from main import build_platform_pairs  # noqa: E402

FAILURES = []


def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        print(f"         got:  {got!r}\n         want: {want!r}")
        FAILURES.append(name)


def check_true(name, cond, extra=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name} {extra}")
    if not cond:
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# Parser: PLAYIT {"results": [...]} shape
# ---------------------------------------------------------------------------
print("[playit response parser]")
body = json.dumps({
    "results": [
        {"flag": "PLAYITPLUS{a}", "status": "accepted",
         "detail": "flag is correct.", "challenge_id": 1},
        {"flag": "PLAYITPLUS{b}", "status": "duplicate",
         "detail": "flag already submitted.", "challenge_id": 1},
        {"flag": "PLAYITPLUS{c}", "status": "invalid",
         "detail": "flag is wrong or expired."},
    ],
    "accepted_count": 1, "rejected_count": 2,
}).encode()
verdicts, details = _parse_response(
    body, ["PLAYITPLUS{a}", "PLAYITPLUS{b}", "PLAYITPLUS{c}"])
check("accepted mapped", verdicts["PLAYITPLUS{a}"], "accepted")
check("duplicate mapped", verdicts["PLAYITPLUS{b}"], "duplicate")
check("invalid mapped", verdicts["PLAYITPLUS{c}"], "invalid")
check("detail kept for log", details["PLAYITPLUS{a}"]["msg"],
      "flag is correct.")

# A non-string flag in the response must not crash the parse or lose
# the other flags' verdicts (regression guard).
body = json.dumps({
    "results": [
        {"flag": ["not", "a", "string"], "status": "accepted"},
        {"flag": {"weird": 1}, "status": "accepted"},
        {"flag": "PLAYITPLUS{ok}", "status": "accepted"},
    ]
}).encode()
try:
    verdicts, _ = _parse_response(body, ["PLAYITPLUS{ok}"])
    check("non-string flags skipped, good flag kept",
          verdicts["PLAYITPLUS{ok}"], "accepted")
except Exception as exc:  # noqa: BLE001
    check_true("non-string flags skipped, good flag kept", False,
               f"raised {exc!r}")

# ---------------------------------------------------------------------------
# Stub platform client
# ---------------------------------------------------------------------------
class StubPlatform:
    def __init__(self, accepting=True, fail=False):
        self.accepting = accepting
        self.fail = fail
        self.batches = []

    def accepting_submissions(self):
        return self.accepting

    def submit_flags(self, flags):
        if self.fail:
            raise PlatformError("stub transport failure")
        self.batches.append(list(flags))
        return {"results": [
            {"flag": f, "status": "accepted", "detail": "flag is correct."}
            for f in flags
        ], "accepted_count": len(flags), "rejected_count": 0}


def _fresh_submitter(platform):
    tmp = Path(tempfile.mkdtemp())
    config.SUBMITTED_FILE = tmp / "submitted.json"
    config.QUEUE_FILE = tmp / "queue.json"
    return Submitter(logger=None, platform=platform)


print("[playit chunking]")
stub = StubPlatform()
sub = _fresh_submitter(stub)
flags = [f"PLAYITPLUS{{f{i}}}" for i in range(300)]
verdicts = sub.submit(flags)
check("300 flags -> batches of 128/128/44",
      [len(b) for b in stub.batches], [128, 128, 44])
check("all 300 accepted", sum(1 for v in verdicts.values()
                              if v == "accepted"), 300)
check("queue empty after success", sub.pending_count(), 0)

print("[playit submissions closed]")
stub = StubPlatform(accepting=False)
sub = _fresh_submitter(stub)
verdicts = sub.submit(["PLAYITPLUS{held}"])
check("closed -> verdict error", verdicts.get("PLAYITPLUS{held}"), "error")
check("closed -> nothing sent", stub.batches, [])
check("closed -> flag queued", sub.pending_count(), 1)

print("[playit transport failure]")
stub = StubPlatform(fail=True)
sub = _fresh_submitter(stub)
verdicts = sub.submit(["PLAYITPLUS{retry}"])
check("failure -> verdict error", verdicts.get("PLAYITPLUS{retry}"), "error")
check("failure -> flag queued, not lost", sub.pending_count(), 1)

# ---------------------------------------------------------------------------
# Pair building from the services map
# ---------------------------------------------------------------------------
print("[playit pairs]")


def _chal(api_id):
    return Challenge(name="Dummy", port=9999, protocol="http",
                     health_path="/", timeout=5,
                     script=Path("exploit.sh"), enabled=True,
                     folder=Path("dummy-web"), api_id=api_id)


class MapPlatform:
    def services(self):
        return {"1": {"101": ["10.0.0.1:18001"],
                      "102": ["127.0.0.1:18001"],
                      "103": ["127.0.0.2:18001", "127.0.0.2:18002"]}}


pairs = build_platform_pairs(MapPlatform(), [_chal("1")], own_team_id="101")
got = sorted((t["ip"], t["port"]) for t, _ in pairs)
check("own team excluded, all endpoints paired", got,
      [("127.0.0.1", 18001), ("127.0.0.2", 18001), ("127.0.0.2", 18002)])
pairs = build_platform_pairs(MapPlatform(), [_chal(None)], own_team_id="101")
check("unmapped challenge skipped", pairs, [])
pairs = build_platform_pairs(MapPlatform(), [_chal("2")], own_team_id="101")
check("unknown api_id skipped", pairs, [])

# ---------------------------------------------------------------------------
# Flag extraction in platform mode (fresh interpreter, env-driven)
# ---------------------------------------------------------------------------
print("[playit flag regex]")
env = dict(os.environ, PLAYIT_EMAIL="a@b.c", PLAYIT_PASSWORD="secret")
out = subprocess.run(
    [sys.executable, "-c",
     "from core.parser import extract_flags;"
     "print(extract_flags('got PLAYITPLUS{abc-123} and LKS{nope}'))"],
    capture_output=True, text=True, env=env,
    cwd=str(Path(__file__).resolve().parent.parent),
)
check("platform mode extracts PLAYITPLUS only",
      out.stdout.strip(), "['PLAYITPLUS{abc-123}']")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("ALL PLAYIT CHECKS PASSED")
