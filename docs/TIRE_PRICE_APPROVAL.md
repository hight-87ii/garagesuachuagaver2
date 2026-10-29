# Giá lốp trong chat

- Chat đọc `parts` tại thời điểm hỏi, chỉ công bố giá bán của mặt hàng `active=1`
  có bản ghi `part_price_approvals` khớp chính xác với `parts.sell_price`.
- Migration 027 chỉ tạo bảng duyệt và trigger hủy duyệt khi giá thay đổi;
  **không tự duyệt bất cứ giá cũ nào**, không sửa giá/tồn kho. Mã `DEMO-`,
  mặt hàng `(mẫu)` và nhà cung cấp `Danh mục mẫu` không được chat báo giá.
- Hiện chưa có quy trình/phân quyền giao diện để quản lý duyệt giá. Trước khi
  triển khai bán hàng, cần thiết kế thao tác duyệt chỉ cho người có quyền, xác
  minh nguồn giá thật và lưu audit. Không duyệt hàng loạt giá tồn tại trước đây.
- Nếu database chưa có mặt hàng lốp đúng kích thước/thương hiệu, chatbot chỉ
  thông báo thiếu sản phẩm và hỏi thông tin cần thiết; không dùng giá của hạng
  mục khác thuộc nhóm “Gầm - lốp”. Hãng/dòng xe chưa đủ chứng minh kích thước
  lốp hay lắp vừa. Giá lốp riêng không phải tổng chi phí thay lốp.
- Khi hỏi giá lốp, backend truy vấn và lọc DB trước theo vai trò/quyền, chỉ tạo snapshot
  gồm mặt hàng đã duyệt (tên, mã, kích thước, đơn vị, giá) rồi gửi snapshot đó cho Ollama
  cùng prompt theo vai trò Khách hàng/Lễ tân/Kỹ thuật viên/Thu ngân/Quản lý/Admin. Ollama
  chỉ diễn đạt; backend vẫn giữ nguyên số tiền và loại bỏ các trường snapshot nội bộ khỏi
  response công khai. Model không được tự thêm giá, tồn kho hoặc xác nhận lắp vừa.
- Trước khi khởi động lại backend production, sao lưu database và lên kế hoạch
  áp dụng migration 027. Các bài test dùng SQLite tạm, không ghi vào DB đang chạy.
