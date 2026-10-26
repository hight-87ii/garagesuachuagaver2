"""Schema cho module phiếu sửa chữa (repair orders) và ghi chú kỹ thuật."""

from pydantic import ConfigDict, Field

from .common import RecordModel
from .enums import (
    ItemKind,
    Priority,
    RepairOrderStatus,
    RepairOrderStatusCode,
)


class RepairOrderIn(RecordModel):
    """Tạo phiếu sửa chữa.

    Không tiếp nhận ``total``: tổng tiền do server tính từ hạng mục và phụ tùng
    đã dùng, ngăn client tự ý đặt tổng tiền. Phiếu mới luôn bắt đầu ở trạng
    thái ``RECEIVED``.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(default="", max_length=40)
    plate: str = Field(min_length=5, max_length=20)
    technician: str = Field(default="", max_length=80)
    status: RepairOrderStatus | RepairOrderStatusCode = "Tiếp nhận"
    status_code: RepairOrderStatusCode | None = None
    priority: Priority = "Bình thường"
    note: str = Field(default="", max_length=1000)
    km_in: int | None = Field(default=None, ge=0)
    initial_condition: str = Field(default="", max_length=2000)
    customer_request: str = Field(default="", max_length=2000)
    inspection_notes: str = Field(default="", max_length=2000)
    customer_id: int | None = None
    vehicle_id: int | None = None


class RepairOrderUpdate(RecordModel):
    """Cập nhật phiếu: không cho sửa ``total``.

    ``status``/``status_code`` đi qua máy trạng thái nên vẫn bị kiểm tra điều
    kiện nghiệp vụ. ``status_note`` là lý do khi tạm dừng/hủy/chờ phụ tùng.
    """

    model_config = ConfigDict(extra="forbid")

    status: RepairOrderStatus | RepairOrderStatusCode | None = None
    status_code: RepairOrderStatusCode | None = None
    status_note: str = Field(default="", max_length=1000)
    technician: str | None = Field(default=None, max_length=80)
    priority: Priority | None = None
    note: str | None = Field(default=None, max_length=1000)
    km_in: int | None = Field(default=None, ge=0)
    initial_condition: str | None = Field(default=None, max_length=2000)
    customer_request: str | None = Field(default=None, max_length=2000)
    inspection_notes: str | None = Field(default=None, max_length=2000)


class RepairOrderTransitionIn(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status_code: RepairOrderStatus | RepairOrderStatusCode
    note: str = Field(default="", max_length=1000)


class RepairOrderItemIn(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: ItemKind = "Dịch vụ"
    name: str = Field(min_length=2, max_length=160)
    quantity: float = Field(default=1, gt=0, le=1000)
    unit_price: int = Field(default=0, ge=0)
    service_id: int | None = None


class RepairItemActualDurationIn(RecordModel):
    """Số phút thao tác thực tế do kỹ thuật viên ghi nhận, không phải thời gian chờ."""
    model_config = ConfigDict(extra="forbid")
    actual_duration_min: int = Field(gt=0, le=1440)


class RepairOrderPartIn(RecordModel):
    model_config = ConfigDict(extra="forbid")

    part_id: int
    quantity: int = Field(default=1, gt=0, le=1000)


class RepairNoteIn(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    content: str = Field(min_length=2, max_length=2000)


class RepairOrderCreatedOut(RecordModel):
    id: int
    code: str
    plate: str | None = None
    status: str | None = None
    status_code: str | None = None
    priority: str | None = None
    technician: str | None = None
    customer_id: int | None = None
    vehicle_id: int | None = None
    note: str | None = None
    km_in: int | None = None
    initial_condition: str | None = None
    customer_request: str | None = None
    inspection_notes: str | None = None
    received_at: str | None = None
    total: int = 0


class RepairOrderOut(RecordModel):
    id: int
    code: str | None = None
    customer_id: int | None = None
    vehicle_id: int | None = None
    plate: str | None = None
    customer_name: str | None = None
    advisor_id: int | None = None
    technician_id: int | None = None
    technician: str | None = None
    status: str | None = None
    status_code: str | None = None
    priority: str | None = None
    km_in: int | None = None
    note: str | None = None
    initial_condition: str | None = None
    customer_request: str | None = None
    inspection_notes: str | None = None
    cancel_reason: str | None = None
    total: int | None = None
    received_at: str | None = None
    opened_at: str | None = None
    completed_at: str | None = None
    delivered_at: str | None = None
    closed_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = None
    color: str | None = None
    vin: str | None = None
    mileage: int | None = None
    customer_phone: str | None = None
    item_count: int | None = None
    part_count: int | None = None


class RepairOrderDetailOut(RepairOrderOut):
    items: list[dict] = Field(default_factory=list)
    parts_used: list[dict] = Field(default_factory=list)
    notes: list[dict] = Field(default_factory=list)
    quotes: list[dict] = Field(default_factory=list)
    history: list[dict] = Field(default_factory=list)
    allowed_transitions: list[dict] = Field(default_factory=list)


class RepairOrderTransitionOut(RepairOrderOut):
    allowed_transitions: list[dict] = Field(default_factory=list)
    history_entry: dict | None = None


class RepairOrderStatusHistoryOut(RecordModel):
    id: int
    repair_order_id: int
    from_status: str = ""
    to_status: str
    from_status_label: str = ""
    to_status_label: str = ""
    note: str = ""
    changed_by: int | None = None
    changed_by_name: str = ""
    created_at: str | None = None


class RepairOrderItemCreatedOut(RecordModel):
    id: int
    kind: str
    name: str
    quantity: float
    unit_price: int
    line_total: int
    order_total: int


class RepairOrderPartCreatedOut(RecordModel):
    id: int
    part_id: int
    name: str
    quantity: int
    unit_price: int
    line_total: int
    order_total: int


class RepairOrderPartOut(RecordModel):
    id: int
    repair_order_id: int | None = None
    part_id: int | None = None
    name: str | None = None
    quantity: int | None = None
    unit_price: int | None = None
    line_total: int | None = None
    part_code: str | None = None
    unit: str | None = None
    stock: int | None = None


class RepairNoteOut(RecordModel):
    id: int
    repair_order_id: int | None = None
    author_id: int | None = None
    author_name: str | None = None
    content: str | None = None
    created_at: str | None = None


class DeletedOut(RecordModel):
    deleted: int
    order_total: int | None = None
