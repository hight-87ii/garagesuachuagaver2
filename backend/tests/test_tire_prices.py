"""Tire price answers use approved catalog snapshots, never demo/RAG prices."""

import pytest

from backend import database
from backend.ai_service import AIService, ai_service
from backend.inventory_query import answer_part_price_question
from backend.tests.test_conversations import API, chat_env, conversation, headers, say


def add_tire(*, code="TIRE-205", name="Lốp Michelin 205/55R16", price=1900000,
             approved=True, active=1, supplier="Nhà phân phối"):
    with database.connect() as db:
        part_id = db.execute(
            """INSERT INTO parts(code,name,category,compatible,unit,cost_price,sell_price,
               stock,min_stock,supplier,active) VALUES(?,?,'Lốp','','chiếc',0,?,0,0,?,?)""",
            (code, name, price, supplier, active),
        ).lastrowid
        if approved:
            admin_id = db.execute("SELECT id FROM users WHERE role='Admin' LIMIT 1").fetchone()[0]
            db.execute("INSERT INTO part_price_approvals(part_id,approved_sell_price,approved_by,source) "
                       "VALUES(?,?,?,'Bảng giá được duyệt')", (part_id, price, admin_id))
        db.commit()
    return part_id


def add_brake(*, code="BRAKE-PAD", name="Má phanh trước", price=850000):
    with database.connect() as db:
        part_id = db.execute(
            """INSERT INTO parts(code,name,category,compatible,unit,cost_price,sell_price,
               stock,min_stock,supplier,active) VALUES(?,?,'Hệ thống phanh','','bộ',0,?,2,1,?,1)""",
            (code, name, price, "Nhà phân phối"),
        ).lastrowid
        admin_id = db.execute("SELECT id FROM users WHERE role='Admin' LIMIT 1").fetchone()[0]
        db.execute("INSERT INTO part_price_approvals(part_id,approved_sell_price,approved_by,source) "
                   "VALUES(?,?,?,'Bảng giá được duyệt')", (part_id, price, admin_id))
        db.commit()
    return part_id


@pytest.mark.parametrize("question", ["Giá lốp hiện tại bao nhiêu?", "Lốp 205/55R16 giá bao nhiêu?",
                                       "Lốp Michelin bao nhiêu tiền?", "Giá vỏ xe ô tô hiện tại?"])
def test_approved_tire_price_on_both_apis(chat_env, question):
    client, vehicle_id = chat_env
    part_id = add_tire()
    auth = headers(client)
    old = client.post(f"{API}/ai/assistant/chat", headers=auth, json={"question": question})
    new = say(client, auth, conversation(client, auth, vehicle_id, "tire-" + question),
              question, "tire-price-1")["result"]
    assert old.status_code == 200, old.text
    for result in (old.json(), new):
        assert "1.900.000" in result["result"]
        assert "TIRE-205" in result["result"]
        assert result["sources"] == [{"type": "part", "id": part_id,
                                      "label": "Danh mục phụ tùng: Lốp Michelin 205/55R16 (TIRE-205)"}]


def test_no_tire_does_not_match_suspension_category(chat_env):
    client, _ = chat_env
    response = client.post(f"{API}/ai/assistant/chat", headers=headers(client),
                           json={"question": "Giá lốp hiện tại bao nhiêu?"})
    assert response.status_code == 200
    assert response.json()["status"] == "no_data"
    assert response.json()["source_count"] == 0
    assert "Giảm xóc" not in response.json()["result"]


def test_generic_assistant_never_falls_back_to_bearings_for_tire_price():
    demo = {"id": 1, "code": "DEMO-BEAR-FRA", "name": "Bi moay-ơ trước - Ford Ranger (mẫu)",
            "category": "Gầm", "compatible": "Gợi ý tra cứu Ford Ranger",
            "sell_price": 1280000, "unit": "cái", "stock": 5}
    service = AIService(api_key="")
    for question in ("Giá lốp?", "Giá lốp phù hợp xe tôi?", "Giá phụ kiện động cơ?"):
        result = service.answer_assistant(question,
            {"vehicle": {"make": "Ford", "model": "Ranger", "year": 2022}},
            [demo], [], "Khách hàng")
        assert result.status == "no_data"
        assert "DEMO-BEAR" not in result.content and "1.280.000" not in result.content


def test_price_lookup_without_approval_table_never_discloses_demo_price(monkeypatch):
    monkeypatch.setenv("CATALOG_MODE", "production")
    import sqlite3
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE parts (id INTEGER PRIMARY KEY,code TEXT,name TEXT,category TEXT,
        compatible TEXT,unit TEXT,sell_price INTEGER,supplier TEXT,active INTEGER)""")
    db.execute("""INSERT INTO parts VALUES (1,'DEMO-TIRE','Lốp 205/55R16 (mẫu)',
        'Lốp','','chiếc',1900000,'',1)""")
    result, sources = answer_part_price_question(db, "Giá lốp 205/55R16?", {"role": "Khách hàng"})
    assert result.status == "no_data" and sources == []
    assert "1.900.000" not in result.content


def test_brake_price_uses_category_from_backend_and_ollama_payload(chat_env, monkeypatch):
    import json
    client, _ = chat_env
    part_id = add_brake()
    prompts = []
    monkeypatch.setattr(ai_service, "provider", "ollama")
    def model(messages):
        payload = json.loads(messages[1]["content"])
        prompts.append(payload)
        return (json.dumps({"intent": "part_price", "topic": "phanh", "keywords": ["phanh"],
                            "part_code": None, "tire_size": None, "brand": None,
                            "vehicle_make": None, "vehicle_model": None, "needs_database": True,
                            "needs_rag": False, "needs_general_knowledge": False,
                            "required_data": ["giá bán"], "clarification_question": None})
                if len(prompts) == 1 else "Mình đã tra danh mục để bạn tham khảo.")
    monkeypatch.setattr(ai_service, "_chat", model)
    response = client.post(f"{API}/ai/assistant/chat", headers=headers(client),
                           json={"question": "Giá phanh bao nhiêu?"}).json()
    assert response["status"] == "fallback"
    assert "850.000" in response["result"] and "BRAKE-PAD" in response["result"]
    assert response["sources"] == [{"type": "part", "id": part_id,
                                    "label": "Danh mục phụ tùng: Má phanh trước (BRAKE-PAD)"}]
    assert prompts[1]["verified_database"][0]["code"] == "BRAKE-PAD"


def test_demo_mode_exposes_only_demo_price_with_explicit_label(chat_env, monkeypatch):
    client, _ = chat_env
    monkeypatch.setenv("CATALOG_MODE", "demo")
    with database.connect() as db:
        db.execute("""INSERT INTO parts(code,name,category,compatible,unit,cost_price,sell_price,
            stock,min_stock,supplier,active) VALUES('DEMO-BRAKE','Má phanh DEMO',
            'Hệ thống phanh','','bộ',0,700000,2,1,'Danh mục mẫu',1)""")
        db.commit()
    response = client.post(f"{API}/ai/assistant/chat", headers=headers(client),
                           json={"question": "Giá phanh?"}).json()
    assert response["status"] == "fallback"
    assert "700.000" in response["result"]
    assert "DEMO" in response["result"] and "chưa được garage phê duyệt" in response["result"]


def test_both_chat_apis_give_ollama_only_approved_prices(monkeypatch, chat_env):
    import json
    client, vehicle_id = chat_env
    add_tire()
    calls = []
    monkeypatch.setattr(ai_service, "provider", "ollama")
    def narrate(messages):
        payload = json.loads(messages[1]["content"])
        calls.append(payload)
        return "Mình đã tra danh mục để bạn tham khảo."
    monkeypatch.setattr(ai_service, "_chat", narrate)
    auth = headers(client)
    old = client.post(f"{API}/ai/assistant/chat", headers=auth,
                      json={"question": "Giá lốp 205/55R16?"}).json()
    new = say(client, auth, conversation(client, auth, vehicle_id),
              "Giá lốp 205/55R16?", "narrated-tire-price")["result"]
    assert len(calls) == 4  # phân tích trước, diễn đạt sau cho mỗi API
    for payload, reply in zip((calls[1], calls[3]), (old, new)):
        assert payload["verified_results"] is True
        assert "TIRE-205" in payload["catalog_sources"][0]
        assert "1.900.000" in payload["backend_answer"]
        assert payload["verified_database"][0]["price_value"] == 1900000
        assert "cost_price" not in json.dumps(payload) and "stock" not in json.dumps(payload)
        assert reply["result"].startswith("Mình đã tra danh mục để bạn tham khảo.")
        assert "1.900.000" in reply["result"] and "TIRE-205" in reply["result"]
        assert reply["source_count"] == 1


def test_ollama_cannot_add_price_or_fitment(monkeypatch):
    from backend.ai_service import AIResult
    service = AIService(provider="ollama")
    backend = AIResult("Lốp (TIRE-205): 1.900.000 ₫/chiếc. Chưa xác nhận lắp vừa.",
                       "fallback", "local", service.model)
    sources = [{"type": "part", "id": 1}]
    for response in ("Giá mới 900.000 ₫", "Đang có hàng và lắp vừa xe bạn.",
                     "Báo giá chính thức đã duyệt.",
                     "Lốp (TIRE-205): 1.900.000 ₫/chiếc. Phí khác 8.000.000 ₫."):
        monkeypatch.setattr(service, "_chat", lambda messages: response)
        assert service.narrate_approved_part_prices("Giá lốp?", backend, sources) is backend
    missing = AIResult("Chưa có giá được duyệt.", "no_data", "local", service.model, True)
    assert service.narrate_approved_part_prices("Giá lốp?", missing, []) is missing


def test_unapproved_demo_and_changed_prices_are_not_disclosed(chat_env):
    client, vehicle_id = chat_env
    add_tire(code="DEMO-TIRE", name="Lốp Michelin 205/55R16 (mẫu)", price=1234567)
    add_tire(code="UNVERIFIED", name="Lốp Michelin 205/55R16", price=2345678, approved=False)
    changed_id = add_tire(code="CHANGED", name="Lốp Michelin 205/55R16", price=3456789)
    with database.connect() as db:
        db.execute("UPDATE parts SET sell_price=4567890 WHERE id=?", (changed_id,))
        db.commit()
    auth = headers(client)
    answer = say(client, auth, conversation(client, auth, vehicle_id),
                 "Giá lốp Michelin?", "unverified-price")["result"]
    assert answer["status"] == "no_data" and answer["source_count"] == 0
    for amount in ("1.234.567", "2.345.678", "4.567.890"):
        assert amount not in answer["result"]


def test_multiple_prices_and_replacement_not_a_quote(chat_env):
    client, vehicle_id = chat_env
    add_tire()
    add_tire(code="TIRE-ALT", name="Lốp Bridgestone 205/55R16", price=2100000)
    auth = headers(client)
    conv = conversation(client, auth, vehicle_id)
    listed = say(client, auth, conv, "Cho tôi xem giá các loại lốp", "list-tires")["result"]
    assert "1.900.000" in listed["result"] and "2.100.000" in listed["result"]
    replaced = say(client, auth, conv, "Thay lốp xe tôi hết bao nhiêu?", "replace-tire")["result"]
    assert "1.900.000" in replaced["result"]
    assert "Chưa thể tính tổng" in replaced["result"]
    assert "kích thước" in replaced["result"]


def test_size_filter_inactive_products_and_stock_permission(chat_env):
    client, _ = chat_env
    add_tire()
    add_tire(code="TIRE-OTHER", name="Lốp Bridgestone 195/65R15", price=1500000)
    add_tire(code="TIRE-INACTIVE", name="Lốp Michelin 205/55R16", price=900000, active=0)
    auth = headers(client)
    price = client.post(f"{API}/ai/assistant/chat", headers=auth,
                        json={"question": "Lốp 205/55R16 giá bao nhiêu?"}).json()
    assert "1.900.000" in price["result"]
    assert "TIRE-OTHER" not in price["result"] and "TIRE-INACTIVE" not in price["result"]
    denied = client.post(f"{API}/ai/assistant/chat", headers=auth,
                         json={"question": "Lốp 205/55R16 còn bao nhiêu trong kho?"}).json()
    assert denied["status"] == "denied" and denied["source_count"] == 0
    assert "1.900.000" not in denied["result"]


def test_approved_price_for_staff_and_missing_size(chat_env):
    client, _ = chat_env
    add_tire()
    manager = headers(client, "manager@garage.vn", "Manager@123")
    response = client.post(f"{API}/ai/assistant/chat", headers=manager,
                           json={"question": "Giá lốp 235/65R17 bao nhiêu?"})
    assert response.status_code == 200
    assert response.json()["status"] == "no_data"
    assert "1.900.000" not in response.json()["result"]
    found = client.post(f"{API}/ai/assistant/chat", headers=manager,
                        json={"question": "Giá lốp xe Toyota Vios?"}).json()
    assert "1.900.000" in found["result"]
    assert "Chưa thể xác nhận lốp phù hợp" in found["result"]
