"""Tư vấn chu kỳ thay dầu từ hồ sơ xe và tài liệu kỹ thuật đã duyệt.

Chu kỳ có cấu trúc trong ``maintenance_intervals`` là nguồn duy nhất để tính
đến hạn. RAG chỉ là tài liệu tham khảo bổ sung; Ollama chỉ diễn đạt lại context
đã được backend kiểm soát và không đọc giá dịch vụ.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date, datetime

from .ai_service import AIResult, ai_service
from .technical_knowledge import search_technical
from .timeutil import VN_TZ, vn_datetime

SEVERE_TERMS = (
    "tac duong", "ket xe", "quang ngan", "di it", "chay pho", "dung cho",
    "cho may", "bui", "kho hanh", "nong", "keo tai", "chay dich vu", "taxi",
    "duong xau", "ngap", "tai trong",
)


def is_maintenance_interval_question(question: str) -> bool:
    text = ai_service._normalize_vi(question)
    if not ("thay dau" in text or "thay nhot" in text or "dau dong co" in text):
        return False
    if any(term in text for term in ("gia", "chi phi", "bao nhieu tien", "thoi gian sua")):
        return False
    return any(term in text for term in (
        "khi nao", "bao lau", "chu ky", "den han", "lan truoc", "lan toi", "tiep",
        "bao nhieu km", "km nua", "da thay", "can thay", "it di", "duong ngan",
        "chay dich vu", "tac duong", "thay chua"))


def _completed(status_code: str | None) -> bool:
    return status_code in ("COMPLETED", "DELIVERED")


def _intervals(articles: list[dict]) -> list[dict]:
    found: list[dict] = []
    for article in articles:
        text = " ".join(str(article.get(key) or "") for key in ("title", "symptoms", "content"))
        km = [int(value.replace(".", "").replace(",", ""))
              for value in re.findall(r"(?<!\d)(\d{1,3}(?:[.,]\d{3})+|\d{4,6})\s*km\b", text.casefold())]
        months = [int(value) for value in re.findall(r"(?<!\d)(\d{1,2})\s*(?:tháng|thang)\b", text.casefold())]
        if km or months:
            found.append({"source_id": article.get("id"), "source_name": article.get("source_name"),
                          "km": sorted(set(km)), "months": sorted(set(months))})
    return found


def _engine_oil_articles(articles: list[dict]) -> list[dict]:
    """Keep engine-oil evidence only; brake/transmission oil is a different schedule."""
    result = []
    for article in articles:
        text = ai_service._normalize_vi(" ".join(
            str(article.get(key) or "") for key in ("title", "symptoms", "content")))
        if (any(term in text for term in ("dau dong co", "dau may", "thay dau dong co"))
                and not any(term in text for term in ("dau phanh", "dau hop so", "atf", "cvt"))):
            result.append(article)
    return result


def _history(db, vehicle_id: int) -> list[dict]:
    rows = db.execute(
        """SELECT rh.id,rh.repair_order_id,rh.repaired_at,rh.mileage,
                  ro.code,ro.status_code,ro.status
           FROM repair_history rh JOIN repair_orders ro ON ro.id=rh.repair_order_id
           WHERE rh.vehicle_id=? ORDER BY rh.repaired_at DESC,rh.id DESC""", (vehicle_id,)
    ).fetchall()
    result = []
    for row in rows:
        if not _completed(row["status_code"]):
            continue
        items = [dict(item) for item in db.execute(
            """SELECT kind,name,quantity FROM repair_order_items
               WHERE repair_order_id=? ORDER BY id""", (row["repair_order_id"],)
        ).fetchall()]
        normalized = " ".join(ai_service._normalize_vi(str(item["name"] or "")) for item in items)
        if not any(term in normalized for term in ("thay dau dong co", "thay nhot", "thay dau may")):
            continue
        oil_items = [item["name"] for item in items if any(term in ai_service._normalize_vi(str(item["name"] or ""))
                     for term in ("dau dong co", "dau may", "5w-", "0w-"))]
        result.append({"history_id": row["id"], "repair_order_id": row["repair_order_id"],
                      "order_code": row["code"], "date": row["repaired_at"],
                      "mileage": row["mileage"], "status_code": row["status_code"],
                      "items": oil_items})
    return result


def _fold(value: object) -> str:
    text = unicodedata.normalize("NFD", str(value or "").casefold())
    return "".join(char for char in text if unicodedata.category(char) != "Mn").replace("đ", "d")


def _norm_engine(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", _fold(value))


def _add_months(moment: date, months: int) -> date:
    month_index = moment.month - 1 + months
    year = moment.year + month_index // 12
    month = month_index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def find_oil_interval(db, vehicle: dict | None) -> dict | None:
    """Chọn bản ghi approved cụ thể nhất, gắn bài published đã duyệt kỹ thuật."""
    if not vehicle:
        return None
    make = _fold(vehicle.get("make"))
    model = _fold(vehicle.get("model"))
    if not make or not model:
        return None
    year = vehicle.get("year")
    engine = _norm_engine(vehicle.get("engine_code"))
    rows = db.execute(
        """SELECT mi.*,a.title AS article_title,a.status AS article_status,
                  a.deleted_at AS article_deleted_at,a.technical_reviewed_by,
                  a.updated_at AS article_updated_at
           FROM maintenance_intervals mi
           LEFT JOIN technical_articles a ON a.id=mi.article_id
           WHERE mi.service_type='engine_oil' AND mi.status='approved'"""
    ).fetchall()
    exact: list[tuple[int, dict]] = []
    unverified: list[dict] = []
    for row in rows:
        item = dict(row)
        if (not item.get("article_id") or item.get("article_status") != "published"
                or item.get("article_deleted_at") or item.get("technical_reviewed_by") is None):
            continue
        if _fold(item["vehicle_make"]) != make or _fold(item["vehicle_model"]) != model:
            continue
        if item.get("year_from") is not None or item.get("year_to") is not None:
            if year is None:
                continue
            if item.get("year_from") is not None and int(year) < int(item["year_from"]):
                continue
            if item.get("year_to") is not None and int(year) > int(item["year_to"]):
                continue
        if not item.get("interval_km") and not item.get("interval_months"):
            continue
        row_engine = _norm_engine(item.get("engine_code"))
        if row_engine and not engine:
            # Hồ sơ chưa có mã động cơ: chỉ dùng khi mọi biến thể cùng mốc.
            item["engine_match"] = "unverified"
            unverified.append(item)
            continue
        if row_engine and row_engine != engine:
            continue
        item["engine_match"] = "exact" if row_engine else "not_required"
        specificity = 8 if row_engine else 0
        if item.get("year_from") is not None or item.get("year_to") is not None:
            specificity += 4
        exact.append((specificity, item))
    candidates = exact
    if not candidates and unverified:
        signatures = {
            (item.get("interval_km"), item.get("interval_months"),
             item.get("severe_interval_km"), item.get("severe_interval_months"))
            for item in unverified
        }
        if len(signatures) == 1:
            candidates = [(4 if item.get("year_from") is not None
                           or item.get("year_to") is not None else 0, item)
                          for item in unverified]
    if not candidates:
        return None
    candidates.sort(key=lambda pair: (-pair[0], -(pair[1].get("year_from") or 0), pair[1]["id"]))
    chosen = candidates[0][1]
    chosen["engine_verified"] = chosen.get("engine_match") in ("exact", "not_required")
    return chosen


def _wants_severe(question: str) -> bool:
    text = ai_service._normalize_vi(question)
    return any(term in text for term in SEVERE_TERMS)


def _active_interval(interval: dict, severe: bool) -> dict:
    if severe and (interval.get("severe_interval_km") or interval.get("severe_interval_months")):
        return {"basis": "severe", "km": interval.get("severe_interval_km"),
                "months": interval.get("severe_interval_months")}
    return {"basis": "normal", "km": interval.get("interval_km"),
            "months": interval.get("interval_months")}


def _compute_due(active: dict, latest: dict | None, current: int | None) -> dict:
    due = {"status": "unknown", "basis": active.get("basis"),
           "interval_km": active.get("km"), "interval_months": active.get("months"),
           "next_due_km": None, "next_due_date": None,
           "km_remaining": None, "days_remaining": None}
    if not latest:
        return due
    latest_mileage = latest.get("mileage")
    if active.get("km") and latest_mileage is not None:
        due["next_due_km"] = int(latest_mileage) + int(active["km"])
        if current is not None:
            due["km_remaining"] = due["next_due_km"] - int(current)
    moment = vn_datetime(latest.get("date"))
    if active.get("months") and moment:
        next_date = _add_months(moment.date(), int(active["months"]))
        due["next_due_date"] = next_date.isoformat()
        due["days_remaining"] = (next_date - datetime.now(VN_TZ).date()).days
    km_remaining = due.get("km_remaining")
    days_remaining = due.get("days_remaining")
    if km_remaining is None and days_remaining is None:
        return due
    if ((km_remaining is not None and km_remaining <= 0)
            or (days_remaining is not None and days_remaining <= 0)):
        due["status"] = "overdue"
    elif ((km_remaining is not None and km_remaining <= 1000)
          or (days_remaining is not None and days_remaining <= 30)):
        due["status"] = "due_soon"
    else:
        due["status"] = "not_due"
    return due


def _public_interval(row: dict) -> dict:
    return {key: row.get(key) for key in (
        "id", "service_type", "vehicle_make", "vehicle_model", "year_from", "year_to",
        "engine_code", "market", "interval_km", "interval_months",
        "severe_interval_km", "severe_interval_months", "conditions_note", "oil_spec",
        "source_name", "source_url", "document_version", "article_id", "article_title",
        "article_updated_at", "status", "approved_at", "engine_match", "engine_verified")}


def build_maintenance_context(db, question: str, vehicle: dict | None,
                              articles: list[dict]) -> dict:
    context: dict = {
        "question": question, "vehicle_verified": {}, "latest_oil_change": None,
        "current_mileage": None, "mileage_since_last_oil": None,
        "days_since_last_oil": None, "interval": None, "active_interval": None,
        "due": None, "intervals_from_rag": _intervals(articles),
        "missing_data": [], "warnings": [], "conclusion": "chưa đủ dữ liệu",
    }
    if not vehicle:
        context["missing_data"] = ["xe đang được hỏi", "số km hiện tại", "hãng/dòng xe"]
        return context
    context["vehicle_verified"] = {key: vehicle.get(key) for key in (
        "id", "make", "model", "year", "variant", "engine_code", "fuel_type", "mileage")}
    current = vehicle.get("mileage")
    context["current_mileage"] = current
    history = _history(db, vehicle["id"])
    latest = history[0] if history else None
    if latest:
        context["latest_oil_change"] = latest
        if current is not None and latest.get("mileage") is not None:
            delta = int(current) - int(latest["mileage"])
            if delta < 0:
                context["warnings"].append(
                    "Số km hiện tại thấp hơn số km tại lần thay dầu; cần xác minh dữ liệu.")
            else:
                context["mileage_since_last_oil"] = delta
        else:
            context["missing_data"].append("số km hiện tại hoặc số km lần thay dầu gần nhất")
        moment = vn_datetime(latest.get("date"))
        if moment:
            context["days_since_last_oil"] = (datetime.now(VN_TZ).date() - moment.date()).days
    else:
        context["missing_data"].append(
            "lần thay dầu động cơ đã hoàn thành trong lịch sử xe")
    if current is None:
        context["missing_data"].append("số km hiện tại")

    interval = find_oil_interval(db, vehicle)
    if interval:
        context["interval"] = _public_interval(interval)
        active = _active_interval(interval, _wants_severe(question))
        context["active_interval"] = active
        context["due"] = _compute_due(active, latest, current)
    elif not context["intervals_from_rag"]:
        context["missing_data"].append(
            "chu kỳ thay dầu phù hợp từ tài liệu kỹ thuật đã duyệt")

    due_status = (context.get("due") or {}).get("status")
    if context["warnings"]:
        context["conclusion"] = "cần xác minh"
    elif due_status == "overdue":
        context["conclusion"] = "đã đến hạn"
    elif due_status == "due_soon":
        context["conclusion"] = "sắp đến hạn"
    elif due_status == "not_due":
        context["conclusion"] = "chưa đến hạn"
    elif not context["missing_data"]:
        context["conclusion"] = "đủ dữ liệu để đối chiếu"
    return context


def answer_maintenance_interval(db, question: str, vehicle: dict | None):
    """Tra cứu chu kỳ có cấu trúc, RAG chỉ bổ sung; không đọc giá dịch vụ."""
    if not is_maintenance_interval_question(question):
        return None
    verified_vehicle = vehicle or {}
    query = "Lịch bảo dưỡng thay dầu động cơ"
    if verified_vehicle:
        query += " cho " + " ".join(str(verified_vehicle.get(key) or "")
                                    for key in ("make", "model", "year", "variant",
                                                "engine_code", "fuel_type"))
    query += "; chu kỳ theo kilomet, thời gian và điều kiện sử dụng"
    articles = _engine_oil_articles(
        search_technical(db, query, limit=6, vehicle=dict(vehicle) if vehicle else None))[:3]
    context = build_maintenance_context(db, question, vehicle, articles)
    interval = context.get("interval") or {}
    sources: list[dict] = []
    if context.get("latest_oil_change"):
        latest = context["latest_oil_change"]
        sources.append({"type": "repair_history", "id": latest["history_id"],
                        "label": "Lần thay dầu đã hoàn thành trong lịch sử xe",
                        "date": str(latest.get("date") or "")[:10]})
    if interval:
        sources.append({
            "type": "maintenance_interval", "id": interval["id"],
            "label": (f"Chu kỳ thay dầu: {interval['vehicle_make']} {interval['vehicle_model']} "
                      f"· {interval['source_name']}"),
            "date": str(interval.get("approved_at") or "")[:10],
        })
        if interval.get("article_id"):
            sources.append({
                "type": "technical_article", "id": interval["article_id"],
                "label": f"Bài kỹ thuật đã duyệt: {interval.get('article_title')}",
                "date": str(interval.get("article_updated_at") or "")[:10],
            })
    for article in articles:
        if interval and article.get("id") == interval.get("article_id"):
            continue
        sources.append({"type": "technical_article", "id": article["id"],
                        "label": f"Kiến thức bảo dưỡng: {article['title']} · {article['source_name']}",
                        "date": str(article.get("updated_at") or "")[:10]})
    return ai_service.narrate_maintenance_interval(question, context, articles), sources
