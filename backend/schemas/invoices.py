"""Schema cho module hóa đơn và thanh toán."""

from pydantic import ConfigDict, Field

from .common import RecordModel
from datetime import date
from typing import Literal

from .enums import InvoiceStatus


class InvoiceIn(RecordModel):
    """Tạo hóa đơn.

    Không tiếp nhận ``subtotal``/``tax``/``total``/``paid_amount``/``status``:
    toàn bộ giá trị tiền do server tính từ phiếu sửa chữa và cấu hình thuế.
    """

    model_config = ConfigDict(extra="forbid")

    repair_order_id: int
    quote_id: int | None = None
    note: str = Field(default="", max_length=1000)


class InvoiceStatusIn(RecordModel):
    model_config = ConfigDict(extra="forbid")

    status: InvoiceStatus


class PaymentIn(RecordModel):
    """Ghi nhận thanh toán.

    ``amount`` để trống nghĩa là thu hết phần còn lại. Số tiền do server kiểm
    tra (không vượt quá số còn phải thu) và tự suy ra trạng thái hóa đơn.
    """

    model_config = ConfigDict(extra="forbid")

    invoice_id: int
    method: Literal["Tiền mặt", "Quét mã cửa hàng"] = "Tiền mặt"
    amount: int | None = Field(default=None, gt=0)
    reference_code: str = Field(default="", max_length=60)
    note: str = Field(default="", max_length=500)
    next_due_at: date | None = None


class InvoiceCreatedOut(RecordModel):
    id: int
    code: str
    repair_order_id: int | None = None
    quote_id: int | None = None
    subtotal: int
    discount: int
    tax: int
    total: int
    estimated_duration_min: int | None = None
    paid_amount: int
    remaining_amount: int
    status: str


class InvoiceOut(RecordModel):
    id: int
    code: str | None = None
    repair_order_id: int | None = None
    quote_id: int | None = None
    order_code: str | None = None
    plate: str | None = None
    technician: str | None = None
    order_status: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    make: str | None = None
    model: str | None = None
    subtotal: int | None = None
    discount: int | None = None
    tax: int | None = None
    total: int | None = None
    estimated_duration_min: int | None = None
    paid_amount: int | None = None
    remaining_amount: int | None = None
    settled_at: str | None = None
    quote_code: str | None = None
    status: str | None = None
    issued_at: str | None = None
    due_at: str | None = None
    note: str | None = None
    created_by: int | None = None


class InvoiceStatusOut(RecordModel):
    id: int
    status: str
    paid_amount: int


class PaymentOut(RecordModel):
    id: int
    invoice_id: int | None = None
    method: str | None = None
    amount: int | None = None
    status: str | None = None
    reference_code: str | None = None
    paid_at: str | None = None
    received_by: int | None = None
    note: str | None = None
    created_at: str | None = None


class PaymentCreatedOut(RecordModel):
    id: int
    invoice_id: int
    amount: int
    method: str
    status: str
    paid_amount: int
    remaining: int
    paid_at: str | None = None


class InvoiceDetailOut(InvoiceOut):
    items: list[dict] = Field(default_factory=list)
    payments: list[dict] = Field(default_factory=list)
