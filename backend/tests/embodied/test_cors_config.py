"""CORS allow-list is read from XINGJU_CORS_ORIGINS (comma-split)."""
from __future__ import annotations

import importlib


def _build_app(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("XINGJU_CORS_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("XINGJU_CORS_ORIGINS", value)
    import api.main as main
    importlib.reload(main)  # re-evaluate module-level CORS wiring under new env
    return main


def test_default_origins_when_env_unset(monkeypatch):
    main = _build_app(monkeypatch, None)
    assert main.CORS_ORIGINS == [
        "http://127.0.0.1:8099",
        "http://localhost:8099",
    ]


def test_origins_from_env_comma_split(monkeypatch):
    main = _build_app(monkeypatch, "https://a.example, https://b.example ,https://c.example")
    assert main.CORS_ORIGINS == [
        "https://a.example",
        "https://b.example",
        "https://c.example",
    ]


def test_empty_env_falls_back_to_default(monkeypatch):
    main = _build_app(monkeypatch, "   ")
    assert main.CORS_ORIGINS == [
        "http://127.0.0.1:8099",
        "http://localhost:8099",
    ]
