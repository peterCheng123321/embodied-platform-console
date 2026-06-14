# Liquid Glass — Phase 0: Shared Design System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and lock the shared 星聚 Liquid Glass design system (orange-retargeted glass material + refraction engine) as `apps/_vendor/glass/`, served at `/vendor/glass/`, validated by a standalone reference page and asset tests, and turn on response compression — the source of truth Phases 1–2 (labeler, ops console) build on.

**Architecture:** Port `glass.css`/`refract.js` from the claude.ai/design bundle into a shared, **reset-free, app-safe** stylesheet plus a token bridge, retarget the green accent to brand orange `#ff5a36` (token **and** hardcoded green literals), and add a plain-JS auto-installer for refraction with a persisted intensity level. Validate in isolation via a `/vendor/glass/preview.html` reference page before touching either live app. Serving and tests reuse the existing FastAPI app + pytest suite.

**Tech Stack:** Plain CSS (custom properties, `backdrop-filter`, SVG `feDisplacementMap`), vanilla ES module JS, FastAPI `StaticFiles` (already mounts `/vendor`), `GZipMiddleware`, pytest + Starlette `TestClient`.

**Spec:** `docs/superpowers/specs/2026-06-14-liquid-glass-ui-design.md`

**Source bundle (read-only reference):** `/tmp/ds_pack/data-annotation/project/glass/{glass.css,refract.js}`

**Run tests from** `backend/` as: `python3 -m pytest <path> -q` (per README.md:77 — this repo uses system `python3`, no venv). Baseline before Phase 0: **225 passed, 10 skipped**.

---

## Scope note (deliberate deviation from spec phasing)

The spec lists "kill the Tailwind Play CDN" under Phase 0. **Moved to the end of Phase 1**: the labeler's markup uses inline Tailwind utility classes, so removing the Play CDN before those classes are migrated to glass classes would break the labeler. Phase 0 keeps the gzip win (independent) and ships the design system additively. This is the only divergence from the spec; flagged here per fail-loud.

## File structure

```
apps/_vendor/glass/
  tokens.css     CREATE  canonical glass tokens (orange); the bridge layer
  glass.css      CREATE  ported material + gl-* component vocabulary, RESET-FREE, orange
  refract.js     CREATE  ported feDisplacementMap installer + plain-JS auto-init + intensity API
  preview.html   CREATE  standalone reference page rendering the glass vocabulary (validation + living ref)
  preview.css    CREATE  preview-only scaffolding (the global reset + backdrop that glass.css no longer carries)
backend/api/main.py            MODIFY  add GZipMiddleware
backend/tests/test_glass_assets.py  CREATE  asset-served + orange-retarget regression tests
```

Why these boundaries: `tokens.css` is the single place an app re-points its own variables onto; `glass.css` is pure presentation with no global side effects (so it is safe to `<link>` into the real apps in Phases 1–2); `preview.css` quarantines the page-level reset/backdrop that must NOT leak into the apps; `refract.js` owns all refraction behavior behind a tiny API.

---

## Task 1: Token bridge — `tokens.css`

**Files:**
- Create: `apps/embodied-platform-console/apps/_vendor/glass/tokens.css` (path relative to repo root: `apps/_vendor/glass/tokens.css`)
- Test: `backend/tests/test_glass_assets.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_glass_assets.py`:

```python
"""Phase 0: the shared glass design system is served and orange-retargeted."""
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def test_tokens_css_served_and_orange():
    r = client.get("/vendor/glass/tokens.css")
    assert r.status_code == 200
    body = r.text
    # Brand orange is the accent (matches both apps' existing --ds-accent / --accent).
    assert "--accent: #ff5a36" in body
    assert "--accent-2: #d6431f" in body
    # No leftover system-green from the source bundle.
    assert "#30d158" not in body
    assert "#28b34a" not in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_glass_assets.py::test_tokens_css_served_and_orange -q`
Expected: FAIL — 404 (file does not exist yet).

- [ ] **Step 3: Create `apps/_vendor/glass/tokens.css`**

```css
/* 星聚 · Liquid Glass — canonical tokens (orange brand).
   Both apps re-point their own --ds-* / --brand vars onto these in Phases 1-2. */
:root {
  --font: "IBM Plex Sans SC", -apple-system, "PingFang SC", system-ui, sans-serif;
  --mono: "IBM Plex Mono", "SF Mono", ui-monospace, monospace;

  /* accent + semantics — brand orange (was system green in the bundle) */
  --accent: #ff5a36;
  --accent-2: #d6431f;
  --accent-glow: color-mix(in oklch, var(--accent) 55%, transparent);
  --danger: #ff453a;
  --warn: #ff9f0a;
  --warn-glow: rgba(255,159,10,0.5);

  /* vibrancy text (over glass) */
  --t1: rgba(255,255,255,0.96);
  --t2: rgba(255,255,255,0.66);
  --t3: rgba(255,255,255,0.42);
  --t4: rgba(255,255,255,0.26);

  /* glass material */
  --glass-blur: 32px;
  --glass-fill: rgba(30,32,42,0.52);
  --glass-fill-2: rgba(42,44,56,0.62);
  --glass-fill-hi: rgba(74,78,94,0.66);
  --hairline: rgba(255,255,255,0.12);

  /* concentric radii */
  --r-xl: 30px; --r-lg: 22px; --r-md: 15px; --r-sm: 10px;

  /* density-driven rhythm */
  --pad: 18px; --gap: 14px; --row: 13px; --fs: 14px;

  /* float shadows */
  --float: 0 2px 8px rgba(0,0,0,0.18), 0 18px 50px rgba(0,0,0,0.42);
  --float-lo: 0 1px 4px rgba(0,0,0,0.20), 0 8px 24px rgba(0,0,0,0.30);
}
:root[data-density="compact"] {
  --pad: 13px; --gap: 10px; --row: 9px; --fs: 13px; --glass-blur: 28px;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_glass_assets.py::test_tokens_css_served_and_orange -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/_vendor/glass/tokens.css backend/tests/test_glass_assets.py
git commit -m "feat(glass): shared orange token bridge + served-asset test"
```

---

## Task 2: Ported material — `glass.css` (orange, reset-free)

**Files:**
- Create: `apps/_vendor/glass/glass.css`
- Source: `/tmp/ds_pack/data-annotation/project/glass/glass.css`
- Test: `backend/tests/test_glass_assets.py`

- [ ] **Step 1: Add the failing test**

Append to `backend/tests/test_glass_assets.py`:

```python
def test_glass_css_served_orange_and_reset_free():
    r = client.get("/vendor/glass/glass.css")
    assert r.status_code == 200
    body = r.text
    # Core material primitive is present.
    assert ".glass {" in body
    # Orange retarget reached the hardcoded green literals too.
    for green_literal in ("#30d158", "#16a34a", "#6ee787", "#9af0b4", "#28b34a"):
        assert green_literal not in body, f"leftover green literal {green_literal}"
    # RESET-FREE: the bundle's global resets must NOT ship in the app-safe file,
    # or they will clobber the real apps' layout when linked in Phases 1-2.
    assert "* { margin: 0" not in body
    assert "overflow: hidden" not in body  # bundle put this on body{}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_glass_assets.py::test_glass_css_served_orange_and_reset_free -q`
Expected: FAIL — 404.

- [ ] **Step 3: Create `apps/_vendor/glass/glass.css` by porting the bundle file with these EXACT transformations**

Copy `/tmp/ds_pack/data-annotation/project/glass/glass.css` to `apps/_vendor/glass/glass.css`, then apply all of:

1. **Delete the `:root { ... }` and `:root[data-density="compact"] { ... }` blocks** (lines ~9–56 in the source) — tokens now live in `tokens.css`. Add at the very top instead:
   ```css
   /* Tokens come from tokens.css (link it before this file). */
   ```
2. **Delete the global reset block** (source line ~7): remove `* { margin: 0; padding: 0; box-sizing: border-box; }`.
3. **Delete the `html, body { ... }`, `body { ... }`, and `#root { ... }` rules** (source lines ~58–68). These page-level resets belong only in `preview.css` / each app's own base. Keep everything from `.gl-stage` onward.
4. **Orange literal swaps** (the green companions to `--accent`):
   - `.gl-logo` background: `linear-gradient(150deg, var(--accent), #16a34a)` → `linear-gradient(150deg, var(--accent), var(--accent-2))`
   - `.gl-prog-fill` background: `linear-gradient(90deg, var(--accent), #6ee787)` → `linear-gradient(90deg, var(--accent), #ff8a6e)`
   - `.gl-hist-ic.human` color: `#9af0b4` → `#ffb59e`
   - `.gl-empty-ai .big` already uses `var(--accent)` — leave.
   - Leave all `var(--ai)` / `#bf5af2` violet rules intact (unused by labeler; used as a generic secondary; Phase 1 decides per-surface).
5. **Keep** the `.glass`, `.glass::before` (specular rim), `.glass::after` (inner glow), all `gl-*` component classes, backdrops (`.gl-bg[data-bg=...]`), motion (`rise`, `aipulse`, etc.), `prefers-reduced-motion` block, and the UX-pass block (`.gl-box.hl`, low-conf triage) exactly as-is.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_glass_assets.py::test_glass_css_served_orange_and_reset_free -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/_vendor/glass/glass.css backend/tests/test_glass_assets.py
git commit -m "feat(glass): port material system, orange retarget, strip global resets"
```

---

## Task 3: Refraction engine — `refract.js` + plain-JS auto-init

**Files:**
- Create: `apps/_vendor/glass/refract.js`
- Source: `/tmp/ds_pack/data-annotation/project/glass/refract.js`
- Test: `backend/tests/test_glass_assets.py`

- [ ] **Step 1: Add the failing test**

Append to `backend/tests/test_glass_assets.py`:

```python
def test_refract_js_served_with_autoinit():
    r = client.get("/vendor/glass/refract.js")
    assert r.status_code == 200
    body = r.text
    assert "installGlassRefraction" in body         # ported core
    assert "GlassRefraction" in body                 # auto-init public API
    # Intensity levels drive default-on refraction (spec §3/§6).
    for level in ("off", "light", "standard", "strong"):
        assert level in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_glass_assets.py::test_refract_js_served_with_autoinit -q`
Expected: FAIL — 404.

- [ ] **Step 3: Create `apps/_vendor/glass/refract.js`**

First copy `/tmp/ds_pack/data-annotation/project/glass/refract.js` verbatim (it already defines the IIFE exposing `window.installGlassRefraction`). Then **append** this auto-init block to the end of the file (after the existing IIFE):

```javascript
/* Plain-JS auto-installer for non-React hosts (labeler + ops console).
   Default-on per spec §3; reversible via the intensity level (persisted). */
(function () {
  var LEVELS = {
    off:      { on: false, scale: 0,  fringe: 0 },
    light:    { on: true,  scale: 14, fringe: 1.5 },
    standard: { on: true,  scale: 28, fringe: 3 },
    strong:   { on: true,  scale: 44, fringe: 5 },
  };
  var KEY = "glass-refract-level";
  var level = localStorage.getItem(KEY) || "standard";   // default-on
  var controller = null;

  function opts() { return LEVELS[level] || LEVELS.standard; }

  function start(root) {
    var host = root || document.body;
    controller = window.installGlassRefraction(host, opts);
    controller.observeAll();
    controller.rebuild();
  }

  function setLevel(next) {
    if (!LEVELS[next]) return;
    level = next;
    localStorage.setItem(KEY, next);
    if (controller) controller.rebuild();
  }

  window.GlassRefraction = {
    start: start,
    setLevel: setLevel,
    getLevel: function () { return level; },
    levels: Object.keys(LEVELS),
  };

  if (document.readyState !== "loading") start();
  else document.addEventListener("DOMContentLoaded", function () { start(); });
})();
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_glass_assets.py::test_refract_js_served_with_autoinit -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/_vendor/glass/refract.js backend/tests/test_glass_assets.py
git commit -m "feat(glass): refraction installer + persisted-intensity auto-init"
```

---

## Task 4: Reference preview page — `preview.html` + `preview.css`

This is the isolated validation surface: it proves the ported glass + orange + refraction render in *this* deployment (real Chrome on `:8099`) before either live app is touched, and becomes the living reference for Phases 1–2.

**Files:**
- Create: `apps/_vendor/glass/preview.css`
- Create: `apps/_vendor/glass/preview.html`
- Test: `backend/tests/test_glass_assets.py` (served check) + manual Chrome verification.

- [ ] **Step 1: Add the failing test**

Append to `backend/tests/test_glass_assets.py`:

```python
def test_preview_page_served_and_wired():
    r = client.get("/vendor/glass/preview.html")
    assert r.status_code == 200
    body = r.text
    # Links the three shared assets in the right order (tokens before glass).
    t = body.index("tokens.css"); g = body.index("glass.css"); j = body.index("refract.js")
    assert t < g, "tokens.css must be linked before glass.css"
    assert "refract.js" in body and j > 0
    # Renders at least the core vocabulary so it is a real reference.
    for cls in ("glass", "gl-top", "gl-rail", "gl-panel", "gl-save"):
        assert cls in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_glass_assets.py::test_preview_page_served_and_wired -q`
Expected: FAIL — 404.

- [ ] **Step 3: Create `apps/_vendor/glass/preview.css`** (the page-level scaffolding glass.css no longer carries)

```css
/* preview-only: the global reset + backdrop that the app-safe glass.css drops. */
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { height: 100%; }
body {
  font-family: var(--font); font-size: var(--fs); color: var(--t1);
  -webkit-font-smoothing: antialiased; overflow: hidden; letter-spacing: -0.01em;
  background: #0a0b12;
}
.gl-stage { position: relative; height: 100vh; width: 100vw; overflow: hidden; isolation: isolate; }
.preview-grid {
  position: relative; z-index: 1; height: 100vh; overflow-y: auto;
  padding: var(--gap); display: flex; flex-direction: column; gap: var(--gap);
}
.preview-row { display: flex; gap: var(--gap); align-items: stretch; flex-wrap: wrap; }
.preview-cap { color: var(--t3); font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; margin: 6px 2px; }
```

- [ ] **Step 4: Create `apps/_vendor/glass/preview.html`**

```html
<!DOCTYPE html>
<html lang="zh-CN" data-density="comfortable">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>星聚 · Liquid Glass 参考</title>
  <link rel="stylesheet" href="/vendor/fonts/plex.css" />
  <link rel="stylesheet" href="/vendor/font-awesome/css/font-awesome.min.css" />
  <link rel="stylesheet" href="/vendor/glass/tokens.css" />
  <link rel="stylesheet" href="/vendor/glass/glass.css" />
  <link rel="stylesheet" href="/vendor/glass/preview.css" />
</head>
<body>
  <div class="gl-stage">
    <div class="gl-bg" data-bg="graphite"></div>
    <div class="preview-grid">

      <div class="preview-cap">顶栏 Top bar</div>
      <header class="glass gl-top">
        <div class="gl-traffic"><i class="tl-r"></i><i class="tl-y"></i><i class="tl-g"></i></div>
        <div class="gl-brand">
          <div class="gl-logo"><i class="fa fa-cube"></i></div>
          <div class="gl-brand-txt"><b>星聚标注</b><span>Liquid Glass</span></div>
        </div>
        <div class="gl-spacer"></div>
        <div class="gl-progress">
          <div class="gl-prog-track"><div class="gl-prog-fill" style="width:62%"></div></div>
          <span class="gl-prog-txt">62%</span>
        </div>
        <div class="gl-avatar">PC</div>
      </header>

      <div class="preview-row" style="flex:1; min-height:340px;">
        <nav class="glass gl-rail" style="flex:0 0 76px;">
          <div class="gl-rail-tools">
            <button class="gl-tool on"><i class="fa fa-mouse-pointer"></i></button>
            <button class="gl-tool"><i class="fa fa-square-o"></i></button>
            <button class="gl-tool"><i class="fa fa-pencil"></i></button>
          </div>
        </nav>

        <section class="glass" style="flex:1; border-radius:var(--r-lg); padding:var(--pad);">
          <div class="preview-cap">按钮 Buttons</div>
          <div class="preview-row" style="margin-bottom:14px;">
            <button class="gl-save"><i class="fa fa-check"></i> 保存全部</button>
            <button class="gl-navbtn">次要 Secondary</button>
            <button class="gl-qbtn"><i class="fa fa-magic"></i> Quick</button>
          </div>
          <div class="preview-cap">分段控件 Segmented</div>
          <div class="gl-seg" style="width:fit-content;">
            <button class="on">图像</button><button>文本</button>
          </div>
        </section>

        <aside class="glass gl-panel" style="flex:0 0 340px;">
          <div class="gl-panel-head">
            <div class="ai-mark"><i class="fa fa-list"></i></div>
            <div><h3>面板 Panel</h3><div class="sub">list rows + history</div></div>
            <span class="gl-count">3</span>
          </div>
          <div class="gl-list">
            <div class="gl-sugg"><div class="gl-sugg-top"><span class="gl-sugg-chip" style="background:var(--accent)"></span><span class="gl-sugg-name">片段 A</span><span class="gl-sugg-conf"><span class="gl-conf-num">94</span></span></div></div>
            <div class="gl-sugg"><div class="gl-sugg-top"><span class="gl-sugg-chip" style="background:var(--accent)"></span><span class="gl-sugg-name">片段 B</span><span class="gl-sugg-conf"><span class="gl-conf-num">88</span></span></div></div>
          </div>
        </aside>
      </div>

      <div class="preview-cap">命令栏 Command bar</div>
      <footer class="glass gl-cmd">
        <div class="gl-nav"><button class="gl-navbtn"><i class="fa fa-chevron-left"></i></button><button class="gl-navbtn"><i class="fa fa-chevron-right"></i></button></div>
        <div class="gl-cmd-input"><i class="fa fa-terminal"></i><input placeholder="/命令…" /><span class="ret">↵</span></div>
        <button class="gl-save"><i class="fa fa-save"></i> 保存</button>
      </footer>

    </div>
  </div>
  <script src="/vendor/glass/refract.js"></script>
</body>
</html>
```

- [ ] **Step 5: Run the served test**

Run: `python3 -m pytest tests/test_glass_assets.py::test_preview_page_served_and_wired -q`
Expected: PASS.

- [ ] **Step 6: Manual visual verification in Chrome (refraction only renders live)**

Ensure the server is running (`:8099`), then open `http://127.0.0.1:8099/vendor/glass/preview.html` in Chrome. Confirm by eye:
- Frosted translucent panels with a bright top-left specular rim over the graphite backdrop.
- **Orange** (not green) logo tile, progress fill, and save button.
- The backdrop visibly **bends at panel rims** (refraction is default `standard`).
- In DevTools console: `GlassRefraction.setLevel('off')` flattens to plain frost; `GlassRefraction.setLevel('strong')` deepens the lensing.

- [ ] **Step 7: Commit**

```bash
git add apps/_vendor/glass/preview.html apps/_vendor/glass/preview.css backend/tests/test_glass_assets.py
git commit -m "feat(glass): standalone reference preview page + served test"
```

---

## Task 5: Response compression — `GZipMiddleware`

**Files:**
- Modify: `backend/api/main.py:55-64` (add after the CORS middleware block)
- Test: manual curl (TestClient/httpx transparently decodes gzip, so a unit assertion on `content-encoding` is unreliable — verify against the live server).

- [ ] **Step 1: Add the import**

In `backend/api/main.py`, below `from fastapi.middleware.cors import CORSMiddleware` (line 23), add:

```python
from fastapi.middleware.gzip import GZipMiddleware
```

- [ ] **Step 2: Register the middleware**

Immediately after the `app.add_middleware(CORSMiddleware, ...)` block ends (after line 64), add:

```python
# Compress text assets (the labeler ships ~590 KB of uncompressed JS/CSS).
app.add_middleware(GZipMiddleware, minimum_size=1000)
```

- [ ] **Step 3: Verify existing tests still pass (no behavior regression)**

Run: `python3 -m pytest tests/ -q`
Expected: PASS (same count as before this task; gzip is transparent to the suite).

- [ ] **Step 4: Verify compression on the live server**

With the server running on `:8099`:

Run:
```bash
curl -s -H 'Accept-Encoding: gzip' -o /dev/null -D - \
  http://127.0.0.1:8099/app/assets/embodied-platform.js | grep -i 'content-encoding'
```
Expected: `content-encoding: gzip`

- [ ] **Step 5: Commit**

```bash
git add backend/api/main.py
git commit -m "perf(server): gzip-compress text assets via GZipMiddleware"
```

---

## Task 6: Phase 0 sign-off

- [ ] **Step 1: Full suite green**

Run: `python3 -m pytest tests/ -q`
Expected: PASS, including the 4 new tests in `tests/test_glass_assets.py`.

- [ ] **Step 2: Confirm no real app changed yet**

Run: `git diff --name-only main...HEAD`
Expected: only files under `apps/_vendor/glass/`, `backend/api/main.py`, `backend/tests/test_glass_assets.py`, and the two `docs/superpowers/` markdown files. **No** changes under `apps/embodied-labeler/` or `apps/embodied-platform/` — Phase 0 is additive.

- [ ] **Step 3: Tag the locked design system**

```bash
git tag glass-phase0-locked
```

The shared system at `/vendor/glass/` is now the source of truth. Phase 1 (labeler) and Phase 2 (ops console) link `tokens.css` + `glass.css` + `refract.js` and map their existing chassis/markup onto the `gl-*` vocabulary, preserving every `id`/`data-*` hook.

---

## Self-review

**Spec coverage (Phase 0 slice of spec §5, §6, §7):**
- §5 shared design system dir → Tasks 1–3. ✓
- §5.1 token bridge → Task 1 (`tokens.css`). ✓
- §5.2 orange retarget incl. literals → Task 2 transformations + regression test. ✓
- §5.3 keep violet as generic secondary (no labeler AI semantic) → Task 2 step 3.4 leaves `--ai`. ✓
- §6 refraction default-on + reversible intensity → Task 3 auto-init levels (`standard` default). ✓
- §7 Phase 0 perf: gzip → Task 5. Tailwind CDN removal → deferred to Phase 1 (scope note, with rationale). ✓
- Validation surface (real Chrome) → Task 4 preview + manual step. ✓
- §5.4 calm dark backdrop → Task 4 uses `data-bg="graphite"`. ✓ (final default backdrop for the apps is a Phase 1 decision.)

**Placeholder scan:** none — every CSS/JS/Python step has literal content; the one "port + transform" task lists exact old→new edits.

**Type/name consistency:** `GlassRefraction.start/setLevel/getLevel/levels` (Task 3) match the test (Task 3) and the manual check (Task 4 step 6). Asset URLs `/vendor/glass/{tokens,glass,preview}.css`,`refract.js` consistent across tasks and tests. Level names `off/light/standard/strong` consistent in code + test.

**Out of scope for Phase 0 (correctly deferred):** linking glass into the real apps, the Tailwind CDN removal, any `apps/embodied-labeler` or `apps/embodied-platform` markup change.
