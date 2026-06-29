"""App-level validation handlers for the embodied platform API."""
from __future__ import annotations

import math
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def _scrub_non_finite(value: Any) -> Any:
    """Recursively replace non-finite floats (NaN/Inf) with None.

    A bounded float field that rejects NaN still echoes the offending ``input``
    into the validation-error context; that nested NaN would crash
    ``JSONResponse.render`` (json.dumps(..., allow_nan=False)) -> 500. Scrubbing
    keeps the 422 error body spec-compliant JSON.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _scrub_non_finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub_non_finite(item) for item in value]
    return value


async def _validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    detail = _scrub_non_finite(jsonable_encoder(exc.errors()))
    return JSONResponse(status_code=422, content={"detail": detail})


def register_validation_handlers(app: FastAPI) -> None:
    """Register the NaN-safe RequestValidationError handler.

    Exception handlers are app-level (not router-level), so this must be called
    on the FastAPI app in production and tests.
    """
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
