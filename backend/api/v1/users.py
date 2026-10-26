import sqlite3

from fastapi import APIRouter, Depends, Query, Request

from ...auth_service import hash_password
from ...core.access import ensure_role
from ...core.audit import write_audit
from ...core.db import connect, transaction
from ...core.deps import client_ip, require_permission
from ...core.errors import BadRequestError, ConflictError, NotFoundError
from ...core.pagination import PageParams, envelope, fetch_page, page_params, search_clause
from ...permissions import ROLE_PERMISSIONS
from ...schemas.auth import UserCreateIn, UserOut, UserUpdateIn
from ...schemas.common import Page

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("", response_model=Page[UserOut])
def list_users(q: str = Query(default="", max_length=100), page: PageParams = Depends(page_params),
               user: dict = Depends(require_permission("staff"))) -> dict:
    base = "SELECT id, full_name, email, role, status, created_at, updated_at FROM users WHERE 1=1"
    clause, params = search_clause(q, ["full_name", "email", "role"])
    with connect() as db:
        rows, total = fetch_page(db, base + clause, tuple(params), "ORDER BY id", page)
    return envelope(rows, total, page)


@router.post("", status_code=201, response_model=UserOut)
def create_user(item: UserCreateIn, request: Request,
                user: dict = Depends(require_permission("staff"))) -> dict:
    ensure_role(user, ("Admin",), message="Chỉ Admin được tạo tài khoản nhân viên")
    if item.role not in ROLE_PERMISSIONS:
        raise BadRequestError("Vai trò không hợp lệ")
    try:
        with connect() as db, transaction(db):
            cursor = db.execute(
                "INSERT INTO users(full_name,email,password_hash,role,status) VALUES(?,?,?,?, 'active')",
                (item.full_name, item.email.lower(), hash_password(item.password), item.role),
            )
            write_audit(db, user, "user.create", "users", cursor.lastrowid,
                        {"email": item.email.lower(), "role": item.role}, client_ip(request))
            return dict(db.execute("SELECT id,full_name,email,role,status FROM users WHERE id=?", (cursor.lastrowid,)).fetchone())
    except sqlite3.IntegrityError as exc:
        raise ConflictError("Email đã được sử dụng") from exc


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, item: UserUpdateIn, request: Request,
                actor: dict = Depends(require_permission("staff"))) -> dict:
    ensure_role(actor, ("Admin",), message="Chỉ Admin được thay đổi tài khoản và phân quyền")
    fields = item.model_dump(exclude_none=True)
    if not fields:
        raise BadRequestError("Không có dữ liệu cập nhật")
    if fields.get("role") and fields["role"] not in ROLE_PERMISSIONS:
        raise BadRequestError("Vai trò không hợp lệ")
    if user_id == actor["id"] and fields.get("status") in {"locked", "disabled"}:
        raise BadRequestError("Không thể tự khóa tài khoản đang đăng nhập")
    if user_id == actor["id"] and fields.get("role") and fields["role"] != actor["role"]:
        raise BadRequestError("Không thể tự thay đổi vai trò của tài khoản đang đăng nhập")
    with connect() as db, transaction(db):
        if not db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone():
            raise NotFoundError("Không tìm thấy người dùng")
        db.execute(f"UPDATE users SET {', '.join(f'{key}=?' for key in fields)} WHERE id=?",
                   (*fields.values(), user_id))
        write_audit(db, actor, "user.update", "users", user_id, fields, client_ip(request))
        return dict(db.execute("SELECT id,full_name,email,role,status FROM users WHERE id=?", (user_id,)).fetchone())
