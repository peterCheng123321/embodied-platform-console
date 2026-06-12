"""Append-only event ingest compatibility API.

This replaces the retired Postgres-backed `/v1/events` service with the
platform's atomic JSON repository while preserving the client-facing batch
contract: strict payload validation and idempotency by client event_id.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .repository import JsonRepository, get_repository
from .schema import EventIngestResponse, LabelEventBatch, TelemetryEventBatch, now_iso


router = APIRouter(prefix="/v1/events", tags=["event-ingest"])


def _repo():
    # Backend selected by env (XINGJU_EMBODIED_PLATFORM_DSN set -> Postgres,
    # unset -> JSON file); both expose the same read()/mutate() surface.
    return get_repository()


def _stored_event(event: BaseModel) -> dict[str, Any]:
    row = event.model_dump(mode="json")
    payload = row["payload"]
    row["event_type"] = payload["event_type"]
    row["ts_server"] = now_iso()
    return row


def _ingest(
    repo: JsonRepository,
    collection: str,
    events: Iterable[BaseModel],
) -> EventIngestResponse:
    def _mutate(state: dict[str, Any]) -> EventIngestResponse:
        existing_ids = {row["event_id"] for row in state[collection]}
        accepted = 0
        deduplicated = 0
        for event in events:
            event_id = str(event.event_id)
            if event_id in existing_ids:
                deduplicated += 1
                continue
            row = _stored_event(event)
            state[collection].append(row)
            existing_ids.add(event_id)
            accepted += 1
        return EventIngestResponse(accepted=accepted, deduplicated=deduplicated, rejected=[])

    return repo.mutate(_mutate)


@router.post("/label", response_model=EventIngestResponse)
def ingest_label_events(
    batch: LabelEventBatch,
    repo: JsonRepository = Depends(_repo),
) -> EventIngestResponse:
    return _ingest(repo, "label_events", batch.events)


@router.post("/telemetry", response_model=EventIngestResponse)
def ingest_telemetry_events(
    batch: TelemetryEventBatch,
    repo: JsonRepository = Depends(_repo),
) -> EventIngestResponse:
    return _ingest(repo, "telemetry_events", batch.events)
