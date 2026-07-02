"""Security/robustness hardening tests ported from the codex/embodied-platform branch.

Pins the hardened behavior of the platform auth + read paths:
- injective HMAC principal encoding (no actor/role delimiter collisions),
- authenticate-before-authorize (no role-set probing without a valid signature),
- non-finite float (Infinity/NaN) in event payloads rejected as 422 not 500,
- bytes-based hmac.compare_digest (non-ASCII input -> 401/403, never 500),
- NaN-safe RequestValidationError handler (422 bodies stay spec JSON),
- partial-merge PATCH /system/settings with repair-on-read,
- validated list reads that drop malformed persisted rows instead of 500ing.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


LOGIN_PASSCODE = "pytest-login-passcode"


def _client(
    tmp_path,
    monkeypatch,
    *,
    raise_server_exceptions: bool = True,
) -> TestClient:
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_AUTH_SECRET", "pytest-embodied-platform-secret")
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_LOGIN_PASSCODE", LOGIN_PASSCODE)
    from api.embodied_platform.routes import register_validation_handlers, router

    app = FastAPI()
    app.include_router(router)
    # Mirror production wiring (api/main.py) so the NaN-safe validation-error
    # handler is exercised in tests too — handlers are app-level, not router-level.
    register_validation_handlers(app)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _no_raise_client(tmp_path, monkeypatch) -> TestClient:
    """Same wiring as ``_client`` but with ``raise_server_exceptions=False`` so an
    unhandled 500 surfaces as a 500 *response* the test can assert on, instead of
    re-raising inside the test process. Used by the 500-guard tests below."""
    return _client(tmp_path, monkeypatch, raise_server_exceptions=False)


def _headers(role: str, actor: str) -> dict[str, str]:
    from api.embodied_platform.routes import sign_principal

    return {
        "X-Embodied-Role": role,
        "X-Embodied-Actor": actor,
        "X-Embodied-Signature": sign_principal(actor, role),
    }


def _admin_headers() -> dict[str, str]:
    return _headers("admin", "pytest-admin")


def _ml_headers() -> dict[str, str]:
    return _headers("ml_engineer", "pytest-ml")


def _annotator_headers() -> dict[str, str]:
    return _headers("annotator", "labeler-a")


def _create_dataset(client: TestClient, name: str = "warehouse-pick-v1") -> dict:
    response = client.post(
        "/api/embodied-platform/datasets",
        headers=_admin_headers(),
        json={
            "name": name,
            "modality": "vision_language_action",
            "robot_type": "mobile_manipulator",
            "storage_uri": f"file:///datasets/{name}",
            "description": "Pick and place episodes from demo fixtures.",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_episode(client: TestClient, dataset_id: str, episode_id: str = "episode-000042") -> dict:
    response = client.post(
        "/api/embodied-platform/episodes",
        headers=_admin_headers(),
        json={
            "dataset_id": dataset_id,
            "episode_id": episode_id,
            "robot_cell": "warehouse-a",
            "frame_count": 240,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _corrupt_state_client(tmp_path, monkeypatch, mutate) -> TestClient:
    """Build a client whose persisted state has been corrupted via ``mutate``
    (a callable taking the state dict). Plants the corruption through the public
    repository surface (``get_repository().write``) — bypassing schema validation
    but staying backend-agnostic, so the same corrupt-persisted-data scenario is
    exercised in both JSON-file and Postgres mode."""
    # Build the client first: it monkeypatches the env that selects/locates the
    # repository backend before the corrupt state is written through it.
    client = _client(tmp_path, monkeypatch, raise_server_exceptions=False)
    from api.embodied_platform.repository import get_repository

    state: dict = {}
    mutate(state)
    get_repository().write(state)
    return client


def test_principal_signature_encoding_is_injective(tmp_path, monkeypatch):
    """The signed (actor, role) message must be injective: a delimiter in one
    field must not let a different (actor, role) pair collide to the same HMAC."""
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_AUTH_SECRET", "pytest-embodied-platform-secret")
    from api.embodied_platform.routes import sign_principal

    assert sign_principal("a", "b:c") != sign_principal("a:b", "c")


def test_forged_signature_with_forbidden_role_reports_invalid_signature(tmp_path, monkeypatch):
    """Authenticate-before-authorize. A forged signature combined with a
    forbidden role must fail on the SIGNATURE (403 'invalid ... signature'), not
    leak the allowed-role set via the role-list message."""
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/embodied-platform/training-jobs",
        headers={
            "X-Embodied-Role": "viewer",  # not an ml_actor role
            "X-Embodied-Actor": "attacker",
            "X-Embodied-Signature": "forged",
        },
        json={
            "name": "policy-run",
            "dataset_id": "ds-x",
            "base_model": "base",
            "optimizer": "lora",
        },
    )
    assert response.status_code == 403, response.text
    detail = response.json()["detail"]
    assert "signature" in detail, detail
    assert "requires one of" not in detail, detail


def test_non_ascii_signature_header_is_403_not_500(tmp_path, monkeypatch):
    """A non-ASCII (latin-1) signature header must yield 403, never a 500
    from hmac.compare_digest raising TypeError on non-ASCII str operands."""
    client = _client(tmp_path, monkeypatch)

    # httpx encodes str header values as ASCII (would raise client-side), so the
    # raw 0xE9 byte is sent as bytes — exactly the on-the-wire obs-text Starlette
    # decodes to the non-ASCII str 'é' that the route's compare_digest chokes on.
    response = client.post(
        "/api/embodied-platform/audit-events",
        headers={
            "X-Embodied-Role": b"admin",
            "X-Embodied-Actor": b"attacker",
            # Pre-fix compare_digest(str, str) raised TypeError on this -> 500.
            "X-Embodied-Signature": b"\xe9",
        },
        json={"action": "probe", "resource": "audit", "detail": None},
    )
    assert response.status_code == 403, response.text


def test_session_non_ascii_passcode_is_unauthorized_not_500(tmp_path, monkeypatch):
    """A non-ASCII passcode must compare safely (bytes) -> 401, never a 500.

    Why it matters: hmac.compare_digest rejects non-ASCII str operands with a
    TypeError, which an unauthenticated caller could trip to DoS the login path.
    """
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/embodied-platform/session",
        json={"actor": "a", "role": "admin", "passcode": "café"},
    )
    assert response.status_code == 401, response.text


def test_annotation_confidence_nan_is_rejected_422_not_500(tmp_path, monkeypatch):
    """NaN confidence must be a clean 422; it must never reach json.dumps in the
    error body (which crashes the default validation handler -> 500)."""
    client = _client(tmp_path, monkeypatch)
    dataset = _create_dataset(client)
    _create_episode(client, dataset["id"])

    for token in ("NaN", "Infinity", "-Infinity"):
        response = client.post(
            "/api/embodied-platform/annotation-tasks",
            headers={**_annotator_headers(), "Content-Type": "application/json"},
            content=(
                '{"dataset_id":"%s","episode_id":"episode-000042",'
                '"task_type":"trajectory_segment","assignee":"x",'
                '"labels":[{"start_frame":0,"end_frame":2,"skill_id":"s","confidence":%s}]}'
                % (dataset["id"], token)
            ),
        )
        assert response.status_code == 422, f"{token}: {response.status_code} {response.text}"
        # The error body itself must be valid JSON (no bare NaN tokens leaked).
        assert response.json()["detail"]


def test_system_settings_patch_is_partial_merge(tmp_path, monkeypatch):
    """PATCH /system/settings must be a PARTIAL MERGE — unspecified fields
    keep their current persisted value rather than reverting to schema defaults.
    The merged result is still validated (out-of-range field -> 422)."""
    client = _client(tmp_path, monkeypatch)

    # Establish a non-default full settings state.
    full = client.patch(
        "/api/embodied-platform/system/settings",
        headers=_admin_headers(),
        json={
            "retention_days": 99,
            "offline_mode": False,
            "active_robot_fleet": "fleetZ",
            "approval_required_for_edge": False,
        },
    )
    assert full.status_code == 200, full.text

    # Partial PATCH touching only retention_days must preserve the other three.
    partial = client.patch(
        "/api/embodied-platform/system/settings",
        headers=_admin_headers(),
        json={"retention_days": 7},
    )
    assert partial.status_code == 200, partial.text

    settings = client.get("/api/embodied-platform/system/settings").json()
    assert settings["retention_days"] == 7
    assert settings["offline_mode"] is False  # preserved, not reverted to True default
    assert settings["active_robot_fleet"] == "fleetZ"  # preserved
    assert settings["approval_required_for_edge"] is False  # preserved

    # The merged result is still validated: an out-of-range value -> 422 (not 500).
    bad = client.patch(
        "/api/embodied-platform/system/settings",
        headers=_admin_headers(),
        json={"retention_days": 99999},
    )
    assert bad.status_code == 422, bad.text
    # The rejected PATCH did not mutate persisted state.
    assert client.get("/api/embodied-platform/system/settings").json()["retention_days"] == 7


def test_system_settings_patch_remains_admin_only(tmp_path, monkeypatch):
    """The partial-merge change must keep admin-only RBAC."""
    client = _client(tmp_path, monkeypatch)
    denied = client.patch(
        "/api/embodied-platform/system/settings",
        headers=_ml_headers(),
        json={"retention_days": 7},
    )
    assert denied.status_code == 403, denied.text


def test_patch_settings_with_explicit_null_field_is_422_not_500(tmp_path, monkeypatch):
    """PATCH /system/settings with an explicit null on a non-nullable
    setting must be a clean 422, not a 500 from SystemSettings.model_validate
    choking on a None merged into a required field."""
    client = _no_raise_client(tmp_path, monkeypatch)
    response = client.patch(
        "/api/embodied-platform/system/settings",
        headers=_admin_headers(),
        json={"retention_days": None},
    )
    assert response.status_code == 422, response.text

    # A null on the bool / str fields is likewise a 422, never a 500.
    for field in ("offline_mode", "active_robot_fleet", "approval_required_for_edge"):
        resp = client.patch(
            "/api/embodied-platform/system/settings",
            headers=_admin_headers(),
            json={field: None},
        )
        assert resp.status_code == 422, (field, resp.text)


def test_patch_settings_partial_merge_still_works_after_null_guard(tmp_path, monkeypatch):
    """The null guard must not break the legitimate partial-merge path: a single
    provided non-null field updates only that field and 200s (omitted fields keep
    their current value)."""
    client = _client(tmp_path, monkeypatch)
    before = client.get("/api/embodied-platform/system/settings").json()

    response = client.patch(
        "/api/embodied-platform/system/settings",
        headers=_admin_headers(),
        json={"retention_days": 45},
    )
    assert response.status_code == 200, response.text
    merged = response.json()
    assert merged["retention_days"] == 45
    # Omitted fields kept their prior value (PATCH semantics).
    assert merged["active_robot_fleet"] == before["active_robot_fleet"]
    assert merged["offline_mode"] == before["offline_mode"]


def test_system_settings_get_and_patch_survive_corrupt_persisted_blob(tmp_path, monkeypatch):
    """A schema-violating persisted system_settings blob must NOT 500 the GET
    AND must NOT 500 the PATCH (PATCH validated the stored blob before it could
    self-heal, leaving it unrepairable via the API). Repair-on-read falls back to
    valid SystemSettings defaults: GET returns a valid 200, and a PATCH overwrites
    the corrupt blob and 200s — restoring API repairability."""
    def _corrupt(state):
        # retention_days far outside [1, 3650]; offline_mode a string, not a bool.
        state["system_settings"] = {"retention_days": 999999, "offline_mode": "nope"}

    client = _corrupt_state_client(tmp_path, monkeypatch, _corrupt)

    got = client.get("/api/embodied-platform/system/settings")
    assert got.status_code == 200, got.text
    # Repaired to defaults rather than echoing the out-of-range corrupt value.
    assert got.json()["retention_days"] == 30

    patched = client.patch(
        "/api/embodied-platform/system/settings",
        headers=_admin_headers(),
        json={"retention_days": 60},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["retention_days"] == 60


def test_id_less_persisted_row_is_404_not_500_and_excluded_from_list(tmp_path, monkeypatch):
    """An id-less persisted row (out-of-band corruption) must not 500 the
    status-PATCH (a raw item['id'] subscript would KeyError) nor the list-GET
    (response_model rejects the malformed row). The status-PATCH must fall through
    to a clean 404 (item.get('id') never matches), and the list-GET must drop the
    malformed row and 200 with the healthy rows — never expose the whole list as a
    500."""
    def _corrupt(state):
        # Two learning-queue rows: one healthy, one missing its 'id'.
        state["learning_queue"] = [
            {
                "id": "learn-ok",
                "episode_id": "episode-corrupt",
                "reason": "ok row",
                "priority": "normal",
                "status": "queued",
                "created_at": "2026-05-30T00:00:00+00:00",
                "updated_at": "2026-05-30T00:00:00+00:00",
            },
            {
                # No 'id' key at all.
                "episode_id": "episode-corrupt",
                "reason": "id-less row",
                "priority": "normal",
                "status": "queued",
                "created_at": "2026-05-30T00:00:00+00:00",
                "updated_at": "2026-05-30T00:00:00+00:00",
            },
        ]

    client = _corrupt_state_client(tmp_path, monkeypatch, _corrupt)

    # PATCH targeting a non-existent id must be a clean 404, never a KeyError 500.
    patched = client.patch(
        "/api/embodied-platform/learning-queue/no-such-id/status",
        headers=_ml_headers(),
        json={"status": "running"},
    )
    assert patched.status_code == 404, patched.text

    # The list drops the malformed (id-less) row and 200s with the healthy one.
    listed = client.get("/api/embodied-platform/learning-queue")
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == ["learn-ok"]


# ---------------------------------------------------------------------------
# Non-finite float (Infinity / NaN) in event payloads → 422, never 500
# ---------------------------------------------------------------------------

def _event_client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_DATA_ROOT", str(tmp_path))
    from api.main import app
    return TestClient(app, raise_server_exceptions=False)


_TELEMETRY_TEMPLATE = (
    '{{"events":[{{"event_id":"00000000-0000-0000-0000-000000000001",'
    '"session_id":"00000000-0000-0000-0000-000000000002",'
    '"annotator_id":"00000000-0000-0000-0000-000000000003",'
    '"ts_client":"2026-01-01T00:00:00Z","schema_version":1,'
    '"payload":{{"event_type":"viewport.changed","zoom":1.0,'
    '"pan_x":{pan_x},"pan_y":{pan_y},'
    '"viewport_rect":[0,0,100,100]}}}}]}}'
)


def test_telemetry_event_inf_pan_x_is_422_not_500(tmp_path, monkeypatch):
    """pan_x: Infinity must be rejected at the Pydantic boundary (422).
    Before the fix, it passed validation and crashed json.dump(allow_nan=False)
    in the repository as an unhandled ValueError → 500."""
    client = _event_client(tmp_path, monkeypatch)
    response = client.post(
        "/v1/events/telemetry",
        content=_TELEMETRY_TEMPLATE.format(pan_x="Infinity", pan_y="0.0"),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, f"expected 422, got {response.status_code}: {response.text}"


def test_telemetry_event_nan_pan_y_is_422_not_500(tmp_path, monkeypatch):
    """pan_y: NaN must be rejected at the Pydantic boundary (422).
    Before the fix, NaN comparisons were undefined and the value passed
    validation, then crashed the serialization layer → 500."""
    client = _event_client(tmp_path, monkeypatch)
    response = client.post(
        "/v1/events/telemetry",
        content=_TELEMETRY_TEMPLATE.format(pan_x="0.0", pan_y="NaN"),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, f"expected 422, got {response.status_code}: {response.text}"


def test_label_event_bbox_inf_width_is_422_not_500(tmp_path, monkeypatch):
    """BBoxGeometry with width: Infinity must be rejected at the Pydantic
    boundary (422). gt=0 evaluates to True for +inf, so without allow_inf_nan=False
    the value passed validation and crashed json.dump(allow_nan=False) → 500."""
    client = _event_client(tmp_path, monkeypatch)
    response = client.post(
        "/v1/events/label",
        content=(
            '{"events":[{"event_id":"00000000-0000-0000-0000-000000000001",'
            '"task_id":"00000000-0000-0000-0000-000000000002",'
            '"annotator_id":"00000000-0000-0000-0000-000000000003",'
            '"ts_client":"2026-01-01T00:00:00Z","schema_version":1,'
            '"payload":{"event_type":"object.created",'
            '"client_object_id":"00000000-0000-0000-0000-000000000004",'
            '"class_id":"00000000-0000-0000-0000-000000000005",'
            '"geometry":{"shape":"bbox","x":0,"y":0,"width":Infinity,"height":1},'
            '"origin":"human","drawn_with":"mouse"}}]}'
        ),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, f"expected 422, got {response.status_code}: {response.text}"


# ---------------------------------------------------------------------------
# Non-finite floats in free-form attributes payloads → 422 (bypass guard)
# ---------------------------------------------------------------------------
#
# ObjectCreatedPayload.attributes and AttributeChangedPayload.attributes are
# dict[str, Any] — the field-level _reject_nul only sees a dict, not the floats
# inside it.  Without the recursive require_finite_numbers validator a client
# could smuggle NaN / Infinity through attributes and still crash the storage
# backends (json.dump(allow_nan=False) → ValueError → 500).

_LABEL_TEMPLATE = (
    '{{"events":[{{"event_id":"00000000-0000-0000-0000-000000000001",'
    '"task_id":"00000000-0000-0000-0000-000000000002",'
    '"annotator_id":"00000000-0000-0000-0000-000000000003",'
    '"ts_client":"2026-01-01T00:00:00Z","schema_version":1,'
    '"payload":{payload}}}]}}'
)

_OBJECT_CREATED_PAYLOAD = (
    '"event_type":"object.created",'
    '"client_object_id":"00000000-0000-0000-0000-000000000004",'
    '"class_id":"00000000-0000-0000-0000-000000000005",'
    '"geometry":{"shape":"bbox","x":0,"y":0,"width":1,"height":1},'
    '"origin":"human","drawn_with":"mouse"'
)

_ATTR_CHANGED_PAYLOAD = (
    '"event_type":"attribute.changed",'
    '"client_object_id":"00000000-0000-0000-0000-000000000004"'
)


def _label_event_body(payload_fields: str) -> str:
    """Build a /v1/events/label JSON body by splicing *payload_fields* inside the
    payload object."""
    return _LABEL_TEMPLATE.format(payload="{" + payload_fields + "}")


def test_object_created_attributes_top_level_nan_is_422(tmp_path, monkeypatch):
    """NaN at the top level of ObjectCreatedPayload.attributes → 422."""
    client = _event_client(tmp_path, monkeypatch)
    payload = _OBJECT_CREATED_PAYLOAD + ',"attributes":{"score":NaN}'
    response = client.post(
        "/v1/events/label",
        content=_label_event_body(payload),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, f"expected 422, got {response.status_code}: {response.text}"


def test_object_created_attributes_top_level_infinity_is_422(tmp_path, monkeypatch):
    """Infinity at the top level of ObjectCreatedPayload.attributes → 422."""
    client = _event_client(tmp_path, monkeypatch)
    payload = _OBJECT_CREATED_PAYLOAD + ',"attributes":{"confidence":Infinity}'
    response = client.post(
        "/v1/events/label",
        content=_label_event_body(payload),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, f"expected 422, got {response.status_code}: {response.text}"


def test_object_created_attributes_top_level_neg_infinity_is_422(tmp_path, monkeypatch):
    """-Infinity at the top level of ObjectCreatedPayload.attributes → 422."""
    client = _event_client(tmp_path, monkeypatch)
    payload = _OBJECT_CREATED_PAYLOAD + ',"attributes":{"score":-Infinity}'
    response = client.post(
        "/v1/events/label",
        content=_label_event_body(payload),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, f"expected 422, got {response.status_code}: {response.text}"


def test_object_created_attributes_nested_list_nan_is_422(tmp_path, monkeypatch):
    """NaN buried inside a list inside ObjectCreatedPayload.attributes → 422."""
    client = _event_client(tmp_path, monkeypatch)
    payload = _OBJECT_CREATED_PAYLOAD + ',"attributes":{"scores":[0.9,NaN,0.8]}'
    response = client.post(
        "/v1/events/label",
        content=_label_event_body(payload),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, f"expected 422, got {response.status_code}: {response.text}"


def test_object_created_attributes_nested_dict_nan_is_422(tmp_path, monkeypatch):
    """NaN buried inside a nested dict inside ObjectCreatedPayload.attributes → 422."""
    client = _event_client(tmp_path, monkeypatch)
    payload = _OBJECT_CREATED_PAYLOAD + ',"attributes":{"meta":{"score":NaN}}'
    response = client.post(
        "/v1/events/label",
        content=_label_event_body(payload),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, f"expected 422, got {response.status_code}: {response.text}"


def test_object_created_attributes_deeply_nested_nan_is_422(tmp_path, monkeypatch):
    """NaN buried in a list inside a dict inside attributes → 422 (deep traversal)."""
    client = _event_client(tmp_path, monkeypatch)
    payload = _OBJECT_CREATED_PAYLOAD + ',"attributes":{"results":[{"v":1.0},{"v":NaN}]}'
    response = client.post(
        "/v1/events/label",
        content=_label_event_body(payload),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, f"expected 422, got {response.status_code}: {response.text}"


def test_attribute_changed_top_level_nan_is_422(tmp_path, monkeypatch):
    """NaN at the top level of AttributeChangedPayload.attributes → 422."""
    client = _event_client(tmp_path, monkeypatch)
    payload = _ATTR_CHANGED_PAYLOAD + ',"attributes":{"score":NaN}'
    response = client.post(
        "/v1/events/label",
        content=_label_event_body(payload),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, f"expected 422, got {response.status_code}: {response.text}"


def test_attribute_changed_nested_infinity_is_422(tmp_path, monkeypatch):
    """Infinity nested inside AttributeChangedPayload.attributes → 422."""
    client = _event_client(tmp_path, monkeypatch)
    payload = _ATTR_CHANGED_PAYLOAD + ',"attributes":{"metrics":{"iou":Infinity}}'
    response = client.post(
        "/v1/events/label",
        content=_label_event_body(payload),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, f"expected 422, got {response.status_code}: {response.text}"


def test_object_created_attributes_with_finite_values_succeeds(tmp_path, monkeypatch):
    """Attributes with only finite floats, ints, strings, and bools must pass
    validation (the recursive guard must not false-positive on valid payloads)."""
    client = _event_client(tmp_path, monkeypatch)
    payload = (
        _OBJECT_CREATED_PAYLOAD
        + ',"attributes":{"score":0.95,"count":3,"nested":{"iou":0.72},"tags":["a","b"]}'
    )
    response = client.post(
        "/v1/events/label",
        content=_label_event_body(payload),
        headers={"Content-Type": "application/json"},
    )
    # The label endpoint returns 200 even when events are rejected-by-dedup;
    # what matters is it didn't 422 (rejected by the recursive guard).
    assert response.status_code == 200, f"unexpected {response.status_code}: {response.text}"
