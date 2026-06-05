from __future__ import annotations

import logging
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from calango import __version__

logger = logging.getLogger(__name__)


class CalangoMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = str(uuid4())
        request.state.request_id = request_id

        try:
            response: Response = await call_next(request)
        except Exception:
            logger.exception("Unhandled exception for request %s", request_id)
            response = JSONResponse(
                status_code=500,
                content={
                    "error": "internal_server_error",
                    "message": "An unexpected error occurred.",
                    "request_id": request_id,
                },
            )

        response.headers["x-request-id"] = request_id
        response.headers["x-calango-version"] = __version__
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["x-frame-options"] = "DENY"
        response.headers["strict-transport-security"] = "max-age=31536000; includeSubDomains"
        response.headers["referrer-policy"] = "strict-origin-when-cross-origin"

        return response
