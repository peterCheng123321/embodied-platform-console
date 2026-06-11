#!/usr/bin/env bash
# Run the Embodied Platform Console (API + SPA, same origin) with zero infrastructure.
#
#   ./scripts/run.sh            # starts console + hosted labeler on :8099
#
# The two env values below are LOCAL DEV PLACEHOLDERS. In any real deployment,
# set your own strong XINGJU_EMBODIED_PLATFORM_AUTH_SECRET and
# XINGJU_EMBODIED_PLATFORM_LOGIN_PASSCODE (and put SSO in front of /session).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT/backend"

export XINGJU_EMBODIED_PLATFORM_AUTH_SECRET="${XINGJU_EMBODIED_PLATFORM_AUTH_SECRET:-dev-change-me-secret}"
export XINGJU_EMBODIED_PLATFORM_LOGIN_PASSCODE="${XINGJU_EMBODIED_PLATFORM_LOGIN_PASSCODE:-ground-control-dev}"
export XINGJU_EMBODIED_PLATFORM_DATA_ROOT="${XINGJU_EMBODIED_PLATFORM_DATA_ROOT:-$REPO_ROOT/backend/data/embodied_platform}"
export XINGJU_EMBODIED_DATA_ROOT="${XINGJU_EMBODIED_DATA_ROOT:-$REPO_ROOT/backend/data/embodied}"
export XINGJU_EMBODIED_CACHE_ROOT="${XINGJU_EMBODIED_CACHE_ROOT:-$REPO_ROOT/backend/data/embodied_cache}"

PORT="${PORT:-8099}"
PY="${PYTHON:-python3}"

echo "Embodied Platform Console"
echo "  Console:  http://127.0.0.1:${PORT}/app/"
echo "  Labeler:  http://127.0.0.1:${PORT}/labeler/"
echo "  Login:    pick a write role + passcode '${XINGJU_EMBODIED_PLATFORM_LOGIN_PASSCODE}' (dev default)"
echo "  Data:     ${XINGJU_EMBODIED_PLATFORM_DATA_ROOT}"
echo "  Segments: ${XINGJU_EMBODIED_DATA_ROOT}"
echo

exec "$PY" -m uvicorn api.main:app --port "$PORT"
