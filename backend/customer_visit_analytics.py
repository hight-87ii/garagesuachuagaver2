"""Thống kê lượt khách đến garage bằng truy vấn cố định, không phụ thuộc LLM."""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta

from .ai_service import AIResult, ai_service
from .permissions import has_permission
from .timeutil import VN_TZ, to_utc_iso, vn_text

DEFAULT_LIMIT = 10
MAX_LIMIT = 20
DENIED = "Bạn không có quyền xem thống kê khách hàng toàn hệ thống."
DEFINITION = (
    "Mỗi phiếu sửa chữa hợp lệ có thời điểm tiếp nhận thực tế được tính là một lần đến garage; "
    "phiếu đã hủy và lịch hẹn chưa tiếp nhận không được tính."
)

# Chuẩn hóa timestamp lưu đúng UTC; timestamp legacy không timezone được coi là giờ Việt Nam.
UTC_RECEIVED_SQL = """
CASE
  WHEN ro.received_at IS NULL OR trim(ro.received_at) = '' THEN NULL
  WHEN upper(trim(ro.received_at)) LIKE '%Z'
    OR substr(trim(ro.received_at), -6, 1) IN ('+', '-')
    THEN strftime('%Y-%m-%dT%H:%M:%SZ', ro.received_at)
  ELSE strftime('%Y-%m-%dT%H:%M:%SZ', ro.received_at, '-7 hours')
END
""".strip()


@dataclass(frozen=True)
class VisitQuery:
    start: datetime
    end: datetime
    period_label: str
    limit: int = DEFAULT_LIMIT
    requested_limit: int = DEFAULT_LIMIT
    min_visits: int = 1
    exact_visits: int | None = None


@dataclass(frozen=True)
class VisitReply:
    result: AIResult
    sources: list[dict]
    analytics: dict | None


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFD", value.casefold().replace("đ", "d"))
    return "".join(char for char in text if unicodedata.category(char) != "Mn")


def is_customer_visit_question(question: str) -> bool:
    text = _fold(question)
    customer = bool(re.search(r"\bkhach(?: hang)?\b", text))
    visit = any(term in text for term in (
        "den garage", "toi garage", "hay toi", "quay lai", "thuong xuyen",
        "khach den", "lan tiep nhan", "nhieu nhat", "su dung dich vu sua chua", "top ",
    )) or bool(re.search(r"\bden\b.*\b(?:lan|garage)\b", text))
    return customer and visit


def _subtract_months(moment: datetime, months: int) -> datetime:
    month_index = moment.year * 12 + moment.month - 1 - months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    next_month = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=moment.tzinfo)
    last_day = (next_month - timedelta(days=1)).day
    return moment.replace(year=year, month=month, day=min(moment.day, last_day))


def parse_customer_visit_question(question: str, now: datetime | None = None) -> VisitQuery | None:
    if not is_customer_visit_question(question):
        return None
    text = _fold(question)
    current = (now or datetime.now(VN_TZ)).astimezone(VN_TZ).replace(microsecond=0)
    if "thang nay" in text:
        start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        label = "tháng này"
    elif "nam nay" in text:
        start = current.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        label = "năm nay"
    else:
        month_match = re.search(r"\b(6|12)\s*thang\s*(?:qua|gan day|tro lai)\b", text)
        months = int(month_match.group(1)) if month_match else 12
        start = _subtract_months(current, months)
        label = f"{months} tháng qua"

    top_match = re.search(r"\btop\s*(\d+)\b", text)
    requested_limit = int(top_match.group(1)) if top_match else DEFAULT_LIMIT
    limit = min(MAX_LIMIT, max(1, requested_limit))
    exact_match = re.search(r"\b(?:dung|chinh xac)\s*(\d+)\s*lan\b", text)
    minimum_match = re.search(r"\b(?:it nhat|tu)\s*(\d+)\s*lan\b", text)
    exact = max(1, int(exact_match.group(1))) if exact_match else None
    minimum = exact if exact is not None else max(1, int(minimum_match.group(1))) if minimum_match else 1
    return VisitQuery(start, current, label, limit, requested_limit, minimum, exact)


def _has_global_access(user: dict) -> bool:
    role = str(user.get("role") or "")
    return all(has_permission(role, permission) for permission in
               ("customer.view", "customer.view_all", "repair_orders"))


def _query(db: sqlite3.Connection, plan: VisitQuery) -> dict:
    start_utc, end_utc = to_utc_iso(plan.start), to_utc_iso(plan.end)
    comparison = "= :visit_threshold" if plan.exact_visits is not None else ">= :visit_threshold"
    rows = db.execute(f"""
        WITH eligible AS (
            SELECT ro.id, ro.code, ro.customer_id, {UTC_RECEIVED_SQL} AS received_utc
            FROM repair_orders AS ro
            JOIN customers AS valid_customer ON valid_customer.id = ro.customer_id
            WHERE ro.customer_id IS NOT NULL
              AND ro.status <> 'Đã hủy'
              AND COALESCE(ro.status_code, '') <> 'CANCELLED'
              AND {UTC_RECEIVED_SQL} >= :start_time
              AND {UTC_RECEIVED_SQL} < :end_time
        ), aggregated AS (
            SELECT customer_id, COUNT(DISTINCT id) AS visit_count,
                   MIN(received_utc) AS first_visit, MAX(received_utc) AS last_visit
            FROM eligible
            GROUP BY customer_id
            HAVING COUNT(DISTINCT id) {comparison}
        )
        SELECT a.customer_id, c.name AS customer_name, a.visit_count,
               a.first_visit, a.last_visit,
               (SELECT json_group_array(json_object(
                    'id', e.id, 'code', e.code, 'received_at', e.received_utc
                )) FROM (SELECT id, code, received_utc FROM eligible
                         WHERE customer_id = a.customer_id
                         ORDER BY received_utc, id) e) AS repair_orders
        FROM aggregated a
        JOIN customers c ON c.id = a.customer_id
        ORDER BY a.visit_count DESC, a.customer_id ASC
        LIMIT :result_limit
    """, {"start_time": start_utc, "end_time": end_utc,
           "visit_threshold": plan.min_visits, "result_limit": plan.limit}).fetchall()

    quality = db.execute(f"""
        SELECT
          SUM(CASE WHEN ro.received_at IS NOT NULL AND trim(ro.received_at) <> ''
                    AND {UTC_RECEIVED_SQL} >= :start_time AND {UTC_RECEIVED_SQL} < :end_time
                    AND (ro.status = 'Đã hủy' OR ro.status_code = 'CANCELLED') THEN 1 ELSE 0 END)
              AS excluded_cancelled_orders,
          SUM(CASE WHEN (ro.received_at IS NULL OR trim(ro.received_at) = '')
                    AND ro.status <> 'Đã hủy' AND COALESCE(ro.status_code, '') <> 'CANCELLED'
                   THEN 1 ELSE 0 END) AS orders_missing_received_at,
          SUM(CASE WHEN ro.received_at IS NOT NULL AND trim(ro.received_at) <> ''
                    AND {UTC_RECEIVED_SQL} >= :start_time AND {UTC_RECEIVED_SQL} < :end_time
                    AND ro.status <> 'Đã hủy' AND COALESCE(ro.status_code, '') <> 'CANCELLED'
                    AND ro.customer_id IS NULL THEN 1 ELSE 0 END) AS orders_missing_customer_id,
          SUM(CASE WHEN ro.received_at IS NOT NULL AND trim(ro.received_at) <> ''
                    AND {UTC_RECEIVED_SQL} >= :start_time AND {UTC_RECEIVED_SQL} < :end_time
                    AND ro.status <> 'Đã hủy' AND COALESCE(ro.status_code, '') <> 'CANCELLED'
                    AND ro.customer_id IS NOT NULL AND c.id IS NULL THEN 1 ELSE 0 END)
              AS orders_invalid_customer_id
        FROM repair_orders ro LEFT JOIN customers c ON c.id = ro.customer_id
    """, {"start_time": start_utc, "end_time": end_utc}).fetchone()

    results = []
    sources = []
    for row in rows:
        orders = json.loads(row["repair_orders"] or "[]")
        results.append({"customer_id": row["customer_id"], "customer_name": row["customer_name"],
                        "visit_count": row["visit_count"],
                        "repair_order_ids": [order["id"] for order in orders],
                        "repair_order_codes": [order["code"] for order in orders],
                        "first_visit": row["first_visit"], "last_visit": row["last_visit"]})
        sources.extend({"type": "repair_order", "id": order["id"],
                        "label": f"Phiếu sửa chữa {order['code']}",
                        "date": str(order["received_at"] or "")[:10]} for order in orders)
    analytics = {
        "metric": "customer_visit_count",
        "period": {"start": plan.start.isoformat(), "end": plan.end.isoformat(),
                   "timezone": "Asia/Ho_Chi_Minh", "bounds": "[start,end)"},
        "definition": DEFINITION, "limit": plan.limit, "requested_limit": plan.requested_limit,
        "minimum_visits": plan.min_visits, "exact_visits": plan.exact_visits,
        "results": results,
        "data_quality": {key: int(quality[key] or 0) for key in (
            "excluded_cancelled_orders", "orders_missing_received_at",
            "orders_missing_customer_id", "orders_invalid_customer_id")},
        "data_quality_note": "Phiếu thiếu received_at được đếm trên toàn bộ dữ liệu vì không thể xác định kỳ thống kê.",
    }
    return {"analytics": analytics, "sources": sources}


def _render(plan: VisitQuery, analytics: dict) -> str:
    results, quality = analytics["results"], analytics["data_quality"]
    condition = (f"đúng {plan.exact_visits} lần" if plan.exact_visits is not None
                 else f"ít nhất {plan.min_visits} lần")
    title = f"Khách hàng đến garage nhiều nhất trong {plan.period_label} ({condition})"
    lines = [f"**{title}**", ""]
    if results:
        for row in results:
            codes = ", ".join(row["repair_order_codes"])
            lines.append(f"- {row['customer_name']} (mã khách {row['customer_id']}) — "
                         f"{row['visit_count']} lần tiếp nhận. Phiếu: {codes}.")
    else:
        lines.append("Không tìm thấy bản ghi phù hợp trong khoảng thời gian và điều kiện yêu cầu.")
    lines.extend(["", f"Kỳ thống kê: {vn_text(to_utc_iso(plan.start))} đến "
                  f"{vn_text(to_utc_iso(plan.end))} (giờ Việt Nam, khoảng [bắt đầu, kết thúc)).",
                  f"Định nghĩa: {DEFINITION}"])
    if plan.requested_limit > MAX_LIMIT:
        lines.append(f"Giới hạn: yêu cầu Top {plan.requested_limit} đã được giới hạn còn Top {MAX_LIMIT}.")
    issues = []
    if quality["orders_missing_received_at"]:
        issues.append(f"{quality['orders_missing_received_at']} phiếu thiếu received_at trên toàn bộ dữ liệu")
    if quality["orders_missing_customer_id"]:
        issues.append(f"{quality['orders_missing_customer_id']} phiếu trong kỳ thiếu customer_id")
    if quality["orders_invalid_customer_id"]:
        issues.append(f"{quality['orders_invalid_customer_id']} phiếu trong kỳ có customer_id không hợp lệ")
    if quality["excluded_cancelled_orders"]:
        issues.append(f"{quality['excluded_cancelled_orders']} phiếu hủy trong kỳ đã bị loại")
    if issues:
        lines.append("Chất lượng dữ liệu: " + "; ".join(issues) + ".")
    return "\n".join(lines)


def answer_customer_visit_question(db: sqlite3.Connection, question: str, user: dict,
                                   now: datetime | None = None) -> VisitReply | None:
    plan = parse_customer_visit_question(question, now)
    if plan is None:
        return None
    # Không được thực hiện bất kỳ truy vấn nghiệp vụ nào trước kiểm tra quyền.
    if not _has_global_access(user):
        return VisitReply(AIResult(DENIED, "denied", "local", ai_service.model), [], None)
    payload = _query(db, plan)
    analytics = payload["analytics"]
    status = "success" if analytics["results"] else "no_data"
    missing = []
    if analytics["data_quality"]["orders_missing_received_at"]:
        missing.append("Phiếu thiếu thời điểm tiếp nhận thực tế")
    result = AIResult(_render(plan, analytics), status, "local", ai_service.model,
                      status == "no_data", missing)
    return VisitReply(result, payload["sources"], analytics)
