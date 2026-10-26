from publish_demo_technical_articles import (
    DEMO_NOTICE, DEMO_SOURCE, DEMO_VERSION, build_demo_item, is_complete_demo,
)


def sample_row(**overrides):
    row = {
        "id": 9001,
        "title": "Phanh có tiếng bất thường khi giảm tốc",
        "symptoms": "phanh kêu, tiếng ở bánh xe",
        "content": (
            "Câu hỏi cần làm rõ: Tiếng xuất hiện ở tốc độ nào?\n\n"
            "Khả năng cần phân biệt: Má, đĩa hoặc chi tiết lắp ghép cần được kiểm tra.\n\n"
            "Kiểm tra thực tế: Quan sát từng bánh và đo kiểm theo tài liệu xe.\n\n"
            "Hướng xử lý khi có căn cứ: Chỉ xử lý bộ phận đã xác nhận bất thường.\n\n"
            "An toàn: Không thử phanh gấp trên đường công cộng."
        ),
        "safety": "Không thử phanh gấp trên đường công cộng.",
        "source_name": "Chưa xác minh — cần tài liệu theo VIN",
        "source_url": "", "document_version": "", "vehicle_make": "",
        "vehicle_model": "", "year_from": None, "year_to": None,
        "engine_code": "", "safety_level": "medium", "revision": 1,
    }
    row.update(overrides)
    return row


def test_build_demo_item_has_required_structure_and_warning():
    item = build_demo_item(sample_row())
    assert item.source_name == DEMO_SOURCE and item.source_url == ""
    assert item.document_version == DEMO_VERSION and item.safety_level == "high"
    assert DEMO_NOTICE in item.content
    for heading in ("Câu hỏi cần làm rõ:", "Các nguyên nhân có thể cần kiểm tra:",
                    "Quy trình kiểm tra theo thứ tự:", "Hướng xử lý có điều kiện:",
                    "Cảnh báo an toàn:", "Phạm vi áp dụng:", "Ghi chú giới hạn:"):
        assert heading in item.content
    assert "Kỹ thuật viên phải kiểm tra trực tiếp" in item.content
    saved = sample_row(content=item.content, safety=item.safety, source_name=item.source_name,
                       source_url=item.source_url, document_version=item.document_version,
                       safety_level=item.safety_level)
    assert is_complete_demo(saved)


def test_demo_content_remains_specific_to_article():
    first = build_demo_item(sample_row())
    second = build_demo_item(sample_row(title="Túi khí báo lỗi sau khi khởi động",
                                        symptoms="đèn SRS sáng", revision=4))
    assert first.content != second.content
    assert "Phanh có tiếng bất thường" in first.content
    assert "Túi khí báo lỗi" in second.content
    assert second.safety_level == "high"
