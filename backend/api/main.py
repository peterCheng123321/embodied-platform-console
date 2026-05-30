"""Standalone FastAPI entrypoint for the Embodied Platform Console.

Serves the JSON-file-backed embodied-platform API AND the single-page app from the
same origin (so the SPA's root-relative /api calls work without a proxy):

    GET  /app/                         -> the operations console SPA
    *    /api/embodied-platform/...     -> the platform API
    GET  /healthz                       -> liveness

No database: the platform persists to an atomic, file-locked JSON store
(see api/embodied_platform/repository.py), so this runs with zero infrastructure.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .embodied_platform.routes import router as embodied_platform_router

logger = logging.getLogger(__name__)

app = FastAPI(title="Embodied Platform Console", version="0.1.0")

# Dev convenience: allow the SPA to be served from a separate static server during
# development. In the bundled run script the SPA is same-origin, so this is only
# exercised when you point a standalone static server at apps/embodied-platform.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:8099",
        "http://localhost:8099",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(embodied_platform_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


# Mount the SPA last so the API routes/healthz take precedence. Guard the mount so
# the app still imports/boots if the static directory is missing (e.g. in CI that
# only runs the API tests).
_SPA_DIR = Path(__file__).resolve().parents[2] / "apps" / "embodied-platform"
if _SPA_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=_SPA_DIR, html=True), name="embodied-platform-app")
else:  # pragma: no cover - defensive
    logger.warning("SPA directory not found at %s; /app not mounted", _SPA_DIR)
