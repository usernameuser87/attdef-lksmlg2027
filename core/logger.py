# core/logger.py — console output + per-round log files.
"""
Output rules:
  * Console: short, one line per event, exactly the format in the spec.
    Never print a full HTML response.
  * Disk: one log file per round (logs/round-NNN-YYYYMMDD-HHMMSS.log)
    with full detail, plus logs/submissions.log (append) for every
    submission attempt and its per-flag result.
"""

import sys
from datetime import datetime
from pathlib import Path

import config


class Logger:
    def __init__(self, logs_dir: Path | None = None):
        self.logs_dir = Path(logs_dir) if logs_dir else config.LOGS_DIR
        # A log directory that cannot be created must never crash the
        # framework at startup: logging is a side channel, the rounds
        # are the work. Warn once and keep going console-only;
        # open_round retries the mkdir every round, so a transient
        # failure (e.g. the dir was deleted) can still recover.
        self._disk_ok = True
        self._open_failed_warned = False
        try:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._disk_ok = False
            print(f"[WARN] cannot create log dir {self.logs_dir} ({exc})"
                  " — continuing console-only", flush=True)
        self._round_file = None

    # -- round lifecycle ----------------------------------------------------
    def open_round(self, round_no: int) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.logs_dir / f"round-{round_no:03d}-{stamp}.log"
        try:
            # Recreate the dir if it vanished after __init__ (deleted,
            # disk hiccup): without this, open() raises FileNotFoundError
            # and the WHOLE round fails before any exploit runs, even
            # though logging is not the work.
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            self._round_file = open(path, "a", encoding="utf-8")
            self._disk_ok = True
            self._write(f"[{datetime.now().isoformat()}] ROUND {round_no} START\n")
        except OSError as exc:
            # Logging failed — the round must still run. Console output
            # keeps working; detail() becomes a no-op while the file
            # is unavailable. Warn once, not once per round.
            self._round_file = None
            self._disk_ok = False
            if not self._open_failed_warned:
                self._open_failed_warned = True
                print(f"[WARN] cannot write round log {path} ({exc})"
                      " — continuing console-only", flush=True)
        return path

    def close_round(self, round_no: int) -> None:
        if self._round_file:
            self._write(f"[{datetime.now().isoformat()}] ROUND {round_no} END\n")
            self._round_file.close()
            self._round_file = None

    # -- low level ----------------------------------------------------------
    def _write(self, text: str) -> None:
        if self._round_file:
            try:
                self._round_file.write(text)
                self._round_file.flush()
            except (OSError, ValueError):
                pass

    def line(self, text: str) -> None:
        """One console line + the same line in the round log file."""
        print(text, flush=True)
        self._write(text + "\n")

    def detail(self, text: str) -> None:
        """Disk only (debug detail that must not flood the console)."""
        self._write(text + "\n")

    # -- submission history -------------------------------------------------
    def submission(self, text: str) -> None:
        """Append one line to logs/submissions.log (never the console)."""
        try:
            with open(config.SUBMISSION_LOG, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().isoformat()}] {text}\n")
        except OSError:
            pass

    # -- fatal --------------------------------------------------------------
    @staticmethod
    def fatal(text: str) -> None:
        print(f"[FATAL] {text}", file=sys.stderr, flush=True)
