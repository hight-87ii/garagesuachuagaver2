"""Module phụ tùng và kho (parts & inventory)."""

import sqlite3

from fastapi import APIRouter, Depends, Header, Query, Request

from ...core.audit import write_audit
from ...core.db import connect, transaction
from ...core.deps import client_ip, require_permission
from ...core.errors import ConflictError, NotFoundError
from ...core.pagination import PageParams, envelope, fetch_page, page_params, search_clause
from ...money import to_vnd
from ...schemas.common import Page
from ...schemas.parts import PartFitmentsIn, PartIn, PartOut, PartStockIn, PartUpdate

router = APIRouter(prefix="/parts", tags=["Parts & Inventory"])


@router.get("/{part_id}/fitments", response_model=list[dict])
def list_fitments(part_id: int, user: dict = Depends(require_permission("inventory"))) -> list[dict]:
    with connect() as db:
        if not db.execute("SELECT id FROM parts WHERE id=?", (part_id,)).fetchone():
            raise NotFoundError("Không tìm thấy phụ tùng")
        return [dict(row) for row in db.execute(
            "SELECT id,make,model,year_from,year_to,variant,engine_code,fuel_type,note "
            "FROM part_fitments WHERE part_id=? ORDER BY id", (part_id,)
        ).fetchall()]


@router.put("/{part_id}/fitments", response_model=list[dict])
def replace_fitments(
    part_id: int, item: PartFitmentsIn, request: Request,
    user: dict = Depends(require_permission("inventory")),
) -> list[dict]:
    """Nhân viên nhập quy tắc từ nguồn đã kiểm chứng; không suy ra từ chuỗi compatible."""
    with connect() as db, transaction(db):
        if not db.execute("SELECT id FROM parts WHERE id=?", (part_id,)).fetchone():
            raise NotFoundError("Không tìm thấy phụ tùng")
        db.execute("DELETE FROM part_fitments WHERE part_id=?", (part_id,))
        for rule in item.fitments:
            db.execute(
                "INSERT INTO part_fitments(part_id,make,model,year_from,year_to,variant,engine_code,fuel_type,note) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (part_id, rule.make, rule.model, rule.year_from, rule.year_to,
                 rule.variant, rule.engine_code, rule.fuel_type, rule.note),
            )
        write_audit(db, user, "part.fitments.update", "parts", part_id,
                    {"count": len(item.fitments)}, client_ip(request))
        return [dict(row) for row in db.execute(
            "SELECT id,make,model,year_from,year_to,variant,engine_code,fuel_type,note "
            "FROM part_fitments WHERE part_id=? ORDER BY id", (part_id,)
        ).fetchall()]


@router.get("", response_model=Page[PartOut], response_model_exclude_none=True)
def list_parts(
    q: str = Query(default="", max_length=120),
    category: str = Query(default="", max_length=60),
    low_stock: bool = Query(default=False),
    page: PageParams = Depends(page_params),
    user: dict = Depends(require_permission("inventory")),
) -> dict:
    base = "SELECT * FROM parts WHERE 1=1"
    params: list = []
    if category and category != "Tất cả":
        base += " AND category=?"
        params.append(category)
    if low_stock:
        base += " AND stock<=min_stock"
    clause, clause_params = search_clause(q, ["code", "name", "category", "compatible", "supplier"])
    base += clause
    params.extend(clause_params)
    order_by = "ORDER BY CASE WHEN stock<=min_stock THEN 0 ELSE 1 END, name"
    with connect() as db:
        items, total = fetch_page(db, base, tuple(params), order_by, page)
    return envelope(items, total, page)


@router.post("", status_code=201, response_model=PartOut, response_model_exclude_none=True)
def create_part(
    item: PartIn,
    request: Request,
    user: dict = Depends(require_permission("inventory")),
) -> dict:
    try:
        with connect() as db, transaction(db):
            cursor = db.execute(
                """
                INSERT INTO parts(code, name, category, compatible, unit, cost_price, sell_price,
                    stock, min_stock, supplier, active)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    item.code.upper(),
                    item.name,
                    item.category,
                    item.compatible,
                    item.unit,
                    to_vnd(item.cost_price),
                    to_vnd(item.sell_price),
                    item.stock,
                    item.min_stock,
                    item.supplier,
                ),
            )
            part_id = cursor.lastrowid
            write_audit(
                db, user, "part.create", "parts", part_id,
                {"code": item.code.upper(), "stock": item.stock}, client_ip(request),
            )
            return dict(db.execute("SELECT * FROM parts WHERE id=?", (part_id,)).fetchone())
    except sqlite3.IntegrityError as exc:
        raise ConflictError("Mã phụ tùng đã tồn tại") from exc


@router.post("/{part_id}/stock", response_model=PartOut, response_model_exclude_none=True)
def add_part_stock(
    part_id: int,
    item: PartStockIn,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: dict = Depends(require_permission("inventory")),
) -> dict:
    with connect() as db, transaction(db):
        part = db.execute("SELECT * FROM parts WHERE id=?", (part_id,)).fetchone()
        if not part:
            raise NotFoundError("Không tìm thấy phụ tùng")
        if idempotency_key:
            previous = db.execute(
                "SELECT * FROM inventory_transactions WHERE idempotency_key=?",
                (idempotency_key.strip(),),
            ).fetchone()
            if previous:
                if previous["operation"] != "STOCK_IN" or previous["part_id"] != part_id or previous["quantity"] != item.amount:
                    raise ConflictError("Idempotency-Key đã được dùng cho giao dịch kho khác")
                return dict(db.execute("SELECT * FROM parts WHERE id=?", (part_id,)).fetchone())
        cursor = db.execute("UPDATE parts SET stock=stock+? WHERE id=?", (item.amount, part_id))
        if cursor.rowcount == 0:
            raise NotFoundError("Không tìm thấy phụ tùng")
        updated = db.execute("SELECT * FROM parts WHERE id=?", (part_id,)).fetchone()
        db.execute(
            "INSERT INTO inventory_transactions(idempotency_key, operation, part_id, quantity, stock_after, created_by) "
            "VALUES(?, 'STOCK_IN', ?, ?, ?, ?)",
            (idempotency_key.strip() if idempotency_key else None, part_id, item.amount, updated["stock"], user["id"]),
        )
        write_audit(db, user, "part.stock_in", "parts", part_id, {"amount": item.amount}, client_ip(request))
        return dict(updated)


@router.patch("/{part_id}", response_model=PartOut, response_model_exclude_none=True)
def update_part(
    part_id: int,
    item: PartUpdate,
    request: Request,
    user: dict = Depends(require_permission("inventory")),
) -> dict:
    fields = item.model_dump(exclude_none=True)
    if "code" in fields:
        fields["code"] = fields["code"].upper()
    for key in ("cost_price", "sell_price"):
        if key in fields:
            fields[key] = to_vnd(fields[key])
    if "active" in fields:
        fields["active"] = int(fields["active"])
    if not fields:
        raise ConflictError("Không có dữ liệu cập nhật")
    try:
        with connect() as db, transaction(db):
            cursor = db.execute(
                f"UPDATE parts SET {', '.join(f'{key}=?' for key in fields)} WHERE id=?",
                (*fields.values(), part_id),
            )
            if cursor.rowcount == 0:
                raise NotFoundError("Không tìm thấy phụ tùng")
            write_audit(db, user, "part.update", "parts", part_id, {"code": fields["code"]}, client_ip(request))
            return dict(db.execute("SELECT * FROM parts WHERE id=?", (part_id,)).fetchone())
    except sqlite3.IntegrityError as exc:
        raise ConflictError("Mã phụ tùng đã tồn tại") from exc


@router.delete("/{part_id}", response_model=PartOut, response_model_exclude_none=True)
def deactivate_part(
    part_id: int,
    request: Request,
    user: dict = Depends(require_permission("inventory")),
) -> dict:
    with connect() as db, transaction(db):
        cursor = db.execute("UPDATE parts SET active=0 WHERE id=?", (part_id,))
        if cursor.rowcount == 0:
            raise NotFoundError("Không tìm thấy phụ tùng")
        write_audit(db, user, "part.deactivate", "parts", part_id, {}, client_ip(request))
        return dict(db.execute("SELECT * FROM parts WHERE id=?", (part_id,)).fetchone())
