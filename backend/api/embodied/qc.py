"""Trajectory segment QC scoring for the hosted temporal labeler.

This intentionally ports only the small quality-scoring core from the
`lerobot-trajectory-qc` fork into the platform backend. It avoids importing the
full fork or its standalone viewer stack, while keeping the same semantics:
temporal IoU matching by skill plus a Jeffreys-prior Beta posterior.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from .schema import SubtaskSegment


JEFFREYS_ALPHA0 = 0.5
JEFFREYS_BETA0 = 0.5

# Compute bound for the exact DP matcher. Its <=22 gate bounds only the GOLD
# (bitmask) side; the recursion depth and (index, mask) memo both grow with the
# ANNOTATOR segment count, which arrives uncapped from POST /segments — ~1000
# segments already overflow Python's recursion limit (a 500), and the lru_cache
# grows without bound before that. score_annotator therefore scores only the
# first ANNOTATOR_SEGMENTS_CAP segments (a deterministic prefix in stored
# order), flags the report, and counts the unscored overflow as failures so a
# flood can never be free (fail-closed).
ANNOTATOR_SEGMENTS_CAP = 512


def temporal_iou(a: tuple[int, int], b: tuple[int, int]) -> float:
    """Intersection-over-union of two integer frame ranges [start, end)."""
    a_start, a_end = a
    b_start, b_end = b
    inter = max(0, min(a_end, b_end) - max(a_start, b_start))
    union = max(a_end, b_end) - min(a_start, b_start)
    if union <= 0:
        return 0.0
    return inter / union


def _greedy_match(weights: list[list[float]]) -> list[tuple[int, int, float]]:
    candidates: list[tuple[float, int, int]] = []
    for i, row in enumerate(weights):
        for j, weight in enumerate(row):
            if weight > 0:
                candidates.append((weight, i, j))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))

    used_a: set[int] = set()
    used_g: set[int] = set()
    pairs: list[tuple[int, int, float]] = []
    for weight, i, j in candidates:
        if i in used_a or j in used_g:
            continue
        used_a.add(i)
        used_g.add(j)
        pairs.append((i, j, weight))
    return pairs


def match_segments(
    annotator: list[SubtaskSegment],
    gold: list[SubtaskSegment],
) -> tuple[list[tuple[int, int, float]], list[int], list[int]]:
    """Maximum-weight skill-constrained temporal matching.

    For ordinary labeler episodes the segment count is small, so use an exact
    dynamic-programming assignment. For very large episodes — more than 22
    gold segments (the bitmask side) or more than ANNOTATOR_SEGMENTS_CAP
    annotator segments (the recursion/memo side) — fall back to a
    deterministic greedy match rather than pulling scipy into the platform
    backend solely for Hungarian assignment.
    """
    if not annotator or not gold:
        return [], list(range(len(annotator))), list(range(len(gold)))

    weights: list[list[float]] = []
    for a in annotator:
        row: list[float] = []
        for g in gold:
            if a.skill_id != g.skill_id:
                row.append(0.0)
            else:
                row.append(temporal_iou((a.start_frame, a.end_frame), (g.start_frame, g.end_frame)))
        weights.append(row)

    # The exact DP recurses once per annotator segment; its safe depth depends on
    # the AMBIENT stack already consumed (pytest, server frames), so gate it well
    # below Python's 1000 default rather than at the truncation cap — a transient
    # RecursionError was observed at 512 under a deep call context. Beyond the
    # gate, the iterative greedy matcher below handles it (stack-free).
    DP_RECURSION_GATE = 256
    if len(gold) <= 22 and len(annotator) <= DP_RECURSION_GATE:
        @lru_cache(maxsize=None)
        def solve(i: int, used_gold_mask: int) -> tuple[float, tuple[tuple[int, int, float], ...]]:
            if i >= len(annotator):
                return 0.0, ()
            best_score, best_pairs = solve(i + 1, used_gold_mask)
            best_key = (best_score, len(best_pairs), tuple((-p[0], -p[1]) for p in best_pairs))
            for j, weight in enumerate(weights[i]):
                if weight <= 0 or (used_gold_mask & (1 << j)):
                    continue
                rest_score, rest_pairs = solve(i + 1, used_gold_mask | (1 << j))
                candidate_pairs = ((i, j, weight), *rest_pairs)
                candidate_score = rest_score + weight
                candidate_key = (
                    candidate_score,
                    len(candidate_pairs),
                    tuple((-p[0], -p[1]) for p in candidate_pairs),
                )
                if candidate_key > best_key:
                    best_score = candidate_score
                    best_pairs = candidate_pairs
                    best_key = candidate_key
            return best_score, best_pairs

        pairs = list(solve(0, 0)[1])
    else:
        pairs = _greedy_match(weights)

    matched_a = {i for i, _, _ in pairs}
    matched_g = {j for _, j, _ in pairs}
    unmatched_a = [i for i in range(len(annotator)) if i not in matched_a]
    unmatched_g = [j for j in range(len(gold)) if j not in matched_g]
    return pairs, unmatched_a, unmatched_g


def score_annotator(
    annotator_id: str,
    segments: list[SubtaskSegment],
    gold: list[SubtaskSegment],
    *,
    iou_success_threshold: float,
) -> dict[str, Any]:
    # Compute bound (see ANNOTATOR_SEGMENTS_CAP): score a deterministic prefix,
    # flag the report, and count the unscored overflow as failures below so a
    # segment flood degrades to a terrible-but-deterministic score, never a
    # recursion blowup.
    capped = len(segments) > ANNOTATOR_SEGMENTS_CAP
    scored = segments[:ANNOTATOR_SEGMENTS_CAP] if capped else segments
    overflow = len(segments) - len(scored)
    pairs, unmatched_a, unmatched_g = match_segments(scored, gold)

    alpha = JEFFREYS_ALPHA0
    beta = JEFFREYS_BETA0
    per_skill_ious: dict[str, list[float]] = {}

    def observe(success: bool) -> None:
        nonlocal alpha, beta
        if success:
            alpha += 1.0
        else:
            beta += 1.0

    for a_idx, g_idx, iou in pairs:
        skill = gold[g_idx].skill_id
        per_skill_ious.setdefault(skill, []).append(iou)
        observe(iou >= iou_success_threshold)

    for g_idx in unmatched_g:
        _ = gold[g_idx]
        observe(False)

    for a_idx in unmatched_a:
        _ = scored[a_idx]
        observe(False)

    # Each over-cap segment is an unscored extra: a failure observation, same
    # as an unmatched segment (no per-item work — plain arithmetic).
    beta += float(overflow)

    per_skill_iou = {
        skill: sum(values) / len(values)
        for skill, values in sorted(per_skill_ious.items())
    }

    return {
        "annotator_id": annotator_id,
        "segment_count": len(segments),
        "matched_count": len(pairs),
        "false_positive_count": len(unmatched_a) + overflow,
        "miss_count": len(unmatched_g),
        "annotator_segments_capped": capped,
        "posterior_alpha": alpha,
        "posterior_beta": beta,
        "posterior_mean": alpha / (alpha + beta),
        "per_skill_iou": per_skill_iou,
    }
