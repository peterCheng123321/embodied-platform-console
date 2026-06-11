"""Seeded adversarial collection workflow tests."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from .adversarial_agents import run_collection_adversarial_agents


LOGIN_PASSCODE = "pytest-login-passcode"


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_AUTH_SECRET", "pytest-embodied-platform-secret")
    monkeypatch.setenv("XINGJU_EMBODIED_PLATFORM_LOGIN_PASSCODE", LOGIN_PASSCODE)
    from api.embodied_platform.routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_seeded_collection_agents_keep_backend_invariants(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    report = run_collection_adversarial_agents(client, seed=20260608, steps=120)

    assert report.failures == [], report.format_failures()
    assert report.seed == 20260608
    assert report.steps == 120
    assert report.successful_writes >= 20
    assert {"collector", "reviewer", "breaker"}.issubset(report.agents_seen)
    assert any(entry.expected_status >= 400 for entry in report.entries)
    assert any(entry.action == "register_valid_attempt" for entry in report.entries)
    assert any(entry.action == "review_valid_attempt" for entry in report.entries)


def test_seeded_collection_agents_are_replayable(tmp_path, monkeypatch):
    client_a = _client(tmp_path / "a", monkeypatch)
    report_a = run_collection_adversarial_agents(client_a, seed=8675309, steps=60)

    client_b = _client(tmp_path / "b", monkeypatch)
    report_b = run_collection_adversarial_agents(client_b, seed=8675309, steps=60)

    assert report_a.failures == [], report_a.format_failures()
    assert report_b.failures == [], report_b.format_failures()
    assert [entry.replay_key for entry in report_a.entries] == [entry.replay_key for entry in report_b.entries]
