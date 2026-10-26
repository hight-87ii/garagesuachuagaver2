"""Tra cứu bài kỹ thuật đã duyệt, tách biệt với hồ sơ xe và dữ liệu thương mại."""

import re
import sqlite3
import unicodedata

from .vector_search import search_vectors

STOPWORDS = {"xe", "toi", "cua", "bi", "co", "la", "gi", "the", "nao", "khi", "chay",
             "luc", "lam", "sao", "can", "phai", "nen", "va", "cho", "ban", "nay",
             "tieng", "nghe", "thay", "duoc", "khong", "ho", "so", "bao", "nhieu",
             "keu", "thi", "nen", "lam", "giup"}


def _fold(text: str) -> str:
    value = unicodedata.normalize("NFD", text.casefold())
    return "".join(char for char in value if unicodedata.category(char) != "Mn").replace("đ", "d")


def _applies(article: dict, vehicle: dict | None) -> bool:
    """Thiếu thông số xe bắt buộc => không dùng bài giới hạn cho cấu hình đó."""
    for rule, field in (("vehicle_make", "make"), ("vehicle_model", "model"),
                        ("engine_code", "engine_code")):
        expected = str(article[rule] or "").strip()
        if expected and _fold(expected) != _fold(str((vehicle or {}).get(field) or "").strip()):
            return False
    if article["year_from"] is not None or article["year_to"] is not None:
        year = (vehicle or {}).get("year")
        if year is None or (article["year_from"] is not None and year < article["year_from"]) or (
                article["year_to"] is not None and year > article["year_to"]):
            return False
    return True


def search_technical(db: sqlite3.Connection, question: str, limit: int = 3,
                      *, vehicle: dict | None = None) -> list[dict]:
    """FTS5 + vector; chỉ bài published khớp cấu hình xe hoặc bài chung."""
    tokens = list(dict.fromkeys(word for word in re.findall(r"[a-z0-9]+", _fold(question))
                                if len(word) > 1 and word not in STOPWORDS))[:8]
    # FTS5 unicode61 không chuẩn hóa chữ đ; tìm trên phiên bản không dấu của câu hỏi
    # và bản có dấu gốc để bao phủ cả hai cách nhập.
    original = re.findall(r"[^\W_]+", question.casefold(), flags=re.UNICODE)
    terms = list(dict.fromkeys([*tokens, *(word for word in original if _fold(word) in tokens)]))
    match = " OR ".join('"' + term.replace('"', '') + '"' for term in terms)
    article_columns = """a.id,a.title,a.symptoms,a.content,a.safety,a.source_name,
                              a.source_url,a.document_version,a.safety_level,a.vehicle_make,
                              a.vehicle_model,a.year_from,a.year_to,a.engine_code,a.updated_at"""
    rows = db.execute(f"""SELECT {article_columns}
                        FROM technical_fts f JOIN technical_articles a ON a.id=f.rowid
                        WHERE technical_fts MATCH ? AND a.status='published' AND a.deleted_at IS NULL AND
                         (?=1 OR (a.vehicle_make='' AND a.vehicle_model='' AND
                           a.year_from IS NULL AND a.year_to IS NULL AND a.engine_code=''))
                       ORDER BY bm25(technical_fts, 5.0, 8.0, 1.0) LIMIT 100""",
                       (match, int(vehicle is not None))).fetchall() if tokens else []
    # Cho phép tìm bài từ chính nội dung tài liệu, không chỉ tên/triệu chứng của bài.
    doc_rows = db.execute(f"""SELECT DISTINCT {article_columns}
        FROM technical_chunk_fts f JOIN technical_chunks c ON c.id=f.rowid
        JOIN technical_articles a ON a.id=c.article_id
         WHERE technical_chunk_fts MATCH ? AND a.status='published' AND a.deleted_at IS NULL AND
          (?=1 OR (a.vehicle_make='' AND a.vehicle_model='' AND
            a.year_from IS NULL AND a.year_to IS NULL AND a.engine_code=''))
         LIMIT 100""", (match, int(vehicle is not None))).fetchall() if tokens else []
    lexical_rank = {}
    for row in [*rows, *doc_rows]:
        lexical_rank.setdefault(row["id"], len(lexical_rank))
    vector_hits = search_vectors(db, question, "technical_chunk")
    semantic_chunks = {}
    for chunk_id, _score in vector_hits:
        hit = db.execute(f"""SELECT {article_columns},c.id AS matched_chunk
            FROM technical_chunks c JOIN technical_articles a ON a.id=c.article_id
            WHERE c.id=? AND a.status='published' AND a.deleted_at IS NULL""", (chunk_id,)).fetchone()
        if hit and hit["id"] not in semantic_chunks:
            semantic_chunks[hit["id"]] = chunk_id
            rows.append(hit)
    results = []
    seen = set()
    for row in [*rows, *doc_rows]:
        article = dict(row)
        if article["id"] in seen or not _applies(article, vehicle):
            continue
        title_match = any(token in _fold(f"{row['title']} {row['symptoms']}").split()
                          for token in tokens)
        excerpts = [dict(hit) for hit in db.execute("""SELECT c.id,c.chunk_index,c.content
             FROM technical_chunk_fts f JOIN technical_chunks c ON c.id=f.rowid
             WHERE technical_chunk_fts MATCH ? AND c.article_id=?
             ORDER BY bm25(technical_chunk_fts) LIMIT 2""", (match, article["id"]))] if tokens else []
        semantic_chunk = semantic_chunks.get(article["id"])
        if semantic_chunk and not any(hit["id"] == semantic_chunk for hit in excerpts):
            excerpt = db.execute("""SELECT id,chunk_index,content FROM technical_chunks
                WHERE id=? AND article_id=?""", (semantic_chunk, article["id"])).fetchone()
            if excerpt:
                excerpts = [dict(excerpt), *excerpts][:2]
        # Tránh một từ phổ thông trong tệp lạc đề kéo bài vào chat.
        doc_match = len(tokens) >= 2 and any(all(
            token in _fold(hit["content"]).split() for token in tokens[:2]) for hit in excerpts)
        if not title_match and not doc_match and not semantic_chunk:
            continue
        article["excerpts"] = excerpts
        results.append(article)
        seen.add(article["id"])
    # Hợp nhất thứ hạng FTS5 và vector; bài khớp cả hai được ưu tiên.
    semantic_rank = {article_id: rank for rank, article_id in enumerate(semantic_chunks)}
    results.sort(key=lambda article: -(
        (1 / (60 + lexical_rank[article["id"]]) if article["id"] in lexical_rank else 0) +
        (1 / (60 + semantic_rank[article["id"]]) if article["id"] in semantic_rank else 0)))
    return results[:max(1, min(limit, 5))]
