"""API AI: chỉ nhận định danh, tự đọc dữ liệu nghiệp vụ và gọi AIService tập trung."""

import hashlib
import json
import re
import time
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request

from ...ai_service import AIResult, ai_service
from ...appointment_chat import pending_appointments_reply
from ...appointment_load import answer_appointment_load, is_load_question
from ...core.access import ensure_record_access
from ...core.audit import write_audit
from ...core.db import connect, normalize_plate, transaction
from ...core.deps import require_permission
from ...core.errors import BadRequestError, NotFoundError
from ...domain import backfill_repair_history
from ...dynamic_query import answer_dynamic_query
from ...customer_visit_analytics import answer_customer_visit_question
from ...knowledge import search_knowledge
from ...schedule import WEEKDAY_LABELS, working_days, working_window
from ...technical_knowledge import search_technical
from ...repair_knowledge import search_repair_cases
from ...repair_history_analysis import build_history_analysis, enrich_history_context, render_history_summary
from ...timeutil import VN_TZ
from ...invoice_query import answer_invoice_question
from ...inventory_query import (answer_inventory_question, answer_part_price_question,
                                is_inventory_question)
from ...maintenance_interval import is_maintenance_interval_question
from ...permissions import has_permission
from ...vehicle_chat import customer_vehicles_reply
from ...schemas.ai import (AIRequest, AIResultOut, AssistantChatIn, InvoiceQueryIn,
                           ServiceExplanationIn, ServiceFollowUpIn, VehicleHistorySummaryIn)

router = APIRouter(prefix="/ai", tags=["AI Services"])

_INDICATOR = r"\b(?:xi\s*nhan(?:h)?|si\s*nhan|den bao re)\b"


def _garage_hours_reply(question: str) -> tuple[AIResult | None, list[dict]]:
    """Đọc lịch làm việc từ cấu hình backend; không để AI tự đoán giờ mở cửa."""
    text = ai_service._normalize_vi(question)
    if not any(term in text for term in (
        "gio lam viec", "thoi gian lam viec", "gio mo cua", "gio dong cua",
        "may gio mo", "may gio dong", "mo cua may gio", "dong cua may gio",
        "mo cua luc", "dong cua luc",
        "garage lam tu may gio", "gara lam tu may gio", "garage co lam viec",
        "gara co lam viec", "hom nay co mo cua", "hom nay garage co lam",
    )):
        return None, []
    days = sorted(working_days())
    window = working_window()
    labels = ", ".join(WEEKDAY_LABELS[day] for day in days)
    answer = (f"Garage làm việc từ {window['start_text']} đến {window['end_text']}, "
              f"vào {labels} (giờ Việt Nam).")
    if "hom nay" in text:
        now = datetime.now(VN_TZ)
        minute = now.hour * 60 + now.minute
        if now.isoweekday() not in days:
            answer += f" Hôm nay là {WEEKDAY_LABELS[now.isoweekday()]}, garage không làm việc theo lịch cấu hình."
        elif window["start"] <= minute < window["end"]:
            answer += f" Hiện tại đang trong giờ làm việc; garage đóng cửa lúc {window['end_text']}."
        elif minute < window["start"]:
            answer += f" Hôm nay garage mở cửa lúc {window['start_text']}."
        else:
            answer += " Giờ làm việc hôm nay đã kết thúc."
    source = {"type": "working_hours", "id": None,
              "label": "Cấu hình ngày và giờ làm việc của garage"}
    return AIResult(answer, "fallback", "local", ai_service.model), [source]


@router.post("/invoices/query", response_model=AIResultOut, response_model_exclude_none=True)
def invoice_ai_query(
    item: InvoiceQueryIn,
    request: Request,
    user: dict = Depends(require_permission("dashboard")),
) -> dict:
    """Tra cứu chỉ đọc; backend tự lấy danh tính, quyền, phạm vi và tính số tiền."""
    with connect() as db, transaction(db):
        answer = answer_invoice_question(db, user, item.question)
        if answer is None:
            raise BadRequestError("Câu hỏi không thuộc phạm vi hóa đơn hoặc công nợ")
        write_audit(db, user, "ai.invoice.query", "invoices", None,
                    {"intent": answer["intent"], "status": answer["status"],
                     "result_count": answer.get("count", 0)},
                    request.client.host if request.client else None)
    return {"result": answer["content"], "status": answer["status"], "is_draft": False,
            "no_data": answer["status"] == "no_data", "sources": answer["sources"],
            "source_count": len(answer["sources"]), "missing_data": []}


def _catalog_service_reply(db, question: str, history: list[dict] | None = None) -> tuple[AIResult | None, list[dict]]:
    """Tra giá/thời lượng dịch vụ công khai tại thời điểm hỏi; không dùng giá do model tạo."""
    text = ai_service._normalize_vi(question)
    if any(term in text for term in ("ngap nuoc", "thuy kich", "chay xe", "phanh hong")):
        return None, []  # hướng dẫn an toàn có ưu tiên cao hơn bảng giá
    if is_maintenance_interval_question(question):
        return None, []  # hỏi mốc bảo dưỡng là tác vụ khác
    names: list[str] = []
    if "thay dau hop so" in text:
        names.append("Thay dầu hộp số")
    elif "thay dau" in text or "thay nhot" in text:
        names.append("Thay dầu động cơ")
    for phrase, name in (
        ("ve sinh xe", "Vệ sinh xe cơ bản"), ("rua xe", "Rửa xe ngoại thất"),
        ("ve sinh noi that", "Vệ sinh nội thất"), ("don noi that", "Vệ sinh nội thất"),
        ("ve sinh khoang may", "Vệ sinh khoang máy"), ("ve sinh dieu hoa", "Vệ sinh điều hòa"),
        ("khu mui", "Khử mùi nội thất"),
    ):
        if phrase in text and name not in names:
            names.append(name)
    # Hỗ trợ hỏi tên dịch vụ khác trong danh mục mà không liệt kê giá phụ tùng.
    services = [dict(row) for row in db.execute(
        "SELECT id,name,price,duration_min,description FROM services WHERE active=1 ORDER BY name"
    ).fetchall()]
    for service in services:
        normalized_name = ai_service._normalize_vi(service["name"])
        if normalized_name in text and service["name"] not in names:
            names.append(service["name"])
    if not names and any(term in text for term in ("gia ve sinh", "ve sinh bao lau", "thoi gian ve sinh")):
        return AIResult("Bạn muốn vệ sinh xe cơ bản, nội thất, ngoại thất hay điều hòa? "
                        "Mỗi hạng mục có giá và thời lượng khác nhau trong danh mục garage.",
                        "clarification", "local", ai_service.model, True), []
    if not names and any(term in text for term in ("vay bao lau", "vay gia bao nhieu", "mat bao lau")):
        # Lịch sử chỉ dùng để hiểu hạng mục đang hỏi nối tiếp, không dùng làm nguồn giá.
        for turn in reversed(history or []):
            if turn.get("role") == "user":
                previous = ai_service._normalize_vi(str(turn.get("text") or ""))
                if previous != text and any(term in previous for term in ("thay dau", "ve sinh xe", "rua xe")):
                    return _catalog_service_reply(db, str(turn["text"]))

    # Xử lý yêu cầu hỏi về dịch vụ kiểm tra hệ thống điện hoặc hỏi sự tồn tại của dịch vụ
    is_service_inquiry = any(term in text for term in (
        "co dich vu nay khong", "garage co dich vu", "co dich vu", "co goi dich vu",
        "co lam dich vu", "co nhan lam", "co goi kiem tra", "co nhan kiem tra",
        "co kiem tra khong", "co nhan khong"
    )) or (
        ("co" in text or "muon" in text) and "dich vu" in text and any(term in text for term in ("khong", "chua"))
    )

    is_electrical_check = ("he thong dien" in text or "dien xe" in text or ("dien" in text and any(term in text for term in ("kiem tra", "chuan doan"))))

    if not names and is_electrical_check and (is_service_inquiry or any(term in text for term in ("co khong", "gia", "chi phi", "bao nhieu"))):
        related_ids = (535, 536, 538, 6)
        by_id = {service["id"]: service for service in services}
        rel_services = [by_id[sid] for sid in related_ids if sid in by_id]
        lines = [
            f"- {s['name']}: {int(s['price']):,} ₫ (thời lượng khoảng {s['duration_min']} phút). {s['description']}".replace(",", ".")
            for s in rel_services
        ]
        content = (
            "Danh mục dịch vụ hiện tại của ThreeH Workshop chưa có gói niêm yết riêng mang tên “Kiểm tra toàn bộ hệ thống điện”. "
            "Bạn vui lòng liên hệ cố vấn dịch vụ để được kỹ thuật viên tiếp nhận, đo kiểm thực tế và báo giá chi tiết theo yêu cầu xe.\n\n"
            "Hiện tại garage có các hạng mục dịch vụ kiểm tra, chẩn đoán điện và hệ thống liên quan đã được niêm yết bạn có thể tham khảo:\n"
            + "\n".join(lines) + "\n\n"
            "Ước tính trên là giá dịch vụ tham khảo theo danh mục đang hoạt động của garage, chưa bao gồm vật tư phụ tùng thay thế nếu phát sinh."
        )
        sources = [{"type": "service", "id": s["id"], "label": f"Danh mục dịch vụ: {s['name']}"} for s in rel_services]
        return AIResult(content, "fallback", "local", ai_service.model), sources

    if not names and is_service_inquiry:
        return AIResult(
            "Danh mục dịch vụ niêm yết hiện tại của garage chưa có gói dịch vụ tương ứng với yêu cầu này. "
            "Vui lòng liên hệ trực tiếp cố vấn dịch vụ hoặc nhân viên xưởng để được kiểm tra khả năng tiếp nhận và báo giá theo tình trạng xe.",
            "no_data", "local", ai_service.model, True, ["Danh mục dịch vụ"]), []

    if not names:
        return None, []
    by_name = {service["name"]: service for service in services}
    found = [by_name[name] for name in dict.fromkeys(names) if name in by_name]
    if not found:
        return AIResult("Danh mục dịch vụ hiện chưa có hạng mục này. Vui lòng hỏi cố vấn dịch vụ để kiểm tra.",
                        "no_data", "local", ai_service.model, True), []
    lines = [f"- {service['name']}: giá dịch vụ tham khảo {int(service['price']):,} ₫; ".replace(",", ".")
             + f"thời lượng thao tác khoảng {service['duration_min']} phút. {service['description']}"
             for service in found]
    total_minutes = sum(int(service["duration_min"]) for service in found)
    total_price = sum(int(service["price"]) for service in found)
    summary = (f"\nCộng {len(found)} dịch vụ: khoảng {total_minutes} phút thao tác và "
               f"{total_price:,} ₫ tiền dịch vụ tham khảo.".replace(",", ".") if len(found) > 1 else "")
    appointment = (" Nếu bạn muốn đến buổi sáng, hãy cho biết ngày và giờ cụ thể để garage "
                   "kiểm tra lịch trống trước khi xác nhận hẹn." if any(term in text for term in
                   ("buoi sang", "sang mai", "sang nay", "muon den", "dat lich", "ranh")) else "")
    answer = ("Theo danh mục dịch vụ đang hoạt động của garage:\n" + "\n".join(lines) + summary +
              "\nƯớc tính chưa gồm thời gian chờ tiếp nhận, vật tư/lọc dầu hoặc phát sinh khi kiểm tra xe. "
              "Giá chính thức và giờ nhận xe cần được nhân viên xác nhận trên báo giá/lịch hẹn." + appointment)
    sources = [{"type": "service", "id": service["id"], "label": f"Danh mục dịch vụ: {service['name']}"}
               for service in found]
    return AIResult(answer, "fallback", "local", ai_service.model), sources


def _is_technical_question(question: str) -> bool:
    """Nhận diện câu hỏi kiến thức xe, kể cả câu hỏi rộng chưa nêu triệu chứng."""
    text = ai_service._normalize_vi(question)
    if re.search(_INDICATOR, text) and any(term in text for term in (
            "chap chon", "khong on dinh", "khong sang", "luc bat", "nguyen nhan", "kiem tra")):
        return True
    if re.search(r"\blop\b", text) and re.search(r"\b(an lech|mon lech|mon khong deu)\b", text):
        return True
    symptom_phrases = ("loc coc", "coc coc", "ken ket", "keu rit", "rit rit", "tieng rit",
                       "tieng nghien", "mat bam", "bam duong", "truot toc do cao",
                       "bi truot", "truot banh", "truot xe",
                       "rung", "giat", "lech lai", "nhao lai", "keo ve mot ben",
                        "khong lanh", "khong mat", "kho no", "khong no", "kho de",
                        "de khong", "de may cham", "tach tach", "check engine", "den ca vang",
                        "den dong co", "qua nhiet", "nong may", "nhiet do dong co",
                        "hao nhien lieu", "ton nhien lieu", "hao xang", "ton xang", "an xang",
                        "tieu thu nhien lieu", "tieu hao nhien lieu", "ton dau", "hao dau")
    if any(phrase in text for phrase in symptom_phrases):
        return True
    if re.search(r"\b(lop|phanh|dong co|may|vo lang)\b", text) and any(
            term in text for term in ("mon", "keu", "rit", "truot", "mat bam", "bam duong",
                                     "toc do cao", "nong", "rung", "kiem tra", "nguyen nhan")):
        return True
    if any(term in text for term in ("troi mua", "di mua", "sau mua")) and any(
            term in text for term in ("lai xe", "xe", "kiem tra", "an toan")):
        return True
    # Câu hỏi rộng cần có ngữ cảnh xe VÀ chủ đề kỹ thuật; không bắt 'mua' đơn
    # lẻ vì nó cũng có thể là 'mua phụ tùng'.
    vehicle = re.search(r"\b(xe|oto|o to|dong co|may|phanh|lop|gat mua|ac quy|hop so|dau hop so)\b", text)
    topic = any(phrase in text for phrase in (
        "troi mua", "mua lon", "mua bao", "mua ngap", "mua mua", "sau mua",
        "di mua", "am uot", "ngap nuoc", "thoi tiet", "nguyen nhan",
        "thuong gap", "van de gi", "can kiem tra", "can luu y",
    ))
    return bool(vehicle and topic)


def _technical_route(question: str, history: list[dict] | None = None,
                     *, allow_semantic: bool = True) -> tuple[str, AIResult | None, bool]:
    """Làm rõ ý định trước khi đòi nguồn; lịch sử chat chỉ để hiểu câu trả lời nối tiếp."""
    text = ai_service._normalize_vi(question).strip(" ?.!\n")
    previous = None
    turns = history or []
    indicator = _INDICATOR
    # Chỉ liên hệ câu nói rút gọn với xi nhan khi lượt trước thật sự nói về nó.
    indicator_context = False
    if len(turns) >= 2 and turns[-1].get("role") == "assistant":
        indicator_context = bool(any(re.search(indicator, ai_service._normalize_vi(str(t.get("text") or "")))
            for t in turns[-6:-1] if t.get("role") == "user")
            and re.search(indicator, ai_service._normalize_vi(str(turns[-1].get("text") or ""))))
    if (indicator_context and not re.search(indicator, text) and re.search(
            r"\b(nguyen nhan|tai sao|vi sao|kiem tra|ben trai|ben phai|ca hai ben)\b", text)
            and not re.search(r"\b(gia|chi phi|ton kho|lich su|hoa don|dat lich)\b", text)):
        previous_indicator = next((str(t.get("text") or "")[:120] for t in reversed(turns[-6:-1])
            if t.get("role") == "user" and re.search(indicator,
                ai_service._normalize_vi(str(t.get("text") or "")))), "")
        previous_symptom = ai_service._normalize_vi(previous_indicator)
        topic = previous_indicator if re.search(r"\b(chap chon|luc|khong sang)\b", previous_symptom) else "Xi nhan"
        question = f"{topic}: {question}"
        text = ai_service._normalize_vi(question).strip(" ?.!\n")
    indicator_mentioned = bool(re.search(indicator, text))
    symptom = bool(re.search(r"\b(chap chon|khong on dinh|bat thuong|bi hong|khong sang|"
                             r"khong nhay|khong hoat dong)\b", text)
                   or re.search(r"\bluc\b.{0,35}\bluc\b", text)
                   or re.search(r"\bluc\b.{0,35}\bkhong\b", text))
    business = bool(re.search(r"\b(gia|chi phi|bao gia|ton kho|lich su|hoa don|"
                              r"dat lich|bao hanh|phu tung)\b", text))
    knowledge = bool(re.search(r"\b(la gi|hoat dong|nguyen nhan|do dau|"
                               r"cach kiem tra|tai sao|vi sao)\b", text))
    if (indicator_mentioned or indicator_context) and symptom and not business and not knowledge:
        side_known = bool(re.search(r"\b(ben trai|ben phai|ca hai ben)\b", text))
        light_known = "canh bao nguy hiem" in text or "hazard" in text
        detail = ("Đèn xi nhan bên đó ở phía trước, phía sau hay cả hai không sáng?" if side_known else
                  "Xi nhan bên trái, bên phải hay cả hai bên hoạt động chập chờn?")
        if not light_known:
            detail += " Đèn cảnh báo nguy hiểm có gặp tình trạng tương tự không?"
        detail += " Bạn muốn kiểm tra nguyên nhân trước hay đã xác định cần thay phụ tùng?"
        detail += (" Nên dừng xe ở nơi an toàn nếu người khác khó nhận biết hướng rẽ; "
                   "hãy kiểm tra sớm, chưa thể xác định nguyên nhân khi chưa kiểm tra xe.")
        return question, AIResult(detail, "clarification", "local", ai_service.model, True), False
    if len(turns) >= 2 and turns[-1].get("role") == "assistant":
        last_user = next((str(t.get("text") or "") for t in reversed(turns[:-1])
                          if t.get("role") == "user"), "")
        if ai_service._normalize_vi(last_user).strip(" ?.!\n") in (
                "troi mua", "xe di mua", "lop mon") and any(
                term in ai_service._normalize_vi(str(turns[-1].get("text") or ""))
                for term in ("ban muon", "lop mon", "di mua")):
            previous = last_user
    # Không ghép chủ đề cũ vào câu hỏi nghiệp vụ hoặc câu hỏi đã nêu chủ đề mới.
    if previous and not any(term in text for term in (
            "gia", "chi phi", "lich su", "hoa don", "dat lich", "ton kho", "garage")):
        old = ai_service._normalize_vi(previous).strip(" ?.!\n")
        if old == "lop mon" and "lop" not in text:
            question = f"Lốp mòn {question}"
        elif old in ("troi mua", "xe di mua") and not any(term in text for term in ("mua", "lop", "phanh", "dong co")):
            question = f"Xe đi mưa: {question}"
        text = ai_service._normalize_vi(question).strip(" ?.!\n")
    clarifications = {
        "troi mua": "Bạn muốn tìm hiểu lưu ý khi lái xe trời mưa hay xe có dấu hiệu bất thường sau khi đi mưa?",
        "xe di mua": "Bạn muốn biết cách lái xe an toàn trong mưa, kiểm tra xe sau khi đi mưa hay xe đang có dấu hiệu bất thường?",
        "lop mon": "Bạn muốn tìm hiểu nguyên nhân lốp mòn hay cách kiểm tra độ mòn? Lốp mòn đều hay lệch một bên?",
        "lop": "Bạn muốn xem giá lốp, hỏi về tình trạng lốp xe hay cần tư vấn thay lốp? Nếu muốn tra giá, bạn có kích thước ghi trên hông lốp không?",
        "lop xe": "Bạn muốn xem giá lốp, hỏi về tình trạng lốp xe hay cần tư vấn thay lốp? Nếu muốn tra giá, bạn có kích thước ghi trên hông lốp không?",
        "vo xe": "Bạn muốn xem giá lốp, hỏi về tình trạng lốp xe hay cần tư vấn thay lốp? Nếu muốn tra giá, bạn có kích thước ghi trên hông lốp không?",
        "vo xe oto": "Bạn muốn xem giá lốp, hỏi về tình trạng lốp xe hay cần tư vấn thay lốp? Nếu muốn tra giá, bạn có kích thước ghi trên hông lốp không?",
    }
    if text in clarifications:
        return question, AIResult(clarifications[text], "clarification", "local", ai_service.model, True), False
    if re.search(r"\bxe nong (?:bat thuong|qua)\b", text) and not re.search(
            r"\b(gia|chi phi|lich su|hoa don|ton kho)\b", text):
        return question, AIResult("Bạn thấy đồng hồ nhiệt độ động cơ tăng cao hay chỉ cảm thấy khoang xe nóng? "
            "Nếu xe báo quá nhiệt, hãy dừng ở nơi an toàn và tắt máy để kiểm tra.",
            "clarification", "local", ai_service.model, True), False
    if _is_technical_question(question):
        return question, None, False
    # Ngữ nghĩa bổ sung cho cách diễn đạt không nằm trong quy tắc ổn định. Không cho
    # model phân loại lại yêu cầu giá/hồ sơ/quyền truy cập hoặc tự tạo nguồn.
    if (allow_semantic and ai_service._enabled and re.search(r"\b(xe|oto|o to|lop|phanh|dong co)\b", text)
            and not any(term in text for term in (
                "gia", "chi phi", "lich su", "hoa don", "dat lich", "ton kho", "phu tung",
                "bao hanh", "khach hang", "garage", "gara"))):
        try:
            raw = ai_service._chat([
                {"role": "system", "content":
                 "Phân loại ý định câu hỏi ô tô. Chỉ trả JSON object có trường kind, một trong: "
                 "technical (kiến thức kỹ thuật đủ rõ), ambiguous (ô tô nhưng chưa rõ nhu cầu), "
                 "symptom (triệu chứng xe cụ thể), business (dữ liệu garage), other (ngoài phạm vi). "
                 "Không đưa ra câu trả lời hay suy đoán tình trạng xe."},
                {"role": "user", "content": json.dumps({"question": question,
                    "history": turns[-4:]}, ensure_ascii=False)},
            ])
            kind = json.loads(raw).get("kind")
            if kind == "ambiguous":
                return question, AIResult("Bạn muốn tìm hiểu điều gì về tình huống này trên xe: "
                    "cách kiểm tra, lưu ý sử dụng hay dấu hiệu bất thường cụ thể?",
                    "clarification", "local", ai_service.model, True), False
            if kind in ("technical", "symptom"):
                return question, None, True
        except Exception:
            pass  # Provider lỗi/sai định dạng: không mở khóa trả lời thiếu nguồn.
    return question, None, False


def _general_knowledge_question(question: str) -> bool:
    """Chỉ mở nhánh không nguồn cho yêu cầu kiến thức rõ, không chứa dữ kiện riêng/giá."""
    text = ai_service._normalize_vi(question)
    if (ai_service._flood_intent(question, []) or ai_service._urgent_guidance(question, ai_service.model)
            or re.search(r"\b(gia|bao gia|chi phi|ton kho|hoa don|lich hen|bao hanh|"
                         r"khach hang|garage|gara|phu tung|bien so|vin)\b", text)
            or any(term in text for term in ("thay het bao nhieu", "sua het bao nhieu"))
            or any(phrase in text for phrase in (
                "xe toi", "xe cua toi", "xe minh", "xe cua minh", "xe nay",
                "xe cua khach", "da sua", "tung sua", "ho so", "cua toi"))):
        return False
    automotive = re.search(r"\b(xe|oto|o to|lop|phanh|abs|turbo|dong co|may|thay dau|xi nhan|si nhan|den bao re|"
                            r"vo lang|hop so|gat mua)\b", text)
    if re.search(r"\b(di|lai)\s+(?:xe\s+)?(?:troi\s+)?mua\b", text):
        automotive = True
    knowledge = any(phrase in text for phrase in (
        "la gi", "the nao", "hoat dong", "nguyen nhan", "do dau", "co the do",
        "can luu y", "luu y gi", "chu y gi", "dau hieu", "co nguy hiem",
        "khi nao can", "khi nao nen", "khi nao", "co can thay", "dinh ky",
        "bao lau thi", "can thay khong", "nen lam gi", "cach kiem tra", "cach lai"))
    return bool(automotive and knowledge)


def _technical_references(db, question: str, vehicle=None, *, semantic_technical: bool = False) -> tuple[list[dict], list[dict]]:
    """Tra nguồn cho câu hỏi kỹ thuật; an toàn/giá/lịch sử đi luồng riêng."""
    text = ai_service._normalize_vi(question)
    if (ai_service._flood_intent(question, []) or ai_service._urgent_guidance(question, ai_service.model)
              or re.search(r"\bgia\b", text)
              or any(term in text for term in ("bao nhieu tien", "thay het bao nhieu", "sua het bao nhieu",
                                                 "lich su", "da sua",
                                                "tung sua", "bao hanh", "dia chi", "hotline",
                                                "bao lau", "phu tung", "linh kien", "phu kien"))):
        return [], []
    if not semantic_technical and not _is_technical_question(question):
        return [], []
    selected = dict(vehicle) if vehicle else None
    indicator_query = bool(re.search(_INDICATOR, text))
    # Mở rộng truy vấn tìm kiếm, không sửa câu hỏi gốc hoặc chỉ mục embedding.
    tire_question = bool(re.search(r"\b(lop|vo xe)\b", text))
    tire_wear = bool(tire_question and any(term in text for term in (
        "an lech", "mon lech", "mon khong deu", "lop mon", "mon khac nhau", "hai ben mon", "mon vai", "mon mep")))
    tire_noise = bool(tire_question and any(term in text for term in (
        "rit", "ken ket", "tieng nghien")))
    tire_slip = bool(tire_question and any(term in text for term in (
        "truot", "mat bam", "bam duong", "toc do cao")))
    intermittent = indicator_query and bool(re.search(r"\b(chap chon|khong on dinh|luc|bat tat|khong sang)\b", text))
    unstable = (indicator_query and "nhay nhanh" not in text and
                bool(re.search(r"\b(chap chon|khong on dinh|luc|bat tat)\b", text)))
    lookup = ("xi nhan chap chon den bao re luc sang luc khong" if unstable else
              re.sub(_INDICATOR, "xi nhan", text) if indicator_query else
              "lốp mòn mép mòn không đều mòn lệch" if tire_wear else
              "lốp rít tiếng rít tiếng nghiến" if tire_noise else
              "lốp mất độ bám trượt ở tốc độ cao" if tire_slip else question)
    cases = search_repair_cases(db, lookup, selected, limit=1)
    articles = [*cases, *search_technical(db, lookup, limit=2 if cases else 3, vehicle=selected)]
    def evidence_text(article):
        return ai_service._normalize_vi(" ".join((str(article.get("title") or ""),
            str(article.get("symptoms") or ""),
            *(str(hit.get("content") or "") for hit in article.get("excerpts") or []))))
    if indicator_query:
        def relevant(article):
            content = evidence_text(article)
            return bool(re.search(_INDICATOR, content) and (not intermittent or re.search(
                r"\b(chap chon|khong on dinh|luc|bat tat|khong sang)\b", content)))
        articles = [article for article in articles if relevant(article)]
    # FTS OR chỉ khớp "phanh" với bài phanh ướt không đủ trả lời tiếng kêu.
    if re.search(r"\bphanh\b", text) and re.search(r"\b(keu|rit|loc coc)\b", text):
        articles = [article for article in articles if re.search(r"\b(keu|tieng|rit|loc coc)\b",
            evidence_text(article))]
    if re.search(r"\b(?:di|lai)\s+(?:xe\s+)?(?:troi\s+)?mua\b|\btroi mua lai xe\b", text):
        articles = [article for article in articles if re.search(
            r"\b(lai|toc do|quan sat|tam nhin|khoang cach|duong tron)\b", evidence_text(article))]
    sources = [{"type": "technical_article", "id": article["id"],
                "label": (f"{'Ca thực tế đã duyệt (tham khảo)' if article.get('source_type') == 'repair_case' else 'Kiến thức kỹ thuật'}: {article['title']} · {article['source_name']}" +
                          (f" · phiên bản {article['document_version']}" if article["document_version"] else "") +
                          (" · Cảnh báo khẩn cấp" if article["safety_level"] == "critical" else
                           " · Cảnh báo cao" if article["safety_level"] == "high" else "") +
                          (f" · đoạn {article['excerpts'][0]['chunk_index']}" if article.get("excerpts") else "")),
                "date": article["updated_at"][:10],
                "url": article["source_url"] if article["source_url"].startswith("https://") else None}
               for article in articles]
    for source, article in zip(sources, articles):
        if article.get("source_type") == "repair_case":
            source["type"] = "repair_case"
    return articles, sources


def _indicator_replacement_reply(db, question: str, vehicle, parts: list[dict], user: dict,
                                 history: list[dict] | None = None) -> tuple[AIResult, list[dict]] | None:
    """Tư vấn thay thế chỉ từ xe đã xác thực, quy tắc lắp vừa và danh mục đang hoạt động."""
    text = ai_service._normalize_vi(question)
    turns = history or []
    direct = bool(re.search(_INDICATOR, text) and re.search(r"\b(thay|doi|lap)\b", text))
    last_assistant = ai_service._normalize_vi(str(turns[-1].get("text") or "")) if turns and turns[-1].get("role") == "assistant" else ""
    previous_request = any(t.get("role") == "user" and re.search(_INDICATOR, ai_service._normalize_vi(str(t.get("text") or "")))
        and re.search(r"\b(thay|doi|lap)\b", ai_service._normalize_vi(str(t.get("text") or ""))) for t in turns[-6:-1])
    continuation = (previous_request and "xi nhan" in last_assistant and
                    bool(re.search(r"\b(trai|phai|truoc|sau|ca hai)\b", text)) and
                    not re.search(r"\b(gia|chi phi|ton kho|lich su|hoa don|lich hen)\b", text))
    if not direct and not continuation:
        return None
    def clarify(message: str):
        return AIResult(message, "clarification", "local", ai_service.model, True), []
    if not vehicle:
        return clarify("Bạn hãy chọn đúng xe trong hồ sơ để garage đối chiếu xi nhan và quyền sở hữu trước khi tư vấn thay thế.")
    combined = " ".join([str(t.get("text") or "") for t in turns[-6:] if t.get("role") == "user"] + [question]) if continuation else question
    normalized = ai_service._normalize_vi(combined)
    sides = [side for side in ("trai", "phai") if re.search(rf"\b{side}\b", normalized)]
    positions = [pos for pos in ("truoc", "sau") if re.search(rf"\b{pos}\b", normalized)]
    if len(sides) != 1:
        return clarify("Bạn cần thay xi nhan bên trái hay bên phải? Nếu cả hai bên, vui lòng nói rõ từng vị trí để đối chiếu phụ tùng.")
    if len(positions) != 1:
        return clarify(f"Xi nhan bên {sides[0]} cần thay ở phía trước hay phía sau? Cần xác định vị trí trước khi tra mã phụ tùng.")
    info = dict(vehicle)
    candidates = []
    for part in parts:
        name = ai_service._normalize_vi(str(part.get("name") or ""))
        if (not re.search(_INDICATOR, name) or
            not re.search(rf"\b{sides[0]}\b", name) or
            not re.search(rf"\b{positions[0]}\b", name)):
            continue
        if part.get("fitments") and ai_service._part_fit_level(part, info) == 3:
            candidates.append(part)
    if len(candidates) != 1:
        return clarify("Chưa có đúng một mã xi nhan khớp vị trí và quy tắc lắp vừa đã xác minh cho xe này. "
                       "Vui lòng hỏi cố vấn dịch vụ đối chiếu VIN và mã phụ tùng; không nên đặt thay chỉ theo triệu chứng.")
    part = candidates[0]
    sources = [{"type": "part", "id": part["id"], "label": f"Danh mục phụ tùng: {part['name']} ({part['code']})"}]
    amount = part.get("sell_price")
    answer = (f"Danh mục ghi {part['name']} ({part['code']}) khớp quy tắc lắp vừa của xe đã chọn. "
              "Vẫn cần đối chiếu VIN và kiểm tra thực tế trước khi quyết định thay. ")
    if has_permission(user.get("role", ""), "inventory.view") and has_permission(user.get("role", ""), "inventory.view_all"):
        answer += f"Tồn kho ghi nhận: {part['stock']} {part['unit']} (chưa giữ hàng). "
    else:
        answer += "Tình trạng hàng cần nhân viên xác nhận; tài khoản này không có quyền xem tồn kho chi tiết. "
    if not amount:
        return AIResult(answer + "Chưa có giá bán được xác nhận; cần cố vấn dịch vụ lập báo giá.",
                        "no_data", "local", ai_service.model, True, ["Giá phụ tùng"]), sources
    answer += f"Giá phụ tùng tham khảo: {int(amount):,} ₫/{part['unit']}. ".replace(",", ".")
    if has_permission(user.get("role", ""), "inventory.view") and not part.get("stock"):
        return AIResult(answer + "Chưa thể lập ước tính thay thế khi chưa xác nhận khả năng cung ứng. "
                        "Vui lòng hỏi cố vấn dịch vụ về hàng và báo giá chính thức.",
                        "no_data", "local", ai_service.model, True, ["Khả năng cung ứng"]), sources
    services = [dict(row) for row in db.execute(
        "SELECT id,name,price FROM services WHERE active=1 ORDER BY id")
        if ai_service._normalize_vi(row["name"]).strip() in ("thay xi nhan", "thay den bao re")]
    if len(services) == 1 and services[0]["price"]:
        service = services[0]
        sources.append({"type": "service", "id": service["id"], "label": f"Danh mục dịch vụ: {service['name']}"})
        answer += (f"Giá công {service['name']}: {int(service['price']):,} ₫; "
                   f"cộng hai hạng mục tham khảo: {int(amount) + int(service['price']):,} ₫. ").replace(",", ".")
        answer += "Chưa gồm phát sinh hoặc thuế; báo giá chính thức cần nhân viên kiểm tra và xác nhận."
    else:
        answer += "Chưa có giá công thay xi nhan được xác nhận, nên chưa thể tính tổng; hãy nhờ cố vấn dịch vụ lập báo giá chính thức."
    return AIResult(answer, "fallback", "local", ai_service.model), sources


@router.get("/knowledge/search")
def knowledge_search(
    q: str = Query(min_length=2, max_length=160),
    vehicle_id: int | None = Query(default=None, gt=0),
    user: dict = Depends(require_permission("dashboard")),
) -> dict:
    """Nguồn có thể dẫn chứng cho RAG; tra giá/tồn kho riêng bằng API nghiệp vụ."""
    with connect() as db:
        # Hai lần truy xuất riêng: lịch sử chỉ sau khi xác thực xe, nguồn chung không
        # nhận customer_id và không bao giờ chứa ghi chú lịch sử.
        vehicle_history = search_knowledge(db, user, q, vehicle_id, kind="vehicle") if vehicle_id else []
        general = search_knowledge(db, user, q, kind="public")
        selected_vehicle = db.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone() if vehicle_id else None
        technical = search_technical(db, q, vehicle=dict(selected_vehicle) if selected_vehicle else None)
        cases = search_repair_cases(db, q, dict(selected_vehicle) if selected_vehicle else None)
    matches = vehicle_history + general
    return {"items": matches, "total": len(matches), "vehicle_history": vehicle_history,
            "general": general, "technical": technical, "cases": cases}


def _public_garage_info(db) -> dict[str, str]:
    """Chỉ các trường liên hệ có thể công khai cho mọi vai trò."""
    return {row["key"]: row["value"].strip() for row in db.execute(
        "SELECT key,value FROM system_settings WHERE key IN ('garage_name','garage_address','garage_phone')"
    ).fetchall()}


def _history_sources(db, vehicle_id: int, *, include_legacy: bool = False, plate: str = "") -> list[dict]:
    """Nguồn truy vết từ chính lịch sử xe đã được kiểm tra quyền ở caller."""
    rows = db.execute(
        """SELECT h.id,h.repaired_at,ro.code FROM repair_history h
           LEFT JOIN repair_orders ro ON ro.id=h.repair_order_id
           WHERE h.vehicle_id=? OR (? AND h.vehicle_id IS NULL AND h.plate=?)
           ORDER BY h.repaired_at DESC,h.id DESC LIMIT 20""",
        (vehicle_id, int(include_legacy), plate),
    ).fetchall()
    return [{"type": "repair_history", "id": row["id"],
             "label": f"{row['code'] or 'Lịch sử sửa chữa'} · {row['repaired_at'][:10]}",
             "date": row["repaired_at"][:10]} for row in rows]


def _order_sources(context: dict) -> list[dict]:
    if not context.get("items") and not context.get("parts"):
        return []
    order = context.get("repair_order") or {}
    sources = [{"type": "repair_order", "id": order.get("id"),
                "label": f"Phiếu sửa chữa {order['code']}"}] if order.get("code") else []
    quote = context.get("quote") or {}
    if quote.get("code"):
        sources.append({"type": "quote", "id": quote["id"],
                        "label": f"Báo giá {quote['code']} ({quote['status']})"})
    invoice = context.get("invoice") or {}
    if invoice.get("code"):
        sources.append({"type": "invoice", "id": invoice.get("id"),
                         "label": f"Hóa đơn {invoice['code']}",
                         "date": str(invoice.get("issued_at") or "")[:10]})
    seen_services = set()
    for item in context.get("items") or []:
        if item.get("service_id") and item.get("garage_description") and item["service_id"] not in seen_services:
            seen_services.add(item["service_id"])
            sources.append({"type": "service", "id": item["service_id"],
                            "label": f"Danh mục dịch vụ: {item['name']}"})
    return sources


def _follow_up_sources(context: dict, question: str) -> list[dict]:
    normalized = ai_service._normalize_vi(question)
    mentioned = set(re.findall(r"\b(?:PSC|BG|HD)-[A-Z0-9-]+\b", question.upper()))
    allowed = {str((context.get(key) or {}).get("code") or "").upper()
               for key in ("repair_order", "quote", "invoice")}
    if mentioned - allowed:
        return []
    if any(term in normalized for term in ("phieu khac", "xe khac", "hoa don khac", "khach hang khac")):
        return []
    # Chứng từ có thể tồn tại nhưng không hề xác nhận bảo hành: không gắn nhầm
    # chứng từ làm nguồn cho một điều kiện bảo hành không có trong dữ liệu.
    if any(term in normalized for term in ("bao hanh", "cam ket")) and any(
            "bảo hành" in missing.lower() for missing in context.get("missing_data") or []):
        return []
    if any(term in normalized for term in ("bao lau", "thoi gian sua", "mat bao lau")) and "bao hanh" not in normalized:
        document = context.get("invoice") or context.get("quote") or {}
        return _order_sources(context) if document.get("estimated_duration_min") else []
    if any(term in normalized for term in ("dia chi", "hotline", "so dien thoai", "lien he")):
        info = context.get("garage_info") or {}
        return ([{"type": "system_settings", "id": None,
                   "label": "Thông tin liên hệ garage đã cấu hình"}] if
                info.get("garage_address") or info.get("garage_phone") else [])
    if any(term in normalized for term in ("gia", "chi phi", "tong tien", "bao nhieu")):
        return [source for source in _order_sources(context) if source["type"] != "service"]
    return _order_sources(context)


def _require_follow_up_source(result: AIResult, sources: list[dict]) -> AIResult:
    if sources or result.status in ("error", "no_data") and result.no_data:
        return result
    return AIResult("Chưa đủ dữ liệu có nguồn phù hợp trong hồ sơ để trả lời câu hỏi này. "
                    "Vui lòng hỏi cố vấn dịch vụ hoặc kỹ thuật viên để xác nhận.",
                    "no_data", "local", ai_service.model, True, ["Nguồn xác nhận cho câu hỏi"])


def _service_data_status(result: AIResult, context: dict) -> str:
    if result.status == "error":
        return "error"
    if result.no_data or not context.get("items") and not context.get("parts"):
        return "no_data"
    return "partial" if result.missing_data else "sourced"


def _assistant_sources(db, question: str, answer: str, vehicle, context, parts, garage_info) -> list[dict]:
    """Chỉ dẫn nguồn thực tế xuất hiện trong câu trả lời; không nhận citation từ LLM."""
    normalized = ai_service._normalize_vi(question)
    sources: list[dict] = []
    estimate = (context or {}).get("latest_work_estimate") or {}
    if estimate.get("id") and any(term in normalized for term in ("bao lau", "thoi gian sua", "mat bao lau")) and "bao hanh" not in normalized:
        sources.append({"type": "invoice" if estimate["source"] == "hóa đơn" else "quote",
                        "id": estimate["id"], "label": f"{estimate['source'].capitalize()} {estimate['code']}"})
    if vehicle and context and context.get("history") and any(term in normalized for term in
            ("lich su", "da sua", "tung sua", "thay lan", "bao duong", "lan truoc")):
        sources.extend(_history_sources(db, vehicle["id"]))
    elif vehicle and context and "thay dau" in normalized and "Hồ sơ ghi lần thay dầu" in answer:
        oil_visit = next((visit for visit in context.get("history") or [] if visit.get("id") and
                          visit.get("mileage") is not None and any(
                              "thay dau" in ai_service._normalize_vi(str(item.get("name") or ""))
                              for item in visit.get("services") or [])), None)
        if oil_visit:
            sources.append({"type": "repair_history", "id": oil_visit["id"],
                            "label": "Lần thay dầu đã ghi nhận", "date": str(oil_visit["repaired_at"])[:10]})
    for part in parts:
        if part["code"].casefold() in answer.casefold():
            sources.append({"type": "part", "id": part["id"],
                            "label": f"Danh mục phụ tùng: {part['name']} ({part['code']})"})
    if any(term in normalized for term in ("dia chi", "hotline", "so dien thoai", "lien he")) and any(
            garage_info.get(key) for key in ("garage_address", "garage_phone")):
        sources.append({"type": "system_settings", "id": None,
                        "label": "Thông tin liên hệ garage đã cấu hình"})
    return sources


def _assistant_appointment_items(db, answer: str, sources: list[dict], parts: list[dict]) -> list[dict]:
    """Chỉ đưa ID danh mục thật có bằng chứng trong câu trả lời, không tin ID do LLM tạo."""
    part_ids = {source["id"] for source in sources if source["type"] == "part"}
    approved = {row["part_id"] for row in db.execute(
        """SELECT a.part_id FROM part_price_approvals a
           JOIN parts p ON p.id=a.part_id
           WHERE p.active=1 AND p.sell_price=a.approved_sell_price""").fetchall()} if db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='part_price_approvals'").fetchone() else set()
    candidates = [{"kind": "part", "id": part["id"], "name": part["name"],
                    "price": part["sell_price"],
                    "availability": "Đang có hàng" if part["stock"] > 0 else "Tạm hết hàng"}
                   for part in parts if part["id"] in part_ids and part["id"] in approved
                   and not part["code"].upper().startswith("DEMO-")]
    normalized = ai_service._normalize_vi(answer)
    for service in db.execute("SELECT id,name,price FROM services WHERE active=1 ORDER BY name").fetchall():
        if ai_service._normalize_vi(service["name"]) in normalized:
            candidates.append({"kind": "service", "id": service["id"],
                               "name": service["name"], "price": service["price"]})
    return candidates[:8]


@router.post("/assistant/chat", response_model=AIResultOut, response_model_exclude_none=True)
def assistant_chat(item: AssistantChatIn, user: dict = Depends(require_permission("dashboard"))) -> dict:
    """Legacy transport: client history is untrusted language context only."""
    from ...chat_pipeline import answer_chat
    started = time.perf_counter()
    output = answer_chat(item.question, user, vehicle_id=item.vehicle_id, plate=item.plate,
                         history=[turn.model_dump() for turn in item.history])
    if output.answer.status == "denied":
        with connect() as db, transaction(db):
            write_audit(db, user, "ai.inventory.denied", "parts", None, {"reason": "permission"}, None)
    else:
        with connect() as db, transaction(db):
            _audit_ai(db, user, "other", "vehicle" if output.vehicle_id else "general",
                      str(output.vehicle_id or 0), output.answer,
                      {"vehicle_id": output.vehicle_id, "question": item.question},
                      int((time.perf_counter() - started) * 1000))
    return output.result


def _audit_ai(db, user: dict, task: str, ref_type: str, ref_id: str, result: AIResult,
              input_fingerprint: dict, latency_ms: int, error: str | None = None) -> None:
    prompt_hash = hashlib.sha256(
        json.dumps(input_fingerprint, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    persisted_status = result.status if result.status in {"success", "fallback", "error"} else "fallback"
    db.execute(
        """INSERT INTO ai_interactions(user_id, task_type, ref_type, ref_id, status, provider,
               model, prompt_hash, metadata, latency_ms)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user["id"], task, ref_type, ref_id, persisted_status, result.provider, result.model,
         prompt_hash, json.dumps({"no_data": result.no_data, "error": error}, ensure_ascii=False),
         latency_ms),
    )


def _vehicle_context(db, vehicle, include_internal_notes: bool) -> dict:
    """Tạo ngữ cảnh tối thiểu từ DB; không đưa giá/thu tiền/trạng thái quyết định cho AI."""
    backfill_repair_history(db, vehicle_id=vehicle["id"])
    # Khách chỉ được xem lịch sử gắn rõ vehicle_id; bản legacy không liên kết chỉ
    # bằng biển số có thể thuộc chủ xe cũ nên chỉ nhân viên được tra bổ sung.
    history_where = "vehicle_id=? OR (vehicle_id IS NULL AND plate=?)" if include_internal_notes else "vehicle_id=?"
    rows = db.execute(
        f"""SELECT id, repair_order_id, repaired_at, mileage, services, note
            FROM repair_history WHERE {history_where} ORDER BY repaired_at DESC, id DESC""",
        (vehicle["id"], vehicle["plate"]) if include_internal_notes else (vehicle["id"],),
    ).fetchall()
    history = []
    for row in rows:
        services: list[dict] = []
        parts: list[dict] = []
        # repair_history.note có thể chứa repair_notes nội bộ khi đồng bộ phiếu.
        notes = [row["note"]] if include_internal_notes and (row["note"] or "").strip() else []
        order_id = row["repair_order_id"]
        if order_id:
            services = [dict(item) for item in db.execute(
                """SELECT id,service_id,name,quantity,actual_duration_min FROM repair_order_items
                   WHERE repair_order_id=? AND kind='Dịch vụ' ORDER BY id""", (order_id,)
            ).fetchall()]
            parts = [dict(item) for item in db.execute(
                """SELECT rp.id,rp.part_id,p.code,rp.name,rp.quantity
                   FROM repair_order_parts rp LEFT JOIN parts p ON p.id=rp.part_id
                   WHERE rp.repair_order_id=? ORDER BY rp.id""",
                (order_id,),
            ).fetchall()]
            parts.extend(dict(item) for item in db.execute(
                """SELECT id,NULL part_id,NULL code,name,quantity FROM repair_order_items
                   WHERE repair_order_id=? AND kind='Phụ tùng' ORDER BY id""", (order_id,)
            ).fetchall())
            if include_internal_notes:
                notes.extend(item["content"] for item in db.execute(
                    "SELECT content FROM repair_notes WHERE repair_order_id=? ORDER BY id", (order_id,)
                ).fetchall() if (item["content"] or "").strip())
        if not services and (row["services"] or "").strip():
            services = [{"name": name.strip(), "quantity": None}
                        for name in row["services"].split(",") if name.strip()]
        history.append({
            "id": row["id"], "repair_order_id": row["repair_order_id"],
            "repaired_at": row["repaired_at"], "mileage": row["mileage"],
            "services": services, "parts": parts, "technical_notes": notes,
        })
    profile = db.execute("""SELECT engine_number,transmission,drivetrain,displacement_cc,power_kw,torque_nm,
                                  fuel_consumption,fuel_tank_liters,tire_size,tire_pressure,
                                  oil_capacity_liters,oil_spec
                           FROM vehicle_profiles WHERE vehicle_id=?""", (vehicle["id"],)).fetchone()
    return {
        "vehicle": {key: vehicle[key] for key in ("id", "plate", "vin", "make", "model", "year",
                                                 "variant", "engine_code", "fuel_type", "mileage")},
        "technical_specs": {key: value for key, value in dict(profile).items() if value is not None}
                           if profile else {},
        "history": history,
    }


@router.post("/repair-history-summary", response_model=AIResultOut, response_model_exclude_none=True)
def repair_history_summary(
    selector: VehicleHistorySummaryIn,
    user: dict = Depends(require_permission("dashboard")),
) -> dict:
    if bool(selector.vehicle_id) == bool(selector.plate):
        raise BadRequestError("Chỉ cung cấp một trong hai trường vehicle_id hoặc plate")
    started = time.perf_counter()
    with connect() as db, transaction(db):
        if selector.vehicle_id:
            vehicle = db.execute("SELECT * FROM vehicles WHERE id=?", (selector.vehicle_id,)).fetchone()
        else:
            vehicle = db.execute(
                "SELECT * FROM vehicles WHERE plate_normalized=? ORDER BY id LIMIT 1",
                (normalize_plate(selector.plate or ""),),
            ).fetchone()
        if not vehicle:
            raise NotFoundError("Không tìm thấy xe")
        ensure_record_access(db, user, vehicle["customer_id"])
        include_internal = user.get("role") != "Khách hàng"
        context = _vehicle_context(db, vehicle, include_internal_notes=include_internal)
        context = enrich_history_context(db, context, include_internal_notes=include_internal)
        analysis = build_history_analysis(context)
        context["analysis"] = analysis
        error_text = None
        try:
            result = ai_service.summarize_repair_history(context)
        except Exception as exc:  # provider lỗi: vẫn trả bản tóm tắt an toàn từ dữ liệu thật
            error_text = str(exc)
            missing = ai_service._missing_fields(context)
            result = AIResult(ai_service._fallback_summary(context, missing), "error", "local",
                              ai_service.model, False, missing)
        # Nội dung nghiệp vụ bắt buộc do backend dựng từ phép tính có nguồn; provider
        # không được tự thay số liệu, bỏ cảnh báo hoặc biến đề xuất thành việc đã làm.
        result.content = render_history_summary(analysis, result.missing_data)
        sources = analysis["sources"]
        latency_ms = int((time.perf_counter() - started) * 1000)
        _audit_ai(db, user, "summary", "vehicle", str(vehicle["id"]), result,
                  {"vehicle_id": vehicle["id"], "history_ids": [item["repaired_at"] for item in context["history"]]},
                  latency_ms, error_text)
    return {"result": result.content, "is_draft": True, "status": result.status,
            "no_data": result.no_data, "source_count": len(sources),
            "sources": sources, "missing_data": result.missing_data,
            "history_summary": analysis}


@router.post("/repair-orders/{order_id}/estimate-draft", response_model=AIResultOut)
def repair_order_estimate_draft(
    order_id: int,
    user: dict = Depends(require_permission("repair_orders")),
) -> dict:
    """AI chỉ diễn giải; tên, số lượng, đơn giá và tổng đều do backend đọc/tính."""
    started = time.perf_counter()
    with connect() as db, transaction(db):
        order = db.execute("SELECT id, code, plate, total FROM repair_orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            raise NotFoundError("Không tìm thấy phiếu sửa chữa")
        items = [dict(row) for row in db.execute(
            """SELECT kind, name, quantity, unit_price, line_total FROM repair_order_items
               WHERE repair_order_id=? UNION ALL
               SELECT 'Phụ tùng', name, quantity, unit_price, line_total FROM repair_order_parts
               WHERE repair_order_id=?""", (order_id, order_id)
        ).fetchall()]
        result = ai_service.explain({"purpose": "Diễn giải báo giá nháp", "order": dict(order), "items": items})
        _audit_ai(db, user, "estimate", "repair_order", str(order_id), result,
                  {"order_id": order_id, "item_count": len(items)},
                  int((time.perf_counter() - started) * 1000))
    return {"result": result.content, "is_draft": True, "status": result.status,
            "source_count": len(items), "missing_data": []}


def _service_context_by_order(db, order_id: int, user: dict, quote_id: int | None = None) -> tuple[dict, dict, list[dict], list[str]]:
    order = db.execute(
        """SELECT ro.id,ro.code,ro.plate,ro.customer_id,ro.customer_request,ro.inspection_notes,ro.note,
                  ro.status_code,ro.km_in,ro.vehicle_id,v.make,v.model,v.year,v.variant,v.engine_code,v.fuel_type
           FROM repair_orders ro LEFT JOIN vehicles v ON v.id=ro.vehicle_id WHERE ro.id=?""", (order_id,)
    ).fetchone()
    if not order:
        raise NotFoundError("Không tìm thấy phiếu sửa chữa")
    ensure_record_access(db, user, order["customer_id"])
    is_customer = user.get("role") == "Khách hàng"
    quote_sql = "SELECT * FROM quotes WHERE repair_order_id=?"
    params: list = [order_id]
    if quote_id is not None:
        quote_sql += " AND id=?"
        params.append(quote_id)
    if is_customer:
        quote_sql += " AND status='Đã duyệt'"
    quote_sql += " ORDER BY (status='Đã duyệt') DESC,version DESC,id DESC LIMIT 1"
    quote = db.execute(quote_sql, params).fetchone()
    reasons = [value.strip() for value in (order["inspection_notes"],) if (value or "").strip()]
    if not is_customer:
        reasons.extend(row["content"].strip() for row in db.execute(
            "SELECT content FROM repair_notes WHERE repair_order_id=? ORDER BY id", (order_id,)
        ).fetchall() if (row["content"] or "").strip())
    confirmed_reason = " • ".join(dict.fromkeys(reasons))
    if quote:
        rows = [dict(row) for row in db.execute(
            """SELECT qi.id,qi.kind,qi.name,qi.quantity,qi.unit_price,qi.line_total quoted_line_total,
                        qi.service_id,qi.estimated_duration_min,
                       COALESCE(s.description,'') garage_description
                FROM quote_items qi LEFT JOIN services s ON s.id=qi.service_id
                WHERE qi.quote_id=? AND qi.kind='Dịch vụ' ORDER BY qi.id""", (quote["id"],)
        ).fetchall()]
    else:
        rows = [dict(row) for row in db.execute(
            """SELECT roi.id,roi.kind,roi.name,roi.quantity,roi.unit_price,NULL quoted_line_total,
                        roi.service_id,NULL estimated_duration_min,
                       COALESCE(s.description,'') garage_description
                FROM repair_order_items roi LEFT JOIN services s ON s.id=roi.service_id
                WHERE roi.repair_order_id=? AND roi.kind='Dịch vụ' ORDER BY roi.id""", (order_id,)
        ).fetchall()]
    items = [{**item, "technician_reason": confirmed_reason or None} for item in rows]
    if quote:
        parts = [dict(row) for row in db.execute(
            """SELECT qi.id,qi.kind,qi.name,qi.quantity,qi.unit_price,qi.line_total quoted_line_total,
                      qi.part_id,p.code part_code
               FROM quote_items qi LEFT JOIN parts p ON p.id=qi.part_id
               WHERE qi.quote_id=? AND qi.kind='Phụ tùng' ORDER BY qi.id""",
            (quote["id"],),
        ).fetchall()]
    else:
        parts = [dict(row) for row in db.execute(
            """SELECT roi.id,'Phụ tùng' kind,roi.name,roi.quantity,roi.unit_price,NULL quoted_line_total,
                      NULL part_id,NULL part_code
               FROM repair_order_items roi
               WHERE roi.repair_order_id=? AND roi.kind='Phụ tùng'
               UNION ALL
                SELECT (1000000+rop.id),'Phụ tùng',rop.name,rop.quantity,rop.unit_price,NULL,rop.part_id,p.code
                FROM repair_order_parts rop LEFT JOIN parts p ON p.id=rop.part_id WHERE rop.repair_order_id=?
               ORDER BY 1""", (order_id, order_id),
        ).fetchall()]
    missing: list[str] = []
    if any(not item["garage_description"] for item in items):
        missing.append("Mô tả kỹ thuật của một hoặc nhiều dịch vụ")
    if not confirmed_reason:
        missing.append("Lý do thực hiện đã được kỹ thuật viên xác nhận")
    if not quote:
        missing.append("Chi phí từ báo giá hiện tại")
    missing.extend(["Kết quả sửa chữa sau kiểm tra thực tế", "Thời gian và điều kiện bảo hành"])
    context = {
        "repair_order": {"id": order["id"], "code": order["code"], "plate": order["plate"],
                         "status_code": order["status_code"], "inspection_notes": order["inspection_notes"] or None,
                         "customer_request": order["customer_request"] or None},
        "vehicle": {key: order[key] for key in ("make", "model", "year", "variant", "engine_code", "fuel_type", "km_in")},
        "quote": ({key: quote[key] for key in ("id", "code", "status", "subtotal", "discount", "tax", "total", "estimated_duration_min")} if quote else None),
        "items": items, "parts": parts, "missing_data": missing,
        "classification": {"confirmed": "Dữ liệu từ phiếu và báo giá", "inferred": "Không có", "unknown": missing},
    }
    _enrich_service_context(db, context, order_id)
    return context, dict(order), items, context["missing_data"]


def _enrich_service_context(db, context: dict, order_id: int) -> None:
    """Only server-derived evidence; no inferred diagnosis, warranty or part fitment."""
    from ...technical_knowledge import _applies

    vehicle = context.get("vehicle") or {}
    if any(not vehicle.get(key) for key in ("make", "model")):
        vehicle = {}
    makes = [row[0] for row in db.execute("SELECT DISTINCT make FROM vehicles WHERE TRIM(make)<>''")]
    for part in context.get("parts") or []:
        part_id = part.get("part_id")
        part["fitment_status"] = "unverified"
        # Name mismatch is a review hint only; names are not fitment evidence.
        name = str(part.get("name") or "").casefold().split()
        part["name_warning"] = bool(vehicle.get("make") and any(
            make.casefold() != str(vehicle["make"]).casefold() and make.casefold() in name
            for make in makes if len(make) >= 3))
        if part_id:
            rules = [dict(rule) for rule in db.execute(
                "SELECT make vehicle_make,model vehicle_model,year_from,year_to,engine_code,variant,fuel_type "
                "FROM part_fitments WHERE part_id=?", (part_id,)
            )]
            if rules and vehicle:
                # _applies validates make/model/year/engine; check variant/fuel too.
                def matches(rule):
                    return _applies(rule, vehicle) and all(
                        not rule[field] or vehicle.get(field) and
                        str(rule[field]).casefold() == str(vehicle[field]).casefold()
                        for field in ("variant", "fuel_type"))
                if any(matches(rule) for rule in rules):
                    part["fitment_status"] = "verified_rule"
                elif any(not vehicle.get(vehicle_field) and rule[rule_field] for rule in rules
                         for rule_field, vehicle_field in (("vehicle_make", "make"), ("vehicle_model", "model"),
                                                          ("engine_code", "engine_code"), ("variant", "variant"),
                                                          ("fuel_type", "fuel_type"))) or (
                             any(vehicle.get("year") is None and (rule["year_from"] or rule["year_to"]) for rule in rules)):
                    part["fitment_status"] = "unverified"
                else:
                    part["fitment_status"] = "review_required"
    missing = context.setdefault("missing_data", [])
    if any(not part.get("part_code") for part in context.get("parts") or []):
        missing.append("Mã phụ tùng để kiểm tra cấu hình xe")
    if context.get("parts"):
        missing.append("Mô tả kỹ thuật được xác nhận cho phụ tùng")
        if any(part.get("fitment_status") != "verified_rule" for part in context["parts"]):
            missing.append("Quy tắc lắp vừa phụ tùng theo cấu hình xe cần kỹ thuật viên đối chiếu")
    quote = context.get("quote") or {}
    invoice = context.get("invoice") or {}
    doc = invoice or quote
    if doc.get("subtotal") is not None:
        lines = [*context.get("items", []), *context.get("parts", [])]
        if lines and all(item.get("quoted_line_total") is not None for item in lines):
            from decimal import Decimal
            total = sum(Decimal(str(item["quoted_line_total"])) for item in lines)
            context["subtotal_mismatch"] = total != Decimal(str(doc["subtotal"]))
            if context["subtotal_mismatch"]:
                missing.append("Chênh lệch tổng dòng và tạm tính chứng từ: cần đối chiếu báo giá/hóa đơn")
    context["missing_data"] = list(dict.fromkeys(missing))


def _service_context_by_invoice(db, invoice_id: int, user: dict) -> tuple[dict, dict, list[dict], list[str]]:
    """Snapshot hóa đơn thuộc chủ xe; không dùng báo giá mới hơn hoặc ghi chú nội bộ."""
    invoice = db.execute(
        """SELECT i.id, i.code, i.status, i.total, i.subtotal, i.discount, i.tax,
                   i.estimated_duration_min,
                  i.paid_amount, i.repair_order_id, i.quote_id, i.issued_at,
                   ro.code order_code, ro.plate, ro.customer_id, ro.customer_request,
                   ro.inspection_notes, ro.km_in,ro.status_code,v.make,v.model,v.year,v.variant,v.engine_code,v.fuel_type
           FROM invoices i JOIN repair_orders ro ON ro.id=i.repair_order_id
           LEFT JOIN vehicles v ON v.id=ro.vehicle_id WHERE i.id=?""",
        (invoice_id,),
    ).fetchone()
    if not invoice:
        raise NotFoundError("Không tìm thấy hóa đơn")
    ensure_record_access(db, user, invoice["customer_id"])
    rows = [dict(row) for row in db.execute(
         """SELECT ii.id,ii.kind,ii.name,ii.quantity,ii.unit_price,ii.line_total quoted_line_total,
                    ii.estimated_duration_min,
                    COALESCE(s.description,'') garage_description,qi.service_id,qi.part_id,p.code part_code
            FROM invoice_items ii
            LEFT JOIN quote_items qi ON qi.id=ii.quote_item_id AND qi.quote_id=?
            LEFT JOIN services s ON s.id=qi.service_id
            LEFT JOIN parts p ON p.id=qi.part_id
           WHERE ii.invoice_id=? ORDER BY ii.id""",
        (invoice["quote_id"], invoice_id),
    ).fetchall()]
    # Lý do chỉ lấy từ ghi nhận kiểm tra; yêu cầu khách không phải kết luận kỹ thuật.
    reason = (invoice["inspection_notes"] or "").strip()
    services = [{**row, "technician_reason": reason or None} for row in rows if row["kind"] == "Dịch vụ"]
    parts = [row for row in rows if row["kind"] == "Phụ tùng"]
    missing = []
    if not reason:
        missing.append("Kết quả kiểm tra kỹ thuật được xác nhận")
    if any(not row["garage_description"] for row in services):
        missing.append("Mô tả chi tiết một hoặc nhiều dịch vụ")
    missing.append("Thời gian và điều kiện bảo hành")
    context = {
        "vehicle": {"plate": invoice["plate"], "make": invoice["make"],
                    "model": invoice["model"], "year": invoice["year"], "km_in": invoice["km_in"],
                    "variant": invoice["variant"], "engine_code": invoice["engine_code"], "fuel_type": invoice["fuel_type"]},
        "repair_order": {"id": invoice["repair_order_id"], "code": invoice["order_code"],
                          "customer_request": invoice["customer_request"],
                          "inspection_notes": reason or None, "status_code": invoice["status_code"]},
        "invoice": {key: invoice[key] for key in
                     ("id", "code", "status", "total", "subtotal", "discount", "tax", "paid_amount", "issued_at", "estimated_duration_min")},
        "items": services, "parts": parts, "missing_data": missing,
    }
    _enrich_service_context(db, context, invoice["repair_order_id"])
    return context, dict(invoice), services, context["missing_data"]


@router.post("/invoices/{invoice_id}/service-explanation", response_model=AIResultOut)
def invoice_service_explanation(
    invoice_id: int,
    user: dict = Depends(require_permission("invoices")),
) -> dict:
    started = time.perf_counter()
    with connect() as db, transaction(db):
        context, invoice, services, missing = _service_context_by_invoice(db, invoice_id, user)
        try:
            result = ai_service.explain_services_for_customer(context)
            error_text = None
        except Exception as exc:
            error_text = str(exc)
            result = AIResult(ai_service._fallback_service_explanation(context, missing), "error", "local",
                              ai_service.model, not bool(services or context["parts"]), missing)
        _audit_ai(db, user, "explain", "invoice", str(invoice_id), result,
                  {"invoice_id": invoice_id, "item_ids": [row["id"] for row in services + context["parts"]]},
                  int((time.perf_counter() - started) * 1000), error_text)
    return {"result": result.content, "is_draft": True, "status": result.status,
             "no_data": result.no_data, "source_count": len(services) + len(context["parts"]),
             "sources": _order_sources(context), "missing_data": result.missing_data,
             "ref_id": str(invoice_id), "ref_code": invoice["code"],
             "data_status": _service_data_status(result, context)}


@router.post("/invoices/{invoice_id}/service-explanation/follow-up", response_model=AIResultOut)
def invoice_service_follow_up(
    invoice_id: int,
    item: ServiceFollowUpIn,
    user: dict = Depends(require_permission("invoices")),
) -> dict:
    started = time.perf_counter()
    with connect() as db, transaction(db):
        context, invoice, services, _ = _service_context_by_invoice(db, invoice_id, user)
        context["garage_info"] = _public_garage_info(db)
        try:
            result = ai_service.answer_service_follow_up(
                context, item.question, [turn.model_dump() for turn in item.history], user["role"])
            error_text = None
        except Exception as exc:
            error_text = str(exc)
            result = AIResult("Không thể trả lời lúc này. Vui lòng hỏi cố vấn dịch vụ.", "error", "local", ai_service.model)
        sources = _follow_up_sources(context, item.question)
        result = _require_follow_up_source(result, sources)
        _audit_ai(db, user, "explain", "invoice", str(invoice_id), result,
                  {"invoice_id": invoice_id, "question": item.question},
                  int((time.perf_counter() - started) * 1000), error_text)
    return {"result": result.content, "is_draft": True, "status": result.status,
             "no_data": result.no_data, "source_count": len(sources), "missing_data": result.missing_data,
             "sources": sources,
             "ref_id": str(invoice_id), "ref_code": invoice["code"],
             "data_status": _service_data_status(result, context)}


@router.post("/service-explanations/{order_code}", response_model=AIResultOut)
def service_explanation_by_code(
    order_code: str,
    user: dict = Depends(require_permission("dashboard")),
) -> dict:
    started = time.perf_counter()
    with connect() as db, transaction(db):
        found = db.execute("SELECT id FROM repair_orders WHERE UPPER(code)=UPPER(?)", (order_code.strip(),)).fetchone()
        if not found:
            raise NotFoundError("Không tìm thấy phiếu sửa chữa")
        context, order, items, missing = _service_context_by_order(db, found["id"], user)
        try:
            result = ai_service.explain_services_for_customer(context)
            error_text = None
        except Exception as exc:
            error_text = str(exc)
            result = AIResult(ai_service._fallback_service_explanation(context, missing), "error", "local", ai_service.model, not bool(items), missing)
        _audit_ai(db, user, "explain", "repair_order", str(order["id"]), result,
                  {"order_id": order["id"], "item_ids": [item["id"] for item in items]},
                  int((time.perf_counter()-started)*1000), error_text)
    return {"result": result.content, "is_draft": True, "status": result.status,
             "no_data": result.no_data, "source_count": len(_order_sources(context)), "missing_data": result.missing_data,
             "sources": _order_sources(context),
             "ref_id": str(order["id"]), "ref_code": order["code"],
             "data_status": _service_data_status(result, context)}


@router.post("/service-explanations/{order_code}/follow-up", response_model=AIResultOut)
def service_explanation_follow_up(
    order_code: str,
    item: ServiceFollowUpIn,
    user: dict = Depends(require_permission("dashboard")),
) -> dict:
    started = time.perf_counter()
    with connect() as db, transaction(db):
        found = db.execute("SELECT id FROM repair_orders WHERE UPPER(code)=UPPER(?)", (order_code.strip(),)).fetchone()
        if not found:
            raise NotFoundError("Không tìm thấy phiếu sửa chữa")
        context, order, items, _ = _service_context_by_order(db, found["id"], user)
        context["garage_info"] = _public_garage_info(db)
        history = [turn.model_dump() for turn in item.history]
        try:
            result = ai_service.answer_service_follow_up(context, item.question, history, user["role"])
            error_text = None
        except Exception as exc:
            error_text = str(exc)
            result = AIResult("Không thể tạo câu trả lời lúc này. Vui lòng hỏi kỹ thuật viên.", "error", "local", ai_service.model)
        sources = _follow_up_sources(context, item.question)
        result = _require_follow_up_source(result, sources)
        _audit_ai(db, user, "explain", "repair_order", str(order["id"]), result,
                  {"order_id": order["id"], "question": item.question, "history_turns": len(history)},
                  int((time.perf_counter()-started)*1000), error_text)
    return {"result": result.content, "is_draft": True, "status": result.status,
             "no_data": result.no_data, "source_count": len(sources), "missing_data": result.missing_data,
             "sources": sources,
             "ref_id": str(order["id"]), "ref_code": order["code"],
             "data_status": _service_data_status(result, context)}


@router.post("/repair-orders/{order_id}/service-explanation", response_model=AIResultOut)
def service_explanation(
    order_id: int,
    selector: ServiceExplanationIn,
    user: dict = Depends(require_permission("dashboard")),
) -> dict:
    """Giải thích dịch vụ từ phiếu/báo giá; client không được cung cấp nội dung hay giá."""
    started = time.perf_counter()
    with connect() as db, transaction(db):
        context, order, _, missing = _service_context_by_order(db, order_id, user)
        if selector.quote_id:
            quote = db.execute("SELECT id,status FROM quotes WHERE id=? AND repair_order_id=?",
                               (selector.quote_id, order_id)).fetchone()
            if not quote or (user.get("role") == "Kh?ch h?ng" and quote["status"] != "?? duy?t"):
                raise BadRequestError("B?o gi? kh?ng thu?c phi?u s?a ch?a n?y")
            if not context.get("quote") or quote["id"] != context["quote"]["id"]:
                context, order, _, missing = _service_context_by_order(db, order_id, user, quote_id=quote["id"])
        if selector.quote_item_id:
            if not context.get("quote"):
                raise BadRequestError("Kh?ng th? ch?n h?ng m?c b?o gi? khi phi?u ch?a c? b?o gi?")
            items = [item for item in context["items"] if item["id"] == selector.quote_item_id]
            if not items:
                raise BadRequestError("H?ng m?c kh?ng thu?c b?o gi? hi?n t?i ho?c kh?ng ph?i d?ch v?")
            context["items"] = items
            context["parts"] = []
            context["subtotal_mismatch"] = False  # only a subset of the quote is shown
            context["selected_item_only"] = True
        items = context["items"] + context["parts"]
        quote = context.get("quote")
        error_text = None
        try:
            result = ai_service.explain_services_for_customer(context)
        except Exception as exc:
            error_text = str(exc)
            result = AIResult(ai_service._fallback_service_explanation(context, missing), "error",
                              "local", ai_service.model, not bool(items), missing)
        _audit_ai(db, user, "explain", "repair_order", str(order_id), result,
                  {"order_id": order_id, "quote_id": quote["id"] if quote else None,
                   "item_ids": [item["id"] for item in items]},
                  int((time.perf_counter() - started) * 1000), error_text)
    return {"result": result.content, "is_draft": True, "status": result.status,
             "no_data": result.no_data, "source_count": len(_order_sources(context)),
             "sources": _order_sources(context), "missing_data": result.missing_data,
             "data_status": _service_data_status(result, context),
             "ref_id": str(order_id), "ref_code": order["code"]}


@router.post("/generate", response_model=AIResultOut, deprecated=True)
def ai_generate(request_body: AIRequest, user: dict = Depends(require_permission("dashboard"))) -> dict:
    """Endpoint cũ chỉ còn cho diễn giải; summary/estimate phải dùng endpoint theo bản ghi."""
    if request_body.task in ("summary", "estimate"):
        raise BadRequestError(
            "Tác vụ này phải dùng endpoint theo xe/phiếu để backend kiểm soát dữ liệu nghiệp vụ"
        )
    result = ai_service.explain(request_body.data)
    with connect() as db, transaction(db):
        _audit_ai(db, user, str(request_body.task.value), request_body.ref_type,
                  request_body.ref_id, result, request_body.data, 0)
    return {"result": result.content, "is_draft": True, "status": result.status}
