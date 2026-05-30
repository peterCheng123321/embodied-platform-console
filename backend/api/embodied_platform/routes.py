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
    AuditEvent,
    AuditEventCreate,
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
