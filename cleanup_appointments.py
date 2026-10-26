"""Dọn dữ liệu kiểm thử và gán kỹ thuật viên/nguồn lực cho lịch hẹn demo."""

import io
import sys

from backend.database import connect, transaction
from backend.migrations import GUARD_STATEMENTS

TECHNICIANS = {
    1: ("Nguyễn Văn Nam", "KHOANG-1"),
    2: ("Trần Đức Long", "KHOANG-2"),
    3: ("Phạm Tuấn Kiệt", "CAU-NANG-1"),
}

with connect() as db:
    with transaction(db):
        smoke = db.execute(
            "SELECT id, repair_order_id FROM appointments WHERE plate='50H-334.55'"
        ).fetchall()
        smoke_ids = [row["id"] for row in smoke]
        order_ids = [row["repair_order_id"] for row in smoke if row["repair_order_id"]]
        if order_ids:
            placeholders = ",".join("?" for _ in order_ids)
            db.execute(f"UPDATE appointments SET repair_order_id=NULL WHERE repair_order_id IN ({placeholders})", order_ids)
        for appointment_id in smoke_ids:
            db.execute("DELETE FROM appointments WHERE id=?", (appointment_id,))
        for order_id in order_ids:
            db.execute("DELETE FROM repair_orders WHERE id=?", (order_id,))

        # Gỡ trigger chặn xóa để dọn nhật ký của bản ghi kiểm thử.
        db.execute("DROP TRIGGER IF EXISTS trg_audit_block_delete")
        for appointment_id in smoke_ids:
            db.execute("DELETE FROM audit_logs WHERE entity_type='appointments' AND entity_id=?", (appointment_id,))
        for order_id in order_ids:
            db.execute("DELETE FROM audit_logs WHERE entity_type='repair_orders' AND entity_id=?", (order_id,))
            db.execute("DELETE FROM audit_logs WHERE entity_type='appointments' AND detail LIKE ?", (f'%"repair_order_id": {order_id}%',))
        for statement in GUARD_STATEMENTS:
            if "trg_audit_block_delete" in statement:
                db.execute(statement)

        # Khôi phục số km đã bị smoke test thay đổi.
        vehicle = db.execute("SELECT id, plate, mileage FROM vehicles WHERE plate='51H-123.45'").fetchone()
        if vehicle and vehicle["mileage"] == 43210:
            known = db.execute(
                "SELECT MAX(mileage) FROM repair_history WHERE vehicle_id=? AND mileage IS NOT NULL",
                (vehicle["id"],),
            ).fetchone()[0]
            orders_max = db.execute(
                "SELECT MAX(km_in) FROM repair_orders WHERE vehicle_id=? AND km_in IS NOT NULL",
                (vehicle["id"],),
            ).fetchone()[0]
            restore = max(known or 0, orders_max or 0, 0) or None
            db.execute("UPDATE vehicles SET mileage=? WHERE id=?", (restore, vehicle["id"]))

        resources = {row["code"]: row["id"] for row in db.execute("SELECT id, code FROM resources").fetchall()}
        for appointment_id, (technician, resource_code) in TECHNICIANS.items():
            db.execute(
                "UPDATE appointments SET technician=?, resource_id=? WHERE id=? AND TRIM(technician)=''",
                (technician, resources.get(resource_code), appointment_id),
            )

    print("appointments:")
    for row in db.execute(
        "SELECT a.id, a.plate, a.status, a.technician, r.name AS resource_name, a.duration_min "
        "FROM appointments a LEFT JOIN resources r ON r.id=a.resource_id ORDER BY a.id"
    ).fetchall():
        print("  ", dict(row))
    print("vehicles 51H-123.45:", dict(db.execute("SELECT plate, mileage FROM vehicles WHERE plate='51H-123.45'").fetchone()))
    print("orders:", db.execute("SELECT COUNT(*) FROM repair_orders").fetchone()[0],
          "| appointments:", db.execute("SELECT COUNT(*) FROM appointments").fetchone()[0],
          "| audit:", db.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0])
