"""Incremental part-catalog knowledge; commercial facts are always re-read from DB."""

from __future__ import annotations

import argparse
from array import array
import hashlib
import math
import os
import re
import sys
import unicodedata

from dotenv import load_dotenv

load_dotenv()

from .core.db import connect, transaction
from .permissions import has_permission
from .vector_index import embed_local
from .vector_search import search_vectors


TECHNICAL_FIELDS = ("code", "name", "category", "technical_description",
                    "technical_specs", "usage_instructions", "usage_requirements")


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFD", str(value or "").casefold())
    return "".join(char for char in normalized
                   if unicodedata.category(char) != "Mn").replace("đ", "d")


def render_part_knowledge(part: dict) -> str:
    """Never include price, stock, supplier or compatibility claims in embeddings."""
    labels = {
        "code": "Mã phụ tùng", "name": "Tên phụ tùng", "category": "Nhóm",
        "technical_description": "Mô tả kỹ thuật", "technical_specs": "Thông số kỹ thuật",
        "usage_instructions": "Hướng dẫn sử dụng", "usage_requirements": "Yêu cầu sử dụng",
    }
    return ". ".join(f"{labels[key]}: {str(part.get(key) or '').strip()}"
                     for key in TECHNICAL_FIELDS if str(part.get(key) or "").strip())


def sync_part_knowledge(db, part_id: int) -> bool:
    """Update the lexical document and queue exactly one changed part for embedding."""
    row = db.execute("SELECT * FROM parts WHERE id=?", (part_id,)).fetchone()
    if not row or not row["active"]:
        db.execute("DELETE FROM knowledge_vectors WHERE source_type='part_catalog' AND source_id=?",
                   (part_id,))
        db.execute("DELETE FROM part_knowledge_documents WHERE part_id=?", (part_id,))
        db.execute("DELETE FROM part_knowledge_index_jobs WHERE part_id=?", (part_id,))
        return False
    content = render_part_knowledge(dict(row))
    if not content:
        return False
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    old = db.execute("SELECT content_hash FROM part_knowledge_documents WHERE part_id=?",
                     (part_id,)).fetchone()
    if old and old["content_hash"] == digest:
        return False
    db.execute("""INSERT INTO part_knowledge_documents(part_id,content,content_hash)
        VALUES(?,?,?) ON CONFLICT(part_id) DO UPDATE SET content=excluded.content,
        content_hash=excluded.content_hash,updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')""",
               (part_id, content, digest))
    db.execute("DELETE FROM knowledge_vectors WHERE source_type='part_catalog' AND source_id=?",
               (part_id,))
    db.execute("""INSERT INTO part_knowledge_index_jobs(part_id,content_hash,status,attempts,last_error)
        VALUES(?,?,'pending',0,'') ON CONFLICT(part_id) DO UPDATE SET
        content_hash=excluded.content_hash,status='pending',attempts=0,last_error='',
        updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')""", (part_id, digest))
    return True


def _embed(text: str, model: str, embed) -> list[float]:
    return (embed(text, model, timeout=int(os.getenv("PART_EMBED_TIMEOUT", "8")))
            if embed is embed_local else embed(text, model))


def process_part_index_job(part_id: int, *, model: str | None = None,
                           embed=embed_local) -> bool:
    """Best-effort worker used after commit; failure leaves a retryable job."""
    model = model or os.getenv("LOCAL_EMBED_MODEL", "bge-m3")
    try:
        with connect() as db:
            row = db.execute("""SELECT d.content,d.content_hash,p.active
                FROM part_knowledge_documents d JOIN parts p ON p.id=d.part_id
                WHERE d.part_id=?""", (part_id,)).fetchone()
        if not row or not row["active"]:
            return False
        vector = _embed(row["content"], model, embed)
        if not vector or any(not isinstance(value, (int, float)) or not math.isfinite(value)
                             for value in vector):
            raise ValueError("invalid embedding")
        packed = array("f", vector)
        if sys.byteorder != "little":
            packed.byteswap()
        with connect() as db, transaction(db):
            current = db.execute("SELECT content_hash FROM part_knowledge_documents WHERE part_id=?",
                                 (part_id,)).fetchone()
            if not current or current["content_hash"] != row["content_hash"]:
                return False
            db.execute("""INSERT INTO knowledge_vectors(model,source_type,source_id,content_hash,
                dimensions,embedding) VALUES(?,'part_catalog',?,?,?,?)
                ON CONFLICT(model,source_type,source_id) DO UPDATE SET
                content_hash=excluded.content_hash,dimensions=excluded.dimensions,
                embedding=excluded.embedding,indexed_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')""",
                (model, part_id, row["content_hash"], len(vector), packed.tobytes()))
            db.execute("""UPDATE part_knowledge_index_jobs SET status='completed',attempts=attempts+1,
                last_error='',updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE part_id=?""",
                       (part_id,))
        return True
    except Exception as exc:
        with connect() as db, transaction(db):
            db.execute("""UPDATE part_knowledge_index_jobs SET status='failed',attempts=attempts+1,
                last_error=?,updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE part_id=?""",
                       (type(exc).__name__[:80], part_id))
        return False


def process_pending_part_jobs(*, limit: int = 50, model: str | None = None,
                              embed=embed_local) -> dict[str, int]:
    """Retry a bounded batch; never rebuild unchanged technical/article vectors."""
    with connect() as db:
        ids = [row["part_id"] for row in db.execute("""SELECT part_id
            FROM part_knowledge_index_jobs WHERE status IN ('pending','failed')
            ORDER BY updated_at,part_id LIMIT ?""", (max(1, min(limit, 500)),)).fetchall()]
    result = {"processed": 0, "completed": 0, "failed": 0}
    for part_id in ids:
        result["processed"] += 1
        if process_part_index_job(part_id, model=model, embed=embed):
            result["completed"] += 1
        else:
            result["failed"] += 1
    return result


def ensure_part_knowledge_schema() -> list[str]:
    """CLI entry points do not run FastAPI lifespan, so apply pending migrations here."""
    from .migrations import run_migrations
    with connect() as db:
        return run_migrations(db)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Xử lý incremental embedding đang chờ của kho tri thức phụ tùng")
    parser.add_argument("--limit", type=int, default=50, help="Số job tối đa trong một lượt")
    parser.add_argument("--model", default=os.getenv("LOCAL_EMBED_MODEL", "bge-m3"))
    args = parser.parse_args()
    migrations = ensure_part_knowledge_schema()
    if migrations:
        print("Đã áp dụng migration: " + ", ".join(migrations))
    result = process_pending_part_jobs(limit=args.limit, model=args.model)
    print(f"Đã xử lý {result['processed']}: thành công {result['completed']}, "
          f"lỗi {result['failed']}.")


if __name__ == "__main__":
    main()


def is_part_knowledge_question(question: str) -> bool:
    text = _fold(question)
    subject = any(term in text for term in (
        "phu tung", "linh kien", "bugi", "loc dau", "loc gio", "ma phanh",
        "ac quy", "cam bien", "day curoa", "rotuyn", "giam xoc"))
    knowledge = any(term in text for term in (
        "la gi", "dung de", "cong dung", "thong so", "huong dan", "cach dung",
        "yeu cau su dung", "hoat dong", "loai nao"))
    return subject and knowledge


def search_part_knowledge(db, question: str, user: dict, *, limit: int = 5) -> list[dict]:
    """Retrieve IDs, then read every returned field from the live authorized DB."""
    tokens = list(dict.fromkeys(word for word in re.findall(r"[a-z0-9]+", _fold(question))
                                if len(word) > 1 and word not in {
                                    "la", "gi", "dung", "de", "cho", "xe", "toi", "cua", "nao"}))[:8]
    match = " OR ".join(f'"{token}"' for token in tokens)
    lexical = [row["part_id"] for row in db.execute("""SELECT d.part_id
        FROM part_knowledge_fts f JOIN part_knowledge_documents d ON d.part_id=f.rowid
        JOIN parts p ON p.id=d.part_id
        WHERE part_knowledge_fts MATCH ? AND p.active=1 ORDER BY bm25(part_knowledge_fts) LIMIT 20""",
        (match,)).fetchall()] if match else []
    semantic = [part_id for part_id, _score in search_vectors(
        db, question, "part_catalog", limit=20)]
    ids = list(dict.fromkeys([*lexical, *semantic]))[:limit]
    if not ids:
        return []
    can_inventory = has_permission(user.get("role", ""), "inventory.view_all")
    normalized_question = _fold(question)
    asks_price = bool(re.search(r"\b(?:gia|bao gia|chi phi|bao nhieu tien)\b", normalized_question))
    asks_stock = any(term in normalized_question for term in ("ton kho", "con hang", "so luong"))
    asks_supplier = any(term in normalized_question for term in ("nha cung cap", "supplier"))
    results = []
    for part_id in ids:
        price_columns = ("p.sell_price,a.approved_sell_price" if asks_price else
                         "NULL sell_price,NULL approved_sell_price")
        stock_column = "p.stock" if can_inventory and asks_stock else "NULL stock"
        supplier_column = "p.supplier" if can_inventory and asks_supplier else "NULL supplier"
        approval_join = ("LEFT JOIN part_price_approvals a ON a.part_id=p.id"
                         if asks_price else "")
        row = db.execute(f"""SELECT p.id,p.code,p.name,p.category,p.unit,p.active,
            p.technical_description,p.technical_specs,p.usage_instructions,p.usage_requirements,
            {price_columns},{stock_column},{supplier_column}
            FROM parts p {approval_join} WHERE p.id=? AND p.active=1""",
            (part_id,)).fetchone()
        if not row:
            continue
        item = {key: row[key] for key in ("id", "code", "name", "category", "unit",
            "technical_description", "technical_specs", "usage_instructions", "usage_requirements")}
        if asks_price:
            item["approved_sell_price"] = (row["sell_price"] if row["sell_price"] is not None
                                            and row["approved_sell_price"] == row["sell_price"] else None)
        if can_inventory and asks_stock:
            item["stock"] = row["stock"]
        if can_inventory and asks_supplier:
            item["supplier"] = row["supplier"]
        item["fitments"] = [dict(rule) for rule in db.execute(
            "SELECT make,model,year_from,year_to,variant,engine_code,fuel_type,note "
            "FROM part_fitments WHERE part_id=? ORDER BY id", (part_id,)).fetchall()]
        results.append(item)
    return results
