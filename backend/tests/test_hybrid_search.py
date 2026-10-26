import sqlite3
from urllib.error import URLError

from backend.migrations import migration_026
from backend.vector_index import index_sources
from backend.vector_search import search_vectors
from backend.technical_knowledge import search_technical
from backend.repair_knowledge import search_repair_cases
from backend.api.v1.ai import _is_technical_question, _technical_references


def sample_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE technical_articles (id INTEGER PRIMARY KEY, title TEXT, symptoms TEXT,
            content TEXT, safety TEXT, source_name TEXT, source_url TEXT, document_version TEXT,
            safety_level TEXT, vehicle_make TEXT DEFAULT '', vehicle_model TEXT DEFAULT '',
            year_from INTEGER, year_to INTEGER, engine_code TEXT DEFAULT '', updated_at TEXT,
            status TEXT, deleted_at TEXT);
        CREATE TABLE technical_chunks (id INTEGER PRIMARY KEY, article_id INTEGER,
            chunk_index INTEGER, content TEXT);
        CREATE VIRTUAL TABLE technical_fts USING fts5(title,symptoms,content);
        CREATE VIRTUAL TABLE technical_chunk_fts USING fts5(content);
        CREATE TABLE repair_knowledge_cases (id INTEGER PRIMARY KEY, status TEXT,
            vehicle_make TEXT, vehicle_model TEXT, vehicle_year INTEGER, engine_code TEXT,
            customer_symptoms TEXT, inspection_findings TEXT, confirmed_cause TEXT,
            work_done TEXT, outcome TEXT, published_at TEXT, updated_at TEXT);
        CREATE VIRTUAL TABLE repair_case_fts USING fts5(customer_symptoms,inspection_findings,
            confirmed_cause,work_done,outcome);
        INSERT INTO technical_articles VALUES
            (1,'Phanh','phanh ướt','Kiểm tra phanh','', 'Tài liệu garage','','','medium',
             '','',NULL,NULL,'','2026-01-01','published',NULL),
            (2,'Xe khác','nước mưa','Không dùng sai xe','', 'Tài liệu garage','','','medium',
             'Toyota','Vios',2020,2020,'','2026-01-01','published',NULL),
            (3,'Bản nháp','mưa','Không công bố','', 'Tài liệu garage','','','medium',
             '','',NULL,NULL,'','2026-01-01','draft',NULL);
        INSERT INTO technical_chunks VALUES (11,1,1,'Kiểm tra hệ thống phanh sau khi trời mưa'),
            (12,2,1,'Toyota Vios dùng sau mưa'), (13,3,1,'Tài liệu chưa duyệt');
        INSERT INTO technical_fts(rowid,title,symptoms,content)
            SELECT id,title,symptoms,content FROM technical_articles;
        INSERT INTO technical_chunk_fts(rowid,content) SELECT id,content FROM technical_chunks;
        INSERT INTO repair_knowledge_cases VALUES
            (5,'published','Toyota','Vios',2020,'','Đề máy sau mưa','Kiểm tra',
             'Nước vào','Đã sửa','Ổn định','2026-01-01','2026-01-01');
        INSERT INTO repair_case_fts(rowid,customer_symptoms,inspection_findings,
            confirmed_cause,work_done,outcome)
            SELECT id,customer_symptoms,inspection_findings,confirmed_cause,work_done,outcome
            FROM repair_knowledge_cases;
    """)
    migration_026(db)
    index_sources(db, "bge-m3", lambda text, model: [1.0, 0.0])
    return db


def test_semantic_retrieval_filters_status_vehicle_and_excerpts(monkeypatch):
    db = sample_db()
    monkeypatch.setattr("backend.technical_knowledge.search_vectors",
                        lambda db, q, kind: search_vectors(db, q, kind,
                                                           embed=lambda text, model: [1.0, 0.0]))
    monkeypatch.setattr("backend.repair_knowledge.search_vectors",
                        lambda db, q, kind: search_vectors(db, q, kind,
                                                           embed=lambda text, model: [1.0, 0.0]))
    hits = search_technical(db, "Sau cơn giông xe có nguy hiểm không?")
    assert [hit["id"] for hit in hits] == [1]
    assert hits[0]["excerpts"][0]["id"] == 11
    assert search_repair_cases(db, "Sau cơn giông không khởi động?", None) == []
    vehicle = {"make": "Toyota", "model": "Vios", "year": 2020, "engine_code": ""}
    assert {hit["id"] for hit in search_technical(db, "Sau cơn giông?", vehicle=vehicle)} == {1, 2}
    assert [hit["id"] for hit in search_repair_cases(db, "Sau cơn giông?", vehicle)] == [5]
    assert search_repair_cases(db, "Sau cơn giông?", {**vehicle, "model": "Camry"}) == []
    db.close()


def test_vector_failure_and_dimension_mismatch_leave_fts_available(monkeypatch):
    db = sample_db()
    assert search_vectors(db, "mưa", "technical_chunk", embed=lambda q, m: [1.0]) == []
    assert search_vectors(db, "mưa", "technical_chunk", embed=lambda q, m: (_ for _ in ()).throw(
        URLError("offline"))) == []
    monkeypatch.setattr("backend.technical_knowledge.search_vectors", lambda *args: [])
    assert search_technical(db, "phanh ướt")[0]["id"] == 1
    db.close()


def test_broad_weather_question_routes_to_approved_technical_sources(monkeypatch):
    db = sample_db()
    monkeypatch.setattr("backend.technical_knowledge.search_vectors", lambda *args: [])
    monkeypatch.setattr("backend.repair_knowledge.search_vectors", lambda *args: [])
    question = "Trời mưa thì xe thường gặp vấn đề gì?"
    assert _is_technical_question(question)
    articles, sources = _technical_references(db, question)
    assert [article["id"] for article in articles] == [1]
    assert sources[0]["type"] == "technical_article"
    assert sources[0]["id"] == 1
    # Câu hỏi nghiệp vụ hoặc cảnh báo an toàn không được chuyển sang RAG.
    for excluded in ("Mua phụ tùng cho xe giá bao nhiêu?", "Lịch sử xe khi trời mưa?",
                     "Xe bị ngập nước sau mưa thì làm sao?"):
        assert _technical_references(db, excluded) == ([], [])
    assert not _is_technical_question("Garage mở cửa lúc mấy giờ?")
    db.close()
