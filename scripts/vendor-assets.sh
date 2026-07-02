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
# NOTE (2026-06-12): fonts.googleapis silently omits IBM Plex Sans SC — the family
# is not in the Google Fonts catalog (requesting it alone returns HTTP 400), so the
# css only ever contained Plex Mono and CJK text already fell back to system fonts.
# We vendor exactly what the CDN serves so rendering is unchanged.
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

# 4. Viewfinder skin fonts — JetBrains Mono (telemetry mono chrome) + Noto Sans SC
# (CJK/UI). This is the reskin's "instrument" type (mock: Viewfinder.dc.html).
# Unlike Plex Sans SC (never in the Google catalog — see note above), Noto Sans SC
# IS served, so this is a real CJK upgrade over the prior system-font fallback.
# Same offline sha1-rewrite pipeline; woff2 shared with plex (dedup by sha1).
VF_CSS_URL='https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Noto+Sans+SC:wght@400;500;700&display=swap'
curl -fsSL -A "$UA" "$VF_CSS_URL" -o "$V/fonts/viewfinder-fonts.orig.css"
python3 - "$V" <<'PY'
import hashlib, pathlib, re, sys, urllib.request
v = pathlib.Path(sys.argv[1]) / "fonts"
css = (v / "viewfinder-fonts.orig.css").read_text()
def fetch(m):
    url = m.group(1)
    name = hashlib.sha1(url.encode()).hexdigest()[:16] + ".woff2"
    dest = v / "woff2" / name
    if not dest.exists():
        urllib.request.urlretrieve(url, dest)
    return f"url(woff2/{name})"
out = re.sub(r"url\((https://fonts\.gstatic\.com/[^)]+)\)", fetch, css)
(v / "viewfinder-fonts.css").write_text(out)
print(f"viewfinder-fonts.css: {len(re.findall(r'woff2/', out))} font files vendored")
PY
rm "$V/fonts/viewfinder-fonts.orig.css"
echo "vendored: $(find "$V" -type f | wc -l | tr -d ' ') files, $(du -sh "$V" | cut -f1)"
