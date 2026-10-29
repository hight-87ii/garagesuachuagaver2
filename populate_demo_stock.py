"""Gán tồn kho GIẢ LẬP cho toàn bộ danh mục phụ tùng hiện tại (chạy thủ công).

Không chạy khi khởi động ứng dụng: tồn kho thực tế phải được kiểm kê/nhập kho.
"""

import argparse
import secrets

from backend.database import connect, transaction


def populate_demo_stock(db, minimum=5, maximum=30, only_empty=False, code_prefix=None):
    if minimum < 1 or maximum < minimum:
        raise ValueError("Khoảng tồn kho phải là các số nguyên dương tăng dần")
    clauses, params = [], []
    if only_empty:
        clauses.append("stock=0")
    if code_prefix:
        clauses.append("code LIKE ?")
        params.append(f"{code_prefix}%")
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    ids = [row[0] for row in db.execute(f"SELECT id FROM parts{where} ORDER BY id", params)]
    with transaction(db):
        db.executemany(
            "UPDATE parts SET stock=? WHERE id=?",
            ((minimum + secrets.randbelow(maximum - minimum + 1), part_id) for part_id in ids),
        )
    return len(ids)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gán tồn kho mô phỏng từ 5 đến 30")
    parser.add_argument("--only-empty", action="store_true", help="Chỉ cập nhật mặt hàng đang hết hàng")
    parser.add_argument("--code-prefix", help="Chỉ cập nhật mã bắt đầu bằng tiền tố này")
    args = parser.parse_args()
    db = connect()
    try:
        count = populate_demo_stock(db, only_empty=args.only_empty, code_prefix=args.code_prefix)
        print(f"Updated demo stock for {count} parts (5-30 units each).")
    finally:
        db.close()
