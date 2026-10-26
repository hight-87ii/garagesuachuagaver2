"""Tiện ích nghiệp vụ dùng chung giữa các module API.

Bao gồm tra cứu xe theo biển số đã chuẩn hóa, sinh mã phiếu/hóa đơn và đồng bộ
tổng tiền phiếu sửa chữa (server tính, không cho client gửi lên).
"""

import sqlite3

from .core.db import normalize_plate
from .timeutil import now_utc_iso

DEFAULT_HISTORY_SERVICE = "Sửa chữa tổng quát"


def locate_vehicle(db: sqlite3.Connection, plate: str):
    """Tìm xe theo biển số đã chuẩn hóa (hỗ trợ tra cứu, không phải định danh duy nhất)."""
    return db.execute(
        "SELECT id, customer_id, plate FROM vehicles "
        "WHERE plate_normalized=? ORDER BY (status='active') DESC, id LIMIT 1",
        (normalize_plate(plate),),
    ).fetchone()


def technician_id_for(db: sqlite3.Connection, full_name: str) -> int | None:
    """Tra cứu id kỹ thuật viên theo tên hiển thị."""
    if not full_name:
        return None
    row = db.execute(
        "SELECT id FROM users WHERE full_name=? AND role='Kỹ thuật viên' LIMIT 1",
        (full_name,),
    ).fetchone()
    return row["id"] if row else None


def customer_name_for(db: sqlite3.Connection, customer_id: int | None) -> str:
    if not customer_id:
        return ""
    row = db.execute("SELECT name FROM customers WHERE id=?", (customer_id,)).fetchone()
    return row["name"] if row else ""


def sync_order_total(db: sqlite3.Connection, order_id: int) -> int:
    """Tổng phiếu = thành tiền dịch vụ/hạng mục + phụ tùng đã dùng (số nguyên đồng)."""
    items = db.execute(
        "SELECT COALESCE(SUM(line_total), 0) FROM repair_order_items WHERE repair_order_id=?",
        (order_id,),
    ).fetchone()[0]
    parts = db.execute(
        "SELECT COALESCE(SUM(line_total), 0) FROM repair_order_parts WHERE repair_order_id=?",
        (order_id,),
    ).fetchone()[0]
    total = int(items) + int(parts)
    db.execute("UPDATE repair_orders SET total=? WHERE id=?", (total, order_id))
    return total


def next_order_code(db: sqlite3.Connection) -> str:
    highest = 1028
    for (code,) in db.execute("SELECT code FROM repair_orders").fetchall():
        digits = "".join(character for character in (code or "") if character.isdigit())
        if digits:
            highest = max(highest, int(digits))
    return f"PSC-{highest + 1}"


def next_invoice_code(db: sqlite3.Connection) -> str:
    prefix_row = db.execute(
        "SELECT value FROM system_settings WHERE key='invoice_prefix'"
    ).fetchone()
    prefix = (prefix_row["value"] if prefix_row else "HD").strip().upper() or "HD"
    highest = 0
    for (code,) in db.execute("SELECT code FROM invoices").fetchall():
        digits = "".join(character for character in (code or "") if character.isdigit())
        if digits:
            highest = max(highest, int(digits))
    return f"{prefix}-{highest + 1:04d}"


def sync_vehicle_mileage(db: sqlite3.Connection, vehicle_id: int | None, mileage: int | None) -> None:
    """Cập nhật số km mới nhất của xe (không bao giờ giảm số km đã ghi)."""
    if not vehicle_id or mileage is None:
        return
    db.execute(
        "UPDATE vehicles SET mileage=? WHERE id=? AND (mileage IS NULL OR mileage < ?)",
        (int(mileage), vehicle_id, int(mileage)),
    )


def order_service_summary(db: sqlite3.Connection, order_id: int) -> str:
    """Tóm tắt hạng mục đã làm của một phiếu (dịch vụ + phụ tùng, không trùng lặp)."""
    names: list[str] = []
    for row in db.execute(
        "SELECT name FROM repair_order_items WHERE repair_order_id=? ORDER BY id", (order_id,)
    ).fetchall():
        if row["name"] and row["name"] not in names:
            names.append(row["name"])
    for row in db.execute(
        "SELECT name FROM repair_order_parts WHERE repair_order_id=? ORDER BY id", (order_id,)
    ).fetchall():
        if row["name"] and row["name"] not in names:
            names.append(row["name"])
    return ", ".join(names) or DEFAULT_HISTORY_SERVICE


def record_repair_history(db: sqlite3.Connection, order_id: int) -> int | None:
    """Ghi một dòng lịch sử sửa chữa khi phiếu hoàn thành (idempotent).

    Nhờ chỉ mục duy nhất ``ux_repair_history_order`` mỗi phiếu chỉ có tối đa một dòng,
    nên thao tác này an toàn khi được gọi lặp lại.
    """
    order = db.execute("SELECT * FROM repair_orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        return None
    if db.execute(
        "SELECT id FROM repair_history WHERE repair_order_id=?", (order_id,)
    ).fetchone():
        return None

    note = (order["note"] or "").strip()
    latest_note = db.execute(
        "SELECT content FROM repair_notes WHERE repair_order_id=? ORDER BY id DESC LIMIT 1",
        (order_id,),
    ).fetchone()
    if latest_note and latest_note["content"]:
        note = f"{note} • {latest_note['content']}" if note else latest_note["content"]

    mileage = order["km_in"]
    if mileage is None and order["vehicle_id"]:
        row = db.execute("SELECT mileage FROM vehicles WHERE id=?", (order["vehicle_id"],)).fetchone()
        mileage = row["mileage"] if row else None
    if mileage is not None:
        mileage = int(mileage)

    cursor = db.execute(
        "INSERT INTO repair_history(vehicle_id, repair_order_id, plate, repaired_at, mileage, services, note, total) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
        (
            order["vehicle_id"],
            order_id,
            order["plate"],
            order["closed_at"] or now_utc_iso(),
            mileage,
            order_service_summary(db, order_id),
            note,
            int(order["total"] or 0),
        ),
    )
    sync_vehicle_mileage(db, order["vehicle_id"], mileage)
    return cursor.lastrowid


def backfill_repair_history(
    db: sqlite3.Connection,
    *,
    vehicle_id: int | None = None,
    plate: str | None = None,
) -> int:
    """Bổ sung lịch sử cho các phiếu đã hoàn thành nhưng chưa có dòng lịch sử.

    Giúp dữ liệu cũ (trước khi có tính năng đồng bộ) vẫn hiển thị đầy đủ.
    """
    query = "SELECT id FROM repair_orders WHERE status='Hoàn thành'"
    params: list = []
    if vehicle_id:
        query += " AND vehicle_id=?"
        params.append(vehicle_id)
    elif plate:
        query += " AND plate=?"
        params.append(plate.upper())
    query += " ORDER BY id"
    filled = 0
    for row in db.execute(query, tuple(params)).fetchall():
        if record_repair_history(db, row["id"]) is not None:
            filled += 1
    return filled
