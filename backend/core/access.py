"""Kiểm soát truy cập theo từng bản ghi (chống IDOR).

Ngoài việc kiểm tra quyền theo vai trò, các bản ghi thuộc sở hữu của khách hàng
được kiểm tra thêm để đảm bảo người dùng chỉ truy cập dữ liệu của chính mình.
"""

import sqlite3

from .errors import ForbiddenError

CUSTOMER_ROLE = "Khách hàng"


def customer_for_user(db: sqlite3.Connection, user: dict) -> dict | None:
    """Tìm hồ sơ khách hàng gắn với tài khoản đăng nhập (theo email hoặc tên)."""
    row = db.execute(
        "SELECT * FROM customers WHERE email=? OR name=? ORDER BY id LIMIT 1",
        (user.get("email", ""), user.get("full_name", "")),
    ).fetchone()
    return dict(row) if row else None


def customer_scope_id(db: sqlite3.Connection, user: dict) -> int | None:
    """ID khách hàng cần giới hạn dữ liệu, hoặc None nếu người dùng là nhân viên.

    Với khách hàng chưa có hồ sơ, trả về -1 để không thấy bản ghi nào.
    """
    if user.get("role") != CUSTOMER_ROLE:
        return None
    customer = customer_for_user(db, user)
    return int(customer["id"]) if customer else -1


def ensure_role(
    user: dict,
    roles: tuple[str, ...],
    *,
    message: str = "Bạn không có quyền thực hiện thao tác này",
) -> None:
    """Chặn các thao tác nhạy cảm theo vai trò cụ thể (ngoài quyền chức năng)."""
    if user.get("role") not in roles:
        raise ForbiddenError(message)


def ensure_record_access(
    db: sqlite3.Connection,
    user: dict,
    owner_customer_id: int | None,
    *,
    message: str = "Bạn không có quyền truy cập dữ liệu này",
) -> None:
    """Với vai trò Khách hàng: bắt buộc bản ghi phải thuộc về khách hàng đó."""
    if user.get("role") != CUSTOMER_ROLE:
        return
    customer = customer_for_user(db, user)
    if (
        customer is None
        or owner_customer_id is None
        or int(owner_customer_id) != int(customer["id"])
    ):
        raise ForbiddenError(message)
