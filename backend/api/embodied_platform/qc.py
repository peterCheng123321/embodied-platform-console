"""Temporal-IoU quality control for embodied annotation datasets.

Pure functions over the JSON repository state dict. No I/O, no FastAPI — the
routes layer wraps these so the QC math stays unit-testable in isolation.

The differentiator (NORTH-STAR data-quality flywheel) is *inter-annotator
agreement*: when two annotators label the same episode, we measure how well their
temporal segments line up. Matching segments greedily (largest-IoU-pair first)
underestimates agreement on repeated skills, so we compute the *optimal*
same-skill assignment via the Hungarian algorithm.
"""
from __future__ import annotations

from typing import Any, Iterable

Range = tuple[int, int]

# Compute bounds so the (unauthenticated, like the other GETs by design) QC
# endpoint cannot be turned into an algorithmic-complexity DoS by hostile data:
#   - MAX_OPTIMAL_GROUP: above this same-skill group size we fall back from the
#     O(n^3) Hungarian assignment to a near-quadratic greedy best-match.
#     Hungarian's optimal-vs-greedy advantage only matters for the small
#     repeated-skill groups seen in real annotation; for pathological groups
#     (e.g. hundreds of identical segments -> a dense all-ones cost matrix, the
#     Hungarian worst case) the greedy bound avoids cubic blowup.
#   - MAX_QC_TASKS: only the first N annotation tasks per episode enter the
#     O(tasks^2) pairwise-agreement loop (coverage still iterates ALL tasks,
#     which is cheap). Bounds C(tasks, 2) against an episode flooded with tasks.
MAX_OPTIMAL_GROUP = 64
MAX_QC_TASKS = 16


class DatasetNotFound(KeyError):
    """The requested dataset id/name does not exist in the state.

    A dedicated subclass lets the route map *only* a genuinely-missing dataset
    to 404; any other KeyError (corrupt episode/label data) must not be masked
    as a misleading 404.
    """


def temporal_iou(a: Range, b: Range) -> float:
    """Intersection-over-union of two integer frame ranges ``[start, end)``.

    Mirrors the LeRobot temporal-IoU definition. Returns 0.0 if either range is
    degenerate (``start >= end``) or the two ranges are disjoint.
    """
    a_start, a_end = a
    b_start, b_end = b
    if a_start >= a_end or b_start >= b_end:
        return 0.0
    inter = min(a_end, b_end) - max(a_start, b_start)
    if inter <= 0:
        return 0.0
    union = (a_end - a_start) + (b_end - b_start) - inter
    if union <= 0:
        return 0.0
    return inter / union


def _label_range(label: Any) -> Range | None:
    """Best-effort ``(start, end)`` for one label, or ``None`` if unusable.

    On-disk state can be corrupt (a label that is not a dict, missing frame
    keys, or a non-integer / NaN / Inf frame). QC must never 500 on such data:
    an unparseable label is treated as non-contributing (skipped) so the report
    degrades to a failing-but-valid result instead of raising.
    """
    if not isinstance(label, dict):
        return None
    try:
        start = int(label["start_frame"])
        end = int(label["end_frame"])
    except (KeyError, TypeError, ValueError, OverflowError):
        # KeyError: missing key. TypeError: None / wrong type. ValueError: a
        # NaN float or non-numeric string. OverflowError: float('inf').
        return None
    return (start, end)


def _label_ranges(labels: Any) -> list[Range]:
    """All parseable ranges from a labels container; corrupt entries dropped."""
    if not isinstance(labels, list):
        return []
    ranges: list[Range] = []
    for label in labels:
        rng = _label_range(label)
        if rng is not None:
            ranges.append(rng)
    return ranges


def _merged_union_length(ranges: Iterable[Range], frame_count: int) -> int:
    """Length of the union of ranges, each clamped to ``[0, frame_count)``.

    Clamping before merging guarantees out-of-bounds labels can never make the
    covered length exceed ``frame_count`` (and thus coverage > 1.0).
    """
    if frame_count <= 0:
        return 0
    clamped: list[Range] = []
    for start, end in ranges:
        lo = max(0, min(start, frame_count))
        hi = max(0, min(end, frame_count))
        if hi > lo:
            clamped.append((lo, hi))
    if not clamped:
        return 0
    clamped.sort()
    total = 0
    cur_start, cur_end = clamped[0]
    for start, end in clamped[1:]:
        if start > cur_end:
            total += cur_end - cur_start
            cur_start, cur_end = start, end
        else:
            cur_end = max(cur_end, end)
    total += cur_end - cur_start
    return total


def score_task(task: dict[str, Any], episode_frame_count: int) -> dict[str, Any]:
    """Per-task QC metrics against an episode of ``episode_frame_count`` frames.

    Returns coverage (clamped union of labeled ranges / frame_count), label_count,
    and validity flags: frame_order (every start < end), in_bounds (every label
    within [0, frame_count)), and overlap (any two labels share frames).
    """
    ranges = _label_ranges(task.get("labels"))

    frame_order = all(start < end for start, end in ranges)
    in_bounds = all(0 <= start and end <= episode_frame_count for start, end in ranges)

    covered = _merged_union_length(ranges, episode_frame_count)
    coverage = (covered / episode_frame_count) if episode_frame_count > 0 else 0.0

    # Overlap: total length of valid (non-degenerate) ranges exceeds their union.
    valid_total = sum(end - start for start, end in ranges if end > start)
    union_total = _merged_union_length(ranges, max(episode_frame_count, _max_end(ranges)))
    overlap = valid_total > union_total

    return {
        "coverage": coverage,
        "label_count": len(ranges),
        "frame_order": frame_order,
        "in_bounds": in_bounds,
        "overlap": overlap,
    }


def _max_end(ranges: list[Range]) -> int:
    return max((end for _, end in ranges), default=0)


def _hungarian_max(matrix: list[list[float]]) -> float:
    """Maximum-weight assignment value over a square cost matrix.

    Implements the O(n^3) Hungarian algorithm on the negated weights (so a
    min-cost assignment maximizes total weight). ``matrix`` must be square; pad
    with zero-weight rows/cols before calling when group sizes differ.
    """
    n = len(matrix)
    if n == 0:
        return 0.0
    INF = float("inf")
    # Minimize cost = -weight. Use the standard potentials/augmenting-path form.
    cost = [[-matrix[i][j] for j in range(n)] for i in range(n)]
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)  # p[j] = row assigned to column j (1-indexed; 0 = none)
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = -1
            for j in range(1, n + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    total = 0.0
    for j in range(1, n + 1):
        if p[j] != 0:
            total += matrix[p[j] - 1][j - 1]
    return total


def _greedy_match_value(ranges_a: list[Range], ranges_b: list[Range]) -> float:
    """Sum of IoUs of a greedy largest-pair-first one-to-one matching.

    Near-quadratic (O(n^2 log n): it sorts the n^2 candidate pairs) — the bounded
    fallback for pathological same-skill groups where the O(n^3) Hungarian optimum
    is not worth the cost (see MAX_OPTIMAL_GROUP). Greedy under-estimates the
    optimal total, which only ever *lowers* agreement — the gate stays fail-closed
    (it never inflates agreement past what the optimum would give).
    """
    pairs = sorted(
        (
            (temporal_iou(a, b), i, j)
            for i, a in enumerate(ranges_a)
            for j, b in enumerate(ranges_b)
        ),
        reverse=True,
    )
    used_a: set[int] = set()
    used_b: set[int] = set()
    total = 0.0
    for iou, i, j in pairs:
        if iou <= 0:
            break  # remaining pairs are all 0 — nothing more to gain.
        if i in used_a or j in used_b:
            continue
        total += iou
        used_a.add(i)
        used_b.add(j)
    return total


def _best_match_value(ranges_a: list[Range], ranges_b: list[Range]) -> float:
    """Total IoU of the best one-to-one matching of two same-skill range lists.

    Optimal (Hungarian) for realistic small groups; falls back to near-quadratic
    greedy when either group exceeds MAX_OPTIMAL_GROUP so a hostile flood of
    same-skill labels (e.g. hundreds of identical segments -> a dense all-ones
    cost matrix, Hungarian's O(n^3) worst case) cannot drive cubic compute (the
    algorithmic-complexity DoS).
    """
    if not ranges_a or not ranges_b:
        return 0.0
    if len(ranges_a) > MAX_OPTIMAL_GROUP or len(ranges_b) > MAX_OPTIMAL_GROUP:
        return _greedy_match_value(ranges_a, ranges_b)
    n = max(len(ranges_a), len(ranges_b))
    matrix = [
        [
            temporal_iou(ranges_a[i], ranges_b[j])
            if i < len(ranges_a) and j < len(ranges_b)
            else 0.0
            for j in range(n)
        ]
        for i in range(n)
    ]
    return _hungarian_max(matrix)


def agreement(task_a: dict[str, Any], task_b: dict[str, Any]) -> float:
    """Mean temporal IoU over the best same-skill matching of two tasks' labels.

    Labels are grouped by ``skill_id``; within each *shared* skill the best
    one-to-one assignment of A-labels to B-labels maximizes total IoU (optimal
    Hungarian for small groups, greedy fallback for pathological ones).

    The denominator spans the *union* of skills (Σ max(|A_skill|, |B_skill|)),
    not just the matched min: a skill only one annotator used, or an extra
    same-skill segment on one side, contributes 0 IoU but still counts in the
    denominator — so spurious one-sided segments lower agreement rather than
    being silently dropped. Returns 0.0 when neither side has any parseable
    label, so the trained-ready gate fails closed rather than vacuously passing.
    """
    groups_a = _group_by_skill(task_a)
    groups_b = _group_by_skill(task_b)

    total_iou = 0.0
    denominator = 0
    for skill in groups_a.keys() | groups_b.keys():
        ranges_a = groups_a.get(skill, [])
        ranges_b = groups_b.get(skill, [])
        # Union over skills: every segment on the larger side must be accounted
        # for, so one-sided skills/extras dilute the mean toward 0.
        denominator += max(len(ranges_a), len(ranges_b))
        total_iou += _best_match_value(ranges_a, ranges_b)

    if denominator == 0:
        return 0.0
    return total_iou / denominator


def _group_by_skill(task: dict[str, Any]) -> dict[str, list[Range]]:
    groups: dict[str, list[Range]] = {}
    labels = task.get("labels")
    if not isinstance(labels, list):
        return groups
    for label in labels:
        rng = _label_range(label)
        if rng is None or not isinstance(label, dict) or "skill_id" not in label:
            # Corrupt or skill-less label: non-contributing, never raises.
            continue
        groups.setdefault(str(label["skill_id"]), []).append(rng)
    return groups


def _matches(item: dict[str, Any], identifier: str, fields: tuple[str, ...]) -> bool:
    return any(str(item.get(field, "")) == identifier for field in fields)


def _task_assignee(task: dict[str, Any]) -> str:
    """Identity used to decide whether two segment tasks are cross-annotator.

    Coerced to ``str`` so a corrupt non-string assignee on disk never raises
    (the 'never 500 on corrupt state' read posture). A missing/empty assignee
    collapses to ``""`` — tasks sharing that sentinel are treated as the SAME
    (unknown) annotator, so they cannot manufacture a distinct-assignee pair and
    the agreement gate stays fail-closed.
    """
    return str(task.get("assignee", "") or "")


def dataset_qc(
    state: dict[str, Any],
    dataset_id: str,
    thresholds: dict[str, float],
) -> dict[str, Any]:
    """Compute a QC report for a dataset over the repository state.

    For each episode in the dataset: coverage (min across that episode's
    trajectory_segment tasks — a single under-covering annotator should fail the
    bar) and, when >= 2 DISTINCT assignees have segment tasks, the worst pairwise
    inter-annotator agreement over cross-assignee pairs only (so one annotator
    double-submitting cannot self-satisfy the bar). With fewer than 2 distinct
    annotators the agreement component fails closed (no agreement is computed and
    it does not vacuously pass). Non-segment task types (success_check /
    safety_event / language_grounding) do not gate trained-ready. The dataset
    passes only if every episode meets both the coverage and agreement bars.

    Robust to corrupt on-disk state: an episode with a non-integer / NaN frame
    count or a label that is not a well-formed dict degrades to a *failing* row
    rather than raising — QC over corrupt state returns a (failing) report,
    never a 500. Only a genuinely-missing dataset raises (DatasetNotFound).
    """
    iou_threshold = thresholds["iou_threshold"]
    coverage_threshold = thresholds["coverage_threshold"]

    dataset = _find_dataset(state, dataset_id)
    dataset_refs = {dataset["id"], dataset.get("name", "")}

    episodes = [
        ep
        for ep in state.get("episodes", [])
        if isinstance(ep, dict) and str(ep.get("dataset_id", "")) in dataset_refs
    ]

    rows: list[dict[str, Any]] = []
    overall_pass = True
    for episode in episodes:
        frame_count = _safe_frame_count(episode.get("frame_count"))
        episode_refs = {episode.get("id", ""), episode.get("episode_id", "")}
        tasks = [
            task
            for task in state.get("annotation_tasks", [])
            if isinstance(task, dict)
            and str(task.get("episode_id", "")) in episode_refs
            and str(task.get("dataset_id", "")) in dataset_refs
        ]

        # Coverage and inter-annotator agreement are properties of the SEGMENTATION
        # task only. Orthogonal task types (success_check / safety_event /
        # language_grounding) legitimately carry no temporal segments, so folding
        # them into the coverage min / agreement min would zero out an otherwise
        # passing episode and wrongly block the trained-ready gate. Restrict both
        # metrics — and the gate's "has annotations" check — to trajectory_segment.
        segment_tasks = [task for task in tasks if task.get("task_type") == "trajectory_segment"]

        if segment_tasks:
            coverage = min(score_task(task, frame_count)["coverage"] for task in segment_tasks)
        else:
            coverage = 0.0

        # Inter-annotator agreement is only meaningful across DISTINCT annotators:
        # one annotator double-submitting segment tasks must NOT self-satisfy the
        # bar, so we pair only segment tasks from different assignees and require
        # >= 2 distinct assignees. Fewer than 2 distinct annotators -> the
        # agreement component fails closed (agreement_value stays None and is NOT
        # vacuously cleared below). Bound the O(tasks^2) pairwise work: only the
        # first MAX_QC_TASKS segment tasks enter the pair loop; coverage above
        # still spans ALL segment tasks (cheap), so a flood cannot vacuously pass.
        distinct_assignees = {_task_assignee(task) for task in segment_tasks}
        agreement_value: float | None = None
        if len(distinct_assignees) >= 2:
            qc_tasks = segment_tasks[:MAX_QC_TASKS]
            cross_assignee_iou = [
                agreement(qc_tasks[i], qc_tasks[j])
                for i in range(len(qc_tasks))
                for j in range(i + 1, len(qc_tasks))
                if _task_assignee(qc_tasks[i]) != _task_assignee(qc_tasks[j])
            ]
            if cross_assignee_iou:
                agreement_value = min(cross_assignee_iou)

        coverage_pass = coverage >= coverage_threshold
        # Fail closed: None (no cross-assignee agreement computed, i.e. < 2 distinct
        # annotators) must NOT pass — one annotator cannot clear the agreement bar.
        agreement_pass = agreement_value is not None and agreement_value >= iou_threshold
        episode_pass = bool(segment_tasks) and coverage_pass and agreement_pass
        if not episode_pass:
            overall_pass = False

        rows.append(
            {
                "episode_id": str(episode.get("episode_id") or episode.get("id") or ""),
                "frame_count": frame_count,
                "task_count": len(tasks),
                "coverage": coverage,
                "agreement": agreement_value,
                "passed": episode_pass,
            }
        )

    if not episodes:
        overall_pass = False

    return {
        "dataset_id": str(dataset.get("id") or dataset.get("name") or dataset_id),
        "passed": overall_pass,
        "episode_count": len(episodes),
        "iou_threshold": iou_threshold,
        "coverage_threshold": coverage_threshold,
        "episodes": rows,
    }


def _safe_frame_count(value: Any) -> int:
    """Episode frame count coerced to a non-negative int; 0 on corrupt input.

    A NaN/Inf/non-numeric frame count must not 500 QC (and must satisfy the
    QCEpisodeRow ``frame_count >= 0`` schema), so any unparseable value or a
    negative value collapses to 0 — yielding 0.0 coverage, a failing row.
    """
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return n if n > 0 else 0


def _find_dataset(state: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    for dataset in state.get("datasets", []):
        if isinstance(dataset, dict) and _matches(dataset, dataset_id, ("id", "name")):
            return dataset
    raise DatasetNotFound(dataset_id)
