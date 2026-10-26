"""Bài học sau sửa: nháp từ phiếu hoàn thành, duyệt người thật trước khi RAG đọc."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from ...core.audit import write_audit
from ...core.db import connect, transaction
from ...core.deps import client_ip, require_permission
from ...core.errors import BadRequestError, NotFoundError
from ...repair_knowledge import capture_completed_case, contains_private_identifier
from ...timeutil import now_utc_iso

router = APIRouter(prefix="/repair-orders", tags=["Repair knowledge cases"])


class CaseIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    customer_symptoms: str = Field(min_length=2, max_length=2000)
    inspection_findings: str = Field(min_length=2, max_length=2000)
    confirmed_cause: str = Field(default="", max_length=2000)
    work_done: str = Field(min_length=2, max_length=4000)
    outcome: str = Field(default="", max_length=2000)


def _case(db, order_id: int) -> dict:
    row = db.execute("""SELECT c.*,u.full_name technician_reviewer_name
        FROM repair_knowledge_cases c LEFT JOIN users u ON u.id=c.technician_reviewed_by
        WHERE c.repair_order_id=?""", (order_id,)).fetchone()
    if not row:
        raise NotFoundError("Phiếu chưa có ca kiến thức; chỉ tạo khi đã hoàn thành và gắn xe")
    return dict(row)


@router.get("/{order_id}/knowledge-case")
def get_case(order_id: int, user: dict = Depends(require_permission("repair_orders"))) -> dict:
    with connect() as db:
        return _case(db, order_id)


@router.post("/{order_id}/knowledge-case/capture")
def capture_case(order_id: int, request: Request,
                 user: dict = Depends(require_permission("repair_orders"))) -> dict:
    with connect() as db, transaction(db):
        if capture_completed_case(db, order_id) is None:
            raise BadRequestError("Chỉ ghi ca cho phiếu đã hoàn thành và có hồ sơ xe")
        write_audit(db, user, "repair_case.capture", "repair_orders", order_id,
                    {"case_id": _case(db, order_id)["id"]}, client_ip(request))
        return _case(db, order_id)


@router.put("/{order_id}/knowledge-case")
def update_case(order_id: int, item: CaseIn, request: Request,
                user: dict = Depends(require_permission("repair_orders"))) -> dict:
    with connect() as db, transaction(db):
        _case(db, order_id)
        db.execute("""UPDATE repair_knowledge_cases SET customer_symptoms=?,inspection_findings=?,
            confirmed_cause=?,work_done=?,outcome=?,status='draft',technician_reviewed_by=NULL,
            technician_reviewed_at=NULL,published_by=NULL,published_at=NULL,updated_at=?
            WHERE repair_order_id=?""", (item.customer_symptoms, item.inspection_findings,
            item.confirmed_cause, item.work_done, item.outcome, now_utc_iso(), order_id))
        write_audit(db, user, "repair_case.edit", "repair_orders", order_id,
                    {"case_id": _case(db, order_id)["id"]}, client_ip(request))
        return _case(db, order_id)


@router.post("/{order_id}/knowledge-case/technical-review")
def review_case(order_id: int, request: Request,
                user: dict = Depends(require_permission("technical_review"))) -> dict:
    with connect() as db, transaction(db):
        case = _case(db, order_id)
        if any(len(str(case[field]).strip()) < 5 for field in (
                "customer_symptoms", "inspection_findings", "confirmed_cause", "work_done", "outcome")):
            raise BadRequestError("Cần bổ sung triệu chứng, kiểm tra, nguyên nhân xác nhận, hạng mục sửa và kết quả sau sửa")
        db.execute("""UPDATE repair_knowledge_cases SET technician_reviewed_by=?,
            technician_reviewed_at=?,updated_at=? WHERE repair_order_id=?""",
            (user["id"], now_utc_iso(), now_utc_iso(), order_id))
        write_audit(db, user, "repair_case.technical_review", "repair_orders", order_id,
                    {"case_id": case["id"]}, client_ip(request))
        return _case(db, order_id)


@router.post("/{order_id}/knowledge-case/publish")
def publish_case(order_id: int, request: Request,
                 user: dict = Depends(require_permission("staff"))) -> dict:
    with connect() as db, transaction(db):
        case = _case(db, order_id)
        if not case["technician_reviewed_by"]:
            raise BadRequestError("Ca cần kỹ thuật viên duyệt trước khi công khai cho trợ lý")
        fields = ("customer_symptoms", "inspection_findings", "confirmed_cause", "work_done", "outcome")
        if any(contains_private_identifier(case[field]) for field in fields):
            raise BadRequestError("Ca chứa số điện thoại, email, biển số hoặc VIN; cần ẩn danh trước khi xuất bản")
        db.execute("""UPDATE repair_knowledge_cases SET status='published',published_by=?,
            published_at=?,updated_at=? WHERE repair_order_id=?""",
            (user["id"], now_utc_iso(), now_utc_iso(), order_id))
        write_audit(db, user, "repair_case.publish", "repair_orders", order_id,
                    {"case_id": case["id"]}, client_ip(request))
        return _case(db, order_id)


@router.post("/{order_id}/knowledge-case/unpublish")
def unpublish_case(order_id: int, request: Request,
                   user: dict = Depends(require_permission("staff"))) -> dict:
    with connect() as db, transaction(db):
        case = _case(db, order_id)
        db.execute("""UPDATE repair_knowledge_cases SET status='draft',published_by=NULL,
            published_at=NULL,updated_at=? WHERE repair_order_id=?""", (now_utc_iso(), order_id))
        write_audit(db, user, "repair_case.unpublish", "repair_orders", order_id,
                    {"case_id": case["id"]}, client_ip(request))
        return _case(db, order_id)
