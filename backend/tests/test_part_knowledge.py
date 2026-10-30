"""Hybrid part knowledge keeps embeddings technical and business facts live."""

import json

from backend import database
from backend.ai_service import ai_service
from backend.part_knowledge import (ensure_part_knowledge_schema, process_part_index_job,
                                    search_part_knowledge, sync_part_knowledge)
from backend.tests.test_conversations import API, chat_env, conversation, headers, say


def test_incremental_part_vector_excludes_business_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "part-knowledge.db")
    database.init_db()
    with database.connect() as db:
        part_id = db.execute("""INSERT INTO parts(code,name,category,compatible,unit,cost_price,
            sell_price,stock,min_stock,supplier,technical_description,technical_specs,
            usage_instructions,usage_requirements,active)
            VALUES('OIL-FLT-01','Lọc dầu động cơ','Lọc','Toyota Vios','cái',50000,
            90000,7,2,'Nhà cung cấp bí mật','Lọc cặn trong dầu động cơ',
            'Ren M20, vật liệu giấy lọc','Bôi dầu gioăng trước khi lắp',
            'Dùng đúng mã theo tài liệu xe',1)""").lastrowid
        assert sync_part_knowledge(db, part_id) is True
        document = db.execute("SELECT * FROM part_knowledge_documents WHERE part_id=?",
                              (part_id,)).fetchone()
        assert "Lọc cặn" in document["content"] and "Ren M20" in document["content"]
        for forbidden in ("90000", "50000", "Nhà cung cấp bí mật", "Toyota Vios", "stock"):
            assert forbidden not in document["content"]
        db.commit()

    assert process_part_index_job(part_id, model="fake", embed=lambda text, model: [1.0, 0.0])
    with database.connect() as db:
        vector = db.execute("""SELECT * FROM knowledge_vectors
            WHERE source_type='part_catalog' AND source_id=?""", (part_id,)).fetchone()
        assert vector and vector["dimensions"] == 2
        old_hash = vector["content_hash"]
        # Stock is live DB data and must not invalidate the technical vector.
        db.execute("UPDATE parts SET stock=99 WHERE id=?", (part_id,))
        assert sync_part_knowledge(db, part_id) is False
        assert db.execute("SELECT content_hash FROM knowledge_vectors WHERE source_id=? AND source_type='part_catalog'",
                          (part_id,)).fetchone()[0] == old_hash
        # A technical edit invalidates only this part and queues one incremental job.
        db.execute("UPDATE parts SET technical_specs='Ren M22' WHERE id=?", (part_id,))
        assert sync_part_knowledge(db, part_id) is True
        assert not db.execute("SELECT 1 FROM knowledge_vectors WHERE source_id=? AND source_type='part_catalog'",
                              (part_id,)).fetchone()
        assert db.execute("SELECT status FROM part_knowledge_index_jobs WHERE part_id=?",
                          (part_id,)).fetchone()[0] == "pending"
        db.commit()


def test_cli_schema_bootstrap_runs_migration_without_fastapi_lifespan(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "cli-bootstrap.db")
    executed = ensure_part_knowledge_schema()
    assert "032_hybrid_part_knowledge" in executed
    with database.connect() as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                          "AND name='part_knowledge_index_jobs'").fetchone()


def test_search_returns_live_authorized_database_fields_and_deactivation(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "part-search.db")
    database.init_db()
    with database.connect() as db:
        part_id = db.execute("""INSERT INTO parts(code,name,category,unit,sell_price,stock,supplier,
            technical_description,technical_specs,active)
            VALUES('SPARK-IR','Bugi iridium','Động cơ','cái',250000,4,'NCC A',
            'Tạo tia lửa đốt hỗn hợp','Khe hở theo tài liệu nhà sản xuất',1)""").lastrowid
        db.execute("INSERT INTO part_price_approvals(part_id,approved_sell_price,approved_by,source) "
                   "VALUES(?,?,(SELECT id FROM users WHERE role='Admin' LIMIT 1),'Test')",
                   (part_id, 250000))
        sync_part_knowledge(db, part_id)
        db.commit()
        customer = search_part_knowledge(db, "Bugi iridium dùng để làm gì?",
                                         {"role": "Khách hàng"})
        assert customer[0]["id"] == part_id and "stock" not in customer[0]
        manager = search_part_knowledge(db, "Thông số, giá, tồn kho và nhà cung cấp bugi iridium",
                                        {"role": "Quản lý"})
        assert manager[0]["stock"] == 4 and manager[0]["supplier"] == "NCC A"
        assert manager[0]["approved_sell_price"] == 250000
        db.execute("UPDATE parts SET active=0 WHERE id=?", (part_id,))
        db.commit()
        assert not db.execute("SELECT 1 FROM part_knowledge_documents WHERE part_id=?",
                              (part_id,)).fetchone()
        assert search_part_knowledge(db, "Bugi iridium", {"role": "Quản lý"}) == []


def test_both_chat_apis_reread_part_after_rag_and_hide_private_inventory(chat_env, monkeypatch):
    client, _ = chat_env
    auth = headers(client)
    with database.connect() as db:
        part_id = db.execute("""INSERT INTO parts(code,name,category,unit,sell_price,stock,supplier,
            technical_description,technical_specs,usage_instructions,active)
            VALUES('SENSOR-O2-X','Cảm biến oxy X','Điện động cơ','cái',850000,9,'NCC riêng',
            'Đo lượng oxy trong khí xả','Điện áp theo tài liệu nhà sản xuất',
            'Kiểm tra giắc điện trước khi tháo',1)""").lastrowid
        sync_part_knowledge(db, part_id)
        db.commit()

    payloads = []
    monkeypatch.setattr(ai_service, "analyze_chat_question", lambda *a: {
        "intent": "technical_explanation", "topic": "part_catalog", "entities": {},
        "needs_database": False, "needs_rag": True, "needs_general_knowledge": False,
        "search_query": "cảm biến oxy", "clarification_question": None,
    })
    def model(messages):
        payload = json.loads(messages[-1]["content"])
        payloads.append(payload)
        item = payload["verified_database"][0]
        return f"{item['name']} ({item['code']}) dùng để đo oxy trong khí xả."
    monkeypatch.setattr(ai_service, "_chat", model)
    question = "Cảm biến oxy X dùng để làm gì?"
    legacy = client.post(f"{API}/ai/assistant/chat", headers=auth,
                         json={"question": question}).json()
    conv = conversation(client, auth, None, "part-knowledge-chat")
    persistent = say(client, auth, conv, question, "part-knowledge-chat-1")["result"]
    for result in (legacy, persistent):
        assert "SENSOR-O2-X" in result["result"]
        assert [(source["type"], source["id"]) for source in result["sources"]] == [
            ("part_knowledge", part_id)]
    assert len(payloads) == 2
    for payload in payloads:
        item = payload["verified_database"][0]
        assert item["id"] == part_id
        assert "stock" not in item and "supplier" not in item and "approved_sell_price" not in item


def test_part_crud_queues_only_incremental_technical_changes(chat_env, monkeypatch):
    client, _ = chat_env
    manager = headers(client, "manager@garage.vn", "Manager@123")
    indexed = []
    monkeypatch.setattr("backend.api.v1.parts.process_part_index_job",
                        lambda part_id: indexed.append(part_id) or True)
    created = client.post(f"{API}/parts", headers=manager, json={
        "code": "HYBRID-CRUD-1", "name": "Lọc nhiên liệu hybrid", "category": "Lọc",
        "unit": "cái", "stock": 2, "supplier": "NCC không embedding",
        "technical_description": "Giữ cặn trong nhiên liệu",
        "technical_specs": "Đầu nối theo tài liệu xe",
        "usage_instructions": "Xả áp suất trước khi tháo",
    })
    assert created.status_code == 201, created.text
    part_id = created.json()["id"]
    assert indexed == [part_id]
    with database.connect() as db:
        first = db.execute("SELECT content_hash,content FROM part_knowledge_documents WHERE part_id=?",
                           (part_id,)).fetchone()
        assert "Giữ cặn" in first["content"] and "NCC không embedding" not in first["content"]

    stock = client.post(f"{API}/parts/{part_id}/stock", headers=manager,
                        json={"amount": 3})
    assert stock.status_code == 200 and indexed == [part_id]
    with database.connect() as db:
        assert db.execute("SELECT content_hash FROM part_knowledge_documents WHERE part_id=?",
                          (part_id,)).fetchone()[0] == first["content_hash"]

    updated = client.patch(f"{API}/parts/{part_id}", headers=manager,
                           json={"technical_specs": "Đầu nối phiên bản B"})
    assert updated.status_code == 200 and indexed == [part_id, part_id]
    with database.connect() as db:
        assert "phiên bản B" in db.execute(
            "SELECT content FROM part_knowledge_documents WHERE part_id=?", (part_id,)).fetchone()[0]
    deleted = client.delete(f"{API}/parts/{part_id}", headers=manager)
    assert deleted.status_code == 200
    with database.connect() as db:
        assert not db.execute("SELECT 1 FROM part_knowledge_documents WHERE part_id=?",
                              (part_id,)).fetchone()
