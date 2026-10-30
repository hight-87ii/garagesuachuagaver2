"""Model chỉ gợi ý ý định; backend vẫn là nơi kiểm tra quyền và dữ kiện."""

import json

from backend.ai_service import ai_service
from backend.chat_pipeline import _battery_weak_signs_reply, _generic_oil_interval_reply
from backend.api.v1.ai import _catalog_service_reply
from backend.chat_intent import extract_tire_size, normalize_analysis, parse_analysis
from backend.inventory_query import (answer_catalog_parts_question, has_explicit_price_intent,
                                     is_part_price_question)
from backend.tests.test_conversations import API, chat_env, headers
from backend.tests.test_tire_prices import add_tire


def analysis(**overrides):
    value = {"intent": "tire_price", "topic": "lốp", "keywords": ["lốp"],
             "part_code": None, "tire_size": None, "brand": None,
             "vehicle_make": None, "vehicle_model": None, "needs_database": True,
             "needs_rag": False, "needs_general_knowledge": False,
             "required_data": [], "clarification_question": None}
    return json.dumps({**value, **overrides}, ensure_ascii=False)


def test_analysis_never_accepts_invented_product_data():
    value = parse_analysis(analysis(part_code="OEM-FAKE", tire_size="205/55R16",
                                    brand="Michelin", vehicle_make="Toyota"), "Giá lốp?")
    assert value["intent"] == "tire_price"
    assert all(value[field] is None for field in
               ("part_code", "tire_size", "brand", "vehicle_make"))
    assert parse_analysis('```json\n' + analysis() + '\n```', "Giá lốp?") is None
    assert parse_analysis(analysis(intent="SELECT * FROM parts"), "Giá lốp?") is None


def test_tire_size_is_normalized_and_components_are_backend_derived():
    for question, normalized in (("205/55R16 có ý nghĩa gì?", "205/55R16"),
                                 ("195/65 R15 là gì?", "195/65R15"),
                                 ("235/60r18 thông số ra sao?", "235/60R18")):
        size = extract_tire_size(question)
        assert size["normalized"] == normalized
        result = normalize_analysis(question, None)
        assert result["intent"] == "technical_explanation"
        assert result["topic"] == "tire_size"
        assert result["entities"]["tire_width_mm"] == int(normalized[:3])
        assert result["entities"]["rim_diameter_inch"] == int(normalized[-2:])


def test_current_tire_topic_overrides_previous_brake_topic():
    result = normalize_analysis("Lốp 205/55R16 có ý nghĩa gì?", {
        "intent": "technical_symptom", "topic": "brake", "needs_database": False,
        "needs_rag": True, "needs_general_knowledge": False,
    }, previous_topic="brake")
    assert result["topic"] == "tire_size"
    assert result["is_new_topic"] is True


def test_backend_policy_distinguishes_current_intents_without_model():
    cases = (
        ("Lốp 205/55R16 có ý nghĩa gì?", "technical_explanation", "tire_size"),
        ("Giá lốp 205/55R16 bao nhiêu?", "tire_price", "tire_price"),
        ("Lốp mòn lệch một bên có thể do đâu?", "technical_symptom", "tire_wear"),
        ("Nên chọn lốp nào?", "tire_compare", "tire_compare"),
        ("Khi nào cần thay dầu?", "maintenance_interval", "oil_change_interval"),
        ("Đèn Check Engine sáng màu vàng thì làm gì?", "technical_symptom", "check_engine"),
    )
    for question, intent, topic in cases:
        result = normalize_analysis(question, None, previous_topic="brake_vibration")
        assert (result["intent"], result["topic"]) == (intent, topic)
        assert result["search_query"] and "phanh" not in result["search_query"].casefold()


def test_invalid_analysis_and_implausible_tire_size_fail_safe():
    assert parse_analysis("not json", "Lốp là gì?") is None
    assert parse_analysis(json.dumps({"intent": "technical_explanation"}), "Lốp là gì?") is None
    assert parse_analysis(analysis(needs_rag="yes"), "Lốp là gì?") is None
    assert extract_tire_size("Lốp 999/99R99 có ý nghĩa gì?") is None
    fallback = normalize_analysis("Lốp 205/55R16 có ý nghĩa gì?", None, previous_topic="check_engine")
    assert fallback["topic"] == "tire_size" and fallback["is_new_topic"] is True


def test_model_cannot_grant_database_or_invent_entities():
    parsed = parse_analysis(analysis(intent="technical_explanation", topic="tire_size",
        entities={"brand": "FakeBrand", "part_code": "DROP-TABLE"},
        needs_database=True, needs_rag=False, needs_general_knowledge=False),
        "Lốp 205/55R16 có ý nghĩa gì?")
    result = normalize_analysis("Lốp 205/55R16 có ý nghĩa gì?", parsed)
    assert result["needs_database"] is False and result["needs_rag"] is True
    assert result["entities"]["brand"] is None and result["entities"]["part_code"] is None


def test_noise_word_tieng_is_never_treated_as_money():
    for question in (
        "Đạp phanh nghe tiếng ken két thì cần kiểm tra gì?",
        "Xe có tiếng lọc cọc khi đi đường bằng, phía sau, rõ hơn khi phanh.",
    ):
        assert has_explicit_price_intent(question) is False
        assert is_part_price_question(question) is False
        assert normalize_analysis(question, None)["intent"] == "technical_symptom"
    assert has_explicit_price_intent("Thay má phanh hết bao nhiêu tiền?") is True
    assert is_part_price_question("Giá má phanh bao nhiêu?") is True
    assert is_part_price_question("Giá thay bóng đèn") is True


def test_battery_warning_signs_are_not_a_catalog_list():
    model_hint = {"intent": "battery_list", "topic": "battery", "needs_database": True,
                  "needs_rag": False, "needs_general_knowledge": False}
    normalized = normalize_analysis("Ắc quy yếu thường có những dấu hiệu nào?", model_hint)
    assert normalized["intent"] == "technical_symptom"
    assert normalized["needs_database"] is False
    assert normalized["needs_rag"] is True

    class NoDatabaseRead:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("Câu hỏi triệu chứng không được đọc danh mục sản phẩm")

    assert answer_catalog_parts_question(
        NoDatabaseRead(), "Ắc quy yếu thường có những dấu hiệu nào?", {"role": "Khách hàng"}) is None
    answer, sources = _battery_weak_signs_reply("Ắc quy yếu thường có những dấu hiệu nào?")
    assert answer.status == "success" and sources == []
    assert "Máy đề quay chậm" in answer.content
    assert "hệ thống sạc" in answer.content
    assert "PT011" not in answer.content


def test_generic_oil_interval_is_not_a_service_price_question():
    question = "Bao lâu thì nên thay dầu động cơ?"
    normalized = normalize_analysis(question, {
        "intent": "unknown", "needs_database": False,
        "needs_rag": False, "needs_general_knowledge": False,
    })
    assert normalized["intent"] == "maintenance_interval"

    class NoDatabaseRead:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("Câu hỏi chu kỳ không được đọc bảng giá dịch vụ")

    assert _catalog_service_reply(NoDatabaseRead(), question) == (None, [])
    answer, sources = _generic_oil_interval_reply(question)
    assert answer.status == "success" and sources == []
    assert "khuyến" not in answer.content or "nhà sản xuất" in answer.content
    assert "số km hoặc thời gian" in answer.content
    assert "450.000" not in answer.content and "45 phút" not in answer.content


def test_two_stage_price_chat_filters_model_claims(chat_env, monkeypatch):
    client, _ = chat_env
    calls = []
    def model(messages):
        calls.append(messages)
        return analysis() if len(calls) == 1 else "Giá lốp là 8.000.000 ₫, còn hàng."
    monkeypatch.setattr(ai_service, "_chat", model)
    response = client.post(f"{API}/ai/assistant/chat", headers=headers(client),
                           json={"question": "Giá lốp?"})
    assert response.status_code == 200
    assert len(calls) == 1  # Không có giá được duyệt => không sinh số tiền bằng model
    assert "8.000.000" not in response.json()["result"]
    assert response.json()["source_count"] == 0


def test_model_cannot_turn_nontechnical_question_into_price_query(chat_env, monkeypatch):
    client, _ = chat_env
    monkeypatch.setattr(ai_service, "_chat", lambda messages: analysis(intent="tire_price"))
    response = client.post(f"{API}/ai/assistant/chat", headers=headers(client),
                           json={"question": "Vô lăng rung khi phanh"})
    assert response.status_code == 200
    assert "Giá bán" not in response.json()["result"]


def test_approved_tire_price_uses_validated_analysis_then_backend_snapshot(chat_env, monkeypatch):
    client, _ = chat_env
    add_tire()
    prompts = []
    def model(messages):
        prompts.append(messages)
        if len(prompts) == 1:
            return analysis(keywords=["vỏ bánh"])
        return "Mình đã tra danh mục để bạn tham khảo."
    monkeypatch.setattr(ai_service, "_chat", model)
    response = client.post(f"{API}/ai/assistant/chat", headers=headers(client),
                           json={"question": "Giá vỏ bánh hiện tại?"})
    assert response.status_code == 200, response.text
    assert len(prompts) == 2
    assert '"intent": "tire_price"' in prompts[1][1]["content"]
    assert "1.900.000" in response.json()["result"]
    assert response.json()["source_count"] == 1
