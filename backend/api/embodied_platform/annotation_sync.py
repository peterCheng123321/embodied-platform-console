"""Bridge temporal labeler saves into the platform annotation queue."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from api.embodied.schema import SubtaskSegment

from .repository import get_repository
from .schema import AnnotationLabel, AnnotationTask, AuditEvent, Dataset, Episode, new_id, now_iso


@dataclass(frozen=True)
class AnnotationSyncResult:
    synced: bool
    task_id: str | None = None
    reason: str | None = None


def sync_labeler_segments_to_platform(
    *,
    dataset_id: str | None,
    episode_id: str,
    episode_index: int | None,
    annotator_id: UUID,
    segments: list[SubtaskSegment],
) -> AnnotationSyncResult:
    """Upsert a platform annotation task from a temporal labeler save.

    The temporal JSONL remains the source-of-truth annotation export. This
    projection keeps the operations console, universal queue, QC gate, and audit
    trail aware of labeler progress. Missing platform context is a soft skip:
    annotators must never lose a JSONL save because the control-plane catalog is
    not ready yet.
    """
    if not dataset_id:
        return AnnotationSyncResult(False, reason="dataset context not provided")
    if episode_index is None and not episode_id:
        return AnnotationSyncResult(False, reason="episode context not provided")

    labels = [_segment_to_label(segment) for segment in segments]
    actor = {
        "actor": f"labeler:{annotator_id}",
        "role": "annotator",
    }

    def _mutate(state: dict[str, Any]) -> AnnotationSyncResult:
        resolved = _resolve_labeler_episode(
            state,
            dataset_id=dataset_id,
            labeler_episode_id=episode_id,
            episode_index=episode_index,
        )
        if resolved is None:
            return AnnotationSyncResult(False, reason="platform dataset or episode not found")

        dataset, episode = resolved
        task = _find_existing_task(
            state,
            dataset_id=str(dataset["id"]),
            episode_id=str(episode["episode_id"]),
            assignee=str(annotator_id),
        )
        now = now_iso()
        label_rows = [label.model_dump(mode="json") for label in labels]
        if task is None:
            created = AnnotationTask(
                id=new_id("ann"),
                dataset_id=str(dataset["id"]),
                episode_id=str(episode["episode_id"]),
                task_type="trajectory_segment",
                assignee=str(annotator_id),
                labels=labels,
                label_count=len(labels),
                status="open",
                updated_at=now,
            )
            task = created.model_dump(mode="json")
            state["annotation_tasks"].append(task)
            action = "annotation.sync.create"
        else:
            if task.get("status") == "accepted":
                return AnnotationSyncResult(False, task_id=str(task["id"]), reason="platform task is accepted")
            task.update(
                labels=label_rows,
                label_count=len(label_rows),
                updated_at=now,
            )
            action = "annotation.sync.update"

        _append_sync_audit(
            state,
            action=action,
            resource=str(task["id"]),
            detail=f"{episode_id} -> {episode['episode_id']} labels={len(label_rows)}",
            actor=actor,
        )
        return AnnotationSyncResult(True, task_id=str(task["id"]))

    return get_repository().mutate(_mutate)


def _segment_to_label(segment: SubtaskSegment) -> AnnotationLabel:
    return AnnotationLabel(
        start_frame=segment.start_frame,
        end_frame=segment.end_frame,
        skill_id=segment.skill_id,
        instruction_text=segment.instruction_text,
        success=segment.success,
    )


def _resolve_labeler_episode(
    state: dict[str, Any],
    *,
    dataset_id: str,
    labeler_episode_id: str,
    episode_index: int | None,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    dataset = _resolve_dataset(state, dataset_id)
    if dataset is None and dataset_id == "demo":
        dataset = _ensure_demo_dataset(state)
    if dataset is None:
        return None
    dataset_refs = {str(dataset.get("id", "")), str(dataset.get("name", "")), dataset_id}
    candidates = [
        episode
        for episode in state.get("episodes", [])
        if isinstance(episode, dict) and str(episode.get("dataset_id", "")) in dataset_refs
    ]
    if not candidates and dataset_id == "demo":
        episode = _ensure_demo_episode(state, dataset, labeler_episode_id)
        return dataset, episode
    if not candidates:
        return None

    exact = _episode_by_identifier(candidates, {labeler_episode_id})
    if exact is not None:
        return dataset, exact

    if episode_index is not None:
        indexed = _episode_by_identifier(candidates, _episode_index_identifiers(dataset_id, episode_index))
        if indexed is not None:
            return dataset, indexed
        if episode_index == 0 and len(candidates) == 1:
            return dataset, candidates[0]

    return None


def _ensure_demo_dataset(state: dict[str, Any]) -> dict[str, Any]:
    dataset = Dataset(
        id="demo",
        name="Demo labeler clip",
        modality="vision_language_action",
        robot_type="demo",
        storage_uri="builtin://embodied/demo_episode",
        description="Built-in temporal annotation demo clip.",
        episode_count=0,
        created_at=now_iso(),
    ).model_dump(mode="json")
    state["datasets"].append(dataset)
    return dataset


def _ensure_demo_episode(
    state: dict[str, Any],
    dataset: dict[str, Any],
    labeler_episode_id: str,
) -> dict[str, Any]:
    episode = Episode(
        id=new_id("ep"),
        dataset_id=str(dataset["id"]),
        episode_id=labeler_episode_id or "demo_episode",
        robot_cell="demo",
        frame_count=167,
        created_at=now_iso(),
    ).model_dump(mode="json")
    state["episodes"].append(episode)
    dataset["episode_count"] = max(1, int(dataset.get("episode_count", 0)))
    return episode


def _resolve_dataset(state: dict[str, Any], dataset_id: str) -> dict[str, Any] | None:
    for dataset in state.get("datasets", []):
        if not isinstance(dataset, dict):
            continue
        if str(dataset.get("id", "")) == dataset_id or str(dataset.get("name", "")) == dataset_id:
            return dataset
    return None


def _episode_by_identifier(candidates: list[dict[str, Any]], identifiers: set[str]) -> dict[str, Any] | None:
    normalized = {item for item in identifiers if item}
    for episode in candidates:
        episode_refs = {str(episode.get("id", "")), str(episode.get("episode_id", ""))}
        if episode_refs & normalized:
            return episode
    return None


def _episode_index_identifiers(dataset_id: str, episode_index: int) -> set[str]:
    return {
        f"{dataset_id}_ep{episode_index}",
        f"{dataset_id}-ep{episode_index}",
        f"episode_{episode_index:06d}",
        f"episode-{episode_index:06d}",
        f"episode_{episode_index}",
        f"episode-{episode_index}",
        str(episode_index),
    }


def _find_existing_task(
    state: dict[str, Any],
    *,
    dataset_id: str,
    episode_id: str,
    assignee: str,
) -> dict[str, Any] | None:
    for task in state.get("annotation_tasks", []):
        if not isinstance(task, dict):
            continue
        if (
            str(task.get("dataset_id", "")) == dataset_id
            and str(task.get("episode_id", "")) == episode_id
            and str(task.get("assignee", "")) == assignee
            and task.get("task_type") == "trajectory_segment"
        ):
            return task
    return None


def _append_sync_audit(
    state: dict[str, Any],
    *,
    action: str,
    resource: str,
    detail: str,
    actor: dict[str, str],
) -> None:
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
