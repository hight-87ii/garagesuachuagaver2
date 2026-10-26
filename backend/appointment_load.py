"""Phân tích tải lịch hẹn theo các cửa sổ 60 phút và thời lượng hẹn thực tế.

Không coi ngưỡng cảnh báo là công suất thực; không cập nhật lịch từ chat.
"""

import re
from collections import Counter
from datetime import datetime, timedelta

from .ai_service import AIResult, ai_service
from .appointment_query import DENIED
from .core.access import customer_scope_id
from .core import config
from .permissions import has_permission
from .schedule import find_conflicts, time_window, working_days, working_hours_issues, working_window
from .timeutil import VN_TZ, to_utc_iso, vn_datetime


def is_load_question(question: str) -> bool:
    text = ai_service._normalize_vi(question)
    if not any(term in text for term in ("lich", "hen", "dat xe", "dat them xe", "tiep nhan", "khung gio")):
        return False
    load_terms = ("trung gio", "chong lan", "dong nhat", "dong xe", "qua tai", "giam tai", "it lich",
                  "con cho", "con trong", "lich trong", "khung gio", "chuyen lich", "doi lich",
                  "lich thay the", "de xuat lich", "xe tro len", "neu khach dat", "neu chuyen")
    if not any(term in text for term in load_terms) and any(term in text for term in (
            "liet ke", "chua xac nhan", "da xac nhan", "da tiep nhan", "da huy")):
        return False  # existing detailed/status queries retain their original semantics
    return any(term in text for term in (
        "ngay mai", "sang mai", "mai co lich", "mai co bao nhieu", "trung gio",
        "chong lan", "dong nhat", "dong xe", "qua tai", "giam tai", "it lich",
        "con cho", "con trong", "lich trong", "khung gio", "chuyen lich", "doi lich",
        "lich thay the", "de xuat lich", "xe tro len", "neu khach dat", "neu chuyen",
    ))


def answer_appointment_load(db, question: str, user: dict):
    if not is_load_question(question):
        return None
    text = ai_service._normalize_vi(question)
    role = str(user.get("role") or "")
    has = lambda permission: has_permission(role, permission)
    recommend = any(term in text for term in ("chuyen", "doi lich", "thay the", "de xuat", "giam tai"))
    availability = any(term in text for term in ("con cho", "con trong", "lich trong", "neu khach dat", "dat them xe", "qua tai"))
    details = any(term in text for term in ("lich nao", "nhung lich", "khach nao", "xe nao", "lich hen nao", "lh-"))
    if (not has("appointment.view") or not has("appointment.view_statistics") or
            recommend and not has("appointment.recommend_reschedule") or
            availability and not has("appointment.check_availability") or
            details and not has("appointment.view_details") or
            role != "Khách hàng" and not has("appointment.view_all") or
            "khach nao" in text and not (has("customer.view") and has("customer_vehicle.view")) or
            "xe nao" in text and not (has("vehicle.view") and has("customer_vehicle.view"))):
        return AIResult(DENIED, "denied", "local", ai_service.model), []

    def response(message, sources=None, status="success"):
        return AIResult(message, status, "local", ai_service.model, status == "no_data"), sources or []

    if "chi nhanh" in text:
        return response("Lịch hẹn chưa có chi nhánh để lọc; không thể kiểm tra phạm vi này.", status="no_data")
    now = datetime.now(VN_TZ)
    today = now.date()
    if "ngay mai" in text or "sang mai" in text or "mai co" in text:
        day = today + timedelta(days=1)
    elif "hom nay" in text:
        day = today
    else:
        date_match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{4}))?\b", text)
        if date_match:
            try:
                day = datetime(int(date_match.group(3) or today.year), int(date_match.group(2)), int(date_match.group(1))).date()
            except ValueError:
                return response("Ngày không hợp lệ, vui lòng nhập ngày theo dạng dd/mm/yyyy.", status="clarification")
        else:
            return response("Vui lòng cho biết ngày cụ thể (hôm nay, ngày mai hoặc dd/mm/yyyy) để kiểm tra tải lịch.", status="clarification")
    if recommend and day < today:
        return response("Không thể đề xuất dời lịch về một ngày trong quá khứ.", status="no_data")
    scope = customer_scope_id(db, user) if role == "Khách hàng" else None
    start = to_utc_iso(datetime.combine(day, datetime.min.time(), VN_TZ))
    end = to_utc_iso(datetime.combine(day + timedelta(days=1), datetime.min.time(), VN_TZ))
    sql = """SELECT id,customer_id,vehicle_id,plate,customer_name,appointment_at,duration_min,status,
                    technician,technician_id,resource_id
             FROM appointments WHERE appointment_at>=? AND appointment_at<?"""
    args = [start, end]
    if role == "Khách hàng":
        sql += " AND (customer_id=? OR (customer_id IS NULL AND EXISTS(SELECT 1 FROM vehicles v WHERE v.id=appointments.vehicle_id AND v.customer_id=?)))"
        args += [scope, scope]
    rows = [dict(row) for row in db.execute(sql + " ORDER BY appointment_at,id", args)]
    counts = Counter(row["status"] for row in rows)
    # Received vehicles are shown in status totals, not counted as future reservations.
    pending = [row for row in rows if row["status"] in ("Đang chờ", "Đã xác nhận")]
    window = working_window()
    threshold = config.APPOINTMENT_OVERLOAD_THRESHOLD
    slot_minutes = config.APPOINTMENT_LOAD_SLOT_MINUTES
    slots = []
    current = window["start"]
    while current < window["end"]:
        last = min(current + slot_minutes, window["end"])
        slot_start = datetime.combine(day, datetime.min.time(), VN_TZ) + timedelta(minutes=current)
        slot_end = datetime.combine(day, datetime.min.time(), VN_TZ) + timedelta(minutes=last)
        matching = [row for row in pending if vn_datetime(row["appointment_at"]) < slot_end and
                    vn_datetime(row["appointment_at"]) + timedelta(minutes=row["duration_min"]) > slot_start]
        unique = {(row["vehicle_id"] if row["vehicle_id"] else row["plate"].strip().upper()) for row in matching}
        slots.append({"start": slot_start, "end": slot_end, "rows": matching, "cars": len(unique)})
        current = last
    sources = []
    active_cars = len({row["vehicle_id"] or row["plate"].strip().upper() for row in rows if row["status"] != "Đã hủy"})
    lines = [f"Ngày {day:%d/%m/%Y} (giờ Việt Nam): {len(rows)} lịch hẹn, {active_cars} xe riêng biệt có lịch chưa hủy; "
             f"{counts['Đang chờ']} đang chờ, {counts['Đã xác nhận']} đã xác nhận, "
             f"{counts['Đã tiếp nhận']} đã tiếp nhận, {counts['Đã hủy']} đã hủy.",
             f"Tải khung giờ tính {len(pending)} lịch chờ/xác nhận (không tính đã hủy/đã tiếp nhận), "
             f"đếm xe riêng biệt theo thời lượng hẹn, cửa sổ thống kê {slot_minutes} phút từ {window['start_text']}, "
             f"ngưỡng cảnh báo {threshold} xe. Ngày làm việc: {'có' if day.isoweekday() in working_days() else 'không'}." ]
    crowded = [slot for slot in slots if slot["cars"] >= threshold]
    if not rows:
        lines.append("Không có lịch hẹn ngày này; điều đó không xác nhận garage còn khả năng tiếp nhận.")
    if crowded and not any(term in text for term in ("khung gio", "dong", "trung gio", "chong lan", "con cho", "con trong", "lich trong", "qua tai", "it lich", "chuyen", "thay the", "de xuat", "bao nhieu xe")):
        lines.append("Khung đạt ngưỡng: " + ", ".join(f"{slot['start']:%H:%M}–{slot['end']:%H:%M} ({slot['cars']} xe)" for slot in crowded) + ".")
    if any(term in text for term in ("khung gio", "dong", "trung gio", "chong lan", "con cho", "con trong", "lich trong", "qua tai", "it lich", "chuyen", "thay the", "de xuat", "bao nhieu xe")):
        shown = [slot for slot in slots if slot["cars"] > 0]
        if "dong nhat" in text and shown:
            highest = max(slot["cars"] for slot in shown)
            shown = [slot for slot in shown if slot["cars"] == highest]
        for slot in shown:
            lines.append(f"- {slot['start']:%H:%M}–{slot['end']:%H:%M}: {slot['cars']} xe theo lịch "
                         + ("(đạt ngưỡng cảnh báo)." if slot in crowded else "(dưới ngưỡng)."))
        if crowded:
            lines.append("Cảnh báo về mật độ lịch, chưa kết luận chắc chắn quá tải theo công suất garage.")
    # Prefer an explicitly requested clock time, not the threshold number or date.
    clock = re.search(r"(?:luc|vao|khung|sang)\s*(\d{1,2})(?:[:h](\d{2}))?\s*(?:gio|h)?\s*(sang|chieu)?", text)
    if clock:
        hour = int(clock.group(1))
        minute = int(clock.group(2) or 0)
        if clock.group(3) == "chieu" and hour < 12:
            hour += 12
        if hour > 23 or minute > 59:
            return response("Giờ cần kiểm tra không hợp lệ.", status="clarification")
        requested = datetime.combine(day, datetime.min.time(), VN_TZ).replace(hour=hour, minute=minute)
        duration = 60  # Without a selected service/appointment the duration is unknown.
        requested_slot = next((slot for slot in slots if slot["start"] <= requested < slot["end"]), None)
        if availability:
            if not has("appointment.check_availability"):
                return response(DENIED, status="denied")
            after = (requested_slot["cars"] if requested_slot else 0) + (1 if "neu" in text or "dat them" in text else 0)
            issues = working_hours_issues(to_utc_iso(requested), duration)
            lines.append(f"Kiểm tra giả định {requested:%H:%M}–{(requested + timedelta(minutes=duration)):%H:%M}: "
                         f"{after} xe trong khung thống kê sau khi thêm xe (nếu có); "
                         + ("ngoài giờ/ngày làm việc." if issues else
                            "đạt ngưỡng cảnh báo." if after >= threshold else "dưới ngưỡng cảnh báo."))
            lines.append("Chưa xác nhận còn chỗ: cần thời lượng dịch vụ, kỹ thuật viên và khoang cụ thể để kiểm tra năng lực.")
    if details:
        if "khach nao" in text and not (has("customer.view") and has("customer_vehicle.view")):
            return response(DENIED, status="denied")
        listed = [row for row in pending if not clock or requested_slot and row in requested_slot["rows"]]
        if "trung gio" in text or "chong lan" in text:
            overlap_ids = set()
            for index, left in enumerate(listed):
                for right in listed[index + 1:]:
                    if (vn_datetime(left["appointment_at"]) < vn_datetime(right["appointment_at"]) + timedelta(minutes=right["duration_min"])
                            and vn_datetime(right["appointment_at"]) < vn_datetime(left["appointment_at"]) + timedelta(minutes=left["duration_min"])):
                        overlap_ids.update((left["id"], right["id"]))
            listed = [row for row in listed if row["id"] in overlap_ids]
            if not listed:
                lines.append("Không tìm thấy cặp lịch chờ/xác nhận có khoảng thời gian chồng lấn trong ngày.")
        for row in listed[:20]:
            label = f"LH-{row['id']:05d} {vn_datetime(row['appointment_at']):%H:%M}, {row['status']}"
            if has("customer.view") and has("customer_vehicle.view"):
                label += f", {row['customer_name']}"
            if has("vehicle.view") and has("customer_vehicle.view"):
                label += f", {row['plate']}"
            lines.append("- " + label)
            sources.append({"type": "appointment", "id": row["id"], "label": f"LH-{row['id']:05d}"})
        if len(listed) > 20:
            lines.append(f"Chỉ hiển thị 20/{len(listed)} lịch.")
    if recommend:
        target = re.search(r"\blh[- ]?(\d{1,8})\b", text)
        selected = next((row for row in pending if target and row["id"] == int(target.group(1))), None)
        if target and not selected:
            return response("Không tìm thấy lịch chờ/xác nhận này trong ngày được hỏi hoặc lịch không thuộc phạm vi truy cập.", status="no_data")
        if not selected:
            choices = [row for slot in crowded for row in slot["rows"] if row["status"] == "Đang chờ"]
            selected = next(iter(choices), None)
        if not selected:
            lines.append("Không có lịch đang chờ nào thuộc khung cảnh báo để đề xuất chuyển; lịch đã xác nhận cần trao đổi với khách trước.")
        else:
            duration = selected["duration_min"]
            if target and clock:
                finish = requested + timedelta(minutes=duration)
                affected = [slot for slot in slots if slot["start"] < finish and slot["end"] > requested]
                overlapping = [row for row in pending if row["id"] != selected["id"] and
                               vn_datetime(row["appointment_at"]) < finish and
                               vn_datetime(row["appointment_at"]) + timedelta(minutes=row["duration_min"]) > requested]
                conflicts = find_conflicts(db, start=to_utc_iso(requested), end=time_window(to_utc_iso(requested), duration),
                                           technician=selected["technician"], technician_id=selected["technician_id"],
                                           resource_id=selected["resource_id"], exclude_id=selected["id"])
                blocked = (bool(working_hours_issues(to_utc_iso(requested), duration)) or requested <= now or
                           any(c["level"] == "blocking" for c in conflicts) or
                           any(row["vehicle_id"] and row["vehicle_id"] == selected["vehicle_id"] or
                               row["customer_id"] and row["customer_id"] == selected["customer_id"] for row in overlapping))
                old_slots = [slot for slot in slots if selected in slot["rows"]]
                new_count = max((len({row["vehicle_id"] or row["plate"] for row in slot["rows"] if row["id"] != selected["id"]}) + 1
                                 for slot in affected), default=0)
                lines.append(f"Mô phỏng chuyển LH-{selected['id']:05d} sang {requested:%H:%M}: "
                             f"{len(old_slots)} khung cũ giảm tối đa 1 xe/khung; "
                             f"khung mới tối đa {new_count} xe theo lịch sau chuyển. "
                             + ("Không hợp lệ do xung đột, giờ đóng cửa hoặc thời điểm đã qua." if blocked else
                                "Đạt ngưỡng cảnh báo, không đề nghị xác nhận." if new_count >= threshold else
                                "Dưới ngưỡng; chỉ là giả định, chưa thay đổi dữ liệu."))
            candidates = []
            if day.isoweekday() in working_days():
                for minute in range(window["start"], window["end"] - duration + 1, 30):
                    candidate = datetime.combine(day, datetime.min.time(), VN_TZ) + timedelta(minutes=minute)
                    if candidate <= now or candidate == vn_datetime(selected["appointment_at"]):
                        continue
                    finish = candidate + timedelta(minutes=duration)
                    overlaps = [row for row in pending if row["id"] != selected["id"] and
                                vn_datetime(row["appointment_at"]) < finish and
                                vn_datetime(row["appointment_at"]) + timedelta(minutes=row["duration_min"]) > candidate]
                    if any((selected["vehicle_id"] and row["vehicle_id"] == selected["vehicle_id"] or
                            selected["customer_id"] and row["customer_id"] == selected["customer_id"]) for row in overlaps):
                        continue
                    if working_hours_issues(to_utc_iso(candidate), duration):
                        continue
                    conflicts = find_conflicts(db, start=to_utc_iso(candidate), end=time_window(to_utc_iso(candidate), duration),
                                               technician=selected["technician"], technician_id=selected["technician_id"],
                                               resource_id=selected["resource_id"], exclude_id=selected["id"])
                    if any(conflict["level"] == "blocking" for conflict in conflicts):
                        continue
                    affected = [slot for slot in slots if slot["start"] < finish and slot["end"] > candidate]
                    if not affected or any(len({(row["vehicle_id"] or row["plate"].strip().upper()) for row in slot["rows"] if row["id"] != selected["id"]}) + 1 >= threshold for slot in affected):
                        continue
                    candidates.append((max(len(overlaps), *(slot["cars"] for slot in affected)), candidate, finish))
            candidates.sort(key=lambda item: (item[0], abs((item[1] - vn_datetime(selected["appointment_at"])).total_seconds())))
            if candidates:
                lines.append(f"Đề xuất tham khảo cho LH-{selected['id']:05d} ({duration} phút; {selected['status']}):")
                for _, begin, finish in candidates[:3]:
                    lines.append(f"- {begin:%H:%M}–{finish:%H:%M} ngày {day:%d/%m}: dưới ngưỡng; không trùng phân công/xe/khách đã ghi nhận.")
                lines.append("Giả định, chưa sửa lịch. Cần xác nhận với khách và kiểm tra lại ngay trước khi lưu; "
                             "chưa có công suất tiếp nhận tổng thể hoặc lịch rảnh của nhân viên chưa được phân công.")
                if has("appointment.view_details"):
                    sources.append({"type": "appointment", "id": selected["id"], "label": f"LH-{selected['id']:05d}"})
            else:
                lines.append("Không tìm được giờ thay thế hợp lệ dưới ngưỡng trong ngày làm việc này; không tự tạo giờ trống.")
    lines.append(f"Truy vấn lúc {now:%d/%m/%Y %H:%M} (giờ Việt Nam). Không thay đổi lịch hẹn.")
    return response("\n".join(lines), sources)
