"""Schema cho module lịch hẹn (đặt lịch, xác nhận, hủy, tiếp nhận)."""

from datetime import datetime

from pydantic import ConfigDict, Field, model_validator

from .common import RecordModel
from .enums import AppointmentStatus, Priority


class RequestedPartIn(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    part_id: int | None = Field(default=None, gt=0)
    name: str = Field(default="", max_length=120)
    quantity: int = Field(default=1, ge=1, le=20)

    @model_validator(mode="after")
    def _require_part(self):
        if not self.part_id and len(self.name) < 2:
            raise ValueError("Cần chọn phụ tùng hoặc mô tả yêu cầu")
        return self


class AppointmentIn(RecordModel):
    """Tạo lịch hẹn.

    Có thể chọn khách hàng/xe bằng ``customer_id``/``vehicle_id`` (ưu tiên) hoặc
    nhập biển số tự do. Yêu cầu do khách hàng tạo luôn bắt đầu ở ``Đang chờ``.
    Chỉ tài khoản nhân viên có vai trò điều phối mới được xác nhận.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    customer_id: int | None = None
    vehicle_id: int | None = None
    customer_name: str = Field(default="", max_length=120)
    plate: str = Field(default="", max_length=20)
    service: str = Field(min_length=2, max_length=120)
    service_id: int | None = Field(default=None, gt=0)
    appointment_at: datetime
    reason: str = Field(default="", max_length=500)
    note: str = Field(default="", max_length=1000)
    requested_parts: list[RequestedPartIn] = Field(default_factory=list, max_length=10)
    duration_min: int = Field(default=60, gt=0, le=1440)
    technician: str = Field(default="", max_length=80)
    resource_id: int | None = None
    status: AppointmentStatus = "Đang chờ"

    @model_validator(mode="after")
    def _require_subject(self):
        if not self.customer_id and not self.vehicle_id and len(self.plate) < 5:
            raise ValueError("Cần chọn khách hàng/xe hoặc nhập biển số xe")
        return self


class AppointmentUpdate(RecordModel):
    """Sửa lịch hẹn (không đổi trạng thái — dùng endpoint xác nhận/hủy).

    Gửi ``resource_id: 0`` để bỏ xếp nguồn lực, ``technician: ""`` để bỏ phân công.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    customer_id: int | None = None
    vehicle_id: int | None = None
    plate: str | None = Field(default=None, max_length=20)
    service: str | None = Field(default=None, min_length=2, max_length=120)
    service_id: int | None = Field(default=None, gt=0)
    appointment_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=1000)
    requested_parts: list[RequestedPartIn] | None = Field(default=None, max_length=10)
    duration_min: int | None = Field(default=None, gt=0, le=1440)
    technician: str | None = Field(default=None, max_length=80)
    resource_id: int | None = None


class AppointmentStatusIn(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: AppointmentStatus
    reason: str = Field(default="", max_length=500)


class AppointmentCancelIn(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(min_length=2, max_length=500)


class AppointmentReceiveIn(RecordModel):
    """Thông tin bổ sung khi chuyển lịch hẹn thành phiếu tiếp nhận."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    km_in: int | None = Field(default=None, ge=0)
    priority: Priority = "Bình thường"
    technician: str = Field(default="", max_length=80)
    note: str = Field(default="", max_length=1000)


class AppointmentOut(RecordModel):
    id: int
    customer_id: int | None = None
    vehicle_id: int | None = None
    customer_name: str | None = None
    plate: str | None = None
    service: str | None = None
    reason: str | None = None
    note: str | None = None
    requested_parts: list[dict] = Field(default_factory=list)
    appointment_at: str | None = None
    duration_min: int | None = None
    status: str | None = None
    technician: str | None = None
    technician_id: int | None = None
    resource_id: int | None = None
    resource_name: str | None = None
    repair_order_id: int | None = None
    repair_order_code: str | None = None
    repair_order_status: str | None = None
    confirmed_at: str | None = None
    cancelled_at: str | None = None
    cancel_reason: str | None = None
    created_by: int | None = None
    linked_customer_id: int | None = None
    phone: str | None = None
    email: str | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = None
    vin: str | None = None
    conflicts: list[dict] | None = None
    warnings: list[dict] | None = None


class AppointmentReceiveOut(RecordModel):
    appointment_id: int
    status: str
    repair_order_id: int
    code: str
    already_received: bool = False
    reused_existing: bool = False
    message: str


class AppointmentRulesOut(RecordModel):
    working_days: list[int]
    working_days_text: str
    working_hours: dict
    slot_advice: str
    resources_enabled: bool
    resources: list[dict] = Field(default_factory=list)
    technicians: list[str] = Field(default_factory=list)
    services: list[dict] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)


class AppointmentCheckOut(RecordModel):
    ok: bool
    blocking: list[dict] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)
    message: str = ""
