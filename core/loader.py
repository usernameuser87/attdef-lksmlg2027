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
from dataclasses import dataclass
from pathlib import Path

import config


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
        # — fall back to the default and warn.
        try:
            timeout = float(raw.get("timeout", config.DEFAULT_EXPLOIT_TIMEOUT))
        except (TypeError, ValueError):
            print(f"[WARN] {folder.name}: invalid timeout "
                  f"{raw.get('timeout')!r}; using default "
                  f"{config.DEFAULT_EXPLOIT_TIMEOUT:g}s")
            timeout = config.DEFAULT_EXPLOIT_TIMEOUT
        protocol = str(raw.get("protocol", "http")).lower()
        if protocol not in ("http", "https", "tcp"):
            print(f"[WARN] {folder.name}: unknown protocol {protocol!r}; skipped")
            continue
        script_name = str(raw.get("script", "exploit.sh"))
        script = folder / script_name
        if not script.exists():
            print(f"[WARN] {folder.name}: script {script_name!r} not found; skipped")
            continue
        found.append(
            Challenge(
                name=name,
                port=port,
                protocol=protocol,
                health_path=str(raw.get("health_path", "")),
                timeout=timeout,
                script=script,
                enabled=bool(raw.get("enabled", True)),
                folder=folder,
            )
        )
    return found
