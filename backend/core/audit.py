"""Ghi nhật ký kiểm toán, có lọc dữ liệu nhạy cảm trước khi lưu."""

import json
import sqlite3
from typing import Any

# Các khóa không bao giờ được ghi vào nhật ký kiểm toán.
SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "new_password",
    "current_password",
    "confirm_password",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "secret",
    "api_key",
    "apikey",
    "card_number",
    "cvv",
    "otp",
}

_MASK = "***"


def sanitize(value: Any) -> Any:
    """Loại bỏ/che các trường nhạy cảm trong dict lồng nhau."""
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                cleaned[key] = _MASK
            else:
                cleaned[key] = sanitize(item)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    return value


def write_audit(
    db: sqlite3.Connection,
    user: dict | None,
    action: str,
    entity_type: str,
    entity_id: Any = None,
    detail: dict | None = None,
    ip: str | None = None,
) -> None:
    """Ghi một dòng nhật ký kiểm toán (đã lọc dữ liệu nhạy cảm)."""
    safe_detail = sanitize(detail or {})
    db.execute(
        "INSERT INTO audit_logs(user_id, actor_email, action, entity_type, entity_id, detail, ip) "
        "VALUES(?, ?, ?, ?, ?, ?, ?)",
        (
            (user or {}).get("id"),
            (user or {}).get("email", ""),
            action,
            entity_type,
            str(entity_id) if entity_id is not None else None,
            json.dumps(safe_detail, ensure_ascii=False),
            ip,
        ),
    )
