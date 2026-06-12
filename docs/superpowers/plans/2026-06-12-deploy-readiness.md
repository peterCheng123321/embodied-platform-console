# Deploy Readiness Implementation Plan (Part A: single-instance deployable · Part B: Postgres repository)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the unified platform deployable beyond localhost — Part A removes the operational blockers for a single production instance (CDN independence, secrets, packaging, CI, backups); Part B replaces the single-host JSON store with a Postgres-backed repository behind the existing `read()/mutate()` interface, opening the path to multi-instance scale-out.

**Architecture:** Part A is pure packaging/ops — no behavior change, every page byte served locally. Part B adds `PgRepository` with the exact same interface as `JsonRepository` (whole-state read, transactional mutate), storing one JSONB row per collection with `SELECT … FOR UPDATE` serialization — row locks coordinate across hosts, writes become O(changed collections). Backend selection is by env var (`XINGJU_EMBODIED_PLATFORM_DSN` set → Postgres; unset → JSON file, today's default). The labeler's per-annotator JSONL segment files (`backend/api/embodied/`) are explicitly OUT of scope — they have their own ETag story.

**Tech Stack:** psycopg3 (sync + pool — routes are sync `def`, FastAPI threadpool), GitHub Actions (postgres:16 service container = the authoritative Postgres test runner; local has no Docker/PG), Caddy (auto-TLS reverse proxy), vanilla shell for vendoring/backup.

**Verification constraints (be honest about these):**
- Local machine has NO docker daemon and NO Postgres. Docker builds and PG tests are verified in CI (`gh run watch` after push). PG tests skip loudly locally with an explicit reason; the CI job is the gate.
- The live dev server on :8099 must keep working after every task (`curl /healthz`).

**Baseline:** branch `codex/first-person-collection-foundation` @ `d6b499b`, 186 tests green, audit green.

---

## Part A — deployable single instance

### Task A1: Vendor all CDN assets (China-deployability + offline integrity)

**Files:**
- Create: `scripts/vendor-assets.sh` (re-runnable downloader)
- Create (committed artifacts): `apps/_vendor/tailwind/tailwind-play.js`, `apps/_vendor/font-awesome/css/font-awesome.min.css` + `apps/_vendor/font-awesome/fonts/*`, `apps/_vendor/fonts/plex.css` + `apps/_vendor/fonts/woff2/*.woff2`
- Modify: `apps/embodied-labeler/index.html:9-13`, `apps/embodied-platform/index.html:9-11`
- Modify: `backend/api/main.py` (mount `/vendor` → `apps/_vendor`, guarded like the other mounts)
- Modify: `tests/embodied-platform-audit.mjs:266-270` (invert pins)

- [ ] **Step 1: Write the vendor script**

```bash
#!/usr/bin/env bash
# Downloads every third-party asset the two SPAs reference, so production
# serves zero bytes from external CDNs (Google Fonts is unreachable from
# mainland China; this is a zh-CN product). Re-runnable; overwrites in place.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
V="$ROOT/apps/_vendor"
UA="Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/126 Safari/537.36"  # fonts.googleapis returns woff2 css only for modern UAs

mkdir -p "$V/tailwind" "$V/font-awesome/css" "$V/font-awesome/fonts" "$V/fonts/woff2"

# 1. Tailwind Play CDN script (self-contained JIT compiler, works offline)
curl -fsSL https://cdn.tailwindcss.com -o "$V/tailwind/tailwind-play.js"

# 2. Font Awesome 4.7 css + the font files its css references
curl -fsSL https://cdn.jsdelivr.net/npm/font-awesome@4.7.0/css/font-awesome.min.css -o "$V/font-awesome/css/font-awesome.min.css"
for f in fontawesome-webfont.woff2 fontawesome-webfont.woff fontawesome-webfont.ttf; do
  curl -fsSL "https://cdn.jsdelivr.net/npm/font-awesome@4.7.0/fonts/$f" -o "$V/font-awesome/fonts/$f"
done

# 3. Google Fonts css2 (Plex Mono 400/500/600 + Plex Sans SC 300-700) + every woff2 it references
CSS_URL='https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans+SC:wght@300;400;500;600;700&display=swap'
curl -fsSL -A "$UA" "$CSS_URL" -o "$V/fonts/plex.orig.css"
# rewrite each fonts.gstatic.com url to a local file named by its sha1, downloading as we go
python3 - "$V" <<'PY'
import hashlib, pathlib, re, sys, urllib.request
v = pathlib.Path(sys.argv[1]) / "fonts"
css = (v / "plex.orig.css").read_text()
def fetch(m):
    url = m.group(1)
    name = hashlib.sha1(url.encode()).hexdigest()[:16] + ".woff2"
    dest = v / "woff2" / name
    if not dest.exists():
        urllib.request.urlretrieve(url, dest)
    return f"url(woff2/{name})"
out = re.sub(r"url\((https://fonts\.gstatic\.com/[^)]+)\)", fetch, css)
(v / "plex.css").write_text(out)
print(f"plex.css: {len(re.findall(r'woff2/', out))} font files vendored")
PY
rm "$V/fonts/plex.orig.css"
echo "vendored: $(find "$V" -type f | wc -l | tr -d ' ') files, $(du -sh "$V" | cut -f1)"
```

- [ ] **Step 2: Run it** — `bash scripts/vendor-assets.sh`. Expected: file count ≥ 60 (Plex Sans SC has many CJK unicode-range subsets), total size single-digit MB. Spot-check: `head -c 200 apps/_vendor/fonts/plex.css` shows `url(woff2/….woff2)`, no `gstatic`.
- [ ] **Step 3: Mount `/vendor` in `backend/api/main.py`** next to the existing guarded mounts (same idiom as `/labeler`):

```python
vendor_dir = _REPO_ROOT / "apps" / "_vendor"
if vendor_dir.is_dir():
    app.mount("/vendor", StaticFiles(directory=vendor_dir), name="vendor")
else:  # pragma: no cover
    logger.warning("vendor assets missing at %s — run scripts/vendor-assets.sh", vendor_dir)
```

(Use the file's actual repo-root variable — read the existing mount block and match it.)
- [ ] **Step 4: Rewrite the HTML refs.** Labeler `index.html` lines 9–13 →

```html
    <script src="/vendor/tailwind/tailwind-play.js"></script>
    <link href="/vendor/font-awesome/css/font-awesome.min.css" rel="stylesheet">
    <link href="/vendor/fonts/plex.css" rel="stylesheet">
```

Platform `index.html` lines 9–11 → `<link rel="stylesheet" href="/vendor/fonts/plex.css">` (drop both preconnects).
- [ ] **Step 5: Invert the audit pins** (lines ~266–270): replace the two `assert.match(html, /IBM\+Plex…/)` Google-URL pins with:

```javascript
assert.match(html, /\/vendor\/fonts\/plex\.css/, 'platform must load the vendored Plex css (no external font CDN)');
assert.doesNotMatch(`${html}\n${labelerHtml}`, /fonts\.googleapis|fonts\.gstatic|cdn\.tailwindcss|cdn\.jsdelivr/, 'no external CDN references — must be deployable behind the GFW');
assert.match(labelerHtml, /\/vendor\/tailwind\/tailwind-play\.js/, 'labeler must load the vendored tailwind runtime');
```

Keep the Chakra-absence pins (270/274/275) untouched.
- [ ] **Step 6: Verify** — `node tests/embodied-platform-audit.mjs` green; `cd backend && python3 -m pytest tests -q` green (mount test may read served HTML); restart :8099 server, `curl -s http://127.0.0.1:8099/vendor/fonts/plex.css | head -c 100` is css; load `/labeler/` in Chrome and confirm icons + CJK font render (screenshot).
- [ ] **Step 7: Commit** — `feat(deploy): vendor tailwind/font-awesome/plex assets — zero external CDN bytes (GFW-safe)` (stage `scripts/vendor-assets.sh apps/_vendor backend/api/main.py apps/embodied-labeler/index.html apps/embodied-platform/index.html tests/embodied-platform-audit.mjs`).

### Task A2: Secrets out of the run script

**Files:** Modify: `scripts/run.sh`; Create: `.env.example`

- [ ] **Step 1:** Replace the unconditional dev exports in `scripts/run.sh` with respect-if-set + loud ephemeral fallback:

```bash
# Secrets: respect the environment; generate an EPHEMERAL secret otherwise so
# dev keeps working — but warn loudly, because sessions die with the process.
if [ -z "${XINGJU_EMBODIED_PLATFORM_AUTH_SECRET:-}" ]; then
  export XINGJU_EMBODIED_PLATFORM_AUTH_SECRET="ephemeral-$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  echo "[run] WARNING: XINGJU_EMBODIED_PLATFORM_AUTH_SECRET not set — generated an ephemeral dev secret (sessions reset on restart). Set it for any real deployment." >&2
fi
if [ -z "${XINGJU_EMBODIED_PLATFORM_LOGIN_PASSCODE:-}" ]; then
  export XINGJU_EMBODIED_PLATFORM_LOGIN_PASSCODE="ground-control-dev"
  echo "[run] WARNING: using the default dev passcode 'ground-control-dev'. Set XINGJU_EMBODIED_PLATFORM_LOGIN_PASSCODE for any real deployment." >&2
fi
```

Keep the data-root exports as-is (paths, not secrets).
- [ ] **Step 2:** `.env.example` documenting every `XINGJU_*` var with one-line comments (secret, passcode, CORS, data roots, dataset root, and Part B's `XINGJU_EMBODIED_PLATFORM_DSN` marked "Part B, optional").
- [ ] **Step 3:** Verify: `bash -n scripts/run.sh`; restart server, login via curl with `ground-control-dev` still works (200); warnings visible in `/tmp/embodied-platform-8099.log`.
- [ ] **Step 4:** Commit — `feat(deploy): env-respecting secrets in run.sh + .env.example (ephemeral dev fallback, loud warnings)`.

### Task A3: State backup/restore

**Files:** Create: `scripts/backup-state.sh`, `scripts/restore-state.sh`

- [ ] **Step 1:** `backup-state.sh` — tar `backend/data/` (JSON store + labeler annotations + cache exclusion) to `backups/state-YYYYmmdd-HHMMSS.tar.gz`, prune to last 14:

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-$ROOT/backups}"; mkdir -p "$DEST"
STAMP="$(date +%Y%m%d-%H%M%S)"
tar -czf "$DEST/state-$STAMP.tar.gz" -C "$ROOT/backend" --exclude='data/embodied_cache' data
ls -1t "$DEST"/state-*.tar.gz | tail -n +15 | xargs rm -f 2>/dev/null || true
echo "backup: $DEST/state-$STAMP.tar.gz ($(du -h "$DEST/state-$STAMP.tar.gz" | cut -f1))"
```

`restore-state.sh "$1"` — refuses without an explicit tarball arg, untars into `backend/` after moving the current `data` to `data.pre-restore-$STAMP`.
- [ ] **Step 2:** Verify round-trip: run backup; `tar -tzf` lists `data/embodied_platform/state.json`; restore into a temp copy and diff. Add `backups/` to `.gitignore`.
- [ ] **Step 3:** Commit — `feat(deploy): state backup/restore scripts (14-day rotation, cache excluded)`.

### Task A4: Dockerfile + compose + Caddy TLS proxy

**Files:** Create: `Dockerfile`, `docker-compose.yml`, `deploy/Caddyfile`, `.dockerignore`

- [ ] **Step 1: Dockerfile** (python:3.13-slim; ffmpeg needed by the materializer):

```dockerfile
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY backend/pyproject.toml backend/pyproject.toml
RUN pip install --no-cache-dir -e backend 2>/dev/null || true
COPY backend backend
COPY apps apps
COPY scripts scripts
RUN pip install --no-cache-dir -e backend
ENV XINGJU_EMBODIED_PLATFORM_DATA_ROOT=/srv/backend/data/embodied_platform \
    XINGJU_EMBODIED_DATA_ROOT=/srv/backend/data/embodied \
    XINGJU_EMBODIED_CACHE_ROOT=/srv/backend/data/embodied_cache
EXPOSE 8099
HEALTHCHECK --interval=30s --timeout=3s CMD python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8099/healthz')"
CMD ["bash", "scripts/run.sh"]
```

- [ ] **Step 2: docker-compose.yml** — `app` (build ., volume `state:/srv/backend/data`, env from `.env`, no published port) + `caddy` (caddy:2-alpine, ports 80/443, `./deploy/Caddyfile:/etc/caddy/Caddyfile`, volumes for caddy data). `deploy/Caddyfile`:

```
{$XINGJU_DOMAIN:localhost} {
    reverse_proxy app:8099
    encode gzip
}
```

- [ ] **Step 3:** `.dockerignore`: `.git`, `backups/`, `backend/data/`, `**/__pycache__`, `.pytest_cache`, `docs/`.
- [ ] **Step 4:** Verify what's verifiable locally: `bash -n` n/a; `docker` daemon absent — note in commit body that the image build is verified by CI (Task A5's `docker-build` job). `python3 -c "import yaml,sys;yaml.safe_load(open('docker-compose.yml'))"` parses.
- [ ] **Step 5:** Commit — `feat(deploy): Dockerfile + compose + caddy auto-TLS proxy (image build verified in CI)`.

### Task A5: GitHub Actions CI

**Files:** Create: `.github/workflows/ci.yml`

- [ ] **Step 1:**

```yaml
name: ci
on:
  push: {branches: [main, 'codex/**']}
  pull_request:
jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: '3.13'}
      - run: pip install -e 'backend[dev]'
      - run: cd backend && python -m pytest tests -q
  static-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: {node-version: '22'}
      - run: node tests/embodied-platform-audit.mjs
  docker-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t embodied-platform-console:ci .
```

(Part B's Task B4 appends the `backend-postgres` job to this file.)
- [ ] **Step 2:** Push and verify: `git push … && gh run watch --repo peterCheng123321/embodied-platform-console --exit-status` (or poll `gh run list`). ALL three jobs must pass — the docker-build job is the Dockerfile's verification.
- [ ] **Step 3:** Commit (the workflow itself) — `feat(ci): pytest + static audit + docker image build on every push`.

### Task A6: README deployment section
- [ ] Add "Deploying" section: `.env` from `.env.example`, `docker compose up -d`, set `XINGJU_DOMAIN`, backups via cron of `scripts/backup-state.sh`, single-instance-only warning (until Part B), data lives in the `state` volume. Verify audit still green (it may read README). Commit — `docs: deployment runbook`.

---

## Part B — Postgres-backed repository

### Design (read this before any B task)
`JsonRepository`'s public surface used by routes/event_routes: `read() -> dict`, `mutate(fn) -> Any` (fn receives the whole state dict, return value passed through), `write(state)`. Collections are the dict's top-level keys (recognized-key whitelist in `repository.py`). `PgRepository` keeps that surface. Storage:

```sql
CREATE TABLE IF NOT EXISTS embodied_platform_state (
    collection text PRIMARY KEY,
    doc        jsonb NOT NULL DEFAULT '[]'::jsonb,
    version    bigint NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now()
);
```

`read()`: one `SELECT collection, doc` → assemble dict (missing collections → `empty_state()` defaults). `mutate(fn)`: one transaction — `SELECT collection, doc FROM embodied_platform_state FOR UPDATE` (row locks serialize writers ACROSS HOSTS), assemble state, deepcopy-compare per collection after running `fn`, `INSERT … ON CONFLICT (collection) DO UPDATE SET doc=…, version=version+1` only for changed collections, commit. Non-finite scrub and key whitelist behavior must match the JSON implementation (reuse its helpers — import them, don't copy).

### Task B1: Contract test extraction (shared between both backends)

**Files:** Create: `backend/tests/embodied_platform/repository_contract.py`; Modify: `backend/tests/embodied_platform/test_repository_robustness.py` (keep json-specific tests there)

- [ ] **Step 1:** Extract the backend-agnostic assertions from the existing repository tests into functions taking a `make_repo` factory: round-trip read/mutate, mutate return passthrough, unknown-key dropped, non-list coercion, mutate isolation (two sequential mutates compose), empty-state defaults.

```python
# repository_contract.py — shared behavioral contract for state repositories.
# Each function takes a zero-arg factory returning a FRESH repository view
# over the SAME underlying store (file path or DSN).
def contract_roundtrip(make_repo):
    repo = make_repo()
    def add(state):
        state["datasets"].append({"id": "ds_c1", "name": "contract"})
        return "rv"
    assert repo.mutate(add) == "rv"
    assert any(d["id"] == "ds_c1" for d in make_repo().read()["datasets"])
```

(…one function per behavior; port the real assertions from the existing tests, do not invent new semantics.)
- [ ] **Step 2:** Wire the existing JSON tests to call the contract functions (so the contract is proven against today's behavior FIRST). Full suite stays green: `python3 -m pytest tests -q` → 186 (count must not drop). Commit — `test(platform): extract backend-agnostic repository contract`.

### Task B2: PgRepository + selection factory

**Files:** Create: `backend/api/embodied_platform/pg_repository.py`; Modify: `backend/api/embodied_platform/repository.py` (add `get_repository()` factory), `backend/pyproject.toml` (add `psycopg[binary,pool]>=3.2`), call sites that construct `JsonRepository` directly (grep `JsonRepository(` in routes.py/event_routes.py — route through the factory).

- [ ] **Step 1 (failing tests first):** `backend/tests/embodied_platform/test_pg_repository.py`:

```python
import os, pytest
DSN = os.environ.get("XINGJU_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(
    not DSN,
    reason="XINGJU_TEST_PG_DSN unset — Postgres repository tests run in CI (backend-postgres job); "
           "set a disposable DSN to run locally. THIS SKIP IS EXPECTED LOCALLY.",
)
# fixtures: create schema in a throwaway database/schema per test, drop after.
# Tests: every repository_contract function against PgRepository, plus:
#  - two PgRepository instances on the same DSN: interleaved mutates never lose updates
#  - version column increments only for changed collections
#  - corrupt doc (manually UPDATE doc='"not a list"') -> read() coerces like JsonRepository
```

- [ ] **Step 2:** Implement `pg_repository.py` (psycopg3 sync, `ConnectionPool`, `ensure_schema()` on init, mutate as designed above — reuse `empty_state`, `_RECOGNIZED_KEYS`-equivalent and scrub helpers imported from `repository.py`).
- [ ] **Step 3:** Factory in `repository.py`:

```python
def get_repository():
    dsn = os.environ.get("XINGJU_EMBODIED_PLATFORM_DSN", "").strip()
    if dsn:
        from .pg_repository import PgRepository
        return PgRepository(dsn)
    return JsonRepository()
```

Route construction sites switch to `get_repository()`. JSON path must remain byte-identical in behavior — full suite green WITHOUT the env var.
- [ ] **Step 4:** Local verify: `python3 -m pytest tests -q` → all green, pg tests reported as SKIPPED with the loud reason (count them: `-rs` flag, expect the skip block listed). Commit — `feat(platform): PgRepository (jsonb-per-collection, FOR UPDATE cross-host serialization) behind env-selected factory`.

### Task B3: Full suite against Postgres in CI

**Files:** Modify: `.github/workflows/ci.yml` (append job), possibly `backend/tests/embodied_platform/conftest.py` (state-reset fixture must TRUNCATE the pg table when DSN is set — mirror how the json tests get a fresh store).

- [ ] **Step 1:** Append to ci.yml:

```yaml
  backend-postgres:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env: {POSTGRES_PASSWORD: ci, POSTGRES_DB: xingju_ci}
        ports: ['5432:5432']
        options: >-
          --health-cmd "pg_isready -U postgres" --health-interval 5s
          --health-timeout 5s --health-retries 10
    env:
      XINGJU_TEST_PG_DSN: postgresql://postgres:ci@localhost:5432/xingju_ci
      XINGJU_EMBODIED_PLATFORM_DSN: postgresql://postgres:ci@localhost:5432/xingju_ci
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: '3.13'}
      - run: pip install -e 'backend[dev]'
      - run: cd backend && python -m pytest tests -q -rs
```

This runs the ENTIRE suite (all 186+ route tests) against PgRepository plus the pg-specific tests — same behavior on both backends is the acceptance bar.
- [ ] **Step 2:** Test isolation: route tests assume a fresh store per test (json: tmp path). With DSN set, add an autouse fixture in conftest that `TRUNCATE embodied_platform_state` between tests. Iterate in CI until green (`gh run watch`); expect this step to surface real ordering/reset bugs — fix them, don't skip them.
- [ ] **Step 3:** Commit — `ci: run the full platform suite against postgres:16 (service container) — both backends must agree`.

### Task B4: Compose + docs for Postgres mode
- [ ] Add commented `postgres:` service + `XINGJU_EMBODIED_PLATFORM_DSN` to `docker-compose.yml` and `.env.example`; README: "Scaling out" section — DSN set → N replicas safe; JSON mode → exactly one instance; note event-ingest retention as a known follow-up. Commit — `docs(deploy): postgres mode + scale-out runbook`.

---

## Out of scope (explicitly, so nobody scope-creeps)
- OIDC/SSO, per-user accounts, tenancy, rate limiting (identity workstream — separate plan).
- Alembic migrations (single CREATE TABLE bootstrap is enough until a second schema change exists).
- Labeler JSONL segment storage, object storage for media, worker queue for ffmpeg.
- Event retention/pruning.

## Self-review
- Spec coverage: A1–A6 = vendored assets/secrets/backups/Docker+TLS/CI/docs ✓; B1–B4 = contract, implementation, CI-pg, runbook ✓.
- No placeholders: every code step has real content; B2's implementation details are constrained by B1's contract + the design block.
- Verification honesty: docker + pg verified in CI only — stated three times deliberately.
