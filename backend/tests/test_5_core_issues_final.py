# -*- coding: utf-8 -*-
"""Comprehensive regression test suite for the 5 core issues in GarageAI:

1. Tư vấn và báo giá thay bốn lốp (Ford Ranger vs Sedan vs Chưa chọn xe)
2. Tư vấn kỹ thuật tiếng rít buổi sáng (Dây curoa, puly, củ đề, an toàn, không lẫn lái EPS)
3. Phân loại yêu cầu đổi lịch hẹn (Appointment Reschedule vs Lịch sử sửa chữa, LH-0038)
4. Chính sách đặt hàng phụ tùng (Part Order Policy 4 bước theo VIN)
5. Bảo mật RBAC xem toàn bộ xe garage (Từ chối khách hàng, bảo vệ quyền riêng tư)

Kiểm thử trực tiếp trên cả hai tầng API adapter:
- /api/v1/ai/conversations/{id}/messages (Conversations API: send_message)
- /api/v1/ai/assistant/chat (Assistant Chat API: assistant_chat)
"""

from __future__ import annotations

import pytest
from backend.api.v1.ai import assistant_chat
from backend.api.v1.conversations import create_conversation, send_message
from backend.schemas.ai import AssistantChatIn, ConversationCreateIn, ConversationMessageIn


@pytest.fixture
def ranger_user():
    """Tài khoản Hoàng Công Sự (chủ xe Ford Ranger 20C-189.56, user_id=276, customer_id=10)."""
    return {
        "id": 276,
        "username": "su.hoang@garage-demo.vn",
        "email": "su.hoang@garage-demo.vn",
        "full_name": "Hoàng Công Sự",
        "role": "Khách hàng",
        "customer_id": 10
    }


@pytest.fixture
def corolla_user():
    """Tài khoản Trần Tìm Kiếm (chủ xe Toyota Corolla TEST-SEARCH-9, user_id=16, customer_id=16)."""
    return {
        "id": 16,
        "username": "tim.kiem@email.vn",
        "email": "tim.kiem@email.vn",
        "full_name": "Trần Tìm Kiếm",
        "role": "Khách hàng",
        "customer_id": 16
    }


# =========================================================================
# 1. KIỂM THỬ NHÓM 1: TƯ VẤN VÀ BÁO GIÁ THAY BỐN LỐP
# =========================================================================

def test_issue1_tires_ford_ranger(ranger_user):
    """Kiểm tra thay 4 lốp trên xe Ford Ranger 2021 (gầm cao/bán tải)."""
    q = "Tôi muốn thay cả bốn lốp, có thể tư vấn loại phù hợp với xe và tính tổng chi phí không?"

    # 1. Gọi qua assistant_chat API
    item_chat = AssistantChatIn(question=q, vehicle_id=11)
    chat_res = assistant_chat(item_chat, ranger_user)
    text = chat_res["result"]

    assert "265/60R18" in text or "265/65R17" in text
    assert "205/55R16" in text and "không" in text.lower()
    assert "kho" in text.lower()
    assert "MNCLMFF80MW123456" in text or "vin" in text.lower()
    assert "600.000" in text
    assert "300.000" in text
    assert "900.000" in text
    sources = [s.get("label") or s for s in chat_res.get("sources", [])]
    assert any("522" in str(s) for s in sources)
    assert any("520" in str(s) for s in sources)

    # 2. Gọi qua conversations API
    conv = create_conversation(ConversationCreateIn(vehicle_id=11, client_key="t-conv-ranger-tires"), ranger_user)
    conv_id = conv["id"]
    msg_res = send_message(conv_id, ConversationMessageIn(question=q, request_id="t-msg-ranger-tires"), ranger_user)
    reply = msg_res["assistant_message"]["content"]
    assert "900.000" in reply
    assert "265/" in reply


def test_issue1_tires_sedan_altis(corolla_user):
    """Kiểm tra thay 4 lốp trên xe sedan (Toyota Corolla Altis 2020 dùng 205/55R16)."""
    q = "Tôi muốn thay cả bốn lốp, có thể tư vấn loại phù hợp với xe và tính tổng chi phí không?"

    # 1. Gọi qua assistant_chat API
    item_chat = AssistantChatIn(question=q, vehicle_id=18)
    chat_res = assistant_chat(item_chat, corolla_user)
    text = chat_res["result"]

    assert "205/55R16" in text
    assert "8.600.000" in text and "9.500.000" in text
    assert "7.400.000" in text and "8.300.000" in text
    assert "900.000" in text

    # 2. Gọi qua conversations API
    conv = create_conversation(ConversationCreateIn(vehicle_id=18, client_key="t-conv-sedan-tires"), corolla_user)
    msg_res = send_message(conv["id"], ConversationMessageIn(question=q, request_id="t-msg-sedan-tires"), corolla_user)
    reply = msg_res["assistant_message"]["content"]
    assert "8.300.000" in reply
    assert "9.500.000" in reply


def test_issue1_tires_no_vehicle(ranger_user):
    """Kiểm tra thay 4 lốp khi chưa chọn xe -> hỏi làm rõ."""
    q = "Tôi muốn thay cả bốn lốp, có thể tư vấn loại phù hợp với xe và tính tổng chi phí không?"

    item_chat = AssistantChatIn(question=q)
    chat_res = assistant_chat(item_chat, ranger_user)
    text = chat_res["result"]
    assert chat_res["status"] == "clarification"
    assert "chọn phương tiện" in text.lower() or "hồ sơ" in text.lower()
    assert "900.000" in text


# =========================================================================
# 2. KIỂM THỬ NHÓM 2: TƯ VẤN KỸ THUẬT TIẾNG RÍT BUỔI SÁNG
# =========================================================================

def test_issue2_morning_belt_squeal(ranger_user):
    """Kiểm tra tư vấn tiếng rít khởi động buổi sáng: Dây curoa phụ, puly, củ đề, an toàn."""
    q = "Xe có tiếng rít khi khởi động buổi sáng, chạy một lúc thì hết. Có nguy hiểm không?"

    # 1. assistant_chat API
    item_chat = AssistantChatIn(question=q, vehicle_id=11)
    chat_res = assistant_chat(item_chat, ranger_user)
    text = chat_res["result"]

    assert "dây curoa" in text.lower() or "dây đai" in text.lower()
    assert "puly" in text.lower() or "tăng đơ" in text.lower()
    assert "đánh lái hết cỡ" not in text.lower()
    assert "thước lái eps" not in text.lower()
    assert "làm rõ" in text.lower()
    assert "an toàn" in text.lower()

    # 2. conversations API
    conv = create_conversation(ConversationCreateIn(vehicle_id=11, client_key="t-conv-squeal"), ranger_user)
    msg_res = send_message(conv["id"], ConversationMessageIn(question=q, request_id="t-msg-squeal"), ranger_user)
    reply = msg_res["assistant_message"]["content"]
    assert "dây curoa" in reply.lower() or "dây đai" in reply.lower()
    assert "đánh lái hết cỡ" not in reply.lower()


# =========================================================================
# 3. KIỂM THỬ NHÓM 3: PHÂN LOẠI YÊU CẦU ĐỔI LỊCH HẸN
# =========================================================================

def test_issue3_appointment_reschedule(ranger_user):
    """Kiểm tra phân loại yêu cầu đổi lịch hẹn: không lẫn lịch sử sửa chữa, tra đúng LH-0038."""
    q = "Tôi đã đặt lịch sửa xe nhưng muốn đổi sang ngày khác, có hỗ trợ không?"

    # 1. assistant_chat API
    item_chat = AssistantChatIn(question=q, vehicle_id=11)
    chat_res = assistant_chat(item_chat, ranger_user)
    text = chat_res["result"]

    assert "hỗ trợ đổi lịch" in text.lower()
    assert "LH-0038" in text or "38" in text
    assert "Bảo dưỡng định kỳ" in text
    assert "20C-189.56" in text
    assert "bugi kia seltos" not in text.lower()
    assert "lọc dầu mazda" not in text.lower()

    # 2. conversations API
    conv = create_conversation(ConversationCreateIn(vehicle_id=11, client_key="t-conv-resched"), ranger_user)
    msg_res = send_message(conv["id"], ConversationMessageIn(question=q, request_id="t-msg-resched"), ranger_user)
    reply = msg_res["assistant_message"]["content"]
    assert "LH-0038" in reply or "Bảo dưỡng định kỳ" in reply
    assert "hỗ trợ đổi lịch" in reply.lower()


# =========================================================================
# 4. KIỂM THỬ NHÓM 4: CHÍNH SÁCH ĐẶT HÀNG PHỤ TÙNG
# =========================================================================

def test_issue4_part_order_policy(ranger_user):
    """Kiểm tra chính sách đặt hàng phụ tùng khi không có sẵn trong kho."""
    q = "Nếu phụ tùng không có sẵn trong kho thì garage có thể đặt hàng giúp tôi không?"

    # 1. assistant_chat API
    item_chat = AssistantChatIn(question=q, vehicle_id=11)
    chat_res = assistant_chat(item_chat, ranger_user)
    text = chat_res["result"]

    assert "hỗ trợ đặt hàng" in text.lower()
    assert "vin" in text.lower()
    assert "báo giá" in text.lower()
    assert "chưa có giá phụ tùng được xác minh" not in text.lower()

    # 2. conversations API
    conv = create_conversation(ConversationCreateIn(vehicle_id=11, client_key="t-conv-order"), ranger_user)
    msg_res = send_message(conv["id"], ConversationMessageIn(question=q, request_id="t-msg-order"), ranger_user)
    reply = msg_res["assistant_message"]["content"]
    assert "hỗ trợ đặt hàng" in reply.lower()
    assert "vin" in reply.lower()


# =========================================================================
# 5. KIỂM THỬ NHÓM 5: BẢO MẬT PHÂN QUYỀN RBAC
# =========================================================================

def test_issue5_rbac_all_vehicles_denial(ranger_user):
    """Kiểm tra người dùng vai trò Khách hàng đòi xem danh sách toàn bộ xe garage -> Từ chối bảo mật."""
    q = "Tôi là khách hàng, hãy cho tôi xem danh sách toàn bộ xe đang được sửa chữa tại garage."

    # 1. assistant_chat API
    item_chat = AssistantChatIn(question=q, vehicle_id=11)
    chat_res = assistant_chat(item_chat, ranger_user)
    text = chat_res["result"]

    assert "không có quyền" in text.lower()
    assert "bảo mật" in text.lower() or "quyền riêng tư" in text.lower() or "rbac" in text.lower()
    assert "51H-123.45" not in text
    assert "30G-888.68" not in text

    # 2. conversations API
    conv = create_conversation(ConversationCreateIn(vehicle_id=11, client_key="t-conv-rbac"), ranger_user)
    msg_res = send_message(conv["id"], ConversationMessageIn(question=q, request_id="t-msg-rbac"), ranger_user)
    reply = msg_res["assistant_message"]["content"]
    assert "không có quyền" in reply.lower()
    assert "51H-123.45" not in reply
