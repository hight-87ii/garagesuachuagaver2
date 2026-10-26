"""Kiểm tra bài đã lưu và truy xuất FTS5, không ghi database."""

from backend.database import connect
from backend.technical_knowledge import search_technical
from backend.technical_expansion_data import articles

QUESTIONS = [
    "Tại sao xe bị nóng máy?",
    "Xe kêu lọc cọc khi đi qua ổ gà cần kiểm tra gì?",
    "Đèn Check Engine nhấp nháy có nguy hiểm không?",
    "Vì sao phanh phát ra tiếng nghiến?",
    "Điều hòa ô tô không mát có thể do những nguyên nhân nào?",
]

with connect() as db:
    titles = [item.title for _, item in articles()]
    placeholders = ",".join("?" for _ in titles)
    imported = {row["id"] for row in db.execute(
        f"SELECT id FROM technical_articles WHERE deleted_at IS NULL AND title IN ({placeholders})", titles)}
    assert len(imported) == 100
    print("Status:", [tuple(row) for row in db.execute(
        "SELECT status,COUNT(*) FROM technical_articles WHERE deleted_at IS NULL GROUP BY status")])
    chunks = db.execute(f"SELECT COUNT(*) FROM technical_chunks WHERE article_id IN ({','.join('?' for _ in imported)})",
                        tuple(imported)).fetchone()[0]
    print("New chunks:", chunks)
    assert chunks == 100
    expected_titles = ("Động cơ nóng bất thường hoặc kim nhiệt lên cao",
                       "Tiếng lọc cọc ở gầm khi chạy qua đường xấu",
                       "Đèn kiểm tra động cơ sáng hoặc nhấp nháy",
                       "Phanh kêu rít hoặc tiếng nghiến khi đạp phanh",
                       "Điều hòa xe không mát hoặc lúc lạnh lúc nóng")
    for question, expected_title in zip(QUESTIONS, expected_titles):
        hits = search_technical(db, question)
        print(question, "->", [(row["id"], row["title"], row["source_name"]) for row in hits])
        assert hits and hits[0]["title"] == expected_title and all(row["id"] not in imported for row in hits), question
    for term in ("EVAP", "dàn lạnh", '"freeze frame"'):
        raw = [tuple(row) for row in db.execute("""SELECT a.id,a.title,a.status FROM technical_chunk_fts f
            JOIN technical_chunks c ON c.id=f.rowid JOIN technical_articles a ON a.id=c.article_id
            WHERE technical_chunk_fts MATCH ? ORDER BY a.id DESC LIMIT 4""", (term,))]
        print("Internal index:", term, "->", raw)
        assert raw and any(row[0] in imported and row[2] == "draft" for row in raw)
