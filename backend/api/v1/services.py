"""Module dịch vụ (danh mục dịch vụ của xưởng)."""

import sqlite3

from fastapi import APIRouter, Depends, Query, Request

from ...core.audit import write_audit
from ...core.db import connect, transaction
from ...core.deps import client_ip, require_permission
from ...core.errors import ConflictError, NotFoundError
from ...core.pagination import PageParams, envelope, fetch_page, page_params, search_clause
from ...money import to_vnd
from ...schemas.common import Page
from ...schemas.services import ServiceIn, ServiceOut, ServicePatch, ServiceUpdate

router = APIRouter(prefix="/services", tags=["Services"])


@router.get("", response_model=Page[ServiceOut], response_model_exclude_none=True)
def list_services(
    q: str = Query(default="", max_length=120),
    category: str = Query(default="", max_length=60),
    page: PageParams = Depends(page_params),
    user: dict = Depends(require_permission("services")),
) -> dict:
    base = "SELECT * FROM services WHERE 1=1"
    params: list = []
    if category and category != "Tất cả":
        base += " AND category=?"
        params.append(category)
    clause, clause_params = search_clause(q, ["name", "category", "description"])
    base += clause
    params.extend(clause_params)
    with connect() as db:
        items, total = fetch_page(db, base, tuple(params), "ORDER BY active DESC, category, name", page)
    return envelope(items, total, page)


@router.post("", status_code=201, response_model=ServiceOut, response_model_exclude_none=True)
def create_service(
    item: ServiceIn,
    request: Request,
    user: dict = Depends(require_permission("services")),
) -> dict:
    try:
        with connect() as db, transaction(db):
            cursor = db.execute(
                "INSERT INTO services(name, category, description, price, duration_min, active) "
                "VALUES(?, ?, ?, ?, ?, 1)",
                (item.name, item.category, item.description, to_vnd(item.price), item.duration_min),
            )
            service_id = cursor.lastrowid
            write_audit(db, user, "service.create", "services", service_id, {"name": item.name}, client_ip(request))
            return dict(db.execute("SELECT * FROM services WHERE id=?", (service_id,)).fetchone())
    except sqlite3.IntegrityError as exc:
        raise ConflictError("Tên dịch vụ đã tồn tại") from exc


@router.patch("/{service_id}", response_model=ServiceOut, response_model_exclude_none=True)
def update_service(
    service_id: int,
    item: ServicePatch,
    request: Request,
    user: dict = Depends(require_permission("services")),
) -> dict:
    fields = item.model_dump(exclude_none=True)
    if "active" in fields:
        fields["active"] = int(fields["active"])
    if "price" in fields:
        fields["price"] = to_vnd(fields["price"])
    if not fields:
        raise ConflictError("Không có dữ liệu cập nhật")
    with connect() as db, transaction(db):
        cursor = db.execute(
            f"UPDATE services SET {', '.join(f'{key}=?' for key in fields)} WHERE id=?",
            (*fields.values(), service_id),
        )
        if cursor.rowcount == 0:
            raise NotFoundError("Không tìm thấy dịch vụ")
        write_audit(db, user, "service.update", "services", service_id, fields, client_ip(request))
        return dict(db.execute("SELECT * FROM services WHERE id=?", (service_id,)).fetchone())


@router.delete("/{service_id}", response_model=ServiceOut, response_model_exclude_none=True)
def deactivate_service(
    service_id: int,
    request: Request,
    user: dict = Depends(require_permission("services")),
) -> dict:
    with connect() as db, transaction(db):
        cursor = db.execute("UPDATE services SET active=0 WHERE id=?", (service_id,))
        if cursor.rowcount == 0:
            raise NotFoundError("Không tìm thấy dịch vụ")
        write_audit(db, user, "service.deactivate", "services", service_id, {}, client_ip(request))
        return dict(db.execute("SELECT * FROM services WHERE id=?", (service_id,)).fetchone())
