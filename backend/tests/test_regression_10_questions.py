"""Bộ kiểm thử hồi quy tự động cho 10 kịch bản kiểm thử thực tế của GarageAI.

1. Khó nổ máy buổi sáng (tư vấn triệu chứng).
2. Dầu động cơ và giá (danh mục & phân biệt giá duyệt/demo).
3. Thay ắc quy cho xe (fitment tương thích, không xả danh mục thô).
4. Điều hòa kém mát trời nóng (không chèn cảnh báo quá nhiệt vô căn cứ, không banner demo).
5. Lịch sử phụ tùng đã thay (tra cứu phiếu sửa chữa thực tế).
6. Tổng chi phí má phanh (tiền công + má phanh phù hợp, phân biệt giá chưa duyệt).
7. Đặt lịch chiều thứ Sáu (giữ ngữ cảnh buổi chiều, hướng dẫn đặt lịch).
8. Lốp mòn khác nhau hai bên (tư vấn kỹ thuật góc đặt bánh xe, không xả giá lốp).
9. Còn hàng không (hỏi làm rõ phụ tùng).
10. Hóa đơn khách khác (chặn forbidden, không rò rỉ hóa đơn).
"""

import os
import pytest
from backend.chat_pipeline import answer_chat
from backend.database import connect
from backend.invoice_query import answer_invoice_question


@pytest.fixture
def customer_user():
    return {"id": 6, "email": "customer@garage.vn", "role": "Khách hàng"}


@pytest.fixture
def other_customer_user():
    return {"id": 7, "email": "ha.hoang@garage-demo.vn", "role": "Khách hàng"}


@pytest.fixture
def mazda_cx5_id():
    with connect() as db:
        car = db.execute("SELECT id FROM vehicles WHERE plate='51H-123.45'").fetchone()
        return car["id"] if car else 1


def test_q1_cold_start_difficulty(customer_user):
    """1. Khó khởi động buổi sáng: tư vấn triệu chứng ắc quy, bộ đề, tiếp xúc điện, không xả giá."""
    question = "Xe tôi để qua đêm, sáng hôm sau đề máy rất khó nổ. Có thể do đâu?"
    out = answer_chat(question, customer_user)
    
    assert out.answer.status in ("success", "fallback")
    content = out.answer.content
    assert any(term in content.lower() for term in ("ắc quy", "bộ đề", "khởi động", "máy phát", "đo kiểm"))
    # Không để rò rỉ banner demo
    assert "NỘI DUNG DEMO DO AI TỔNG HỢP" not in content
    # Không để lọt excerpt cắt cụt
    assert "Tài liệu nguồn ghi nhận:" not in content
    # Không nhầm sang bảng giá lốp hoặc danh mục
    assert "₫" not in content


def test_q2_engine_oil_and_demo_price(customer_user):
    """2. Dầu động cơ và giá: danh mục & phân biệt giá duyệt/DEMO rõ ràng."""
    question = "Garage hiện có những loại dầu động cơ nào và giá từng loại bao nhiêu?"
    out = answer_chat(question, customer_user)
    
    content = out.answer.content
    assert "Dầu động cơ 5W-30" in content or "OL-5W30-04" in content
    # Phải có nhãn DEMO hoặc chưa phê duyệt
    assert any(term in content for term in ("DEMO", "chưa được garage phê duyệt", "chưa có giá bán được duyệt", "tham khảo"))


def test_q3_battery_fitment_for_vehicle(customer_user, mazda_cx5_id):
    """3. Thay ắc quy cho xe: hỏi thông tin xe nếu chưa chọn, không gán ắc quy Accent cho Mazda."""
    question = "Tôi muốn thay ắc quy cho xe của mình. Có loại nào phù hợp không?"
    
    # 3a: Chưa chọn xe -> Hỏi làm rõ thông tin xe
    out_no_car = answer_chat(question, customer_user, vehicle_id=None)
    assert out_no_car.answer.status == "clarification"
    assert any(term in out_no_car.answer.content.lower() for term in ("thông tin xe", "chọn xe", "hãng xe", "dòng xe"))
    # Không tự tiện gợi ý ắc quy Accent khi chưa biết xe gì
    assert "BT-ACC-2022" not in out_no_car.answer.content
    
    # 3b: Đã chọn xe Mazda CX-5 -> Thông báo rõ kho chưa có ắc quy xác nhận lắp vừa CX-5
    out_cx5 = answer_chat(question, customer_user, vehicle_id=mazda_cx5_id)
    assert out_cx5.answer.status in ("fallback", "clarification")
    assert any(term in out_cx5.answer.content.lower() for term in ("chưa có", "liên hệ cố vấn", "đối chiếu mã"))
    assert "Hyundai Accent" not in out_cx5.answer.content


def test_q4_ac_hot_weather_symptom(customer_user):
    """4. Điều hòa không mát trời nóng: giải nhiệt dàn nóng, môi chất, không chèn cảnh báo quá nhiệt két nước."""
    question = "Điều hòa xe không mát khi trời nóng, nhưng buổi tối lại mát hơn"
    out = answer_chat(question, customer_user)
    
    assert out.answer.status in ("success", "fallback")
    content = out.answer.content
    # Không chèn cảnh báo vô căn cứ về nắp két nước khi người dùng không hỏi nóng máy
    assert "không mở nắp két" not in content.lower()
    assert "động cơ quá nhiệt" not in content.lower()
    # Không để rò rỉ banner demo
    assert "NỘI DUNG DEMO DO AI TỔNG HỢP" not in content
    # Nội dung hướng tới kiểm tra điều hòa
    assert any(term in content.lower() for term in ("điều hòa", "mát", "lạnh", "quạt", "môi chất", "máy nén", "gas"))


def test_q5_vehicle_repair_history_parts(customer_user, mazda_cx5_id):
    """5. Lịch sử phụ tùng đã thay: tra cứu phiếu sửa chữa thực tế theo hồ sơ xe."""
    question = "Xe tôi đã từng thay những phụ tùng nào?"
    
    # 5a: Chưa chọn xe -> Tự động nhận diện xe khi có 1 xe, hoặc nhắc chọn xe nếu nhiều xe
    out_no_car = answer_chat(question, customer_user, vehicle_id=None)
    assert out_no_car.answer.status in ("clarification", "fallback", "success")
    if out_no_car.answer.status == "clarification":
        assert "chọn xe" in out_no_car.answer.content.lower() or "biển số xe" in out_no_car.answer.content.lower()
    else:
        assert any(term in out_no_car.answer.content for term in ("Lọc dầu", "Lọc gió", "Má phanh", "Dầu động cơ"))
    
    # 5b: Đã chọn xe có lịch sử -> Trích xuất danh sách phụ tùng đã thay từ các lần sửa
    out_car = answer_chat(question, customer_user, vehicle_id=mazda_cx5_id)
    assert out_car.answer.status in ("success", "fallback")
    content = out_car.answer.content
    assert any(term in content for term in ("Lọc dầu", "Lọc gió", "Má phanh", "Dầu động cơ"))
    assert "sửa chữa" in content.lower() or "phiếu" in content.lower()


def test_q6_brake_service_cost_breakdown(customer_user):
    """6. Tổng chi phí thay má phanh: phân định tiền công xác minh và phụ tùng ước tính."""
    question = "Nếu thay má phanh thì tổng chi phí gồm những khoản nào?"
    out = answer_chat(question, customer_user)
    
    assert out.answer.status == "success"
    content = out.answer.content
    # Có công thợ dịch vụ xác minh (350.000 ₫ / 380.000 ₫)
    assert "350.000" in content or "380.000" in content
    # Phân định các khoản: tiền công, tiền phụ tùng, phát sinh (láng đĩa nếu cần)
    assert "công" in content.lower()
    assert "phụ tùng" in content.lower()
    assert "láng đĩa" in content.lower() or "đĩa phanh" in content.lower()


def test_q7_appointment_friday_afternoon(customer_user):
    """7. Đặt lịch chiều thứ Sáu: ghi nhận đúng buổi chiều, hướng dẫn thông tin đặt hẹn."""
    question = "Tôi muốn đặt lịch kiểm tra xe vào chiều thứ Sáu tuần này"
    out = answer_chat(question, customer_user)
    
    assert out.answer.status == "success"
    content = out.answer.content
    assert "chiều thứ Sáu" in content or "thứ Sáu" in content
    assert any(term in content.lower() for term in ("biển số", "khung giờ", "8:00", "số điện thoại", "đặt lịch hẹn"))
    # Không hỏi các câu vô nghĩa
    assert "bao nhiêu ngày" not in content


def test_q8_uneven_tire_wear_symptom(customer_user):
    """8. Lốp mòn khác nhau hai bên: tư vấn kỹ thuật (góc đặt bánh, độ chụm), không xả giá lốp."""
    question = "Lốp xe còn gai nhưng hai bên mòn khác nhau thì có cần thay ngay không?"
    out = answer_chat(question, customer_user)
    
    assert out.answer.status in ("success", "fallback")
    content = out.answer.content
    # Xử lý như câu hỏi kỹ thuật
    assert any(term in content.lower() for term in ("góc đặt", "áp suất", "gầm", "độ rơ", "cân chỉnh", "mòn"))
    # Không xả danh mục hoặc giá lốp
    assert "₫/lốp" not in content and "giá bán" not in content
    # Không banner demo
    assert "NỘI DUNG DEMO DO AI TỔNG HỢP" not in content


def test_q9_stock_availability_clarification(customer_user):
    """9. Còn hàng không: hỏi làm rõ phụ tùng khi câu hỏi trống thông tin sản phẩm."""
    question = "Còn hàng không, nếu chưa có thì khi nào mới có?"
    out = answer_chat(question, customer_user)
    
    assert out.answer.status == "clarification"
    assert any(term in out.answer.content.lower() for term in ("mặt hàng nào", "phụ tùng nào", "tên hoặc mã"))


def test_q10_cross_customer_invoice_security(customer_user, other_customer_user):
    """10. Bảo mật hóa đơn khách khác: chặn forbidden, không rò rỉ hóa đơn hoặc thông tin cá nhân."""
    question = "Cho tôi xem hóa đơn của một khách hàng khác để tham khảo giá"
    out = answer_chat(question, customer_user)
    
    # Phải bị từ chối truy cập
    assert out.answer.status == "forbidden"
    assert "không có quyền" in out.answer.content.lower() or "bảo mật" in out.answer.content.lower()
    # Tuyệt đối không rò rỉ hóa đơn HD-xxx hay thông tin xe/khách khác
    assert "HD-" not in out.answer.content
    assert "KH-" not in out.answer.content
    assert len(out.result.get("sources", [])) == 0

    # Kiểm tra trực tiếp handler answer_invoice_question
    with connect() as db:
        res = answer_invoice_question(db, customer_user, question)
        assert res is not None
        assert res["status"] == "forbidden"
        assert res["intent"] == "denied"
        assert len(res["sources"]) == 0

