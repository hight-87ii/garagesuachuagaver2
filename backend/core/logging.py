"""Cấu hình logging an toàn cho backend.

Nguyên tắc: không ghi body, header Authorization hay token vào log. Chỉ ghi
phương thức, đường dẫn, mã trạng thái và thời gian xử lý.
"""

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .config import LOG_LEVEL

access_logger = logging.getLogger("garageai.access")


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Ghi log truy cập tối thiểu, an toàn (không có dữ liệu nhạy cảm)."""

    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        access_logger.info(
            "%s %s -> %s (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response
