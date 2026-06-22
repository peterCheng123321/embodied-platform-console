"""Sub-task time-segment annotation schema (embodied-AI labeler).

Mirrors lerobot.annotations.schema.SubtaskSegment from the LeRobot fork at
/Users/peter/Downloads/project/lerobot-trajectory-qc/src/lerobot/annotations/schema.py.
Kept in sync by hand; the only divergence is the optional `success` field added here
(ATLAS-inspired; see docs/embodied/annotation-ux-research-2026-05-23.md §1.1).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class SubtaskSegment(BaseModel):
    """One atomic sub-task time-segment from one annotator."""

    annotator_id: UUID
    episode_index: int = Field(ge=0)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    skill_id: str = Field(min_length=1, max_length=200)
    instruction_text: str | None = Field(default=None, max_length=2000)
    ts_client: datetime | None = None
    schema_version: int = 1
    success: bool | None = None

    @model_validator(mode="after")
    def _check_frame_order(self) -> "SubtaskSegment":
        # Owns the end>start invariant. Non-negativity is enforced live by
        # Field(ge=0) on start_frame / end_frame above (that check fires
        # *before* this model_validator in mode='after', so a redundant
        # branch here would be unreachable).
        if self.start_frame >= self.end_frame:
            raise ValueError(
                f"start_frame ({self.start_frame}) must be < end_frame ({self.end_frame})"
            )
        return self
