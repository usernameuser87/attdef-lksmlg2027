# core/scanner.py — health checks.
"""
For every (target, challenge) pair, decide ONLINE vs OFFLINE before any
exploit runs. Offline pairs are skipped for the whole round.

  * http/https: GET http(s)://IP:PORT<health_path> with a short timeout.
    ONLINE when we get any HTTP response (2xx/3xx/4xx). 5xx counts as
    OFFLINE — the service is up but broken, exploits would only waste time.
  * tcp: plain socket connect.

Checks run concurrently (ThreadPoolExecutor) so 9 targets x N challenges
finish in seconds, not minutes. A single slow target can never block the
round: every check has its own hard timeout.
"""

import http.client
import socket
import ssl
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import config
from core.loader import Challenge
from core.net import direct_opener, direct_opener_unverified


def check_one(ip: str, challenge: Challenge, timeout: float | None = None) -> bool:
    timeout = timeout if timeout is not None else config.DEFAULT_HEALTH_TIMEOUT
    if challenge.protocol in ("http", "https"):
        path = challenge.health_path or "/"
        url = f"{challenge.protocol}://{ip}:{challenge.port}{path}"
        req = urllib.request.Request(url, method="GET")
        try:
            # Direct connection — never through a proxy (see core/net.py).
            with direct_opener().open(req, timeout=timeout) as resp:
                return resp.status < 500
        except urllib.error.HTTPError as exc:
            # Any HTTP response means the service is alive.
            return exc.code < 500
        except urllib.error.URLError as exc:
            # Self-signed / untrusted certificate: the service IS alive,
            # only its certificate is untrusted — retry the liveness
            # check without verification. A health check sends no
            # credentials, so this leaks nothing. Without this, any
            # https challenge with a self-signed cert is marked
            # OFFLINE forever and its exploit never runs.
            if isinstance(exc.reason, ssl.SSLError):
                try:
                    with direct_opener_unverified().open(
                        req, timeout=timeout
                    ) as resp:
                        return resp.status < 500
                except urllib.error.HTTPError as exc2:
                    return exc2.code < 500
                except (urllib.error.URLError, OSError, TimeoutError,
                        ValueError, http.client.HTTPException):
                    return False
            return False
        except (OSError, TimeoutError, ValueError, http.client.HTTPException):
            return False
    # tcp: connect only.
    try:
        with socket.create_connection((ip, challenge.port), timeout=timeout):
            return True
    except (OSError, TimeoutError, ValueError):
        return False


def check_all(pairs, timeout: float | None = None) -> dict:
    """pairs: list of (target_dict, Challenge). Returns {(ip, slug): bool}."""
    results: dict = {}
    if not pairs:
        return results
    with ThreadPoolExecutor(max_workers=config.SCAN_WORKERS) as pool:
        futures = {
            pool.submit(check_one, target["ip"], chal, timeout): (target, chal)
            for target, chal in pairs
        }
        for fut, (target, chal) in futures.items():
            try:
                results[(target["ip"], chal.slug)] = bool(fut.result())
            except Exception:
                results[(target["ip"], chal.slug)] = False
    return results
