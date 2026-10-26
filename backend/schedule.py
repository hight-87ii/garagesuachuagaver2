"""Kiểm tra lịch làm việc và xung đột phân công cho lịch hẹn.

Module thuần nghiệp vụ (không phụ thuộc FastAPI), dùng lại được từ router lịch hẹn:

* Khung giờ / ngày làm việc của garage lấy từ cấu hình (biến môi trường).
* Trùng lịch theo **kỹ thuật viên** và theo **nguồn lực** (khoang sửa, cầu nâng...).
  Phần nguồn lực chỉ bật khi garage đã cấu hình ít nhất một nguồn lực đang hoạt động.
* Kỹ thuật viên còn phiếu sửa chữa chưa hoàn thành được coi là xung đột phân công.

Mọi cảnh báo trả về dạng ``dict`` để router đưa nguyên vào ``error.details`` hoặc
trường ``conflicts`` của phản hồi.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

from .core.config import WORKING_DAYS, WORKING_END, WORKING_START
from .timeutil import UTC_STORAGE_FORMAT, vn_datetime, vn_text

#: Nhãn thứ theo ISO-8601 (1 = Thứ 2 ... 7 = Chủ nhật).
WEEKDAY_LABELS = {
    1: "Thứ 2",
    2: "Thứ 3",
    3: "Thứ 4",
    4: "Thứ 5",
    5: "Thứ 6",
    6: "Thứ 7",
    7: "Chủ nhật",
}

#: Trạng thái lịch hẹn còn chiếm chỗ trong lịch làm việc.
ACTIVE_STATUSES = ("Đang chờ", "Đã xác nhận", "Đã tiếp nhận")

#: Trạng thái phiếu sửa chữa còn chiếm thời gian của kỹ thuật viên.
OPEN_ORDER_STATUSES = (
    "Tiếp nhận",
    "Đang kiểm tra",
    "Đã báo giá",
    "Đã duyệt",
    "Đang sửa",
    "Chờ phụ tùng",
    "Tạm dừng",
)

DEFAULT_START_MINUTES = 7 * 60 + 30
DEFAULT_END_MINUTES = 18 * 60


def _minutes(text: str, fallback: int) -> int:
    """Đọc "HH:MM" thành số phút trong ngày, không hợp lệ thì dùng mặc định."""
    try:
        hours, _, minutes = str(text).strip().partition(":")
        value = int(hours) * 60 + int(minutes or 0)
    except (TypeError, ValueError):
        return fallback
    return value if 0 <= value <= 24 * 60 else fallback


def _text(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def working_days() -> set[int]:
    """Các thứ làm việc (ISO-8601) đọc từ cấu hình."""
    days = {
        int(part)
        for part in str(WORKING_DAYS).split(",")
        if part.strip().isdigit() and 1 <= int(part) <= 7
    }
    return days or {1, 2, 3, 4, 5, 6}


def working_window() -> dict:
    """Khung giờ làm việc trong ngày, tính bằng phút kể từ 00:00 giờ Việt Nam."""
    start = _minutes(WORKING_START, DEFAULT_START_MINUTES)
    end = _minutes(WORKING_END, DEFAULT_END_MINUTES)
    if end <= start:
        start, end = DEFAULT_START_MINUTES, DEFAULT_END_MINUTES
    return {"start": start, "end": end, "start_text": _text(start), "end_text": _text(end)}


def working_rules() -> dict:
    """Mô tả lịch làm việc để trả về cho giao diện."""
    days = sorted(working_days())
    window = working_window()
    return {
        "working_days": days,
        "working_days_text": ", ".join(WEEKDAY_LABELS[day] for day in days),
        "working_hours": {
            "start": window["start_text"],
            "end": window["end_text"],
        },
        "slot_advice": "Mỗi lịch hẹn nên dài tối thiểu 30 phút và nằm trong khung giờ làm việc.",
    }


def time_window(start_utc: str, duration_min: int) -> str:
    """Thời điểm kết thúc (UTC ISO) của một lịch hẹn."""
    moment = vn_datetime(start_utc)
    if moment is None:
        return start_utc
    end = moment + timedelta(minutes=int(duration_min or 0))
    return end.astimezone(timezone.utc).strftime(UTC_STORAGE_FORMAT)


def working_hours_issues(start_utc: str, duration_min: int) -> list[dict]:
    """Kiểm tra lịch hẹn có nằm trong ngày và giờ làm việc của garage hay không."""
    moment = vn_datetime(start_utc)
    if moment is None:
        return []
    window = working_window()
    days = working_days()
    issues: list[dict] = []
    weekday = moment.isoweekday()
    if weekday not in days:
        issues.append(
            {
                "code": "closed_day",
                "level": "blocking",
                "message": (
                    f"Garage không làm việc vào {WEEKDAY_LABELS[weekday].lower()}. "
                    f"Lịch làm việc: {', '.join(WEEKDAY_LABELS[day] for day in sorted(days))}."
                ),
            }
        )
    end = moment + timedelta(minutes=int(duration_min or 0))
    start_minutes = moment.hour * 60 + moment.minute
    same_day = end.date() == moment.date()
    if not same_day or start_minutes < window["start"] or end.hour * 60 + end.minute > window["end"]:
        issues.append(
            {
                "code": "outside_working_hours",
                "level": "blocking",
                "message": (
                    f"Lịch hẹn nằm ngoài giờ làm việc "
                    f"({window['start_text']} - {window['end_text']})."
                ),
            }
        )
    return issues


def resources_configured(db: sqlite3.Connection) -> bool:
    """Garage đã cấu hình nguồn lực (khoang sửa, cầu nâng...) hay chưa."""
    row = db.execute("SELECT COUNT(*) FROM resources WHERE active = 1").fetchone()
    return bool(row and row[0])


def _overlapping_appointments(
    db: sqlite3.Connection,
    *,
    start: str,
    end: str,
    exclude_id: int | None,
    condition: str,
    params: tuple,
) -> list[dict]:
    placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
    excluded = "AND a.id <> ?" if exclude_id else ""
    sql = f"""
        SELECT a.id, a.customer_name, a.plate, a.service, a.appointment_at, a.duration_min,
               a.status, a.technician, a.resource_id, r.name AS resource_name
        FROM appointments a
        LEFT JOIN resources r ON r.id = a.resource_id
        WHERE a.status IN ({placeholders})
          AND datetime(a.appointment_at) < datetime(?)
          AND datetime(a.appointment_at, '+' || a.duration_min || ' minutes') > datetime(?)
          {excluded}
          {condition}
        ORDER BY a.appointment_at
    """
    arguments: list = [*ACTIVE_STATUSES, end, start]
    if exclude_id:
        arguments.append(exclude_id)
    arguments.extend(params)
    return [dict(row) for row in db.execute(sql, tuple(arguments)).fetchall()]


def find_conflicts(
    db: sqlite3.Connection,
    *,
    start: str,
    end: str,
    technician: str = "",
    technician_id: int | None = None,
    resource_id: int | None = None,
    exclude_id: int | None = None,
) -> list[dict]:
    """Tìm lịch trùng kỹ thuật viên / nguồn lực và phiếu đang xử lý của kỹ thuật viên."""
    conflicts: list[dict] = []
    technician = (technician or "").strip()

    if technician_id or technician:
        if technician_id and technician:
            condition = "AND (a.technician_id = ? OR LOWER(a.technician) = LOWER(?))"
            params = (technician_id, technician)
        elif technician_id:
            condition = "AND a.technician_id = ?"
            params = (technician_id,)
        else:
            condition = "AND LOWER(a.technician) = LOWER(?)"
            params = (technician,)
        for row in _overlapping_appointments(
            db, start=start, end=end, exclude_id=exclude_id, condition=condition, params=params
        ):
            conflicts.append(
                {
                    "kind": "technician_busy",
                    "level": "blocking",
                    "message": (
                        f"Kỹ thuật viên {technician or row['technician']} đã có lịch hẹn "
                        f"lúc {vn_text(row['appointment_at'])} (lịch #{row['id']}, "
                        f"biển số {row['plate']})."
                    ),
                    "appointment_id": row["id"],
                    "at": vn_text(row["appointment_at"]),
                    "status": row["status"],
                    "plate": row["plate"],
                    "technician": row["technician"],
                }
            )

        rows = db.execute(
            f"""
            SELECT id, code, plate, status, technician
            FROM repair_orders
            WHERE status IN ({', '.join('?' for _ in OPEN_ORDER_STATUSES)})
              AND (technician_id = ? OR LOWER(technician) = LOWER(?))
            ORDER BY id DESC
            """,
            (*OPEN_ORDER_STATUSES, technician_id, technician),
        ).fetchall()
        for row in rows:
            conflicts.append(
                {
                    "kind": "technician_working",
                    "level": "warning",
                    "message": (
                        f"Kỹ thuật viên {technician or row['technician']} đang xử lý phiếu "
                        f"{row['code']} (biển số {row['plate']}, trạng thái {row['status']})."
                    ),
                    "repair_order_id": row["id"],
                    "code": row["code"],
                    "plate": row["plate"],
                    "status": row["status"],
                    "technician": row["technician"],
                }
            )

    if resource_id:
        for row in _overlapping_appointments(
            db,
            start=start,
            end=end,
            exclude_id=exclude_id,
            condition="AND a.resource_id = ?",
            params=(resource_id,),
        ):
            conflicts.append(
                {
                    "kind": "resource_busy",
                    "level": "blocking",
                    "message": (
                        f"Nguồn lực {row['resource_name'] or row['resource_id']} đã được dùng "
                        f"lúc {vn_text(row['appointment_at'])} (lịch #{row['id']}, "
                        f"biển số {row['plate']})."
                    ),
                    "appointment_id": row["id"],
                    "at": vn_text(row["appointment_at"]),
                    "status": row["status"],
                    "plate": row["plate"],
                    "resource_id": row["resource_id"],
                    "resource_name": row["resource_name"],
                }
            )

    return conflicts


def blocking_items(issues: list[dict], conflicts: list[dict]) -> list[dict]:
    """Các vấn đề chặn việc xác nhận lịch hẹn."""
    return [item for item in [*issues, *conflicts] if item.get("level") == "blocking"]


def conflict_summary(items: list[dict]) -> str:
    """Câu tóm tắt ngắn gọn cho thông báo lỗi."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]["message"]
    return f"{items[0]['message']} Và {len(items) - 1} cảnh báo khác."
