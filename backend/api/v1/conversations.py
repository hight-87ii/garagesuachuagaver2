"""Hội thoại bền vững: chỉ backend đọc lịch sử theo chủ tài khoản và cấp nguồn cho AI."""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, Request

from ...ai_service import AIResult, ai_service
from ...appointment_chat import pending_appointments_reply
from ...appointment_load import answer_appointment_load, is_load_question
from ...conversation_context import context_window, resolve_follow_up, summarize
from ...core.access import ensure_record_access
from ...core.audit import write_audit
from ...core.db import connect, normalize_plate, transaction
from ...core.deps import client_ip, require_permission
from ...core.errors import AppError, BadRequestError, ConflictError, NotFoundError
from ...dynamic_query import answer_dynamic_query
from ...customer_visit_analytics import answer_customer_visit_question
from ...schemas.ai import ConversationCreateIn, ConversationMessageIn
from ...invoice_query import answer_invoice_question
from ...inventory_query import answer_inventory_question, is_inventory_question
from ...timeutil import now_utc_iso
from ...vehicle_chat import customer_vehicles_reply
from .ai import (_assistant_appointment_items, _assistant_sources, _audit_ai,
                   _catalog_service_reply, _garage_hours_reply, _public_garage_info,
                   _technical_references, _vehicle_context)

router = APIRouter(prefix="/ai/conversations", tags=["AI Conversations"])


def _owned(db, conversation_id: int, user: dict) -> dict:
    row = db.execute("SELECT * FROM ai_conversations WHERE id=? AND user_id=?",
                     (conversation_id, user["id"])).fetchone()
    if not row:
        raise NotFoundError("Không tìm thấy cuộc trò chuyện")
    if row["vehicle_id"]:
        vehicle = db.execute("SELECT customer_id FROM vehicles WHERE id=?", (row["vehicle_id"],)).fetchone()
        if vehicle:
            ensure_record_access(db, user, vehicle["customer_id"])
    return dict(row)


def _message(row: dict) -> dict:
    meta = json.loads(row.get("metadata") or "{}")
    return {"id": row["id"], "role": row["role"], "content": row["content"],
            "status": row["status"], "request_id": row["request_id"],
            "created_at": row["created_at"], "result": meta.get("result") if row["role"] == "assistant" else None}


@router.get("")
def list_conversations(user: dict = Depends(require_permission("dashboard"))) -> list[dict]:
    with connect() as db:
        rows = db.execute("""SELECT c.id,c.title,c.status,c.vehicle_id,v.plate vehicle_plate,
                                   c.created_at,c.updated_at
                            FROM ai_conversations c LEFT JOIN vehicles v ON v.id=c.vehicle_id
                            WHERE c.user_id=? ORDER BY c.updated_at DESC,c.id DESC""",
                          (user["id"],)).fetchall()
        return [dict(row) for row in rows]


@router.post("", status_code=201)
def create_conversation(item: ConversationCreateIn,
                        user: dict = Depends(require_permission("dashboard"))) -> dict:
    if item.vehicle_id and item.plate:
        raise BadRequestError("Chỉ chọn một xe hoặc nhập một biển số")
    with connect() as db, transaction(db):
        vehicle_id = None
        if item.vehicle_id or item.plate:
            vehicle = db.execute(
                "SELECT id,customer_id FROM vehicles WHERE id=?" if item.vehicle_id else
                "SELECT id,customer_id FROM vehicles WHERE plate_normalized=? ORDER BY id LIMIT 1",
                (item.vehicle_id if item.vehicle_id else normalize_plate(item.plate or ""),),
            ).fetchone()
            if not vehicle:
                raise NotFoundError("Không tìm thấy xe")
            ensure_record_access(db, user, vehicle["customer_id"])
            vehicle_id = vehicle["id"]
        db.execute("""INSERT OR IGNORE INTO ai_conversations(user_id,vehicle_id,client_key)
                      VALUES(?,?,?)""", (user["id"], vehicle_id, item.client_key))
        row = db.execute("SELECT * FROM ai_conversations WHERE user_id=? AND client_key=?",
                         (user["id"], item.client_key)).fetchone()
        if row["vehicle_id"] != vehicle_id:
            raise ConflictError("Khóa tạo hội thoại đã được dùng cho xe khác")
        return {key: row[key] for key in ("id", "title", "status", "vehicle_id", "created_at", "updated_at")}


@router.get("/{conversation_id}")
def conversation_detail(conversation_id: int,
                        user: dict = Depends(require_permission("dashboard"))) -> dict:
    with connect() as db:
        conversation = _owned(db, conversation_id, user)
        vehicle = (db.execute("SELECT plate FROM vehicles WHERE id=?", (conversation["vehicle_id"],)).fetchone()
                   if conversation["vehicle_id"] else None)
        rows = [dict(row) for row in db.execute(
            "SELECT * FROM ai_messages WHERE conversation_id=? ORDER BY id", (conversation_id,)
        ).fetchall()]
    return {**{key: conversation[key] for key in
               ("id", "title", "status", "vehicle_id", "created_at", "updated_at")},
            "vehicle_plate": vehicle["plate"] if vehicle else None,
            "messages": [_message(row) for row in rows]}


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: int, request: Request,
                        user: dict = Depends(require_permission("dashboard"))) -> dict:
    with connect() as db, transaction(db):
        _owned(db, conversation_id, user)
        db.execute("DELETE FROM ai_conversations WHERE id=? AND user_id=?", (conversation_id, user["id"]))
        write_audit(db, user, "ai.conversation.delete", "ai_conversations", conversation_id,
                    {"scope": "one_conversation"}, client_ip(request))
    return {"id": conversation_id, "deleted": True}


def _reply_body(conversation_id: int, user_row: dict, assistant_row: dict) -> dict:
    metadata = json.loads(assistant_row["metadata"] or "{}")
    return {"conversation_id": conversation_id, "user_message": _message(user_row),
            "assistant_message": _message(assistant_row), "result": metadata["result"]}


@router.post("/{conversation_id}/messages")
def send_message(conversation_id: int, item: ConversationMessageIn,
                 user: dict = Depends(require_permission("dashboard"))) -> dict:
    started = time.perf_counter()
    with connect() as db, transaction(db):
        conversation = _owned(db, conversation_id, user)
        if conversation["status"] != "active":
            raise BadRequestError("Cuộc trò chuyện đã được lưu trữ")
        found = db.execute("SELECT * FROM ai_messages WHERE conversation_id=? AND request_id=? AND role='user'",
                           (conversation_id, item.request_id)).fetchone()
        if found:
            user_row = dict(found)
            if user_row["content"] != item.question:
                raise ConflictError("Mã yêu cầu đã được dùng cho câu hỏi khác")
            assistant = db.execute("SELECT * FROM ai_messages WHERE in_reply_to=?", (user_row["id"],)).fetchone()
            if assistant:
                return _reply_body(conversation_id, user_row, dict(assistant))
            if user_row["status"] == "pending" and db.execute(
                    "SELECT (julianday('now')-julianday(created_at))*86400 FROM ai_messages WHERE id=?",
                    (user_row["id"],)).fetchone()[0] < 30:
                raise ConflictError("Câu hỏi đang được xử lý; vui lòng chờ rồi thử lại")
            db.execute("UPDATE ai_messages SET status='pending',created_at=? WHERE id=?",
                       (now_utc_iso(), user_row["id"]))
        else:
            if db.execute("""SELECT 1 FROM ai_messages WHERE conversation_id=? AND role='user'
                              AND status='pending' LIMIT 1""", (conversation_id,)).fetchone():
                raise ConflictError("Hãy chờ câu trả lời hiện tại trước khi gửi câu hỏi tiếp theo")
            cursor = db.execute("""INSERT INTO ai_messages(conversation_id,role,content,status,request_id)
                                   VALUES(?,'user',?,'pending',?)""",
                                (conversation_id, item.question, item.request_id))
            user_row = dict(db.execute("SELECT * FROM ai_messages WHERE id=?", (cursor.lastrowid,)).fetchone())
            if conversation["title"] == "Cuộc trò chuyện mới":
                title = item.question[:75].strip() + ("…" if len(item.question) > 75 else "")
                db.execute("UPDATE ai_conversations SET title=?,updated_at=? WHERE id=?",
                           (title, now_utc_iso(), conversation_id))

    try:
        with connect() as db, transaction(db):
            _owned(db, conversation_id, user)
            visit_reply = answer_customer_visit_question(db, item.question, user)
            early_inventory = (answer_inventory_question(db, item.question, user)
                               if visit_reply is None and is_inventory_question(item.question) else None)
            previous = [dict(row) for row in db.execute(
                "SELECT * FROM ai_messages WHERE conversation_id=? AND id<? AND status='completed' ORDER BY id",
                (conversation_id, user_row["id"]),
            ).fetchall()]
            state = summarize([*previous, {"role": "user", "content": item.question, "status": "completed"}])
            vehicle = (db.execute("SELECT * FROM vehicles WHERE id=?", (conversation["vehicle_id"],)).fetchone()
                       if conversation["vehicle_id"] and visit_reply is None else None)
            context = _vehicle_context(db, vehicle, user["role"] != "Khách hàng") if vehicle else None
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
            inventory_reply = (answer_inventory_question(db, item.question, user, dict(vehicle) if vehicle else None)
                               if is_inventory_question(item.question) and (not early_inventory or early_inventory[0].status != "denied")
                               else early_inventory) if visit_reply is None else None
            parts = [dict(row) for row in db.execute(
                "SELECT id,code,name,category,compatible,unit,sell_price,stock FROM parts WHERE active=1 ORDER BY name"
            ).fetchall()] if visit_reply is None and inventory_reply is None else []
            rules = (db.execute("SELECT part_id,make,model,year_from,year_to,variant,engine_code,fuel_type,note "
                                "FROM part_fitments ORDER BY id").fetchall()
                     if visit_reply is None and inventory_reply is None else [])
            for part in parts:
                part["fitments"] = [dict(rule) for rule in rules if rule["part_id"] == part["id"]]
            garage_info = _public_garage_info(db) if visit_reply is None else {}
            load_reply = (answer_appointment_load(db, item.question, user) if visit_reply is None and not inventory_reply and is_load_question(item.question) else None)
            dynamic_reply = None if visit_reply is not None or inventory_reply or load_reply else answer_dynamic_query(db, item.question, user)
            hours_result, hours_sources = ((None, []) if visit_reply is not None or inventory_reply or load_reply or dynamic_reply is not None
                                           else _garage_hours_reply(item.question))
            appointment_reply = (None if visit_reply is not None or inventory_reply or load_reply or dynamic_reply is not None or hours_result is not None
                                  else pending_appointments_reply(db, item.question, user))
            vehicle_reply = None if visit_reply is not None or inventory_reply or load_reply or appointment_reply is not None or dynamic_reply is not None or hours_result is not None else customer_vehicles_reply(db, item.question, user)
            invoice_answer = None if visit_reply is not None or inventory_reply or load_reply or vehicle_reply is not None or appointment_reply is not None or dynamic_reply is not None or hours_result is not None else answer_invoice_question(db, user, item.question)
            catalog_result, catalog_sources = (None, []) if visit_reply is not None or inventory_reply or load_reply or dynamic_reply or hours_result or appointment_reply or vehicle_reply or invoice_answer is not None else _catalog_service_reply(
                db, item.question, [{"role": row["role"], "text": row["content"]} for row in previous[-8:]])
            technical_articles, technical_sources = ([], []) if visit_reply is not None or inventory_reply or load_reply or catalog_result or dynamic_reply or hours_result or appointment_reply or vehicle_reply or invoice_answer else _technical_references(
                db, item.question, vehicle)
        # Nhà cung cấp AI chạy NGOÀI transaction: không khóa SQLite khi chờ mạng.
        if visit_reply is not None:
            resolved, state_update = visit_reply.result, {}
        elif inventory_reply is not None:
            resolved, state_update = inventory_reply[0], {}
        elif load_reply is not None:
            resolved, state_update = load_reply[0], {}
        elif dynamic_reply is not None:
            resolved, state_update = dynamic_reply[0], {}
        elif hours_result is not None:
            resolved, state_update = hours_result, {}
        elif invoice_answer is not None:
            resolved = AIResult(invoice_answer["content"], invoice_answer["status"], "local",
                                ai_service.model, invoice_answer["status"] == "no_data")
            state_update = {}
        elif appointment_reply is not None:
            resolved, state_update = appointment_reply[0], {}
        elif vehicle_reply is not None:
            resolved, state_update = vehicle_reply[0], {}
        elif catalog_result is not None:
            resolved, state_update = catalog_result, {}
        elif technical_articles:
            resolved, state_update = ai_service.answer_technical(item.question, technical_articles, user["role"]), {}
        else:
            resolved, state_update = resolve_follow_up(ai_service, item.question, state, context, parts)
            if resolved is None:
                resolved = ai_service.answer_assistant(item.question, context, parts,
                    context_window(previous), user["role"], garage_info, conversation_summary=state)
        with connect() as db:
            sources = (visit_reply.sources if visit_reply is not None else
                        inventory_reply[1] if inventory_reply is not None else
                        load_reply[1] if load_reply is not None else
                        dynamic_reply[1] if dynamic_reply is not None else
                       hours_sources if hours_result is not None else
                       invoice_answer["sources"] if invoice_answer is not None else
                       appointment_reply[1] if appointment_reply is not None else
                       vehicle_reply[1] if vehicle_reply is not None else
                       technical_sources if technical_articles else
                       _assistant_sources(db, item.question, resolved.content, vehicle, context, parts, garage_info))
            sources.extend(catalog_sources)
            if (not sources and visit_reply is None and inventory_reply is None and load_reply is None and dynamic_reply is None and hours_result is None and appointment_reply is None and vehicle_reply is None and invoice_answer is None and
                    resolved.status not in ("error", "clarification", "safety")):
                resolved = AIResult("Chưa có dữ liệu đủ căn cứ cho câu trả lời này. "
                                    "Bạn cần xác minh thông tin nào trước?", "clarification", "local",
                                    ai_service.model, True, ["Nguồn dữ liệu phù hợp"])
            suggestions = (_assistant_appointment_items(db, resolved.content, sources, parts)
                           if user["role"] == "Khách hàng" and sources and
                           resolved.status not in ("error", "no_data", "clarification", "safety") else [])
            product_ids = [source["id"] for source in sources if source["type"] == "part"]
            next_state = {**state, **state_update}
            if product_ids:
                previous_ids = state.get("product_ids") or []
                # Trả giá riêng "cái thứ hai" không làm mất thứ tự hai lựa chọn ban đầu.
                keep_group = (state_update.get("product_ids") != [] and previous_ids and
                              all(pid in previous_ids for pid in product_ids))
                next_state.update({"product_ids": previous_ids if keep_group else product_ids[:8],
                                   "topic": "parts"})
            if resolved.status == "error":
                raise RuntimeError("AI không phản hồi")
            result = {"result": resolved.content, "status": resolved.status, "is_draft": True,
                      "no_data": resolved.no_data, "missing_data": resolved.missing_data,
                       "sources": sources, "source_count": len(sources), "suggested_items": suggestions}
            if visit_reply is not None:
                result["is_draft"] = False
                if visit_reply.analytics is not None:
                    result["analytics"] = visit_reply.analytics
            if suggestions:
                snapshots = {entry["part_id"]: entry for entry in next_state.get("price_snapshots") or []}
                for entry in suggestions:
                    if entry["kind"] == "part":
                        snapshots[entry["id"]] = {"part_id": entry["id"], "price_at_time": entry["price"],
                                                  "recorded_at": now_utc_iso()}
                next_state["price_snapshots"] = list(snapshots.values())[-8:]
        with connect() as db, transaction(db):
            _owned(db, conversation_id, user)
            cursor = db.execute("""INSERT INTO ai_messages(conversation_id,role,content,status,in_reply_to,metadata)
                                   VALUES(?,'assistant',?,'completed',?,?)""",
                                (conversation_id, resolved.content, user_row["id"],
                                 json.dumps({"result": result, "context": next_state}, ensure_ascii=False)))
            db.execute("UPDATE ai_messages SET status='completed' WHERE id=?", (user_row["id"],))
            db.execute("UPDATE ai_conversations SET context_summary=?,updated_at=? WHERE id=?",
                       (json.dumps(next_state, ensure_ascii=False), now_utc_iso(), conversation_id))
            _audit_ai(db, user, "other", "ai_conversation", str(conversation_id), resolved,
                      {"request_id": item.request_id, "vehicle_id": conversation["vehicle_id"]},
                      int((time.perf_counter()-started)*1000))
            assistant_row = dict(db.execute("SELECT * FROM ai_messages WHERE id=?", (cursor.lastrowid,)).fetchone())
            user_row = dict(db.execute("SELECT * FROM ai_messages WHERE id=?", (user_row["id"],)).fetchone())
        return _reply_body(conversation_id, user_row, assistant_row)
    except Exception as exc:
        with connect() as db, transaction(db):
            db.execute("UPDATE ai_messages SET status='failed' WHERE id=? AND status='pending'",
                       (user_row["id"],))
        raise AppError("Không thể trả lời hoặc lưu tin nhắn. Tin nhắn của bạn đã được giữ lại; hãy thử lại.",
                       code="ai_message_failed", status_code=503) from exc
