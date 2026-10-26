import sqlite3

from backend.migrations import migration_026
from backend.vector_index import index_sources


def test_local_index_incremental_and_revoke():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE technical_articles (id INTEGER PRIMARY KEY, title TEXT, symptoms TEXT,
            status TEXT, deleted_at TEXT);
        CREATE TABLE technical_chunks (id INTEGER PRIMARY KEY, article_id INTEGER, content TEXT);
        CREATE TABLE repair_knowledge_cases (id INTEGER PRIMARY KEY, status TEXT,
            vehicle_make TEXT, vehicle_model TEXT, vehicle_year INTEGER, engine_code TEXT,
            customer_symptoms TEXT, inspection_findings TEXT, confirmed_cause TEXT,
            work_done TEXT, outcome TEXT);
        INSERT INTO technical_articles VALUES (1,'Phanh','phanh ướt','published',NULL);
        INSERT INTO technical_articles VALUES (2,'Bản nháp','không dùng','draft',NULL);
        INSERT INTO technical_chunks VALUES (11,1,'Kiểm tra phanh sau khi đi mưa');
        INSERT INTO technical_chunks VALUES (12,2,'Không được lập chỉ mục');
        INSERT INTO repair_knowledge_cases VALUES (5,'published','Toyota','Vios',2020,'',
            'Khó nổ sau mưa','Đã kiểm tra','Đã xác nhận','Đã sửa','Hoạt động bình thường');
        INSERT INTO repair_knowledge_cases VALUES (6,'draft','Toyota','Vios',2020,'',
            'Nháp riêng','', '', '', '');
    """)
    migration_026(db)
    calls = []

    def embed(text, model):
        calls.append((text, model))
        return [0.5, 0.25, 0.125]

    assert index_sources(db, "bge-m3", embed) == {"created": 2, "skipped": 0, "removed": 0}
    assert all("Không được lập" not in text and "Nháp riêng" not in text for text, _ in calls)
    assert index_sources(db, "bge-m3", embed) == {"created": 0, "skipped": 2, "removed": 0}
    assert len(calls) == 2
    row = db.execute("SELECT dimensions,length(embedding) AS size FROM knowledge_vectors LIMIT 1").fetchone()
    assert (row["dimensions"], row["size"]) == (3, 12)

    db.execute("UPDATE technical_articles SET status='draft' WHERE id=1")
    db.execute("UPDATE repair_knowledge_cases SET status='draft' WHERE id=5")
    assert db.execute("SELECT COUNT(*) FROM knowledge_vectors").fetchone()[0] == 0
    assert index_sources(db, "bge-m3", embed) == {"created": 0, "skipped": 0, "removed": 0}
    db.close()


def test_local_index_refreshes_changed_chunks_and_model():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE technical_articles (id INTEGER PRIMARY KEY, title TEXT, symptoms TEXT,
            status TEXT, deleted_at TEXT);
        CREATE TABLE technical_chunks (id INTEGER PRIMARY KEY, article_id INTEGER, content TEXT);
        CREATE TABLE repair_knowledge_cases (id INTEGER PRIMARY KEY, status TEXT,
            vehicle_make TEXT, vehicle_model TEXT, vehicle_year INTEGER, engine_code TEXT,
            customer_symptoms TEXT, inspection_findings TEXT, confirmed_cause TEXT,
            work_done TEXT, outcome TEXT);
        INSERT INTO technical_articles VALUES (1,'Tài liệu','triệu chứng','published',NULL);
        INSERT INTO technical_chunks VALUES (1,1,'Nội dung cũ');
    """)
    migration_026(db)
    embed = lambda text, model: [1.0, 0.0]
    assert index_sources(db, "bge-m3", embed)["created"] == 1
    db.execute("UPDATE technical_chunks SET content='Nội dung mới' WHERE id=1")
    assert db.execute("SELECT COUNT(*) FROM knowledge_vectors").fetchone()[0] == 0
    assert index_sources(db, "bge-m3", embed)["created"] == 1
    assert index_sources(db, "another-model", embed)["created"] == 1
    assert index_sources(db, "bge-m3", embed, rebuild=True)["created"] == 1
    db.close()
