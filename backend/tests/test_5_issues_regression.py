"""Kiểm thử hồi quy 5 lỗi kiểm thử GarageAI:
1. Sai liên kết câu hỏi và câu trả lời / Multi-turn topic drift
2. Ollama tự tạo giá (ngăn chặn bịa giá)
3. Phân loại câu hỏi dịch vụ (kiểm tra hệ thống điện)
4. Cải thiện tư vấn kỹ thuật (xe hao nhiên liệu)
5. Kiểm thử hồi quy 6 câu hỏi cốt lõi trên cả hai API chat
"""

from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import connect, transaction
from backend.ai_service import strip_unverified_prices


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def ranger_customer_headers(client):
    """Đăng nhập bằng tài khoản Hoàng Công Sự (chủ xe Ford Ranger 20C-189.56, user_id=276)."""
    with connect() as db, transaction(db):
        from backend.auth_service import hash_password
        pwd_hash = hash_password("CustomerPass123!")
        db.execute("UPDATE users SET password_hash=?, password_algo='pbkdf2_sha256' WHERE id=276", (pwd_hash,))

    resp = client.post("/api/v1/auth/login", json={"email": "su.hoang@garage-demo.vn", "password": "CustomerPass123!"})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_strip_unverified_prices():
    """Kiểm tra bộ lọc hậu kiểm loại bỏ triệt để giá bịa."""
    hallucinated = (
        "Dầu hộp số tự động cần được thay định kỳ.\n"
        "Chi phí thay dầu hộp số tự động\n"
        "Chi phí thay dầu hộp số tự động bao gồm:\n"
        "1. Tiền công thay dầu: Khoảng 300.000 - 500.000 ₫ tùy theo garage.\n"
        "2. Tiền phụ tùng dầu hộp số tự động: Chi phí phụ thuộc vào loại dầu, từ 500.000 ₫ đến 1.000.000 ₫.\n\n"
        "Gợi ý: Đưa xe đến garage để kiểm tra."
    )
    cleaned = strip_unverified_prices(hallucinated)
    assert "300.000" not in cleaned
    assert "500.000" not in cleaned
    assert "1.000.000" not in cleaned
    assert "Garage chưa có bảng giá niêm yết cố định cho hạng mục này" in cleaned


def test_conversations_flow_6_questions(client, ranger_customer_headers):
    """Kiểm thử hội thoại đa lượt liên tục trên API /api/v1/ai/conversations/{id}/messages.
    
    Đảm bảo:
    - Không bị topic drift giữa các lượt.
    - Không bịa giá dầu hộp số.
    - Nhận diện đúng danh mục dịch vụ kiểm tra điện.
    - Tư vấn hao nhiên liệu chuẩn mực (3 nguyên nhân, 1 câu hỏi, cảnh báo mùi xăng, không EVAP lan man).
    - Lấy đúng phiếu bảo dưỡng và số tiền thực tế.
    """
    # 1. Tạo cuộc hội thoại mới gắn xe Ford Ranger
    c_resp = client.post("/api/v1/ai/conversations", json={
        "client_key": "test-regression-flow-6q-1",
        "vehicle_id": 11
    }, headers=ranger_customer_headers)
    assert c_resp.status_code == 201
    conv_id = c_resp.json()["id"]

    # Lượt 1: Thay má phanh
    q1 = "Nếu thay má phanh thì tổng chi phí gồm những khoản nào?"
    r1 = client.post(f"/api/v1/ai/conversations/{conv_id}/messages", json={
        "question": q1,
        "request_id": "req-flow-q1"
    }, headers=ranger_customer_headers)
    assert r1.status_code == 200
    msg1 = r1.json()["assistant_message"]["content"]
    assert "Tiền công thay thế" in msg1
    assert "Tiền phụ tùng" in msg1
    assert "Chi phí phát sinh kỹ thuật" in msg1

    # Lượt 2: Vô lăng rung ở 80 km/h
    q2 = "Xe chạy khoảng 80 km/h thì vô lăng rung, nhưng chạy chậm lại bình thường. Nguyên nhân có thể là gì?"
    r2 = client.post(f"/api/v1/ai/conversations/{conv_id}/messages", json={
        "question": q2,
        "request_id": "req-flow-q2"
    }, headers=ranger_customer_headers)
    assert r2.status_code == 200
    msg2 = r2.json()["assistant_message"]["content"]
    assert any(term in msg2.lower() for term in ("cân bằng động", "bánh xe", "lốp", "rô-tuyn"))

    # Lượt 3: Dầu hộp số tự động (KHÔNG được dính vô lăng rung của lượt 2, KHÔNG bịa giá 300k-500k)
    q3 = "Dầu hộp số tự động có cần thay định kỳ không? Khi nào nên thay?"
    r3 = client.post(f"/api/v1/ai/conversations/{conv_id}/messages", json={
        "question": q3,
        "request_id": "req-flow-q3"
    }, headers=ranger_customer_headers)
    assert r3.status_code == 200
    msg3 = r3.json()["assistant_message"]["content"]
    # Phải nói về dầu hộp số
    assert "dầu hộp số" in msg3.lower() or "hộp số" in msg3.lower()
    # Tuyệt đối không bị trôi chủ đề vô lăng rung
    assert "vô lăng" not in msg3.lower()
    # Tuyệt đối không bịa khoảng giá tiền công / dầu hộp số
    assert "300.000" not in msg3
    assert "500.000 - 1.000.000" not in msg3
    assert "500.000 ₫ đến 1.000.000" not in msg3

    # Lượt 4: Dịch vụ kiểm tra toàn bộ hệ thống điện (phải tra cứu danh mục, KHÔNG biến thành dầu hộp số)
    q4 = "Tôi muốn kiểm tra toàn bộ hệ thống điện của xe, garage có dịch vụ này không?"
    r4 = client.post(f"/api/v1/ai/conversations/{conv_id}/messages", json={
        "question": q4,
        "request_id": "req-flow-q4"
    }, headers=ranger_customer_headers)
    assert r4.status_code == 200
    msg4 = r4.json()["assistant_message"]["content"]
    # Phải nói về dịch vụ kiểm tra hệ thống điện
    assert "hệ thống điện" in msg4.lower()
    # Tuyệt đối không bị lặp lại dầu hộp số
    assert "dầu hộp số" not in msg4.lower()
    # Phải liệt kê các dịch vụ kiểm tra/chẩn đoán liên quan có giá niêm yết từ DB
    assert "Chẩn đoán lỗi bằng máy quét" in msg4
    assert "Kiểm tra ắc quy và hệ thống sạc" in msg4
    sources4 = r4.json()["result"].get("sources", [])
    assert len(sources4) >= 1
    assert any(s.get("type") == "service" for s in sources4)

    # Lượt 5: Xe hao nhiên liệu (tư vấn 3 nhóm nguyên nhân, 1 câu hỏi làm rõ, cảnh báo mùi xăng, không EVAP lan man)
    q5 = "Xe bị hao nhiên liệu hơn bình thường dù tôi vẫn chạy cùng một tuyến đường. Có thể do đâu?"
    r5 = client.post(f"/api/v1/ai/conversations/{conv_id}/messages", json={
        "question": q5,
        "request_id": "req-flow-q5"
    }, headers=ranger_customer_headers)
    assert r5.status_code == 200
    msg5 = r5.json()["assistant_message"]["content"]
    # Phải nói về hao nhiên liệu
    assert any(term in msg5.lower() for term in ("hao nhiên liệu", "nhiên liệu", "tiêu hao"))
    # Phải có nguyên nhân lốp/phanh và nạp khí/lọc gió/cảm biến
    assert any(term in msg5.lower() for term in ("lốp", "phanh"))
    assert any(term in msg5.lower() for term in ("lọc gió", "cảm biến", "hòa khí"))
    # Không liệt kê lan man EVAP hoặc nước làm mát rò rỉ
    assert "evap" not in msg5.lower()
    assert "van xả evap" not in msg5.lower()
    # Phải có câu hỏi làm rõ
    assert any(term in msg5.lower() for term in ("check engine", "đèn báo", "ì", "giật"))
    # Phải có cảnh báo an toàn mùi xăng / rò rỉ cháy nổ
    assert any(term in msg5.lower() for term in ("mùi xăng", "cháy nổ", "rò rỉ"))

    # Lượt 6: Lần bảo dưỡng gần nhất xe thay phụ tùng gì và hết bao nhiêu tiền
    q6 = "Cho tôi biết lần bảo dưỡng gần nhất xe đã thay những phụ tùng gì và hết bao nhiêu tiền?"
    r6 = client.post(f"/api/v1/ai/conversations/{conv_id}/messages", json={
        "question": q6,
        "request_id": "req-flow-q6"
    }, headers=ranger_customer_headers)
    assert r6.status_code == 200
    msg6 = r6.json()["assistant_message"]["content"]
    # Phải trích xuất đúng phiếu sửa chữa gần nhất PSC-1029
    assert "PSC-1029" in msg6
    # Phải nêu phụ tùng đã thay: Dầu động cơ 5W-30 4L
    assert "Dầu động cơ 5W-30" in msg6
    # Phải có số tiền tổng chi phí (1.220.400 ₫ hoặc HD-0004)
    assert "1.220.400" in msg6 or "HD-0004" in msg6


def test_assistant_chat_transport_6_questions(client, ranger_customer_headers):
    """Kiểm thử tương tự trên endpoint legacy /api/v1/ai/assistant/chat."""
    # Câu 1
    r1 = client.post("/api/v1/ai/assistant/chat", json={
        "question": "Nếu thay má phanh thì tổng chi phí gồm những khoản nào?"
    }, headers=ranger_customer_headers)
    assert r1.status_code == 200
    assert "Tiền công thay thế" in r1.json()["result"]

    # Câu 3 (Dầu hộp số - không tự bịa giá)
    r3 = client.post("/api/v1/ai/assistant/chat", json={
        "question": "Dầu hộp số tự động có cần thay định kỳ không? Khi nào nên thay?"
    }, headers=ranger_customer_headers)
    assert r3.status_code == 200
    msg3 = r3.json()["result"]
    assert "dầu hộp số" in msg3.lower() or "hộp số" in msg3.lower()
    assert "300.000" not in msg3
    assert "500.000 - 1.000.000" not in msg3

    # Câu 4 (Kiểm tra hệ thống điện - nhận diện dịch vụ)
    r4 = client.post("/api/v1/ai/assistant/chat", json={
        "question": "Tôi muốn kiểm tra toàn bộ hệ thống điện của xe, garage có dịch vụ này không?"
    }, headers=ranger_customer_headers)
    assert r4.status_code == 200
    msg4 = r4.json()["result"]
    assert "hệ thống điện" in msg4.lower()
    assert "dầu hộp số" not in msg4.lower()
    assert "Chẩn đoán lỗi bằng máy quét" in msg4

    # Câu 5 (Hao nhiên liệu - chuẩn 3 nhóm nguyên nhân, cảnh báo an toàn mùi xăng)
    r5 = client.post("/api/v1/ai/assistant/chat", json={
        "question": "Xe bị hao nhiên liệu hơn bình thường dù tôi vẫn chạy cùng một tuyến đường. Có thể do đâu?"
    }, headers=ranger_customer_headers)
    assert r5.status_code == 200
    msg5 = r5.json()["result"]
    assert any(t in msg5.lower() for t in ("hao nhiên liệu", "nhiên liệu"))
    assert "evap" not in msg5.lower()
    assert any(t in msg5.lower() for t in ("mùi xăng", "cháy nổ", "rò rỉ"))

    # Câu 6 (Bảo dưỡng gần nhất với vehicle_id=11)
    r6 = client.post("/api/v1/ai/assistant/chat", json={
        "question": "Cho tôi biết lần bảo dưỡng gần nhất xe đã thay những phụ tùng gì và hết bao nhiêu tiền?",
        "vehicle_id": 11
    }, headers=ranger_customer_headers)
    assert r6.status_code == 200
    msg6 = r6.json()["result"]
    assert "PSC-1029" in msg6
    assert "Dầu động cơ 5W-30" in msg6
    assert "1.220.400" in msg6 or "HD-0004" in msg6
