from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from calango.exceptions import CalangoException

logger = logging.getLogger(__name__)


async def calango_exception_handler(request: Request, exc: CalangoException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.error_code,
            "message": exc.message,
            "request_id": request_id,
        },
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    logger.exception("Unhandled exception for request %s", request_id)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred.",
            "request_id": request_id,
        },
    )
