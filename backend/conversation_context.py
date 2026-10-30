"""Ngữ cảnh hội thoại giới hạn kích thước; DB vẫn lưu nguyên bản toàn bộ tin nhắn."""

from __future__ import annotations

import json
import re
from typing import Any

from .ai_service import AIResult, AIService


MAX_HISTORY_CHARS = 6500  # xấp xỉ giới hạn token, không dùng lịch sử vô hạn cho provider


def message_meta(row: dict) -> dict:
    try:
        return json.loads(row.get("metadata") or "{}")
    except (ValueError, TypeError):
        return {}


def context_window(messages: list[dict]) -> list[dict]:
    chosen: list[dict] = []
    used = 0
    for row in reversed(messages):
        if row["status"] != "completed":
            continue
        text = str(row["content"])[:1200]
        if chosen and used + len(text) > MAX_HISTORY_CHARS:
            break
        chosen.append({"role": row["role"], "text": text})
        used += len(text)
    return list(reversed(chosen))


def summarize(messages: list[dict]) -> dict:
    """Chỉ tóm tắt ngữ cảnh cần dùng, không biến lời khách thành dữ liệu xe xác minh."""
    state: dict[str, Any] = {"topic": "", "product_ids": [], "pending": "",
                             "reported": {}, "decisions": [], "price_snapshots": [],
                             "technical_context": empty_technical_context()}
    for row in messages:
        if row["status"] != "completed":
            continue
        if row["role"] == "assistant":
            context = message_meta(row).get("context", {})
            state.update({key: value for key, value in context.items()
                          if key in ("topic", "product_ids", "pending", "price_snapshots",
                                     "active_topic", "active_entities")})
            if context.get("technical_context"):
                state["technical_context"] = context["technical_context"]
        else:
            text = AIService._normalize_vi(row["content"])
            state["technical_context"] = update_technical_context(
                state.get("technical_context"), row["content"])
            if any(term in text for term in ("toi chon", "minh chon", "chot loai", "lay loai")):
                state["decisions"].append(str(row["content"])[:180])
            # Không nhận năm ở cuối mã phụ tùng như SP-SEL-2022 là đời xe khách.
            year = re.search(r"(?<![\w-])((?:19|20)\d{2})\b", text)
            engine = re.search(r"(?:dong co|may)\s+((?:\d{1,2}\.\d|[a-z]\w{2,10})(?:\s*turbo)?)", text)
            vin = re.search(r"\bvin\s*[:#-]?\s*([a-hj-npr-z0-9]{17})\b", text)
            if state["pending"] == "compatibility":
                # Câu trả lời rút gọn cho câu hỏi làm rõ: "2022", "1.4 Turbo", "G4FG", VIN.
                bare_engine = re.fullmatch(r"(\d{1,2}\.\d\s*(?:turbo)?|[a-z]\w{2,10})[.!\s]*", text)
                bare_vin = re.fullmatch(r"([a-hj-npr-z0-9]{17})[.!\s]*", text)
                if not engine and bare_engine and any(char.isdigit() for char in bare_engine[1]):
                    state["reported"]["engine"] = bare_engine[1].strip()
                if not vin and bare_vin:
                    state["reported"]["vin"] = bare_vin[1].upper()
            if year:
                state["reported"]["year"] = int(year[1])
            if engine:
                state["reported"]["engine"] = engine[1].strip()
            if vin:
                state["reported"]["vin"] = vin[1].upper()
    state["product_ids"] = list(dict.fromkeys(state["product_ids"]))[:8]
    state["decisions"] = state["decisions"][-6:]
    return state


def empty_technical_context() -> dict[str, Any]:
    return {"symptom": "", "trigger_conditions": [], "vehicle_location": "",
            "frequency": "", "severity": "", "related_symptoms": [],
            "clarifications_asked": [], "known_facts": [], "unknown_facts": [],
            "safety_status": "unknown", "next_best_question": ""}


def _add_unique(values: list[str], value: str) -> list[str]:
    return list(dict.fromkeys([*values, value]))


def update_technical_context(previous: dict | None, text: str,
                             assistant_text: str = "") -> dict[str, Any]:
    """Trích xuất facts hội thoại, không biến suy đoán của AI thành dữ kiện xe."""
    context = {**empty_technical_context(), **(previous or {})}
    for key in ("trigger_conditions", "related_symptoms", "clarifications_asked",
                "known_facts", "unknown_facts"):
        context[key] = list(context.get(key) or [])
    normalized = AIService._normalize_vi(text)

    symptom_aliases = (("đèn Check Engine", ("check engine", "den dong co", "den ca vang")),
                       ("lọc cọc", ("loc coc", "coc coc")),
                       ("tiếng rít", ("rit", "ken ket", "nghien")),
                       ("rung/lắc", ("rung", "lac")),
                       ("lệch lái", ("lech lai", "keo ve", "nhao lai")))
    detected = next((label for label, aliases in symptom_aliases
                     if any(alias in normalized for alias in aliases)), "")
    # Một triệu chứng được nêu rõ và khác triệu chứng trước là chủ đề kỹ thuật
    # mới. Không mang vị trí/điều kiện của tiếng kêu sang đèn cảnh báo động cơ.
    if detected and context.get("symptom") and context["symptom"] != detected:
        context = empty_technical_context()
    if detected:
        context["symptom"] = detected

    triggers = (("khi phanh", ("phanh", "dap phanh", "danh phanh")),
                ("khi đánh lái", ("danh lai", "quay vo lang")),
                ("khi qua chỗ xóc", ("o ga", "cho xoc", "duong xoc")),
                ("khi đi đường bình thường", ("duong binh thuong", "mat duong bang", "di chuyen")))
    for label, aliases in triggers:
        if any(alias in normalized for alias in aliases):
            context["trigger_conditions"] = _add_unique(context["trigger_conditions"], label)
            context["known_facts"] = _add_unique(context["known_facts"], label)

    location = ""
    if re.search(r"\b(phia sau|sau xe|banh sau)\b", normalized):
        location = "phía sau"
    elif re.search(r"\b(phia truoc|truoc xe|banh truoc)\b", normalized):
        location = "phía trước"
    if location:
        old = context.get("vehicle_location") or ""
        if old and old != location and old != "chưa rõ":
            context["vehicle_location"] = "chưa rõ"
            context["known_facts"] = _add_unique(context["known_facts"],
                                                   f"mâu thuẫn vị trí: {old}/{location}")
            context["unknown_facts"] = _add_unique(context["unknown_facts"],
                                                    "xác nhận lại vị trí tiếng kêu")
        else:
            context["vehicle_location"] = location
            context["known_facts"] = _add_unique(context["known_facts"], location)

    for label, aliases in (("thường xuyên", ("luon", "moi khi")),
                           ("thỉnh thoảng", ("thinh thoang", "luc co luc khong"))):
        if any(alias in normalized for alias in aliases):
            context["frequency"] = label
    if any(term in normalized for term in ("mat phanh", "khong an phanh", "khong kiem soat",
                                          "vo lang long", "rung manh")):
        context["severity"] = "nguy cơ mất an toàn"
        context["safety_status"] = "urgent"
    elif context["safety_status"] == "unknown":
        context["safety_status"] = "chưa ghi nhận dấu hiệu khẩn cấp"

    if assistant_text:
        asked = []
        if any(term in AIService._normalize_vi(assistant_text) for term in ("phanh", "danh lai", "o ga", "duong binh thuong")):
            asked.append("điều kiện xuất hiện")
        if any(term in AIService._normalize_vi(assistant_text) for term in ("phia truoc", "phia sau")):
            asked.append("vị trí")
        context["clarifications_asked"] = list(dict.fromkeys([*context["clarifications_asked"], *asked]))

    if context["symptom"] == "đèn Check Engine":
        # Đây là câu hỏi độc lập đủ rõ để RAG/Ollama trả lời; bộ hỏi tiếp dành
        # cho tiếng kêu không được chặn câu trả lời hiện tại.
        next_question = ""
    elif context["vehicle_location"] == "chưa rõ":
        next_question = "Bạn xác nhận giúp tiếng kêu phát ra phía trước hay phía sau xe?"
    elif not context["vehicle_location"]:
        next_question = "Bạn nghe tiếng kêu rõ hơn ở phía trước hay phía sau xe?"
    elif not context["trigger_conditions"]:
        next_question = "Tiếng kêu xuất hiện rõ hơn khi phanh, đánh lái, qua chỗ xóc hay cả khi đi đường bình thường?"
    elif any("khi phanh" == item for item in context["trigger_conditions"]) and not any(
            term in normalized for term in ("dap phanh", "nhai phanh", "tha phanh")):
        next_question = "Tiếng kêu rõ hơn lúc đạp phanh, lúc nhả phanh hay vẫn kêu khi không phanh?"
    else:
        next_question = "Bạn có thấy rung vô-lăng, xe lệch hướng hoặc tiếng kêu tăng dần không?"
    context["next_best_question"] = next_question
    return context


def is_reference(question: str) -> bool:
    text = AIService._normalize_vi(question)
    return any(word in text for word in (
        "cai nao", "loai nao", "cai do", "cai thu", "loai thu", "cai dau", "loai dau",
        "phu hop", "tuong thich", "the con xe toi", "gia bao nhieu", "bao nhieu tien",
    ))


def conversation_topic(value: str) -> str:
    """Chủ đề hẹp dùng để không mang mã sản phẩm sang câu hỏi khác."""
    text = AIService._normalize_vi(value)
    topic_terms = (
        ("glass", ("kinh xe", "kinh lai", "kinh chan gio", "kinh oto")),
        ("tire", ("lop", "vo xe", "banh xe", "mam xe")),
        ("brake", ("phanh", "abs", "ma phanh", "dia phanh")),
        ("battery", ("ac quy", "acquy", "binh ac quy", "binh dien")),
        ("engine", ("bugi", "dong co", "may xe", "cuon danh lua")),
        ("oil", ("dau dong co", "dau nhot", "loc dau", "dau hop so", "thay dau")),
        ("invoice", ("hoa don", "cong no", "da thanh toan")),
        ("appointment", ("lich hen", "dat lich", "gio nhan xe")),
    )
    return next((topic for topic, terms in topic_terms if any(term in text for term in terms)), "")


def _product_topic(part: dict) -> str:
    return conversation_topic(" ".join(str(part.get(key) or "")
                                        for key in ("name", "category", "compatible")))


def resolve_follow_up(
    service: AIService, question: str, state: dict, vehicle: dict | None,
    parts: list[dict],
) -> tuple[AIResult | None, dict]:
    """Chỉ dùng ID từ metadata server đã lưu, đọc lại giá/tương thích từ DB mỗi lượt."""
    text = service._normalize_vi(question)
    product_ids = state.get("product_ids") or []
    selected_entries = [next((p for p in parts if p.get("id") == pid), None) for pid in product_ids]
    selected = [p for p in selected_entries if p is not None]
    pending = state.get("pending", "")
    incoming_topic = conversation_topic(question)
    current_topic = next((_product_topic(part) for part in selected if _product_topic(part)), "")
    current_topic = current_topic or (state.get("topic") if state.get("topic") not in ("", "parts") else "")
    # Một chủ đề mới luôn làm mất liên kết sản phẩm cũ. Câu hỏi tham chiếu
    # không có chủ đề mới ("giá bao nhiêu?", "loại nào?") vẫn giữ ngữ cảnh.
    new_topic = bool(incoming_topic and current_topic and incoming_topic != current_topic
                     and not is_reference(question))
    if new_topic:
        return None, {"topic": "", "product_ids": [], "pending": "", "price_snapshots": []}
    if product_ids and not selected and is_reference(question):
        return (AIResult("Các mã phụ tùng vừa trao đổi không còn trong danh mục đang hoạt động. "
                         "Bạn muốn tra lại bugi hiện có không?", "clarification", "local", service.model, True),
                {"product_ids": [], "pending": "", "price_snapshots": []})
    if not selected or not (is_reference(question) or pending == "compatibility" or
                            re.search(r"\b(?:19|20)\d{2}\b", text) or "dong co" in text):
        return None, {}

    second = any(term in text for term in ("thu hai", "so 2", "thu 2"))
    first = any(term in text for term in ("thu nhat", "so 1", "thu 1"))
    if second or first:
        index = 1 if second else 0
        if index >= len(selected_entries) or selected_entries[index] is None:
            return AIResult("Lựa chọn này không còn trong danh mục đang hoạt động. "
                            "Bạn muốn tra một mã phụ tùng khác không?",
                            "clarification", "local", service.model, True), {}
        selected = [selected_entries[index]]
    if any(term in text for term in ("gia", "bao nhieu")) and not any(
            term in text for term in ("phu hop", "tuong thich")):
        if any(not p.get("price_approved") for p in selected):
            return AIResult("Giá của mã phụ tùng đang hỏi chưa được duyệt hoặc đã thay đổi. "
                            "Vui lòng để cố vấn dịch vụ xác minh bảng giá hiện hành.",
                            "no_data", "local", service.model, True, ["Giá đã duyệt"]), {}
        details = "; ".join(f"{p['name']} ({p['code']}): {int(p['sell_price']):,} ₫/{p['unit']}".replace(",", ".")
                            for p in selected[:3])
        return AIResult("Theo giá bán hiện tại: " + details + ".", "fallback", "local", service.model), {}

    if not (pending == "compatibility" or any(term in text for term in
            ("phu hop", "tuong thich", "cai nao", "loai nao", "xe toi", "dong co"))):
        return None, {}
    info = (vehicle or {}).get("vehicle") or {}
    reported = state.get("reported") or {}
    names = ", ".join(f"{p['name']} ({p['code']})" for p in selected[:3])
    if not info.get("make") or not info.get("model"):
        return AIResult("Bạn muốn đối chiếu " + names + " cho xe hãng, dòng nào?",
                        "clarification", "local", service.model, True), {"pending": "compatibility"}
    make = service._normalize_vi(info["make"])
    model = service._normalize_vi(info["model"])
    candidates = [p for p in selected if (
        any(service._normalize_vi(rule.get("make") or "") == make and
            service._normalize_vi(rule.get("model") or "") == model
            for rule in p.get("fitments") or []) or
        any(make in segment and model in segment for segment in
            service._normalize_vi(p.get("compatible") or "").split(",")))]
    if not candidates:
        return AIResult(f"Các mã {names} chưa được danh mục ghi cho xe "
                        f"{info['make']} {info['model']} của bạn. Bạn muốn tìm bugi đúng xe này không?",
                        "clarification", "local", service.model, True), {"pending": ""}
    year = info.get("year") or reported.get("year")
    if not year:
        return AIResult(f"Bạn cho biết {info['make']} {info['model']} đời nào để đối chiếu {names}?",
                        "clarification", "local", service.model, True, ["Năm sản xuất"]), {"pending": "compatibility"}
    engine = info.get("engine_code") or reported.get("engine")
    if any("bugi" in service._normalize_vi(p["name"]) for p in selected) and not engine:
        return AIResult(f"{info['make']} {info['model']} đời {year}: bạn biết phiên bản động cơ hoặc mã động cơ không? "
                        "Danh mục chưa đủ căn cứ chọn bugi chỉ theo đời xe.",
                        "clarification", "local", service.model, True, ["Mã động cơ"]), {"pending": "compatibility"}

    verified: list[dict] = []
    for part in selected:
        # Chỉ khẳng định nếu có quy tắc cấu hình cụ thể và đầy đủ, không dựa trên mô tả cũ.
        candidate = {**info, "year": year, "engine_code": engine or info.get("engine_code")}
        if any(service._part_fit_level({**part, "fitments": [rule]}, candidate) == 3 and
               ("bugi" not in service._normalize_vi(part["name"]) or rule.get("engine_code"))
               for rule in part.get("fitments") or []):
            verified.append(part)
    if verified:
        details = "; ".join((f"{p['name']} ({p['code']}): {int(p['sell_price']):,} ₫/{p['unit']}".replace(",", ".")
                             if p.get("price_approved") else
                             f"{p['name']} ({p['code']}): giá chưa được duyệt")
                            for p in verified[:3])
        caveat = ("Thông số xe bạn cung cấp cần kỹ thuật viên đối chiếu với VIN trước khi lắp."
                  if not info.get("engine_code") or not info.get("year") else
                  "Vẫn cần đối chiếu VIN/mã phụ tùng trước khi lắp.")
        return AIResult("Quy tắc danh mục ghi phù hợp: " + details + ". " + caveat,
                        "fallback", "local", service.model), {"pending": ""}
    return (AIResult(f"Chưa thể xác nhận {names} phù hợp {info['make']} {info['model']} đời {year} "
                     f"với động cơ {engine or 'chưa rõ'}: danh mục chưa có quy tắc đủ chi tiết cho cấu hình này. "
                     "Garage cần đối chiếu mã OEM theo VIN; không nên chọn chỉ theo tên xe.",
                     "clarification", "local", service.model, True, ["Quy tắc tương thích theo động cơ"]),
            {"pending": "compatibility"})
