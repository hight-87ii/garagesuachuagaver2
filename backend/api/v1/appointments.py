"""Module lịch hẹn: đặt lịch, sửa, xác nhận, hủy và chuyển thành phiếu tiếp nhận.

Quy tắc nghiệp vụ chính:

* Lịch mới luôn bắt đầu ở trạng thái ``Đang chờ``. Không cho tạo lịch ở trạng thái
  ``Đã hủy`` hoặc ``Đã tiếp nhận``; việc xác nhận phải qua kiểm tra quy tắc.
* Xác nhận lịch kiểm tra giờ/ngày làm việc và trùng lịch kỹ thuật viên - nguồn lực.
  Có thể bỏ qua cảnh báo bằng ``?force=true`` (được ghi nhật ký).
* ``Đã tiếp nhận`` chỉ đạt được qua endpoint ``/receive``: luôn tạo (hoặc dùng lại)
  đúng một phiếu sửa chữa, nhờ vậy không sinh bản ghi trùng.
"""

from fastapi import APIRouter, Depends, Query, Request

from ...core.access import customer_scope_id, ensure_record_access
from ...core.audit import write_audit
from ...core.db import connect, normalize_plate, transaction
from ...core.deps import client_ip, require_permission
from ...core.errors import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from ...core.pagination import PageParams, envelope, fetch_page, page_params, search_clause
from ...permissions import has_permission
from ...domain import (
    customer_name_for,
    locate_vehicle,
    next_order_code,
    sync_vehicle_mileage,
    technician_id_for,
)
from ...schemas.appointments import (
    AppointmentCancelIn,
    AppointmentCheckOut,
    AppointmentIn,
    AppointmentOut,
    AppointmentReceiveIn,
    AppointmentReceiveOut,
    AppointmentRulesOut,
    AppointmentStatusIn,
    AppointmentUpdate,
)
from ...schemas.common import Page
from ...schedule import (
    ACTIVE_STATUSES,
    OPEN_ORDER_STATUSES,
    blocking_items,
    conflict_summary,
    find_conflicts,
    resources_configured,
    time_window,
    working_hours_issues,
    working_rules,
)
from ...timeutil import now_utc_iso, to_utc_iso, vn_text
from ...workflow import ensure_status_history

router = APIRouter(prefix="/appointments", tags=["Appointments"])

#: Chuyển trạng thái hợp lệ. "Đã tiếp nhận" chỉ đạt được qua /receive.
ALLOWED_TRANSITIONS = {
    "Đang chờ": {"Đã xác nhận", "Đã hủy"},
    "Đã xác nhận": {"Đang chờ", "Đã hủy"},
    "Đã hủy": {"Đang chờ", "Đã xác nhận"},
    "Đã tiếp nhận": set(),
}
APPOINTMENT_OPERATOR_ROLES = ("Admin", "Quản lý", "Lễ tân")


def _ensure_appointment_operator(user: dict, action: str) -> None:
    if user.get("role") not in APPOINTMENT_OPERATOR_ROLES:
        raise ForbiddenError(
            f"Chỉ Admin, Quản lý hoặc Lễ tân được {action}. Khách hàng chỉ có thể gửi yêu cầu và hủy lịch của mình."
        )

DETAIL_SQL = """
    SELECT a.*, COALESCE(a.customer_id, v.customer_id) AS linked_customer_id,
           c.phone, c.email, v.make, v.model, v.year, v.vin,
           r.name AS resource_name, r.kind AS resource_kind,
           ro.code AS repair_order_code, ro.status AS repair_order_status
    FROM appointments a
    LEFT JOIN vehicles v ON v.id = a.vehicle_id
    LEFT JOIN customers c ON c.id = COALESCE(a.customer_id, v.customer_id)
    LEFT JOIN resources r ON r.id = a.resource_id
    LEFT JOIN repair_orders ro ON ro.id = a.repair_order_id
    WHERE a.id = ?
"""


def _serialize(row: dict) -> dict:
    item = dict(row)
    for key in ("appointment_at", "confirmed_at", "cancelled_at"):
        if item.get(key):
            item[key] = vn_text(item[key])
    return item


def _row_or_404(db, appointment_id: int, user: dict | None = None) -> dict:
    row = db.execute(DETAIL_SQL, (appointment_id,)).fetchone()
    if not row:
        raise NotFoundError("Không tìm thấy lịch hẹn")
    item = dict(row)
    # Chống IDOR: khách hàng chỉ truy cập lịch hẹn thuộc về mình.
    if user is not None:
        ensure_record_access(db, user, item.get("linked_customer_id"))
    return item


def _payload(db, appointment_id: int, user: dict | None = None) -> dict:
    """Chi tiết lịch hẹn kèm cảnh báo trùng lịch còn hiệu lực."""
    row = _row_or_404(db, appointment_id, user)
    payload = _serialize(row)
    payload["requested_parts"] = [dict(part) for part in db.execute(
        """SELECT apr.id,apr.part_id,apr.name,apr.quantity,
                  CASE WHEN p.id IS NULL THEN NULL WHEN p.active=0 THEN 'Cần xác nhận'
                       WHEN p.stock>=apr.quantity THEN 'Đang có hàng' ELSE 'Cần xác nhận' END availability
           FROM appointment_part_requests apr LEFT JOIN parts p ON p.id=apr.part_id
           WHERE apr.appointment_id=? ORDER BY apr.id""", (appointment_id,),
    ).fetchall()]
    if row["status"] in ("Đang chờ", "Đã xác nhận"):
        start = row["appointment_at"]
        duration = int(row["duration_min"] or 0)
        issues = working_hours_issues(start, duration)
        conflicts = find_conflicts(
            db,
            start=start,
            end=time_window(start, duration),
            technician=row["technician"] or "",
            technician_id=row["technician_id"],
            resource_id=row["resource_id"],
            exclude_id=appointment_id,
        )
        payload["warnings"] = [*issues, *conflicts]
        payload["conflicts"] = conflicts
    else:
        payload["warnings"] = []
        payload["conflicts"] = []
    return payload


def _save_part_requests(db, appointment_id: int, requested_parts: list) -> None:
    """Lưu nhu cầu khách, tuyệt đối không trừ kho hoặc thêm vào phiếu sửa chữa."""
    resolved = []
    seen = set()
    for request in requested_parts:
        part = None
        if request.part_id:
            part = db.execute("SELECT id,name FROM parts WHERE id=? AND active=1", (request.part_id,)).fetchone()
            if not part:
                raise BadRequestError("Phụ tùng đã chọn không còn trong danh mục")
        name = part["name"] if part else request.name.strip()
        key = ("id", part["id"]) if part else ("name", name.casefold())
        if key in seen:
            raise BadRequestError("Không chọn trùng phụ tùng trong một lịch hẹn")
        seen.add(key)
        resolved.append((appointment_id, part["id"] if part else None, name, request.quantity))
    db.execute("DELETE FROM appointment_part_requests WHERE appointment_id=?", (appointment_id,))
    db.executemany(
        "INSERT INTO appointment_part_requests(appointment_id,part_id,name,quantity) VALUES(?,?,?,?)",
        resolved,
    )


def _validated_service(db, service_id: int | None, name: str) -> str:
    if not service_id:
        return name
    row = db.execute("SELECT name FROM services WHERE id=? AND active=1", (service_id,)).fetchone()
    if not row:
        raise BadRequestError("Dịch vụ đã chọn không còn trong danh mục")
    return row["name"]


def _validate_resource(db, resource_id: int | None) -> None:
    if not resource_id:
        return
    row = db.execute("SELECT id, active FROM resources WHERE id=?", (resource_id,)).fetchone()
    if not row:
        raise BadRequestError("Nguồn lực không tồn tại")
    if not row["active"]:
        raise BadRequestError("Nguồn lực đã ngừng sử dụng")


def _resolve_subject(
    db,
    *,
    customer_id: int | None,
    vehicle_id: int | None,
    plate: str,
    customer_name: str,
) -> dict:
    """Xác định khách hàng, xe và biển số (chuẩn hóa) của lịch hẹn."""
    vehicle = None
    if vehicle_id:
        row = db.execute(
            "SELECT id, customer_id, plate FROM vehicles WHERE id=?", (vehicle_id,)
        ).fetchone()
        if not row:
            raise BadRequestError("Xe không tồn tại")
        vehicle = dict(row)
    if not vehicle and plate:
        found = locate_vehicle(db, plate)
        if found:
            vehicle = {"id": found["id"], "customer_id": found["customer_id"], "plate": found["plate"]}

    if vehicle and customer_id and vehicle["customer_id"]:
        if int(vehicle["customer_id"]) != int(customer_id):
            raise BadRequestError(
                "Xe đang thuộc hồ sơ khách hàng khác. Hãy chọn đúng khách hàng hoặc liên kết xe trước.",
                details={
                    "customer_id": customer_id,
                    "vehicle_customer_id": vehicle["customer_id"],
                },
            )
    customer_id = customer_id or (vehicle["customer_id"] if vehicle else None)
    if customer_id:
        row = db.execute("SELECT id, name FROM customers WHERE id=?", (customer_id,)).fetchone()
        if not row:
            raise BadRequestError("Khách hàng không tồn tại")
        customer_name = row["name"]
    elif vehicle and not customer_name:
        customer_name = customer_name_for(db, vehicle["customer_id"])

    resolved_plate = (vehicle["plate"] if vehicle else plate or "").strip().upper()
    if len(resolved_plate) < 5:
        raise BadRequestError("Biển số xe không hợp lệ (tối thiểu 5 ký tự)")
    if not (customer_name or "").strip():
        raise BadRequestError("Cần chọn khách hàng hoặc nhập tên khách hàng")
    return {
        "customer_id": customer_id,
        "vehicle_id": vehicle["id"] if vehicle else None,
        "plate": resolved_plate,
        "customer_name": customer_name.strip(),
    }


def _conflict_error(action: str, blocking: list[dict], warnings: list[dict]) -> ConflictError:
    return ConflictError(
        f"Chưa thể {action} lịch hẹn: {conflict_summary(blocking)}",
        code="appointment_conflict",
        details={
            "blocking": blocking,
            "warnings": warnings,
            "suggest": (
                "Chọn khung giờ, kỹ thuật viên hoặc nguồn lực khác; nếu vẫn muốn tiếp tục "
                "hãy gửi lại với force=true."
            ),
        },
    )


def _confirm_locked(db, current: dict, user: dict, request: Request, force: bool) -> None:
    """Xác nhận lịch hẹn trong transaction hiện tại (đã kiểm tra quy tắc)."""
    start = current["appointment_at"]
    duration = int(current["duration_min"] or 0)
    issues = working_hours_issues(start, duration)
    conflicts = find_conflicts(
        db,
        start=start,
        end=time_window(start, duration),
        technician=current["technician"] or "",
        technician_id=current["technician_id"],
        resource_id=current["resource_id"],
        exclude_id=current["id"],
    )
    blocking = blocking_items(issues, conflicts)
    if blocking and not force:
        warnings = [item for item in [*issues, *conflicts] if item.get("level") != "blocking"]
        raise _conflict_error("xác nhận", blocking, warnings)
    db.execute(
        "UPDATE appointments SET status='Đã xác nhận', confirmed_at=?, cancelled_at=NULL, "
        "cancel_reason='' WHERE id=?",
        (now_utc_iso(), current["id"]),
    )
    write_audit(
        db, user, "appointment.confirm", "appointments", current["id"],
        {"forced": bool(blocking), "status": "Đã xác nhận"}, client_ip(request),
    )


# --------------------------------------------------------------------------------------
# Đọc dữ liệu
# --------------------------------------------------------------------------------------
@router.get("", response_model=Page[AppointmentOut], response_model_exclude_none=True)
def list_appointments(
    status: str = Query(default="", max_length=40),
    q: str = Query(default="", max_length=120),
    date: str = Query(default="", max_length=10, description="Lọc theo ngày (giờ Việt Nam), YYYY-MM-DD"),
    technician: str = Query(default="", max_length=80),
    resource_id: int | None = Query(default=None),
    page: PageParams = Depends(page_params),
    user: dict = Depends(require_permission("appointments")),
) -> dict:
    base = """
        SELECT a.*, COALESCE(a.customer_id, v.customer_id) AS linked_customer_id,
               c.phone, c.email, v.make, v.model, v.year, v.vin,
               r.name AS resource_name, ro.code AS repair_order_code,
               ro.status AS repair_order_status
        FROM appointments a
        LEFT JOIN vehicles v ON v.id = a.vehicle_id
        LEFT JOIN customers c ON c.id = COALESCE(a.customer_id, v.customer_id)
        LEFT JOIN resources r ON r.id = a.resource_id
        LEFT JOIN repair_orders ro ON ro.id = a.repair_order_id
        WHERE 1 = 1
    """
    params: list = []
    if status and status != "Tất cả":
        base += " AND a.status = ?"
        params.append(status)
    if date:
        base += " AND date(a.appointment_at, '+7 hours') = ?"
        params.append(date)
    if technician:
        base += " AND LOWER(a.technician) = LOWER(?)"
        params.append(technician)
    if resource_id:
        base += " AND a.resource_id = ?"
        params.append(resource_id)
    clause, clause_params = search_clause(
        q, ["a.customer_name", "a.plate", "a.service", "a.reason", "a.technician", "r.name"]
    )
    base += clause
    params.extend(clause_params)
    with connect() as db:
        # Chống IDOR: khách hàng chỉ thấy lịch hẹn thuộc về mình.
        scope = customer_scope_id(db, user)
        if scope is not None:
            base += " AND COALESCE(a.customer_id, v.customer_id) = ?"
            params.append(scope)
        items, total = fetch_page(db, base, tuple(params), "ORDER BY a.appointment_at", page)
    for item in items:
        item["appointment_at"] = vn_text(item["appointment_at"])
    return envelope(items, total, page)


@router.get("/rules", response_model=AppointmentRulesOut, response_model_exclude_none=True)
def appointment_rules(
    user: dict = Depends(require_permission("appointments")),
) -> dict:
    """Lịch làm việc, nguồn lực và kỹ thuật viên để giao diện dựng form đặt lịch."""
    with connect() as db:
        resources = [
            dict(row)
            for row in db.execute(
                "SELECT id, code, name, kind, capacity, active, note FROM resources "
                "WHERE active = 1 ORDER BY kind, name"
            ).fetchall()
        ]
        technicians = [
            row[0]
            for row in db.execute(
                """
                SELECT full_name FROM users WHERE role='Kỹ thuật viên' AND status='active'
                UNION
                SELECT technician FROM repair_orders WHERE TRIM(technician) <> ''
                UNION
                SELECT technician FROM appointments WHERE TRIM(technician) <> ''
                ORDER BY 1
                """
            ).fetchall()
        ]
        enabled = resources_configured(db)
        services = [dict(row) for row in db.execute(
            "SELECT id,name,category,price,duration_min FROM services WHERE active=1 ORDER BY category,name"
        ).fetchall()]
    return {
        **working_rules(),
        "resources_enabled": enabled,
        "resources": resources,
        "technicians": technicians,
        "services": services,
        "statuses": [*ACTIVE_STATUSES, "Đã hủy"],
    }


@router.get("/part-options")
def appointment_part_options(user: dict = Depends(require_permission("appointments"))) -> list[dict]:
    """Danh mục công khai: chỉ giá bán và tình trạng, không trả số lượng tồn."""
    with connect() as db:
        return [dict(row) for row in db.execute(
            """SELECT id,code,name,category,compatible,unit,sell_price,
                      CASE WHEN stock>0 THEN 'Đang có hàng' ELSE 'Tạm hết hàng' END availability
               FROM parts WHERE active=1 ORDER BY name"""
        ).fetchall()]


@router.get("/conflicts", response_model=AppointmentCheckOut, response_model_exclude_none=True)
def check_appointment_conflicts(
    at: str = Query(min_length=10, max_length=40, description="Thời gian hẹn (giờ Việt Nam)"),
    duration_min: int = Query(default=60, gt=0, le=1440),
    technician: str = Query(default="", max_length=80),
    resource_id: int | None = Query(default=None),
    exclude_id: int | None = Query(default=None, description="Bỏ qua chính lịch đang sửa"),
    user: dict = Depends(require_permission("appointments")),
) -> dict:
    """Kiểm tra trước khi lưu: giờ làm việc + trùng kỹ thuật viên/nguồn lực."""
    start = to_utc_iso(at)
    with connect() as db:
        _validate_resource(db, resource_id)
        technician_id = technician_id_for(db, technician)
        issues = working_hours_issues(start, duration_min)
        conflicts = find_conflicts(
            db,
            start=start,
            end=time_window(start, duration_min),
            technician=technician,
            technician_id=technician_id,
            resource_id=resource_id,
            exclude_id=exclude_id,
        )
    blocking = blocking_items(issues, conflicts)
    warnings = [item for item in [*issues, *conflicts] if item.get("level") != "blocking"]
    return {
        "ok": not blocking,
        "blocking": blocking,
        "warnings": warnings,
        "message": conflict_summary(blocking) if blocking else "Khung giờ và phân công hợp lệ.",
    }


@router.get("/{appointment_id}", response_model=AppointmentOut, response_model_exclude_none=True)
def appointment_detail(
    appointment_id: int,
    user: dict = Depends(require_permission("appointments")),
) -> dict:
    with connect() as db:
        return _payload(db, appointment_id, user)


# --------------------------------------------------------------------------------------
# Ghi dữ liệu
# --------------------------------------------------------------------------------------
@router.post("", status_code=201, response_model=AppointmentOut, response_model_exclude_none=True)
def create_appointment(
    item: AppointmentIn,
    request: Request,
    force: bool = Query(default=False, description="Xác nhận dù còn cảnh báo trùng lịch"),
    user: dict = Depends(require_permission("appointments")),
) -> dict:
    if user.get("role") == "Khách hàng" and item.status != "Đang chờ":
        raise BadRequestError(
            "Lịch mới luôn bắt đầu ở trạng thái Đang chờ và phải được nhân viên có thẩm quyền xác nhận.",
            details={"status": item.status},
        )
    if user.get("role") != "Khách hàng" and item.status in ("Đã hủy", "Đã tiếp nhận"):
        raise BadRequestError(
            "Không thể tạo lịch mới ở trạng thái này; lịch mới phải bắt đầu từ Đang chờ hoặc được nhân viên xác nhận hợp lệ.",
            details={"status": item.status},
        )
    if user.get("role") == "Khách hàng" and (item.technician or item.resource_id):
        raise ForbiddenError("Khách hàng không được tự phân công kỹ thuật viên hoặc nguồn lực")
    start = to_utc_iso(item.appointment_at)
    with connect() as db, transaction(db):
        subject = _resolve_subject(
            db,
            customer_id=item.customer_id,
            vehicle_id=item.vehicle_id,
            plate=item.plate,
            customer_name=item.customer_name,
        )
        ensure_record_access(db, user, subject["customer_id"])
        # resource_id = 0 là quy ước "không xếp nguồn lực" của client; không ghi 0
        # vào khóa ngoại để tránh vi phạm ràng buộc.
        resource_id = item.resource_id or None
        _validate_resource(db, resource_id)
        technician_id = technician_id_for(db, item.technician)
        issues = working_hours_issues(start, item.duration_min)
        conflicts = find_conflicts(
            db,
            start=start,
            end=time_window(start, item.duration_min),
            technician=item.technician,
            technician_id=technician_id,
            resource_id=resource_id,
        )
        if item.status == "Đã xác nhận":
            blocking = blocking_items(issues, conflicts)
            if blocking and not force:
                warnings = [i for i in [*issues, *conflicts] if i.get("level") != "blocking"]
                raise _conflict_error("xác nhận", blocking, warnings)
        cursor = db.execute(
            """
            INSERT INTO appointments(customer_id, vehicle_id, customer_name, plate, service,
                reason, note, appointment_at, duration_min, status, technician, technician_id,
                resource_id, confirmed_at, created_by)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                subject["customer_id"],
                subject["vehicle_id"],
                subject["customer_name"],
                subject["plate"],
                _validated_service(db, item.service_id, item.service),
                item.reason,
                item.note,
                start,
                item.duration_min,
                item.status,
                item.technician,
                technician_id,
                resource_id,
                now_utc_iso() if item.status == "Đã xác nhận" else None,
                user["id"],
            ),
        )
        appointment_id = cursor.lastrowid
        _save_part_requests(db, appointment_id, item.requested_parts)
        write_audit(
            db, user, "appointment.create", "appointments", appointment_id,
            {
                "plate": subject["plate"],
                "status": item.status,
                "technician": item.technician,
                "resource_id": resource_id,
            },
            client_ip(request),
        )
    with connect() as db:
        return _payload(db, appointment_id)


@router.patch("/{appointment_id}", response_model=AppointmentOut, response_model_exclude_none=True)
def update_appointment(
    appointment_id: int,
    item: AppointmentUpdate,
    request: Request,
    force: bool = Query(default=False, description="Lưu dù còn cảnh báo trùng lịch"),
    user: dict = Depends(require_permission("appointments")),
) -> dict:
    fields = item.model_dump(exclude_none=True)
    if not fields:
        raise BadRequestError("Không có dữ liệu cập nhật")
    if "appointment_at" in fields and not has_permission(user.get("role", ""), "appointment.reschedule"):
        raise ForbiddenError("Bạn không có quyền đổi thời gian lịch hẹn")
    if "resource_id" in fields and fields["resource_id"] == 0:
        fields["resource_id"] = None
    if user.get("role") == "Khách hàng":
        privileged = {"customer_id", "vehicle_id", "plate", "technician", "resource_id"} & set(fields)
        if privileged:
            raise ForbiddenError("Khách hàng không được thay đổi phân công hoặc chủ thể của lịch hẹn")
    with connect() as db, transaction(db):
        current = _row_or_404(db, appointment_id, user)
        if current["status"] in ("Đã tiếp nhận", "Đã hủy"):
            raise BadRequestError(
                "Không thể sửa lịch hẹn đã tiếp nhận hoặc đã hủy. Hãy khôi phục lịch về "
                "Đang chờ trước khi chỉnh sửa.",
                details={"status": current["status"]},
            )
        start = (
            to_utc_iso(fields["appointment_at"])
            if "appointment_at" in fields
            else current["appointment_at"]
        )
        duration = int(fields.get("duration_min", current["duration_min"]))
        if "vehicle_id" in fields:
            vehicle_hint = fields["vehicle_id"]
        elif "plate" in fields:
            vehicle_hint = None  # biển số mới -> tra lại xe tương ứng
        else:
            vehicle_hint = current["vehicle_id"]
        subject = _resolve_subject(
            db,
            customer_id=fields.get("customer_id", current["customer_id"]),
            vehicle_id=vehicle_hint,
            plate=fields.get("plate", current["plate"]),
            customer_name=current["customer_name"] or "",
        )
        ensure_record_access(db, user, subject["customer_id"])
        technician = fields.get("technician", current["technician"] or "")
        technician_id = technician_id_for(db, technician)
        resource_id = fields.get("resource_id", current["resource_id"])
        _validate_resource(db, resource_id)
        issues = working_hours_issues(start, duration)
        conflicts = find_conflicts(
            db,
            start=start,
            end=time_window(start, duration),
            technician=technician,
            technician_id=technician_id,
            resource_id=resource_id,
            exclude_id=appointment_id,
        )
        if current["status"] == "Đã xác nhận" or "appointment_at" in fields:
            blocking = blocking_items(issues, conflicts)
            if blocking and not force:
                warnings = [i for i in [*issues, *conflicts] if i.get("level") != "blocking"]
                raise _conflict_error("lưu", blocking, warnings)
        db.execute(
            """
            UPDATE appointments SET customer_id=?, vehicle_id=?, customer_name=?, plate=?,
                service=?, reason=?, note=?, appointment_at=?, duration_min=?, technician=?,
                technician_id=?, resource_id=?
            WHERE id=?
            """,
            (
                subject["customer_id"],
                subject["vehicle_id"],
                subject["customer_name"],
                subject["plate"],
                _validated_service(db, fields.get("service_id"), fields.get("service", current["service"])),
                fields.get("reason", current["reason"]),
                fields.get("note", current["note"]),
                start,
                duration,
                technician,
                technician_id,
                resource_id,
                appointment_id,
            ),
        )
        if item.requested_parts is not None:
            _save_part_requests(db, appointment_id, item.requested_parts)
        write_audit(
            db, user, "appointment.update", "appointments", appointment_id,
            {"fields": sorted(fields), "technician": technician}, client_ip(request),
        )
    with connect() as db:
        return _payload(db, appointment_id)


@router.post("/{appointment_id}/confirm", response_model=AppointmentOut, response_model_exclude_none=True)
def confirm_appointment(
    appointment_id: int,
    request: Request,
    force: bool = Query(default=False, description="Xác nhận dù còn cảnh báo trùng lịch"),
    user: dict = Depends(require_permission("appointments")),
) -> dict:
    _ensure_appointment_operator(user, "xác nhận lịch hẹn")
    with connect() as db:
        with transaction(db):
            current = _row_or_404(db, appointment_id, user)
            if current["status"] == "Đã tiếp nhận":
                raise BadRequestError(
                    "Lịch hẹn đã được tiếp nhận, không cần xác nhận lại.",
                    details={"repair_order_id": current["repair_order_id"]},
                )
            if current["status"] == "Đã hủy":
                raise BadRequestError("Lịch hẹn đã hủy. Hãy khôi phục lịch về Đang chờ trước.")
            if current["status"] != "Đã xác nhận":
                _confirm_locked(db, current, user, request, force)
        return _payload(db, appointment_id)


@router.post("/{appointment_id}/cancel", response_model=AppointmentOut, response_model_exclude_none=True)
def cancel_appointment(
    appointment_id: int,
    item: AppointmentCancelIn,
    request: Request,
    user: dict = Depends(require_permission("appointments")),
) -> dict:
    with connect() as db:
        with transaction(db):
            current = _row_or_404(db, appointment_id, user)
            if current["status"] == "Đã tiếp nhận":
                raise BadRequestError(
                    "Lịch hẹn đã được tiếp nhận. Hãy hủy phiếu sửa chữa thay vì hủy lịch hẹn.",
                    details={"repair_order_id": current["repair_order_id"]},
                )
            if current["status"] != "Đã hủy":
                db.execute(
                    "UPDATE appointments SET status='Đã hủy', cancelled_at=?, cancel_reason=? "
                    "WHERE id=?",
                    (now_utc_iso(), item.reason, appointment_id),
                )
                write_audit(
                    db, user, "appointment.cancel", "appointments", appointment_id,
                    {"reason": item.reason}, client_ip(request),
                )
        return _payload(db, appointment_id)


@router.patch("/{appointment_id}/status", response_model=AppointmentOut, response_model_exclude_none=True)
def update_appointment_status(
    appointment_id: int,
    item: AppointmentStatusIn,
    request: Request,
    force: bool = Query(default=False, description="Xác nhận dù còn cảnh báo trùng lịch"),
    user: dict = Depends(require_permission("appointments")),
) -> dict:
    """Đổi trạng thái (tương thích client cũ).

    Không cho đặt trực tiếp ``Đã tiếp nhận``: phải đi qua ``/receive`` để luôn có
    phiếu sửa chữa và không tạo phiếu trùng.
    """
    _ensure_appointment_operator(user, "thay đổi trạng thái lịch hẹn")
    if item.status == "Đã tiếp nhận":
        raise BadRequestError(
            "Vui lòng dùng chức năng Tiếp nhận xe để tạo phiếu sửa chữa, tránh tạo phiếu trùng.",
            details={"suggest": "POST /appointments/{id}/receive"},
        )
    with connect() as db:
        with transaction(db):
            current = _row_or_404(db, appointment_id, user)
            if item.status == current["status"]:
                return _payload(db, appointment_id)
            if item.status not in ALLOWED_TRANSITIONS.get(current["status"], set()):
                raise BadRequestError(
                    f"Không thể chuyển lịch hẹn từ {current['status']} sang {item.status}.",
                    details={"from": current["status"], "to": item.status},
                )
            if item.status == "Đã xác nhận":
                _confirm_locked(db, current, user, request, force)
            elif item.status == "Đã hủy":
                reason = item.reason.strip() or "Hủy bởi nhân viên"
                db.execute(
                    "UPDATE appointments SET status='Đã hủy', cancelled_at=?, cancel_reason=? "
                    "WHERE id=?",
                    (now_utc_iso(), reason, appointment_id),
                )
                write_audit(
                    db, user, "appointment.cancel", "appointments", appointment_id,
                    {"reason": reason}, client_ip(request),
                )
            else:  # Đang chờ: bỏ xác nhận hoặc khôi phục lịch đã hủy
                db.execute(
                    "UPDATE appointments SET status='Đang chờ', confirmed_at=NULL, "
                    "cancelled_at=NULL, cancel_reason='' WHERE id=?",
                    (appointment_id,),
                )
                write_audit(
                    db, user, "appointment.status", "appointments", appointment_id,
                    {"status": "Đang chờ"}, client_ip(request),
                )
        return _payload(db, appointment_id)


@router.post(
    "/{appointment_id}/receive",
    status_code=201,
    response_model=AppointmentReceiveOut,
    response_model_exclude_none=True,
)
def receive_appointment(
    appointment_id: int,
    item: AppointmentReceiveIn,
    request: Request,
    user: dict = Depends(require_permission("appointments")),
) -> dict:
    """Chuyển lịch hẹn thành phiếu tiếp nhận — không tạo bản ghi trùng.

    * Lịch đã có phiếu thì trả lại đúng phiếu đó (``already_received``).
    * Nếu xe đã có phiếu đang mở thì dùng lại phiếu đó (``reused_existing``).
    * Chỉ khi chưa có mới tạo phiếu mới, trong cùng transaction với việc cập nhật lịch.
    """
    _ensure_appointment_operator(user, "tiếp nhận xe")
    with connect() as db:
        with transaction(db):
            appointment = _row_or_404(db, appointment_id, user)
            if appointment["status"] == "Đã hủy":
                raise BadRequestError("Lịch hẹn đã hủy, không thể tiếp nhận xe.")

            if appointment["repair_order_id"]:
                order = db.execute(
                    "SELECT id, code, status FROM repair_orders WHERE id=?",
                    (appointment["repair_order_id"],),
                ).fetchone()
                if order:
                    return {
                        "appointment_id": appointment_id,
                        "status": appointment["status"],
                        "repair_order_id": order["id"],
                        "code": order["code"],
                        "already_received": True,
                        "reused_existing": True,
                        "message": f"Lịch hẹn đã được tiếp nhận bằng phiếu {order['code']}.",
                    }

            technician = (item.technician or appointment["technician"] or "").strip()
            technician_id = technician_id_for(db, technician)
            # Lịch tạo bằng biển số tự do có thể chưa gắn customer_id/vehicle_id; tra
            # lại xe để phiếu tiếp nhận vẫn gắn đúng hồ sơ.
            order_customer_id = appointment["linked_customer_id"] or appointment["customer_id"]
            order_vehicle_id = appointment["vehicle_id"]
            if not order_vehicle_id:
                found = locate_vehicle(db, appointment["plate"])
                if found:
                    order_vehicle_id = found["id"]
                    order_customer_id = order_customer_id or found["customer_id"]
            requested_parts = db.execute(
                "SELECT name,quantity FROM appointment_part_requests WHERE appointment_id=? ORDER BY id",
                (appointment_id,),
            ).fetchall()
            requested_text = ("Phụ tùng khách muốn trao đổi: " + ", ".join(
                f"{row['name']} (dự kiến {row['quantity']})" for row in requested_parts
            ) + ". Cần kiểm tra xe, xác nhận tương thích và chốt với khách trước khi thêm vào phiếu.") if requested_parts else ""
            target_plate = normalize_plate(appointment["plate"])
            placeholders = ", ".join("?" for _ in OPEN_ORDER_STATUSES)
            existing = None
            for row in db.execute(
                f"SELECT id, code, plate, status FROM repair_orders "
                f"WHERE status IN ({placeholders}) ORDER BY id DESC",
                OPEN_ORDER_STATUSES,
            ).fetchall():
                if normalize_plate(row["plate"]) == target_plate:
                    existing = dict(row)
                    break

            if existing:
                order_id = existing["id"]
                code = existing["code"]
                reused = True
                db.execute(
                    "UPDATE repair_orders SET technician=?, technician_id=?, "
                    "customer_id=COALESCE(customer_id, ?), vehicle_id=COALESCE(vehicle_id, ?), "
                    "km_in=COALESCE(?, km_in), received_at=COALESCE(received_at, ?) "
                    "WHERE id=?",
                    (
                        technician,
                        technician_id,
                        order_customer_id,
                        order_vehicle_id,
                        item.km_in,
                        now_utc_iso(),
                        order_id,
                    ),
                )
                if requested_text:
                    db.execute(
                        "UPDATE repair_orders SET customer_request=TRIM(COALESCE(customer_request,'') || char(10) || ?) WHERE id=?",
                        (requested_text, order_id),
                    )
            else:
                code = next_order_code(db)
                note = item.note or appointment["reason"] or appointment["service"]
                received_at = now_utc_iso()
                initial_condition = appointment["note"] or "Xe tiếp nhận theo lịch hẹn"
                customer_request = (appointment["reason"] or appointment["service"] or note) + (
                    "\n" + requested_text if requested_text else ""
                )
                cursor = db.execute(
                    """
                    INSERT INTO repair_orders(code, customer_id, vehicle_id, plate, customer_name,
                        advisor_id, technician_id, technician, status, status_code, priority, km_in,
                        note, initial_condition, customer_request, inspection_notes,
                        total, received_at, opened_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'Tiếp nhận', 'RECEIVED', ?, ?, ?, ?, ?, '', 0, ?, ?)
                    """,
                    (
                        code,
                        order_customer_id,
                        order_vehicle_id,
                        appointment["plate"],
                        appointment["customer_name"],
                        user["id"],
                        technician_id,
                        technician,
                        item.priority,
                        item.km_in,
                        note,
                        initial_condition,
                        customer_request,
                        received_at,
                        received_at,
                    ),
                )
                order_id = cursor.lastrowid
                ensure_status_history(db, order_id)
                reused = False
                write_audit(
                    db, user, "repair_order.create", "repair_orders", order_id,
                    {"code": code, "plate": appointment["plate"], "from_appointment": appointment_id},
                    client_ip(request),
                )

            db.execute(
                "UPDATE appointments SET status='Đã tiếp nhận', repair_order_id=?, technician=?, "
                "technician_id=?, cancelled_at=NULL, cancel_reason='' WHERE id=?",
                (order_id, technician, technician_id, appointment_id),
            )
            if item.km_in is not None:
                sync_vehicle_mileage(db, order_vehicle_id, item.km_in)
            write_audit(
                db, user, "appointment.receive", "appointments", appointment_id,
                {"repair_order_id": order_id, "code": code, "reused_existing": reused},
                client_ip(request),
            )
        message = (
            f"Đã dùng lại phiếu đang mở {code} cho xe {appointment['plate']}."
            if reused
            else f"Đã tạo phiếu tiếp nhận {code} cho xe {appointment['plate']}."
        )
        return {
            "appointment_id": appointment_id,
            "status": "Đã tiếp nhận",
            "repair_order_id": order_id,
            "code": code,
            "already_received": False,
            "reused_existing": reused,
            "message": message,
        }
