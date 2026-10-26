"""Phụ thuộc dùng chung: xác thực (authentication) và phân quyền (authorization)."""

from fastapi import Depends, Header, Request

from ..auth_service import read_token
from ..permissions import has_permission, permissions_for
from .db import connect
from .errors import ForbiddenError, UnauthorizedError


def client_ip(request: Request | None) -> str | None:
    return request.client.host if request and request.client else None


def current_user(authorization: str | None = Header(default=None)) -> dict:
    """Giải mã token Bearer và trả về người dùng đang đăng nhập."""
    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedError("Vui lòng đăng nhập")
    user_id = read_token(authorization.removeprefix("Bearer ").strip())
    if not user_id:
        raise UnauthorizedError("Phiên đăng nhập đã hết hạn")
    with connect() as db:
        user = db.execute(
            "SELECT id, full_name, email, role, status FROM users WHERE id=?", (user_id,)
        ).fetchone()
    if not user or user["status"] != "active":
        raise UnauthorizedError("Tài khoản không hoạt động")
    return dict(user)


def require_permission(permission: str):
    """Dependency kiểm tra quyền ở backend (không tin tưởng frontend)."""

    def dependency(user: dict = Depends(current_user)) -> dict:
        if not has_permission(user["role"], permission):
            raise ForbiddenError("Bạn không có quyền truy cập chức năng này")
        return user

    return dependency


def require_any_permission(*permissions: str):
    """Dependency cho phép truy cập khi có ít nhất một quyền trong danh sách."""

    def dependency(user: dict = Depends(current_user)) -> dict:
        if not any(has_permission(user["role"], permission) for permission in permissions):
            raise ForbiddenError("Bạn không có quyền truy cập chức năng này")
        return user

    return dependency


def public_user(user: dict) -> dict:
    """Chỉ trả về các trường không nhạy cảm của người dùng."""
    return {
        "id": user["id"],
        "full_name": user["full_name"],
        "email": user["email"],
        "role": user["role"],
        "permissions": permissions_for(user["role"]),
    }
