"""Tra cứu ngữ nghĩa cục bộ trên vector đã lập chỉ mục, không thay thế lọc quyền/nguồn."""

from array import array
import math
import os
import sys
from urllib import error

from .vector_index import embed_local


def search_vectors(db, question: str, source_type: str, *, model: str | None = None,
                   embed=embed_local, limit: int = 30) -> list[tuple[int, float]]:
    """Trả ID nguồn theo cosine; chỉ quét vector của nguồn vẫn được xuất bản."""
    if source_type not in ("technical_chunk", "repair_case", "part_catalog") or not question.strip():
        return []
    model = model or os.getenv("LOCAL_EMBED_MODEL", "bge-m3")
    if source_type == "technical_chunk":
        rows = db.execute("""SELECT v.source_id,v.dimensions,v.embedding
            FROM knowledge_vectors v JOIN technical_chunks c ON c.id=v.source_id
            JOIN technical_articles a ON a.id=c.article_id
            WHERE v.model=? AND v.source_type='technical_chunk'
              AND a.status='published' AND a.deleted_at IS NULL""", (model,)).fetchall()
    elif source_type == "repair_case":
        rows = db.execute("""SELECT v.source_id,v.dimensions,v.embedding
            FROM knowledge_vectors v JOIN repair_knowledge_cases c ON c.id=v.source_id
            WHERE v.model=? AND v.source_type='repair_case' AND c.status='published'""",
                           (model,)).fetchall()
    else:
        rows = db.execute("""SELECT v.source_id,v.dimensions,v.embedding
            FROM knowledge_vectors v JOIN part_knowledge_documents d ON d.part_id=v.source_id
            JOIN parts p ON p.id=d.part_id
            WHERE v.model=? AND v.source_type='part_catalog' AND p.active=1""",
                          (model,)).fetchall()
    if not rows:
        return []
    try:
        query = embed(question, model, timeout=15) if embed is embed_local else embed(question, model)
    except (error.URLError, TimeoutError, OSError, ValueError):
        return []  # FTS5 vẫn có thể phục vụ khi Ollama tạm ngừng.
    if not query or not all(isinstance(x, (float, int)) and math.isfinite(x) for x in query):
        return []
    magnitude = math.sqrt(sum(x * x for x in query))
    if not magnitude:
        return []
    matches = []
    for row in rows:
        if row["dimensions"] != len(query) or len(row["embedding"]) != 4 * len(query):
            continue
        vector = array("f")
        vector.frombytes(row["embedding"])
        if sys.byteorder != "little":
            vector.byteswap()
        length = math.sqrt(sum(x * x for x in vector))
        if not length:
            continue
        score = sum(a * b for a, b in zip(query, vector)) / (magnitude * length)
        if math.isfinite(score) and score >= 0.60:
            matches.append((row["source_id"], score))
    return sorted(matches, key=lambda hit: hit[1], reverse=True)[:limit]
