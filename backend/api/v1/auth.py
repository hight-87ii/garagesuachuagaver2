"""Module xác thực (authentication) và phân quyền (authorization)."""

import os
import sqlite3

from fastapi import APIRouter, Depends, Request, Response

from ...auth_service import create_token, hash_password, verify_password
from ...core.audit import write_audit
from ...core.db import connect, transaction
from ...core.deps import client_ip, current_user, public_user, require_permission
from ...core.errors import BadRequestError, ConflictError, ForbiddenError, UnauthorizedError
from ...permissions import PERMISSIONS, ROLE_PERMISSIONS, permissions_for
from ...schemas.auth import LoginIn, LoginOut, PasswordChangeIn, RbacOut, RegisterIn, UserOut, UserSettingsIn
from ...schemas.common import Message

router = APIRouter(prefix="/auth", tags=["Authentication"])
rbac_router = APIRouter(prefix="/rbac", tags=["Authorization"])

DEMO_PASSWORDS = {
    "admin@garage.vn": "Admin@123",
    "manager@garage.vn": "Manager@123",
    "reception@garage.vn": "Reception@123",
    "technician@garage.vn": "Technician@123",
    "cashier@garage.vn": "Cashier@123",
    "customer@garage.vn": "Customer@123",
    "ha.hoang@garage-demo.vn": "Ha@123456",
    "su.hoang@garage-demo.vn": "Su@123456",
    "tuat.hoang@garage-demo.vn": "Tuat@123456",
}


@router.get("/demo-accounts")
def demo_accounts(response: Response) -> list[dict]:
    """Danh sách tự điền chỉ bật trong môi trường demo, không dùng ở production."""
    response.headers["Cache-Control"] = "no-store"
    if os.getenv("ENABLE_DEMO_ACCOUNTS", "false").lower() not in {"1", "true", "yes"}:
        return []
    with connect() as db:
        rows = db.execute(
            "SELECT full_name,email,role FROM users WHERE status='active' ORDER BY id"
        ).fetchall()
    return [
        {"name": row["full_name"], "email": row["email"], "role": row["role"],
         "password": DEMO_PASSWORDS[row["email"]]}
        for row in rows if row["email"] in DEMO_PASSWORDS
    ]


@router.post("/register", status_code=201, response_model=LoginOut, response_model_exclude_none=True)
def register(item: RegisterIn) -> dict:
    email = item.email.strip().lower()
    try:
        with connect() as db, transaction(db):
            cursor = db.execute(
                "INSERT INTO users(full_name, email, password_hash, role, status) "
                "VALUES(?, ?, ?, 'Lễ tân', 'active')",
                (item.full_name.strip(), email, hash_password(item.password)),
            )
            user_id = cursor.lastrowid
            write_audit(db, None, "user.register", "users", user_id, {"email": email})
    except sqlite3.IntegrityError as exc:
        raise ConflictError("Email đã được sử dụng") from exc
    account = {"id": user_id, "full_name": item.full_name.strip(), "email": email, "role": "Lễ tân"}
    return {"access_token": create_token(user_id), "token_type": "bearer", "user": public_user(account)}


@router.post("/login", response_model=LoginOut, response_model_exclude_none=True)
def login(item: LoginIn, request: Request) -> dict:
    with connect() as db, transaction(db):
        user = db.execute(
            "SELECT * FROM users WHERE email=?", (item.email.strip().lower(),)
        ).fetchone()
        if not user or not verify_password(item.password, user["password_hash"]):
            raise UnauthorizedError("Email hoặc mật khẩu không đúng")
        if user["status"] != "active":
            raise ForbiddenError("Tài khoản đã bị khóa")
        write_audit(
            db,
            {"id": user["id"], "email": user["email"]},
            "auth.login",
            "users",
            user["id"],
            {"email": user["email"]},
            client_ip(request),
        )
    return {
        "access_token": create_token(user["id"]),
        "token_type": "bearer",
        "user": public_user(dict(user)),
    }


@router.get("/me", response_model=UserOut, response_model_exclude_none=True)
def me(user: dict = Depends(current_user)) -> dict:
    return {**user, "permissions": permissions_for(user["role"])}


@router.post("/password", response_model=Message, response_model_exclude_none=True)
def change_password(item: PasswordChangeIn, user: dict = Depends(current_user)) -> dict:
    with connect() as db, transaction(db):
        account = db.execute(
            "SELECT password_hash FROM users WHERE id=?", (user["id"],)
        ).fetchone()
        if not account or not verify_password(item.current_password, account["password_hash"]):
            raise BadRequestError("Mật khẩu hiện tại không đúng")
        db.execute(
            "UPDATE users SET password_hash=?, password_algo='pbkdf2_sha256' WHERE id=?",
            (hash_password(item.new_password), user["id"]),
        )
        write_audit(db, user, "user.change_password", "users", user["id"])
    return {"message": "Đổi mật khẩu thành công"}


@router.get("/settings")
def get_user_settings(user: dict = Depends(current_user)) -> dict:
    with connect() as db, transaction(db):
        db.execute("INSERT OR IGNORE INTO user_preferences(user_id) VALUES(?)", (user["id"],))
        row = db.execute(
            """SELECT u.full_name,u.email,COALESCE(u.phone,'') phone,p.language,
                      p.notify_appointment,p.notify_repair,p.notify_promotion
               FROM users u JOIN user_preferences p ON p.user_id=u.id WHERE u.id=?""",
            (user["id"],),
        ).fetchone()
        return {**dict(row), "notify_appointment": bool(row["notify_appointment"]),
                "notify_repair": bool(row["notify_repair"]),
                "notify_promotion": bool(row["notify_promotion"])}


@router.patch("/settings")
def update_user_settings(item: UserSettingsIn, user: dict = Depends(current_user)) -> dict:
    with connect() as db, transaction(db):
        db.execute("UPDATE users SET full_name=?,phone=? WHERE id=?", (item.full_name, item.phone, user["id"]))
        db.execute(
            """INSERT INTO user_preferences(user_id,language,notify_appointment,notify_repair,notify_promotion)
               VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET language=excluded.language,
               notify_appointment=excluded.notify_appointment,notify_repair=excluded.notify_repair,
               notify_promotion=excluded.notify_promotion,updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')""",
            (user["id"], item.language, int(item.notify_appointment), int(item.notify_repair), int(item.notify_promotion)),
        )
        write_audit(db, user, "user.settings.update", "users", user["id"], {"language": item.language})
    return get_user_settings(user)


@rbac_router.get("/roles", response_model=RbacOut, response_model_exclude_none=True)
def rbac_roles(user: dict = Depends(require_permission("staff"))) -> dict:
    return {
        "roles": {role: sorted(granted) for role, granted in ROLE_PERMISSIONS.items()},
        "permissions": PERMISSIONS,
    }
