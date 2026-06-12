"""Compatibility tests for the retired Postgres event ingest surface."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_DATA_ROOT", str(tmp_path))
    from api.main import app

    return TestClient(app)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_label_event_ingest_is_idempotent_and_append_only(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    event_id = str(uuid4())
    task_id = str(uuid4())
    annotator_id = str(uuid4())
    client_object_id = str(uuid4())
    class_id = str(uuid4())

    created_event = {
        "event_id": event_id,
        "task_id": task_id,
        "annotator_id": annotator_id,
        "ts_client": _now(),
        "payload": {
            "event_type": "object.created",
            "client_object_id": client_object_id,
            "class_id": class_id,
            "geometry": {"shape": "bbox", "x": 10, "y": 20, "width": 100, "height": 80},
            "origin": "human",
            "drawn_with": "mouse",
        },
    }
    replacement_attempt = {
        **created_event,
        "payload": {
            "event_type": "label.submitted",
            "duration_ms": 1200,
            "active_ms": 900,
            "idle_ms": 300,
        },
    }

    first = client.post("/v1/events/label", json={"events": [created_event]})
    assert first.status_code == 200, first.text
    assert first.json() == {"accepted": 1, "deduplicated": 0, "rejected": []}

    duplicate = client.post("/v1/events/label", json={"events": [replacement_attempt]})
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json() == {"accepted": 0, "deduplicated": 1, "rejected": []}

    from api.embodied_platform.repository import get_repository

    state = get_repository().read()
    assert len(state["label_events"]) == 1
    stored = state["label_events"][0]
    assert stored["event_id"] == event_id
    assert stored["event_type"] == "object.created"
    assert stored["payload"]["event_type"] == "object.created"
    assert stored["payload"]["geometry"]["shape"] == "bbox"
    assert stored["ts_server"]


def test_telemetry_event_ingest_accepts_mixed_batches_and_deduplicates(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    session_id = str(uuid4())
    annotator_id = str(uuid4())
    task_id = str(uuid4())
    first_event_id = str(uuid4())
    second_event_id = str(uuid4())
    third_event_id = str(uuid4())

    first_batch = {
        "events": [
            {
                "event_id": first_event_id,
                "session_id": session_id,
                "annotator_id": annotator_id,
                "ts_client": _now(),
                "payload": {
                    "event_type": "session.started",
                    "device_class": "desktop",
                    "input_device": "mouse",
                    "screen_bucket": "1440_to_4k",
                    "locale": "zh-CN",
                },
            },
            {
                "event_id": second_event_id,
                "session_id": session_id,
                "annotator_id": annotator_id,
                "task_id": task_id,
                "ts_client": _now(),
                "payload": {
                    "event_type": "task.opened",
                    "has_model_prelabel": False,
                },
            },
        ]
    }
    second_batch = {
        "events": [
            first_batch["events"][1],
            {
                "event_id": third_event_id,
                "session_id": session_id,
                "annotator_id": annotator_id,
                "ts_client": _now(),
                "payload": {
                    "event_type": "hotkey.used",
                    "key": "1",
                    "action": "class_select",
                },
            },
        ]
    }

    first = client.post("/v1/events/telemetry", json=first_batch)
    assert first.status_code == 200, first.text
    assert first.json() == {"accepted": 2, "deduplicated": 0, "rejected": []}

    second = client.post("/v1/events/telemetry", json=second_batch)
    assert second.status_code == 200, second.text
    assert second.json() == {"accepted": 1, "deduplicated": 1, "rejected": []}

    from api.embodied_platform.repository import get_repository

    state = get_repository().read()
    assert [event["event_type"] for event in state["telemetry_events"]] == [
        "session.started",
        "task.opened",
        "hotkey.used",
    ]


def test_event_ingest_rejects_unknown_discriminators(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    bad = {
        "events": [
            {
                "event_id": str(uuid4()),
                "task_id": str(uuid4()),
                "annotator_id": str(uuid4()),
                "ts_client": _now(),
                "payload": {"event_type": "not.real"},
            }
        ]
    }

    response = client.post("/v1/events/label", json=bad)
    assert response.status_code == 422, response.text


def test_event_payload_with_nul_byte_is_422_not_500(tmp_path, monkeypatch):
    """U+0000 cannot exist in PostgreSQL jsonb (the PG backend would 500 inside
    psycopg) and the retired Postgres ingest rejected it too — the EventModel
    boundary must turn it into the same clean 422 on every backend, with
    nothing persisted."""
    client = _client(tmp_path, monkeypatch)
    from api.embodied_platform.repository import get_repository

    event = {
        "event_id": str(uuid4()),
        "session_id": str(uuid4()),
        "annotator_id": str(uuid4()),
        "ts_client": _now(),
        "payload": {
            "event_type": "hotkey.used",
            "key": "s\x00",
            "action": "mark_start",
        },
    }
    response = client.post("/v1/events/telemetry", json={"events": [event]})
    assert response.status_code == 422, response.text
    assert "NUL" in response.text
    assert get_repository().read()["telemetry_events"] == []
