#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-$ROOT/backups}"; mkdir -p "$DEST"
STAMP="$(date +%Y%m%d-%H%M%S)"
tar -czf "$DEST/state-$STAMP.tar.gz" -C "$ROOT/backend" --exclude='data/embodied_cache' data
ls -1t "$DEST"/state-*.tar.gz | tail -n +15 | xargs rm -f 2>/dev/null || true
echo "backup: $DEST/state-$STAMP.tar.gz ($(du -h "$DEST/state-$STAMP.tar.gz" | cut -f1))"
