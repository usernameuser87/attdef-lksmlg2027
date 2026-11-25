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

Response shapes the parser understands. The REAL scoreboard format
(verified live 2026-11-24 against the competition endpoint) is a
JSON array of {"flag": ..., "msg": ...} items — there is NO "status"
field, the verdict lives inside the message text:

  * [{"flag": "LKS{...}",
      "msg": "[LKS{...}] Flag accepted! Earned 75.90 flag points!"}]
  * [{"flag": "LKS{...}",
      "msg": "[LKS{...}] Flag is invalid or too old."}]

Note the scoreboard lumps "invalid" and "too old" into one message;
both are terminal, so that message maps to INVALID. The points in an
accepted message are extracted ("Earned X flag points!") and shown
in the console/log output.

Older/guessed shapes are still accepted, for the mock server and any
other scoreboard:
  * {"accepted": [...], "invalid": [...], "too_old": [...],
     "duplicate": [...]}
  * {"results": [{"flag": "...", "status": "accepted"}, ...]}
  * [{"flag": "...", "status": "accepted"}, ...]
  * {"flags": {"LKS{...}": "accepted", ...}}
Anything else is treated as "unknown" -> the flags stay queued.
"""

import json
import os
import re
import urllib.error
import urllib.request
from http.client import HTTPException
from pathlib import Path

import config
from core.net import direct_opener

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


_MSG_POINTS_RE = re.compile(
    r"Earned\s+([0-9]+(?:\.[0-9]+)?)\s+flag points", re.IGNORECASE
)


def _verdict_from_msg(msg) -> str:
    """Verdict from a scoreboard message string (real format)."""
    if not msg:
        return UNKNOWN
    text = str(msg).lower()
    if "flag accepted" in text or "accepted!" in text:
        return ACCEPTED
    # The real scoreboard lumps invalid and too-old into one message;
    # both are terminal, so either mapping lands in "rejected".
    if "invalid or too old" in text:
        return INVALID
    if "too old" in text or "expired" in text:
        return TOO_OLD
    if "duplicate" in text or "already submitted" in text:
        return DUPLICATE
    if "invalid" in text:
        return INVALID
    return UNKNOWN


def _points_from_msg(msg):
    """Points earned, from 'Earned 75.90 flag points!' — else None."""
    if not msg:
        return None
    match = _MSG_POINTS_RE.search(str(msg))
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _parse_response(body: bytes, sent: list[str]):
    """Map every sent flag to a verdict.

    Returns (verdicts, details):
      verdicts: {flag: canonical verdict}
      details:  {flag: {"points": float | None, "msg": str | None}}
    Unknown shape -> every verdict UNKNOWN (flags stay queued).
    """
    verdicts = {flag: UNKNOWN for flag in sent}
    details = {flag: {"points": None, "msg": None} for flag in sent}
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except (ValueError, UnicodeDecodeError):
        return verdicts, details
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
            return verdicts, details
        # Shape 2: {"results": [{"flag":..., "status":...}, ...]}
        results = data.get("results")
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict):
                    flag = item.get("flag")
                    if flag in verdicts:
                        verdicts[str(flag)] = _normalise_status(item.get("status"))
            return verdicts, details
        # Shape 3: {"flags": {"LKS{...}": "accepted", ...}}
        flags_map = data.get("flags")
        if isinstance(flags_map, dict):
            for flag, status in flags_map.items():
                if flag in verdicts:
                    verdicts[str(flag)] = _normalise_status(status)
            return verdicts, details
    elif isinstance(data, list):
        # Shape 4 (REAL scoreboard): [{"flag":..., "msg":...}, ...]
        # and the guessed variant [{"flag":..., "status":...}, ...].
        for item in data:
            if not isinstance(item, dict):
                continue
            flag = item.get("flag")
            if flag not in verdicts:
                continue
            flag = str(flag)
            msg = item.get("msg", item.get("message"))
            if item.get("status") is not None:
                verdicts[flag] = _normalise_status(item.get("status"))
            elif msg is not None:
                verdicts[flag] = _verdict_from_msg(msg)
                details[flag] = {
                    "points": _points_from_msg(msg),
                    "msg": str(msg),
                }
    return verdicts, details


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
        # Per-flag detail from the most recent submit() call:
        # {flag: {"points": float | None, "msg": str | None}}.
        self.last_details: dict[str, dict] = {}
        self._load()

    # -- persistent state ---------------------------------------------------
    def _load(self) -> None:
        try:
            data = json.loads(config.SUBMITTED_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        # A corrupt submitted.json must never crash startup, and a
        # non-dict payload (e.g. a bare list) must not raise either:
        # keep only the valid flag strings, drop the rest.
        # A non-LIST value (e.g. "accepted": "LKS{ABC}") must also be
        # ignored — iterating a string would shred it into single
        # characters and the flag would be submitted again forever.
        def _flag_set(value):
            if not isinstance(value, list):
                return set()
            return {str(f) for f in value if isinstance(f, str)}

        if isinstance(data, dict):
            self.accepted = _flag_set(data.get("accepted"))
            self.rejected = _flag_set(data.get("rejected"))
        else:
            self.accepted, self.rejected = set(), set()
        try:
            data = json.loads(config.QUEUE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        # Per-item tolerance: ONE bad entry (e.g. "attempts": "abc")
        # used to raise inside the list comprehension and wipe the
        # WHOLE queue — every queued flag lost, even the good ones.
        # Now bad entries are skipped and the rest survive.
        self.queue = []
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict) or not item.get("flag"):
                    continue
                try:
                    attempts = int(item.get("attempts", 0))
                except (TypeError, ValueError):
                    attempts = 0
                self.queue.append(
                    {"flag": str(item["flag"]), "attempts": attempts}
                )

    def _save(self) -> None:
        # A state file that cannot be written (disk full, permissions,
        # a directory in the way) must not kill the round: the
        # in-memory state is still correct for this process, and the
        # flags were already sent or queued. Warn (the warning itself
        # goes through the tolerant submission log) and keep going;
        # on restart the state may be stale, which only costs a
        # re-submission that the scoreboard answers DUPLICATE.
        try:
            _atomic_write_json(
                config.SUBMITTED_FILE,
                {"accepted": sorted(self.accepted), "rejected": sorted(self.rejected)},
            )
            _atomic_write_json(config.QUEUE_FILE, self.queue)
        except OSError as exc:
            self._log(f"SUBMIT state save failed ({exc}); state kept in memory only")

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

        verdicts, details = self._send(batch)
        self.last_details = details
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
            points = details.get(flag, {}).get("points")
            suffix = f" (+{points:.2f} pts)" if points is not None else ""
            self._log(f"SUBMIT {flag} -> {verdict}{suffix}")
        self._save()
        return verdicts

    # -- transport ----------------------------------------------------------
    def _send(self, batch: list[str]):
        body = json.dumps(batch).encode("utf-8")
        try:
            # The Request construction is INSIDE the try on purpose: a
            # malformed SUBMIT_URL (no scheme, a space in the host, ...)
            # raises ValueError / InvalidURL here, and if that escaped
            # _send, submit() would raise too — the round would fail
            # AND the flags would never be queued, so a rotated flag
            # would be lost forever. Inside the try it is just a
            # transport error: flags stay queued and are retried.
            req = urllib.request.Request(
                config.SUBMIT_URL,
                data=body,
                method="PUT",
                headers={
                    "X-Team-Token": config.TEAM_TOKEN,
                    "Content-Type": "application/json",
                },
            )
            # Direct connection — never through a proxy (see core/net.py).
            with direct_opener().open(req, timeout=config.SUBMIT_TIMEOUT) as resp:
                return _parse_response(resp.read(), batch)
        except urllib.error.HTTPError as exc:
            # The server answered but not 2xx: the body may still carry
            # per-flag verdicts. If it does not, the whole request
            # failed -> ERROR (not "unknown": a 4xx/5xx is a failure).
            try:
                verdicts, details = _parse_response(exc.read(), batch)
            except Exception:
                verdicts = {flag: UNKNOWN for flag in batch}
                details = {flag: {"points": None, "msg": None} for flag in batch}
            if all(v == UNKNOWN for v in verdicts.values()):
                return (
                    {flag: ERROR for flag in batch},
                    {flag: {"points": None, "msg": None} for flag in batch},
                )
            return verdicts, details
        except (urllib.error.URLError, OSError, TimeoutError, ValueError,
                HTTPException) as exc:
            # HTTPException matters: http.client.InvalidURL (a URL with
            # a space or control character in the host) is NOT a
            # ValueError subclass, so without this it escapes _send,
            # fails the round, and the flags are never queued.
            self._log(f"SUBMIT transport error: {exc}")
            return (
                {flag: ERROR for flag in batch},
                {flag: {"points": None, "msg": None} for flag in batch},
            )

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
            if item["attempts"] == config.SUBMIT_MAX_RETRIES:
                # Log once, when the threshold is crossed — not every
                # round afterwards, or the log fills with one line per
                # queued flag per round during a long outage.
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
