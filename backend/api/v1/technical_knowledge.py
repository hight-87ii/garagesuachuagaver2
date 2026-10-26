"""Quản lý bài kỹ thuật: nhân viên soạn nháp, quản lý duyệt trước khi chat tra cứu."""

import hashlib
import json
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal

from ...core.audit import write_audit
from ...core.db import connect, transaction
from ...core.deps import client_ip, require_permission
from ...core.errors import BadRequestError, ConflictError, NotFoundError
from ...timeutil import now_utc_iso
from ...technical_documents import MAX_UPLOAD_BYTES, extract_document, index_article_chunks

router = APIRouter(prefix="/ai/technical-articles", tags=["Technical knowledge"])


class ArticleIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=5, max_length=180)
    symptoms: str = Field(min_length=3, max_length=800, description="Từ khóa, cách gọi khác của triệu chứng")
    content: str = Field(min_length=30, max_length=8000, description="Khả năng cần kiểm tra và câu hỏi làm rõ; không khẳng định chẩn đoán")
    safety: str = Field(default="", max_length=1000)
    source_name: str = Field(min_length=3, max_length=200)
    source_url: str = Field(default="", max_length=500)
    document_version: str = Field(default="", max_length=80)
    vehicle_make: str = Field(default="", max_length=80)
    vehicle_model: str = Field(default="", max_length=80)
    year_from: int | None = Field(default=None, ge=1950, le=2100)
    year_to: int | None = Field(default=None, ge=1950, le=2100)
    engine_code: str = Field(default="", max_length=80)
    safety_level: Literal["low", "medium", "high", "critical"] = "medium"
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def check_applicability(self):
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("Năm bắt đầu không thể lớn hơn năm kết thúc")
        if self.vehicle_model and not self.vehicle_make:
            raise ValueError("Cần nhập hãng xe khi giới hạn dòng xe")
        if self.engine_code and (not self.vehicle_make or not self.vehicle_model):
            raise ValueError("Cần nhập hãng và dòng xe khi giới hạn mã động cơ")
        return self


def _row(db, article_id: int) -> dict:
    article = db.execute("""SELECT a.*,u.full_name technical_reviewer_name,
        d.filename document_filename,d.uploaded_at document_uploaded_at,
        (SELECT COUNT(*) FROM technical_chunks c WHERE c.article_id=a.id) chunk_count
        FROM technical_articles a LEFT JOIN users u ON u.id=a.technical_reviewed_by
        LEFT JOIN technical_documents d ON d.article_id=a.id WHERE a.id=? AND a.deleted_at IS NULL""",
                         (article_id,)).fetchone()
    if not article:
        raise NotFoundError("Không tìm thấy bài kỹ thuật")
    return dict(article)


def _check_revision(article: dict, expected: int | None):
    if expected is not None and article["revision"] != expected:
        raise ConflictError("Bài đã thay đổi ở phiên làm việc khác. Hãy tải lại trước khi thao tác.")


def _history(db, article: dict, action: str, user: dict, reason: str = "") -> None:
    doc = db.execute("SELECT filename,mime_type,sha256,data FROM technical_documents WHERE article_id=?",
                     (article["id"],)).fetchone()
    db.execute("""INSERT INTO technical_article_history
        (article_id,revision,action,actor_id,reason,snapshot,document_filename,document_mime,document_sha256,document_data)
        VALUES(?,?,?,?,?,?,?,?,?,?)""", (article["id"], article["revision"], action, user["id"], reason,
        json.dumps({k: v for k, v in article.items() if k not in ("document_filename", "chunk_count")}, ensure_ascii=False),
        doc["filename"] if doc else None, doc["mime_type"] if doc else None,
        doc["sha256"] if doc else None, doc["data"] if doc else None))


def _stats(db):
    row = db.execute("""SELECT COUNT(*) total,
      SUM(CASE WHEN status='draft' THEN 1 ELSE 0 END) draft,
      SUM(CASE WHEN status='draft' AND technical_reviewed_by IS NULL AND withdrawn_at IS NULL THEN 1 ELSE 0 END) pending_technical,
      SUM(CASE WHEN status='draft' AND technical_reviewed_by IS NOT NULL AND withdrawn_at IS NULL THEN 1 ELSE 0 END) pending_publish,
      SUM(CASE WHEN status='published' THEN 1 ELSE 0 END) published,
      SUM(CASE WHEN withdrawn_at IS NOT NULL AND status='draft' THEN 1 ELSE 0 END) withdrawn,
      SUM(CASE WHEN TRIM(source_name)='' OR TRIM(document_version)='' THEN 1 ELSE 0 END) source_warning
      FROM technical_articles WHERE deleted_at IS NULL""").fetchone()
    return {key: row[key] or 0 for key in row.keys()}


@router.get("")
def list_articles(
    page: int | None = Query(default=None, ge=1), page_size: int = Query(default=20, ge=1, le=50),
    q: str = Query(default="", max_length=160), status: str = Query(default=""),
    review: str = Query(default=""), safety_level: str = Query(default=""),
    vehicle_make: str = Query(default="", max_length=80), vehicle_model: str = Query(default="", max_length=80),
    technical_reviewer: int | None = Query(default=None, gt=0), publisher: int | None = Query(default=None, gt=0),
    has_document: bool | None = None, has_source: bool | None = None,
    updated_since: str = Query(default="", max_length=10), sort: str = Query(default="priority"),
    user: dict = Depends(require_permission("repair_orders")),
):
    with connect() as db:
        # Preserve the legacy array response for existing integrations; the management UI
        # always passes page and receives metadata without full content or document blobs.
        if page is None:
            return [dict(row) for row in db.execute("""SELECT a.*,u.full_name technical_reviewer_name,
             d.filename document_filename,d.uploaded_at document_uploaded_at,
             (SELECT COUNT(*) FROM technical_chunks c WHERE c.article_id=a.id) chunk_count
             FROM technical_articles a LEFT JOIN users u ON u.id=a.technical_reviewed_by
             LEFT JOIN technical_documents d ON d.article_id=a.id WHERE a.deleted_at IS NULL
             ORDER BY a.id DESC LIMIT 200""")]
        if status not in ("", "draft", "published", "pending_technical", "pending_publish", "withdrawn", "source_warning") or review not in ("", "reviewed", "unreviewed") or safety_level not in ("", "low", "medium", "high", "critical") or sort not in ("priority", "recent", "title"):
            raise BadRequestError("Bộ lọc hoặc thứ tự không hợp lệ")
        where = ["a.deleted_at IS NULL"]
        params = []
        if q.strip():
            where.append("(" + " OR ".join(f"instr(vi_fold({field}),vi_fold(?))>0" for field in
                         ("a.title", "a.symptoms", "a.vehicle_make", "a.vehicle_model", "a.engine_code", "a.source_name", "CAST(a.id AS TEXT)")) + ")")
            params.extend([q.strip()] * 7)
        if status == "source_warning":
            where.append("(TRIM(a.source_name)='' OR TRIM(a.document_version)='')")
        elif status == "withdrawn":
            where.append("a.status='draft' AND a.withdrawn_at IS NOT NULL")
        elif status in ("pending_technical", "pending_publish"):
            where.append("a.status='draft' AND a.withdrawn_at IS NULL AND a.technical_reviewed_by IS " +
                         ("NULL" if status == "pending_technical" else "NOT NULL"))
        elif status:
            where.append("a.status=?"); params.append(status)
        if review:
            where.append("a.technical_reviewed_by IS " + ("NOT NULL" if review == "reviewed" else "NULL"))
        if safety_level:
            where.append("a.safety_level=?"); params.append(safety_level)
        for field, value in (("vehicle_make", vehicle_make), ("vehicle_model", vehicle_model)):
            if value.strip():
                where.append(f"vi_fold(a.{field})=vi_fold(?)"); params.append(value.strip())
        if technical_reviewer:
            where.append("a.technical_reviewed_by=?"); params.append(technical_reviewer)
        if publisher:
            where.append("a.reviewed_by=?"); params.append(publisher)
        if has_document is not None:
            where.append("d.article_id IS " + ("NOT NULL" if has_document else "NULL"))
        if has_source is not None:
            where.append("TRIM(a.source_name) " + ("<>''" if has_source else "=''"))
        if updated_since:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", updated_since):
                raise BadRequestError("Ngày cập nhật phải theo YYYY-MM-DD")
            where.append("a.updated_at>=?"); params.append(updated_since)
        base = " FROM technical_articles a LEFT JOIN technical_documents d ON d.article_id=a.id WHERE " + " AND ".join(where)
        total = db.execute("SELECT COUNT(*)" + base, params).fetchone()[0]
        order = {"priority": "CASE WHEN a.status='draft' AND a.technical_reviewed_by IS NOT NULL THEN 0 WHEN a.status='draft' THEN 1 ELSE 2 END,a.updated_at DESC,a.id DESC",
                 "recent": "a.updated_at DESC,a.id DESC", "title": "a.title COLLATE NOCASE,a.id DESC"}[sort]
        items = [dict(row) for row in db.execute("""SELECT a.id,a.title,a.symptoms,a.source_name,a.source_url,a.document_version,
            a.vehicle_make,a.vehicle_model,a.year_from,a.year_to,a.engine_code,a.safety_level,
            a.status,a.reviewed_by,a.technical_reviewed_by,a.technical_reviewed_at,a.updated_at,a.revision,a.withdrawn_at,
            u.full_name technical_reviewer_name,p.full_name publisher_name,d.filename document_filename,d.uploaded_at document_uploaded_at
            FROM technical_articles a LEFT JOIN technical_documents d ON d.article_id=a.id
            LEFT JOIN users u ON u.id=a.technical_reviewed_by LEFT JOIN users p ON p.id=a.reviewed_by
            WHERE """ + " AND ".join(where) + " ORDER BY " + order + " LIMIT ? OFFSET ?",
            (*params, page_size, (page - 1) * page_size))]
        return {"items": items, "total": total, "page": page, "page_size": page_size,
                "pages": max(1, (total + page_size - 1) // page_size), "stats": _stats(db)}


@router.get("/filter-options")
def filter_options(user: dict = Depends(require_permission("repair_orders"))) -> dict:
    with connect() as db:
        reviewers = [dict(row) for row in db.execute("""SELECT DISTINCT u.id,u.full_name name FROM technical_articles a
            JOIN users u ON u.id=a.technical_reviewed_by WHERE a.deleted_at IS NULL ORDER BY u.full_name LIMIT 100""")]
        publishers = [dict(row) for row in db.execute("""SELECT DISTINCT u.id,u.full_name name FROM technical_articles a
            JOIN users u ON u.id=a.reviewed_by WHERE a.deleted_at IS NULL ORDER BY u.full_name LIMIT 100""")]
        makes = [row[0] for row in db.execute("""SELECT DISTINCT vehicle_make FROM technical_articles
            WHERE deleted_at IS NULL AND vehicle_make<>'' ORDER BY vehicle_make LIMIT 100""")]
        models = [row[0] for row in db.execute("""SELECT DISTINCT vehicle_model FROM technical_articles
            WHERE deleted_at IS NULL AND vehicle_model<>'' ORDER BY vehicle_model LIMIT 100""")]
        return {"reviewers": reviewers, "publishers": publishers, "makes": makes, "models": models}


@router.get("/{article_id}")
def article_detail(article_id: int, user: dict = Depends(require_permission("repair_orders"))) -> dict:
    with connect() as db:
        article = _row(db, article_id)
        article["chunks"] = [dict(row) for row in db.execute(
            "SELECT chunk_index,content FROM technical_chunks WHERE article_id=? ORDER BY chunk_index", (article_id,))]
        article["history"] = [dict(row) for row in db.execute("""SELECT h.id,h.revision,h.action,h.reason,h.created_at,
            u.full_name actor_name,h.document_filename,h.document_sha256
            FROM technical_article_history h LEFT JOIN users u ON u.id=h.actor_id
            WHERE h.article_id=? ORDER BY h.id DESC LIMIT 50""", (article_id,))]
        return article


@router.post("", status_code=201)
def create_article(item: ArticleIn, request: Request,
                   user: dict = Depends(require_permission("repair_orders"))) -> dict:
    with connect() as db, transaction(db):
        cursor = db.execute("""INSERT INTO technical_articles
            (title,symptoms,content,safety,source_name,source_url,document_version,
             vehicle_make,vehicle_model,year_from,year_to,engine_code,safety_level,created_by)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (item.title, item.symptoms, item.content, item.safety, item.source_name,
             item.source_url, item.document_version, item.vehicle_make, item.vehicle_model,
             item.year_from, item.year_to, item.engine_code, item.safety_level, user["id"]))
        index_article_chunks(db, cursor.lastrowid, item.content)
        write_audit(db, user, "technical.create", "technical_articles", cursor.lastrowid,
                    {"status": "draft"}, client_ip(request))
        return _row(db, cursor.lastrowid)


@router.put("/{article_id}")
def update_article(article_id: int, item: ArticleIn, request: Request,
                   user: dict = Depends(require_permission("repair_orders"))) -> dict:
    with connect() as db, transaction(db):
        article = _row(db, article_id)
        _check_revision(article, item.expected_revision)
        _history(db, article, "update", user)
        db.execute("""UPDATE technical_articles SET title=?,symptoms=?,content=?,safety=?,
            source_name=?,source_url=?,document_version=?,vehicle_make=?,vehicle_model=?,
            year_from=?,year_to=?,engine_code=?,safety_level=?,status='draft',reviewed_by=NULL,
             technical_reviewed_by=NULL,technical_reviewed_at=NULL,withdrawn_at=NULL,
             revision=revision+1,updated_at=? WHERE id=?""",
            (item.title, item.symptoms, item.content, item.safety, item.source_name,
             item.source_url, item.document_version, item.vehicle_make, item.vehicle_model,
             item.year_from, item.year_to, item.engine_code, item.safety_level, now_utc_iso(), article_id))
        index_article_chunks(db, article_id, item.content)
        write_audit(db, user, "technical.update", "technical_articles", article_id,
                    {"status": "draft"}, client_ip(request))
        return _row(db, article_id)


@router.post("/{article_id}/document")
async def upload_document(article_id: int, request: Request, file: UploadFile = File(...),
                          expected_revision: int | None = Query(default=None, ge=1),
                           user: dict = Depends(require_permission("repair_orders"))) -> dict:
    """Lưu đúng tệp nguồn và tách đoạn trong một transaction; không xuất bản tự động."""
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    filename = re.split(r"[/\\]", file.filename or "")[-1].strip()[:180]
    if not filename:
        raise BadRequestError("Cần chọn tệp tài liệu")
    text, mime = extract_document(filename, data)
    with connect() as db, transaction(db):
        article = _row(db, article_id)
        _check_revision(article, expected_revision)
        _history(db, article, "document.upload", user, filename)
        db.execute("""INSERT INTO technical_documents(article_id,filename,mime_type,sha256,data,extracted_text)
            VALUES(?,?,?,?,?,?) ON CONFLICT(article_id) DO UPDATE SET filename=excluded.filename,
            mime_type=excluded.mime_type,sha256=excluded.sha256,data=excluded.data,
            extracted_text=excluded.extracted_text,uploaded_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')""",
            (article_id, filename, mime, hashlib.sha256(data).hexdigest(), data, text))
        chunk_count = index_article_chunks(db, article_id, text)
        db.execute("""UPDATE technical_articles SET status='draft',reviewed_by=NULL,
             technical_reviewed_by=NULL,technical_reviewed_at=NULL,withdrawn_at=NULL,
             revision=revision+1,updated_at=? WHERE id=?""",
            (now_utc_iso(), article_id))
        write_audit(db, user, "technical.document.upload", "technical_articles", article_id,
                    {"filename": filename, "sha256": hashlib.sha256(data).hexdigest(),
                     "chunk_count": chunk_count}, client_ip(request))
        return _row(db, article_id)


@router.get("/{article_id}/document")
def download_document(article_id: int,
                      user: dict = Depends(require_permission("repair_orders"))) -> Response:
    with connect() as db:
        _row(db, article_id)
        document = db.execute("SELECT filename,mime_type,data FROM technical_documents WHERE article_id=?",
                              (article_id,)).fetchone()
        if not document:
            raise NotFoundError("Bài chưa có tệp nguồn")
        return Response(document["data"], media_type=document["mime_type"], headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(document['filename'])}",
             "X-Content-Type-Options": "nosniff"})


@router.get("/{article_id}/history/{history_id}/document")
def download_history_document(article_id: int, history_id: int,
                              user: dict = Depends(require_permission("repair_orders"))) -> Response:
    with connect() as db:
        document = db.execute("""SELECT document_filename,document_mime,document_data
            FROM technical_article_history WHERE article_id=? AND id=?""", (article_id, history_id)).fetchone()
        if not document or document["document_data"] is None:
            raise NotFoundError("Phiên bản lịch sử này không có tệp nguồn")
        return Response(document["document_data"], media_type=document["document_mime"], headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(document['document_filename'])}",
            "X-Content-Type-Options": "nosniff"})


@router.post("/{article_id}/technical-review")
def technical_review(article_id: int, request: Request,
                     expected_revision: int | None = Query(default=None, ge=1),
                      user: dict = Depends(require_permission("technical_review"))) -> dict:
    with connect() as db, transaction(db):
        article = _row(db, article_id)
        _check_revision(article, expected_revision)
        if article["status"] != "draft":
            raise BadRequestError("Chỉ duyệt chuyên môn bài nháp")
        _history(db, article, "technical.review", user)
        db.execute("""UPDATE technical_articles SET technical_reviewed_by=?,technical_reviewed_at=?,
            revision=revision+1,updated_at=? WHERE id=?""", (user["id"], now_utc_iso(), now_utc_iso(), article_id))
        write_audit(db, user, "technical.review", "technical_articles", article_id,
                    {"technical_reviewer_id": user["id"]}, client_ip(request))
        return _row(db, article_id)


@router.post("/{article_id}/publish")
def publish_article(article_id: int, request: Request,
                    expected_revision: int | None = Query(default=None, ge=1),
                     user: dict = Depends(require_permission("staff"))) -> dict:
    with connect() as db, transaction(db):
        article = _row(db, article_id)
        _check_revision(article, expected_revision)
        if article["technical_reviewed_by"] is None:
            raise BadRequestError("Bài cần kỹ thuật viên duyệt chuyên môn trước khi xuất bản")
        if article["source_name"].startswith("Chưa xác minh"):
            raise BadRequestError("Bài chưa xác minh nguồn; cần cập nhật nguồn trước khi xuất bản")
        _history(db, article, "publish", user)
        db.execute("UPDATE technical_articles SET status='published',reviewed_by=?,withdrawn_at=NULL,revision=revision+1,updated_at=? WHERE id=?",
                   (user["id"], now_utc_iso(), article_id))
        write_audit(db, user, "technical.publish", "technical_articles", article_id,
                    {"status": "published"}, client_ip(request))
        return _row(db, article_id)


@router.post("/{article_id}/unpublish")
def unpublish_article(article_id: int, request: Request,
                      expected_revision: int | None = Query(default=None, ge=1),
                      reason: str = Query(default="", max_length=500),
                       user: dict = Depends(require_permission("staff"))) -> dict:
    with connect() as db, transaction(db):
        article = _row(db, article_id)
        _check_revision(article, expected_revision)
        _history(db, article, "unpublish", user, reason)
        db.execute("UPDATE technical_articles SET status='draft',reviewed_by=NULL,withdrawn_at=?,revision=revision+1,updated_at=? WHERE id=?",
                   (now_utc_iso(), now_utc_iso(), article_id))
        write_audit(db, user, "technical.unpublish", "technical_articles", article_id,
                    {"status": "draft", "reason": reason}, client_ip(request))
        return _row(db, article_id)


@router.delete("/{article_id}")
def delete_article(article_id: int, request: Request, reason: str = Query(min_length=3, max_length=500),
                   expected_revision: int | None = Query(default=None, ge=1),
                   user: dict = Depends(require_permission("staff"))) -> dict:
    with connect() as db, transaction(db):
        article = _row(db, article_id)
        _check_revision(article, expected_revision)
        _history(db, article, "delete", user, reason)
        db.execute("""UPDATE technical_articles SET status='draft',reviewed_by=NULL,deleted_at=?,
            revision=revision+1,updated_at=? WHERE id=?""", (now_utc_iso(), now_utc_iso(), article_id))
        write_audit(db, user, "technical.delete", "technical_articles", article_id,
                    {"reason": reason, "soft_delete": True}, client_ip(request))
        return {"id": article_id, "deleted": True}
