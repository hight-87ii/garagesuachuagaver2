"""Tra cứu khách hàng–xe bằng các ý định và SQL cố định do backend kiểm soát.

Schema hiện tại lưu chủ sở hữu hiện tại tại ``vehicles.customer_id`` (một xe/một chủ),
không có lịch sử đổi chủ, đồng sở hữu, chi nhánh hoặc phạm vi nhân viên. Vì vậy "đang
sở hữu" trong module này là xe ``active`` đang liên kết trực tiếp với khách ``active``.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .ai_service import AIResult, ai_service
from .core.access import customer_scope_id
from .core.db import normalize_plate
from .permissions import has_permission
from .timeutil import VN_TZ, to_utc_iso

DENIED = "Bạn không có đủ quyền xem khách hàng, xe và quan hệ sở hữu xe cho truy vấn này."
NO_DATA = "Không tìm thấy dữ liệu khách hàng hoặc xe phù hợp trong phạm vi bạn được xem."
LIMIT = 20


@dataclass(frozen=True)
class CustomerVehicleFilters:
    vehicle_only: bool = False
    count_operator: str | None = None
    vehicle_count: int | None = None
    maximum_count: bool = False
    customer_id: int | None = None
    customer_name: str | None = None
    makes: tuple[str, ...] = ()
    models: tuple[tuple[str, str], ...] = ()
    year: int | None = None
    plate_normalized: str | None = None
    unpaid_invoice: bool = False
    repaired_this_month: bool = False
    repaired_multiple_times: bool = False
    repaired_any: bool = False
    no_repair_history: bool = False
    awaiting_reception: bool = False


def _normalize(value: str) -> str:
    return ai_service._normalize_vi(value)


def is_customer_vehicle_question(question: str) -> bool:
    text = _normalize(question)
    vehicle_words = any(term in text for term in (" xe", "xe ", "bien so", "phuong tien"))
    relation_words = any(term in text for term in (
        "khach hang", "khach nao", "chu xe", "thuoc khach", "so huu", "dang ky",
        "bao nhieu xe", "nhieu xe", "xe nao", "nhung xe", "chua co lich su sua",
        "cho tiep nhan",
    ))
    return relation_words and (vehicle_words or "so huu" in text)


def _number(value: str) -> int:
    return int(value) if value.isdigit() else {
        "mot": 1, "hai": 2, "ba": 3, "bon": 4, "nam": 5,
        "sau": 6, "bay": 7, "tam": 8, "chin": 9, "muoi": 10,
    }[value]


def _known_vehicle_filters(db: sqlite3.Connection, text: str) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    rows = [dict(row) for row in db.execute(
        "SELECT DISTINCT make,model FROM vehicles WHERE status='active' "
        "AND TRIM(make)<>'' AND TRIM(model)<>'' ORDER BY length(make)+length(model) DESC"
    ).fetchall()]
    models = []
    for row in rows:
        if _normalize(f"{row['make']} {row['model']}") in text:
            pair = (row["make"], row["model"])
            if pair not in models:
                models.append(pair)
    # Cho phép hỏi riêng mẫu xe khi mẫu đó chỉ thuộc một hãng trong dữ liệu hiện có.
    by_model: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        by_model.setdefault(_normalize(row["model"]), []).append((row["make"], row["model"]))
    for normalized_model, pairs in by_model.items():
        unique_pairs = list(dict.fromkeys(pairs))
        if (len(unique_pairs) == 1 and re.search(rf"(?<!\w){re.escape(normalized_model)}(?!\w)", text)
                and unique_pairs[0] not in models):
            models.append(unique_pairs[0])
    model_makes = {_normalize(make) for make, _ in models}
    makes = []
    for make in dict.fromkeys(row["make"] for row in rows):
        normalized_make = _normalize(make)
        if (re.search(rf"(?<!\w){re.escape(normalized_make)}(?!\w)", text)
                and normalized_make not in model_makes):
            makes.append(make)
    return tuple(makes), tuple(models)


def classify_customer_vehicle_question(db: sqlite3.Connection, question: str) -> CustomerVehicleFilters:
    text = _normalize(question)
    number_pattern = r"(\d{1,2}|mot|hai|ba|bon|nam|sau|bay|tam|chin|muoi)"
    exact = re.search(rf"(?:dung|co|so huu|dang co)\s+{number_pattern}\s+(?:chiec\s+)?xe\b", text)
    at_least = re.search(rf"(?:tu|it nhat)\s+{number_pattern}\s+(?:chiec\s+)?xe\s*(?:tro len)?", text)
    more_than = re.search(rf"(?:nhieu hon|tren)\s+{number_pattern}\s+(?:chiec\s+)?xe", text)
    operator = count = None
    match = exact or at_least or more_than
    if match:
        count = _number(match.group(1))
        operator = "=" if exact else ">=" if at_least else ">"

    customer_id = customer_name = None
    for row in db.execute("SELECT id,name FROM customers WHERE status='active' ORDER BY length(name) DESC").fetchall():
        if _normalize(row["name"]) in text:
            customer_id, customer_name = int(row["id"]), row["name"]
            break
    makes, models = _known_vehicle_filters(db, text)
    year_match = re.search(r"(?:nam|san xuat)\s*(19\d{2}|20\d{2}|2100)\b", text)
    plate_match = re.search(r"bien\s+so\s+([0-9]{2}[A-Z]{1,2}[ .-]?[0-9]{3,5}(?:[.-][0-9]{2})?)",
                            text, re.IGNORECASE)
    no_history = any(term in text for term in ("chua co lich su sua", "chua tung sua"))
    return CustomerVehicleFilters(
        vehicle_only=(any(term in text for term in ("xe nao", "nhung xe", "liet ke xe", "liet ke cac xe"))
                      and customer_id is None
                      and not any(term in text for term in ("khach hang", "khach nao", "chu xe",
                                                            "thuoc khach", "so huu", "dang ky"))),
        count_operator=operator,
        vehicle_count=count,
        maximum_count=any(term in text for term in ("nhieu xe nhat", "so huu nhieu xe nhat")),
        customer_id=customer_id,
        customer_name=customer_name,
        makes=makes,
        models=models,
        year=int(year_match.group(1)) if year_match else None,
        plate_normalized=normalize_plate(plate_match.group(1)) if plate_match else None,
        unpaid_invoice="hoa don" in text and any(term in text for term in ("chua thanh toan", "con no", "cong no")),
        repaired_this_month="sua" in text and "thang nay" in text,
        repaired_multiple_times="sua" in text and any(term in text for term in ("nhieu lan", "tu 2 lan", "tren 1 lan")),
        repaired_any=not no_history and any(term in text for term in ("da tung sua", "co lich su sua")),
        no_repair_history=no_history,
        awaiting_reception=any(term in text for term in ("cho tiep nhan", "dang cho tiep nhan")),
    )


def _required_permissions(filters: CustomerVehicleFilters, list_query: bool) -> set[str]:
    required = ({"vehicle.view"} if filters.vehicle_only else
                {"customer.view", "vehicle.view", "customer_vehicle.view"})
    if list_query:
        required.add("vehicle.view_all")
        if not filters.vehicle_only:
            required |= {"customer.view_all", "customer_vehicle.view_all"}
    if filters.unpaid_invoice:
        required |= {"invoice.view", "invoice.view_debt"}
        if list_query:
            required.add("invoice.view_all")
    if filters.repaired_this_month or filters.repaired_multiple_times or filters.repaired_any or filters.no_repair_history:
        required.add("repair_orders")
    if filters.awaiting_reception:
        required.add("appointments")
    return required


def _permissions_ok(user: dict, filters: CustomerVehicleFilters, scope: int | None) -> bool:
    # Khách có scope sở hữu nên được tra cứu hồ sơ của chính mình bằng quyền view;
    # nhân viên không có scope cần bộ quyền view_all cho mọi truy vấn toàn hệ thống.
    list_query = scope is None
    return all(has_permission(str(user.get("role") or ""), permission)
               for permission in _required_permissions(filters, list_query))


def _customer_query(filters: CustomerVehicleFilters, scope: int | None) -> tuple[str, list[Any]]:
    sql = """
        SELECT c.id,c.name,COUNT(DISTINCT v.id) vehicle_count
        FROM customers c JOIN vehicles v ON v.customer_id=c.id AND v.status='active'
        WHERE c.status='active'
    """
    params: list[Any] = []
    if scope is not None:
        sql += " AND c.id=?"
        params.append(scope)
    if filters.customer_id is not None:
        sql += " AND c.id=?"
        params.append(filters.customer_id)
    if filters.plate_normalized:
        sql += " AND EXISTS(SELECT 1 FROM vehicles pv WHERE pv.customer_id=c.id AND pv.status='active' AND pv.plate_normalized=?)"
        params.append(filters.plate_normalized)
    for make, model in filters.models:
        sql += " AND EXISTS(SELECT 1 FROM vehicles mv WHERE mv.customer_id=c.id AND mv.status='active' AND LOWER(TRIM(mv.make))=LOWER(?) AND LOWER(TRIM(mv.model))=LOWER(?))"
        params.extend((make, model))
    for make in filters.makes:
        sql += " AND EXISTS(SELECT 1 FROM vehicles mk WHERE mk.customer_id=c.id AND mk.status='active' AND LOWER(TRIM(mk.make))=LOWER(?))"
        params.append(make)
    if filters.year:
        sql += " AND EXISTS(SELECT 1 FROM vehicles yv WHERE yv.customer_id=c.id AND yv.status='active' AND yv.year=?)"
        params.append(filters.year)
    if filters.unpaid_invoice:
        sql += """ AND EXISTS(
            SELECT 1 FROM vehicles iv JOIN repair_orders ro ON ro.vehicle_id=iv.id
            JOIN invoices i ON i.repair_order_id=ro.id
            WHERE iv.customer_id=c.id AND i.status<>'Đã hủy'
              AND COALESCE((SELECT SUM(p.amount) FROM payments p
                            WHERE p.invoice_id=i.id AND p.status='completed'),0) < i.total)"""
    if filters.repaired_this_month:
        now = datetime.now(VN_TZ)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        sql += " AND EXISTS(SELECT 1 FROM vehicles rv JOIN repair_history rh ON rh.vehicle_id=rv.id WHERE rv.customer_id=c.id AND rh.repaired_at>=? AND rh.repaired_at<?)"
        params.extend((to_utc_iso(start), to_utc_iso(end)))
    if filters.repaired_multiple_times:
        sql += " AND EXISTS(SELECT 1 FROM vehicles rv WHERE rv.customer_id=c.id AND rv.status='active'"
        if filters.models:
            make, model = filters.models[0]
            sql += " AND LOWER(TRIM(rv.make))=LOWER(?) AND LOWER(TRIM(rv.model))=LOWER(?)"
            params.extend((make, model))
        elif filters.makes:
            sql += " AND LOWER(TRIM(rv.make))=LOWER(?)"
            params.append(filters.makes[0])
        if filters.year:
            sql += " AND rv.year=?"
            params.append(filters.year)
        sql += " AND (SELECT COUNT(*) FROM repair_history rh WHERE rh.vehicle_id=rv.id)>1)"
    if filters.repaired_any:
        sql += " AND EXISTS(SELECT 1 FROM vehicles rv JOIN repair_history rh ON rh.vehicle_id=rv.id WHERE rv.customer_id=c.id)"
    if filters.no_repair_history:
        sql += " AND EXISTS(SELECT 1 FROM vehicles nv WHERE nv.customer_id=c.id AND nv.status='active' AND NOT EXISTS(SELECT 1 FROM repair_history rh WHERE rh.vehicle_id=nv.id))"
    if filters.awaiting_reception:
        sql += " AND EXISTS(SELECT 1 FROM appointments a WHERE COALESCE(a.customer_id,(SELECT customer_id FROM vehicles av WHERE av.id=a.vehicle_id))=c.id AND a.status='Đang chờ')"
    sql += " GROUP BY c.id"
    if filters.count_operator and filters.vehicle_count is not None:
        sql += f" HAVING COUNT(DISTINCT v.id) {filters.count_operator} ?"
        params.append(filters.vehicle_count)
    if filters.maximum_count:
        sql += " ORDER BY vehicle_count DESC,c.name,c.id LIMIT 1"
    else:
        sql += " ORDER BY c.name,c.id LIMIT ?"
        params.append(LIMIT + 1)
    return sql, params


def _vehicles_for_customer(db: sqlite3.Connection, customer_id: int, filters: CustomerVehicleFilters) -> list[dict]:
    sql = "SELECT id,make,model,year,plate,status FROM vehicles WHERE customer_id=? AND status='active'"
    params: list[Any] = [customer_id]
    if filters.plate_normalized:
        sql += " AND plate_normalized=?"
        params.append(filters.plate_normalized)
    if filters.count_operator is None:
        if filters.models:
            clauses = []
            for make, model in filters.models:
                clauses.append("(LOWER(TRIM(make))=LOWER(?) AND LOWER(TRIM(model))=LOWER(?))")
                params.extend((make, model))
            sql += " AND (" + " OR ".join(clauses) + ")"
        elif filters.makes:
            sql += " AND LOWER(TRIM(make)) IN (" + ",".join("LOWER(?)" for _ in filters.makes) + ")"
            params.extend(filters.makes)
        if filters.year:
            sql += " AND year=?"
            params.append(filters.year)
    # Khi có nhiều mẫu, hiển thị tất cả xe của khách để chứng minh điều kiện số lượng;
    # các điều kiện mẫu đã được kiểm tra bằng EXISTS ở truy vấn khách hàng.
    if filters.no_repair_history:
        sql += " AND NOT EXISTS(SELECT 1 FROM repair_history rh WHERE rh.vehicle_id=vehicles.id)"
    if filters.repaired_any:
        sql += " AND EXISTS(SELECT 1 FROM repair_history rh WHERE rh.vehicle_id=vehicles.id)"
    if filters.awaiting_reception:
        sql += " AND EXISTS(SELECT 1 FROM appointments a WHERE a.vehicle_id=vehicles.id AND a.status='Đang chờ')"
    sql += " ORDER BY id LIMIT 10"
    return [dict(row) for row in db.execute(sql, params).fetchall()]


def search_customers_by_vehicle(db: sqlite3.Connection, filters: CustomerVehicleFilters,
                                scope: int | None = None) -> list[dict]:
    sql, params = _customer_query(filters, scope)
    return [dict(row) for row in db.execute(sql, params).fetchall()]


def get_customers_by_vehicle_count(db: sqlite3.Connection, count: int,
                                   filters: CustomerVehicleFilters | None = None,
                                   scope: int | None = None) -> list[dict]:
    base = filters or CustomerVehicleFilters()
    merged = CustomerVehicleFilters(**{**base.__dict__, "count_operator": "=", "vehicle_count": count})
    return search_customers_by_vehicle(db, merged, scope)


def get_vehicles_by_customer(db: sqlite3.Connection, customer_id: int) -> list[dict]:
    return _vehicles_for_customer(db, customer_id, CustomerVehicleFilters())


def get_vehicle_owner(db: sqlite3.Connection, vehicle_id: int) -> dict | None:
    row = db.execute("""SELECT c.id,c.name,v.id vehicle_id,v.make,v.model,v.year,v.plate
                      FROM vehicles v JOIN customers c ON c.id=v.customer_id
                      WHERE v.id=? AND v.status='active' AND c.status='active'""", (vehicle_id,)).fetchone()
    return dict(row) if row else None


def get_customer_vehicle_summary(db: sqlite3.Connection, filters: CustomerVehicleFilters,
                                 scope: int | None = None) -> list[dict]:
    rows = search_customers_by_vehicle(db, filters, scope)
    return [{**row, "vehicles": _vehicles_for_customer(db, row["id"], filters)} for row in rows[:LIMIT]]


def _vehicle_only_rows(db: sqlite3.Connection, filters: CustomerVehicleFilters,
                       scope: int | None) -> list[dict]:
    sql = "SELECT v.id,v.make,v.model,v.year,v.plate FROM vehicles v WHERE v.status='active'"
    params: list[Any] = []
    if scope is not None:
        sql += " AND v.customer_id=?"
        params.append(scope)
    if filters.no_repair_history:
        sql += " AND NOT EXISTS(SELECT 1 FROM repair_history rh WHERE rh.vehicle_id=v.id)"
    if filters.repaired_any:
        sql += " AND EXISTS(SELECT 1 FROM repair_history rh WHERE rh.vehicle_id=v.id)"
    if filters.awaiting_reception:
        sql += " AND EXISTS(SELECT 1 FROM appointments a WHERE a.vehicle_id=v.id AND a.status='Đang chờ')"
    if filters.year:
        sql += " AND v.year=?"
        params.append(filters.year)
    sql += " ORDER BY v.id LIMIT ?"
    params.append(LIMIT + 1)
    return [dict(row) for row in db.execute(sql, params).fetchall()]


def answer_customer_vehicle_question(db: sqlite3.Connection, question: str, user: dict):
    if not is_customer_vehicle_question(question):
        return None
    text = _normalize(question)
    if "chi nhanh" in text:
        return AIResult("Hệ thống hiện chưa lưu chi nhánh cho khách hàng hoặc xe nên không thể lọc chính xác theo chi nhánh.",
                        "clarification", "local", ai_service.model, True, ["Chi nhánh"]), []
    filters = classify_customer_vehicle_question(db, question)
    scope = customer_scope_id(db, user)
    if not _permissions_ok(user, filters, scope):
        return AIResult(DENIED, "fallback", "local", ai_service.model), []
    constrained = any((filters.count_operator, filters.maximum_count, filters.customer_id,
                       filters.makes, filters.models, filters.year, filters.plate_normalized,
                       filters.unpaid_invoice, filters.repaired_this_month,
                       filters.repaired_multiple_times, filters.repaired_any,
                       filters.no_repair_history, filters.awaiting_reception))
    mentioned_vehicle = re.search(r"(?:so huu|co)\s+(?:xe\s+)?([a-z0-9]+)", text)
    generic_words = {"xe", "nhieu", "bao", "tu", "dung", "mot", "hai", "ba", "bon", "nam"}
    if not constrained and mentioned_vehicle and mentioned_vehicle.group(1) not in generic_words:
        return AIResult(NO_DATA, "success", "local", ai_service.model), []
    if filters.vehicle_only:
        vehicles = _vehicle_only_rows(db, filters, scope)
        if not vehicles:
            return AIResult(NO_DATA, "success", "local", ai_service.model), []
        shown = vehicles[:LIMIT]
        lines = [f"Tìm thấy {len(vehicles) if len(vehicles) <= LIMIT else f'trên {LIMIT}'} xe phù hợp trong phạm vi bạn được xem."]
        lines.extend(f"{car['make']} {car['model']}{f' {car['year']}' if car['year'] else ''} · {car['plate']}"
                     for car in shown)
        sources = [{"type": "vehicle", "id": car["id"], "label": car["plate"]} for car in shown]
        return AIResult("\n".join(lines), "success", "local", ai_service.model), sources

    # Nếu nhiều hồ sơ active trùng đúng tên được nhắc, không tự chọn một người.
    if filters.customer_name and scope is None:
        duplicates = db.execute("SELECT id FROM customers WHERE status='active' AND LOWER(TRIM(name))=LOWER(?)",
                                (filters.customer_name,)).fetchall()
        if len(duplicates) > 1:
            codes = ", ".join(f"KH-{row['id']:05d}" for row in duplicates[:10])
            return AIResult(f"Có {len(duplicates)} khách hàng trùng tên {filters.customer_name} ({codes}). "
                            "Vui lòng chọn đúng mã khách hàng trên màn hình Khách hàng.",
                            "clarification", "local", ai_service.model), []
    rows = get_customer_vehicle_summary(db, filters, scope)
    if not rows:
        return AIResult(NO_DATA, "success", "local", ai_service.model), []

    definition = "Đếm xe đang hoạt động và đang liên kết trực tiếp với chủ sở hữu hiện tại trong hệ thống."
    if filters.maximum_count:
        heading = f"Khách hàng sở hữu nhiều xe nhất có {rows[0]['vehicle_count']} xe."
    elif filters.customer_id is not None and not any((filters.models, filters.makes, filters.year, filters.plate_normalized)):
        heading = f"{filters.customer_name} đang có {rows[0]['vehicle_count']} xe trong hệ thống."
    else:
        heading = f"Tìm thấy {len(rows)} khách hàng phù hợp."
        if len(rows) == LIMIT:
            heading += f" Chỉ hiển thị tối đa {LIMIT} kết quả."
    lines = [heading, definition]
    sources = []
    for row in rows:
        cars = row["vehicles"]
        vehicle_text = "; ".join(
            f"{car['make']} {car['model']}{f' {car['year']}' if car['year'] else ''} · {car['plate']}"
            for car in cars
        ) or "Không có xe phù hợp để hiển thị"
        lines.append(f"KH-{row['id']:05d} · {row['name']} · {row['vehicle_count']} xe: {vehicle_text}")
        sources.extend({"type": "vehicle", "id": car["id"], "label": car["plate"]} for car in cars)
    return AIResult("\n".join(lines), "success", "local", ai_service.model), sources
