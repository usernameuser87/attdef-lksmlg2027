# core/platform.py — PLAYIT PLUS 2026 platform API client (API v2.0.0).
"""
Talks to the ADTickPlatform participant API (see the official
participant API reference, v2.0.0):

  * POST /api/v2/authenticate  {"email", "password"} -> {"token": JWT}
    The token is cached and refreshed ONCE on a 401/403, mirroring the
    behaviour verified against the mock platform on 2026-11-27.
  * GET  /api/v2/session       -> own identity, incl. "team_id".
  * GET  /api/v2/game/status   -> {"match": {"accepting_submissions"},
                                   "scheduler": {"interval_seconds"}}
  * GET  /api/v2/services      -> {challenge_id: {team_id: ["host:port"]}}
  * POST /api/v2/submit        {"flags": [...]} (1..128 per request)
                               -> {"results": [{"flag", "status",
                                   "detail", "challenge_id"}], ...}

Transport rules match the rest of the framework: stdlib urllib only,
NEVER through a proxy (core/net.py), and TLS verification is OFF by
default because CTF platforms routinely use self-signed certificates
(config.PLAYIT_VERIFY_TLS=1 turns it on).

Errors are raised as PlatformError; callers decide what a failure
means (the submitter queues the flags — they are never lost).
"""

import json
import urllib.error
import urllib.request
from http.client import HTTPException

import config
from core.net import direct_opener, direct_opener_unverified


class PlatformError(Exception):
    """Any platform transport/protocol failure (flags stay queued)."""


class PlatformClient:
    def __init__(self, base_url=None, email=None, password=None,
                 verify_tls=None, timeout=None, logger=None):
        self.base_url = (base_url or config.PLAYIT_BASE_URL).rstrip("/")
        self.email = email if email is not None else config.PLAYIT_EMAIL
        self.password = password if password is not None else config.PLAYIT_PASSWORD
        self.verify_tls = (
            config.PLAYIT_VERIFY_TLS if verify_tls is None else verify_tls
        )
        self.timeout = timeout if timeout is not None else config.SUBMIT_TIMEOUT
        self.logger = logger
        self._token = None

    # -- transport ------------------------------------------------------
    def _opener(self):
        if self.base_url.lower().startswith("https://") and not self.verify_tls:
            return direct_opener_unverified()
        return direct_opener()

    def _raw(self, method, path, payload=None, token=None):
        """One HTTP round-trip. Returns (status, parsed_json_or_None).

        Raises PlatformError on any transport failure. HTTP error
        statuses are RETURNED (not raised) so callers can read the
        problem+json body.
        """
        url = self.base_url + path
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            req = urllib.request.Request(url, data=data, method=method,
                                         headers=headers)
            with self._opener().open(req, timeout=self.timeout) as resp:
                return resp.status, self._parse(resp.read())
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, self._parse(exc.read())
            except Exception:
                return exc.code, None
        except (urllib.error.URLError, OSError, TimeoutError, ValueError,
                HTTPException) as exc:
            raise PlatformError(f"{method} {path} failed: {exc}") from exc

    @staticmethod
    def _parse(raw):
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return None

    # -- auth -----------------------------------------------------------
    def authenticate(self):
        """Log in and cache the JWT. Raises PlatformError on failure."""
        status, data = self._raw(
            "POST", "/api/v2/authenticate",
            {"email": self.email, "password": self.password},
        )
        if status == 429:
            raise PlatformError("authenticate rate limited (HTTP 429)")
        if status != 200 or not isinstance(data, dict) or not data.get("token"):
            raise PlatformError(f"authenticate failed (HTTP {status})")
        self._token = str(data["token"])
        return self._token

    def request(self, method, path, payload=None):
        """Authenticated request with ONE re-auth retry on 401/403.

        Returns the parsed JSON body. Raises PlatformError on any
        failure, including a second 401/403 and HTTP 429.
        """
        if self._token is None:
            self.authenticate()
        status, data = self._raw(method, path, payload, token=self._token)
        if status in (401, 403):
            self.authenticate()
            status, data = self._raw(method, path, payload, token=self._token)
            if status in (401, 403):
                raise PlatformError(f"{method} {path}: auth rejected twice")
        if status == 429:
            raise PlatformError(f"{method} {path}: rate limited (HTTP 429)")
        if status >= 400:
            raise PlatformError(f"{method} {path}: HTTP {status}")
        return data

    # -- endpoints --------------------------------------------------------
    def session(self):
        """Own identity dict (incl. team_id), or {} if unavailable."""
        data = self.request("GET", "/api/v2/session")
        return data if isinstance(data, dict) else {}

    def my_team_id(self):
        """Own team id as a string, or None if the API doesn't say."""
        team_id = self.session().get("team_id")
        return None if team_id is None else str(team_id)

    def game_status(self):
        """Raw game/status dict ({} on unexpected shape)."""
        data = self.request("GET", "/api/v2/game/status")
        return data if isinstance(data, dict) else {}

    def tick_seconds(self, fallback):
        """scheduler.interval_seconds from game/status, else fallback."""
        try:
            scheduler = self.game_status().get("scheduler") or {}
            value = float(scheduler.get("interval_seconds"))
            if value > 0:
                return value
        except (TypeError, ValueError, PlatformError):
            pass
        return fallback

    def accepting_submissions(self):
        """True/False from game/status; None if the API can't be asked.

        None means "unknown" — the caller should still try to submit
        (the submit endpoint gives the real answer), while an explicit
        False means hold the flags in the queue.
        """
        try:
            match = self.game_status().get("match") or {}
        except PlatformError:
            return None
        value = match.get("accepting_submissions")
        return value if isinstance(value, bool) else None

    def services(self):
        """The services map {challenge_id: {team_id: ["host:port"]}}."""
        data = self.request("GET", "/api/v2/services")
        return data if isinstance(data, dict) else {}

    def submit_flags(self, flags):
        """POST one batch (1..128 flags). Returns the response dict."""
        if not (1 <= len(flags) <= 128):
            raise PlatformError(
                f"submit batch must be 1..128 flags, got {len(flags)}")
        data = self.request("POST", "/api/v2/submit", {"flags": list(flags)})
        if not isinstance(data, dict):
            raise PlatformError("submit returned an unparsable response")
        return data
