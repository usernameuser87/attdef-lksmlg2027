# core/parser.py — flag extraction from Bash stdout.
"""
Pipeline (in order):
  1. Strip ANSI escape codes (coloured terminal output).
  2. Strip curl progress-meter output (lines full of % and carriage
     returns). curl -s should not print it, but a script without -s does.
  3. Strip HTML tags — but never let a tag's contents glue into a flag.
     Tags are replaced by a single space so "<div>LKS{A}</div><b>LKS{B}</b>"
     still yields two separate flags.
  4. Normalise whitespace.
  5. Extract with a regex that cannot cross a tag, a space or a brace.

Supported formats:
  * LKS{...}
  * LKSMLG2027{...}

The longer alternative (LKSMLG2027) is tried FIRST, otherwise the
regex would match the "LKS" prefix of an LKSMLG2027 flag and stop
at the wrong place. Flag bodies may contain any visible character
except whitespace, angle brackets and a closing brace.

Duplicates are removed, first occurrence wins, order is preserved.
"""

import re

# ANSI: CSI sequences, OSC sequences, charset switches.
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[A-Za-z]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b\([A-Za-z0-9]"
    r"|\x1b[@-Z\\-_]"
)

# curl progress meter: header line and the "  % Total ..." rows.
_CURL_PROGRESS_RE = re.compile(
    r"^[^\n]*%\s+Total\s+%\s+Received[^\n]*\n?",
    re.IGNORECASE | re.MULTILINE,
)
_CURL_PROGRESS_ROW_RE = re.compile(
    r"^[ \t]*\d+(?:\.\d+)?%[^\n]*\n?", re.MULTILINE
)

_TAG_RE = re.compile(r"<[^>]*>")

# Longer alternative first. Body: no whitespace, no < >, no }.
_FLAG_RE = re.compile(r"LKSMLG2027\{[^}\s<>]+\}|LKS\{[^}\s<>]+\}")


def clean(text: str) -> str:
    """Return stdout with noise removed, keeping flag text intact."""
    if not text:
        return ""
    # \r is the progress meter's line separator; keep the last segment.
    text = text.replace("\r", "\n")
    text = _ANSI_RE.sub("", text)
    text = _CURL_PROGRESS_RE.sub("", text)
    text = _CURL_PROGRESS_ROW_RE.sub("", text)
    # Tags -> space, so adjacent tags cannot fuse two words into one.
    text = _TAG_RE.sub(" ", text)
    # Collapse whitespace; a flag never contains a space.
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def extract_flags(text: str) -> list[str]:
    """Extract unique flags from raw stdout (cleaning included)."""
    found = _FLAG_RE.findall(clean(text))
    seen: set[str] = set()
    unique: list[str] = []
    for flag in found:
        if flag not in seen:
            seen.add(flag)
            unique.append(flag)
    return unique
