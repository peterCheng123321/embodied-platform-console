#!/usr/bin/env bash
# Restore backend/data from a tarball produced by backup-state.sh.
# Refuses to run without an explicit tarball argument; the current data dir is
# moved aside to backend/data.pre-restore-<stamp> (never deleted) before untar.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ "$#" -ne 1 ]; then
  echo "usage: $0 <state-YYYYmmdd-HHMMSS.tar.gz>" >&2
  exit 1
fi
TARBALL="$1"
if [ ! -f "$TARBALL" ]; then
  echo "error: no such tarball: $TARBALL" >&2
  exit 1
fi
STAMP="$(date +%Y%m%d-%H%M%S)"
if [ -d "$ROOT/backend/data" ]; then
  mv "$ROOT/backend/data" "$ROOT/backend/data.pre-restore-$STAMP"
  echo "moved aside: backend/data -> backend/data.pre-restore-$STAMP"
fi
tar -xzf "$TARBALL" -C "$ROOT/backend"
echo "restored: $TARBALL -> $ROOT/backend/data"
