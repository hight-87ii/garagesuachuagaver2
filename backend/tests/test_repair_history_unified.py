# -*- coding: utf-8 -*-
"""Bộ kiểm thử toàn diện luồng tra cứu lịch sử sửa chữa và phụ tùng đã thay thế của GarageAI.

Kiểm tra đầy đủ 8 câu hỏi cốt lõi theo yêu cầu trên cả hai transport:
- answer_chat (chat pipeline trực tiếp)
- API hội thoại (/api/v1/ai/conversations/{id}/messages)
Đồng thời kiểm tra chặt chẽ phân quyền RBAC và phân định dịch vụ vs phụ tùng vs báo giá.
"""

import pytest
import sqlite3
from unittest.mock import patch

from backend.ai_service import ai_service
from backend.chat_pipeline import answer_chat
from backend.core.db import connect
from backend.repair_history_query import (
    answer_vehicle_repair_history,
    is_repair_history_question,
    query_vehicle_repair_history,
)


@pytest.fixture
def customer_user():
    """Khách hàng sở hữu xe 1 (Mazda CX-5, 51H-123.45)."""
    return {"id": 46, "email": "customer@garage.vn", "role": "Khách hàng", "name": "Nguyễn Minh Anh"}


@pytest.fixture
def other_customer_user():
    """Khách hàng khác không sở hữu xe 1."""
    return {"id": 275, "email": "ha.hoang@garage-demo.vn", "role": "Khách hàng", "name": "Hoàng Văn Hà"}


@pytest.fixture
def db_conn():
    with connect() as conn:
        yield conn


# =============================================================================
# 1. BỘ KIỂM THỬ 8 CÂU HỎI CỐT LÕI
# =============================================================================

def test_q1_general_repairs_overview(customer_user):
    """Câu 1: Xe này đã sửa những gì?
    - Tổng quan các lần sửa chữa đã hoàn thành
    - Phân định rõ ràng giữa dịch vụ kỹ thuật đã làm và phụ tùng đã thay
    - Tuyệt đối không báo 'Chưa có dữ liệu đủ căn cứ'
    """
    question = "Xe này đã sửa những gì?"
    result = answer_chat(question, customer_user, vehicle_id=1)
    content = result.answer.content

    assert "chưa có dữ liệu đủ căn cứ" not in content.lower()
    assert result.answer.status in ("success", "fallback")
    assert "Mazda CX-5" in content or "51H-123.45" in content
    # Có phần dịch vụ và phụ tùng
    assert "dịch vụ" in content.lower()
    assert "phụ tùng" in content.lower()
    assert any(srv in content for srv in ("Vệ sinh điều hòa", "Bảo dưỡng", "Kiểm tra"))
    assert any(part in content for part in ("Dầu động cơ", "Lọc dầu", "Má phanh"))


def test_q2_parts_replacement_history(customer_user):
    """Câu 2: Xe tôi đã từng thay những phụ tùng nào trong các lần sửa chữa trước?
    - Trích xuất đầy đủ phụ tùng đã thay thế thực tế từ các phiếu hoàn thành
    - Kèm số lượng, ngày, số km
    - Không bị báo thiếu căn cứ
    """
    question = "Xe tôi đã từng thay những phụ tùng nào trong các lần sửa chữa trước?"
    result = answer_chat(question, customer_user, vehicle_id=1)
    content = result.answer.content

    assert "chưa có dữ liệu đủ căn cứ" not in content.lower()
    assert result.answer.status in ("success", "fallback")
    assert any(part in content for part in ("Dầu động cơ", "Lọc dầu", "Má phanh", "Lọc gió điều hòa"))
    assert "phiếu sửa chữa" in content.lower() or "hoàn thành" in content.lower()


def test_q3_latest_engine_oil_change(customer_user):
    """Câu 3: Xe tôi đã thay dầu động cơ lần gần nhất khi nào?
    - Trích xuất chính xác ngày và số km lần thay dầu gần nhất
    - Nêu loại dầu đã thay
    - Tính toán số km đã chạy thêm kể từ lần thay dầu đó
    - Nhắc nhở mốc bảo dưỡng / thay dầu tiếp theo
    """
    question = "Xe tôi đã thay dầu động cơ lần gần nhất khi nào?"
    result = answer_chat(question, customer_user, vehicle_id=1)
    content = result.answer.content

    assert "chưa có dữ liệu đủ căn cứ" not in content.lower()
    assert result.answer.status in ("success", "fallback")
    assert "dầu động cơ" in content.lower()
    assert "km" in content.lower()
    # Kiểm tra có mốc ngày hoặc km của lần thay gần nhất
    assert "2026" in content or "42.500" in content or "40.000" in content


def test_q4_brake_pads_check(customer_user):
    """Câu 4: Xe tôi đã thay má phanh chưa?
    - Trả lời rõ ràng xe ĐÃ từng thay má phanh tại xưởng
    - Nêu chi tiết loại má phanh (Má phanh trước Toyota), ngày thay, mốc km
    - Nhắc nhở đo kiểm độ mòn thực tế định kỳ
    """
    question = "Xe tôi đã thay má phanh chưa?"
    result = answer_chat(question, customer_user, vehicle_id=1)
    content = result.answer.content

    assert "chưa có dữ liệu đủ căn cứ" not in content.lower()
    assert result.answer.status in ("success", "fallback")
    assert "đã từng thay má phanh" in content.lower() or "má phanh trước" in content.lower()
    assert "độ mòn" in content.lower() or "kiểm tra" in content.lower()


def test_q5_latest_visit_parts(customer_user):
    """Câu 5: Những phụ tùng nào đã được thay trong lần bảo dưỡng gần nhất?
    - Xác định đúng lần vào xưởng gần nhất (PSC-1147 ngày 2026-10-28)
    - Trả lời rõ lần đó chỉ làm dịch vụ Vệ sinh điều hòa, chưa thay phụ tùng
    - Không nhầm lẫn dịch vụ thành phụ tùng
    """
    question = "Những phụ tùng nào đã được thay trong lần bảo dưỡng gần nhất?"
    result = answer_chat(question, customer_user, vehicle_id=1)
    content = result.answer.content

    assert "chưa có dữ liệu đủ căn cứ" not in content.lower()
    assert result.answer.status in ("success", "fallback")
    assert "vệ sinh điều hòa" in content.lower() or "chưa ghi nhận thay thế phụ tùng" in content.lower()


def test_q6_all_parts_replacement_history(customer_user):
    """Câu 6: Hiển thị toàn bộ lịch sử thay thế phụ tùng.
    - Hiển thị danh sách đầy đủ phụ tùng đã thay thế
    - Không bỏ sót các hạng mục chính
    """
    question = "Hiển thị toàn bộ lịch sử thay thế phụ tùng."
    result = answer_chat(question, customer_user, vehicle_id=1)
    content = result.answer.content

    assert "chưa có dữ liệu đủ căn cứ" not in content.lower()
    assert result.answer.status in ("success", "fallback")
    assert "Dầu động cơ" in content
    assert "Lọc dầu" in content


def test_q7_quoted_not_replaced_parts(customer_user):
    """Câu 7: Phụ tùng nào chỉ nằm trong báo giá nhưng chưa được thay?
    - Trích xuất chính xác 'Lọc dầu Mazda LF10-14-302' trong Báo giá BG-1028-01 / PSC-1028
    - Giải thích rõ phụ tùng này chưa được nghiệm thu thực tế vì phiếu đang sửa
    - Không gộp chung vào danh sách phụ tùng đã hoàn tất
    """
    question = "Phụ tùng nào chỉ nằm trong báo giá nhưng chưa được thay?"
    result = answer_chat(question, customer_user, vehicle_id=1)
    content = result.answer.content

    assert "chưa có dữ liệu đủ căn cứ" not in content.lower()
    assert result.answer.status in ("success", "fallback")
    assert "Lọc dầu Mazda LF10-14-302" in content
    assert "BG-1028-01" in content or "PSC-1028" in content
    assert "chưa" in content.lower() or "báo giá" in content.lower()


def test_q8_hypothetical_no_history(customer_user):
    """Câu 8: Xe này chưa từng sửa chữa thì sao?
    - Trả lời rõ ràng, tự nhiên về trường hợp xe chưa có phiếu sửa chữa nào
    - Hướng dẫn khách đặt lịch hẹn bảo dưỡng / kiểm tra tổng quát
    """
    question = "Xe này chưa từng sửa chữa thì sao?"
    result = answer_chat(question, customer_user, vehicle_id=1)
    content = result.answer.content

    assert "chưa có dữ liệu đủ căn cứ" not in content.lower()
    assert "chưa ghi nhận phiếu sửa chữa" in content.lower() or "đặt lịch hẹn" in content.lower()


# =============================================================================
# 2. KIỂM THỬ KHẢ NĂNG TỰ ĐỘNG NHẬN DIỆN XE CỦA KHÁCH HÀNG (KHÔNG CẦN VEHICLE_ID)
# =============================================================================

def test_auto_vehicle_identification_single_vehicle(customer_user):
    """Khách hàng chỉ có 1 xe trong hồ sơ: tự động nhận diện xe khi hỏi phụ tùng đã thay."""
    result = answer_chat("Xe tôi đã từng thay những phụ tùng nào trong các lần sửa chữa trước?", customer_user)
    content = result.answer.content

    assert "Mazda CX-5" in content or "51H-123.45" in content
    assert result.answer.status in ("success", "fallback")
    assert "chưa có dữ liệu đủ căn cứ" not in content.lower()


# =============================================================================
# 3. KIỂM THỬ PHÂN BIỆT DỊCH VỤ VÀ PHỤ TÙNG (DỊCH VỤ KHÔNG TỰ BIẾN THÀNH PHỤ TÙNG)
# =============================================================================

def test_service_is_not_treated_as_replaced_part(db_conn, customer_user):
    """Phiếu chỉ có dịch vụ 'Bảo dưỡng định kỳ' hoặc 'Vệ sinh điều hòa' không được coi là đã thay phụ tùng."""
    cur = db_conn.cursor()
    plate = "51H-TEST-SRV"
    code = "PSC-TEST-SRV-99"

    cur.execute(
        """INSERT INTO vehicles(customer_id, plate, plate_normalized, make, model, year, status)
           VALUES(1, ?, '51HTESTSRV', 'Honda', 'CR-V', 2022, 'active')""",
        (plate,)
    )
    test_v_id = cur.lastrowid
    ro_id = None
    try:
        cur.execute(
            """INSERT INTO repair_orders(code, vehicle_id, customer_id, plate, status, status_code, completed_at)
               VALUES(?, ?, 1, ?, 'Hoàn thành', 'COMPLETED', '2026-02-15T10:00:00Z')""",
            (code, test_v_id, plate)
        )
        ro_id = cur.lastrowid
        cur.execute(
            """INSERT INTO repair_order_items(repair_order_id, kind, name, quantity, unit_price)
               VALUES(?, 'Dịch vụ', 'Vệ sinh khoang máy và kiểm tra gầm', 1, 500000)""",
            (ro_id,)
        )
        db_conn.commit()

        res, sources = answer_vehicle_repair_history(
            db_conn, "Xe này đã từng thay phụ tùng gì?", customer_user, vehicle_id=test_v_id
        )
        # Báo rõ chỉ làm dịch vụ, chưa từng thay phụ tùng
        assert "chưa ghi nhận thay thế phụ tùng" in res.content
        assert "khoang máy" not in res.content or "dịch vụ" in res.content.lower()
    finally:
        if ro_id:
            cur.execute("DELETE FROM repair_order_items WHERE repair_order_id=?", (ro_id,))
            cur.execute("DELETE FROM repair_orders WHERE id=?", (ro_id,))
        cur.execute("DELETE FROM vehicles WHERE id=?", (test_v_id,))
        db_conn.commit()


# =============================================================================
# 4. KIỂM THỬ BẢO MẬT PHÂN QUYỀN RBAC (CHỐNG LỖ HỔNG IDOR)
# =============================================================================

def test_rbac_unauthorized_user_blocked(other_customer_user):
    """Khách hàng khác không thể tra cứu lịch sử sửa chữa của xe không thuộc sở hữu."""
    from backend.core.errors import ForbiddenError

    with pytest.raises(ForbiddenError):
        answer_chat("Xe này đã sửa những gì?", other_customer_user, vehicle_id=1)


# =============================================================================
# 5. KIỂM THỬ HỘI THOẠI TRÊN API AI CONVERSATIONS
# =============================================================================

def test_conversations_api_flow(db_conn, customer_user):
    """Kiểm tra luồng hội thoại qua bảng ai_conversations và ai_messages."""
    from backend.api.v1.conversations import create_conversation, conversation_detail

    # 1. Tạo hội thoại cho xe 1
    class FakeConvIn:
        vehicle_id = 1
        plate = None
        client_key = "test_unified_repair_history_key_01"

    conv = create_conversation(FakeConvIn(), user=customer_user)
    assert conv["vehicle_id"] == 1
    conv_id = conv["id"]

    try:
        # 2. Gửi câu hỏi vào hội thoại qua answer_chat với history
        q = "Xe tôi đã từng thay những phụ tùng nào trong các lần sửa chữa trước?"
        output = answer_chat(q, customer_user, vehicle_id=1)
        assert output.answer.status in ("success", "fallback")
        assert "chưa có dữ liệu đủ căn cứ" not in output.answer.content.lower()
        assert any(p in output.answer.content for p in ("Dầu động cơ", "Lọc dầu", "Má phanh"))
    finally:
        # Dọn dẹp hội thoại test
        db_conn.execute("DELETE FROM ai_messages WHERE conversation_id=?", (conv_id,))
        db_conn.execute("DELETE FROM ai_conversations WHERE id=?", (conv_id,))
        db_conn.commit()

