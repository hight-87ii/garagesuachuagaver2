import os
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from .migrations import run_migrations
from .money import with_tax
from .timeutil import VN_TZ, to_utc_iso

DB_PATH = Path(os.getenv("DATABASE_PATH", Path(__file__).parent / "garage.db"))


def connect() -> sqlite3.Connection:
    """Mở kết nối SQLite ở chế độ tự quản lý transaction (autocommit)."""
    connection = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    connection.row_factory = sqlite3.Row
    def vi_fold(value):
        text = unicodedata.normalize("NFD", str(value or "").replace("Đ", "D").replace("đ", "d"))
        return "".join(char for char in text if unicodedata.category(char) != "Mn").casefold()
    connection.create_function("vi_fold", 1, vi_fold, deterministic=True)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def transaction(db: sqlite3.Connection):
    """Bọc nhiều thao tác ghi trong một transaction nguyên tử."""
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except BaseException:
        db.execute("ROLLBACK")
        raise
    db.execute("COMMIT")


def init_db() -> None:
    db = connect()
    try:
        run_migrations(db)
        seed_demo_data(db)
        from .technical_starter_data import seed_reference_articles
        seed_reference_articles(db)
        from .oil_interval_data import seed_oil_intervals
        seed_oil_intervals(db)
        from .popular_vehicle_fitments import seed_popular_vehicle_fitments
        seed_popular_vehicle_fitments(db)
    finally:
        db.close()


DEMO_USERS = [
    ("Quản trị hệ thống", "admin@garage.vn", "Admin@123", "Admin"),
    ("Hoàng Nam", "manager@garage.vn", "Manager@123", "Quản lý"),
    ("Nguyễn Lan", "reception@garage.vn", "Reception@123", "Lễ tân"),
    ("Trần Tuấn", "technician@garage.vn", "Technician@123", "Kỹ thuật viên"),
    ("Lê Mai", "cashier@garage.vn", "Cashier@123", "Thu ngân"),
    ("Nguyễn Minh Anh", "customer@garage.vn", "Customer@123", "Khách hàng"),
    ("Hoàng Văn Hà", "ha.hoang@garage-demo.vn", "Ha@123456", "Khách hàng"),
    ("Hoàng Công Sự", "su.hoang@garage-demo.vn", "Su@123456", "Khách hàng"),
    ("Hoàng Minh Tuất", "tuat.hoang@garage-demo.vn", "Tuat@123456", "Khách hàng"),
]

SERVICES = [
    ("Bảo dưỡng định kỳ", "Bảo dưỡng", "Kiểm tra tổng thể và thay thế vật tư theo định kỳ", 850000, 120),
    ("Thay dầu động cơ", "Bảo dưỡng", "Thay dầu động cơ và kiểm tra mức dung dịch", 450000, 45),
    ("Kiểm tra hệ thống phanh", "Sửa chữa", "Kiểm tra má phanh, đĩa phanh và hệ thống thủy lực", 350000, 60),
    ("Vệ sinh điều hòa", "Chăm sóc xe", "Vệ sinh lọc gió và khử mùi hệ thống điều hòa", 650000, 90),
    ("Cân chỉnh bánh xe", "Lốp", "Cân bằng động và kiểm tra góc đặt bánh xe", 300000, 60),
    ("Kiểm tra tổng quát", "Kiểm tra", "Kiểm tra nhanh các hệ thống quan trọng của xe", 250000, 45),
]

# Giá công và thời lượng MINH HỌA của garage demo. Không gồm vật tư phát sinh;
# nhân viên cần cập nhật giá thực tế trong Danh mục dịch vụ trước khi gửi báo giá.
EXTRA_SERVICES = [
    ("Vệ sinh xe cơ bản", "Chăm sóc xe", "Rửa ngoại thất, hút bụi nội thất cơ bản; không gồm tẩy ố hoặc đánh bóng", 180000, 45),
    ("Rửa xe ngoại thất", "Chăm sóc xe", "Rửa và lau khô thân xe, kính và bánh xe bên ngoài", 120000, 30),
    ("Vệ sinh nội thất", "Chăm sóc xe", "Hút bụi, vệ sinh ghế, taplo và thảm ở mức thông thường", 650000, 120),
    ("Vệ sinh khoang máy", "Chăm sóc xe", "Vệ sinh khoang động cơ sau khi kiểm tra an toàn điện và che chắn", 300000, 60),
    ("Khử mùi nội thất", "Chăm sóc xe", "Làm sạch mùi nhẹ trong cabin sau khi kiểm tra nguyên nhân", 250000, 45),
    ("Thay lọc dầu động cơ", "Bảo dưỡng", "Công thay lọc dầu; lọc dầu là vật tư tính riêng nếu cần", 150000, 20),
    ("Thay lọc gió động cơ", "Bảo dưỡng", "Công thay lọc gió; phụ tùng tính riêng theo xe", 180000, 25),
    ("Thay lọc gió điều hòa", "Bảo dưỡng", "Công thay lọc gió cabin; phụ tùng tính riêng theo xe", 180000, 25),
    ("Thay nước làm mát", "Bảo dưỡng", "Xả và bổ sung nước làm mát phù hợp; dung dịch tính riêng", 420000, 60),
    ("Thay dầu hộp số", "Bảo dưỡng", "Công thay dầu hộp số theo cấu hình xe; dầu và lọc tính riêng", 900000, 120),
    ("Vệ sinh họng gió", "Bảo dưỡng", "Vệ sinh họng ga/họng gió sau khi kỹ thuật viên kiểm tra", 450000, 60),
    ("Vệ sinh kim phun", "Bảo dưỡng", "Vệ sinh hệ thống phun nhiên liệu sau khi kiểm tra kỹ thuật", 480000, 90),
    ("Vệ sinh và căn chỉnh phanh", "Sửa chữa", "Vệ sinh cơ cấu phanh và kiểm tra căn chỉnh, chưa gồm phụ tùng", 640000, 90),
    ("Đảo lốp", "Lốp", "Đảo vị trí bánh xe và kiểm tra áp suất", 220000, 45),
]

PARTS = [
    ("LF10-14-302", "Lọc dầu Mazda", "Lọc - dầu", "Mazda CX-5, Mazda 3", 260000, 320000, 3, 5, "Phụ tùng Thành Công"),
    ("BP-TOY-482", "Má phanh trước Toyota", "Hệ thống phanh", "Toyota Camry, Corolla", 1800000, 2150000, 2, 4, "Toyota Parts Việt Nam"),
    ("AF-HY-221", "Lọc gió động cơ Hyundai", "Lọc - dầu", "Hyundai Tucson, Santa Fe", 340000, 450000, 18, 5, "AutoParts Hà Nội"),
    ("OL-5W30-04", "Dầu động cơ 5W-30 4L", "Dầu nhớt", "Mazda, Toyota, Kia", 540000, 680000, 24, 8, "Shell Lubricants"),
    ("SP-KIA-09", "Bugi Kia Seltos", "Động cơ", "Kia Seltos 2020-2023", 130000, 185000, 1, 4, "Kia Service"),
    ("AC-FLT-112", "Lọc gió điều hòa", "Điều hòa", "Mazda, Toyota, Hyundai", 210000, 290000, 12, 5, "Phụ tùng Minh Long"),
]

# Danh mục mẫu bổ sung: giá và tương thích chỉ để tham khảo trong môi trường demo.
# Không khẳng định lắp vừa trước khi nhân viên đối chiếu đời xe, mã linh kiện và VIN.
EXTRA_PARTS = [
    # code, name, category, compatible, unit, cost_price, sell_price, stock, min_stock
    ("AF-VIO-2020", "Lọc gió động cơ Toyota Vios", "Lọc - dầu", "Toyota Vios 2018-2022", "cái", 165000, 245000, 12, 4),
    ("OF-RAN-2021", "Lọc dầu động cơ Ford Ranger", "Lọc - dầu", "Ford Ranger 2019-2022", "cái", 205000, 295000, 9, 4),
    ("BP-VIO-2020", "Bộ má phanh trước Toyota Vios", "Hệ thống phanh", "Toyota Vios 2018-2022", "bộ", 880000, 1190000, 5, 3),
    ("BR-CX5-2021", "Đĩa phanh trước Mazda CX-5", "Hệ thống phanh", "Mazda CX-5 2019-2022", "cái", 1320000, 1690000, 4, 2),
    ("AC-CX5-2021", "Lọc gió điều hòa Mazda CX-5", "Điều hòa", "Mazda CX-5 2019-2022", "cái", 185000, 265000, 13, 5),
    ("BT-ACC-2022", "Ắc quy Hyundai Accent", "Điện - ắc quy", "Hyundai Accent 2020-2023", "bình", 1320000, 1690000, 5, 3),
    ("WP-CAM-2020", "Bộ gạt mưa Toyota Camry", "Chăm sóc xe", "Toyota Camry 2018-2022", "bộ", 240000, 350000, 8, 3),
    ("SH-RAN-2021", "Giảm xóc sau Ford Ranger", "Gầm", "Ford Ranger 2019-2022", "cái", 1170000, 1490000, 3, 3),
    ("COOL-LL-01", "Nước làm mát động cơ loại dài hạn 1L", "Dung dịch", "Toyota, Mazda, Hyundai, Ford, Kia", "chai", 140000, 210000, 20, 6),
    ("SP-SEL-2022", "Bộ bugi Kia Seltos", "Động cơ", "Kia Seltos 2020-2023", "bộ", 580000, 780000, 7, 3),
    ("AC-CRV-2019", "Lọc gió điều hòa Honda CR-V", "Điều hòa", "Honda CR-V 2017-2020", "cái", 200000, 285000, 5, 3),
    ("AF-XPA-2023", "Lọc gió động cơ Mitsubishi Xpander", "Lọc - dầu", "Mitsubishi Xpander 2022-2024", "cái", 190000, 275000, 10, 4),
]

# Danh mục bóng đèn do garage cung cấp. Thông số chưa được cung cấp được ghi rõ
# là cần đối chiếu trên nhãn sản phẩm, không tự suy đoán công suất hay lắp vừa.
# code, name, category, compatible, unit, cost, sell, stock, min_stock, supplier,
# compatibility_accuracy, usage_requirements, price_note, supplier_note,
# technical_description, technical_specs, usage_instructions
LIGHTING_PARTS = [
    ("BD001", "Bóng đèn pha H4 Halogen", "Đèn pha", "Xe 12V có cụm đèn dùng chân H4", "cái", 60000, 90000, 30, 5, "Chưa chỉ định", "Tương thích có điều kiện theo chuẩn chân H4; chưa có dữ liệu hãng, dòng xe hoặc đời xe.", "Đối chiếu chân bóng, điện áp, công suất ghi trên bóng cũ và hướng dẫn của xe; ngắt nguồn trước khi thay.", "Giá nhập 60.000đ và giá bán 90.000đ do garage cung cấp; chưa kèm thời điểm hiệu lực.", "Chưa có tên, mã nhà cung cấp hoặc thông tin bảo hành.", "Bóng halogen H4 dùng cho cụm đèn pha phù hợp, thường tích hợp chức năng chiếu gần và chiếu xa trong cùng bóng.", "Chuẩn chân H4; công nghệ Halogen; điện áp và công suất phải kiểm tra trên nhãn sản phẩm thực tế.", "Không chạm tay trực tiếp vào phần thủy tinh; lắp đúng ngàm, đậy kín nắp chống bụi và kiểm tra luồng sáng sau khi thay."),
    ("BD002", "Bóng đèn pha H7 Halogen", "Đèn pha", "Xe 12V có cụm đèn dùng chân H7", "cái", 70000, 110000, 25, 5, "Chưa chỉ định", "Tương thích có điều kiện theo chuẩn chân H7; chưa có dữ liệu hãng, dòng xe hoặc đời xe.", "Đối chiếu chân bóng, điện áp, công suất ghi trên bóng cũ và hướng dẫn của xe; ngắt nguồn trước khi thay.", "Giá nhập 70.000đ và giá bán 110.000đ do garage cung cấp; chưa kèm thời điểm hiệu lực.", "Chưa có tên, mã nhà cung cấp hoặc thông tin bảo hành.", "Bóng halogen H7 dùng cho vị trí chiếu sáng riêng biệt trên cụm đèn pha phù hợp.", "Chuẩn chân H7; công nghệ Halogen; điện áp và công suất phải kiểm tra trên nhãn sản phẩm thực tế.", "Không chạm tay trực tiếp vào phần thủy tinh; lắp đúng ngàm, đậy kín nắp chống bụi và kiểm tra luồng sáng sau khi thay."),
    ("BD003", "Bóng đèn LED H4", "Đèn pha LED", "Xe 12V có cụm đèn dùng chân H4 và đủ không gian cho bộ tản nhiệt", "cái", 250000, 380000, 12, 4, "Chưa chỉ định", "Chỉ xác nhận chuẩn chân H4; chưa có dữ liệu kích thước, công suất, màu sáng, hãng, dòng xe hoặc đời xe.", "Kiểm tra điện áp, kích thước tản nhiệt, chụp chống bụi, hướng chip LED, khả năng báo lỗi và quy định chiếu sáng trước khi lắp.", "Giá nhập 250.000đ và giá bán 380.000đ do garage cung cấp; chưa kèm thời điểm hiệu lực.", "Chưa có tên, mã nhà cung cấp, thương hiệu hoặc thông tin bảo hành.", "Bóng LED thay thế theo chuẩn chân H4 cho cụm đèn tương thích; cần đánh giá quang học và khả năng tản nhiệt trên xe thực tế.", "Chuẩn chân H4; công nghệ LED; công suất, nhiệt màu, quang thông và chuẩn chống nước chưa được cung cấp.", "Lắp đúng hướng chip LED theo thiết kế cụm đèn, cố định bộ tản nhiệt/driver, kiểm tra chóa cắt sáng và không sử dụng nếu gây chói hoặc báo lỗi."),
    ("BD004", "Bóng đèn P21W", "Đèn phanh/chiếu sáng", "Xe 12V có đui và chân bóng phù hợp chuẩn P21W", "cái", 15000, 25000, 50, 10, "Chưa chỉ định", "Tương thích có điều kiện theo chuẩn P21W; phải đối chiếu kiểu chân đế, màu bóng và vị trí sử dụng.", "Đối chiếu bóng cũ và sơ đồ đèn của xe; không thay bằng bóng khác công suất hoặc sai màu quy định.", "Giá nhập 15.000đ và giá bán 25.000đ do garage cung cấp; chưa kèm thời điểm hiệu lực.", "Chưa có tên, mã nhà cung cấp hoặc thông tin bảo hành.", "Bóng sợi đốt P21W dùng cho vị trí đèn phanh hoặc chiếu sáng tín hiệu khi cụm đèn quy định đúng chuẩn.", "Chuẩn P21W; công suất danh định 21W theo ký hiệu; điện áp, kiểu chân đế và màu bóng phải kiểm tra trên sản phẩm thực tế.", "Ngắt nguồn, tháo bóng nguội, lắp đúng chốt định vị và kiểm tra đầy đủ chức năng đèn sau khi thay."),
    ("BD005", "Bóng đèn W5W", "Đèn vị trí/nội thất", "Xe 12V có đui cắm phù hợp chuẩn W5W", "cái", 8000, 15000, 60, 10, "Chưa chỉ định", "Tương thích có điều kiện theo chuẩn W5W; phải đối chiếu kích thước, màu bóng và vị trí sử dụng.", "Đối chiếu bóng cũ và sơ đồ đèn của xe; dùng đúng màu sáng theo vị trí và quy định áp dụng.", "Giá nhập 8.000đ và giá bán 15.000đ do garage cung cấp; chưa kèm thời điểm hiệu lực.", "Chưa có tên, mã nhà cung cấp hoặc thông tin bảo hành.", "Bóng chân cắm W5W dùng cho đèn vị trí, đèn biển số hoặc một số vị trí nội thất khi cụm đèn quy định đúng chuẩn.", "Chuẩn W5W; công suất danh định 5W theo ký hiệu; điện áp và kích thước phải kiểm tra trên sản phẩm thực tế.", "Ngắt nguồn, kéo bóng thẳng khỏi đui, lắp chắc chắn và kiểm tra chức năng trước khi đóng lại cụm đèn."),
    ("BD006", "Bóng đèn H11 Halogen", "Đèn sương mù/chiếu sáng", "Xe 12V có cụm đèn dùng chân H11", "cái", 80000, 120000, 20, 5, "Chưa chỉ định", "Tương thích có điều kiện theo chuẩn chân H11; chưa có dữ liệu hãng, dòng xe hoặc đời xe.", "Đối chiếu chân bóng, điện áp, công suất ghi trên bóng cũ và hướng dẫn của xe; ngắt nguồn trước khi thay.", "Giá nhập 80.000đ và giá bán 120.000đ do garage cung cấp; chưa kèm thời điểm hiệu lực.", "Chưa có tên, mã nhà cung cấp hoặc thông tin bảo hành.", "Bóng halogen H11 dùng cho đèn sương mù hoặc vị trí chiếu sáng có cụm đèn tương thích.", "Chuẩn chân H11; công nghệ Halogen; điện áp và công suất phải kiểm tra trên nhãn sản phẩm thực tế.", "Không chạm tay trực tiếp vào phần thủy tinh; xoay khóa đúng khớp, kiểm tra gioăng kín và thử đèn sau khi thay."),
]


def seed_demo_data(db) -> None:
    from .auth_service import hash_password
    from .workflow import ensure_status_history

    with transaction(db):
        for full_name, email, password, role in DEMO_USERS:
            db.execute(
                """
                INSERT INTO users(full_name, email, password_hash, role, status)
                VALUES(?, ?, ?, ?, 'active')
                ON CONFLICT(email) DO UPDATE SET
                    full_name = excluded.full_name,
                    password_hash = excluded.password_hash,
                    role = excluded.role,
                    status = 'active'
                """,
                (full_name, email, hash_password(password), role),
            )

        if db.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
            db.executemany(
                "INSERT INTO customers(name, phone, email, address) VALUES(?, ?, ?, '')",
                [
                    ("Nguyễn Minh Anh", "090 123 4567", "customer@garage.vn"),
                    ("Trần Quốc Huy", "091 886 2204", "huy.tran@email.vn"),
                    ("Lê Thu Hà", "098 331 7702", "ha.le@email.vn"),
                ],
            )

        db.execute(
            "UPDATE customers SET address='18 Nguyễn Huệ, Quận 1, TP.HCM' "
            "WHERE name='Nguyễn Minh Anh' AND address=''"
        )
        # Hoàn thiện hồ sơ tài khoản khách hàng demo để cổng thông tin cá nhân
        # luôn có dữ liệu xe, liên hệ và lịch sử nhất quán sau mỗi lần khởi tạo.
        db.execute(
            "UPDATE users SET phone=COALESCE(NULLIF(phone,''), '090 123 4567') "
            "WHERE email='customer@garage.vn'"
        )
        db.execute(
            "UPDATE customers SET email='customer@garage.vn', "
            "address=COALESCE(NULLIF(address,''), '18 Nguyễn Huệ, Quận 1, TP.HCM'), "
            "note=COALESCE(NULLIF(note,''), 'Khách hàng cá nhân sử dụng cổng ThreeH Workshop') "
            "WHERE name='Nguyễn Minh Anh' AND phone='090 123 4567'"
        )

        extra_customers = [
            ("Đặng Quốc Bảo", "093 771 4455", "bao.dang@email.vn", "12 Lê Văn Việt, Quận 9, TP.HCM"),
            ("Vũ Hoàng Yến", "097 220 6631", "yen.vu@email.vn", "45 Nguyễn Trãi, Hà Đông, Hà Nội"),
            ("Bùi Thanh Sơn", "090 664 8890", "son.bui@email.vn", "88 Trần Hưng Đạo, Quận 5, TP.HCM"),
            ("Hoàng Văn Hà", "098 611 2233", "ha.hoang@garage-demo.vn", "12 Lương Ngọc Quyến, phường Hoàng Văn Thụ, TP. Thái Nguyên"),
            ("Hoàng Công Sự", "097 522 3344", "su.hoang@garage-demo.vn", "86 Bắc Kạn, phường Quang Trung, TP. Thái Nguyên"),
            ("Hoàng Minh Tuất", "096 433 4455", "tuat.hoang@garage-demo.vn", "35 Cách Mạng Tháng Tám, phường Trưng Vương, TP. Thái Nguyên"),
        ]
        for name, phone, email, address in extra_customers:
            if not db.execute("SELECT id FROM customers WHERE phone=?", (phone,)).fetchone():
                db.execute(
                    "INSERT INTO customers(name, phone, email, address) VALUES(?, ?, ?, ?)",
                    (name, phone, email, address),
                )

        def customer_id(phone: str) -> int | None:
            row = db.execute("SELECT id FROM customers WHERE phone=?", (phone,)).fetchone()
            return row["id"] if row else None

        vehicles = [
            (customer_id("090 123 4567"), "51H-123.45", "Mazda", "CX-5", 2021, "JMZKE1972L0123456", 42500),
            (customer_id("091 886 2204"), "30G-888.68", "Toyota", "Camry", 2020, "LVGBD1AK0LG123456", 58900),
            (customer_id("098 331 7702"), "51K-456.78", "Kia", "Seltos", 2022, None, 21300),
            (customer_id("093 771 4455"), "43A-567.89", "Honda", "CR-V", 2019, "", 61200),
            (customer_id("097 220 6631"), "29A-112.23", "Hyundai", "Tucson", 2021, None, 38600),
            (customer_id("097 220 6631"), "29A-778.90", "Ford", "Ranger", 2018, None, 88400),
            (customer_id("090 664 8890"), "50H-334.55", "Mitsubishi", "Xpander", 2023, None, 15200),
            (customer_id("098 611 2233"), "20A-246.81", "Toyota", "Vios", 2020, "RL4BT9F35LZ012481", 46820),
            (customer_id("097 522 3344"), "20C-189.56", "Ford", "Ranger", 2021, "MNCLMFF80MW123456", 45400),
            (customer_id("096 433 4455"), "20A-735.92", "Hyundai", "Accent", 2022, "KMHCT41DANU345678", 28750),
        ]
        for owner, plate, make, model, year, vin, mileage in vehicles:
            if owner and not db.execute("SELECT id FROM vehicles WHERE plate=?", (plate,)).fetchone():
                db.execute(
                    """
                    INSERT INTO vehicles(customer_id, plate, plate_normalized, vin, make, model, year, mileage)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (owner, plate, normalize_plate(plate), vin or None, make, model, year, mileage),
                )
        demo_vehicle_details = {
            "20A-246.81": "Bạc",
            "20C-189.56": "Xám ánh kim",
            "20A-735.92": "Đỏ đô",
        }
        for plate, color in demo_vehicle_details.items():
            db.execute("UPDATE vehicles SET color=? WHERE plate=? AND (color IS NULL OR color='')", (color, plate))
        db.execute(
            "UPDATE vehicles SET vin=COALESCE(NULLIF(vin,''), 'JMZKE1972L0123456'), "
            "color=COALESCE(NULLIF(color,''), 'Trắng ngọc trai'), "
            "mileage=CASE WHEN mileage IS NULL OR mileage < 43820 THEN 43820 ELSE mileage END "
            "WHERE plate='51H-123.45'"
        )

        if db.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 0:
            db.executemany(
                "INSERT INTO services(name, category, description, price, duration_min, active) "
                "VALUES(?, ?, ?, ?, ?, 1)",
                SERVICES,
            )
        # Bổ sung hạng mục tham khảo còn thiếu, không đè giá/thời lượng do garage đã sửa.
        db.executemany(
            "INSERT OR IGNORE INTO services(name, category, description, price, duration_min, active) "
            "VALUES(?, ?, ?, ?, ?, 1)",
            EXTRA_SERVICES,
        )
        from .catalog_expansion import seed_expanded_catalog

        if db.execute("SELECT COUNT(*) FROM parts").fetchone()[0] == 0:
            db.executemany(
                "INSERT INTO parts(code, name, category, compatible, unit, cost_price, sell_price, "
                "stock, min_stock, supplier, active) VALUES(?, ?, ?, ?, 'cái', ?, ?, ?, ?, ?, 1)",
                PARTS,
            )
        # Chỉ thêm mã chưa có: không đặt lại giá hay tồn kho do nhân viên đã chỉnh.
        db.executemany(
            """INSERT OR IGNORE INTO parts(code,name,category,compatible,unit,cost_price,sell_price,
                   stock,min_stock,supplier,active) VALUES(?,?,?,?,?,?,?,?,?,'Danh mục mẫu',1)""",
            EXTRA_PARTS,
        )
        db.executemany(
            """INSERT OR IGNORE INTO parts(code,name,category,compatible,unit,cost_price,sell_price,
                   stock,min_stock,supplier,compatibility_accuracy,usage_requirements,price_note,
                   supplier_note,technical_description,technical_specs,usage_instructions,active)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
            LIGHTING_PARTS,
        )
        # Giá bán bóng đèn do garage cung cấp trong đợt cập nhật danh mục. Chỉ
        # duyệt lần đầu khi giá hiện tại vẫn đúng snapshot; giá bị sửa sau đó
        # sẽ bị trigger thu hồi duyệt và không được tự duyệt lại khi khởi động.
        admin_id = db.execute("SELECT id FROM users WHERE role='Admin' ORDER BY id LIMIT 1").fetchone()[0]
        for lighting_part in LIGHTING_PARTS:
            code, sell_price = lighting_part[0], lighting_part[6]
            db.execute(
                """INSERT OR IGNORE INTO part_price_approvals(
                       part_id,approved_sell_price,approved_by,source)
                   SELECT id,sell_price,?,? FROM parts
                   WHERE code=? AND sell_price=?""",
                (admin_id, "Giá do garage cung cấp khi cập nhật danh mục bóng đèn", code, sell_price),
            )
        seed_expanded_catalog(db)

        def vehicle(plate: str):
            return db.execute("SELECT id, customer_id FROM vehicles WHERE plate=?", (plate,)).fetchone()

        def technician_id(full_name: str) -> int | None:
            row = db.execute("SELECT id FROM users WHERE full_name=?", (full_name,)).fetchone()
            return row["id"] if row else None

        if db.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 0:
            today = datetime.now(VN_TZ).strftime("%Y-%m-%d")
            tomorrow = (datetime.now(VN_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")
            resources = {
                row["code"]: row["id"]
                for row in db.execute("SELECT id, code FROM resources").fetchall()
            }
            appointments = [
                ("Nguyễn Minh Anh", "51H-123.45", "Bảo dưỡng định kỳ", f"{today}T08:30", "Đã xác nhận", "Bảo dưỡng định kỳ 40.000 km", "Nguyễn Văn Nam", "KHOANG-1", 90),
                ("Trần Quốc Huy", "30G-888.68", "Kiểm tra hệ thống phanh", f"{today}T10:00", "Đang chờ", "Phanh trước kêu khi đạp", "Trần Đức Long", "KHOANG-2", 60),
                ("Lê Thu Hà", "51K-456.78", "Thay dầu động cơ", f"{today}T13:30", "Đã xác nhận", "Đến kỳ thay dầu", "Phạm Tuấn Kiệt", "CAU-NANG-1", 45),
                ("Đặng Quốc Bảo", "43A-567.89", "Vệ sinh điều hòa", f"{tomorrow}T09:00", "Đang chờ", "Điều hòa lạnh chậm", "", "", 60),
                ("Hoàng Văn Hà", "20A-246.81", "Bảo dưỡng định kỳ", f"{tomorrow}T08:00", "Đã xác nhận", "Kiểm tra mốc 45.000 km", "Trần Tuấn", "KHOANG-1", 90),
                ("Hoàng Công Sự", "20C-189.56", "Kiểm tra hệ thống phanh", f"{tomorrow}T10:30", "Đang chờ", "Phanh có tiếng kêu nhẹ", "", "KHOANG-2", 60),
                ("Hoàng Minh Tuất", "20A-735.92", "Thay dầu động cơ", f"{tomorrow}T14:00", "Đã xác nhận", "Đến kỳ thay dầu", "Trần Tuấn", "CAU-NANG-1", 45),
            ]
            for name, plate, service, moment, status, reason, tech, resource_code, duration in appointments:
                linked = vehicle(plate)
                db.execute(
                    """
                    INSERT INTO appointments(customer_id, vehicle_id, customer_name, plate, service,
                        reason, appointment_at, duration_min, status, technician, technician_id,
                        resource_id, confirmed_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        linked["customer_id"] if linked else None,
                        linked["id"] if linked else None,
                        name,
                        plate,
                        service,
                        reason,
                        to_utc_iso(moment),
                        duration,
                        status,
                        tech,
                        technician_id(tech) if tech else None,
                        resources.get(resource_code),
                        to_utc_iso(moment) if status == "Đã xác nhận" else None,
                    ),
                )

        seed_orders = [
            ("PSC-1028", "51H-123.45", "Nguyễn Văn Nam", "Đang sửa", "IN_PROGRESS", "Thay dầu và kiểm tra lọc gió", "Cao", 42500, "2026-10-17 09:15"),
            ("PSC-1027", "30G-888.68", "Trần Đức Long", "Chờ phụ tùng", "WAITING_FOR_PARTS", "Má phanh trước đã mòn", "Bình thường", 58900, "2026-10-17 10:40"),
            ("PSC-1026", "51K-456.78", "Phạm Tuấn Kiệt", "Đang kiểm tra", "INSPECTING", "Xe rung nhẹ khi chạy chậm", "Thấp", 21300, "2026-10-16 15:05"),
        ]
        for code, plate, technician, status, status_code, note, priority, km_in, created in seed_orders:
            if db.execute("SELECT id FROM repair_orders WHERE code=?", (code,)).fetchone():
                continue
            linked = vehicle(plate)
            created_utc = to_utc_iso(created)
            total = db.execute(
                "SELECT COALESCE(SUM(CAST(ROUND(quantity * unit_price) AS INTEGER)), 0) "
                "FROM repair_order_items i JOIN repair_orders r ON r.id=i.repair_order_id WHERE r.code=?",
                (code,),
            ).fetchone()[0]
            cursor = db.execute(
                """
                INSERT INTO repair_orders(code, customer_id, vehicle_id, plate, customer_name,
                    technician_id, technician, status, status_code, priority, km_in, note,
                    initial_condition, customer_request, inspection_notes, total, received_at, opened_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    code,
                    linked["customer_id"] if linked else None,
                    linked["id"] if linked else None,
                    plate,
                    db.execute("SELECT name FROM customers WHERE id=?", (linked["customer_id"],)).fetchone()["name"] if linked else "",
                    technician_id(technician),
                    technician,
                    status,
                    status_code,
                    priority,
                    km_in,
                    note,
                    note,
                    note,
                    note,
                    total,
                    created_utc,
                    created_utc,
                ),
            )
            db.execute(
                "INSERT INTO repair_order_status_history"
                "(repair_order_id, from_status, to_status, note, changed_by_name, created_at) "
                "VALUES(?, '', ?, 'Khởi tạo phiếu', 'Hệ thống', ?)",
                (cursor.lastrowid, status_code, created_utc),
            )

        seed_items = {
            "PSC-1028": [("Dịch vụ", "Thay dầu động cơ", 1, 850000), ("Phụ tùng", "Lọc dầu Mazda LF10-14-302", 1, 320000), ("Dịch vụ", "Vệ sinh kim phun", 1, 480000), ("Dịch vụ", "Kiểm tra lọc gió", 1, 200000)],
            "PSC-1027": [("Dịch vụ", "Công thay má phanh trước", 1, 450000), ("Phụ tùng", "Má phanh trước (cặp)", 1, 2150000), ("Dịch vụ", "Vệ sinh và căn chỉnh phanh", 1, 640000)],
            "PSC-1026": [("Dịch vụ", "Kiểm tra tổng quát", 1, 350000), ("Dịch vụ", "Vệ sinh họng gió", 1, 450000), ("Dịch vụ", "Cân chỉnh bánh xe", 1, 150000)],
        }
        for code, items in seed_items.items():
            order = db.execute("SELECT id FROM repair_orders WHERE code=?", (code,)).fetchone()
            if not order:
                continue
            if db.execute("SELECT COUNT(*) FROM repair_order_items WHERE repair_order_id=?", (order["id"],)).fetchone()[0] == 0:
                db.executemany(
                    "INSERT INTO repair_order_items(repair_order_id, service_id, kind, name, quantity, "
                    "unit_price, line_total) VALUES(?, (SELECT id FROM services WHERE name=? LIMIT 1), ?, ?, ?, ?, ?)",
                    [
                        (order["id"], name if kind == "Dịch vụ" else None, kind, name, quantity, price, quantity * price)
                        for kind, name, quantity, price in items
                    ],
                )
            total = db.execute(
                "SELECT COALESCE(SUM(line_total), 0) FROM repair_order_items WHERE repair_order_id=?",
                (order["id"],),
            ).fetchone()[0]
            db.execute("UPDATE repair_orders SET total=? WHERE id=?", (total, order["id"]))

        if db.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 0:
            for index, (code, status) in enumerate(
                [("PSC-1028", "Đã thanh toán"), ("PSC-1027", "Chưa thanh toán"), ("PSC-1026", "Thanh toán một phần")],
                start=1,
            ):
                order = db.execute("SELECT id, total FROM repair_orders WHERE code=?", (code,)).fetchone()
                if not order:
                    continue
                subtotal, tax, total = with_tax(order["total"])
                paid = total if status == "Đã thanh toán" else (total // 2 if status == "Thanh toán một phần" else 0)
                db.execute(
                    """
                    INSERT INTO invoices(code, repair_order_id, subtotal, tax, total, paid_amount, status)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (f"HD-{index:04d}", order["id"], subtotal, tax, total, paid, status),
                )
                invoice = db.execute("SELECT id FROM invoices WHERE code=?", (f"HD-{index:04d}",)).fetchone()
                if paid > 0:
                    method = "Chuyển khoản" if status == "Đã thanh toán" else "Tiền mặt"
                    db.execute(
                        "INSERT INTO payments(invoice_id, method, amount, reference_code, note) "
                        "VALUES(?, ?, ?, ?, ?)",
                        (invoice["id"], method, paid, f"TT{index:05d}", "Ghi nhận thanh toán mẫu"),
                    )

        history = [
            ("43A-567.89", "2026-09-02", 61200, "Thay dầu hộp số, bảo dưỡng định kỳ", "Hộp số hoạt động ổn định", 2450000),
            ("43A-567.89", "2026-03-18", 54800, "Thay má phanh sau, cân chỉnh thước lái", "Đã căn chỉnh, không còn lệch lái", 3120000),
            ("29A-112.23", "2026-08-25", 38600, "Bảo dưỡng 35.000 km, vệ sinh điều hòa", "Lọc gió điều hòa đã thay mới", 1980000),
            ("29A-778.90", "2026-05-14", 88400, "Thay lốp trước, kiểm tra gầm", "Đề nghị theo dõi giảm xóc", 4260000),
            ("50H-334.55", "2026-07-09", 15200, "Thay dầu động cơ, lọc dầu", "Xe mới, các hạng mục bình thường", 1120000),
            ("51H-123.45", "2026-06-12", 42500, "Thay dầu động cơ, lọc dầu", "Các hạng mục vận hành bình thường", 1450000),
            ("51H-123.45", "2026-01-08", 35100, "Bảo dưỡng 35.000 km, vệ sinh phanh", "Theo dõi má phanh ở lần bảo dưỡng tiếp theo", 2180000),
            ("51H-123.45", "2025-08-20", 28700, "Thay lọc gió điều hòa", "Điều hòa hoạt động tốt", 680000),
        ]
        for plate, repaired_at, mileage, services, note, total in history:
            if not db.execute(
                "SELECT id FROM repair_history WHERE plate=? AND repaired_at=?", (plate, repaired_at)
            ).fetchone():
                linked = vehicle(plate)
                db.execute(
                    "INSERT INTO repair_history(vehicle_id, plate, repaired_at, mileage, services, note, total) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?)",
                    (linked["id"] if linked else None, plate, repaired_at, mileage, services, note, total),
                )

        if db.execute("SELECT COUNT(*) FROM quotes").fetchone()[0] == 0:
            admin = db.execute("SELECT id FROM users WHERE email='admin@garage.vn'").fetchone()
            admin_id = admin["id"] if admin else None
            # Phiếu đang thi công/chờ phụ tùng cần báo giá đã duyệt để có thể hoàn thành.
            seed_quotes = [
                ("BG-1028-01", "PSC-1028", "Báo giá thay dầu và kiểm tra lọc gió", "2026-10-17 10:05"),
                ("BG-1027-01", "PSC-1027", "Báo giá thay má phanh trước", "2026-10-17 11:00"),
            ]
            for quote_code, order_code, note, approved_at in seed_quotes:
                order = db.execute(
                    "SELECT id, total FROM repair_orders WHERE code=?", (order_code,)
                ).fetchone()
                if not order:
                    continue
                subtotal, tax, total = with_tax(order["total"])
                cursor = db.execute(
                    """
                    INSERT INTO quotes(code, repair_order_id, version, status, subtotal, tax, total,
                        note, approved_by, approved_at)
                    VALUES(?, ?, 1, 'Đã duyệt', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        quote_code,
                        order["id"],
                        subtotal,
                        tax,
                        total,
                        note,
                        admin_id,
                        to_utc_iso(approved_at),
                    ),
                )
                db.executemany(
                    "INSERT INTO quote_items(quote_id, kind, name, quantity, unit_price, line_total) "
                    "VALUES(?, ?, ?, ?, ?, ?)",
                    [
                        (cursor.lastrowid, kind, name, quantity, price, quantity * price)
                        for kind, name, quantity, price in seed_items[order_code]
                    ],
                )

        # Snapshot chi tiết cho hóa đơn seed/legacy sau khi báo giá đã tồn tại.
        db.execute(
            """UPDATE invoices SET quote_id=(SELECT q.id FROM quotes q
               WHERE q.repair_order_id=invoices.repair_order_id AND q.status='Đã duyệt'
               ORDER BY q.version DESC,q.id DESC LIMIT 1)
               WHERE quote_id IS NULL AND EXISTS(SELECT 1 FROM quotes q
               WHERE q.repair_order_id=invoices.repair_order_id AND q.status='Đã duyệt')"""
        )
        db.execute(
            """INSERT INTO invoice_items(invoice_id,quote_item_id,kind,name,quantity,unit_price,line_total)
               SELECT i.id,qi.id,qi.kind,qi.name,qi.quantity,qi.unit_price,qi.line_total
               FROM invoices i JOIN quote_items qi ON qi.quote_id=i.quote_id
               WHERE NOT EXISTS(SELECT 1 FROM invoice_items ii WHERE ii.invoice_id=i.id)"""
        )
        db.execute(
            """INSERT INTO invoice_items(invoice_id,kind,name,quantity,unit_price,line_total)
               SELECT i.id,roi.kind,roi.name,roi.quantity,roi.unit_price,roi.line_total
               FROM invoices i JOIN repair_order_items roi ON roi.repair_order_id=i.repair_order_id
               WHERE NOT EXISTS(SELECT 1 FROM invoice_items ii WHERE ii.invoice_id=i.id)"""
        )

        # Lịch sử sửa chữa/hóa đơn đầy đủ cho các tài khoản khách hàng demo.
        visit_templates = [
            ("2025-02-10", "Thay dầu động cơ", 450000, "Dầu động cơ 5W-30 4L", 1, 680000, 18200),
            ("2025-05-18", "Kiểm tra hệ thống phanh", 350000, "Má phanh trước", 1, 2150000, 24700),
            ("2025-09-22", "Vệ sinh điều hòa", 650000, "Lọc gió điều hòa", 1, 290000, 31200),
            ("2026-02-14", "Bảo dưỡng định kỳ", 850000, "Lọc dầu động cơ", 1, 320000, 37600),
            ("2026-06-08", "Cân chỉnh bánh xe", 300000, "", 0, 0, 42800),
            ("2026-09-28", "Kiểm tra tổng quát", 250000, "Kiểm tra hệ thống đánh lửa", 1, 740000, 45200),
        ]
        demo_billing_profiles = [
            ("090 123 4567", 4),
            ("098 611 2233", 6),
            ("097 522 3344", 6),
            ("096 433 4455", 6),
        ]
        technician = db.execute("SELECT id FROM users WHERE email='technician@garage.vn'").fetchone()
        for phone, visit_count in demo_billing_profiles:
            customer = db.execute("SELECT id,name FROM customers WHERE phone=?", (phone,)).fetchone()
            if not customer:
                continue
            linked_vehicle = db.execute(
                "SELECT id,plate,make,model FROM vehicles WHERE customer_id=? ORDER BY id LIMIT 1", (customer["id"],)
            ).fetchone()
            if not linked_vehicle:
                continue
            for index, (visit_date, service_name, service_price, part_name, part_qty, part_price, mileage) in enumerate(visit_templates[:visit_count], 1):
                order_code = f"PSC-KH{customer['id']:02d}-{index:02d}"
                if db.execute("SELECT id FROM repair_orders WHERE code=?", (order_code,)).fetchone():
                    continue
                # Dữ liệu demo dùng chung nhiều khách: không gắn phụ tùng riêng hãng/dòng
                # cho xe khác, hoặc tạo lịch sử km cao hơn bản ghi đến sau.
                named_part = part_name.casefold()
                make = (linked_vehicle["make"] or "").casefold()
                model = (linked_vehicle["model"] or "").casefold()
                if (("mazda" in named_part and (make != "mazda" or model not in ("cx-5", "mazda 3", "3")))
                        or ("kia seltos" in named_part and (make != "kia" or model != "seltos"))
                        or ("toyota" in named_part and make != "toyota")):
                    part_name, part_qty, part_price = "", 0, 0
                later_mileage = db.execute(
                    "SELECT MIN(mileage) FROM repair_history WHERE vehicle_id=? AND repaired_at>? AND mileage IS NOT NULL",
                    (linked_vehicle["id"], visit_date)).fetchone()[0]
                if later_mileage is not None and mileage >= later_mileage:
                    mileage = max(0, later_mileage - 100)
                subtotal = service_price + part_qty * part_price
                _, tax, invoice_total = with_tax(subtotal)
                payment_mode = index % 3
                paid_amount = invoice_total if payment_mode == 1 else (invoice_total // 2 if payment_mode == 2 else 0)
                invoice_status = "Đã thanh toán" if paid_amount == invoice_total else ("Thanh toán một phần" if paid_amount else "Chưa thanh toán")
                order_status = "Đã bàn giao" if invoice_status == "Đã thanh toán" else "Hoàn thành"
                order_status_code = "DELIVERED" if invoice_status == "Đã thanh toán" else "COMPLETED"
                moment = to_utc_iso(f"{visit_date} 09:00")
                cursor = db.execute(
                    """INSERT INTO repair_orders(code,customer_id,vehicle_id,plate,customer_name,
                       technician_id,technician,status,status_code,priority,km_in,note,initial_condition,
                       customer_request,inspection_notes,total,received_at,opened_at,completed_at,delivered_at,closed_at)
                       VALUES(?,?,?,?,?,?,?,?,?,'Bình thường',?,?,?,?,?,?,?,?,?,?,?)""",
                    (order_code, customer["id"], linked_vehicle["id"], linked_vehicle["plate"], customer["name"],
                     technician["id"] if technician else None, "Trần Tuấn", order_status, order_status_code,
                     mileage, f"Lịch sử dịch vụ {service_name}", "Xe vận hành bình thường khi tiếp nhận",
                     service_name, f"Đã kiểm tra và thực hiện {service_name}", subtotal, moment, moment,
                     moment, moment if order_status_code == "DELIVERED" else None, moment),
                )
                order_id = cursor.lastrowid
                service_row = db.execute("SELECT id FROM services WHERE name=?", (service_name,)).fetchone()
                db.execute(
                    """INSERT INTO repair_order_items(repair_order_id,service_id,kind,name,quantity,unit_price,line_total)
                       VALUES(?,?,'Dịch vụ',?,1,?,?)""",
                    (order_id, service_row["id"] if service_row else None, service_name, service_price, service_price),
                )
                if part_name:
                    db.execute(
                        """INSERT INTO repair_order_items(repair_order_id,kind,name,quantity,unit_price,line_total)
                           VALUES(?,'Phụ tùng',?,?,?,?)""",
                        (order_id, part_name, part_qty, part_price, part_qty * part_price),
                    )
                quote_code = f"BG-KH{customer['id']:02d}-{index:02d}"
                quote = db.execute(
                    """INSERT INTO quotes(code,repair_order_id,version,status,subtotal,discount,tax,total,tax_rate,
                       note,approved_by,approved_at,created_by) VALUES(?,?,1,'Đã duyệt',?,0,?,?,0.08,?,?,?,?)""",
                    (quote_code, order_id, subtotal, tax, invoice_total, "Báo giá lịch sử đã duyệt",
                     1, moment, 1),
                )
                quote_id = quote.lastrowid
                db.execute(
                    "INSERT INTO quote_items(quote_id,kind,service_id,name,quantity,unit_price,line_total) VALUES(?,'Dịch vụ',?,?,1,?,?)",
                    (quote_id, service_row["id"] if service_row else None, service_name, service_price, service_price),
                )
                if part_name:
                    part_row = db.execute("SELECT id FROM parts WHERE name=? LIMIT 1", (part_name,)).fetchone()
                    db.execute(
                        "INSERT INTO quote_items(quote_id,kind,part_id,name,quantity,unit_price,line_total) VALUES(?,'Phụ tùng',?,?,?,?,?)",
                        (quote_id, part_row["id"] if part_row else None, part_name, part_qty, part_price, part_qty * part_price),
                    )
                invoice_code = f"HD-KH{customer['id']:02d}-{index:02d}"
                invoice = db.execute(
                    """INSERT INTO invoices(code,repair_order_id,quote_id,subtotal,discount,tax,total,paid_amount,status,
                       issued_at,note,created_by) VALUES(?,?,?, ?,0,?,?,?,?,?,'Hóa đơn lịch sử',1)""",
                    (invoice_code, order_id, quote_id, subtotal, tax, invoice_total, paid_amount, invoice_status, moment),
                )
                invoice_id = invoice.lastrowid
                db.execute(
                    """INSERT INTO invoice_items(invoice_id,quote_item_id,kind,name,quantity,unit_price,line_total)
                       SELECT ?,id,kind,name,quantity,unit_price,line_total FROM quote_items WHERE quote_id=?""",
                    (invoice_id, quote_id),
                )
                if paid_amount:
                    db.execute(
                        "INSERT INTO payments(invoice_id,method,amount,reference_code,paid_at,note) VALUES(?,'Chuyển khoản',?,?,?,'Thanh toán lịch sử')",
                        (invoice_id, paid_amount, f"LS{customer['id']:02d}{index:02d}", moment),
                    )
                services_summary = service_name + (f", {part_name}" if part_name else "")
                db.execute(
                    """INSERT OR IGNORE INTO repair_history(vehicle_id,repair_order_id,plate,repaired_at,mileage,services,note,total)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (linked_vehicle["id"], order_id, linked_vehicle["plate"], visit_date, mileage,
                     services_summary, "Đã hoàn tất các hạng mục theo báo giá", invoice_total),
                )
                ensure_status_history(db, order_id)


def normalize_plate(value: str) -> str:
    """Chuẩn hóa biển số để tra cứu (không dùng làm định danh duy nhất)."""
    if not value:
        return ""
    cleaned = value.upper().replace("-", "").replace(".", "").replace(" ", "").replace("+", "")
    return cleaned
