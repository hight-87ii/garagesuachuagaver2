"""Module hóa đơn (invoices) và thanh toán (payments).

Bảo mật: giá trị tiền của hóa đơn do server tính từ phiếu sửa chữa và cấu hình
thuế; số tiền thanh toán được kiểm tra không vượt quá số còn phải thu và trạng
thái hóa đơn do server suy ra, không nhận từ client.
"""

from fastapi import APIRouter, Depends, Header, Query, Request

from ...core.access import customer_scope_id, ensure_record_access, ensure_role
from ...core.audit import write_audit
from ...core.db import connect, transaction
from ...core.deps import client_ip, require_permission
from ...core.errors import BadRequestError, ConflictError, NotFoundError
from ...core.pagination import PageParams, envelope, fetch_page, page_params, search_clause
from ...domain import next_invoice_code
from ...money import DEFAULT_TAX_RATE, with_tax
from ...schemas.common import Page
from ...schemas.invoices import (
    InvoiceCreatedOut,
    InvoiceDetailOut,
    InvoiceIn,
    InvoiceOut,
    InvoiceStatusIn,
    InvoiceStatusOut,
    PaymentCreatedOut,
    PaymentIn,
    PaymentOut,
)
from ...timeutil import now_utc_iso, vn_text

router = APIRouter(prefix="/invoices", tags=["Invoices"])
payments_router = APIRouter(prefix="/payments", tags=["Invoices"])


def _invoice_or_404(db, invoice_id: int) -> dict:
    invoice = db.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not invoice:
        raise NotFoundError("Không tìm thấy hóa đơn")
    return dict(invoice)


def _invoice_owner(db, invoice_id: int) -> int | None:
    row = db.execute(
        "SELECT ro.customer_id FROM invoices i JOIN repair_orders ro ON ro.id = i.repair_order_id WHERE i.id=?",
        (invoice_id,),
    ).fetchone()
    return row["customer_id"] if row else None


def _approved_quote(db, order_id: int, quote_id: int | None) -> dict:
    if quote_id:
        quote = db.execute(
            "SELECT * FROM quotes WHERE id=? AND repair_order_id=?", (quote_id, order_id)
        ).fetchone()
    else:
        quote = db.execute(
            "SELECT * FROM quotes WHERE repair_order_id=? AND status='Đã duyệt' "
            "ORDER BY version DESC, id DESC LIMIT 1", (order_id,)
        ).fetchone()
    if not quote:
        raise BadRequestError("Hóa đơn phải liên kết với một báo giá đã được duyệt")
    if quote["status"] != "Đã duyệt":
        raise BadRequestError("Chỉ được lập hóa đơn từ báo giá đã duyệt")
    if quote["valid_until"] and quote["valid_until"] <= now_utc_iso():
        raise BadRequestError("Báo giá đã hết thời hạn hiệu lực")
    if int(quote["total"] or 0) <= 0:
        raise BadRequestError("Báo giá phải có tổng tiền lớn hơn 0")
    return dict(quote)


@router.get("", response_model=Page[InvoiceOut], response_model_exclude_none=True)
def list_invoices(
    status: str = Query(default="", max_length=40),
    q: str = Query(default="", max_length=120),
    page: PageParams = Depends(page_params),
    user: dict = Depends(require_permission("invoices")),
) -> dict:
    base = """
        SELECT i.*, (SELECT MAX(p.paid_at) FROM payments p WHERE p.invoice_id=i.id AND p.status='completed') AS last_paid_at,
               q.code AS quote_code, ro.code AS order_code, ro.plate, ro.technician, ro.status AS order_status,
               c.name AS customer_name, c.phone AS customer_phone, v.make, v.model
        FROM invoices i JOIN repair_orders ro ON ro.id = i.repair_order_id
        LEFT JOIN quotes q ON q.id = i.quote_id
        LEFT JOIN vehicles v ON v.id = ro.vehicle_id
        LEFT JOIN customers c ON c.id = ro.customer_id WHERE 1 = 1
    """
    params: list = []
    if status and status != "Tất cả":
        base += " AND i.status=?"
        params.append(status)
    clause, clause_params = search_clause(q, ["i.code", "ro.code", "ro.plate", "c.name"])
    base += clause
    params.extend(clause_params)
    with connect() as db:
        scope = customer_scope_id(db, user)
        if scope is not None:
            base += " AND ro.customer_id=?"
            params.append(scope)
        items, total = fetch_page(db, base, tuple(params), "ORDER BY i.id DESC", page)
    for item in items:
        item["issued_at"] = vn_text(item["issued_at"])
        item["remaining_amount"] = max(0, int(item["total"] or 0) - int(item["paid_amount"] or 0))
        item["settled_at"] = (vn_text(item["last_paid_at"]) if item["status"] == "Đã thanh toán"
                              and item["remaining_amount"] == 0 else None)
    return envelope(items, total, page)


@router.get("/candidates", response_model=list[dict], response_model_exclude_none=True)
def invoice_candidates(user: dict = Depends(require_permission("invoices"))) -> list[dict]:
    """Các báo giá đã duyệt chưa được lập hóa đơn."""
    ensure_role(user, ("Admin", "Quản lý", "Thu ngân"), message="Khách hàng không được lập hóa đơn")
    with connect() as db:
        rows = db.execute(
            "SELECT q.id AS quote_id, q.code AS quote_code, q.repair_order_id, q.total, "
            "q.valid_until, ro.code AS order_code, ro.plate, c.name AS customer_name "
            "FROM quotes q JOIN repair_orders ro ON ro.id=q.repair_order_id "
            "LEFT JOIN customers c ON c.id=ro.customer_id "
            "WHERE q.status='Đã duyệt' AND (q.valid_until IS NULL OR q.valid_until > ?) "
            "AND NOT EXISTS (SELECT 1 FROM invoices i WHERE i.quote_id=q.id AND i.status <> 'Đã hủy') "
            "ORDER BY q.id DESC",
            (now_utc_iso(),),
        ).fetchall()
        return [dict(row) for row in rows]


@router.get("/payment-summary", response_model=dict)
def payment_summary(user: dict = Depends(require_permission("invoices"))) -> dict:
    """Tổng hợp toàn bộ hóa đơn, không phụ thuộc phân trang danh sách."""
    ensure_role(user, ("Admin", "Quản lý", "Thu ngân"), message="Chỉ nhân viên được xem tổng hợp công nợ")
    with connect() as db:
        row = db.execute("""SELECT COUNT(*) invoice_count,
             COALESCE(SUM(paid_amount),0) collected,
             COALESCE(SUM(MAX(total-paid_amount,0)),0) remaining,
             COALESCE(SUM(CASE WHEN status='Thanh toán một phần' THEN 1 ELSE 0 END),0) partial_count,
             COALESCE(SUM(CASE WHEN status='Chưa thanh toán' THEN 1 ELSE 0 END),0) unpaid_count,
             COALESCE(SUM(CASE WHEN status='Đã thanh toán' THEN 1 ELSE 0 END),0) settled_count
             FROM invoices WHERE status<>'Đã hủy'""").fetchone()
    return dict(row)


@router.get("/pipeline", response_model=list[dict], response_model_exclude_none=True)
def invoice_pipeline(user: dict = Depends(require_permission("invoices"))) -> list[dict]:
    """Các xe đã tiếp nhận và mức độ sẵn sàng lập hóa đơn dành cho quầy thu ngân."""
    ensure_role(user, ("Admin", "Quản lý", "Thu ngân"), message="Chỉ bộ phận nội bộ được xem luồng hóa đơn")
    with connect() as db:
        rows = db.execute(
            """SELECT ro.id repair_order_id, ro.code order_code, ro.plate, ro.customer_name,
                      ro.status order_status, ro.status_code, ro.opened_at, ro.total order_total,
                      q.id quote_id, q.code quote_code, q.status quote_status, q.total quote_total,
                      i.id invoice_id, i.code invoice_code, i.status invoice_status, i.total invoice_total
               FROM repair_orders ro
               LEFT JOIN quotes q ON q.id=(SELECT q2.id FROM quotes q2 WHERE q2.repair_order_id=ro.id
                    ORDER BY (q2.status='Đã duyệt') DESC, q2.version DESC, q2.id DESC LIMIT 1)
               LEFT JOIN invoices i ON i.id=(SELECT i2.id FROM invoices i2 WHERE i2.repair_order_id=ro.id
                    AND i2.status<>'Đã hủy' ORDER BY i2.id DESC LIMIT 1)
               WHERE ro.status<>'Đã hủy' ORDER BY ro.opened_at DESC, ro.id DESC"""
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        if item["invoice_id"]:
            stage = "Đã lập hóa đơn"
            stage_code = "INVOICED"
        elif item["quote_status"] == "Đã duyệt":
            stage = "Sẵn sàng lập hóa đơn"
            stage_code = "READY"
        elif item["quote_id"]:
            stage = "Chờ duyệt báo giá"
            stage_code = "WAITING_QUOTE_APPROVAL"
        else:
            stage = "Chờ kiểm tra và báo giá"
            stage_code = "WAITING_QUOTE"
        item.update({"stage": stage, "stage_code": stage_code,
                     "opened_at": vn_text(item["opened_at"])})
        result.append(item)
    return result


@router.get("/{invoice_id}", response_model=InvoiceDetailOut, response_model_exclude_none=True)
def invoice_detail(invoice_id: int, user: dict = Depends(require_permission("invoices"))) -> dict:
    with connect() as db:
        invoice = db.execute(
            "SELECT i.*, q.code AS quote_code, ro.code AS order_code, ro.plate, ro.technician, "
            "ro.status AS order_status, c.name AS customer_name, c.phone AS customer_phone, "
            "v.make, v.model FROM invoices i JOIN repair_orders ro ON ro.id=i.repair_order_id "
            "LEFT JOIN quotes q ON q.id=i.quote_id LEFT JOIN customers c ON c.id=ro.customer_id "
            "LEFT JOIN vehicles v ON v.id=ro.vehicle_id WHERE i.id=?", (invoice_id,)
        ).fetchone()
        if not invoice:
            raise NotFoundError("Không tìm thấy hóa đơn")
        ensure_record_access(db, user, _invoice_owner(db, invoice_id))
        payload = dict(invoice)
        payload["remaining_amount"] = max(0, int(payload["total"] or 0) - int(payload["paid_amount"] or 0))
        payload["items"] = [dict(row) for row in db.execute("SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY id", (invoice_id,)).fetchall()]
        payload["payments"] = [dict(row) for row in db.execute("SELECT * FROM payments WHERE invoice_id=? ORDER BY id DESC", (invoice_id,)).fetchall()]
        for payment in payload["payments"]:
            payment["paid_at"] = vn_text(payment["paid_at"])
        payload["settled_at"] = (payload["payments"][0]["paid_at"] if payload["status"] == "Đã thanh toán"
                                 and payload["remaining_amount"] == 0 and payload["payments"] else None)
        payload["issued_at"] = vn_text(payload.get("issued_at"))
        return payload


@router.post("", status_code=201, response_model=InvoiceCreatedOut, response_model_exclude_none=True)
def create_invoice(
    item: InvoiceIn,
    request: Request,
    user: dict = Depends(require_permission("invoices")),
) -> dict:
    ensure_role(user, ("Admin", "Quản lý", "Thu ngân"), message="Khách hàng chỉ được xem hóa đơn của mình")
    with connect() as db, transaction(db):
        order = db.execute(
            "SELECT id, vehicle_id, total FROM repair_orders WHERE id=?", (item.repair_order_id,)
        ).fetchone()
        if not order:
            raise NotFoundError("Không tìm thấy phiếu sửa chữa")
        quote = _approved_quote(db, item.repair_order_id, item.quote_id)
        # Tổng tiền do server tính từ snapshot báo giá đã duyệt, KHÔNG nhận từ client.
        subtotal = int(quote["subtotal"] or 0)
        discount = int(quote["discount"] or 0)
        tax = int(quote["tax"] or 0)
        total = int(quote["total"] or 0)
        code = next_invoice_code(db)
        cursor = db.execute(
            "INSERT INTO invoices(code, repair_order_id, quote_id, subtotal, discount, tax, total, estimated_duration_min, paid_amount, status, note, created_by) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, 0, 'Chưa thanh toán', ?, ?)",
            (code, item.repair_order_id, quote["id"], subtotal, discount, tax, total,
             quote["estimated_duration_min"], item.note.strip(), user["id"]),
        )
        invoice_id = cursor.lastrowid
        db.execute(
            "INSERT INTO invoice_items(invoice_id, quote_item_id, kind, name, quantity, unit_price, line_total, estimated_duration_min, estimate_source) "
            "SELECT ?, id, kind, name, quantity, unit_price, line_total, estimated_duration_min, estimate_source FROM quote_items WHERE quote_id=?",
            (invoice_id, quote["id"]),
        )
        write_audit(db, user, "invoice.create", "invoices", invoice_id, {"code": code, "total": total}, client_ip(request))
    return {
        "id": invoice_id,
        "code": code,
        "repair_order_id": item.repair_order_id,
        "quote_id": quote["id"],
        "subtotal": subtotal,
        "discount": discount,
        "tax": tax,
        "total": total,
        "estimated_duration_min": quote["estimated_duration_min"],
        "paid_amount": 0,
        "status": "Chưa thanh toán",
        "quote_id": quote["id"],
        "remaining_amount": total,
    }


@router.patch("/{invoice_id}/status", response_model=InvoiceStatusOut, response_model_exclude_none=True)
def update_invoice_status(
    invoice_id: int,
    item: InvoiceStatusIn,
    request: Request,
    user: dict = Depends(require_permission("invoices")),
) -> dict:
    ensure_role(user, ("Admin", "Quản lý", "Thu ngân"), message="Khách hàng không được thay đổi trạng thái hóa đơn")
    with connect() as db, transaction(db):
        invoice = _invoice_or_404(db, invoice_id)
        ensure_record_access(db, user, _invoice_owner(db, invoice_id))
        paid = int(invoice["paid_amount"])
        if item.status == "Đã thanh toán":
            if paid < int(invoice["total"]):
                raise BadRequestError("Hãy ghi nhận số tiền thực thu, hình thức và ghi chú tại quầy trước khi tất toán")
        elif item.status == "Chưa thanh toán":
            if paid > 0:
                raise BadRequestError("Không thể đưa hóa đơn đã có thanh toán về chưa thanh toán")
            paid = 0
        elif item.status == "Thanh toán một phần":
            raise BadRequestError("Hãy ghi nhận số tiền cụ thể qua endpoint thanh toán")
        db.execute("UPDATE invoices SET status=?, paid_amount=? WHERE id=?", (item.status, paid, invoice_id))
        write_audit(db, user, "invoice.status", "invoices", invoice_id, {"status": item.status}, client_ip(request))
    return {"id": invoice_id, "status": item.status, "paid_amount": paid}


@router.get("/{invoice_id}/payments", response_model=Page[PaymentOut], response_model_exclude_none=True)
def list_payments(
    invoice_id: int,
    page: PageParams = Depends(page_params),
    user: dict = Depends(require_permission("invoices")),
) -> dict:
    with connect() as db:
        _invoice_or_404(db, invoice_id)
        ensure_record_access(db, user, _invoice_owner(db, invoice_id))
        items, total = fetch_page(
            db, "SELECT * FROM payments WHERE invoice_id=?", (invoice_id,), "ORDER BY id DESC", page
        )
    return envelope(items, total, page)


@payments_router.post("", status_code=201, response_model=PaymentCreatedOut, response_model_exclude_none=True)
def create_payment(
    item: PaymentIn,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: dict = Depends(require_permission("invoices")),
) -> dict:
    ensure_role(user, ("Admin", "Quản lý", "Thu ngân"), message="Chỉ nhân viên thu ngân được ghi nhận thanh toán")
    with connect() as db, transaction(db):
        invoice = _invoice_or_404(db, item.invoice_id)
        ensure_record_access(db, user, _invoice_owner(db, item.invoice_id))
        key = idempotency_key.strip() if idempotency_key and idempotency_key.strip() else None
        if key:
            previous = db.execute("SELECT * FROM payments WHERE idempotency_key=?", (key,)).fetchone()
            if previous:
                if previous["status"] != "completed" or previous["invoice_id"] != item.invoice_id or previous["method"] != item.method or (
                    item.amount is not None and int(previous["amount"]) != int(item.amount)
                ) or (item.reference_code.strip() and previous["reference_code"] != item.reference_code.strip()):
                    raise ConflictError("Idempotency-Key đã được dùng cho hóa đơn khác")
                current = _invoice_or_404(db, item.invoice_id)
                return {
                    "id": previous["id"], "invoice_id": item.invoice_id, "amount": previous["amount"],
                    "method": previous["method"], "status": current["status"],
                    "paid_amount": current["paid_amount"],
                    "remaining": max(0, int(current["total"]) - int(current["paid_amount"])),
                    "paid_at": vn_text(previous["paid_at"]),
                }
        if invoice["status"] == "Đã hủy":
            raise BadRequestError("Hóa đơn đã hủy, không thể ghi nhận thanh toán")
        paid = int(invoice["paid_amount"])
        total = int(invoice["total"])
        remaining = max(0, total - paid)
        if remaining == 0:
            raise BadRequestError("Hóa đơn đã được thanh toán đầy đủ")
        amount = int(item.amount) if item.amount is not None else remaining
        if amount > remaining:
            raise BadRequestError("Số tiền thanh toán vượt quá số còn phải thu")
        if item.reference_code.strip():
            duplicate_reference = db.execute(
                "SELECT id FROM payments WHERE invoice_id=? AND reference_code=?",
                (item.invoice_id, item.reference_code.strip()),
            ).fetchone()
            if duplicate_reference:
                raise ConflictError("Mã tham chiếu thanh toán đã được ghi nhận cho hóa đơn này")
        cursor = db.execute(
            "INSERT INTO payments(invoice_id, method, amount, reference_code, idempotency_key, note, received_by) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (item.invoice_id, item.method, amount, item.reference_code.strip(), key, item.note.strip(), user["id"]),
        )
        payment_id = cursor.lastrowid
        payment_time = db.execute("SELECT paid_at FROM payments WHERE id=?", (payment_id,)).fetchone()["paid_at"]
        paid_new = paid + amount
        status = "Đã thanh toán" if paid_new >= total else "Thanh toán một phần"
        due_at = None if status == "Đã thanh toán" else (
            item.next_due_at.isoformat() if item.next_due_at else invoice["due_at"])
        db.execute("UPDATE invoices SET paid_amount=?, status=?, due_at=? WHERE id=?",
                   (paid_new, status, due_at, item.invoice_id))
        write_audit(
            db, user, "payment.create", "invoices", item.invoice_id,
            {"amount": amount, "method": item.method, "remaining": max(0, total - paid_new),
             "next_due_at": due_at}, client_ip(request),
        )
    return {
        "id": payment_id,
        "invoice_id": item.invoice_id,
        "amount": amount,
        "method": item.method,
        "status": status,
        "paid_amount": paid_new,
        "remaining": max(0, total - paid_new),
        "paid_at": vn_text(payment_time),
    }
