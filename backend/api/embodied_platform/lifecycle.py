"""Lifecycle and transition policy for embodied platform records."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .schema import now_iso


JOB_TRANSITIONS = {
    "queued": {"running", "failed", "cancelled"},
    "running": {"succeeded", "failed", "cancelled"},
    "failed": {"queued"},
    "cancelled": {"queued"},
    "succeeded": set(),
}

# Collection-run termination table. The non-terminal statuses are DERIVED from
# attempt progress; the only operator-settable statuses are the manual terminals
# 'completed'/'failed', valid from any non-terminal state. Unlike the job machine
# there is no same-status no-op: every terminal state (derived 'passed' included)
# rejects further transitions with 409.
COLLECTION_RUN_TRANSITIONS = {
    "collecting": {"completed", "failed"},
    "ready_for_review": {"completed", "failed"},
    "blocked": {"completed", "failed"},
    "passed": set(),
    "completed": set(),
    "failed": set(),
}

# Manual terminal run statuses. Attempt/review writes recompute the run status
# from progress, which would silently resurrect a terminated run; route writes
# reject those updates while the run carries one of these.
COLLECTION_RUN_MANUAL_TERMINAL = {"completed", "failed"}

# Annotation review machine: open -> review -> accepted | rework -> review.
# 'accepted' is terminal; there is no transition back to 'open' and no
# same-status no-op.
ANNOTATION_TRANSITIONS = {
    "open": {"review"},
    "review": {"accepted", "rework"},
    "rework": {"review"},
    "accepted": set(),
}

# Import formats the ingest pipeline can actually parse. The ImportJobCreate
# schema's `format` Literal advertises more values, but only LeRobot has a real
# parser; any other format would otherwise be silently parsed AS LeRobot.
SUPPORTED_IMPORT_FORMATS = {"lerobot"}


def transition_job(job: dict[str, Any], status: str, message: str | None) -> None:
    current = job.get("status", "queued")
    if current == status:
        job.update(message=message, updated_at=now_iso())
        return
    if status not in JOB_TRANSITIONS.get(current, set()):
        raise HTTPException(status_code=409, detail=f"cannot transition job from {current} to {status}")
    job.update(status=status, message=message, updated_at=now_iso())
