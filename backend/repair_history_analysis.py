"""Phân tích lịch sử sửa chữa xác định được từ database, không dùng suy đoán của LLM."""

from __future__ import annotations

from collections import defaultdict
from calendar import monthrange
from datetime import datetime, timedelta
from typing import Any

from .ai_service import ai_service
from .timeutil import VN_TZ, vn_datetime


def _date(value: Any) -> datetime | None:
    return vn_datetime(value)


def _day(value: Any) -> str:
    moment = _date(value)
    return moment.strftime("%Y-%m-%d") if moment else str(value or "Không rõ ngày")[:10]


def _code(visit: dict) -> str:
    return visit.get("order_code") or f"LS-{int(visit['id']):05d}"


def _work_state(status_code: str | None) -> str:
    if status_code in ("COMPLETED", "DELIVERED"):
        return "Đã hoàn thành"
    if status_code in ("INSPECTING", "IN_PROGRESS"):
        return "Đang thực hiện"
    if status_code == "WAITING_FOR_PARTS":
        return "Chờ phụ tùng"
    if status_code in ("RECEIVED", "QUOTED", "APPROVED", "ON_HOLD"):
        return "Chờ xử lý"
    return "Chưa đủ dữ liệu xác định"


def _fitment_matches(rule: dict, vehicle: dict) -> bool:
    normalize = ai_service._normalize_vi
    if normalize(rule.get("make") or "") != normalize(vehicle.get("make") or ""):
        return False
    if rule.get("model") and normalize(rule["model"]) != normalize(vehicle.get("model") or ""):
        return False
    year = vehicle.get("year")
    if rule.get("year_from") and (year is None or year < rule["year_from"]):
        return False
    if rule.get("year_to") and (year is None or year > rule["year_to"]):
        return False
    for key in ("variant", "engine_code", "fuel_type"):
        if rule.get(key) and normalize(rule[key]) != normalize(vehicle.get(key) or ""):
            return False
    return True


def enrich_history_context(db, context: dict, *, include_internal_notes: bool) -> dict:
    """Bổ sung mã phiếu, trạng thái, chi tiết thực tế và đề xuất có nguồn cho context."""
    vehicle = context.get("vehicle") or {}
    for visit in context.get("history") or []:
        order_id = visit.get("repair_order_id")
        visit.update({"order_code": None, "order_status": None, "status_code": None,
                      "work_state": "Chưa đủ dữ liệu xác định", "proposed_items": []})
        if not order_id:
            continue
        order = db.execute(
            """SELECT code,status,status_code,inspection_notes,initial_condition,customer_request,
                      note,received_at,completed_at,delivered_at
               FROM repair_orders WHERE id=?""", (order_id,),
        ).fetchone()
        if not order:
            continue
        visit.update({"order_code": order["code"], "order_status": order["status"],
                      "status_code": order["status_code"], "work_state": _work_state(order["status_code"]),
                      "received_at": order["received_at"], "completed_at": order["completed_at"],
                      "delivered_at": order["delivered_at"]})
        if include_internal_notes:
            extra_notes = [order[key] for key in ("inspection_notes",) if (order[key] or "").strip()]
            for note in extra_notes:
                if note not in visit["technical_notes"]:
                    visit["technical_notes"].append(note)
        actual_names = {ai_service._normalize_vi(item.get("name") or "")
                        for item in [*(visit.get("services") or []), *(visit.get("parts") or [])]}
        if include_internal_notes:
            proposals = db.execute(
                """SELECT q.code quote_code,q.status quote_status,qi.kind,qi.name,qi.quantity
                   FROM quotes q JOIN quote_items qi ON qi.quote_id=q.id
                   WHERE q.repair_order_id=? ORDER BY q.version DESC,qi.id""", (order_id,),
            ).fetchall()
            seen = set()
            for item in proposals:
                key = (item["kind"], ai_service._normalize_vi(item["name"]))
                if key in seen or key[1] in actual_names:
                    continue
                seen.add(key)
                visit["proposed_items"].append(dict(item))
        for part in visit.get("parts") or []:
            part_id = part.get("part_id")
            if not part_id:
                part["fitment_status"] = "Chưa đủ dữ liệu xác định"
                continue
            rules = [dict(row) for row in db.execute(
                "SELECT make,model,year_from,year_to,variant,engine_code,fuel_type,note FROM part_fitments WHERE part_id=?",
                (part_id,),
            ).fetchall()]
            part["fitment_status"] = ("Chưa có quy tắc lắp vừa đã xác minh" if not rules else
                                      "Phù hợp quy tắc đã lưu" if any(_fitment_matches(rule, vehicle) for rule in rules)
                                      else "Không khớp quy tắc lắp vừa đã lưu")
    return context


def build_history_analysis(context: dict) -> dict:
    vehicle = context.get("vehicle") or {}
    all_history = context.get("history") or []
    history = [visit for visit in all_history if visit.get("status_code") != "CANCELLED"]
    history.sort(key=lambda visit: (_date(visit.get("repaired_at")) or datetime.min.replace(tzinfo=VN_TZ), visit["id"]),
                 reverse=True)
    now = datetime.now(VN_TZ)
    linked_orders = {visit["repair_order_id"] for visit in history if visit.get("repair_order_id")}
    unique_days = {_day(visit.get("repaired_at")) for visit in history}

    timeline = []
    missing_by_visit = []
    warnings = []
    for visit in history:
        code = _code(visit)
        missing = []
        if visit.get("mileage") is None:
            missing.append("số km")
        if not visit.get("technical_notes"):
            missing.append("ghi chú kỹ thuật")
        if not visit.get("status_code"):
            missing.append("trạng thái hoàn thành")
        # Schema chưa có cột kết quả sau sửa chữa tách biệt.
        missing.append("kết quả sau sửa chữa")
        for part in visit.get("parts") or []:
            if not part.get("code"):
                missing.append(f"mã phụ tùng: {part.get('name') or 'không rõ tên'}")
            if part.get("fitment_status") == "Không khớp quy tắc lắp vừa đã lưu":
                warnings.append({"order_code": code,
                                 "reason": f"Phụ tùng {part.get('name')} không khớp quy tắc lắp vừa đã lưu; cần đối chiếu mã phụ tùng và cấu hình xe.",
                                 "kind": "needs_verification"})
        missing = list(dict.fromkeys(missing))
        if missing:
            missing_by_visit.append({"order_code": code, "fields": missing})
        timeline.append({**visit, "order_code": code, "date": _day(visit.get("repaired_at")),
                         "work_state": visit.get("work_state") or _work_state(visit.get("status_code")),
                         "missing_fields": missing})

    ascending = list(reversed(history))
    intervals = []
    for previous, current in zip(ascending, ascending[1:]):
        before, after = _date(previous.get("repaired_at")), _date(current.get("repaired_at"))
        if before and after:
            intervals.append({"from_code": _code(previous), "to_code": _code(current),
                              "from_date": _day(previous.get("repaired_at")),
                              "to_date": _day(current.get("repaired_at")), "days": (after.date() - before.date()).days})
    latest_date = _date(history[0].get("repaired_at")) if history else None
    def months_ago(months: int) -> datetime:
        month_index = now.year * 12 + now.month - 1 - months
        year, month = divmod(month_index, 12)
        return now.replace(year=year, month=month + 1, day=min(now.day, monthrange(year, month + 1)[1]))
    counts = {}
    visit_day_counts = {}
    for months in (3, 6, 12):
        moments = [(visit, _date(visit.get("repaired_at"))) for visit in history]
        within = [(visit, moment) for visit, moment in moments if moment and moment >= months_ago(months)]
        counts[str(months)] = len(within)
        visit_day_counts[str(months)] = len({_day(visit.get("repaired_at")) for visit, _ in within})
    frequency_comment = ("Chưa đủ ít nhất 2 lần sửa chữa để nhận xét khoảng cách giữa các lần vào garage."
                         if len(history) < 2 else
                         f"Có {len(history)} bản ghi hợp lệ; khoảng cách quan sát được từ "
                         f"{min(item['days'] for item in intervals)} đến {max(item['days'] for item in intervals)} ngày."
                         if intervals else "Các bản ghi chưa đủ ngày hợp lệ để tính khoảng cách.")

    occurrences: dict[tuple[str, str], list[dict]] = defaultdict(list)
    work_status: dict[str, list[dict]] = defaultdict(list)
    for visit in history:
        code, state = _code(visit), visit.get("work_state") or "Chưa đủ dữ liệu xác định"
        seen_visit_items = set()
        for kind, items in (("Dịch vụ", visit.get("services") or []), ("Phụ tùng", visit.get("parts") or [])):
            for item in items:
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                item_key = (kind, ai_service._normalize_vi(name))
                if item_key in seen_visit_items:
                    continue
                seen_visit_items.add(item_key)
                entry = {"kind": kind, "name": name, "date": _day(visit.get("repaired_at")),
                         "order_code": code, "status": state}
                occurrences[item_key].append(entry)
                work_status[state].append(entry)
        for item in visit.get("proposed_items") or []:
            work_status["Đã đề xuất nhưng chưa xác nhận thực hiện"].append({
                "kind": item.get("kind"), "name": item.get("name"), "date": _day(visit.get("repaired_at")),
                "order_code": code, "status": f"Báo giá {item.get('quote_code')} · {item.get('quote_status')}",
            })
    repeated = [{"kind": entries[0]["kind"], "name": entries[0]["name"], "count": len(entries),
                 "occurrences": entries, "interpretation": "Xuất hiện trong nhiều phiếu; chưa đủ căn cứ phân biệt bảo dưỡng định kỳ với lỗi tái diễn."}
                for entries in occurrences.values() if len(entries) >= 2]
    repeated.sort(key=lambda item: (-item["count"], item["name"]))
    for item in repeated:
        codes = ", ".join(entry["order_code"] for entry in item["occurrences"])
        warnings.append({"order_code": codes,
                         "reason": f"Hạng mục {item['name']} xuất hiện {item['count']} lần; cần kỹ thuật viên xác định là bảo dưỡng định kỳ hay vấn đề tái diễn.",
                         "kind": "needs_verification"})

    mileage_changes = []
    mileage_visits = [visit for visit in ascending if visit.get("mileage") is not None]
    for previous, current in zip(mileage_visits, mileage_visits[1:]):
        before, after = _date(previous.get("repaired_at")), _date(current.get("repaired_at"))
        delta = int(current["mileage"]) - int(previous["mileage"])
        entry = {"from_code": _code(previous), "to_code": _code(current),
                 "from_mileage": int(previous["mileage"]), "to_mileage": int(current["mileage"]),
                 "delta": delta, "days": (after.date() - before.date()).days if before and after else None,
                 "abnormal": delta < 0}
        mileage_changes.append(entry)
        if delta < 0:
            warnings.append({"order_code": _code(current),
                             "reason": f"Số km giảm {abs(delta):,} km so với {_code(previous)}; giữ nguyên dữ liệu và cần xác minh đồng hồ hoặc nhập liệu.".replace(",", "."),
                             "kind": "mileage_anomaly"})

    maintenance_rules = (
        ("Dầu động cơ và lọc dầu", ("dau dong co", "loc dau", "thay dau")),
        ("Lọc gió động cơ", ("loc gio dong co",)),
        ("Lọc gió điều hòa", ("loc gio dieu hoa", "loc dieu hoa")),
        ("Hệ thống phanh", ("phanh",)),
        ("Bugi", ("bugi",)),
        ("Lốp và cân chỉnh bánh xe", ("lop", "can chinh", "can bang dong")),
        ("Hệ thống điều hòa", ("dieu hoa",)),
    )
    maintenance = []
    for label, keywords in maintenance_rules:
        found = []
        for visit in history:
            names = [item.get("name") or "" for item in [*(visit.get("services") or []), *(visit.get("parts") or [])]]
            if any(any(keyword in ai_service._normalize_vi(name) for keyword in keywords) for name in names):
                found.append(visit)
        if found:
            latest = found[0]
            maintenance.append({"name": label, "last_date": _day(latest.get("repaired_at")),
                                "last_mileage": latest.get("mileage"), "order_code": _code(latest),
                                "verified_cycle": None,
                                "note": "Chưa có chu kỳ nhà sản xuất đã xác minh gắn với hồ sơ; không tính hạn tiếp theo."})

    for entry in missing_by_visit:
        warnings.append({"order_code": entry["order_code"],
                         "reason": "Thiếu " + ", ".join(entry["fields"]), "kind": "missing_data"})
    sources = [{"type": "repair_history", "id": visit["id"], "label": f"{_code(visit)} · {_day(visit.get('repaired_at'))}",
                "date": _day(visit.get("repaired_at"))} for visit in history]
    issues = [{"order_code": _code(visit), "notes": visit.get("technical_notes") or []}
              for visit in history if visit.get("technical_notes")]
    return {
        "overview": {"record_count": len(history), "linked_order_count": len(linked_orders),
                     "unique_visit_days": len(unique_days), "latest_date": _day(history[0]["repaired_at"]) if history else None,
                     "latest_mileage": history[0].get("mileage") if history else None,
                     "order_codes": [_code(visit) for visit in history]},
        "frequency": {"intervals": intervals, "counts": counts,
                      "visit_day_counts": visit_day_counts,
                      "days_since_latest": (now.date() - latest_date.date()).days if latest_date else None,
                      "comment": frequency_comment},
        "timeline": timeline, "repeated_items": repeated,
        "work_status": dict(work_status), "mileage_changes": mileage_changes,
        "maintenance_tracking": maintenance, "issues": issues,
        "reception_notes": ["Đối chiếu số km hiện tại với lần ghi nhận gần nhất.",
                            "Hỏi khách về công việc thực hiện ngoài hệ thống sau lần ghi nhận gần nhất.",
                            "Không dùng lịch sử này như chẩn đoán cho tình trạng hiện tại."],
        "verification_warnings": warnings,
        "completeness": {"missing_by_visit": missing_by_visit,
                         "general_missing": (["Nguồn/chu kỳ bảo dưỡng nhà sản xuất đã xác minh"] if maintenance else [])},
        "sources": sources,
        "definition": "Một bản ghi hợp lệ là repair_history không liên kết phiếu đã hủy; số ngày vào garage là số ngày sửa chữa khác nhau.",
        "vehicle": vehicle,
    }


def render_history_summary(analysis: dict, missing: list[str]) -> str:
    overview = analysis["overview"]
    if not overview["record_count"]:
        return (
            "**1. Tổng quan lịch sử:** Chưa đủ dữ liệu lịch sử sửa chữa phù hợp cho xe này.\n\n"
            "**2. Tần suất sửa chữa:** Chưa có phiếu hợp lệ để tính.\n\n"
            "**3. Dòng thời gian sửa chữa:** Chưa có dữ liệu.\n\n"
            "**4. Hạng mục đã thực hiện:** Chưa có dữ liệu.\n\n"
            "**11. Những điểm cần kỹ thuật viên xác minh:** Đối chiếu thông tin xe và hỏi khách về các lần sửa bên ngoài hệ thống.\n\n"
            "**12. Dữ liệu còn thiếu và độ đầy đủ hồ sơ:** Lịch sử sửa chữa, dịch vụ, phụ tùng, số km, trạng thái và ghi chú kỹ thuật.\n\n"
            "**13. Nguồn đối chiếu:** Không có nguồn lịch sử phù hợp.\n\n"
            "Bản tóm tắt AI — cần kỹ thuật viên đối chiếu hồ sơ."
        )
    mileage = f"; số km gần nhất {overview['latest_mileage']:,} km".replace(",", ".") if overview["latest_mileage"] is not None else ""
    sections = [
        f"**1. Tổng quan lịch sử:** {overview['record_count']} bản ghi sửa chữa hợp lệ, "
        f"{overview['linked_order_count']} phiếu được liên kết, {overview['unique_visit_days']} ngày vào garage. "
        f"Lần gần nhất {overview['latest_date']}{mileage}. Mã phiếu: {', '.join(overview['order_codes'])}. "
        f"{analysis['definition']}",
    ]
    frequency = analysis["frequency"]
    interval_text = "; ".join(f"{item['from_code']} → {item['to_code']}: {item['days']} ngày" for item in frequency["intervals"])
    sections.append(f"**2. Tần suất sửa chữa:** 3 tháng: {frequency['counts']['3']} phiếu/bản ghi trên {frequency['visit_day_counts']['3']} ngày vào garage; "
                    f"6 tháng: {frequency['counts']['6']} phiếu/bản ghi trên {frequency['visit_day_counts']['6']} ngày; "
                    f"12 tháng: {frequency['counts']['12']} phiếu/bản ghi trên {frequency['visit_day_counts']['12']} ngày. "
                    f"Từ lần gần nhất đến nay: {frequency['days_since_latest']} ngày. "
                    f"Khoảng giữa các lần: {interval_text or 'chưa đủ dữ liệu'}. {frequency['comment']}")
    timeline_lines = []
    performed = []
    for visit in analysis["timeline"]:
        services = ", ".join(item["name"] for item in visit.get("services") or []) or "chưa có dịch vụ chi tiết"
        parts = ", ".join(f"{item['name']}{f' [{item.get('code')}]' if item.get('code') else ''}" for item in visit.get("parts") or []) or "không ghi nhận"
        notes = "; ".join(visit.get("technical_notes") or []) or "chưa có ghi chú/kết quả"
        km = f"{visit['mileage']:,} km".replace(",", ".") if visit.get("mileage") is not None else "chưa có số km"
        timeline_lines.append(f"- {visit['order_code']} · {visit['date']} · {km} · {visit['work_state']} · Dịch vụ: {services} · Phụ tùng: {parts} · Ghi chú: {notes}")
        performed.extend(f"{item['name']} ({visit['order_code']})" for item in [*(visit.get("services") or []), *(visit.get("parts") or [])])
    sections.append("**3. Dòng thời gian sửa chữa:**\n" + "\n".join(timeline_lines))
    sections.append("**4. Hạng mục đã thực hiện:** " + ("; ".join(performed) if performed else "Chưa có chi tiết hạng mục thực tế."))
    repeated = analysis["repeated_items"]
    repeated_text = "; ".join(f"{item['name']} ({item['count']} lần: " + ", ".join(
        f"{entry['order_code']} ngày {entry['date']} [{entry['status']}]" for entry in item["occurrences"]) + ")"
        for item in repeated) or "Không có hạng mục xuất hiện trong từ hai phiếu trở lên."
    sections.append("**5. Các hạng mục xuất hiện nhiều lần:** " + repeated_text +
                    " Việc lặp tên chưa chứng minh lỗi tái diễn; cần phân biệt với bảo dưỡng định kỳ.")
    states = []
    for state, entries in analysis["work_status"].items():
        states.append(f"{state}: " + ", ".join(f"{item['name']} ({item['order_code']})" for item in entries))
    sections.append("**6. Tình trạng xử lý công việc:** " + ("; ".join(states) if states else "Chưa đủ dữ liệu xác định."))
    mileage_lines = []
    for item in analysis["mileage_changes"]:
        delta = f"{item['delta']:,}".replace(",", ".")
        mileage_lines.append(f"{item['from_code']} {item['from_mileage']:,} km → {item['to_code']} {item['to_mileage']:,} km: "
                             f"chênh {delta} km trong {item['days'] if item['days'] is not None else 'không rõ'} ngày"
                             f"{' [CẦN XÁC MINH: số km giảm]' if item['abnormal'] else ''}".replace(",", "."))
    sections.append("**7. Biến động số km:** " + ("; ".join(mileage_lines) if mileage_lines else "Chưa đủ hai lần có số km để so sánh."))
    maintenance = analysis["maintenance_tracking"]
    maintenance_text = "; ".join(f"{item['name']}: gần nhất {item['order_code']} ngày {item['last_date']}, "
        f"{f'{item['last_mileage']:,} km'.replace(',', '.') if item['last_mileage'] is not None else 'chưa có số km'}. {item['note']}"
        for item in maintenance) or "Chưa có hạng mục bảo dưỡng thuộc nhóm theo dõi trong dữ liệu."
    sections.append("**8. Thông tin bảo dưỡng cần theo dõi:** " + maintenance_text)
    issue_text = "; ".join(f"{item['order_code']}: " + "; ".join(item["notes"]) for item in analysis["issues"])
    sections.append("**9. Vấn đề từng được ghi nhận:** " + (issue_text or "Không có ghi chú vấn đề trong dữ liệu được phép truy cập; không đồng nghĩa xe không có vấn đề."))
    sections.append("**10. Lưu ý khi tiếp nhận:** " + "; ".join(analysis["reception_notes"]))
    warning_text = "\n".join(f"- {item['order_code']}: {item['reason']} (nghi vấn cần kiểm tra, chưa phải bất thường đã xác nhận)"
                              for item in analysis["verification_warnings"])
    sections.append("**11. Những điểm cần kỹ thuật viên xác minh:**\n" + (warning_text or "Không phát hiện cảnh báo có căn cứ từ các trường hiện có."))
    missing_lines = [f"{item['order_code']}: " + ", ".join(item["fields"]) for item in analysis["completeness"]["missing_by_visit"]]
    missing_lines.extend(analysis["completeness"]["general_missing"])
    missing_lines.extend(field for field in missing if field not in missing_lines)
    sections.append("**12. Dữ liệu còn thiếu và độ đầy đủ hồ sơ:** " +
                    ("; ".join(dict.fromkeys(missing_lines)) if missing_lines else "Không phát hiện trường chính bị thiếu theo quy tắc hiện tại."))
    sections.append("**13. Nguồn đối chiếu:** " + ", ".join(source["label"] for source in analysis["sources"]))
    return "\n\n".join(sections) + "\n\nBản tóm tắt AI — cần kỹ thuật viên đối chiếu hồ sơ."
