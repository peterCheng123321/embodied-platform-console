"""Standalone FastAPI entrypoint for the Embodied Platform Console.

Serves the JSON-file-backed embodied-platform API AND the single-page app from the
same origin (so the SPA's root-relative /api calls work without a proxy):

    GET  /app/                         -> the operations console SPA
    GET  /labeler/                     -> the temporal segment labeler
    POST /v1/events/...                -> append-only annotation/telemetry ingest
    *    /api/embodied-platform/...     -> the platform API
    *    /api/embodied/...              -> temporal labeler compatibility API
    GET  /healthz                       -> liveness

No database: the platform persists to an atomic, file-locked JSON store
(see api/embodied_platform/repository.py), so this runs with zero infrastructure.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .embodied.routes import router as embodied_router
from .embodied_platform.event_routes import router as event_ingest_router
from .embodied_platform.routes import router as embodied_platform_router
from .embodied_platform.validation import (
    register_validation_handlers as register_embodied_platform_validation_handlers,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Embodied Platform Console", version="0.1.0")

_DEFAULT_CORS_ORIGINS = [
    "http://127.0.0.1:8099",
    "http://localhost:8099",
]


def _cors_origins() -> list[str]:
    raw = os.environ.get("XINGJU_CORS_ORIGINS", "")
    parsed = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return parsed or _DEFAULT_CORS_ORIGINS


CORS_ORIGINS = _cors_origins()

# Dev convenience: allow the SPA to be served from a separate static server during
# development. In the bundled run script the SPA is same-origin, so this is only
# exercised when you point a standalone static server at apps/embodied-platform.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Cross-origin labeler deploys need to READ the segments ETag for the
    # If-Match optimistic-concurrency handshake (same-origin reads it freely).
    expose_headers=["ETag"],
)

# Compress text assets (the labeler ships ~590 KB of uncompressed JS/CSS).
app.add_middleware(GZipMiddleware, minimum_size=1000)


# Cap declared request-body size as a coarse anti-disk-exhaustion guard (issue
# #2). This is defense-in-depth ONLY: a client can omit/forge Content-Length
# (e.g. chunked), so the load-bearing control is the per-field/per-list
# max_length on the parsed Pydantic models — this just rejects an obviously
# oversized write at the edge before it is parsed.
MAX_REQUEST_BODY_BYTES = 4 * 1024 * 1024  # 4 MiB


@app.middleware("http")
async def _limit_request_body(request: Request, call_next):
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            too_large = int(declared) > MAX_REQUEST_BODY_BYTES
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "invalid Content-Length"})
        if too_large:
            return JSONResponse(status_code=413, content={"detail": "request body too large"})
    return await call_next(request)

app.include_router(embodied_platform_router)
app.include_router(embodied_router)
app.include_router(event_ingest_router)

# NaN-safe RequestValidationError handler (exception handlers are app-level, not
# router-level, so the platform router cannot register this itself).
register_embodied_platform_validation_handlers(app)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root_redirect() -> RedirectResponse:
    """Bare origin lands on the operations console instead of a 404."""
    return RedirectResponse("/app/", status_code=307)


# Mount static apps last so the API routes/healthz take precedence. Guard each
# mount so API-only CI still imports cleanly when an app folder is absent.
_ROOT_DIR = Path(__file__).resolve().parents[2]
_SPA_DIR = _ROOT_DIR / "apps" / "embodied-platform"
_LABELER_DIR = _ROOT_DIR / "apps" / "embodied-labeler"
_LABELER_ASSETS_DIR = _LABELER_DIR / "assets" / "embodied"
_VENDOR_DIR = _ROOT_DIR / "apps" / "_vendor"


def _embodied_cache_dir() -> Path:
    return Path(
        os.environ.get(
            "XINGJU_EMBODIED_CACHE_ROOT",
            str(Path(__file__).resolve().parents[1] / "data" / "embodied_cache"),
        )
    )


_CACHE_DIR = _embodied_cache_dir()

app.mount(
    "/embodied-cache",
    StaticFiles(directory=str(_CACHE_DIR), check_dir=False),
    name="embodied-cache",
)
if _LABELER_ASSETS_DIR.is_dir():
    app.mount(
        "/embodied-assets",
        StaticFiles(directory=str(_LABELER_ASSETS_DIR), check_dir=False),
        name="embodied-assets",
    )
else:  # pragma: no cover - defensive
    logger.warning("Temporal labeler assets directory not found at %s; /embodied-assets not mounted", _LABELER_ASSETS_DIR)

if _LABELER_DIR.is_dir():
    app.mount("/labeler", StaticFiles(directory=_LABELER_DIR, html=True), name="embodied-labeler")
else:  # pragma: no cover - defensive
    logger.warning("Temporal labeler directory not found at %s; /labeler not mounted", _LABELER_DIR)

if _SPA_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=_SPA_DIR, html=True), name="embodied-platform-app")
else:  # pragma: no cover - defensive
    logger.warning("SPA directory not found at %s; /app not mounted", _SPA_DIR)

if _VENDOR_DIR.is_dir():
    app.mount("/vendor", StaticFiles(directory=_VENDOR_DIR), name="vendor")
else:  # pragma: no cover - defensive
    logger.warning("Vendored assets directory not found at %s; /vendor not mounted — run scripts/vendor-assets.sh", _VENDOR_DIR)
