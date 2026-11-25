#!/usr/bin/env python3
"""Unit tests — parser + scheduler. No servers, no sleeping (fake clock).

Run:  python3 tests/test_units.py
Exit code 0 = all pass.
"""

import json
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from core.parser import clean, extract_flags  # noqa: E402
from core.scheduler import Scheduler, next_round_index  # noqa: E402
from core.submitter import Submitter, _parse_response  # noqa: E402

FAILURES = []


def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        print(f"         got:  {got!r}\n         want: {want!r}")
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
print("[parser]")
check("html-wrapped flag",
      extract_flags("<div>LKS{ABC123}</div>"), ["LKS{ABC123}"])
check("LKSMLG2027 format",
      extract_flags("here: LKSMLG2027{hello_world-1} end"),
      ["LKSMLG2027{hello_world-1}"])
check("both formats, longer first",
      extract_flags("LKSMLG2027{AAA} and LKS{BBB}"),
      ["LKSMLG2027{AAA}", "LKS{BBB}"])
check("two flags in adjacent tags are not fused",
      extract_flags("<div>LKS{A}</div><b>LKS{B}</b>"),
      ["LKS{A}", "LKS{B}"])
check("dedupe, order preserved",
      extract_flags("LKS{X} foo LKS{X} bar LKS{Y} LKS{X}"),
      ["LKS{X}", "LKS{Y}"])
check("no flag", extract_flags("nothing here\njust text"), [])
check("empty input", extract_flags(""), [])
check("flag body cannot cross a tag",
      extract_flags("<div>LKS{NOPE</div>}"), [])
check("ANSI colours stripped",
      extract_flags("\x1b[32mLKS{GREEN}\x1b[0m"), ["LKS{GREEN}"])
check("curl progress meter stripped",
      extract_flags("  % Total    % Received % Xferd\n"
                    "100  1234  100  1234    0     0  12345      0 --:--:-- --:--:-- --:--:-- 12345\n"
                    "LKS{AFTER}"),
      ["LKS{AFTER}"])
check("carriage returns in progress output",
      extract_flags("  0% foo\r 50% bar\rLKS{CR}"), ["LKS{CR}"])
check("whitespace around flag",
      extract_flags("   \n\t LKS{WS} \n  "), ["LKS{WS}"])
check("flag with punctuation inside",
      extract_flags("LKS{a-b_c.d:e!f}"), ["LKS{a-b_c.d:e!f}"])
check("clean() keeps text, drops tags",
      clean("<p>hello</p> world"), "hello world")
check("flag survives a line starting with a percentage",
      extract_flags("50% done LKS{PERCENT}"), ["LKS{PERCENT}"])
check("real curl meter rows are still stripped",
      extract_flags("  % Total    % Received % Xferd\n"
                    "100  1234  100  1234    0     0  12345      0 "
                    "--:--:-- --:--:-- --:--:-- 12345\n"
                    "LKS{METER}"),
      ["LKS{METER}"])

# ---------------------------------------------------------------------------
# Submitter response parsing — incl. the REAL scoreboard {"flag","msg"}
# shape (verified live 2026-11-24). The old code only read a "status"
# field, which the real API never sends, so every flag came back
# UNKNOWN and stayed queued forever.
# ---------------------------------------------------------------------------
print("[submitter: _parse_response]")

_real_body = json.dumps([
    {"flag": "LKS{AAA}",
     "msg": "[LKS{AAA}] Flag accepted! Earned 75.9046639493366 flag points!"},
    {"flag": "LKS{BBB}",
     "msg": "[LKS{BBB}] Flag is invalid or too old."},
]).encode()
_v, _d = _parse_response(_real_body, ["LKS{AAA}", "LKS{BBB}"])
check("real msg shape: accepted",
      _v["LKS{AAA}"], "accepted")
check("real msg shape: points extracted",
      _d["LKS{AAA}"]["points"], 75.9046639493366)
check("real msg shape: invalid-or-too-old -> invalid",
      _v["LKS{BBB}"], "invalid")
check("real msg shape: no points on reject",
      _d["LKS{BBB}"]["points"], None)

_status_body = json.dumps([
    {"flag": "LKS{CCC}", "status": "accepted"},
]).encode()
_v, _d = _parse_response(_status_body, ["LKS{CCC}"])
check("status shape still works",
      _v["LKS{CCC}"], "accepted")

_dict_body = json.dumps({
    "accepted": ["LKS{DDD}"], "invalid": [], "too_old": [], "duplicate": [],
}).encode()
_v, _d = _parse_response(_dict_body, ["LKS{DDD}"])
check("dict shape still works",
      _v["LKS{DDD}"], "accepted")

_garbage_body = b"not json at all"
_v, _d = _parse_response(_garbage_body, ["LKS{EEE}"])
check("unparsable body -> unknown (stays queued)",
      _v["LKS{EEE}"], "unknown")

# ---------------------------------------------------------------------------
# Direct opener (core/net.py): never through a proxy.
# With a dead proxy configured and the target NOT in no_proxy, plain
# urlopen must fail while the direct opener succeeds. This is the bug
# that made health checks and submissions fail on proxy-configured
# machines (verified 2026-11-24).
# ---------------------------------------------------------------------------
print("[net: direct opener bypasses proxy]")
import os as _os
import threading as _threading
import urllib.request as _urlreq
from http.server import BaseHTTPRequestHandler as _H, ThreadingHTTPServer as _S

from core.net import direct_opener  # noqa: E402


class _Quiet(_H):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *a):
        pass


_srv = _S(("127.0.0.1", 18098), _Quiet)
_threading.Thread(target=_srv.serve_forever, daemon=True).start()
_saved_env = {k: _os.environ.get(k) for k in
              ("http_proxy", "HTTP_PROXY", "no_proxy", "NO_PROXY")}
_os.environ["http_proxy"] = "http://127.0.0.1:9"  # dead proxy
_os.environ["HTTP_PROXY"] = "http://127.0.0.1:9"
_os.environ.pop("no_proxy", None)
_os.environ.pop("NO_PROXY", None)
try:
    try:
        with _urlreq.urlopen("http://127.0.0.1:18098/", timeout=3) as r:
            _plain_ok = r.status == 200
    except Exception:
        _plain_ok = False
    check("plain urlopen fails through dead proxy", _plain_ok, False)
    try:
        with direct_opener().open("http://127.0.0.1:18098/", timeout=3) as r:
            _direct_ok = r.status == 200 and r.read() == b"OK"
    except Exception:
        _direct_ok = False
    check("direct opener succeeds through dead proxy", _direct_ok, True)
finally:
    for _k, _v in _saved_env.items():
        if _v is None:
            _os.environ.pop(_k, None)
        else:
            _os.environ[_k] = _v
    _srv.shutdown()

# ---------------------------------------------------------------------------
# Runner: a timed-out exploit keeps its partial output (the flag it
# printed before hanging). And the TimeoutExpired handling must work
# on Python 3.8-3.10 too, where .stdout does not exist (only .output).
# ---------------------------------------------------------------------------
print("[runner: timeout keeps partial output]")
import tempfile as _tempfile

from core.loader import Challenge as _Challenge  # noqa: E402
from core.runner import run_one as _run_one  # noqa: E402

_tmp = _tempfile.mkdtemp()
_script = Path(_tmp) / "slow.sh"
_script.write_text("#!/bin/bash\necho 'LKS{TIMEOUTFLAG}'\nsleep 30\n",
                   encoding="utf-8")
_chal = _Challenge(name="Slow", port=1, protocol="tcp", health_path="",
                   timeout=0.5, script=_script, enabled=True,
                   folder=Path(_tmp))
_res = _run_one({"name": "T", "ip": "127.0.0.1"}, _chal)
check("timed_out is True", _res.timed_out, True)
check("partial stdout kept", "LKS{TIMEOUTFLAG}" in _res.stdout, True)

# ---------------------------------------------------------------------------
# Loader: a bad timeout in one challenge must not crash the framework —
# it falls back to the default and warns.
# ---------------------------------------------------------------------------
print("[loader: bad timeout falls back, no crash]")
from core.loader import load_challenges as _load_challenges  # noqa: E402

_bad_dir = Path(_tempfile.mkdtemp())
(_bad_dir / "badtimeout").mkdir()
(_bad_dir / "badtimeout" / "config.json").write_text(
    json.dumps({"name": "Bad", "port": 8081, "protocol": "http",
                "timeout": "not-a-number", "script": "exploit.sh"}),
    encoding="utf-8")
(_bad_dir / "badtimeout" / "exploit.sh").write_text("true\n",
                                                    encoding="utf-8")
(_bad_dir / "nulltimeout").mkdir()
(_bad_dir / "nulltimeout" / "config.json").write_text(
    json.dumps({"name": "Null", "port": 8082, "protocol": "http",
                "timeout": None, "script": "exploit.sh"}),
    encoding="utf-8")
(_bad_dir / "nulltimeout" / "exploit.sh").write_text("true\n",
                                                     encoding="utf-8")
# Non-positive / non-finite timeouts are just as bad as non-numeric
# ones: -5 kills every exploit instantly (TimeoutExpired at once),
# 0 does the same, and nan makes subprocess.run raise ValueError,
# which poisons the whole round. All must fall back to the default.
for _slug, _bad_timeout in (("neg", -5), ("zero", 0),
                            ("nan", "nan"), ("inf", "inf")):
    (_bad_dir / _slug).mkdir()
    (_bad_dir / _slug / "config.json").write_text(
        json.dumps({"name": _slug, "port": 8083, "protocol": "http",
                    "timeout": _bad_timeout, "script": "exploit.sh"}),
        encoding="utf-8")
    (_bad_dir / _slug / "exploit.sh").write_text("true\n", encoding="utf-8")
_loaded = _load_challenges(_bad_dir)
check("all bad-timeout challenges still load", len(_loaded), 6)
check("bad timeout -> default",
      all(c.timeout == 30 for c in _loaded), True)

# A RELATIVE challenges dir must still work: the runner executes each
# script with cwd=challenge.folder, so a relative script path would
# not resolve (exit 127, "No such file or directory", zero flags).
# The loader resolves everything to absolute paths.
print("[loader: relative challenges dir resolves to absolute paths]")
import os as _os2

_rel_parent = Path(_tempfile.mkdtemp())
(_rel_parent / "chals" / "demo").mkdir(parents=True)
(_rel_parent / "chals" / "demo" / "config.json").write_text(
    json.dumps({"name": "Demo", "port": 8081, "protocol": "http",
                "script": "exploit.sh"}), encoding="utf-8")
(_rel_parent / "chals" / "demo" / "exploit.sh").write_text(
    "echo 'LKS{RELATIVE}'\n", encoding="utf-8")
_old_cwd = _os2.getcwd()
try:
    _os2.chdir(_rel_parent)
    _rel_loaded = _load_challenges(Path("chals"))
finally:
    _os2.chdir(_old_cwd)
check("relative dir loads 1 challenge", len(_rel_loaded), 1)
check("script path is absolute",
      _rel_loaded[0].script.is_absolute(), True)
check("script path exists",
      _rel_loaded[0].script.exists(), True)
_res2 = _run_one({"name": "T", "ip": "127.0.0.1"}, _rel_loaded[0])
check("exploit runs from a relative dir",
      "LKS{RELATIVE}" in _res2.stdout, True)

# A health_path without a leading slash ("health") used to build
# "http://IP:PORThealth" — an InvalidURL that crashed check_one and
# wrongly marked the pair offline. The loader normalises it, and the
# scanner now treats any URL error as offline instead of raising.
print("[loader/scanner: health_path without slash]")
_noslash_dir = Path(_tempfile.mkdtemp())
(_noslash_dir / "noslash").mkdir()
(_noslash_dir / "noslash" / "config.json").write_text(
    json.dumps({"name": "NoSlash", "port": 8081, "protocol": "http",
                "health_path": "health", "script": "exploit.sh"}),
    encoding="utf-8")
(_noslash_dir / "noslash" / "exploit.sh").write_text("true\n",
                                                     encoding="utf-8")
_noslash = _load_challenges(_noslash_dir)
check("health_path normalised to /health",
      _noslash[0].health_path, "/health")
from core.scanner import check_one as _check_one  # noqa: E402
_raw = _Challenge(name="Raw", port=18080, protocol="http",
                  health_path="health", timeout=1, script=_script,
                  enabled=True, folder=Path(_tmp))
try:
    _ok = _check_one("127.0.0.1", _raw, timeout=1)
    check("unnormalised health_path does not raise", True, True)
    check("unnormalised health_path -> offline", _ok, False)
except Exception as _e:
    check("unnormalised health_path does not raise", False, True)

# submitted.json with a string instead of a list must not shred the
# flag into single characters.
print("[submitter: corrupt submitted.json]")
import os as _os3

from core.submitter import Submitter as _Submitter  # noqa: E402

_corr = Path(_tempfile.mkdtemp())
(_corr / "submitted.json").write_text(
    json.dumps({"accepted": "LKS{ABC}", "rejected": ["LKS{DEF}"]}),
    encoding="utf-8")
_sub = _Submitter.__new__(_Submitter)
_sub.logger = None
_sub.accepted, _sub.rejected, _sub.queue = set(), set(), []
_sub.last_details = {}
# Point the submitter at the corrupt file by patching config paths.
import config as _cfg  # noqa: E402
_old_sub, _old_q = _cfg.SUBMITTED_FILE, _cfg.QUEUE_FILE
_cfg.SUBMITTED_FILE, _cfg.QUEUE_FILE = (_corr / "submitted.json",
                                        _corr / "queue.json")
try:
    _sub._load()
finally:
    _cfg.SUBMITTED_FILE, _cfg.QUEUE_FILE = _old_sub, _old_q
check("string accepted -> empty set (no single chars)",
      _sub.accepted, set())
check("valid rejected list still loads",
      _sub.rejected, {"LKS{DEF}"})

# An empty ATTDEF_LOGS_DIR / ATTDEF_DATA_DIR must mean "default",
# not Path(".") (which would scatter state files into the cwd).
print("[config: empty LOGS_DIR/DATA_DIR fall back to defaults]")
import subprocess as _sp

_out = _sp.run(
    [sys.executable, "-c",
     "import os; os.environ['ATTDEF_LOGS_DIR']=''; "
     "os.environ['ATTDEF_DATA_DIR']=''; import config; "
     "print(config.LOGS_DIR); print(config.DATA_DIR)"],
    capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
)
_lines = _out.stdout.strip().splitlines()
check("empty LOGS_DIR -> default logs dir",
      _lines[0].endswith("/logs") if _lines else False, True)
check("empty DATA_DIR -> default data dir",
      _lines[1].endswith("/data") if len(_lines) > 1 else False, True)

# Non-finite / non-positive env values must fall back too: TICK=nan
# used to crash the scheduler after round 1 (math.ceil(nan)),
# TICK=inf crashed main() at timedelta(seconds=inf), and a negative
# timeout made every exploit/submission fail silently.
print("[config: non-finite / non-positive env values fall back]")
_out = _sp.run(
    [sys.executable, "-c",
     "import os; os.environ['ATTDEF_TICK']='nan'; "
     "os.environ['ATTDEF_SUBMIT_TIMEOUT']='-5'; "
     "os.environ['ATTDEF_HEALTH_TIMEOUT']='0'; "
     "os.environ['ATTDEF_EXPLOIT_TIMEOUT']='inf'; "
     "import config; print(config.TICK_SECONDS, config.SUBMIT_TIMEOUT, "
     "config.DEFAULT_HEALTH_TIMEOUT, config.DEFAULT_EXPLOIT_TIMEOUT)"],
    capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
)
check("nan/inf/negative/zero env -> defaults 180 15 3 30",
      _out.stdout.strip().split() == ["180", "15", "3", "30"], True)
_out = _sp.run(
    [sys.executable, "-c",
     "import os; os.environ['ATTDEF_TICK']='inf'; "
     "import config; print(config.TICK_SECONDS)"],
    capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
)
check("ATTDEF_TICK=inf -> 180", _out.stdout.strip(), "180")

# ---------------------------------------------------------------------------
# Scheduler (pure function)
# ---------------------------------------------------------------------------
print("[scheduler: next_round_index]")
check("at start -> 0", next_round_index(100.0, 100.0, 5.0), 0)
check("before first slot -> 1", next_round_index(100.0, 103.0, 5.0), 1)
check("exactly on slot -> that slot", next_round_index(100.0, 105.0, 5.0), 1)
check("just past slot -> next", next_round_index(100.0, 105.001, 5.0), 2)
check("overrun 8s, tick 5 -> index 2 (slot 5 skipped)",
      next_round_index(100.0, 108.0, 5.0), 2)
check("overrun 190s, tick 180 -> index 2",
      next_round_index(1000.0, 1190.0, 180.0), 2)
check("tick 180, exactly 180s later -> 1",
      next_round_index(0.0, 180.0, 180.0), 1)


def _raises_value_error(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


# A non-finite tick must fail fast at construction, with a clear
# message — not crash mysteriously after round 1 (nan: math.ceil
# raises; inf: timedelta(seconds=inf) raises in main()).
check("Scheduler(nan) raises ValueError",
      _raises_value_error(lambda: Scheduler(float("nan"))), True)
check("Scheduler(inf) raises ValueError",
      _raises_value_error(lambda: Scheduler(float("inf"))), True)
check("next_round_index with nan tick raises ValueError",
      _raises_value_error(lambda: next_round_index(0.0, 10.0, float("nan"))),
      True)

# ---------------------------------------------------------------------------
# Scheduler class with a fake clock (no real sleeping)
# ---------------------------------------------------------------------------
print("[scheduler: class with fake clock]")


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(round(seconds, 3))
        self.now += seconds


fake = FakeClock()
sch = Scheduler(tick=5.0, clock=fake.clock, sleep=fake.sleep)
sch.anchor()
check("anchor = 1000", sch.start_mono, 1000.0)
check("wait_until(0) sleeps 0", (sch.wait_until(0), fake.slept), (1000.0, []))
sch.wait_until(1)
check("wait_until(1) sleeps 5s", fake.slept, [5.0])
check("clock advanced to 1005", fake.now, 1005.0)
# Simulate round index 0 running long: it started at 1000 and ends
# at 1008 (8s with a 5s tick -> the slot at 1005 is missed).
fake.now = 1008.0
nxt, skipped = sch.advance_after_round(0)
check("overrun: next index 2 (slot 1010)", nxt, 2)
check("overrun: 1 round skipped", skipped, 1)
# Round index 2 runs 1010..1011 (fast). Next must be index 3 at 1015.
sch.wait_until(2)
fake.now = 1011.0
nxt, skipped = sch.advance_after_round(2)
check("fast round: next index 3", nxt, 3)
check("fast round: 0 skipped", skipped, 0)
check("wait to index 3 sleeps 4s (1011 -> 1015)",
      (sch.wait_until(3), fake.slept[-1]), (1015.0, 4.0))

# ---------------------------------------------------------------------------
# Submitter state loading — one bad entry must not wipe the whole queue
# ---------------------------------------------------------------------------
print("[submitter: state loading]")


def _load_submitter(submitted_text, queue_text):
    """Build a Submitter over temp state files; returns it."""
    tmp = Path(tempfile.mkdtemp())
    config.DATA_DIR = tmp
    config.SUBMITTED_FILE = tmp / "submitted.json"
    config.QUEUE_FILE = tmp / "queue.json"
    if submitted_text is not None:
        config.SUBMITTED_FILE.write_text(submitted_text, encoding="utf-8")
    if queue_text is not None:
        config.QUEUE_FILE.write_text(queue_text, encoding="utf-8")
    return Submitter()


sub = _load_submitter(
    None,
    json.dumps([
        {"flag": "LKS{GOOD1}", "attempts": 2},
        {"flag": "LKS{GOOD2}", "attempts": "abc"},  # corrupt value
        {"flag": "LKS{GOOD3}"},                     # no attempts key
        {"no_flag": True},                          # not a flag entry
    ]),
)
check("corrupt attempts value keeps the good flags",
      [i["flag"] for i in sub.queue],
      ["LKS{GOOD1}", "LKS{GOOD2}", "LKS{GOOD3}"])
check("corrupt attempts defaults to 0",
      [i["attempts"] for i in sub.queue], [2, 0, 0])
sub = _load_submitter("[1, 2, 3]", "not json at all")  # non-dict / bad JSON
check("submitted.json as bare list does not crash",
      (sub.accepted, sub.rejected, sub.queue), (set(), set(), []))
sub = _load_submitter(None, json.dumps({"a": 1}))  # queue as dict
check("queue.json as dict loads as empty, no crash", sub.queue, [])

# ---------------------------------------------------------------------------
# Scanner — https with a self-signed cert must read ONLINE, not OFFLINE
# ---------------------------------------------------------------------------
print("[scanner: https self-signed]")
import shutil
import ssl as _ssl
import subprocess as _subprocess
import threading as _threading
from http.server import HTTPServer, SimpleHTTPRequestHandler

from core.loader import Challenge as _Challenge
from core.scanner import check_one as _check_one


def _https_challenge(port):
    return _Challenge(
        name="t", port=port, protocol="https", health_path="/",
        timeout=3.0, script=Path("x"), enabled=True, folder=Path("."),
    )


if shutil.which("openssl") is None:
    print("  SKIP  openssl not available (https self-signed test)")
else:
    _tmp = Path(tempfile.mkdtemp())
    _subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048",
         "-keyout", str(_tmp / "key.pem"), "-out", str(_tmp / "cert.pem"),
         "-days", "2", "-nodes", "-subj", "/CN=127.0.0.1"],
        check=True, capture_output=True,
    )
    _ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
    _ctx.load_cert_chain(str(_tmp / "cert.pem"), str(_tmp / "key.pem"))
    _srv = HTTPServer(("127.0.0.1", 0), SimpleHTTPRequestHandler)
    _srv.socket = _ctx.wrap_socket(_srv.socket, server_side=True)
    _port = _srv.server_address[1]
    _threading.Thread(target=_srv.serve_forever, daemon=True).start()
    check("https self-signed cert -> ONLINE",
          _check_one("127.0.0.1", _https_challenge(_port)), True)
    _srv.shutdown()
    check("https dead port -> OFFLINE",
          _check_one("127.0.0.1", _https_challenge(_port)), False)

# --- runner: $IP/$PORT env vars (regression for the 2026-11-25 report) ---
# A script that uses $IP/$PORT directly (no $1/$2 assignment) used to
# get empty values and curl failed with "URL rejected: No host part in
# the URL" (exit 3, "malformed"). The runner now exports IP/PORT as
# env vars too, so both conventions work.
print("[runner: $IP/$PORT env vars]")
import threading as _threading2
from http.server import BaseHTTPRequestHandler as _BH, HTTPServer as _HS
from core.loader import Challenge as _Challenge
from core.runner import run_one as _run_one

class _FlagHandler(_BH):
    def do_GET(self):
        body = b"<html><body>LKS{TEST00_ENVIP01}</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass

_srv2 = _HS(("127.0.0.1", 0), _FlagHandler)
_port2 = _srv2.server_address[1]
_threading2.Thread(target=_srv2.serve_forever, daemon=True).start()
_chdir = Path(tempfile.mkdtemp())
(_chdir / "exploit.sh").write_text(
    "#!/bin/bash\nset -u\n"
    "curl -s --max-time 5 \"http://$IP:$PORT/x\"\n",
    encoding="utf-8",
)
_chal = _Challenge(name="env-ip", port=_port2, protocol="http",
                   health_path="/", timeout=10.0,
                   script=_chdir / "exploit.sh", enabled=True, folder=_chdir)
_res = _run_one({"name": "t", "ip": "127.0.0.1"}, _chal)
check("script using $IP/$PORT (no $1/$2) gets the flag",
      extract_flags(_res.stdout), ["LKS{TEST00_ENVIP01}"])
check("script using $IP/$PORT exits 0", _res.returncode, 0)
_srv2.shutdown()

# ---------------------------------------------------------------------------
# Logger: an unusable logs dir must never raise, and must never kill a
# round. Logging is a side channel; the rounds are the work.
# ---------------------------------------------------------------------------
print("[logger: unusable logs dir never raises]")
from core.logger import Logger as _Logger
import shutil as _shutil

_bad_log_file = Path(_tempfile.mktemp())
_bad_log_file.write_text("not a directory")
try:
    _lg = _Logger(logs_dir=_bad_log_file)
    _lg.open_round(1)
    _lg.line("[TEST] console still works")
    _lg.close_round(1)
    check("Logger(logs_dir=<existing file>) never raises", True, True)
except Exception:
    check("Logger(logs_dir=<existing file>) never raises", False, True)
# A logs dir deleted after startup is recreated by open_round.
_good_log_dir = Path(_tempfile.mkdtemp()) / "logs"
_lg2 = _Logger(logs_dir=_good_log_dir)
_shutil.rmtree(_good_log_dir)
_lg2.open_round(1)
_lg2.line("[TEST] round runs after dir deleted")
_lg2.close_round(1)
check("open_round recreates a deleted logs dir",
      _good_log_dir.is_dir()
      and len(list(_good_log_dir.glob("round-*.log"))) == 1, True)

# ---------------------------------------------------------------------------
# Submitter: a malformed SUBMIT_URL must be a transport error (flags
# stay queued), never an exception that fails the round and loses flags.
# ---------------------------------------------------------------------------
print("[submitter: malformed SUBMIT_URL never raises]")
import config as _config2
from core.submitter import Submitter as _Submitter

_tmp2 = Path(_tempfile.mkdtemp())
_config2.SUBMITTED_FILE = _tmp2 / "s.json"
_config2.QUEUE_FILE = _tmp2 / "q.json"
_config2.TEAM_TOKEN = "TEST_TOKEN"
_malformed_ok = True
for _bad_url in ("notaurl", "", "http://exa mple.com/flags", "://bad"):
    _config2.SUBMIT_URL = _bad_url
    _sub = _Submitter(logger=None)
    try:
        _v = _sub.submit(["LKS{TEST00_MAL01}"])
        if _v != {"LKS{TEST00_MAL01}": "error"} or _sub.pending_count() != 1:
            _malformed_ok = False
    except Exception:
        _malformed_ok = False
check("malformed SUBMIT_URL -> error + queued, no raise", _malformed_ok, True)

# ---------------------------------------------------------------------------
# Submitter: an unwritable state file must not kill the round either.
# ---------------------------------------------------------------------------
print("[submitter: unwritable state file never raises]")
_config2.SUBMIT_URL = "http://127.0.0.1:9/flags"  # unreachable -> ERROR
_config2.SUBMITTED_FILE = _tmp2 / "adir"  # a directory, not a file
_config2.QUEUE_FILE = _tmp2 / "q2.json"
(_tmp2 / "adir").mkdir(exist_ok=True)
_sub2 = _Submitter(logger=None)
try:
    _v2 = _sub2.submit(["LKS{TEST00_SAVE01}"])
    check("unwritable state file -> submit returns, no raise",
          _v2 == {"LKS{TEST00_SAVE01}": "error"}
          and _sub2.pending_count() == 1, True)
except Exception:
    check("unwritable state file -> submit returns, no raise", False, True)

# ---------------------------------------------------------------------------
# Loader: "enabled" as a string must be parsed, not bool()'d.
# bool("false") is True in Python, so a config.json with
# "enabled": "false" used to ENABLE the challenge.
# ---------------------------------------------------------------------------
print("[loader: enabled as string]")
_enabled_dir = Path(_tempfile.mkdtemp())
for _slug, _enabled in (("strfalse", "false"), ("str0", "0"), ("strno", "no"),
                        ("strtrue", "true"), ("str1", "1"),
                        ("boolfalse", False), ("booltrue", True),
                        ("upperfalse", "FALSE"), ("mixed", "Off")):
    (_enabled_dir / _slug).mkdir()
    (_enabled_dir / _slug / "config.json").write_text(
        json.dumps({"name": _slug, "port": 8081, "protocol": "http",
                    "timeout": 30, "script": "exploit.sh",
                    "enabled": _enabled}), encoding="utf-8")
    (_enabled_dir / _slug / "exploit.sh").write_text("true\n", encoding="utf-8")
_enabled = {c.slug: c.enabled for c in _load_challenges(_enabled_dir)}
check("\"false\"/\"0\"/\"no\"/\"FALSE\"/\"Off\" disable the challenge",
      all(_enabled[s] is False for s in
          ("strfalse", "str0", "strno", "upperfalse", "mixed")), True)
check("\"true\"/\"1\" enable the challenge",
      all(_enabled[s] is True for s in ("strtrue", "str1", "booltrue")), True)
check("bool false still disables", _enabled["boolfalse"], False)

# ---------------------------------------------------------------------------
# Loader: the script must be a FILE, not just something that exists.
# A directory named exploit.sh used to load fine and then fail every
# round with exit 126 (bash: "is a directory"), zero flags.
# ---------------------------------------------------------------------------
print("[loader: script must be a file]")
_dirscript_dir = Path(_tempfile.mkdtemp())
(_dirscript_dir / "dirscript").mkdir()
(_dirscript_dir / "dirscript" / "config.json").write_text(
    json.dumps({"name": "ds", "port": 8081, "protocol": "http",
                "timeout": 5, "script": "exploit.sh"}), encoding="utf-8")
(_dirscript_dir / "dirscript" / "exploit.sh").mkdir()
check("script as a directory is skipped",
      _load_challenges(_dirscript_dir), [])

# ---------------------------------------------------------------------------
# Config: .env with `export KEY=value` lines, and a .env that cannot be
# read at all, must both work. The first silently left the token empty
# (flags only queued); the second crashed the framework at import.
# ---------------------------------------------------------------------------
print("[config: .env export prefix and unreadable .env]")
import shutil as _shutil2
_env_dir = Path(_tempfile.mkdtemp())
_shutil2.copy(Path(__file__).resolve().parent.parent / "config.py",
              _env_dir / "config.py")
(_env_dir / ".env").write_text(
    "export ATTDEF_TEAM_TOKEN=tok123\nexport ATTDEF_TICK=42\n",
    encoding="utf-8")
_out = _sp.run(
    [sys.executable, "-c",
     "import config; print(config.TEAM_TOKEN, config.TICK_SECONDS)"],
    capture_output=True, text=True, cwd=str(_env_dir),
)
check("export-style .env sets the token and tick",
      _out.stdout.strip() == "tok123 42.0", True)
_bad_env_dir = Path(_tempfile.mkdtemp())
_shutil2.copy(Path(__file__).resolve().parent.parent / "config.py",
              _bad_env_dir / "config.py")
(_bad_env_dir / ".env").mkdir()  # .env is a directory
_out = _sp.run(
    [sys.executable, "-c", "import config; print('imported ok')"],
    capture_output=True, text=True, cwd=str(_bad_env_dir),
)
check(".env as a directory does not crash import",
      _out.returncode == 0 and "imported ok" in _out.stdout, True)
_bad_utf_dir = Path(_tempfile.mkdtemp())
_shutil2.copy(Path(__file__).resolve().parent.parent / "config.py",
              _bad_utf_dir / "config.py")
(_bad_utf_dir / ".env").write_bytes(b"ATTDEF_TICK=\xff\xfe\n")
_out = _sp.run(
    [sys.executable, "-c", "import config; print('imported ok')"],
    capture_output=True, text=True, cwd=str(_bad_utf_dir),
)
check(".env with bad UTF-8 does not crash import",
      _out.returncode == 0 and "imported ok" in _out.stdout, True)

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
    sys.exit(1)
print("ALL UNIT TESTS PASSED")
