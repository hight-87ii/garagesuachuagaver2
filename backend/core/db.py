"""Truy cập cơ sở dữ liệu ở mức thấp (đọc nhanh, ghi trong transaction)."""

from typing import Any

from ..database import connect, normalize_plate, transaction

__all__ = ["connect", "transaction", "normalize_plate", "rows", "one", "scalar", "exists"]


def rows(query: str, params: tuple = ()) -> list[dict]:
    """Trả về danh sách bản ghi dạng dict."""
    with connect() as db:
        return [dict(row) for row in db.execute(query, params).fetchall()]


def one(query: str, params: tuple = ()) -> dict | None:
    """Trả về một bản ghi dạng dict hoặc None."""
    with connect() as db:
        row = db.execute(query, params).fetchone()
        return dict(row) if row else None


def scalar(query: str, params: tuple = (), default: Any = 0) -> Any:
    """Trả về giá trị đầu tiên của truy vấn (dùng cho COUNT/SUM)."""
    with connect() as db:
        row = db.execute(query, params).fetchone()
        if row is None or row[0] is None:
            return default
        return row[0]


def exists(query: str, params: tuple = ()) -> bool:
    with connect() as db:
        return db.execute(query, params).fetchone() is not None
