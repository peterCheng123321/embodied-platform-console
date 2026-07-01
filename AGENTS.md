# AGENTS.md — operating manual for AI agents working in this repo

This repository is maintained almost entirely by AI coding agents. This file is the
**canonical, machine-facing brief**: read it before you touch anything. It is the
source of truth for how to build, test, and ship a change here. `CLAUDE.md` points
back to this file; `CONTRIBUTING.md` is the human-prose version of the same flow.

> One rule above all others: **never push to `main`.** Every change lands through a
> reviewed pull request that passes CI. See "Shipping a change" below.

## What this is

**Embodied Platform Console (具身平台运营台)** — a production-style operations console
for embodied-AI / robot-fleet pipelines (Data → Collection → Annotation → Training →
Models → Sim2Real → Deployment → Online Learning → Monitoring → Audit → System), built
as an offline-capable PWA over a small, zero-infrastructure FastAPI backend that
persists to an atomic, file-locked JSON store (or Postgres when a DSN is set).

- **UI is fully in Simplified Chinese** and so are issues and PR descriptions. Keep it that way.
- The SPA is **vanilla ES/CSS/HTML with no build step** — edit the served assets directly.
- Single-operator / internal-tool scope by design: file-based persistence, signed-header auth.

## Repository map

```
apps/embodied-platform/     # SPA: vanilla JS/CSS/HTML + service worker + demo fixtures
apps/embodied-labeler/      # Hosted temporal segment labeler (mounted at /labeler/)
apps/_vendor/               # Vendored fonts + the Liquid Glass design kit (do not hand-edit)
backend/
  api/
    main.py                 # FastAPI app: mounts /app, /labeler, APIs, assets, /healthz
    embodied/               # Temporal labeler dataset/bundle/segment API + LeRobot reader
    embodied_platform/      # Platform endpoints, RBAC + audit + job state machine,
                            #   schema.py (Pydantic), repository.py (JSON) / pg_repository.py
  tests/embodied/           # labeler-API tests
  tests/embodied_platform/  # platform API + e2e tests
  pyproject.toml            # deps + pytest config (testpaths = ["tests"])
tests/embodied-platform-audit.mjs   # static structure/design/localization audit (Node)
scripts/                    # run.sh, fix-push.sh, install-hooks.sh, backup/restore
.github/workflows/ci.yml    # the 7 required checks
.github/rulesets/main-protection.json   # server-side main protection (admin-applied)
```

## Setup (once per clone)

```bash
cd backend && python -m pip install -e ".[dev]" && cd ..
scripts/install-hooks.sh    # activates the pre-push guard (core.hooksPath is not cloned)
```

## Run it

```bash
./scripts/run.sh            # console: http://127.0.0.1:8099/app/  ·  labeler: /labeler/
```

Log in with a write role (e.g. `admin`) and the dev passcode `ground-control-dev` to
unlock live writes. With the backend stopped the SPA still runs in offline demo mode.

## Verify your change (run before you ship — CI runs all of this)

```bash
cd backend && python3 -m pytest tests -q        # ~235 pass, ~10 skipped (PG-gated) is the baseline
node tests/embodied-platform-audit.mjs          # from repo root: structural + localization audit
```

- Backend tests live under `backend/tests/embodied/` and `backend/tests/embodied_platform/`
  because `testpaths = ["tests"]`. **Do not** put tests under `backend/api/.../tests/` — they
  will not be collected. Issue bodies sometimes guess that path; the real one is `backend/tests/`.
- A new automated test that **fails before your fix and passes after** is expected for every
  bug/feature PR (it is part of the issue acceptance criteria).

## Shipping a change

Make your fix in the working tree **on `main`**, then:

```bash
scripts/fix-push.sh <slug> "<conventional-commit title>"
# e.g.
scripts/fix-push.sh queue-retry-log "fix(queue): log swallowed projection error"
```

`fix-push` runs a fast subset of CI locally (audit + JS syntax + backend JSON-store tests +
whitespace/bytecode hygiene), then cuts `fix/<slug>`, commits, pushes the **branch**, and
opens a PR into `main`. It never writes to `main`. CI is authoritative — the Postgres and
Docker jobs run on the PR, not locally.

**`fix-push` ships a one-line title via `--fill`.** The PR conventions below need a body, so
after it opens the PR, amend the commit to add the trailer and set the full PR body:

```bash
git commit --amend            # add a blank line + "Closes #<N>" + the Co-Authored-By trailer
git push -f origin fix/<slug> # the pre-push hook only blocks main, so force-push of a fix branch is fine
gh pr edit <N> --body-file <path-to-chinese-body.md>
```

### Pull-request conventions (match the existing issues/PRs exactly)

- **One PR per issue.** No unrelated drive-by changes; do not "improve" adjacent code.
- **Branch:** `fix/<slug>` for bug/security, `feat/<slug>` for feature/feature-gap.
- **Title:** Conventional Commits — `fix(api): …`, `feat(platform): …`, `docs(…): …`.
- **Body (Simplified Chinese):** state `Closes #<N>`, walk the fix, and **paste the actual
  output** of the commands in the issue's 验收标准 (acceptance criteria) as evidence.
- **Commit trailer:** end the commit message with a `Co-Authored-By:` line for the agent.
- A PR merges on **1 approving review + all 7 required checks green** (admins can bypass).

### Filing an issue (when you find a bug / gap / speedup)

Issues are detailed Simplified-Chinese reports. Match the in-repo format (see any open issue):
`## 问题概述 / ## 位置 (file:line) / ## 证据 / ## 影响 (state severity) / ## 建议修复 /
## 验收标准 (a checklist incl. a fail-before/pass-after test) / ## 提交格式要求`, then a footer
stamp. Label with exactly one of `bug` / `security` / `tech-debt` / `enhancement` /
`feature-gap` **plus** one `severity:critical|high|medium|low`. Before filing, check open
issues and in-flight PRs so you don't duplicate.

## The CI gate (what must be green to merge)

Seven required checks, all defined in `.github/workflows/ci.yml`; their names are mirrored
in `.github/rulesets/main-protection.json` (keep the two in sync — a renamed job that the
ruleset still requires never goes green and blocks every merge):

`repository hygiene` · `static frontend and design audit` ·
`backend tests (Python 3.11, JSON store)` · `backend tests (Python 3.13, JSON store)` ·
`backend tests (Postgres repository)` · `docker image build` · `docker runtime smoke`

Both storage backends (JSON file and Postgres 16) must agree before anything merges.

## Gotchas that bite agents

- **Never push to `main`** and never `git push --no-verify` to dodge the guard — the
  server-side ruleset still rejects it for non-admins.
- **Tests are under `backend/tests/`, not `backend/api/.../tests/`** (see above).
- **UI strings are Simplified Chinese.** The audit fails if you introduce English or
  medical/clinical copy, or break module wiring (`data-module` / `*-panel` / JS handler).
- **No SPA build step** — there is no bundler; edit `apps/**/assets/*.js|*.css` directly.
  Bump the `?v=` query and the service-worker `CACHE` name together when you change a cached asset.
- **The JSON store is single-instance** (file locks don't coordinate across hosts); use the
  Postgres path (`XINGJU_EMBODIED_PLATFORM_DSN`) for multi-replica. Tests must pass on both.
- **Don't commit `__pycache__`/`*.pyc` or trailing whitespace** — `repository hygiene` rejects them.

## Code style

- Python targets ≥3.11, typed FastAPI + Pydantic v2; match the surrounding style and keep
  changes surgical. Run `ruff check` before shipping (the lint gate is wired into CI/`fix-push`).
- Keep functions small and fail loud; the repo prefers explicit errors over silent fallbacks.
