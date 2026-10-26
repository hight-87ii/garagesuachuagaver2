"""Hỗ trợ phân trang nhất quán cho các endpoint danh sách."""

import sqlite3
from dataclasses import dataclass
from typing import Any

from fastapi import Query

from .config import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


@dataclass(frozen=True)
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_params(
    page: int = Query(default=1, ge=1, description="Trang hiện tại (bắt đầu từ 1)"),
    page_size: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Số bản ghi mỗi trang",
    ),
) -> PageParams:
    """Dependency đọc và kiểm tra tham số phân trang."""
    return PageParams(page=page, page_size=page_size)


def envelope(items: list[dict], total: int, params: PageParams) -> dict:
    pages = (total + params.page_size - 1) // params.page_size if params.page_size else 0
    return {
        "items": items,
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
        "pages": pages,
    }


def fetch_page(
    db: sqlite3.Connection,
    base_sql: str,
    params: tuple,
    order_by: str,
    page: PageParams,
) -> tuple[list[dict], int]:
    """Chạy truy vấn đếm + truy vấn dữ liệu có LIMIT/OFFSET.

    ``base_sql`` là câu SELECT chưa có ORDER BY; ``order_by`` được thêm riêng để
    có thể tái sử dụng cho truy vấn đếm.
    """
    total = int(db.execute(f"SELECT COUNT(*) FROM ({base_sql})", params).fetchone()[0])
    rows = [
        dict(row)
        for row in db.execute(
            f"{base_sql} {order_by} LIMIT ? OFFSET ?",
            (*params, page.page_size, page.offset),
        ).fetchall()
    ]
    return rows, total


def search_clause(keyword: str, columns: list[str]) -> tuple[str, list[Any]]:
    """Tạo mệnh đề LIKE an toàn (tham số hóa) cho nhiều cột."""
    if not keyword:
        return "", []
    pattern = f"%{keyword}%"
    clause = " AND (" + " OR ".join(f"{column} LIKE ?" for column in columns) + ")"
    return clause, [pattern] * len(columns)
