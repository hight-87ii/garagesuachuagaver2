"""Cập nhật các bài đã đối chiếu từng nguồn, không duyệt hoặc xuất bản.

    python apply_technical_source_reviews.py
    python apply_technical_source_reviews.py --apply
"""

import argparse
import json

from starlette.requests import Request

from backend.database import DB_PATH, connect
from backend.api.v1.technical_knowledge import ArticleIn, update_article
from backend.technical_source_reviews import REVIEWS


def run(apply: bool = False):
    if not DB_PATH.is_file():
        raise RuntimeError(f"Database không tồn tại: {DB_PATH}")
    request = Request({"type": "http", "method": "PUT", "path": "/api/v1/ai/technical-articles",
                       "headers": [], "client": ("127.0.0.1", 0), "server": ("localhost", 0), "scheme": "http"})
    with connect() as db:
        user = dict(db.execute("SELECT id,email,role FROM users WHERE email='admin@garage.vn' AND status='active'").fetchone())
        found = {row["title"]: dict(row) for row in db.execute(
            "SELECT * FROM technical_articles WHERE deleted_at IS NULL AND title IN ("
            + ",".join("?" for _ in REVIEWS) + ")", tuple(REVIEWS))}
    if set(found) != set(REVIEWS):
        raise RuntimeError("Không tìm đủ bài cần đối chiếu; không ghi dữ liệu")
    changed, already = [], []
    for title, evidence in REVIEWS.items():
        row = found[title]
        if row["status"] != "draft":
            raise RuntimeError(f"Bài không còn là nháp: {title}")
        keys = ("source_name", "source_url", "document_version")
        if all(row[key] == evidence[key] for key in keys):
            already.append(row["id"])
            continue
        if not row["source_name"].startswith("Chưa xác minh"):
            raise RuntimeError(f"Nguồn đã được nhân viên thay đổi; không ghi đè: {title}")
        payload = {key: row[key] for key in ArticleIn.model_fields if key != "expected_revision"}
        payload.update({key: evidence[key] for key in keys})
        payload["expected_revision"] = row["revision"]
        item = ArticleIn.model_validate(payload)
        if apply:
            saved = update_article(row["id"], item, request, user)
            assert saved["status"] == "draft" and saved["reviewed_by"] is None
            changed.append(row["id"])
        else:
            changed.append(row["id"])
    return {"database": str(DB_PATH), "mode": "apply" if apply else "dry-run",
            "reviewed_source_candidates": len(REVIEWS), "updated": changed, "already_updated": already,
            "still_need_individual_source_review": 100 - len(REVIEWS),
            "evidence": {title: item["evidence"] for title, item in REVIEWS.items()}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.apply), ensure_ascii=False, indent=2))
