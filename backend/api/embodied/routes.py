"""Embodied-AI sub-task annotation endpoints.

POST /api/embodied/segments  — full-replace write of a labeler's segment list
GET  /api/embodied/segments  — read current segments for an episode+annotator pair
GET  /api/embodied/datasets  — list available datasets
GET  /api/embodied/datasets/{dataset_id}/episodes  — list episodes in a dataset
GET  /api/embodied/datasets/{dataset_id}/episodes/{episode_index}  — episode bundle

Output path mirrors a LeRobot dataset:
  <DATA_ROOT>/<episode_id>/meta/annotations/<annotator_id>/subtask_segments.v1.jsonl
where DATA_ROOT defaults to backend/data/embodied/ and is overridable via the
XINGJU_EMBODIED_DATA_ROOT env var (used by tests to redirect to tmp_path).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from .schema import SubtaskSegment
from .datasets import DEMO_ROOT, DatasetInfo, list_datasets, dataset_root_for
from .lerobot_reader import list_episodes
from .episode_materializer import MaterializeTimeoutError, materialize
from .qc import score_annotator


logger = logging.getLogger(__name__)


# TODO(auth): replace this header-equals-body check with a real per-annotator
# token (signed cookie or bearer JWT) issued by the platform login flow. The
# current check is defense-in-depth only — it rejects co-resident origins that
# tamper with the request body, but a caller who knows the annotator_id can
# still forge the header. Localhost-only CORS (see api/main.py) is what keeps
# this safe today; this header gap will become real the moment CORS opens up.


router = APIRouter(prefix="/api/embodied", tags=["embodied"])


def _data_root() -> Path:
    return Path(os.environ.get(
        "XINGJU_EMBODIED_DATA_ROOT",
        Path(__file__).resolve().parents[2] / "data" / "embodied",
    ))


def _cache_root() -> Path:
    return Path(os.environ.get(
        "XINGJU_EMBODIED_CACHE_ROOT",
        Path(__file__).resolve().parents[2] / "data" / "embodied_cache",
    ))


def _cache_url(bundle_file: Path, cache_root: Path) -> str:
    # Build the /embodied-cache URL for one materialized file WITHOUT assuming
    # the materializer's internal cache-slug scheme. The bundle's clip/sprite/
    # proprio all live under cache_root/<...>/ep<ix>/; we just make the file
    # path relative to cache_root and prefix the static mount. This stays
    # correct even if Phase 2 changes how it names <dataset_id>.
    rel = bundle_file.resolve().relative_to(cache_root.resolve())
    return "/embodied-cache/" + rel.as_posix()


def _load_gold(dataset_root: Path, episode_index: int) -> list[dict] | None:
    """Return gold segments for one episode, or None when no _gold file exists.

    Gold lives at <root>/meta/annotations/_gold/subtask_segments.v1.jsonl
    (fork-native, all episodes in one file). Filter to this episode_index.
    Tolerate malformed lines the same way GET /segments does — skip, don't 500.
    """
    path = dataset_root / "meta" / "annotations" / "_gold" / "subtask_segments.v1.jsonl"
    if not path.exists():
        return None
    out: list[dict] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                seg = SubtaskSegment.model_validate_json(line)
            except ValidationError as exc:
                logger.warning("dropping malformed gold line in %s: %s", path, exc)
                continue
            if seg.episode_index == episode_index:
                out.append(seg.model_dump(mode="json"))
    return out


def _load_segments_file(path: Path, *, episode_index: int | None = None) -> list[SubtaskSegment]:
    out: list[SubtaskSegment] = []
    if not path.exists():
        return out
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                seg = SubtaskSegment.model_validate_json(line)
            except ValidationError as exc:
                logger.warning("dropping malformed segment line in %s: %s", path, exc)
                continue
            if episode_index is None or seg.episode_index == episode_index:
                out.append(seg)
    return out


def _load_annotation_segments(ann_root: Path, *, episode_index: int | None = None) -> dict[str, list[SubtaskSegment]]:
    if not ann_root.is_dir():
        return {}
    out: dict[str, list[SubtaskSegment]] = {}
    for ann_dir in sorted(ann_root.iterdir(), key=lambda p: p.name):
        if not ann_dir.is_dir() or ann_dir.name == "_gold":
            continue
        segments = _load_segments_file(ann_dir / "subtask_segments.v1.jsonl", episode_index=episode_index)
        if segments:
            out.setdefault(ann_dir.name, []).extend(segments)
    return out


def _merge_annotation_maps(*maps: dict[str, list[SubtaskSegment]]) -> dict[str, list[SubtaskSegment]]:
    merged: dict[str, list[SubtaskSegment]] = {}
    for source in maps:
        for annotator_id, segments in source.items():
            merged.setdefault(annotator_id, []).extend(segments)
    return merged


def _annotations_dir_has_episode(ann_dir: Path, episode_index: int | None) -> bool:
    """True iff any annotator subdir (excluding _gold) holds a valid segment
    for this episode_index.

    episode_index=None means the directory itself is episode-scoped (the API
    write store keyed by episode_id) — any valid segment line counts. The
    directory name is authoritative there; re-filtering on the line's own
    episode_index stamp would make the flag lie False for clients that saved
    under the right episode_id with a stale stamp.
    """
    if not ann_dir.is_dir():
        return False
    for sub in ann_dir.iterdir():
        if not sub.is_dir() or sub.name == "_gold":
            continue
        f = sub / "subtask_segments.v1.jsonl"
        if not f.exists():
            continue
        with f.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    seg = SubtaskSegment.model_validate_json(line)
                except ValidationError:
                    continue
                if episode_index is None or seg.episode_index == episode_index:
                    return True
    return False


def _has_annotations(dataset_root: Path, dataset_id: str, episode_index: int) -> bool:
    """True iff any annotator (excluding _gold) has a segment for this episode.

    Two stores are scanned:
    1. The fork-native DATASET-ROOT layout
       (<dataset_root>/meta/annotations/<annotator>/subtask_segments.v1.jsonl,
       all episodes in one file, filtered by episode_index) — annotations that
       ship WITH the recorded dataset.
    2. The API write store POST /segments fills:
       <XINGJU_EMBODIED_DATA_ROOT>/<episode_id>/meta/annotations/... — the
       labeler derives episode_id as f"{dataset_id}_ep{episode_index}"
       (embodied.js EPISODE_ID), which makes the mapping deterministic.
    """
    if _annotations_dir_has_episode(dataset_root / "meta" / "annotations", episode_index):
        return True
    api_store = _data_root() / f"{dataset_id}_ep{episode_index}" / "meta" / "annotations"
    return _annotations_dir_has_episode(api_store, None)  # dir is episode-scoped


# --- Demo dataset ---------------------------------------------------------
# The built-in "demo" dataset is NOT a recorded LeRobotDataset: assets/embodied
# is prep_embodied_demo.py's OUTPUT (demo_episode.mp4, sprite.png,
# demo_episode.gripper.json, episode_meta.json, gold_segments.json) and has no
# meta/info.json or meta/episodes/*.parquet for the reader/materializer to read.
# So the demo path is served directly off those files via the /embodied-assets
# static mount, bypassing list_episodes/materialize entirely.

def _demo_meta() -> dict:
    return json.loads((DEMO_ROOT / "episode_meta.json").read_text())


def _demo_gold() -> list[dict]:
    # assets/embodied/gold_segments.json is a JSON ARRAY of
    # {start_frame,end_frame,skill_id,instruction_text} — the legacy demo shape,
    # not annotator JSONL. Returned as-is for the labeler's gold overlay.
    return json.loads((DEMO_ROOT / "gold_segments.json").read_text())


def _demo_gold_segments() -> list[SubtaskSegment]:
    zero = UUID("00000000-0000-0000-0000-000000000000")
    return [
        SubtaskSegment(
            annotator_id=zero,
            episode_index=0,
            start_frame=item["start_frame"],
            end_frame=item["end_frame"],
            skill_id=item["skill_id"],
            instruction_text=item.get("instruction_text"),
        )
        for item in _demo_gold()
    ]


def _demo_episode_summary() -> dict:
    meta = _demo_meta()
    # The demo labeler saves under the HISTORICAL episode_id "demo_episode"
    # (not "demo_ep0") — scan that store so the picker's annotated-marker is
    # truthful for the demo too.
    demo_store = _data_root() / "demo_episode" / "meta" / "annotations"
    return {
        "episode_index": meta.get("episode_index", 0),
        "task": meta.get("task", ""),
        "length": meta.get("total_frames", 0),
        "fps": meta.get("fps", 0),
        "has_annotations": _annotations_dir_has_episode(demo_store, None),
    }


def _demo_bundle() -> dict:
    meta = _demo_meta()
    return {
        "video_url": "/embodied-assets/demo_episode.mp4",
        "sprite_url": "/embodied-assets/sprite.png",
        "proprio_url": "/embodied-assets/demo_episode.gripper.json",
        "meta": meta,
        "gold": _demo_gold(),
    }


def _segments_path(episode_id: str, annotator_id: UUID) -> Path:
    # NOTE: this is the API's own annotation store under
    # XINGJU_EMBODIED_DATA_ROOT, keyed by the labeler's free-text episode_id
    # (the frontend currently sends "demo_episode") — NOT the recorded
    # dataset root that _has_annotations() scans. See _has_annotations for
    # the divergence and why it is deliberate for now.
    return _data_root() / episode_id / "meta" / "annotations" / str(annotator_id) / "subtask_segments.v1.jsonl"


# ETag is the file's mtime in nanoseconds (or "0" when the file does not yet
# exist). It identifies the version a client most recently read; clients echo
# it on POST as If-Match so two concurrent tabs can't silently overwrite each
# other's saves. mtime_ns is monotonic per-file across atomic os.replace, so
# the etag changes on every successful write.
def _etag(path: Path) -> str:
    try:
        return str(path.stat().st_mtime_ns)
    except FileNotFoundError:
        return "0"


class SegmentsRequest(BaseModel):
    episode_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    annotator_id: UUID
    segments: list[SubtaskSegment]


class SegmentsResponse(BaseModel):
    # `path` removed: leaking the server filesystem layout to the browser
    # served no client purpose and gave a free recon hint to anyone who
    # could reach the endpoint.
    written: int


@router.post("/segments", response_model=SegmentsResponse)
def post_segments(
    req: SegmentsRequest,
    response: Response,
    x_annotator_id: UUID = Header(..., alias="X-Annotator-Id"),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> SegmentsResponse:
    # Defense-in-depth: body annotator_id and header must agree, so a
    # body-tampering attempt from a co-resident origin fails closed.
    if x_annotator_id != req.annotator_id:
        raise HTTPException(status_code=403, detail="annotator_id mismatch")
    out = _segments_path(req.episode_id, req.annotator_id)
    # Optimistic concurrency: when If-Match is supplied, fail with 409 if the
    # file has changed since the client last read it. Omitting If-Match is a
    # deliberate force-overwrite (the manual "save" retry after a conflict).
    if if_match is not None:
        current = _etag(out)
        if if_match != current:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "stale_write",
                    "expected_etag": current,
                    "provided_etag": if_match,
                },
            )
    out.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: serialize to a sibling .tmp, fsync to flush the page cache,
    # then os.replace into place. os.replace is atomic on POSIX, so a crash
    # mid-write (process kill, OOM, disk-full at flush) leaves the previous
    # file intact rather than truncated/empty. Mitigates the documented
    # truncate-and-die hazard when auto-save fires from multiple tabs.
    tmp = out.with_suffix(out.suffix + ".tmp")
    try:
        with tmp.open("w") as f:
            for seg in req.segments:
                f.write(seg.model_dump_json() + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, out)
    except Exception:
        # Best-effort cleanup of the partial temp file; re-raise so FastAPI
        # surfaces the failure to the caller rather than masking it.
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    response.headers["ETag"] = _etag(out)
    return SegmentsResponse(written=len(req.segments))


@router.get("/segments", response_model=list[SubtaskSegment])
def get_segments(
    response: Response,
    episode_id: str = Query(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$"),
    annotator_id: UUID = Query(...),
    x_annotator_id: UUID = Header(..., alias="X-Annotator-Id"),
) -> list[SubtaskSegment]:
    # Defense-in-depth: caller must echo the queried annotator_id in the
    # header so a co-resident origin can't read another annotator's labels
    # just by guessing the UUID.
    if x_annotator_id != annotator_id:
        raise HTTPException(status_code=403, detail="annotator_id mismatch")
    path = _segments_path(episode_id, annotator_id)
    # Version token for optimistic concurrency — present even when the file
    # doesn't exist yet ("0"), so a first save can still be conflict-checked.
    response.headers["ETag"] = _etag(path)
    if not path.exists():
        return []
    out: list[SubtaskSegment] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Tolerate pre-existing legacy lines that fail the current
            # validator (e.g. degenerate start==end written before that
            # invariant was enforced). Skipping with a warning keeps the
            # page loadable; rejecting the whole file would strand the
            # annotator behind an opaque 500. The POST path still rejects
            # new bad input, so this only degrades gracefully on read.
            try:
                out.append(SubtaskSegment.model_validate_json(line))
            except ValidationError as exc:
                logger.warning(
                    "dropping malformed segment line in %s: %s", path, exc
                )
    return out


@router.get("/datasets", response_model=list[DatasetInfo])
def get_datasets() -> list[DatasetInfo]:
    return list_datasets()


@router.get("/datasets/{dataset_id}/episodes")
def get_dataset_episodes(dataset_id: str) -> list[dict]:
    if dataset_id == "demo":
        # Zero-config default: served directly from assets/embodied, not the reader.
        return [_demo_episode_summary()]
    root = dataset_root_for(dataset_id)  # raises HTTPException(404) on unknown id
    out: list[dict] = []
    for ep in list_episodes(root):
        out.append({
            "episode_index": ep.episode_index,
            "task": ep.task,
            "length": ep.length,
            "fps": ep.fps,
            "has_annotations": _has_annotations(root, dataset_id, ep.episode_index),
        })
    return out


@router.get("/datasets/{dataset_id}/episodes/{episode_index}/qc")
def get_dataset_episode_qc(
    dataset_id: str,
    episode_index: int,
    iou_success_threshold: float = Query(default=0.7, ge=0, le=1),
) -> JSONResponse:
    if dataset_id == "demo":
        if episode_index != 0:
            raise HTTPException(status_code=404, detail="demo has only episode 0")
        gold = _demo_gold_segments()
        annotators = _load_annotation_segments(
            _data_root() / "demo_episode" / "meta" / "annotations",
            episode_index=None,
        )
    else:
        root = dataset_root_for(dataset_id)
        raw_gold = _load_gold(root, episode_index) or []
        gold = [SubtaskSegment.model_validate(item) for item in raw_gold]
        annotators = _merge_annotation_maps(
            _load_annotation_segments(root / "meta" / "annotations", episode_index=episode_index),
            _load_annotation_segments(
                _data_root() / f"{dataset_id}_ep{episode_index}" / "meta" / "annotations",
                episode_index=None,
            ),
        )

    scores = [
        score_annotator(
            annotator_id,
            segments,
            gold,
            iou_success_threshold=iou_success_threshold,
        )
        for annotator_id, segments in sorted(annotators.items())
    ]
    return JSONResponse({
        "dataset_id": dataset_id,
        "episode_index": episode_index,
        "gold_count": len(gold),
        "iou_success_threshold": iou_success_threshold,
        "annotators": scores,
    })


# Serialize first-request materialization per episode: sync handlers run in
# Starlette's threadpool, so two simultaneous GETs for the same uncached
# episode would both pass the .complete sentinel check and spawn overlapping
# ffmpeg pipelines writing the same clip/sprite with -y — a torn bundle could
# then be sealed behind the sentinel and served forever. The sentinel guards
# against crashes; this lock guards against concurrency. Keyed by
# (dataset_id, episode_index); entries are tiny and bounded by the episode
# count, so no eviction is needed.
_materialize_locks: dict[tuple[str, int], threading.Lock] = {}
_materialize_locks_guard = threading.Lock()


def _materialize_lock(dataset_id: str, episode_index: int) -> threading.Lock:
    with _materialize_locks_guard:
        return _materialize_locks.setdefault(
            (dataset_id, episode_index), threading.Lock()
        )


@router.get("/datasets/{dataset_id}/episodes/{episode_index}")
def get_dataset_episode(dataset_id: str, episode_index: int) -> JSONResponse:
    if dataset_id == "demo":
        # The demo has exactly one episode (index 0); reject anything else 404.
        if episode_index != 0:
            raise HTTPException(status_code=404, detail="demo has only episode 0")
        return JSONResponse(_demo_bundle())
    root = dataset_root_for(dataset_id)  # raises HTTPException(404) on unknown id
    cache_root = _cache_root()
    with _materialize_lock(dataset_id, episode_index):
        try:
            bundle = materialize(root, episode_index, cache_root=cache_root)
        except IndexError:
            # get_episode_meta raises IndexError for an unknown/negative
            # episode_index; map it to 404 like the demo branch does instead
            # of letting it escape as a 500.
            raise HTTPException(
                status_code=404, detail=f"episode {episode_index} not found"
            )
        except MaterializeTimeoutError as exc:
            # A hung ffmpeg/ffprobe hit its wall-clock timeout. Surface a
            # clean retryable 503 instead of an opaque 500; the `with` block
            # guarantees the per-episode lock is released, so the retry is
            # not deadlocked behind the dead pipeline.
            raise HTTPException(status_code=503, detail=str(exc))
    meta = json.loads(bundle.meta.read_text())
    return JSONResponse({
        "video_url": _cache_url(bundle.clip, cache_root),
        "sprite_url": _cache_url(bundle.sprite, cache_root),
        "proprio_url": _cache_url(bundle.proprio, cache_root),
        "meta": meta,
        "gold": _load_gold(root, episode_index),
    })
