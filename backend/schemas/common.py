"""Schema dùng chung: model bản ghi, phân trang và lỗi."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class RecordModel(BaseModel):
    """Model đọc dữ liệu.

    * ``extra="allow"``: giữ nguyên các cột mở rộng trả về từ câu SELECT.
    * ``from_attributes=True``: cho phép khởi tạo từ sqlite3.Row / dict.
    """

    model_config = ConfigDict(extra="allow", from_attributes=True, populate_by_name=True)


class Page(BaseModel, Generic[T]):
    """Kết quả danh sách có phân trang."""

    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


class Message(RecordModel):
    message: str


class ErrorBody(RecordModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(RecordModel):
    error: ErrorBody
    detail: str
