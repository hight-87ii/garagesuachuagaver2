"""Module phiếu sửa chữa (repair orders), hạng mục, phụ tùng đã dùng và ghi chú.

Luồng trạng thái và các điều kiện nghiệp vụ nằm trong ``backend/workflow.py``.
Router này chỉ lắp ghép dữ liệu, kiểm tra quyền/IDOR, ghi audit và trả phản hồi.
"""

from fastapi import APIRouter, Depends, Header, Query, Request

from ...core.access import ensure_record_access, ensure_role
from ...core.audit import write_audit
from ...core.db import connect, transaction
from ...core.deps import client_ip, require_permission
from ...core.errors import BadRequestError, ConflictError, NotFoundError
from ...core.pagination import PageParams, envelope, fetch_page, page_params, search_clause
from ...domain import (
    customer_name_for,
    locate_vehicle,
    next_order_code,
    sync_order_total,
    sync_vehicle_mileage,
    technician_id_for,
)
from ...money import line_total, to_vnd
from ...schemas.common import Page
from ...schemas.repair_orders import (
    DeletedOut,
    RepairNoteIn,
    RepairNoteOut,
    RepairOrderCreatedOut,
    RepairOrderDetailOut,
    RepairOrderIn,
    RepairOrderItemCreatedOut,
    RepairOrderItemIn,
    RepairItemActualDurationIn,
    RepairOrderOut,
    RepairOrderPartCreatedOut,
    RepairOrderPartIn,
    RepairOrderPartOut,
    RepairOrderStatusHistoryOut,
    RepairOrderTransitionIn,
    RepairOrderTransitionOut,
    RepairOrderUpdate,
)
from ...timeutil import now_utc_iso
from ...workflow import (
    EDITABLE_STATUS_CODES,
    change_status,
    ensure_status_history,
    history_for,
    order_status_code,
    resolve_status_code,
    status_label,
    transition_payload,
    workflow_definition,
)

router = APIRouter(prefix="/repair-orders", tags=["Repair Orders"])


@router.get("/options")
def repair_order_options(user: dict = Depends(require_permission("repair_orders"))) -> dict:
    with connect() as db:
        technicians = [dict(row) for row in db.execute(
            "SELECT id,full_name FROM users WHERE role='Kỹ thuật viên' AND status='active' ORDER BY full_name"
        ).fetchall()]
        services = [dict(row) for row in db.execute(
            "SELECT id,name,category,description,price,duration_min FROM services WHERE active=1 ORDER BY category,name"
        ).fetchall()]
    return {"technicians": technicians, "services": services,
            "priorities": ["Thấp", "Bình thường", "Cao", "Gấp"]}


def _order_or_404(db, order_id: int, *, with_access: bool = False, user: dict | None = None) -> dict:
    row = db.execute("SELECT * FROM repair_orders WHERE id=?", (order_id,)).fetchone()
    if not row:
        raise NotFoundError("Không tìm thấy phiếu sửa chữa")
    order = dict(row)
    if with_access and user is not None:
        ensure_record_access(db, user, order.get("customer_id"))
    return order


def _ensure_editable(order: dict) -> None:
    code = order_status_code(order)
    if code not in EDITABLE_STATUS_CODES:
        raise BadRequestError(
            "Phiếu đã hoàn thành, bàn giao hoặc hủy nên không thể sửa nội dung.",
            details={"status_code": code},
        )


@router.get("/workflow", response_model=dict)
def get_repair_order_workflow(
    _: dict = Depends(require_permission("repair_orders")),
) -> dict:
    """Đồ thị trạng thái và điều kiện của từng bước chuyển."""
    return workflow_definition()


@router.get("", response_model=Page[RepairOrderOut], response_model_exclude_none=True)
def list_repair_orders(
    status: str = Query(default="", max_length=40),
    q: str = Query(default="", max_length=120),
    page: PageParams = Depends(page_params),
    user: dict = Depends(require_permission("repair_orders")),
) -> dict:
    base = """
        SELECT r.*, v.make, v.model, v.year, v.color, v.vin,
               (SELECT COUNT(*) FROM repair_order_items i WHERE i.repair_order_id = r.id) AS item_count,
               (SELECT COUNT(*) FROM repair_order_parts p WHERE p.repair_order_id = r.id) AS part_count
        FROM repair_orders r
        LEFT JOIN vehicles v ON v.id = r.vehicle_id
        WHERE 1 = 1
    """
    params: list = []
    if status and status != "Tất cả":
        base += " AND r.status_code = ?"
        params.append(resolve_status_code(status))
    clause, clause_params = search_clause(
        q,
        [
            "r.code",
            "r.plate",
            "r.technician",
            "r.note",
            "r.customer_name",
            "r.customer_request",
            "r.inspection_notes",
        ],
    )
    base += clause
    params.extend(clause_params)
    with connect() as db:
        items, total = fetch_page(db, base, tuple(params), "ORDER BY r.id DESC", page)
    return envelope(items, total, page)


@router.get("/{order_id}", response_model=RepairOrderDetailOut, response_model_exclude_none=True)
def repair_order_detail(
    order_id: int,
    user: dict = Depends(require_permission("repair_orders")),
) -> dict:
    with connect() as db:
        order = db.execute(
            """
            SELECT r.*, v.make, v.model, v.year, v.color, v.vin, v.mileage,
                   c.name AS customer_name, c.phone AS customer_phone
            FROM repair_orders r
            LEFT JOIN vehicles v ON v.id = r.vehicle_id
            LEFT JOIN customers c ON c.id = r.customer_id
            WHERE r.id = ?
            """,
            (order_id,),
        ).fetchone()
        if not order:
            raise NotFoundError("Không tìm thấy phiếu sửa chữa")
        # Chống IDOR theo từng bản ghi.
        ensure_record_access(db, user, order["customer_id"])
        ensure_status_history(db, order_id, order)
        items = [dict(row) for row in db.execute(
            "SELECT * FROM repair_order_items WHERE repair_order_id=? ORDER BY id", (order_id,)
        ).fetchall()]
        parts_used = [dict(row) for row in db.execute(
            """
            SELECT rp.*, p.code AS part_code, p.unit FROM repair_order_parts rp
            JOIN parts p ON p.id = rp.part_id WHERE rp.repair_order_id=? ORDER BY rp.id
            """,
            (order_id,),
        ).fetchall()]
        notes = [dict(row) for row in db.execute(
            "SELECT * FROM repair_notes WHERE repair_order_id=? ORDER BY id DESC", (order_id,)
        ).fetchall()]
        quotes = [dict(row) for row in db.execute(
            "SELECT * FROM quotes WHERE repair_order_id=? ORDER BY version DESC", (order_id,)
        ).fetchall()]
        history = history_for(db, order_id, order)
        workflow = transition_payload(db, order)
    return {
        **dict(order),
        "items": items,
        "parts_used": parts_used,
        "notes": notes,
        "quotes": quotes,
        "history": history,
        "allowed_transitions": workflow["allowed_transitions"],
    }


@router.get("/{order_id}/history", response_model=list[RepairOrderStatusHistoryOut])
def repair_order_status_history(
    order_id: int,
    user: dict = Depends(require_permission("repair_orders")),
) -> list[dict]:
    with connect() as db:
        order = _order_or_404(db, order_id, with_access=True, user=user)
        return history_for(db, order_id, order)


@router.post("", status_code=201, response_model=RepairOrderCreatedOut, response_model_exclude_none=True)
def create_repair_order(
    item: RepairOrderIn,
    request: Request,
    user: dict = Depends(require_permission("repair_orders")),
) -> dict:
    requested = item.status_code or item.status
    if resolve_status_code(requested) != "RECEIVED":
        raise BadRequestError("Phiếu mới phải bắt đầu ở trạng thái Tiếp nhận (RECEIVED).")
    plate = item.plate.strip().upper()
    received_at = now_utc_iso()
    with connect() as db, transaction(db):
        code = item.code.strip() or next_order_code(db)
        if db.execute("SELECT id FROM repair_orders WHERE code=?", (code,)).fetchone():
            raise ConflictError("Mã phiếu đã tồn tại")
        vehicle = locate_vehicle(db, plate)
        vehicle_id = item.vehicle_id or (vehicle["id"] if vehicle else None)
        customer_id = item.customer_id or (vehicle["customer_id"] if vehicle else None)
        cursor = db.execute(
            """
            INSERT INTO repair_orders(
                code, customer_id, vehicle_id, plate, customer_name, advisor_id,
                technician_id, technician, status, status_code, priority, km_in,
                note, initial_condition, customer_request, inspection_notes,
                total, received_at, opened_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'Tiếp nhận', 'RECEIVED', ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                code,
                customer_id,
                vehicle_id,
                plate,
                customer_name_for(db, customer_id),
                user["id"],
                technician_id_for(db, item.technician),
                item.technician,
                item.priority,
                item.km_in,
                item.note,
                item.initial_condition,
                item.customer_request,
                item.inspection_notes,
                received_at,
                received_at,
            ),
        )
        order_id = cursor.lastrowid
        ensure_status_history(
            db,
            order_id,
            {
                "status_code": "RECEIVED",
                "status": "Tiếp nhận",
                "advisor_id": user["id"],
                "received_at": received_at,
            },
        )
        write_audit(
            db, user, "repair_order.create", "repair_orders", order_id,
            {"code": code, "plate": plate}, client_ip(request),
        )
    return {
        "id": order_id,
        "code": code,
        "plate": plate,
        "status": "Tiếp nhận",
        "status_code": "RECEIVED",
        "priority": item.priority,
        "technician": item.technician,
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
        "note": item.note,
        "km_in": item.km_in,
        "initial_condition": item.initial_condition,
        "customer_request": item.customer_request,
        "inspection_notes": item.inspection_notes,
        "received_at": received_at,
        "total": 0,
    }


@router.patch("/{order_id}", response_model=RepairOrderOut, response_model_exclude_none=True)
def update_repair_order(
    order_id: int,
    item: RepairOrderUpdate,
    request: Request,
    user: dict = Depends(require_permission("repair_orders")),
) -> dict:
    fields = item.model_dump(exclude_none=True)
    target_label = fields.pop("status", None)
    target_code = fields.pop("status_code", None)
    status_note = fields.pop("status_note", "") or ""
    if not fields and not target_code and not target_label:
        raise BadRequestError("Không có dữ liệu cập nhật")

    with connect() as db, transaction(db):
        order = _order_or_404(db, order_id, with_access=True, user=user)
        current = order_status_code(order)
        if current not in EDITABLE_STATUS_CODES:
            raise BadRequestError("Phiếu đã kết thúc, không thể cập nhật.")

        if target_label and target_code:
            if resolve_status_code(target_label) != resolve_status_code(target_code):
                raise BadRequestError("Trạng thái và mã trạng thái không khớp nhau.")
        target = target_code or target_label
        if target:
            target_code_value = resolve_status_code(target)
            if target_code_value in ("CANCELLED", "DELIVERED"):
                ensure_role(
                    user,
                    ("Admin", "Quản lý"),
                    message="Chỉ Admin/Quản lý được hủy phiếu hoặc xác nhận bàn giao.",
                )
            change_status(db, order_id, target_code_value, status_note, user)

        if fields:
            if "technician" in fields:
                fields["technician_id"] = technician_id_for(db, fields["technician"])
            assignments = ", ".join(f"{key}=?" for key in fields)
            cursor = db.execute(
                f"UPDATE repair_orders SET {assignments} WHERE id=?",
                (*fields.values(), order_id),
            )
            if cursor.rowcount == 0:
                raise NotFoundError("Không tìm thấy phiếu sửa chữa")
            if fields.get("km_in") is not None:
                sync_vehicle_mileage(db, order["vehicle_id"], fields["km_in"])

        write_audit(
            db, user, "repair_order.update", "repair_orders", order_id,
            {key: str(value) for key, value in fields.items()}
            | ({"status_code": target_code_value} if target else {}),
            client_ip(request),
        )
        return dict(db.execute("SELECT * FROM repair_orders WHERE id=?", (order_id,)).fetchone())


@router.post(
    "/{order_id}/transition",
    response_model=RepairOrderTransitionOut,
    response_model_exclude_none=True,
)
def transition_repair_order(
    order_id: int,
    item: RepairOrderTransitionIn,
    request: Request,
    user: dict = Depends(require_permission("repair_orders")),
) -> dict:
    """Chuyển trạng thái theo đúng đồ thị, kiểm tra điều kiện nghiệp vụ."""
    target = resolve_status_code(item.status_code)
    if target in ("CANCELLED", "DELIVERED"):
        ensure_role(
            user,
            ("Admin", "Quản lý"),
            message="Chỉ Admin/Quản lý được hủy phiếu hoặc xác nhận bàn giao.",
        )
    with connect() as db, transaction(db):
        order = _order_or_404(db, order_id, with_access=True, user=user)
        old_code = order_status_code(order)
        updated = change_status(db, order_id, target, item.note, user)
        history = history_for(db, order_id, updated)
        workflow = transition_payload(db, updated)
        write_audit(
            db, user, "repair_order.transition", "repair_orders", order_id,
            {"from": old_code, "to": target, "note": item.note.strip()},
            client_ip(request),
        )
    return {
        **updated,
        "allowed_transitions": workflow["allowed_transitions"],
        "history_entry": history[-1] if history else None,
    }


def technician_id_for_with_db(full_name: str) -> int | None:
    with connect() as db:
        return technician_id_for(db, full_name)


@router.post("/{order_id}/items", status_code=201, response_model=RepairOrderItemCreatedOut, response_model_exclude_none=True)
def add_repair_order_item(
    order_id: int,
    item: RepairOrderItemIn,
    request: Request,
    user: dict = Depends(require_permission("repair_orders")),
) -> dict:
    with connect() as db, transaction(db):
        order = _order_or_404(db, order_id)
        _ensure_editable(order)
        item_name = item.name
        service_id = item.service_id
        if item.kind == "Dịch vụ" and service_id:
            service = db.execute(
                "SELECT id,name,price FROM services WHERE id=? AND active=1", (service_id,)
            ).fetchone()
            if not service:
                raise NotFoundError("Dịch vụ không tồn tại hoặc đã ngừng hoạt động")
            # Tên và giá phải đọc lại từ database, không tin dữ liệu gửi từ giao diện.
            item_name = service["name"]
            unit_price = to_vnd(service["price"])
        else:
            unit_price = to_vnd(item.unit_price)
        amount = line_total(item.quantity, unit_price)
        cursor = db.execute(
            "INSERT INTO repair_order_items(repair_order_id, service_id, kind, name, quantity, unit_price, line_total) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (order_id, service_id, item.kind, item_name, item.quantity, unit_price, amount),
        )
        item_id = cursor.lastrowid
        total = sync_order_total(db, order_id)
        write_audit(
            db, user, "repair_order.item_add", "repair_orders", order_id,
            {"item_id": item_id, "name": item_name, "service_id": service_id}, client_ip(request),
        )
    return {
        "id": item_id,
        "kind": item.kind,
        "name": item_name,
        "quantity": item.quantity,
        "unit_price": unit_price,
        "line_total": amount,
        "order_total": total,
    }


@router.patch("/{order_id}/items/{item_id}/actual-duration")
def record_actual_duration(
    order_id: int, item_id: int, item: RepairItemActualDurationIn, request: Request,
    user: dict = Depends(require_permission("repair_orders")),
) -> dict:
    ensure_role(user, ("Admin", "Quản lý", "Kỹ thuật viên"),
                message="Chỉ kỹ thuật viên hoặc quản lý được ghi thời gian thực tế")
    with connect() as db, transaction(db):
        order = _order_or_404(db, order_id)
        if order_status_code(order) not in ("IN_PROGRESS", "COMPLETED"):
            raise BadRequestError("Chỉ ghi thời gian thực tế khi đang sửa hoặc đã hoàn thành")
        row = db.execute(
            "SELECT id,kind,service_id FROM repair_order_items WHERE id=? AND repair_order_id=?",
            (item_id, order_id),
        ).fetchone()
        if not row or row["kind"] != "Dịch vụ" or not row["service_id"]:
            raise BadRequestError("Chỉ ghi thời gian cho dịch vụ từ danh mục thuộc phiếu này")
        db.execute("UPDATE repair_order_items SET actual_duration_min=? WHERE id=?",
                   (item.actual_duration_min, item_id))
        write_audit(db, user, "repair_order.item_actual_duration", "repair_orders", order_id,
                    {"item_id": item_id, "actual_duration_min": item.actual_duration_min}, client_ip(request))
    return {"id": item_id, "actual_duration_min": item.actual_duration_min}


@router.delete("/{order_id}/items/{item_id}", response_model=DeletedOut, response_model_exclude_none=True)
def delete_repair_order_item(
    order_id: int,
    item_id: int,
    request: Request,
    user: dict = Depends(require_permission("repair_orders")),
) -> dict:
    with connect() as db, transaction(db):
        order = _order_or_404(db, order_id)
        _ensure_editable(order)
        cursor = db.execute("DELETE FROM repair_order_items WHERE id=? AND repair_order_id=?", (item_id, order_id))
        if cursor.rowcount == 0:
            raise NotFoundError("Không tìm thấy hạng mục")
        total = sync_order_total(db, order_id)
        write_audit(
            db, user, "repair_order.item_delete", "repair_orders", order_id,
            {"item_id": item_id}, client_ip(request),
        )
    return {"deleted": item_id, "order_total": total}


@router.get("/{order_id}/parts", response_model=Page[RepairOrderPartOut], response_model_exclude_none=True)
def list_order_parts(
    order_id: int,
    page: PageParams = Depends(page_params),
    user: dict = Depends(require_permission("repair_orders")),
) -> dict:
    base = """
        SELECT rp.*, p.code AS part_code, p.unit, p.stock FROM repair_order_parts rp
        JOIN parts p ON p.id = rp.part_id WHERE rp.repair_order_id=?
    """
    with connect() as db:
        items, total = fetch_page(db, base, (order_id,), "ORDER BY rp.id", page)
    return envelope(items, total, page)


@router.post("/{order_id}/parts", status_code=201, response_model=RepairOrderPartCreatedOut, response_model_exclude_none=True)
def add_order_part(
    order_id: int,
    item: RepairOrderPartIn,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: dict = Depends(require_permission("repair_orders")),
) -> dict:
    with connect() as db, transaction(db):
        order = _order_or_404(db, order_id)
        _ensure_editable(order)
        key = idempotency_key.strip() if idempotency_key and idempotency_key.strip() else None
        if key:
            previous = db.execute(
                "SELECT * FROM inventory_transactions WHERE idempotency_key=?", (key,)
            ).fetchone()
            if previous:
                if previous["operation"] != "CONSUME" or previous["part_id"] != item.part_id or previous["quantity"] != item.quantity or previous["repair_order_id"] != order_id:
                    raise ConflictError("Idempotency-Key đã được dùng cho giao dịch kho khác")
                record = db.execute(
                    "SELECT * FROM repair_order_parts WHERE id=?", (previous["repair_order_part_id"],)
                ).fetchone()
                total = sync_order_total(db, order_id)
                return {
                    "id": record["id"], "part_id": record["part_id"], "name": record["name"],
                    "quantity": record["quantity"], "unit_price": record["unit_price"],
                    "line_total": record["line_total"], "order_total": total,
                }
        part = db.execute("SELECT * FROM parts WHERE id=?", (item.part_id,)).fetchone()
        if not part:
            raise NotFoundError("Không tìm thấy phụ tùng")
        unit_price = to_vnd(part["sell_price"])
        amount = line_total(item.quantity, unit_price)
        cursor = db.execute(
            "INSERT INTO repair_order_parts(repair_order_id, part_id, name, quantity, unit_price, line_total, created_by) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (order_id, item.part_id, part["name"], item.quantity, unit_price, amount, user["id"]),
        )
        part_use_id = cursor.lastrowid
        stock_update = db.execute(
            "UPDATE parts SET stock = stock - ? WHERE id=? AND stock >= ?",
            (item.quantity, item.part_id, item.quantity),
        )
        if stock_update.rowcount == 0:
            raise BadRequestError("Số lượng tồn kho không đủ; không cho phép tồn kho âm")
        stock_after = db.execute("SELECT stock FROM parts WHERE id=?", (item.part_id,)).fetchone()["stock"]
        db.execute(
            "INSERT INTO inventory_transactions(idempotency_key, operation, part_id, repair_order_id, repair_order_part_id, quantity, stock_after, created_by) "
            "VALUES(?, 'CONSUME', ?, ?, ?, ?, ?, ?)",
            (key, item.part_id, order_id, part_use_id, item.quantity, stock_after, user["id"]),
        )
        total = sync_order_total(db, order_id)
        write_audit(
            db, user, "repair_order.part_add", "repair_orders", order_id,
            {"part_id": item.part_id, "quantity": item.quantity}, client_ip(request),
        )
    return {
        "id": part_use_id,
        "part_id": item.part_id,
        "name": part["name"],
        "quantity": item.quantity,
        "unit_price": unit_price,
        "line_total": amount,
        "order_total": total,
    }


@router.delete("/{order_id}/parts/{part_use_id}", response_model=DeletedOut, response_model_exclude_none=True)
def delete_order_part(
    order_id: int,
    part_use_id: int,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: dict = Depends(require_permission("repair_orders")),
) -> dict:
    with connect() as db, transaction(db):
        order = _order_or_404(db, order_id)
        _ensure_editable(order)
        key = (idempotency_key.strip() if idempotency_key and idempotency_key.strip() else f"reverse:repair-order-part:{part_use_id}")
        previous = db.execute(
            "SELECT * FROM inventory_transactions WHERE idempotency_key=?", (key,)
        ).fetchone()
        if previous:
            if previous["operation"] != "REVERSE" or previous["repair_order_id"] != order_id:
                raise ConflictError("Idempotency-Key đã được dùng cho giao dịch kho khác")
            return {"deleted": part_use_id, "order_total": sync_order_total(db, order_id)}
        record = db.execute(
            "SELECT * FROM repair_order_parts WHERE id=? AND repair_order_id=?", (part_use_id, order_id)
        ).fetchone()
        if not record:
            raise NotFoundError("Không tìm thấy phụ tùng đã dùng")
        db.execute("UPDATE parts SET stock = stock + ? WHERE id=?", (record["quantity"], record["part_id"]))
        stock_after = db.execute("SELECT stock FROM parts WHERE id=?", (record["part_id"],)).fetchone()["stock"]
        db.execute(
            "INSERT INTO inventory_transactions(idempotency_key, operation, part_id, repair_order_id, repair_order_part_id, quantity, stock_after, created_by) "
            "VALUES(?, 'REVERSE', ?, ?, ?, ?, ?, ?)",
            (key, record["part_id"], order_id, part_use_id, record["quantity"], stock_after, user["id"]),
        )
        db.execute("DELETE FROM repair_order_parts WHERE id=?", (part_use_id,))
        total = sync_order_total(db, order_id)
        write_audit(
            db, user, "repair_order.part_delete", "repair_orders", order_id,
            {"part_use_id": part_use_id}, client_ip(request),
        )
    return {"deleted": part_use_id, "order_total": total}


@router.get("/{order_id}/notes", response_model=Page[RepairNoteOut], response_model_exclude_none=True)
def list_repair_notes(
    order_id: int,
    page: PageParams = Depends(page_params),
    user: dict = Depends(require_permission("repair_orders")),
) -> dict:
    base = "SELECT * FROM repair_notes WHERE repair_order_id=?"
    with connect() as db:
        items, total = fetch_page(db, base, (order_id,), "ORDER BY id DESC", page)
    return envelope(items, total, page)


@router.post("/{order_id}/notes", status_code=201, response_model=RepairNoteOut, response_model_exclude_none=True)
def add_repair_note(
    order_id: int,
    item: RepairNoteIn,
    request: Request,
    user: dict = Depends(require_permission("repair_orders")),
) -> dict:
    with connect() as db, transaction(db):
        order = _order_or_404(db, order_id)
        _ensure_editable(order)
        cursor = db.execute(
            "INSERT INTO repair_notes(repair_order_id, author_id, author_name, content) VALUES(?, ?, ?, ?)",
            (order_id, user["id"], user["full_name"], item.content.strip()),
        )
        note_id = cursor.lastrowid
        write_audit(
            db, user, "repair_order.note_add", "repair_orders", order_id,
            {"note_id": note_id}, client_ip(request),
        )
    return {
        "id": note_id,
        "repair_order_id": order_id,
        "author_id": user["id"],
        "author_name": user["full_name"],
        "content": item.content.strip(),
        "created_at": now_utc_iso(),
    }
