"""Strict Pydantic schemas for the embodied-only platform API."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic import model_validator


JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
AnnotationStatus = Literal["open", "review", "accepted", "rework"]
DeploymentStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
LearningPriority = Literal["low", "normal", "high", "urgent"]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("*", mode="before")
    @classmethod
    def _strip_strings(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value


class DatasetCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    modality: Literal["vision", "language", "action", "vision_language_action", "multimodal"]
    robot_type: str = Field(min_length=1, max_length=80)
    storage_uri: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=500)


class Dataset(DatasetCreate):
    id: str
    episode_count: int = Field(ge=0)
    created_at: str


class EpisodeCreate(StrictModel):
    dataset_id: str = Field(min_length=1)
    episode_id: str = Field(min_length=1, max_length=120)
    robot_cell: str | None = Field(default=None, max_length=120)
    frame_count: int = Field(default=0, ge=0)


class Episode(EpisodeCreate):
    id: str
    created_at: str


class ImportJobCreate(StrictModel):
    source_uri: str = Field(min_length=1, max_length=500)
    dataset_name: str = Field(min_length=1, max_length=120)
    format: Literal["lerobot", "rosbag", "rlds", "jsonl", "parquet"]


class ImportJob(ImportJobCreate):
    id: str
    status: JobStatus = "queued"
    message: str | None = None
    created_at: str
    updated_at: str


class StatusUpdate(StrictModel):
    status: JobStatus
    message: str | None = Field(default=None, max_length=500)


class AnnotationLabel(StrictModel):
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    skill_id: str = Field(min_length=1, max_length=80)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _check_frame_order(self) -> "AnnotationLabel":
        if self.start_frame >= self.end_frame:
            raise ValueError("start_frame must be less than end_frame")
        return self


class AnnotationTaskCreate(StrictModel):
    dataset_id: str = Field(min_length=1)
    episode_id: str = Field(min_length=1)
    task_type: Literal["trajectory_segment", "success_check", "language_grounding", "safety_event"]
    assignee: str = Field(min_length=1, max_length=120)
    labels: list[AnnotationLabel] = Field(default_factory=list)
    status: AnnotationStatus = "open"


class AnnotationTask(AnnotationTaskCreate):
    id: str
    label_count: int = Field(ge=0)
    updated_at: str


class TrainingJobCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    dataset_id: str = Field(min_length=1)
    base_model: str = Field(min_length=1, max_length=120)
    optimizer: Literal["full", "lora", "qlora", "distillation"]


class TrainingJob(TrainingJobCreate):
    id: str
    status: JobStatus = "queued"
    message: str | None = None
    created_at: str
    updated_at: str


class ModelVersionCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=80)
    artifact_uri: str = Field(min_length=1, max_length=500)
    metrics: dict[str, float] = Field(default_factory=dict)


class ModelVersion(ModelVersionCreate):
    id: str
    active: bool = False
    created_at: str


class SimulationJobCreate(StrictModel):
    scenario: str = Field(min_length=1, max_length=120)
    model_id: str = Field(min_length=1)
    simulator: Literal["isaac", "mujoco", "gazebo", "maniskill"]
    sim2real_metric: str | None = Field(default=None, max_length=120)


class SimulationJob(SimulationJobCreate):
    id: str
    status: JobStatus = "queued"
    message: str | None = None
    created_at: str
    updated_at: str


class DeploymentCreate(StrictModel):
    model_id: str = Field(min_length=1)
    target: str = Field(min_length=1, max_length=120)
    environment: str = Field(min_length=1, max_length=120)


class Deployment(DeploymentCreate):
    id: str
    status: DeploymentStatus = "queued"
    message: str | None = None
    created_at: str
    updated_at: str


class LearningQueueItemCreate(StrictModel):
    episode_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=240)
    priority: LearningPriority = "normal"


class LearningQueueItem(LearningQueueItemCreate):
    id: str
    status: JobStatus = "queued"
    created_at: str
    updated_at: str


class AuditEventCreate(StrictModel):
    action: str = Field(min_length=1, max_length=120)
    resource: str = Field(min_length=1, max_length=120)
    detail: str | None = Field(default=None, max_length=500)


class AuditEvent(AuditEventCreate):
    id: str
    actor: str
    role: str
    created_at: str


class SystemSettings(StrictModel):
    retention_days: int = Field(default=30, ge=1, le=3650)
    offline_mode: bool = True
    active_robot_fleet: str = Field(default="warehouse-fleet-a", min_length=1, max_length=120)
    approval_required_for_edge: bool = True


class SessionRequest(StrictModel):
    actor: str = Field(min_length=1, max_length=120)
    # role is a plain str so an unknown role is rejected by the endpoint with a
    # 403 (write-role check) rather than a 422 schema-validation error.
    role: str = Field(min_length=1, max_length=120)
    passcode: str = Field(min_length=1, max_length=200)


class SessionResponse(StrictModel):
    actor: str
    role: str
    signature: str
    issued_at: str


class MonitoringOverview(StrictModel):
    dataset_count: int
    episode_count: int
    queued_jobs: int
    running_jobs: int
    active_model_id: str | None
    active_deployments: int
    open_learning_items: int
    recent_audit_events: int
    sim_success_rate: float
