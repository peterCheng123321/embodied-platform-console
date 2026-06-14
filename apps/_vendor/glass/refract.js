/* 星聚标注 · Liquid Glass — real refraction installer
   Finds every .glass surface, measures it, builds a bevel displacement
   map sized to that element, and swaps its backdrop-filter to an SVG
   feDisplacementMap filter so the backdrop genuinely bends at the rim.
   Chrome/Edge only (backdrop-filter: url()); elsewhere falls back to frost. */
(function () {
  function buildGlassMap(w, h, r, bevel, soft) {
    const inset = bevel;
    const iw = Math.max(2, w - inset * 2);
    const ih = Math.max(2, h - inset * 2);
    const ir = Math.max(0, r - inset);
    const svg =
      "<svg xmlns='http://www.w3.org/2000/svg' width='" + w + "' height='" + h + "'>" +
        "<defs>" +
          "<linearGradient id='gx' x1='0' y1='0' x2='1' y2='0'><stop offset='0' stop-color='#000000'/><stop offset='1' stop-color='#ff0000'/></linearGradient>" +
          "<linearGradient id='gy' x1='0' y1='0' x2='0' y2='1'><stop offset='0' stop-color='#000000'/><stop offset='1' stop-color='#00ff00'/></linearGradient>" +
          "<filter id='s' x='-20%' y='-20%' width='140%' height='140%'><feGaussianBlur stdDeviation='" + soft + "'/></filter>" +
        "</defs>" +
        "<rect width='" + w + "' height='" + h + "' fill='url(#gx)'/>" +
        "<rect width='" + w + "' height='" + h + "' fill='url(#gy)' style='mix-blend-mode:screen'/>" +
        "<rect x='" + inset + "' y='" + inset + "' width='" + iw + "' height='" + ih + "' rx='" + ir + "' ry='" + ir + "' fill='#7f7f7f' filter='url(#s)'/>" +
      "</svg>";
    return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
  }

  let UID = 0;

  function installGlassRefraction(root, getOpts) {
    let defs = document.getElementById("gl-refract-defs");
    if (!defs) {
      defs = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      defs.id = "gl-refract-defs";
      defs.setAttribute("aria-hidden", "true");
      defs.style.cssText = "position:absolute;width:0;height:0;pointer-events:none;";
      document.body.appendChild(defs);
    }

    function rebuild() {
      const opts = getOpts();
      const scale = opts.scale || 0;
      const fringe = opts.fringe || 0;
      const maxArea = opts.maxArea || 160000;
      const on = opts.on && scale > 0;
      const els = Array.prototype.slice.call(root.querySelectorAll(".glass"));
      let html = "";
      els.forEach(function (el) {
        let id = el.getAttribute("data-refract");
        if (!id) { id = "glr" + (++UID); el.setAttribute("data-refract", id); }
        if (!on) { el.style.backdropFilter = ""; el.style.webkitBackdropFilter = ""; return; }
        const w = el.offsetWidth, h = el.offsetHeight;
        if (w < 8 || h < 8 || w * h > maxArea) {
          el.style.backdropFilter = "";
          el.style.webkitBackdropFilter = "";
          return;
        }
        const cs = getComputedStyle(el);
        const r = parseFloat(cs.borderTopLeftRadius) || 16;
        const minD = Math.min(w, h);
        // rim width: keep a neutral (undistorted) center on thin bars too
        let bevel = Math.min(30, Math.round(minD * 0.4));
        bevel = Math.max(4, Math.min(bevel, Math.floor(minD / 2) - 5));
        const soft = Math.max(3, Math.round(bevel * 0.55));
        const map = buildGlassMap(w, h, r, bevel, soft);
        const blur = parseFloat(el.getAttribute("data-frost")) || 26;
        const head =
          '<filter id="' + id + '" color-interpolation-filters="sRGB" x="-15%" y="-15%" width="130%" height="130%">' +
            '<feGaussianBlur in="SourceGraphic" stdDeviation="' + blur + '" result="f"/>' +
            '<feImage href="' + map + '" x="0" y="0" width="' + w + '" height="' + h + '" result="m" preserveAspectRatio="none"/>';
        let body;
        if (fringe > 0) {
          // split channels: red bends most, blue least → rainbow only at the refracting rim
          body =
            '<feDisplacementMap in="f" in2="m" scale="' + (scale + fringe) + '" xChannelSelector="R" yChannelSelector="G" result="dR"/>' +
            '<feDisplacementMap in="f" in2="m" scale="' + scale + '" xChannelSelector="R" yChannelSelector="G" result="dG"/>' +
            '<feDisplacementMap in="f" in2="m" scale="' + (scale - fringe) + '" xChannelSelector="R" yChannelSelector="G" result="dB"/>' +
            '<feColorMatrix in="dR" type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="cR"/>' +
            '<feColorMatrix in="dG" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0" result="cG"/>' +
            '<feColorMatrix in="dB" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0" result="cB"/>' +
            '<feBlend in="cR" in2="cG" mode="screen" result="cRG"/>' +
            '<feBlend in="cRG" in2="cB" mode="screen"/>';
        } else {
          body = '<feDisplacementMap in="f" in2="m" scale="' + scale + '" xChannelSelector="R" yChannelSelector="G"/>';
        }
        html += head + body + '</filter>';
        el.style.backdropFilter = "url(#" + id + ") saturate(185%) brightness(0.95)";
        el.style.webkitBackdropFilter = "url(#" + id + ") saturate(185%) brightness(0.95)";
      });
      defs.innerHTML = html;
    }

    let raf = 0;
    const ro = new ResizeObserver(function () {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(rebuild);
    });
    function observeAll() {
      ro.disconnect();
      root.querySelectorAll(".glass").forEach(function (el) { ro.observe(el); });
    }
    function destroy() {
      cancelAnimationFrame(raf);
      ro.disconnect();
      root.querySelectorAll(".glass").forEach(function (el) {
        el.style.backdropFilter = ""; el.style.webkitBackdropFilter = "";
      });
      if (defs) defs.innerHTML = "";
    }
    return { rebuild: rebuild, observeAll: observeAll, destroy: destroy };
  }

  window.installGlassRefraction = installGlassRefraction;
})();

/* Plain-JS auto-installer for non-React hosts (labeler + ops console).
   Default-on per spec §3; reversible via the intensity level (persisted). */
(function () {
  var LEVELS = {
    off:      { on: false, scale: 0,  fringe: 0 },
    light:    { on: true,  scale: 14, fringe: 1.5, maxArea: 160000 },
    standard: { on: true,  scale: 28, fringe: 3,   maxArea: 160000 },
    strong:   { on: true,  scale: 44, fringe: 5,   maxArea: 160000 },
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
