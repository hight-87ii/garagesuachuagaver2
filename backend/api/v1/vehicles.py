"""Module phương tiện (xe) và tra cứu xe của khách hàng."""

from fastapi import APIRouter, Depends, Query, Request

from ...core.access import customer_for_user, ensure_record_access
from ...core.audit import write_audit
from ...core.db import connect, normalize_plate, transaction
from ...core.deps import client_ip, require_permission
from ...core.errors import BadRequestError, ConflictError, NotFoundError
from ...core.pagination import PageParams, envelope, fetch_page, page_params, search_clause
from ...domain import backfill_repair_history, locate_vehicle
from ...schemas.common import Page
from ...schemas.vehicles import (
    MyVehiclesOut,
    VehicleDetailOut,
    VehicleHistoryOut,
    VehicleIn,
    VehicleOut,
    VehicleUpdate,
)
from ...timeutil import vn_text

router = APIRouter(prefix="/vehicles", tags=["Vehicles"])
my_router = APIRouter(prefix="/my-vehicles", tags=["Vehicles"])

# Số km mới nhất đã ghi nhận cho xe (ưu tiên lịch sử, dự phòng theo cột mileage của xe).
_LAST_MILEAGE_SQL = (
    "(SELECT rh.mileage FROM repair_history rh WHERE rh.vehicle_id = v.id AND rh.mileage IS NOT NULL "
    "ORDER BY rh.repaired_at DESC, rh.id DESC LIMIT 1)"
)
_LAST_SERVICE_SQL = (
    "(SELECT rh.services FROM repair_history rh WHERE rh.vehicle_id = v.id "
    "ORDER BY rh.repaired_at DESC, rh.id DESC LIMIT 1)"
)
_LAST_NOTE_SQL = (
    "(SELECT rh.note FROM repair_history rh WHERE rh.vehicle_id = v.id "
    "AND TRIM(COALESCE(rh.note, '')) <> '' ORDER BY rh.repaired_at DESC, rh.id DESC LIMIT 1)"
)
_HISTORY_SELECT = """
    SELECT rh.*, ro.code AS order_code, ro.status AS order_status, ro.technician AS order_technician
    FROM repair_history rh
    LEFT JOIN repair_orders ro ON ro.id = rh.repair_order_id
"""


def _customer_summary(db, customer_id: int | None) -> dict:
    if not customer_id:
        return {}
    row = db.execute("SELECT id, name, phone FROM customers WHERE id=?", (customer_id,)).fetchone()
    return dict(row) if row else {}


def insert_vehicle(
    db,
    customer_id: int,
    item: VehicleIn,
    user: dict,
    request: Request,
    reuse_existing: bool = False,
) -> dict:
    """Tạo xe mới cho một khách hàng (dùng chung cho nhiều endpoint).

    Kiểm tra trùng lặp theo biển số (đã chuẩn hóa) và số VIN:
    - Nếu xe đã tồn tại và thuộc đúng khách hàng này: khi ``reuse_existing`` bật thì
      trả về bản ghi hiện có (kèm ``reused = True``) thay vì tạo trùng.
    - Nếu xe đã thuộc khách hàng khác: trả lỗi kèm thông tin bản ghi để client
      quyết định dùng endpoint liên kết (``/vehicles/{id}/link``).
    """
    plate = item.plate.strip().upper()
    if not db.execute("SELECT id FROM customers WHERE id=?", (customer_id,)).fetchone():
        raise NotFoundError("Không tìm thấy khách hàng")

    vin = (item.vin or "").strip().upper() or None
    duplicate = locate_vehicle(db, plate)
    if duplicate is not None:
        # locate_vehicle chỉ trả về vài cột, đọc lại bản ghi đầy đủ.
        duplicate = db.execute("SELECT * FROM vehicles WHERE id=?", (duplicate["id"],)).fetchone()
    elif vin:
        duplicate = db.execute("SELECT * FROM vehicles WHERE vin=?", (vin,)).fetchone()

    if duplicate is not None:
        existing = dict(duplicate)
        detail = {
            "reason": "duplicate_plate" if normalize_plate(plate) == existing["plate_normalized"] else "duplicate_vin",
            "vehicle": existing,
            "customer": _customer_summary(db, existing["customer_id"]),
            "same_customer": int(existing["customer_id"]) == int(customer_id),
            "suggest": "reuse_existing"
            if int(existing["customer_id"]) == int(customer_id)
            else "link_vehicle",
        }
        if reuse_existing and detail["same_customer"]:
            return {**existing, "reused": True}
        raise ConflictError(
            "Biển số hoặc số VIN đã tồn tại trong hệ thống", details=detail
        )

    cursor = db.execute(
        """
        INSERT INTO vehicles(customer_id, plate, plate_normalized, vin, make, model, year,
                             variant, engine_code, fuel_type, mileage)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            customer_id,
            plate,
            normalize_plate(plate),
            vin,
            item.make.strip(),
            item.model.strip(),
            item.year,
            item.variant,
            item.engine_code,
            item.fuel_type,
            item.mileage,
        ),
    )
    vehicle_id = cursor.lastrowid
    write_audit(
        db, user, "vehicle.create", "vehicles", vehicle_id,
        {"customer_id": customer_id, "plate": plate}, client_ip(request),
    )
    return dict(db.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone())


def link_vehicle(
    db,
    vehicle_id: int,
    customer_id: int,
    user: dict,
    request: Request,
    move: bool = False,
    note: str = "",
) -> dict:
    """Liên kết xe đã có vào hồ sơ khách hàng (đúng bản ghi hiện có).

    * Cùng chủ sở hữu: không làm gì (idempotent).
    * Khác chủ sở hữu: chỉ chuyển khi ``move = True``; ngược lại trả lỗi kèm dữ liệu
      để client xác nhận.
    """
    vehicle = db.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
    if not vehicle:
        raise NotFoundError("Không tìm thấy xe")
    if not db.execute("SELECT id FROM customers WHERE id=?", (customer_id,)).fetchone():
        raise NotFoundError("Không tìm thấy khách hàng")

    if int(vehicle["customer_id"]) == int(customer_id):
        return {**dict(vehicle), "linked": False, "reused": True}

    if not move:
        raise ConflictError(
            "Xe đang thuộc khách hàng khác, cần xác nhận chuyển",
            details={
                "reason": "vehicle_belongs_to_other_customer",
                "vehicle": dict(vehicle),
                "current_customer": _customer_summary(db, vehicle["customer_id"]),
                "target_customer": _customer_summary(db, customer_id),
                "require": "move",
            },
        )

    previous_customer = vehicle["customer_id"]
    db.execute("UPDATE vehicles SET customer_id=? WHERE id=?", (customer_id, vehicle_id))
    write_audit(
        db, user, "vehicle.link", "vehicles", vehicle_id,
        {
            "from_customer_id": previous_customer,
            "to_customer_id": customer_id,
            "plate": vehicle["plate"],
            "note": note,
        },
        client_ip(request),
    )
    updated = dict(db.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone())
    return {**updated, "linked": True, "previous_customer": _customer_summary(db, previous_customer)}


def vehicle_history_rows(db, vehicle_id: int, plate: str) -> list[dict]:
    return [
        dict(row)
        for row in db.execute(
            _HISTORY_SELECT
            + " WHERE rh.vehicle_id = ? OR (rh.vehicle_id IS NULL AND rh.plate = ?)"
            " ORDER BY rh.repaired_at DESC, rh.id DESC",
            (vehicle_id, plate),
        ).fetchall()
    ]



@router.get("", response_model=Page[VehicleOut], response_model_exclude_none=True)
def list_vehicles(
    q: str = Query(default="", max_length=120),
    page: PageParams = Depends(page_params),
    user: dict = Depends(require_permission("vehicles")),
) -> dict:
    base = f"""
        SELECT v.*, c.name AS customer_name, c.phone AS customer_phone,
            (SELECT MAX(rh.repaired_at) FROM repair_history rh WHERE rh.vehicle_id = v.id) AS last_visit,
            COALESCE({_LAST_MILEAGE_SQL}, v.mileage) AS last_mileage,
            {_LAST_SERVICE_SQL} AS last_service,
            {_LAST_NOTE_SQL} AS last_note,
            (SELECT COUNT(*) FROM repair_history rh WHERE rh.vehicle_id = v.id) AS history_count,
            (SELECT COALESCE(SUM(rh.total), 0) FROM repair_history rh WHERE rh.vehicle_id = v.id) AS lifetime_value,
            (SELECT COUNT(*) FROM repair_orders ro WHERE ro.vehicle_id = v.id
                AND ro.status NOT IN ('Hoàn thành', 'Đã bàn giao', 'Đã hủy')) AS active_order_count,
            (SELECT COUNT(*) FROM appointments a WHERE a.vehicle_id = v.id
                AND a.status <> 'Đã hủy') AS appointment_count
        FROM vehicles v JOIN customers c ON c.id = v.customer_id WHERE 1 = 1
    """
    params: list = []
    clause, clause_params = search_clause(
        q,
        [
            "v.plate",
            "v.plate_normalized",
            "v.vin",
            "v.make",
            "v.model",
            "c.name",
            "c.phone",
        ],
    )
    base += clause
    params.extend(clause_params)
    with connect() as db:
        items, total = fetch_page(db, base, tuple(params), "ORDER BY v.plate COLLATE NOCASE", page)
    return envelope(items, total, page)


@router.get("/{vehicle_id}", response_model=VehicleDetailOut, response_model_exclude_none=True)
def vehicle_detail(
    vehicle_id: int,
    user: dict = Depends(require_permission("vehicles")),
) -> dict:
    with connect() as db, transaction(db):
        vehicle = db.execute(
            """
            SELECT v.*, c.name AS customer_name, c.phone AS customer_phone,
                   c.email AS customer_email, c.address AS customer_address
            FROM vehicles v JOIN customers c ON c.id = v.customer_id WHERE v.id = ?
            """,
            (vehicle_id,),
        ).fetchone()
        if not vehicle:
            raise NotFoundError("Không tìm thấy xe")
        # Chống IDOR: khách hàng chỉ xem được xe thuộc sở hữu của mình.
        ensure_record_access(db, user, vehicle["customer_id"])
        # Bổ sung lịch sử cho các phiếu đã hoàn thành nhưng chưa được đồng bộ.
        backfill_repair_history(db, vehicle_id=vehicle_id)
        history = vehicle_history_rows(db, vehicle_id, vehicle["plate"])
        notes = [dict(row) for row in db.execute(
            "SELECT rn.id, rn.content, rn.author_name, rn.created_at, ro.code AS order_code "
            "FROM repair_notes rn JOIN repair_orders ro ON ro.id = rn.repair_order_id "
            "WHERE ro.vehicle_id = ? ORDER BY rn.id DESC LIMIT 10",
            (vehicle_id,),
        ).fetchall()]
        appointments = [dict(row) for row in db.execute(
            "SELECT * FROM appointments WHERE vehicle_id=? ORDER BY appointment_at DESC LIMIT 8", (vehicle_id,)
        ).fetchall()]
        orders = [dict(row) for row in db.execute(
            "SELECT * FROM repair_orders WHERE vehicle_id=? ORDER BY id DESC LIMIT 8", (vehicle_id,)
        ).fetchall()]
        invoices = [dict(row) for row in db.execute(
            """
            SELECT i.*, ro.code AS order_code FROM invoices i
            JOIN repair_orders ro ON ro.id = i.repair_order_id
            WHERE ro.vehicle_id=? ORDER BY i.id DESC LIMIT 8
            """,
            (vehicle_id,),
        ).fetchall()]
    for item in appointments:
        item["appointment_at"] = vn_text(item["appointment_at"])
    for item in invoices:
        item["issued_at"] = vn_text(item["issued_at"])
    base = dict(vehicle)
    last_mileage = next((item["mileage"] for item in history if item["mileage"] is not None), None)
    last_note = next((item["note"] for item in history if (item["note"] or "").strip()), None)
    return {
        **base,
        "history": history,
        "notes": notes,
        "appointments": appointments,
        "orders": orders,
        "invoices": invoices,
        "last_mileage": last_mileage if last_mileage is not None else base.get("mileage"),
        "last_service": history[0]["services"] if history else None,
        "last_note": last_note,
        "lifetime_value": sum(int(item["total"] or 0) for item in history),
    }


@router.post("", status_code=201, response_model=VehicleOut, response_model_exclude_none=True)
def create_vehicle(
    item: VehicleIn,
    request: Request,
    customer_id: int = Query(..., gt=0, description="ID khách hàng sở hữu xe"),
    reuse_existing: bool = Query(
        default=False,
        description="Nếu biển số/VIN đã có và thuộc đúng khách hàng này, dùng lại bản ghi hiện có",
    ),
    user: dict = Depends(require_permission("vehicles")),
) -> dict:
    with connect() as db, transaction(db):
        return insert_vehicle(db, customer_id, item, user, request, reuse_existing=reuse_existing)


@router.post("/{vehicle_id}/link", response_model=VehicleOut, response_model_exclude_none=True)
def link_existing_vehicle(
    vehicle_id: int,
    request: Request,
    customer_id: int = Query(..., gt=0, description="ID khách hàng cần liên kết xe"),
    move: bool = Query(default=False, description="Xác nhận chuyển xe sang khách hàng mới"),
    note: str = Query(default="", max_length=500),
    user: dict = Depends(require_permission("vehicles")),
) -> dict:
    """Liên kết xe đã có với khách hàng (``move = true`` khi xe thuộc khách khác)."""
    with connect() as db, transaction(db):
        return link_vehicle(db, vehicle_id, customer_id, user, request, move=move, note=note)


@router.get("/{vehicle_id}/repairs", response_model=Page[VehicleHistoryOut], response_model_exclude_none=True)
def vehicle_repairs(
    vehicle_id: int,
    page: PageParams = Depends(page_params),
    user: dict = Depends(require_permission("vehicles")),
) -> dict:
    """Toàn bộ lịch sử sửa chữa của xe (theo ID), kèm phiếu sửa chữa liên quan."""
    with connect() as db, transaction(db):
        vehicle = db.execute("SELECT id, plate, customer_id FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
        if not vehicle:
            raise NotFoundError("Không tìm thấy xe")
        ensure_record_access(db, user, vehicle["customer_id"])
        backfill_repair_history(db, vehicle_id=vehicle_id)
        base = (
            _HISTORY_SELECT
            + " WHERE rh.vehicle_id = ? OR (rh.vehicle_id IS NULL AND rh.plate = ?)"
        )
        params = (vehicle_id, vehicle["plate"])
        items, total = fetch_page(db, base, params, "ORDER BY rh.repaired_at DESC, rh.id DESC", page)
    for item in items:
        item["source"] = "repair_order" if item.get("repair_order_id") else "manual"
    return envelope(items, total, page)


@router.patch("/{vehicle_id}", response_model=VehicleOut, response_model_exclude_none=True)
def update_vehicle(
    vehicle_id: int,
    item: VehicleUpdate,
    request: Request,
    user: dict = Depends(require_permission("vehicles")),
) -> dict:
    fields = item.model_dump(exclude_none=True)
    if not fields:
        raise BadRequestError("Không có dữ liệu cập nhật")
    with connect() as db, transaction(db):
        if not db.execute("SELECT id FROM vehicles WHERE id=?", (vehicle_id,)).fetchone():
            raise NotFoundError("Không tìm thấy xe")
        if "vin" in fields:
            vin = (fields["vin"] or "").strip().upper() or None
            if vin and db.execute(
                "SELECT id FROM vehicles WHERE vin=? AND id<>?", (vin, vehicle_id)
            ).fetchone():
                raise ConflictError("Số VIN đã tồn tại trong hệ thống")
            fields["vin"] = vin
        cursor = db.execute(
            f"UPDATE vehicles SET {', '.join(f'{key}=?' for key in fields)} WHERE id=?",
            (*fields.values(), vehicle_id),
        )
        if cursor.rowcount == 0:
            raise NotFoundError("Không tìm thấy xe")
        write_audit(db, user, "vehicle.update", "vehicles", vehicle_id, fields, client_ip(request))
        return dict(db.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone())


@router.get("/{plate}/history", response_model=Page[dict], response_model_exclude_none=True)
def vehicle_history(
    plate: str,
    page: PageParams = Depends(page_params),
    user: dict = Depends(require_permission("vehicles")),
) -> dict:
    base = "SELECT * FROM repair_history WHERE plate=?"
    params = (plate.upper(),)
    with connect() as db:
        items, total = fetch_page(db, base, params, "ORDER BY repaired_at DESC", page)
    if total == 0:
        raise NotFoundError("Chưa có lịch sử sửa chữa")
    return envelope(items, total, page)


@my_router.get("", response_model=MyVehiclesOut, response_model_exclude_none=True)
def my_vehicles(user: dict = Depends(require_permission("my_vehicles"))) -> dict:
    with connect() as db:
        customer = customer_for_user(db, user)
        if not customer:
            return {"customer": user, "vehicles": []}
        vehicles = [dict(row) for row in db.execute(
            "SELECT * FROM vehicles WHERE customer_id=? ORDER BY plate", (customer["id"],)
        ).fetchall()]
        result = []
        for vehicle in vehicles:
            vehicle_id = vehicle["id"]
            history = [dict(row) for row in db.execute(
                "SELECT * FROM repair_history WHERE vehicle_id=? ORDER BY repaired_at DESC", (vehicle_id,)
            ).fetchall()]
            orders = [dict(row) for row in db.execute(
                "SELECT id, code, plate, status, status_code, note, total FROM repair_orders "
                "WHERE vehicle_id=? ORDER BY id DESC LIMIT 5",
                (vehicle_id,),
            ).fetchall()]
            appointments = [dict(row) for row in db.execute(
                "SELECT id, service, appointment_at, status FROM appointments "
                "WHERE vehicle_id=? ORDER BY appointment_at DESC LIMIT 5",
                (vehicle_id,),
            ).fetchall()]
            for item in appointments:
                item["appointment_at"] = vn_text(item["appointment_at"])
            result.append({
                **vehicle,
                "history": history,
                "orders": orders,
                "appointments": appointments,
                "lifetime_value": sum(int(item["total"] or 0) for item in history),
            })
    return {"customer": customer, "vehicles": result}
