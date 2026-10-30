"""Giải thích thông số lốp theo topic hiện tại, tách khỏi tra giá/tồn kho."""

from __future__ import annotations

from .ai_service import ai_service
from .chat_intent import extract_tire_size
from .technical_knowledge import filter_relevant_technical, search_technical


def is_tire_size_question(question: str, analysis: dict | None = None) -> bool:
    if not extract_tire_size(question):
        return False
    text = ai_service._normalize_vi(question)
    if any(term in text for term in ("gia", "bao nhieu tien", "bao gia", "chi phi")):
        return False
    return bool((analysis or {}).get("topic") == "tire_size" or
                any(term in text for term in ("y nghia", "thong so", "la gi", "nghia la")))


def referenced_tire_size(question: str, state: dict, history: list[dict]) -> str | None:
    """Giải tham chiếu ngôn ngữ; kích thước kế thừa vẫn chỉ là lời người dùng."""
    text = ai_service._normalize_vi(question)
    if not (any(term in text for term in ("loai nay", "loai do", "no", "kich thuoc nay"))
            and any(term in text for term in ("lap vua", "phu hop", "tuong thich"))):
        return None
    current = extract_tire_size(question)
    if current:
        return current["normalized"]
    entity = (state.get("active_entities") or {}).get("tire_size")
    if isinstance(entity, str) and extract_tire_size(entity):
        return extract_tire_size(entity)["normalized"]
    for turn in reversed(history):
        if turn.get("role") == "user":
            found = extract_tire_size(str(turn.get("text") or ""))
            if found:
                return found["normalized"]
    return None


def tire_fitment_reference_answer(size: str, vehicle_context: dict | None):
    """Không biến kích thước được nhắc lại thành kết luận tương thích."""
    from .ai_service import AIResult
    if not vehicle_context:
        content = (f"Bạn đang hỏi kích thước {size}. Chưa thể xác nhận lắp vừa vì chưa có hồ sơ xe "
                   "đã được backend kiểm tra; vui lòng chọn xe hoặc cung cấp thông số nhà sản xuất.")
    else:
        specified = str((vehicle_context.get("technical_specs") or {}).get("tire_size") or "").strip()
        match_note = (f" Hồ sơ kỹ thuật hiện ghi kích thước {specified}, nhưng" if specified else "")
        content = (f"Chưa thể khẳng định {size} lắp phù hợp với xe này.{match_note} vẫn cần đối chiếu "
                   "thông số nhà sản xuất, tải trọng, chỉ số tốc độ, mâm và khoảng hở thực tế.")
    return AIResult(content, "clarification", "local", ai_service.model, True,
                    ["Thông số tương thích đã xác minh"]), []


def _relevant(article: dict, size: dict) -> bool:
    text = ai_service._normalize_vi(" ".join(
        str(article.get(key) or "") for key in ("title", "symptoms", "content")))
    return ("lop" in text and any(term in text for term in (
        "thong so", "kich thuoc", "be rong", "ti le", "vanh", "radial")))


def prepare_tire_size_answer(db, question: str, analysis: dict | None, vehicle=None):
    size = extract_tire_size(question)
    if not size or not is_tire_size_question(question, analysis):
        return None
    query = (f"giải thích thông số lốp {size['normalized']}, bề rộng, tỷ lệ chiều cao, "
             "cấu trúc radial và đường kính vành")
    articles = filter_relevant_technical(search_technical(
        db, query, limit=4, vehicle=dict(vehicle) if vehicle else None), "tire_size", question)
    articles = [article for article in articles if _relevant(article, size)][:3]
    context = {"tire_size": size["normalized"], "tire_width_mm": size["tire_width_mm"],
               "aspect_ratio_percent": size["aspect_ratio_percent"],
               "construction": size["construction"], "rim_diameter_inch": size["rim_diameter_inch"],
               "sidewall_height_mm": size["sidewall_height_mm"],
               "fitment_verified": False}
    sources = [{"type": "technical_article", "id": article["id"],
                "label": f"Kiến thức kỹ thuật: {article['title']} · {article['source_name']}",
                "date": str(article.get("updated_at") or "")[:10]}
               for article in articles]
    return context, articles, sources


def answer_tire_size_question(db, question: str, analysis: dict | None, vehicle=None):
    """Wrapper tương thích cho caller cũ; pipeline chung dùng bước prepare trước."""
    prepared = prepare_tire_size_answer(db, question, analysis, vehicle)
    if prepared is None:
        return None
    context, articles, sources = prepared
    return ai_service.narrate_tire_size(question, context, articles), sources
