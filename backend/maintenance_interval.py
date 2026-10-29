"""Tư vấn chu kỳ thay dầu từ hồ sơ xe và tài liệu kỹ thuật đã duyệt.

Module này không đọc giá dịch vụ. Mọi số km/ngày lịch sử đều lấy từ DB; Ollama
chỉ diễn đạt lại context đã được backend kiểm soát.
"""

from __future__ import annotations

import re
from datetime import datetime

from .ai_service import AIResult, ai_service
from .technical_knowledge import search_technical
from .timeutil import VN_TZ, vn_datetime


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


def build_maintenance_context(db, question: str, vehicle: dict | None,
                              articles: list[dict]) -> dict:
    context: dict = {"question": question, "vehicle_verified": {}, "latest_oil_change": None,
                     "current_mileage": None, "mileage_since_last_oil": None,
                     "days_since_last_oil": None, "intervals_from_rag": _intervals(articles),
                     "missing_data": [], "warnings": [], "conclusion": "chưa đủ dữ liệu"}
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
                context["warnings"].append("Số km hiện tại thấp hơn số km tại lần thay dầu; cần xác minh dữ liệu.")
            else:
                context["mileage_since_last_oil"] = delta
        else:
            context["missing_data"].append("số km hiện tại hoặc số km lần thay dầu gần nhất")
        moment = vn_datetime(latest.get("date"))
        if moment:
            context["days_since_last_oil"] = (datetime.now(VN_TZ).date() - moment.date()).days
    else:
        context["missing_data"].append("lần thay dầu động cơ đã hoàn thành trong lịch sử xe")
    if current is None:
        context["missing_data"].append("số km hiện tại")
    if not context["intervals_from_rag"]:
        context["missing_data"].append("chu kỳ thay dầu phù hợp từ tài liệu kỹ thuật đã duyệt")
    if context["warnings"]:
        context["conclusion"] = "cần xác minh"
    elif not context["missing_data"]:
        context["conclusion"] = "đủ dữ liệu để đối chiếu"
    return context


def answer_maintenance_interval(db, question: str, vehicle: dict | None):
    """Truy vấn RAG theo cấu hình xe rồi tổng hợp dữ liệu lịch sử thực tế."""
    if not is_maintenance_interval_question(question):
        return None
    verified_vehicle = vehicle or {}
    query = "Lịch bảo dưỡng thay dầu động cơ"
    if verified_vehicle:
        query += " cho " + " ".join(str(verified_vehicle.get(key) or "")
                                    for key in ("make", "model", "year", "variant", "engine_code", "fuel_type"))
    query += "; chu kỳ theo kilomet, thời gian và điều kiện sử dụng"
    articles = search_technical(db, query, limit=3, vehicle=dict(vehicle) if vehicle else None)
    context = build_maintenance_context(db, question, vehicle, articles)
    sources = [{"type": "technical_article", "id": article["id"],
                "label": f"Kiến thức bảo dưỡng: {article['title']} · {article['source_name']}",
                "date": str(article.get("updated_at") or "")[:10]}
               for article in articles]
    if context.get("latest_oil_change"):
        latest = context["latest_oil_change"]
        sources.insert(0, {"type": "repair_history", "id": latest["history_id"],
                           "label": "Lần thay dầu đã hoàn thành trong lịch sử xe",
                           "date": str(latest.get("date") or "")[:10]})
    return ai_service.narrate_maintenance_interval(question, context, articles), sources
