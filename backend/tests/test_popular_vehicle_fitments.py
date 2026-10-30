"""Kiểm tra bảng tra cứu phụ tùng chi tiết (part_fitments) cho các dòng xe phổ biến."""

import pytest
from backend import database
from backend.ai_service import ai_service
from backend.popular_vehicle_fitments import (
    FITMENT_RULES,
    POPULAR_PARTS,
    seed_popular_vehicle_fitments,
)


@pytest.fixture
def db_conn():
    with database.connect() as db:
        yield db


def test_popular_vehicle_fitments_coverage(db_conn):
    """Kiểm tra độ phủ fitments cho các dòng xe phổ biến nhất tại Việt Nam."""
    makes = {row["make"] for row in db_conn.execute("SELECT DISTINCT make FROM part_fitments")}
    models = {row["model"] for row in db_conn.execute("SELECT DISTINCT model FROM part_fitments")}

    # Đảm bảo đủ các hãng xe phổ biến
    expected_makes = {"Toyota", "Honda", "Mazda", "Hyundai", "Kia", "Mitsubishi", "Ford"}
    assert expected_makes.issubset(makes), f"Thiếu hãng xe: {expected_makes - makes}"

    # Đảm bảo đủ các model xe thịnh hành
    expected_models = {
        "Vios", "Camry", "Corolla Cross", "Fortuner", "Innova",
        "City", "CR-V", "Civic",
        "CX-5", "Mazda 3",
        "Accent", "Tucson", "Santa Fe", "Grand i10",
        "Seltos", "Cerato", "K3", "Morning",
        "Xpander", "Outlander",
        "Ranger", "Everest",
    }
    assert expected_models.issubset(models), f"Thiếu dòng xe: {expected_models - models}"


def test_seed_popular_vehicle_fitments_is_idempotent(db_conn):
    """Kiểm tra tính idempotent của seed_popular_vehicle_fitments."""
    count_before = db_conn.execute("SELECT count(*) FROM part_fitments").fetchone()[0]
    parts_before = db_conn.execute("SELECT count(*) FROM parts").fetchone()[0]

    # Chạy lại seed không làm sinh bản ghi trùng
    added_parts, added_fitments = seed_popular_vehicle_fitments(db_conn)
    assert added_parts == 0
    assert added_fitments == 0

    count_after = db_conn.execute("SELECT count(*) FROM part_fitments").fetchone()[0]
    parts_after = db_conn.execute("SELECT count(*) FROM parts").fetchone()[0]
    assert count_after == count_before
    assert parts_after == parts_before


def test_popular_parts_have_approved_prices(db_conn):
    """Toàn bộ phụ tùng chuẩn mới bổ sung đều có giá bán được phê duyệt hợp lệ."""
    codes = [p[0] for p in POPULAR_PARTS]
    for code in codes:
        part = db_conn.execute("SELECT id, sell_price FROM parts WHERE code=?", (code,)).fetchone()
        assert part is not None, f"Phụ tùng {code} chưa được tạo trong parts"
        assert part["sell_price"] > 0, f"Phụ tùng {code} chưa có sell_price"

        approval = db_conn.execute(
            "SELECT approved_sell_price FROM part_price_approvals WHERE part_id=?",
            (part["id"],),
        ).fetchone()
        assert approval is not None, f"Phụ tùng {code} chưa có bản ghi phê duyệt giá"
        assert approval["approved_sell_price"] == part["sell_price"]


def test_level_3_fitment_matching_for_popular_vehicles(db_conn):
    """Kiểm tra quy tắc fitment đạt Level 3 (verified rule) khi đối chiếu xe thực tế."""
    rules_by_part: dict[int, list[dict]] = {}
    for row in db_conn.execute(
        "SELECT part_id, make, model, year_from, year_to, variant, engine_code, fuel_type, note "
        "FROM part_fitments"
    ):
        rules_by_part.setdefault(row["part_id"], []).append(dict(row))

    def get_part(code: str) -> dict:
        row = db_conn.execute("SELECT id, code, name, category, compatible FROM parts WHERE code=?", (code,)).fetchone()
        assert row is not None, f"Mã {code} không tồn tại"
        d = dict(row)
        d["fitments"] = rules_by_part.get(d["id"], [])
        return d

    # 1. Toyota Vios 2020:
    vios_2020 = {"make": "Toyota", "model": "Vios", "year": 2020}
    assert ai_service._part_fit_level(get_part("BT-GS-45L"), vios_2020) == 3
    assert ai_service._part_fit_level(get_part("OF-TOY-001"), vios_2020) == 3
    assert ai_service._part_fit_level(get_part("AF-VIO-2020"), vios_2020) == 3
    assert ai_service._part_fit_level(get_part("BP-VIO-2020"), vios_2020) == 3
    assert ai_service._part_fit_level(get_part("AC-TOY-001"), vios_2020) == 3
    assert ai_service._part_fit_level(get_part("WP-VIO-01"), vios_2020) == 3

    # 2. Honda City 2021:
    city_2021 = {"make": "Honda", "model": "City", "year": 2021}
    assert ai_service._part_fit_level(get_part("BT-GS-45L"), city_2021) == 3
    assert ai_service._part_fit_level(get_part("OF-HON-001"), city_2021) == 3
    assert ai_service._part_fit_level(get_part("AF-HON-CIT"), city_2021) == 3
    assert ai_service._part_fit_level(get_part("BP-HON-CIT"), city_2021) == 3
    assert ai_service._part_fit_level(get_part("WP-VIO-01"), city_2021) == 3

    # 3. Hyundai Accent 2022:
    accent_2022 = {"make": "Hyundai", "model": "Accent", "year": 2022}
    assert ai_service._part_fit_level(get_part("BT-ACC-2022"), accent_2022) == 3
    assert ai_service._part_fit_level(get_part("OF-HY-001"), accent_2022) == 3
    assert ai_service._part_fit_level(get_part("AF-HY-ACC"), accent_2022) == 3
    assert ai_service._part_fit_level(get_part("BP-HY-ACC"), accent_2022) == 3
    assert ai_service._part_fit_level(get_part("AC-HY-ACC"), accent_2022) == 3

    # 4. Mitsubishi Xpander 2023:
    xpander_2023 = {"make": "Mitsubishi", "model": "Xpander", "year": 2023}
    assert ai_service._part_fit_level(get_part("BT-GS-45L"), xpander_2023) == 3
    assert ai_service._part_fit_level(get_part("OF-MIT-001"), xpander_2023) == 3
    assert ai_service._part_fit_level(get_part("AF-XPA-2023"), xpander_2023) == 3
    assert ai_service._part_fit_level(get_part("BP-MIT-XP"), xpander_2023) == 3
    assert ai_service._part_fit_level(get_part("AC-MIT-XP"), xpander_2023) == 3

    # 5. Ford Ranger 2021:
    ranger_2021 = {"make": "Ford", "model": "Ranger", "year": 2021}
    assert ai_service._part_fit_level(get_part("OF-RAN-2021"), ranger_2021) == 3
    assert ai_service._part_fit_level(get_part("AF-FOR-RAN"), ranger_2021) == 3
    assert ai_service._part_fit_level(get_part("BP-FOR-RAN"), ranger_2021) == 3
    assert ai_service._part_fit_level(get_part("SH-RAN-2021"), ranger_2021) == 3

    # 6. Mazda CX-5 2021:
    cx5_2021 = {"make": "Mazda", "model": "CX-5", "year": 2021}
    assert ai_service._part_fit_level(get_part("LF10-14-302"), cx5_2021) == 3
    assert ai_service._part_fit_level(get_part("AF-MAZ-CX5"), cx5_2021) == 3
    assert ai_service._part_fit_level(get_part("AC-CX5-2021"), cx5_2021) == 3
    assert ai_service._part_fit_level(get_part("BP-MAZ-CX5"), cx5_2021) == 3
    assert ai_service._part_fit_level(get_part("BR-CX5-2021"), cx5_2021) == 3
    assert ai_service._part_fit_level(get_part("SP-MAZ-01"), cx5_2021) == 3

    # 7. Kia Seltos 2022:
    seltos_2022 = {"make": "Kia", "model": "Seltos", "year": 2022}
    assert ai_service._part_fit_level(get_part("OF-HY-001"), seltos_2022) == 3
    assert ai_service._part_fit_level(get_part("AC-HY-ACC"), seltos_2022) == 3
    assert ai_service._part_fit_level(get_part("BT-DIN-60L"), seltos_2022) == 3
    assert ai_service._part_fit_level(get_part("SP-KIA-09"), seltos_2022) == 3


def test_negative_cross_brand_fitment(db_conn):
    """Kiểm tra không gán nhầm phụ tùng khác hãng hoặc khác thông số kỹ thuật."""
    rules_by_part: dict[int, list[dict]] = {}
    for row in db_conn.execute(
        "SELECT part_id, make, model, year_from, year_to, variant, engine_code, fuel_type, note "
        "FROM part_fitments"
    ):
        rules_by_part.setdefault(row["part_id"], []).append(dict(row))

    def get_part(code: str) -> dict:
        row = db_conn.execute("SELECT id, code, name, category, compatible FROM parts WHERE code=?", (code,)).fetchone()
        d = dict(row)
        d["fitments"] = rules_by_part.get(d["id"], [])
        return d

    vios = {"make": "Toyota", "model": "Vios", "year": 2020}
    cx5 = {"make": "Mazda", "model": "CX-5", "year": 2021}

    # Má phanh Hyundai không lắp vừa Toyota Vios
    assert ai_service._part_fit_level(get_part("BP-HY-ACC"), vios) == 0
    # Lọc dầu Ford Ranger không lắp vừa Mazda CX-5
    assert ai_service._part_fit_level(get_part("OF-RAN-2021"), cx5) == 0
    # Má phanh Mitsubishi Xpander không lắp vừa Mazda CX-5
    assert ai_service._part_fit_level(get_part("BP-MIT-XP"), cx5) == 0
    # Không có ắc quy nào trong kho tự tiện gán cho Mazda CX-5
    assert ai_service._part_fit_level(get_part("BT-GS-45L"), cx5) == 0
    assert ai_service._part_fit_level(get_part("BT-ACC-2022"), cx5) == 0

