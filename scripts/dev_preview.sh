#!/usr/bin/env bash
# Dev-only preview launcher: runs the real FastAPI app against the local
# SQLite preview DB (scripts/dev_preview_seed.py) so the signup/directory
# pages can be exercised in a browser. Never used in production.
#
# PHONE TESTING. The server listens on every interface, so any device on the
# same router can open it — which is the only honest way to check the mobile
# layout, because a 390px-wide desktop window still has a mouse, hover states
# and a scrollbar, and a real phone has none of those. Two things have to line
# up for it to work:
#
#   1. The listen address must be 0.0.0.0, not 127.0.0.1. Loopback is reachable
#      only from this machine, by definition — that is what loopback means.
#   2. APP_BASE_URL must be this machine's address ON THE ROUTER. It is not
#      decoration: the profile and product pages build their share links from
#      it, and the verification and password-reset emails build theirs from it
#      too. Left at 127.0.0.1, every one of those links would point the phone
#      at itself and fail.
#
# WHAT IS EXPOSED is this repo's ./dev_preview.db — a seeded SQLite file with
# throwaway accounts. The live Supabase database is not reachable from here,
# because the DATABASE_URL export below replaces it before the app ever reads
# the setting. It is still a debug server on a shared network though, so prefer
# a home router over café or campus Wi-Fi.
#
# Overrides:
#   PORT=9000 ./scripts/dev_preview.sh          # different port
#   HOST=127.0.0.1 ./scripts/dev_preview.sh     # this laptop only, no LAN
#   ./scripts/dev_preview.sh --reload           # extra uvicorn flags pass through
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

# --- This machine's address on the router --------------------------------
# Two attempts, in order of precision then availability.
#
# First: ask the routing table which interface carries the default route, then
# ask that interface for its address. This is the accurate one — it picks
# correctly when Wi-Fi, Ethernet and a tethered phone are all up at once.
#
# Then: parse ifconfig. Needed more often than it looks. `route` needs a routing
# socket and `ipconfig` needs to reach configd, so both fail under a sandbox or a
# restrictive security agent, and there is no default route at all on a router
# with no internet uplink — which still runs a perfectly good LAN, and is
# exactly the case where the address is worth finding.
#
# The filters carry the real knowledge: en*/bridge* only, because a utun/ipsec
# VPN address and awdl0's AirDrop link-local are both unreachable from the
# phone; and 169.254.* is dropped because a self-assigned address means DHCP
# never answered, so nothing else on the network can route to it either.
lan_address() {
    local iface="" addr=""

    if command -v route >/dev/null 2>&1 && command -v ipconfig >/dev/null 2>&1; then
        iface="$(route -n get default 2>/dev/null | awk '/interface: /{print $2; exit}')"
        [ -n "$iface" ] && addr="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
    fi

    if [ -z "$addr" ] && command -v ifconfig >/dev/null 2>&1; then
        addr="$(ifconfig 2>/dev/null | awk '
            /^[a-z][a-z0-9]*:/ { ifc = substr($1, 1, length($1) - 1) }
            /^[[:space:]]*inet / && ifc ~ /^(en|bridge)[0-9]/ {
                if ($2 !~ /^(127\.|169\.254\.)/) { print $2; exit }
            }')"
    fi

    if [ -z "$addr" ] && command -v ip >/dev/null 2>&1; then    # Linux
        addr="$(ip -4 route get 1.1.1.1 2>/dev/null \
                | awk '{for (i = 1; i <= NF; i++) if ($i == "src") {print $(i + 1); exit}}')"
    fi

    printf '%s' "$addr"
}

LAN_IP="$(lan_address)"
[ "$HOST" = "0.0.0.0" ] || LAN_IP=""      # asked for loopback: there is no LAN URL to offer

export DATABASE_URL="sqlite+aiosqlite:///./dev_preview.db"
export APP_ENV="development"

# Point the app at the address a browser will actually type — the LAN one when
# there is a LAN, loopback otherwise, and in both cases the port we are really
# serving on rather than the 8000 hardcoded in .env. An explicit export from the
# caller wins; the .env value deliberately does not, since .env is the file
# saying 127.0.0.1 and overriding it is the entire point of this block.
if [ -z "${APP_BASE_URL:-}" ]; then
    export APP_BASE_URL="http://${LAN_IP:-127.0.0.1}:${PORT}"
fi

# Google will not register a private-IP http:// callback at all, so letting the
# redirect URI derive from a 192.168.x.x APP_BASE_URL (see config.py's
# google_redirect_uri) would break the sign-in that works on this laptop today.
# Pin it back to loopback — unless .env or the environment already names one, in
# which case that is the URI actually registered with Google and guessing over
# it would be worse than doing nothing. Consequence worth knowing: "Continue
# with Google" only works in the laptop's browser; on the phone, sign in with
# the email and password form.
if [ -z "${GOOGLE_REDIRECT_URI:-}" ] && ! grep -qs '^GOOGLE_REDIRECT_URI=.' .env; then
    export GOOGLE_REDIRECT_URI="http://127.0.0.1:${PORT}/api/auth/google/callback"
fi

[ -f ./dev_preview.db ] || ./venv/bin/python scripts/dev_preview_seed.py

# The seed above only runs when the file is ABSENT, so an existing preview DB
# silently lags behind every model change made since it was created. That is how
# signup started failing with `no such column: users.failed_login_attempts`
# (added by 0005_login_lockout) — and because the ORM SELECTs the full column
# list, one missing column breaks every query on that table, not just the new
# feature. Patch the additive drift on each launch; the sync script aborts this
# launcher (set -e) with re-seed instructions if the drift needs a rebuild.
./venv/bin/python scripts/dev_preview_sync.py

# --- Where to open it ----------------------------------------------------
# Printed before uvicorn starts, so the addresses sit above its own log lines
# rather than being buried by the first request.
printf '\n  CartFlow dev preview\n'
printf '  ─────────────────────────────────────────────────────────\n'
printf '  This laptop     http://127.0.0.1:%s\n' "$PORT"
if [ -n "$LAN_IP" ]; then
    printf '  Phone / tablet  http://%s:%s\n' "$LAN_IP" "$PORT"
    printf '                  Same Wi-Fi as this laptop. Type it in full —\n'
    printf '                  no https, and the port is not optional.\n'
    printf '  Share + email links point at %s\n' "$LAN_IP"
    printf '  Not loading?    Approve the macOS firewall prompt for python, and\n'
    printf '                  check the phone is on this router, not mobile data.\n'
else
    if [ "$HOST" = "0.0.0.0" ]; then
        printf '  Phone / tablet  no LAN address found — is Wi-Fi off?\n'
    else
        printf '  Phone / tablet  disabled (HOST=%s)\n' "$HOST"
    fi
fi
printf '  ─────────────────────────────────────────────────────────\n\n'

# ${1+"$@"} rather than "$@": under `set -u` an empty "$@" is an unbound
# variable on bash 3.2, which is still what /bin/bash is on macOS.
#
# `python -m uvicorn`, not `./venv/bin/uvicorn`: the venv's console scripts
# carry a hard-coded shebang to the interpreter path they were created with,
# and this project's path contains spaces — which a #! line cannot express.
# Invoking the module through the python symlink sidesteps the shebang, so it
# keeps working no matter where the venv is copied. Same pattern for alembic:
# `./venv/bin/python -m alembic ...`.
exec ./venv/bin/python -m uvicorn app.main:app --host "$HOST" --port "$PORT" ${1+"$@"}
