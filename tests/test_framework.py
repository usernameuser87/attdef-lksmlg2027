#!/usr/bin/env python3
"""End-to-end test for the Auto ATTDEF Framework.

Run:  python3 tests/test_framework.py
Exit code 0 = all checks pass.

What it does (all against localhost, nothing touches the real
competition infrastructure):
  Phase 1 — normal tick (5s), 3 rounds, mock submit server fails its
           FIRST request with HTTP 500 (queue/retry test).
           Checks: exact tick spacing, flags found + submitted once,
           no lost flags, both flag formats, offline targets skipped,
           nonzero-exit exploit still yields its flag, per-round logs.
  Phase 2 — overrun: only the "slow" challenge (sleeps 8s) enabled,
           tick 5s, 2 executed rounds.
           Checks: the missed grid slot is skipped (rounds 1 and 3
           run, never 2), rounds never overlap, next round starts on
           the grid (t0 + 10s), slow flag still submitted.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
DATA = TESTS / "data"
LOGS = TESTS / "logs"
CHALLENGES = TESTS / "challenges"

FAILURES: list[str] = []
PASSES: list[str] = []


def check(name, ok, detail=""):
    (PASSES if ok else FAILURES).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + (f"  ({detail})" if detail and not ok else ""))


def read_jsonl(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def set_enabled(slug, enabled):
    cfg = CHALLENGES / slug / "config.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["enabled"] = enabled
    cfg.write_text(json.dumps(data), encoding="utf-8")


def wait_for_http(url, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


class Proc:
    """A subprocess whose stdout lines are timestamped as they arrive."""

    def __init__(self, argv, env, cwd):
        self.proc = subprocess.Popen(
            argv, env=env, cwd=str(cwd),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        self.lines: list[tuple[float, str]] = []
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def _drain(self):
        for line in self.proc.stdout:
            self.lines.append((time.time(), line.rstrip("\n")))

    def wait(self, timeout):
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            return self.proc.wait()

    def kill(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()

    def text(self):
        return "\n".join(line for _, line in self.lines)

    def round_starts(self):
        """[(round_no, arrival_time)] for every '[ROUND n] START' line."""
        out = []
        for ts, line in self.lines:
            m = re.search(r"\[ROUND (\d+)\] START", line)
            if m:
                out.append((int(m.group(1)), ts))
        return out


def base_env(**overrides):
    env = dict(os.environ)
    env.update({
        "ATTDEF_SUBMIT_URL": "http://127.0.0.1:18081/flags",
        "ATTDEF_TEAM_TOKEN": "TEST_TOKEN",
        "ATTDEF_CHALLENGES_DIR": str(CHALLENGES),
        "ATTDEF_TARGETS_FILE": str(TESTS / "targets.json"),
        "ATTDEF_LOGS_DIR": str(LOGS),
        "ATTDEF_DATA_DIR": str(DATA),
        "ATTDEF_EXPLOIT_TIMEOUT": "10",
        "ATTDEF_HEALTH_TIMEOUT": "2",
        "PYTHONUNBUFFERED": "1",
    })
    env.update(overrides)
    return env


def clean_dirs():
    for d in (DATA, LOGS):
        d.mkdir(parents=True, exist_ok=True)
        for p in d.iterdir():
            p.unlink()
    for slug in ("calculator", "web-flag", "notes-app", "offline-chal"):
        set_enabled(slug, True)
    set_enabled("slow", False)


# ===========================================================================
# Phase 1 — normal tick
# ===========================================================================
def phase1(vuln, submit):
    print("\n[phase 1] normal tick: 5s, 3 rounds, submit fails first request")
    env = base_env(ATTDEF_TICK="5", ATTDEF_MAX_ROUNDS="3")
    fw = Proc([sys.executable, "main.py"], env, ROOT)
    rc = fw.wait(timeout=90)
    out = fw.text()
    starts = fw.round_starts()

    check("framework exits 0", rc == 0, f"rc={rc}")
    check("3 rounds started", [n for n, _ in starts] == [1, 2, 3],
          f"starts={[n for n, _ in starts]}")
    check("round 3 finished + DONE line",
          "[ROUND 3] FINISHED" in out and "reached MAX_ROUNDS=3" in out)
    if len(starts) == 3:
        i1 = starts[1][1] - starts[0][1]
        i2 = starts[2][1] - starts[1][1]
        check("tick 1 is ~5s", 4.0 <= i1 <= 6.0, f"{i1:.2f}s")
        check("tick 2 is ~5s", 4.0 <= i2 <= 6.0, f"{i2:.2f}s")
        print(f"        measured intervals: {i1:.2f}s, {i2:.2f}s (target 5s)")
    check("no traceback / no [ERROR] in console",
          "Traceback" not in out and "[ERROR]" not in out)

    # Offline handling.
    check("offline team reported", "[OFFLINE] Test Team B (offline)" in out)
    check("offline challenge reported",
          "[OFFLINE] Test Team A | Offline Chal | SKIPPED" in out)
    exec_lines = [l for l in out.splitlines() if l.startswith("[EXEC]")]
    check("only online pairs executed (3 chal x 1 team x 3 rounds = 9)",
          len(exec_lines) == 9, f"got {len(exec_lines)}")
    check("no EXEC for offline pairs",
          not any("Offline Chal" in l or "Test Team B" in l for l in exec_lines))

    # Flags: served vs accepted.
    served = [e["flag"] for e in read_jsonl(DATA / "served.jsonl")]
    received = read_jsonl(DATA / "received.jsonl")
    accepted = []
    for entry in received:
        if entry.get("status") == 200:
            accepted.extend(entry.get("result", {}).get("accepted", []))
    served_set, accepted_set = set(served), set(accepted)
    check("at least one flag served", len(served_set) >= 1,
          f"served={len(served_set)}")
    check("no flag lost (every served flag accepted)",
          served_set <= accepted_set,
          f"missing={sorted(served_set - accepted_set)}")
    check("no flag submitted twice",
          len(accepted) == len(accepted_set),
          f"accepted={len(accepted)} unique={len(accepted_set)}")
    check("both flag formats accepted",
          any(f.startswith("LKS{") for f in accepted_set)
          and any(f.startswith("LKSMLG2027{") for f in accepted_set))
    check("first submit request failed with 500 (queue test)",
          received and received[0].get("status") == 500)
    check("queued flags retried and accepted in a later round",
          len([e for e in received if e.get("status") == 200]) >= 2)
    check("[QUEUE] line shown while retry pending",
          "[QUEUE]" in out)

    # Logs on disk.
    round_logs = sorted(LOGS.glob("round-*.log"))
    check("one log file per round (3)", len(round_logs) == 3,
          f"got {len(round_logs)}")
    check("submissions.log exists with entries",
          (LOGS / "submissions.log").exists()
          and (LOGS / "submissions.log").stat().st_size > 0)
    return out


# ===========================================================================
# Phase 2 — overrun (round longer than the tick)
# ===========================================================================
def phase2():
    print("\n[phase 2] overrun: only 'slow' (8s) enabled, tick 5s, 2 rounds")
    for slug in ("calculator", "web-flag", "notes-app", "offline-chal"):
        set_enabled(slug, False)
    set_enabled("slow", True)
    env = base_env(ATTDEF_TICK="5", ATTDEF_MAX_ROUNDS="2")
    fw = Proc([sys.executable, "main.py"], env, ROOT)
    rc = fw.wait(timeout=90)
    out = fw.text()
    starts = fw.round_starts()

    check("framework exits 0", rc == 0, f"rc={rc}")
    check("rounds 1 and 3 ran, round 2 skipped",
          [n for n, _ in starts] == [1, 3],
          f"starts={[n for n, _ in starts]}")
    check("skip notice printed", "[SKIP] 1 round(s) skipped" in out)
    if len(starts) == 2:
        gap = starts[1][1] - starts[0][1]
        check("round 3 starts on the grid (~10s after round 1)",
              8.5 <= gap <= 11.5, f"{gap:.2f}s")
        print(f"        measured gap: {gap:.2f}s (target 10s)")
    # No overlap: round 1 FINISHED must come before round 3 START.
    idx_fin = out.find("[ROUND 1] FINISHED")
    idx_start3 = out.find("[ROUND 3] START")
    check("no overlap (round 1 finished before round 3 started)",
          0 <= idx_fin < idx_start3)
    # Slow flag still submitted (phase 2 has its own log files).
    served2 = {e["flag"] for e in read_jsonl(DATA / "served2.jsonl")}
    received2 = read_jsonl(DATA / "received2.jsonl")
    accepted2 = []
    for entry in received2:
        if entry.get("status") == 200:
            accepted2.extend(entry.get("result", {}).get("accepted", []))
    check("slow challenge flag submitted", len(accepted2) >= 1,
          f"accepted={accepted2}")
    check("no slow flag lost", served2 <= set(accepted2),
          f"missing={sorted(served2 - set(accepted2))}")
    check("no traceback / no [ERROR] in console",
          "Traceback" not in out and "[ERROR]" not in out)
    return out


# ===========================================================================
def main():
    print("Auto ATTDEF Framework — end-to-end test")
    print(f"project root: {ROOT}")
    clean_dirs()

    vuln_env = dict(os.environ)
    vuln_env.update({
        "MOCK_VULN_PORT": "18080",
        "MOCK_ROTATE_SECONDS": "8",
        "MOCK_SERVED_LOG": str(DATA / "served.jsonl"),
        "PYTHONUNBUFFERED": "1",
    })
    submit_env = dict(os.environ)
    submit_env.update({
        "MOCK_SUBMIT_PORT": "18081",
        "MOCK_SUBMIT_TOKEN": "TEST_TOKEN",
        "MOCK_RECEIVED_LOG": str(DATA / "received.jsonl"),
        "MOCK_FAIL_FIRST": "1",
        # Answer with the REAL scoreboard's [{"flag","msg"}] shape, so
        # the e2e run proves the framework parses the live API.
        "MOCK_MSG_FORMAT": "1",
        "PYTHONUNBUFFERED": "1",
    })
    vuln = subprocess.Popen(
        [sys.executable, "tests/mock_vuln_server.py"],
        env=vuln_env, cwd=str(ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    submit = subprocess.Popen(
        [sys.executable, "tests/mock_submit_server.py"],
        env=submit_env, cwd=str(ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        ok = wait_for_http("http://127.0.0.1:18080/health")
        check("mock vuln server up", ok)
        # A GET to /flags returns 501 (PUT-only) — that still proves the
        # submit server is listening.
        try:
            urllib.request.urlopen("http://127.0.0.1:18081/flags", timeout=2)
            ok = False
        except urllib.error.HTTPError:
            ok = True
        except Exception:
            ok = False
        check("mock submit server up", ok)

        phase1(vuln, submit)

        # Fresh logs for phase 2 (new rotation window, no fail-first).
        submit.kill()
        submit.wait()
        submit_env["MOCK_FAIL_FIRST"] = "0"
        submit_env["MOCK_RECEIVED_LOG"] = str(DATA / "received2.jsonl")
        vuln_env["MOCK_SERVED_LOG"] = str(DATA / "served2.jsonl")
        vuln.kill()
        vuln.wait()
        vuln = subprocess.Popen(
            [sys.executable, "tests/mock_vuln_server.py"],
            env=vuln_env, cwd=str(ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        submit = subprocess.Popen(
            [sys.executable, "tests/mock_submit_server.py"],
            env=submit_env, cwd=str(ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        wait_for_http("http://127.0.0.1:18080/health")
        time.sleep(0.5)
        phase2()
    finally:
        for p in (vuln, submit):
            try:
                p.kill()
                p.wait()
            except Exception:
                pass
        # Leave the test fixtures in their default state.
        for slug in ("calculator", "web-flag", "notes-app", "offline-chal"):
            set_enabled(slug, True)
        set_enabled("slow", False)

    print(f"\n{len(PASSES)} passed, {len(FAILURES)} failed")
    if FAILURES:
        print("FAILED CHECKS:")
        for name in FAILURES:
            print(f"  - {name}")
        sys.exit(1)
    print("ALL END-TO-END TESTS PASSED")


if __name__ == "__main__":
    main()
