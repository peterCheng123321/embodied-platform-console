"""Tests for embodied-AI sub-task segment annotation."""
from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.embodied.schema import SubtaskSegment


class TestSubtaskSegmentSchema:
    def test_valid_segment_constructs(self):
        s = SubtaskSegment(
            annotator_id=uuid4(),
            episode_index=0,
            start_frame=10,
            end_frame=50,
            skill_id="reach",
        )
        assert s.start_frame == 10
        assert s.end_frame == 50
        assert s.success is None  # new optional field

    def test_end_frame_must_exceed_start(self):
        with pytest.raises(ValidationError, match="start_frame.*must be < end_frame"):
            SubtaskSegment(
                annotator_id=uuid4(),
                episode_index=0,
                start_frame=50,
                end_frame=50,  # equal is invalid
                skill_id="reach",
            )

    def test_success_flag_round_trips(self):
        s = SubtaskSegment(
            annotator_id=uuid4(),
            episode_index=0,
            start_frame=0,
            end_frame=10,
            skill_id="grasp",
            success=True,
        )
        assert s.success is True
        s2 = SubtaskSegment.model_validate_json(s.model_dump_json())
        assert s2.success is True


@pytest.fixture
def embodied_app(tmp_path, monkeypatch):
    """Standalone FastAPI app with only the embodied router — no DB pool."""
    monkeypatch.setenv("XINGJU_EMBODIED_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_DATA_ROOT", str(tmp_path / "platform"))
    monkeypatch.delenv("XINGJU_EMBODIED_PLATFORM_DSN", raising=False)
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


def _platform_repo(tmp_path):
    from api.embodied_platform.repository import JsonRepository

    return JsonRepository(tmp_path / "platform" / "state.json")


def _seed_platform_episode(tmp_path, *, dataset_id: str = "ds_platform") -> None:
    from api.embodied_platform.repository import empty_state

    state = empty_state()
    state["datasets"].append({
        "id": dataset_id,
        "name": "warehouse-pick-v1",
        "modality": "vision_language_action",
        "robot_type": "mobile_manipulator",
        "storage_uri": "file:///datasets/warehouse-pick-v1",
        "description": None,
        "episode_count": 2,
        "created_at": "2026-06-14T00:00:00+00:00",
        "trained_ready": False,
    })
    state["episodes"].append({
        "id": "ep_platform_1",
        "dataset_id": dataset_id,
        "episode_id": "episode_000001",
        "robot_cell": "warehouse-a",
        "frame_count": 140,
        "created_at": "2026-06-14T00:00:01+00:00",
    })
    _platform_repo(tmp_path).write(state)


class TestPostSegments:
    def test_writes_jsonl_at_expected_path(self, client, tmp_path):
        ann = "550e8400-e29b-41d4-a716-446655440000"
        body = {
            "episode_id": "demo_episode",
            "annotator_id": ann,
            "segments": [
                {"annotator_id": ann, "episode_index": 0, "start_frame": 0,
                 "end_frame": 50, "skill_id": "reach"},
                {"annotator_id": ann, "episode_index": 0, "start_frame": 50,
                 "end_frame": 100, "skill_id": "grasp"},
            ],
        }
        r = client.post("/api/embodied/segments", json=body, headers=_auth(ann))
        assert r.status_code == 200, r.text
        assert r.json()["written"] == 2
        out = tmp_path / "demo_episode" / "meta" / "annotations" / ann / "subtask_segments.v1.jsonl"
        assert out.exists()
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["skill_id"] == "reach"

    def test_response_does_not_leak_server_path(self, client, tmp_path):
        # #12: SegmentsResponse used to echo the on-disk path; that's a recon
        # leak with no client need. Assert the field is gone and that nothing
        # else in the response body contains the data-root prefix.
        ann = str(uuid4())
        r = client.post("/api/embodied/segments", json={
            "episode_id": "demo_episode",
            "annotator_id": ann,
            "segments": [{"annotator_id": ann, "episode_index": 0,
                          "start_frame": 0, "end_frame": 10, "skill_id": "reach"}],
        }, headers=_auth(ann))
        assert r.status_code == 200, r.text
        body = r.json()
        assert "path" not in body
        assert str(tmp_path) not in r.text
        assert "subtask_segments" not in r.text

    def test_rejects_bad_frame_order(self, client):
        ann = str(uuid4())
        body = {
            "episode_id": "demo_episode",
            "annotator_id": ann,
            "segments": [
                {"annotator_id": ann, "episode_index": 0, "start_frame": 50,
                 "end_frame": 10, "skill_id": "reach"},  # end < start
            ],
        }
        r = client.post("/api/embodied/segments", json=body, headers=_auth(ann))
        assert r.status_code == 422

    def test_rejects_zero_width_segment(self, client):
        # #8: [10, 10) is a zero-frame segment — must be rejected with 422,
        # not silently written. Edge-drag in the UI can produce this.
        ann = str(uuid4())
        body = {
            "episode_id": "demo_episode",
            "annotator_id": ann,
            "segments": [
                {"annotator_id": ann, "episode_index": 0, "start_frame": 10,
                 "end_frame": 10, "skill_id": "reach"},
            ],
        }
        r = client.post("/api/embodied/segments", json=body, headers=_auth(ann))
        assert r.status_code == 422

    def test_rejects_negative_start_frame(self, client):
        # #8: a negative start_frame is meaningless and the validator must
        # catch it (Field constraint + model_validator belt-and-suspenders).
        ann = str(uuid4())
        body = {
            "episode_id": "demo_episode",
            "annotator_id": ann,
            "segments": [
                {"annotator_id": ann, "episode_index": 0, "start_frame": -1,
                 "end_frame": 10, "skill_id": "reach"},
            ],
        }
        r = client.post("/api/embodied/segments", json=body, headers=_auth(ann))
        assert r.status_code == 422

    def test_post_without_annotator_header_is_forbidden(self, client):
        # #4: missing header => 422 (FastAPI dependency validation). The
        # important thing is the request never reaches the writer.
        ann = str(uuid4())
        body = {
            "episode_id": "demo_episode",
            "annotator_id": ann,
            "segments": [{"annotator_id": ann, "episode_index": 0,
                          "start_frame": 0, "end_frame": 10, "skill_id": "reach"}],
        }
        r = client.post("/api/embodied/segments", json=body)  # no header
        assert r.status_code == 422  # FastAPI missing-header validation

    def test_post_with_mismatched_annotator_header_is_forbidden(self, client, tmp_path):
        # #4: header UUID != body UUID — explicit 403, and nothing written.
        ann = str(uuid4())
        other = str(uuid4())
        body = {
            "episode_id": "demo_episode",
            "annotator_id": ann,
            "segments": [{"annotator_id": ann, "episode_index": 0,
                          "start_frame": 0, "end_frame": 10, "skill_id": "reach"}],
        }
        r = client.post("/api/embodied/segments", json=body, headers=_auth(other))
        assert r.status_code == 403
        assert "annotator_id mismatch" in r.text
        out = tmp_path / "demo_episode" / "meta" / "annotations" / ann
        assert not out.exists()

    def test_creates_annotator_subdir(self, client, tmp_path):
        ann = str(uuid4())
        client.post("/api/embodied/segments", json={
            "episode_id": "demo_episode",
            "annotator_id": ann,
            "segments": [{"annotator_id": ann, "episode_index": 0,
                          "start_frame": 0, "end_frame": 10, "skill_id": "idle"}],
        }, headers=_auth(ann))
        assert (tmp_path / "demo_episode" / "meta" / "annotations" / ann).is_dir()

    def test_full_replace_overwrites(self, client, tmp_path):
        ann = str(uuid4())
        # First POST: 3 segments
        client.post("/api/embodied/segments", json={
            "episode_id": "demo_episode",
            "annotator_id": ann,
            "segments": [
                {"annotator_id": ann, "episode_index": 0, "start_frame": i*10,
                 "end_frame": i*10+5, "skill_id": "reach"} for i in range(3)
            ],
        }, headers=_auth(ann))
        # Second POST: 1 segment
        client.post("/api/embodied/segments", json={
            "episode_id": "demo_episode",
            "annotator_id": ann,
            "segments": [{"annotator_id": ann, "episode_index": 0,
                          "start_frame": 100, "end_frame": 200, "skill_id": "place"}],
        }, headers=_auth(ann))
        out = tmp_path / "demo_episode" / "meta" / "annotations" / ann / "subtask_segments.v1.jsonl"
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0])["skill_id"] == "place"

    def test_rejects_path_traversal_in_episode_id(self, client):
        ann = str(uuid4())
        body = {
            "episode_id": "../../etc/pwn",
            "annotator_id": ann,
            "segments": [{"annotator_id": ann, "episode_index": 0,
                          "start_frame": 0, "end_frame": 10, "skill_id": "reach"}],
        }
        r = client.post("/api/embodied/segments", json=body, headers=_auth(ann))
        assert r.status_code == 422

    def test_syncs_save_to_platform_annotation_task(self, client, tmp_path):
        _seed_platform_episode(tmp_path)
        ann = str(uuid4())

        first = client.post(
            "/api/embodied/segments",
            json={
                "episode_id": "ds_platform_ep1",
                "dataset_id": "ds_platform",
                "episode_index": 1,
                "annotator_id": ann,
                "segments": [{
                    "annotator_id": ann,
                    "episode_index": 1,
                    "start_frame": 0,
                    "end_frame": 12,
                    "skill_id": "reach",
                    "instruction_text": "approach the cube",
                    "success": True,
                }],
            },
            headers=_auth(ann),
        )

        assert first.status_code == 200, first.text
        body = first.json()
        assert body["written"] == 1
        assert body["platform_synced"] is True
        task_id = body["platform_task_id"]
        state = _platform_repo(tmp_path).read()
        assert len(state["annotation_tasks"]) == 1
        task = state["annotation_tasks"][0]
        assert task["id"] == task_id
        assert task["dataset_id"] == "ds_platform"
        assert task["episode_id"] == "episode_000001"
        assert task["assignee"] == ann
        assert task["label_count"] == 1
        assert task["labels"][0]["instruction_text"] == "approach the cube"
        assert task["labels"][0]["success"] is True
        assert any(event["action"] == "annotation.sync.create" for event in state["audit_events"])

        second = client.post(
            "/api/embodied/segments",
            json={
                "episode_id": "ds_platform_ep1",
                "dataset_id": "ds_platform",
                "episode_index": 1,
                "annotator_id": ann,
                "segments": [{
                    "annotator_id": ann,
                    "episode_index": 1,
                    "start_frame": 20,
                    "end_frame": 40,
                    "skill_id": "grasp",
                }],
            },
            headers=_auth(ann),
        )

        assert second.status_code == 200, second.text
        assert second.json()["platform_task_id"] == task_id
        state = _platform_repo(tmp_path).read()
        assert len(state["annotation_tasks"]) == 1
        assert state["annotation_tasks"][0]["label_count"] == 1
        assert state["annotation_tasks"][0]["labels"][0]["skill_id"] == "grasp"
        assert any(event["action"] == "annotation.sync.update" for event in state["audit_events"])

    def test_platform_sync_skip_does_not_block_jsonl_save(self, client, tmp_path):
        ann = str(uuid4())
        saved = client.post(
            "/api/embodied/segments",
            json={
                "episode_id": "missing_dataset_ep0",
                "dataset_id": "missing_dataset",
                "episode_index": 0,
                "annotator_id": ann,
                "segments": [{
                    "annotator_id": ann,
                    "episode_index": 0,
                    "start_frame": 0,
                    "end_frame": 10,
                    "skill_id": "reach",
                }],
            },
            headers=_auth(ann),
        )

        assert saved.status_code == 200, saved.text
        assert saved.json()["platform_synced"] is False
        assert saved.json()["platform_sync_reason"] == "platform dataset or episode not found"
        out = tmp_path / "missing_dataset_ep0" / "meta" / "annotations" / ann / "subtask_segments.v1.jsonl"
        assert out.exists()
        assert _platform_repo(tmp_path).read()["annotation_tasks"] == []

    def test_demo_save_creates_platform_demo_task(self, client, tmp_path):
        ann = str(uuid4())
        saved = client.post(
            "/api/embodied/segments",
            json={
                "episode_id": "demo_episode",
                "dataset_id": "demo",
                "episode_index": 0,
                "annotator_id": ann,
                "segments": [{
                    "annotator_id": ann,
                    "episode_index": 0,
                    "start_frame": 0,
                    "end_frame": 10,
                    "skill_id": "reach",
                }],
            },
            headers=_auth(ann),
        )

        assert saved.status_code == 200, saved.text
        assert saved.json()["platform_synced"] is True
        state = _platform_repo(tmp_path).read()
        assert state["datasets"][0]["id"] == "demo"
        assert state["episodes"][0]["episode_id"] == "demo_episode"
        assert len(state["annotation_tasks"]) == 1
        assert state["annotation_tasks"][0]["dataset_id"] == "demo"
        assert state["annotation_tasks"][0]["episode_id"] == "demo_episode"

    def test_platform_sync_exception_does_not_block_jsonl_save(self, client, tmp_path, monkeypatch):
        from api.embodied import routes as routes_mod

        def fail_sync(**_kwargs):
            raise RuntimeError("control plane unavailable")

        monkeypatch.setattr(routes_mod, "sync_labeler_segments_to_platform", fail_sync)
        ann = str(uuid4())
        saved = client.post(
            "/api/embodied/segments",
            json={
                "episode_id": "ds_platform_ep0",
                "dataset_id": "ds_platform",
                "episode_index": 0,
                "annotator_id": ann,
                "segments": [{
                    "annotator_id": ann,
                    "episode_index": 0,
                    "start_frame": 0,
                    "end_frame": 10,
                    "skill_id": "reach",
                }],
            },
            headers=_auth(ann),
        )

        assert saved.status_code == 200, saved.text
        assert saved.json()["platform_synced"] is False
        assert saved.json()["platform_sync_reason"] == "platform sync failed"
        out = tmp_path / "ds_platform_ep0" / "meta" / "annotations" / ann / "subtask_segments.v1.jsonl"
        assert out.exists()


class TestGetSegments:
    def test_empty_when_no_file(self, client):
        ann = str(uuid4())
        r = client.get(
            f"/api/embodied/segments?episode_id=demo_episode&annotator_id={ann}",
            headers=_auth(ann),
        )
        assert r.status_code == 200
        assert r.json() == []

    def test_round_trip(self, client):
        ann = str(uuid4())
        seg = {"annotator_id": ann, "episode_index": 0, "start_frame": 0,
               "end_frame": 50, "skill_id": "reach", "success": True}
        client.post("/api/embodied/segments", json={
            "episode_id": "demo_episode",
            "annotator_id": ann,
            "segments": [seg],
        }, headers=_auth(ann))
        r = client.get(
            f"/api/embodied/segments?episode_id=demo_episode&annotator_id={ann}",
            headers=_auth(ann),
        )
        assert r.status_code == 200
        got = r.json()
        assert len(got) == 1
        assert got[0]["skill_id"] == "reach"
        assert got[0]["success"] is True

    def test_get_without_annotator_header_is_forbidden(self, client):
        # #4 mirror: GET also requires the header.
        ann = str(uuid4())
        r = client.get(f"/api/embodied/segments?episode_id=demo_episode&annotator_id={ann}")
        assert r.status_code == 422

    def test_get_with_mismatched_annotator_header_is_forbidden(self, client):
        # #4 mirror: header != query => 403, nothing returned.
        ann = str(uuid4())
        other = str(uuid4())
        r = client.get(
            f"/api/embodied/segments?episode_id=demo_episode&annotator_id={ann}",
            headers=_auth(other),
        )
        assert r.status_code == 403

    def test_rejects_path_traversal_in_get(self, client):
        ann = str(uuid4())
        r = client.get(
            f"/api/embodied/segments?episode_id=../../etc/pwn&annotator_id={ann}",
            headers=_auth(ann),
        )
        assert r.status_code == 422

    def test_get_skips_legacy_degenerate_segments(self, client, tmp_path):
        # B-R1: a JSONL file written before the end>start invariant was
        # enforced will contain degenerate lines. The GET handler must
        # skip those rather than 500 the whole page. We write the file
        # directly (bypassing POST so the validator can't reject) and
        # assert the response keeps only the well-formed segments.
        ann = str(uuid4())
        episode_id = "demo_episode"
        out = tmp_path / episode_id / "meta" / "annotations" / ann / "subtask_segments.v1.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            {"annotator_id": ann, "episode_index": 0, "start_frame": 5,
             "end_frame": 15, "skill_id": "reach"},
            {"annotator_id": ann, "episode_index": 0, "start_frame": 10,
             "end_frame": 10, "skill_id": "bad"},  # degenerate, must be skipped
            {"annotator_id": ann, "episode_index": 0, "start_frame": 20,
             "end_frame": 30, "skill_id": "grasp"},
        ]
        out.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

        r = client.get(
            f"/api/embodied/segments?episode_id={episode_id}&annotator_id={ann}",
            headers=_auth(ann),
        )
        assert r.status_code == 200, r.text
        got = r.json()
        assert len(got) == 2
        assert [g["skill_id"] for g in got] == ["reach", "grasp"]
