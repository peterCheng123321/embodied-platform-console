/* 星聚 · Liquid Glass — labeler glue.
   Wires the 控制中心 Control Center to live glass settings. Refraction itself
   auto-installs via /vendor/glass/refract.js (it finds the .glass chassis
   slabs). This module ONLY adds controls; it removes no existing behaviour. */

const LS = {
  density: "glass-density",
  backdrop: "glass-backdrop",
  bright: "glass-bright",
  focus: "glass-focus",
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function setSeg(group, value) {
  $$(`[data-cc="${group}"] button`).forEach((b) =>
    b.classList.toggle("on", b.dataset.value === value)
  );
}

/* ---- apply persisted settings on load ----------------------------------- */
function restore() {
  const density = localStorage.getItem(LS.density) || "comfortable";
  document.documentElement.setAttribute("data-density", density);
  setSeg("density", density);

  const backdrop = localStorage.getItem(LS.backdrop) || "graphite";
  const bg = $(".glass-backdrop");
  if (bg) bg.setAttribute("data-bg", backdrop);
  setSeg("backdrop", backdrop);

  const bright = localStorage.getItem(LS.bright) || "100";
  document.documentElement.style.setProperty("--cc-bright", String(+bright / 100));
  const slider = $("#cc-bright");
  if (slider) slider.value = bright;

  const focus = localStorage.getItem(LS.focus) === "1";
  document.body.classList.toggle("glass-focus", focus);
  const fsw = $("#cc-focus");
  if (fsw) fsw.setAttribute("aria-pressed", String(focus));

  // refraction level is owned + persisted by GlassRefraction; reflect it.
  if (window.GlassRefraction) setSeg("refract", window.GlassRefraction.getLevel());
}

/* ---- wire the controls --------------------------------------------------- */
function wire() {
  // open / close
  const scrim = $("#cc-scrim");
  const open = () => { if (scrim) { scrim.hidden = false; if (window.GlassRefraction) setSeg("refract", window.GlassRefraction.getLevel()); } };
  const close = () => { if (scrim) scrim.hidden = true; };
  $("#cc-toggle")?.addEventListener("click", open);
  scrim?.addEventListener("click", (e) => { if (e.target === scrim) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && scrim && !scrim.hidden) close(); });

  // refraction intensity (关/轻/标准/强)
  $$('[data-cc="refract"] button').forEach((b) =>
    b.addEventListener("click", () => {
      window.GlassRefraction?.setLevel(b.dataset.value);
      setSeg("refract", b.dataset.value);
    })
  );

  // density (舒适/紧凑)
  $$('[data-cc="density"] button').forEach((b) =>
    b.addEventListener("click", () => {
      document.documentElement.setAttribute("data-density", b.dataset.value);
      localStorage.setItem(LS.density, b.dataset.value);
      setSeg("density", b.dataset.value);
      // slabs resize on density change; refract.js's ResizeObserver re-fits
      // each displacement map automatically — nothing to do here.
    })
  );

  // backdrop mood (石墨/午夜/暖橙)
  $$('[data-cc="backdrop"] button').forEach((b) =>
    b.addEventListener("click", () => {
      $(".glass-backdrop")?.setAttribute("data-bg", b.dataset.value);
      localStorage.setItem(LS.backdrop, b.dataset.value);
      setSeg("backdrop", b.dataset.value);
    })
  );

  // backdrop brightness
  $("#cc-bright")?.addEventListener("input", (e) => {
    const v = e.target.value;
    document.documentElement.style.setProperty("--cc-bright", String(+v / 100));
    localStorage.setItem(LS.bright, v);
  });

  // focus: dim the backdrop + drop its grain so the work pops
  $("#cc-focus")?.addEventListener("click", (e) => {
    const on = e.currentTarget.getAttribute("aria-pressed") !== "true";
    e.currentTarget.setAttribute("aria-pressed", String(on));
    document.body.classList.toggle("glass-focus", on);
    localStorage.setItem(LS.focus, on ? "1" : "0");
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => { restore(); wire(); });
} else {
  restore();
  wire();
}
