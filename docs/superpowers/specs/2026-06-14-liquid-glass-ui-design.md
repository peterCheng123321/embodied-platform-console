# 星聚 · Liquid Glass UI — Design Spec

_2026-06-14 · branch `embodied/liquid-glass-ui` · repo `embodied-platform-console`_

## 1. Goal

Massively upgrade the UI/UX of the 星聚 platform by porting the **Apple Liquid Glass**
material system from the design handoff bundle (`Liquid Glass UI Pack.html`, claude.ai/design)
onto the two live frontends:

- **Labeler** — `apps/embodied-labeler/` (the LeRobot trajectory-subtask workstation)
- **Ops console** — `apps/embodied-platform/` (the 11-panel operations dashboard)

Both run today behind the FastAPI app on `:8099`. This spec supersedes the **visual material
layer** of `docs/superpowers/specs/2026-06-12-xingju-design-language.md` (the current flat
"instrument console" language); the information architecture, copy, and semantics from that
doc are retained.

## 2. Source material

The bundle (`/tmp/ds_pack/data-annotation/`, also archived locally) ships a glass component
**kit**, not application screens. Authoritative files:

- `glass/glass.css` — the material system (tokens, `.glass` primitive, 7 backdrops, the
  top-bar / rail / panel / canvas / command-bar / control vocabulary, motion, adaptive
  legibility pass).
- `kit/kit.css`, `kit/components.jsx`, `kit/app.jsx` — the component library + Control Center + Glass Lab.
- `glass/refract.js` — the real-refraction installer: finds `.glass` surfaces, builds a
  per-element SVG bevel displacement map, swaps `backdrop-filter` to an `feDisplacementMap`
  filter (Chrome/Edge only; automatic frost fallback elsewhere) with optional chromatic fringe.

## 3. Decisions (locked with user)

| Axis | Decision | Notes |
|---|---|---|
| **Scope** | Everything — labeler **and** ops console | Phased; see §7 |
| **Depth** | "Rebuild from the pack" → see §4 | Reinterpreted: vocabulary + preserve logic |
| **Refraction** | **On everywhere by default** (incl. video/timeline/tables) | User's explicit, informed override of the chrome-only recommendation. Kept **reversible** via the 关/轻/标准/强 intensity tweak; frame-accuracy caveat documented in §6. |
| **Look** | Glass material + **calm dark backdrop** + **星聚 orange `#ff5a36`** accent | Orange is already the brand accent in *both* apps; no violet "AI" semantic in the labeler |

## 4. What "rebuild from the pack" means (the contract)

The pack has **no** labeler or ops screens to recreate, and is full of components specific to
image-bbox / NER AI annotation (AI-suggestion panel, bounding boxes, AI command bar, NER spans)
that **do not exist** in either app. Per the bundle's own README ("match the visual output;
don't copy the prototype's internal structure"), "rebuild" therefore means:

> **Port the glass material system + component vocabulary as one shared source of truth, apply
> it to the apps' _real_ features, and preserve all working interaction logic.**

**Preserve-logic contract (the safety rail):**
- Keep every existing `id` and `data-*` hook that JS binds to. Do **not** rename or remove them.
- Change only presentational markup/classes and CSS. No rewrite of the labeler's video sync,
  scrubbing, frame stepping, timeline SVG rendering, gripper plot, keyboard shortcuts, segment
  editing, or backend save; no rewrite of the ops console's `renderAll()`, `table()`,
  `runAction()` router, hash routing, auth, or persistence.
- Verifiable: existing pytest suites still pass and the apps still function on `:8099`.

## 5. Architecture — one shared glass design system

New shared directory consumed by both apps:

```
apps/_shared/glass/
  tokens.css   — NEW shared token layer (the bridge; see below)
  glass.css    — ported material system, retargeted to orange
  refract.js   — refraction installer, default-on everywhere per §3, automatic frost fallback
```

### 5.1 Token bridge (the two apps do NOT share token names today)
- Labeler uses `--ds-*` (`--ds-canvas #141619`, `--ds-surface #1a1d20`, `--ds-ink`, `--ds-accent
  #ff5a36`, `--ds-shadow: none`, …).
- Ops uses `--bg/--surface/--edge/--ink/--brand #1f7a6b/--accent #ff5a36/--st-*`.
- Both already use accent **`#ff5a36`** and IBM Plex fonts.

`tokens.css` defines the canonical glass tokens (`--accent`, `--glass-*`, `--t1..t4`,
`--hairline`, `--r-*`, `--pad/gap/row/fs`, `--float`). Each app's existing `--ds-*` / `--brand`
variables are then **re-pointed onto** these (e.g. `--ds-surface: var(--glass-fill)`,
`--ds-shadow: var(--float)`), so existing consumers keep working while gaining the glass look.

### 5.2 Orange retarget (token AND literals)
`glass.css` hardcodes green companions to `--accent: #30d158`. Flipping the token is not enough —
hunt and retune these literals:
- `.gl-logo` gradient end `#16a34a`
- `.gl-prog-fill` gradient end `#6ee787`
- `.gl-hist-ic.human` `#9af0b4`
- all `color-mix(... var(--accent) ...)` partners (recompute against orange so tints read warm)

New accent set: `--accent: #ff5a36`, `--accent-2: #d6431f` (darker orange for gradients),
`--accent-glow: color-mix(in oklch, var(--accent) 55%, transparent)`.

### 5.3 Semantics
- **Labeler:** drop the violet `--ai` semantic (no AI-suggestion layer). Orange = your
  annotations; the existing **gold lane** stays = reference; keep the amber `--warn` for
  low-IoU / unsaved triage (maps to existing `--ds-state-risk`).
- **Ops console:** keep the 6 semantic status tokens (`--st-neutral/info/ok/warn/danger`),
  reskinned as glass-legible tints over the dark backdrop.

### 5.4 Backdrop
Calm dark (`graphite` / `nocturne` from glass.css) by default so chrome glass has something to
refract without competing with the video. Backdrop is a tweak.

## 6. Refraction — default-on everywhere, reversible

Per §3 the refraction installer runs over **all** `.glass` surfaces by default, including the
frames around the video, the timeline, and the ops tables.

**Documented caveat (fail-loud):** `feDisplacementMap` shifts pixels at the rim. Over the
frame-accurate **timeline lanes** and the **video**, strong refraction can visually move where a
segment boundary appears relative to the frame it encodes, and heavy `backdrop-filter` across the
ops console's 14 tables costs scroll/GPU. Mitigations kept in the build:
- The **强度** tweak (关/轻/标准/强) is wired and persisted; default `标准`. `关` restores plain
  frost and is the automatic off-Chrome fallback.
- Per-surface `data-frost` / `data-refract` attributes so individual surfaces can be tuned or
  opted out without code changes if a correctness issue surfaces in use.
- `refract.js` rebuilds each surface's SVG map on resize via `ResizeObserver` (cost scales with
  surface count — relevant for the ops console; the intensity tweak is the escape hatch).

## 7. Phasing (each phase independently shippable)

**Phase 0 — Shared design system + perf.**
- Build/lock `apps/_shared/glass/{tokens,glass}.css` + `refract.js`, retargeted to orange.
- **Replace the 407 KB Tailwind Play CDN** (`/vendor/tailwind/tailwind-play.js`) in the labeler
  with compiled/static CSS, and **add `GZipMiddleware`** to `backend/api/main.py` (folds in the
  prior perf findings — uncompressed 590 KB labeler payload → ~120–150 KB).
- Source of truth for everything after.

**Phase 1 — Labeler, end-to-end (flagship).**
- Map the console chassis onto glass: `console-topbar`→`gl-top`, `console-tree`→glass rail/panel,
  `console-viewport` video card→glass canvas frame (clear center), `console-inspector`→glass panel
  (skill palette + segments + savebar), `console-conductor` timeline→glass panel, `console-bottombar`→glass command/status bar.
- Preserve every `id`/`data-*`; video + timeline render in clear-centered glass frames.

**Phase 2 — Ops console, panel-by-panel.**
- `.platform-workspace`→`gl-app` grid, `.module-rail`→glass rail, each `.module-panel`→glass panel,
  `.summary-grid` tiles→glass tiles, `.data-table` rows→glass list rows, `.btn-*`→glass buttons,
  `.tag`→glass badges, monitoring board→glass tiles. Tables stay legible.

## 8. Verification

- Existing pytest suites (`backend/tests/...`) pass unchanged each phase.
- App boots and functions on `:8099` (video sync, shortcuts, timeline edit, save; ops CRUD + routing).
- Visual check in real Chrome (refraction only renders live, not in static capture).
- Perf check: labeler critical-path payload compressed; no Tailwind Play CDN request.

## 9. Risks / open items

1. **Refraction over precision content** — accepted by user; mitigated via the intensity tweak +
   per-surface opt-out (§6). Revisit if frame-accuracy is reported off.
2. **Tailwind utility classes in labeler markup** — the labeler HTML uses many inline Tailwind
   utilities; removing the Play CDN means either compiling a static Tailwind build or migrating
   those utilities to glass classes. Phase 0 picks one (lean toward a small compiled static build
   as a safety net so Phase 1 markup migration is incremental, not big-bang).
3. **Backdrop vs video focus** — calm dark default; revisit if the backdrop distracts.
4. **`color-mix`/`backdrop-filter: url()` support** — Chrome/Edge first-class; Safari/Firefox get
   frost fallback automatically. Acceptable per refraction caveat.

## 10. Out of scope

- No recreation of the pack's image-bbox / NER / AI-suggestion / Control-Center / Glass-Lab
  screens (not product features).
- No change to backend business logic, data model, or the ops action semantics.
- No new product features — this is a material/UX reskin preserving all behavior.
