# core/loader.py — challenge discovery.
"""
A challenge is a folder under CHALLENGES_DIR containing a config.json:

    {
      "name": "Calculator",
      "port": 8081,
      "protocol": "http",          // "http" | "https" | "tcp"
      "health_path": "/health",    // HTTP only; "" = root
      "timeout": 30,               // per-exploit timeout, seconds
      "script": "exploit.sh",      // bash script in the same folder
      "enabled": true
    }

Adding a challenge = create a folder + config.json + exploit.sh.
No other file has to change. Invalid or disabled folders are skipped
with a warning, never a crash.
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path

import config


def _as_bool(value, default: bool = True) -> bool:
    """Parse an "enabled" value. A bare bool("false") is True in
    Python, so a config.json with "enabled": "false" used to ENABLE
    the challenge — the exact opposite of what the user asked.
    Strings are parsed case-insensitively; anything unrecognised
    falls back to the default."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1", "yes", "on"):
            return True
        if text in ("false", "0", "no", "off"):
            return False
    return default


@dataclass
class Challenge:
    name: str
    port: int
    protocol: str  # "http" | "https" | "tcp"
    health_path: str
    timeout: float
    script: Path
    enabled: bool
    folder: Path
    # Platform challenge id (PLAYIT mode): the "api_id" in config.json
    # maps this folder to a challenge in GET /api/v2/services. None =
    # not mapped (the challenge is skipped in platform mode).
    api_id: str | None = None

    @property
    def slug(self) -> str:
        return self.folder.name


def load_challenges(challenges_dir: Path | None = None) -> list[Challenge]:
    # Resolve to an absolute path: the runner executes each script with
    # cwd=challenge.folder, so a relative script path would not resolve.
    # (A relative ATTDEF_CHALLENGES_DIR used to make every exploit fail
    # with "No such file or directory", exit 127, and zero flags.)
    if challenges_dir is not None:
        base = Path(challenges_dir).resolve()
    else:
        base = config.CHALLENGES_DIR
    found: list[Challenge] = []
    if not base.is_dir():
        return found
    for folder in sorted(base.iterdir()):
        if not folder.is_dir():
            continue
        cfg_path = folder / "config.json"
        if not cfg_path.exists():
            continue
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            print(f"[WARN] {folder.name}: config.json unreadable ({exc}); skipped")
            continue
        try:
            name = str(raw["name"])
            port = int(raw["port"])
        except (KeyError, TypeError, ValueError) as exc:
            print(f"[WARN] {folder.name}: missing/invalid name or port ({exc}); skipped")
            continue
        # A bad timeout must never crash the whole framework at startup
        # — fall back to the default and warn. "Bad" covers non-numeric
        # values AND non-positive / non-finite ones: a timeout of -5
        # makes every exploit for that challenge die instantly
        # (TimeoutExpired at once), and a timeout of nan makes
        # subprocess.run raise ValueError, which poisons the whole
        # round (run_one only catches TimeoutExpired and OSError).
        try:
            timeout = float(raw.get("timeout", config.DEFAULT_EXPLOIT_TIMEOUT))
        except (TypeError, ValueError):
            print(f"[WARN] {folder.name}: invalid timeout "
                  f"{raw.get('timeout')!r}; using default "
                  f"{config.DEFAULT_EXPLOIT_TIMEOUT:g}s")
            timeout = config.DEFAULT_EXPLOIT_TIMEOUT
        if not math.isfinite(timeout) or timeout <= 0:
            print(f"[WARN] {folder.name}: invalid timeout "
                  f"{raw.get('timeout')!r}; using default "
                  f"{config.DEFAULT_EXPLOIT_TIMEOUT:g}s")
            timeout = config.DEFAULT_EXPLOIT_TIMEOUT
        protocol = str(raw.get("protocol", "http")).lower()
        if protocol not in ("http", "https", "tcp"):
            print(f"[WARN] {folder.name}: unknown protocol {protocol!r}; skipped")
            continue
        # A health_path without a leading slash ("health" instead of
        # "/health") used to build "http://IP:PORThealth" — an invalid
        # URL that crashed the health check and wrongly marked the
        # pair offline. Normalise it here.
        health_path = str(raw.get("health_path", ""))
        if health_path and not health_path.startswith("/"):
            health_path = "/" + health_path
        script_name = str(raw.get("script", "exploit.sh"))
        script = folder / script_name
        if not script.is_file():
            print(f"[WARN] {folder.name}: script {script_name!r} not found "
                  f"or not a file; skipped")
            continue
        api_id = raw.get("api_id")
        found.append(
            Challenge(
                name=name,
                port=port,
                protocol=protocol,
                health_path=health_path,
                timeout=timeout,
                script=script,
                enabled=_as_bool(raw.get("enabled", True)),
                folder=folder,
                api_id=None if api_id is None else str(api_id),
            )
        )
    return found
