"""Tra cứu lịch hẹn bằng ý định và SQL cố định, có kiểm tra RBAC trước truy vấn dữ liệu.

Trạng thái thật trong schema: Đang chờ, Đã xác nhận, Đã tiếp nhận, Đã hủy.
Đang sửa/hoàn thành chỉ được suy ra từ ``repair_orders`` liên kết; schema chưa có
``no_show``, ca làm việc, chi nhánh hoặc bộ phận.
"""

from __future__ import annotations

import sqlite3
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .ai_service import AIResult, ai_service
from .core.access import customer_scope_id
from .permissions import has_permission
from .timeutil import VN_TZ, now_utc_iso, to_utc_iso, vn_text

PENDING = "Đang chờ"
CONFIRMED = "Đã xác nhận"
CHECKED_IN = "Đã tiếp nhận"
CANCELLED = "Đã hủy"
REAL_STATUSES = (PENDING, CONFIRMED, CHECKED_IN, CANCELLED)
ACTIVE_STATUSES = (PENDING, CONFIRMED, CHECKED_IN)
LIMIT = 20
DENIED = "Bạn không có quyền truy cập dữ liệu lịch hẹn này. Vui lòng liên hệ quản trị viên để được cấp quyền phù hợp."
NO_DATA = "Không có lịch hẹn phù hợp với điều kiện và phạm vi bạn được phép xem."


@dataclass(frozen=True)
class AppointmentFilters:
    statuses: tuple[str, ...] = ()
    period_from: str | None = None
    period_to: str | None = None
    period_label: str = "Toàn bộ thời gian"
    wants_list: bool = False
    wants_statistics: bool = True
    overdue: bool = False
    no_technician: bool = False
    missing_repair_order: bool = False
    repair_state: str | None = None
    comparison_today_yesterday: bool = False
    active_only: bool = False
    assigned_to_me: bool = False
    time_from: str | None = None
    time_to: str | None = None
    limit: int = LIMIT
    upcoming_only: bool = False
    reception_delay_min: int | None = None


def _normalize(value: str) -> str:
    return ai_service._normalize_vi(value)


def is_appointment_question(question: str) -> bool:
    text = _normalize(question)
    return any(term in text for term in (
        "lich hen", "lich dat", "cuoc hen", "cho xac nhan", "chua xac nhan",
        "da xac nhan", "da tiep nhan", "da duoc tiep nhan", "tiep nhan xe", "xe da den garage",
        "qua gio", "cho xu ly",
    ))


def _period(text: str) -> tuple[str | None, str | None, str]:
    now = datetime.now(VN_TZ)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if "ngay mai" in text or "mai co" in text:
        start = today + timedelta(days=1)
        return to_utc_iso(start), to_utc_iso(start + timedelta(days=1)), "Ngày mai"
    if "hom qua" in text:
        start = today - timedelta(days=1)
        return to_utc_iso(start), to_utc_iso(today), "Hôm qua"
    if "tuan nay" in text:
        start = today - timedelta(days=today.weekday())
        return to_utc_iso(start), to_utc_iso(start + timedelta(days=7)), "Tuần này"
    if "hom nay" in text:
        return to_utc_iso(today), to_utc_iso(today + timedelta(days=1)), "Hôm nay"
    return None, None, "Toàn bộ thời gian"


def classify_appointment_question(question: str) -> AppointmentFilters:
    text = _normalize(question)
    statuses = []
    if any(term in text for term in ("chua xac nhan", "cho xac nhan", "chua co nhan vien xac nhan", "cho xu ly")):
        statuses.append(PENDING)
    if "da xac nhan" in text or "xac nhan nhung" in text:
        statuses.append(CONFIRMED)
    not_checked_in = any(term in text for term in ("chua tiep nhan", "cho tiep nhan"))
    if not not_checked_in and any(term in text for term in ("da tiep nhan", "da duoc tiep nhan", "tiep nhan xe", "xe da den garage", "da den garage")):
        statuses.append(CHECKED_IN)
    if any(term in text for term in ("da huy", "lich huy")):
        statuses.append(CANCELLED)
    repair_state = None
    if any(term in text for term in ("dang sua", "dang sua chua")):
        repair_state = "in_progress"
    elif any(term in text for term in ("da hoan thanh", "hoan thanh")):
        repair_state = "completed"
    wants_list = any(term in text for term in ("liet ke", "nhung lich", "lich hen nao", "lich nao",
                                                 "cac lich", "nhung xe", "xe nao"))
    wants_statistics = not wants_list or any(term in text for term in ("bao nhieu", "thong ke", "tong so", "so sanh"))
    period_from, period_to, period_label = _period(text)
    comparison = "so sanh" in text and "hom nay" in text and "hom qua" in text
    active_only = not statuses and repair_state is None
    limit_match = re.search(r"\b(\d{1,2})\s+lich", text)
    hour_match = re.search(r"tu\s+(\d{1,2})\s*(?:gio|h)\s+den\s+(\d{1,2})\s*(?:gio|h)", text)
    delay_match = re.search(r"tre\s+hon\s+(\d{1,3})\s*phut", text)
    return AppointmentFilters(
        statuses=tuple(dict.fromkeys(statuses)), period_from=period_from, period_to=period_to,
        period_label=period_label, wants_list=wants_list, wants_statistics=wants_statistics,
        overdue="qua gio" in text and any(term in text for term in ("chua tiep nhan", "cho tiep nhan", "qua gio")),
        no_technician=any(term in text for term in ("chua duoc phan cong", "chua co ky thuat vien", "chua phan cong ky thuat vien")),
        missing_repair_order=any(term in text for term in ("chua co phieu sua chua", "chua co phieu tiep nhan")),
        repair_state=repair_state, comparison_today_yesterday=comparison,
        active_only=active_only, assigned_to_me=any(term in text for term in ("toi phu trach", "do toi phu trach")),
        time_from=f"{int(hour_match.group(1)):02d}:00" if hour_match else None,
        time_to=f"{int(hour_match.group(2)):02d}:00" if hour_match else None,
        limit=min(50, max(1, int(limit_match.group(1)))) if limit_match else LIMIT,
        upcoming_only="gan nhat" in text,
        reception_delay_min=int(delay_match.group(1)) if delay_match else None,
    )


def _has(user: dict, permission: str) -> bool:
    return has_permission(str(user.get("role") or ""), permission)


def _permissions_ok(user: dict, filters: AppointmentFilters) -> bool:
    required = {"appointment.view", "appointment.view_status"}
    if filters.wants_statistics:
        required.add("appointment.view_statistics")
    if filters.wants_list:
        required.add("appointment.view_details")
    if user.get("role") != "Khách hàng":
        required.add("appointment.view_all")
    return all(_has(user, permission) for permission in required)


def _where(filters: AppointmentFilters, scope: int | None, user: dict) -> tuple[str, list[Any]]:
    clauses = ["1=1"]
    params: list[Any] = []
    if scope is not None:
        clauses.append("(a.customer_id=? OR (a.customer_id IS NULL AND EXISTS(SELECT 1 FROM vehicles sv WHERE sv.id=a.vehicle_id AND sv.customer_id=?)))")
        params.extend((scope, scope))
    if filters.statuses:
        clauses.append("a.status IN (" + ",".join("?" for _ in filters.statuses) + ")")
        params.extend(filters.statuses)
    elif filters.active_only:
        clauses.append("a.status<>'Đã hủy'")
    if filters.period_from:
        clauses.append("a.appointment_at>=? AND a.appointment_at<?")
        params.extend((filters.period_from, filters.period_to))
    if filters.time_from:
        clauses.append("time(a.appointment_at,'+7 hours')>=? AND time(a.appointment_at,'+7 hours')<=?")
        params.extend((filters.time_from, filters.time_to))
    if filters.upcoming_only:
        clauses.append("a.appointment_at>=?")
        params.append(now_utc_iso())
    if filters.overdue:
        clauses.append("a.appointment_at<? AND a.status IN ('Đang chờ','Đã xác nhận')")
        params.append(now_utc_iso())
    if filters.no_technician:
        clauses.append("TRIM(COALESCE((SELECT ro.technician FROM repair_orders ro WHERE ro.id=a.repair_order_id),a.technician,''))='' ")
    if filters.missing_repair_order:
        clauses.append("a.repair_order_id IS NULL")
    if filters.reception_delay_min is not None:
        clauses.append("EXISTS(SELECT 1 FROM repair_orders dro WHERE dro.id=a.repair_order_id "
                       "AND dro.received_at IS NOT NULL AND (julianday(dro.received_at)-julianday(a.appointment_at))*1440>?)")
        params.append(filters.reception_delay_min)
    if filters.repair_state == "in_progress":
        clauses.append("a.status='Đã tiếp nhận' AND EXISTS(SELECT 1 FROM repair_orders ro WHERE ro.id=a.repair_order_id AND ro.status_code IN ('INSPECTING','QUOTED','APPROVED','IN_PROGRESS','WAITING_FOR_PARTS','ON_HOLD'))")
    elif filters.repair_state == "completed":
        clauses.append("a.status='Đã tiếp nhận' AND EXISTS(SELECT 1 FROM repair_orders ro WHERE ro.id=a.repair_order_id AND ro.status_code IN ('COMPLETED','DELIVERED'))")
    if filters.assigned_to_me:
        clauses.append("(a.technician_id=? OR LOWER(TRIM(a.technician))=LOWER(TRIM(?)))")
        params.extend((user["id"], user.get("full_name", "")))
    return " AND ".join(clauses), params


def count_appointments_by_status(db: sqlite3.Connection, filters: AppointmentFilters,
                                 scope: int | None, user: dict) -> dict[str, int]:
    where, params = _where(filters, scope, user)
    rows = db.execute(f"SELECT a.status,COUNT(*) count FROM appointments a WHERE {where} GROUP BY a.status", params).fetchall()
    return {row["status"]: int(row["count"]) for row in rows}


def get_appointments_by_status(db: sqlite3.Connection, filters: AppointmentFilters,
                               scope: int | None, user: dict) -> list[dict]:
    where, params = _where(filters, scope, user)
    rows = db.execute(
        f"""SELECT a.id,a.appointment_at,a.status,a.customer_name,a.plate,a.service,
                   a.technician,a.repair_order_id
            FROM appointments a WHERE {where}
            ORDER BY a.appointment_at,a.id LIMIT ?""", (*params, filters.limit + 1),
    ).fetchall()
    return [dict(row) for row in rows]


def get_pending_confirmation_appointments(db, filters, scope, user):
    return get_appointments_by_status(db, AppointmentFilters(**{**filters.__dict__, "statuses": (PENDING,)}), scope, user)


def get_confirmed_appointments(db, filters, scope, user):
    return get_appointments_by_status(db, AppointmentFilters(**{**filters.__dict__, "statuses": (CONFIRMED,)}), scope, user)


def get_checked_in_appointments(db, filters, scope, user):
    return get_appointments_by_status(db, AppointmentFilters(**{**filters.__dict__, "statuses": (CHECKED_IN,)}), scope, user)


def get_overdue_appointments(db, filters, scope, user):
    return get_appointments_by_status(db, AppointmentFilters(**{**filters.__dict__, "overdue": True}), scope, user)


def get_appointment_status_summary(db: sqlite3.Connection, filters: AppointmentFilters,
                                   scope: int | None, user: dict) -> dict[str, int]:
    return count_appointments_by_status(db, filters, scope, user)


def _count_period(db: sqlite3.Connection, start: datetime, end: datetime,
                  scope: int | None, user: dict) -> int:
    filters = AppointmentFilters(period_from=to_utc_iso(start), period_to=to_utc_iso(end), active_only=True)
    return sum(count_appointments_by_status(db, filters, scope, user).values())


def _applied_filters(filters: AppointmentFilters) -> str:
    values = [filters.period_label]
    if filters.statuses:
        values.append("trạng thái: " + ", ".join(filters.statuses))
    if filters.time_from:
        values.append(f"giờ hẹn từ {filters.time_from} đến {filters.time_to}")
    if filters.overdue:
        values.append("đã quá giờ và chưa tiếp nhận")
    if filters.no_technician:
        values.append("chưa phân công kỹ thuật viên")
    if filters.missing_repair_order:
        values.append("chưa có phiếu sửa chữa")
    if filters.reception_delay_min is not None:
        values.append(f"tiếp nhận trễ hơn {filters.reception_delay_min} phút")
    if filters.upcoming_only:
        values.append("lịch sắp tới gần nhất")
    return "; ".join(values)


def answer_appointment_question(db: sqlite3.Connection, question: str, user: dict):
    if not is_appointment_question(question):
        return None
    text = _normalize(question)
    filters = classify_appointment_question(question)
    if not _permissions_ok(user, filters):
        return AIResult(DENIED, "fallback", "local", ai_service.model), []
    if filters.time_from and not filters.period_from:
        return AIResult("Vui lòng cho biết ngày cụ thể (ví dụ hôm nay hoặc ngày mai) cho khoảng giờ cần lọc.",
                        "clarification", "local", ai_service.model, True, ["Ngày hẹn"]), []
    if filters.time_from and (filters.time_from > filters.time_to or int(filters.time_to[:2]) > 23):
        return AIResult("Khoảng giờ không hợp lệ; vui lòng nhập giờ bắt đầu và kết thúc trong cùng một ngày.",
                        "clarification", "local", ai_service.model, True, ["Khoảng giờ hợp lệ"]), []
    if any(term in text for term in ("ca lam viec", "ca hien tai")):
        return AIResult("Hệ thống hiện chưa lưu cấu hình ca làm việc nên không thể lọc chính xác theo ca.",
                        "clarification", "local", ai_service.model, True, ["Cấu hình ca làm việc"]), []
    if "chi nhanh" in text or "bo phan" in text:
        return AIResult("Hệ thống hiện chưa gắn lịch hẹn với chi nhánh hoặc bộ phận nên không thể lọc theo phạm vi này.",
                        "clarification", "local", ai_service.model, True, ["Chi nhánh hoặc bộ phận"]), []
    if any(term in text for term in ("no show", "khong den", "vang mat")):
        return AIResult("Hệ thống chưa có trạng thái khách không đến (no-show), nên không thể thống kê chính xác yêu cầu này.",
                        "clarification", "local", ai_service.model, True, ["Trạng thái no-show"]), []

    # Chỉ sau kiểm tra quyền mới xác định hồ sơ sở hữu và truy vấn lịch hẹn.
    scope = customer_scope_id(db, user)
    if filters.wants_list:
        asks_customer = "khach" in text
        asks_vehicle = any(term in text for term in (" xe", "xe ", "bien so"))
        if ((asks_customer and not _has(user, "customer.view")) or
                (asks_vehicle and not _has(user, "vehicle.view")) or
                ((asks_customer or asks_vehicle) and not _has(user, "customer_vehicle.view"))):
            return AIResult(DENIED, "fallback", "local", ai_service.model), []

    queried_at = datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M")
    if filters.comparison_today_yesterday:
        now = datetime.now(VN_TZ)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_count = _count_period(db, today, today + timedelta(days=1), scope, user)
        yesterday_count = _count_period(db, today - timedelta(days=1), today, scope, user)
        difference = today_count - yesterday_count
        direction = "nhiều hơn" if difference > 0 else "ít hơn" if difference < 0 else "bằng"
        content = (f"So sánh lịch hẹn đang hoạt động (không gồm lịch đã hủy):\n"
                   f"- Hôm nay: {today_count} lịch hẹn.\n- Hôm qua: {yesterday_count} lịch hẹn.\n"
                   f"- Hôm nay {direction} hôm qua {abs(difference)} lịch.\nDữ liệu truy vấn lúc {queried_at} (giờ Việt Nam).")
        return AIResult(content, "success", "local", ai_service.model), []

    if filters.wants_list:
        rows = get_appointments_by_status(db, filters, scope, user)
        if not rows:
            return AIResult(NO_DATA, "success", "local", ai_service.model), []
        invalid = [row for row in rows if row["status"] not in REAL_STATUSES]
        if invalid:
            return AIResult("Dữ liệu lịch hẹn có trạng thái không hợp lệ; cần quản trị viên kiểm tra trước khi trả lời.",
                            "no_data", "local", ai_service.model, True, ["Trạng thái lịch hẹn hợp lệ"]), []
        shown = rows[:filters.limit]
        can_relation = _has(user, "customer_vehicle.view")
        can_customer = can_relation and _has(user, "customer.view")
        can_vehicle = can_relation and _has(user, "vehicle.view")
        lines = [f"{filters.period_label}: có {len(rows) if len(rows) <= filters.limit else f'trên {filters.limit}'} lịch hẹn phù hợp.",
                 f"Điều kiện đã áp dụng: {_applied_filters(filters)}; giới hạn {filters.limit} kết quả."]
        for row in shown:
            fields = [f"LH-{row['id']:05d}", vn_text(row["appointment_at"]) or "Không rõ thời gian", row["status"]]
            if can_customer:
                fields.append(row["customer_name"])
            if can_vehicle:
                fields.append(row["plate"])
            lines.append(" · ".join(fields))
        lines.append(f"Dữ liệu truy vấn lúc {queried_at} (giờ Việt Nam).")
        sources = [{"type": "appointment", "id": row["id"], "label": f"LH-{row['id']:05d}",
                    "date": (vn_text(row["appointment_at"]) or "")[:10]} for row in shown]
        return AIResult("\n".join(lines), "success", "local", ai_service.model), sources

    counts = get_appointment_status_summary(db, filters, scope, user)
    if filters.statuses:
        lines = [f"{filters.period_label}:"]
        for status in filters.statuses:
            label = "Chưa xác nhận" if status == PENDING else f"{status}"
            lines.append(f"- {label}: {counts.get(status, 0)} lịch hẹn.")
    else:
        lines = [f"{filters.period_label} (không cộng lịch đã hủy vào tổng đang hoạt động):",
                 f"- Chưa xác nhận: {counts.get(PENDING, 0)} lịch hẹn.",
                 f"- Đã xác nhận: {counts.get(CONFIRMED, 0)} lịch hẹn.",
                 f"- Đã tiếp nhận xe: {counts.get(CHECKED_IN, 0)} lịch hẹn."]
        if CANCELLED in counts or "huy" in text:
            lines.append(f"- Đã hủy: {counts.get(CANCELLED, 0)} lịch hẹn.")
        lines.append(f"- Tổng đang hoạt động: {sum(counts.get(status, 0) for status in ACTIVE_STATUSES)} lịch hẹn.")
    lines.append(f"Dữ liệu truy vấn lúc {queried_at} (giờ Việt Nam).")
    return AIResult("\n".join(lines), "success", "local", ai_service.model), []
