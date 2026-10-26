"""Tra cứu hóa đơn/công nợ bằng các truy vấn cố định do backend kiểm soát.

Module này không gọi LLM, không nhận SQL và không tin danh tính từ nội dung chat.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .core.access import customer_scope_id
from .permissions import has_permission
from .timeutil import VN_TZ, to_utc_iso, vn_text


DENIED = "Bạn không có quyền truy cập chức năng tra cứu hóa đơn và công nợ. Vui lòng liên hệ quản trị viên để được cấp quyền phù hợp."
NO_DATA = "Không tìm thấy hóa đơn phù hợp với điều kiện bạn cung cấp."
INCONSISTENT = "Chưa thể xác định chính xác số liệu do dữ liệu hóa đơn hoặc thanh toán chưa đầy đủ. Vui lòng kiểm tra lại."


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFD", (text or "").casefold())
    return "".join(ch for ch in folded if unicodedata.category(ch) != "Mn").replace("đ", "d")


def is_invoice_question(question: str) -> bool:
    text = _normalize(question)
    return any(term in text for term in (
        "hoa don", "cong no", "con no", "chua thanh toan", "da thanh toan",
        "thanh toan mot phan", "tien da thu", "phai thu", "khach hang nao con no",
    ))


@dataclass(frozen=True)
class InvoiceIntent:
    kind: str
    wants_total: bool
    wants_amount: bool
    wants_debt: bool
    invoice_code: str | None
    date_from: str | None
    date_to: str | None
    customer_id: int | None
    customer_name: str | None
    highest_debt: bool


def _period(text: str) -> tuple[str | None, str | None]:
    now = datetime.now(VN_TZ)
    if "hom nay" in text:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return to_utc_iso(start), to_utc_iso(start + timedelta(days=1))
    if "thang nay" in text:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return to_utc_iso(start), to_utc_iso(end)
    return None, None


def classify_invoice_question(db: sqlite3.Connection, question: str) -> InvoiceIntent:
    text = _normalize(question)
    code_match = re.search(r"\b(?:HD|INV)[-A-Z0-9]+\b", question, re.IGNORECASE)
    if "mot phan" in text:
        kind = "partial"
    elif any(term in text for term in ("chua thanh toan", "dang cho thanh toan")):
        kind = "unpaid"
    elif any(term in text for term in ("cong no", "con no", "phai thu", "no nhieu")):
        kind = "debt"
    elif "da thu" in text and any(term in text for term in ("tong", "bao nhieu")):
        kind = "collected"
    elif "da thanh toan" in text or "da thu" in text:
        kind = "paid"
    elif code_match:
        kind = "detail"
    else:
        kind = "all"
    wants_total = any(term in text for term in ("tong", "bao nhieu tien", "so tien", "so sanh"))
    wants_debt = any(term in text for term in ("cong no", "con no", "phai thu", "no bao nhieu", "no nhieu"))
    wants_amount = wants_total or wants_debt or any(term in text for term in ("da thanh toan bao nhieu", "tien da thu"))
    date_from, date_to = _period(text)
    customer_id = None
    customer_name = None
    # Chỉ khớp tên khách thực có trong DB; không dùng phần văn bản tùy ý làm SQL.
    for row in db.execute("SELECT id,name FROM customers WHERE status='active' ORDER BY length(name) DESC").fetchall():
        if _normalize(row["name"]) in text:
            customer_id, customer_name = int(row["id"]), row["name"]
            break
    return InvoiceIntent(kind, wants_total, wants_amount, wants_debt,
                         code_match.group(0).upper() if code_match else None,
                         date_from, date_to, customer_id, customer_name,
                         "nhieu nhat" in text or "lon nhat" in text)


def _allowed(user: dict, permission: str) -> bool:
    return has_permission(str(user.get("role") or ""), permission)


def _money(value: int) -> str:
    return f"{int(value):,} ₫".replace(",", ".")


def _status(total: int, paid: int, cancelled: bool) -> str:
    if cancelled:
        return "Đã hủy"
    if paid <= 0:
        return "Chưa thanh toán"
    if paid < total:
        return "Thanh toán một phần"
    return "Đã thanh toán"


def _query_rows(db: sqlite3.Connection, user: dict, intent: InvoiceIntent) -> list[dict[str, Any]]:
    sql = """
        SELECT i.id,i.code,i.total,i.paid_amount cached_paid,i.status stored_status,i.issued_at,
               i.due_at,ro.customer_id,c.name customer_name,
               COALESCE(SUM(CASE WHEN p.status='completed' THEN p.amount ELSE 0 END),0) paid_actual,
               MAX(CASE WHEN p.status='completed' THEN p.paid_at END) last_paid_at
        FROM invoices i JOIN repair_orders ro ON ro.id=i.repair_order_id
        LEFT JOIN customers c ON c.id=ro.customer_id
        LEFT JOIN payments p ON p.invoice_id=i.id
        WHERE 1=1
    """
    params: list[Any] = []
    if intent.invoice_code:
        sql += " AND UPPER(i.code)=?"
        params.append(intent.invoice_code)
    if intent.customer_id is not None:
        sql += " AND ro.customer_id=?"
        params.append(intent.customer_id)
    scope = customer_scope_id(db, user)
    if scope is not None:
        sql += " AND ro.customer_id=?"
        params.append(scope)
    elif not _allowed(user, "invoice.view_all"):
        # Mặc định an toàn cho nhân viên không có quyền xem tất cả: chỉ chứng từ họ lập/thu.
        sql += " AND (i.created_by=? OR EXISTS(SELECT 1 FROM payments ownp WHERE ownp.invoice_id=i.id AND ownp.received_by=?))"
        params.extend((user["id"], user["id"]))
    if intent.date_from:
        if intent.kind in ("paid", "collected"):
            sql += (" AND EXISTS(SELECT 1 FROM payments periodp WHERE periodp.invoice_id=i.id "
                    "AND periodp.status='completed' AND periodp.paid_at>=? AND periodp.paid_at<?)")
        else:
            sql += " AND i.issued_at>=? AND i.issued_at<?"
        params.extend((intent.date_from, intent.date_to))
    sql += " GROUP BY i.id ORDER BY i.issued_at DESC,i.id DESC LIMIT 100"
    rows = []
    for row in db.execute(sql, tuple(params)).fetchall():
        item = dict(row)
        total, paid = int(item["total"] or 0), int(item["paid_actual"] or 0)
        item["paid_actual"] = paid
        item["remaining"] = max(0, total - paid)
        item["derived_status"] = _status(total, paid, item["stored_status"] == "Đã hủy")
        rows.append(item)
    if intent.kind == "unpaid":
        rows = [row for row in rows if row["derived_status"] == "Chưa thanh toán"]
    elif intent.kind == "partial":
        rows = [row for row in rows if row["derived_status"] == "Thanh toán một phần"]
    elif intent.kind == "paid":
        rows = [row for row in rows if row["derived_status"] == "Đã thanh toán"]
    elif intent.kind == "debt":
        rows = [row for row in rows if row["remaining"] > 0 and row["derived_status"] != "Đã hủy"]
    if intent.highest_debt:
        rows.sort(key=lambda row: row["remaining"], reverse=True)
        rows = rows[:1]
    return rows


def answer_invoice_question(db: sqlite3.Connection, user: dict, question: str) -> dict | None:
    """Trả kết quả có cấu trúc, hoặc None nếu câu hỏi không thuộc hóa đơn."""
    if not is_invoice_question(question):
        return None
    if not _allowed(user, "invoice.view"):
        return {"content": DENIED, "status": "forbidden", "sources": [], "intent": "denied"}
    intent = classify_invoice_question(db, question)
    if ((intent.wants_amount and not _allowed(user, "invoice.view_amount")) or
            (intent.wants_debt and not _allowed(user, "invoice.view_debt")) or
            (intent.wants_total and not _allowed(user, "invoice.calculate"))):
        return {"content": DENIED, "status": "forbidden", "sources": [], "intent": intent.kind}
    rows = _query_rows(db, user, intent)
    if not rows:
        return {"content": NO_DATA, "status": "no_data", "sources": [], "intent": intent.kind}
    inconsistent = [row for row in rows if int(row["cached_paid"] or 0) != row["paid_actual"] or
                    (row["stored_status"] != row["derived_status"] and row["stored_status"] != "Đã hủy")]
    if inconsistent:
        return {"content": INCONSISTENT, "status": "inconsistent", "sources": [], "intent": intent.kind}
    can_amount = _allowed(user, "invoice.view_amount")
    can_debt = _allowed(user, "invoice.view_debt")
    lines = []
    for row in rows[:20]:
        line = f"- {row['code']} · {vn_text(row['issued_at'])} · {row['customer_name'] or 'Khách hàng chưa xác định'}"
        if can_amount:
            line += f" · Tổng {_money(row['total'])} · Đã thanh toán {_money(row['paid_actual'])}"
        if can_debt:
            line += f" · Còn nợ {_money(row['remaining'])}"
        line += f" · {row['derived_status']}"
        lines.append(line)
    filters = [intent.kind]
    if intent.customer_name:
        filters.append(f"khách hàng {intent.customer_name}")
    if intent.date_from:
        filters.append("kỳ thời gian được yêu cầu")
    heading = f"Tìm thấy {len(rows)} hóa đơn (điều kiện: {', '.join(filters)})."
    totals = ""
    if intent.wants_total:
        total = sum(int(row["total"]) for row in rows)
        if intent.kind == "collected" and intent.date_from:
            placeholders = ",".join("?" for _ in rows)
            paid = int(db.execute(
                f"SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='completed' "
                f"AND invoice_id IN ({placeholders}) AND paid_at>=? AND paid_at<?",
                (*[row["id"] for row in rows], intent.date_from, intent.date_to),
            ).fetchone()[0])
        else:
            paid = sum(int(row["paid_actual"]) for row in rows)
        totals = f"\nTổng phải thu: {_money(total)}; tổng đã thanh toán: {_money(paid)}"
        if can_debt:
            totals += f"; tổng còn nợ: {_money(sum(int(row['remaining']) for row in rows))}"
        totals += "."
    sources = [{"type": "invoice", "id": row["id"], "label": f"Hóa đơn {row['code']}"} for row in rows[:20]]
    return {"content": heading + totals + "\n" + "\n".join(lines), "status": "success",
            "sources": sources, "intent": intent.kind, "count": len(rows)}


# Các công cụ giới hạn được backend/kiểm thử gọi trực tiếp.
def get_unpaid_invoices(db, user, question="Liệt kê hóa đơn chưa thanh toán"):
    return answer_invoice_question(db, user, question)


def get_paid_invoices(db, user, question="Liệt kê hóa đơn đã thanh toán"):
    return answer_invoice_question(db, user, question)


def get_partially_paid_invoices(db, user, question="Liệt kê hóa đơn thanh toán một phần"):
    return answer_invoice_question(db, user, question)


def get_invoice_details(db, user, invoice_code: str):
    return answer_invoice_question(db, user, f"Chi tiết hóa đơn {invoice_code}")


def get_invoice_payment_summary(db, user, question="Tính tổng tiền hóa đơn và đã thanh toán"):
    return answer_invoice_question(db, user, question)


def get_outstanding_debt_summary(db, user, question="Tổng công nợ hiện tại là bao nhiêu?"):
    return answer_invoice_question(db, user, question)
