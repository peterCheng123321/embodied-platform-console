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
    # The body{} rule (which held overflow:hidden) must be gone; component rules
    # (.gl-stage, .gl-panel, etc.) legitimately use overflow:hidden and are kept.
    # Check for the bare body selector (not .gl-body or html,body or similar).
    assert "\nbody {" not in body  # bundle put overflow:hidden on body{}


def test_refract_js_served_with_autoinit():
    r = client.get("/vendor/glass/refract.js")
    assert r.status_code == 200
    body = r.text
    assert "installGlassRefraction" in body         # ported core
    assert "GlassRefraction" in body                 # auto-init public API
    # Intensity levels drive default-on refraction (spec §3/§6).
    for level in ("off", "light", "standard", "strong"):
        assert level in body
