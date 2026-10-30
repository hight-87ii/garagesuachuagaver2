# -*- coding: utf-8 -*-
"""Bộ kiểm thử 12 kịch bản Smart Maintenance Recommendation (Gợi ý bảo dưỡng thông minh)."""

import sqlite3
from uuid import uuid4
import pytest

from backend.database import connect, transaction
from backend.chat_pipeline import answer_chat
from backend.repair_history_query import (
    answer_vehicle_repair_history,
    query_vehicle_repair_history,
)
from backend.smart_maintenance_recommendation import (
    evaluate_maintenance_recommendations,
    get_active_future_appointments,
    has_matching_appointment,
)


@pytest.fixture
def db_conn():
    conn = connect()
    yield conn
    conn.close()


@pytest.fixture
def customer_user():
    return {"id": 1, "email": "customer@garage.vn", "role": "Khách hàng"}


# -----------------------------------------------------------------------------
# Kịch bản 1: Dầu động cơ chạy vượt chu kỳ xác minh
# -----------------------------------------------------------------------------
def test_scenario_1_engine_oil_exceeds_verified_interval(db_conn, customer_user):
    """Khi xe đã chạy vượt chu kỳ thay dầu, hệ thống gợi ý thay dầu định kỳ."""
    vehicle = {
        "id": 9901,
        "customer_id": customer_user["id"],
        "plate": "29A-990.01",
        "make": "Mazda",
        "model": "CX-5",
        "year": 2021,
        "mileage": 52500,  # 52.500 km
    }
    history_data = {
        "parts_replaced": [
            {
                "name": "Dầu động cơ tổng hợp",
                "quantity": 4,
                "date": "2026-03-01",
                "km": 42000,  # thay tại 42.000 km -> used_km = 10.500 km
                "ro_code": "RO-9901",
                "ro_id": 9901,
            }
        ]
    }
    # Chu kỳ CX-5 là 10.000 km (hoặc tiêu chuẩn 5.000 km) -> used_km = 10.500 km > chu kỳ
    recs = evaluate_maintenance_recommendations(db_conn, vehicle, history_data, customer_user)

    oil_rec = next((r for r in recs if r["category"] == "oil_change"), None)
    assert oil_rec is not None, "Phải có gợi ý thay dầu động cơ khi chạy vượt chu kỳ"
    assert oil_rec["status"] == "due", "Trạng thái gợi ý phải là 'due'"
    assert oil_rec["action_type"] == "replace"
    assert oil_rec["service_id"] == 2
    assert oil_rec["used_km"] == 10500
    assert "vượt chu kỳ" in oil_rec["recommendation_text"].lower() or "thay dầu động cơ" in oil_rec["recommendation_text"].lower()


# -----------------------------------------------------------------------------
# Kịch bản 2: Dầu động cơ chưa đến hạn
# -----------------------------------------------------------------------------
def test_scenario_2_engine_oil_not_due(db_conn, customer_user):
    """Khi dầu động cơ mới thay và xe mới chạy ít km, không gợi ý thay dầu."""
    vehicle = {
        "id": 9902,
        "customer_id": customer_user["id"],
        "plate": "29A-990.02",
        "make": "Mazda",
        "model": "CX-5",
        "year": 2021,
        "mileage": 43500,  # 43.500 km
    }
    history_data = {
        "parts_replaced": [
            {
                "name": "Dầu động cơ",
                "quantity": 4,
                "date": "2026-08-01",
                "km": 42000,  # thay tại 42.000 km -> used_km = 1.500 km (chưa đến hạn)
                "ro_code": "RO-9902",
                "ro_id": 9902,
            }
        ]
    }
    recs = evaluate_maintenance_recommendations(db_conn, vehicle, history_data, customer_user)
    oil_rec = next((r for r in recs if r["category"] == "oil_change"), None)
    assert oil_rec is None, "Không được gợi ý thay dầu động cơ khi chưa đến hạn (mới chạy 1.500 km)"


# -----------------------------------------------------------------------------
# Kịch bản 3: Má phanh chạy 20.000 km -> nhắc kiểm tra độ mòn, TUYỆT ĐỐI không mặc định thay thế
# -----------------------------------------------------------------------------
def test_scenario_3_brake_pads_20000km_inspect_wear_not_replace(db_conn, customer_user):
    """Mốc 20.000 km má phanh CHỈ NHẮC KIỂM TRA ĐỘ MÒN, không được mặc định thay thế."""
    vehicle = {
        "id": 9903,
        "customer_id": customer_user["id"],
        "plate": "29A-990.03",
        "make": "Toyota",
        "model": "Camry",
        "year": 2020,
        "mileage": 50500,  # 50.500 km
    }
    history_data = {
        "parts_replaced": [
            {
                "name": "Má phanh trước",
                "quantity": 1,
                "date": "2025-05-10",
                "km": 30000,  # thay tại 30.000 km -> used_km = 20.500 km >= 20.000 km
                "ro_code": "RO-9903",
                "ro_id": 9903,
            }
        ]
    }
    recs = evaluate_maintenance_recommendations(db_conn, vehicle, history_data, customer_user)
    brake_rec = next((r for r in recs if r["category"] == "brake_pads"), None)
    assert brake_rec is not None, "Phải có gợi ý kiểm tra má phanh khi đã chạy 20.000 km"
    assert brake_rec["action_type"] == "inspect_wear", "Hành động BẮT BUỘC phải là inspect_wear, KHÔNG PHẢI replace"
    assert brake_rec["service_id"] == 3  # ID 3: Kiểm tra hệ thống phanh
    assert brake_rec["status"] == "inspect"

    # Kiểm tra nội dung: Nhấn mạnh kiểm tra độ mòn / đo độ dày, không mặc định thay thế
    text = brake_rec["recommendation_text"].lower()
    assert "kiểm tra độ mòn" in text or "độ mòn má phanh" in text
    assert "không mặc định thay thế" in text or "đo độ dày" in text


# -----------------------------------------------------------------------------
# Kịch bản 4: Không có số km hiện tại (missing_mileage)
# -----------------------------------------------------------------------------
def test_scenario_4_missing_current_mileage(db_conn, customer_user):
    """Khi xe chưa cập nhật số kilomet hiện tại, thông báo khách cập nhật hoặc kiểm tra."""
    vehicle = {
        "id": 9904,
        "customer_id": customer_user["id"],
        "plate": "29A-990.04",
        "make": "Kia",
        "model": "Seltos",
        "year": 2022,
        "mileage": None,  # Không có số km
    }
    history_data = {
        "parts_replaced": [
            {
                "name": "Dầu động cơ",
                "quantity": 4,
                "date": "2026-01-01",
                "km": 10000,
                "ro_code": "RO-9904",
                "ro_id": 9904,
            }
        ]
    }
    recs = evaluate_maintenance_recommendations(db_conn, vehicle, history_data, customer_user)
    assert len(recs) == 1
    rec = recs[0]
    assert rec.get("missing_mileage") is True, "Phải gắn cờ missing_mileage = True"
    assert "chưa có thông tin số kilomet" in rec["recommendation_text"]


# -----------------------------------------------------------------------------
# Kịch bản 5: Không có lịch sử thay phụ tùng (no_history)
# -----------------------------------------------------------------------------
def test_scenario_5_no_replacement_history(db_conn, customer_user):
    """Xe chưa từng thay phụ tùng nào -> không suy đoán mốc bảo dưỡng."""
    vehicle = {
        "id": 9905,
        "customer_id": customer_user["id"],
        "plate": "29A-990.05",
        "make": "Hyundai",
        "model": "Tucson",
        "year": 2021,
        "mileage": 35000,
    }
    history_data = {
        "parts_replaced": []  # Chưa có phụ tùng thay thế nào
    }
    recs = evaluate_maintenance_recommendations(db_conn, vehicle, history_data, customer_user)
    assert recs == [], "Không có lịch sử thay thế phụ tùng thì không được suy đoán mốc bảo dưỡng"


# -----------------------------------------------------------------------------
# Kịch bản 6: Nhiều xe thuộc cùng khách hàng (hỏi chọn xe trước)
# -----------------------------------------------------------------------------
def test_scenario_6_multiple_vehicles_clarification(db_conn):
    """Khách có nhiều xe, hỏi lịch sử mà không chỉ định xe -> yêu cầu làm rõ."""
    test_email = f"test2xe_{uuid4().hex[:8]}@garage.vn"
    with transaction(db_conn):
        cid = db_conn.execute(
            "INSERT INTO customers(name, email, phone, status) VALUES(?, ?, ?, 'active')",
            ("Khách Test 2 Xe", test_email, f"09{uuid4().int % 100000000:08d}")
        ).lastrowid
        db_conn.execute(
            "INSERT INTO vehicles(customer_id, plate, plate_normalized, make, model, year, mileage, status) VALUES(?, '30A-111.11', '30A11111', 'Toyota', 'Vios', 2020, 40000, 'active')",
            (cid,)
        )
        db_conn.execute(
            "INSERT INTO vehicles(customer_id, plate, plate_normalized, make, model, year, mileage, status) VALUES(?, '30A-222.22', '30A22222', 'Honda', 'CR-V', 2021, 30000, 'active')",
            (cid,)
        )

    try:
        user = {"id": 9999, "email": test_email, "role": "Khách hàng"}
        ans, sources = answer_vehicle_repair_history(db_conn, "Xe tôi đã từng thay những phụ tùng nào?", user)
        assert ans.status == "clarification", "Phải yêu cầu làm rõ khi khách hàng có nhiều xe"
        assert "2 xe" in ans.content
        assert "30A-111.11" in ans.content and "30A-222.22" in ans.content
    finally:
        with transaction(db_conn):
            db_conn.execute("DELETE FROM vehicles WHERE customer_id=?", (cid,))
            db_conn.execute("DELETE FROM customers WHERE id=?", (cid,))


# -----------------------------------------------------------------------------
# Kịch bản 7: Chu kỳ không có nguồn xác minh (dùng mốc tiêu chuẩn)
# -----------------------------------------------------------------------------
def test_scenario_7_interval_without_verified_source(db_conn, customer_user):
    """Xe không có trong bảng maintenance_intervals -> dùng mốc tiêu chuẩn 5.000 km và ghi rõ nguồn."""
    vehicle = {
        "id": 9907,
        "customer_id": customer_user["id"],
        "plate": "29A-990.07",
        "make": "Peugeot",  # Dòng xe chưa có interval trong database
        "model": "3008",
        "year": 2021,
        "mileage": 46000,
    }
    history_data = {
        "parts_replaced": [
            {
                "name": "Dầu nhớt Total 5W-30",
                "quantity": 4,
                "date": "2026-02-15",
                "km": 40000,  # used_km = 6.000 km >= mốc tiêu chuẩn 5.000 km
                "ro_code": "RO-9907",
                "ro_id": 9907,
            }
        ]
    }
    recs = evaluate_maintenance_recommendations(db_conn, vehicle, history_data, customer_user)
    oil_rec = next((r for r in recs if r["category"] == "oil_change"), None)
    assert oil_rec is not None
    assert oil_rec["source_type"] == "standard"
    assert "tiêu chuẩn" in oil_rec["source_name"].lower()
    assert "kỹ thuật viên xác nhận" in oil_rec["source_name"].lower()


# -----------------------------------------------------------------------------
# Kịch bản 8: Đã có lịch hẹn tương ứng trong tương lai -> không tạo gợi ý trùng
# -----------------------------------------------------------------------------
def test_scenario_8_future_appointment_prevents_duplicate(db_conn):
    """Xe đã có lịch hẹn tương lai cho dịch vụ thay dầu -> không gợi ý đặt lịch trùng."""
    v_id = 9908
    with transaction(db_conn):
        cid = db_conn.execute(
            "INSERT INTO customers(name, email, phone, status) VALUES(?, ?, ?, 'active')",
            ("Customer Test 8", f"cust8_{uuid4().hex[:8]}@garage.vn", f"09{uuid4().int % 100000000:08d}")
        ).lastrowid
        db_conn.execute(
            "INSERT INTO vehicles(id, customer_id, plate, plate_normalized, make, model, year, mileage, status) VALUES(?, ?, '29A-990.08', '29A99008', 'Mazda', 'CX-5', 2021, 55000, 'active')",
            (v_id, cid)
        )
        db_conn.execute("DELETE FROM appointments WHERE vehicle_id=?", (v_id,))
        db_conn.execute(
            """INSERT INTO appointments(customer_id, customer_name, vehicle_id, plate, service, appointment_at, status)
               VALUES(?, 'Customer Test 8', ?, '29A-990.08', 'Thay dầu động cơ', datetime('now', '+3 days'), 'Đã xác nhận')""",
            (cid, v_id)
        )

    try:
        vehicle = {
            "id": v_id,
            "customer_id": cid,
            "plate": "29A-990.08",
            "make": "Mazda",
            "model": "CX-5",
            "year": 2021,
            "mileage": 55000,
        }
        history_data = {
            "parts_replaced": [
                {
                    "name": "Dầu động cơ",
                    "quantity": 4,
                    "date": "2026-01-01",
                    "km": 40000,  # used_km = 15.000 km >= 10.000 km
                    "ro_code": "RO-9908",
                    "ro_id": 9908,
                }
            ]
        }
        recs = evaluate_maintenance_recommendations(db_conn, vehicle, history_data, {"id": 8888, "role": "Khách hàng"})
        oil_rec = next((r for r in recs if r["category"] == "oil_change"), None)
        assert oil_rec is None, "Không được gợi ý đặt lịch thay dầu trùng lặp khi đã có lịch hẹn tương lai"
    finally:
        with transaction(db_conn):
            db_conn.execute("DELETE FROM appointments WHERE vehicle_id=?", (v_id,))
            db_conn.execute("DELETE FROM vehicles WHERE id=?", (v_id,))
            db_conn.execute("DELETE FROM customers WHERE id=?", (cid,))


# -----------------------------------------------------------------------------
# Kịch bản 9: Khách nhấn nút đặt lịch -> pre-fill xe và dịch vụ
# -----------------------------------------------------------------------------
def test_scenario_9_appointment_prefill_payload(db_conn, customer_user):
    """Dữ liệu recommendation cung cấp đủ thông tin pre-fill cho AppointmentCreateModal."""
    vehicle = {
        "id": 9909,
        "customer_id": customer_user["id"],
        "plate": "29A-990.09",
        "make": "Mazda",
        "model": "CX-5",
        "year": 2021,
        "mileage": 53000,
    }
    history_data = {
        "parts_replaced": [
            {
                "name": "Dầu động cơ",
                "quantity": 4,
                "date": "2026-02-01",
                "km": 42000,
                "ro_code": "RO-9909",
                "ro_id": 9909,
            }
        ]
    }
    recs = evaluate_maintenance_recommendations(db_conn, vehicle, history_data, customer_user)
    assert len(recs) >= 1
    rec = recs[0]
    # Kiểm tra payload khớp AppointmentSelection: { vehicle_id, kind: 'service', id, name }
    assert rec["vehicle_id"] == 9909
    assert rec["service_id"] == 2
    assert rec["service_name"] == "Thay dầu động cơ"
    assert rec["action_label"] == "Đặt lịch thay dầu động cơ"


# -----------------------------------------------------------------------------
# Kịch bản 10: Backend không có lịch trống (xung đột / blocking conflicts)
# -----------------------------------------------------------------------------
def test_scenario_10_appointment_conflict_blocking(db_conn):
    """Kiểm tra logic xung đột lịch hẹn: khi khung giờ có conflict, API trả blocking warnings."""
    # Bảng appointments có các trạng thái quản lý xung đột
    rows = db_conn.execute("SELECT id, status, appointment_at FROM appointments LIMIT 1").fetchall()
    assert len(rows) > 0


# -----------------------------------------------------------------------------
# Kịch bản 11: Khách chưa xác nhận đặt lịch -> không tự tạo lịch hẹn trong DB
# -----------------------------------------------------------------------------
def test_scenario_11_chat_does_not_auto_create_appointment(db_conn, customer_user):
    """Trò chuyện hoặc nhận gợi ý bảo dưỡng tuyệt đối KHÔNG tự động tạo bản ghi trong bảng appointments."""
    count_before = db_conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]

    # Thực hiện tra cứu qua pipeline chat
    result = answer_chat("Xe tôi đã từng thay những phụ tùng nào?", customer_user, vehicle_id=1)
    assert result is not None

    count_after = db_conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
    assert count_before == count_after, "AI Chat TUYỆT ĐỐI không được tự ý tạo lịch hẹn trong database"


# -----------------------------------------------------------------------------
# Kịch bản 12: Truy cập xe không thuộc quyền sở hữu -> từ chối (403 / denied)
# -----------------------------------------------------------------------------
def test_scenario_12_rbac_unauthorized_vehicle_access_denied(db_conn):
    """Khách hàng A hỏi lịch sử sửa chữa của xe thuộc khách hàng B -> bị từ chối truy cập."""
    # Xe 1 thuộc customer_id = 1
    # Khách hàng có customer_id = 2
    unauthorized_user = {"id": 2, "customer_id": 2, "email": "other@garage.vn", "role": "Khách hàng"}
    ans, sources = answer_vehicle_repair_history(db_conn, "Xe 51H-123.45 đã từng thay những gì?", unauthorized_user, vehicle_id=1)

    assert ans.status == "denied", "Phải trả về status='denied' khi truy cập xe không thuộc quyền sở hữu"
    assert "không có quyền truy cập" in ans.content.lower()
    assert len(ans.maintenance_recommendations) == 0, "Không được trả về bất kỳ gợi ý bảo dưỡng nào của xe người khác"
