"""Module nhật ký kiểm toán (audit logging) và tương tác AI."""

from fastapi import APIRouter, Depends, Query

from ...core.db import connect
from ...core.deps import require_permission
from ...core.pagination import PageParams, envelope, fetch_page, page_params, search_clause
from ...schemas.audit import AIInteractionOut, AuditLogOut
from ...schemas.common import Page

router = APIRouter(tags=["Audit Logging"])


@router.get("/audit-logs", response_model=Page[AuditLogOut], response_model_exclude_none=True)
def list_audit_logs(
    q: str = Query(default="", max_length=120),
    page: PageParams = Depends(page_params),
    user: dict = Depends(require_permission("staff")),
) -> dict:
    base = "SELECT * FROM audit_logs WHERE 1=1"
    clause, clause_params = search_clause(q, ["action", "actor_email", "entity_type", "entity_id"])
    base += clause
    with connect() as db:
        items, total = fetch_page(db, base, tuple(clause_params), "ORDER BY id DESC", page)
    return envelope(items, total, page)


@router.get("/ai-interactions", response_model=Page[AIInteractionOut], response_model_exclude_none=True)
def list_ai_interactions(
    task_type: str = Query(default="", max_length=40),
    status: str = Query(default="", max_length=40),
    page: PageParams = Depends(page_params),
    user: dict = Depends(require_permission("staff")),
) -> dict:
    base = "SELECT * FROM ai_interactions WHERE 1=1"
    params: list = []
    if task_type and task_type != "Tất cả":
        base += " AND task_type=?"
        params.append(task_type)
    if status and status != "Tất cả":
        base += " AND status=?"
        params.append(status)
    with connect() as db:
        items, total = fetch_page(db, base, tuple(params), "ORDER BY id DESC", page)
    return envelope(items, total, page)
