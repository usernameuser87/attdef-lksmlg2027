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
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (stdlib only). Never overwrites real env vars."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
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


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


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
TICK_SECONDS = _env_float("ATTDEF_TICK", 180)
# 0 = run forever. > 0 = stop after that many executed rounds (testing).
MAX_ROUNDS = _env_int("ATTDEF_MAX_ROUNDS", 0)

# ---------------------------------------------------------------------------
# Submission API (official scoreboard)
# ---------------------------------------------------------------------------
SUBMIT_URL = os.environ.get(
    "ATTDEF_SUBMIT_URL", "http://103.145.226.89:8080/flags"
)
TEAM_TOKEN = os.environ.get("ATTDEF_TEAM_TOKEN", "")
SUBMIT_TIMEOUT = _env_float("ATTDEF_SUBMIT_TIMEOUT", 15)
# Max times a queued flag is retried before it is moved to the dead queue.
SUBMIT_MAX_RETRIES = _env_int("ATTDEF_SUBMIT_MAX_RETRIES", 10)

# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
CHALLENGES_DIR = Path(
    os.environ.get("ATTDEF_CHALLENGES_DIR", str(BASE_DIR / "challenges"))
)
# Default per-exploit timeout (seconds) when a challenge has no timeout.
DEFAULT_EXPLOIT_TIMEOUT = _env_float("ATTDEF_EXPLOIT_TIMEOUT", 30)
# Default health-check timeout (seconds).
DEFAULT_HEALTH_TIMEOUT = _env_float("ATTDEF_HEALTH_TIMEOUT", 3)
# Parallel workers for health checks and exploit runs.
SCAN_WORKERS = _env_int("ATTDEF_SCAN_WORKERS", 20)
EXEC_WORKERS = _env_int("ATTDEF_EXEC_WORKERS", 20)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
LOGS_DIR = Path(os.environ.get("ATTDEF_LOGS_DIR", str(BASE_DIR / "logs")))
DATA_DIR = Path(os.environ.get("ATTDEF_DATA_DIR", str(BASE_DIR / "data")))
SUBMITTED_FILE = DATA_DIR / "submitted.json"
QUEUE_FILE = DATA_DIR / "queue.json"
SUBMISSION_LOG = LOGS_DIR / "submissions.log"
