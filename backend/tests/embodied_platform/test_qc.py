"""Unit tests for the temporal-IoU QC primitives (pure functions over repo state).

These encode WHY the QC differentiator matters:
- temporal_iou is the LeRobot-style overlap measure; degenerate/disjoint must be 0.
- agreement MUST use optimal (Hungarian) same-skill matching, not greedy — the
  repeated-skill fixture below has a strictly different optimal vs greedy mean,
  so a greedy implementation cannot pass it.
- coverage is the fraction of episode frames actually labeled (clamped union),
  which is what the trained-ready gate enforces.
"""
from __future__ import annotations

import pytest

from api.embodied_platform.qc import agreement, dataset_qc, score_task, temporal_iou


def _task(*labels: tuple[int, int, str]) -> dict:
    return {
        "labels": [
            {"start_frame": s, "end_frame": e, "skill_id": k} for s, e, k in labels
        ]
    }


def test_temporal_iou_identical_ranges_is_one():
    assert temporal_iou((0, 100), (0, 100)) == pytest.approx(1.0)


def test_temporal_iou_disjoint_ranges_is_zero():
    assert temporal_iou((0, 10), (10, 20)) == 0.0
    assert temporal_iou((0, 10), (50, 60)) == 0.0


def test_temporal_iou_half_overlap_is_one_third():
    # [0,10) and [5,15): intersection 5, union 15 -> 1/3.
    assert temporal_iou((0, 10), (5, 15)) == pytest.approx(1 / 3)


def test_temporal_iou_degenerate_range_is_zero():
    # start >= end is degenerate (zero-length) on either side -> 0.
    assert temporal_iou((5, 5), (0, 10)) == 0.0
    assert temporal_iou((0, 10), (7, 7)) == 0.0
    assert temporal_iou((10, 5), (0, 10)) == 0.0


def test_agreement_uses_optimal_matching_not_greedy_on_repeated_skill():
    # Two "grasp" labels on each side. The greedy choice (take the globally
    # largest IoU pair first) locks A1<->B1 (0.667) and forces A2<->B2 (0.0),
    # giving mean 0.333. The OPTIMAL assignment is the off-diagonal
    # A1<->B2 (0.40) + A2<->B1 (0.40) -> mean 0.40. A greedy impl returns 0.333.
    task_a = _task((0, 50, "grasp"), (40, 60, "grasp"))
    task_b = _task((10, 60, "grasp"), (0, 20, "grasp"))

    result = agreement(task_a, task_b)

    assert result == pytest.approx(0.40)
    assert result != pytest.approx(1 / 3)


def test_agreement_matches_only_within_same_skill_id():
    # Different skills never match: each is its own 1x1 group with no counterpart.
    task_a = _task((0, 100, "approach"))
    task_b = _task((0, 100, "grasp"))
    assert agreement(task_a, task_b) == 0.0


def test_agreement_identical_labels_is_one():
    task_a = _task((0, 50, "approach"), (50, 100, "grasp"))
    task_b = _task((0, 50, "approach"), (50, 100, "grasp"))
    assert agreement(task_a, task_b) == pytest.approx(1.0)


def test_agreement_no_labels_is_zero():
    assert agreement(_task(), _task()) == 0.0


def test_agreement_one_sided_skill_counts_against_agreement():
    # A and B agree perfectly on "grasp" (IoU 1.0). A adds an *extra* "place"
    # segment that B never labeled. That spurious one-sided segment must DRAG
    # agreement down (contribute 0 IoU over the union denominator), not be
    # silently dropped: without it agreement is 1.0; with it, the matched IoU
    # (1.0 on grasp) is divided over 2 segments (grasp + the unmatched place)
    # -> 0.5. A one-sided skill can only ever lower the score.
    shared_only = _task((0, 100, "grasp"))
    with_extra = _task((0, 100, "grasp"), (100, 200, "place"))
    task_b = _task((0, 100, "grasp"))

    assert agreement(shared_only, task_b) == pytest.approx(1.0)
    assert agreement(with_extra, task_b) == pytest.approx(0.5)
    # Symmetric: the extra skill on either side lowers it the same way.
    assert agreement(task_b, with_extra) == pytest.approx(0.5)


def test_score_task_coverage_is_labeled_fraction_of_episode():
    # Labels cover frames [0,64) and [65,140) of a 200-frame episode.
    # Union length = 64 + 75 = 139; coverage = 139/200.
    task = _task((0, 64, "approach"), (65, 140, "grasp"))
    score = score_task(task, 200)
    assert score["coverage"] == pytest.approx(139 / 200)
    assert score["label_count"] == 2


def test_score_task_overlapping_labels_union_not_double_counted():
    # [0,60) and [40,100) overlap; union is [0,100) = 100 frames of 100.
    task = _task((0, 60, "a"), (40, 100, "b"))
    score = score_task(task, 100)
    assert score["coverage"] == pytest.approx(1.0)
    assert score["overlap"] is True


def test_score_task_clamps_out_of_bounds_so_coverage_never_exceeds_one():
    # A label running past the episode end must not push coverage above 1.0.
    task = _task((0, 500, "a"))
    score = score_task(task, 100)
    assert score["coverage"] == pytest.approx(1.0)
    assert score["in_bounds"] is False


def test_score_task_zero_frame_episode_is_zero_coverage_not_div_by_zero():
    task = _task((0, 10, "a"))
    score = score_task(task, 0)
    assert score["coverage"] == 0.0


def test_score_task_empty_labels_is_zero_coverage():
    score = score_task(_task(), 100)
    assert score["coverage"] == 0.0
    assert score["label_count"] == 0


# ---------------------------------------------------------------------------
# Blue-team regression guard — F3 (white-team adjudication 2026-06-08).
# ---------------------------------------------------------------------------

_THRESHOLDS = {"iou_threshold": 0.7, "coverage_threshold": 0.9}


def _segment_task(task_id: str, assignee: str) -> dict:
    # A fully-covering, single-skill segment over a 100-frame episode. Two of
    # these agree perfectly (IoU 1.0), so the ONLY thing standing between this
    # data and a passing gate is whether agreement requires distinct annotators.
    return {
        "id": task_id,
        "dataset_id": "ds-f3",
        "episode_id": "ep-f3",
        "task_type": "trajectory_segment",
        "assignee": assignee,
        "labels": [{"start_frame": 0, "end_frame": 100, "skill_id": "grasp"}],
    }


def _state_with_segment_tasks(tasks: list[dict]) -> dict:
    return {
        "datasets": [{"id": "ds-f3", "name": "f3-ds"}],
        "episodes": [{"id": "ep-f3", "dataset_id": "ds-f3", "episode_id": "ep-f3", "frame_count": 100}],
        "annotation_tasks": tasks,
    }


def test_single_annotator_double_submit_does_not_pass_agreement_gate():
    """F3: inter-annotator agreement must count DISTINCT assignees. One annotator
    double-submitting two perfectly-overlapping (IoU 1.0) segment tasks for the
    same episode must NOT self-satisfy the agreement bar that gates trained-ready.

    Both tasks have full coverage, so coverage clears its bar — proving the failure
    is SPECIFICALLY the agreement gate, not coverage. With < 2 distinct annotators
    no cross-assignee agreement is computed (agreement stays None) and the gate
    fails closed. A buggy impl that paired same-annotator tasks would compute 1.0
    here and wrongly pass."""
    state = _state_with_segment_tasks(
        [
            _segment_task("task-1", "annotator-a"),
            _segment_task("task-2", "annotator-a"),  # SAME annotator, second submit.
        ]
    )

    report = dataset_qc(state, "ds-f3", _THRESHOLDS)

    assert report["passed"] is False
    row = report["episodes"][0]
    # Coverage is fine — so the only thing failing is the agreement gate.
    assert row["coverage"] >= _THRESHOLDS["coverage_threshold"]
    # No cross-assignee agreement was computed: it must stay None (not vacuously 1.0).
    assert row["agreement"] is None
    assert row["passed"] is False


def test_two_distinct_annotators_with_matching_labels_pass_the_gate():
    """F3 (positive side): the gate is not over-tightened. Two DISTINCT annotators
    submitting the same perfectly-overlapping labels DO clear the agreement bar and
    the episode passes — so the distinct-assignee rule blocks only self-agreement,
    not legitimate cross-annotator agreement."""
    state = _state_with_segment_tasks(
        [
            _segment_task("task-1", "annotator-a"),
            _segment_task("task-2", "annotator-b"),  # DIFFERENT annotator.
        ]
    )

    report = dataset_qc(state, "ds-f3", _THRESHOLDS)

    assert report["passed"] is True
    row = report["episodes"][0]
    assert row["agreement"] == pytest.approx(1.0)
    assert row["passed"] is True
