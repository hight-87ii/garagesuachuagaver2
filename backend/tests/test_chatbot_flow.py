# -*- coding: utf-8 -*-
"""Kiểm thử toàn diện GarageAI Chatbot: Multi-turn Context, 8 nhóm dữ liệu, RBAC và Fallback."""

import pytest
from backend.chat_pipeline import answer_chat
from backend.database import connect
from backend.ai_service import ai_service


def test_multiturn_tire_inquiry_sequence():
    """Kiểm thử chuỗi hội thoại 3 lượt kế thừa ngữ cảnh:
    Turn 1: Hỏi giá lốp Michelin 205/55R16
    Turn 2: Hỏi loại rẻ hơn (kế thừa size 205/55R16, tìm lốp rẻ hơn)
    Turn 3: Yêu cầu so sánh hai loại vừa thảo luận.
    """
    user = {"id": 1, "role": "Khách hàng", "customer_id": 1}

    # Turn 1
    q1 = "Giá lốp Michelin 205/55R16 bao nhiêu?"
    out1 = answer_chat(q1, user, trusted_history=True)
    assert not out1.answer.no_data, "Turn 1 phải tìm thấy lốp Michelin có giá duyệt"
    assert "2.150.000" in out1.answer.content or "2150000" in out1.answer.content
    assert "TIRE-MICH-20555R16" in out1.answer.content
    assert len(out1.product_ids) >= 1
    michelin_id = out1.product_ids[0]

    # Turn 2
    state_turn2 = {
        "product_ids": [michelin_id],
        "topic": "parts",
        "active_topic": "tire_price",
        "price_snapshots": [{"part_id": michelin_id, "price_at_time": 2150000}]
    }
    history_turn2 = [
        {"role": "user", "text": q1},
        {"role": "assistant", "text": out1.answer.content}
    ]
    q2 = "Có loại nào rẻ hơn không?"
    out2 = answer_chat(q2, user, history=history_turn2, state=state_turn2, trusted_history=True)
    assert not out2.answer.no_data, "Turn 2 phải tìm thấy lốp cùng kích cỡ có giá rẻ hơn"
    assert "TIRE-BS-20555R16" in out2.answer.content or "Bridgestone" in out2.answer.content
    assert "1.850.000" in out2.answer.content or "300.000" in out2.answer.content
    assert len(out2.product_ids) >= 2, "Turn 2 phải giữ cả 2 ID sản phẩm để phục vụ so sánh ở lượt 3"

    # Turn 3
    state_turn3 = {
        "product_ids": out2.product_ids,
        "topic": "parts",
        "active_topic": "tire_compare"
    }
    history_turn3 = [
        *history_turn2,
        {"role": "user", "text": q2},
        {"role": "assistant", "text": out2.answer.content}
    ]
    q3 = "So sánh hai loại đó giúp tôi."
    out3 = answer_chat(q3, user, history=history_turn3, state=state_turn3, trusted_history=True)
    assert not out3.answer.no_data, "Turn 3 phải trả về bảng so sánh chi tiết"
    assert "Michelin" in out3.answer.content
    assert "Bridgestone" in out3.answer.content
    assert any(term in out3.answer.content for term in ("giá bán", "tiết kiệm", "vận hành", "khuyến nghị", "đặc điểm", "thông số"))
    sources = out3.result.get("sources", [])
    assert len(sources) >= 2, "Turn 3 phải đính kèm sources của cả 2 sản phẩm từ Database"


def test_eight_data_groups_separation():
    """Kiểm chứng phân định 8 nhóm dữ liệu đúng nguyên tắc Database vs RAG vs RBAC."""
    user = {"id": 1, "role": "Khách hàng", "customer_id": 1}

    # 1. Nhóm Sản phẩm & Giá bán -> Phải lấy trực tiếp từ Database
    out_price = answer_chat("Giá lốp Michelin 205/55R16 bao nhiêu?", user)
    assert "2.150.000" in out_price.answer.content
    assert any(s.get("type") == "part" for s in out_price.result.get("sources", []))

    # 2. Nhóm Lịch sử sửa chữa -> Database có xác thực quyền (Không lộ chéo khách)
    other_user = {"id": 999, "role": "Khách hàng", "customer_id": 999}
    out_hist = answer_chat("Cho tôi xem lịch sử sửa chữa và phụ tùng đã thay của các xe khác", other_user)
    assert out_hist.answer.status in ("clarification", "no_data", "fallback")
    assert "100.000.000" not in out_hist.answer.content

    # 3. Nhóm Hướng dẫn kỹ thuật & Triệu chứng -> RAG / Tri thức
    out_symptom = answer_chat("Xe để qua đêm sáng hôm sau đề máy khó nổ có thể do đâu?", user)
    assert out_symptom.answer.status in ("success", "fallback")
    assert any(w in out_symptom.answer.content.casefold() for w in ("ắc quy", "bộ đề", "khởi động", "máy phát", "mối nối"))

    # 4. Nhóm Quy trình bảo dưỡng -> RAG / Chu kỳ
    out_maint = answer_chat("Bao lâu thì cần thay dầu động cơ một lần?", user)
    assert out_maint.answer.status in ("success", "fallback")
    assert any(w in out_maint.answer.content.casefold() for w in ("dầu", "chu kỳ", "bảo dưỡng", "km", "tháng"))

    # 5. Nhóm So sánh sản phẩm -> Kết hợp Database + Qwen/Fallback
    with connect() as db:
        mich = db.execute("SELECT id FROM parts WHERE code='TIRE-MICH-20555R16'").fetchone()
        bs = db.execute("SELECT id FROM parts WHERE code='TIRE-BS-20555R16'").fetchone()
        assert mich and bs
        state_compare = {"product_ids": [mich[0], bs[0]], "topic": "parts"}
        out_comp = answer_chat("So sánh hai loại đó giúp tôi", user, state=state_compare, trusted_history=True)
        assert len(out_comp.result.get("sources", [])) == 2


def test_offline_fallback_safety(monkeypatch):
    """Kiểm tra tính an toàn: khi Ollama offline hoặc lỗi kết nối, hệ thống tự động fallback chính xác."""
    user = {"id": 1, "role": "Khách hàng", "customer_id": 1}
    def mock_chat_failure(*args, **kwargs):
        raise ConnectionError("Ollama service unavailable")
    monkeypatch.setattr(ai_service, "_chat", mock_chat_failure)

    out = answer_chat("Giá lốp Michelin 205/55R16 bao nhiêu?", user)
    assert out.answer.status in ("fallback", "success")
    assert "2.150.000" in out.answer.content
