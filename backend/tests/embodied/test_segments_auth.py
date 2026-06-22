"""Real authentication on the labeler segment routes (issue #2).

Before this fix, POST/GET /api/embodied/segments were gated only by
`X-Annotator-Id == body.annotator_id` — both values are client-controlled and
unsigned, so any caller who put the same UUID in both passed. These tests pin
the fix: writes/reads now require a valid platform principal HMAC signature
(the same `_verify_principal_signature` the platform router uses), and
`annotator_id` is derived from the authenticated actor, not the header/body.

The canonical acceptance command names backend/api/embodied/tests/... but the
repo collects from `testpaths = ["tests"]` (backend/pyproject.toml), so the test
lives here at backend/tests/embodied/test_segments_auth.py and runs as
`python -m pytest tests/embodied/test_segments_auth.py`. The auth secret is set
by the autouse fixture in conftest.py.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.embodied.routes import principal_annotator_id
from api.embodied_platform.routes import sign_principal


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    """Embodied router app on a tmp data root (auth secret comes from conftest)."""
    monkeypatch.setenv("XINGJU_EMBODIED_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_DATA_ROOT", str(tmp_path / "platform"))
    monkeypatch.delenv("XINGJU_EMBODIED_PLATFORM_DSN", raising=False)
    from fastapi import FastAPI
    from api.embodied.routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _auth(actor: str, role: str = "annotator") -> dict[str, str]:
    return {
        "X-Embodied-Actor": actor,
        "X-Embodied-Role": role,
        "X-Embodied-Signature": sign_principal(actor, role),
    }


def _body(annotator_id: str, *, n: int = 1) -> dict:
    return {
        "episode_id": "demo_episode",
        "annotator_id": annotator_id,
        "segments": [{"annotator_id": annotator_id, "episode_index": 0,
                      "start_frame": 0, "end_frame": 10, "skill_id": "reach"}] * n,
    }


# --- the core authz bypass --------------------------------------------------

def test_matching_header_and_body_without_signature_is_rejected(client):
    """X-Annotator-Id == body.annotator_id but NO valid principal signature.
    Used to be 200 (both values client-controlled); must now be rejected,
    because identity is no longer taken from the header/body."""
    ann = "550e8400-e29b-41d4-a716-446655440000"
    r = client.post("/api/embodied/segments", json=_body(ann),
                    headers={"X-Annotator-Id": ann})
    assert r.status_code in (401, 403), r.text


def test_post_without_any_auth_is_rejected(client):
    ann = "550e8400-e29b-41d4-a716-446655440000"
    r = client.post("/api/embodied/segments", json=_body(ann))
    assert r.status_code == 403, r.text


def test_post_with_forged_signature_is_rejected(client, tmp_path):
    actor = "mallory"
    r = client.post("/api/embodied/segments", json=_body(str(principal_annotator_id(actor))),
                    headers={"X-Embodied-Actor": actor, "X-Embodied-Role": "annotator",
                             "X-Embodied-Signature": "forged"})
    assert r.status_code == 403, r.text
    # Nothing was written for the forged principal.
    assert not (tmp_path / "demo_episode" / "meta" / "annotations").exists()


def test_get_without_signature_is_rejected(client):
    r = client.get("/api/embodied/segments?episode_id=demo_episode")
    assert r.status_code == 403, r.text


# --- valid principal: write + read round-trip -------------------------------

def test_valid_principal_writes_and_reads(client, tmp_path):
    actor = "alice"
    ann = str(principal_annotator_id(actor))
    r = client.post("/api/embodied/segments", json=_body(ann), headers=_auth(actor))
    assert r.status_code == 200, r.text
    assert r.json()["written"] == 1
    # Stored under the DERIVED annotator id.
    out = tmp_path / "demo_episode" / "meta" / "annotations" / ann / "subtask_segments.v1.jsonl"
    assert out.exists()

    got = client.get("/api/embodied/segments?episode_id=demo_episode", headers=_auth(actor))
    assert got.status_code == 200
    assert [s["skill_id"] for s in got.json()] == ["reach"]


def test_annotator_id_is_derived_from_principal_not_body(client, tmp_path):
    """Even if the body carries a different annotator_id, the stored identity is
    the one derived from the authenticated actor — body/header are not trusted."""
    actor = "alice"
    derived = str(principal_annotator_id(actor))
    spoofed = "00000000-0000-0000-0000-0000000000ff"
    assert spoofed != derived
    r = client.post("/api/embodied/segments", json=_body(spoofed), headers=_auth(actor))
    assert r.status_code == 200, r.text
    # Written under the derived id, NOT the spoofed body value.
    assert (tmp_path / "demo_episode" / "meta" / "annotations" / derived).is_dir()
    assert not (tmp_path / "demo_episode" / "meta" / "annotations" / spoofed).exists()
    got = client.get("/api/embodied/segments?episode_id=demo_episode", headers=_auth(actor))
    assert got.json()[0]["annotator_id"] == derived


def test_one_annotator_cannot_read_anothers_segments(client):
    """Authorization: a principal only ever reads its OWN labels — reads are
    scoped to the derived id, so Bob cannot see Alice's segments."""
    client.post("/api/embodied/segments",
                json=_body(str(principal_annotator_id("alice"))), headers=_auth("alice"))
    bob = client.get("/api/embodied/segments?episode_id=demo_episode", headers=_auth("bob"))
    assert bob.status_code == 200
    assert bob.json() == []  # Bob's own (empty) store, never Alice's


# --- size caps (disk-exhaustion guards) -------------------------------------

def test_oversized_segment_list_is_rejected(client):
    """The list max_length is the primary disk-exhaustion guard: a valid
    principal still cannot write an unbounded number of segments at once."""
    actor = "alice"
    ann = str(principal_annotator_id(actor))
    r = client.post("/api/embodied/segments", json=_body(ann, n=2001), headers=_auth(actor))
    assert r.status_code == 422, r.text


def test_oversized_instruction_text_is_rejected(client):
    actor = "alice"
    ann = str(principal_annotator_id(actor))
    body = _body(ann)
    body["segments"][0]["instruction_text"] = "x" * 2001  # over the 2000 cap
    r = client.post("/api/embodied/segments", json=body, headers=_auth(actor))
    assert r.status_code == 422, r.text


def test_oversized_request_body_is_rejected_413(monkeypatch, tmp_path):
    """The ASGI Content-Length cap in api/main.py rejects an obviously oversized
    write at the edge (defense-in-depth) before it is routed/parsed."""
    monkeypatch.setenv("XINGJU_EMBODIED_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_DATA_ROOT", str(tmp_path / "platform"))
    from api.main import app, MAX_REQUEST_BODY_BYTES

    full = TestClient(app)
    oversized = b'{"junk":"' + b"a" * (MAX_REQUEST_BODY_BYTES + 1) + b'"}'
    r = full.post("/api/embodied/segments", content=oversized,
                  headers={"Content-Type": "application/json", **_auth("alice")})
    assert r.status_code == 413, r.status_code
