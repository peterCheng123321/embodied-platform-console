"""Repository + schema robustness tests ported from the codex/embodied-platform branch.

Pins the hardened persistence behavior:
- corrupt / non-dict / wrong-shape on-disk state degrades to empty_state (never 500),
- an unwritable lock path degrades SHARED reads to best-effort unlocked reads,
- the state file is always RFC-8259 JSON (json.dump allow_nan=False),
- ModelVersionCreate.metrics rejects NaN/Inf values and bounds key count/length.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from .repository_contract import ALL_CONTRACTS


LOGIN_PASSCODE = "pytest-login-passcode"

# Marks tests that exercise JSON-file storage mechanics by definition (state
# file + flock lock-path behavior), so they only run in JSON-file mode.
_JSON_FILE_ONLY = pytest.mark.skipif(
    bool(os.environ.get("XINGJU_EMBODIED_PLATFORM_DSN", "").strip()),
    reason="exercises JSON-file storage mechanics; the PG equivalent lives in test_pg_repository.py",
)


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_AUTH_SECRET", "pytest-embodied-platform-secret")
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_LOGIN_PASSCODE", LOGIN_PASSCODE)
    from api.embodied_platform.routes import register_validation_handlers, router

    app = FastAPI()
    app.include_router(router)
    register_validation_handlers(app)
    return TestClient(app)


def _headers(role: str, actor: str) -> dict[str, str]:
    from api.embodied_platform.routes import sign_principal

    return {
        "X-Embodied-Role": role,
        "X-Embodied-Actor": actor,
        "X-Embodied-Signature": sign_principal(actor, role),
    }


def _admin_headers() -> dict[str, str]:
    return _headers("admin", "pytest-admin")


def _ml_headers() -> dict[str, str]:
    return _headers("ml_engineer", "pytest-ml")


def _annotator_headers() -> dict[str, str]:
    return _headers("annotator", "labeler-a")


def _create_dataset(client: TestClient, name: str = "warehouse-pick-v1") -> dict:
    response = client.post(
        "/api/embodied-platform/datasets",
        headers=_admin_headers(),
        json={
            "name": name,
            "modality": "vision_language_action",
            "robot_type": "mobile_manipulator",
            "storage_uri": f"file:///datasets/{name}",
            "description": "Pick and place episodes from demo fixtures.",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_episode(client: TestClient, dataset_id: str, episode_id: str = "episode-000042") -> dict:
    response = client.post(
        "/api/embodied-platform/episodes",
        headers=_admin_headers(),
        json={
            "dataset_id": dataset_id,
            "episode_id": episode_id,
            "robot_cell": "warehouse-a",
            "frame_count": 240,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _reject_constant(value):  # pragma: no cover - helper raises on NaN/Infinity tokens
    raise ValueError(f"non-spec JSON constant in state file: {value}")


@pytest.mark.parametrize("contract", ALL_CONTRACTS, ids=lambda fn: fn.__name__)
def test_json_repository_satisfies_shared_contract(contract, tmp_path):
    """The backend-agnostic repository contract (repository_contract.py) must
    hold for JsonRepository — proven against today's behavior FIRST, then
    reused verbatim by the Postgres backend tests (test_pg_repository.py)."""
    from api.embodied_platform.repository import JsonRepository

    contract(lambda: JsonRepository(tmp_path / "state.json"))


def test_corrupt_state_file_degrades_to_empty_state_not_500(tmp_path, monkeypatch):
    """Missing/corrupt/non-dict on-disk state must degrade to empty_state on read,
    never propagate a 500 to every read endpoint."""
    for content in ('"x"', "5", '{"datasets":5}', "{ bad json"):
        root = Path(tmp_path) / f"root-{abs(hash(content))}"
        root.mkdir(parents=True, exist_ok=True)
        (root / "state.json").write_text(content)
        monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_DATA_ROOT", str(root))
        monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_AUTH_SECRET", "pytest-embodied-platform-secret")
        from api.embodied_platform.routes import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=False)

        datasets = client.get("/api/embodied-platform/datasets")
        assert datasets.status_code == 200, f"{content!r}: {datasets.status_code}"
        assert datasets.json() == []

        overview = client.get("/api/embodied-platform/monitoring/overview")
        assert overview.status_code == 200, f"{content!r}: {overview.status_code}"


def test_repository_writes_spec_compliant_json_rejecting_nan(tmp_path):
    """The repository must write with allow_nan=False so the on-disk state file is
    always RFC-8259 JSON even if a NaN slips past the API layer."""
    import math

    from api.embodied_platform.repository import JsonRepository

    repo = JsonRepository(tmp_path / "state.json")

    def _mutate(state: dict) -> None:
        state["models"].append({"id": "m1", "metrics": {"loss": math.nan}})
        return None

    try:
        repo.mutate(_mutate)
    except ValueError:
        # Acceptable: the write refuses to persist non-spec JSON.
        pass
    # If a state.json exists, it must parse with a strict (non-NaN) JSON parser.
    state_file = tmp_path / "state.json"
    if state_file.exists():
        import json

        json.loads(state_file.read_text(), parse_constant=_reject_constant)


@_JSON_FILE_ONLY
def test_unwritable_lock_path_still_serves_reads_200(tmp_path, monkeypatch):
    """A read-only / unwritable data root must NOT 500 every endpoint. The
    file lock is opened in append-create mode on the read path; if the lock file
    cannot be created, a SHARED read must degrade to a best-effort unlocked read
    (the in-process RLock still serializes readers) so unauthenticated GETs keep
    working on an ops misconfig — instead of every endpoint 500ing.

    We make the lock UNCREATABLE deterministically (and without chmod, which is a
    no-op under root) by pre-creating ``state.json.lock`` as a DIRECTORY: opening
    it in append mode raises IsADirectoryError (an OSError), exercising the
    read-resilience branch. The seeded dataset must still come back, proving a real
    read happened (not just the empty-state fallback)."""
    import json as _json

    from api.embodied_platform.repository import COLLECTIONS

    root = Path(tmp_path)
    state = {name: [] for name in COLLECTIONS}
    state["system_settings"] = {}
    state["datasets"] = [
        {
            "id": "ds-readonly",
            "name": "readonly-ds",
            "modality": "vision_language_action",
            "robot_type": "so100",
            "storage_uri": "file:///datasets/readonly",
            "description": None,
            "episode_count": 0,
            "created_at": "2026-05-30T00:00:00+00:00",
        }
    ]
    # Direct write (a client write is blocked) so the lock dir can't interfere yet.
    (root / "state.json").write_text(_json.dumps(state))
    # Make the lock path UNCREATABLE: a directory cannot be opened in append mode.
    (root / "state.json.lock").mkdir()

    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_DATA_ROOT", str(root))
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_AUTH_SECRET", "pytest-embodied-platform-secret")
    from api.embodied_platform.routes import router

    app = FastAPI()
    app.include_router(router)
    read_client = TestClient(app, raise_server_exceptions=False)

    response = read_client.get("/api/embodied-platform/datasets")
    assert response.status_code == 200, response.text
    # A genuine read of the seeded state, not the empty-state degrade.
    assert [d["id"] for d in response.json()] == ["ds-readonly"]


def test_model_metrics_nan_is_rejected_422_not_silent_null(tmp_path, monkeypatch):
    """NaN/Infinity metric values must be rejected (422), not silently coerced to
    null on read-back or persisted as non-spec JSON tokens."""
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/embodied-platform/models",
        headers={**_ml_headers(), "Content-Type": "application/json"},
        content='{"name":"m","version":"1","artifact_uri":"s3://x","metrics":{"acc":NaN,"loss":Infinity}}',
    )
    assert response.status_code == 422, response.text


def test_oversized_metrics_dict_is_rejected_422(tmp_path, monkeypatch):
    """An unbounded metrics dict lets one write balloon shared state.json; cap it."""
    client = _client(tmp_path, monkeypatch)

    metrics = {f"k{i}": 0.1 for i in range(500)}
    response = client.post(
        "/api/embodied-platform/models",
        headers=_ml_headers(),
        json={"name": "m", "version": "1", "artifact_uri": "s3://x", "metrics": metrics},
    )
    assert response.status_code == 422, response.status_code


def test_metric_key_length_is_bounded_422(tmp_path, monkeypatch):
    """The metrics validator must bound key LENGTH, not just key count. The
    count cap alone (<=100 keys) leaves a single key unbounded, so one POST /models
    could persist ~100 MB of key bytes into the SHARED state.json — re-parsed on
    every later read/write, slowing the platform for ALL principals. A single
    oversized metric KEY (count == 1, so the count cap cannot fire) must 422 before
    it is persisted. Guards the key-length cap specifically, distinct from the
    existing key-COUNT cap test."""
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/embodied-platform/models",
        headers=_ml_headers(),
        json={
            "name": "m",
            "version": "1",
            "artifact_uri": "s3://x",
            # One key (count cap can't fire), 129 chars (> the 128 length cap).
            "metrics": {"k" * 129: 0.1},
        },
    )
    assert response.status_code == 422, response.status_code
    # And it must NOT have been persisted: no model row survives the rejection.
    assert client.get("/api/embodied-platform/models").json() == []


def test_valid_metrics_and_confidence_round_trip_through_full_stack(tmp_path, monkeypatch):
    """Guards the hardened fields' happy path: valid metric floats and a valid
    confidence must persist and read back intact, and the persisted state must
    be spec JSON. Without this, the NaN/cap changes could silently break model
    metric tracking while every rejection test still passes."""
    import json

    client = _client(tmp_path, monkeypatch)
    dataset = _create_dataset(client)
    _create_episode(client, dataset["id"])

    model = client.post(
        "/api/embodied-platform/models",
        headers=_ml_headers(),
        json={
            "name": "metrics-policy",
            "version": "2.0.0",
            "artifact_uri": "models://policy/2",
            "metrics": {"success_rate": 0.92, "loss": 0.13},
        },
    )
    assert model.status_code == 200, model.text
    assert model.json()["metrics"] == {"success_rate": 0.92, "loss": 0.13}

    listed = client.get("/api/embodied-platform/models").json()
    assert listed[0]["metrics"] == {"success_rate": 0.92, "loss": 0.13}

    annotation = client.post(
        "/api/embodied-platform/annotation-tasks",
        headers=_annotator_headers(),
        json={
            "dataset_id": dataset["id"],
            "episode_id": "episode-000042",
            "task_type": "trajectory_segment",
            "assignee": "annotator-a",
            "labels": [{"start_frame": 0, "end_frame": 64, "skill_id": "grasp", "confidence": 0.8}],
        },
    )
    assert annotation.status_code == 200, annotation.text
    assert annotation.json()["labels"][0]["confidence"] == 0.8

    # The persisted state (either backend) must re-serialize as strict spec
    # JSON — allow_nan=False raises if any NaN/Infinity reached the stored
    # floats — and the metrics must have survived persistence intact.
    from api.embodied_platform.repository import get_repository

    state = get_repository().read()
    json.dumps(state, allow_nan=False)
    assert state["models"][0]["metrics"] == {"success_rate": 0.92, "loss": 0.13}
