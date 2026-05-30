# Embodied Platform Console · 具身平台运营台

A production-style **operations control console for embodied-AI / robot-fleet pipelines** — ten
modules spanning the full lifecycle (Data → Annotation → Training → Models → Sim2Real → Deployment →
Online Learning → Monitoring → Audit → System), built as an **offline-capable PWA** over a small,
**zero-infrastructure FastAPI** backend that persists to an atomic, file-locked JSON store.

The UI is a clean **blue + white** instrument theme (IBM Plex Sans SC / Plex Mono / Chakra Petch),
fully in Simplified Chinese, with a live-API mode that gracefully falls back to an offline demo.

> Single-operator / internal-tool scope by design: file-based persistence, signed-header auth, no
> multi-tenancy. It is a focused, runnable reference console — not an enterprise SaaS.

## Quick start

```bash
# 1) install backend deps (any venv)
cd backend && python -m pip install -e ".[dev]" && cd ..

# 2) run API + SPA on one origin
./scripts/run.sh
# -> open http://127.0.0.1:8099/app/
```

Click **登录 (Login)**, choose a write role (e.g. `admin`), and enter the dev passcode
(`ground-control-dev`). That mints an HMAC-signed session and unlocks live writes; every create
flows through the API, persists to the JSON store, and is recorded in the audit trail. With the
backend stopped, the SPA still runs fully in **offline demo** mode (localStorage-persisted).

## What's inside

- **10 modules**, each with forms + tables and a shared status-tag system: datasets/episodes/imports,
  annotation tasks (robotics-native task types: trajectory-segment / success-check / language-grounding
  / safety-event), training jobs, model registry + activation, simulation/sim2real jobs, edge
  deployments, an online-learning queue, a visual monitoring board (metric tiles + sim-success gauge),
  an append-only audit log, and system settings.
- **Auth & governance**: 6-role RBAC mirrored frontend + backend, HMAC-signed writes verified with
  constant-time comparison, a `/session` login that mints the signature, and an audit event on every
  mutation. Job records enforce a legal state machine; references are integrity-checked.
- **Resilience**: atomic, `flock`-guarded JSON persistence (`os.replace` + `fsync`); offline-first PWA
  with a service worker and demo fixtures.

## Architecture

```
apps/embodied-platform/        # SPA (vanilla ES/CSS/HTML, no build step) + service worker + fixtures
backend/
  api/
    main.py                    # FastAPI: mounts the API + serves the SPA same-origin + /healthz
    embodied_platform/
      routes.py                # all endpoints + /session + RBAC + audit + job state machine
      schema.py                # strict Pydantic models
      repository.py            # atomic, file-locked JSON repository
  tests/embodied_platform/     # API + e2e round-trip tests (FastAPI TestClient)
tests/embodied-platform-audit.mjs  # static design/structure audit
scripts/run.sh                 # one-command run (API + SPA, same origin)
```

## Tests

```bash
cd backend && python -m pytest tests/embodied_platform -q   # API + e2e round-trip
node tests/embodied-platform-audit.mjs                      # design/structure audit (from repo root)
```

## Configuration

| Env var | Purpose | Dev default |
|---|---|---|
| `XINGJU_EMBODIED_PLATFORM_AUTH_SECRET` | HMAC secret for signing/verifying principals | `dev-change-me-secret` |
| `XINGJU_EMBODIED_PLATFORM_LOGIN_PASSCODE` | passcode gating `/session` login | `ground-control-dev` |
| `XINGJU_EMBODIED_PLATFORM_DATA_ROOT` | JSON state directory | `backend/data/embodied_platform` |

**Security note:** the defaults above are local-dev placeholders. Set your own strong values and
front `/session` with real SSO before exposing this anywhere.

## License

MIT — see [LICENSE](LICENSE).
