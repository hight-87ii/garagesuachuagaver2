"""Schema cho module dịch vụ AI."""

from typing import Literal

from pydantic import ConfigDict, Field

from .common import RecordModel
from .enums import AITask


class AIRequest(RecordModel):
    model_config = ConfigDict(extra="forbid")

    task: AITask
    data: dict = Field(default_factory=dict)
    ref_type: str = Field(default="", max_length=40)
    ref_id: str = Field(default="", max_length=40)


class AIResultOut(RecordModel):
    """Kết quả AI luôn là bản nháp, cần kỹ thuật viên xác nhận."""

    result: str
    is_draft: bool = True
    status: str
    no_data: bool = False
    source_count: int = 0
    suggested_items: list[dict] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    ref_code: str | None = None
    ref_id: str | None = None
    history_summary: dict | None = None
    analytics: dict | None = None
    data_status: Literal["sourced", "partial", "no_data", "error"] | None = None


class VehicleHistorySummaryIn(RecordModel):
    """Giao diện chỉ gửi định danh; backend tự lấy toàn bộ ngữ cảnh từ database."""

    model_config = ConfigDict(extra="forbid")
    vehicle_id: int | None = Field(default=None, gt=0)
    plate: str | None = Field(default=None, min_length=2, max_length=30)


class ServiceExplanationIn(RecordModel):
    """Chọn báo giá/hạng mục đã tồn tại; không cho client gửi tên hoặc giá."""

    model_config = ConfigDict(extra="forbid")
    quote_id: int | None = Field(default=None, gt=0)
    quote_item_id: int | None = Field(default=None, gt=0)


class ServiceFollowUpTurn(RecordModel):
    """Một lượt hội thoại đã hiển thị cho khách; chỉ dùng làm ngữ cảnh, không phải dữ liệu nghiệp vụ."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=1200)


class ServiceFollowUpIn(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=2, max_length=500)
    history: list[ServiceFollowUpTurn] = Field(default_factory=list, max_length=10)


class AssistantChatIn(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=2, max_length=500)
    vehicle_id: int | None = Field(default=None, gt=0)
    plate: str | None = Field(default=None, min_length=2, max_length=30)
    history: list[ServiceFollowUpTurn] = Field(default_factory=list, max_length=10)


class ConversationCreateIn(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    client_key: str = Field(min_length=8, max_length=80)
    vehicle_id: int | None = Field(default=None, gt=0)
    plate: str | None = Field(default=None, min_length=2, max_length=30)


class ConversationMessageIn(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: str = Field(min_length=8, max_length=80)
    question: str = Field(min_length=2, max_length=500)


class InvoiceQueryIn(RecordModel):
    """Câu hỏi hóa đơn; không nhận role, user ID, SQL hoặc số tiền từ client."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=2, max_length=500)
