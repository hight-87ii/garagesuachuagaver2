"""Model chỉ gợi ý ý định; backend vẫn là nơi kiểm tra quyền và dữ kiện."""

import json

from backend.ai_service import ai_service
from backend.chat_intent import parse_analysis
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
