"""Bổ sung gợi ý xe tương thích còn thiếu cho dữ liệu demo hiện có."""

from backend.catalog_expansion import catalog_parts
from backend.database import connect, transaction


OLD_GENERIC = "Chọn đúng thông số theo hướng dẫn nhà sản xuất xe; chưa xác nhận tương thích"
FALLBACK = (
    "Toyota Vios/Corolla, Mazda CX-5, Hyundai Accent/Tucson, Kia Seltos, "
    "Mitsubishi Xpander, Ford Ranger; chưa xác nhận lắp vừa, phải kiểm tra VIN/mã/thông số thực tế"
)


def update_compatibility(db):
    demo_hints = {row[0]: row[3] for row in catalog_parts()}
    changed = 0
    with transaction(db):
        for code, hint in demo_hints.items():
            changed += db.execute(
                "UPDATE parts SET compatible=? WHERE code=? AND (trim(compatible)='' OR compatible=?)",
                (hint, code, OLD_GENERIC),
            ).rowcount
        changed += db.execute(
            "UPDATE parts SET compatible=? WHERE trim(compatible)=''",
            (FALLBACK,),
        ).rowcount
    return changed


if __name__ == "__main__":
    db = connect()
    try:
        changed = update_compatibility(db)
        blank = db.execute("SELECT count(1) FROM parts WHERE trim(compatible)='' ").fetchone()[0]
        print(f"Updated compatibility for {changed} parts. Blank compatibility: {blank}.")
    finally:
        db.close()
