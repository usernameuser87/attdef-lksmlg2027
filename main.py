#!/usr/bin/env python3
"""Auto ATTDEF Framework — LKSMLG 2027.

Run once, it runs forever:

    python3 main.py

One round every TICK_SECONDS (default 180), counted from each round's
START time with time.monotonic(). Python only orchestrates: it runs
your Bash exploits, parses flags from their stdout, submits them to
the scoreboard, and logs everything. Exploit logic stays in Bash.

Layout of one round:
  1. Health-check every (target, challenge) pair. Offline -> skipped.
  2. Run `bash exploit.sh <IP> <PORT>` for every online pair.
  3. Parse flags (LKS{...} / LKSMLG2027{...}) from stdout.
  4. Submit new flags (deduplicated, queued safely on failure).
"""

import sys
import time
import traceback
from datetime import datetime, timedelta

import config
from core.loader import load_challenges
from core.logger import Logger
from core.parser import extract_flags
from core.runner import run_all
from core.scanner import check_all
from core.scheduler import Scheduler
from core.submitter import Submitter

_DISPLAY_VERDICT = {
    "accepted": "Accepted",
    "invalid": "Invalid",
    "too_old": "Too old",
    "duplicate": "Duplicate",
    "error": "Error",
    "unknown": "Unknown",
}


def run_round(round_no, targets, challenges, logger, submitter):
    """One full round. Returns nothing; never raises (errors are logged)."""
    started = time.monotonic()
    logger.open_round(round_no)
    logger.line(f"[ROUND {round_no}] START")
    try:
        pairs = [(t, c) for t in targets for c in challenges]
        online = check_all(pairs)

        online_pairs = []
        for target, chal in pairs:
            if online.get((target["ip"], chal.slug)):
                logger.line(f"[ONLINE] {target['name']} | {chal.name}")
                online_pairs.append((target, chal))
            else:
                logger.line(f"[OFFLINE] {target['name']} | {chal.name} | SKIPPED")

        results = run_all(online_pairs)
        found: list[str] = []
        for res in results:
            logger.line(f"[EXEC] {res.challenge.name} | {res.target_name}")
            if res.timed_out:
                logger.detail(
                    f"  TIMEOUT after {res.challenge.timeout:g}s "
                    f"(partial stdout kept)"
                )
            if res.error:
                logger.detail(f"  ERROR: {res.error}")
            if res.returncode not in (None, 0):
                logger.detail(f"  exit code {res.returncode} (flags still parsed)")
            if res.stderr.strip():
                logger.detail(f"  stderr: {res.stderr.strip()[:500]}")
            flags = extract_flags(res.stdout)
            for flag in flags:
                logger.line(f"[FLAG] {flag}")
            found.extend(flags)

        verdicts = submitter.submit(found)
        if verdicts:
            details = getattr(submitter, "last_details", {}) or {}
            for flag, verdict in verdicts.items():
                line = (
                    f"[SUBMIT] {_DISPLAY_VERDICT.get(verdict, verdict)} | {flag}"
                )
                points = details.get(flag, {}).get("points")
                if points is not None:
                    line += f" | +{points:.2f} pts"
                logger.line(line)
        else:
            logger.line("[SUBMIT] nothing new to submit")
        queued = submitter.pending_count()
        if queued:
            logger.line(f"[QUEUE] {queued} flag(s) waiting for retry")

        elapsed = time.monotonic() - started
        accepted = sum(1 for v in verdicts.values() if v == "accepted")
        logger.line(
            f"[ROUND {round_no}] FINISHED in {elapsed:.1f}s | "
            f"flags found: {len(set(found))} | accepted: {accepted}"
        )
    except Exception:
        logger.line(f"[ERROR] round {round_no} failed: {traceback.format_exc(limit=3)}")
        logger.detail(traceback.format_exc())
    finally:
        logger.close_round(round_no)


def main() -> int:
    logger = Logger()
    print("=" * 60, flush=True)
    print("Auto ATTDEF Framework — LKSMLG 2027", flush=True)
    print(f"Tick: {config.TICK_SECONDS:g}s (from round START, monotonic)", flush=True)
    print(f"Submit API: {config.SUBMIT_URL}", flush=True)
    if not config.TEAM_TOKEN:
        print(
            "[WARN] ATTDEF_TEAM_TOKEN is empty — flags will be QUEUED, "
            "not submitted. Set it in .env",
            flush=True,
        )
    print("=" * 60, flush=True)

    targets = config.load_targets()
    all_challenges = load_challenges()
    challenges = [c for c in all_challenges if c.enabled]
    disabled = len(all_challenges) - len(challenges)
    if not targets:
        Logger.fatal("no targets configured")
        return 1
    if not challenges:
        Logger.fatal("no enabled challenges found — check challenges/*/config.json")
        return 1
    print(f"Targets: {len(targets)} | Challenges: {len(challenges)}"
          + (f" ({disabled} disabled)" if disabled else ""), flush=True)
    for chal in challenges:
        print(f"  - {chal.name} (port {chal.port}, {chal.protocol}, "
              f"timeout {chal.timeout:g}s, {chal.script.name})", flush=True)

    submitter = Submitter(logger=logger)
    if submitter.pending_count():
        print(f"[QUEUE] {submitter.pending_count()} flag(s) from a previous run "
              f"will be retried", flush=True)

    scheduler = Scheduler(config.TICK_SECONDS)
    scheduler.anchor()

    index = 0  # 0-based round index; displayed as index + 1
    executed = 0
    try:
        while True:
            scheduler.wait_until(index)
            run_round(index + 1, targets, challenges, logger, submitter)
            executed += 1
            if config.MAX_ROUNDS and executed >= config.MAX_ROUNDS:
                print(f"[DONE] reached MAX_ROUNDS={config.MAX_ROUNDS}", flush=True)
                break
            index, skipped = scheduler.advance_after_round(index)
            if skipped:
                logger.line(
                    f"[SKIP] {skipped} round(s) skipped — previous round "
                    f"overran the {config.TICK_SECONDS:g}s tick"
                )
            wait = scheduler.seconds_until(index)
            wall_next = datetime.now() + timedelta(seconds=max(0, wait))
            logger.line(
                f"[NEXT ROUND] {config.TICK_SECONDS:g}-second schedule | "
                f"Round {index + 1} at {wall_next.strftime('%H:%M:%S')} "
                f"(in {max(0, wait):.0f}s)"
            )
    except KeyboardInterrupt:
        print("\n[STOP] framework stopped by user", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
