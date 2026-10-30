# -*- coding: utf-8 -*-
"""Bộ kiểm thử 15 kịch bản tư vấn kỹ thuật và tra cứu lịch sử sửa chữa với Qwen (GarageAI)."""

import sqlite3
from uuid import uuid4
import pytest
from unittest.mock import patch, MagicMock

from backend.database import connect
from backend.chat_pipeline import answer_chat
from backend.repair_history_query import (
    answer_vehicle_repair_history,
    is_repair_history_question,
    query_vehicle_repair_history,
)
from backend.ai_service import ai_service, AIResult


@pytest.fixture
def db_conn():
    conn = connect()
    yield conn
    conn.close()


@pytest.fixture
def customer_user():
    return {"id": 1, "email": "customer@garage.vn", "role": "Khách hàng"}


# -----------------------------------------------------------------------------
# Kịch bản 1: Xe khó khởi động sau khi để qua đêm
# -----------------------------------------------------------------------------
def test_scenario_1_cold_start_overnight_natural_advisory(customer_user):
    question = "Xe tôi để qua đêm, sáng hôm sau đề máy rất khó nổ. Có thể do đâu?"
    result = answer_chat(question, customer_user)

    content = result.answer.content
    assert content, "Phản hồi không được để trống"
    # 1. Giải thích nguyên nhân để qua đêm: ắc quy tụt áp/tự xả, cọc bình, bộ đề, nhiên liệu
    assert any(term in content.lower() for term in ("ắc quy", "điện áp", "bình", "tụt áp", "nguồn điện"))
    assert any(term in content.lower() for term in ("qua đêm", "nguội", "máy khởi động", "bộ đề", "cọc bình"))
    # 2. Không chứa cảnh báo ngập nước / khói khét rập khuôn
    assert "ngập nước" not in content.lower()
    assert "khói hoặc mùi khét" not in content.lower()
    # 3. Đưa ra đúng câu hỏi làm rõ quan trọng nhất
    assert any(q in content for q in (
        "quay yếu", "chỉ nghe tiếng tạch tạch", "vẫn quay bình thường nhưng không nổ"
    ))
    # 4. Có sources chỉ dẫn bài viết kỹ thuật
    assert len(result.result.get("sources", [])) > 0


# -----------------------------------------------------------------------------
# Kịch bản 2: Xe đề chỉ có tiếng tạch tạch
# -----------------------------------------------------------------------------
def test_scenario_2_click_only_starting_symptom(customer_user):
    question = "Khi đề máy chỉ nghe tiếng tạch tạch rồi im re, không thấy động cơ quay."
    result = answer_chat(question, customer_user)

    content = result.answer.content
    # Nhận diện ngay dấu hiệu nguồn điện/bộ đề/rơ-le
    assert any(term in content.lower() for term in ("ắc quy", "rơ-le", "củ đề", "máy khởi động", "cọc bình"))
    assert any(term in content.lower() for term in ("sụt áp", "điện áp", "yếu", "cạn kiệt", "tiếp xúc"))
    # Hướng dẫn an toàn và kiểm tra đo đạc
    assert any(term in content.lower() for term in ("câu bình", "đo", "10 giây", "quá nhiệt", "kiểm tra"))
    # Không hỏi lại câu làm rõ ban đầu
    assert "động cơ quay yếu, chỉ nghe tiếng tạch tạch" not in content


# -----------------------------------------------------------------------------
# Kịch bản 3: Động cơ quay bình thường nhưng không nổ
# -----------------------------------------------------------------------------
def test_scenario_3_crank_normal_no_start_symptom(customer_user):
    question = "Máy đề vẫn quay khỏe bình thường nhưng động cơ không nổ được."
    result = answer_chat(question, customer_user)

    content = result.answer.content
    # Loại trừ ắc quy yếu và máy đề
    assert any(term in content.lower() for term in ("vẫn hoạt động tốt", "ắc quy và", "bộ đề"))
    # Tập trung vào nhiên liệu (bơm xăng, lọc xăng) và đánh lửa (bugi, bô-bin, CKP)
    assert any(term in content.lower() for term in ("bơm xăng", "nhiên liệu", "áp suất"))
    assert any(term in content.lower() for term in ("đánh lửa", "bugi", "trục khuỷu", "ckp", "bô-bin"))


# -----------------------------------------------------------------------------
# Kịch bản 4: Khách trả lời câu hỏi làm rõ ở lượt tiếp theo (multi-turn follow-up)
# -----------------------------------------------------------------------------
def test_scenario_4_multiturn_clarification_followup(customer_user):
    # Lượt 1: Khách hỏi khó nổ ban đầu
    turn1 = answer_chat("Xe tôi để qua đêm, sáng hôm sau đề máy rất khó nổ. Có thể do đâu?", customer_user)
    assert turn1.answer.status in ("success", "fallback")

    # Lượt 2: Khách cung cấp biểu hiện chi tiết
    turn2 = answer_chat(
        "Đề thấy quay chậm lắm, đèn taplo hơi tối đi.",
        customer_user,
        state=turn1.state_update,
        history=[
            {"role": "user", "text": "Xe tôi để qua đêm, sáng hôm sau đề máy rất khó nổ. Có thể do đâu?"},
            {"role": "assistant", "text": turn1.answer.content}
        ]
    )
    content2 = turn2.answer.content
    # Phân tích sâu vào ắc quy sụt áp và hệ thống sạc/máy phát
    assert any(term in content2.lower() for term in ("sụt áp", "ắc quy bị yếu", "dưới 9.6v", "cọc bình", "máy phát", "dynamo"))
    # Hướng dẫn xử lý cụ thể
    assert any(term in content2.lower() for term in ("siết", "câu bình", "cca", "dòng rò"))
    # Không lặp lại câu hỏi làm rõ ban đầu
    assert "động cơ quay yếu, chỉ nghe tiếng tạch tạch hay vẫn quay bình thường" not in content2


# -----------------------------------------------------------------------------
# Kịch bản 5: Khách hỏi lịch sử phụ tùng đã thay (xe có lịch sử)
# -----------------------------------------------------------------------------
def test_scenario_5_customer_parts_replacement_history_single_vehicle(customer_user):
    question = "Xe tôi đã từng thay những phụ tùng nào trong các lần sửa chữa trước?"
    result = answer_chat(question, customer_user)

    content = result.answer.content
    # Tự động nhận diện xe Mazda CX-5 (51H-123.45) của khách
    assert "51H-123.45" in content or "Mazda" in content
    # Không báo "Chưa có dữ liệu đủ căn cứ..."
    assert "chưa có dữ liệu đủ căn cứ" not in content.lower()
    # Liệt kê phụ tùng đã thay thực tế trong DB
    assert any(part in content for part in ("Lọc dầu", "Má phanh", "Lọc gió", "Dầu động cơ"))
    # Có ngày và số km
    assert any(year in content for year in ("2025", "2026"))
    assert "km" in content.lower()
    # Có sources dẫn chứng từ phiếu sửa chữa
    sources = result.result.get("sources", [])
    assert len(sources) > 0
    assert all("id" in s for s in sources)


# -----------------------------------------------------------------------------
# Kịch bản 6: Xe có nhiều phiếu sửa chữa (tổng hợp đầy đủ, sắp xếp giảm dần)
# -----------------------------------------------------------------------------
def test_scenario_6_multiple_completed_repair_orders_aggregation(db_conn):
    # Xe ID 1 (51H-123.45) có nhiều phiếu sửa chữa đã hoàn thành
    data = query_vehicle_repair_history(db_conn, 1)
    parts = data["parts_replaced"]

    assert len(parts) >= 4, "Phải tổng hợp được các phụ tùng từ nhiều phiếu"
    assert len(data["completed_repair_orders"]) >= 2, "Phải nhận diện nhiều phiếu hoàn thành"

    # Kiểm tra sắp xếp theo ngày giảm dần
    dates = [p["date"] for p in parts if p.get("date")]
    assert dates == sorted(dates, reverse=True), "Phụ tùng phải được sắp xếp mới nhất lên trước"


# -----------------------------------------------------------------------------
# Kịch bản 7: Phiếu sửa chữa có dịch vụ nhưng không có phụ tùng (thông báo đúng)
# -----------------------------------------------------------------------------
def test_scenario_7_completed_repair_orders_without_parts(db_conn, customer_user):
    suffix = uuid4().hex[:6].upper()
    plate = f"88A-{suffix}"
    code = f"PSC-SRV-{suffix}"
    cur = db_conn.cursor()
    cur.execute("INSERT INTO vehicles(plate, plate_normalized, customer_id, make, model, year, status) VALUES(?, ?, 1, 'Toyota', 'Vios', 2021, 'active')", (plate, plate.replace("-", "")))
    v_id = cur.lastrowid
    ro_id = None
    try:
        cur.execute(
            """INSERT INTO repair_orders(code, vehicle_id, customer_id, plate, customer_name, status, status_code, completed_at)
               VALUES(?, ?, 1, ?, 'Nguyễn Minh Anh', 'Hoàn thành', 'COMPLETED', '2026-03-01T10:00:00Z')""",
            (code, v_id, plate)
        )
        ro_id = cur.lastrowid
        cur.execute("INSERT INTO repair_order_items(repair_order_id, kind, name, quantity, unit_price) VALUES(?, 'Dịch vụ', 'Vệ sinh khoang máy', 1, 300000)", (ro_id,))
        db_conn.commit()

        res, sources = answer_vehicle_repair_history(db_conn, f"Xe {plate} đã thay phụ tùng gì?", customer_user, vehicle_id=v_id)
        content = res.content
        assert "chỉ thực hiện các dịch vụ" in content or "chưa ghi nhận thay thế phụ tùng" in content
        assert "chưa có dữ liệu đủ căn cứ" not in content.lower()
    finally:
        if ro_id:
            cur.execute("DELETE FROM repair_order_items WHERE repair_order_id=?", (ro_id,))
            cur.execute("DELETE FROM repair_orders WHERE id=?", (ro_id,))
        cur.execute("DELETE FROM vehicles WHERE id=?", (v_id,))
        db_conn.commit()


# -----------------------------------------------------------------------------
# Kịch bản 8: Phụ tùng chỉ có trong báo giá, chưa xác nhận thực hiện
# -----------------------------------------------------------------------------
def test_scenario_8_quoted_parts_not_counted_as_replaced(db_conn):
    # Xe ID 2 (Camry 30G-888.68) chỉ có phiếu trạng thái 'Chờ phụ tùng' / Báo giá
    data = query_vehicle_repair_history(db_conn, 2)
    # Phụ tùng trong phiếu chưa hoàn thành không được tính là đã thay
    assert len(data["parts_replaced"]) == 0
    assert len(data["pending_repair_orders"]) >= 1


# -----------------------------------------------------------------------------
# Kịch bản 9: Phụ tùng đã được ghi nhận hoàn thành
# -----------------------------------------------------------------------------
def test_scenario_9_completed_parts_accuracy(db_conn):
    data = query_vehicle_repair_history(db_conn, 1)
    parts = data["parts_replaced"]

    # Đảm bảo phụ tùng thuộc phiếu hoàn thành có đầy đủ thuộc tính
    for p in parts:
        assert p.get("name"), "Tên phụ tùng không được rỗng"
        assert p.get("quantity") is not None and p["quantity"] > 0
        assert p.get("source") in ("repair_order_item", "repair_order_part", "repair_history")


# -----------------------------------------------------------------------------
# Kịch bản 10: Có hóa đơn nhưng không có đủ chi tiết phụ tùng
# -----------------------------------------------------------------------------
def test_scenario_10_invoice_without_itemized_parts(db_conn, customer_user):
    suffix = uuid4().hex[:6].upper()
    plate = f"88A-{suffix}"
    code = f"PSC-PKG-{suffix}"
    cur = db_conn.cursor()
    cur.execute("INSERT INTO vehicles(plate, plate_normalized, customer_id, make, model, year, status) VALUES(?, ?, 1, 'Ford', 'Ranger', 2020, 'active')", (plate, plate.replace("-", "")))
    v_id = cur.lastrowid
    ro_id = None
    try:
        cur.execute(
            """INSERT INTO repair_orders(code, vehicle_id, customer_id, plate, customer_name, status, status_code, completed_at)
               VALUES(?, ?, 1, ?, 'Nguyễn Minh Anh', 'Hoàn thành', 'COMPLETED', '2026-01-10T10:00:00Z')""",
            (code, v_id, plate)
        )
        ro_id = cur.lastrowid
        cur.execute("INSERT INTO repair_order_items(repair_order_id, kind, name, quantity, unit_price) VALUES(?, 'Dịch vụ', 'Gói bảo dưỡng cấp lớn 4 vạn', 1, 2000000)", (ro_id,))
        db_conn.commit()

        res, sources = answer_vehicle_repair_history(db_conn, f"Xe {plate} đã thay phụ tùng gì?", customer_user, vehicle_id=v_id)
        assert "chưa ghi nhận thay thế phụ tùng" in res.content
        assert "Giảm xóc" not in res.content
        assert "Má phanh" not in res.content
    finally:
        if ro_id:
            cur.execute("DELETE FROM repair_order_items WHERE repair_order_id=?", (ro_id,))
            cur.execute("DELETE FROM repair_orders WHERE id=?", (ro_id,))
        cur.execute("DELETE FROM vehicles WHERE id=?", (v_id,))
        db_conn.commit()


# -----------------------------------------------------------------------------
# Kịch bản 11: Khách có nhiều xe (yêu cầu làm rõ chọn xe)
# -----------------------------------------------------------------------------
def test_scenario_11_customer_with_multiple_vehicles_clarification(db_conn):
    # Khách hàng ID 5 (yen.vu@email.vn) sở hữu 2 xe: 29A-112.23 (Tucson) và 29A-778.90 (Ranger)
    user5 = {"id": 5, "email": "yen.vu@email.vn", "role": "Khách hàng"}
    res, sources = answer_vehicle_repair_history(db_conn, "Xe tôi đã từng thay những phụ tùng nào trong các lần sửa trước?", user5)

    assert res.status == "clarification"
    assert "29A-112.23" in res.content
    assert "29A-778.90" in res.content
    assert "chọn xe" in res.content.lower()


# -----------------------------------------------------------------------------
# Kịch bản 12: Khách không có quyền xem xe (chặn RBAC an toàn)
# -----------------------------------------------------------------------------
def test_scenario_12_rbac_ownership_idor_protection(db_conn):
    attacker = {"id": 100, "email": "attacker@demo.vn", "role": "Khách hàng"}
    # Thử tra cứu xe của khách ID khác (ví dụ xe ID 1 thuộc customer_id=1)
    res, sources = answer_vehicle_repair_history(db_conn, "Xe 51H-123.45 đã thay những phụ tùng gì?", attacker, vehicle_id=1)

    assert res.status == "denied"
    assert "không có quyền" in res.content.lower()
    # Tuyệt đối không để lộ danh sách phụ tùng của xe khác
    assert "Lọc dầu" not in res.content
    assert "Má phanh" not in res.content


# -----------------------------------------------------------------------------
# Kịch bản 13: Xe không có lịch sử sửa chữa nào (thông báo đúng)
# -----------------------------------------------------------------------------
def test_scenario_13_vehicle_with_no_repair_history(db_conn):
    # Khách hàng ID 12 (han.pham@email.vn) sở hữu xe ID 14 (51K-909.09, Kia Seltos) chưa từng có phiếu sửa chữa nào
    user12 = {"id": 12, "email": "han.pham@email.vn", "role": "Khách hàng"}
    res, sources = answer_vehicle_repair_history(db_conn, "Xe tôi đã từng thay những phụ tùng nào?", user12)

    assert "chưa ghi nhận phiếu sửa chữa hoặc lịch sử dịch vụ nào" in res.content
    assert "chưa có dữ liệu đủ căn cứ" not in res.content.lower()


# -----------------------------------------------------------------------------
# Kịch bản 14: Database lỗi hoặc truy vấn timeout (xử lý exception graceful)
# -----------------------------------------------------------------------------
def test_scenario_14_database_error_graceful_handling(customer_user):
    # Mock kết nối DB ném sqlite3.OperationalError
    mock_db = MagicMock()
    mock_db.execute.side_effect = sqlite3.OperationalError("database is locked")

    res, sources = answer_vehicle_repair_history(
        mock_db,
        "Xe tôi đã từng thay những phụ tùng nào trong các lần sửa chữa trước?",
        customer_user,
        vehicle_id=1
    )

    assert res.status == "error"
    assert "Chưa thể tra cứu" in res.content
    assert sources == []


# -----------------------------------------------------------------------------
# Kịch bản 15: Qwen không hoạt động hoặc trả nội dung rỗng (tự động fallback chuẩn xác)
# -----------------------------------------------------------------------------
def test_scenario_15_qwen_offline_fallback_safety(customer_user):
    # Khi Qwen/Ollama không khả dụng hoặc trả rỗng
    with patch.object(ai_service, "_chat", side_effect=Exception("Ollama connection refused")):
        # 1. Câu hỏi kỹ thuật: fallback chuyên môn vẫn hoạt động chuẩn xác
        res_tech = answer_chat("Xe tôi để qua đêm, sáng hôm sau đề máy rất khó nổ. Có thể do đâu?", customer_user)
        assert res_tech.answer.status in ("success", "fallback")
        assert "ắc quy" in res_tech.answer.content.lower()

        # 2. Câu hỏi phụ tùng đã thay: trích xuất chính xác từ DB không bị gián đoạn
        res_hist = answer_chat("Xe tôi đã từng thay những phụ tùng nào trong các lần sửa chữa trước?", customer_user)
        assert res_hist.answer.status in ("success", "fallback")
        assert any(part in res_hist.answer.content for part in ("Lọc dầu", "Dầu động cơ", "Má phanh"))
        assert len(res_hist.result.get("sources", [])) > 0
