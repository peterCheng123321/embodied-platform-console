"""ETag/If-Match optimistic concurrency for /api/embodied/segments.

Two tabs editing the same annotator's file must not silently overwrite each
other. Mechanism: GET (and POST) return the current file's mtime_ns as an
ETag header; the client echoes it back as If-Match on POST; the backend
rejects with 409 stale_write when the file has moved on. Omitting If-Match
is a deliberate force-overwrite — both the back-compat path for old clients
and the manual "save again" retry after a conflict.
"""
from __future__ import annotations

from uuid import uuid4

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


def _auth(ann: str) -> dict[str, str]:
    """Helper: build the X-Annotator-Id header all real callers send."""
    return {"X-Annotator-Id": ann}


def _seg(ann: str, start: int = 0, end: int = 10) -> dict:
    return {"annotator_id": ann, "episode_index": 0,
            "start_frame": start, "end_frame": end, "skill_id": "reach"}


def _post(client, ann, segs, if_match=None, header_ann=None):
    headers = _auth(header_ann if header_ann is not None else ann)
    if if_match is not None:
        headers["If-Match"] = if_match
    return client.post(
        "/api/embodied/segments",
        json={"episode_id": "demo_episode", "annotator_id": ann, "segments": segs},
        headers=headers,
    )


def _get(client, ann, headers=None):
    return client.get(
        f"/api/embodied/segments?episode_id=demo_episode&annotator_id={ann}",
        headers=headers if headers is not None else _auth(ann),
    )


class TestEtagHeaders:
    def test_get_returns_etag_zero_before_first_write(self, client):
        # ETag is present even for a not-yet-existing file (value: "0"), so a
        # first save can still be conflict-checked against "nothing written".
        ann = str(uuid4())
        r = _get(client, ann)
        assert r.status_code == 200
        assert r.headers.get("ETag") == "0"

    def test_post_returns_new_etag(self, client):
        ann = str(uuid4())
        r = _post(client, ann, [_seg(ann)])
        assert r.status_code == 200
        etag = r.headers.get("ETag")
        assert etag and etag != "0"

    def test_get_after_post_returns_matching_etag(self, client):
        # The token a client reads must equal the token the write produced,
        # otherwise the first save after a reload would always 409.
        ann = str(uuid4())
        post_r = _post(client, ann, [_seg(ann)])
        get_r = _get(client, ann)
        assert post_r.headers["ETag"] == get_r.headers["ETag"]

    def test_etag_changes_after_every_successful_write(self, client):
        # mtime_ns must advance across atomic os.replace on each write, or a
        # stale tab could overwrite without tripping the If-Match check.
        ann = str(uuid4())
        seen = set()
        for i in range(3):
            r = _post(client, ann, [_seg(ann, i * 10, i * 10 + 5)])
            assert r.status_code == 200
            seen.add(r.headers["ETag"])
        assert len(seen) == 3


class TestIfMatchConcurrency:
    def test_post_without_if_match_force_overwrites(self, client):
        # Backwards-compat: clients that don't send If-Match still win. This
        # is also the deliberate force-overwrite path after a 409.
        ann = str(uuid4())
        assert _post(client, ann, [_seg(ann)]).status_code == 200
        assert _post(client, ann, [_seg(ann, 20, 30)]).status_code == 200

    def test_post_with_matching_if_match_succeeds(self, client):
        ann = str(uuid4())
        etag1 = _post(client, ann, [_seg(ann)]).headers["ETag"]
        r2 = _post(client, ann, [_seg(ann, 20, 30)], if_match=etag1)
        assert r2.status_code == 200
        assert r2.headers["ETag"] != etag1  # etag advances on every write

    def test_first_save_with_if_match_zero_succeeds(self, client):
        # A tab that read before any file existed holds etag "0"; its first
        # save must go through (nothing to conflict with yet).
        ann = str(uuid4())
        initial = _get(client, ann).headers["ETag"]
        assert _post(client, ann, [_seg(ann)], if_match=initial).status_code == 200

    def test_post_with_stale_if_match_rejected_409(self, client, tmp_path):
        ann = str(uuid4())
        # Tab B reads the initial etag (file doesn't exist yet → "0").
        initial_etag = _get(client, ann).headers["ETag"]
        # Tab A writes first (no If-Match, so it succeeds).
        assert _post(client, ann, [_seg(ann)]).status_code == 200
        # Tab B now tries to write with its stale token.
        b = _post(client, ann, [_seg(ann, 50, 60)], if_match=initial_etag)
        assert b.status_code == 409
        detail = b.json()["detail"]
        assert detail["error"] == "stale_write"
        assert detail["provided_etag"] == initial_etag
        assert detail["expected_etag"] != initial_etag
        # The rejected write must not have replaced Tab A's content.
        out = (tmp_path / "demo_episode" / "meta" / "annotations" / ann
               / "subtask_segments.v1.jsonl")
        assert '"start_frame":50' not in out.read_text().replace(" ", "")


class TestAnnotatorHeaderStillEnforced:
    """ETag plumbing must not weaken the X-Annotator-Id defense-in-depth."""

    def test_post_with_if_match_but_no_annotator_header_is_rejected(self, client):
        ann = str(uuid4())
        r = client.post(
            "/api/embodied/segments",
            json={"episode_id": "demo_episode", "annotator_id": ann,
                  "segments": [_seg(ann)]},
            headers={"If-Match": "0"},  # concurrency token but no identity
        )
        assert r.status_code == 422  # FastAPI missing-header validation

    def test_post_auth_mismatch_beats_stale_if_match(self, client, tmp_path):
        # Auth check runs before the concurrency check: a mismatched header
        # gets 403 (not 409), and nothing is written.
        ann = str(uuid4())
        other = str(uuid4())
        r = _post(client, ann, [_seg(ann)], if_match="12345", header_ann=other)
        assert r.status_code == 403
        assert "annotator_id mismatch" in r.text
        assert not (tmp_path / "demo_episode" / "meta" / "annotations" / ann).exists()

    def test_get_without_annotator_header_is_rejected(self, client):
        ann = str(uuid4())
        r = _get(client, ann, headers={})
        assert r.status_code == 422
