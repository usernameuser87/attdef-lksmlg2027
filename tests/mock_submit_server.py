#!/usr/bin/env python3
"""TEST ONLY — mock scoreboard (submission API) for the ATTDEF test suite.

Binds 127.0.0.1 only. Mimics PUT /flags:

  * Header X-Team-Token must equal MOCK_SUBMIT_TOKEN (default TEST_TOKEN).
  * Body: JSON array of flags.
  * Response: {"accepted": [...], "invalid": [...],
                "too_old": [...], "duplicate": [...]}
    With MOCK_MSG_FORMAT=1 the response instead matches the REAL
    scoreboard format (verified live 2026-11-24):
    [{"flag": "...",
      "msg": "[...] Flag accepted! Earned 75.5 flag points!"},
     {"flag": "...",
      "msg": "[...] Flag is invalid or too old."}]
    The received log still records the dict verdicts, so the e2e
    test's assertions work in either mode.
  * A flag containing "OLD" is "too_old"; a malformed flag is
    "invalid"; a flag already accepted is "duplicate".
  * With MOCK_FAIL_FIRST=1 the FIRST request returns HTTP 500 without
    recording anything, so the framework must queue and retry.

Every request is appended to MOCK_RECEIVED_LOG (JSON lines) so the
test can prove flags were submitted exactly once and none were lost.
"""

import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("MOCK_SUBMIT_PORT", "18081"))
TOKEN = os.environ.get("MOCK_SUBMIT_TOKEN", "TEST_TOKEN")
RECEIVED_LOG = os.environ.get("MOCK_RECEIVED_LOG", "tests/data/received.jsonl")
FAIL_FIRST = os.environ.get("MOCK_FAIL_FIRST", "0") == "1"
# 1 = answer with the real scoreboard's [{"flag","msg"}] shape.
MSG_FORMAT = os.environ.get("MOCK_MSG_FORMAT", "0") == "1"

_FLAG_RE = re.compile(r"LKSMLG2027\{[^}\s<>]+\}|LKS\{[^}\s<>]+\}")

_seen: set[str] = set()
_lock = threading.Lock()
_requests = 0


def _log(entry: dict) -> None:
    with _lock:
        with open(RECEIVED_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def do_PUT(self):  # noqa: N802 - stdlib name
        global _requests
        if self.path != "/flags":
            return self._send(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        with _lock:
            _requests += 1
            req_no = _requests
        if self.headers.get("X-Team-Token") != TOKEN:
            return self._send(401, {"error": "bad token"})
        if FAIL_FIRST and req_no == 1:
            _log({"ts": time.time(), "status": 500, "flags": [],
                  "result": {"error": "simulated failure"}})
            return self._send(500, {"error": "simulated failure"})
        try:
            flags = json.loads(body.decode("utf-8"))
        except ValueError:
            return self._send(400, {"error": "bad json"})
        if not isinstance(flags, list):
            return self._send(400, {"error": "expected a JSON array"})
        result = {"accepted": [], "invalid": [], "too_old": [], "duplicate": []}
        with _lock:
            for flag in flags:
                if not isinstance(flag, str) or not _FLAG_RE.fullmatch(flag):
                    result["invalid"].append(flag)
                elif "OLD" in flag:
                    result["too_old"].append(flag)
                elif flag in _seen:
                    result["duplicate"].append(flag)
                else:
                    _seen.add(flag)
                    result["accepted"].append(flag)
        _log({"ts": time.time(), "status": 200, "flags": flags, "result": result})
        if MSG_FORMAT:
            # Real scoreboard shape: one {"flag","msg"} per flag.
            items = []
            for flag in flags:
                if flag in result["accepted"]:
                    items.append({"flag": flag,
                                  "msg": f"[{flag}] Flag accepted! "
                                         f"Earned 75.5 flag points!"})
                elif flag in result["duplicate"]:
                    items.append({"flag": flag,
                                  "msg": f"[{flag}] Flag already submitted."})
                else:
                    items.append({"flag": flag,
                                  "msg": f"[{flag}] Flag is invalid or too old."})
            return self._send(200, items)
        return self._send(200, result)

    def _send(self, code, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    os.makedirs(os.path.dirname(RECEIVED_LOG) or ".", exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[mock-submit] listening on 127.0.0.1:{PORT} "
          f"(fail_first={FAIL_FIRST})", flush=True)
    server.serve_forever()
