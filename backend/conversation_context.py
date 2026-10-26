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
                             "reported": {}, "decisions": [], "price_snapshots": []}
    for row in messages:
        if row["status"] != "completed":
            continue
        if row["role"] == "assistant":
            state.update({key: value for key, value in message_meta(row).get("context", {}).items()
                          if key in ("topic", "product_ids", "pending", "price_snapshots")})
        else:
            text = AIService._normalize_vi(row["content"])
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


def is_reference(question: str) -> bool:
    text = AIService._normalize_vi(question)
    return any(word in text for word in (
        "cai nao", "loai nao", "cai do", "cai thu", "loai thu", "cai dau", "loai dau",
        "phu hop", "tuong thich", "the con xe toi", "gia bao nhieu", "bao nhieu tien",
    ))


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
    new_topic = not is_reference(question) and any(term in text for term in (
        "thay dau", "loc dau", "dia chi", "gio mo cua", "lich hen", "hoa don",
        "mat phanh", "vo lang", "ngap nuoc", "bao hanh",
    ))
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
        details = "; ".join(f"{p['name']} ({p['code']}): {int(p['sell_price']):,} ₫/{p['unit']}".replace(",", ".")
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
