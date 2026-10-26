"""Nạp 100 bản nháp đã biên tập qua ArticleIn/create_article (không duyệt hộ).

    python import_technical_expansion.py         # đối chiếu trước khi ghi
    python import_technical_expansion.py --apply # nạp từng đợt; chạy lại an toàn
"""

import argparse
import json
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

from starlette.requests import Request

from backend.database import DB_PATH, connect
from backend.api.v1.technical_knowledge import create_article
from backend.technical_expansion_data import GROUPS, articles


def folded(value: str) -> str:
    value = unicodedata.normalize("NFD", value.casefold().replace("đ", "d"))
    return " ".join("".join(c for c in value if unicodedata.category(c) != "Mn").split())


def run(apply: bool = False) -> dict:
    if not DB_PATH.is_file():
        raise RuntimeError(f"Database chưa tồn tại: {DB_PATH}. Không tự tạo database mới.")
    with connect() as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"technical_articles", "technical_chunks", "audit_logs"} <= tables:
            raise RuntimeError("Database chưa có migration bài kỹ thuật/chia đoạn/kiểm toán")
        author = db.execute("SELECT id,email,role FROM users WHERE email='admin@garage.vn' AND status='active'").fetchone()
        if not author:
            raise RuntimeError("Chưa có tài khoản quản trị hoạt động để ghi người tạo")
        user = dict(author)
        existing = [(row[0], folded(row[1]), folded(row[2])) for row in db.execute(
            "SELECT id,title,content FROM technical_articles WHERE deleted_at IS NULL")]
    request = Request({"type": "http", "method": "POST", "path": "/api/v1/ai/technical-articles",
                       "headers": [], "client": ("127.0.0.1", 0), "server": ("localhost", 0), "scheme": "http"})
    counts = Counter()
    duplicates = []
    ids = []
    for group, item in articles():
        title, content = folded(item.title), folded(item.content)
        match = next((id for id, other_title, other_content in existing
                      if title == other_title or content == other_content or
                      SequenceMatcher(None, title, other_title).ratio() >= 0.90), None)
        if match is not None:
            duplicates.append({"title": item.title, "existing_id": match})
            continue
        # Prevent duplicates inside the import even in dry-run mode.
        if apply:
            saved = create_article(item, request, user)
            assert saved["status"] == "draft" and saved["technical_reviewed_by"] is None
            ids.append(saved["id"])
            existing.append((saved["id"], title, content))
        else:
            existing.append((-1, title, content))
        counts[group] += 1
    if apply:
        with connect() as db:
            if ids:
                placeholders = ",".join("?" for _ in ids)
                saved = db.execute(f"SELECT COUNT(*) FROM technical_articles WHERE id IN ({placeholders}) AND status='draft'", ids).fetchone()[0]
                chunked = db.execute(f"SELECT COUNT(DISTINCT article_id), COUNT(*) FROM technical_chunks WHERE article_id IN ({placeholders})", ids).fetchone()
                assert saved == len(ids) == chunked[0], (saved, len(ids), chunked[0])
                assert db.execute(f"SELECT COUNT(*) FROM technical_articles WHERE id IN ({placeholders}) AND (reviewed_by IS NOT NULL OR technical_reviewed_by IS NOT NULL)", ids).fetchone()[0] == 0
                chunks = chunked[1]
            else:
                chunks = 0
    else:
        chunks = 0
    return {"database": str(DB_PATH), "mode": "apply" if apply else "dry-run",
            "new_articles": len(ids) if apply else sum(counts.values()),
            "per_group": {name: counts[name] for name, _ in GROUPS},
            "skipped_duplicates": duplicates, "chunked": len(ids) if apply else 0,
            "chunks": chunks, "verified_sources": 0, "need_source_review": len(ids) if apply else sum(counts.values()),
            "embeddings": 0, "ids": ids}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Tạo bài nháp trong DATABASE_PATH hiện tại")
    args = parser.parse_args()
    print(json.dumps(run(args.apply), ensure_ascii=False, indent=2))
