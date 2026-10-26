"""Xử lý lỗi thống nhất.

Mọi lỗi trả về cùng một cấu trúc JSON:

    {
      "error": {"code": "not_found", "message": "...", "details": null},
      "detail": "..."          # giữ lại để tương thích với client cũ
    }

Không bao giờ trả stack trace hay thông tin nội bộ ra ngoài.
"""

import logging
import sqlite3
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("garageai.error")

_HTTP_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
}


class AppError(Exception):
    """Lỗi nghiệp vụ có thể dự đoán trước, được ánh xạ sang HTTP status phù hợp."""

    status_code = 400
    code = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationAppError(AppError):
    status_code = 422
    code = "validation_error"


def error_body(code: str, message: str, details: Any | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}, "detail": message}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message, exc.details))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "Yêu cầu không hợp lệ"
        headers = getattr(exc, "headers", None)
        return JSONResponse(status_code=exc.status_code, content=error_body(code, message), headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_body(
                "validation_error",
                "Dữ liệu gửi lên không hợp lệ",
                jsonable_encoder(exc.errors()),
            ),
        )

    @app.exception_handler(sqlite3.IntegrityError)
    async def _integrity_error(_: Request, exc: sqlite3.IntegrityError) -> JSONResponse:
        # Ràng buộc toàn vẹn dữ liệu (UNIQUE/FK/CHECK) -> 409, không lộ chi tiết SQL.
        logger.warning("integrity error: %s", exc)
        return JSONResponse(
            status_code=409,
            content=error_body("conflict", "Dữ liệu vi phạm ràng buộc toàn vẹn của hệ thống"),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error: %s", exc)
        return JSONResponse(
            status_code=500,
            content=error_body("internal_error", "Lỗi hệ thống, vui lòng thử lại sau"),
        )
