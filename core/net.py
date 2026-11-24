# core/net.py — direct HTTP(S), never through a proxy.
"""
The competition hosts (targets and the scoreboard) are direct IPs on
the competition network. urllib.request.urlopen() honours the
http_proxy / https_proxy / all_proxy environment variables, so on any
machine with a proxy configured (a VPS, a VPN, a corporate laptop)
every health check and every flag submission would be routed to the
proxy instead — and fail.

Verified 2026-11-24: with http_proxy pointed at a dead address and
the target not in no_proxy, plain urlopen fails with URLError
(connection refused) while this opener succeeds.

Use direct_opener().open(...) everywhere the framework talks HTTP.
"""

import ssl
import urllib.request

_OPENER = None
_UNVERIFIED_OPENER = None


def direct_opener():
    """A urllib opener that never uses a proxy. Built once, reused."""
    global _OPENER
    if _OPENER is None:
        _OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return _OPENER


def direct_opener_unverified():
    """Like direct_opener(), but also skips TLS certificate checks.

    Only for health checks: they send no credentials, they only ask
    "is something alive here". CTF services very often use self-signed
    certificates, and a strict check would mark them OFFLINE forever.
    """
    global _UNVERIFIED_OPENER
    if _UNVERIFIED_OPENER is None:
        _UNVERIFIED_OPENER = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(
                context=ssl._create_unverified_context()
            ),
        )
    return _UNVERIFIED_OPENER
