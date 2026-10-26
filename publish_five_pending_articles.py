"""Bổ sung 3 nguồn đã đọc, duyệt lại và xuất bản đúng 5 bài đang chờ.

    python -X utf8 publish_five_pending_articles.py         # kiểm tra trước
    python -X utf8 publish_five_pending_articles.py --apply # cập nhật + duyệt + xuất bản

Mọi thay đổi đi qua update_article/technical_review/publish_article để lưu history,
audit, revision và cập nhật chỉ mục. Không sửa bài ngoài danh sách cố định.
"""

import argparse
import json
from pathlib import Path

from starlette.requests import Request

from backend.api.v1.technical_knowledge import (
    ArticleIn, publish_article, technical_review, update_article,
)
from backend.database import DB_PATH, connect
from backend.pending_publish_source_reviews import REVIEWS

TARGETS = {
    28: "Xe lệch về một bên khi phanh",
    29: "Vô lăng rung khi đạp phanh",
    104: "Mã P0455 rò lớn hệ hơi nhiên liệu",
    107: "Lập báo giá sau khi chẩn đoán triệu chứng",
    108: "An toàn khi xử lý xe điện và hybrid",
}


def request(method: str, path: str) -> Request:
    return Request({"type": "http", "method": method, "path": path, "headers": [],
                    "client": ("127.0.0.1", 0), "server": ("localhost", 0), "scheme": "http"})


def run(apply: bool = False) -> dict:
    if not DB_PATH.is_file():
        raise RuntimeError(f"Database không tồn tại: {DB_PATH}")
    with connect() as db:
        people = {row["email"]: dict(row) for row in db.execute(
            "SELECT id,email,role FROM users WHERE email IN ('technician@garage.vn','manager@garage.vn') AND status='active'")}
        if set(people) != {"technician@garage.vn", "manager@garage.vn"}:
            raise RuntimeError("Thiếu tài khoản kỹ thuật viên hoặc quản lý đang hoạt động")
        rows = {row["id"]: dict(row) for row in db.execute(
            "SELECT * FROM technical_articles WHERE id IN (28,29,104,107,108) AND deleted_at IS NULL")}
        waiting = {row["id"] for row in db.execute(
            "SELECT id FROM technical_articles WHERE status='draft' AND technical_reviewed_by IS NOT NULL "
            "AND withdrawn_at IS NULL AND deleted_at IS NULL")}
    if set(rows) != set(TARGETS) or any(rows[i]["title"] != title for i, title in TARGETS.items()):
        raise RuntimeError("ID/tiêu đề 5 bài không còn khớp; không thao tác")
    if waiting != set(TARGETS):
        raise RuntimeError(f"Danh sách chờ xuất bản đã thay đổi: {sorted(waiting)}")
    if any(rows[i]["status"] != "draft" for i in TARGETS):
        raise RuntimeError("Có bài không còn là nháp")
    if any(rows[i]["source_name"].startswith("Chưa xác minh") for i in (28, 29)):
        raise RuntimeError("Hai bài Bosch không còn nguồn đã đối chiếu")

    plan = {"update_sources": sorted(REVIEWS), "technical_review_again": sorted(REVIEWS),
            "publish_ids": sorted(TARGETS)}
    if not apply:
        return {"database": str(DB_PATH), "mode": "dry-run", **plan}

    technician = people["technician@garage.vn"]
    manager = people["manager@garage.vn"]
    current = rows.copy()
    for title, source in REVIEWS.items():
        article_id = next(i for i, expected in TARGETS.items() if expected == title)
        row = current[article_id]
        if not row["source_name"].startswith("Chưa xác minh"):
            raise RuntimeError(f"Nguồn đã được thay đổi ngoài kế hoạch: {title}")
        payload = {key: row[key] for key in ArticleIn.model_fields if key != "expected_revision"}
        payload.update({key: source[key] for key in ("source_name", "source_url", "document_version")})
        payload["expected_revision"] = row["revision"]
        current[article_id] = update_article(article_id, ArticleIn.model_validate(payload),
            request("PUT", f"/api/v1/ai/technical-articles/{article_id}"), manager)
        current[article_id] = technical_review(article_id,
            request("POST", f"/api/v1/ai/technical-articles/{article_id}/technical-review"),
            current[article_id]["revision"], technician)

    published = []
    for article_id in sorted(TARGETS):
        row = current[article_id]
        saved = publish_article(article_id,
            request("POST", f"/api/v1/ai/technical-articles/{article_id}/publish"),
            row["revision"], manager)
        if saved["status"] != "published":
            raise RuntimeError(f"Không xuất bản được bài {article_id}")
        published.append({"id": article_id, "title": saved["title"],
                          "technical_reviewed_by": saved["technical_reviewed_by"],
                          "published_by": saved["reviewed_by"], "revision": saved["revision"]})

    with connect() as db:
        verified = [dict(row) for row in db.execute(
            "SELECT id,title,status,source_name,source_url,document_version,technical_reviewed_by,reviewed_by "
            "FROM technical_articles WHERE id IN (28,29,104,107,108) ORDER BY id")]
        if len(verified) != 5 or any(row["status"] != "published" for row in verified):
            raise RuntimeError("Kiểm tra sau xuất bản không đạt")
        fts = db.execute("SELECT COUNT(*) FROM technical_fts WHERE rowid IN (28,29,104,107,108)").fetchone()[0]
        if fts != 5:
            raise RuntimeError(f"Chỉ mục bài xuất bản không đủ: {fts}/5")
    return {"database": str(DB_PATH), "mode": "apply", **plan,
            "published": published, "fts_indexed": fts}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.apply), ensure_ascii=False, indent=2))
