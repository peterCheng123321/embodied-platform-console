"""Seeded adversarial agents for the collection API test surface."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import random
import re
from typing import Any, Callable

from fastapi.testclient import TestClient


ISSUE_CODES = [
    "missing_required_speech",
    "speech_while_motion",
    "task_description_mismatch",
    "unclear_target_object",
    "scene_clutter_insufficient",
    "scene_clutter_invalid_plane",
    "lighting_too_dark",
    "other_people_or_devices_visible",
    "gripper_out_of_frame",
    "marker_or_block_missing",
    "motion_too_fast",
    "background_noise",
    "device_disconnect",
    "abnormal_recovery_missing",
    "task_specific_setup_failure",
    "attempt_limit_exhausted",
    "upload_quota_incomplete",
]

TASK_IDS = [f"task_{index:02d}" for index in range(1, 9)]
ATTEMPT_UPLOADED_STATUSES = {"uploaded", "ready_for_review", "accepted", "rejected", "rework"}


@dataclass(frozen=True)
class ActionEntry:
    step: int
    agent: str
    action: str
    expected_status: int
    actual_status: int
    payload: dict[str, Any]
    response: dict[str, Any] | list[dict[str, Any]] | str

    @property
    def replay_key(self) -> tuple[int, str, str, int, str]:
        payload = normalise_dynamic_ids(json.dumps(self.payload, sort_keys=True, ensure_ascii=False))
        return (self.step, self.agent, self.action, self.expected_status, payload)


@dataclass
class AgentReport:
    seed: int
    steps: int
    entries: list[ActionEntry] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    successful_writes: int = 0

    @property
    def agents_seen(self) -> set[str]:
        return {entry.agent for entry in self.entries}

    def format_failures(self) -> str:
        if not self.failures:
            return ""
        tail = [
            f"{entry.step}:{entry.agent}.{entry.action} expected={entry.expected_status} actual={entry.actual_status} payload={entry.payload}"
            for entry in self.entries[-12:]
        ]
        return "\n".join(["Adversarial agent failures:", *self.failures, "Recent actions:", *tail])


def normalise_dynamic_ids(value: str) -> str:
    value = re.sub(r"crun_[0-9a-f]{12}", "crun_<id>", value)
    value = re.sub(r"cat_[0-9a-f]{12}", "cat_<id>", value)
    return value


class CollectionWorld:
    def __init__(self, client: TestClient, seed: int, steps: int) -> None:
        self.client = client
        self.rng = random.Random(seed)
        self.report = AgentReport(seed=seed, steps=steps)

    def headers(self, role: str, actor: str) -> dict[str, str]:
        from api.embodied_platform.routes import sign_principal

        return {
            "X-Embodied-Role": role,
            "X-Embodied-Actor": actor,
            "X-Embodied-Signature": sign_principal(actor, role),
        }

    def get_json(self, path: str) -> Any:
        response = self.client.get(path)
        if response.status_code != 200:
            raise AssertionError(f"GET {path} failed with {response.status_code}: {response.text}")
        return response.json()

    def post(
        self,
        *,
        step: int,
        agent: str,
        action: str,
        path: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None,
        expected_status: int,
    ) -> Any:
        before = self.snapshot_counts()
        response = self.client.post(path, headers=headers or {}, json=payload)
        body = self.safe_body(response)
        self.add_entry(step, agent, action, expected_status, response.status_code, payload, body)
        self.check_status(step, action, expected_status, response.status_code, body)
        self.check_mutation_boundary(step, action, before, response.status_code, expected_status)
        self.check_invariants(step, f"{agent}.{action}")
        return body

    def patch(
        self,
        *,
        step: int,
        agent: str,
        action: str,
        path: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None,
        expected_status: int,
    ) -> Any:
        before = self.snapshot_counts()
        response = self.client.patch(path, headers=headers or {}, json=payload)
        body = self.safe_body(response)
        self.add_entry(step, agent, action, expected_status, response.status_code, payload, body)
        self.check_status(step, action, expected_status, response.status_code, body)
        self.check_mutation_boundary(step, action, before, response.status_code, expected_status)
        self.check_invariants(step, f"{agent}.{action}")
        return body

    def add_entry(
        self,
        step: int,
        agent: str,
        action: str,
        expected_status: int,
        actual_status: int,
        payload: dict[str, Any],
        body: Any,
    ) -> None:
        self.report.entries.append(ActionEntry(
            step=step,
            agent=agent,
            action=action,
            expected_status=expected_status,
            actual_status=actual_status,
            payload=payload,
            response=body,
        ))
        if actual_status == 200 and expected_status == 200:
            self.report.successful_writes += 1

    def safe_body(self, response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text

    def check_status(self, step: int, action: str, expected_status: int, actual_status: int, body: Any) -> None:
        if actual_status != expected_status:
            self.report.failures.append(
                f"step {step} {action}: expected HTTP {expected_status}, got {actual_status}, body={body}"
            )

    def snapshot_counts(self) -> dict[str, int]:
        return {
            "runs": len(self.get_json("/api/embodied-platform/collection-runs")),
            "attempts": len(self.get_json("/api/embodied-platform/collection-attempts")),
            "audit": len(self.get_json("/api/embodied-platform/audit-events")),
        }

    def check_mutation_boundary(
        self,
        step: int,
        action: str,
        before: dict[str, int],
        actual_status: int,
        expected_status: int,
    ) -> None:
        after = self.snapshot_counts()
        if expected_status >= 400 and actual_status >= 400 and after != before:
            self.report.failures.append(f"step {step} {action}: rejected write mutated state {before} -> {after}")

    def check_invariants(self, step: int, label: str) -> None:
        profiles = self.get_json("/api/embodied-platform/collection-profiles")
        runs = self.get_json("/api/embodied-platform/collection-runs")
        attempts = self.get_json("/api/embodied-platform/collection-attempts")
        audits = self.get_json("/api/embodied-platform/audit-events")
        if [profile["id"] for profile in profiles] != ["first_person_trial_v1"]:
            self.report.failures.append(f"step {step} {label}: unexpected profiles {profiles}")
            return

        profile = profiles[0]
        task_by_id = {task["task_id"]: task for task in profile["tasks"]}
        run_by_id = {run["id"]: run for run in runs}
        attempt_keys: set[tuple[str, str, int]] = set()
        for attempt in attempts:
            key = (attempt["run_id"], attempt["task_id"], attempt["attempt_index"])
            if key in attempt_keys:
                self.report.failures.append(f"step {step} {label}: duplicate attempt identity {key}")
            attempt_keys.add(key)
            if attempt["run_id"] not in run_by_id:
                self.report.failures.append(f"step {step} {label}: orphan attempt {attempt['id']}")
                continue
            task = task_by_id.get(attempt["task_id"])
            if not task:
                self.report.failures.append(f"step {step} {label}: unknown task on attempt {attempt['id']}")
                continue
            if attempt["attempt_index"] > task["max_attempts"]:
                self.report.failures.append(f"step {step} {label}: attempt over max {attempt['id']}")
            if attempt["status"] == "deleted" and not attempt["deleted"]:
                self.report.failures.append(f"step {step} {label}: deleted attempt flag missing {attempt['id']}")

        for run in runs:
            progress = self.get_json(f"/api/embodied-platform/collection-runs/{run['id']}/progress")
            expected = self.expected_progress(profile, run, attempts)
            if progress != expected:
                self.report.failures.append(
                    f"step {step} {label}: progress mismatch for {run['id']} expected={expected} actual={progress}"
                )
            if run["status"] != progress["status"]:
                self.report.failures.append(
                    f"step {step} {label}: run {run['id']} status {run['status']} != progress {progress['status']}"
                )
        if len(audits) < len([entry for entry in self.report.entries if entry.actual_status == 200]):
            self.report.failures.append(f"step {step} {label}: audit log shorter than successful writes")

    def expected_progress(
        self,
        profile: dict[str, Any],
        run: dict[str, Any],
        attempts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        tasks = []
        run_attempts = [attempt for attempt in attempts if attempt["run_id"] == run["id"]]
        for task in profile["tasks"]:
            task_attempts = [attempt for attempt in run_attempts if attempt["task_id"] == task["task_id"]]
            attempt_count = len(task_attempts)
            uploaded_count = sum(1 for attempt in task_attempts if attempt["status"] in ATTEMPT_UPLOADED_STATUSES)
            accepted_count = sum(1 for attempt in task_attempts if attempt["status"] == "accepted")
            remaining_attempts = max(0, task["max_attempts"] - attempt_count)
            if accepted_count >= task["required_uploads"]:
                status = "passed"
            elif uploaded_count >= task["required_uploads"]:
                status = "ready_for_review"
            elif remaining_attempts == 0:
                status = "blocked"
            else:
                status = "collecting"
            tasks.append({
                "task_id": task["task_id"],
                "status": status,
                "attempt_count": attempt_count,
                "uploaded_count": uploaded_count,
                "accepted_count": accepted_count,
                "remaining_attempts": remaining_attempts,
                "required_uploads": task["required_uploads"],
                "max_attempts": task["max_attempts"],
            })

        blocked_task_count = sum(1 for task in tasks if task["status"] == "blocked")
        ready_task_count = sum(1 for task in tasks if task["status"] in {"ready_for_review", "passed"})
        completed_task_count = sum(1 for task in tasks if task["status"] == "passed")
        if blocked_task_count:
            status = "blocked"
        elif completed_task_count == profile["task_count_required"]:
            status = "passed"
        elif ready_task_count == profile["task_count_required"]:
            status = "ready_for_review"
        else:
            status = "collecting"
        return {
            "run_id": run["id"],
            "profile_id": profile["id"],
            "status": status,
            "completed_task_count": completed_task_count,
            "ready_task_count": ready_task_count,
            "blocked_task_count": blocked_task_count,
            "tasks": tasks,
        }

    def random_run(self) -> dict[str, Any] | None:
        runs = self.get_json("/api/embodied-platform/collection-runs")
        if not runs:
            return None
        return self.rng.choice(runs)

    def random_attempt(self) -> dict[str, Any] | None:
        attempts = self.get_json("/api/embodied-platform/collection-attempts")
        if not attempts:
            return None
        return self.rng.choice(attempts)


def valid_run_payload(rng: random.Random) -> dict[str, str]:
    suffix = rng.randrange(100000, 999999)
    return {
        "profile_id": "first_person_trial_v1",
        "subject_id": f"subject-{suffix}",
        "assignee": f"collector-{suffix % 17}",
    }


def register_payload(rng: random.Random, run: dict[str, Any], force_duplicate: bool = False) -> dict[str, Any]:
    task_id = rng.choice(TASK_IDS)
    existing = []
    if force_duplicate:
        existing = [1]
    attempt_index = rng.choice(existing) if existing else rng.randrange(1, 9)
    return {
        "task_id": task_id,
        "attempt_index": attempt_index,
        "video_uri": f"file:///adversarial/{run['id']}/{task_id}/{attempt_index}-{rng.randrange(1000)}.mp4",
        "duration_seconds": round(rng.uniform(1, 300), 2),
        "frame_count": rng.randrange(1, 9000),
        "status": rng.choice(["uploaded", "recorded", "draft"]),
        "transcript": rng.choice(["操作开始。操作结束，任务成功。", "任务名称：随机试采。正在执行动作。", ""]),
    }


def create_valid_run(world: CollectionWorld, step: int) -> None:
    world.post(
        step=step,
        agent="collector",
        action="create_valid_run",
        path="/api/embodied-platform/collection-runs",
        payload=valid_run_payload(world.rng),
        headers=world.headers("annotator", "collector-a"),
        expected_status=200,
    )


def create_invalid_profile_run(world: CollectionWorld, step: int) -> None:
    payload = valid_run_payload(world.rng)
    payload["profile_id"] = "profile_does_not_exist"
    world.post(
        step=step,
        agent="breaker",
        action="create_invalid_profile_run",
        path="/api/embodied-platform/collection-runs",
        payload=payload,
        headers=world.headers("annotator", "collector-a"),
        expected_status=404,
    )


def create_forged_run(world: CollectionWorld, step: int) -> None:
    world.post(
        step=step,
        agent="breaker",
        action="create_forged_run",
        path="/api/embodied-platform/collection-runs",
        payload=valid_run_payload(world.rng),
        headers={"X-Embodied-Role": "admin", "X-Embodied-Actor": "forged", "X-Embodied-Signature": "bad"},
        expected_status=403,
    )


def register_valid_attempt(world: CollectionWorld, step: int) -> None:
    run = world.random_run()
    if run is None:
        create_valid_run(world, step)
        return
    attempts = world.get_json("/api/embodied-platform/collection-attempts")
    used = {
        (attempt["task_id"], attempt["attempt_index"])
        for attempt in attempts
        if attempt["run_id"] == run["id"]
    }
    available = [
        (task_id, index)
        for task_id in TASK_IDS
        for index in range(1, 9)
        if (task_id, index) not in used
    ]
    if not available:
        return
    task_id, attempt_index = world.rng.choice(available)
    payload = {
        "task_id": task_id,
        "attempt_index": attempt_index,
        "video_uri": f"file:///adversarial/{run['id']}/{task_id}/attempt-{attempt_index}.mp4",
        "duration_seconds": round(world.rng.uniform(1, 300), 2),
        "frame_count": world.rng.randrange(1, 9000),
        "status": world.rng.choice(["uploaded", "recorded", "draft"]),
        "transcript": world.rng.choice(["操作开始。操作结束，任务成功。", "任务名称：随机试采。正在执行动作。", ""]),
    }
    world.post(
        step=step,
        agent="collector",
        action="register_valid_attempt",
        path=f"/api/embodied-platform/collection-runs/{run['id']}/attempts",
        payload=payload,
        headers=world.headers("annotator", "collector-a"),
        expected_status=200,
    )


def register_duplicate_attempt(world: CollectionWorld, step: int) -> None:
    attempt = world.random_attempt()
    if attempt is None:
        register_valid_attempt(world, step)
        return
    payload = {
        "task_id": attempt["task_id"],
        "attempt_index": attempt["attempt_index"],
        "video_uri": f"file:///adversarial/duplicate/{attempt['id']}.mp4",
        "duration_seconds": 12.0,
        "frame_count": 360,
        "status": "uploaded",
    }
    world.post(
        step=step,
        agent="breaker",
        action="register_duplicate_attempt",
        path=f"/api/embodied-platform/collection-runs/{attempt['run_id']}/attempts",
        payload=payload,
        headers=world.headers("annotator", "collector-a"),
        expected_status=409,
    )


def register_unknown_task(world: CollectionWorld, step: int) -> None:
    run = world.random_run()
    if run is None:
        create_valid_run(world, step)
        return
    payload = {
        "task_id": "task_99",
        "attempt_index": 1,
        "video_uri": f"file:///adversarial/{run['id']}/unknown.mp4",
        "duration_seconds": 10.0,
        "frame_count": 300,
        "status": "uploaded",
    }
    world.post(
        step=step,
        agent="breaker",
        action="register_unknown_task",
        path=f"/api/embodied-platform/collection-runs/{run['id']}/attempts",
        payload=payload,
        headers=world.headers("annotator", "collector-a"),
        expected_status=422,
    )


def register_over_limit_attempt(world: CollectionWorld, step: int) -> None:
    run = world.random_run()
    if run is None:
        create_valid_run(world, step)
        return
    payload = {
        "task_id": world.rng.choice(TASK_IDS),
        "attempt_index": 9,
        "video_uri": f"file:///adversarial/{run['id']}/over-limit.mp4",
        "duration_seconds": 10.0,
        "frame_count": 300,
        "status": "uploaded",
    }
    world.post(
        step=step,
        agent="breaker",
        action="register_over_limit_attempt",
        path=f"/api/embodied-platform/collection-runs/{run['id']}/attempts",
        payload=payload,
        headers=world.headers("annotator", "collector-a"),
        expected_status=422,
    )


def review_valid_attempt(world: CollectionWorld, step: int) -> None:
    attempt = world.random_attempt()
    if attempt is None:
        register_valid_attempt(world, step)
        return
    issue_codes = world.rng.sample(ISSUE_CODES, k=world.rng.randrange(0, 3))
    payload = {
        "decision": world.rng.choice(["accept", "reject", "needs_rework"]),
        "check_results": [
            {"check_id": f"issue.{code}", "result": "fail", "note": "seeded adversarial check"}
            for code in issue_codes
        ],
        "issue_codes": issue_codes,
        "notes": f"seeded review {step}",
    }
    world.patch(
        step=step,
        agent="reviewer",
        action="review_valid_attempt",
        path=f"/api/embodied-platform/collection-attempts/{attempt['id']}/review",
        payload=payload,
        headers=world.headers("reviewer", "reviewer-a"),
        expected_status=200,
    )


def review_unknown_issue(world: CollectionWorld, step: int) -> None:
    attempt = world.random_attempt()
    if attempt is None:
        register_valid_attempt(world, step)
        return
    payload = {
        "decision": "reject",
        "check_results": [{"check_id": "issue.not_real", "result": "fail", "note": ""}],
        "issue_codes": ["not_a_real_issue"],
        "notes": "",
    }
    world.patch(
        step=step,
        agent="breaker",
        action="review_unknown_issue",
        path=f"/api/embodied-platform/collection-attempts/{attempt['id']}/review",
        payload=payload,
        headers=world.headers("reviewer", "reviewer-a"),
        expected_status=422,
    )


def review_forged_attempt(world: CollectionWorld, step: int) -> None:
    attempt = world.random_attempt()
    if attempt is None:
        register_valid_attempt(world, step)
        return
    payload = {
        "decision": "accept",
        "check_results": [],
        "issue_codes": [],
        "notes": "",
    }
    world.patch(
        step=step,
        agent="breaker",
        action="review_forged_attempt",
        path=f"/api/embodied-platform/collection-attempts/{attempt['id']}/review",
        payload=payload,
        headers={"X-Embodied-Role": "reviewer", "X-Embodied-Actor": "forged", "X-Embodied-Signature": "bad"},
        expected_status=403,
    )


Action = Callable[[CollectionWorld, int], None]


WEIGHTED_ACTIONS: list[Action] = [
    create_valid_run,
    create_valid_run,
    register_valid_attempt,
    register_valid_attempt,
    register_valid_attempt,
    review_valid_attempt,
    review_valid_attempt,
    register_duplicate_attempt,
    register_unknown_task,
    register_over_limit_attempt,
    review_unknown_issue,
    create_invalid_profile_run,
    create_forged_run,
    review_forged_attempt,
]


def run_collection_adversarial_agents(client: TestClient, *, seed: int, steps: int) -> AgentReport:
    world = CollectionWorld(client, seed, steps)
    world.check_invariants(0, "initial")
    create_valid_run(world, 1)
    register_valid_attempt(world, 2)
    review_valid_attempt(world, 3)
    for step in range(4, steps + 1):
        if world.report.failures:
            break
        action = world.rng.choice(WEIGHTED_ACTIONS)
        action(world, step)
    return world.report
