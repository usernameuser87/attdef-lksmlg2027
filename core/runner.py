# core/runner.py — execute Bash exploits.
"""
Rules, exactly as specified:
  * Run as:  bash script.sh <IP> <PORT>   (IP = $1, PORT = $2)
  * The script is used as-is. No source changes, no format assumptions.
  * stdout and stderr are captured SEPARATELY.
  * A nonzero exit code does NOT mean "no flag" — flags are parsed from
    stdout regardless of the exit code.
  * Every process has its own hard timeout; on timeout the process is
    killed and whatever stdout it produced so far is still parsed.
  * One failing process never stops the others, and outputs are never
    mixed: each result is stored per (target, challenge) and only
    logged by the caller afterwards.
"""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import config
from core.loader import Challenge


@dataclass
class ExecResult:
    target_name: str
    target_ip: str
    challenge: Challenge
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    timed_out: bool = False
    error: str = ""


def run_one(target: dict, challenge: Challenge) -> ExecResult:
    result = ExecResult(
        target_name=target["name"], target_ip=target["ip"], challenge=challenge
    )
    cmd = ["bash", str(challenge.script), target["ip"], str(challenge.port)]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=challenge.timeout,
            cwd=str(challenge.folder),
        )
        result.stdout = proc.stdout or ""
        result.stderr = proc.stderr or ""
        result.returncode = proc.returncode
    except subprocess.TimeoutExpired as exc:
        # Keep partial output: a slow exploit may have printed the flag
        # before the timeout hit.
        # TimeoutExpired carries partial stdout as .stdout on Python
        # 3.11+ and as .output on 3.8-3.10 — read whichever exists.
        def _partial(value):
            if value is None:
                return ""
            if isinstance(value, (bytes, bytearray)):
                return value.decode("utf-8", "replace")
            return str(value)

        result.timed_out = True
        result.stdout = _partial(
            getattr(exc, "stdout", None) or getattr(exc, "output", None)
        )
        result.stderr = _partial(getattr(exc, "stderr", None))
        result.returncode = None
    except OSError as exc:
        result.error = str(exc)
    return result


def run_all(pairs) -> list[ExecResult]:
    """pairs: list of (target_dict, Challenge). Runs them concurrently."""
    if not pairs:
        return []
    with ThreadPoolExecutor(max_workers=config.EXEC_WORKERS) as pool:
        return list(pool.map(lambda p: run_one(p[0], p[1]), pairs))
