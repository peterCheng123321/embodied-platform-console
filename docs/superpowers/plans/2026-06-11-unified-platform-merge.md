# Unified Platform Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One functional web app — the Embodied Platform Console at `:8099` — absorbing every unique-value piece from the three codebases, with dead code removed and one design language.

**Architecture:** `embodied-platform-console` (FastAPI serving `/app/` SPA + `/labeler/` + all APIs same-origin, zero-infra JSON store) is the unified home. The `projects` repo becomes a committed redirect shell + design-history archive. The `codex/embodied-platform` branch's unique backend value (security hardening, real LeRobot ingest, dataset QC gate, tests) is ported into the console; its frontend annotation studio and `ml/` tree are preserved on the branch and explicitly NOT ported (the hosted labeler is the single annotation surface). Design aligns on the XINGJU "Clinical Precision" palette (deep teal `#0d4f4a` + signal coral `#ff5a36`, IBM Plex Sans SC/Mono), light for the ops console, dark `.console`-scope for the labeler.

**Tech Stack:** FastAPI + Pydantic v2 + pyarrow (no DB), vanilla no-build JS SPA, pytest + node static audits.

**Repos:**
- CONSOLE = `/Users/peter/Downloads/project/embodied-platform-console` (branch `codex/first-person-collection-foundation`, single commit `e3c010e`, ALL unification currently uncommitted)
- PROJECTS = `/Users/peter/Downloads/project/projects` (branch `embodied/labeler` @ `3a5ea2d` + uncommitted retirement WIP, 47 paths)
- CODEX_WT = `/Users/peter/.config/superpowers/worktrees/projects/codex-embodied-platform` (branch `codex/embodied-platform` @ `7fd4191` + ~1,278 uncommitted lines)

**Baseline (verified 2026-06-11):** console backend `python3 -m pytest tests -q` → 100 passed; `node tests/embodied-platform-audit.mjs` → pass; projects `node tests/embodied-design-audit.mjs` → pass; projects backend tests need Postgres (being retired). Live uvicorn PID serving :8099 from console working tree — must be restarted at the end.

**Explicitly decided (flagged per CLAUDE.md Rule 7 — surface, don't average):**
1. Console repo wins as home (most recent, tested, already serves everything same-origin). The codex branch's *frontend* annotation studio, frame-sequence viewer, media fixtures, and `ml/` tree are NOT ported — the hosted labeler is the one annotation surface. They remain recoverable on branch `codex/embodied-platform`.
2. The orphaned Postgres events stack in PROJECTS (zero consumers ever; console ships a contract-compatible JSON-backed `/v1/events`) is deleted as dead code; recoverable at tag `archive/standalone-platform`.
3. Design direction: XINGJU teal/coral everywhere; the platform SPA's "Azure" blue is re-bound at the token layer (its `--st-ok` blue → real green-teal — semantic fix). Labeler keeps its spec'd dark mission-console chassis (deliberate, documented design with CJK 13px floor) — alignment means shared brand/semantic colors + fonts, not flattening light/dark.
4. f4c09c9's landing-page CSS fixes are MOOT (that page is retired to a redirect stub); its five behavioral labeler fixes are re-ported by hand into the current-era labeler (a cherry-pick cannot apply — code drifted).

---

## Phase A — Pin & protect (nothing is safe until these commits exist)

### Task A1: Commit the console working tree (the entire unified platform is uncommitted)

**Files:** all 13 modified + 10 untracked paths in CONSOLE.

- [ ] **Step 1: Re-snapshot and confirm no concurrent mutation**

Run twice, 5s apart; outputs must match:
```bash
cd /Users/peter/Downloads/project/embodied-platform-console && git status --porcelain | sort | shasum
sleep 5 && git status --porcelain | sort | shasum
```
Expected: identical hashes. If not, STOP and report.

- [ ] **Step 2: Verify green before committing**
```bash
cd backend && python3 -m pytest tests -q && cd .. && node tests/embodied-platform-audit.mjs
```
Expected: `100 passed`, `Embodied platform audit passed`.

- [ ] **Step 3: Verify nothing generated gets committed**
```bash
git status --porcelain | grep -E '__pycache__|\.pytest_cache|backend/data/' || echo CLEAN
```
Expected: `CLEAN` (gitignore covers them).

- [ ] **Step 4: Commit**
```bash
git add -A
git commit -m "feat: unified platform baseline — hosted labeler, embodied API, event ingest, first-person collection

- apps/embodied-labeler/: temporal labeler hosted same-origin at /labeler/ (api-base meta empty -> window.location.origin)
- backend/api/embodied/: dataset/episode/segment API + lerobot_reader + episode_materializer + NEW qc.py annotator scoring + /qc endpoint
- backend/api/embodied_platform/event_routes.py: /v1/events/{label,telemetry} JSON-backed replacement for the retired Postgres ingest (same batch contract, event_id idempotency)
- collection foundation: first_person_trial_v1 profile, runs/attempts/review/progress + SPA collection module
- tests: embodied suite ported + test_qc_routes, collection foundation + adversarial agents, event ingest compat, unified labeler mount
Baseline: backend 100 passed; static audit green."
```

### Task A2: Commit the projects retirement WIP

- [ ] **Step 1: Re-snapshot stability (same two-hash check as A1.1) in PROJECTS**
- [ ] **Step 2: Verify the migration audit**
```bash
cd /Users/peter/Downloads/project/projects && node tests/embodied-design-audit.mjs
```
Expected: `Embodied migration audit passed`.
- [ ] **Step 3: Tag the pre-retirement tip for recovery, then commit**
```bash
git tag archive/standalone-platform 3a5ea2d
git add -A
git commit -m "feat: retire standalone frontends to unified-platform redirects

index.html/ops.html -> http://127.0.0.1:8099/app/ (hash carried); embodied.html -> /labeler/ (dataset/episode params carried).
Deletes assets/{annotation,console,embodied}, backend/api/embodied, backend/tests/embodied, prep script, 4 retired audits.
Full pre-retirement tree preserved at tag archive/standalone-platform (3a5ea2d)."
```

### Task A3: Commit the codex worktree's uncommitted hardening

- [ ] **Step 1:**
```bash
cd /Users/peter/.config/superpowers/worktrees/projects/codex-embodied-platform
git add -A && git commit -m "chore(embodied-platform): commit white-team hardening WIP — global search, _valid_rows reads, ingest/qc/repository hardening, +tests, adjudication doc

Preservation commit: this branch is the archive of the codex platform variant; unique backend value is being ported to embodied-platform-console, frontend studio + ml/ intentionally remain here."
```

## Phase B — Port codex-unique backend value into the console

Reference for every task: diff the codex file against the console file and apply the codex-side hunks named below. Codex paths under CODEX_WT, console paths under CONSOLE.

### Task B1: Security hardening in `backend/api/embodied_platform/routes.py`

**Port from codex `backend/api/embodied_platform/routes.py`:**
1. `_canonical_principal_message()` — length-prefixed injective HMAC encoding (codex ~133-147). Console currently signs collidable `f"{actor}:{role}"` (`sign('a','b:c') == sign('a:b','c')`).
2. Authn-before-authz: verify HMAC signature BEFORE role membership check (codex ~91-113) so unauthenticated callers can't probe role sets.
3. `hmac.compare_digest` on encoded bytes for signature AND passcode (non-ASCII input → 403, not 500).
4. `_valid_rows()` validated list reads; `_coerce_system_settings` + `SystemSettingsPatch`; `_scrub_non_finite` + `RequestValidationError` handler with `register_validation_handlers(app)` wired in `main.py`.

- [ ] **Step 1: Port the failing tests first** — extract the matching tests from codex `backend/tests/embodied_platform/test_embodied_platform.py` (HMAC collision test, unauthenticated-role-probe test, non-ASCII signature/passcode tests, non-finite payload tests, settings-patch tests) into a NEW console file `backend/tests/embodied_platform/test_hardening.py`. Adapt fixture names to console's conftest.
- [ ] **Step 2:** `python3 -m pytest tests/embodied_platform/test_hardening.py -q` → expect FAILURES (collision test fails against `f"{actor}:{role}"`).
- [ ] **Step 3:** Apply hunks 1–4 to console routes.py/schema.py/main.py. Session-issued signatures change value — that's fine (sessions are minted per login; SPA stores whatever `/session` returns).
- [ ] **Step 4:** `python3 -m pytest tests -q` → ALL pass (100 baseline + new).
- [ ] **Step 5:** Commit `fix(platform): port codex security hardening — injective HMAC canonicalization, authn-before-authz, bytes compare_digest, validated reads, non-finite scrub`.

### Task B2: Repository + schema robustness

**Port from codex `repository.py`:** corrupt/non-dict state → `empty_state()` with warning; read-only-root fallback for shared reads; recognized-key whitelist + non-list coercion; `json.dump(..., allow_nan=False)`; `_LOCKS.setdefault(resolved, RLock())` (TOCTOU nit). **From codex `schema.py`:** `ModelVersionCreate` metrics hardening (`allow_inf_nan=False`, 100-key cap, 128-char key cap).

- [ ] **Step 1:** Port matching codex tests into `backend/tests/embodied_platform/test_repository_robustness.py`; run → fail.
- [ ] **Step 2:** Apply; keep console's 5 collection collections in the whitelist (`collection_profiles, collection_runs, collection_attempts, label_events, telemetry_events`).
- [ ] **Step 3:** Full suite green. Commit `fix(platform): repository corrupt-state/read-only/allow_nan handling + metrics caps`.

### Task B3: Real LeRobot import + dataset QC gate

**Port wholesale (new files):** codex `backend/api/embodied_platform/ingest.py` (284 lines: `parse_lerobot_root`, file:// URI, traversal guards, 1 MiB info.json cap, 100k episode cap), codex `backend/api/embodied_platform/qc.py` (461 lines: dataset QC — distinct from the labeler-scoring `embodied/qc.py`), codex tests `test_ingest.py`, `test_qc.py`, `fixtures/lerobot_demo/`.
**Port into console routes.py:** `SUPPORTED_IMPORT_FORMATS = {"lerobot"}` guard; `POST /imports` parses + `_ensure_dataset`/`_materialize_episodes` (console's currently only records the job — keep its status-PATCH flow on top); `GET /datasets/{id}/qc`; `POST /datasets/{id}/trained-ready` with `_assert_qc_passes`/`_gate_failure_reasons`.
**Perf fix from the earlier verified review:** run `parse_lerobot_root()` BEFORE `repo.mutate()`, pass the result into the mutator (do not hold the write lock during filesystem parsing).

- [ ] **Step 1:** Copy `ingest.py`, `qc.py`, tests, fixtures. Run ported tests → import errors/failures expected.
- [ ] **Step 2:** Wire routes; parse-outside-mutate; audit events for import/qc/trained-ready mutations (match console's audit pattern).
- [ ] **Step 3:** Full suite green. Commit `feat(platform): real lerobot import + dataset QC gate + trained-ready (ported from codex branch, parse moved outside write lock)`.

### Task B4: Service-worker media/Range bypass

**File:** `CONSOLE/apps/embodied-platform/sw.js`. Port codex sw.js guard (~15 lines): never `respondWith()` requests with `Range` header or `destination` in `{video, audio}` — pass through to network. Bump `CACHE` `embodied-platform-v13` → `v14` and asset query `?v=12` → `?v=13` in sw precache list AND `index.html` asset tags together.

- [ ] **Step 1:** Apply; grep `tests/embodied-platform-audit.mjs` for pinned versions/sw assertions and update pins in the same change.
- [ ] **Step 2:** `node tests/embodied-platform-audit.mjs` green. Commit `fix(spa): sw bypasses media/range requests; cache bump v14`.

## Phase C — f4c09c9 behavioral fixes re-ported into the hosted labeler

**File:** `CONSOLE/apps/embodied-labeler/assets/embodied/embodied.js` (current era — JKL machine, `isEditableTarget` at ~83, stepFrame ~294, digit handler ~734, renderLanes tooltip ~943, saveAll ~2000, Cmd+S ~2147). A cherry-pick of f4c09c9 WILL NOT APPLY; re-implement each in current handlers. View original rationale: `git -C /Users/peter/Downloads/project/projects show f4c09c9`.

### Task C1: stepFrame pauses playback first (NLE convention)
- [ ] In `stepFrame(delta)` add as first lines:
```javascript
if (!video.paused) {
    video.pause();
    syncPlayButton(false);
}
```
(If JKL shuttle state must also reset, call the existing JKL pause helper used at ~383-391 instead — match current idiom.)

### Task C2: Hoist `computeIouMatches()` out of the renderLanes per-segment loop
- [ ] Before the `state.segments.forEach` loop:
```javascript
const iouByIdForLanes = GOLD_SEGMENTS.length ? computeIouMatches() : null;
```
and replace the per-segment `computeIouMatches().get(seg.id)` (~943) with `iouByIdForLanes.get(seg.id)` guarded on `iouByIdForLanes`.

### Task C3: Manual save guards on `state.pendingStart`
- [ ] In `saveAll()` (both Cmd+S and button paths flow through it), after the in-flight guard:
```javascript
if (state.pendingStart !== null) {
    if (!auto) showToast('片段未关闭 — 按 O 或 S 标记结束后再保存', 'info');
    return;
}
```
(Auto-save already defers via `scheduleAutoSave` at ~1443 — this restores symmetry for manual saves.)

### Task C4: Cmd/Ctrl+digit no longer hijacks browser tab-switch
- [ ] In the digit-hotkey handler (~734): `if (e.metaKey || e.ctrlKey) return;` before the `Digit[1-9]` match.

### Task C5: Focused buttons keep native Space activation; Cmd+S works from inputs
- [ ] Where global keydown handlers call `isEditableTarget(e)` for Space/transport hotkeys, also return early when `e.target.closest('button')` (mirror the existing seg-list handler at ~1747). Do NOT add the button check to the digit handler (digits over a focused button are fine).
- [ ] Remove the `isEditableTarget` gate from the Cmd+S handler (~2147) so ⌘S saves from any focus context (f4c09c9 rationale: save must always work; preventDefault stops the browser dialog).

### Task C6: Version bump + pins + verify
- [ ] Bump `embodied.js?v=26` → `?v=27` in `apps/embodied-labeler/index.html`. Update `backend/tests/embodied_platform/test_unified_labeler_mount.py` (it literally asserts `embodied.js?v=26`).
- [ ] Add static pins to `tests/embodied-platform-audit.mjs`: regex for the pendingStart guard inside saveAll, the metaKey/ctrlKey digit guard, and the hoisted `iouByIdForLanes`.
- [ ] `python3 -m pytest tests -q` + `node tests/embodied-platform-audit.mjs` green.
- [ ] Commit `fix(labeler): re-port f4c09c9 behavioral fixes — pause-on-step, IoU hoist, pendingStart save guard, cmd-digit guard, button-focus hotkeys, ungated cmd+s (v27)`.

## Phase D — Design alignment (XINGJU teal, one semantic palette)

### Task D1: Re-bind the platform SPA tokens from Azure blue to Clinical Precision teal

**File:** `CONSOLE/apps/embodied-platform/assets/embodied-platform.css` `:root` (lines ~9-38). Value-level alignment (names stay — lowest-risk; namespace merge is out of scope):
```css
--bg: #f7faf9;            /* was #f4f7fb  blue-tint -> teal-tint paper   */
--surface: #ffffff;
--surface-2: #f6f7f7;     /* was #eef3fa                                  */
--surface-3: #eef2f1;     /* was #e3ecf7                                  */
--hairline: rgba(13, 79, 74, 0.14);        /* was #d8e2f0                 */
--hairline-strong: rgba(13, 79, 74, 0.26); /* was #c2d2e8                 */
--ink: #16201f;           /* was #0f2747                                  */
--ink-muted: #5e6e6b;     /* was #51617d                                  */
--ink-faint: #8a9996;     /* was #8595b0                                  */
--brand: #0d4f4a;         /* was #1e40af — XINGJU deep teal               */
--brand-lum: #1f7a6b;     /* was #2563eb                                  */
--brand-glow: rgba(13, 79, 74, 0.16);
--accent: #ff5a36;        /* NEW — signal coral, sparingly (active rail,  */
                          /* wordmark tick); never for status             */
--st-neutral: #64748b;
--st-info: #0d6e8a;       /* was #0ea5e9 — teal-leaning info              */
--st-ok: #1f7a6b;         /* was #2563eb — SEMANTIC FIX: ok is green-teal,*/
                          /* not blue                                     */
--st-warn: #b56b00;       /* was #d97706 — match landing-system warn      */
--st-danger: #d92d20;     /* was #dc2626                                  */
```
- [ ] **Step 1:** Apply token re-bind. Grep the file for hardcoded `#1e40af|#2563eb|rgba(37, 99, 235` outside `:root` and re-point to tokens.
- [ ] **Step 2:** Font accent: replace `--font-accent: "Chakra Petch"` with `"IBM Plex Mono"` and remove the Chakra Petch `<link>` from `apps/embodied-platform/index.html` (one less divergent font; rail-title tracking idiom already mono).
- [ ] **Step 3:** Title/wordmark: `具身平台运营台` → `星聚 · 具身平台运营台` in `index.html` `<title>` + header wordmark element.
- [ ] **Step 4:** Bump sw assets `?v=13` → `?v=14`, CACHE `v14` → `v15` (versions move together; update audit pins).
- [ ] **Step 5:** `node tests/embodied-platform-audit.mjs` + screenshot `/app/` (preview tools) — verify teal chrome, green-teal OK chips, no leftover blue accents. Commit `feat(design): align platform SPA to XINGJU Clinical Precision palette (teal brand, semantic ok/warn/danger, Plex-only fonts)`.

### Task D2: Tokenize state-color leaks in the labeler chassis

**Files:** `CONSOLE/apps/embodied-labeler/assets/console/console.css` (hardcoded `#7ec98f/#d98c5f/#7b9ec9/#24303c`), `assets/embodied/embodied.css` (emerald `rgba(16,185,129)/rgb(52,211,153)` save-pulse).
- [ ] Define in console.css `.console` scope: `--ds-state-pass: #7ec98f; --ds-state-risk: #d98c5f; --ds-state-assign: #7b9ec9; --ds-row-selected: #24303c;` and replace the hex usages with `var(...)` (values unchanged — pure tokenization).
- [ ] Re-point the embodied.css save-pulse emeralds at the teal system: `rgba(31,122,107,*)` (`--ds-ok`-equivalent) keeping alphas.
- [ ] Bump `embodied.css?v=29`→`30`, `console.css?v=2`→`3` in `apps/embodied-labeler/index.html`; update any pins. Audit + visual check of labeler save pulse. Commit `chore(design): tokenize chassis state colors; save-pulse joins teal palette`.

## Phase E — Dead code removal

### Task E1: PROJECTS — delete the orphaned Postgres events stack

Zero consumers ever (verified: no fetch to `/v1/events` in any frontend at HEAD or tip); console serves the compatible replacement; dev.sh no longer starts it.
- [ ] Delete `backend/` entirely (api/{events,db,models,main}.py, db/schema.sql, tests/, pyproject.toml) — recoverable at `archive/standalone-platform`.
- [ ] Rewrite `README.md` honestly: repo = redirect shell + docs/synthetic research archive; remove the stale `.venv` one-time setup and the stale cache-root default note; Tests section = `node tests/embodied-design-audit.mjs` only; point events-schema archaeology at the tag.
- [ ] Update `tests/embodied-design-audit.mjs`: replace the "main.py doesn't import embodied" assertions with "backend/ does not exist"; keep redirect assertions. Run it → green.
- [ ] Commit `chore: retire orphaned Postgres events stack (no consumers; unified platform serves /v1/events) — recoverable at archive/standalone-platform`.

### Task E2: PROJECTS — branch & worktree cleanup

- [ ] `git tag archive/frontend-review-fixes f4c09c9` (fixes now re-ported in console Phase C).
- [ ] Remove worktrees + branches: `git worktree remove .claude/worktrees/embodied-risk-fixes && git branch -d worktree-embodied-risk-fixes` (identical to main); same for `gap-analysis-md` (ancestor of both big branches; `-d` succeeds) and `frontend-review-fixes` (`-D` after tagging).
- [ ] Codex worktree: `git worktree remove ~/.config/superpowers/worktrees/projects/codex-embodied-platform` AFTER A3's commit; KEEP branch `codex/embodied-platform` (archive of unported studio/ml).
- [ ] Leave `origin/import-codebase` deletion as a user note (remote-destructive).

### Task E3: CONSOLE — internal cleanup
- [ ] Fix vestigial `backend/tests/embodied_platform/conftest.py` no-op `reset_schema` wording (references a Postgres parent that doesn't exist here).
- [ ] README: env-var table + module list + test commands current (11 modules, ingest/QC endpoints, labeler v27).
- [ ] Commit `chore: conftest wording + README refresh`.

## Phase F — Verify & ship

### Task F1: Full verification
- [ ] `cd CONSOLE/backend && python3 -m pytest tests -q` → ALL green (expect ~140-180 with ported suites; 0 skipped-silently — report exact number).
- [ ] `node tests/embodied-platform-audit.mjs` green; `cd PROJECTS && node tests/embodied-design-audit.mjs` green.
- [ ] Restart the live server (old PID serves pre-merge code): kill the uvicorn on :8099, `./scripts/run.sh` fresh; curl `/healthz`, `/app/`, `/labeler/` → 200.
- [ ] Browser-verify with preview tools: `/app/` login (`admin`/`ground-control-dev`) → create a collection run (write path); open `/labeler/?dataset=demo&episode=0` → mark a segment, ⌘S save, step-frame-while-playing pauses; screenshot both surfaces as proof.

### Task F2: Ship
- [ ] CONSOLE: `git push origin codex/first-person-collection-foundation` and fast-forward `main`: `git checkout main && git merge --ff-only codex/first-person-collection-foundation && git push origin main && git checkout codex/first-person-collection-foundation`.
- [ ] PROJECTS: `git push origin embodied/labeler --tags`.
- [ ] Final report: commits made, test counts, what lives where, what stays archived on `codex/embodied-platform`.

---

## Self-review notes
- Spec coverage: merge (Phases A-C), dead code (E), design (D), functional app (F). ✓
- The only intentionally-unported items are listed in "Explicitly decided" with recovery paths. ✓
- Version-string coupling (`?v=` pins in tests/audit) is called out in every task that touches assets. ✓
