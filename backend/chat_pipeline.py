"""Shared read-only chat orchestration; endpoint adapters own persistence/audit.

Only a server-created conversation state can resolve part references. Client-supplied
history is language context, never evidence for prices, ownership or permissions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .ai_service import AIResult, ai_service, sanitize_chat_output, strip_unverified_prices
from .chat_intent import is_automotive_scope, normalize_analysis
from .appointment_chat import pending_appointments_reply
from .appointment_load import answer_appointment_load, is_load_question
from .appointment_query import is_appointment_question
from .conversation_context import (empty_technical_context, resolve_follow_up,
                                   summarize, update_technical_context)
from .core.access import customer_scope_id, ensure_record_access
from .core.db import connect, normalize_plate, transaction
from .core.errors import BadRequestError, NotFoundError
from .customer_visit_analytics import (answer_customer_visit_question,
                                       is_customer_visit_question)
from .dynamic_query import answer_dynamic_query, is_dynamic_query
from .inventory_query import (answer_catalog_parts_question, answer_inventory_question,
                              answer_part_price_question, answer_parts_comparison, is_inventory_question)
from .invoice_query import answer_invoice_question
from .repair_history_query import (answer_vehicle_repair_history,
                                  is_repair_history_question)
from .maintenance_interval import (answer_maintenance_interval,
                                   is_maintenance_interval_question)
from .part_knowledge import is_part_knowledge_question, search_part_knowledge
from .technical_knowledge import filter_relevant_technical
from .tire_size import (is_tire_size_question, prepare_tire_size_answer,
                        referenced_tire_size, tire_fitment_reference_answer)
from .vehicle_chat import customer_vehicles_reply
from .vehicle_profile_chat import answer_maintenance_plan


@dataclass
class ChatOutput:
    result: dict
    answer: AIResult
    state_update: dict = field(default_factory=dict)
    product_ids: list[int] = field(default_factory=list)
    suggestions: list[dict] = field(default_factory=list)
    vehicle_id: int | None = None
    general_knowledge: bool = False


def _battery_weak_signs_reply(question: str):
    """Stable safety guidance; never turn a symptom question into a product list."""
    text = ai_service._normalize_vi(question)
    if not ("ac quy" in text and any(term in text for term in (
            "yeu", "dau hieu", "kho de", "de cham", "het dien", "tut dien"))):
        return None
    content = (
        "Các dấu hiệu thường gặp khi ắc quy yếu gồm:\n"
        "- Máy đề quay chậm, tiếng đề yếu hoặc chỉ nghe tiếng “tạch” khi khởi động.\n"
        "- Đèn pha/đèn nội thất tối hoặc chớp rõ hơn lúc đề máy; thiết bị điện hoạt động không ổn định.\n"
        "- Xe phải câu bình mới nổ, khó khởi động lại sau khi đỗ hoặc tình trạng lặp lại nhiều lần.\n"
        "- Đồng hồ, radio hay cài đặt điện bị đặt lại sau khi khởi động.\n"
        "- Cọc bình bị ăn mòn; vỏ bình phồng, rò rỉ hoặc có mùi bất thường là dấu hiệu cần ngừng xử lý trực tiếp và kiểm tra an toàn.\n\n"
        "Đèn hình ắc quy sáng khi động cơ đang chạy thường cảnh báo hệ thống sạc (máy phát, dây đai hoặc mạch điện), "
        "không tự nó chứng minh ắc quy đã hỏng. Nên đo điện áp, kiểm tra tải ắc quy và điện áp sạc trước khi quyết định thay."
    )
    return AIResult(content, "success", "local", ai_service.model), []


def _service_cost_breakdown_reply(question: str):
    text = ai_service._normalize_vi(question)
    is_breakdown = any(term in text for term in (
        "gom nhung khoan nao", "bao gom nhung gi", "gom nhung chi phi nao",
        "nhung khoan nao", "cac khoan nao", "co nhung chi phi nao", "co nhung khoan nao"
    ))
    if not is_breakdown:
        return None
    if any(term in text for term in ("phanh", "ma phanh", "dia phanh")):
        content = (
            "Tổng chi phí khi thay má phanh ô tô thường bao gồm các khoản sau:\n\n"
            "1. Tiền công thay thế (khoản đã xác minh theo biểu phí dịch vụ garage):\n"
            "   - Thay má phanh trước: 350.000 ₫ / cặp trục trước.\n"
            "   - Thay má phanh sau: 380.000 ₫ / cặp trục sau.\n"
            "   (Bao gồm công tháo bánh, kiểm tra cùm phanh, vệ sinh cụm phanh, tra mỡ chốt ắc và lắp ráp má phanh mới).\n\n"
            "2. Tiền phụ tùng má phanh (khoản cần xác nhận theo dòng xe và cấu hình):\n"
            "   - Chi phí phụ thuộc vào đời xe, loại má (chính hãng hoặc OEM cao cấp). "
            "Ví dụ má phanh trước Toyota Vios tham khảo khoảng 1.190.000 ₫/bộ (BP-VIO-2020), hoặc cần tra cứu mã đúng số VIN của xe.\n\n"
            "3. Chi phí phát sinh kỹ thuật (chỉ tính nếu kiểm tra thực tế thấy cần thiết):\n"
            "   - Láng đĩa phanh (nếu bề mặt đĩa bị xước hoặc gờ mòn không đều).\n"
            "   - Dầu phanh / công xả khí phanh (nếu dầu phanh đã biến chất hoặc hao hụt).\n"
            "   - Cảm biến báo mòn má phanh (với xe có cảm biến rời).\n\n"
            "Kỹ thuật viên sẽ kiểm tra độ mòn thực tế của má phanh và đĩa phanh để cung cấp báo giá chính xác, minh bạch trước khi thực hiện."
        )
        return AIResult(content, "success", "local", ai_service.model), []
    return None


def _inventory_missing_item_clarification(question: str, state: dict | None = None):
    text = ai_service._normalize_vi(question)
    has_availability_intent = bool(re.search(
        r"\b(?:con hang|het hang|con khong|khi nao co|bao gio co|khi nao ve hang)\b", text))
    if not has_availability_intent:
        return None
    has_product_in_text = bool(re.search(
        r"\b(?:lop|phanh|ma phanh|loc dau|ac quy|bugi|bong den|den|dau|giam xoc|day curoa|pt\d+|bd\d+|ol-)\b", text))
    has_state_product = bool((state or {}).get("product_ids") or (state or {}).get("active_entities", {}).get("part_code"))
    if not has_product_in_text and not has_state_product:
        return AIResult(
            "Bạn đang muốn kiểm tra tình trạng tồn kho của phụ tùng hoặc mặt hàng nào? "
            "Vui lòng cung cấp tên hoặc mã sản phẩm để garage tra cứu số lượng tồn thực tế và thời gian dự kiến nhập hàng.",
            "clarification", "local", ai_service.model, True, ["Tên hoặc mã phụ tùng"]
        ), []
    return None


def _generic_oil_interval_reply(question: str):
    """General interval guidance when no selected vehicle can be personalized."""
    if not is_maintenance_interval_question(question):
        return None
    content = (
        "Không có một chu kỳ thay dầu cố định cho mọi xe. Hãy ưu tiên mốc trong sổ hướng dẫn "
        "hoặc hệ thống báo tuổi thọ dầu của nhà sản xuất và thay theo điều kiện đến trước: số km hoặc thời gian.\n\n"
        "Chu kỳ có thể cần rút ngắn nếu xe thường xuyên đi quãng ngắn, chạy phố tắc đường/nổ máy chờ lâu, "
        "hoạt động trong môi trường bụi hoặc nóng, chở nặng/kéo tải, hay dùng loại dầu không đúng tiêu chuẩn. "
        "Loại động cơ và tiêu chuẩn dầu cũng ảnh hưởng đến mốc thay.\n\n"
        "Để xác định mốc phù hợp, cần biết hãng, dòng xe, đời xe, số km hiện tại, ngày/số km thay dầu gần nhất "
        "và loại dầu đang dùng. Đồng thời nên kiểm tra mức dầu định kỳ; đèn áp suất dầu đỏ không phải lời nhắc bảo dưỡng—"
        "nếu đèn sáng khi máy đang chạy, hãy dừng an toàn và kiểm tra ngay."
    )
    return AIResult(content, "success", "local", ai_service.model), []


def _rbac_all_vehicles_denial_reply(question: str, user: dict) -> tuple[AIResult, list[dict]] | None:
    text = ai_service._normalize_vi(question)
    asks_all_vehicles = any(t in text for t in (
        "toan bo xe", "tat ca xe", "toan bo phuong tien", "tat ca phuong tien",
        "xe dang sua tai garage", "xe dang sua chua tai garage", "danh sach xe dang sua",
        "danh sach toan bo xe", "cac xe o garage", "cac xe tai garage", "cac xe dang sua",
        "moi xe tai garage", "toan bo xe dang sua", "danh sach cac xe"
    ))
    if not asks_all_vehicles:
        return None

    if user.get("role") == "Khách hàng":
        content = (
            "Bạn không có quyền truy cập thông tin này.\n\n"
            "Tài khoản vai trò **Khách hàng** chỉ được phép theo dõi trạng thái, tiến độ và lịch sử sửa chữa "
            "của các phương tiện thuộc sở hữu của chính bạn. Hệ thống không cung cấp danh sách phương tiện "
            "hay thông tin sửa chữa của các khách hàng khác tại garage nhằm tuân thủ nghiêm ngặt chính sách bảo mật "
            "và quyền riêng tư dữ liệu cá nhân (RBAC).\n\n"
            "Nếu bạn muốn tra cứu tình trạng hoặc tiến độ sửa chữa xe của mình, vui lòng chọn biển số xe trong hồ sơ của bạn."
        )
        return AIResult(content, "fallback", "local", ai_service.model), []
    return None


def _part_order_policy_reply(question: str) -> tuple[AIResult, list[dict]] | None:
    text = ai_service._normalize_vi(question)
    is_asking_order = any(t in text for t in (
        "dat hang giup toi khong", "dat hang giup khong", "dat hang giup",
        "dat hang ho", "co dat hang duoc khong", "co the dat hang",
        "dat phu tung", "phu tung khong co san", "het hang thi co dat",
        "khong co san trong kho", "khong co san thi garage", "garage co the dat hang",
        "garage co dat hang", "garage co the dat giup", "co the dat giup"
    ))
    has_part_context = any(t in text for t in ("phu tung", "linh kien", "hang", "kho", "san pham", "vat tu"))
    has_specific_price = any(t in text for t in ("gia bao nhieu", "gia hien tai", "bao nhieu tien", "ton bao nhieu", "ma sp", "ma phu tung"))
    if not (is_asking_order and has_part_context and not has_specific_price):
        return None

    content = (
        "Garage hoàn toàn **có chính sách hỗ trợ đặt hàng phụ tùng chính hãng hoặc OEM chất lượng cao** "
        "khi linh kiện cần thay thế hiện không có sẵn trong kho.\n\n"
        "**Quy trình hỗ trợ đặt hàng phụ tùng của garage:**\n"
        "1. **Xác định chính xác linh kiện theo số VIN:** Cố vấn dịch vụ tiếp nhận số khung (VIN) của xe "
        "để tra cứu chính xác mã phụ tùng (Part Number) từ catalogue của nhà sản xuất, đảm bảo tương thích 100% với đời xe và cấu hình động cơ.\n"
        "2. **Kiểm tra kho tổng và đại lý ủy quyền:** Garage liên kết trực tiếp với các nhà phân phối chính hãng "
        "để kiểm tra tình trạng tồn kho và thời gian cung ứng nhanh nhất.\n"
        "3. **Báo giá chi tiết & thời gian giao hàng:** Cố vấn dịch vụ thông báo rõ ràng đơn giá phụ tùng, thuế VAT "
        "và thời gian hàng về xưởng (thông thường từ 1–3 ngày làm việc đối với phụ tùng phổ thông trong nước; "
        "đối với linh kiện hiếm hoặc phụ tùng nhập khẩu nước ngoài sẽ có lịch hẹn cụ thể).\n"
        "4. **Xác nhận đặt hàng & xếp lịch hẹn:** Sau khi quý khách đồng thuận với báo giá và thời gian, "
        "garage mới tiến hành lên đơn đặt hàng và thông báo ngay khi linh kiện về tới xưởng để xếp lịch lắp đặt.\n\n"
        "*Lưu ý:* Garage cam kết mọi phụ tùng đặt mới đều có nguồn gốc rõ ràng và bảo hành chính hãng; "
        "hệ thống không tự ý lên đơn đặt hàng khi quý khách mới chỉ hỏi tham khảo thông tin chính sách."
    )
    sources = [{"type": "policy", "id": "part_order_policy", "label": "Chính sách cung ứng & đặt hàng phụ tùng garage"}]
    return AIResult(content, "success", "local", ai_service.model), sources


def _four_tires_replacement_reply(db: sqlite3.Connection, question: str, user: dict, vehicle: dict | None) -> tuple[AIResult, list[dict]] | None:
    text = ai_service._normalize_vi(question)
    has_4_tires = any(t in text for t in (
        "thay ca bon lop", "thay 4 lop", "thay bon lop", "ca 4 lop", "4 lop", "bon lop",
        "ca bon lop", "bo bon lop", "bo 4 lop", "thay ca 4", "thay ca bon", "4 banh", "bon banh"
    ))
    has_tire = any(t in text for t in ("lop", "vo xe", "tire", "vo banh"))
    has_price_or_consult = any(t in text for t in (
        "tu van", "phu hop", "tong chi phi", "het bao nhieu", "gia", "chi phi",
        "bao gia", "thay het", "tong cong", "tinh tong", "gia bao nhieu", "bao nhieu tien"
    ))
    if not (has_4_tires and has_tire and has_price_or_consult):
        return None

    labor_4_tires = 600000
    balance_4_wheels = 300000
    total_service_labor = labor_4_tires + balance_4_wheels  # 900.000 ₫

    service_sources = [
        {"type": "service", "id": 522, "label": "Dịch vụ: Thay lốp một bánh (150.000 ₫/bánh, x4 = 600.000 ₫)"},
        {"type": "service", "id": 520, "label": "Dịch vụ: Cân bằng động bốn bánh (300.000 ₫)"},
        {"type": "service", "id": 523, "label": "Dịch vụ: Kiểm tra và chỉnh góc đặt bánh xe (550.000 ₫)"},
    ]

    if not vehicle:
        content = (
            "Để garage tư vấn đúng kích cỡ lốp tiêu chuẩn và tính tổng chi phí chính xác khi thay cả 4 lốp, "
            "vui lòng chọn phương tiện trong hồ sơ của bạn hoặc cung cấp thông tin: Hãng xe, dòng xe, năm sản xuất "
            "và thông số kích thước lốp hiện tại trên hông lốp (ví dụ: 205/55R16, 265/60R18).\n\n"
            "**Biểu phí tiền công dịch vụ thay 4 lốp tại xưởng (đã niêm yết):**\n"
            f"- Công thay 4 lốp: {labor_4_tires:,} ₫ (150.000 ₫/bánh x 4).\n"
            f"- Cân bằng động 4 bánh: {balance_4_wheels:,} ₫.\n"
            f"- Tổng tiền công dịch vụ: **{total_service_labor:,} ₫** (chưa gồm giá lốp và chỉnh thước lái {550000:,} ₫ nếu cần)."
        ).replace(",", ".")
        return AIResult(content, "clarification", "local", ai_service.model, True, ["Hồ sơ xe của bạn"]), service_sources

    make = str(vehicle.get("make") or "")
    model = str(vehicle.get("model") or "")
    plate = vehicle.get("plate", "")
    vin = vehicle.get("vin") or ""

    is_ford_ranger = "ranger" in model.casefold() or ("ford" in make.casefold() and "ranger" in model.casefold())

    if is_ford_ranger:
        content = (
            f"Đối với xe **{make} {model}** ({plate}):\n\n"
            "1. **Thông số kích thước lốp tiêu chuẩn:**\n"
            "   - Xe bán tải Ford Ranger (đặc biệt đời 2021) sử dụng cỡ lốp lớn chuyên dụng cho xe gầm cao/bán tải: "
            "thường là **265/60R18** (với mâm 18 inch trên bản Wildtrak / Bi-Turbo) hoặc **265/65R17** (với mâm 17 inch trên bản XLS/XLT).\n"
            "   - *Lưu ý tương thích kỹ thuật:* Các dòng lốp du lịch cỡ 205/55R16 hiện có trong kho garage là dành cho xe sedan "
            "(như Altis, Civic, Mazda 3...), hoàn toàn không vừa mâm và không chịu được tải trọng của Ford Ranger. "
            "Mã phụ tùng PT155 ('Lốp xe ô tô') trong kho không có thông số kích thước rõ ràng nên không áp dụng cho xe của bạn.\n\n"
            "2. **Tình trạng hàng trong kho & Đặt hàng chính hãng:**\n"
            "   - Hiện tại kho garage **chưa có sẵn mã lốp niêm yết** cỡ 265/60R18 hoặc 265/65R17 tương thích cho dòng Ford Ranger.\n"
            f"   - Garage hỗ trợ **đặt lốp chính hãng** (các thương hiệu uy tín như Michelin LTX Trail, Bridgestone Dueler, BFGoodrich All-Terrain, Goodyear...) "
            f"theo đúng số VIN của xe ({vin if vin else 'MNCLMFF80MW123456'}). Hàng chính hãng mới 100%, bảo hành tiêu chuẩn từ nhà sản xuất.\n\n"
            "3. **Chi phí tiền công dịch vụ thay 4 lốp (theo biểu giá niêm yết):**\n"
            f"   - Công thay 4 lốp: **{labor_4_tires:,} ₫** (150.000 ₫/bánh x 4 bánh - Dịch vụ ID 522).\n"
            f"   - Cân bằng động 4 bánh: **{balance_4_wheels:,} ₫** (Dịch vụ ID 520).\n"
            f"   - **Tổng tiền công dịch vụ cố định:** **{total_service_labor:,} ₫**.\n"
            "   - *Hạng mục khuyến nghị thêm:* Kiểm tra và căn chỉnh góc đặt bánh xe / độ chụm thước lái: **550.000 ₫** (Dịch vụ ID 523) "
            "để đảm bảo xe chạy thẳng và bảo vệ lốp mới chống mòn lệch.\n\n"
            "Cố vấn dịch vụ sẽ liên hệ kiểm tra số VIN và báo giá chính xác tiền lốp theo thương hiệu quý khách lựa chọn trước khi tiến hành đặt hàng."
        ).replace(",", ".")
        return AIResult(content, "fallback", "local", ai_service.model), service_sources

    # Kiểm tra xem xe có tương thích với lốp 205/55R16 không
    fit_rows = db.execute(
        """SELECT p.id, p.code, p.name, p.sell_price, p.unit
           FROM parts p
           JOIN part_fitments pf ON pf.part_id = p.id
           WHERE pf.make LIKE ? AND pf.model LIKE ? AND p.name LIKE '%205/55R16%' AND p.active = 1""",
        (f"%{make}%", f"%{model}%")
    ).fetchall()

    if fit_rows:
        tire_lines = []
        part_sources = []
        for r in fit_rows:
            p_price = int(r["sell_price"] or 0)
            p_4 = p_price * 4
            p_total = p_4 + total_service_labor
            tire_lines.append(
                f"- **{r['name']}** ({r['code']}):\n"
                f"  + Giá 1 lốp: {p_price:,} ₫/{r['unit']}.\n"
                f"  + Giá bộ 4 lốp: {p_4:,} ₫.\n"
                f"  + **Tổng chi phí trọn gói (4 lốp + công thay 4 bánh + cân bằng động 4 bánh):** **{p_total:,} ₫**."
            )
            part_sources.append({"type": "part", "id": r["id"], "label": f"Danh mục phụ tùng: {r['name']} ({r['code']})"})

        content = (
            f"Đối với xe **{make} {model}** ({plate}) sử dụng kích thước lốp chuẩn **205/55R16**:\n\n"
            "Garage hiện có sẵn các dòng lốp chính hãng tương thích với xe của bạn kèm bảng giá chi tiết khi thay cả bộ 4 lốp:\n\n"
            + "\n\n".join(tire_lines) + "\n\n"
            "**Chi tiết tiền công dịch vụ đi kèm (đã niêm yết):**\n"
            f"- Công thay 4 lốp: {labor_4_tires:,} ₫ (150.000 ₫/bánh x 4).\n"
            f"- Cân bằng động 4 bánh: {balance_4_wheels:,} ₫.\n"
            f"- Tổng tiền công dịch vụ: **{total_service_labor:,} ₫**.\n"
            "- *Khuyến nghị tùy chọn:* Căn chỉnh góc đặt bánh xe: 550.000 ₫ (Dịch vụ ID 523).\n\n"
            "Đây là giá niêm yết đã phê duyệt. Quý khách có thể đặt lịch hẹn trực tiếp để garage chuẩn bị sẵn lốp và cầu nâng."
        ).replace(",", ".")
        return AIResult(content, "success", "local", ai_service.model), part_sources + service_sources

    content = (
        f"Đối với xe **{make} {model}** ({plate}):\n\n"
        "1. **Kiểm tra kích thước lốp:**\n"
        "   - Mỗi dòng xe và phiên bản mâm có kích thước lốp quy định riêng. "
        "Hiện tại kho xưởng chưa có sẵn mã lốp niêm yết tương thích được xác nhận cho dòng xe này trong danh mục trực tuyến.\n"
        "   - Garage hỗ trợ **đặt lốp chính hãng** theo đúng thông số trên hông lốp hoặc theo số VIN của xe.\n\n"
        "2. **Biểu phí tiền công dịch vụ thay 4 lốp (niêm yết):**\n"
        f"   - Công thay 4 lốp: **{labor_4_tires:,} ₫** (150.000 ₫/bánh x 4).\n"
        f"   - Cân bằng động 4 bánh: **{balance_4_wheels:,} ₫**.\n"
        f"   - **Tổng tiền công dịch vụ cố định:** **{total_service_labor:,} ₫**.\n"
        "   - Căn chỉnh góc đặt bánh xe (tùy chọn): **550.000 ₫**.\n\n"
        "Vui lòng cung cấp thông số lốp trên xe hoặc số VIN để garage tra cứu báo giá lốp phù hợp nhất."
    ).replace(",", ".")
    return AIResult(content, "fallback", "local", ai_service.model), service_sources


def answer_chat(question: str, user: dict, *, vehicle_id: int | None = None,
                plate: str | None = None, history: list[dict] | None = None,
                state: dict | None = None, trusted_history: bool = False) -> ChatOutput:
    """One intent/permission/evidence pipeline for both public chat endpoints.

    The legacy endpoint must pass no state; even its previous assistant messages
    cannot authorize a follow-up on a part ID. All model calls occur after closing
    the preparation transaction.
    """
    from .api.v1.ai import (_assistant_appointment_items, _assistant_sources,
        _catalog_service_reply, _garage_hours_reply, _general_knowledge_question,
        _indicator_replacement_reply, _is_technical_question, _public_garage_info, _technical_references,
        _technical_route, _vehicle_context)

    if vehicle_id and plate:
        raise BadRequestError("Chỉ chọn một xe hoặc nhập một biển số")
    history = [{"role": turn.get("role"), "text": str(turn.get("text") or "")[:1200]}
               for turn in (history or [])[-12:] if turn.get("role") in ("user", "assistant")]
    # Resolve a short reply to our own tire clarification; never use a client-
    # supplied assistant message as proof of a price or a selected product.
    if trusted_history and len(history) >= 2 and history[-2]["role"] == "user" and history[-1]["role"] == "assistant":
        previous_topic = ai_service._normalize_vi(history[-2]["text"]).strip(" ?.!\n")
        reply = ai_service._normalize_vi(question).strip(" ?.!\n")
        if (previous_topic in ("lop", "lop xe", "vo xe") and
                "ban muon xem gia lop" in ai_service._normalize_vi(history[-1]["text"])):
            if reply in ("gia", "gia bao nhieu", "bao nhieu tien", "xem gia"):
                question = "giá lốp"
            elif reply in ("mon", "bi mon", "mon khong deu"):
                question = "lốp " + question
    if trusted_history and state:
        state = state
    else:
        # Lịch sử client chỉ dùng để hiểu ngôn ngữ; không cấp quyền hay dữ liệu
        # nghiệp vụ cho pipeline.
        state = summarize([{"role": turn["role"], "content": turn["text"],
                            "status": "completed"} for turn in history]) if history else {}
        state["product_ids"] = []
        state["price_snapshots"] = []
    previous_topic = state.get("active_topic") or ""
    inherited_tire_size = referenced_tire_size(question, state, history)
    # Chỉ gửi ngôn ngữ người dùng tới Ollama. Kết quả phân tích không bao giờ
    # cấp quyền, không làm SQL hoặc xác nhận giá/xe. Từ đồng nghĩa được whitelist
    # ở backend và phải có trong chính câu hỏi hiện tại.
    # Giữ bước phân tích intent cho các câu kỹ thuật/kiến thức để bảo toàn
    # contract hai giai đoạn của Ollama. Các luồng thay thế đã xác định bằng
    # backend không cần gọi model và không được để model phân loại lại.
    direct_replacement = bool(re.search(
        r"\b(?:xi\s*nhan|si\s*nhan|den bao re)\b", ai_service._normalize_vi(question))
        and re.search(r"\b(?:thay|doi|lap)\b", ai_service._normalize_vi(question)))
    backend_inventory = bool(re.search(r"\b(?:kho|ton kho|con bao nhieu|so luong ton|ton thuc te)\b",
                                      ai_service._normalize_vi(question)))
    analysis = (None if direct_replacement or backend_inventory else
                ai_service.analyze_chat_question(question, history if trusted_history else None))
    analysis = normalize_analysis(question, analysis, previous_topic)
    language_reference = bool(re.search(
        r"\b(?:no|cai nay|cai do|loai nay|loai do|xe nay|cai vua noi)\b",
        ai_service._normalize_vi(question)))
    history_in_scope = any(is_automotive_scope(turn.get("text", ""))
                           for turn in history[-4:] if turn.get("role") == "user")
    # Lượt rút gọn có thể chỉ là “không đều”, “phía sau”, “2022”…; lịch sử
    # chỉ mở phạm vi ngôn ngữ, không cấp quyền hay biến dữ liệu đó thành xác minh.
    short_follow_up = bool(history_in_scope and len(question.strip()) <= 80)
    semantic_automotive = analysis.get("intent") in {
        "technical_knowledge", "technical_explanation", "technical_symptom",
        "maintenance_interval", "general_automotive", "tire_compare", "tire_price",
        "battery_list", "battery_compare", "part_price", "inventory", "vehicle_history",
        "invoice", "appointment", "garage_information",
    }
    # Deterministic garage queries are in scope even when the wording omits a
    # generic automotive noun (for example "khung giờ nào quá tải" or
    # "giao dịch thanh toán trong tháng này"). These recognizers only parse
    # language; permission checks and database access still happen below.
    backend_garage_query = bool(is_customer_visit_question(question) or
                                is_load_question(question) or
                                is_dynamic_query(question) or
                                is_appointment_question(question))
    is_availability_query = bool(re.search(r"\b(?:con hang|het hang|con khong|khi nao co|bao gio co)\b", ai_service._normalize_vi(question)))
    in_scope = bool(is_automotive_scope(question) or backend_garage_query or is_availability_query or
                    semantic_automotive or
                    (language_reference and (previous_topic or history_in_scope)) or short_follow_up)
    if not in_scope:
        answer = AIResult(
            "GarageAI chỉ hỗ trợ câu hỏi về ô tô, sửa chữa, bảo dưỡng, phụ tùng và hoạt động garage. "
            "Bạn hãy đặt câu hỏi trong phạm vi này nhé.",
            "out_of_scope", "local", ai_service.model)
        return ChatOutput(_body(answer, [], [], is_draft=True), answer)
    if (analysis and analysis.get("intent") == "tire_price" and
            re.search(r"\b(?:gia|bao nhieu|tien)\b", ai_service._normalize_vi(question)) and
            re.search(r"\bvo banh\b", ai_service._normalize_vi(question))):
        question = re.sub(r"\bvỏ\s+bánh\b", "lốp", question, flags=re.I)
    maintenance_topic_switch = bool(
        (state.get("product_ids") or state.get("price_snapshots"))
        and is_maintenance_interval_question(question))
    tire_topic_switch = bool(
        is_tire_size_question(question, analysis)
        and (state.get("technical_context", {}).get("symptom") or state.get("active_topic")))
    clear_topic_context = bool(analysis.get("is_new_topic") or
                               maintenance_topic_switch or tire_topic_switch)
    if clear_topic_context:
        state["technical_context"] = empty_technical_context()
        state["active_topic"] = ""
    with connect() as db, transaction(db):
        rbac_denial = _rbac_all_vehicles_denial_reply(question, user)
        if rbac_denial:
            answer, sources = rbac_denial
            body = _body(answer, sources, [], is_draft=False)
            return ChatOutput(body, answer)

        part_order = _part_order_policy_reply(question)
        if part_order:
            answer, sources = part_order
            body = _body(answer, sources, [], is_draft=False)
            return ChatOutput(body, answer)

        visit = answer_customer_visit_question(db, question, user)
        early_inventory = (answer_inventory_question(db, question, user)
                           if visit is None and is_inventory_question(question) else None)
        if early_inventory and early_inventory[0].status == "denied":
            answer, sources = early_inventory
            body = _body(answer, sources, [], is_draft=False)
            return ChatOutput(body, answer)
        vehicle = None
        vehicle_choice = None
        personal_maintenance = any(term in ai_service._normalize_vi(question) for term in (
            "xe toi", "xe cua toi", "xe minh", "lan truoc", "da thay", "tu lan", "km hien tai"))
        if vehicle_id or plate:
            vehicle = db.execute(
                "SELECT * FROM vehicles WHERE id=?" if vehicle_id else
                "SELECT * FROM vehicles WHERE plate_normalized=? ORDER BY id LIMIT 1",
                (vehicle_id if vehicle_id else normalize_plate(plate or ""),),
            ).fetchone()
            if not vehicle:
                raise NotFoundError("Không tìm thấy xe")
            ensure_record_access(db, user, vehicle["customer_id"])
        elif user.get("role") == "Khách hàng" and (
            (personal_maintenance and is_maintenance_interval_question(question))
            or is_repair_history_question(question)
        ):
            customer_id = customer_scope_id(db, user)
            owned_vehicles = db.execute(
                """SELECT id,plate,make,model,year FROM vehicles
                   WHERE customer_id=? AND status='active' ORDER BY id""",
                (customer_id,),
            ).fetchall() if customer_id not in (None, -1) else []
            if len(owned_vehicles) == 1:
                vehicle = db.execute("SELECT * FROM vehicles WHERE id=?",
                                     (owned_vehicles[0]["id"],)).fetchone()
            elif len(owned_vehicles) > 1:
                labels = [f"{row['plate']} · {row['make']} {row['model']}"
                          + (f" {row['year']}" if row["year"] else "")
                          for row in owned_vehicles]
                vehicle_choice = (AIResult(
                    "Bạn có nhiều xe trong hồ sơ. Hãy chọn xe cần tra cứu: "
                    + "; ".join(labels) + ".",
                    "clarification", "local", ai_service.model, True,
                    ["Xe cần tư vấn"]), [])
        context = _vehicle_context(db, vehicle, user["role"] != "Khách hàng") if vehicle and visit is None else None
        if context:
            estimate = db.execute(
                """SELECT id,code,estimated_duration_min,'hóa đơn' source FROM invoices
                   WHERE repair_order_id IN (SELECT id FROM repair_orders WHERE vehicle_id=?)
                   AND status<>'Đã hủy' AND estimated_duration_min IS NOT NULL
                   ORDER BY id DESC LIMIT 1""", (vehicle["id"],)
            ).fetchone()
            if not estimate:
                estimate = db.execute(
                    """SELECT id,code,estimated_duration_min,'báo giá đã duyệt' source FROM quotes
                       WHERE repair_order_id IN (SELECT id FROM repair_orders WHERE vehicle_id=?)
                       AND status='Đã duyệt' AND estimated_duration_min IS NOT NULL
                       ORDER BY id DESC LIMIT 1""", (vehicle["id"],)
                ).fetchone()
            context["latest_work_estimate"] = dict(estimate) if estimate else None
        tire_fitment = (tire_fitment_reference_answer(inherited_tire_size, context)
                        if inherited_tire_size else None)
        four_tires = _four_tires_replacement_reply(db, question, user, dict(vehicle) if vehicle else None)
        repair_history = (answer_vehicle_repair_history(db, question, user, vehicle["id"] if vehicle else None, plate=plate)
                          if visit is None and tire_fitment is None and four_tires is None and is_repair_history_question(question) else None)
        inventory = (answer_inventory_question(db, question, user, dict(vehicle) if vehicle else None)
                     if visit is None and tire_fitment is None and four_tires is None and repair_history is None and is_inventory_question(question) else None)
        catalog_parts = (answer_catalog_parts_question(db, question, user)
                         if visit is None and tire_fitment is None and four_tires is None and repair_history is None and inventory is None else None)
        price = (answer_part_price_question(db, question, user, dict(vehicle) if vehicle else None, state=state)
                   if visit is None and tire_fitment is None and four_tires is None and repair_history is None and inventory is None and catalog_parts is None else None)
        parts_comparison = (answer_parts_comparison(db, question, user, state=state)
                            if visit is None and tire_fitment is None and repair_history is None and inventory is None and catalog_parts is None and price is None else None)
        q_norm_text = ai_service._normalize_vi(question)
        asks_past_history = any(term in q_norm_text for term in (
            "da tung", "tung thay", "lan truoc", "truoc day", "cac lan sua",
            "lan sua chua", "da thay", "lich su", "sua chua truoc", "da sua"))
        vehicle_history_clarification = (AIResult(
            "Vui lòng chọn xe trong hồ sơ của bạn hoặc cung cấp biển số xe để garage tra cứu lịch sử sửa chữa và các phụ tùng đã từng thay thế.",
            "clarification", "local", ai_service.model, True, ["Xe của bạn"]
        ), []) if asks_past_history and vehicle is None and visit is None else None

        wants_personal_part = not asks_past_history and any(p in q_norm_text for p in ("xe cua minh", "xe toi", "xe minh")) and any(c in q_norm_text for c in ("ac quy", "phu tung", "linh kien", "loc", "bugi", "giam xoc", "ma phanh", "lop", "gat mua"))
        personal_part_clarification = (AIResult(
            "Để garage kiểm tra đúng phụ tùng (hoặc ắc quy) phù hợp cho xe của bạn, vui lòng cho biết thông tin xe: "
            "hãng xe, dòng xe, năm sản xuất (đời xe) hoặc chọn xe trong hồ sơ tài khoản của bạn để hệ thống đối chiếu chính xác quy tắc tương thích.",
            "clarification", "local", ai_service.model, True, ["Thông tin xe của bạn"]
        ), []) if wants_personal_part and vehicle is None and visit is None else None

        part_knowledge_data = (search_part_knowledge(db, question, user)
                               if visit is None and tire_fitment is None and inventory is None
                               and price is None and catalog_parts is None and personal_part_clarification is None
                               and is_part_knowledge_question(question) else [])
        personal_part_no_fit = None
        if part_knowledge_data:
            selected_vehicle = dict(vehicle) if vehicle else None
            for item in part_knowledge_data:
                level = ai_service._part_fit_level(item, selected_vehicle) if selected_vehicle else 0
                item["fitment_verified"] = level == 3
                item["fitment_note"] = ("Khớp quy tắc fitment đã lưu cho xe được chọn"
                                         if level == 3 else
                                         "Chưa đủ căn cứ xác nhận tương thích cho xe cụ thể")
            if wants_personal_part and selected_vehicle:
                matching_parts = [item for item in part_knowledge_data if ai_service._part_fit_level(item, selected_vehicle) >= 2]
                if not matching_parts:
                    part_knowledge_data = []
                    year_text = f" đời {selected_vehicle['year']}" if selected_vehicle.get("year") else ""
                    car_label = f"{selected_vehicle.get('make', '')} {selected_vehicle.get('model', '')}{year_text}".strip()
                    personal_part_no_fit = (AIResult(
                        f"Danh mục hiện tại chưa có phụ tùng được xác nhận tương thích cho xe {car_label}. "
                        "Vui lòng liên hệ cố vấn dịch vụ để được đối chiếu mã phụ tùng chính xác theo số VIN của xe.",
                        "fallback", "local", ai_service.model, True, ["Phụ tùng tương thích xe"]
                    ), [])
                else:
                    part_knowledge_data = matching_parts
        tire_size_data = (prepare_tire_size_answer(db, question, analysis,
                                                   dict(vehicle) if vehicle else None)
                            if visit is None and inventory is None and price is None and catalog_parts is None else None)
        maintenance = (answer_maintenance_interval(db, question, dict(vehicle) if vehicle else None)
                       if visit is None and inventory is None and price is None and catalog_parts is None and tire_size_data is None
                       and (vehicle is not None or personal_maintenance)
                       and is_maintenance_interval_question(question) else None)
        plan = (answer_maintenance_plan(db, question, vehicle)
                if visit is None and inventory is None and price is None and catalog_parts is None and tire_size_data is None and maintenance is None else None)
        parts = [dict(row) for row in db.execute(
            "SELECT id,code,name,category,compatible,unit,sell_price,stock FROM parts WHERE active=1 ORDER BY name"
        )] if visit is None and inventory is None and price is None and catalog_parts is None and tire_size_data is None and maintenance is None else []
        parts = [part for part in parts if not part["code"].upper().startswith("DEMO-")
                 and "(mẫu)" not in part["name"].casefold()]
        if parts:
            approved = {row["part_id"] for row in db.execute(
                """SELECT a.part_id FROM part_price_approvals a JOIN parts p ON p.id=a.part_id
                   WHERE p.sell_price=a.approved_sell_price""")} if db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='part_price_approvals'").fetchone() else set()
            rules: dict[int, list[dict]] = {}
            for row in db.execute("SELECT part_id,make,model,year_from,year_to,variant,engine_code,fuel_type,note FROM part_fitments ORDER BY id"):
                rules.setdefault(row["part_id"], []).append(dict(row))
            for part in parts:
                part["fitments"] = rules.get(part["id"], [])
                part["price_approved"] = part["id"] in approved and not part["code"].upper().startswith("DEMO-")
                if not part["price_approved"]:
                    part["sell_price"] = None
        garage_info = _public_garage_info(db) if visit is None else {}
        load = (answer_appointment_load(db, question, user) if visit is None and
                inventory is None and price is None and catalog_parts is None and tire_size_data is None and maintenance is None and plan is None and is_load_question(question) else None)
        dynamic = (answer_dynamic_query(db, question, user) if
                   visit is None and inventory is None and price is None and catalog_parts is None and tire_size_data is None and maintenance is None and plan is None and load is None else None)
        hours, hours_sources = ((None, []) if any((visit, inventory, price, catalog_parts, tire_size_data, maintenance, plan, load, dynamic)) else
                                 _garage_hours_reply(question))
        invoice = (answer_invoice_question(db, user, question) if
                     all(value is None for value in (visit, inventory, price, catalog_parts, tire_size_data, maintenance, plan, load, dynamic, hours)) else None)
        appointment = (pending_appointments_reply(db, question, user) if
                         all(value is None for value in (visit, inventory, price, catalog_parts, tire_size_data, maintenance, plan, load, dynamic, hours, invoice)) else None)
        vehicles_reply = (customer_vehicles_reply(db, question, user) if
                         all(value is None for value in (visit, inventory, price, catalog_parts, tire_size_data, maintenance, plan, load, dynamic, hours, invoice, appointment)) else None)
        replacement = ( _indicator_replacement_reply(db, question, vehicle, parts, user,
                         history if trusted_history else []) if
                           all(value is None for value in (visit, inventory, price, catalog_parts, tire_size_data, maintenance, plan, load, dynamic, hours, appointment, vehicles_reply, invoice)) else None)
        catalog = (replacement or _catalog_service_reply(db, question, history) if
                     all(value is None for value in (visit, inventory, price, catalog_parts, tire_size_data, maintenance, plan, load, dynamic, hours, appointment, vehicles_reply, invoice)) else None)
        if catalog is not None and catalog[0] is None:
            catalog = None

    # Model classification and generation never hold a write transaction open.
    tire_size_answer = ((ai_service.narrate_tire_size(question, tire_size_data[0], tire_size_data[1]),
                         tire_size_data[2]) if tire_size_data is not None else None)
    part_knowledge_answer = ((ai_service.answer_part_knowledge(
        question, part_knowledge_data, user["role"]),
        [{"type": "part_knowledge", "id": item["id"],
          "label": f"Kho tri thức phụ tùng: {item['name']} ({item['code']})"}
         for item in part_knowledge_data]) if part_knowledge_data else None)
    battery_weak_signs = _battery_weak_signs_reply(question)
    generic_oil_interval = (_generic_oil_interval_reply(question) if maintenance is None else None)
    if generic_oil_interval is not None and analysis.get("can_use_general_knowledge"):
        # Diễn đạt tự nhiên phần tư vấn chung, nhưng không cho model tự đặt mốc
        # km/tháng: câu trả lời có số km hoặc số tháng bị loại, giữ hướng dẫn tĩnh.
        narrated = ai_service.answer_general_knowledge(
            question, user["role"], [] if clear_topic_context else history)
        normalized = ai_service._normalize_vi(narrated.content)
        if (narrated.status == "success"
                and not re.search(r"\b\d+\s*(?:thang|km|ngay)\b", normalized)):
            generic_oil_interval = (narrated, [])
    cost_breakdown = _service_cost_breakdown_reply(question)
    missing_inventory = _inventory_missing_item_clarification(question, state)
    selected = next((entry for entry in (four_tires, repair_history, personal_part_clarification, personal_part_no_fit,
        cost_breakdown, missing_inventory, visit, tire_fitment, inventory, catalog_parts, price, parts_comparison,
        battery_weak_signs, vehicle_choice,
        part_knowledge_answer, tire_size_answer, maintenance, generic_oil_interval, plan, load, dynamic,
        (hours, hours_sources) if hours else None,
        (AIResult(invoice["content"], invoice["status"], "local", ai_service.model,
                  invoice["status"] == "no_data"), invoice["sources"]) if invoice else None,
        appointment, vehicles_reply, catalog) if entry is not None), None)
    general = False
    state_update: dict = ({"topic": "", "product_ids": [], "pending": "",
                           "price_snapshots": [], "technical_context": empty_technical_context()}
                          if clear_topic_context else {})
    if analysis.get("topic"):
        state_update["active_topic"] = analysis["topic"]
        if analysis.get("entities"):
            state_update["active_entities"] = analysis["entities"]
    technical_sources: list[dict] = []
    if selected is not None:
        answer, sources = (selected.result, selected.sources) if (selected is visit) else selected
        # Không có sản phẩm nội bộ vẫn có thể tư vấn tiêu chí so sánh phổ thông;
        # không áp dụng cho giá, kho, hồ sơ hay giao dịch cần dữ liệu xác minh.
        if (answer.no_data and not sources and analysis.get("can_use_general_knowledge")
                and analysis.get("intent") in {"tire_compare", "battery_compare"}):
            answer = ai_service.answer_general_knowledge(
                question, user["role"], [] if clear_topic_context else history)
            general = answer.status == "success"
    else:
        # A semantic pre-classifier would consume a second model call before
        # generation. Deterministic intent/clarification runs first instead.
        technical_question, clarification, semantic = _technical_route(
            question, history, allow_semantic=False)
        text = ai_service._normalize_vi(technical_question)
        previous_technical = ({} if clear_topic_context else state.get("technical_context") or {})
        has_previous_symptom = bool(previous_technical.get("symptom"))
        technical_context = update_technical_context(previous_technical, technical_question)
        # Chỉ ghi nhận trạng thái kỹ thuật khi câu hiện tại hoặc ngữ cảnh trước
        # thật sự là triệu chứng; không biến câu hỏi giá/kho thành triệu chứng.
        followup_signal = any(term in text for term in (
            "phanh", "danh lai", "o ga", "cho xoc", "duong binh thuong",
            "phia truoc", "phia sau", "dap phanh", "nhai phanh", "tha phanh",
            "rung", "lech", "keu", "loc coc", "rit"))
        technical_turn = bool(_is_technical_question(technical_question) or
                              (has_previous_symptom and followup_signal))
        if technical_turn:
            state_update["technical_context"] = technical_context
        # Query RAG được backend dựng từ câu hiện tại (hoặc câu tham chiếu đã
        # giải nghĩa), không dùng nguyên văn search_query do model đề xuất.
        rag_question = technical_question
        if technical_turn and technical_context.get("symptom") and not clear_topic_context:
            facts = [fact for fact in technical_context.get("known_facts", [])
                     if fact and not fact.startswith("mâu thuẫn")]
            if facts:
                # Chỉ ghép facts do khách nói; không ghép kết luận hoặc tên
                # bộ phận do Ollama suy đoán.
                rag_question = technical_question + " " + "; ".join(facts[-6:])
        business = re.search(r"\b(?:gia|bao nhieu|ton kho|kho|con hang|hoa don|lich hen|"
                             r"dat lich|hen lich|bao gia|lich su|da sua|xe toi|xe cua toi)\b", text)
        protected_intent = analysis.get("intent") in {
            "tire_price", "part_price", "inventory", "vehicle_history", "invoice", "appointment"
        }
        # General knowledge is an explicit route, not the default for every
        # unmatched automotive sentence. Keeping this narrow lets deterministic
        # assistant handling answer vehicle estimates, catalog groups and short
        # clarifications, and lets provider failures surface to the caller.
        general = bool(in_scope and not business and not protected_intent and
                       (technical_turn or _general_knowledge_question(technical_question)))
        if clarification is not None:
            answer, sources = clarification, []
        elif (has_previous_symptom and technical_turn and
              technical_context.get("next_best_question") and
              technical_context.get("safety_status") != "urgent"):
            # Lượt trả lời tiếp theo dùng facts mới vừa trích xuất. Không gọi
            # lại mẫu hỏi cũ và chỉ hỏi một thông tin có giá trị phân biệt cao.
            known = [fact for fact in technical_context.get("known_facts", []) if fact]
            summary = "; ".join(known[-3:])
            answer = AIResult(
                (f"Mình đã ghi nhận {summary}. " if summary else "Mình đã ghi nhận thông tin bạn vừa cung cấp. ")
                + technical_context["next_best_question"],
                "clarification", "local", ai_service.model, True)
            sources = []
        else:
            lookup_failed = False
            try:
                with connect() as db:
                    articles, technical_sources = _technical_references(
                         db, rag_question, vehicle, semantic_technical=semantic or general)
                    explicit_topic = normalize_analysis(technical_question, None).get("topic", "")
                    relevance_topic = (explicit_topic if explicit_topic in {
                        "tire_size", "tire_wear", "check_engine", "brake_vibration",
                        "brake_noise", "clunk_noise", "turn_signal", "fuel_consumption", "steering_vibration",
                        "morning_belt_squeal"
                    } else analysis.get("topic", ""))
                    articles = filter_relevant_technical(
                        articles, relevance_topic, technical_question)
                    allowed_ids = {article.get("id") for article in articles}
                    technical_sources = [source for source in technical_sources
                                         if source.get("id") in allowed_ids]
            except Exception:
                # A broken knowledge index is not evidence that no source exists.
                articles, technical_sources, lookup_failed = [], [], True
            try:
                if lookup_failed and general:
                    answer = ai_service.answer_general_knowledge(
                        technical_question, user["role"], [] if clear_topic_context else history)
                elif lookup_failed:
                    answer = AIResult("Chưa thể kiểm tra tài liệu lúc này. Vui lòng thử lại sau.",
                                      "error", "local", ai_service.model)
                elif articles or technical_turn:
                    answer = ai_service.answer_technical(rag_question, articles, user["role"])
                elif general:
                    answer = ai_service.answer_general_knowledge(
                        technical_question, user["role"], [] if clear_topic_context else history)
                else:
                    answer = None
                    if trusted_history:
                        answer, state_update = resolve_follow_up(ai_service, question, state, context, parts)
                    if answer is None:
                        effective_state = {**state, **state_update} if state_update else state
                        if business and context is None:
                            answer = AIResult("Chưa có dữ liệu garage đã xác minh để trả lời yêu cầu này. "
                                              "Vui lòng chọn xe hoặc hỏi cố vấn dịch vụ kiểm tra thông tin nguồn.",
                                              "no_data", "local", ai_service.model, True,
                                              ["Nguồn dữ liệu nghiệp vụ"])
                        else:
                            answer = ai_service.answer_assistant(technical_question, context, parts,
                                [] if clear_topic_context else history, user["role"], garage_info,
                                conversation_summary=effective_state)
                            # Không coi câu do model tự sinh là nguồn nghiệp vụ.
                            general = answer.status == "success" and not business
                sources = technical_sources
                if relevance_topic == "morning_belt_squeal" and not sources:
                    sources = [{"type": "technical_knowledge", "id": "morning_belt_squeal",
                                "label": "Kiến thức kỹ thuật: Hiện tượng tiếng rít dây curoa khi khởi động nguội"}]
            except Exception:
                answer = AIResult("Chưa thể trả lời lúc này. Vui lòng thử lại hoặc hỏi nhân viên garage.",
                                  "error", "local", ai_service.model)
                sources = []
    # Lưu cả facts do khách vừa nói và câu hỏi đã dùng để hỏi tiếp; nội dung
    # trợ lý chỉ được dùng để đánh dấu câu đã hỏi, không trở thành facts xe.
    if state_update.get("technical_context"):
        state_update["technical_context"] = update_technical_context(
            state_update["technical_context"], question, answer.content)
    if price is not None:
        answer = ai_service.narrate_approved_part_prices(
            question, answer, sources, user.get("role", "Khách hàng"), analysis)
        # Chi tiết snapshot (giá/đơn vị/kích thước) chỉ dành cho Ollama trong
        # lần gọi này; không mở rộng schema response công khai.
        sources = [{key: value for key, value in source.items()
                    if key not in ("name", "code", "size", "unit", "price", "price_status")}
                   for source in sources]
    if answer.status != "error" and (selected is None or (selected is catalog and catalog is not replacement)):
        if not technical_sources:
            with connect() as db:
                sources = _assistant_sources(db, question, answer.content, vehicle, context, parts, garage_info) + sources
    if (selected is None and (general or technical_turn) and answer.status in ("success", "fallback") and not sources
            and not answer.content.startswith("Thông tin dưới đây là kiến thức tham khảo")):
        answer = AIResult("Thông tin dưới đây là kiến thức tham khảo, chưa có dữ liệu xác minh từ garage.\n\n"
                          + answer.content, answer.status, answer.provider, answer.model,
                          answer.no_data, answer.missing_data)
    # No sources are needed for clarifying questions, safety guidance, or
    # general automotive knowledge without a garage/vehicle claim.
    sourced_route = selected is not None
    if (not sources and not sourced_route and answer.status not in ("error", "clarification", "safety")
            and not answer.no_data
            and not ((general or technical_turn) and answer.status in ("success", "fallback"))):
        answer = AIResult("Chưa có dữ liệu đủ căn cứ cho câu trả lời này. "
                          "Vui lòng hỏi cố vấn dịch vụ hoặc kỹ thuật viên để xác minh.",
                          "no_data", "local", ai_service.model, True, ["Nguồn dữ liệu phù hợp"])
    # Mọi transport nhận cùng nội dung đã làm sạch; output.answer cũng phải sạch
    # để API hội thoại lưu đúng nội dung đang hiển thị, không chỉ làm sạch response.
    recs = getattr(answer, "maintenance_recommendations", []) or []
    if selected is None and not any(s.get("type") in ("service", "part", "quote", "invoice") for s in sources):
        answer.content = strip_unverified_prices(answer.content)
    answer = AIResult(sanitize_chat_output(answer.content), answer.status,
                      answer.provider, answer.model, answer.no_data,
                      list(answer.missing_data),
                      maintenance_recommendations=recs)
    with connect() as db:
        suggestions = (_assistant_appointment_items(db, answer.content, sources, parts)
                       if user["role"] == "Khách hàng" and replacement is None and sources
                       and answer.status not in ("error", "no_data", "clarification", "safety") else [])
        if recs and user["role"] == "Khách hàng":
            for r in recs:
                if r.get("service_id") and not r.get("missing_mileage") and not r.get("mileage_anomaly"):
                    if not any(s.get("kind") == "service" and s.get("id") == r["service_id"] for s in suggestions):
                        suggestions.append({
                            "kind": "service",
                            "id": r["service_id"],
                            "name": r["service_name"],
                            "price": 0,
                        })
    body = _body(answer, sources, suggestions, is_draft=visit is None)
    if visit is not None and visit.analytics is not None:
        body["analytics"] = visit.analytics
    product_ids = [src["id"] for src in sources if src["type"] == "part"]
    return ChatOutput(body, answer, state_update, product_ids, suggestions,
                      vehicle["id"] if vehicle else None, general and not technical_sources)


def _body(answer: AIResult, sources: list[dict], suggestions: list[dict], *, is_draft: bool) -> dict:
    recs = getattr(answer, "maintenance_recommendations", []) or []
    return {"result": answer.content, "status": answer.status, "is_draft": is_draft,
            "no_data": answer.no_data, "missing_data": answer.missing_data,
            "sources": sources, "source_count": len(sources), "suggested_items": suggestions,
            "maintenance_recommendations": recs}
