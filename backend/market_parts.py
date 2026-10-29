"""Sản phẩm có tên/mã được đối chiếu với trang nhà sản xuất.

Chỉ tạo bản ghi *chưa kích hoạt*: tên sản phẩm có thật không chứng minh garage
đang bán, có hàng, có giá được duyệt hoặc phù hợp với một xe cụ thể.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketPart:
    code: str  # mã nội bộ REF-, mã sản phẩm thật nằm trong tên
    name: str
    category: str
    source_url: str


MARKET_PARTS = (
    MarketPart("REF-BS-T005A-20555R16", "Lốp Bridgestone Turanza T005A 205/55R16", "Lốp",
               "https://www.bridgestone.com.vn/en/tire/turanza-t005a/205-55r16"),
    MarketPart("REF-MI-PRIMACY5", "Lốp Michelin Primacy 5 (chọn kích thước cụ thể)", "Lốp",
               "https://www.michelin.vn/auto/tyres/michelin-primacy-5"),
    MarketPart("REF-MANN-HU7162X", "Lọc dầu MANN-FILTER HU 716/2 x", "Lọc - dầu",
               "https://www.mann-filter.com/uk-en/catalogue/search-results/product.html/hu716/2x_mann-filter.html"),
    MarketPart("REF-OSRAM-7507", "Bóng xi nhan OSRAM ORIGINAL PY21W 12V 21W (7507)", "Điện - ắc quy",
               "https://www.osram.com/ecat/Lamps%20with%20metal%20bases-Signal%20lamps-Car%20lighting-Automotive/gb/en/GPS01_1057060/ZMP_60924"),
    MarketPart("REF-NGK-BKR6E11", "Bugi NGK BKR6E-11 (mã kho 2756)", "Động cơ",
               "https://www.ngkntk.com/nordic/part-finder/motorcycles-scooter/spark-plugs/honda/gl-1800-a-gold-wing-sc47-bkr6e-11-6-1800-2001-2005"),
)


def import_market_parts(db) -> int:
    """Chỉ thêm tên mới ở trạng thái chờ xác minh, không sửa mặt hàng hiện có."""
    inserted = 0
    for part in MARKET_PARTS:
        cursor = db.execute("""INSERT OR IGNORE INTO parts
            (code,name,category,compatible,unit,cost_price,sell_price,stock,min_stock,supplier,active)
            VALUES(?,?,?,'Chưa xác minh tương thích; đối chiếu VIN/thông số và tài liệu hãng',
                   'cái',0,0,0,0,'Chưa xác minh nguồn cung',0)""",
            (part.code, part.name, part.category))
        inserted += cursor.rowcount
    return inserted


if __name__ == "__main__":
    import argparse
    import sys
    from .database import connect, transaction

    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Xem trước danh sách linh kiện có tên thật")
    parser.add_argument("--apply", action="store_true", help="Thêm bản ghi chưa kích hoạt vào database")
    args = parser.parse_args()
    if not args.apply:
        for part in MARKET_PARTS:
            print(part.code, part.name, part.source_url)
    else:
        with connect() as db, transaction(db):
            print("Added inactive parts:", import_market_parts(db))
