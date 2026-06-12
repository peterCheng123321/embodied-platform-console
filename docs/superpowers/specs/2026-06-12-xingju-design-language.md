# XINGJU Unified Design Language — "Instrument Grammar" (2026-06-12)

One language, two grounds. The ops console (`/app/`, light "paper" ground) and the labeler (`/labeler/`, dark "instrument" ground) keep their grounds but share every other decision: the radius scale, the edge grammar, the motion tokens, the button anatomy, and the focus/selection treatment. Detail-level spec — corners, edges, transitions, buttons, and the annotating surface — per the 2026-06-12 direction.

## 0. Palette (already unified — unchanged)
Brand `#0d4f4a` · brand-lum `#1f7a6b` · accent (coral) `#ff5a36` — **navigation/identity/recording only, never status** · status: ok `#1f7a6b`, warn `#b56b00`, danger `#d92d20`, info `#0d6e8a`, neutral `#64748b` · fonts IBM Plex Sans SC / IBM Plex Mono.

## 1. Corners — one 3-step radius scale
```css
--r-1: 4px;    /* chips, tags, kbd hints, inputs' inner elements, segment rects */
--r-2: 8px;    /* buttons, inputs, cards-on-overlay, toasts, palette */
--r-full: 999px; /* pills (status dots' labels), circular transport play button */
```
Rules:
- **Surfaces tile square.** Chassis regions, tables, rails, lanes: radius 0, separated by hairlines (this is already the labeler chassis law; the platform adopts it for its panel tiling — panels lose their 10px outer radius).
- **Controls are rounded.** Anything interactive (button, input, select, chip) uses `--r-1`/`--r-2`. Replace the platform's 10px/7px (`--radius`, `--radius-sm`) with 8/4. Replace labeler Tailwind `rounded-md` (6px) usages' computed look via a CSS override mapping to 8px (do not rewrite HTML classes wholesale; override `.rounded-md{border-radius:var(--r-2)}` etc. inside the app's own CSS scope).
- **Pills are full.** Play/pause circle, status pills.

## 2. Edges — hairline-first elevation
```css
/* light ground */            /* dark ground (.console scope) */
--edge:        rgba(13,79,74,.14);   #26292e;
--edge-strong: rgba(13,79,74,.26);   #343a40;
--overlay-shadow: 0 12px 32px rgba(22,32,31,.16);  /* overlays ONLY */
```
Rules:
- Regions separate by 1px `--edge`; emphasis by `--edge-strong`. **No decorative glows**: remove the platform's `--brand-glow` halos and `0 12px 30px` card elevation; the only shadow in the system is `--overlay-shadow` on floating layers (⌘K palette, login dialog, toasts, dropdowns).
- Inputs: 1px `--edge`, focus → 1px `--edge-strong` + focus ring (no glow).
- Tables: header row gets `--edge-strong` bottom rule; body rows `--edge`.

## 3. Transitions — tokenized motion
```css
--motion-fast: 120ms;  /* color, background, border, opacity on hover/press */
--motion-base: 180ms;  /* transform+opacity entrances; overlay fades */
--ease: cubic-bezier(0.2, 0, 0, 1);  /* decelerate; one curve everywhere */
```
Rules:
- Hover/press state changes: `--motion-fast` on color/background/border only. **Never transition `all`** (audit-pinned).
- Entrances (toast, palette, dialog, module switch): `--motion-base`, fade + 4px rise (`translateY(4px)→0`).
- The labeler's save-pulse and lane interactions keep their timings but adopt `--ease`.
- `prefers-reduced-motion: reduce` collapses both tokens to `1ms` — in BOTH apps (labeler currently lacks the media block; add it).

## 4. Buttons — one anatomy, five intents
Anatomy: height 36px (44px only for the labeler's primary mark action + play circle), padding 0 14px, radius `--r-2`, weight 500, gap 8px icon-text, `transition: background --motion-fast var(--ease), border-color --motion-fast var(--ease)`.
States: hover = ground-tint shift; active = `translateY(0.5px)` + 6% darker; focus-visible = 2px ring (`--brand-lum` on light, `--accent` on dark) with 2px offset; disabled = 45% ink, no pointer events, **never** removed from tab order mid-flight without aria-busy.
Intents:
- `primary` — filled `--brand`, white ink (创建/保存/启动 class of actions)
- `secondary` — transparent, 1px `--edge-strong`, ink text (刷新, 重试, cancel class)
- `danger` — filled `--st-danger` (重置演示数据 moves here from its current outline-red)
- `ghost` — borderless, tint on hover (transport steps, rail items, icon buttons)
- `record` — filled `--accent`, white ink; **labeler-exclusive** (标记终点 Mark end while a segment is open; the pulsing dot lives here)
Loading state: spinner replaces icon, label persists, `aria-busy="true"` (matches existing 保存中… pattern).

## 5. The annotating surface (labeler details)
- **Segment rects (lanes):** radius `--r-1`; default 1px `--edge`; hover `--edge-strong` + brightness +4%; **selected**: 1.5px `--accent` outline + 8% accent tint; drag handles appear on hover/selection as 3px end-bars (`--motion-fast` fade-in).
- **Skill chips (right rail):** radius `--r-1`; selected = `--edge-strong` + brand tint + the existing numbered kbd hint; hover ground tint; the color dot stays data-not-chrome.
- **Transport cluster:** all `ghost` intent, the play circle `--r-full` `record`-colored as today; frame-stepper group shares one hairline border with internal 1px separators (already close — tokenize).
- **Toasts:** dark surface + 1px `--edge-strong` + `--r-2` + `--overlay-shadow`; 3px leading bar in status color; enter/exit per §3.
- **⌘K palette:** `--r-2`, `--overlay-shadow`, selected row = brand tint + 2px left bar `--accent`.
- **kbd hints:** mono, 11px, `--r-1`, 1px `--edge`, never bolded.

## 6. Application order (implementation)
1. Token blocks (`--r-*`, `--motion-*`, `--ease`, `--edge*`, `--overlay-shadow`) land in BOTH `embodied-platform.css` `:root` and the labeler (`embodied.css` `:root` + `.console` re-bind for dark edge values). Audit pins assert the token names exist in both files with matching values where ground-independent (`--r-1/--r-2/--motion-fast/--motion-base/--ease`).
2. Platform: radius swap 10/7→tokens, glow removal, button intents (existing `.btn-primary/.btn-secondary/.btn-danger` refactor + ghost), table edges, transition token sweep (no `transition: all`).
3. Labeler: Tailwind radius overrides, button intent mapping (mark-start=secondary→on-open swaps to record; transport=ghost), segment/chip/toast/palette details per §5, reduced-motion block.
4. Visual regression: before/after screenshots of /app/ (dashboard + collection) and /labeler/ (idle + segment-selected + palette open).

## Non-goals
Light/dark theming flips, palette changes, layout/IA changes, Tailwind removal, the landing redirect stubs.
