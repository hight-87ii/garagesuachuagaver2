# Danh mục mẫu mở rộng (tham khảo tháng 10/2026)

Khởi động backend chạy `init_db()` để thêm **50 dịch vụ** mở rộng. Nhóm **197 phụ tùng `DEMO-*`/`(mẫu)` đã bị xóa** và không còn được tạo lại. Với cơ sở dữ liệu đã vận hành, tổng số dịch vụ có thể khác vì dữ liệu người dùng đã chỉnh sửa.

Nếu chỉ muốn nạp danh mục vào database hiện có mà không chạy các seed khác: `python -m backend.catalog_expansion` (dùng `DATABASE_PATH` nếu database nằm ở đường dẫn khác). Để **gán giả lập 5 đơn vị cho mọi mặt hàng đang có `stock=0` đúng một lần**, chạy `python -m backend.catalog_expansion --fill-demo-stock`. Lệnh giữ nguyên mọi số lượng đang dương; không tự chạy khi khởi động để tránh tái tạo hàng đã bán hết.

Nhóm: bảo dưỡng định kỳ, động cơ/làm mát, phanh, gầm–lốp, hộp số, điện–ắc quy, điều hòa, chẩn đoán, chăm sóc xe; các loại lọc, phanh, treo, điện động cơ, gạt mưa, dầu nhớt và vật tư tiêu hao. Giá niêm yết mẫu là **VND, giá một đơn vị**, không phải bảng giá đã xác nhận cho garage. Dịch vụ mới tính **công**, chưa gồm phụ tùng và dung dịch; không cộng thêm riêng một công việc nếu đã nằm trong gói bảo dưỡng. Thời gian chỉ là ước tính, không cam kết thời điểm giao xe.

Nguồn đối chiếu công khai:

- [Gara Ô Tô Mỹ Đình THC – bảng giá công bảo dưỡng/sửa chữa 08/2026](https://otomydinhthc.com/bang-gia-dich-vu-sua-chua-o-to/): liệt kê công bảo dưỡng định kỳ, thay lọc/dầu, phanh, gầm, điện và nêu rõ **chưa gồm phụ tùng**. Dùng để chọn nhóm nghiệp vụ và tham khảo cỡ giá công, không sao chép toàn bộ bảng giá.
- [NATcenter – chi phí bảo dưỡng 2026](https://natcenter.vn/chi-phi-bao-duong-xe-o-to/): khoảng giá bán lẻ lọc (100.000–1.500.000đ tùy loại), má/đĩa phanh, ắc quy (800.000–3.500.000đ), dầu/phụ tùng và điều hòa. Các giá mặt hàng demo được ước tính trong hoặc gần các khoảng công khai, không phải giá được nguồn xác nhận cho từng mẫu xe.
- [Bài đăng Hà Thành Garage trên Facebook về mốc bảo dưỡng 5.000 km](https://www.facebook.com/hathanhgarage.campha2/posts/c%C3%A1c-m%E1%BB%91c-b%E1%BA%A3o-d%C6%B0%E1%BB%A1ng-xe-b%E1%BA%A3o-d%C6%B0%E1%BB%A1ng-m%E1%BB%91c-5000km-r%E1%BA%A5t-nhi%E1%BB%81u-b%C3%A1c-%C4%91%E1%BA%B7t-c%C3%A2u-h%E1%BB%8Fi-h%C3%A0-th%C3%A0nh-gar/1259539346308822/): bài công khai qua tìm kiếm đề cập kiểm tra má phanh, áp suất lốp, độ rơ vô lăng, đầu cực ắc quy. Facebook không cho đọc đầy đủ nội dung trực tiếp; **không dùng bài đăng này làm chứng cứ cho giá cụ thể**.

**Trước khi báo giá hoặc lắp đặt:** nhân viên cần xác nhận giá thực tế, loại dầu/gas, kích thước, mã phụ tùng, đời xe/động cơ/VIN và nguồn cung. `DEMO-*` chỉ là mã nội bộ minh họa, không phải mã hãng hoặc chứng nhận lắp vừa. Trường `compatible` chỉ gợi ý tìm kiếm; không tạo `part_fitments` đã xác minh. Giá vốn bằng 0; **tồn kho khởi tạo 5 và ngưỡng 3 là dữ liệu giả lập**, không xác nhận hàng đang có sẵn. Cần kiểm kê/nhập kho thực tế trước khi vận hành thật. Giá và nguồn tham khảo có thể thay đổi theo thời gian, vùng và chất lượng phụ tùng.
