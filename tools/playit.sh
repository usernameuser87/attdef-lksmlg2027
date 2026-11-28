#!/usr/bin/env bash
# tools/playit.sh — manual helper for the PLAYIT PLUS 2026 platform API
# (ADTickPlatform participant API v2.0.0). Use it as a fallback when the
# framework is not running, or for quick checks during the match.
#
# Usage:
#   ./tools/playit.sh status                 Game status (tick, submissions open?)
#   ./tools/playit.sh challenges             Challenge list (ids for config.json api_id)
#   ./tools/playit.sh session                Your session (own team id, role)
#   ./tools/playit.sh services               Target map: challenge -> team -> host:port
#   ./tools/playit.sh submit FLAG [FLAG...]  Submit one or more flags (batches of <=128)
#   ./tools/playit.sh submit-file FILE       Extract every PLAYITPLUS{...} in FILE and submit
#
# Config comes from the environment or the repo's .env file:
#   PLAYIT_BASE_URL    default https://10.0.2.3
#   PLAYIT_EMAIL       participant account email (needed for authed commands)
#   PLAYIT_PASSWORD    participant account password
#   PLAYIT_VERIFY_TLS  1 = verify the platform TLS certificate (default: off)
#
# The JWT is cached in data/.playit-token (gitignored) and refreshed
# automatically once when the platform rejects it. Requires: curl, python3.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
TOKEN_FILE="${REPO_DIR}/data/.playit-token"

# --- config -------------------------------------------------------------
# Load PLAYIT_* values from .env when they are not already in the env.
load_env_file() {
    local file="$1" line key value
    [[ -f "${file}" ]] || return 0
    while IFS= read -r line || [[ -n "${line}" ]]; do
        case "${line}" in ''|'#'*) continue ;; esac
        key="${line%%=*}"
        case "${key}" in PLAYIT_*) ;; *) continue ;; esac
        value="${line#*=}"
        value="${value%\"}"; value="${value#\"}"
        value="${value%\'}"; value="${value#\'}"
        if [[ -z "${!key:-}" ]]; then
            printf -v "${key}" '%s' "${value}"
            export "${key}"
        fi
    done < "${file}"
}
load_env_file "${REPO_DIR}/.env"
load_env_file "./.env"

BASE_URL="${PLAYIT_BASE_URL:-https://10.0.2.3}"
BASE_URL="${BASE_URL%/}"
EMAIL="${PLAYIT_EMAIL:-}"
PASSWORD="${PLAYIT_PASSWORD:-}"

CURL_TLS=(-k)
if [[ "${PLAYIT_VERIFY_TLS:-}" == "1" ]]; then
    CURL_TLS=()
fi

die() { echo "ERROR: $*" >&2; exit 1; }

command -v curl >/dev/null 2>&1 || die "curl not found"
command -v python3 >/dev/null 2>&1 || die "python3 not found"

# --- http ---------------------------------------------------------------
# api_call METHOD PATH [JSON_BODY] [TOKEN]
# Sets API_BODY and API_CODE. Must NOT be called inside $(...) or a
# pipeline — the globals would be lost in the subshell.
# Direct connection (no proxy): the platform is reached over the VPN.
API_BODY=""
API_CODE="000"
api_call() {
    local method="$1" path="$2" body="${3:-}" token="${4:-}"
    local args=(-s --noproxy '*' --max-time 15 -X "${method}"
                "${CURL_TLS[@]}" -w $'\n%{http_code}')
    if [[ -n "${token}" ]]; then
        args+=(-H "Authorization: Bearer ${token}")
    fi
    if [[ -n "${body}" ]]; then
        args+=(-H 'Content-Type: application/json' --data-binary "${body}")
    fi
    local raw
    if ! raw="$(curl "${args[@]}" "${BASE_URL}${path}" 2>/dev/null)"; then
        die "cannot reach ${BASE_URL} — is the WireGuard VPN connected and PLAYIT_BASE_URL right?"
    fi
    API_CODE="${raw##*$'\n'}"
    API_BODY="${raw%$'\n'*}"
}

TOKEN=""
login() {
    [[ -n "${EMAIL}" && -n "${PASSWORD}" ]] || \
        die "PLAYIT_EMAIL / PLAYIT_PASSWORD are not set (fill them in .env)"
    local payload
    payload="$(python3 -c 'import json,sys; print(json.dumps({"email": sys.argv[1], "password": sys.argv[2]}))' "${EMAIL}" "${PASSWORD}")"
    api_call POST /api/v2/authenticate "${payload}"
    if [[ "${API_CODE}" == "429" ]]; then
        die "rate limited by the platform (429) — wait a bit, then retry"
    fi
    if [[ "${API_CODE}" != "200" ]]; then
        echo "${API_BODY}" >&2
        die "login failed (HTTP ${API_CODE}) — check PLAYIT_EMAIL / PLAYIT_PASSWORD"
    fi
    TOKEN="$(printf '%s' "${API_BODY}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("token",""))')"
    [[ -n "${TOKEN}" ]] || die "login response had no token"
    mkdir -p "$(dirname "${TOKEN_FILE}")"
    printf '%s' "${TOKEN}" > "${TOKEN_FILE}"
    chmod 600 "${TOKEN_FILE}" 2>/dev/null || true
}

ensure_token() {
    if [[ -s "${TOKEN_FILE}" ]]; then
        TOKEN="$(cat "${TOKEN_FILE}")"
    else
        login
    fi
}

# api_authed METHOD PATH [JSON_BODY] — authed call with one re-login.
# Result in API_BODY / API_CODE.
api_authed() {
    ensure_token
    api_call "$1" "$2" "${3:-}" "${TOKEN}"
    if [[ "${API_CODE}" == "401" || "${API_CODE}" == "403" ]]; then
        rm -f "${TOKEN_FILE}"
        login
        api_call "$1" "$2" "${3:-}" "${TOKEN}"
    fi
}

pretty() {
    python3 -c '
import json, sys
raw = sys.stdin.read()
try:
    print(json.dumps(json.loads(raw), indent=2))
except Exception:
    print(raw)
'
}

# --- submit ---------------------------------------------------------------
submit_flags() {
    local flags=("$@")
    local total=${#flags[@]}
    (( total > 0 )) || die "no flags given"
    local start=0 accepted=0
    while (( start < total )); do
        local chunk=("${flags[@]:start:128}")
        local payload parsed chunk_accepted
        payload="$(python3 -c 'import json,sys; print(json.dumps({"flags": sys.argv[1:]}))' "${chunk[@]}")"
        api_authed POST /api/v2/submit "${payload}"
        if [[ "${API_CODE}" == "429" ]]; then
            die "rate limited by the platform (429) — wait a bit, then retry"
        fi
        if [[ "${API_CODE}" != "200" ]]; then
            echo "${API_BODY}" >&2
            die "submit failed (HTTP ${API_CODE})"
        fi
        parsed="$(printf '%s' "${API_BODY}" | python3 -c '
import json, sys
data = json.load(sys.stdin)
for r in data.get("results", []):
    detail = r.get("detail", "")
    line = "[" + str(r.get("status", "?")) + "] " + str(r.get("flag", "?"))
    if detail:
        line += " - " + str(detail)
    print(line)
print(data.get("accepted_count", 0))
' 2>/dev/null)" || parsed=""
        if [[ -z "${parsed}" ]]; then
            echo "${API_BODY}"
            chunk_accepted=0
        else
            echo "${parsed}" | sed '$d'
            chunk_accepted="$(echo "${parsed}" | tail -1)"
        fi
        accepted=$(( accepted + chunk_accepted ))
        start=$(( start + 128 ))
    done
    echo "Done: ${accepted}/${total} accepted."
}

# --- commands -------------------------------------------------------------
usage() {
    sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

cmd="${1:-}"
case "${cmd}" in
    status)
        api_call GET /api/v2/game/status
        printf '%s' "${API_BODY}" | pretty
        ;;
    challenges)
        api_call GET /api/v2/challenges
        printf '%s' "${API_BODY}" | pretty
        ;;
    session)
        api_authed GET /api/v2/session
        printf '%s' "${API_BODY}" | pretty
        ;;
    services)
        api_authed GET /api/v2/services
        printf '%s' "${API_BODY}" | pretty
        ;;
    submit)
        shift
        (( $# > 0 )) || { usage >&2; exit 1; }
        submit_flags "$@"
        ;;
    submit-file)
        shift
        [[ -n "${1:-}" && -f "${1}" ]] || die "usage: $0 submit-file FILE"
        mapfile -t found < <(grep -oE 'PLAYITPLUS\{[^}]+\}' "${1}" | sort -u)
        (( ${#found[@]} > 0 )) || die "no PLAYITPLUS{...} flags found in ${1}"
        echo "Found ${#found[@]} flag(s) in ${1}:"
        submit_flags "${found[@]}"
        ;;
    ""|-h|--help|help)
        usage
        ;;
    *)
        echo "Unknown command: ${cmd}" >&2
        usage >&2
        exit 1
        ;;
esac
