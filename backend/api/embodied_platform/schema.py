"""Strict Pydantic schemas for the embodied-only platform API."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic import model_validator


JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
AnnotationStatus = Literal["open", "review", "accepted", "rework"]
DeploymentStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
LearningPriority = Literal["low", "normal", "high", "urgent"]
CollectionRunStatus = Literal["not_started", "collecting", "ready_for_review", "passed", "failed", "blocked"]
CollectionAttemptStatus = Literal[
    "draft",
    "recorded",
    "uploaded",
    "ready_for_review",
    "accepted",
    "rejected",
    "rework",
    "deleted",
    "blocked",
]
CollectionTaskMode = Literal["ordinary", "speak_while_doing"]
ReviewDecision = Literal["accept", "reject", "needs_rework"]
CheckResult = Literal["pass", "fail", "not_applicable"]


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


class EventModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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


class IssueCode(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    severity: Literal["info", "warning", "critical"] = "warning"


class CollectionTask(StrictModel):
    task_id: str = Field(min_length=1, max_length=40)
    mode: CollectionTaskMode
    title: str = Field(min_length=1, max_length=160)
    required_uploads: int = Field(ge=1, le=20)
    max_attempts: int = Field(ge=1, le=50)
    environment: dict[str, str | int | bool] = Field(default_factory=dict)
    target_objects: list[str] = Field(default_factory=list)
    speech: list[str] = Field(default_factory=list)
    procedure_steps: list[str] = Field(default_factory=list)
    duration_rules: list[str] = Field(default_factory=list)
    qc_checks: list[str] = Field(default_factory=list)
    task_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_quota_fits_attempts(self) -> "CollectionTask":
        if self.required_uploads > self.max_attempts:
            raise ValueError("required_uploads must be less than or equal to max_attempts")
        return self


class CollectionProfile(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    version: int = Field(ge=1)
    source: str = Field(min_length=1, max_length=240)
    task_count_required: int = Field(ge=1, le=100)
    default_required_uploads: int = Field(ge=1, le=20)
    default_max_attempts: int = Field(ge=1, le=50)
    completion_policy: str = Field(min_length=1, max_length=120)
    tasks: list[CollectionTask]
    issue_codes: list[IssueCode]

    @model_validator(mode="after")
    def _check_task_count(self) -> "CollectionProfile":
        if len(self.tasks) != self.task_count_required:
            raise ValueError("tasks length must equal task_count_required")
        return self


class CollectionRunCreate(StrictModel):
    profile_id: str = Field(min_length=1, max_length=80)
    subject_id: str = Field(min_length=1, max_length=120)
    assignee: str = Field(min_length=1, max_length=120)


class CollectionRun(CollectionRunCreate):
    id: str
    status: CollectionRunStatus = "collecting"
    created_at: str
    updated_at: str


class CollectionAttemptCreate(StrictModel):
    task_id: str = Field(min_length=1, max_length=40)
    attempt_index: int = Field(ge=1, le=50)
    video_uri: str = Field(min_length=1, max_length=500)
    duration_seconds: float | None = Field(default=None, ge=0, le=3600)
    frame_count: int | None = Field(default=None, ge=0, le=1000000)
    status: CollectionAttemptStatus = "uploaded"
    transcript: str | None = Field(default=None, max_length=2000)


class ReviewCheckResult(StrictModel):
    check_id: str = Field(min_length=1, max_length=120)
    result: CheckResult
    note: str = Field(default="", max_length=500)


class AttemptReviewCreate(StrictModel):
    decision: ReviewDecision
    check_results: list[ReviewCheckResult] = Field(default_factory=list)
    issue_codes: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=1000)


class AttemptReview(AttemptReviewCreate):
    reviewer: str
    reviewed_at: str


class CollectionAttempt(CollectionAttemptCreate):
    id: str
    run_id: str
    profile_id: str
    deleted: bool = False
    recorded_at: str
    review: AttemptReview | None = None
    segment_annotation_ref: str | None = Field(default=None, max_length=240)


class CollectionTaskProgress(StrictModel):
    task_id: str
    status: Literal["collecting", "ready_for_review", "passed", "blocked"]
    attempt_count: int
    uploaded_count: int
    accepted_count: int
    remaining_attempts: int
    required_uploads: int
    max_attempts: int


class CollectionRunProgress(StrictModel):
    run_id: str
    profile_id: str
    status: CollectionRunStatus
    completed_task_count: int
    ready_task_count: int
    blocked_task_count: int
    tasks: list[CollectionTaskProgress]


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


class SystemSettingsPatch(StrictModel):
    """Partial update for PATCH /system/settings: every field optional, so only
    provided fields are merged onto the current settings. Each field keeps the
    same constraints as SystemSettings so a bad value is a clean 422 at the
    request boundary (not a 500 from constructing the merged result later).

    The field types are ``... | None`` only so an OMITTED field defaults to None
    and is dropped by ``exclude_unset`` before the merge. An EXPLICIT null on any
    field is rejected at the boundary (422) — these settings are not nullable, so
    merging a None into the required SystemSettings would otherwise raise a
    ValidationError inside the mutator and surface as a 500."""

    retention_days: Annotated[int, Field(ge=1, le=3650)] | None = None
    offline_mode: bool | None = None
    active_robot_fleet: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    approval_required_for_edge: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_null(cls, data):
        if isinstance(data, dict):
            nulled = [key for key, value in data.items() if value is None]
            if nulled:
                raise ValueError(
                    f"system settings field(s) may not be null: {', '.join(sorted(nulled))}"
                )
        return data


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


class BBoxGeometry(EventModel):
    shape: Literal["bbox"] = "bbox"
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    slice_index: int | None = Field(default=None, ge=0)


class PolygonGeometry(EventModel):
    shape: Literal["polygon"] = "polygon"
    vertices: list[tuple[float, float]] = Field(min_length=3)
    slice_index: int | None = Field(default=None, ge=0)

    @field_validator("vertices")
    @classmethod
    def _no_explicit_close(cls, value: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if len(value) >= 4 and value[0] == value[-1]:
            raise ValueError("polygon vertices must not repeat the first point at the end")
        return value


class MaskGeometry(EventModel):
    shape: Literal["mask"] = "mask"
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    rle_counts: str = Field(min_length=1)
    slice_index: int | None = Field(default=None, ge=0)


class KeypointGeometry(EventModel):
    shape: Literal["keypoint"] = "keypoint"
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    visible: bool = True
    slice_index: int | None = Field(default=None, ge=0)


EventGeometry = Annotated[
    Union[BBoxGeometry, PolygonGeometry, MaskGeometry, KeypointGeometry],
    Field(discriminator="shape"),
]


LabelOrigin = Literal["human", "human_edited", "model_accepted", "adjudicator"]


class ObjectCreatedPayload(EventModel):
    event_type: Literal["object.created"] = "object.created"
    client_object_id: UUID
    class_id: UUID
    geometry: EventGeometry
    attributes: dict[str, Any] = Field(default_factory=dict)
    origin: LabelOrigin
    prelabel_model: str | None = Field(default=None, max_length=120)
    prelabel_confidence: float | None = Field(default=None, ge=0, le=1)
    self_confidence: float | None = Field(default=None, ge=0, le=1)
    first_click_xy: tuple[float, float] | None = None
    drawn_with: Literal["mouse", "hotkey", "sam_click", "sam_text", "tracker"] = "mouse"


class ObjectEditedPayload(EventModel):
    event_type: Literal["object.edited"] = "object.edited"
    client_object_id: UUID
    edit_type: Literal["vertex_move", "resize", "translate", "reshape", "mask_paint"]
    new_geometry: EventGeometry
    delta_px: float | None = Field(default=None, ge=0)


class ObjectDeletedPayload(EventModel):
    event_type: Literal["object.deleted"] = "object.deleted"
    client_object_id: UUID
    age_ms: int | None = Field(default=None, ge=0)


class ClassChangedPayload(EventModel):
    event_type: Literal["class.changed"] = "class.changed"
    client_object_id: UUID
    new_class_id: UUID


class AttributeChangedPayload(EventModel):
    event_type: Literal["attribute.changed"] = "attribute.changed"
    client_object_id: UUID
    attributes: dict[str, Any]


class ActionUndoPayload(EventModel):
    event_type: Literal["action.undo"] = "action.undo"
    target_event_id: UUID


class ActionRedoPayload(EventModel):
    event_type: Literal["action.redo"] = "action.redo"
    target_event_id: UUID


class LabelSubmittedPayload(EventModel):
    event_type: Literal["label.submitted"] = "label.submitted"
    duration_ms: int = Field(ge=0)
    active_ms: int = Field(ge=0)
    idle_ms: int = Field(ge=0)
    self_confidence: float | None = Field(default=None, ge=0, le=1)


class LabelUnsubmittedPayload(EventModel):
    event_type: Literal["label.unsubmitted"] = "label.unsubmitted"
    reopened_by: UUID
    reason: str = Field(min_length=1, max_length=1024)


LabelEventPayload = Annotated[
    Union[
        ObjectCreatedPayload,
        ObjectEditedPayload,
        ObjectDeletedPayload,
        ClassChangedPayload,
        AttributeChangedPayload,
        ActionUndoPayload,
        ActionRedoPayload,
        LabelSubmittedPayload,
        LabelUnsubmittedPayload,
    ],
    Field(discriminator="event_type"),
]


class LabelEventIn(EventModel):
    event_id: UUID
    task_id: UUID
    annotator_id: UUID
    payload: LabelEventPayload
    ts_client: datetime
    schema_version: int = Field(default=1, ge=1)


class SessionStartedPayload(EventModel):
    event_type: Literal["session.started"] = "session.started"
    device_class: Literal["desktop", "laptop", "tablet", "mobile"]
    input_device: Literal["mouse", "trackpad", "stylus", "touch"]
    screen_bucket: Literal["sub_1080", "1080_to_1440", "1440_to_4k", "4k_plus"]
    locale: str = Field(min_length=1, max_length=1024)
    rtt_ms: int | None = Field(default=None, ge=0)


class SessionEndedPayload(EventModel):
    event_type: Literal["session.ended"] = "session.ended"
    reason: Literal["submit", "idle", "logout", "crash"]


class TaskOpenedPayload(EventModel):
    event_type: Literal["task.opened"] = "task.opened"
    task_class: str | None = Field(default=None, max_length=1024)
    has_model_prelabel: bool
    prelabel_hash: str | None = Field(default=None, max_length=1024)


class TaskSubmittedPayload(EventModel):
    event_type: Literal["task.submitted"] = "task.submitted"
    duration_ms: int = Field(ge=0)
    active_ms: int = Field(ge=0)
    idle_ms: int = Field(ge=0)
    self_confidence: float | None = Field(default=None, ge=0, le=1)


class TaskAbandonedPayload(EventModel):
    event_type: Literal["task.abandoned"] = "task.abandoned"
    duration_ms: int = Field(ge=0)
    last_state: Literal["nothing_drawn", "partial", "complete_unsubmitted"]


class FocusChangedPayload(EventModel):
    event_type: Literal["focus.changed"] = "focus.changed"
    state: Literal["lost", "gained"]


class ViewportChangedPayload(EventModel):
    event_type: Literal["viewport.changed"] = "viewport.changed"
    zoom: float = Field(gt=0)
    pan_x: float
    pan_y: float
    viewport_rect: tuple[float, float, float, float]


class HoverObservedPayload(EventModel):
    event_type: Literal["hover.observed"] = "hover.observed"
    target: Literal["object", "class_palette", "prelabel"]
    target_id: UUID | None = None
    duration_ms: int = Field(ge=0)


class HotkeyUsedPayload(EventModel):
    event_type: Literal["hotkey.used"] = "hotkey.used"
    key: str = Field(min_length=1, max_length=1024)
    action: str = Field(min_length=1, max_length=1024)


class ReviewOutcomePayload(EventModel):
    event_type: Literal["review.outcome"] = "review.outcome"
    reviewer_id: UUID
    verdict: Literal["accept", "edit", "reject"]
    overturn: bool


class GoldOutcomePayload(EventModel):
    event_type: Literal["gold.outcome"] = "gold.outcome"
    gold_task_id: UUID
    iou: float = Field(ge=0, le=1)
    class_match: bool
    accuracy_score: float = Field(ge=0, le=1)


class ObjectFirstClickPayload(EventModel):
    event_type: Literal["object.first_click"] = "object.first_click"
    client_object_id: UUID
    first_click_xy: tuple[float, float]


class UnsureRaisedPayload(EventModel):
    event_type: Literal["unsure.raised"] = "unsure.raised"
    reason: Literal["ambiguous_class", "blurry_image", "edge_case", "taxonomy_gap", "needs_SME", "other"]
    free_text: str | None = Field(default=None, max_length=1000)


TelemetryEventPayload = Annotated[
    Union[
        SessionStartedPayload,
        SessionEndedPayload,
        TaskOpenedPayload,
        TaskSubmittedPayload,
        TaskAbandonedPayload,
        FocusChangedPayload,
        ViewportChangedPayload,
        HoverObservedPayload,
        HotkeyUsedPayload,
        ReviewOutcomePayload,
        GoldOutcomePayload,
        ObjectFirstClickPayload,
        UnsureRaisedPayload,
    ],
    Field(discriminator="event_type"),
]


class TelemetryEventIn(EventModel):
    event_id: UUID
    session_id: UUID
    annotator_id: UUID
    project_id: UUID | None = None
    task_id: UUID | None = None
    payload: TelemetryEventPayload
    ts_client: datetime
    schema_version: int = Field(default=1, ge=1)


class LabelEventBatch(EventModel):
    events: list[LabelEventIn] = Field(min_length=1, max_length=500)


class TelemetryEventBatch(EventModel):
    events: list[TelemetryEventIn] = Field(min_length=1, max_length=1000)


class EventIngestResponse(EventModel):
    accepted: int
    deduplicated: int
    rejected: list[dict[str, Any]] = Field(default_factory=list)


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
