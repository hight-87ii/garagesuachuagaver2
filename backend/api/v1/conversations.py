"""Hội thoại bền vững: chỉ backend đọc lịch sử theo chủ tài khoản và cấp nguồn cho AI."""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, Request

from ...ai_service import ai_service
from ...chat_pipeline import answer_chat
from ...conversation_context import context_window, summarize
from ...core.access import ensure_record_access
from ...core.audit import write_audit
from ...core.db import connect, normalize_plate, transaction
from ...core.deps import client_ip, require_permission
from ...core.errors import AppError, BadRequestError, ConflictError, NotFoundError
from ...schemas.ai import ConversationCreateIn, ConversationMessageIn
from ...timeutil import now_utc_iso
from .ai import _audit_ai

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
                     (user_row["id"],)).fetchone()[0] < 180:
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
        with connect() as db:
            _owned(db, conversation_id, user)
            previous = [dict(row) for row in db.execute(
                "SELECT * FROM ai_messages WHERE conversation_id=? AND id<? AND status='completed' ORDER BY id",
                (conversation_id, user_row["id"]),
            ).fetchall()]
        state = summarize([*previous, {"role": "user", "content": item.question, "status": "completed"}])
        output = answer_chat(item.question, user, vehicle_id=conversation["vehicle_id"],
                             history=context_window(previous), state=state, trusted_history=True)
        resolved, result = output.answer, output.result
        if resolved.status == "error" and not output.general_knowledge:
            raise RuntimeError("AI không phản hồi")
        next_state = {**state, **output.state_update}
        if output.product_ids:
            previous_ids = state.get("product_ids") or []
            keep_group = (output.state_update.get("product_ids") != [] and previous_ids and
                          all(pid in previous_ids for pid in output.product_ids))
            next_state.update({"product_ids": previous_ids if keep_group else output.product_ids[:8],
                               "topic": "parts"})
        if output.suggestions:
            snapshots = {entry["part_id"]: entry for entry in next_state.get("price_snapshots") or []}
            for entry in output.suggestions:
                if entry["kind"] == "part":
                    snapshots[entry["id"]] = {"part_id": entry["id"], "price_at_time": entry["price"],
                                              "recorded_at": now_utc_iso()}
            next_state["price_snapshots"] = list(snapshots.values())[-8:]
        with connect() as db, transaction(db):
            _owned(db, conversation_id, user)
            existing = db.execute("SELECT * FROM ai_messages WHERE in_reply_to=?", (user_row["id"],)).fetchone()
            if existing:
                return _reply_body(conversation_id, user_row, dict(existing))
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
