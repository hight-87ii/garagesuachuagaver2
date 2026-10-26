"""Module khách hàng.

Phạm vi nghiệp vụ:
- Thêm/xem/sửa hồ sơ khách hàng.
- Quản lý nhiều xe của một khách hàng (thêm mới hoặc liên kết xe đã có).
- Tìm kiếm theo tên, số điện thoại, biển số, VIN.
- Phát hiện trùng lặp (điện thoại/email/tên/biển số/VIN) và hỗ trợ dùng lại bản ghi cũ.
- Hiển thị lần sửa gần nhất, số km gần nhất và ghi chú liên quan.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request

from ...core.access import ensure_record_access
from ...core.audit import write_audit
from ...core.db import connect, normalize_plate, transaction
from ...core.deps import client_ip, require_any_permission, require_permission
from ...core.errors import BadRequestError, ConflictError, NotFoundError
from ...core.pagination import PageParams, envelope, fetch_page, page_params
from ...domain import backfill_repair_history
from ...schemas.common import Page
from ...schemas.customers import CustomerDetailOut, CustomerIn, CustomerOut, CustomerUpdate
from ...schemas.lookup import LookupOut
from ...schemas.vehicles import LinkVehicleIn, VehicleIn, VehicleOut
from ...timeutil import vn_text
from .vehicles import insert_vehicle, link_vehicle

router = APIRouter(prefix="/customers", tags=["Customers"])
lookup_router = APIRouter(tags=["Lookup"])

# Số km / dịch vụ / ghi chú của lần sửa gần nhất (gộp theo mọi xe của khách).
_C_LAST_MILEAGE = (
    "(SELECT rh.mileage FROM vehicles v JOIN repair_history rh ON rh.vehicle_id = v.id "
    "WHERE v.customer_id = c.id AND rh.mileage IS NOT NULL "
    "ORDER BY rh.repaired_at DESC, rh.id DESC LIMIT 1)"
)
_C_MAX_MILEAGE = "(SELECT MAX(v.mileage) FROM vehicles v WHERE v.customer_id = c.id)"
_C_LAST_SERVICE = (
    "(SELECT rh.services FROM vehicles v JOIN repair_history rh ON rh.vehicle_id = v.id "
    "WHERE v.customer_id = c.id ORDER BY rh.repaired_at DESC, rh.id DESC LIMIT 1)"
)
_C_LAST_NOTE = (
    "(SELECT rh.note FROM vehicles v JOIN repair_history rh ON rh.vehicle_id = v.id "
    "WHERE v.customer_id = c.id AND TRIM(COALESCE(rh.note, '')) <> '' "
    "ORDER BY rh.repaired_at DESC, rh.id DESC LIMIT 1)"
)

_LIST_SELECT = f"""
    SELECT c.*,
        (SELECT COUNT(*) FROM vehicles v WHERE v.customer_id = c.id) AS vehicle_count,
        (SELECT GROUP_CONCAT(v.plate, ' • ') FROM vehicles v WHERE v.customer_id = c.id) AS plates,
        (SELECT GROUP_CONCAT(v.vin, ' • ') FROM vehicles v
            WHERE v.customer_id = c.id AND TRIM(COALESCE(v.vin, '')) <> '') AS vins,
        (SELECT MAX(rh.repaired_at) FROM vehicles v JOIN repair_history rh ON rh.vehicle_id = v.id
            WHERE v.customer_id = c.id) AS last_visit,
        COALESCE({_C_LAST_MILEAGE}, {_C_MAX_MILEAGE}) AS last_mileage,
        {_C_LAST_SERVICE} AS last_service,
        {_C_LAST_NOTE} AS last_note,
        (SELECT COALESCE(SUM(rh.total), 0) FROM vehicles v JOIN repair_history rh ON rh.vehicle_id = v.id
            WHERE v.customer_id = c.id) AS lifetime_value,
        (SELECT COUNT(*) FROM appointments a WHERE a.customer_id = c.id) AS appointment_count
    FROM customers c
    WHERE 1 = 1
"""


def normalize_phone(value: str) -> str:
    """Chuẩn hóa số điện thoại về dãy chữ số để so khớp trùng lặp."""
    return "".join(character for character in (value or "") if character.isdigit())


def find_customer_duplicates(
    db,
    *,
    phone: str = "",
    email: str = "",
    name: str = "",
    plate: str = "",
    vin: str = "",
) -> list[dict]:
    """Tìm các hồ sơ khách hàng có khả năng trùng, kèm lý do khớp."""
    matches: dict[int, str] = {}

    digits = normalize_phone(phone)
    if digits:
        for row in db.execute(
            "SELECT id, phone FROM customers WHERE COALESCE(phone, '') <> ''"
        ).fetchall():
            if digits in normalize_phone(row["phone"]):
                matches.setdefault(row["id"], "phone")

    if email.strip():
        for row in db.execute(
            "SELECT id FROM customers WHERE LOWER(COALESCE(email, '')) = ?", (email.strip().lower(),)
        ).fetchall():
            matches.setdefault(row["id"], "email")

    if name.strip():
        for row in db.execute(
            "SELECT id FROM customers WHERE LOWER(TRIM(name)) = ?", (name.strip().lower(),)
        ).fetchall():
            matches.setdefault(row["id"], "name")

    if plate.strip():
        for row in db.execute(
            "SELECT DISTINCT customer_id FROM vehicles WHERE plate_normalized LIKE ?",
            (f"%{normalize_plate(plate)}%",),
        ).fetchall():
            matches.setdefault(row["customer_id"], "plate")

    if vin.strip():
        for row in db.execute(
            "SELECT DISTINCT customer_id FROM vehicles WHERE vin LIKE ?", (f"%{vin.strip().upper()}%",)
        ).fetchall():
            matches.setdefault(row["customer_id"], "vin")

    if not matches:
        return []

    placeholders = ", ".join("?" for _ in matches)
    found = {
        row["id"]: row
        for row in db.execute(f"{_LIST_SELECT} AND c.id IN ({placeholders})", tuple(matches)).fetchall()
    }
    return [{**found[customer_id], "match": reason} for customer_id, reason in matches.items() if customer_id in found]


def customer_detail_payload(db, customer_id: int) -> dict:
    """Dựng payload chi tiết: xe, lịch sử sửa chữa, ghi chú, lần sửa gần nhất."""
    customer = db.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
    if not customer:
        raise NotFoundError("Không tìm thấy khách hàng")

    vehicles = [
        dict(row)
        for row in db.execute(
            f"""
            SELECT v.*,
                (SELECT MAX(rh.repaired_at) FROM repair_history rh WHERE rh.vehicle_id = v.id) AS last_visit,
                COALESCE(
                    (SELECT rh.mileage FROM repair_history rh WHERE rh.vehicle_id = v.id AND rh.mileage IS NOT NULL
                        ORDER BY rh.repaired_at DESC, rh.id DESC LIMIT 1),
                    v.mileage
                ) AS last_mileage,
                (SELECT rh.services FROM repair_history rh WHERE rh.vehicle_id = v.id
                    ORDER BY rh.repaired_at DESC, rh.id DESC LIMIT 1) AS last_service,
                (SELECT rh.note FROM repair_history rh WHERE rh.vehicle_id = v.id
                    AND TRIM(COALESCE(rh.note, '')) <> ''
                    ORDER BY rh.repaired_at DESC, rh.id DESC LIMIT 1) AS last_note,
                (SELECT COUNT(*) FROM repair_history rh WHERE rh.vehicle_id = v.id) AS history_count
            FROM vehicles v WHERE v.customer_id = ? ORDER BY v.plate COLLATE NOCASE
            """,
            (customer_id,),
        ).fetchall()
    ]

    history: list[dict] = []
    for vehicle in vehicles:
        # Bổ sung lịch sử cho phiếu đã hoàn thành nhưng chưa đồng bộ.
        backfill_repair_history(db, vehicle_id=vehicle["id"])
        history.extend(
            dict(row)
            for row in db.execute(
                """
                SELECT rh.*, ro.code AS order_code, ro.status AS order_status,
                       ro.technician AS order_technician
                FROM repair_history rh
                LEFT JOIN repair_orders ro ON ro.id = rh.repair_order_id
                WHERE rh.vehicle_id = ? OR (rh.vehicle_id IS NULL AND rh.plate = ?)
                ORDER BY rh.repaired_at DESC, rh.id DESC
                """,
                (vehicle["id"], vehicle["plate"]),
            ).fetchall()
        )
    history.sort(key=lambda item: (item.get("repaired_at") or "", item.get("id") or 0), reverse=True)

    notes = [
        dict(row)
        for row in db.execute(
            """
            SELECT rn.id, rn.content, rn.author_name, rn.created_at, ro.code AS order_code, ro.plate
            FROM repair_notes rn
            JOIN repair_orders ro ON ro.id = rn.repair_order_id
            WHERE ro.customer_id = ? ORDER BY rn.id DESC LIMIT 10
            """,
            (customer_id,),
        ).fetchall()
    ]

    appointments = [
        dict(row)
        for row in db.execute(
            "SELECT * FROM appointments WHERE customer_id=? ORDER BY appointment_at DESC LIMIT 5",
            (customer_id,),
        ).fetchall()
    ]
    for item in appointments:
        item["appointment_at"] = vn_text(item["appointment_at"])

    payload = dict(customer)
    last_mileage = next((item["mileage"] for item in history if item["mileage"] is not None), None)
    if last_mileage is None:
        mileage_values = [item["mileage"] for item in vehicles if item["mileage"] is not None]
        last_mileage = max(mileage_values) if mileage_values else None
    last_note = next((item["note"] for item in history if (item["note"] or "").strip()), None)
    return {
        **payload,
        "vehicles": vehicles,
        "history": history,
        "notes": notes,
        "appointments": appointments,
        "last_visit": history[0]["repaired_at"] if history else None,
        "last_mileage": last_mileage,
        "last_service": history[0]["services"] if history else None,
        "last_note": last_note,
        "vehicle_count": len(vehicles),
        "lifetime_value": sum(int(item["total"] or 0) for item in history),
    }


@router.get("", response_model=Page[CustomerOut], response_model_exclude_none=True)
def list_customers(
    q: str = Query(default="", max_length=120, description="Tìm theo tên, SĐT, email, biển số hoặc VIN"),
    vehicle_filter: Literal["all", "with", "without"] = Query(default="all"),
    page: PageParams = Depends(page_params),
    user: dict = Depends(require_permission("customers")),
) -> dict:
    base = _LIST_SELECT
    params: list = []
    if q:
        base += (
            " AND (c.name LIKE ? OR c.phone LIKE ? OR c.email LIKE ? OR c.address LIKE ?"
            " OR EXISTS (SELECT 1 FROM vehicles v WHERE v.customer_id = c.id"
            " AND (v.plate LIKE ? OR v.plate_normalized LIKE ? OR v.vin LIKE ?)))"
        )
        params.extend([f"%{q}%"] * 7)
    if vehicle_filter != "all":
        base += (
            " AND " if vehicle_filter == "with" else " AND NOT "
        ) + "EXISTS (SELECT 1 FROM vehicles v WHERE v.customer_id = c.id)"
    with connect() as db:
        items, total = fetch_page(db, base, tuple(params), "ORDER BY c.name COLLATE NOCASE", page)
    return envelope(items, total, page)


@router.get("/summary")
def customer_summary(user: dict = Depends(require_permission("customers"))) -> dict:
    """Tổng hợp từ cùng các biểu thức nghiệp vụ dùng cho danh sách khách hàng."""
    with connect() as db:
        row = db.execute(
            f"""SELECT COUNT(*) AS customers,
                       COALESCE(SUM(vehicle_count), 0) AS vehicles,
                       COALESCE(SUM(appointment_count), 0) AS appointments,
                       COALESCE(SUM(lifetime_value), 0) AS lifetime_value,
                       COALESCE(SUM(CASE WHEN vehicle_count > 0 THEN 1 ELSE 0 END), 0) AS with_vehicles
                FROM ({_LIST_SELECT})"""
        ).fetchone()
    return dict(row)


@router.get("/duplicates", response_model=Page[CustomerOut], response_model_exclude_none=True)
def check_duplicates(
    phone: str = Query(default="", max_length=30),
    email: str = Query(default="", max_length=120),
    name: str = Query(default="", max_length=120),
    plate: str = Query(default="", max_length=20),
    vin: str = Query(default="", max_length=20),
    page: PageParams = Depends(page_params),
    user: dict = Depends(require_permission("customers")),
) -> dict:
    """Kiểm tra trùng lặp trước khi tạo khách hàng (trả về bản ghi hiện có)."""
    with connect() as db:
        matches = find_customer_duplicates(db, phone=phone, email=email, name=name, plate=plate, vin=vin)
    total = len(matches)
    start = page.offset
    return envelope(matches[start : start + page.page_size], total, page)


@router.get("/{customer_id}", response_model=CustomerDetailOut, response_model_exclude_none=True)
def customer_detail(
    customer_id: int,
    user: dict = Depends(require_permission("customers")),
) -> dict:
    with connect() as db, transaction(db):
        # Chống IDOR: khách hàng chỉ xem được hồ sơ của chính mình.
        ensure_record_access(db, user, customer_id)
        return customer_detail_payload(db, customer_id)


@router.post("", status_code=201, response_model=CustomerOut, response_model_exclude_none=True)
def create_customer(
    item: CustomerIn,
    request: Request,
    allow_duplicate: bool = Query(
        default=False,
        description="Bỏ qua cảnh báo trùng (SĐT/email) và vẫn tạo hồ sơ mới",
    ),
    user: dict = Depends(require_permission("customers")),
) -> dict:
    with connect() as db, transaction(db):
        duplicates = find_customer_duplicates(
            db, phone=item.phone, email=item.email, name=item.name
        )
        strong = [entry for entry in duplicates if entry["match"] in ("phone", "email")]
        if strong and not allow_duplicate:
            # Trả kèm dữ liệu để client chọn dùng lại hồ sơ cũ hoặc tạo mới.
            raise ConflictError(
                "Khách hàng có thể đã tồn tại trong hệ thống",
                details={
                    "reason": "duplicate_customer",
                    "customers": duplicates,
                    "suggest": "reuse_customer",
                },
            )
        cursor = db.execute(
            "INSERT INTO customers(name, phone, email, address, note) VALUES(?, ?, ?, ?, ?)",
            (item.name.strip(), item.phone.strip(), item.email.strip(), item.address.strip(), item.note.strip()),
        )
        customer_id = cursor.lastrowid
        write_audit(
            db, user, "customer.create", "customers", customer_id,
            {"phone": item.phone, "used_existing": False}, client_ip(request),
        )
        return dict(db.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone())


@router.patch("/{customer_id}", response_model=CustomerOut, response_model_exclude_none=True)
def update_customer(
    customer_id: int,
    item: CustomerUpdate,
    request: Request,
    user: dict = Depends(require_permission("customers")),
) -> dict:
    fields = item.model_dump(exclude_none=True)
    if not fields:
        raise BadRequestError("Không có dữ liệu cập nhật")
    with connect() as db, transaction(db):
        cursor = db.execute(
            f"UPDATE customers SET {', '.join(f'{key}=?' for key in fields)} WHERE id=?",
            (*fields.values(), customer_id),
        )
        if cursor.rowcount == 0:
            raise NotFoundError("Không tìm thấy khách hàng")
        write_audit(db, user, "customer.update", "customers", customer_id, fields, client_ip(request))
        return dict(db.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone())


@router.post("/{customer_id}/vehicles", status_code=201, response_model=VehicleOut, response_model_exclude_none=True)
def add_customer_vehicle(
    customer_id: int,
    item: VehicleIn,
    request: Request,
    reuse_existing: bool = Query(
        default=False,
        description="Nếu biển số/VIN đã có và thuộc đúng khách hàng, dùng lại bản ghi hiện có",
    ),
    user: dict = Depends(require_permission("vehicles")),
) -> dict:
    with connect() as db, transaction(db):
        return insert_vehicle(db, customer_id, item, user, request, reuse_existing=reuse_existing)


@router.post("/{customer_id}/vehicles/link", response_model=VehicleOut, response_model_exclude_none=True)
def link_customer_vehicle(
    customer_id: int,
    item: LinkVehicleIn,
    request: Request,
    user: dict = Depends(require_permission("vehicles")),
) -> dict:
    """Gắn xe đã có vào hồ sơ khách hàng (``move = true`` khi xe thuộc khách khác)."""
    with connect() as db, transaction(db):
        return link_vehicle(db, item.vehicle_id, customer_id, user, request, move=item.move, note=item.note)


@lookup_router.get("/lookup", response_model=LookupOut, response_model_exclude_none=True)
def lookup(
    q: str = Query(default="", max_length=120),
    phone: str = Query(default="", max_length=30),
    email: str = Query(default="", max_length=120),
    name: str = Query(default="", max_length=120),
    plate: str = Query(default="", max_length=20),
    vin: str = Query(default="", max_length=20),
    user: dict = Depends(require_any_permission("customers", "vehicles")),
) -> dict:
    """Tra cứu nhanh khách hàng và xe đã có (hỗ trợ liên kết đúng bản ghi hiện có)."""
    keyword = q.strip()
    with connect() as db:
        customers = find_customer_duplicates(
            db,
            phone=phone or keyword,
            email=email,
            name=name or (keyword if not phone else ""),
            plate=plate or keyword,
            vin=vin or keyword,
        )

        vehicle_matches: dict[int, str] = {}
        if plate:
            for row in db.execute(
                "SELECT id FROM vehicles WHERE plate_normalized LIKE ?",
                (f"%{normalize_plate(plate)}%",),
            ).fetchall():
                vehicle_matches.setdefault(row["id"], "plate")
        if vin:
            for row in db.execute(
                "SELECT id FROM vehicles WHERE COALESCE(vin, '') <> '' AND vin LIKE ?",
                (f"%{vin.upper()}%",),
            ).fetchall():
                vehicle_matches.setdefault(row["id"], "vin")
        if keyword:
            for row in db.execute(
                "SELECT id FROM vehicles WHERE plate LIKE ? OR plate_normalized LIKE ?"
                " OR COALESCE(vin, '') LIKE ? OR make LIKE ? OR model LIKE ?",
                (f"%{keyword}%",) * 5,
            ).fetchall():
                vehicle_matches.setdefault(row["id"], "keyword")

        vehicles: list[dict] = []
        if vehicle_matches:
            placeholders = ", ".join("?" for _ in vehicle_matches)
            fetched = {
                row["id"]: dict(row)
                for row in db.execute(
                    f"""
                    SELECT v.*, c.name AS customer_name, c.phone AS customer_phone,
                        (SELECT MAX(rh.repaired_at) FROM repair_history rh WHERE rh.vehicle_id = v.id) AS last_visit,
                        (SELECT COUNT(*) FROM repair_history rh WHERE rh.vehicle_id = v.id) AS history_count
                    FROM vehicles v JOIN customers c ON c.id = v.customer_id
                    WHERE v.id IN ({placeholders})
                    """,
                    tuple(vehicle_matches),
                ).fetchall()
            }
            vehicles = [
                {**fetched[vehicle_id], "match": reason}
                for vehicle_id, reason in vehicle_matches.items()
                if vehicle_id in fetched
            ]
    return {"query": keyword, "customers": customers, "vehicles": vehicles}
