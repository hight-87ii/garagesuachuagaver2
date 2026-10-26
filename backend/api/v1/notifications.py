"""Nhắc việc trong ứng dụng, tạo từ bản ghi hiện tại và giới hạn theo vai trò."""

from fastapi import APIRouter, Depends

from ...core.access import customer_scope_id
from ...core.db import connect
from ...core.deps import require_permission
from ...permissions import has_permission
from ...timeutil import vn_text

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("")
def list_notifications(user: dict = Depends(require_permission("dashboard"))) -> dict:
    items: list[dict] = []
    role = user["role"]
    with connect() as db:
        scope = customer_scope_id(db, user)
        preference = db.execute(
            "SELECT notify_appointment,notify_repair FROM user_preferences WHERE user_id=?",
            (user["id"],),
        ).fetchone()
        notify_appointment = not preference or bool(preference["notify_appointment"])
        notify_repair = not preference or bool(preference["notify_repair"])

        if has_permission(role, "appointments") and notify_appointment:
            if scope is not None:
                rows = db.execute(
                    """SELECT a.id,a.plate,a.service,a.appointment_at,a.status FROM appointments a
                       LEFT JOIN vehicles v ON v.id=a.vehicle_id
                       WHERE COALESCE(a.customer_id,v.customer_id)=? AND a.status IN ('Đang chờ','Đã xác nhận')
                         AND a.appointment_at>=strftime('%Y-%m-%dT%H:%M:%SZ','now')
                         AND a.appointment_at<=strftime('%Y-%m-%dT%H:%M:%SZ','now','+7 days')
                       ORDER BY a.appointment_at LIMIT 8""", (scope,),
                ).fetchall()
                for row in rows:
                    items.append({"id": f"appointment:{row['id']}", "title": "Lịch hẹn sắp tới",
                                  "description": f"{row['plate']} · {row['service']} · {vn_text(row['appointment_at'])}",
                                  "page": "Lịch hẹn", "kind": "appointment"})
            else:
                rows = db.execute(
                    """SELECT id,plate,service,appointment_at FROM appointments
                       WHERE status='Đang chờ' ORDER BY appointment_at DESC LIMIT 8"""
                ).fetchall()
                for row in rows:
                    items.append({"id": f"appointment:{row['id']}", "title": "Lịch hẹn chờ xác nhận",
                                  "description": f"{row['plate']} · {row['service']} · {vn_text(row['appointment_at'])}",
                                  "page": "Lịch hẹn", "kind": "appointment"})

        if scope is not None and notify_repair:
            rows = db.execute(
                """SELECT id,code,plate,status FROM repair_orders
                   WHERE customer_id=? AND status NOT IN ('Hoàn thành','Đã bàn giao','Đã hủy')
                   ORDER BY id DESC LIMIT 6""", (scope,),
            ).fetchall()
            for row in rows:
                items.append({"id": f"repair:{row['id']}", "title": "Xe đang được xử lý",
                              "description": f"{row['plate']} · phiếu {row['code']} · {row['status']}",
                              "page": "Xe của tôi", "kind": "repair"})
        elif scope is None and notify_repair and has_permission(role, "repair_orders"):
            rows = db.execute(
                """SELECT id,code,plate,status FROM repair_orders
                   WHERE status_code IN ('WAITING_FOR_PARTS','ON_HOLD')
                   ORDER BY id DESC LIMIT 8"""
            ).fetchall()
            for row in rows:
                items.append({"id": f"repair:{row['id']}", "title": "Phiếu cần theo dõi",
                              "description": f"{row['code']} · {row['plate']} · {row['status']}",
                              "page": "Phiếu sửa chữa", "kind": "repair"})

        if has_permission(role, "invoices"):
            sql = """SELECT i.id,i.code,i.total-i.paid_amount remaining,r.plate,i.due_at
                     FROM invoices i JOIN repair_orders r ON r.id=i.repair_order_id
                     WHERE i.status<>'Đã hủy' AND i.total>i.paid_amount"""
            params: tuple = ()
            if scope is not None:
                sql += " AND r.customer_id=?"
                params = (scope,)
            sql += " ORDER BY COALESCE(i.due_at,i.issued_at),i.id LIMIT 8"
            for row in db.execute(sql, params).fetchall():
                due = f" · hẹn {row['due_at']}" if row["due_at"] else ""
                amount = f"{int(row['remaining']):,}".replace(",", ".")
                items.append({"id": f"invoice:{row['id']}",
                              "title": "Hóa đơn còn phải trả" if scope is not None else "Hóa đơn còn phải thu",
                              "description": f"{row['code']} · {row['plate']} · {amount} ₫{due}",
                              "page": "Hóa đơn", "kind": "invoice"})

        if scope is None and has_permission(role, "inventory"):
            rows = db.execute(
                "SELECT id,code,name,stock,unit FROM parts WHERE active=1 AND stock<=min_stock "
                "ORDER BY stock,name LIMIT 8"
            ).fetchall()
            for row in rows:
                items.append({"id": f"part:{row['id']}", "title": "Phụ tùng cần bổ sung",
                              "description": f"{row['name']} ({row['code']}) · còn {row['stock']} {row['unit']}",
                              "page": "Kho phụ tùng", "kind": "part"})
    return {"count": len(items), "items": items}
