"""FastAPI routes for the embodied-only platform MVP."""
from __future__ import annotations

from collections.abc import Callable
import hmac
import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException

from .repository import JsonRepository
from .schema import (
    AnnotationTask,
    AnnotationTaskCreate,
    AttemptReview,
    AttemptReviewCreate,
    AuditEvent,
    AuditEventCreate,
    CollectionAttempt,
    CollectionAttemptCreate,
    CollectionProfile,
    CollectionRun,
    CollectionRunCreate,
    CollectionRunProgress,
    CollectionTaskProgress,
    Dataset,
    DatasetCreate,
    Deployment,
    DeploymentCreate,
    Episode,
    EpisodeCreate,
    ImportJob,
    ImportJobCreate,
    LearningQueueItem,
    LearningQueueItemCreate,
    ModelVersion,
    ModelVersionCreate,
    MonitoringOverview,
    SessionRequest,
    SessionResponse,
    SimulationJob,
    SimulationJobCreate,
    StatusUpdate,
    SystemSettings,
    TrainingJob,
    TrainingJobCreate,
    new_id,
    now_iso,
)


router = APIRouter(prefix="/api/embodied-platform", tags=["embodied-platform"])

WRITE_ROLES = {
    "admin",
    "data_manager",
    "annotator",
    "reviewer",
    "ml_engineer",
    "deployment_operator",
    # Compatibility with the initial scaffold; production UI uses the specific roles above.
    "operator",
}

JOB_TRANSITIONS = {
    "queued": {"running", "failed", "cancelled"},
    "running": {"succeeded", "failed", "cancelled"},
    "failed": {"queued"},
    "cancelled": {"queued"},
    "succeeded": set(),
}


def _repo() -> JsonRepository:
    return JsonRepository()


def require_write_actor(
    x_embodied_role: str = Header(default="viewer"),
    x_embodied_actor: str = Header(default="anonymous"),
    x_embodied_signature: str = Header(default="", alias="X-Embodied-Signature"),
) -> dict[str, str]:
    if x_embodied_role not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="write access requires an embodied platform write role")
    _verify_principal_signature(x_embodied_actor, x_embodied_role, x_embodied_signature)
    return {"role": x_embodied_role, "actor": x_embodied_actor}


def require_roles(*allowed_roles: str) -> Callable[[str, str], dict[str, str]]:
    allowed = set(allowed_roles)

    def _dependency(
        x_embodied_role: str = Header(default="viewer"),
        x_embodied_actor: str = Header(default="anonymous"),
        x_embodied_signature: str = Header(default="", alias="X-Embodied-Signature"),
    ) -> dict[str, str]:
        if x_embodied_role not in allowed:
            raise HTTPException(status_code=403, detail=f"requires one of: {', '.join(sorted(allowed))}")
        _verify_principal_signature(x_embodied_actor, x_embodied_role, x_embodied_signature)
        return {"role": x_embodied_role, "actor": x_embodied_actor}

    return _dependency


data_actor = require_roles("admin", "data_manager", "operator")
annotation_actor = require_roles("admin", "annotator", "reviewer", "operator")
ml_actor = require_roles("admin", "ml_engineer", "operator")
deployment_actor = require_roles("admin", "deployment_operator", "operator")
system_actor = require_roles("admin")


def _auth_secret() -> str:
    secret = os.environ.get("XINGJU_EMBODIED_PLATFORM_AUTH_SECRET")
    if not secret:
        raise RuntimeError("XINGJU_EMBODIED_PLATFORM_AUTH_SECRET is required for embodied write auth")
    return secret


def sign_principal(actor: str, role: str) -> str:
    return hmac.digest(_auth_secret().encode(), f"{actor}:{role}".encode(), "sha256").hex()


def _verify_principal_signature(actor: str, role: str, signature: str) -> None:
    try:
        expected = sign_principal(actor, role)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not signature or not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=403, detail="invalid embodied platform principal signature")


@router.post("/session", response_model=SessionResponse)
def create_session(req: SessionRequest) -> SessionResponse:
    """Mint a principal HMAC signature so the SPA can perform live writes.

    This is the documented dev/internal login boundary — front it with SSO in
    production. Checks run in authenticate-before-authorize order so an
    unauthenticated caller cannot enumerate which roles are writable:
      1. login passcode env unset -> 503 (server not configured for login)
      2. passcode mismatch         -> 401
      3. role not a write role     -> 403
      4. auth secret unset         -> 503 (raised by sign_principal)
    """
    login_passcode = os.environ.get("XINGJU_EMBODIED_PLATFORM_LOGIN_PASSCODE")
    if not login_passcode:
        raise HTTPException(status_code=503, detail="login disabled")
    if not hmac.compare_digest(req.passcode, login_passcode):
        raise HTTPException(status_code=401, detail="invalid passcode")
    if req.role not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="role is not an embodied platform write role")
    try:
        signature = sign_principal(req.actor, req.role)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return SessionResponse(actor=req.actor, role=req.role, signature=signature, issued_at=now_iso())


def _append_audit(
    state: dict[str, Any],
    *,
    action: str,
    resource: str,
    detail: str | None,
    actor: dict[str, str],
) -> AuditEvent:
    event = AuditEvent(
        id=new_id("audit"),
        action=action,
        resource=resource,
        detail=detail,
        actor=actor["actor"],
        role=actor["role"],
        created_at=now_iso(),
    )
    state["audit_events"].append(event.model_dump(mode="json"))
    return event


def _collection(repo: JsonRepository, name: str) -> list[dict[str, Any]]:
    return repo.read()[name]


def _first_person_profile() -> CollectionProfile:
    common_checks = [
        "speech.required_phrase",
        "scene.clutter",
        "scene.lighting",
        "view.first_person",
        "device.gripper_visibility",
        "device.marker_visibility",
        "audio.background_noise",
    ]
    tasks = [
        ("task_01", "ordinary", "笔帽拔下后插到笔杆尾端"),
        ("task_02", "ordinary", "杯盖盖紧后杯子倒放"),
        ("task_03", "ordinary", "塑料袋撑开后放入空瓶并收拢袋口"),
        ("task_04", "ordinary", "多个物体按颜色排序"),
        ("task_05", "ordinary", "左右手按顺序抽纸巾擦桌子"),
        ("task_06", "ordinary", "拧瓶盖"),
        ("task_07", "speak_while_doing", "抽出碗底一次性筷子并拢摆齐"),
        ("task_08", "speak_while_doing", "毛巾卷成一卷后放进抽屉右侧"),
    ]
    issue_codes = [
        ("missing_required_speech", "必需口述缺失或不清晰", "critical"),
        ("speech_while_motion", "常规模式口述与动作重叠", "warning"),
        ("task_description_mismatch", "任务描述与结果不一致", "critical"),
        ("unclear_target_object", "目标物体指代不清", "warning"),
        ("scene_clutter_insufficient", "杂乱物数量或分布不足", "warning"),
        ("scene_clutter_invalid_plane", "杂乱物平面或堆叠不合规", "warning"),
        ("lighting_too_dark", "环境过暗", "warning"),
        ("other_people_or_devices_visible", "出现其他人员或采集设备", "critical"),
        ("gripper_out_of_frame", "夹爪出画或触碰画面边缘", "critical"),
        ("marker_or_block_missing", "定位块或固定码可见性不足", "critical"),
        ("motion_too_fast", "动作过快", "warning"),
        ("background_noise", "背景音干扰", "warning"),
        ("device_disconnect", "设备断连或重启", "critical"),
        ("abnormal_recovery_missing", "异常情况未按规则口述恢复", "warning"),
        ("task_specific_setup_failure", "任务特定准备不合规", "warning"),
        ("attempt_limit_exhausted", "录制次数已用尽", "critical"),
        ("upload_quota_incomplete", "上传数量不足", "critical"),
    ]
    return CollectionProfile(
        id="first_person_trial_v1",
        name="第一人称试采流程",
        version=1,
        source="Feishu workflow inspected 2026-06-08",
        task_count_required=8,
        default_required_uploads=6,
        default_max_attempts=8,
        completion_policy="uploaded_count_per_task",
        tasks=[
            {
                "task_id": task_id,
                "mode": mode,
                "title": title,
                "required_uploads": 6,
                "max_attempts": 8,
                "environment": {"clutter_min": 6 if task_id != "task_04" else 0, "first_person_view": True},
                "target_objects": [],
                "speech": ["操作开始", "操作结束，任务成功"] if mode == "ordinary" else ["任务名称", "作业流程"],
                "procedure_steps": [],
                "duration_rules": [],
                "qc_checks": common_checks,
                "task_notes": [],
            }
            for task_id, mode, title in tasks
        ],
        issue_codes=[
            {"id": code, "label": label, "severity": severity}
            for code, label, severity in issue_codes
        ],
    )


def _profiles(state: dict[str, Any]) -> list[dict[str, Any]]:
    existing = state.get("collection_profiles") or []
    if existing:
        return existing
    return [_first_person_profile().model_dump(mode="json")]


def _profile_by_id(state: dict[str, Any], profile_id: str) -> CollectionProfile:
    for profile in _profiles(state):
        if profile["id"] == profile_id:
            return CollectionProfile.model_validate(profile)
    raise HTTPException(status_code=404, detail=f"collection profile not found: {profile_id}")


def _attempts_for_run(state: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    return [attempt for attempt in state["collection_attempts"] if attempt["run_id"] == run_id]


def _uploaded_status(status: str) -> bool:
    return status in {"uploaded", "ready_for_review", "accepted", "rejected", "rework"}


def _progress_for_run(state: dict[str, Any], run: dict[str, Any]) -> CollectionRunProgress:
    profile = _profile_by_id(state, run["profile_id"])
    attempts = _attempts_for_run(state, run["id"])
    task_progress: list[CollectionTaskProgress] = []
    for task in profile.tasks:
        task_attempts = [attempt for attempt in attempts if attempt["task_id"] == task.task_id]
        attempt_count = len(task_attempts)
        uploaded_count = sum(1 for attempt in task_attempts if _uploaded_status(attempt["status"]))
        accepted_count = sum(1 for attempt in task_attempts if attempt["status"] == "accepted")
        remaining_attempts = max(0, task.max_attempts - attempt_count)
        if accepted_count >= task.required_uploads:
            task_status = "passed"
        elif uploaded_count >= task.required_uploads:
            task_status = "ready_for_review"
        elif remaining_attempts == 0:
            task_status = "blocked"
        else:
            task_status = "collecting"
        task_progress.append(CollectionTaskProgress(
            task_id=task.task_id,
            status=task_status,
            attempt_count=attempt_count,
            uploaded_count=uploaded_count,
            accepted_count=accepted_count,
            remaining_attempts=remaining_attempts,
            required_uploads=task.required_uploads,
            max_attempts=task.max_attempts,
        ))
    blocked_task_count = sum(1 for task in task_progress if task.status == "blocked")
    ready_task_count = sum(1 for task in task_progress if task.status in {"ready_for_review", "passed"})
    completed_task_count = sum(1 for task in task_progress if task.status == "passed")
    if blocked_task_count:
        status = "blocked"
    elif completed_task_count == profile.task_count_required:
        status = "passed"
    elif ready_task_count == profile.task_count_required:
        status = "ready_for_review"
    else:
        status = "collecting"
    return CollectionRunProgress(
        run_id=run["id"],
        profile_id=profile.id,
        status=status,
        completed_task_count=completed_task_count,
        ready_task_count=ready_task_count,
        blocked_task_count=blocked_task_count,
        tasks=task_progress,
    )


def _find(state: dict[str, Any], collection: str, item_id: str) -> dict[str, Any]:
    for item in state[collection]:
        if item["id"] == item_id:
            return item
    raise HTTPException(status_code=404, detail=f"{collection} item not found")


def _matches(item: dict[str, Any], identifier: str, fields: tuple[str, ...]) -> bool:
    return any(str(item.get(field, "")) == identifier for field in fields)


def _resolve_reference(state: dict[str, Any], collection: str, identifier: str, fields: tuple[str, ...]) -> dict[str, Any]:
    for item in state[collection]:
        if _matches(item, identifier, fields):
            return item
    raise HTTPException(status_code=422, detail=f"{collection} reference not found: {identifier}")


def _require_reference(state: dict[str, Any], collection: str, identifier: str, fields: tuple[str, ...]) -> None:
    _resolve_reference(state, collection, identifier, fields)


def _require_episode_in_dataset(state: dict[str, Any], dataset_id: str, episode_id: str) -> None:
    dataset = _resolve_reference(state, "datasets", dataset_id, ("id", "name"))
    episode = _resolve_reference(state, "episodes", episode_id, ("id", "episode_id"))
    allowed_dataset_refs = {dataset["id"], dataset["name"], dataset_id}
    if episode["dataset_id"] not in allowed_dataset_refs:
        raise HTTPException(status_code=422, detail=f"episode {episode_id} is not part of dataset {dataset_id}")


def _transition_job(job: dict[str, Any], status: str, message: str | None) -> None:
    current = job.get("status", "queued")
    if current == status:
        job.update(message=message, updated_at=now_iso())
        return
    if status not in JOB_TRANSITIONS.get(current, set()):
        raise HTTPException(status_code=409, detail=f"cannot transition job from {current} to {status}")
    job.update(status=status, message=message, updated_at=now_iso())


@router.get("/datasets", response_model=list[Dataset])
def list_datasets(repo: JsonRepository = Depends(_repo)) -> list[dict[str, Any]]:
    return _collection(repo, "datasets")


@router.post("/datasets", response_model=Dataset)
def create_dataset(
    req: DatasetCreate,
    actor: dict[str, str] = Depends(data_actor),
    repo: JsonRepository = Depends(_repo),
) -> Dataset:
    def _mutate(state: dict[str, Any]) -> Dataset:
        for existing in state["datasets"]:
            if existing["name"] == req.name:
                raise HTTPException(status_code=409, detail=f"dataset already exists: {req.name}")
            if existing["storage_uri"] == req.storage_uri:
                raise HTTPException(status_code=409, detail=f"dataset storage already exists: {req.storage_uri}")
        dataset = Dataset(id=new_id("ds"), episode_count=0, created_at=now_iso(), **req.model_dump(mode="json"))
        state["datasets"].append(dataset.model_dump(mode="json"))
        _append_audit(state, action="dataset.create", resource=dataset.id, detail=dataset.name, actor=actor)
        return dataset

    return repo.mutate(_mutate)


@router.get("/episodes", response_model=list[Episode])
def list_episodes(repo: JsonRepository = Depends(_repo)) -> list[dict[str, Any]]:
    return _collection(repo, "episodes")


@router.post("/episodes", response_model=Episode)
def create_episode(
    req: EpisodeCreate,
    actor: dict[str, str] = Depends(data_actor),
    repo: JsonRepository = Depends(_repo),
) -> Episode:
    def _mutate(state: dict[str, Any]) -> Episode:
        _require_reference(state, "datasets", req.dataset_id, ("id", "name"))
        if any(_matches(episode, req.episode_id, ("episode_id",)) for episode in state["episodes"]):
            raise HTTPException(status_code=409, detail=f"episode already exists: {req.episode_id}")
        episode = Episode(id=new_id("ep"), created_at=now_iso(), **req.model_dump(mode="json"))
        state["episodes"].append(episode.model_dump(mode="json"))
        for dataset in state["datasets"]:
            if dataset["id"] == req.dataset_id or dataset["name"] == req.dataset_id:
                dataset["episode_count"] = int(dataset.get("episode_count", 0)) + 1
        _append_audit(state, action="episode.create", resource=episode.id, detail=episode.episode_id, actor=actor)
        return episode

    return repo.mutate(_mutate)


@router.get("/imports", response_model=list[ImportJob])
def list_imports(repo: JsonRepository = Depends(_repo)) -> list[dict[str, Any]]:
    return _collection(repo, "imports")


@router.post("/imports", response_model=ImportJob)
def create_import(
    req: ImportJobCreate,
    actor: dict[str, str] = Depends(data_actor),
    repo: JsonRepository = Depends(_repo),
) -> ImportJob:
    def _mutate(state: dict[str, Any]) -> ImportJob:
        ts = now_iso()
        job = ImportJob(id=new_id("imp"), created_at=ts, updated_at=ts, **req.model_dump(mode="json"))
        state["imports"].append(job.model_dump(mode="json"))
        _append_audit(state, action="import.create", resource=job.id, detail=req.source_uri, actor=actor)
        return job

    return repo.mutate(_mutate)


@router.patch("/imports/{job_id}/status", response_model=ImportJob)
def update_import_status(
    job_id: str,
    req: StatusUpdate,
    actor: dict[str, str] = Depends(data_actor),
    repo: JsonRepository = Depends(_repo),
) -> ImportJob:
    def _mutate(state: dict[str, Any]) -> ImportJob:
        job = _find(state, "imports", job_id)
        _transition_job(job, req.status, req.message)
        _append_audit(state, action="import.status", resource=job_id, detail=req.status, actor=actor)
        return ImportJob.model_validate(job)

    return repo.mutate(_mutate)


@router.get("/annotation-tasks", response_model=list[AnnotationTask])
def list_annotation_tasks(repo: JsonRepository = Depends(_repo)) -> list[dict[str, Any]]:
    return _collection(repo, "annotation_tasks")


@router.post("/annotation-tasks", response_model=AnnotationTask)
def save_annotation_task(
    req: AnnotationTaskCreate,
    actor: dict[str, str] = Depends(annotation_actor),
    repo: JsonRepository = Depends(_repo),
) -> AnnotationTask:
    def _mutate(state: dict[str, Any]) -> AnnotationTask:
        _require_episode_in_dataset(state, req.dataset_id, req.episode_id)
        task = AnnotationTask(
            id=new_id("ann"),
            label_count=len(req.labels),
            updated_at=now_iso(),
            **req.model_dump(mode="json"),
        )
        state["annotation_tasks"].append(task.model_dump(mode="json"))
        _append_audit(state, action="annotation.save", resource=task.id, detail=req.episode_id, actor=actor)
        return task

    return repo.mutate(_mutate)


@router.get("/collection-profiles", response_model=list[CollectionProfile])
def list_collection_profiles(repo: JsonRepository = Depends(_repo)) -> list[dict[str, Any]]:
    return _profiles(repo.read())


@router.get("/collection-profiles/{profile_id}", response_model=CollectionProfile)
def get_collection_profile(profile_id: str, repo: JsonRepository = Depends(_repo)) -> CollectionProfile:
    return _profile_by_id(repo.read(), profile_id)


@router.get("/collection-runs", response_model=list[CollectionRun])
def list_collection_runs(repo: JsonRepository = Depends(_repo)) -> list[dict[str, Any]]:
    return _collection(repo, "collection_runs")


@router.get("/collection-attempts", response_model=list[CollectionAttempt])
def list_collection_attempts(repo: JsonRepository = Depends(_repo)) -> list[dict[str, Any]]:
    return _collection(repo, "collection_attempts")


@router.post("/collection-runs", response_model=CollectionRun)
def create_collection_run(
    req: CollectionRunCreate,
    actor: dict[str, str] = Depends(annotation_actor),
    repo: JsonRepository = Depends(_repo),
) -> CollectionRun:
    def _mutate(state: dict[str, Any]) -> CollectionRun:
        _profile_by_id(state, req.profile_id)
        run = CollectionRun(
            id=new_id("crun"),
            status="collecting",
            created_at=now_iso(),
            updated_at=now_iso(),
            **req.model_dump(mode="json"),
        )
        state["collection_runs"].append(run.model_dump(mode="json"))
        _append_audit(state, action="collection.run.create", resource=run.id, detail=run.subject_id, actor=actor)
        return run

    return repo.mutate(_mutate)


@router.post("/collection-runs/{run_id}/attempts", response_model=CollectionAttempt)
def create_collection_attempt(
    run_id: str,
    req: CollectionAttemptCreate,
    actor: dict[str, str] = Depends(annotation_actor),
    repo: JsonRepository = Depends(_repo),
) -> CollectionAttempt:
    def _mutate(state: dict[str, Any]) -> CollectionAttempt:
        run = _find(state, "collection_runs", run_id)
        profile = _profile_by_id(state, run["profile_id"])
        task = next((task for task in profile.tasks if task.task_id == req.task_id), None)
        if not task:
            raise HTTPException(status_code=422, detail=f"unknown collection task: {req.task_id}")
        if req.attempt_index > task.max_attempts:
            raise HTTPException(status_code=422, detail=f"attempt_index exceeds max attempts for {req.task_id}")
        existing = [
            attempt for attempt in state["collection_attempts"]
            if attempt["run_id"] == run_id and attempt["task_id"] == req.task_id and attempt["attempt_index"] == req.attempt_index
        ]
        if existing:
            raise HTTPException(status_code=409, detail="collection attempt already exists")
        attempt = CollectionAttempt(
            id=new_id("cat"),
            run_id=run_id,
            profile_id=profile.id,
            deleted=req.status == "deleted",
            recorded_at=now_iso(),
            **req.model_dump(mode="json"),
        )
        state["collection_attempts"].append(attempt.model_dump(mode="json"))
        progress = _progress_for_run(state, run)
        run.update(status=progress.status, updated_at=now_iso())
        _append_audit(state, action="collection.attempt.create", resource=attempt.id, detail=req.task_id, actor=actor)
        return attempt

    return repo.mutate(_mutate)


@router.patch("/collection-attempts/{attempt_id}/review", response_model=CollectionAttempt)
def review_collection_attempt(
    attempt_id: str,
    req: AttemptReviewCreate,
    actor: dict[str, str] = Depends(annotation_actor),
    repo: JsonRepository = Depends(_repo),
) -> CollectionAttempt:
    def _mutate(state: dict[str, Any]) -> CollectionAttempt:
        attempt = _find(state, "collection_attempts", attempt_id)
        profile = _profile_by_id(state, attempt["profile_id"])
        allowed_issue_codes = {issue.id for issue in profile.issue_codes}
        bad_codes = [code for code in req.issue_codes if code not in allowed_issue_codes]
        if bad_codes:
            raise HTTPException(status_code=422, detail=f"unknown issue codes: {', '.join(bad_codes)}")
        review = AttemptReview(
            reviewer=actor["actor"],
            reviewed_at=now_iso(),
            **req.model_dump(mode="json"),
        )
        attempt["review"] = review.model_dump(mode="json")
        if req.decision == "accept":
            attempt["status"] = "accepted"
        elif req.decision == "reject":
            attempt["status"] = "rejected"
        else:
            attempt["status"] = "rework"
        run = _find(state, "collection_runs", attempt["run_id"])
        progress = _progress_for_run(state, run)
        run.update(status=progress.status, updated_at=now_iso())
        _append_audit(state, action="collection.review", resource=attempt_id, detail=req.decision, actor=actor)
        return CollectionAttempt.model_validate(attempt)

    return repo.mutate(_mutate)


@router.get("/collection-runs/{run_id}/progress", response_model=CollectionRunProgress)
def get_collection_run_progress(run_id: str, repo: JsonRepository = Depends(_repo)) -> CollectionRunProgress:
    state = repo.read()
    run = _find(state, "collection_runs", run_id)
    return _progress_for_run(state, run)


@router.get("/training-jobs", response_model=list[TrainingJob])
def list_training_jobs(repo: JsonRepository = Depends(_repo)) -> list[dict[str, Any]]:
    return _collection(repo, "training_jobs")


@router.post("/training-jobs", response_model=TrainingJob)
def create_training_job(
    req: TrainingJobCreate,
    actor: dict[str, str] = Depends(ml_actor),
    repo: JsonRepository = Depends(_repo),
) -> TrainingJob:
    def _mutate(state: dict[str, Any]) -> TrainingJob:
        _require_reference(state, "datasets", req.dataset_id, ("id", "name"))
        ts = now_iso()
        job = TrainingJob(id=new_id("train"), created_at=ts, updated_at=ts, **req.model_dump(mode="json"))
        state["training_jobs"].append(job.model_dump(mode="json"))
        _append_audit(state, action="training.create", resource=job.id, detail=req.name, actor=actor)
        return job

    return repo.mutate(_mutate)


@router.patch("/training-jobs/{job_id}/status", response_model=TrainingJob)
def update_training_status(
    job_id: str,
    req: StatusUpdate,
    actor: dict[str, str] = Depends(ml_actor),
    repo: JsonRepository = Depends(_repo),
) -> TrainingJob:
    def _mutate(state: dict[str, Any]) -> TrainingJob:
        job = _find(state, "training_jobs", job_id)
        _transition_job(job, req.status, req.message)
        _append_audit(state, action="training.status", resource=job_id, detail=req.status, actor=actor)
        return TrainingJob.model_validate(job)

    return repo.mutate(_mutate)


@router.get("/models", response_model=list[ModelVersion])
def list_models(repo: JsonRepository = Depends(_repo)) -> list[dict[str, Any]]:
    return _collection(repo, "models")


@router.post("/models", response_model=ModelVersion)
def create_model(
    req: ModelVersionCreate,
    actor: dict[str, str] = Depends(ml_actor),
    repo: JsonRepository = Depends(_repo),
) -> ModelVersion:
    def _mutate(state: dict[str, Any]) -> ModelVersion:
        model = ModelVersion(id=new_id("model"), created_at=now_iso(), **req.model_dump(mode="json"))
        state["models"].append(model.model_dump(mode="json"))
        _append_audit(
            state,
            action="model.create",
            resource=model.id,
            detail=f"{model.name}:{model.version}",
            actor=actor,
        )
        return model

    return repo.mutate(_mutate)


@router.post("/models/{model_id}/activate", response_model=ModelVersion)
def activate_model(
    model_id: str,
    actor: dict[str, str] = Depends(ml_actor),
    repo: JsonRepository = Depends(_repo),
) -> ModelVersion:
    def _mutate(state: dict[str, Any]) -> ModelVersion:
        selected = _find(state, "models", model_id)
        for model in state["models"]:
            model["active"] = model["id"] == model_id
        _append_audit(state, action="model.activate", resource=model_id, detail=selected["version"], actor=actor)
        return ModelVersion.model_validate(selected)

    return repo.mutate(_mutate)


@router.get("/simulation-jobs", response_model=list[SimulationJob])
def list_simulation_jobs(repo: JsonRepository = Depends(_repo)) -> list[dict[str, Any]]:
    return _collection(repo, "simulation_jobs")


@router.post("/simulation-jobs", response_model=SimulationJob)
def create_simulation_job(
    req: SimulationJobCreate,
    actor: dict[str, str] = Depends(ml_actor),
    repo: JsonRepository = Depends(_repo),
) -> SimulationJob:
    def _mutate(state: dict[str, Any]) -> SimulationJob:
        _require_reference(state, "models", req.model_id, ("id", "name", "version"))
        ts = now_iso()
        job = SimulationJob(id=new_id("sim"), created_at=ts, updated_at=ts, **req.model_dump(mode="json"))
        state["simulation_jobs"].append(job.model_dump(mode="json"))
        _append_audit(state, action="simulation.create", resource=job.id, detail=req.scenario, actor=actor)
        return job

    return repo.mutate(_mutate)


@router.patch("/simulation-jobs/{job_id}/status", response_model=SimulationJob)
def update_simulation_status(
    job_id: str,
    req: StatusUpdate,
    actor: dict[str, str] = Depends(ml_actor),
    repo: JsonRepository = Depends(_repo),
) -> SimulationJob:
    def _mutate(state: dict[str, Any]) -> SimulationJob:
        job = _find(state, "simulation_jobs", job_id)
        _transition_job(job, req.status, req.message)
        _append_audit(state, action="simulation.status", resource=job_id, detail=req.status, actor=actor)
        return SimulationJob.model_validate(job)

    return repo.mutate(_mutate)


@router.get("/deployments", response_model=list[Deployment])
def list_deployments(repo: JsonRepository = Depends(_repo)) -> list[dict[str, Any]]:
    return _collection(repo, "deployments")


@router.post("/deployments", response_model=Deployment)
def create_deployment(
    req: DeploymentCreate,
    actor: dict[str, str] = Depends(deployment_actor),
    repo: JsonRepository = Depends(_repo),
) -> Deployment:
    def _mutate(state: dict[str, Any]) -> Deployment:
        _require_reference(state, "models", req.model_id, ("id", "name", "version"))
        ts = now_iso()
        deployment = Deployment(id=new_id("dep"), created_at=ts, updated_at=ts, **req.model_dump(mode="json"))
        state["deployments"].append(deployment.model_dump(mode="json"))
        _append_audit(
            state,
            action="deployment.create",
            resource=deployment.id,
            detail=req.target,
            actor=actor,
        )
        return deployment

    return repo.mutate(_mutate)


@router.patch("/deployments/{deployment_id}/status", response_model=Deployment)
def update_deployment_status(
    deployment_id: str,
    req: StatusUpdate,
    actor: dict[str, str] = Depends(deployment_actor),
    repo: JsonRepository = Depends(_repo),
) -> Deployment:
    def _mutate(state: dict[str, Any]) -> Deployment:
        deployment = _find(state, "deployments", deployment_id)
        _transition_job(deployment, req.status, req.message)
        _append_audit(state, action="deployment.status", resource=deployment_id, detail=req.status, actor=actor)
        return Deployment.model_validate(deployment)

    return repo.mutate(_mutate)


@router.get("/learning-queue", response_model=list[LearningQueueItem])
def list_learning_queue(repo: JsonRepository = Depends(_repo)) -> list[dict[str, Any]]:
    return _collection(repo, "learning_queue")


@router.post("/learning-queue", response_model=LearningQueueItem)
def enqueue_learning_item(
    req: LearningQueueItemCreate,
    actor: dict[str, str] = Depends(annotation_actor),
    repo: JsonRepository = Depends(_repo),
) -> LearningQueueItem:
    def _mutate(state: dict[str, Any]) -> LearningQueueItem:
        _require_reference(state, "episodes", req.episode_id, ("id", "episode_id"))
        ts = now_iso()
        item = LearningQueueItem(id=new_id("learn"), created_at=ts, updated_at=ts, **req.model_dump(mode="json"))
        state["learning_queue"].append(item.model_dump(mode="json"))
        _append_audit(state, action="learning.enqueue", resource=item.id, detail=req.reason, actor=actor)
        return item

    return repo.mutate(_mutate)


@router.patch("/learning-queue/{item_id}/status", response_model=LearningQueueItem)
def update_learning_item_status(
    item_id: str,
    req: StatusUpdate,
    actor: dict[str, str] = Depends(ml_actor),
    repo: JsonRepository = Depends(_repo),
) -> LearningQueueItem:
    def _mutate(state: dict[str, Any]) -> LearningQueueItem:
        item = _find(state, "learning_queue", item_id)
        _transition_job(item, req.status, req.message)
        _append_audit(state, action="learning.status", resource=item_id, detail=req.status, actor=actor)
        return LearningQueueItem.model_validate(item)

    return repo.mutate(_mutate)


@router.get("/monitoring/overview", response_model=MonitoringOverview)
def monitoring_overview(repo: JsonRepository = Depends(_repo)) -> MonitoringOverview:
    state = repo.read()
    jobs = (
        state["imports"]
        + state["training_jobs"]
        + state["simulation_jobs"]
        + state["deployments"]
        + state["learning_queue"]
    )
    active_model = next((model["id"] for model in state["models"] if model.get("active")), None)
    sim_jobs = state["simulation_jobs"]
    sim_success = [job for job in sim_jobs if job.get("status") == "succeeded"]
    return MonitoringOverview(
        dataset_count=len(state["datasets"]),
        episode_count=len(state["episodes"]),
        queued_jobs=sum(1 for job in jobs if job.get("status") == "queued"),
        running_jobs=sum(1 for job in jobs if job.get("status") == "running"),
        active_model_id=active_model,
        active_deployments=sum(1 for dep in state["deployments"] if dep.get("status") in {"queued", "running"}),
        open_learning_items=sum(1 for item in state["learning_queue"] if item.get("status") in {"queued", "running"}),
        recent_audit_events=len(state["audit_events"][-20:]),
        sim_success_rate=(len(sim_success) / len(sim_jobs)) if sim_jobs else 0.0,
    )


@router.get("/audit-events", response_model=list[AuditEvent])
def list_audit_events(repo: JsonRepository = Depends(_repo)) -> list[dict[str, Any]]:
    return _collection(repo, "audit_events")


@router.post("/audit-events", response_model=AuditEvent)
def create_audit_event(
    req: AuditEventCreate,
    actor: dict[str, str] = Depends(require_write_actor),
    repo: JsonRepository = Depends(_repo),
) -> AuditEvent:
    def _mutate(state: dict[str, Any]) -> AuditEvent:
        return _append_audit(
            state,
            action=req.action,
            resource=req.resource,
            detail=req.detail,
            actor=actor,
        )

    return repo.mutate(_mutate)


@router.get("/system/settings", response_model=SystemSettings)
def get_system_settings(repo: JsonRepository = Depends(_repo)) -> dict[str, Any]:
    return repo.read()["system_settings"]


@router.patch("/system/settings", response_model=SystemSettings)
def update_system_settings(
    req: SystemSettings,
    actor: dict[str, str] = Depends(system_actor),
    repo: JsonRepository = Depends(_repo),
) -> SystemSettings:
    def _mutate(state: dict[str, Any]) -> SystemSettings:
        state["system_settings"] = req.model_dump(mode="json")
        _append_audit(
            state,
            action="system.settings",
            resource="settings",
            detail="settings updated",
            actor=actor,
        )
        return req

    return repo.mutate(_mutate)
