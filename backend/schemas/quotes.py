"""Schema cho module báo giá (quotes)."""

from pydantic import ConfigDict, Field

from .common import RecordModel
from .enums import ItemKind, QuoteStatus


class QuoteItemIn(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: ItemKind = "Dịch vụ"
    name: str = Field(min_length=2, max_length=160)
    quantity: float = Field(default=1, gt=0, le=1000)
    unit_price: int = Field(default=0, ge=0)
    service_id: int | None = None
    part_id: int | None = None


class QuoteIn(RecordModel):
    model_config = ConfigDict(extra="forbid")

    repair_order_id: int
    discount: int = Field(default=0, ge=0)
    tax_rate: float = Field(default=0.08, ge=0, le=1)
    note: str = Field(default="", max_length=1000)
    valid_until: str | None = Field(default=None, max_length=40)
    items: list[QuoteItemIn] = Field(default_factory=list)


class QuoteStatusIn(RecordModel):
    model_config = ConfigDict(extra="forbid")

    status: QuoteStatus


class QuoteNarrativeIn(RecordModel):
    """Nhân viên duyệt/chỉnh lời diễn giải của báo giá Nháp."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    note: str = Field(min_length=1, max_length=4000)


class QuoteCreatedOut(RecordModel):
    id: int
    code: str
    version: int
    status: str
    subtotal: int
    discount: int
    tax: int
    total: int
    estimated_duration_min: int | None = None
    tax_rate: float | None = None
    valid_until: str | None = None


class AIQuoteDraftIn(RecordModel):
    """Chỉ chọn các dòng đã có trên phiếu; không nhận tên, giá hoặc tổng tiền."""

    model_config = ConfigDict(extra="forbid")
    repair_order_id: int = Field(gt=0)
    service_item_ids: list[int] = Field(default_factory=list, max_length=100)
    part_usage_ids: list[int] = Field(default_factory=list, max_length=100)
    valid_until: str | None = Field(default=None, max_length=40)
    explanation: str | None = Field(default=None, min_length=1, max_length=4000)
    expected_total: int | None = Field(default=None, ge=0)


class AIQuoteDraftOut(QuoteCreatedOut):
    labor_subtotal: int = 0
    parts_subtotal: int = 0
    ai_status: str
    explanation: str
    sources: list[dict] = Field(default_factory=list)


class AIQuotePreviewOut(RecordModel):
    subtotal: int
    labor_subtotal: int
    parts_subtotal: int
    discount: int
    tax: int
    total: int
    tax_rate: float
    valid_until: str
    estimated_duration_min: int | None = None
    ai_status: str
    explanation: str


class QuoteOut(RecordModel):
    id: int
    code: str | None = None
    repair_order_id: int | None = None
    order_code: str | None = None
    plate: str | None = None
    version: int | None = None
    status: str | None = None
    subtotal: int | None = None
    discount: int | None = None
    tax: int | None = None
    total: int | None = None
    estimated_duration_min: int | None = None
    tax_rate: float | None = None
    valid_until: str | None = None
    validity_status: str | None = None
    note: str | None = None
    approved_by: int | None = None
    approved_at: str | None = None
    created_by: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


class QuoteDetailOut(QuoteOut):
    items: list[dict] = Field(default_factory=list)


class QuoteStatusOut(RecordModel):
    id: int
    status: str
