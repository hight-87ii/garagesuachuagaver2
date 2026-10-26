"""Ước tính thời lượng công việc từ danh mục và thời gian thực tế đã ghi nhận.

Không dùng thời gian mở/đóng phiếu: khoảng đó có thể gồm chờ phụ tùng, qua đêm.
Không suy ra thời gian cho phụ tùng hay hạng mục không có dịch vụ liên kết.
"""

from statistics import median


def service_duration(db, service_id: int | None, name: str, quantity: float) -> tuple[int | None, str | None]:
    service = db.execute("SELECT id,name,duration_min FROM services WHERE id=?", (service_id,)).fetchone() if service_id else None
    if service and service["name"] != name:
        service = None
    if not service:
        service = db.execute("SELECT id,name,duration_min FROM services WHERE name=?", (name,)).fetchone()
    if not service:
        return None, None
    baseline = int(service["duration_min"])
    samples = db.execute(
        """SELECT roi.actual_duration_min,roi.quantity FROM repair_order_items roi
           JOIN repair_orders ro ON ro.id=roi.repair_order_id
           WHERE roi.service_id=? AND roi.actual_duration_min IS NOT NULL AND roi.quantity>0
             AND ro.status_code IN ('COMPLETED','DELIVERED')
           ORDER BY roi.id DESC LIMIT 20""", (service["id"],)
    ).fetchall()
    per_unit = baseline
    source = "catalog"
    if len(samples) >= 3:
        observed = median(float(row["actual_duration_min"]) / float(row["quantity"]) for row in samples)
        # Chỉ dùng lịch sử đủ mẫu và trong khoảng hợp lý so với thời lượng danh mục.
        if max(5, baseline / 2) <= observed <= min(1440, baseline * 2):
            per_unit = observed
            source = "history"
    return max(1, round(per_unit * float(quantity))), source


def quote_duration(db, quote_id: int) -> int | None:
    value = db.execute(
        "SELECT SUM(estimated_duration_min) FROM quote_items WHERE quote_id=? AND kind='Dịch vụ'",
        (quote_id,),
    ).fetchone()[0]
    return int(value) if value else None
