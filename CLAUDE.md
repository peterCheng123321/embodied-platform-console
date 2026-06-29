# CLAUDE.md

This repository is maintained by AI agents. The full operating manual — how to set up,
run, test, and **ship a change through the protected-`main` PR flow** — lives in
[AGENTS.md](./AGENTS.md). Read it before making any change.

Two things that bite agents most often (the rest is in AGENTS.md):

- **Never push to `main`.** Ship via `scripts/fix-push.sh <slug> "<title>"`, which opens a
  reviewed PR; `main` requires 1 review + 7 green CI checks.
- **Tests live under `backend/tests/`** (`testpaths = ["tests"]`), not `backend/api/.../tests/`.
  Verify with `cd backend && python3 -m pytest tests -q` and `node tests/embodied-platform-audit.mjs`.
