"""Tra cứu tồn kho chỉ đọc: nhận diện ý định, kiểm quyền, truy vấn cố định.

Schema hiện tại là một kho tổng, không có giữ chỗ, mức mục tiêu hoặc nhu cầu
phụ tùng chưa xuất kho. repair_order_parts đã trừ stock khi ghi nhận sử dụng.
"""

import re
from datetime import datetime

from .ai_service import AIResult, ai_service
from .permissions import has_permission
from .timeutil import VN_TZ

DENIED = "Bạn không có quyền truy cập thông tin tồn kho này. Vui lòng liên hệ quản trị viên để được cấp quyền phù hợp."


def is_inventory_question(question: str) -> bool:
    text = ai_service._normalize_vi(question)
    subject = any(word in text for word in ("kho", "phu tung", "linh kien", "mat hang", "vat tu", "loc dau", "ma sp"))
    intent = any(word in text for word in (
        "ton kho", "ton thuc te", "ton kha dung", "so luong ton", "so luong", "con bao nhieu",
        "sap het", "het hang", "duoi muc", "muc toi thieu", "ton thap",
        "thap nhat", "can nhap", "nhap them", "bo sung", "thieu hang", "khong du hang",
        "gia tri kho", "gia nhap", "gia von", "giao dich kho", "lich su nhap", "lich su xuat",
        "tinh trang ton", "tinh trang kho", "muc tieu", "giu cho", "thong ke",
    ))
    return subject and intent


def answer_inventory_question(db, question: str, user: dict, vehicle: dict | None = None):
    if not is_inventory_question(question):
        return None
    text = ai_service._normalize_vi(question)
    role = user.get("role", "")

    def reply(content, status="fallback", sources=None):
        return AIResult(content, status, "local", ai_service.model, status == "no_data"), sources or []

    # Check permissions BEFORE any SELECT on parts, fitments or transactions.
    value = any(term in text for term in ("gia nhap", "gia von", "gia tri kho", "gia tri ton"))
    transactions = any(term in text for term in ("giao dich kho", "lich su nhap", "lich su xuat"))
    restock = any(term in text for term in ("can nhap", "nhap them", "bo sung", "muc tieu"))
    statistics = any(term in text for term in ("bao nhieu mat hang", "thong ke", "tong hop", "tinh trang kho", "tinh trang ton", "theo tung kho"))
    low = any(term in text for term in ("sap het", "ton thap", "duoi muc", "muc toi thieu", "thieu hut", "can nhap", "nhap them", "bo sung"))
    if (not has_permission(role, "inventory.view") and not (statistics and has_permission(role, "inventory.view_statistics"))
            or value and not has_permission(role, "inventory.view_stock_value")
            or transactions and not has_permission(role, "inventory.view_transactions")
            or restock and not has_permission(role, "inventory.recommend_restock")
            or low and not statistics and not has_permission(role, "inventory.view_low_stock")
            or not statistics and not has_permission(role, "inventory.view_all")):
        return reply(DENIED, "denied")
    if transactions:
        return reply("Lịch sử nhập/xuất cần tra theo API giao dịch kho; chat chưa hỗ trợ truy vấn giao dịch.", "no_data")
    if value:
        return reply("Giá trị tồn kho cần tra trong báo cáo kho; chat chưa hỗ trợ tính giá trị.", "no_data")
    if any(term in text for term in ("kho a", "kho b", "chi nhanh", "theo tung kho")):
        return reply("Hệ thống hiện chỉ có một kho tổng, chưa lưu kho/chi nhánh riêng nên không thể lọc hoặc tổng hợp theo kho.", "no_data")
    if any(term in text for term in ("giu cho", "ton kha dung", "phieu sua chua", "dang sua", "chua hoan thanh", "nhu cau")):
        return reply("Chưa có dữ liệu giữ chỗ hoặc nhu cầu phụ tùng đã xác nhận cho phiếu đang mở. "
                     "Phụ tùng đã sử dụng đã được trừ khỏi tồn thực tế; không thể tính tồn khả dụng hay thiếu theo phiếu.", "no_data")
    if "muc tieu" in text:
        return reply("Chưa cấu hình mức tồn mục tiêu, nên không thể tính số lượng nhập để đạt mục tiêu. "
                     "Cần bổ sung trường target_stock (khác min_stock) và quy trình cấu hình trước khi triển khai đề xuất này.", "no_data")

    # Không lấy giá vốn, nhà cung cấp hay mô tả tương thích không được xác minh.
    rows = [dict(row) for row in db.execute(
        "SELECT id,code,name,category,unit,stock,min_stock FROM parts WHERE active=1 ORDER BY id"
    )]
    categories = sorted({row["category"] for row in rows}, key=len, reverse=True)
    selected_categories = [cat for cat in categories if re.search(
        r"(?<!\w)" + re.escape(ai_service._normalize_vi(cat)) + r"(?!\w)", text)]
    if selected_categories:
        rows = [row for row in rows if row["category"] in selected_categories]
    # Only explicit verified fitment rules can establish compatibility.
    makes = [row["make"] for row in db.execute("SELECT DISTINCT make FROM part_fitments")]
    selected_make = next((make for make in makes if ai_service._normalize_vi(make) in text), None)
    models = [row["model"] for row in db.execute("SELECT DISTINCT model FROM part_fitments")]
    selected_model = next((model for model in models if ai_service._normalize_vi(model) in text), None)
    if vehicle and not any(term in text for term in ("xe nay", "xe toi", "xe dang", "xe duoc chon")):
        vehicle = None
    if vehicle or selected_make or selected_model:
        rules = [dict(row) for row in db.execute(
            "SELECT part_id,make,model,year_from,year_to,variant,engine_code,fuel_type FROM part_fitments"
        )]
        def fits(rule):
            if selected_make and rule["make"].casefold() != selected_make.casefold():
                return False
            if selected_model and rule["model"].casefold() != selected_model.casefold():
                return False
            if not vehicle:
                return True
            if rule["make"].casefold() != str(vehicle["make"]).casefold() or rule["model"].casefold() != str(vehicle["model"]).casefold():
                return False
            year = vehicle["year"]
            if (rule["year_from"] or rule["year_to"]) and not year:
                return False
            if year and (rule["year_from"] and year < rule["year_from"] or rule["year_to"] and year > rule["year_to"]):
                return False
            return all(not rule[field] or vehicle[field] and rule[field].casefold() == str(vehicle[field]).casefold()
                       for field in ("variant", "engine_code", "fuel_type"))
        matched = {rule["part_id"] for rule in rules if fits(rule)}
        rows = [row for row in rows if row["id"] in matched]
    # Search for exact product code or name, without interpreting the question as SQL.
    specific = [row for row in rows if re.search(r"(?<!\w)" + re.escape(ai_service._normalize_vi(row["code"])) + r"(?!\w)", text)]
    if specific:
        rows = specific
    out = [row for row in rows if row["stock"] == 0]
    low_rows = [row for row in rows if row["stock"] is not None and row["min_stock"] is not None and 0 < row["stock"] <= row["min_stock"]]
    normal = [row for row in rows if row["stock"] is not None and row["min_stock"] is not None and row["stock"] > row["min_stock"]]
    unknown = [row for row in rows if row["stock"] is None or row["stock"] != 0 and row["min_stock"] is None]
    stamp = datetime.now(VN_TZ).strftime("%d/%m/%Y %H:%M (giờ Việt Nam)")
    summary = (f"Tại {stamp}, kho tổng (đánh giá theo tồn thực tế, không có dữ liệu giữ chỗ): "
               f"{len(out)} mặt hàng hết, {len(low_rows)} sắp hết, {len(normal)} bình thường, "
               f"{len(unknown)} chưa đủ dữ liệu đánh giá.")
    if restock:
        summary += f" {len([row for row in out + low_rows if row['min_stock'] is not None and row['stock'] < row['min_stock']])} mặt hàng dưới mức tối thiểu cần xem xét nhập thêm."
    if statistics and not has_permission(role, "inventory.view_all"):
        return reply(summary)
    if "het hang" in text and "sap het" not in text:
        chosen = out
    elif low or "sap het" in text:
        chosen = out + low_rows if "sap het" in text or restock else low_rows
    else:
        chosen = rows
    chosen.sort(key=(lambda row: (row["stock"] if row["stock"] is not None else 10**9, row["code"]))
                if "thap nhat" in text else
                (lambda row: (-(row["min_stock"] - row["stock"]) if row["min_stock"] is not None and row["stock"] is not None else 0, row["code"])))
    limit_match = re.search(r"\b(\d{1,2})\s+(?:phu tung|linh kien|mat hang)", text)
    limit = min(int(limit_match.group(1)), 50) if limit_match else 20
    lines = []
    for row in chosen[:limit]:
        status = "Hết hàng" if row in out else "Sắp hết" if row in low_rows else "Bình thường" if row in normal else "Chưa đủ dữ liệu"
        minimum = str(row["min_stock"]) if row["min_stock"] is not None else "chưa cấu hình"
        lines.append(f"- {row['code']} – {row['name']} ({row['category']}): tồn thực tế {row['stock']} {row['unit']}; "
                     f"tối thiểu {minimum}; {status}." +
                     (f" Thiếu {max(row['min_stock'] - row['stock'], 0)} để đạt tối thiểu (tham khảo, không phải đơn nhập)."
                      if restock and row["min_stock"] is not None and row["stock"] is not None else ""))
    if not lines:
        return reply(summary + " Không có mặt hàng phù hợp với bộ lọc; không suy ra tương thích từ tên/mô tả.", "no_data")
    suffix = f"\nHiển thị {len(lines)}/{len(chosen)} mặt hàng." if len(chosen) > limit else ""
    if restock:
        suffix += "\nChỉ tính khoảng thiếu tới mức tối thiểu; chưa có mức tồn mục tiêu để đề xuất nhập tới mục tiêu."
    sources = [{"type": "part", "id": row["id"], "label": f"Kho phụ tùng: {row['code']} ({row['name']})"} for row in chosen[:limit]]
    return reply(summary + "\n" + "\n".join(lines) + suffix, sources=sources)
