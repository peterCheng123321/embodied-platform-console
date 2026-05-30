"""Tests for the embodied-only platform MVP API."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _write_dataset_in_process(path: str, index: int) -> int:
    from pathlib import Path

    from api.embodied_platform.repository import JsonRepository

    repo = JsonRepository(Path(path) / "state.json")

    def _mutate(state: dict) -> int:
        dataset_id = f"ds-process-{index}"
        state["datasets"].append(
            {
                "id": dataset_id,
                "name": f"process-dataset-{index}",
                "modality": "vision_language_action",
                "robot_type": "mobile_manipulator",
                "storage_uri": f"file:///datasets/process-{index}",
                "description": None,
                "episode_count": 0,
                "created_at": "2026-05-30T00:00:00+00:00",
            }
        )
        state["audit_events"].append(
            {
                "id": f"audit-process-{index}",
                "action": "dataset.create",
                "resource": dataset_id,
                "detail": f"process-dataset-{index}",
                "actor": "pytest",
                "role": "admin",
                "created_at": "2026-05-30T00:00:00+00:00",
            }
        )
        return index

    return repo.mutate(_mutate)


LOGIN_PASSCODE = "pytest-login-passcode"


def _client(
    tmp_path,
    monkeypatch,
    *,
    configure_secret: bool = True,
    configure_passcode: bool = True,
) -> TestClient:
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_DATA_ROOT", str(tmp_path))
    if configure_secret:
        monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_AUTH_SECRET", "pytest-embodied-platform-secret")
    else:
        monkeypatch.delenv("XINGJU_EMBODIED_PLATFORM_AUTH_SECRET", raising=False)
    if configure_passcode:
        monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_LOGIN_PASSCODE", LOGIN_PASSCODE)
    else:
        monkeypatch.delenv("XINGJU_EMBODIED_PLATFORM_LOGIN_PASSCODE", raising=False)
    from api.embodied_platform.routes import router

    app = FastAPI()
    app.include_router(router)
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


def _deployment_headers() -> dict[str, str]:
    return _headers("deployment_operator", "pytest-edge")


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


def _create_model(client: TestClient) -> dict:
    response = client.post(
        "/api/embodied-platform/models",
        headers=_ml_headers(),
        json={"name": "mobile-policy", "version": "1.0.0", "artifact_uri": "models://policy/1"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_dataset_creation_and_listing_uses_json_repository(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    body = _create_dataset(client)
    assert body["name"] == "warehouse-pick-v1"
    assert body["episode_count"] == 0

    listed = client.get("/api/embodied-platform/datasets")
    assert listed.status_code == 200
    assert [item["name"] for item in listed.json()] == ["warehouse-pick-v1"]


def test_episode_creation_increments_dataset_and_rejects_missing_dataset(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    dataset = _create_dataset(client)

    missing = client.post(
        "/api/embodied-platform/episodes",
        headers=_admin_headers(),
        json={"dataset_id": "missing-dataset", "episode_id": "episode-orphan", "frame_count": 20},
    )
    assert missing.status_code == 422

    episode = _create_episode(client, dataset["id"])
    assert episode["dataset_id"] == dataset["id"]

    datasets = client.get("/api/embodied-platform/datasets").json()
    assert datasets[0]["episode_count"] == 1

    episodes = client.get("/api/embodied-platform/episodes").json()
    assert [item["episode_id"] for item in episodes] == ["episode-000042"]


def test_duplicate_episode_identity_is_rejected_without_count_increment(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    dataset = _create_dataset(client)
    _create_episode(client, dataset["id"], "episode-dup")

    duplicate = client.post(
        "/api/embodied-platform/episodes",
        headers=_admin_headers(),
        json={
            "dataset_id": dataset["id"],
            "episode_id": "episode-dup",
            "robot_cell": "warehouse-a",
            "frame_count": 240,
        },
    )
    assert duplicate.status_code == 409

    datasets = client.get("/api/embodied-platform/datasets").json()
    episodes = client.get("/api/embodied-platform/episodes").json()
    assert datasets[0]["episode_count"] == 1
    assert len(episodes) == 1


def test_signed_write_authentication_rejects_forged_principals(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    payload = {
        "name": "warehouse-pick-v1",
        "modality": "vision_language_action",
        "robot_type": "mobile_manipulator",
        "storage_uri": "file:///datasets/warehouse-pick-v1",
    }

    no_signature = client.post(
        "/api/embodied-platform/datasets",
        headers={"X-Embodied-Role": "admin", "X-Embodied-Actor": "attacker"},
        json=payload,
    )
    assert no_signature.status_code == 403

    bad_signature = client.post(
        "/api/embodied-platform/datasets",
        headers={
            "X-Embodied-Role": "admin",
            "X-Embodied-Actor": "attacker",
            "X-Embodied-Signature": "not-valid",
        },
        json=payload,
    )
    assert bad_signature.status_code == 403

    signed = client.post("/api/embodied-platform/datasets", headers=_admin_headers(), json=payload)
    assert signed.status_code == 200, signed.text


def test_writes_fail_closed_without_configured_auth_secret(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, configure_secret=False)

    response = client.post(
        "/api/embodied-platform/datasets",
        headers={
            "X-Embodied-Role": "admin",
            "X-Embodied-Actor": "attacker",
            "X-Embodied-Signature": "forged",
        },
        json={
            "name": "warehouse-pick-v1",
            "modality": "vision_language_action",
            "robot_type": "mobile_manipulator",
            "storage_uri": "file:///datasets/warehouse-pick-v1",
        },
    )

    assert response.status_code == 503


def test_duplicate_dataset_identity_is_rejected(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _create_dataset(client)

    duplicate_name = client.post(
        "/api/embodied-platform/datasets",
        headers=_admin_headers(),
        json={
            "name": "warehouse-pick-v1",
            "modality": "vision_language_action",
            "robot_type": "mobile_manipulator",
            "storage_uri": "file:///datasets/warehouse-pick-v1-copy",
        },
    )
    assert duplicate_name.status_code == 409

    duplicate_storage = client.post(
        "/api/embodied-platform/datasets",
        headers=_admin_headers(),
        json={
            "name": "warehouse-pick-copy",
            "modality": "vision_language_action",
            "robot_type": "mobile_manipulator",
            "storage_uri": "file:///datasets/warehouse-pick-v1",
        },
    )
    assert duplicate_storage.status_code == 409


def test_import_job_lifecycle_and_job_state_transitions(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    dataset = _create_dataset(client)

    import_job = client.post(
        "/api/embodied-platform/imports",
        headers=_admin_headers(),
        json={
            "source_uri": "s3://robot-lake/run-042",
            "dataset_name": "run-042",
            "format": "lerobot",
        },
    )
    assert import_job.status_code == 200, import_job.text
    import_id = import_job.json()["id"]

    running_import = client.patch(
        f"/api/embodied-platform/imports/{import_id}/status",
        headers=_admin_headers(),
        json={"status": "running", "message": "decoder started"},
    )
    assert running_import.status_code == 200, running_import.text
    assert running_import.json()["status"] == "running"

    training_job = client.post(
        "/api/embodied-platform/training-jobs",
        headers=_admin_headers(),
        json={
            "name": "rt-policy-smoke",
            "dataset_id": dataset["id"],
            "base_model": "rt-2-x",
            "optimizer": "lora",
        },
    )
    assert training_job.status_code == 200, training_job.text
    training_id = training_job.json()["id"]

    claimed = client.patch(
        f"/api/embodied-platform/training-jobs/{training_id}/status",
        headers=_admin_headers(),
        json={"status": "running", "message": "worker claimed job"},
    )
    assert claimed.status_code == 200, claimed.text

    completed = client.patch(
        f"/api/embodied-platform/training-jobs/{training_id}/status",
        headers=_admin_headers(),
        json={"status": "succeeded", "message": "metrics archived"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "succeeded"


def test_annotation_task_save_and_list(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    dataset = _create_dataset(client)
    _create_episode(client, dataset["id"])

    saved = client.post(
        "/api/embodied-platform/annotation-tasks",
        headers=_admin_headers(),
        json={
            "dataset_id": dataset["id"],
            "episode_id": "episode-000042",
            "task_type": "trajectory_segment",
            "assignee": "annotator-a",
            "labels": [
                {"start_frame": 0, "end_frame": 64, "skill_id": "approach"},
                {"start_frame": 65, "end_frame": 140, "skill_id": "grasp"},
            ],
            "status": "review",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["label_count"] == 2

    listed = client.get("/api/embodied-platform/annotation-tasks")
    assert listed.status_code == 200
    assert listed.json()[0]["episode_id"] == "episode-000042"
    assert listed.json()[0]["status"] == "review"


def test_annotation_rejects_degenerate_segments(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    dataset = _create_dataset(client)
    _create_episode(client, dataset["id"])

    rejected = client.post(
        "/api/embodied-platform/annotation-tasks",
        headers=_annotator_headers(),
        json={
            "dataset_id": dataset["id"],
            "episode_id": "episode-000042",
            "task_type": "trajectory_segment",
            "assignee": "annotator-a",
            "labels": [{"start_frame": 42, "end_frame": 42, "skill_id": "grasp"}],
        },
    )

    assert rejected.status_code == 422


def test_annotation_rejects_episode_from_another_dataset(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    first_dataset = _create_dataset(client, "warehouse-pick-v1")
    second_dataset = _create_dataset(client, "hotel-service-v1")
    _create_episode(client, second_dataset["id"], "hotel-episode-0001")

    rejected = client.post(
        "/api/embodied-platform/annotation-tasks",
        headers=_annotator_headers(),
        json={
            "dataset_id": first_dataset["id"],
            "episode_id": "hotel-episode-0001",
            "task_type": "trajectory_segment",
            "assignee": "annotator-a",
            "labels": [{"start_frame": 0, "end_frame": 42, "skill_id": "approach"}],
        },
    )

    assert rejected.status_code == 422


def test_model_version_switch_tracks_active_model(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    first = client.post(
        "/api/embodied-platform/models",
        headers=_admin_headers(),
        json={"name": "mobile-policy", "version": "1.0.0", "artifact_uri": "models://policy/1"},
    )
    second = client.post(
        "/api/embodied-platform/models",
        headers=_admin_headers(),
        json={"name": "mobile-policy", "version": "1.1.0", "artifact_uri": "models://policy/2"},
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    switched = client.post(
        f"/api/embodied-platform/models/{second.json()['id']}/activate",
        headers=_admin_headers(),
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["active"] is True

    models = client.get("/api/embodied-platform/models").json()
    assert {model["version"]: model["active"] for model in models} == {
        "1.0.0": False,
        "1.1.0": True,
    }


def test_job_status_rejects_invalid_terminal_transition(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    dataset = _create_dataset(client)

    training_job = client.post(
        "/api/embodied-platform/training-jobs",
        headers=_ml_headers(),
        json={
            "name": "terminal-transition-smoke",
            "dataset_id": dataset["id"],
            "base_model": "rt-2-x",
            "optimizer": "lora",
        },
    )
    assert training_job.status_code == 200, training_job.text
    training_id = training_job.json()["id"]
    assert client.patch(
        f"/api/embodied-platform/training-jobs/{training_id}/status",
        headers=_ml_headers(),
        json={"status": "running", "message": "worker claimed job"},
    ).status_code == 200
    assert client.patch(
        f"/api/embodied-platform/training-jobs/{training_id}/status",
        headers=_ml_headers(),
        json={"status": "succeeded", "message": "metrics archived"},
    ).status_code == 200

    invalid = client.patch(
        f"/api/embodied-platform/training-jobs/{training_id}/status",
        headers=_ml_headers(),
        json={"status": "running", "message": "should not restart terminal job"},
    )

    assert invalid.status_code == 409


def test_rejects_orphan_references_for_pipeline_resources(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    assert client.post(
        "/api/embodied-platform/training-jobs",
        headers=_ml_headers(),
        json={
            "name": "orphan-training",
            "dataset_id": "missing-dataset",
            "base_model": "rt-2-x",
            "optimizer": "lora",
        },
    ).status_code == 422

    assert client.post(
        "/api/embodied-platform/simulation-jobs",
        headers=_ml_headers(),
        json={
            "scenario": "orphan-sim",
            "model_id": "missing-model",
            "simulator": "isaac",
        },
    ).status_code == 422

    assert client.post(
        "/api/embodied-platform/deployments",
        headers=_deployment_headers(),
        json={
            "model_id": "missing-model",
            "target": "jetson-orin",
            "environment": "warehouse-a",
        },
    ).status_code == 422

    assert client.post(
        "/api/embodied-platform/learning-queue",
        headers=_annotator_headers(),
        json={
            "episode_id": "missing-episode",
            "reason": "hard-negative candidate",
            "priority": "normal",
        },
    ).status_code == 422


def test_deployment_operator_can_update_deployment_status_and_audit_is_written(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    model = _create_model(client)

    created = client.post(
        "/api/embodied-platform/deployments",
        headers=_deployment_headers(),
        json={
            "model_id": model["id"],
            "target": "jetson-orin",
            "environment": "warehouse-a",
        },
    )
    assert created.status_code == 200, created.text
    deployment_id = created.json()["id"]

    updated = client.patch(
        f"/api/embodied-platform/deployments/{deployment_id}/status",
        headers=_deployment_headers(),
        json={"status": "running", "message": "canary deployment started"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "running"

    audit_events = client.get("/api/embodied-platform/audit-events").json()
    assert any(event["action"] == "deployment.status" for event in audit_events)


def test_monitoring_counts_deployments_as_jobs_until_terminal(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    model = _create_model(client)

    created = client.post(
        "/api/embodied-platform/deployments",
        headers=_deployment_headers(),
        json={
            "model_id": model["id"],
            "target": "jetson-orin",
            "environment": "warehouse-a",
        },
    )
    assert created.status_code == 200, created.text
    deployment_id = created.json()["id"]

    overview = client.get("/api/embodied-platform/monitoring/overview").json()
    assert overview["queued_jobs"] == 1
    assert overview["active_deployments"] == 1

    assert client.patch(
        f"/api/embodied-platform/deployments/{deployment_id}/status",
        headers=_deployment_headers(),
        json={"status": "running", "message": "canary live"},
    ).status_code == 200
    assert client.patch(
        f"/api/embodied-platform/deployments/{deployment_id}/status",
        headers=_deployment_headers(),
        json={"status": "succeeded", "message": "rollout complete"},
    ).status_code == 200

    after_terminal = client.get("/api/embodied-platform/monitoring/overview").json()
    assert after_terminal["queued_jobs"] == 0
    assert after_terminal["running_jobs"] == 0
    assert after_terminal["active_deployments"] == 0


def test_audit_creation_monitoring_overview_and_rbac_rejection(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    unauthorized = client.post(
        "/api/embodied-platform/deployments",
        headers={"X-Embodied-Role": "viewer", "X-Embodied-Actor": "reader"},
        json={
            "model_id": "model-1",
            "target": "jetson-orin",
            "environment": "warehouse-a",
        },
    )
    assert unauthorized.status_code == 403

    ml_denied = client.patch(
        "/api/embodied-platform/system/settings",
        headers=_ml_headers(),
        json={
            "retention_days": 90,
            "offline_mode": True,
            "active_robot_fleet": "warehouse-fleet-a",
            "approval_required_for_edge": True,
        },
    )
    assert ml_denied.status_code == 403

    audit = client.post(
        "/api/embodied-platform/audit-events",
        headers=_admin_headers(),
        json={"action": "operator.note", "resource": "runbook", "detail": "handoff accepted"},
    )
    assert audit.status_code == 200, audit.text
    assert audit.json()["actor"] == "pytest-admin"

    overview = client.get("/api/embodied-platform/monitoring/overview")
    assert overview.status_code == 200
    body = overview.json()
    assert "dataset_count" in body
    assert "open_learning_items" in body
    assert body["recent_audit_events"] >= 1


def test_session_mints_signature_accepted_by_write_routes(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    session = client.post(
        "/api/embodied-platform/session",
        json={"actor": "ground-control-op", "role": "data_manager", "passcode": LOGIN_PASSCODE},
    )
    assert session.status_code == 200, session.text
    body = session.json()
    assert body["actor"] == "ground-control-op"
    assert body["role"] == "data_manager"
    assert body["signature"]
    assert body["issued_at"]

    # The minted signature is the dev/SSO login boundary: it must unlock the same
    # write routes that the SPA calls, without the test pre-knowing the secret.
    created = client.post(
        "/api/embodied-platform/datasets",
        headers={
            "X-Embodied-Role": body["role"],
            "X-Embodied-Actor": body["actor"],
            "X-Embodied-Signature": body["signature"],
        },
        json={
            "name": "session-minted-v1",
            "modality": "vision_language_action",
            "robot_type": "mobile_manipulator",
            "storage_uri": "file:///datasets/session-minted-v1",
        },
    )
    assert created.status_code == 200, created.text


def test_session_strips_inputs_so_signature_matches_returned_principal(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    # StrictModel strips strings; the signature is over the stripped actor/role.
    # The response echoes the canonical (stripped) principal a client must use.
    session = client.post(
        "/api/embodied-platform/session",
        json={"actor": "  padded-op  ", "role": "data_manager", "passcode": LOGIN_PASSCODE},
    )
    assert session.status_code == 200, session.text
    body = session.json()
    assert body["actor"] == "padded-op"

    from api.embodied_platform.routes import sign_principal

    assert body["signature"] == sign_principal("padded-op", "data_manager")


def test_session_wrong_passcode_is_unauthorized(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/embodied-platform/session",
        json={"actor": "ground-control-op", "role": "data_manager", "passcode": "wrong-passcode"},
    )
    assert response.status_code == 401, response.text


def test_session_non_write_role_is_forbidden(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    # Correct passcode isolates the failure to the role check (403, not 401).
    response = client.post(
        "/api/embodied-platform/session",
        json={"actor": "ground-control-op", "role": "viewer", "passcode": LOGIN_PASSCODE},
    )
    assert response.status_code == 403, response.text


def test_session_disabled_when_login_passcode_env_unset(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, configure_passcode=False)

    response = client.post(
        "/api/embodied-platform/session",
        json={"actor": "ground-control-op", "role": "data_manager", "passcode": "anything"},
    )
    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "login disabled"


def test_session_fails_closed_when_auth_secret_env_unset(tmp_path, monkeypatch):
    # Passcode configured + correct, role valid: the only thing missing is the
    # signing secret, so this exercises a different 503 path than login-disabled.
    client = _client(tmp_path, monkeypatch, configure_secret=False)

    response = client.post(
        "/api/embodied-platform/session",
        json={"actor": "ground-control-op", "role": "data_manager", "passcode": LOGIN_PASSCODE},
    )
    assert response.status_code == 503, response.text
    assert response.json()["detail"] != "login disabled"


def test_session_to_dataset_round_trip_persists_and_audits(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    session = client.post(
        "/api/embodied-platform/session",
        json={"actor": "e2e-operator", "role": "data_manager", "passcode": LOGIN_PASSCODE},
    ).json()
    headers = {
        "X-Embodied-Role": session["role"],
        "X-Embodied-Actor": session["actor"],
        "X-Embodied-Signature": session["signature"],
    }

    created = client.post(
        "/api/embodied-platform/datasets",
        headers=headers,
        json={
            "name": "e2e-round-trip-v1",
            "modality": "vision_language_action",
            "robot_type": "mobile_manipulator",
            "storage_uri": "file:///datasets/e2e-round-trip-v1",
        },
    )
    assert created.status_code == 200, created.text
    dataset_id = created.json()["id"]

    listed = client.get("/api/embodied-platform/datasets").json()
    assert [item["name"] for item in listed] == ["e2e-round-trip-v1"]

    audit_events = client.get("/api/embodied-platform/audit-events").json()
    assert any(
        event["action"] == "dataset.create"
        and event["resource"] == dataset_id
        and event["actor"] == "e2e-operator"
        and event["role"] == "data_manager"
        for event in audit_events
    )


def test_json_repository_mutations_preserve_parallel_writes(tmp_path):
    from api.embodied_platform.repository import JsonRepository

    repo = JsonRepository(tmp_path / "state.json")

    def write_event(index: int) -> int:
        def _mutate(state: dict) -> int:
            state["audit_events"].append(
                {
                    "id": f"audit-{index}",
                    "action": "stress.write",
                    "resource": f"resource-{index}",
                    "detail": "parallel writer",
                    "actor": "pytest",
                    "role": "admin",
                    "created_at": "2026-05-30T00:00:00+00:00",
                }
            )
            return index

        return repo.mutate(_mutate)

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sorted(pool.map(write_event, range(40))) == list(range(40))

    assert len(repo.read()["audit_events"]) == 40


def test_json_repository_mutations_preserve_multi_process_writes(tmp_path):
    from api.embodied_platform.repository import JsonRepository

    with ProcessPoolExecutor(max_workers=6) as pool:
        assert sorted(pool.map(_write_dataset_in_process, [str(tmp_path)] * 20, range(20))) == list(range(20))

    state = JsonRepository(tmp_path / "state.json").read()
    assert len(state["datasets"]) == 20
    assert len(state["audit_events"]) == 20
