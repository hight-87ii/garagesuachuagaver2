"""Module báo giá (quotes)."""

import hashlib
import json
import time
from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Request

from ...ai_service import AIResult, ai_service
from ...core.access import ensure_record_access, ensure_role
from ...core.audit import write_audit
from ...core.db import connect, transaction
from ...core.deps import client_ip, require_permission
from ...core.errors import BadRequestError, NotFoundError
from ...duration import quote_duration, service_duration
from ...core.pagination import PageParams, envelope, fetch_page, page_params
from ...money import DEFAULT_DISCOUNT_RATE, DEFAULT_TAX_RATE, line_total, tax_for, to_vnd
from ...quote_validity import approval_validity_error, validity_state
from ...schemas.common import Page
from ...schemas.quotes import (
    AIQuoteDraftIn,
    AIQuoteDraftOut,
    AIQuotePreviewOut,
    QuoteCreatedOut,
    QuoteDetailOut,
    QuoteIn,
    QuoteNarrativeIn,
    QuoteOut,
    QuoteStatusIn,
    QuoteStatusOut,
)
from ...timeutil import now_utc, now_utc_iso, to_utc_iso
from ...workflow import change_status, order_status_code

router = APIRouter(prefix="/quotes", tags=["Quotes"])


def _quote_valid_until(value: str | None, db=None) -> str:
    if not value:
        days = 7
        if db is not None:
            row = db.execute("SELECT value FROM system_settings WHERE key='quote_valid_days'").fetchone()
            if row:
                days = max(1, min(90, int(row["value"])))
        return to_utc_iso(now_utc() + timedelta(days=days))
    normalized = to_utc_iso(value)
    if normalized <= now_utc_iso():
        raise BadRequestError("Thời hạn báo giá phải ở tương lai")
    return normalized


def _expire_if_needed(db, quote: dict) -> dict:
    # Hiệu lực là trạng thái độc lập; đọc dữ liệu không được sửa lịch sử duyệt.
    return {**quote, "validity_status": validity_state(quote.get("valid_until"))}


def _selected_database_lines(db, item: AIQuoteDraftIn) -> tuple[list[dict], int, int]:
    """Đọc tên, số lượng và giá hiện hành từ DB; tuyệt đối không nhận giá từ AI/client."""
    service_ids = list(dict.fromkeys(item.service_item_ids))
    part_ids = list(dict.fromkeys(item.part_usage_ids))
    if len(service_ids) != len(item.service_item_ids) or len(part_ids) != len(item.part_usage_ids):
        raise BadRequestError("Danh sách hạng mục không được chứa ID trùng lặp")
    if not service_ids and not part_ids:
        raise BadRequestError("Cần chọn ít nhất một dịch vụ hoặc phụ tùng")
    services: list[dict] = []
    parts: list[dict] = []
    if service_ids:
        placeholders = ",".join("?" for _ in service_ids)
        services = [dict(row) for row in db.execute(
            f"""SELECT roi.id source_id, 'Dịch vụ' kind, s.id service_id, NULL part_id,
                       s.name, s.description, roi.quantity, s.price unit_price
                FROM repair_order_items roi JOIN services s ON s.id=roi.service_id
                WHERE roi.repair_order_id=? AND roi.kind='Dịch vụ' AND s.active=1
                  AND roi.id IN ({placeholders}) ORDER BY roi.id""",
            (item.repair_order_id, *service_ids),
        ).fetchall()]
        if len(services) != len(service_ids):
            raise BadRequestError("Có dịch vụ không thuộc phiếu, không có trong danh mục hoặc đã ngừng hoạt động")
    if part_ids:
        placeholders = ",".join("?" for _ in part_ids)
        parts = [dict(row) for row in db.execute(
            f"""SELECT rop.id source_id, 'Phụ tùng' kind, NULL service_id, p.id part_id,
                       p.name, p.compatible description, rop.quantity, p.sell_price unit_price
                FROM repair_order_parts rop JOIN parts p ON p.id=rop.part_id
                WHERE rop.repair_order_id=? AND p.active=1
                  AND rop.id IN ({placeholders}) ORDER BY rop.id""",
            (item.repair_order_id, *part_ids),
        ).fetchall()]
        if len(parts) != len(part_ids):
            raise BadRequestError("Có phụ tùng không thuộc phiếu, không có trong danh mục hoặc đã ngừng hoạt động")
    lines = services + parts
    labor = sum(line_total(row["quantity"], row["unit_price"]) for row in services)
    part_total = sum(line_total(row["quantity"], row["unit_price"]) for row in parts)
    return lines, labor, part_total


def _narrative_context(order, lines: list[dict], duration: int | None) -> dict:
    technical_parts = [value.strip() for value in
                       (order["inspection_notes"], order["customer_request"])
                       if (value or "").strip()]
    return {
        "repair_order": {"id": order["id"], "code": order["code"]},
        "items": [{"source_item_id": f"{'service' if row['kind'] == 'Dịch vụ' else 'part'}:{row['source_id']}",
                   "kind": row["kind"], "name": row["name"],
                   "description": (row["description"] or "")[:500],
                   "estimated_duration_min": row["estimated_duration_min"]} for row in lines],
        "estimated_duration_min": duration,
        "technical_context": " • ".join(dict.fromkeys(technical_parts))[:1500],
    }


def _generate_narrative(context: dict) -> tuple[AIResult, str | None]:
    try:
        return ai_service.create_quote_narrative(context), None
    except Exception:
        return AIResult(ai_service._fallback_quote_narrative(context), "error", "local", ai_service.model), "provider_unavailable"


@router.post("/ai-draft/preview", response_model=AIQuotePreviewOut)
def preview_ai_quote_draft(
    item: AIQuoteDraftIn,
    user: dict = Depends(require_permission("repair_orders")),
) -> dict:
    """Không lưu báo giá; giá được đọc lại khi người dùng xác nhận lưu."""
    with connect() as db:
        order = db.execute("SELECT * FROM repair_orders WHERE id=?", (item.repair_order_id,)).fetchone()
        if not order:
            raise NotFoundError("Không tìm thấy phiếu sửa chữa")
        ensure_record_access(db, user, order["customer_id"])
        if order_status_code(order) in ("COMPLETED", "DELIVERED", "CANCELLED"):
            raise BadRequestError("Phiếu đã kết thúc, không thể tạo báo giá")
        lines, labor, parts = _selected_database_lines(db, item)
        duration_values = []
        for row in lines:
            minutes, _ = (service_duration(db, row["service_id"], row["name"], row["quantity"])
                          if row["kind"] == "Dịch vụ" else (None, None))
            row["estimated_duration_min"] = minutes
            if minutes is not None:
                duration_values.append(minutes)
        duration = sum(duration_values) if duration_values else None
        valid_until = _quote_valid_until(item.valid_until, db)
    subtotal = labor + parts
    discount = tax_for(subtotal, DEFAULT_DISCOUNT_RATE)
    taxable = max(0, subtotal - discount)
    tax = tax_for(taxable, DEFAULT_TAX_RATE)
    generated, _ = _generate_narrative(_narrative_context(order, lines, duration))
    return {"subtotal": subtotal, "labor_subtotal": labor, "parts_subtotal": parts,
            "discount": discount, "tax": tax, "total": taxable + tax,
            "tax_rate": float(DEFAULT_TAX_RATE), "valid_until": valid_until,
            "estimated_duration_min": duration, "ai_status": generated.status,
            "explanation": generated.content}


@router.post("/ai-draft", status_code=201, response_model=AIQuoteDraftOut)
def create_ai_quote_draft(
    item: AIQuoteDraftIn,
    request: Request,
    user: dict = Depends(require_permission("repair_orders")),
) -> dict:
    """Tạo báo giá Nháp bằng giá DB; AI chỉ viết diễn giải và có thể thất bại độc lập."""
    started = time.perf_counter()
    with connect() as db, transaction(db):
        order = db.execute("SELECT * FROM repair_orders WHERE id=?", (item.repair_order_id,)).fetchone()
        if not order:
            raise NotFoundError("Không tìm thấy phiếu sửa chữa")
        ensure_record_access(db, user, order["customer_id"])
        if order_status_code(order) in ("COMPLETED", "DELIVERED", "CANCELLED"):
            raise BadRequestError("Phiếu đã kết thúc, không thể tạo báo giá")
        lines, labor_subtotal, parts_subtotal = _selected_database_lines(db, item)
        subtotal = labor_subtotal + parts_subtotal
        discount = tax_for(subtotal, DEFAULT_DISCOUNT_RATE)
        taxable = max(0, subtotal - discount)
        tax = tax_for(taxable, DEFAULT_TAX_RATE)
        total = taxable + tax
        if item.expected_total is not None and total != item.expected_total:
            raise BadRequestError("Giá đã thay đổi kể từ lúc xem trước. Vui lòng tạo lại bản xem trước.")
        version = db.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM quotes WHERE repair_order_id=?",
            (item.repair_order_id,),
        ).fetchone()[0]
        code = f"BG-{order['id']}-{version:02d}"
        valid_until = _quote_valid_until(item.valid_until, db)
        cursor = db.execute(
            """INSERT INTO quotes(code, repair_order_id, version, status, subtotal, discount,
                   tax, total, tax_rate, valid_until, note, created_by)
               VALUES(?, ?, ?, 'Nháp', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (code, item.repair_order_id, version, subtotal, discount, tax, total,
             float(DEFAULT_TAX_RATE), valid_until,
             "Phần diễn giải đang chờ xử lý; số tiền đã được backend xác nhận.", user["id"]),
        )
        quote_id = cursor.lastrowid
        for row in lines:
            amount = line_total(row["quantity"], row["unit_price"])
            minutes, source = (service_duration(db, row["service_id"], row["name"], row["quantity"])
                               if row["kind"] == "Dịch vụ" else (None, None))
            row["estimated_duration_min"] = minutes
            row["estimate_source"] = source
            db.execute(
                """INSERT INTO quote_items(quote_id, kind, service_id, part_id, name, quantity,
                        unit_price, line_total, estimated_duration_min, estimate_source)
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (quote_id, row["kind"], row["service_id"], row["part_id"], row["name"],
                 row["quantity"], to_vnd(row["unit_price"]), amount, minutes, source),
            )
        duration = quote_duration(db, quote_id)
        db.execute("UPDATE quotes SET estimated_duration_min=? WHERE id=?", (duration, quote_id))
        write_audit(db, user, "quote.ai_draft.create", "quotes", quote_id,
                    {"code": code, "total": total, "source": "database"}, client_ip(request))

    # Gọi AI sau khi báo giá tài chính đã commit: provider lỗi không làm mất báo giá.
    # Lời giải thích dành cho khách: không đưa ghi chú nội bộ vào prompt/provider.
    ai_context = _narrative_context(order, lines, duration)
    if item.explanation is not None:
        generated, error_text = AIResult(item.explanation.strip(), "success", "staff", "reviewed"), None
    else:
        generated, error_text = _generate_narrative(ai_context)
    with connect() as db, transaction(db):
        db.execute("UPDATE quotes SET note=? WHERE id=?", (generated.content, quote_id))
        prompt_hash = hashlib.sha256(json.dumps(
            {"quote_id": quote_id, "service_item_ids": item.service_item_ids,
             "part_usage_ids": item.part_usage_ids}, sort_keys=True
        ).encode()).hexdigest()
        persisted_status = generated.status if generated.status in {"success", "fallback", "error"} else "fallback"
        db.execute(
            """INSERT INTO ai_interactions(user_id, task_type, ref_type, ref_id, status,
                   provider, model, prompt_hash, metadata, latency_ms)
               VALUES(?, 'estimate', 'quote', ?, ?, ?, ?, ?, ?, ?)""",
            (user["id"], str(quote_id), persisted_status, generated.provider, generated.model,
             prompt_hash, json.dumps({"error": error_text, "financial_source": "database"}, ensure_ascii=False),
             int((time.perf_counter() - started) * 1000)),
        )
    return {
        "id": quote_id, "code": code, "version": version, "status": "Nháp",
        "subtotal": subtotal, "labor_subtotal": labor_subtotal, "parts_subtotal": parts_subtotal,
        "discount": discount, "tax": tax, "total": total, "tax_rate": float(DEFAULT_TAX_RATE),
        "valid_until": valid_until, "ai_status": generated.status, "explanation": generated.content,
        "estimated_duration_min": duration,
        "sources": [{"type": "repair_order", "id": order["id"],
                     "label": f"Phiếu sửa chữa {order['code']}"},
                    {"type": "quote", "id": quote_id, "label": f"Báo giá nháp {code}"}],
    }


@router.get("", response_model=Page[QuoteOut], response_model_exclude_none=True)
def list_quotes(
    order_id: int | None = Query(default=None, ge=1),
    status: str = Query(default="", max_length=40),
    page: PageParams = Depends(page_params),
    user: dict = Depends(require_permission("repair_orders")),
) -> dict:
    base = """
        SELECT q.*, ro.code AS order_code, ro.plate FROM quotes q
        JOIN repair_orders ro ON ro.id = q.repair_order_id WHERE 1 = 1
    """
    params: list = []
    if order_id:
        base += " AND q.repair_order_id = ?"
        params.append(order_id)
    if status and status != "Tất cả":
        base += " AND q.status = ?"
        params.append(status)
    with connect() as db:
        items, total = fetch_page(db, base, tuple(params), "ORDER BY q.id DESC", page)
        items = [_expire_if_needed(db, dict(item)) for item in items]
    return envelope(items, total, page)


@router.get("/{quote_id}", response_model=QuoteDetailOut, response_model_exclude_none=True)
def quote_detail(
    quote_id: int,
    user: dict = Depends(require_permission("repair_orders")),
) -> dict:
    with connect() as db:
        quote = db.execute(
            "SELECT q.*, ro.code AS order_code, ro.plate, ro.customer_id AS owner_customer_id "
            "FROM quotes q JOIN repair_orders ro ON ro.id = q.repair_order_id WHERE q.id=?",
            (quote_id,),
        ).fetchone()
        if not quote:
            raise NotFoundError("Không tìm thấy báo giá")
        ensure_record_access(db, user, quote["owner_customer_id"])
        quote = _expire_if_needed(db, dict(quote))
        items = [dict(row) for row in db.execute(
            "SELECT * FROM quote_items WHERE quote_id=? ORDER BY id", (quote_id,)
        ).fetchall()]
    payload = dict(quote)
    payload.pop("owner_customer_id", None)
    return {**payload, "items": items}


@router.patch("/{quote_id}/narrative", response_model=QuoteDetailOut, response_model_exclude_none=True)
def update_quote_narrative(
    quote_id: int,
    item: QuoteNarrativeIn,
    request: Request,
    user: dict = Depends(require_permission("repair_orders")),
) -> dict:
    """Chỉ sửa lời giải thích trên bản nháp; các con số và hạng mục bất biến."""
    with connect() as db, transaction(db):
        quote = db.execute("SELECT * FROM quotes WHERE id=?", (quote_id,)).fetchone()
        if not quote:
            raise NotFoundError("Không tìm thấy báo giá")
        quote = _expire_if_needed(db, dict(quote))
        if quote["status"] != "Nháp":
            raise BadRequestError("Chỉ có thể sửa diễn giải khi báo giá ở trạng thái Nháp")
        db.execute("UPDATE quotes SET note=? WHERE id=?", (item.note, quote_id))
        write_audit(db, user, "quote.narrative.update", "quotes", quote_id,
                    {"length": len(item.note)}, client_ip(request))
    return quote_detail(quote_id, user)


@router.post("", status_code=201, response_model=QuoteCreatedOut, response_model_exclude_none=True)
def create_quote(
    item: QuoteIn,
    request: Request,
    user: dict = Depends(require_permission("repair_orders")),
) -> dict:
    with connect() as db, transaction(db):
        if item.discount > 0:
            ensure_role(
                user,
                ("Admin", "Quản lý"),
                message="Chỉ Admin/Quản lý được áp dụng chiết khấu.",
            )
        configured_tax_rate = float(DEFAULT_TAX_RATE)
        order = db.execute("SELECT * FROM repair_orders WHERE id=?", (item.repair_order_id,)).fetchone()
        if not order:
            raise NotFoundError("Không tìm thấy phiếu sửa chữa")
        ensure_record_access(db, user, order["customer_id"])
        if order_status_code(order) in ("DELIVERED", "CANCELLED"):
            raise BadRequestError("Phiếu đã kết thúc, không thể tạo báo giá.")
        version = db.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM quotes WHERE repair_order_id=?",
            (item.repair_order_id,),
        ).fetchone()[0]
        code = f"BG-{order['id']}-{version:02d}"
        valid_until = _quote_valid_until(item.valid_until, db)
        cursor = db.execute(
            "INSERT INTO quotes(code, repair_order_id, version, status, subtotal, discount, tax, total, tax_rate, valid_until, note, created_by) "
            "VALUES(?, ?, ?, 'Chờ duyệt', 0, ?, 0, 0, ?, ?, ?, ?)",
            (code, item.repair_order_id, version, to_vnd(item.discount), configured_tax_rate, valid_until, item.note.strip(), user["id"]),
        )
        quote_id = cursor.lastrowid
        subtotal = 0
        for entry in item.items:
            price = to_vnd(entry.unit_price)
            amount = line_total(entry.quantity, price)
            subtotal += amount
            minutes, source = (service_duration(db, entry.service_id, entry.name, entry.quantity)
                               if entry.kind == "Dịch vụ" else (None, None))
            db.execute(
                "INSERT INTO quote_items(quote_id, kind, service_id, part_id, name, quantity, unit_price, line_total, estimated_duration_min, estimate_source) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (quote_id, entry.kind, entry.service_id, entry.part_id, entry.name, entry.quantity, price, amount, minutes, source),
            )
        discount = to_vnd(item.discount)
        taxable = max(0, subtotal - discount)
        tax = tax_for(taxable, configured_tax_rate)
        total = taxable + tax
        duration = quote_duration(db, quote_id)
        db.execute(
            "UPDATE quotes SET subtotal=?, discount=?, tax=?, total=?, estimated_duration_min=? WHERE id=?",
            (subtotal, discount, tax, total, duration, quote_id),
        )
        write_audit(db, user, "quote.create", "quotes", quote_id, {"code": code, "total": total}, client_ip(request))
    return {
        "id": quote_id,
        "code": code,
        "version": version,
        "status": "Chờ duyệt",
        "subtotal": subtotal,
        "discount": discount,
        "tax": tax,
        "total": total,
        "tax_rate": configured_tax_rate,
        "valid_until": valid_until,
        "estimated_duration_min": duration,
    }


@router.patch("/{quote_id}/status", response_model=QuoteStatusOut, response_model_exclude_none=True)
def update_quote_status(
    quote_id: int,
    item: QuoteStatusIn,
    request: Request,
    user: dict = Depends(require_permission("repair_orders")),
) -> dict:
    with connect() as db, transaction(db):
        quote = db.execute("SELECT * FROM quotes WHERE id=?", (quote_id,)).fetchone()
        if not quote:
            raise NotFoundError("Không tìm thấy báo giá")
        quote = _expire_if_needed(db, dict(quote))
        if item.status == "Đã duyệt":
            ensure_role(user, ("Admin", "Quản lý"), message="Chỉ Admin/Quản lý được duyệt báo giá.")
            latest = db.execute("SELECT id FROM quotes WHERE repair_order_id=? ORDER BY version DESC, id DESC LIMIT 1", (quote["repair_order_id"],)).fetchone()
            if latest["id"] != quote_id:
                raise BadRequestError("Đây không phải phiên bản báo giá mới nhất; vui lòng xử lý phiên bản mới.")
            error = approval_validity_error(quote["valid_until"])
            if error:
                raise BadRequestError(error)
        order = db.execute(
            "SELECT * FROM repair_orders WHERE id=?", (quote["repair_order_id"],)
        ).fetchone()
        if not order:
            raise NotFoundError("Không tìm thấy phiếu sửa chữa")

        allowed = {
            "Nháp": {"Chờ duyệt", "Từ chối"},
            "Chờ duyệt": {"Đã duyệt", "Từ chối"},
        }
        if item.status not in allowed.get(quote["status"], set()):
            raise BadRequestError("Chuyển trạng thái báo giá không hợp lệ")
        if order_status_code(order) in ("COMPLETED", "DELIVERED", "CANCELLED"):
            raise BadRequestError("Phiếu đã kết thúc, không thể thay đổi báo giá")

        if item.status == "Đã duyệt":
            # Duyệt báo giá là thao tác nhạy cảm: chỉ quản lý/admin và báo giá
            # phải có hạng mục, tổng tiền > 0, phiếu đã ở bước "Đã báo giá".
            ensure_role(
                user,
                ("Admin", "Quản lý"),
                message="Chỉ Admin/Quản lý được duyệt báo giá.",
            )
            code = order_status_code(order)
            if code != "QUOTED":
                raise BadRequestError(
                    "Hãy chuyển phiếu sang trạng thái Đã báo giá trước khi duyệt báo giá."
                )
            if code in ("COMPLETED", "DELIVERED", "CANCELLED"):
                raise BadRequestError("Phiếu đã kết thúc, không thể duyệt báo giá.")
            if quote["status"] == "Hết hiệu lực":
                raise BadRequestError("Báo giá đã hết thời hạn hiệu lực")
            line_count = int(
                db.execute(
                    "SELECT COUNT(*) FROM quote_items WHERE quote_id=?", (quote_id,)
                ).fetchone()[0]
            )
            if line_count == 0 or int(quote["total"] or 0) <= 0:
                raise BadRequestError(
                    "Báo giá phải có ít nhất một hạng mục và tổng tiền lớn hơn 0."
                )

        approved_by = user["id"] if item.status == "Đã duyệt" else quote["approved_by"]
        approved_at = now_utc_iso() if item.status == "Đã duyệt" else quote["approved_at"]
        if item.status == "Đã duyệt":
            error = approval_validity_error(quote["valid_until"])
            if error:
                raise BadRequestError(error)
        db.execute(
            "UPDATE quotes SET status=?, approved_by=?, approved_at=? WHERE id=?",
            (item.status, approved_by, approved_at, quote_id),
        )
        if item.status == "Đã duyệt":
            # Phiên bản cũ hơn còn hiệu lực sẽ tự động hết hiệu lực.
            db.execute(
                "UPDATE quotes SET status='Hết hiệu lực' WHERE repair_order_id=? AND id<>? AND status IN ('Nháp', 'Chờ duyệt')",
                (quote["repair_order_id"], quote_id),
            )
            # Phiếu đang chờ duyệt báo giá chuyển sang Đã duyệt ngay trong cùng
            # transaction; nếu điều kiện khác chưa đạt, toàn bộ thao tác rollback.
            if order_status_code(order) == "QUOTED":
                change_status(
                    db,
                    int(order["id"]),
                    "APPROVED",
                    f"Duyệt báo giá {quote['code']}",
                    user,
                )
        write_audit(db, user, "quote.status", "quotes", quote_id, {"status": item.status}, client_ip(request))
    return {"id": quote_id, "status": item.status}
