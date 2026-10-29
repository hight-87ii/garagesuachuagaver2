"""Shared read-only chat orchestration; endpoint adapters own persistence/audit.

Only a server-created conversation state can resolve part references. Client-supplied
history is language context, never evidence for prices, ownership or permissions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .ai_service import AIResult, ai_service
from .appointment_chat import pending_appointments_reply
from .appointment_load import answer_appointment_load, is_load_question
from .conversation_context import (resolve_follow_up, summarize,
                                   update_technical_context)
from .core.access import ensure_record_access
from .core.db import connect, normalize_plate, transaction
from .core.errors import BadRequestError, NotFoundError
from .customer_visit_analytics import answer_customer_visit_question
from .dynamic_query import answer_dynamic_query
from .inventory_query import (answer_catalog_parts_question, answer_inventory_question,
                              answer_part_price_question, is_inventory_question)
from .invoice_query import answer_invoice_question
from .maintenance_interval import (answer_maintenance_interval,
                                   is_maintenance_interval_question)
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
    if (analysis and analysis["intent"] == "tire_price" and
            re.search(r"\b(?:gia|bao nhieu|tien)\b", ai_service._normalize_vi(question)) and
            re.search(r"\bvo banh\b", ai_service._normalize_vi(question))):
        question = re.sub(r"\bvỏ\s+bánh\b", "lốp", question, flags=re.I)
    # Client history is useful for language, but never for server-only follow-up
    # decisions. State comes solely from persisted conversation metadata.
    if trusted_history and state:
        state = state
    else:
        # Legacy chat được phép dùng lịch sử để hiểu ngôn ngữ, nhưng summarize
        # không lấy lịch sử client làm bằng chứng giá/quyền/xe.
        state = summarize([{"role": turn["role"], "content": turn["text"],
                            "status": "completed"} for turn in history]) if history else {}
        state["product_ids"] = []
        state["price_snapshots"] = []
    with connect() as db, transaction(db):
        visit = answer_customer_visit_question(db, question, user)
        early_inventory = (answer_inventory_question(db, question, user)
                           if visit is None and is_inventory_question(question) else None)
        if early_inventory and early_inventory[0].status == "denied":
            answer, sources = early_inventory
            body = _body(answer, sources, [], is_draft=False)
            return ChatOutput(body, answer)
        vehicle = None
        if vehicle_id or plate:
            vehicle = db.execute(
                "SELECT * FROM vehicles WHERE id=?" if vehicle_id else
                "SELECT * FROM vehicles WHERE plate_normalized=? ORDER BY id LIMIT 1",
                (vehicle_id if vehicle_id else normalize_plate(plate or ""),),
            ).fetchone()
            if not vehicle:
                raise NotFoundError("Không tìm thấy xe")
            ensure_record_access(db, user, vehicle["customer_id"])
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
        inventory = (answer_inventory_question(db, question, user, dict(vehicle) if vehicle else None)
                     if visit is None and is_inventory_question(question) else None)
        price = (answer_part_price_question(db, question, user, dict(vehicle) if vehicle else None)
                  if visit is None and inventory is None else None)
        catalog_parts = (answer_catalog_parts_question(db, question, user)
                         if visit is None and inventory is None and price is None else None)
        personal_maintenance = any(term in ai_service._normalize_vi(question) for term in (
            "xe toi", "xe cua toi", "xe minh", "lan truoc", "da thay", "tu lan", "km hien tai"))
        maintenance = (answer_maintenance_interval(db, question, dict(vehicle) if vehicle else None)
                       if visit is None and inventory is None and price is None and catalog_parts is None
                       and (vehicle is not None or personal_maintenance)
                       and is_maintenance_interval_question(question) else None)
        plan = (answer_maintenance_plan(db, question, vehicle)
                if visit is None and inventory is None and price is None and catalog_parts is None and maintenance is None else None)
        parts = [dict(row) for row in db.execute(
            "SELECT id,code,name,category,compatible,unit,sell_price,stock FROM parts WHERE active=1 ORDER BY name"
        )] if visit is None and inventory is None and price is None and catalog_parts is None and maintenance is None else []
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
                inventory is None and price is None and catalog_parts is None and maintenance is None and plan is None and is_load_question(question) else None)
        dynamic = (answer_dynamic_query(db, question, user) if
                   visit is None and inventory is None and price is None and catalog_parts is None and maintenance is None and plan is None and load is None else None)
        hours, hours_sources = ((None, []) if any((visit, inventory, price, catalog_parts, maintenance, plan, load, dynamic)) else
                                 _garage_hours_reply(question))
        appointment = (pending_appointments_reply(db, question, user) if
                         all(value is None for value in (visit, inventory, price, catalog_parts, maintenance, plan, load, dynamic, hours)) else None)
        vehicles_reply = (customer_vehicles_reply(db, question, user) if
                         all(value is None for value in (visit, inventory, price, catalog_parts, maintenance, plan, load, dynamic, hours, appointment)) else None)
        invoice = (answer_invoice_question(db, user, question) if
                     all(value is None for value in (visit, inventory, price, catalog_parts, maintenance, plan, load, dynamic, hours, appointment, vehicles_reply)) else None)
        replacement = ( _indicator_replacement_reply(db, question, vehicle, parts, user,
                         history if trusted_history else []) if
                           all(value is None for value in (visit, inventory, price, catalog_parts, maintenance, plan, load, dynamic, hours, appointment, vehicles_reply, invoice)) else None)
        catalog = (replacement or _catalog_service_reply(db, question, history) if
                     all(value is None for value in (visit, inventory, price, catalog_parts, maintenance, plan, load, dynamic, hours, appointment, vehicles_reply, invoice)) else None)
        if catalog is not None and catalog[0] is None:
            catalog = None

    # Model classification and generation never hold a write transaction open.
    selected = next((entry for entry in (visit, inventory, price, catalog_parts, maintenance, plan, load, dynamic,
        (hours, hours_sources) if hours else None,
        (AIResult(invoice["content"], invoice["status"], "local", ai_service.model,
                  invoice["status"] == "no_data"), invoice["sources"]) if invoice else None,
        appointment, vehicles_reply, catalog) if entry is not None), None)
    general = False
    state_update: dict = {}
    technical_sources: list[dict] = []
    if selected is not None:
        answer, sources = (selected.result, selected.sources) if visit is not None else selected
    else:
        # A semantic pre-classifier would consume a second model call before
        # generation. Deterministic intent/clarification runs first instead.
        technical_question, clarification, semantic = _technical_route(
            question, history, allow_semantic=False)
        text = ai_service._normalize_vi(technical_question)
        previous_technical = state.get("technical_context") or {}
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
        rag_question = technical_question
        if technical_turn and technical_context.get("symptom"):
            facts = [fact for fact in technical_context.get("known_facts", [])
                     if fact and not fact.startswith("mâu thuẫn")]
            if facts:
                # Chỉ ghép facts do khách nói; không ghép kết luận hoặc tên
                # bộ phận do Ollama suy đoán.
                rag_question = technical_question + " " + "; ".join(facts[-6:])
        business = re.search(r"\b(?:gia|bao nhieu|ton kho|kho|con hang|hoa don|lich hen|"
                             r"bao gia|lich su|da sua|xe toi|xe cua toi)\b", text)
        general = _general_knowledge_question(technical_question) or (
            not business and _is_technical_question(technical_question))
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
            except Exception:
                # A broken knowledge index is not evidence that no source exists.
                articles, technical_sources, lookup_failed = [], [], True
            try:
                if lookup_failed:
                    answer = AIResult("Chưa thể kiểm tra tài liệu lúc này. Vui lòng thử lại sau.",
                                      "error", "local", ai_service.model)
                elif articles:
                    answer = ai_service.answer_technical(rag_question, articles, user["role"])
                elif general:
                    answer = ai_service.answer_general_knowledge(technical_question, user["role"], history)
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
                                history, user["role"], garage_info,
                                conversation_summary=effective_state)
                            # Không coi câu do model tự sinh là nguồn nghiệp vụ.
                            general = answer.status == "success" and not business
                sources = technical_sources
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
    if (selected is None and general and answer.status == "success" and not sources
            and not answer.content.startswith("Thông tin dưới đây là kiến thức tham khảo")):
        answer = AIResult("Thông tin dưới đây là kiến thức tham khảo, chưa có dữ liệu xác minh từ garage.\n"
                          + answer.content, answer.status, answer.provider, answer.model,
                          answer.no_data, answer.missing_data)
    # No sources are needed for clarifying questions, safety guidance, or
    # general automotive knowledge without a garage/vehicle claim.
    sourced_route = selected is not None
    if (not sources and not sourced_route and answer.status not in ("error", "clarification", "safety")
            and not answer.no_data
            and not (general and answer.status == "success")):
        answer = AIResult("Chưa có dữ liệu đủ căn cứ cho câu trả lời này. "
                          "Vui lòng hỏi cố vấn dịch vụ hoặc kỹ thuật viên để xác minh.",
                          "no_data", "local", ai_service.model, True, ["Nguồn dữ liệu phù hợp"])
    with connect() as db:
        suggestions = (_assistant_appointment_items(db, answer.content, sources, parts)
                       if user["role"] == "Khách hàng" and replacement is None and sources
                       and answer.status not in ("error", "no_data", "clarification", "safety") else [])
    body = _body(answer, sources, suggestions, is_draft=visit is None)
    if visit is not None and visit.analytics is not None:
        body["analytics"] = visit.analytics
    product_ids = [src["id"] for src in sources if src["type"] == "part"]
    return ChatOutput(body, answer, state_update, product_ids, suggestions,
                      vehicle["id"] if vehicle else None, general and not technical_sources)


def _body(answer: AIResult, sources: list[dict], suggestions: list[dict], *, is_draft: bool) -> dict:
    return {"result": answer.content, "status": answer.status, "is_draft": is_draft,
            "no_data": answer.no_data, "missing_data": answer.missing_data,
            "sources": sources, "source_count": len(sources), "suggested_items": suggestions}
