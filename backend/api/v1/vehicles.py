"""Module phương tiện (xe) và tra cứu xe của khách hàng."""

import re

from fastapi import APIRouter, Depends, Query, Request

from ...core.access import customer_for_user, ensure_record_access, ensure_role
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
    VehicleProfileUpdate,
)
from ...timeutil import vn_text
from ...timeutil import now_utc_iso

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
        known_makes = [row[0] for row in db.execute("SELECT DISTINCT make FROM vehicles WHERE TRIM(make)<>''")]
        for vehicle in vehicles:
            vehicle_id = vehicle["id"]
            history = [dict(row) for row in db.execute(
                """SELECT rh.*, ro.code AS order_code, ro.status AS order_status,
                          COALESCE(ro.received_at,ro.opened_at,ro.created_at) AS received_at,
                           ro.status_code AS order_status_code, ro.plate AS linked_order_plate,
                           ro.inspection_notes,
                          ro.initial_condition, ro.customer_request
                   FROM repair_history rh LEFT JOIN repair_orders ro
                     ON ro.id=rh.repair_order_id AND ro.vehicle_id=rh.vehicle_id
                   WHERE rh.vehicle_id=? ORDER BY rh.repaired_at DESC""", (vehicle_id,)
            ).fetchall()]
            for item in history:
                issues = []
                if item["repair_order_id"] and not item["order_code"]:
                    issues.append("Liên kết phiếu không khớp xe; nhân viên cần đối chiếu phiếu gốc")
                if item["order_code"] and normalize_plate(item["linked_order_plate"] or "") != normalize_plate(vehicle["plate"]):
                    issues.append("Biển số trên phiếu khác hồ sơ xe; cần đối chiếu")
                if normalize_plate(item["plate"] or "") != normalize_plate(vehicle["plate"]):
                    issues.append("Biển số trong lịch sử khác hồ sơ xe; cần đối chiếu")
                if item["repair_order_id"] and item["order_code"]:
                    item["items"] = [dict(row) for row in db.execute(
                        "SELECT kind,name,quantity FROM repair_order_items WHERE repair_order_id=? ORDER BY id",
                        (item["repair_order_id"],)).fetchall()]
                    item["parts"] = [dict(row) for row in db.execute(
                        "SELECT name,quantity FROM repair_order_parts WHERE repair_order_id=? ORDER BY id",
                        (item["repair_order_id"],)).fetchall()]
                    invoice = db.execute(
                        "SELECT code FROM invoices WHERE repair_order_id=? AND status<>'Đã hủy' ORDER BY id DESC LIMIT 1",
                        (item["repair_order_id"],)).fetchone()
                    quote = db.execute(
                        "SELECT code FROM quotes WHERE repair_order_id=? ORDER BY version DESC,id DESC LIMIT 1",
                        (item["repair_order_id"],)).fetchone()
                    item["invoice_code"] = invoice["code"] if invoice else None
                    item["quote_code"] = quote["code"] if quote else None
                else:
                    item["items"], item["parts"] = [], []
                described = " ".join([item["services"] or "", *[part["name"] for part in item["parts"]]])
                for make in known_makes:
                    if make.casefold() != vehicle["make"].casefold() and re.search(
                            rf"(?<!\w){re.escape(make)}(?!\w)", described, re.IGNORECASE):
                        issues.append("Mô tả nhắc đến hãng xe khác; cần đối chiếu phiếu gốc")
                        break
                item["review_flags"] = issues
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
                "profile": dict(db.execute("SELECT * FROM vehicle_profiles WHERE vehicle_id=?",
                                           (vehicle_id,)).fetchone() or {}),
                "history": history,
                "orders": orders,
                "appointments": appointments,
                "lifetime_value": sum(int(item["total"] or 0) for item in history),
            })
    return {"customer": customer, "vehicles": result}


_OWNER_PROFILE_FIELDS = {
    "color", "mileage", "first_registration_year", "vehicle_type", "seat_count",
    "door_count", "registration_info", "inspection_expires_at",
    "liability_insurance_expires_at", "comprehensive_insurance_expires_at",
}


def _save_profile(db, vehicle_id: int, fields: dict, user: dict, request: Request) -> dict:
    vehicle = db.execute("SELECT id,customer_id,mileage,year FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
    if not vehicle:
        raise NotFoundError("Không tìm thấy xe")
    ensure_record_access(db, user, vehicle["customer_id"])
    if not fields:
        raise BadRequestError("Không có dữ liệu cập nhật")
    if (fields.get("first_registration_year") is not None and vehicle["year"] is not None
            and fields["first_registration_year"] < vehicle["year"]):
        raise BadRequestError("Năm đăng ký lần đầu không thể trước năm sản xuất")
    vehicle_fields = {key: fields.pop(key) for key in ("color", "mileage") if key in fields}
    if "mileage" in vehicle_fields:
        mileage = vehicle_fields["mileage"]
        recorded = db.execute("SELECT MAX(mileage) FROM repair_history WHERE vehicle_id=?",
                              (vehicle_id,)).fetchone()[0]
        if mileage is None or mileage < max(vehicle["mileage"] or 0, recorded or 0):
            raise BadRequestError("Số km mới không được thấp hơn số km đã ghi trong hồ sơ")
        fields["mileage_updated_at"] = now_utc_iso()
    if any(key in fields for key in ("next_service_at", "next_service_mileage")):
        existing = db.execute("SELECT maintenance_source FROM vehicle_profiles WHERE vehicle_id=?",
                              (vehicle_id,)).fetchone()
        if not (fields.get("maintenance_source") or (existing and existing[0])):
            raise BadRequestError("Cần nguồn lịch bảo dưỡng đã xác minh trước khi đặt mốc tiếp theo")
    if vehicle_fields:
        db.execute(f"UPDATE vehicles SET {', '.join(key + '=?' for key in vehicle_fields)} WHERE id=?",
                   (*vehicle_fields.values(), vehicle_id))
    db.execute("INSERT OR IGNORE INTO vehicle_profiles(vehicle_id) VALUES(?)", (vehicle_id,))
    if fields:
        fields["updated_at"] = now_utc_iso()
        db.execute(f"UPDATE vehicle_profiles SET {', '.join(key + '=?' for key in fields)} WHERE vehicle_id=?",
                   (*fields.values(), vehicle_id))
    write_audit(db, user, "vehicle.profile.update", "vehicles", vehicle_id,
                {"fields": list(vehicle_fields) + list(fields)}, client_ip(request))
    return {"vehicle": dict(db.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()),
            "profile": dict(db.execute("SELECT * FROM vehicle_profiles WHERE vehicle_id=?",
                                       (vehicle_id,)).fetchone())}


@my_router.patch("/{vehicle_id}/profile")
def update_my_vehicle_profile(vehicle_id: int, item: VehicleProfileUpdate, request: Request,
                              user: dict = Depends(require_permission("my_vehicles"))) -> dict:
    fields = item.model_dump(exclude_unset=True, mode="json")
    if set(fields) - _OWNER_PROFILE_FIELDS:
        raise BadRequestError("Thông số kỹ thuật và lịch bảo dưỡng cần garage xác minh")
    with connect() as db, transaction(db):
        return _save_profile(db, vehicle_id, fields, user, request)


@router.patch("/{vehicle_id}/profile")
def update_vehicle_profile(vehicle_id: int, item: VehicleProfileUpdate, request: Request,
                           user: dict = Depends(require_permission("vehicles"))) -> dict:
    ensure_role(user, ("Admin", "Quản lý", "Kỹ thuật viên"),
                message="Chỉ nhân sự kỹ thuật hoặc quản lý được xác minh thông số và lịch bảo dưỡng")
    with connect() as db, transaction(db):
        return _save_profile(db, vehicle_id, item.model_dump(exclude_unset=True, mode="json"), user, request)
