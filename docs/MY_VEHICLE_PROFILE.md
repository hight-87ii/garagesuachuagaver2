# Hồ sơ “Xe của tôi”

- `GET /api/v1/my-vehicles` trả `profile` (nếu chưa có: `{}`), lịch sử theo đúng `vehicle_id`, chi tiết dịch vụ/phụ tùng và mã báo giá/hóa đơn gắn phiếu. Khách chỉ thấy xe thuộc hồ sơ của mình.
- `PATCH /api/v1/my-vehicles/{id}/profile` cho chủ xe bổ sung màu, km, năm đăng ký, loại xe, số chỗ/cửa và hạn giấy tờ; không nhận VIN, biển số hay thông số kỹ thuật. Km mới không được thấp hơn km hiện tại hoặc km cao nhất trong lịch sử. Ngày nhập chỉ là thông tin do khách khai báo, không phải xác minh giấy tờ.
- `PATCH /api/v1/vehicles/{id}/profile` cho Admin/Quản lý/Kỹ thuật viên có quyền xe bổ sung thông số kỹ thuật và mốc bảo dưỡng. Mốc bảo dưỡng cần `maintenance_source`; không tự sinh chu kỳ từ hãng/dòng xe. Không lưu tệp giấy tờ hoặc ảnh xe.
- Migration `028_vehicle_profiles` tạo bảng `vehicle_profiles`, giữ nguyên bảng `vehicles` và toàn bộ dữ liệu lịch sử. `029` chỉ đảm bảo cột `maintenance_items`, **không chỉnh sửa** số km, phiếu, hóa đơn hay mô tả lịch sử. Không backfill giá trị chưa xác minh. VIN đang được dùng như định danh số khung; **số máy** chưa có cột xác thực và hiển thị “Chưa cập nhật”.

## Đối chiếu dữ liệu cũ

Kiểm tra bản ghi xe `20C-189.56` trong database hiện tại: `vehicles.mileage=61240`, không phải 45.400; phiếu ngày 20/10/2026 có 45.400 km, nhưng lịch sử ngày 28/09/2026 có 47.500 km. Các phiếu seed dùng mẫu chung gồm “Bugi Kia Seltos”, “Lọc dầu Mazda”, “Má phanh trước Toyota” cho Ford Ranger. Đây là dữ liệu đã lưu, **không tự sửa** do có thể liên quan báo giá, hóa đơn và thanh toán. Giao diện cảnh báo khi km lịch sử giảm hoặc mô tả nhắc hãng khác có trong hồ sơ xe. Cần người quản lý đối chiếu và hiệu đính theo quy trình nghiệp vụ riêng. Nếu migration 029 từng chạy ở phiên bản sửa dữ liệu trước đây, cần đối chiếu bản sao lưu để xác định dữ liệu đã bị đổi; bản sửa này không tự khôi phục lịch sử.

Hồ sơ hiện chưa có lịch bảo dưỡng hãng/OEM xác minh theo VIN, kết quả kiểm tra riêng cho mọi phiếu, ảnh xe, tệp giấy tờ và số máy. Giao diện giữ “Chưa cập nhật”/“Chưa đủ dữ liệu” thay vì suy đoán. Lịch dự kiến không phải lịch hẹn được xác nhận.
