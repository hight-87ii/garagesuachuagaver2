"""Lập chỉ mục embedding cục bộ; chưa dùng vector để trả lời chat.

Chạy từ gốc dự án: python -m backend.vector_index --model bge-m3
Ollama chỉ được gọi qua localhost; không tự động tải mô hình hay gửi dữ liệu ra ngoài.
"""

import argparse
from array import array
import hashlib
import json
import math
import sys
from urllib import error, request

from .database import connect
from .migrations import run_migrations


def eligible_sources(db):
    """Không đưa bài nháp/thu hồi/xóa hay ca chưa duyệt vào chỉ mục."""
    for row in db.execute("""SELECT c.id, c.content, a.title, a.symptoms
        FROM technical_chunks c JOIN technical_articles a ON a.id=c.article_id
        WHERE a.status='published' AND a.deleted_at IS NULL
        ORDER BY c.id"""):
        text = f"{row['title']}. {row['symptoms']}. {row['content']}".strip()
        if text:
            yield "technical_chunk", row["id"], text
    for row in db.execute("""SELECT id,vehicle_make,vehicle_model,vehicle_year,engine_code,
        customer_symptoms,inspection_findings,confirmed_cause,work_done,outcome
        FROM repair_knowledge_cases WHERE status='published' ORDER BY id"""):
        text = "Ca sửa chữa tham khảo: " + ". ".join(str(row[key]) for key in (
            "vehicle_make", "vehicle_model", "vehicle_year", "engine_code",
            "customer_symptoms", "inspection_findings", "confirmed_cause", "work_done", "outcome"
        ) if row[key] is not None and str(row[key]).strip())
        yield "repair_case", row["id"], text
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='part_knowledge_documents'").fetchone():
        for row in db.execute("""SELECT d.part_id,d.content FROM part_knowledge_documents d
            JOIN parts p ON p.id=d.part_id WHERE p.active=1 ORDER BY d.part_id"""):
            if str(row["content"] or "").strip():
                yield "part_catalog", row["part_id"], row["content"]


def embed_local(text: str, model: str, base_url: str = "http://127.0.0.1:11434",
                timeout: int = 120) -> list[float]:
    payload = json.dumps({"model": model, "input": text}, ensure_ascii=False).encode("utf-8")
    req = request.Request(base_url.rstrip("/") + "/api/embed", data=payload,
                          headers={"Content-Type": "application/json"}, method="POST")
    with request.urlopen(req, timeout=timeout) as response:
        vectors = json.load(response).get("embeddings", [])
    if len(vectors) != 1 or not vectors[0]:
        raise ValueError("Ollama không trả về embedding hợp lệ")
    return vectors[0]


def index_sources(db, model: str, embed=embed_local, *, rebuild: bool = False) -> dict[str, int]:
    """Bỏ qua nội dung không đổi; loại vector cũ sau khi duyệt lại nguồn."""
    if not model.strip():
        raise ValueError("Tên mô hình embedding không được để trống")
    sources = list(eligible_sources(db))
    current = {(kind, source_id): hashlib.sha256(text.encode("utf-8")).hexdigest()
               for kind, source_id, text in sources}
    old = {(row["source_type"], row["source_id"]): row["content_hash"]
           for row in db.execute("SELECT source_type,source_id,content_hash FROM knowledge_vectors WHERE model=?", (model,))}
    stats = {"created": 0, "skipped": 0, "removed": 0}
    # Xóa trước cả khi Ollama chưa chạy được, tránh giữ nguồn đã bị thu hồi.
    for key in old.keys() - current.keys():
        db.execute("DELETE FROM knowledge_vectors WHERE model=? AND source_type=? AND source_id=?",
                   (model, *key))
        stats["removed"] += 1
    for kind, source_id, text in sources:
        digest = current[(kind, source_id)]
        if not rebuild and old.get((kind, source_id)) == digest:
            stats["skipped"] += 1
            continue
        vector = embed(text, model)
        if not vector or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in vector):
            raise ValueError(f"Embedding không hợp lệ: {kind} #{source_id}")
        packed = array("f", vector)
        if sys.byteorder != "little":
            packed.byteswap()
        db.execute("""INSERT INTO knowledge_vectors(model,source_type,source_id,content_hash,dimensions,embedding)
            VALUES(?,?,?,?,?,?) ON CONFLICT(model,source_type,source_id) DO UPDATE SET
            content_hash=excluded.content_hash,dimensions=excluded.dimensions,
            embedding=excluded.embedding,indexed_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')""",
            (model, kind, source_id, digest, len(vector), packed.tobytes()))
        stats["created"] += 1
    return stats


def main() -> None:
    # PowerShell/Windows co the chon cp1252 lam encoding cho terminal.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Lập chỉ mục vector từ nguồn kỹ thuật đã xuất bản")
    parser.add_argument("--model", default="bge-m3", help="Mô hình embedding đã cài trong Ollama")
    parser.add_argument("--rebuild", action="store_true", help="Tạo lại mọi embedding của mô hình này")
    args = parser.parse_args()
    db = connect()
    try:
        run_migrations(db)
        result = index_sources(db, args.model, rebuild=args.rebuild)
        print(f"Chỉ mục {args.model}: tạo/cập nhật {result['created']}, "
              f"bỏ qua {result['skipped']}, loại nguồn không còn hợp lệ {result['removed']}.")
    except (error.URLError, ValueError) as exc:
        parser.exit(1, f"Không lập chỉ mục xong: {exc}\nKiểm tra Ollama đang chạy và mô hình đã cài.\n")
    finally:
        db.close()


if __name__ == "__main__":
    main()
