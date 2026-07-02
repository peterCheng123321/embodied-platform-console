"""ETag/If-Match optimistic concurrency for /api/embodied/segments.

Two tabs editing the same annotator's file must not silently overwrite each
other. Mechanism: GET (and POST) return the current file's mtime_ns as an
ETag header; the client echoes it back as If-Match on POST; the backend
rejects with 409 stale_write when the file has moved on. Omitting If-Match
is a deliberate force-overwrite — both the back-compat path for old clients
and the manual "save again" retry after a conflict.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def embodied_app(tmp_path, monkeypatch):
    """Standalone FastAPI app with only the embodied router — no DB pool."""
    monkeypatch.setenv("XINGJU_EMBODIED_DATA_ROOT", str(tmp_path))
    from fastapi import FastAPI
    from api.embodied.routes import router

    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(embodied_app):
    return TestClient(embodied_app)


def _auth(actor: str, role: str = "annotator") -> dict[str, str]:
    """Signed platform principal headers (issue #2). The segment routes derive
    annotator_id from this authenticated actor."""
    from api.embodied_platform.routes import sign_principal
    return {
        "X-Embodied-Actor": actor,
        "X-Embodied-Role": role,
        "X-Embodied-Signature": sign_principal(actor, role),
    }


def _annotator_id(actor: str) -> str:
    """The derived annotator_id the server will store for this actor."""
    from api.embodied.routes import principal_annotator_id
    return str(principal_annotator_id(actor))


def _seg(ann: str, start: int = 0, end: int = 10) -> dict:
    return {"annotator_id": ann, "episode_index": 0,
            "start_frame": start, "end_frame": end, "skill_id": "reach"}


def _post(client, actor, segs, if_match=None, headers=None):
    # Identity is derived from the signed actor; the body annotator_id is
    # ignored by the server (issue #2) but kept here so callers can assert the
    # on-disk path, which uses the derived id == _annotator_id(actor).
    ann = _annotator_id(actor)
    if headers is None:
        headers = _auth(actor)
    if if_match is not None:
        headers = {**headers, "If-Match": if_match}
    return client.post(
        "/api/embodied/segments",
        json={"episode_id": "demo_episode", "annotator_id": ann, "segments": segs},
        headers=headers,
    )


def _get(client, actor, headers=None):
    ann = _annotator_id(actor)
    return client.get(
        f"/api/embodied/segments?episode_id=demo_episode&annotator_id={ann}",
        headers=headers if headers is not None else _auth(actor),
    )


class TestEtagHeaders:
    def test_get_returns_etag_zero_before_first_write(self, client):
        # ETag is present even for a not-yet-existing file (value: "0"), so a
        # first save can still be conflict-checked against "nothing written".
        actor = "alice"
        r = _get(client, actor)
        assert r.status_code == 200
        assert r.headers.get("ETag") == "0"

    def test_post_returns_new_etag(self, client):
        actor = "alice"
        ann = _annotator_id(actor)
        r = _post(client, actor, [_seg(ann)])
        assert r.status_code == 200
        etag = r.headers.get("ETag")
        assert etag and etag != "0"

    def test_get_after_post_returns_matching_etag(self, client):
        # The token a client reads must equal the token the write produced,
        # otherwise the first save after a reload would always 409.
        actor = "alice"
        ann = _annotator_id(actor)
        post_r = _post(client, actor, [_seg(ann)])
        get_r = _get(client, actor)
        assert post_r.headers["ETag"] == get_r.headers["ETag"]

    def test_etag_changes_after_every_successful_write(self, client):
        # mtime_ns must advance across atomic os.replace on each write, or a
        # stale tab could overwrite without tripping the If-Match check.
        actor = "alice"
        ann = _annotator_id(actor)
        seen = set()
        for i in range(3):
            r = _post(client, actor, [_seg(ann, i * 10, i * 10 + 5)])
            assert r.status_code == 200
            seen.add(r.headers["ETag"])
        assert len(seen) == 3


class TestIfMatchConcurrency:
    def test_post_without_if_match_force_overwrites(self, client):
        # Backwards-compat: clients that don't send If-Match still win. This
        # is also the deliberate force-overwrite path after a 409.
        actor = "alice"
        ann = _annotator_id(actor)
        assert _post(client, actor, [_seg(ann)]).status_code == 200
        assert _post(client, actor, [_seg(ann, 20, 30)]).status_code == 200

    def test_post_with_matching_if_match_succeeds(self, client):
        actor = "alice"
        ann = _annotator_id(actor)
        etag1 = _post(client, actor, [_seg(ann)]).headers["ETag"]
        r2 = _post(client, actor, [_seg(ann, 20, 30)], if_match=etag1)
        assert r2.status_code == 200
        assert r2.headers["ETag"] != etag1  # etag advances on every write

    def test_first_save_with_if_match_zero_succeeds(self, client):
        # A tab that read before any file existed holds etag "0"; its first
        # save must go through (nothing to conflict with yet).
        actor = "alice"
        ann = _annotator_id(actor)
        initial = _get(client, actor).headers["ETag"]
        assert _post(client, actor, [_seg(ann)], if_match=initial).status_code == 200

    def test_post_with_stale_if_match_rejected_409(self, client, tmp_path):
        actor = "alice"
        ann = _annotator_id(actor)
        # Tab B reads the initial etag (file doesn't exist yet → "0").
        initial_etag = _get(client, actor).headers["ETag"]
        # Tab A writes first (no If-Match, so it succeeds).
        assert _post(client, actor, [_seg(ann)]).status_code == 200
        # Tab B now tries to write with its stale token.
        b = _post(client, actor, [_seg(ann, 50, 60)], if_match=initial_etag)
        assert b.status_code == 409
        detail = b.json()["detail"]
        assert detail["error"] == "stale_write"
        assert detail["provided_etag"] == initial_etag
        assert detail["expected_etag"] != initial_etag
        # The rejected write must not have replaced Tab A's content.
        out = (tmp_path / "demo_episode" / "meta" / "annotations" / ann
               / "subtask_segments.v1.jsonl")
        assert '"start_frame":50' not in out.read_text().replace(" ", "")


class TestPrincipalSignatureEnforced:
    """ETag plumbing must not weaken the principal-signature auth (issue #2)."""

    def test_post_with_if_match_but_no_signature_is_rejected(self, client):
        # A concurrency token without a signed principal is still unauthenticated:
        # the auth dependency rejects it with 403 before any write.
        actor = "alice"
        ann = _annotator_id(actor)
        r = client.post(
            "/api/embodied/segments",
            json={"episode_id": "demo_episode", "annotator_id": ann,
                  "segments": [_seg(ann)]},
            headers={"If-Match": "0"},  # concurrency token but no identity
        )
        assert r.status_code == 403

    def test_post_forged_signature_beats_stale_if_match(self, client, tmp_path):
        # Auth check runs before the concurrency check: a forged signature gets
        # 403 (not 409) even with a stale If-Match, and nothing is written.
        actor = "alice"
        ann = _annotator_id(actor)
        r = _post(
            client, actor, [_seg(ann)], if_match="12345",
            headers={
                "X-Embodied-Actor": actor,
                "X-Embodied-Role": "annotator",
                "X-Embodied-Signature": "forged",
            },
        )
        assert r.status_code == 403
        assert "invalid embodied platform principal signature" in r.text
        assert not (tmp_path / "demo_episode" / "meta" / "annotations" / ann).exists()

    def test_get_without_signature_is_rejected(self, client):
        actor = "alice"
        r = _get(client, actor, headers={})
        assert r.status_code == 403
