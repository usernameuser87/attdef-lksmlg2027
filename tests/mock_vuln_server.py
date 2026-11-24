#!/usr/bin/env python3
"""TEST ONLY — mock vulnerable service for the ATTDEF test suite.

Binds 127.0.0.1 only. Simulates the three example challenges:

  GET /health              -> 200 "OK"
  GET /calc?expr=...       -> command injection: an expr containing
                              "secret"/"cat" leaks the current flag
                              inside an HTML page.
  GET /page?file=...       -> LFI: a file containing "flag" leaks it.
  GET /api/debug           -> unauthenticated debug endpoint, JSON
                              with the flag.

The flag ROTATES every MOCK_ROTATE_SECONDS (default 8) and alternates
between LKS{...} and LKSMLG2027{...} so both parser formats are
exercised. Every flag actually served is appended to
MOCK_SERVED_LOG (JSON lines) so the test can prove no flag was lost.
"""

import hashlib
import json
import os
import random
import string
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("MOCK_VULN_PORT", "18080"))
ROTATE = float(os.environ.get("MOCK_ROTATE_SECONDS", "8"))
SERVED_LOG = os.environ.get("MOCK_SERVED_LOG", "tests/data/served.jsonl")

_START = time.time()
_lock = threading.Lock()
# Random per-process salt: within one run the flag is deterministic
# per rotation window (so dedupe is testable), but a server restart
# produces different flags (so phase 2 is not polluted by phase 1's
# already-accepted flags).
_SALT = "".join(random.choices(string.ascii_uppercase, k=4))


def current_flag() -> str:
    """One deterministic flag per rotation window, so the test can prove
    the framework deduplicates a flag found by several challenges in
    the same round and never resubmits an already-accepted flag."""
    idx = int((time.time() - _START) / ROTATE)
    fmt = "LKS" if idx % 2 == 0 else "LKSMLG2027"
    suffix = hashlib.md5(f"window-{idx}".encode()).hexdigest()[:6].upper()
    return f"{fmt}{{TEST{idx:02d}_{_SALT}{suffix}}}"


def log_served(flag: str) -> None:
    with _lock:
        with open(SERVED_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "flag": flag}) + "\n")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def do_GET(self):  # noqa: N802 - stdlib name
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path == "/health":
            return self._send(200, "OK", "text/plain")
        if parsed.path == "/calc":
            expr = qs.get("expr", [""])[0]
            if "secret" in expr or "cat" in expr:
                flag = current_flag()
                log_served(flag)
                body = (
                    "<html><head><title>Calculator</title></head><body>"
                    f"<div>result: {flag}</div></body></html>"
                )
                return self._send(200, body)
            return self._send(
                200, "<html><body><div>result: 2</div></body></html>"
            )
        if parsed.path == "/page":
            fname = qs.get("file", [""])[0]
            if "flag" in fname:
                flag = current_flag()
                log_served(flag)
                return self._send(200, f"flag file contents:\n{flag}\n", "text/plain")
            return self._send(404, "not found", "text/plain")
        if parsed.path == "/api/debug":
            flag = current_flag()
            log_served(flag)
            return self._send(
                200,
                json.dumps({"debug": True, "flag": flag}),
                "application/json",
            )
        return self._send(404, "not found", "text/plain")

    def _send(self, code, body, ctype="text/html"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    os.makedirs(os.path.dirname(SERVED_LOG) or ".", exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[mock-vuln] listening on 127.0.0.1:{PORT} "
          f"(rotate every {ROTATE:g}s)", flush=True)
    server.serve_forever()
