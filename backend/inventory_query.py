"""Tra cứu tồn kho chỉ đọc: nhận diện ý định, kiểm quyền, truy vấn cố định.

Schema hiện tại là một kho tổng, không có giữ chỗ, mức mục tiêu hoặc nhu cầu
phụ tùng chưa xuất kho. repair_order_parts đã trừ stock khi ghi nhận sử dụng.
"""

import os
import re
from datetime import datetime

from .ai_service import AIResult, ai_service
from .permissions import has_permission
from .timeutil import VN_TZ

DENIED = "Bạn không có quyền truy cập thông tin tồn kho này. Vui lòng liên hệ quản trị viên để được cấp quyền phù hợp."


def _catalog_mode() -> str:
    """Mặc định production; demo phải được bật rõ ràng bằng cấu hình môi trường."""
    return os.getenv("CATALOG_MODE", "production").strip().casefold()


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


def is_part_price_question(question: str) -> bool:
    """Nhận diện hỏi giá phụ tùng, tách khỏi luồng tra tồn kho."""
    text = ai_service._normalize_vi(question)
    subject = any(term in text for term in (
        "lop", "vo xe", "bugi", "phanh", "ma phanh", "dia phanh", "bo phanh",
        "phu tung", "linh kien", "ma phu tung", "ma hang",
    ))
    intent = any(term in text for term in (
        "gia", "bao nhieu", "bao nhiêu", "het bao nhieu", "tien",
    ))
    return subject and intent


def answer_catalog_parts_question(db, question: str, user: dict):
    """Tra cứu dạng danh mục: đếm/ liệt kê/ so sánh các nhóm phụ tùng."""
    text = ai_service._normalize_vi(question)
    wants_battery = any(term in text for term in ("ac quy", "acquy", "binh ac quy"))
    wants_tire = bool(re.search(r"\b(lop|vo xe|tire)\b", text))
    intent = any(term in text for term in (
        "may loai", "co nhung", "nhung loai", "bao nhieu loai", "liet ke",
        "so sanh", "khac nhau", "lua chon", "danh sach",
    ))
    if not (intent and (wants_battery or wants_tire)):
        return None

    rows = [dict(row) for row in db.execute(
        """SELECT id,code,name,category,unit,sell_price,supplier FROM parts
           WHERE active=1 ORDER BY name,code"""
    )]
    if wants_battery:
        rows = [row for row in rows if re.search(r"\b(ac quy|acquy|binh ac quy)\b",
                                                  ai_service._normalize_vi(row["name"]))
                and not re.search(r"\b(day cap|coc binh|cam bien)\b",
                                  ai_service._normalize_vi(row["name"]))]
        subject = "ắc quy"
    else:
        rows = [row for row in rows if re.search(r"\b(lop|vo xe|tire)\b",
                                                  ai_service._normalize_vi(row["name"]))
                and not re.search(r"\b(van lop|cam bien ap suat|tpms)\b",
                                  ai_service._normalize_vi(row["name"]))]
        subject = "lốp"
    if not rows:
        return (AIResult(f"Hiện chưa có sản phẩm {subject} phù hợp trong danh mục đang hoạt động.",
                         "no_data", "local", ai_service.model, True,
                         [f"Danh mục {subject}"]), [])

    # Chỉ hiển thị giá nếu snapshot giá đã được duyệt; không biến sell_price
    # chưa duyệt thành giá bán công khai.
    approved = {}
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='part_price_approvals'").fetchone():
        approved = {row["part_id"]: row["approved_sell_price"] for row in db.execute(
            "SELECT part_id,approved_sell_price FROM part_price_approvals")}
    lines = []
    for row in rows:
        price = (f" · {int(row['sell_price']):,} ₫/{row['unit']}".replace(",", ".")
                 if row["id"] in approved and approved[row["id"]] == row["sell_price"] else
                 " · chưa có giá bán được duyệt")
        lines.append(f"- {row['name']} ({row['code']}){price}")
    lead = (f"Garage hiện có {len(rows)} loại {subject}:" if any(term in text for term in
             ("may loai", "bao nhieu loai", "co nhung")) else
            f"Các lựa chọn {subject} đang có trong danh mục garage:")
    suffix = ("\nCó thể so sánh tiếp theo kích thước, thương hiệu hoặc giá đã duyệt."
              if wants_tire and "so sanh" in text else "")
    sources = [{"type": "part", "id": row["id"],
                "label": f"Danh mục phụ tùng: {row['name']} ({row['code']})"}
               for row in rows]
    return AIResult(lead + "\n" + "\n".join(lines) + suffix,
                    "fallback", "local", ai_service.model), sources


def answer_part_price_question(db, question: str, user: dict, vehicle: dict | None = None):
    """Only disclose prices explicitly approved for the current catalog snapshot."""
    if not is_part_price_question(question):
        return None
    text = ai_service._normalize_vi(question)
    wants_tire = bool(re.search(r"\b(lop|vo xe)\b", text))
    wants_brake = bool(re.search(r"\b(phanh|ma phanh|dia phanh|bo phanh)\b", text))
    # Câu hỏi chung về "phụ tùng xe tôi" cần đi qua nhánh yêu cầu xe/
    # hồ sơ; không biến nó thành yêu cầu liệt kê toàn bộ danh mục có giá.
    if not wants_tire and any(term in text for term in ("xe toi", "xe cua toi", "xe minh")):
        return None
    size = re.search(r"\b\d{3}\s*/?\s*\d{2}\s*r\s*\d{2}\b", text, re.I)
    size_text = re.sub(r"\s+", "", size.group(0)).upper() if size else ""
    brands = [brand for brand in (
        "michelin", "bridgestone", "goodyear", "continental", "yokohama",
        "dunlop", "kumho", "hankook", "maxxis",
    ) if brand in text]
    # A running backend may not yet have applied migration 027. Fail closed;
    # never treat sell_price alone as approval.
    approvals_available = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='part_price_approvals'"
    ).fetchone() is not None
    rows = [dict(row) for row in db.execute(
        ("SELECT p.id,p.code,p.name,p.category,p.compatible,p.unit,p.sell_price,p.supplier, "
         "a.approved_sell_price FROM parts p LEFT JOIN part_price_approvals a ON a.part_id=p.id "
         "WHERE p.active=1 ORDER BY p.name,p.code" if approvals_available else
         "SELECT id,code,name,category,compatible,unit,sell_price,supplier, "
         "NULL approved_sell_price FROM parts WHERE active=1 ORDER BY name,code")
    ).fetchall()]

    def searchable(row):
        return ai_service._normalize_vi(" ".join(
            str(row.get(key) or "") for key in ("name", "category", "compatible", "code")
        ))

    if wants_tire:
        rows = [row for row in rows if re.search(
            r"\b(lop|vo xe|tire)\b",
            ai_service._normalize_vi(str(row["name"]))) and not re.search(
                r"\b(giam xoc|ro tuyn|bi moay|can bang|va lop)\b",
                ai_service._normalize_vi(str(row["name"])))]
    elif wants_brake:
        rows = [row for row in rows if re.search(
            r"\b(phanh|ma phanh|dia phanh|bo phanh)\b",
            ai_service._normalize_vi(f"{row['name']} {row['category']}"))]
    elif "bugi" in text:
        rows = [row for row in rows if "bugi" in ai_service._normalize_vi(str(row["name"]))]
    else:
        # Generic "giá linh kiện" is not permission to disclose every part.
        rows = [row for row in rows if ai_service._normalize_vi(str(row["name"])) in text
                or ai_service._normalize_vi(str(row["code"])) in text
                or ai_service._normalize_vi(str(row["category"])) in text]
    if size_text:
        compact = size_text.casefold()
        rows = [row for row in rows if compact in re.sub(r"\s+", "", searchable(row)).upper().casefold()]
    if brands:
        rows = [row for row in rows if any(brand in searchable(row) for brand in brands)]
    # Text in compatible/name is not a verified fitment rule. No tire size is
    # stored on the vehicle record: do not infer one from make/model alone.

    if not rows:
        hint = (f" kích thước {size_text}" if size_text else "")
        return (AIResult(
            ("Chưa tìm thấy lốp" + hint if wants_tire else
             "Chưa tìm thấy phụ tùng phanh" if wants_brake else
             "Chưa tìm thấy phụ tùng được hỏi") +
            " trong danh mục phụ tùng đang hoạt động. "
            "Bạn có thể cung cấp tên/mã sản phẩm hoặc kích thước ghi trên hông lốp để garage tra đúng mã.",
            "no_data", "local", ai_service.model,
             True, ["Kích thước hoặc mã lốp" if wants_tire else
                    "Mã hoặc loại phụ tùng phanh" if wants_brake else "Tên hoặc mã phụ tùng"]), [])

    demo_mode = _catalog_mode() == "demo"
    priced = [row for row in rows
              if row["sell_price"] is not None and int(row["sell_price"]) > 0
              and ((demo_mode and (row["code"].upper().startswith("DEMO-")
                                   or "(mẫu)" in row["name"].casefold()
                                   or "mẫu" in str(row["supplier"] or "").casefold()))
                   or (not demo_mode and not row["code"].upper().startswith("DEMO-")
                       and "(mẫu)" not in row["name"].casefold()
                       and row["supplier"] != "Danh mục mẫu"
                       and row["approved_sell_price"] == row["sell_price"]))]
    if not priced:
        return (AIResult(
            f"Danh mục có sản phẩm phù hợp nhưng chưa có giá bán "
            f"{'lốp' if wants_tire else 'phụ tùng phanh' if wants_brake else 'phụ tùng'} hiện hành được duyệt "
            "(hoặc chỉ có dữ liệu mẫu). Vui lòng nhờ cố vấn dịch vụ kiểm tra bảng giá trước khi báo khách.",
            "no_data", "local", ai_service.model, True,
            ["Giá bán lốp" if wants_tire else
             "Giá bán phụ tùng phanh" if wants_brake else "Giá bán phụ tùng"]), [])

    limit = 8
    lines = []
    for row in priced[:limit]:
        lines.append(f"- {row['name']} ({row['code']}): "
                     f"{int(row['sell_price']):,} ₫/{row['unit']}.".replace(",", "."))
    suffix = (f"\nĐang hiển thị {len(lines)}/{len(priced)} lựa chọn. Vui lòng cho biết kích thước "
              "hoặc thương hiệu để thu hẹp kết quả." if len(priced) > limit else "")
    vehicle_note = (" Chưa thể xác nhận lốp phù hợp với xe đã chọn chỉ từ hãng/dòng xe; "
                    "vui lòng cung cấp kích thước trên hông lốp và đối chiếu thực tế."
                    if any(term in text for term in ("xe toi", "xe cua toi", "xe minh", "vios")) else "")
    total_note = (" Chưa thể tính tổng tiền thay lốp: cần xác nhận mã lốp, số lượng, "
                  "giá công và các khoản áp dụng trên báo giá."
                  if "thay lop" in text or "thay vo xe" in text else "")
    content = (("Theo giá DEMO trong danh mục minh họa:\n" if demo_mode else
                "Theo giá bán đã được duyệt cho từng mặt hàng trong danh mục garage:\n") +
               "\n".join(lines) + suffix + vehicle_note + total_note +
                ("\nGiá lốp chưa gồm công thay và các chi phí khác; " if wants_tire else
                 "\nGiá phụ tùng phanh chưa gồm công thay và các chi phí khác; " if wants_brake else
                 "\nGiá phụ tùng chưa gồm công thay và các chi phí khác; ") +
                ("Đây là giá tham khảo DEMO trước khi tới garage; chưa được garage phê duyệt, "
                 "không phải tra cứu hóa đơn và không dùng để lập hóa đơn."
                 if demo_mode else "đây chưa phải báo giá chính thức."))
    # Snapshot này vừa là nguồn hiển thị vừa là dữ liệu đã lọc để Ollama diễn đạt.
    # Không đưa stock/cost_price/supplier hoặc dữ liệu chưa được duyệt vào snapshot.
    sources = [{"type": "part", "id": row["id"],
                 "label": f"Danh mục {'DEMO ' if demo_mode else ''}phụ tùng: {row['name']} ({row['code']})",
                 "name": row["name"], "code": row["code"],
                 "unit": row["unit"], "price": int(row["sell_price"]),
                 "price_status": "DEMO" if demo_mode else "approved",
                "size": next((part for part in re.findall(
                    r"\d{3}\s*/?\s*\d{2}\s*[Rr]\s*\d{2}", str(row["name"]))), None)}
                for row in priced[:limit]]
    return AIResult(content, "fallback", "local", ai_service.model, False), sources


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
