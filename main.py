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
from core.platform import PlatformClient, PlatformError
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


def build_platform_pairs(platform, challenges, own_team_id):
    """(target, challenge) pairs from GET /api/v2/services (PLAYIT mode).

    The map is {challenge_id: {team_id: ["host:port", ...]}}. The own
    team is excluded (attacking yourself only wastes the tick). A
    challenge folder joins in via "api_id" in its config.json;
    unmapped challenges are skipped. A failed fetch yields no pairs —
    the round still runs and queued flags are still submitted.
    """
    try:
        services = platform.services()
    except PlatformError:
        return []
    pairs = []
    for chal in challenges:
        if chal.api_id is None:
            continue
        teams = services.get(str(chal.api_id))
        if not isinstance(teams, dict):
            continue
        for team_id, endpoints in teams.items():
            if own_team_id is not None and str(team_id) == str(own_team_id):
                continue
            if not isinstance(endpoints, list):
                continue
            for endpoint in endpoints:
                host, _, port = str(endpoint).rpartition(":")
                if not host:
                    continue
                try:
                    port_no = int(port)
                except ValueError:
                    port_no = chal.port
                pairs.append((
                    {"name": f"Tim {team_id}", "ip": host, "port": port_no},
                    chal,
                ))
    return pairs


def run_round(round_no, targets, challenges, logger, submitter, pairs=None):
    """One full round. Returns nothing; never raises (errors are logged).

    pairs: explicit (target, challenge) pairs (platform mode). None =
    the legacy cross-product of targets x challenges.
    """
    started = time.monotonic()
    try:
        # open_round is inside the try: if the log file cannot be
        # created (disk full, permissions), the round must still run
        # and the framework must not crash — the docstring promises
        # this function never raises.
        logger.open_round(round_no)
        logger.line(f"[ROUND {round_no}] START")
        if pairs is None:
            pairs = [(t, c) for t in targets for c in challenges]
        online = check_all(pairs)

        online_pairs = []
        for target, chal in pairs:
            if online.get((target["ip"], target.get("port"), chal.slug)):
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
    platform = PlatformClient(logger=logger) if config.PLATFORM_MODE else None
    tick = config.TICK_SECONDS
    own_team_id = None
    print("=" * 60, flush=True)
    print("Auto ATTDEF Framework — LKSMLG 2027", flush=True)
    if platform is not None:
        print(f"Mode: PLAYIT PLUS 2026 platform ({config.PLAYIT_BASE_URL})",
              flush=True)
        # The platform is the tick authority in this mode; a failed
        # fetch falls back to ATTDEF_TICK inside tick_seconds().
        tick = platform.tick_seconds(config.TICK_SECONDS)
        print(f"Tick: {tick:g}s (platform game/status, from round START, "
              f"monotonic)", flush=True)
        try:
            own_team_id = platform.my_team_id()
        except PlatformError as exc:
            print(f"[WARN] cannot read own team from the platform ({exc}); "
                  f"own services will not be excluded from targets",
                  flush=True)
        if own_team_id is not None:
            print(f"Own team id: {own_team_id} (excluded from targets)",
                  flush=True)
    else:
        print(f"Tick: {tick:g}s (from round START, monotonic)", flush=True)
        print(f"Submit API: {config.SUBMIT_URL}", flush=True)
        if not config.TEAM_TOKEN:
            print(
                "[WARN] ATTDEF_TEAM_TOKEN is empty — flags will be QUEUED, "
                "not submitted. Set it in .env",
                flush=True,
            )
    print("=" * 60, flush=True)

    targets = [] if platform is not None else config.load_targets()
    all_challenges = load_challenges()
    challenges = [c for c in all_challenges if c.enabled]
    disabled = len(all_challenges) - len(challenges)
    if platform is None and not targets:
        Logger.fatal("no targets configured")
        return 1
    if not challenges:
        Logger.fatal("no enabled challenges found — check challenges/*/config.json")
        return 1
    if platform is not None:
        unmapped = [c.name for c in challenges if c.api_id is None]
        print(f"Targets: from the platform services map | "
              f"Challenges: {len(challenges)}"
              + (f" ({disabled} disabled)" if disabled else ""), flush=True)
        if unmapped:
            print(f"[WARN] challenges without api_id are skipped in "
                  f"platform mode: {', '.join(unmapped)}", flush=True)
    else:
        print(f"Targets: {len(targets)} | Challenges: {len(challenges)}"
              + (f" ({disabled} disabled)" if disabled else ""), flush=True)
    for chal in challenges:
        print(f"  - {chal.name} (port {chal.port}, {chal.protocol}, "
              f"timeout {chal.timeout:g}s, {chal.script.name})", flush=True)

    submitter = Submitter(logger=logger, platform=platform)
    if submitter.pending_count():
        print(f"[QUEUE] {submitter.pending_count()} flag(s) from a previous run "
              f"will be retried", flush=True)

    scheduler = Scheduler(tick)
    scheduler.anchor()

    index = 0  # 0-based round index; displayed as index + 1
    executed = 0
    try:
        while True:
            scheduler.wait_until(index)
            pairs = None
            if platform is not None:
                # Fresh pairs every round: the services map can change
                # between ticks (services restart, teams drop out).
                pairs = build_platform_pairs(platform, challenges, own_team_id)
            run_round(index + 1, targets, challenges, logger, submitter,
                      pairs=pairs)
            executed += 1
            if config.MAX_ROUNDS and executed >= config.MAX_ROUNDS:
                print(f"[DONE] reached MAX_ROUNDS={config.MAX_ROUNDS}", flush=True)
                break
            index, skipped = scheduler.advance_after_round(index)
            if skipped:
                logger.line(
                    f"[SKIP] {skipped} round(s) skipped — previous round "
                    f"overran the {tick:g}s tick"
                )
            wait = scheduler.seconds_until(index)
            wall_next = datetime.now() + timedelta(seconds=max(0, wait))
            logger.line(
                f"[NEXT ROUND] {tick:g}-second schedule | "
                f"Round {index + 1} at {wall_next.strftime('%H:%M:%S')} "
                f"(in {max(0, wait):.0f}s)"
            )
    except KeyboardInterrupt:
        print("\n[STOP] framework stopped by user", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
