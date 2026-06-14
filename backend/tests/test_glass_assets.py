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
