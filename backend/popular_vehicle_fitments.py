"""Bảng tra cứu phụ tùng chi tiết (part_fitments) cho các dòng xe phổ biến tại Việt Nam.

Cung cấp dữ liệu kỹ thuật chuẩn xác, đối chiếu theo từng dòng xe, khoảng năm sản xuất,
mã động cơ, phiên bản và ghi chú kỹ thuật để phục vụ khách hàng tra cứu tương thích.
"""

from __future__ import annotations

import sqlite3

# Danh mục phụ tùng chất lượng cao bổ sung cho các dòng xe phổ biến
# code, name, category, compatible, unit, cost_price, sell_price, stock, min_stock, supplier,
# compatibility_accuracy, usage_requirements, price_note, supplier_note,
# technical_description, technical_specs, usage_instructions
POPULAR_PARTS = [
    # --- ẮC QUY ---
    (
        "BT-GS-45L",
        "Ắc quy GS 12V 45Ah 46B24LS",
        "Điện - ắc quy",
        "Toyota Vios, Yaris, Honda City, Honda CR-V, Mitsubishi Xpander, Attrage",
        "bình",
        950000,
        1250000,
        12,
        4,
        "GS Battery Việt Nam",
        "Đã xác minh theo chuẩn cọc nổi JIS L (trái), kích thước khay 238x129x227mm.",
        "Kiểm tra điện áp trước khi lắp, vệ sinh sạch đầu cọc và bôi mỡ bảo quản chống oxy hóa.",
        "Giá bán đã bao gồm VAT và thu hồi bình cũ theo chính sách của garage.",
        "Bảo hành chính hãng 09 tháng kể từ ngày lắp đặt.",
        "Ắc quy miễn bảo dưỡng (MF) công nghệ chì-axit cao cấp, dòng phóng khởi động ổn định.",
        "Điện áp danh định: 12V; Dung lượng: 45Ah; Dòng khởi động nguội CCA: 430A; Chuẩn cọc: L (cọc nổi).",
        "Lắp cố định thanh kẹp bình, siết chặt ốc cọc dương trước cọc âm sau, kiểm tra hệ thống sạc máy phát sau lắp.",
    ),
    (
        "BT-DIN-60L",
        "Ắc quy GS/Varta 12V 60Ah DIN60L",
        "Điện - ắc quy",
        "Kia Seltos, Kia Cerato, Kia K3, Hyundai Tucson (xăng), Hyundai Elantra",
        "bình",
        1180000,
        1550000,
        8,
        3,
        "Varta Battery Việt Nam",
        "Chuẩn kích thước DIN cọc chìm tiêu chuẩn châu Âu/Hàn Quốc (242x175x175mm).",
        "Đối chiếu đúng loại cọc chìm DIN và chiều cao khay 175mm trước khi siết giá đỡ.",
        "Giá bán niêm yết đã bao gồm công đo kiểm máy phát và công thay thế tại garage.",
        "Bảo hành chính hãng 12 tháng.",
        "Ắc quy khô miễn bảo dưỡng chuẩn DIN, chống rung lắc và khả năng phóng điện sâu.",
        "Điện áp danh định: 12V; Dung lượng: 60Ah; Dòng khởi động nguội CCA: 540A; Chuẩn cọc: DIN cọc chìm.",
        "Lắp đặt theo đúng thứ tự cực, siết chặt ngàm cố định đáy bình DIN, kiểm tra rò rỉ điện tĩnh sau khi tắt máy.",
    ),
    (
        "BT-DIN-75L",
        "Ắc quy Varta/GS 12V 75Ah DIN75L",
        "Điện - ắc quy",
        "Ford Ranger, Ford Everest, Hyundai Santa Fe, Toyota Fortuner (dầu), Kia Sorento",
        "bình",
        1520000,
        1950000,
        6,
        2,
        "Varta Battery Việt Nam",
        "Chuẩn DIN cọc chìm cỡ lớn (278x175x190mm) chịu tải cao cho động cơ diesel và xe gầm cao.",
        "Kiểm tra cảm biến dòng ắc quy (BMS/IBS) và thực hiện reset cảm biến sau khi thay trên xe Ford.",
        "Giá bán chính thức đã phê duyệt, áp dụng cho toàn hệ thống.",
        "Bảo hành chính hãng 12 tháng.",
        "Ắc quy công nghệ PowerFrame chống ăn mòn cực bản, cung cấp dòng khởi động mạnh mẽ cho máy dầu.",
        "Điện áp: 12V; Dung lượng: 75Ah; Dòng khởi động CCA: 680A; Kích thước: 278 x 175 x 190 mm.",
        "Sử dụng thiết bị nuôi nguồn OBD-II khi tháo bình cũ để không mất cài đặt hộp điều khiển xe.",
    ),

    # --- LỌC DẦU ĐỘNG CƠ ---
    (
        "OF-TOY-001",
        "Lọc dầu động cơ Toyota 90915-YZZE2",
        "Lọc - dầu",
        "Toyota Vios, Corolla Cross, Corolla Altis, Camry, Innova, Fortuner (xăng), Yaris",
        "cái",
        85000,
        150000,
        40,
        10,
        "Toyota Parts Việt Nam",
        "Mã OEM chính hãng Denso/Toyota 90915-YZZE2 / 90915-10003.",
        "Bôi một lớp dầu động cơ sạch lên gioăng cao su trước khi vặn; siết lực 14-16 Nm.",
        "Giá bán lẻ đã được phê duyệt.",
        "Hàng chính hãng Toyota Nhật Bản / Thái Lan.",
        "Lọc dầu dạng cốc xoay ren với màng lọc xếp nếp vi sợi tổng hợp, van an toàn chống tụt áp.",
        "Ren bắt: 3/4-16 UNF; Đường kính ngoài: 65 mm; Chiều cao: 88 mm; Gioăng cao su chịu nhiệt NBR.",
        "Xả hết dầu cũ, thay long đền ốc xả đáy, lắp lọc mới vặn tay tới khi gioăng tiếp xúc rồi siết thêm 3/4 vòng.",
    ),
    (
        "OF-HON-001",
        "Lọc dầu động cơ Honda 15400-RAF-T01",
        "Lọc - dầu",
        "Honda City, Honda CR-V, Honda Civic, Honda HR-V, Honda Accord",
        "cái",
        95000,
        160000,
        30,
        8,
        "Honda Parts Việt Nam",
        "Mã phụ tùng OEM chuẩn 15400-RAF-T01 / 15400-RTA-003 cho động cơ L-series và R-series.",
        "Dùng tay hoặc khẩu chụp tháo lọc chuyên dụng đường kính 65mm 14 rãnh.",
        "Giá niêm yết đã phê duyệt.",
        "Nhập khẩu chính hãng Honda Motors.",
        "Lọc cốc kim loại tích hợp van một chiều silicone chịu nhiệt độ cao ngăn dầu chảy ngược về các-te.",
        "Ren bắt: M20 x 1.5; Đường kính ngoài: 65 mm; Chiều cao: 85 mm.",
        "Bôi dầu mỏng lên ron cao su trước khi lắp, châm dầu động cơ đủ mức quy định và nổ máy kiểm tra rò rỉ.",
    ),
    (
        "OF-HY-001",
        "Lọc dầu Hyundai / Kia 26300-35505",
        "Lọc - dầu",
        "Hyundai Accent, Tucson (xăng), Grand i10, Elantra, Kia Seltos, Cerato, K3, Morning",
        "cái",
        80000,
        140000,
        35,
        10,
        "Mobis Auto Parts",
        "Mã OEM chuẩn Hyundai Mobis 26300-35505 / 26300-35504.",
        "Thay thế định kỳ sau mỗi 10.000 km hoặc sau mỗi 2 lần thay dầu máy.",
        "Giá bán lẻ chính thức đã duyệt.",
        "Nhập khẩu chính hãng Hyundai Mobis Hàn Quốc.",
        "Lọc dầu chất lượng cao đạt chuẩn OE, lưu lượng tuần hoàn dầu tối ưu cho động cơ Kappa, Gamma và Nu.",
        "Ren bắt: M20 x 1.5; Đường kính ngoài: 80 mm; Chiều cao: 75 mm.",
        "Vặn chặt đúng mô-men xoắn, kiểm tra đèn báo áp suất dầu trên bảng đồng hồ tắt sau 2 giây nổ máy.",
    ),
    (
        "OF-MIT-001",
        "Lọc dầu Mitsubishi 1230A182",
        "Lọc - dầu",
        "Mitsubishi Xpander, Outlander, Attrage, Mirage",
        "cái",
        90000,
        155000,
        25,
        6,
        "Mitsubishi Motors Việt Nam",
        "Mã OEM 1230A182 / MD135737 chuẩn xác cho động cơ MIVEC 1.2L, 1.5L, 2.0L, 2.4L.",
        "Kiểm tra không để dính ron cũ trên thân động cơ trước khi lắp lọc mới.",
        "Giá bán lẻ đã phê duyệt.",
        "Nhập khẩu chính hãng Mitsubishi.",
        "Lọc dầu kết cấu vỏ thép dập sâu chịu áp suất cao, màng lọc giấy phenolic lọc sạch hạt kim loại >20 micron.",
        "Ren: M20 x 1.5; Đường kính: 68 mm; Chiều cao: 85 mm.",
        "Lắp ráp nhẹ nhàng tránh biến dạng ren, châm dầu và kiểm tra mức dầu trên que thăm ở vị trí MAX.",
    ),

    # --- LỌC GIÓ ĐỘNG CƠ ---
    (
        "AF-MAZ-CX5",
        "Lọc gió động cơ Mazda PE07-13-3A0A",
        "Lọc - dầu",
        "Mazda CX-5 (2017-2024), Mazda 3 (2015-2024), Mazda 6 (2015-2024)",
        "cái",
        180000,
        290000,
        18,
        5,
        "VinaMazda Parts",
        "Chuẩn kích thước hộp lọc động cơ SkyActiv-G 2.0L và 2.5L.",
        "Kiểm tra gioăng cao su viền lọc ôm khít rãnh hộp lọc trước khi cài chốt.",
        "Giá bán đã phê duyệt.",
        "Phụ tùng chính hãng Mazda.",
        "Màng lọc không khí đa lớp có lớp tĩnh điện bắt giữ bụi siêu nhỏ, bảo vệ cảm biến MAF.",
        "Kích thước: 270 x 180 x 42 mm; Chất liệu: Sợi cellulose tổng hợp kết hợp gioăng viền đúc nguyên khối.",
        "Tháo nẹp lò xo hộp lọc gió, hút bụi bên trong đáy hộp trước khi đặt tấm lọc mới, cài chặt các ngàm gài.",
    ),
    (
        "AF-HON-CIT",
        "Lọc gió động cơ Honda City 17220-55A-Z01",
        "Lọc - dầu",
        "Honda City (2014-2024)",
        "cái",
        160000,
        260000,
        16,
        4,
        "Honda Parts Việt Nam",
        "Chuẩn mã 17220-55A-Z01 cho dòng xe Honda City thế hệ GM6 và GN2.",
        "Vệ sinh sạch cặn bụi lá cây trong cổ hút và đáy hộp gió trước khi lắp.",
        "Giá niêm yết đã phê duyệt.",
        "Nhà cung cấp phụ tùng Honda chính hãng.",
        "Tấm lọc gió động cơ dạng phẳng viền nhựa đúc, xếp nếp đều đặn giúp lưu lượng khí nạp thông suốt.",
        "Kích thước: 200 x 142 x 45 mm; Màu sắc màng lọc: Trắng sợi tổng hợp.",
        "Đặt đúng chiều mũi tên luồng khí, đóng chặt nắp hộp gió và siết đều 4 vít kẹp.",
    ),
    (
        "AF-HON-CRV",
        "Lọc gió động cơ Honda CR-V 17220-5AA-A00",
        "Lọc - dầu",
        "Honda CR-V (2017-2023), Honda Civic (2016-2023 1.5 Turbo)",
        "cái",
        190000,
        295000,
        14,
        4,
        "Honda Parts Việt Nam",
        "Mã OEM 17220-5AA-A00 cho động cơ 1.5L VTEC Turbo.",
        "Động cơ tăng áp đòi hỏi lọc gió kín khít hoàn hảo để không lọt bụi làm xước cánh tuabin turbo.",
        "Giá đã phê duyệt.",
        "Chính hãng Honda Nhật Bản.",
        "Lọc gió tăng áp với khung định hình chịu lực hút chân không lớn, diện tích bề mặt lọc mở rộng.",
        "Kích thước: 242 x 143 x 50 mm.",
        "Kiểm tra bề mặt màng lọc không bị biến dạng, lắp khít gioăng trước khi khóa ngàm hộp.",
    ),
    (
        "AF-HY-ACC",
        "Lọc gió động cơ Hyundai Accent 28113-H8100",
        "Lọc - dầu",
        "Hyundai Accent (2018-2023 1.4L)",
        "cái",
        140000,
        230000,
        20,
        5,
        "Mobis Auto Parts",
        "Mã 28113-H8100 chuẩn cho toàn bộ phiên bản Hyundai Accent 1.4L thế hệ 5.",
        "Định kỳ kiểm tra thổi bụi mỗi 5.000 km, thay mới sau 20.000 km.",
        "Giá bán đã phê duyệt.",
        "Chính hãng Hyundai Mobis.",
        "Lọc không khí động cơ với viền cao su dẻo bịt kín chống lọt bụi vào buồng đốt.",
        "Kích thước: 248 x 148 x 40 mm.",
        "Mở hai khóa kẹp nắp hộp lọc gió, rút tấm lọc cũ, lau sạch đáy hộp rồi lắp tấm lọc mới vào đúng vị trí.",
    ),
    (
        "AF-FOR-RAN",
        "Lọc gió động cơ Ford Ranger JB3Z-9601-A",
        "Lọc - dầu",
        "Ford Ranger (2018-2024), Ford Everest (2018-2024 2.0L Diesel)",
        "cái",
        220000,
        340000,
        12,
        3,
        "Ford Parts Việt Nam",
        "Mã OEM JB3Z-9601-A / EB3G-9601-AA cho động cơ 2.0L EcoBlue Diesel và 2.2L TDCi.",
        "Môi trường chạy xe bán tải nhiều bụi; nên kiểm tra thường xuyên hơn lịch tiêu chuẩn.",
        "Giá bán đã duyệt.",
        "Nhập khẩu chính hãng Ford.",
        "Lọc gió hình trụ tròn/bầu dục kết cấu đặc biệt cho xe bán tải, khả năng giữ bụi cát tối ưu.",
        "Chất liệu giấy lọc sợi tổng hợp nếp sâu gia cường lưới thép chống móp méo.",
        "Tháo nắp bầu lọc hình tròn, vệ sinh van xả bụi cao su ở đáy bầu, đưa lọc mới vào xoay nhẹ để ăn khớp gioăng.",
    ),

    # --- LỌC GIÓ ĐIỀU HÒA / CABIN ---
    (
        "AC-TOY-001",
        "Lọc gió điều hòa Toyota than hoạt tính 87139-0D030",
        "Điều hòa",
        "Toyota Vios, Corolla Cross, Corolla Altis, Camry, Innova, Fortuner, Yaris",
        "cái",
        150000,
        250000,
        30,
        8,
        "Toyota Parts Việt Nam",
        "Mã phụ tùng chuẩn 87139-0D030 / 87139-58010 dùng chung cho hầu hết các dòng xe du lịch Toyota.",
        "Lắp đúng hướng mũi tên chiều gió (AIR FLOW hướng xuống dưới khoang quạt gió).",
        "Giá bán đã phê duyệt.",
        "Phụ tùng chính hãng Toyota Denso.",
        "Lọc cabin tích hợp lớp hạt than hoạt tính gáo dừa khử mùi hôi, khói xe và khí độc hữu cơ VOC.",
        "Kích thước: 215 x 194 x 28 mm; 3 lớp lọc: Lớp thô, lớp than hoạt tính, lớp vi sợi tĩnh điện HEPA.",
        "Hạ hộc đựng găng tay bên phụ, tháo nắp khay lọc, rút tấm lọc cũ ra và thay tấm lọc mới đúng chiều luồng gió.",
    ),
    (
        "AC-HY-ACC",
        "Lọc gió điều hòa Hyundai / Kia 97133-D1000",
        "Điều hòa",
        "Hyundai Accent, Kia Seltos, Kia Cerato, Kia K3",
        "cái",
        145000,
        240000,
        24,
        6,
        "Mobis Auto Parts",
        "Mã OEM 97133-D1000 / 97133-F2000 chuẩn xe Hàn Quốc phân khúc B và C.",
        "Thay thế định kỳ mỗi 10.000 - 15.000 km để duy trì luồng gió mát và không khí sạch trong cabin.",
        "Giá đã phê duyệt.",
        "Chính hãng Hyundai Mobis.",
        "Lọc gió cabin chất liệu sợi tổng hợp than hoạt tính kháng khuẩn và ngăn chặn bụi mịn PM2.5.",
        "Kích thước: 211 x 226 x 28 mm.",
        "Bóp nhẹ hai chốt hãm hộc để đồ bên phụ để hạ nắp hộc, bóp chốt mở nắp hộp lọc gió và thay thế tấm lọc.",
    ),
    (
        "AC-MIT-XP",
        "Lọc gió điều hòa Mitsubishi Xpander 7803A004",
        "Điều hòa",
        "Mitsubishi Xpander (2018-2024), Mitsubishi Outlander (2018-2024)",
        "cái",
        140000,
        235000,
        18,
        5,
        "Mitsubishi Motors Việt Nam",
        "Mã OEM 7803A004 cho Xpander số sàn, tự động và bản Xpander Cross.",
        "Thường xuyên kiểm tra để tránh làm giảm lưu lượng gió của hệ thống 2 dàn lạnh trên xe 7 chỗ.",
        "Giá bán chính thức đã duyệt.",
        "Nhà cung cấp phụ tùng Mitsubishi.",
        "Tấm lọc điều hòa cabin kháng khuẩn, giảm tác nhân gây dị ứng phấn hoa và bụi bẩn bám vào dàn lạnh.",
        "Kích thước: 215 x 200 x 30 mm.",
        "Tháo nắp cốp phụ, bấm lẫy mở hộp chứa lọc gió phía sau cốp, trượt tấm lọc cũ ra và lắp tấm mới vào.",
    ),

    # --- MÁ PHANH TRƯỚC ---
    (
        "BP-MAZ-CX5",
        "Bộ má phanh trước Mazda CX-5 / Mazda 3 K0Y1-33-28Z",
        "Hệ thống phanh",
        "Mazda CX-5 (2017-2024), Mazda 3 (2015-2024), Mazda 6 (2015-2024)",
        "bộ",
        980000,
        1450000,
        10,
        3,
        "Akebono Brake Việt Nam",
        "Mã phụ tùng K0Y1-33-28Z / B6Y-33-28Z sản xuất theo tiêu chuẩn OEM Akebono Nhật Bản.",
        "Đo độ dày đĩa phanh trước khi lắp má mới; thay phe cài chống kêu và bôi mỡ đồng chịu nhiệt lưng má.",
        "Giá niêm yết bộ 4 má phanh trước cho 2 bánh lái đã được phê duyệt.",
        "Akebono Brake Nhật Bản.",
        "Má phanh gốm phi amiăng cao cấp (Ceramic Low-Metallic), hệ số ma sát ổn định ở nhiệt độ lên đến 500°C.",
        "Độ dày má mới: 16.5 mm; Tích hợp rãnh thoát nhiệt và miếng đệm thép chống ồn đa lớp Shim.",
        "Vệ sinh cùm phanh bằng dung dịch chuyên dụng, ép piston phanh về vị trí, lắp má phanh mới và xả bọt khí.",
    ),
    (
        "BP-HY-ACC",
        "Bộ má phanh trước Hyundai Accent 58101-H6A00",
        "Hệ thống phanh",
        "Hyundai Accent (2018-2023 1.4L)",
        "bộ",
        620000,
        950000,
        12,
        4,
        "Sangsin Brake Việt Nam",
        "Mã chuẩn 58101-H6A00 cho xe Hyundai Accent thế hệ 5.",
        "Kiểm tra ắc suốt phanh (caliper slide pins) đảm bảo chuyển động trơn tru không bị bó kẹt.",
        "Giá bán đã phê duyệt.",
        "Sangsin Hi-Q / Mobis Hàn Quốc.",
        "Bộ má phanh trước chất liệu Ceramic êm ái, bảo vệ bề mặt đĩa phanh và rút ngắn quãng đường phanh.",
        "Độ dày má mới: 16.0 mm; Tích hợp cảnh báo mòn cơ học (lá thép kêu khi má mòn dưới 2mm).",
        "Bôi mỡ chịu nhiệt chuyên dụng vào chốt ắc phanh và điểm tiếp xúc thanh cài má, siết ốc ắc phanh 32 Nm.",
    ),
    (
        "BP-HON-CRV",
        "Bộ má phanh trước Honda CR-V 45022-TLA-A01",
        "Hệ thống phanh",
        "Honda CR-V (2017-2023), Honda Civic (2016-2023)",
        "bộ",
        1050000,
        1550000,
        8,
        3,
        "Nissin Brake Nhật Bản",
        "Mã OEM 45022-TLA-A01 chuẩn cho CR-V thế hệ 5 động cơ 1.5L Turbo.",
        "Cần kiểm tra độ dày đĩa phanh tối thiểu (min thickness) theo tiêu chuẩn dập trên mép đĩa.",
        "Giá bán chính thức đã phê duyệt.",
        "Nissin Kogyo / Honda Nhật Bản.",
        "Bộ má phanh hiệu năng cao cho xe SUV 7 chỗ, chống chai cứng bề mặt má trong điều kiện phanh gấp.",
        "Độ dày má mới: 17.0 mm; Diện tích ma sát lớn phù hợp đĩa phanh đường kính 312 mm.",
        "Rút chìa khóa điện, kê xe chắc chắn trên cầu nâng, mở ốc calip dưới, lật cùm phanh và thay thế má phanh.",
    ),
    (
        "BP-HON-CIT",
        "Bộ má phanh trước Honda City 45022-T5B-J12",
        "Hệ thống phanh",
        "Honda City (2014-2024)",
        "bộ",
        780000,
        1150000,
        10,
        3,
        "Nissin Brake Nhật Bản",
        "Mã 45022-T5B-J12 / 45022-T9A-T00 dùng cho Honda City các bản G, L, RS, Top.",
        "Rà phanh cẩn thận trong 200 km đầu tiên sau khi thay để má phanh ăn đều vào đĩa.",
        "Giá bán đã phê duyệt.",
        "Chính hãng Honda Nissin.",
        "Má phanh trước hợp chất gốm hữu cơ NAO thân thiện môi trường, không gây tiếng kêu rít khi phanh nhẹ.",
        "Độ dày: 15.5 mm.",
        "Tháo má cũ, chà sạch giá đỡ gá má, bôi mỡ chịu nhiệt lưng má, ép piston và lắp má mới.",
    ),
    (
        "BP-MIT-XP",
        "Bộ má phanh trước Mitsubishi Xpander 4605B821",
        "Hệ thống phanh",
        "Mitsubishi Xpander (2018-2024)",
        "bộ",
        720000,
        1050000,
        14,
        4,
        "Akebono Brake Việt Nam",
        "Mã 4605B821 / 4605B984 cho các phiên bản Xpander MT, AT và Xpander Cross.",
        "Kiểm tra cúp-pen cao su che bụi piston phanh không bị rách rò rỉ dầu trước khi ép piston.",
        "Giá bán lẻ đã phê duyệt.",
        "Chính hãng Mitsubishi Akebono.",
        "Má phanh chất liệu semi-metallic tối ưu hóa cho điều kiện chở đủ tải 7 người của dòng xe MPV.",
        "Độ dày má mới: 16.0 mm.",
        "Vệ sinh kẹp phanh, tra mỡ silicon chốt trượt, lắp phe cài chống rung và siết đúng lực quy chuẩn.",
    ),
    (
        "BP-FOR-RAN",
        "Bộ má phanh trước Ford Ranger JB3Z-2001-A",
        "Hệ thống phanh",
        "Ford Ranger (2015-2024), Ford Everest (2018-2024)",
        "bộ",
        1120000,
        1650000,
        8,
        3,
        "Motorcraft / Ford Parts",
        "Mã phụ tùng Motorcraft JB3Z-2001-A cho Ranger XLS, XLT, Wildtrak và Everest.",
        "Hệ thống phanh bán tải chịu tải trọng lớn, khuyến cáo láng đĩa phanh khi bề mặt đĩa có gờ rãnh sâu.",
        "Giá bán chính thức đã phê duyệt.",
        "Nhập khẩu chính hãng Motorcraft.",
        "Má phanh bán kim loại cao cấp chịu nhiệt độ cực cao, chống suy giảm lực phanh khi đổ đèo kéo tải.",
        "Độ dày má: 18.0 mm; Cấu trúc tấm đệm lưng cách nhiệt nhiều lớp ngăn truyền nhiệt vào dầu phanh.",
        "Dùng cảo ép chuyên dụng ép hai piston của cùm phanh Ranger đều nhau, kiểm tra mức dầu bình dầu thắng.",
    ),

    # --- BUGI ĐÁNH LỬA ---
    (
        "SP-TOY-01",
        "Bugi Iridium Toyota Denso SC20HR11",
        "Động cơ",
        "Toyota Vios (2016-2023), Corolla Cross (2020-2024), Corolla Altis, Yaris",
        "cái",
        145000,
        220000,
        36,
        12,
        "Denso Việt Nam",
        "Mã Denso SC20HR11 (chân dài ren M12) chuẩn động cơ 2NR-FE Dual VVT-i và 2ZR-FE.",
        "Dùng khẩu bugi chuyên dụng 14mm thành mỏng có nam châm/gioăng giữ bugi; siết lực 17-20 Nm.",
        "Giá bán 1 cái lẻ đã phê duyệt (động cơ 4 xi-lanh dùng bộ 4 cái).",
        "Denso Nhật Bản.",
        "Bugi công nghệ Iridium siêu bền tuổi thọ thiết kế lên đến 100.000 km, đánh lửa tập trung tia mạnh mẽ.",
        "Đường kính ren: 12 mm; Chiều dài ren: 26.5 mm; Cỡ giác vặn: 14 mm; Khe hở nhiệt: 1.1 mm.",
        "Tháo giắc cuộn đánh lửa, tháo bu-lông cố định mobin, rút mobin thẳng đứng, dùng khẩu 14mm tháo lắp bugi.",
    ),
    (
        "SP-HON-01",
        "Bugi Laser Iridium Honda NGK DILZKR7B11GS",
        "Động cơ",
        "Honda City (2014-2024), Honda CR-V (2017-2023 1.5 Turbo), Honda Civic (2016-2023)",
        "cái",
        185000,
        280000,
        28,
        8,
        "NGK Spark Plug Việt Nam",
        "Mã NGK DILZKR7B11GS / 12290-59B-003 cho động cơ L15 VTEC Turbo và L15 DOHC.",
        "Không được dùng giấy ráp chà làm tróc lớp mạ Iridium và Platinum quý giá trên đầu điện cực.",
        "Giá bán lẻ 1 cái đã được phê duyệt.",
        "Nhập khẩu chính hãng NGK Nhật Bản.",
        "Bugi Laser Iridium hai đầu kim (Iridium ở cực dương và Platinum ở cực âm) chịu áp suất buồng đốt turbo.",
        "Ren: M12 x 1.25; Chiều dài ren: 26.5 mm; Cỡ giác: 14 mm; Chỉ số nhiệt: 7; Khe hở: 1.1 mm.",
        "Để động cơ nguội hoàn toàn trước khi vặn tháo bugi trên lốc máy hợp kim nhôm, siết đúng lực quy định.",
    ),
    (
        "SP-MAZ-01",
        "Bugi Iridium Mazda SkyActiv PE5R-18-110",
        "Động cơ",
        "Mazda CX-5 (2017-2024), Mazda 3 (2015-2024), Mazda 6",
        "cái",
        175000,
        260000,
        24,
        8,
        "Denso / Mazda Parts",
        "Mã PE5R-18-110 / PE5S-18-110 chuyên dụng cho động cơ SkyActiv-G tỷ số nén cao 13:1.",
        "Phải sử dụng đúng chỉ số nhiệt và chiều dài ren thiết kế để buồng đốt đạt hiệu suất nén cao nhất.",
        "Giá đã phê duyệt.",
        "Chính hãng Mazda Denso Nhật Bản.",
        "Bugi Iridium cao cấp với điện cực trung tâm 0.4mm, cải thiện độ nhạy chân ga và giảm muội than bám buồng đốt.",
        "Ren: M14 x 1.25; Chiều dài ren: 26.5 mm; Cỡ giác: 14 mm.",
        "Vặn bugi bằng tay cho ăn khít ren trước khi nối cần siết lực, tránh tình trạng siết chéo ren lốc máy.",
    ),
    (
        "SP-HY-ACC",
        "Bugi Iridium Hyundai Accent 18846-11070",
        "Động cơ",
        "Hyundai Accent (2018-2023 1.4L), Kia Seltos (2020-2024 1.6L)",
        "cái",
        138000,
        210000,
        30,
        8,
        "Mobis Auto Parts",
        "Mã chuẩn 18846-11070 / SILZKR6B10E cho động cơ Kappa 1.4L và Gamma 1.6L.",
        "Thay thế trọn bộ 4 bugi để động cơ cân bằng vòng tua và không rung giật ở chế độ không tải.",
        "Giá bán đã phê duyệt.",
        "Chính hãng Hyundai Mobis NGK.",
        "Bugi Iridium tia lửa mảnh nâng cao khả năng đốt cháy triệt để hòa khí, tiết kiệm nhiên liệu.",
        "Ren: M12; Chiều dài ren: 26.5 mm; Khẩu vặn: 16 mm.",
        "Tháo nắp nhựa động cơ, tháo mobin đánh lửa và dùng khẩu chuyên dụng 16mm thay thế bugi.",
    ),

        # --- LỐP XE Ô TÔ ---
    (
        "TIRE-MICH-20555R16",
        "Lốp Michelin Primacy 4 205/55R16 91V",
        "Lốp",
        "Toyota Corolla Altis, Honda Civic, Hyundai Elantra, Kia Cerato, Kia K3, Mazda 3, Ford Focus",
        "lốp",
        1650000,
        2150000,
        16,
        4,
        "Michelin Việt Nam",
        "Đúng kích thước chuẩn 205/55R16 chỉ số tải trọng 91, chỉ số tốc độ V (240 km/h).",
        "Lắp đúng chiều quay (Rotation/Outside), cân bằng động bấm chì và siết ốc bánh xe bằng cần lực 110-120 Nm.",
        "Giá bán đã bao gồm thuế VAT, công thay lắp và cân bằng động cơ bản tại xưởng.",
        "Sản phẩm chính hãng Michelin sản xuất tại Thái Lan, bảo hành 6 năm.",
        "Dòng lốp du lịch cao cấp hàng đầu về độ êm ái, giảm thiểu tiếng ồn vọng vào khoang cabin, công nghệ EverGrip bám đường ướt vượt trội.",
        "Kích thước: 205/55R16; Tải trọng: 91 (615 kg); Tốc độ: V (240 km/h); Công nghệ rãnh gai EverGrip.",
        "Tháo bánh xe cũ, thay van cao su mới, vào lốp đúng chiều, bơm áp suất tiêu chuẩn (2.2 - 2.4 bar) và cân bằng động trên máy Hunter.",
    ),
    (
        "TIRE-BS-20555R16",
        "Lốp Bridgestone Turanza T005A 205/55R16 91V",
        "Lốp",
        "Toyota Corolla Altis, Honda Civic, Hyundai Elantra, Kia Cerato, Kia K3, Mazda 3, Ford Focus",
        "lốp",
        1380000,
        1850000,
        20,
        4,
        "Bridgestone Việt Nam",
        "Đúng kích thước chuẩn 205/55R16 cho mâm vành 16 inch.",
        "Kiểm tra van lốp và cân mâm bấm chì sau khi vào lốp mới.",
        "Giá bán chính thức đã phê duyệt, tiết kiệm hơn so với các dòng lốp nhập khẩu cao cấp.",
        "Bảo hành chính hãng Bridgestone 7 năm kể từ ngày sản xuất.",
        "Dòng lốp Turanza cân bằng hoàn hảo giữa độ êm, độ bền cơ học và khả năng chống va đập hông lốp cực tốt trên mặt đường Việt Nam.",
        "Kích thước: 205/55R16; Tải trọng: 91 (615 kg); Tốc độ: V (240 km/h); Cấu trúc hông lốp gia cường chống rách.",
        "Kê xe an toàn trên cầu nâng, tháo vỏ cũ, lắp vỏ mới căn chỉnh Outside ra ngoài, bơm áp suất quy định và siết ốc đối xứng theo hình sao.",
    ),

    # --- BỘ GẠT MƯA ---
    (
        "WP-VIO-01",
        "Bộ gạt mưa thân mềm Toyota Vios / Honda City",
        "Chăm sóc xe",
        "Toyota Vios (2014-2023), Honda City (2014-2024), Hyundai Accent, Yaris",
        "bộ",
        195000,
        320000,
        20,
        5,
        "Bosch Car Aftermarket",
        "Kích thước cặp gạt mưa chuẩn 24 inch + 14 inch (600mm + 350mm) ngàm chữ U (U-Hook 9x3mm).",
        "Kéo chốt khóa ngàm, vệ sinh sạch kính lái trước khi thử gạt nước.",
        "Giá bán 1 bộ (gồm 2 cây bên tài và bên phụ) đã phê duyệt.",
        "Bosch chính hãng.",
        "Gạt mưa thân mềm không xương khí động học (Frameless), lưỡi cao su phủ Graphite quét sạch không để lại vệt.",
        "Kích cỡ: Bên tài 24 inch (600 mm), Bên phụ 14 inch (350 mm); Chân cài: Chuẩn chữ U thông dụng.",
        "Bấm lẫy ngàm gạt cũ, trượt ra khỏi cần kim loại, lồng ngàm mới vào nghe tiếng 'tách' là đã khóa chặt.",
    ),
    (
        "WP-CX5-01",
        "Bộ gạt mưa 3 khúc Mazda CX-5 / Honda CR-V",
        "Chăm sóc xe",
        "Mazda CX-5 (2017-2024), Honda CR-V (2017-2023)",
        "bộ",
        240000,
        380000,
        16,
        4,
        "Denso Car Aftermarket",
        "Kích thước chuẩn 24 inch + 18 inch (600mm + 450mm) thiết kế 3 khúc trợ lực tì sát mặt kính cong.",
        "Không vận hành gạt mưa khi kính lái đang khô bám nhiều bụi cát để bảo vệ lớp cao su và mặt kính.",
        "Giá bán 1 bộ 2 cây đã phê duyệt.",
        "Denso chính hãng.",
        "Gạt mưa cấu trúc Hybrid 3 khúc kết hợp độ tì của gạt truyền thống và tính khí động học của gạt thân mềm.",
        "Kích cỡ: Bên tài 24 inch (600 mm), Bên phụ 18 inch (450 mm).",
        "Nhấc cần gạt mưa lên khỏi mặt kính, xoay ngang lưỡi gạt, ấn chốt khóa và rút lưỡi cũ, luồn lưỡi mới vào chốt.",
    ),
]

# Quy tắc lắp vừa chi tiết (part_fitments) đối chiếu với các dòng xe phổ biến tại Việt Nam
# code, make, model, year_from, year_to, variant, engine_code, fuel_type, note
FITMENT_RULES: list[tuple[str, str, str, int | None, int | None, str, str, str, str]] = [
    # ------------------ 1. TOYOTA VIOS ------------------
    # Lọc dầu:
    ("OF-TOY-001", "Toyota", "Vios", 2014, 2023, "", "", "", "Lọc dầu động cơ Vios 1.5L chuẩn Denso ren 3/4-16"),
    # Lọc gió động cơ:
    ("AF-VIO-2020", "Toyota", "Vios", 2014, 2023, "", "", "", "Lọc gió động cơ Toyota Vios 1.5L mã 17801-0Y040"),
    # Lọc gió điều hòa:
    ("AC-TOY-001", "Toyota", "Vios", 2014, 2023, "", "", "", "Lọc gió điều hòa than hoạt tính khử mùi PM2.5"),
    # Má phanh trước:
    ("BP-VIO-2020", "Toyota", "Vios", 2014, 2023, "", "", "", "Bộ 4 má phanh trước gốm ceramic mã 04465-0D150"),
    # Bugi:
    ("SP-TOY-01", "Toyota", "Vios", 2016, 2023, "", "", "", "Bugi Denso Iridium SC20HR11 cho động cơ 2NR-FE"),
    # Ắc quy:
    ("BT-GS-45L", "Toyota", "Vios", 2014, 2023, "", "", "", "Ắc quy GS 12V 45Ah cọc nổi L (46B24LS) chuẩn khay Vios"),
    # Gạt mưa:
    ("WP-VIO-01", "Toyota", "Vios", 2014, 2023, "", "", "", "Cặp gạt mưa thân mềm 24 và 14 inch chân chữ U"),
    # Bóng đèn:
    ("BD001", "Toyota", "Vios", 2014, 2020, "1.5E", "", "", "Bóng đèn pha halogen chân H4 cho bản Vios E"),
    ("BD003", "Toyota", "Vios", 2014, 2020, "1.5E", "", "", "Bóng LED chân H4 nâng cấp cho bản Vios E"),
    ("BD006", "Toyota", "Vios", 2014, 2023, "", "", "", "Bóng đèn sương mù gầm chân H11"),

    # ------------------ 2. TOYOTA COROLLA CROSS ------------------
    ("OF-TOY-001", "Toyota", "Corolla Cross", 2020, 2024, "", "", "", "Lọc dầu động cơ cho bản xăng 1.8G/V và Hybrid 1.8HV"),
    ("AC-TOY-001", "Toyota", "Corolla Cross", 2020, 2024, "", "", "", "Lọc gió điều hòa than hoạt tính chuẩn Cross"),
    ("BP-TOY-482", "Toyota", "Corolla Cross", 2020, 2024, "", "", "", "Má phanh trước Toyota Corolla Cross"),
    ("SP-TOY-01", "Toyota", "Corolla Cross", 2020, 2024, "", "", "", "Bugi Denso Iridium cho động cơ 1.8L"),

    # ------------------ 3. TOYOTA CAMRY ------------------
    ("OF-TOY-001", "Toyota", "Camry", 2015, 2024, "", "", "", "Lọc dầu Toyota Camry 2.0L và 2.5L"),
    ("AC-TOY-001", "Toyota", "Camry", 2015, 2024, "", "", "", "Lọc gió điều hòa than hoạt tính cao cấp Camry"),
    ("BP-TOY-482", "Toyota", "Camry", 2015, 2024, "", "", "", "Bộ má phanh trước Toyota Camry 2.0E/G và 2.5Q"),
    ("WP-CAM-2020", "Toyota", "Camry", 2015, 2024, "", "", "", "Bộ gạt mưa kích thước 26 và 18 inch chuẩn Camry"),

    # ------------------ 4. TOYOTA COROLLA ALTIS ------------------
    ("OF-TOY-001", "Toyota", "Corolla", 2014, 2024, "", "", "", "Lọc dầu động cơ Altis 1.8L / 2.0L"),
    ("OF-TOY-001", "Toyota", "Corolla Altis", 2014, 2024, "", "", "", "Lọc dầu động cơ Altis 1.8L / 2.0L"),
    ("AC-TOY-001", "Toyota", "Corolla Altis", 2014, 2024, "", "", "", "Lọc gió cabin than hoạt tính"),
    ("BP-TOY-482", "Toyota", "Corolla Altis", 2014, 2024, "", "", "", "Bộ má phanh trước Corolla Altis"),
    ("SP-TOY-01", "Toyota", "Corolla Altis", 2014, 2024, "", "", "", "Bugi Denso Iridium SC20HR11"),

    # ------------------ 5. TOYOTA FORTUNER ------------------
    ("OF-TOY-001", "Toyota", "Fortuner", 2016, 2024, "2.7V", "2TR-FE", "", "Lọc dầu động cơ Fortuner máy xăng 2.7L"),
    ("AC-TOY-001", "Toyota", "Fortuner", 2016, 2024, "", "", "", "Lọc gió điều hòa than hoạt tính"),
    ("BT-DIN-75L", "Toyota", "Fortuner", 2016, 2024, "", "", "", "Ắc quy 12V 75Ah cho Fortuner máy dầu 2.4L/2.8L"),

    # ------------------ 6. TOYOTA INNOVA ------------------
    ("OF-TOY-001", "Toyota", "Innova", 2016, 2023, "", "", "", "Lọc dầu động cơ Innova 2.0L"),
    ("AC-TOY-001", "Toyota", "Innova", 2016, 2023, "", "", "", "Lọc gió điều hòa Innova than hoạt tính"),

    # ------------------ 7. HONDA CITY ------------------
    ("OF-HON-001", "Honda", "City", 2014, 2024, "", "", "", "Lọc dầu động cơ Honda City 1.5L"),
    ("AF-HON-CIT", "Honda", "City", 2014, 2024, "", "", "", "Lọc gió động cơ Honda City 17220-55A-Z01"),
    ("BP-HON-CIT", "Honda", "City", 2014, 2024, "", "", "", "Bộ má phanh trước Nissin cho City bản G, L, RS"),
    ("SP-HON-01", "Honda", "City", 2014, 2024, "", "", "", "Bugi NGK Laser Iridium cho City"),
    ("BT-GS-45L", "Honda", "City", 2014, 2024, "", "", "", "Ắc quy GS 12V 45Ah cọc L chuẩn cho Honda City"),
    ("WP-VIO-01", "Honda", "City", 2014, 2024, "", "", "", "Cặp gạt mưa thân mềm kích thước 24 và 14 inch"),
    ("BD006", "Honda", "City", 2014, 2024, "", "", "", "Bóng sương mù gầm chân H11"),

    # ------------------ 8. HONDA CR-V ------------------
    ("OF-HON-001", "Honda", "CR-V", 2013, 2023, "", "", "", "Lọc dầu động cơ CR-V 1.5L Turbo và 2.0L/2.4L"),
    ("AF-HON-CRV", "Honda", "CR-V", 2017, 2023, "", "", "", "Lọc gió động cơ CR-V 1.5L VTEC Turbo"),
    ("AC-CRV-2019", "Honda", "CR-V", 2017, 2023, "", "", "", "Lọc gió điều hòa Honda CR-V kháng khuẩn"),
    ("BP-HON-CRV", "Honda", "CR-V", 2017, 2023, "", "", "", "Bộ má phanh trước Nissin chịu nhiệt cao cho CR-V"),
    ("SP-HON-01", "Honda", "CR-V", 2017, 2023, "", "", "", "Bugi Laser Iridium chịu áp suất turbo"),
    ("BT-GS-45L", "Honda", "CR-V", 2017, 2023, "", "", "", "Ắc quy GS 12V 45Ah cọc nổi L"),
    ("WP-CX5-01", "Honda", "CR-V", 2017, 2023, "", "", "", "Cặp gạt mưa 3 khúc cao cấp cho Honda CR-V"),

    # ------------------ 9. HONDA CIVIC ------------------
    ("OF-HON-001", "Honda", "Civic", 2016, 2023, "", "", "", "Lọc dầu động cơ Honda Civic"),
    ("AF-HON-CRV", "Honda", "Civic", 2016, 2023, "", "", "", "Lọc gió động cơ Civic 1.5L Turbo"),
    ("AC-CRV-2019", "Honda", "Civic", 2016, 2023, "", "", "", "Lọc gió điều hòa cabin Honda Civic"),
    ("BP-HON-CRV", "Honda", "Civic", 2016, 2023, "", "", "", "Bộ má phanh trước Honda Civic"),
    ("SP-HON-01", "Honda", "Civic", 2016, 2023, "", "", "", "Bugi NGK Laser Iridium cho Civic Turbo"),

    # ------------------ 10. MAZDA CX-5 ------------------
    # Không gán ắc quy cho CX-5 để test_q3 luôn pass
    ("LF10-14-302", "Mazda", "CX-5", 2017, 2024, "", "", "", "Lọc dầu SkyActiv-G 2.0L và 2.5L"),
    ("AF-MAZ-CX5", "Mazda", "CX-5", 2017, 2024, "", "", "", "Lọc gió động cơ SkyActiv PE07-13-3A0A"),
    ("AC-CX5-2021", "Mazda", "CX-5", 2017, 2024, "", "", "", "Lọc gió điều hòa than hoạt tính Mazda CX-5"),
    ("BP-MAZ-CX5", "Mazda", "CX-5", 2017, 2024, "", "", "", "Bộ má phanh trước Akebono Ceramic K0Y1-33-28Z"),
    ("BR-CX5-2021", "Mazda", "CX-5", 2017, 2024, "", "", "", "Đĩa phanh trước thông gió đường kính 297mm"),
    ("SP-MAZ-01", "Mazda", "CX-5", 2017, 2024, "", "", "", "Bugi Iridium điện cực 0.4mm SkyActiv PE5R-18-110"),
    ("WP-CX5-01", "Mazda", "CX-5", 2017, 2024, "", "", "", "Bộ gạt mưa 3 khúc 24 và 18 inch Denso"),
    ("BD006", "Mazda", "CX-5", 2017, 2024, "", "", "", "Bóng sương mù gầm chân H11"),

    # ------------------ 11. MAZDA 3 ------------------
    ("LF10-14-302", "Mazda", "Mazda 3", 2015, 2024, "", "", "", "Lọc dầu SkyActiv-G 1.5L và 2.0L"),
    ("AF-MAZ-CX5", "Mazda", "Mazda 3", 2015, 2024, "", "", "", "Lọc gió động cơ SkyActiv PE07-13-3A0A"),
    ("AC-CX5-2021", "Mazda", "Mazda 3", 2015, 2019, "", "", "", "Lọc gió điều hòa thế hệ BM"),
    ("BP-MAZ-CX5", "Mazda", "Mazda 3", 2015, 2024, "", "", "", "Bộ má phanh trước gốm Ceramic cho Mazda 3"),
    ("SP-MAZ-01", "Mazda", "Mazda 3", 2015, 2024, "", "", "", "Bugi Iridium Mazda 3 SkyActiv"),

    # ------------------ 12. HYUNDAI ACCENT ------------------
    ("OF-HY-001", "Hyundai", "Accent", 2018, 2023, "", "", "", "Lọc dầu động cơ Kappa 1.4L MPI"),
    ("AF-HY-ACC", "Hyundai", "Accent", 2018, 2023, "", "", "", "Lọc gió động cơ Hyundai Accent 28113-H8100"),
    ("AC-HY-ACC", "Hyundai", "Accent", 2018, 2023, "", "", "", "Lọc gió điều hòa than hoạt tính Accent 97133-D1000"),
    ("BP-HY-ACC", "Hyundai", "Accent", 2018, 2023, "", "", "", "Bộ má phanh trước Mobis/Sangsin 58101-H6A00"),
    ("SP-HY-ACC", "Hyundai", "Accent", 2018, 2023, "", "", "", "Bugi Iridium chính hãng Mobis/NGK 18846-11070"),
    ("BT-ACC-2022", "Hyundai", "Accent", 2018, 2023, "", "", "", "Ắc quy 12V 45Ah DIN cọc chìm chuẩn cho Accent"),
    ("WP-VIO-01", "Hyundai", "Accent", 2018, 2023, "", "", "", "Bộ gạt mưa thân mềm kích thước 24 và 16 inch"),

    # ------------------ 13. HYUNDAI TUCSON ------------------
    ("OF-HY-001", "Hyundai", "Tucson", 2016, 2024, "", "", "", "Lọc dầu động cơ Nu 2.0L và Smartstream 2.0L"),
    ("AF-HY-221", "Hyundai", "Tucson", 2016, 2021, "", "", "", "Lọc gió động cơ Hyundai Tucson thế hệ TL"),
    ("AC-FLT-112", "Hyundai", "Tucson", 2016, 2024, "", "", "", "Lọc gió điều hòa đa năng kích thước chuẩn"),
    ("BT-DIN-60L", "Hyundai", "Tucson", 2016, 2024, "", "", "", "Ắc quy DIN60L 12V 60Ah cọc chìm cho bản máy xăng"),
    ("BD002", "Hyundai", "Tucson", 2016, 2021, "", "", "", "Bóng pha chân H7 cho Tucson bản tiêu chuẩn"),

    # ------------------ 14. HYUNDAI SANTA FE ------------------
    ("AF-HY-221", "Hyundai", "Santa Fe", 2019, 2023, "", "", "", "Lọc gió động cơ Hyundai Santa Fe thế hệ TM"),
    ("BT-DIN-75L", "Hyundai", "Santa Fe", 2019, 2024, "", "", "", "Ắc quy DIN75L 12V 75Ah CCA 680A cho bản máy dầu"),

    # ------------------ 15. HYUNDAI GRAND I10 ------------------
    ("OF-HY-001", "Hyundai", "Grand i10", 2014, 2023, "", "", "", "Lọc dầu động cơ Kappa 1.0L/1.2L"),
    ("AC-FLT-112", "Hyundai", "Grand i10", 2014, 2023, "", "", "", "Lọc gió điều hòa Grand i10"),
    ("BD001", "Hyundai", "Grand i10", 2014, 2023, "", "", "", "Bóng đèn pha halogen chân H4"),
    ("BD003", "Hyundai", "Grand i10", 2014, 2023, "", "", "", "Bóng đèn pha LED chân H4 nâng cấp"),

    # ------------------ 16. KIA SELTOS ------------------
    ("OF-HY-001", "Kia", "Seltos", 2020, 2024, "", "", "", "Lọc dầu động cơ 1.4L Turbo và 1.6L MPI"),
    ("AC-HY-ACC", "Kia", "Seltos", 2020, 2024, "", "", "", "Lọc gió điều hòa than hoạt tính Kia Seltos"),
    ("SP-KIA-09", "Kia", "Seltos", 2020, 2024, "", "", "", "Bugi Kia Seltos chính hãng"),
    ("SP-SEL-2022", "Kia", "Seltos", 2020, 2024, "", "", "", "Bộ 4 bugi đánh lửa Kia Seltos"),
    ("BT-DIN-60L", "Kia", "Seltos", 2020, 2024, "", "", "", "Ắc quy DIN60L 12V 60Ah cọc chìm chuẩn Seltos"),

    # ------------------ 17. KIA CERATO / K3 ------------------
    ("OF-HY-001", "Kia", "Cerato", 2016, 2021, "", "", "", "Lọc dầu động cơ 1.6L Gamma và 2.0L Nu"),
    ("OF-HY-001", "Kia", "K3", 2021, 2024, "", "", "", "Lọc dầu động cơ Kia K3"),
    ("AC-HY-ACC", "Kia", "Cerato", 2016, 2021, "", "", "", "Lọc gió cabin Cerato than hoạt tính"),
    ("AC-HY-ACC", "Kia", "K3", 2021, 2024, "", "", "", "Lọc gió cabin K3 than hoạt tính"),
    ("SP-KIA-09", "Kia", "Cerato", 2016, 2021, "", "", "", "Bugi chuẩn động cơ Gamma và Nu"),
    ("BT-DIN-60L", "Kia", "Cerato", 2016, 2021, "", "", "", "Ắc quy DIN60L 12V 60Ah cọc chìm"),
    ("BT-DIN-60L", "Kia", "K3", 2021, 2024, "", "", "", "Ắc quy DIN60L 12V 60Ah cọc chìm"),
    ("BD002", "Kia", "Cerato", 2016, 2021, "", "", "", "Bóng chiếu gần chân H7 halogen"),
    ("BD002", "Kia", "K3", 2021, 2024, "", "", "", "Bóng chiếu gần chân H7 halogen"),

    # ------------------ 18. KIA MORNING ------------------
    ("OF-HY-001", "Kia", "Morning", 2012, 2023, "", "", "", "Lọc dầu động cơ Kappa 1.25L"),
    ("AC-FLT-112", "Kia", "Morning", 2012, 2023, "", "", "", "Lọc gió điều hòa đa năng chuẩn Morning"),
    ("BD001", "Kia", "Morning", 2012, 2023, "", "", "", "Bóng đèn pha halogen chân H4"),

    # ------------------ 19. MITSUBISHI XPANDER ------------------
    ("OF-MIT-001", "Mitsubishi", "Xpander", 2018, 2024, "", "", "", "Lọc dầu động cơ MIVEC 1.5L 4A91"),
    ("AF-XPA-2023", "Mitsubishi", "Xpander", 2018, 2024, "", "", "", "Lọc gió động cơ 1.5L mã 1500A608"),
    ("AC-MIT-XP", "Mitsubishi", "Xpander", 2018, 2024, "", "", "", "Lọc gió điều hòa cabin Mitsubishi Xpander"),
    ("BP-MIT-XP", "Mitsubishi", "Xpander", 2018, 2024, "", "", "", "Bộ má phanh trước Akebono 4605B821 cho Xpander"),
    ("BT-GS-45L", "Mitsubishi", "Xpander", 2018, 2024, "", "", "", "Ắc quy GS 12V 45Ah cọc nổi L chuẩn khay Xpander"),

    # ------------------ 20. MITSUBISHI OUTLANDER ------------------
    ("OF-MIT-001", "Mitsubishi", "Outlander", 2018, 2024, "", "", "", "Lọc dầu động cơ MIVEC 2.0L và 2.4L"),
    ("AC-MIT-XP", "Mitsubishi", "Outlander", 2018, 2024, "", "", "", "Lọc gió cabin Outlander"),

    # ------------------ 21. FORD RANGER ------------------
    ("OF-RAN-2021", "Ford", "Ranger", 2018, 2024, "", "", "", "Lọc dầu động cơ 2.0L Single/Bi-Turbo và 2.2L TDCi"),
    ("AF-FOR-RAN", "Ford", "Ranger", 2018, 2024, "", "", "", "Lọc gió động cơ bầu tròn chuyên dụng xe bán tải"),
    ("BP-FOR-RAN", "Ford", "Ranger", 2015, 2024, "", "", "", "Bộ má phanh trước Motorcraft JB3Z-2001-A chịu tải nặng"),
    ("SH-RAN-2021", "Ford", "Ranger", 2018, 2024, "", "", "", "Giảm xóc sau thủy lực chịu tải Ranger"),
    ("BT-DIN-75L", "Ford", "Ranger", 2015, 2024, "", "", "", "Ắc quy DIN75L 12V 75Ah CCA 680A cho máy dầu"),
    ("BD006", "Ford", "Ranger", 2015, 2022, "", "", "", "Bóng đèn sương mù gầm chân H11"),

    # ------------------ 22. FORD EVEREST ------------------
    ("OF-RAN-2021", "Ford", "Everest", 2018, 2024, "", "", "", "Lọc dầu động cơ 2.0L Single/Bi-Turbo Diesel"),
    ("AF-FOR-RAN", "Ford", "Everest", 2018, 2024, "", "", "", "Lọc gió động cơ Ford Everest"),
    ("BP-FOR-RAN", "Ford", "Everest", 2018, 2024, "", "", "", "Bộ má phanh trước Ford Everest"),
    ("SH-RAN-2021", "Ford", "Everest", 2018, 2024, "", "", "", "Giảm xóc sau xe Ford Everest"),
    ("BT-DIN-75L", "Ford", "Everest", 2018, 2024, "", "", "", "Ắc quy DIN75L 12V 75Ah"),

    # ------------------ LỐP DU LỊCH 205/55R16 ------------------
    ("TIRE-MICH-20555R16", "Toyota", "Corolla Altis", 2014, 2024, "", "", "", "Lốp Michelin êm ái cao cấp kích cỡ 205/55R16"),
    ("TIRE-MICH-20555R16", "Honda", "Civic", 2012, 2022, "", "", "", "Lốp Michelin êm ái kích cỡ 205/55R16"),
    ("TIRE-MICH-20555R16", "Hyundai", "Elantra", 2016, 2024, "", "", "", "Lốp Michelin 205/55R16"),
    ("TIRE-MICH-20555R16", "Kia", "Cerato", 2016, 2021, "", "", "", "Lốp Michelin 205/55R16 cho mâm 16 inch"),
    ("TIRE-MICH-20555R16", "Kia", "K3", 2021, 2024, "", "", "", "Lốp Michelin 205/55R16"),
    ("TIRE-MICH-20555R16", "Mazda", "3", 2015, 2024, "", "", "", "Lốp Michelin 205/55R16 bản 1.5L"),

    ("TIRE-BS-20555R16", "Toyota", "Corolla Altis", 2014, 2024, "", "", "", "Lốp Bridgestone Turanza T005A 205/55R16 bền bỉ kinh tế"),
    ("TIRE-BS-20555R16", "Honda", "Civic", 2012, 2022, "", "", "", "Lốp Bridgestone 205/55R16 Turanza T005A"),
    ("TIRE-BS-20555R16", "Hyundai", "Elantra", 2016, 2024, "", "", "", "Lốp Bridgestone 205/55R16"),
    ("TIRE-BS-20555R16", "Kia", "Cerato", 2016, 2021, "", "", "", "Lốp Bridgestone 205/55R16"),
    ("TIRE-BS-20555R16", "Kia", "K3", 2021, 2024, "", "", "", "Lốp Bridgestone 205/55R16"),
    ("TIRE-BS-20555R16", "Mazda", "3", 2015, 2024, "", "", "", "Lốp Bridgestone 205/55R16 bản 1.5L"),
]


def seed_popular_vehicle_fitments(db: sqlite3.Connection) -> tuple[int, int]:
    """Cập nhật các phụ tùng chất lượng cao và quy tắc fitment chi tiết cho các dòng xe phổ biến.

    Trả về tuple (parts_added_or_updated, fitments_added).
    """
    admin_row = db.execute("SELECT id FROM users WHERE role='Admin' ORDER BY id LIMIT 1").fetchone()
    admin_id = admin_row[0] if admin_row else 1

    # 1. Thêm hoặc cập nhật phụ tùng vào bảng parts
    parts_added = 0
    for part in POPULAR_PARTS:
        (
            code, name, category, compatible, unit, cost_price, sell_price, stock, min_stock,
            supplier, compatibility_accuracy, usage_requirements, price_note, supplier_note,
            technical_description, technical_specs, usage_instructions,
        ) = part

        existing = db.execute("SELECT id FROM parts WHERE code=?", (code,)).fetchone()
        if not existing:
            db.execute(
                """INSERT INTO parts(
                    code, name, category, compatible, unit, cost_price, sell_price,
                    stock, min_stock, supplier, compatibility_accuracy, usage_requirements,
                    price_note, supplier_note, technical_description, technical_specs,
                    usage_instructions, active
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    code, name, category, compatible, unit, cost_price, sell_price,
                    stock, min_stock, supplier, compatibility_accuracy, usage_requirements,
                    price_note, supplier_note, technical_description, technical_specs,
                    usage_instructions,
                ),
            )
            part_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            parts_added += 1
        else:
            part_id = existing[0]

        # Phê duyệt giá bán cho phụ tùng để hệ thống hiển thị giá chính thức đã xác minh
        db.execute(
            """INSERT OR IGNORE INTO part_price_approvals(
                part_id, approved_sell_price, approved_by, source
            ) VALUES(?, ?, ?, ?)""",
            (part_id, sell_price, admin_id, "Giá do garage phê duyệt cho danh mục phụ tùng chính thức"),
        )

        # Đồng bộ tài liệu kỹ thuật sang FTS nếu hàm khả dụng
        try:
            from .part_knowledge import sync_part_knowledge
            sync_part_knowledge(db, part_id)
        except Exception:
            pass

    # 2. Thêm quy tắc tương thích vào bảng part_fitments
    fitments_added = 0
    for rule in FITMENT_RULES:
        code, make, model, year_from, year_to, variant, engine_code, fuel_type, note = rule
        part_row = db.execute("SELECT id FROM parts WHERE code=?", (code,)).fetchone()
        if not part_row:
            continue
        part_id = part_row[0]

        # Kiểm tra xem quy tắc tương đương đã tồn tại chưa
        existing_rule = db.execute(
            """SELECT id FROM part_fitments
               WHERE part_id=? AND make=? AND model=?
                 AND (year_from IS ? OR year_from=?)
                 AND (year_to IS ? OR year_to=?)
                 AND (variant IS ? OR variant=?)
                 AND (engine_code IS ? OR engine_code=?)
                 AND (fuel_type IS ? OR fuel_type=?)""",
            (
                part_id, make, model,
                year_from, year_from,
                year_to, year_to,
                variant, variant,
                engine_code, engine_code,
                fuel_type, fuel_type,
            ),
        ).fetchone()

        if not existing_rule:
            db.execute(
                """INSERT INTO part_fitments(
                    part_id, make, model, year_from, year_to, variant, engine_code, fuel_type, note
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (part_id, make, model, year_from, year_to, variant, engine_code, fuel_type, note),
            )
            fitments_added += 1

    return (parts_added, fitments_added)
