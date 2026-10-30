"""Bộ lọc động có giới hạn cho AI.

Module chỉ biên dịch các entity, field, operator và sort được khai báo ở đây. Nội dung
chat không bao giờ trở thành tên bảng/cột hay mảnh SQL. Mọi giá trị đều truyền bằng tham số.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from .ai_service import AIResult, ai_service
from .core.access import customer_scope_id
from .permissions import has_permission
from .timeutil import VN_TZ, now_utc_iso, to_utc_iso, vn_text

Entity = Literal["invoice", "payment", "customer_debt", "vehicle", "repair_order", "service_usage"]
Operator = Literal["gt", "gte", "lt", "lte", "eq", "ne", "between", "in"]

MAX_RESULTS = 50
DEFAULT_LIMIT = 20
DENIED = "Bạn không có quyền truy cập hoặc lọc dữ liệu này. Vui lòng liên hệ quản trị viên để được cấp quyền phù hợp."
NO_DATA = "Không tìm thấy dữ liệu phù hợp với các điều kiện đã áp dụng."
ALLOWED_FIELDS: dict[str, set[str]] = {
    "invoice": {"code", "issued_at", "customer_id", "customer_name", "total_amount",
                "paid_amount", "outstanding_amount", "payment_status"},
    "payment": {"invoice_code", "payment_amount", "method", "paid_at"},
    "customer_debt": {"customer_code", "customer_name", "outstanding_amount"},
    "vehicle": {"make", "model", "year", "plate"},
    "repair_order": {"code", "plate", "status", "status_code", "total_amount",
                     "opened_at", "open_days", "part_id"},
    "service_usage": {"service_name", "usage_count"},
}


@dataclass(frozen=True)
class QueryCondition:
    field: str
    operator: Operator
    value: Any
    value_to: Any | None = None


@dataclass(frozen=True)
class SortSpec:
    field: str
    direction: Literal["asc", "desc"] = "desc"


@dataclass(frozen=True)
class QueryPlan:
    entity: Entity
    filters: tuple[QueryCondition, ...] = ()
    sort: SortSpec | None = None
    limit: int = DEFAULT_LIMIT
    date_from: str | None = None
    date_to: str | None = None
    date_label: str = "Toàn bộ thời gian"
    aggregate: Literal["list", "count"] = "list"
    fields: tuple[str, ...] = ()
    filter_logic: Literal["and", "or"] = "and"


def _normalize(value: str) -> str:
    return ai_service._normalize_vi(value)


def _entity(text: str) -> Entity | None:
    if "giao dich thanh toan" in text or "cac giao dich" in text:
        return "payment"
    if "khach hang" in text and any(term in text for term in ("cong no", "con no", "tong no")):
        return "customer_debt"
    if "hoa don" in text:
        return "invoice"
    if "phieu sua chua" in text or "phieu sua" in text or "cho phu tung" in text:
        return "repair_order"
    if "dich vu" in text and any(term in text for term in ("su dung nhieu", "pho bien", "nhieu nhat")):
        return "service_usage"
    if any(term in text for term in ("xe san xuat", "xe doi", "nam san xuat")):
        return "vehicle"
    return None


def is_dynamic_query(question: str) -> bool:
    text = _normalize(question)
    entity = _entity(text)
    if entity is None:
        return False
    dynamic_terms = ("tren ", "duoi ", "lon hon", "nho hon", "tro len", "tro xuong",
                     "tu ", "den ", "cao nhat", "thap nhat", "tang dan", "giam dan",
                     "gan nhat", "nhieu nhat", "qua ", "trong thang", "nam san xuat",
                     "truoc ngay", "sau ngay", "cho phu tung", "chua hoan thanh",
                     "su dung phu tung")
    return any(term in text for term in dynamic_terms)


def _has(user: dict, permission: str) -> bool:
    return has_permission(str(user.get("role") or ""), permission)


def _base_allowed(entity: Entity, user: dict) -> bool:
    role = user.get("role")
    if entity in ("invoice", "payment"):
        needed = {"invoice.view", "invoice.view_amount"}
        if role != "Khách hàng":
            needed.add("invoice.view_all")
    elif entity == "customer_debt":
        needed = {"customer.view", "invoice.view", "invoice.view_debt"}
        if role != "Khách hàng":
            needed |= {"customer.view_all", "invoice.view_all"}
    elif entity == "vehicle":
        needed = {"vehicle.view"}
        if role != "Khách hàng":
            needed.add("vehicle.view_all")
    elif entity == "repair_order":
        needed = {"repair_orders"}
    else:
        needed = {"reports", "services"}
    return all(_has(user, permission) for permission in needed)


def _money_number(raw: str, unit: str | None) -> int:
    number = float(raw.replace(",", "."))
    multiplier = 1
    if unit in ("ty",):
        multiplier = 1_000_000_000
    elif unit in ("trieu", "m"):
        multiplier = 1_000_000
    elif unit in ("nghin", "ngan", "k"):
        multiplier = 1_000
    return int(round(number * multiplier))


MONEY = r"(\d+(?:[.,]\d+)?)\s*(ty|trieu|nghin|ngan|k|m)?(?:\s*dong)?"


def _comparison(text: str, field: str) -> QueryCondition | None:
    between = re.search(rf"tu\s+{MONEY}\s+den\s+{MONEY}", text)
    if between:
        return QueryCondition(field, "between", _money_number(between.group(1), between.group(2)),
                              _money_number(between.group(3), between.group(4)))
    patterns: tuple[tuple[str, Operator], ...] = (
        (rf"(?:lon hon|tren)\s+hoac\s+bang\s+{MONEY}", "gte"),
        (rf"(?:nho hon|duoi)\s+hoac\s+bang\s+{MONEY}", "lte"),
        (rf"(?:tu\s+)?{MONEY}\s+tro len", "gte"),
        (rf"(?:tu\s+)?{MONEY}\s+tro xuong", "lte"),
        (rf"(?:tren|lon hon|cao hon)\s+{MONEY}", "gt"),
        (rf"(?:duoi|nho hon|thap hon)\s+{MONEY}", "lt"),
        (rf"(?:khong qua|toi da)\s+{MONEY}", "lte"),
        (rf"(?:bang|dung)\s+{MONEY}", "eq"),
        (rf"(?:khac)\s+{MONEY}", "ne"),
    )
    for pattern, operator in patterns:
        match = re.search(pattern, text)
        if match:
            return QueryCondition(field, operator, _money_number(match.group(1), match.group(2)))
    return None


def _date_range(text: str, *, date_field: str = "issued_at") -> tuple[str | None, str | None, str]:
    now = datetime.now(VN_TZ)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if "hom nay" in text:
        return to_utc_iso(today), to_utc_iso(today + timedelta(days=1)), "Hôm nay"
    if "thang nay" in text:
        start = today.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return to_utc_iso(start), to_utc_iso(end), "Tháng này"
    if "tuan nay" in text:
        start = today - timedelta(days=today.weekday())
        return to_utc_iso(start), to_utc_iso(start + timedelta(days=7)), "Tuần này"
    def parsed(raw: str) -> datetime | None:
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=VN_TZ)
            except ValueError:
                pass
        return None
    ranged = re.search(r"tu\s+ngay\s+(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})\s+den\s+ngay\s+(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})", text)
    if ranged:
        start, end = parsed(ranged.group(1)), parsed(ranged.group(2))
        if start and end and start <= end:
            return to_utc_iso(start), to_utc_iso(end + timedelta(days=1)), f"Từ {ranged.group(1)} đến {ranged.group(2)}"
    before = re.search(r"truoc\s+ngay\s+(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})", text)
    if before and (end := parsed(before.group(1))):
        return None, to_utc_iso(end), f"Trước ngày {before.group(1)}"
    after = re.search(r"sau\s+ngay\s+(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})", text)
    if after and (start := parsed(after.group(1))):
        return to_utc_iso(start + timedelta(days=1)), None, f"Sau ngày {after.group(1)}"
    return None, None, "Toàn bộ thời gian"


def _limit(text: str, entity: Entity) -> int:
    nouns = {"invoice": "hoa don", "payment": "giao dich", "repair_order": "phieu",
             "vehicle": "xe", "customer_debt": "khach hang", "service_usage": "dich vu"}
    match = re.search(rf"\b(\d{{1,3}})\s+{nouns[entity]}\b", text)
    return min(MAX_RESULTS, max(1, int(match.group(1)))) if match else DEFAULT_LIMIT


def _invoice_money_field(text: str) -> str:
    if any(term in text for term in ("con no", "cong no", "so tien con no", "outstanding")):
        return "outstanding_amount"
    if any(term in text for term in ("so tien da thanh toan", "tien da thu", "tong da thu", "da thu tren", "da thu duoi")):
        return "paid_amount"
    return "total_amount"


def compile_query_plan(db: sqlite3.Connection, question: str, user: dict) -> QueryPlan | None:
    """Chuyển câu hỏi thành plan chỉ gồm field/operator đã cho phép; không tạo SQL."""
    text = _normalize(question)
    entity = _entity(text)
    if entity is None or not is_dynamic_query(question):
        return None
    if any(term in text for term in ("khach hang khac", "nguoi khac", "khach khac", "ai khac", "cua nguoi khac")):
        if not _has(user, "invoice.view_all"):
            return QueryPlan(entity, (QueryCondition("__denied__", "eq", True),))
    if not _base_allowed(entity, user):
        return QueryPlan(entity, (QueryCondition("__denied__", "eq", True),))
    date_from, date_to, date_label = _date_range(text)
    aggregate: Literal["list", "count"] = "count" if "bao nhieu" in text and "liet ke" not in text else "list"
    limit = _limit(text, entity)
    filters: list[QueryCondition] = []
    sort = None

    if entity == "invoice":
        money_field = _invoice_money_field(text)
        condition = _comparison(text, money_field)
        if condition:
            filters.append(condition)
        statuses = []
        if "chua thanh toan" in text:
            statuses.append("unpaid")
        if "thanh toan mot phan" in text:
            statuses.append("partial")
        if "da thanh toan" in text and "chua thanh toan" not in text:
            statuses.append("paid")
        if "da huy" in text:
            statuses.append("cancelled")
        if statuses:
            filters.append(QueryCondition("payment_status", "in", tuple(statuses)))
        for row in db.execute("SELECT id,name FROM customers WHERE status='active' ORDER BY length(name) DESC").fetchall():
            if _normalize(row["name"]) in text:
                if not _has(user, "customer.view"):
                    filters.append(QueryCondition("__denied__", "eq", True))
                else:
                    filters.append(QueryCondition("customer_id", "eq", int(row["id"])))
                break
        if money_field == "outstanding_amount" and not _has(user, "invoice.view_debt"):
            filters.append(QueryCondition("__denied__", "eq", True))
        direction = "asc" if any(term in text for term in ("tang dan", "thap nhat", "thap den cao")) else "desc"
        sort = SortSpec(money_field if any(term in text for term in ("cao nhat", "thap nhat", "giam dan", "tang dan", "cao xuong thap")) else "issued_at", direction)
        fields = ("code", "issued_at", "customer_name", "total_amount", "paid_amount", "outstanding_amount", "payment_status")
    elif entity == "payment":
        condition = _comparison(text, "payment_amount")
        if condition:
            filters.append(condition)
        sort = SortSpec("payment_amount" if any(term in text for term in ("cao nhat", "thap nhat", "giam dan", "tang dan")) else "paid_at",
                        "asc" if any(term in text for term in ("tang dan", "thap nhat")) else "desc")
        fields = ("invoice_code", "payment_amount", "method", "paid_at")
    elif entity == "customer_debt":
        condition = _comparison(text, "outstanding_amount")
        if condition:
            filters.append(condition)
        sort = SortSpec("outstanding_amount", "asc" if "tang dan" in text else "desc")
        fields = ("customer_code", "customer_name", "outstanding_amount")
    elif entity == "vehicle":
        year_range = re.search(r"tu\s+(?:nam\s+)?(19\d{2}|20\d{2}|2100)\s+den\s+(?:nam\s+)?(19\d{2}|20\d{2}|2100)", text)
        if year_range:
            filters.append(QueryCondition("year", "between", int(year_range.group(1)), int(year_range.group(2))))
        sort = SortSpec("year", "asc" if "tang dan" in text else "desc")
        fields = ("make", "model", "year", "plate")
    elif entity == "repair_order":
        condition = _comparison(text, "total_amount")
        if condition:
            filters.append(condition)
        days = re.search(r"qua\s+(\d{1,3})\s+ngay", text)
        if days:
            filters.append(QueryCondition("open_days", "gt", int(days.group(1))))
        statuses = []
        if "cho phu tung" in text:
            statuses.append("WAITING_FOR_PARTS")
        if "chua hoan thanh" in text:
            statuses.extend(("RECEIVED", "INSPECTING", "QUOTED", "APPROVED", "IN_PROGRESS", "WAITING_FOR_PARTS", "ON_HOLD"))
        if statuses:
            filters.append(QueryCondition("status_code", "in", tuple(dict.fromkeys(statuses))))
        found_part = False
        for row in db.execute("SELECT id,code,name FROM parts WHERE active=1 ORDER BY length(name) DESC").fetchall():
            if _normalize(row["name"]) in text or _normalize(row["code"]) in text:
                filters.append(QueryCondition("part_id", "eq", int(row["id"])))
                found_part = True
                break
        if "su dung phu tung" in text and not found_part:
            filters.append(QueryCondition("__missing_part__", "eq", True))
        sort = SortSpec("total_amount" if any(term in text for term in ("cao nhat", "giam dan")) else "opened_at", "desc")
        fields = ("code", "plate", "status", "total_amount", "opened_at")
    else:
        sort = SortSpec("usage_count", "desc")
        fields = ("service_name", "usage_count")
    return QueryPlan(entity, tuple(filters), sort, limit, date_from, date_to, date_label,
                     aggregate, fields, "or" if " hoac " in text else "and")


def _sql_condition(expression: str, condition: QueryCondition) -> tuple[str, list[Any]]:
    if condition.operator == "between":
        return f"{expression} BETWEEN ? AND ?", [condition.value, condition.value_to]
    if condition.operator == "in":
        values = tuple(condition.value)
        return f"{expression} IN ({','.join('?' for _ in values)})", list(values)
    symbol = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "eq": "=", "ne": "<>"}[condition.operator]
    return f"{expression} {symbol} ?", [condition.value]


def _money(value: int) -> str:
    return f"{int(value):,} VNĐ".replace(",", ".")


def _condition_text(condition: QueryCondition) -> str:
    names = {"total_amount": "tổng tiền", "paid_amount": "tiền đã thanh toán",
             "outstanding_amount": "tiền còn nợ", "payment_amount": "giá trị giao dịch",
             "year": "năm sản xuất", "open_days": "số ngày đang mở",
             "payment_status": "trạng thái", "customer_id": "khách hàng",
             "status_code": "trạng thái phiếu", "part_id": "phụ tùng"}
    operators = {"gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "eq": "=", "ne": "≠"}
    name = names.get(condition.field, condition.field)
    if condition.operator == "between":
        values = (f"{condition.value}–{condition.value_to}" if condition.field == "year" else
                  f"{_money(condition.value)} đến {_money(condition.value_to)}")
        return f"{name} trong khoảng {values}"
    if condition.operator == "in":
        status_names = {"unpaid": "chưa thanh toán", "partial": "thanh toán một phần",
                        "paid": "đã thanh toán", "cancelled": "đã hủy"}
        return f"{name} thuộc {', '.join(status_names.get(str(v), str(v)) for v in condition.value)}"
    value = condition.value if condition.field in ("year", "open_days", "customer_id", "status_code", "part_id") else _money(condition.value)
    return f"{name} {operators.get(condition.operator, condition.operator)} {value}"


def _invoice_rows(db: sqlite3.Connection, plan: QueryPlan, user: dict) -> list[dict]:
    paid = "COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id=i.id AND p.status='completed'),0)"
    outstanding = f"MAX(i.total-({paid}),0)"
    sql = f"""SELECT i.id,i.code,i.total,i.paid_amount cached_paid,i.status stored_status,i.issued_at,
                     ro.customer_id,c.name customer_name,{paid} paid_actual,{outstanding} remaining
              FROM invoices i JOIN repair_orders ro ON ro.id=i.repair_order_id
              LEFT JOIN customers c ON c.id=ro.customer_id WHERE 1=1"""
    params: list[Any] = []
    asks_cancelled = any(condition.field == "payment_status" and "cancelled" in condition.value for condition in plan.filters)
    if not asks_cancelled:
        sql += " AND i.status<>'Đã hủy'"
    scope = customer_scope_id(db, user)
    if scope is not None:
        sql += " AND ro.customer_id=?"
        params.append(scope)
    predicates: list[str] = []
    predicate_params: list[Any] = []
    for condition in (condition for condition in plan.filters if condition.field != "payment_status"):
        expression = {"total_amount": "i.total", "paid_amount": paid,
                      "outstanding_amount": outstanding, "customer_id": "ro.customer_id"}.get(condition.field)
        if expression:
            fragment, values = _sql_condition(expression, condition)
            predicates.append(fragment)
            predicate_params.extend(values)
    status_conditions = next((condition.value for condition in plan.filters if condition.field == "payment_status"), ())
    if status_conditions:
        pieces = []
        if "unpaid" in status_conditions:
            pieces.append(f"({paid})=0 AND i.total>0 AND i.status<>'Đã hủy'")
        if "partial" in status_conditions:
            pieces.append(f"({paid})>0 AND ({paid})<i.total AND i.status<>'Đã hủy'")
        if "paid" in status_conditions:
            pieces.append(f"({paid})>=i.total AND i.status<>'Đã hủy'")
        if "cancelled" in status_conditions:
            pieces.append("i.status='Đã hủy'")
        predicates.append("(" + ") OR (".join(pieces) + ")")
    if predicates:
        connector = " OR " if plan.filter_logic == "or" else " AND "
        sql += " AND (" + connector.join(f"({predicate})" for predicate in predicates) + ")"
        params.extend(predicate_params)
    if plan.date_from:
        sql += " AND i.issued_at>=?"
        params.append(plan.date_from)
    if plan.date_to:
        sql += " AND i.issued_at<?"
        params.append(plan.date_to)
    sort_expr = {"total_amount": "i.total", "paid_amount": paid,
                 "outstanding_amount": outstanding, "issued_at": "i.issued_at"}[plan.sort.field]
    sql += f" ORDER BY {sort_expr} {plan.sort.direction.upper()},i.id DESC LIMIT ?"
    params.append(100_000 if plan.aggregate == "count" else plan.limit + 1)
    return [dict(row) for row in db.execute(sql, params).fetchall()]


def _derived_status(row: dict) -> str:
    if row["stored_status"] == "Đã hủy":
        return "Đã hủy"
    if row["paid_actual"] <= 0:
        return "Chưa thanh toán"
    if row["paid_actual"] < row["total"]:
        return "Thanh toán một phần"
    return "Đã thanh toán"


def _answer_invoices(db, plan, user):
    rows = _invoice_rows(db, plan, user)
    inconsistent = [row for row in rows if int(row["cached_paid"] or 0) != int(row["paid_actual"] or 0)
                    or (row["stored_status"] != _derived_status(row) and row["stored_status"] != "Đã hủy")]
    if inconsistent:
        return AIResult("Dữ liệu hóa đơn và giao dịch thanh toán chưa nhất quán; cần đối soát trước khi trả lời.",
                        "no_data", "local", ai_service.model, True, ["Số tiền thanh toán nhất quán"]), []
    applied = [_condition_text(c) for c in plan.filters if not c.field.startswith("__")]
    if plan.aggregate == "count":
        return AIResult(f"Tìm thấy {len(rows)} hóa đơn. Điều kiện: {', '.join(applied) or 'hóa đơn hợp lệ'}; "
                        f"kỳ: {plan.date_label}. Đơn vị tiền mặc định: VNĐ.",
                        "success", "local", ai_service.model), []
    if not rows:
        return AIResult(NO_DATA + f" Điều kiện: {', '.join(applied)}; đơn vị tiền: VNĐ.",
                        "success", "local", ai_service.model), []
    connector = " OR " if plan.filter_logic == "or" else ", "
    lines = [f"Tìm thấy {len(rows) if len(rows) <= plan.limit else f'trên {plan.limit}'} hóa đơn.",
             f"Điều kiện đã áp dụng: {connector.join(applied) or 'hóa đơn hợp lệ'}; kỳ: {plan.date_label}; đơn vị: VNĐ."]
    for row in rows[:plan.limit]:
        lines.append(f"{row['code']} · {vn_text(row['issued_at'])} · {row['customer_name'] or 'Chưa xác định'} · "
                     f"Tổng {_money(row['total'])} · Đã thanh toán {_money(row['paid_actual'])} · "
                     f"Còn nợ {_money(row['remaining'])} · {_derived_status(row)}")
    sources = [{"type": "invoice", "id": row["id"], "label": f"Hóa đơn {row['code']}"} for row in rows[:plan.limit]]
    return AIResult("\n".join(lines), "success", "local", ai_service.model), sources


def _answer_payments(db, plan, user):
    sql = """SELECT p.id,p.amount,p.method,p.paid_at,i.code invoice_code,ro.customer_id
             FROM payments p JOIN invoices i ON i.id=p.invoice_id
             JOIN repair_orders ro ON ro.id=i.repair_order_id
             WHERE p.status='completed' AND i.status<>'Đã hủy'"""
    params: list[Any] = []
    scope = customer_scope_id(db, user)
    if scope is not None:
        sql += " AND ro.customer_id=?"
        params.append(scope)
    for condition in plan.filters:
        if condition.field == "payment_amount":
            fragment, values = _sql_condition("p.amount", condition)
            sql += " AND " + fragment
            params.extend(values)
    if plan.date_from:
        sql += " AND p.paid_at>=?"
        params.append(plan.date_from)
    if plan.date_to:
        sql += " AND p.paid_at<?"
        params.append(plan.date_to)
    sort = "p.amount" if plan.sort.field == "payment_amount" else "p.paid_at"
    sql += f" ORDER BY {sort} {plan.sort.direction.upper()},p.id DESC LIMIT ?"
    params.append(100_000 if plan.aggregate == "count" else plan.limit + 1)
    rows = [dict(row) for row in db.execute(sql, params).fetchall()]
    applied = [_condition_text(c) for c in plan.filters]
    if plan.aggregate == "count":
        return AIResult(f"Tìm thấy {len(rows)} giao dịch hợp lệ. Điều kiện: {', '.join(applied)}; kỳ: {plan.date_label}; đơn vị: VNĐ.",
                        "success", "local", ai_service.model), []
    if not rows:
        return AIResult(NO_DATA, "success", "local", ai_service.model), []
    lines = [f"Điều kiện đã áp dụng: {', '.join(applied)}; kỳ: {plan.date_label}; đơn vị: VNĐ."]
    lines.extend(f"{row['invoice_code']} · {_money(row['amount'])} · {row['method']} · {vn_text(row['paid_at'])}"
                 for row in rows[:plan.limit])
    return AIResult("\n".join(lines), "success", "local", ai_service.model), [
        {"type": "payment", "id": row["id"], "label": f"Thanh toán {row['invoice_code']}"} for row in rows[:plan.limit]]


def _answer_customer_debt(db, plan, user):
    paid = "COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id=i.id AND p.status='completed'),0)"
    debt = f"SUM(MAX(i.total-({paid}),0))"
    sql = f"""SELECT c.id,c.name,{debt} debt FROM customers c
              JOIN repair_orders ro ON ro.customer_id=c.id JOIN invoices i ON i.repair_order_id=ro.id
              WHERE c.status='active' AND i.status<>'Đã hủy'"""
    params: list[Any] = []
    scope = customer_scope_id(db, user)
    if scope is not None:
        sql += " AND c.id=?"
        params.append(scope)
    sql += " GROUP BY c.id"
    for condition in plan.filters:
        if condition.field == "outstanding_amount":
            fragment, values = _sql_condition(debt, condition)
            sql += " HAVING " + fragment
            params.extend(values)
    sql += f" ORDER BY debt {plan.sort.direction.upper()},c.id LIMIT ?"
    params.append(100_000 if plan.aggregate == "count" else plan.limit + 1)
    rows = [dict(row) for row in db.execute(sql, params).fetchall()]
    if plan.aggregate == "count":
        return AIResult(f"Có {len(rows)} khách hàng phù hợp. Điều kiện: {', '.join(_condition_text(c) for c in plan.filters)}; đơn vị: VNĐ.",
                        "success", "local", ai_service.model), []
    if not rows:
        return AIResult(NO_DATA, "success", "local", ai_service.model), []
    lines = [f"Điều kiện đã áp dụng: {', '.join(_condition_text(c) for c in plan.filters)}; sắp xếp {plan.sort.direction}; đơn vị: VNĐ."]
    lines.extend(f"KH-{row['id']:05d} · {row['name']} · Tổng công nợ {_money(row['debt'])}" for row in rows[:plan.limit])
    return AIResult("\n".join(lines), "success", "local", ai_service.model), []


def _answer_vehicles(db, plan, user):
    sql = "SELECT v.id,v.make,v.model,v.year,v.plate FROM vehicles v WHERE v.status='active'"
    params: list[Any] = []
    scope = customer_scope_id(db, user)
    if scope is not None:
        sql += " AND v.customer_id=?"
        params.append(scope)
    for condition in plan.filters:
        if condition.field == "year":
            fragment, values = _sql_condition("v.year", condition)
            sql += " AND " + fragment
            params.extend(values)
    sql += f" ORDER BY v.year {plan.sort.direction.upper()},v.id LIMIT ?"
    params.append(100_000 if plan.aggregate == "count" else plan.limit + 1)
    rows = [dict(row) for row in db.execute(sql, params).fetchall()]
    if plan.aggregate == "count":
        return AIResult(f"Có {len(rows)} xe phù hợp. Điều kiện: {', '.join(_condition_text(c) for c in plan.filters)}.",
                        "success", "local", ai_service.model), []
    if not rows:
        return AIResult(NO_DATA, "success", "local", ai_service.model), []
    lines = [f"Điều kiện đã áp dụng: {', '.join(_condition_text(c) for c in plan.filters)}."]
    lines.extend(f"{row['make']} {row['model']} {row['year'] or 'chưa rõ năm'} · {row['plate']}" for row in rows[:plan.limit])
    return AIResult("\n".join(lines), "success", "local", ai_service.model), [
        {"type": "vehicle", "id": row["id"], "label": row["plate"]} for row in rows[:plan.limit]]


def _answer_repair_orders(db, plan, user):
    sql = "SELECT r.id,r.code,r.plate,r.status,r.status_code,r.total,r.opened_at FROM repair_orders r WHERE r.status_code<>'CANCELLED'"
    params: list[Any] = []
    predicates: list[str] = []
    predicate_params: list[Any] = []
    for condition in plan.filters:
        if condition.field == "total_amount":
            fragment, values = _sql_condition("r.total", condition)
        elif condition.field == "open_days":
            cutoff = to_utc_iso(datetime.now(VN_TZ) - timedelta(days=int(condition.value)))
            fragment, values = "r.opened_at<? AND r.status_code NOT IN ('COMPLETED','DELIVERED','CANCELLED')", [cutoff]
        elif condition.field == "status_code":
            fragment, values = _sql_condition("r.status_code", condition)
        elif condition.field == "part_id":
            fragment, values = "EXISTS(SELECT 1 FROM repair_order_parts rp WHERE rp.repair_order_id=r.id AND rp.part_id=?)", [condition.value]
        else:
            continue
        predicates.append(fragment)
        predicate_params.extend(values)
    if predicates:
        connector = " OR " if plan.filter_logic == "or" else " AND "
        sql += " AND (" + connector.join(f"({predicate})" for predicate in predicates) + ")"
        params.extend(predicate_params)
    if plan.date_from:
        sql += " AND r.opened_at>=?"
        params.append(plan.date_from)
    if plan.date_to:
        sql += " AND r.opened_at<?"
        params.append(plan.date_to)
    sort = "r.total" if plan.sort.field == "total_amount" else "r.opened_at"
    sql += f" ORDER BY {sort} {plan.sort.direction.upper()},r.id DESC LIMIT ?"
    params.append(100_000 if plan.aggregate == "count" else plan.limit + 1)
    rows = [dict(row) for row in db.execute(sql, params).fetchall()]
    if plan.aggregate == "count":
        return AIResult(f"Tìm thấy {len(rows)} phiếu sửa chữa. Điều kiện: {', '.join(_condition_text(c) for c in plan.filters)}.",
                        "success", "local", ai_service.model), []
    if not rows:
        return AIResult(NO_DATA, "success", "local", ai_service.model), []
    lines = [f"Điều kiện đã áp dụng: {', '.join(_condition_text(c) for c in plan.filters)}; đơn vị tiền: VNĐ."]
    lines.extend(f"{row['code']} · {row['plate']} · {row['status']} · {_money(row['total'])} · mở {vn_text(row['opened_at'])}"
                 for row in rows[:plan.limit])
    return AIResult("\n".join(lines), "success", "local", ai_service.model), [
        {"type": "repair_order", "id": row["id"], "label": row["code"]} for row in rows[:plan.limit]]


def _answer_service_usage(db, plan, user):
    sql = """SELECT MIN(roi.id) id,roi.name,SUM(roi.quantity) usage_count
             FROM repair_order_items roi JOIN repair_orders ro ON ro.id=roi.repair_order_id
             WHERE roi.kind='Dịch vụ' AND ro.status_code<>'CANCELLED'"""
    params: list[Any] = []
    if plan.date_from:
        sql += " AND roi.created_at>=?"
        params.append(plan.date_from)
    if plan.date_to:
        sql += " AND roi.created_at<?"
        params.append(plan.date_to)
    sql += " GROUP BY LOWER(TRIM(roi.name)) ORDER BY usage_count DESC,roi.name LIMIT ?"
    params.append(plan.limit + 1)
    rows = [dict(row) for row in db.execute(sql, params).fetchall()]
    if not rows:
        return AIResult(NO_DATA, "success", "local", ai_service.model), []
    lines = [f"Dịch vụ được sử dụng nhiều nhất; kỳ: {plan.date_label}."]
    lines.extend(f"{index}. {row['name']} · {row['usage_count']:g} lượt" for index, row in enumerate(rows[:plan.limit], 1))
    return AIResult("\n".join(lines), "success", "local", ai_service.model), []


def answer_dynamic_query(db: sqlite3.Connection, question: str, user: dict):
    text = _normalize(question)
    plan = compile_query_plan(db, question, user)
    if plan is None:
        return None
    if any(condition.field == "__denied__" for condition in plan.filters):
        denied_msg = (
            "Bạn không có quyền truy cập thông tin hóa đơn của khách hàng khác. "
            "Vì lý do bảo mật và quyền riêng tư, tài khoản của bạn chỉ được phép tra cứu các bản ghi thuộc sở hữu của mình."
            if any(term in text for term in ("khach hang khac", "nguoi khac", "khach khac", "ai khac", "cua nguoi khac"))
            else DENIED
        )
        return AIResult(denied_msg, "fallback", "local", ai_service.model), []
    if any(condition.field == "__missing_part__" for condition in plan.filters):
        return AIResult("Không nhận diện được phụ tùng trong danh mục. Vui lòng nêu đúng tên hoặc mã phụ tùng.",
                        "clarification", "local", ai_service.model, True, ["Tên hoặc mã phụ tùng"]), []
    allowed = ALLOWED_FIELDS[plan.entity]
    if (any(condition.field not in allowed for condition in plan.filters)
            or (plan.sort and plan.sort.field not in allowed)
            or any(field not in allowed for field in plan.fields)):
        return AIResult("Bộ lọc chứa trường không được phép truy vấn.", "error", "local", ai_service.model), []
    text = _normalize(question)
    if plan.entity in ("invoice", "payment", "customer_debt", "repair_order"):
        has_numeric_filter = any(condition.field in ("total_amount", "paid_amount", "outstanding_amount",
                                                      "payment_amount", "open_days") for condition in plan.filters)
        if not has_numeric_filter and re.search(r"\b(?:tren|duoi|tu|lon hon|nho hon)\b", text):
            return AIResult("Chưa xác định được giá trị số. Vui lòng nhập bằng chữ số và nêu đơn vị nếu không phải VNĐ.",
                            "clarification", "local", ai_service.model, True, ["Giá trị số"]), []
    if plan.entity == "vehicle" and not any(condition.field == "year" for condition in plan.filters):
        return AIResult("Chưa xác định được khoảng năm sản xuất. Vui lòng nhập theo dạng từ năm 2020 đến năm 2024.",
                        "clarification", "local", ai_service.model, True, ["Khoảng năm sản xuất"]), []
    handlers = {"invoice": _answer_invoices, "payment": _answer_payments,
                "customer_debt": _answer_customer_debt, "vehicle": _answer_vehicles,
                "repair_order": _answer_repair_orders, "service_usage": _answer_service_usage}
    result, sources = handlers[plan.entity](db, plan, user)
    if result.status == "success":
        queried_at = datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M")
        result.content += f"\nDữ liệu truy vấn lúc {queried_at} (giờ Việt Nam), trong phạm vi tài khoản hiện tại."
    return result, sources
