"""Danh mục demo mở rộng cho garage cỡ vừa (giá VND tham khảo, không phải báo giá).

Mã DEMO là mã nội bộ giả định, KHÔNG phải mã OEM. Không tạo quy tắc lắp vừa,
không khai báo giá vốn khi chưa có dữ liệu nhập hàng thực tế. Tồn kho mẫu là
số liệu GIẢ LẬP, không đại diện hàng vật lý.
"""

# name, category, scope of work, labour price (VND), estimated minutes.
# Giá công chưa gồm phụ tùng/dung dịch; nhóm chăm sóc xe là giá thao tác.
CATALOG_SERVICES = [
    ("Bảo dưỡng mốc 5.000 km", "Bảo dưỡng", "Kiểm tra cơ bản, thay dầu theo cấu hình xe; vật tư tính riêng", 250000, 60),
    ("Bảo dưỡng mốc 10.000 km", "Bảo dưỡng", "Kiểm tra phanh, lọc, chất lỏng và thay dầu; vật tư tính riêng", 350000, 90),
    ("Bảo dưỡng mốc 20.000 km", "Bảo dưỡng", "Kiểm tra chuyên sâu hệ truyền động, gầm và lọc; vật tư tính riêng", 550000, 150),
    ("Bảo dưỡng mốc 40.000 km", "Bảo dưỡng", "Kiểm tra tổng thể theo lịch hãng; hạng mục và vật tư xác nhận theo xe", 850000, 240),
    ("Thay dầu và lọc dầu động cơ", "Bảo dưỡng", "Công xả dầu, thay lọc và kiểm tra rò rỉ; dầu/lọc tính riêng", 250000, 45),
    ("Thay lọc nhiên liệu", "Bảo dưỡng", "Công thay lọc nhiên liệu sau khi xác định vị trí và loại lọc", 300000, 60),
    ("Thay bugi động cơ 4 xi-lanh", "Động cơ", "Công thay bộ bugi 4 xi-lanh dễ tiếp cận; bugi tính riêng", 300000, 60),
    ("Thay cuộn đánh lửa", "Động cơ", "Công thay một cuộn đánh lửa sau chẩn đoán; linh kiện tính riêng", 250000, 45),
    ("Kiểm tra rò rỉ dầu động cơ", "Động cơ", "Kiểm tra xác định vị trí rò rỉ; chưa gồm tháo máy/sửa chữa", 350000, 60),
    ("Thay gioăng nắp giàn cò", "Động cơ", "Công thay gioăng nắp giàn cò máy phổ thông; vật tư tính riêng", 650000, 120),
    ("Thay dây curoa phụ", "Động cơ", "Công thay dây curoa phụ; kiểm tra tăng đai, dây tính riêng", 350000, 60),
    ("Thay bơm nước động cơ", "Động cơ", "Công thay bơm nước loại tiếp cận thông thường; phụ tùng tính riêng", 800000, 150),
    ("Thay van hằng nhiệt", "Động cơ", "Công thay van hằng nhiệt, xả khí hệ thống làm mát", 550000, 90),
    ("Kiểm tra hệ thống làm mát", "Động cơ", "Kiểm tra két nước, quạt, ống dẫn và điểm rò rỉ", 300000, 60),
    ("Thay két nước động cơ", "Động cơ", "Công tháo lắp két nước và kiểm tra kín; két/dung dịch tính riêng", 750000, 150),
    ("Thay dầu phanh và xả khí", "Hệ thống phanh", "Công thay dầu phanh và xả khí theo quy trình phù hợp xe", 400000, 75),
    ("Thay má phanh trước", "Hệ thống phanh", "Công thay bộ má phanh trước, kiểm tra đĩa; má tính riêng", 350000, 60),
    ("Thay má phanh sau", "Hệ thống phanh", "Công thay bộ má phanh sau, kiểm tra cơ cấu; má tính riêng", 380000, 75),
    ("Thay đĩa phanh trước", "Hệ thống phanh", "Công thay cặp đĩa phanh trước; đĩa tính riêng", 550000, 90),
    ("Thay đĩa phanh sau", "Hệ thống phanh", "Công thay cặp đĩa phanh sau; đĩa tính riêng", 550000, 90),
    ("Vệ sinh phanh bốn bánh", "Hệ thống phanh", "Tháo kiểm tra và vệ sinh cơ cấu phanh bốn bánh", 550000, 120),
    ("Kiểm tra hệ thống ABS", "Hệ thống phanh", "Đọc lỗi ABS, kiểm tra tín hiệu cảm biến; chưa gồm thay thế", 350000, 60),
    ("Cân bằng động bốn bánh", "Lốp", "Cân bằng động bốn bánh; chưa gồm tháo lốp đặc biệt", 300000, 60),
    ("Vá lốp không săm", "Lốp", "Kiểm tra và vá một vị trí lốp nếu đủ điều kiện an toàn", 120000, 30),
    ("Thay lốp một bánh", "Lốp", "Công tháo lắp một lốp và bơm đúng áp suất; lốp tính riêng", 150000, 30),
    ("Kiểm tra và chỉnh góc đặt bánh xe", "Lốp", "Đo và chỉnh góc đặt trên xe đủ điều kiện; sửa gầm tính riêng", 550000, 90),
    ("Thay giảm xóc trước một bên", "Gầm", "Công thay giảm xóc trước một bên; cân chỉnh nếu cần tính riêng", 550000, 90),
    ("Thay giảm xóc sau một bên", "Gầm", "Công thay giảm xóc sau một bên; phụ tùng tính riêng", 400000, 75),
    ("Thay rô tuyn lái ngoài một bên", "Gầm", "Công thay rô tuyn lái; cần kiểm tra góc đặt sau sửa", 400000, 75),
    ("Thay rô tuyn cân bằng một bên", "Gầm", "Công thay rô tuyn cân bằng; phụ tùng tính riêng", 320000, 60),
    ("Thay bi moay-ơ một bên", "Gầm", "Công thay bi moay-ơ một bên loại thông dụng", 650000, 120),
    ("Kiểm tra hệ thống treo và lái", "Gầm", "Kiểm tra độ rơ, cao su, giảm xóc và cơ cấu lái", 300000, 60),
    ("Thay dầu hộp số sàn", "Hộp số", "Công xả và châm dầu hộp số sàn đúng cấp dầu", 350000, 60),
    ("Thay dầu hộp số tự động xả đáy", "Hộp số", "Công thay dầu AT theo phương pháp xả đáy; dầu tính riêng", 500000, 90),
    ("Thay dầu hộp số CVT xả đáy", "Hộp số", "Công thay dầu CVT đúng đặc tính; dầu tính riêng", 550000, 90),
    ("Thay dầu cầu sau", "Hộp số", "Công xả/châm dầu cầu sau; dầu tính riêng", 300000, 45),
    ("Kiểm tra ly hợp và hộp số", "Hộp số", "Chạy thử và kiểm tra triệu chứng ly hợp/hộp số; chưa gồm tháo", 350000, 60),
    ("Chẩn đoán lỗi bằng máy quét", "Kiểm tra", "Đọc mã lỗi và thông số hiện hành; không thay thế chẩn đoán sâu", 350000, 60),
    ("Kiểm tra ắc quy và hệ thống sạc", "Điện - ắc quy", "Đo ắc quy, máy phát và kiểm tra đầu cực", 200000, 30),
    ("Thay ắc quy ô tô", "Điện - ắc quy", "Công thay ắc quy, kiểm tra sạc; bình tính riêng", 180000, 30),
    ("Kiểm tra máy phát điện", "Điện - ắc quy", "Kiểm tra điện áp sạc và dây curoa, chưa gồm sửa máy phát", 300000, 45),
    ("Thay bóng đèn pha", "Điện - ắc quy", "Công thay một bóng đèn pha loại dễ tiếp cận", 180000, 30),
    ("Thay gạt mưa trước", "Điện - ắc quy", "Công thay cặp lưỡi gạt mưa trước; vật tư tính riêng", 120000, 20),
    ("Kiểm tra hệ thống điều hòa", "Điều hòa", "Kiểm tra áp suất, rò rỉ và hiệu suất làm lạnh", 300000, 60),
    ("Nạp gas điều hòa sau kiểm tra", "Điều hòa", "Công hút chân không/nạp gas phù hợp; gas tính riêng", 450000, 90),
    ("Vệ sinh dàn lạnh điều hòa", "Điều hòa", "Vệ sinh dàn lạnh theo phương án tiếp cận phù hợp", 850000, 150),
    ("Thay lốc điều hòa", "Điều hòa", "Công thay lốc điều hòa và kiểm tra đường ống; vật tư tính riêng", 1400000, 240),
    ("Đánh bóng đèn pha hai bên", "Chăm sóc xe", "Đánh bóng bề mặt chóa đèn hai bên; đánh giá tình trạng trước", 550000, 90),
    ("Đánh bóng sơn một bước", "Chăm sóc xe", "Đánh bóng sơn ngoại thất một bước, không gồm xử lý sơn hư nặng", 1800000, 240),
    ("Dọn nội thất chuyên sâu", "Chăm sóc xe", "Vệ sinh ghế, trần, sàn, taplo; cần khảo sát trước khi làm", 1500000, 300),
]

# Mỗi dòng là một nhóm hàng *gợi ý tìm kiếm* theo mẫu xe, không phải mã OEM
# hay xác nhận tương thích. Giá bán từng dòng được nội suy từ khoảng giá công khai,
# không phải giá chào của nguồn. Giá vốn giữ 0; tồn kho khởi tạo là giả lập.
VEHICLES = [
    ("TVI", "Toyota Vios", 0), ("TCO", "Toyota Corolla", 90),
    ("MCX", "Mazda CX-5", 140), ("HAC", "Hyundai Accent", 30),
    ("HTU", "Hyundai Tucson", 130), ("KSE", "Kia Seltos", 95),
    ("MXP", "Mitsubishi Xpander", 75), ("FRA", "Ford Ranger", 180),
]

# short code, name, category, unit, sample price in thousands, SUV/pickup adjustment applies
PART_FAMILIES = [
    ("AF", "Lọc gió động cơ", "Lọc - dầu", "cái", 260),
    ("CF", "Lọc gió điều hòa", "Điều hòa", "cái", 280),
    ("OF", "Lọc dầu động cơ", "Lọc - dầu", "cái", 210),
    ("FF", "Lọc nhiên liệu", "Lọc - dầu", "cái", 490),
    ("BPF", "Bộ má phanh trước", "Hệ thống phanh", "bộ", 1150),
    ("BPR", "Bộ má phanh sau", "Hệ thống phanh", "bộ", 950),
    ("RDF", "Đĩa phanh trước", "Hệ thống phanh", "cái", 1500),
    ("RDR", "Đĩa phanh sau", "Hệ thống phanh", "cái", 1350),
    ("SHF", "Giảm xóc trước", "Gầm", "cái", 1550),
    ("SHR", "Giảm xóc sau", "Gầm", "cái", 1250),
    ("FPU", "Bơm nhiên liệu", "Động cơ", "cái", 1750),
    ("IC", "Cuộn đánh lửa", "Động cơ", "cái", 1100),
    ("BEL", "Dây curoa phụ", "Động cơ", "sợi", 570),
    ("TH", "Van hằng nhiệt", "Động cơ", "cái", 720),
    ("RAD", "Két nước động cơ", "Động cơ", "cái", 2100),
    ("PUMP", "Bơm nước động cơ", "Động cơ", "cái", 1550),
    ("BEAR", "Bi moay-ơ trước", "Gầm", "cái", 1100),
    ("TIE", "Rô tuyn lái ngoài", "Gầm", "cái", 530),
    ("LINK", "Rô tuyn cân bằng trước", "Gầm", "cái", 430),
    ("WIP", "Bộ lưỡi gạt mưa trước", "Chăm sóc xe", "bộ", 360),
]

# code, name, category, unit, indicative selling price (thousands of VND)
CONSUMABLES = [
    ("OIL-0W20-1", "Dầu động cơ 0W-20 chai 1L", "Dầu nhớt", "chai", 260),
    ("OIL-0W20-4", "Dầu động cơ 0W-20 can 4L", "Dầu nhớt", "can", 980),
    ("OIL-5W30-1", "Dầu động cơ 5W-30 chai 1L", "Dầu nhớt", "chai", 225),
    ("OIL-5W30-4", "Dầu động cơ 5W-30 can 4L", "Dầu nhớt", "can", 820),
    ("OIL-5W40-4", "Dầu động cơ 5W-40 can 4L", "Dầu nhớt", "can", 890),
    ("OIL-10W40-4", "Dầu động cơ 10W-40 can 4L", "Dầu nhớt", "can", 620),
    ("ATF-1", "Dầu hộp số tự động ATF chai 1L", "Dầu nhớt", "chai", 350),
    ("CVT-1", "Dầu hộp số CVT chai 1L", "Dầu nhớt", "chai", 420),
    ("GEAR-75W90-1", "Dầu hộp số sàn 75W-90 chai 1L", "Dầu nhớt", "chai", 320),
    ("GEAR-80W90-1", "Dầu cầu 80W-90 chai 1L", "Dầu nhớt", "chai", 240),
    ("BRK-DOT3-500", "Dầu phanh DOT 3 chai 500ml", "Dung dịch", "chai", 180),
    ("BRK-DOT4-500", "Dầu phanh DOT 4 chai 500ml", "Dung dịch", "chai", 230),
    ("COOL-RED-1", "Nước làm mát pha sẵn màu đỏ 1L", "Dung dịch", "chai", 190),
    ("COOL-GREEN-1", "Nước làm mát pha sẵn màu xanh 1L", "Dung dịch", "chai", 180),
    ("WASH-2", "Nước rửa kính ô tô can 2L", "Dung dịch", "can", 110),
    ("AC-GAS-R134A", "Gas điều hòa R134a bình 1kg", "Điều hòa", "bình", 680),
    ("AC-OIL-250", "Dầu lạnh điều hòa chai 250ml", "Điều hòa", "chai", 340),
    ("BAT-45AH", "Ắc quy ô tô 12V 45Ah", "Điện - ắc quy", "bình", 1350),
    ("BAT-60AH", "Ắc quy ô tô 12V 60Ah", "Điện - ắc quy", "bình", 1750),
    ("BAT-70AH", "Ắc quy ô tô 12V 70Ah", "Điện - ắc quy", "bình", 2100),
    ("BULB-H4", "Bóng đèn pha halogen H4", "Điện - ắc quy", "cái", 210),
    ("BULB-H7", "Bóng đèn pha halogen H7", "Điện - ắc quy", "cái", 240),
    ("SIGNAL-PY21W", "Bóng xi nhan vàng PY21W 12V 21W", "Điện - ắc quy", "cái", 65),
    ("SIGNAL-WY5W", "Bóng xi nhan vàng WY5W 12V 5W", "Điện - ắc quy", "cái", 45),
    ("SIGNAL-WY21W", "Bóng xi nhan vàng WY21W 12V 21W", "Điện - ắc quy", "cái", 85),
    ("SIGNAL-SOCKET-BAU15S", "Đui bóng xi nhan BAU15s", "Điện - ắc quy", "cái", 90),
    ("SIGNAL-RELAY-2PIN", "Rơ-le chớp xi nhan 12V loại 2 chân", "Điện - ắc quy", "cái", 150),
    ("TIRE-185-65R15", "Lốp ô tô 185/65R15 phổ thông", "Lốp", "cái", 1450),
    ("TIRE-195-65R15", "Lốp ô tô 195/65R15 phổ thông", "Lốp", "cái", 1650),
    ("TIRE-205-55R16", "Lốp ô tô 205/55R16 phổ thông", "Lốp", "cái", 1950),
    ("TIRE-215-60R17", "Lốp ô tô 215/60R17 SUV/CUV", "Lốp", "cái", 2450),
    ("TIRE-265-65R17", "Lốp ô tô 265/65R17 bán tải/SUV", "Lốp", "cái", 3150),
    ("TIRE-MODEL-MI-PRIMACY4", "Lốp Michelin Primacy 4 (chọn kích thước)", "Lốp", "cái", 2650),
    ("TIRE-MODEL-BS-T005A", "Lốp Bridgestone Turanza T005A (chọn kích thước)", "Lốp", "cái", 2450),
    ("TIRE-MODEL-CT-CC6", "Lốp Continental ComfortContact CC6 (chọn kích thước)", "Lốp", "cái", 1950),
    ("TIRE-MODEL-MI-PS5", "Lốp Michelin Pilot Sport 5 (chọn kích thước)", "Lốp", "cái", 3350),
    ("TIRE-MODEL-DL-LM705", "Lốp Dunlop SP Sport LM705 (chọn kích thước)", "Lốp", "cái", 1850),
    ("CLEAN-BRAKE", "Dung dịch vệ sinh phanh chai 500ml", "Vật tư tiêu hao", "chai", 130),
    ("CLEAN-THROTTLE", "Dung dịch vệ sinh họng ga chai 500ml", "Vật tư tiêu hao", "chai", 170),
]


COMMON_MODELS = "Toyota Vios/Corolla, Mazda CX-5, Hyundai Accent/Tucson, Kia Seltos, Mitsubishi Xpander, Ford Ranger"


def consumable_compatibility(code):
    """Gợi ý tra cứu có điều kiện; không thay thế đối chiếu VIN/thông số kỹ thuật."""
    tire_models = {
        "TIRE-185-65R15": "Toyota Vios, Hyundai Accent bản dùng lốp 185/65R15",
        "TIRE-195-65R15": "Toyota Corolla và xe dùng lốp 195/65R15",
        "TIRE-205-55R16": "Toyota Corolla, Hyundai Elantra và xe dùng lốp 205/55R16",
        "TIRE-215-60R17": "Hyundai Tucson, Kia Seltos và SUV/CUV dùng lốp 215/60R17",
        "TIRE-265-65R17": "Ford Ranger và bán tải/SUV dùng lốp 265/65R17",
    }
    tire_product_profiles = {
        "TIRE-MODEL-MI-PRIMACY4": "Sedan/CUV; thiên về vận hành êm, hạn chế tiếng ồn và bám đường ướt",
        "TIRE-MODEL-BS-T005A": "Sedan/SUV chạy phố; thiên về độ êm, tĩnh lặng và độ bền",
        "TIRE-MODEL-CT-CC6": "Sedan/CUV; thiên về giảm ồn và thoải mái trên hành trình dài",
        "TIRE-MODEL-MI-PS5": "Sedan/coupe hiệu suất cao; thiên về độ bám và phản hồi lái thể thao",
        "TIRE-MODEL-DL-LM705": "Sedan/CUV; cân bằng chi phí, độ êm và hạn chế tiếng ồn mặt đường",
    }
    if code in tire_product_profiles:
        return f"{tire_product_profiles[code]}; phải chọn đúng kích thước, tải trọng, cấp tốc độ và thông số mâm theo xe"
    if code in tire_models:
        return f"Gợi ý: {tire_models[code]}; phải đối chiếu tem lốp, mâm, tải trọng và cấp tốc độ"
    if code.startswith("SIGNAL-"):
        return f"{COMMON_MODELS} nếu hệ thống 12V và đúng chuẩn chân/công suất; kiểm tra bóng cũ trước khi lắp"
    if code.startswith("BULB-"):
        standard = code.removeprefix("BULB-")
        return f"{COMMON_MODELS} trên phiên bản dùng chân {standard}; đối chiếu cụm đèn thực tế"
    if code.startswith("BAT-"):
        capacity = code.removeprefix("BAT-")
        return f"Xe 12V trong nhóm {COMMON_MODELS} nếu đúng kích thước, cọc, chiều cọc và dung lượng {capacity}"
    if code.startswith("OIL-"):
        grade = code.split("-")[1]
        return f"{COMMON_MODELS} khi tài liệu nhà sản xuất cho phép dầu SAE {grade}; kiểm tra API/ACEA và dung tích"
    if code == "ATF-1":
        return f"Xe số tự động trong nhóm {COMMON_MODELS} khi đúng chuẩn ATF của hộp số; không dùng thay dầu CVT"
    if code == "CVT-1":
        return "Toyota Vios/Corolla và xe dùng hộp số CVT khi đúng chuẩn dầu của nhà sản xuất"
    if code.startswith("GEAR-"):
        return f"Xe số sàn/cầu trong nhóm {COMMON_MODELS} khi đúng cấp SAE và chuẩn GL theo tài liệu xe"
    if code.startswith("BRK-"):
        grade = "DOT 4" if "DOT4" in code else "DOT 3"
        return f"{COMMON_MODELS} khi nắp bình dầu/tài liệu xe cho phép {grade}; không trộn sai chuẩn"
    if code.startswith("COOL-"):
        return f"{COMMON_MODELS} khi đúng tiêu chuẩn nước làm mát của hãng; màu sắc không quyết định tương thích"
    if code == "WASH-2":
        return f"Bình rửa kính của {COMMON_MODELS}; không châm vào bình nước làm mát"
    if code.startswith("AC-"):
        return f"Hệ thống điều hòa của {COMMON_MODELS} khi đúng loại môi chất/dầu ghi trên tem khoang máy"
    if code.startswith("CLEAN-"):
        return f"Vật tư bảo dưỡng cho {COMMON_MODELS}; kỹ thuật viên kiểm tra bề mặt và hướng dẫn sản phẩm trước khi dùng"
    return f"Gợi ý cho {COMMON_MODELS}; phải đối chiếu VIN, mã và thông số thực tế trước khi dùng"


def catalog_parts():
    """Danh mục DEMO đã bị loại bỏ; giữ iterator rỗng cho caller cũ."""
    return iter(())


def fill_empty_stock_once(db):
    """Gán tồn kho giả lập cho mã đang hết; KHÔNG gọi từ seed khởi động."""
    return db.execute("UPDATE parts SET stock=5 WHERE stock=0").rowcount


def seed_expanded_catalog(db):
    """Chỉ bổ sung dịch vụ; không tạo lại phụ tùng DEMO đã bị loại bỏ."""
    db.executemany(
        "INSERT OR IGNORE INTO services(name,category,description,price,duration_min,active) "
        "VALUES(?,?,?,?,?,1)", CATALOG_SERVICES,
    )


if __name__ == "__main__":
    import sys

    from .database import connect, transaction

    if len(sys.argv) > 2 or (len(sys.argv) == 2 and sys.argv[1] != "--fill-demo-stock"):
        raise SystemExit("Usage: python -m backend.catalog_expansion [--fill-demo-stock]")
    db = connect()
    try:
        with transaction(db):
            seed_expanded_catalog(db)
            if len(sys.argv) == 2:
                print("Stock entries filled:", fill_empty_stock_once(db))
        print("Services:", db.execute("SELECT count(*) FROM services").fetchone()[0])
        print("Parts/consumables:", db.execute("SELECT count(*) FROM parts").fetchone()[0])
    finally:
        db.close()
