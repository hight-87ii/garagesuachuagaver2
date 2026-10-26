"""Module báo cáo (reports) cho dashboard và thống kê vận hành."""

import sqlite3
import unicodedata
import re
import csv
import io
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ...core.db import connect
from ...core.deps import require_permission
from ...core.access import customer_scope_id
from ...schemas.reports import (
    DashboardOut,
    InventoryReportOut,
    RevenuePointOut,
    RevenueReportOut,
    WorkloadOut,
)
from ...timeutil import VN_TZ, vn_text

router = APIRouter(tags=["Reports"])

ACTIVE_STATUSES = (
    "Tiếp nhận",
    "Đang kiểm tra",
    "Đã báo giá",
    "Đã duyệt",
    "Đang sửa",
    "Chờ phụ tùng",
    "Tạm dừng",
)
COMPLETED_STATUSES = ("Hoàn thành", "Đã bàn giao")

# Quy ước kế toán của báo cáo:
# - Kỳ ghi nhận theo ngày phát hành hóa đơn (issued_at), quy đổi UTC -> UTC+7.
# - Doanh thu = tổng invoices.total của hóa đơn không ở trạng thái "Đã hủy".
# - Tiền công/phụ tùng = tổng invoice_items.line_total theo loại, trước giảm giá và thuế.
# - Công nợ = max(total - paid_amount, 0) của hóa đơn chưa hủy.
REPORT_RULES = {
    "timezone": "Asia/Ho_Chi_Minh (UTC+7)",
    "period_field": "invoices.issued_at",
    "revenue_formula": "SUM(invoices.total) với invoices.status != 'Đã hủy'",
    "labor_formula": "SUM(invoice_items.line_total) với kind = 'Dịch vụ', trước giảm giá và thuế",
    "parts_formula": "SUM(invoice_items.line_total) với kind = 'Phụ tùng', trước giảm giá và thuế",
    "debt_formula": "SUM(MAX(invoices.total - invoices.paid_amount, 0)) của hóa đơn chưa hủy",
    "cancelled_invoice_rule": "Hóa đơn 'Đã hủy' bị loại khỏi doanh thu, tiền công, phụ tùng và công nợ",
}


def _default_period() -> tuple[date, date]:
    today = datetime.now(VN_TZ).date()
    return today.replace(day=1), today


def _period(from_date: date | None, to_date: date | None) -> tuple[str, str]:
    default_from, default_to = _default_period()
    start, end = from_date or default_from, to_date or default_to
    if start > end:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Từ ngày không được sau đến ngày")
    if (end - start).days > 366:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Khoảng báo cáo tối đa 366 ngày")
    return start.isoformat(), end.isoformat()


def _invoice_window(db: sqlite3.Connection, start: str, end: str,
                    status: str | None = None) -> dict:
    """One row per valid invoice; shared by comparison and drill-down."""
    where = "status <> 'Đã hủy' AND date(issued_at, '+7 hours') BETWEEN ? AND ?"
    params: list = [start, end]
    if status:
        where += " AND status=?"
        params.append(status)
    return dict(db.execute(f"""SELECT COUNT(*) invoice_count, COALESCE(SUM(total),0) revenue,
        COALESCE(SUM(discount),0) discount, COALESCE(SUM(tax),0) tax
        FROM invoices WHERE {where}""", params).fetchone())


def _today_revenue(db: sqlite3.Connection) -> int:
    return int(db.execute(
        "SELECT COALESCE(SUM(total), 0) FROM invoices "
        "WHERE status <> 'Đã hủy' AND date(issued_at, '+7 hours') = date('now', '+7 hours')"
    ).fetchone()[0])


def _growth(db: sqlite3.Connection) -> float:
    current = int(db.execute(
        "SELECT COALESCE(SUM(total), 0) FROM invoices WHERE status <> 'Đã hủy' "
        "AND date(issued_at, '+7 hours') >= date('now', '+7 hours', '-6 days')"
    ).fetchone()[0])
    previous = int(db.execute(
        "SELECT COALESCE(SUM(total), 0) FROM invoices WHERE status <> 'Đã hủy' "
        "AND date(issued_at, '+7 hours') BETWEEN date('now', '+7 hours', '-13 days') "
        "AND date('now', '+7 hours', '-7 days')"
    ).fetchone()[0])
    if previous:
        return round((current - previous) / previous * 100, 1)
    return 100.0 if current else 0.0


def _revenue_series(db: sqlite3.Connection, days: int = 7) -> list[int]:
    rows = db.execute(
        "SELECT date(issued_at, '+7 hours') AS day, COALESCE(SUM(total), 0) AS revenue "
        "FROM invoices WHERE status <> 'Đã hủy' "
        "AND date(issued_at, '+7 hours') >= date('now', '+7 hours', ?) GROUP BY day",
        (f"-{days - 1} days",),
    ).fetchall()
    lookup = {row["day"]: int(row["revenue"]) for row in rows}
    today = datetime.now(VN_TZ).date()
    return [lookup.get((today - timedelta(days=offset)).isoformat(), 0) for offset in range(days - 1, -1, -1)]


def dashboard_payload(db: sqlite3.Connection, user: dict | None = None) -> dict:
    scope = customer_scope_id(db, user or {}) if user else None
    if scope is not None:
        appointment_owner = "COALESCE(customer_id, (SELECT customer_id FROM vehicles v WHERE v.id=appointments.vehicle_id))"
        metrics = {
            "appointments": int(db.execute(
                f"SELECT COUNT(*) FROM appointments WHERE {appointment_owner}=? "
                "AND date(appointment_at, '+7 hours')=date('now','+7 hours') AND status<>'Đã hủy'",
                (scope,),
            ).fetchone()[0]),
            "in_progress": int(db.execute(
                f"SELECT COUNT(*) FROM repair_orders WHERE customer_id=? AND status IN "
                f"({', '.join('?' for _ in ACTIVE_STATUSES)})", (scope, *ACTIVE_STATUSES),
            ).fetchone()[0]),
            "completed": int(db.execute(
                f"SELECT COUNT(*) FROM repair_orders WHERE customer_id=? AND status IN "
                f"({', '.join('?' for _ in COMPLETED_STATUSES)})", (scope, *COMPLETED_STATUSES),
            ).fetchone()[0]),
            "revenue": 0, "growth": 0.0,
        }
        appointments = [dict(row) for row in db.execute(
            f"SELECT * FROM appointments WHERE {appointment_owner}=? ORDER BY appointment_at DESC LIMIT 5",
            (scope,),
        ).fetchall()]
        orders = [dict(row) for row in db.execute(
            "SELECT * FROM repair_orders WHERE customer_id=? ORDER BY id DESC LIMIT 5", (scope,),
        ).fetchall()]
        for item in appointments:
            item["appointment_at"] = vn_text(item["appointment_at"])
        return {"metrics": metrics, "appointments": appointments, "repair_orders": orders,
                "revenue": [0, 0, 0, 0, 0, 0, 0]}
    metrics = {
        "appointments": int(db.execute(
            "SELECT COUNT(*) FROM appointments "
            "WHERE date(appointment_at, '+7 hours') = date('now', '+7 hours') AND status <> 'Đã hủy'"
        ).fetchone()[0]),
        "in_progress": int(db.execute(
            f"SELECT COUNT(*) FROM repair_orders WHERE status IN "
            f"({', '.join('?' for _ in ACTIVE_STATUSES)})",
            ACTIVE_STATUSES,
        ).fetchone()[0]),
        "completed": int(db.execute(
            f"SELECT COUNT(*) FROM repair_orders WHERE status IN "
            f"({', '.join('?' for _ in COMPLETED_STATUSES)})",
            COMPLETED_STATUSES,
        ).fetchone()[0]),
        "revenue": _today_revenue(db),
        "growth": _growth(db),
    }
    appointments = [dict(row) for row in db.execute(
        "SELECT * FROM appointments ORDER BY appointment_at LIMIT 5"
    ).fetchall()]
    orders = [dict(row) for row in db.execute(
        """SELECT ro.*, v.make, v.model FROM repair_orders ro
           LEFT JOIN vehicles v ON v.id=ro.vehicle_id ORDER BY ro.id DESC LIMIT 5"""
    ).fetchall()]
    for item in appointments:
        item["appointment_at"] = vn_text(item["appointment_at"])
    return {
        "metrics": metrics,
        "appointments": appointments,
        "repair_orders": orders,
        "revenue": _revenue_series(db, 7),
    }


@router.get("/dashboard", response_model=DashboardOut, response_model_exclude_none=True)
def dashboard(user: dict = Depends(require_permission("dashboard"))) -> dict:
    with connect() as db:
        return dashboard_payload(db, user)


@router.get("/reports/dashboard", response_model=DashboardOut, response_model_exclude_none=True)
def report_dashboard(user: dict = Depends(require_permission("dashboard"))) -> dict:
    with connect() as db:
        return dashboard_payload(db, user)


@router.get("/reports/revenue", response_model=RevenueReportOut, response_model_exclude_none=True)
def revenue_report(
    days: int = Query(default=7, ge=1, le=90),
    user: dict = Depends(require_permission("dashboard")),
) -> dict:
    with connect() as db:
        rows = db.execute(
            """
            SELECT date(issued_at, '+7 hours') AS day,
                   COUNT(*) AS invoices,
                   COALESCE(SUM(total), 0) AS revenue
            FROM invoices WHERE status <> 'Đã hủy'
              AND date(issued_at, '+7 hours') >= date('now', '+7 hours', ?)
            GROUP BY day ORDER BY day
            """,
            (f"-{days - 1} days",),
        ).fetchall()
    points = [RevenuePointOut(day=row["day"], invoices=int(row["invoices"]), revenue=int(row["revenue"])) for row in rows]
    return {
        "days": days,
        "points": [point.model_dump() for point in points],
        "total_revenue": sum(point.revenue for point in points),
        "total_invoices": sum(point.invoices for point in points),
    }


@router.get("/reports/workload", response_model=list[WorkloadOut], response_model_exclude_none=True)
def workload_report(user: dict = Depends(require_permission("dashboard"))) -> list[dict]:
    with connect() as db:
        rows = db.execute(
            "SELECT status, COUNT(*) AS count FROM repair_orders GROUP BY status ORDER BY count DESC"
        ).fetchall()
    return [{"status": row["status"], "count": int(row["count"])} for row in rows]


@router.get("/reports/inventory", response_model=InventoryReportOut, response_model_exclude_none=True)
def inventory_report(user: dict = Depends(require_permission("dashboard"))) -> dict:
    with connect() as db:
        summary = db.execute(
            "SELECT COUNT(*) AS total_items, COALESCE(SUM(stock), 0) AS total_stock, "
            "COALESCE(SUM(stock * sell_price), 0) AS stock_value, "
            "COALESCE(SUM(CASE WHEN stock <= min_stock THEN 1 ELSE 0 END), 0) AS low_stock FROM parts"
        ).fetchone()
        low_items = [dict(row) for row in db.execute(
            "SELECT id, code, name, stock, min_stock, unit FROM parts WHERE stock <= min_stock ORDER BY stock"
        ).fetchall()]
    return {
        "total_items": int(summary["total_items"]),
        "total_stock": int(summary["total_stock"]),
        "stock_value": int(summary["stock_value"]),
        "low_stock": int(summary["low_stock"]),
        "low_stock_items": low_items,
    }


@router.get("/reports/overview")
def overview_report(
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    appointment_status: str | None = Query(default=None),
    invoice_status: Literal["Chưa thanh toán", "Thanh toán một phần", "Đã thanh toán"] | None = None,
    order_status: str | None = Query(default=None, max_length=50),
    part_category: str | None = Query(default=None, max_length=80),
    service_category: str | None = Query(default=None, max_length=80),
    history_query: str | None = Query(default=None, max_length=100),
    user: dict = Depends(require_permission("reports")),
) -> dict:
    """Báo cáo hợp nhất, chỉ tổng hợp từ các bảng nghiệp vụ trong database."""
    start, end = _period(from_date, to_date)
    with connect() as db:
        invoice_filter = " AND i.status=?" if invoice_status else ""
        invoice_params = (start, end, invoice_status) if invoice_status else (start, end)
        revenue_rows = db.execute(
            f"""
            SELECT date(i.issued_at, '+7 hours') AS day,
                   COUNT(*) AS invoice_count,
                   COALESCE(SUM(i.total), 0) AS revenue,
                   COALESCE(SUM(i.discount), 0) AS discount,
                   COALESCE(SUM(i.tax), 0) AS tax,
                   COALESCE(SUM(CASE WHEN ii.kind='Dịch vụ' THEN ii.line_total ELSE 0 END), 0) AS labor,
                   COALESCE(SUM(CASE WHEN ii.kind='Phụ tùng' THEN ii.line_total ELSE 0 END), 0) AS parts
            FROM invoices i
            LEFT JOIN invoice_items ii ON ii.invoice_id=i.id
            WHERE i.status <> 'Đã hủy'
              AND date(i.issued_at, '+7 hours') BETWEEN ? AND ?
              {invoice_filter}
            GROUP BY date(i.issued_at, '+7 hours') ORDER BY day
            """,
            invoice_params,
        ).fetchall()
        # COUNT/SUM(i.total) bị nhân theo số dòng invoice_items. Tổng doanh thu lấy riêng
        # theo hóa đơn để bảo đảm mỗi hóa đơn chỉ được tính đúng một lần.
        invoice_daily = db.execute(
            """SELECT date(issued_at, '+7 hours') day, COUNT(*) invoice_count,
                       COALESCE(SUM(total),0) revenue, COALESCE(SUM(discount),0) discount,
                       COALESCE(SUM(tax),0) tax
                FROM invoices WHERE status <> 'Đã hủy'
                  AND date(issued_at, '+7 hours') BETWEEN ? AND ?
                """ + (" AND status=?" if invoice_status else "") +
                " GROUP BY day ORDER BY day", invoice_params
        ).fetchall()
        invoice_by_day = {row["day"]: dict(row) for row in invoice_daily}
        series = []
        for row in revenue_rows:
            invoice = invoice_by_day.get(row["day"], {})
            series.append({
                "day": row["day"], "invoice_count": int(invoice.get("invoice_count", 0)),
                "revenue": int(invoice.get("revenue", 0)), "labor": int(row["labor"]),
                "parts": int(row["parts"]), "discount": int(invoice.get("discount", 0)),
                "tax": int(invoice.get("tax", 0)),
            })
        # Hóa đơn có thể chưa có invoice_items (dữ liệu legacy); vẫn xuất hiện trong series.
        seen_days = {item["day"] for item in series}
        for day, invoice in invoice_by_day.items():
            if day not in seen_days:
                series.append({"day": day, "invoice_count": int(invoice["invoice_count"]),
                               "revenue": int(invoice["revenue"]), "labor": 0, "parts": 0,
                               "discount": int(invoice["discount"]), "tax": int(invoice["tax"])})
        series.sort(key=lambda item: item["day"])
        monthly: dict[str, dict] = {}
        for point in series:
            month = point["day"][:7]
            bucket = monthly.setdefault(month, {"day": month, "invoice_count": 0, "revenue": 0,
                                                "labor": 0, "parts": 0, "discount": 0, "tax": 0})
            for key in ("invoice_count", "revenue", "labor", "parts", "discount", "tax"):
                bucket[key] += point[key]

        summary = {
            key: sum(int(item[key]) for item in series)
            for key in ("invoice_count", "revenue", "labor", "parts", "discount", "tax")
        }
        # Only a reconciliation of invoice item rows with invoice totals, not a
        # replacement for invoices.total (legacy invoices may lack item rows).
        summary["reconciled_total"] = summary["labor"] + summary["parts"] - summary["discount"] + summary["tax"]
        summary["reconciliation_difference"] = summary["revenue"] - summary["reconciled_total"]
        collected = db.execute("""SELECT COALESCE(SUM(p.amount),0) FROM payments p
            JOIN invoices i ON i.id=p.invoice_id WHERE p.status='completed' AND i.status<>'Đã hủy'
            AND date(p.paid_at, '+7 hours') BETWEEN ? AND ?""",
            (start, end)).fetchone()[0]
        summary["collected"] = int(collected)
        length = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
        prior_end = date.fromisoformat(start) - timedelta(days=1)
        prior_start = prior_end - timedelta(days=length - 1)
        previous = _invoice_window(db, prior_start.isoformat(), prior_end.isoformat(), invoice_status)
        delta = summary["revenue"] - int(previous["revenue"])
        comparison = {"from": prior_start.isoformat(), "to": prior_end.isoformat(),
                      "revenue": int(previous["revenue"]), "invoice_count": int(previous["invoice_count"]),
                      "difference": delta, "percent": round(delta / previous["revenue"] * 100, 1)
                      if previous["revenue"] else None}
        debt_row = db.execute(
            """SELECT COUNT(*) invoice_count,
                      COALESCE(SUM(CASE WHEN total > paid_amount THEN total-paid_amount ELSE 0 END),0) amount
               FROM invoices WHERE status <> 'Đã hủy' AND total > paid_amount"""
        ).fetchone()
        invoice_status_counts = {row["status"]: row["count"] for row in db.execute(
            "SELECT status,COUNT(*) count FROM invoices WHERE status<>'Đã hủy' GROUP BY status")}
        summary["payment_status_counts"] = invoice_status_counts
        debts = [dict(row) for row in db.execute(
            """SELECT i.id, i.code, i.status, i.total, i.paid_amount,
                      i.total-i.paid_amount remaining, i.due_at, r.code order_code,
                      r.plate, r.customer_name
                FROM invoices i JOIN repair_orders r ON r.id=i.repair_order_id
                WHERE i.status <> 'Đã hủy' AND i.total > i.paid_amount
                ORDER BY COALESCE(i.due_at, i.issued_at), i.id LIMIT 100"""
        ).fetchall()]

        active_where = f"status IN ({', '.join('?' for _ in ACTIVE_STATUSES)})"
        active_params: list = list(ACTIVE_STATUSES)
        if order_status:
            active_where += " AND status=?"
            active_params.append(order_status)
        summary["active_orders"] = db.execute(
            "SELECT COUNT(*) FROM repair_orders WHERE " + active_where, active_params).fetchone()[0]
        active_orders = [dict(row) for row in db.execute(
            f"""SELECT id, code, plate, customer_name, technician, status, status_code,
                        note, total, opened_at
                 FROM repair_orders WHERE {active_where}
                 ORDER BY opened_at LIMIT 100""", active_params
        ).fetchall()]

        appointment_sql = """SELECT id, customer_name, plate, service, appointment_at, duration_min,
                                    status, technician
                             FROM appointments
                             WHERE date(appointment_at, '+7 hours') BETWEEN ? AND ?"""
        appointment_params: list = [start, end]
        if appointment_status:
            appointment_sql += " AND status=?"
            appointment_params.append(appointment_status)
        appointment_sql += " ORDER BY appointment_at LIMIT 100"
        appointments = [dict(row) for row in db.execute(appointment_sql, appointment_params).fetchall()]
        for item in appointments:
            item["appointment_at"] = vn_text(item["appointment_at"])

        history_sql = """SELECT h.id, h.plate, h.repaired_at, h.mileage, h.services, h.note, h.total,
                                 r.code order_code,
                                 c.id customer_id, c.name customer_name, v.make, v.model
                          FROM repair_history h
                          LEFT JOIN repair_orders r ON r.id=h.repair_order_id
                          LEFT JOIN vehicles v ON v.id=h.vehicle_id
                          LEFT JOIN customers c ON c.id=v.customer_id"""
        history_sql += " WHERE date(h.repaired_at, '+7 hours') BETWEEN ? AND ?"
        history_params: list = [start, end]
        if history_query and history_query.strip():
            needle = f"%{history_query.strip()}%"
            history_sql += " AND (h.plate LIKE ? OR c.name LIKE ? OR c.phone LIKE ? OR r.code LIKE ?)"
            history_params.extend([needle, needle, needle, needle])
        history_sql += " ORDER BY h.repaired_at DESC LIMIT 100"
        history = [dict(row) for row in db.execute(history_sql, history_params).fetchall()]

        popular_services = [dict(row) for row in db.execute(
            """SELECT ii.name, CAST(SUM(ii.quantity) AS REAL) quantity, SUM(ii.line_total) amount,
                      COUNT(DISTINCT i.id) invoice_count
                FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id
                WHERE ii.kind='Dịch vụ' AND i.status <> 'Đã hủy'
                  AND date(i.issued_at, '+7 hours') BETWEEN ? AND ?
                """ + invoice_filter +
                (" AND EXISTS(SELECT 1 FROM quote_items qi JOIN services s ON s.id=qi.service_id "
                 "WHERE qi.id=ii.quote_item_id AND s.category=?)" if service_category else "") +
                " GROUP BY ii.name ORDER BY quantity DESC, amount DESC LIMIT 10",
            (*invoice_params, service_category) if service_category else invoice_params
        ).fetchall()]
        popular_parts = [dict(row) for row in db.execute(
            """SELECT ii.name, CAST(SUM(ii.quantity) AS REAL) quantity, SUM(ii.line_total) amount,
                      COUNT(DISTINCT i.id) invoice_count,MAX(p.code) code,MAX(p.unit) unit,
                      MAX(p.stock) stock,MAX(p.min_stock) min_stock
                FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id
                LEFT JOIN quote_items qi ON qi.id=ii.quote_item_id
                LEFT JOIN parts p ON p.id=qi.part_id
                WHERE ii.kind='Phụ tùng' AND i.status <> 'Đã hủy'
                  AND date(i.issued_at, '+7 hours') BETWEEN ? AND ?
                """ + invoice_filter + (" AND p.category=?" if part_category else "") +
                " GROUP BY ii.name ORDER BY quantity DESC, amount DESC LIMIT 10",
            (*invoice_params, part_category) if part_category else invoice_params
        ).fetchall()]
        inventory = [dict(row) for row in db.execute(
            """SELECT id, code, name, category, unit, stock, min_stock,
                       stock*cost_price cost_value,
                       CASE WHEN stock=0 THEN 'Hết hàng' WHEN stock<=min_stock THEN 'Sắp hết' ELSE 'An toàn' END status
                FROM parts WHERE active=1""" + (" AND category=?" if part_category else "") +
                " ORDER BY stock<=min_stock DESC, stock, name LIMIT 100",
            (part_category,) if part_category else ()
        ).fetchall()]
        stock_counts = db.execute("""SELECT COUNT(*) total,
            COALESCE(SUM(CASE WHEN stock=0 THEN 1 ELSE 0 END),0) out_of_stock,
            COALESCE(SUM(CASE WHEN stock<=min_stock THEN 1 ELSE 0 END),0) low_stock
            FROM parts WHERE active=1""" + (" AND category=?" if part_category else ""),
            (part_category,) if part_category else ()).fetchone()
        summary["inventory_counts"] = dict(stock_counts)
        appointment_counts = {row["status"]: row["count"] for row in db.execute(
            "SELECT status,COUNT(*) count FROM appointments WHERE date(appointment_at, '+7 hours') BETWEEN ? AND ?"
            + (" AND status=?" if appointment_status else "") + " GROUP BY status",
            (*appointment_params[:2], appointment_status) if appointment_status else appointment_params[:2])}
        summary["appointment_counts"] = appointment_counts

    return {
        "period": {"from": start, "to": end}, "comparison": comparison, "rules": REPORT_RULES,
        "filters": {"invoice_status": invoice_status, "appointment_status": appointment_status,
                    "order_status": order_status, "part_category": part_category,
                    "service_category": service_category, "history_query": history_query},
        "summary": {**summary, "debt": int(debt_row["amount"]),
                    "debt_invoices": int(debt_row["invoice_count"])},
        "revenue_series": series, "monthly_series": list(monthly.values()), "active_orders": active_orders,
        "appointments": appointments, "history": history,
        "popular_services": popular_services, "popular_parts": popular_parts,
        "inventory": inventory, "debts": debts,
    }


@router.get("/reports/drilldown")
def report_drilldown(
    kind: Literal["revenue", "debt", "service", "part", "inventory", "history", "orders", "appointments"],
    from_date: date | None = None, to_date: date | None = None,
    day: date | None = None, name: str | None = Query(default=None, max_length=180),
    month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    q: str | None = Query(default=None, max_length=100),
    invoice_status: Literal["Chưa thanh toán", "Thanh toán một phần", "Đã thanh toán"] | None = None,
    appointment_status: str | None = Query(default=None, max_length=50),
    order_status: str | None = Query(default=None, max_length=50),
    part_category: str | None = Query(default=None, max_length=80),
    service_category: str | None = Query(default=None, max_length=80),
    stock: Literal["all", "low", "out"] = "all",
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=50),
    user: dict = Depends(require_permission("reports")),
) -> dict:
    """Bounded source rows with the same validity/date rules as overview; read-only."""
    start, end = _period(from_date, to_date)
    where: list[str] = []
    params: list = []
    if kind == "revenue":
        where = ["i.status<>'Đã hủy'", "date(i.issued_at, '+7 hours') BETWEEN ? AND ?"]
        params = [start, end]
        if day:
            if not start <= day.isoformat() <= end:
                from fastapi import HTTPException
                raise HTTPException(422, "Ngày chọn nằm ngoài khoảng báo cáo")
            where.append("date(i.issued_at, '+7 hours')=?")
            params.append(day.isoformat())
        if month:
            if month < start[:7] or month > end[:7]:
                from fastapi import HTTPException
                raise HTTPException(422, "Tháng chọn nằm ngoài khoảng báo cáo")
            where.append("substr(date(i.issued_at, '+7 hours'),1,7)=?")
            params.append(month)
        if invoice_status:
            where.append("i.status=?")
            params.append(invoice_status)
        base = " FROM invoices i JOIN repair_orders r ON r.id=i.repair_order_id WHERE " + " AND ".join(where)
        fields = "i.id,i.code,i.status,i.issued_at,i.total,i.paid_amount,r.code order_code,r.plate"
        amount_field = "i.total"
        ordering = "i.issued_at DESC,i.id DESC"
    elif kind == "debt":
        # Debt is a current balance, independent of invoice issue-date filters.
        base = " FROM invoices i JOIN repair_orders r ON r.id=i.repair_order_id WHERE i.status<>'Đã hủy' AND i.total>i.paid_amount"
        fields = "i.id,i.code,i.status,i.issued_at,i.total,i.paid_amount,i.total-i.paid_amount remaining,r.code order_code,r.plate"
        amount_field = "i.total-i.paid_amount"
        ordering = "i.issued_at DESC,i.id DESC"
    elif kind in ("service", "part"):
        if not name:
            from fastapi import HTTPException
            raise HTTPException(422, "Cần chọn tên hạng mục để xem nguồn")
        where = ["ii.kind=?", "ii.name=?", "i.status<>'Đã hủy'",
                 "date(i.issued_at, '+7 hours') BETWEEN ? AND ?"]
        params = ["Dịch vụ" if kind == "service" else "Phụ tùng", name, start, end]
        if invoice_status:
            where.append("i.status=?")
            params.append(invoice_status)
        if kind == "service" and service_category:
            where.append("EXISTS(SELECT 1 FROM quote_items qi JOIN services s ON s.id=qi.service_id WHERE qi.id=ii.quote_item_id AND s.category=?)")
            params.append(service_category)
        if kind == "part" and part_category:
            where.append("EXISTS(SELECT 1 FROM quote_items qi JOIN parts p ON p.id=qi.part_id WHERE qi.id=ii.quote_item_id AND p.category=?)")
            params.append(part_category)
        base = " FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id WHERE " + " AND ".join(where)
        fields = "ii.id,ii.name,ii.kind,ii.quantity,ii.line_total,i.code invoice_code,i.issued_at"
        amount_field = "ii.line_total"
        ordering = "i.issued_at DESC,ii.id DESC"
    elif kind == "inventory":
        where = ["p.active=1"]
        if stock == "low":
            where.append("p.stock<=p.min_stock")
        elif stock == "out":
            where.append("p.stock=0")
        if part_category:
            where.append("p.category=?")
            params.append(part_category)
        if q:
            where.append("(p.code LIKE ? OR p.name LIKE ?)")
            params.extend([f"%{q.strip()}%"] * 2)
        base = " FROM parts p WHERE " + " AND ".join(where)
        fields = "p.id,p.code,p.name,p.category,p.stock,p.min_stock,p.unit"
        amount_field = "0"
        ordering = "p.stock ASC,p.id DESC"
    elif kind == "history":
        where = ["date(h.repaired_at, '+7 hours') BETWEEN ? AND ?"]
        params = [start, end]
        if q:
            where.append("(h.plate LIKE ? OR r.code LIKE ? OR c.name LIKE ? OR c.phone LIKE ?)")
            params.extend([f"%{q.strip()}%"] * 4)
        base = (" FROM repair_history h LEFT JOIN repair_orders r ON r.id=h.repair_order_id "
                "LEFT JOIN vehicles v ON v.id=h.vehicle_id LEFT JOIN customers c ON c.id=v.customer_id WHERE "
                + " AND ".join(where))
        fields = "h.id,h.plate,h.repaired_at,h.services,h.total,r.code order_code"
        amount_field = "0"  # history.total is not equivalent to collected money
        ordering = "h.repaired_at DESC,h.id DESC"
    elif kind == "orders":
        where = [f"r.status IN ({', '.join('?' for _ in ACTIVE_STATUSES)})"]
        params = list(ACTIVE_STATUSES)
        if order_status:
            where.append("r.status=?")
            params.append(order_status)
        if q:
            where.append("(r.code LIKE ? OR r.plate LIKE ?)")
            params.extend([f"%{q.strip()}%"] * 2)
        base = " FROM repair_orders r WHERE " + " AND ".join(where)
        fields = "r.id,r.code,r.plate,r.status,r.status_code,r.opened_at,r.technician"
        amount_field = "0"
        ordering = "r.opened_at DESC,r.id DESC"
    else:
        where = ["date(a.appointment_at, '+7 hours') BETWEEN ? AND ?"]
        params = [start, end]
        if appointment_status:
            where.append("a.status=?")
            params.append(appointment_status)
        base = " FROM appointments a WHERE " + " AND ".join(where)
        fields = "a.id,a.plate,a.appointment_at,a.duration_min,a.status,a.service"
        amount_field = "0"
        ordering = "a.appointment_at DESC,a.id DESC"
    with connect() as db:
        metrics = db.execute(f"SELECT COUNT(*) total, COALESCE(SUM({amount_field}),0) amount" + base, params).fetchone()
        rows = [dict(row) for row in db.execute(
            f"SELECT {fields}" + base + f" ORDER BY {ordering} LIMIT ? OFFSET ?",
            (*params, page_size, (page - 1) * page_size))]
    return {"kind": kind, "period": {"from": start, "to": end}, "total": metrics["total"],
            "amount": metrics["amount"], "page": page, "page_size": page_size,
            "pages": max(1, (metrics["total"] + page_size - 1) // page_size), "items": rows}


@router.get("/reports/export")
def export_report(
    kind: Literal["revenue", "debt", "service", "part", "inventory", "history", "orders", "appointments"],
    from_date: date | None = None, to_date: date | None = None,
    day: date | None = None, name: str | None = Query(default=None, max_length=180),
    month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    q: str | None = Query(default=None, max_length=100),
    invoice_status: Literal["Chưa thanh toán", "Thanh toán một phần", "Đã thanh toán"] | None = None,
    appointment_status: str | None = None, order_status: str | None = None,
    part_category: str | None = None, service_category: str | None = None,
    stock: Literal["all", "low", "out"] = "all",
    user: dict = Depends(require_permission("reports")),
) -> Response:
    """CSV of exactly the scoped source rows; bounded to avoid unbounded exports."""
    from fastapi import HTTPException
    first = report_drilldown(kind, from_date, to_date, day, name, month, q, invoice_status,
                             appointment_status, order_status, part_category, service_category, stock, 1, 50, user)
    if first["total"] > 5000:
        raise HTTPException(422, "Xuất tối đa 5.000 dòng; hãy thu hẹp kỳ hoặc bộ lọc")
    records = list(first["items"])
    for page in range(2, first["pages"] + 1):
        records.extend(report_drilldown(kind, from_date, to_date, day, name, month, q, invoice_status,
                                        appointment_status, order_status, part_category, service_category,
                                        stock, page, 50, user)["items"])
    output = io.StringIO()
    writer = csv.writer(output)
    output.write('\ufeff')
    writer.writerow(["Report", kind, "From", first["period"]["from"], "To", first["period"]["to"],
                     "Exported (UTC+7)", datetime.now(VN_TZ).isoformat()])
    writer.writerow(["Total rows", first["total"], "Total amount", first["amount"]])
    if records:
        keys = list(records[0])
        writer.writerow(keys)
        for row in records:
            writer.writerow([("'" + str(row[key]) if str(row[key]).startswith(("=", "+", "-", "@")) else row[key])
                             if row[key] is not None else "" for key in keys])
    filename = f"threeh-{kind}-{first['period']['from']}-{first['period']['to']}.csv"
    return Response(output.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"',
                             "X-Content-Type-Options": "nosniff"})


class ReportQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=300)
    from_date: date
    to_date: date
    invoice_status: Literal["Chưa thanh toán", "Thanh toán một phần", "Đã thanh toán"] | None = None
    appointment_status: str | None = None
    order_status: str | None = None
    part_category: str | None = None
    service_category: str | None = None


@router.post("/reports/explain")
def explain_report(item: ReportQuestion, user: dict = Depends(require_permission("reports"))) -> dict:
    """Read-only explanations of the same report snapshot; never model-generated figures."""
    start, end = _period(item.from_date, item.to_date)
    if any(term in item.question.casefold() for term in ("khung giờ", "lịch hẹn", "chồng lấn", "đông xe")):
        from ...appointment_load import answer_appointment_load
        with connect() as db:
            answer = answer_appointment_load(db, item.question, user)
        if answer:
            result, sources = answer
            return {"result": result.content, "period": {"from": start, "to": end},
                    "sources": sources, "is_draft": True, "status": result.status,
                    "note": "Câu hỏi lịch hẹn theo ngày cụ thể dùng bộ phân tích tải lịch hiện có, không lấy từ kỳ doanh thu."}
        return {"result": "Chưa hỗ trợ câu hỏi lịch hẹn này trong phần giải thích báo cáo. Hãy nêu ngày và khung giờ cụ thể.",
                "period": {"from": start, "to": end}, "sources": [], "is_draft": True, "status": "no_data"}
    report = overview_report(item.from_date, item.to_date, item.appointment_status,
                             item.invoice_status, item.order_status, item.part_category,
                             item.service_category, None, user)
    summary, comparison = report["summary"], report["comparison"]
    folded = unicodedata.normalize("NFD", item.question.casefold().replace("đ", "d"))
    text = "".join(ch for ch in folded if unicodedata.category(ch) != "Mn")
    period = f"{start} đến {end} (giờ Việt Nam)"
    money = lambda n: f"{int(n):,}".replace(",", ".") + " ₫"
    sources: list[dict] = []
    if "cong no" in text or "con no" in text or "hoa don nao" in text:
        threshold_match = re.search(r"(?:tren|hon)\s+(\d+)\s*trieu", text)
        if threshold_match:
            threshold = int(threshold_match.group(1)) * 1_000_000
            with connect() as db:
                count, amount = db.execute("""SELECT COUNT(*),COALESCE(SUM(total-paid_amount),0)
                    FROM invoices WHERE status<>'Đã hủy' AND total-paid_amount>?""", (threshold,)).fetchone()
                debt = [dict(row) for row in db.execute("""SELECT id,code,total-paid_amount remaining
                    FROM invoices WHERE status<>'Đã hủy' AND total-paid_amount>?
                    ORDER BY remaining DESC,id DESC LIMIT 10""", (threshold,))]
        else:
            debt = report["debts"][:10]
            count, amount = summary["debt_invoices"], summary["debt"]
        answer = (f"Dữ kiện: Dư nợ hiện tại {money(amount)} trên {count} hóa đơn "
                  + (f"còn nợ trên {money(threshold)}" if threshold_match else "chưa thu đủ") +
                  ", không giới hạn theo kỳ phát hành. " +
                  ("Mã hóa đơn: " + ", ".join(f"{row['code']} ({money(row['remaining'])})" for row in debt) + ". " if debt else "") +
                  "Chỉ tính hóa đơn chưa hủy và phần dương giữa tổng tiền với đã thanh toán.")
        sources = [{"type": "invoice", "id": row["id"], "label": row["code"]} for row in debt]
    elif "sap het" in text or "ton kho" in text or "het hang" in text:
        low = [row for row in report["inventory"] if row["stock"] <= row["min_stock"]][:10]
        answer = (f"Dữ kiện: {summary['inventory_counts']['low_stock']} mã dưới hoặc bằng ngưỡng tồn tối thiểu "
                  "(bao gồm hết hàng). " + ", ".join(f"{row['code']}: {row['stock']}/{row['min_stock']} {row['unit']}" for row in low) +
                  ". Đây là tồn kho hiện tại, không phải lượng phụ tùng ghi trên hóa đơn.")
        sources = [{"type": "part", "id": row["id"], "label": row["code"]} for row in low]
    elif "phu tung" in text:
        top = report["popular_parts"][:3]
        answer = (f"Dữ kiện kỳ {period}: " +
                  ("; ".join(f"{row.get('code') or row['name']}: {row['quantity']:g} đơn vị trên {row['invoice_count']} hóa đơn" for row in top)
                   if top else "không có dòng phụ tùng hợp lệ") +
                  ". Số lượng hóa đơn không phải số lượng xuất kho hoặc số xe.")
        sources = [{"type": "invoice_items", "id": None, "label": "Dòng phụ tùng trên hóa đơn hợp lệ trong kỳ"}]
    elif "dich vu" in text or "pho bien" in text:
        top = report["popular_services"][:3]
        answer = (f"Dữ kiện kỳ {period}: " +
                  ("; ".join(f"{row['name']}: {row['quantity']:g} đơn vị ghi trên hóa đơn, {row['invoice_count']} hóa đơn" for row in top)
                   if top else "không có dòng dịch vụ hợp lệ") + ". Không đồng nhất số lượng này với số xe đã sửa.")
        sources = [{"type": "invoice_items", "id": None, "label": "Dòng dịch vụ trên hóa đơn hợp lệ trong kỳ"}]
    elif "phieu" in text or "dang xu ly" in text:
        answer = (f"Dữ kiện hiện tại: {summary['active_orders']} phiếu đang xử lý theo bộ lọc trạng thái. "
                  "Trạng thái sửa chữa không đồng nghĩa trạng thái thanh toán.")
        sources = [{"type": "repair_order", "id": row["id"], "label": row["code"]}
                   for row in report["active_orders"][:10]]
    elif "thuc thu" in text or "da thu" in text:
        answer = (f"Dữ kiện kỳ {period}: doanh thu theo ngày phát hành hóa đơn {money(summary['revenue'])}; "
                  f"tiền thực thu theo ngày thanh toán hợp lệ {money(summary['collected'])}. "
                  "Hai chỉ số dùng mốc thời gian khác nhau; chênh lệch không tự chứng minh thất thoát.")
        sources = [{"type": "invoices", "id": None, "label": "Hóa đơn hợp lệ và giao dịch completed theo kỳ"}]
    elif "doanh thu" in text or "ky truoc" in text:
        percent = (f"{comparison['percent']}%" if comparison["percent"] is not None else
                   "không có cơ sở tính tỷ lệ vì kỳ trước bằng 0")
        answer = (f"Dữ kiện kỳ {period}: doanh thu {money(summary['revenue'])} trên {summary['invoice_count']} hóa đơn. "
                  f"Kỳ trước {comparison['from']} đến {comparison['to']}: {money(comparison['revenue'])}; "
                  f"chênh lệch {money(comparison['difference'])}, tỷ lệ {percent}. "
                  "Đây là so sánh giá trị hóa đơn, không giải thích nguyên nhân tăng giảm.")
        sources = [{"type": "invoices", "id": None, "label": "Hóa đơn chưa hủy theo ngày phát hành (UTC+7)"}]
    else:
        return {"result": "Chưa có phép tính báo cáo đã xác nhận cho câu hỏi này. Vui lòng chọn câu hỏi gợi ý hoặc mở bảng dữ liệu nguồn.",
                "period": report["period"], "sources": [], "is_draft": True, "status": "no_data"}
    return {"result": answer, "period": report["period"], "sources": sources,
            "is_draft": True, "status": "success"}
