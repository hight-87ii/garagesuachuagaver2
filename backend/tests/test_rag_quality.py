"""Tập câu hỏi cố định để đo định tuyến và độ chính xác truy xuất (không gọi LLM)."""

import json

import pytest

from backend.ai_service import AIService
from backend.api.v1.ai import _general_knowledge_question, _is_technical_question, _technical_references, _technical_route
from backend.technical_knowledge import search_technical
from backend.tests.test_hybrid_search import sample_db


@pytest.fixture
def corpus(monkeypatch):
    db = sample_db()
    # Đánh giá FTS/định tuyến độc lập với Ollama: vector đã được kiểm ở test_hybrid_search.
    monkeypatch.setattr("backend.technical_knowledge.search_vectors", lambda *a, **kw: [])
    monkeypatch.setattr("backend.repair_knowledge.search_vectors", lambda *a, **kw: [])
    entries = [
        (10, "Đèn xi nhan chập chờn", "đèn báo rẽ lúc sáng lúc không", "Kiểm tra đèn và mạch theo xe."),
        (11, "Đèn nội thất hỏng", "đèn trần không sáng", "Kiểm tra đèn trong cabin."),
        (12, "Lốp mòn không đều", "lốp mòn lệch một bên", "Đo áp suất và kiểm tra độ mòn."),
        (13, "Động cơ quá nhiệt", "máy nóng bất thường", "Dừng xe an toàn và kiểm tra nhiệt độ."),
        (14, "Turbo lag", "độ trễ tăng áp", "Giải thích độ trễ của bộ tăng áp."),
    ]
    for aid, title, symptoms, content in entries:
        db.execute("""INSERT INTO technical_articles(id,title,symptoms,content,safety,source_name,
            source_url,document_version,safety_level,updated_at,status)
            VALUES(?,?,?,?,'','Nguồn đã duyệt','','','medium','2026-01-01','published')""",
            (aid, title, symptoms, content))
        db.execute("INSERT INTO technical_fts(rowid,title,symptoms,content) VALUES(?,?,?,?)",
                   (aid, title, symptoms, content))
        db.execute("INSERT INTO technical_chunks(id,article_id,chunk_index,content) VALUES(?,?,1,?)",
                   (aid * 10, aid, content))
        db.execute("INSERT INTO technical_chunk_fts(rowid,content) VALUES(?,?)", (aid * 10, content))
    yield db
    db.close()


@pytest.mark.parametrize("question,expected", [
    ("Nguyên nhân si nhan lúc được lúc không?", 10),
    ("Lốp xe bị ăn lệch một bên", 12),
    ("Turbo lag là gì?", 14),
])
def test_retrieval_variants_find_right_approved_article(corpus, question, expected):
    articles, sources = _technical_references(corpus, question, semantic_technical=True)
    assert articles and articles[0]["id"] == expected
    assert sources[0]["id"] == expected


def test_short_brake_noise_does_not_cite_unrelated_wet_brake(corpus):
    articles, sources = _technical_references(corpus, "phanh kêu")
    assert articles == [] and sources == []


def test_hot_car_without_measured_temperature_needs_safe_clarification():
    _, clarification, _ = _technical_route("Xe nóng bất thường")
    assert clarification is not None and clarification.status == "clarification"
    assert "nhiệt" in clarification.content.lower()


def test_colloquial_tire_wear_routes_to_technical_retrieval(corpus):
    question = "Lốp xe bị ăn lệch một bên"
    assert _is_technical_question(question)
    articles, _ = _technical_references(corpus, question)
    assert articles and articles[0]["id"] == 12


@pytest.mark.parametrize("question", [
    "Lốp mòn đi có cảm giác rít rít",
    "Đi tốc độ cao bị trượt, lốp có vẻ mất độ bám",
])
def test_tire_noise_and_high_speed_slip_route_to_rag(corpus, question):
    assert _is_technical_question(question)
    articles, _ = _technical_references(corpus, question)
    assert articles and articles[0]["id"] == 12


def test_tire_price_routes_to_catalog_not_rag(corpus):
    assert not _is_technical_question("Giá lốp 205/55R16 bao nhiêu?")
    assert _technical_references(corpus, "Giá lốp 205/55R16 bao nhiêu?") == ([], [])


def test_general_rain_driving_without_selected_vehicle_is_not_business():
    assert _general_knowledge_question("Đi trời mưa cần chú ý gì?")


def test_rain_driving_does_not_cite_wet_brake_article(corpus):
    corpus.execute("""INSERT INTO technical_articles(id,title,symptoms,content,safety,source_name,
        source_url,document_version,safety_level,updated_at,status)
        VALUES(15,'Lái xe trời mưa an toàn','giảm tốc độ, giữ khoảng cách',
        'Giảm tốc độ và quan sát đường khi trời mưa.','','Nguồn đã duyệt','','',
        'medium','2026-01-01','published')""")
    corpus.execute("INSERT INTO technical_fts(rowid,title,symptoms,content) "
                   "VALUES(15,'Lái xe trời mưa an toàn','giảm tốc độ, giữ khoảng cách',"
                   "'Giảm tốc độ và quan sát đường khi trời mưa.')")
    for question in ("Đi trời mưa cần chú ý gì?", "Trời mưa lái xe thế nào?"):
        articles, _ = _technical_references(corpus, question, semantic_technical=True)
        assert [article["id"] for article in articles] == [15]


def test_ollama_receives_only_retrieved_source_metadata(monkeypatch, corpus):
    article = search_technical(corpus, "lốp mòn không đều")[0]
    assert article["id"] == 12
    article["excerpts"] = [{"id": 120, "content": "Đo áp suất và kiểm tra độ mòn."}]
    captured = []
    service = AIService(api_key="mock")
    monkeypatch.setattr(service, "_chat", lambda messages: captured.extend(messages) or
                        "Tài liệu nêu hướng kiểm tra tham khảo, không khẳng định xe này bị hỏng.")
    result = service.answer_technical("Lốp mòn không đều?", [article], "Khách hàng")
    context = json.loads(captured[1]["content"])["technical_articles"][0]
    assert result.status == "success" and context["source_id"] == 12
    assert context["source_name"] == "Nguồn đã duyệt"
    assert context["chunk_ids"] == [120]
    assert "không tạo URL" in captured[0]["content"]


def test_indicator_follow_up_uses_topic_for_retrieval(corpus):
    question, clarification, _ = _technical_route("nguyên nhân là gì?", [
        {"role": "user", "text": "xi nhan chập chờn"},
        {"role": "assistant", "text": "Xi nhan bên nào bị chập chờn?"},
    ])
    assert clarification is None and "xi nhan chập chờn" in question.lower()
    articles, _ = _technical_references(corpus, question, semantic_technical=True)
    assert articles and articles[0]["id"] == 10


def test_replacement_price_does_not_use_technical_document_as_quote(corpus):
    question = "Lốp xe bị ăn lệch, thay hết bao nhiêu?"
    assert not _general_knowledge_question(question)
    assert _technical_references(corpus, question) == ([], [])
