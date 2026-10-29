# Tên linh kiện có đối chiếu nguồn (29/10/2026)

`python -m backend.market_parts` xem trước; `python -m backend.market_parts --apply`
thêm 5 bản ghi **chưa kích hoạt**. Nhập lại không tạo trùng, không sửa dữ liệu hiện có.
`REF-` là mã nội bộ; mã sản phẩm thật được ghi trong tên, không phải mã OEM của xe.

| Linh kiện | Nguồn nhà sản xuất |
| --- | --- |
| Bridgestone Turanza T005A 205/55R16 | [Bridgestone Việt Nam](https://www.bridgestone.com.vn/en/tire/turanza-t005a/205-55r16) |
| Michelin Primacy 5 (chưa chọn kích thước) | [Michelin Việt Nam](https://www.michelin.vn/auto/tyres/michelin-primacy-5) |
| MANN-FILTER HU 716/2 x | [MANN-FILTER](https://www.mann-filter.com/uk-en/catalogue/search-results/product.html/hu716/2x_mann-filter.html) |
| OSRAM ORIGINAL PY21W 7507 | [OSRAM](https://www.osram.com/ecat/Lamps%20with%20metal%20bases-Signal%20lamps-Car%20lighting-Automotive/gb/en/GPS01_1057060/ZMP_60924) |
| NGK BKR6E-11 (2756) | [NGK](https://www.ngkntk.com/nordic/part-finder/motorcycles-scooter/spark-plugs/honda/gl-1800-a-gold-wing-sc47-bkr6e-11-6-1800-2001-2005) |

Nguồn xác nhận **sản phẩm tồn tại**, không chứng minh garage đã nhập hàng hoặc
được phân phối tại Việt Nam, giá hiện tại hay lắp vừa xe khách. Bản ghi có
`active=0`, `stock=0`, `sell_price=0`, không tạo phê duyệt giá hoặc quy tắc
`part_fitments`. Nhân viên chỉ kích hoạt sau khi xác minh nguồn cung, kiểm kê,
giá bán và ứng dụng theo VIN/đời/phiên bản/động cơ. Không đổi tên hàng `DEMO-*`
thành mã hãng: chúng vẫn là hàng minh họa, không phải SKU được xác minh.
