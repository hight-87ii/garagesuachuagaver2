"""Middleware chuyển hướng API phiên bản cũ sang /api/v1 (tương thích ngược)."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .core.config import API_PREFIX, API_VERSION

VERSIONED_PREFIX = f"{API_PREFIX}/{API_VERSION}"


class ApiVersionMiddleware(BaseHTTPMiddleware):
    """Client cũ gọi ``/api/...`` sẽ được phục vụ bởi ``/api/v1/...``.

    Đây là lớp tương thích ngược; đường dẫn chuẩn của hệ thống là ``/api/v1``.
    Việc viết lại đường dẫn (không dùng HTTP redirect) giữ nguyên method và body.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.scope.get("path", "")
        if (
            path.startswith(f"{API_PREFIX}/")
            and path != VERSIONED_PREFIX
            and not path.startswith(f"{VERSIONED_PREFIX}/")
        ):
            request.scope["path"] = f"{VERSIONED_PREFIX}{path[len(API_PREFIX):]}"
        return await call_next(request)
