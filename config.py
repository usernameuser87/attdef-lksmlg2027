# config.py — Auto ATTDEF Framework (LKSMLG 2027)
"""
Global configuration.

Sources, in order of precedence (highest first):
  1. Environment variables (ATTDEF_*)
  2. .env file in the project root
  3. Defaults in this file

The nine competition targets are defined here. They are the ONLY targets
the framework will ever touch. A targets.json file (or ATTDEF_TARGETS_FILE)
can override them — used by the test suite to point at localhost.
"""

import json
import math
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (stdlib only). Never overwrites real env vars."""
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError) as exc:
        # A .env that is a directory, unreadable, or not valid UTF-8
        # used to crash the whole framework at import time (config is
        # imported first, before any try/except exists). Ignore it
        # with a warning instead — the defaults still work.
        print(f"[WARN] cannot read .env {path} ({exc}); ignoring it")
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        # Allow the common `export KEY=value` form in .env files.
        # Without this, `export ATTDEF_TEAM_TOKEN=...` silently sets
        # a variable literally named "export ATTDEF_TEAM_TOKEN" and
        # the token stays empty, so every flag is only queued.
        if key.startswith("export ") or key.startswith("export\t"):
            key = key[7:].strip()
        if not key:
            continue
        # Strip surrounding quotes, if any.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_dotenv(BASE_DIR / ".env")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _positive_float(name: str, default: float) -> float:
    """Env float that must be finite and > 0, else the default.

    A plain float() accepts "nan", "inf" and negatives, and each of
    those breaks something downstream in a different, confusing way:
    TICK=nan crashes the scheduler after round 1 (math.ceil(nan)),
    TICK=inf crashes main() at timedelta(seconds=inf), a negative
    timeout makes every exploit time out instantly, and a 0 submit
    timeout turns every submission into a transport error. So any
    non-finite or non-positive value falls back to the default.
    """
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value) or value <= 0:
        return default
    return value


# ---------------------------------------------------------------------------
# Competition targets — ONLY these are in scope. Do not add others.
# ---------------------------------------------------------------------------
DEFAULT_TARGETS = [
    {"name": "SMKN 5 Malang", "ip": "103.145.226.96"},
    {"name": "SMKS Islam Batu", "ip": "103.145.226.94"},
    {"name": "SMKN 11 Malang", "ip": "103.145.226.90"},
    {"name": "SMKN 8 Malang", "ip": "103.145.226.93"},
    {"name": "SMKN 12 Malang", "ip": "103.145.226.82"},
    {"name": "SMKS PGRI 3 Malang", "ip": "103.185.52.42"},
    {"name": "SMKN 9 Malang", "ip": "103.145.226.92"},
    {"name": "SMK Telkom Malang", "ip": "103.185.52.146"},
    {"name": "SMKN 2 Malang", "ip": "103.145.226.98"},
]


def load_targets():
    """Return the target list. A targets file overrides the built-ins.

    The override exists so the test suite can run against localhost
    without touching competition infrastructure.
    """
    targets_file = os.environ.get("ATTDEF_TARGETS_FILE")
    candidates = []
    if targets_file:
        candidates.append(Path(targets_file))
    candidates.append(BASE_DIR / "targets.json")
    for path in candidates:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                targets = [
                    {"name": str(t["name"]), "ip": str(t["ip"])}
                    for t in data
                ]
                if targets:
                    return targets
            except (ValueError, KeyError, TypeError):
                continue
    return list(DEFAULT_TARGETS)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
# Interval between round START times, in seconds. 180 = competition tick.
# A bad value (0, negative, non-numeric, nan, inf) falls back to 180
# instead of crashing the framework after round 1.
TICK_SECONDS = _positive_float("ATTDEF_TICK", 180)
# 0 = run forever. > 0 = stop after that many executed rounds (testing).
MAX_ROUNDS = _env_int("ATTDEF_MAX_ROUNDS", 0)

# ---------------------------------------------------------------------------
# Submission API (official scoreboard)
# ---------------------------------------------------------------------------
SUBMIT_URL = os.environ.get(
    "ATTDEF_SUBMIT_URL", "http://103.145.226.89:8080/flags"
)
TEAM_TOKEN = os.environ.get("ATTDEF_TEAM_TOKEN", "")
SUBMIT_TIMEOUT = _positive_float("ATTDEF_SUBMIT_TIMEOUT", 15)
# How many times a queued flag is retried before a warning is logged.
# Flags are NEVER dropped for exceeding this — they stay queued and
# keep being retried, because a lost flag is worse than a late one.
SUBMIT_MAX_RETRIES = _env_int("ATTDEF_SUBMIT_MAX_RETRIES", 10)

# ---------------------------------------------------------------------------
# PLAYIT PLUS 2026 platform mode (ADTickPlatform participant API v2.0.0)
# ---------------------------------------------------------------------------
# When PLAYIT_EMAIL and PLAYIT_PASSWORD are set, the framework runs in
# platform mode: targets come from GET /api/v2/services, the tick comes
# from GET /api/v2/game/status, and flags go to POST /api/v2/submit
# with a JWT (see core/platform.py). Without them, the legacy LKSMLG
# scoreboard behaviour above is used unchanged.
PLAYIT_BASE_URL = os.environ.get("PLAYIT_BASE_URL", "https://10.0.2.3")
PLAYIT_EMAIL = os.environ.get("PLAYIT_EMAIL", "")
PLAYIT_PASSWORD = os.environ.get("PLAYIT_PASSWORD", "")
PLAYIT_VERIFY_TLS = os.environ.get(
    "PLAYIT_VERIFY_TLS", "").strip().lower() in ("1", "true", "yes", "on")
PLATFORM_MODE = bool(PLAYIT_EMAIL and PLAYIT_PASSWORD)

# ---------------------------------------------------------------------------
# Flag format
# ---------------------------------------------------------------------------
# ATTDEF_FLAG_REGEX overrides everything. In platform mode the default
# is the PLAYIT PLUS format; otherwise the parser's built-in LKS /
# LKSMLG2027 patterns are used (FLAG_PATTERN = None).
FLAG_PATTERN = os.environ.get("ATTDEF_FLAG_REGEX") or (
    r"PLAYITPLUS\{[^}\s<>]+\}" if PLATFORM_MODE else None
)

# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
CHALLENGES_DIR = Path(
    os.environ.get("ATTDEF_CHALLENGES_DIR", str(BASE_DIR / "challenges"))
).resolve()
# .resolve() matters: a relative ATTDEF_CHALLENGES_DIR would make every
# exploit fail ("No such file or directory", exit 127) because the
# runner executes scripts with cwd=challenge.folder.
# Default per-exploit timeout (seconds) when a challenge has no timeout.
DEFAULT_EXPLOIT_TIMEOUT = _positive_float("ATTDEF_EXPLOIT_TIMEOUT", 30)
# Default health-check timeout (seconds).
DEFAULT_HEALTH_TIMEOUT = _positive_float("ATTDEF_HEALTH_TIMEOUT", 3)
# Parallel workers for health checks and exploit runs. A bad value
# (0, negative) would crash ThreadPoolExecutor — clamp to the default.
SCAN_WORKERS = _env_int("ATTDEF_SCAN_WORKERS", 20)
if SCAN_WORKERS < 1:
    SCAN_WORKERS = 20
EXEC_WORKERS = _env_int("ATTDEF_EXEC_WORKERS", 20)
if EXEC_WORKERS < 1:
    EXEC_WORKERS = 20

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
LOGS_DIR = Path(
    os.environ.get("ATTDEF_LOGS_DIR") or str(BASE_DIR / "logs")
)
DATA_DIR = Path(
    os.environ.get("ATTDEF_DATA_DIR") or str(BASE_DIR / "data")
)
# An empty string must mean "unset": Path("") is Path("."), which would
# scatter state files into the current directory.
SUBMITTED_FILE = DATA_DIR / "submitted.json"
QUEUE_FILE = DATA_DIR / "queue.json"
SUBMISSION_LOG = LOGS_DIR / "submissions.log"
