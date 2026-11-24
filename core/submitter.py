# core/submitter.py — flag submission with a safe queue.
"""
Reliability rules:
  * The team token comes from .env only (config.TEAM_TOKEN). It is
    never hardcoded and never written to any log.
  * Never submit an empty string or a duplicate (inside one batch,
    or a flag that already has a terminal verdict).
  * HTTP 200 does NOT mean "all accepted". Every flag's verdict is
    read from the response body, per flag.
  * A flag with a terminal verdict (accepted / invalid / too_old /
    duplicate) is recorded on disk and never submitted again.
  * A flag whose submission failed (network error, HTTP 5xx, or an
    unparsable response) goes into a persistent queue
    (data/queue.json) and is retried in later rounds. Flags are
    never lost because a submission failed.
  * All state files are written atomically (temp file + os.replace).

Response shapes the parser understands (the exact scoreboard format
is not documented, so several common shapes are accepted):
  * {"accepted": [...], "invalid": [...], "too_old": [...],
     "duplicate": [...]}
  * {"results": [{"flag": "...", "status": "accepted"}, ...]}
  * [{"flag": "...", "status": "accepted"}, ...]
  * {"flags": {"LKS{...}": "accepted", ...}}
Anything else is treated as "unknown" -> the flags stay queued.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import config

# Canonical verdicts.
ACCEPTED = "accepted"
INVALID = "invalid"
TOO_OLD = "too_old"
DUPLICATE = "duplicate"
ERROR = "error"
UNKNOWN = "unknown"

TERMINAL = {ACCEPTED, INVALID, TOO_OLD, DUPLICATE}

# Words the scoreboard may use -> canonical verdict.
_STATUS_ALIASES = {
    "accepted": ACCEPTED,
    "accept": ACCEPTED,
    "ok": ACCEPTED,
    "valid": ACCEPTED,
    "invalid": INVALID,
    "rejected": INVALID,
    "wrong": INVALID,
    "bad": INVALID,
    "too_old": TOO_OLD,
    "too old": TOO_OLD,
    "expired": TOO_OLD,
    "old": TOO_OLD,
    "duplicate": DUPLICATE,
    "duplicated": DUPLICATE,
    "already_submitted": DUPLICATE,
    "already submitted": DUPLICATE,
    "already": DUPLICATE,
    "error": ERROR,
    "failed": ERROR,
}


def _normalise_status(raw) -> str:
    if raw is None:
        return UNKNOWN
    key = str(raw).strip().lower()
    return _STATUS_ALIASES.get(key, UNKNOWN)


def _parse_response(body: bytes, sent: list[str]) -> dict[str, str]:
    """Map every sent flag to a verdict. Unknown shape -> all UNKNOWN."""
    verdicts = {flag: UNKNOWN for flag in sent}
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except (ValueError, UnicodeDecodeError):
        return verdicts
    if isinstance(data, dict):
        # Shape 1: {"accepted": [...], "invalid": [...], ...}
        hit = False
        for key, verdict in (
            ("accepted", ACCEPTED),
            ("invalid", INVALID),
            ("too_old", TOO_OLD),
            ("duplicate", DUPLICATE),
            ("error", ERROR),
        ):
            values = data.get(key)
            if isinstance(values, list):
                hit = True
                for flag in values:
                    if flag in verdicts:
                        verdicts[str(flag)] = verdict
        if hit:
            return verdicts
        # Shape 2: {"results": [{"flag":..., "status":...}, ...]}
        results = data.get("results")
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict):
                    flag = item.get("flag")
                    if flag in verdicts:
                        verdicts[str(flag)] = _normalise_status(item.get("status"))
            return verdicts
        # Shape 3: {"flags": {"LKS{...}": "accepted", ...}}
        flags_map = data.get("flags")
        if isinstance(flags_map, dict):
            for flag, status in flags_map.items():
                if flag in verdicts:
                    verdicts[str(flag)] = _normalise_status(status)
            return verdicts
    elif isinstance(data, list):
        # Shape 4: [{"flag":..., "status":...}, ...]
        for item in data:
            if isinstance(item, dict):
                flag = item.get("flag")
                if flag in verdicts:
                    verdicts[str(flag)] = _normalise_status(item.get("status"))
    return verdicts


def _atomic_write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class Submitter:
    def __init__(self, logger=None):
        self.logger = logger
        self.accepted: set[str] = set()
        self.rejected: set[str] = set()  # terminal non-accepted verdicts
        self.queue: list[dict] = []  # [{"flag": str, "attempts": int}]
        self._load()

    # -- persistent state ---------------------------------------------------
    def _load(self) -> None:
        try:
            data = json.loads(config.SUBMITTED_FILE.read_text(encoding="utf-8"))
            self.accepted = set(data.get("accepted", []))
            self.rejected = set(data.get("rejected", []))
        except (OSError, ValueError):
            self.accepted, self.rejected = set(), set()
        try:
            data = json.loads(config.QUEUE_FILE.read_text(encoding="utf-8"))
            self.queue = [
                {"flag": str(item["flag"]), "attempts": int(item.get("attempts", 0))}
                for item in data
                if isinstance(item, dict) and item.get("flag")
            ]
        except (OSError, ValueError, KeyError, TypeError):
            self.queue = []

    def _save(self) -> None:
        _atomic_write_json(
            config.SUBMITTED_FILE,
            {"accepted": sorted(self.accepted), "rejected": sorted(self.rejected)},
        )
        _atomic_write_json(config.QUEUE_FILE, self.queue)

    # -- public API ---------------------------------------------------------
    def pending_count(self) -> int:
        return len(self.queue)

    def submit(self, candidates: list[str]) -> dict[str, str]:
        """Submit new flags (plus queued retries). Returns {flag: verdict}.

        Flags already accepted/rejected are never sent again.
        """
        # Build one deduplicated batch: queued retries first, then new.
        batch: list[str] = []
        seen: set[str] = set()
        for item in self.queue:
            flag = item["flag"]
            if flag and flag not in self.accepted and flag not in self.rejected:
                if flag not in seen:
                    seen.add(flag)
                    batch.append(flag)
        for flag in candidates:
            flag = (flag or "").strip()
            if not flag:
                continue
            if flag in self.accepted or flag in self.rejected or flag in seen:
                continue
            seen.add(flag)
            batch.append(flag)
        if not batch:
            return {}

        if not config.TEAM_TOKEN:
            self._log("SUBMIT aborted: ATTDEF_TEAM_TOKEN is empty (set it in .env)")
            self._enqueue(batch, reason="no token")
            return {flag: ERROR for flag in batch}

        verdicts = self._send(batch)
        for flag, verdict in verdicts.items():
            if verdict == ACCEPTED:
                self.accepted.add(flag)
                self._drop_from_queue(flag)
            elif verdict in (INVALID, TOO_OLD, DUPLICATE):
                self.rejected.add(flag)
                self._drop_from_queue(flag)
            else:
                # ERROR / UNKNOWN: keep it queued, it is not lost.
                self._enqueue([flag], reason=verdict)
            self._log(f"SUBMIT {flag} -> {verdict}")
        self._save()
        return verdicts

    # -- transport ----------------------------------------------------------
    def _send(self, batch: list[str]) -> dict[str, str]:
        body = json.dumps(batch).encode("utf-8")
        req = urllib.request.Request(
            config.SUBMIT_URL,
            data=body,
            method="PUT",
            headers={
                "X-Team-Token": config.TEAM_TOKEN,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=config.SUBMIT_TIMEOUT) as resp:
                return _parse_response(resp.read(), batch)
        except urllib.error.HTTPError as exc:
            # The server answered but not 2xx: the body may still carry
            # per-flag verdicts. If it does not, the whole request
            # failed -> ERROR (not "unknown": a 4xx/5xx is a failure).
            try:
                verdicts = _parse_response(exc.read(), batch)
            except Exception:
                verdicts = {flag: UNKNOWN for flag in batch}
            if all(v == UNKNOWN for v in verdicts.values()):
                return {flag: ERROR for flag in batch}
            return verdicts
        except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
            self._log(f"SUBMIT transport error: {exc}")
            return {flag: ERROR for flag in batch}

    # -- queue helpers ------------------------------------------------------
    def _enqueue(self, flags: list[str], reason: str = "") -> None:
        queued = {item["flag"]: item for item in self.queue}
        for flag in flags:
            if flag in self.accepted or flag in self.rejected:
                continue
            item = queued.get(flag)
            if item is None:
                item = {"flag": flag, "attempts": 0}
                self.queue.append(item)
                queued[flag] = item
            item["attempts"] += 1
            if item["attempts"] >= config.SUBMIT_MAX_RETRIES:
                self._log(
                    f"SUBMIT {flag} exceeded {config.SUBMIT_MAX_RETRIES} "
                    f"retries ({reason}); kept in queue, will keep retrying"
                )
        self._save()

    def _drop_from_queue(self, flag: str) -> None:
        self.queue = [item for item in self.queue if item["flag"] != flag]

    def _log(self, text: str) -> None:
        if self.logger:
            self.logger.submission(text)
