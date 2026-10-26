# Đối chiếu nguồn cho 100 bản nháp kỹ thuật

Ngày truy cập: 26/10/2026. Đây không phải danh sách 100 bài đã được xác minh. **Không tự gắn một trang tổng quát cho nhiều bài chuyên sâu** nếu trang không chứng minh được các nhận định cụ thể.

## Đợt đầu: đã đối chiếu trực tiếp nguồn Bosch (3/100)

| Bài | Nguồn đã đọc | Phần liên quan |
| --- | --- | --- |
| Xe lệch về một bên khi phanh | [Bosch Car Service — Brake Repair & Maintenance](https://ap.boschcarservice.com/in/en/car-services/car-brake-service/brake-repair-and-maintenance) | FAQ xe lệch khi phanh: kẹp phanh, má, đĩa và lốp |
| Vô lăng rung khi đạp phanh | [Bosch Car Service — Brake Repair & Maintenance](https://ap.boschcarservice.com/in/en/car-services/car-brake-service/brake-repair-and-maintenance) | FAQ rung khi phanh: đĩa và các thành phần hệ phanh |
| Má phanh mòn không đều giữa hai bên | [Bosch Car Service — Brake Repair & Maintenance](https://ap.boschcarservice.com/in/en/car-services/car-brake-service/brake-repair-and-maintenance) | Kiểm tra mòn má/đĩa, kẹp phanh và rò; không thay theo phỏng đoán |

Chi tiết dấu vết nằm ở `backend/technical_source_reviews.py`. ID 28 và 29 đã được duyệt/xuất bản ngày 26/10/2026; bài ID 34 vẫn là nháp.

## Nguồn ứng viên đã đọc nhưng **chưa** đối chiếu từng bài

- [Car Care Council — Car Care Guide](https://www.carcare.org/car-care-resources/car-care-guide): bảo dưỡng tổng quát, làm mát, điện/ắc quy, lốp và phanh; phần trang web là tóm tắt, không chứng minh chi tiết chẩn đoán cho mọi bài.
- [Car Care Council — Vehicle Systems Overview](https://www.carcare.org/vehicle-systems-overview): danh mục hệ thống và mốc kiểm tra tổng quát; không phải quy trình sửa chữa theo VIN.
- [Bosch Car Service — Vehicle maintenance](https://ap.boschcarservice.com/in/en/car-services/car-inspection-and-checks/car-periodic-maintenance): danh mục kiểm tra theo hệ thống và nguyên tắc lịch bảo dưỡng theo xe; không thay thông số hãng.

Nguồn tìm thấy qua công cụ tìm kiếm nhưng không đọc được nội dung đầy đủ ở môi trường hiện tại (403); **chưa** dùng để xác minh bài: [NHTSA TireWise](https://www.nhtsa.gov/vehicle-safety/tires), [Bridgestone Tire Cupping](https://www.bridgestonetire.com/learn/maintenance/tire-cupping), các bài mã lỗi trên [OBD-Codes](https://www.obd-codes.com/). Không tự tạo PDF/DOCX từ nội dung của chính bài và gọi đó là nguồn độc lập.

## Trạng thái

Đợt đầu có 3 bài nguồn Bosch; cả ID 28, 29 và 34 hiện đã xuất bản. Sau đó ID 104, 107, 108 được bổ sung nguồn độc lập và xuất bản. Ngày 26/10/2026, 94 bài còn lại được xuất bản riêng dưới nhãn **DEMO AI chưa xác minh** để trình diễn RAG; thao tác này không biến nguồn ứng viên thành nguồn đã xác minh.

## File đối chiếu 97 bài còn lại

[`TECHNICAL_SOURCE_MATRIX_97.csv`](TECHNICAL_SOURCE_MATRIX_97.csv) có **đúng 97 dòng bài** (không tính header), ID/nhóm/tiêu đề theo database, tên và URL ứng viên, mục/trang liên quan, SHA-256 của tài liệu đã đọc, tình trạng truy cập liên kết bổ sung và giới hạn cần xác minh. Tạo lại bằng `python -X utf8 create_technical_source_matrix.py`; script kiểm tra tiêu đề/trạng thái/nguồn trong database nhưng **không ghi database**. Phân bổ: động cơ 15, phanh 9, lái 12, điện 15, hộp số 10, điều hòa 8, bảo dưỡng 12, lốp 6, mã lỗi 5, quy trình 5.

Trong đó 92 bài có mục/trang kỹ năng phù hợp trong [ASE — Automobile Study Guide ©2026](https://www.ase.com/wp-content/uploads/ASE_Automobile_Study_Guide.pdf) (56 trang; SHA-256 `3A5A4F364498D681BBF320ED9227DEA5C3BB05AE1F3EAB3FBA6DB4F624F34B25`). Đây **chỉ là đối chiếu chủ đề**, không có nghĩa đã xác minh toàn bộ câu chữ của bài. ID 104, 107 và 108 có nguồn độc lập trong `backend/pending_publish_source_reviews.py`; các dòng khác có trạng thái `published — DEMO AI chưa xác minh` khi phù hợp. Liên kết chỉ tìm được qua trích đoạn/403 không được xem là đã đối chiếu. Mã P0xxx và an toàn cao áp vẫn phải tuân thủ giới hạn xe/VIN ghi trong nguồn.
