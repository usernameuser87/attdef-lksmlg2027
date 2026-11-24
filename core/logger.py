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
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._round_file = None

    # -- round lifecycle ----------------------------------------------------
    def open_round(self, round_no: int) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.logs_dir / f"round-{round_no:03d}-{stamp}.log"
        self._round_file = open(path, "a", encoding="utf-8")
        self._write(f"[{datetime.now().isoformat()}] ROUND {round_no} START\n")
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
