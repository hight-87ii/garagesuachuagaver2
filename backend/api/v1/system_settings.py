from fastapi import APIRouter, Depends, Request

from ...core.access import ensure_role
from ...core.audit import write_audit
from ...core.config import WORKING_DAYS, WORKING_END, WORKING_START
from ...core.db import connect, transaction
from ...core.deps import client_ip, require_permission
from ...money import DEFAULT_DISCOUNT_RATE, DEFAULT_TAX_RATE
from ...schemas.system import SystemSettingsUpdate

router = APIRouter(prefix="/system-settings", tags=["System Settings"])


def payload(db) -> dict:
    values = {row["key"]: row["value"] for row in db.execute("SELECT key,value FROM system_settings")}
    return {**values, "quote_valid_days": int(values.get("quote_valid_days", "7")),
            "financial_rules": {"tax_rate": float(DEFAULT_TAX_RATE),
                                "draft_discount_rate": float(DEFAULT_DISCOUNT_RATE)},
            "working_hours": {"days": WORKING_DAYS, "start": WORKING_START, "end": WORKING_END}}


@router.get("")
def get_settings(user: dict = Depends(require_permission("staff"))) -> dict:
    with connect() as db:
        return payload(db)


@router.patch("")
def update_settings(item: SystemSettingsUpdate, request: Request,
                    user: dict = Depends(require_permission("staff"))) -> dict:
    ensure_role(user, ("Admin",), message="Chỉ Admin được thay đổi cài đặt hệ thống")
    values = item.model_dump()
    with connect() as db, transaction(db):
        for key, value in values.items():
            db.execute("""INSERT INTO system_settings(key,value,updated_by) VALUES(?,?,?)
                          ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_by=excluded.updated_by,
                          updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')""",
                       (key, str(value), user["id"]))
        write_audit(db, user, "system_settings.update", "system_settings", "global", values, client_ip(request))
        return payload(db)
