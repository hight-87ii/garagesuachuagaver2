# -*- coding: utf-8 -*-
"""Module tra cứu lịch sử sửa chữa và phụ tùng đã thay thế chuẩn xác từ Database."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from .ai_service import AIResult, ai_service
from .core.access import customer_scope_id, ensure_record_access
from .core.db import normalize_plate
from .smart_maintenance_recommendation import (
    evaluate_maintenance_recommendations,
    format_recommendations_text,
)


def is_repair_history_question(question: str) -> bool:
    """Nhận diện câu hỏi về lịch sử sửa chữa hoặc phụ tùng/linh kiện đã từng thay."""
    text = ai_service._normalize_vi(question)

    # Loại trừ ngay các câu hỏi về đổi lịch hẹn hoặc hủy lịch hẹn (tránh nhầm "đặt lịch sửa xe" thành "lịch sử")
    if any(term in text for term in (
        "doi lich", "doi sang ngay", "doi ngay", "doi gio", "doi lich hen",
        "huy lich", "chuyen sang ngay", "chuyen lich", "muon doi sang", "ho tro doi"
    )):
        return False

    # 1. Các từ khóa lịch sử sửa chữa rõ ràng (dùng regex boundary để tránh nhầm "lich sua" thành "lich su")
    has_history = any(re.search(pattern, text) for pattern in (
        r"\blich su\b", r"\bda tung\b", r"\btung sua\b", r"\bda sua\b", r"\bcac lan sua\b", r"\blan sua\b",
        r"\btruoc day\b", r"\blan truoc\b", r"\bsua chua truoc\b", r"\bnhung lan truoc\b", r"\btung vao xuong\b",
        r"\blan gan nhat\b", r"\blan sua gan nhat\b", r"\blan bao duong gan nhat\b", r"\bbao duong gan nhat\b",
        r"\bthay lan gan nhat\b", r"\bda thay chua\b", r"\btung thay chua\b", r"\bda thay nhung\b",
        r"\bchua tung sua\b", r"\bchua sua chua\b", r"\bchua tung vao xuong\b"
    ))

    # 2. Câu hỏi phụ tùng nằm trong báo giá nhưng chưa thay
    has_quote_unreplaced = (
        any(term in text for term in ("bao gia", "trong bao gia", "chua duoc thay", "chua thay"))
        and any(term in text for term in ("phu tung", "linh kien", "vat tu", "nam trong", "de xuat", "hang muc"))
    )

    # 3. Tra cứu bộ phận cụ thể đã thay chưa / thay khi nào
    has_specific_part = any(term in text for term in (
        "thay dau", "thay nhot", "thay ma phanh", "thay loc", "thay bugi", "thay lop", "thay ac quy"
    )) and any(term in text for term in (
        "lan gan nhat", "khi nao", "chua", "ngay nao", "bao gio", "luc nao", "o moc"
    ))

    # 4. Xe này đã sửa những gì / đã làm gì
    has_repair_summary = any(term in text for term in (
        "da sua nhung gi", "sua nhung gi", "da sua gi", "tung sua gi", "da lam nhung gi"
    ))

    # 5. Phụ tùng đã thay kèm ngữ cảnh xe
    has_parts = any(term in text for term in (
        "phu tung", "linh kien", "vat tu", "thay gi", "thay nhung gi",
        "thay the nhung gi", "tung thay", "da thay"
    ))
    has_vehicle_ref = any(term in text for term in (
        "xe toi", "xe cua toi", "xe minh", "xe nay", "xe cua minh", "chiec xe"
    ))

    return bool(
        has_history or
        has_quote_unreplaced or
        has_specific_part or
        has_repair_summary or
        (has_parts and (has_vehicle_ref or any(w in text for w in ("da thay", "tung thay", "truoc day"))))
    )


def query_vehicle_repair_history(db: sqlite3.Connection, vehicle_id: int) -> dict[str, Any]:
    """Truy vấn các phiếu sửa chữa đã hoàn thành, dịch vụ thực hiện, phụ tùng đã thay và phụ tùng trong báo giá."""
    ro_rows = db.execute(
        """SELECT id, code, status, status_code, km_in, customer_request, note,
                  COALESCE(completed_at, delivered_at, received_at, created_at) as action_date
           FROM repair_orders
           WHERE vehicle_id = ?
           ORDER BY action_date DESC, id DESC""",
        (vehicle_id,),
    ).fetchall()

    completed_statuses = {
        'hoan thanh', 'da ban giao', 'da dong', 'da giao xe',
        'completed', 'delivered', 'closed', 'paid'
    }

    completed_ros = []
    other_ros = []
    for ro in ro_rows:
        ro_dict = dict(ro)
        status_norm = ai_service._normalize_vi(ro_dict.get("status") or "")
        code_norm = (ro_dict.get("status_code") or "").lower()
        if status_norm in completed_statuses or code_norm in completed_statuses:
            completed_ros.append(ro_dict)
        else:
            other_ros.append(ro_dict)

    completed_ro_ids = [r["id"] for r in completed_ros]
    pending_ro_ids = [r["id"] for r in other_ros]

    parts_replaced = []
    services_performed = []
    seen_part_keys = set()
    seen_service_keys = set()

    if completed_ro_ids:
        # Từ repair_order_items (kind = 'Phụ tùng')
        items = db.execute(
            f"""SELECT roi.id, roi.name, roi.quantity, roi.unit_price,
                       ro.id as ro_id, ro.code as ro_code, ro.km_in,
                       COALESCE(ro.completed_at, ro.delivered_at, ro.received_at, roi.created_at) as action_date
                FROM repair_order_items roi
                JOIN repair_orders ro ON ro.id = roi.repair_order_id
                WHERE ro.id IN ({','.join('?' * len(completed_ro_ids))}) AND roi.kind = 'Phụ tùng'
                ORDER BY action_date DESC, roi.id DESC""",
            completed_ro_ids,
        ).fetchall()

        for it in items:
            date_str = (it["action_date"] or "")[:10]
            key = (it["name"].strip().lower(), date_str)
            if key not in seen_part_keys:
                seen_part_keys.add(key)
                parts_replaced.append({
                    "name": it["name"].strip(),
                    "quantity": it["quantity"] or 1,
                    "date": date_str,
                    "km": it["km_in"],
                    "ro_code": it["ro_code"],
                    "ro_id": it["ro_id"],
                    "source": "repair_order_item",
                })

        # Từ repair_order_parts
        rop_items = db.execute(
            f"""SELECT rop.id, rop.name, rop.quantity, rop.unit_price,
                       ro.id as ro_id, ro.code as ro_code, ro.km_in,
                       COALESCE(ro.completed_at, ro.delivered_at, ro.received_at, rop.created_at) as action_date
                FROM repair_order_parts rop
                JOIN repair_orders ro ON ro.id = rop.repair_order_id
                WHERE ro.id IN ({','.join('?' * len(completed_ro_ids))})
                ORDER BY action_date DESC, rop.id DESC""",
            completed_ro_ids,
        ).fetchall()

        for rop in rop_items:
            date_str = (rop["action_date"] or "")[:10]
            key = (rop["name"].strip().lower(), date_str)
            if key not in seen_part_keys:
                seen_part_keys.add(key)
                parts_replaced.append({
                    "name": rop["name"].strip(),
                    "quantity": rop["quantity"] or 1,
                    "date": date_str,
                    "km": rop["km_in"],
                    "ro_code": rop["ro_code"],
                    "ro_id": rop["ro_id"],
                    "source": "repair_order_part",
                })

        # Từ repair_order_items (kind = 'Dịch vụ') của các phiếu hoàn thành
        srv_items = db.execute(
            f"""SELECT roi.id, roi.name, roi.quantity, roi.unit_price,
                       ro.id as ro_id, ro.code as ro_code, ro.km_in,
                       COALESCE(ro.completed_at, ro.delivered_at, ro.received_at, roi.created_at) as action_date
                FROM repair_order_items roi
                JOIN repair_orders ro ON ro.id = roi.repair_order_id
                WHERE ro.id IN ({','.join('?' * len(completed_ro_ids))}) AND roi.kind = 'Dịch vụ'
                ORDER BY action_date DESC, roi.id DESC""",
            completed_ro_ids,
        ).fetchall()

        for it in srv_items:
            date_str = (it["action_date"] or "")[:10]
            key = (it["name"].strip().lower(), date_str)
            if key not in seen_service_keys:
                seen_service_keys.add(key)
                services_performed.append({
                    "name": it["name"].strip(),
                    "quantity": it["quantity"] or 1,
                    "date": date_str,
                    "km": it["km_in"],
                    "ro_code": it["ro_code"],
                    "ro_id": it["ro_id"],
                })

    # Từ repair_history
    history_rows = db.execute(
        """SELECT id, repaired_at, mileage, services, note
           FROM repair_history
           WHERE vehicle_id = ?
           ORDER BY repaired_at DESC, id DESC""",
        (vehicle_id,),
    ).fetchall()

    for h in history_rows:
        date_str = (h["repaired_at"] or "")[:10]
        services_text = h["services"] or ""
        for segment in services_text.split(","):
            s_clean = segment.strip()
            s_norm = ai_service._normalize_vi(s_clean)
            if any(term in s_norm for term in ("loc dau", "loc gio", "ma phanh", "dau dong co", "dau nhot", "bugi", "gat mua", "ac quy", "lop", "day curoa")):
                p_name = re.sub(r"^(?:thay|kiem tra va thay)\s+", "", s_clean, flags=re.I).strip()
                p_name = p_name[0].upper() + p_name[1:] if p_name else s_clean
                key = (p_name.lower(), date_str)
                if key not in seen_part_keys:
                    seen_part_keys.add(key)
                    parts_replaced.append({
                        "name": p_name,
                        "quantity": 1,
                        "date": date_str,
                        "km": h["mileage"],
                        "ro_code": None,
                        "ro_id": None,
                        "source": "repair_history",
                    })
            elif s_clean:
                key = (s_clean.lower(), date_str)
                if key not in seen_service_keys:
                    seen_service_keys.add(key)
                    services_performed.append({
                        "name": s_clean,
                        "quantity": 1,
                        "date": date_str,
                        "km": h["mileage"],
                        "ro_code": None,
                        "ro_id": None,
                    })

    parts_replaced.sort(key=lambda x: x.get("date") or "", reverse=True)
    services_performed.sort(key=lambda x: x.get("date") or "", reverse=True)

    # Phụ tùng trong báo giá hoặc phiếu chưa hoàn thành (chưa thay)
    quoted_not_replaced = []
    seen_quoted_keys = set()
    if pending_ro_ids:
        # Từ quote_items
        q_items = db.execute(
            f"""SELECT qi.id, qi.name, qi.quantity, qi.unit_price,
                       q.id as quote_id, q.code as quote_code, q.status as quote_status,
                       ro.id as ro_id, ro.code as ro_code, ro.status as ro_status, ro.km_in,
                       COALESCE(q.created_at, ro.created_at) as action_date
                FROM quote_items qi
                JOIN quotes q ON q.id = qi.quote_id
                JOIN repair_orders ro ON ro.id = q.repair_order_id
                WHERE ro.id IN ({','.join('?' * len(pending_ro_ids))}) AND qi.kind = 'Phụ tùng'
                ORDER BY action_date DESC, qi.id DESC""",
            pending_ro_ids,
        ).fetchall()
        for qi in q_items:
            date_str = (qi["action_date"] or "")[:10]
            key = (qi["name"].strip().lower(), qi["ro_code"])
            if key not in seen_quoted_keys:
                seen_quoted_keys.add(key)
                quoted_not_replaced.append({
                    "name": qi["name"].strip(),
                    "quantity": qi["quantity"] or 1,
                    "unit_price": qi["unit_price"] or 0,
                    "quote_code": qi["quote_code"],
                    "quote_id": qi["quote_id"],
                    "ro_code": qi["ro_code"],
                    "ro_id": qi["ro_id"],
                    "ro_status": qi["ro_status"] or "Chưa hoàn thành",
                    "date": date_str,
                })

        # Từ repair_order_items (kind = 'Phụ tùng')
        pending_items = db.execute(
            f"""SELECT roi.id, roi.name, roi.quantity, roi.unit_price,
                       ro.id as ro_id, ro.code as ro_code, ro.status as ro_status, ro.km_in,
                       roi.created_at as action_date
                FROM repair_order_items roi
                JOIN repair_orders ro ON ro.id = roi.repair_order_id
                WHERE ro.id IN ({','.join('?' * len(pending_ro_ids))}) AND roi.kind = 'Phụ tùng'
                ORDER BY action_date DESC, roi.id DESC""",
            pending_ro_ids,
        ).fetchall()
        for pi in pending_items:
            date_str = (pi["action_date"] or "")[:10]
            key = (pi["name"].strip().lower(), pi["ro_code"])
            if key not in seen_quoted_keys:
                seen_quoted_keys.add(key)
                quoted_not_replaced.append({
                    "name": pi["name"].strip(),
                    "quantity": pi["quantity"] or 1,
                    "unit_price": pi["unit_price"] or 0,
                    "quote_code": None,
                    "quote_id": None,
                    "ro_code": pi["ro_code"],
                    "ro_id": pi["ro_id"],
                    "ro_status": pi["ro_status"] or "Đang xử lý",
                    "date": date_str,
                })

    return {
        "total_repair_orders": len(ro_rows),
        "completed_repair_orders": completed_ros,
        "pending_repair_orders": other_ros,
        "parts_replaced": parts_replaced,
        "services_performed": services_performed,
        "quoted_not_replaced": quoted_not_replaced,
        "history_entries": [dict(h) for h in history_rows],
    }


def answer_vehicle_repair_history(
    db: sqlite3.Connection,
    question: str,
    user: dict,
    vehicle_id: int | None = None,
    plate: str | None = None,
) -> tuple[AIResult, list[dict]] | None:
    """Xử lý tra cứu lịch sử sửa chữa và phụ tùng đã thay thế với đầy đủ phân quyền và nhận diện xe."""
    if not is_repair_history_question(question):
        return None

    try:
        target_vehicle = None
        if vehicle_id or plate:
            row = db.execute(
                "SELECT * FROM vehicles WHERE id=?" if vehicle_id else
                "SELECT * FROM vehicles WHERE plate_normalized=? ORDER BY id LIMIT 1",
                (vehicle_id if vehicle_id else normalize_plate(plate or ""),),
            ).fetchone()
            if not row:
                return AIResult("Không tìm thấy thông tin phương tiện yêu cầu trong hệ thống.",
                                "clarification", "local", ai_service.model, True, ["Xe của bạn"]), []
            target_vehicle = dict(row)
            try:
                ensure_record_access(db, user, target_vehicle["customer_id"])
            except Exception:
                return AIResult("Bạn không có quyền truy cập hồ sơ lịch sử sửa chữa của phương tiện này.",
                                "denied", "local", ai_service.model, True, ["Quyền sở hữu xe"]), []
        elif user.get("role") == "Khách hàng":
            customer_id = customer_scope_id(db, user)
            owned_vehicles = [dict(v) for v in db.execute(
                """SELECT * FROM vehicles WHERE customer_id=? AND status='active' ORDER BY id""",
                (customer_id,),
            ).fetchall()] if customer_id not in (None, -1) else []

            if len(owned_vehicles) > 1:
                labels = [f"{v['plate']} ({v['make']} {v['model']})" for v in owned_vehicles]
                return AIResult(
                    f"Hồ sơ của bạn đang có {len(owned_vehicles)} xe: {', '.join(labels)}. "
                    "Vui lòng chọn xe trong hồ sơ của bạn hoặc cung cấp biển số xe để garage tra cứu lịch sử sửa chữa và các phụ tùng đã từng thay thế.",
                    "clarification", "local", ai_service.model, True, ["Chọn xe của bạn"]
                ), []
            elif len(owned_vehicles) == 1:
                target_vehicle = owned_vehicles[0]
            else:
                return AIResult(
                    "Vui lòng chọn xe trong hồ sơ của bạn hoặc cung cấp biển số xe để garage tra cứu lịch sử sửa chữa và các phụ tùng đã từng thay thế.",
                    "clarification", "local", ai_service.model, True, ["Xe của bạn"]
                ), []
        else:
            return AIResult(
                "Vui lòng chọn xe trong hồ sơ của bạn hoặc cung cấp biển số xe để garage tra cứu lịch sử sửa chữa và các phụ tùng đã từng thay thế.",
                "clarification", "local", ai_service.model, True, ["Biển số xe"]
            ), []

        data = query_vehicle_repair_history(db, target_vehicle["id"])
        parts = data["parts_replaced"]
        total_ros = data["total_repair_orders"]
        history_entries = data["history_entries"]
        completed_ros = data.get("completed_repair_orders", [])

        v_label = f"{target_vehicle.get('make', '')} {target_vehicle.get('model', '')} (biển số {target_vehicle.get('plate', '')})".strip()
        sources = []
        q_norm = ai_service._normalize_vi(question)

        # Phân loại trọng tâm câu hỏi
        is_quote_query = (
            any(k in q_norm for k in ("bao gia", "trong bao gia", "chua duoc thay", "chua thay")) and
            any(k in q_norm for k in ("phu tung", "linh kien", "vat tu", "nam trong", "de xuat", "hang muc"))
        )
        is_oil = any(k in q_norm for k in ("dau dong co", "dau nhot", "nhot", "dau may", "thay dau"))
        is_latest_oil_query = is_oil and any(k in q_norm for k in ("lan gan nhat", "khi nao", "ngay nao", "bao gio", "luc nao", "chua", "o moc"))
        is_brake = any(k in q_norm for k in ("ma phanh", "bo phanh", "phanh"))
        is_brake_query = is_brake and any(k in q_norm for k in ("chua", "thay chua", "da thay", "khi nao", "ngay nao", "bao gio", "o moc"))
        is_latest_visit_parts_query = (
            any(k in q_norm for k in ("lan bao duong gan nhat", "lan vao xuong gan nhat", "lan sua gan nhat", "lan gan nhat")) and
            any(k in q_norm for k in ("phu tung", "linh kien", "vat tu", "thay nhung gi", "thay gi", "da thay"))
        )
        is_general_repair_query = any(k in q_norm for k in (
            "da sua nhung gi", "sua nhung gi", "da sua gi", "tung sua gi", "da lam nhung gi"
        ))
        is_no_history_hypothetical = (
            any(k in q_norm for k in ("chua tung sua", "chua sua chua", "chua tung vao xuong")) and
            any(k in q_norm for k in ("thi sao", "the nao", "ra sao", "neu"))
        )

        # 1. Xe chưa từng có phiếu sửa chữa nào hoặc hỏi giả định chưa sửa
        if (total_ros == 0 and len(history_entries) == 0) or is_no_history_hypothetical:
            return AIResult(
                f"Hệ thống ThreeH Workshop chưa ghi nhận phiếu sửa chữa hoặc lịch sử dịch vụ nào cho xe {v_label}. "
                "Nếu xe chưa từng sửa chữa hoặc bảo dưỡng tại xưởng, bạn có thể đặt lịch hẹn kiểm tra tổng quát hoặc bảo dưỡng định kỳ để tạo hồ sơ theo dõi cho xe nhé.",
                "fallback", "local", ai_service.model, False
            ), [{"type": "vehicle", "id": target_vehicle["id"], "label": f"Hồ sơ xe: {v_label}"}]

        # 2. Câu hỏi phụ tùng chỉ nằm trong báo giá nhưng chưa được thay
        if is_quote_query:
            quoted_items = data.get("quoted_not_replaced", [])
            if quoted_items:
                lines = []
                for idx, item in enumerate(quoted_items, start=1):
                    price_str = f", đơn giá {item['unit_price']:,} ₫".replace(",", ".") if item.get("unit_price") else ""
                    quote_info = f"Báo giá {item['quote_code']}" if item.get("quote_code") else ""
                    ro_info = f"Phiếu sửa chữa {item['ro_code']}" if item.get("ro_code") else ""
                    doc_info = " / ".join(p for p in (quote_info, ro_info) if p)
                    lines.append(
                        f"{idx}. {item['name']} (Số lượng: {item['quantity']}{price_str})"
                        + (f" – thuộc {doc_info}" if doc_info else "")
                        + f" (Trạng thái: {item['ro_status']})."
                    )
                    if item.get("ro_id"):
                        sources.append({
                            "type": "repair_order",
                            "id": item["ro_id"],
                            "label": f"Phiếu sửa chữa {item.get('ro_code') or item['ro_id']}: {item['name']} (chưa nghiệm thu)"
                        })
                    elif item.get("quote_id"):
                        sources.append({
                            "type": "quote",
                            "id": item["quote_id"],
                            "label": f"Báo giá {item.get('quote_code') or item['quote_id']}: {item['name']}"
                        })

                fallback_content = (
                    f"Theo hồ sơ trên hệ thống ThreeH Workshop, xe {v_label} có các hạng mục phụ tùng sau nằm trong báo giá hoặc phiếu đang xử lý nhưng chưa được nghiệm thu thay thế thực tế:\n\n"
                    + "\n".join(lines) + "\n\n"
                    "Lưu ý: Các hạng mục trên mới chỉ nằm trong dự toán báo giá hoặc đang trong quá trình thực hiện, chưa được hoàn thành nghiệm thu và bàn giao xe nên chưa được tính vào lịch sử phụ tùng đã thay thế."
                )
            else:
                fallback_content = (
                    f"Hệ thống không ghi nhận phụ tùng nào chỉ nằm trong báo giá mà chưa thay cho xe {v_label}. "
                    "Mọi phụ tùng được lập trong các báo giá trước đây đều đã được hoàn tất nghiệm thu hoặc không có báo giá nào đang chờ xử lý dở dang."
                )
                sources.append({"type": "vehicle", "id": target_vehicle["id"], "label": f"Hồ sơ xe: {v_label}"})

            narrated = ai_service.narrate_repair_history(question, target_vehicle, quoted_items, user.get("role", "Khách hàng"), fallback_content)
            return narrated, sources

        # 3. Câu hỏi về thay dầu động cơ lần gần nhất khi nào
        if is_latest_oil_query:
            oil_item = None
            for p in parts:
                p_norm = ai_service._normalize_vi(p["name"])
                if any(k in p_norm for k in ("dau dong co", "dau nhot", "nhot", "5w-", "10w-", "dau may")):
                    oil_item = p
                    break
            if not oil_item:
                for h in history_entries:
                    s_norm = ai_service._normalize_vi(h.get("services") or "")
                    if any(k in s_norm for k in ("dau dong co", "dau nhot", "nhot", "5w-", "10w-", "thay dau")):
                        oil_item = {
                            "name": "Dầu động cơ",
                            "date": str(h.get("repaired_at") or "")[:10],
                            "km": h.get("mileage"),
                            "ro_code": None,
                            "ro_id": None
                        }
                        break

            if oil_item:
                date_str = f"ngày {oil_item['date']}" if oil_item.get("date") else "thời gian trước"
                km_str = f" tại mốc {oil_item['km']:,} km".replace(",", ".") if oil_item.get("km") else ""
                ro_str = f" (Phiếu sửa chữa {oil_item['ro_code']})" if oil_item.get("ro_code") else ""
                cur_km = target_vehicle.get("mileage")
                mileage_diff_str = ""
                if cur_km and oil_item.get("km"):
                    diff = cur_km - oil_item["km"]
                    if diff >= 0:
                        mileage_diff_str = f" Hiện tại số km ghi nhận của xe là {cur_km:,} km, tức xe đã vận hành thêm khoảng {diff:,} km kể từ lần thay dầu đó.".replace(",", ".")

                fallback_content = (
                    f"Theo lịch sử sửa chữa đã xác minh từ hệ thống ThreeH Workshop:\n\n"
                    f"Xe {v_label} đã thay dầu động cơ lần gần nhất vào {date_str}{km_str}{ro_str}, loại dầu sử dụng là **{oil_item['name']}**.\n\n"
                    f"{mileage_diff_str}\n\n"
                    "Theo khuyến nghị bảo dưỡng thông thường (mỗi 5.000 km hoặc 6 tháng tùy điều kiện nào đến trước), bạn nên theo dõi mốc này để chủ động thay dầu và lọc dầu định kỳ, giúp động cơ luôn vận hành bền bỉ."
                )
                if oil_item.get("ro_id"):
                    sources.append({"type": "repair_order", "id": oil_item["ro_id"], "label": f"Phiếu sửa chữa {oil_item.get('ro_code') or oil_item['ro_id']}: {oil_item['name']}"})
                else:
                    sources.append({"type": "vehicle", "id": target_vehicle["id"], "label": f"Lịch sử bảo dưỡng xe {v_label}"})
            else:
                fallback_content = (
                    f"Hệ thống ThreeH Workshop chưa ghi nhận lần thay dầu động cơ nào đã hoàn thành cho xe {v_label}. "
                    "Bạn vui lòng cung cấp mốc số km hoặc ngày thay dầu gần nhất để garage tư vấn mốc bảo dưỡng tiếp theo nhé."
                )
                sources.append({"type": "vehicle", "id": target_vehicle["id"], "label": f"Hồ sơ xe: {v_label}"})

            narrated = ai_service.narrate_repair_history(question, target_vehicle, [oil_item] if oil_item else [], user.get("role", "Khách hàng"), fallback_content)
            return narrated, sources

        # 4. Câu hỏi xe đã thay má phanh chưa
        if is_brake_query:
            brake_item = None
            for p in parts:
                p_norm = ai_service._normalize_vi(p["name"])
                if any(k in p_norm for k in ("ma phanh", "bo phanh", "phanh")):
                    brake_item = p
                    break
            if not brake_item:
                for h in history_entries:
                    s_norm = ai_service._normalize_vi(h.get("services") or "")
                    if any(k in s_norm for k in ("ma phanh", "bo phanh")):
                        brake_item = {
                            "name": "Má phanh",
                            "date": str(h.get("repaired_at") or "")[:10],
                            "km": h.get("mileage"),
                            "ro_code": None,
                            "ro_id": None
                        }
                        break

            if brake_item:
                date_str = f"ngày {brake_item['date']}" if brake_item.get("date") else "thời gian trước"
                km_str = f" ở mốc {brake_item['km']:,} km".replace(",", ".") if brake_item.get("km") else ""
                ro_str = f" (Phiếu sửa chữa {brake_item['ro_code']})" if brake_item.get("ro_code") else ""
                cur_km = target_vehicle.get("mileage")
                mileage_diff_str = ""
                if cur_km and brake_item.get("km"):
                    diff = cur_km - brake_item["km"]
                    if diff >= 0:
                        mileage_diff_str = f" Hiện tại số km ghi nhận của xe là {cur_km:,} km, tức xe đã vận hành thêm khoảng {diff:,} km kể từ lần thay má phanh đó.".replace(",", ".")

                fallback_content = (
                    f"Theo hồ sơ xưởng, xe {v_label} **đã từng thay má phanh**:\n\n"
                    f"- Phụ tùng thay thế: **{brake_item['name']}**\n"
                    f"- Thời gian thực hiện: {date_str}{km_str}{ro_str}.\n\n"
                    f"{mileage_diff_str}\n\n"
                    "Kỹ thuật viên khuyến nghị nên duy trì kiểm tra độ mòn má phanh và đĩa phanh định kỳ sau mỗi 10.000 - 20.000 km hoặc mỗi lần bảo dưỡng để đảm bảo an toàn phanh tối đa."
                )
                if brake_item.get("ro_id"):
                    sources.append({"type": "repair_order", "id": brake_item["ro_id"], "label": f"Phiếu sửa chữa {brake_item.get('ro_code') or brake_item['ro_id']}: {brake_item['name']}"})
                else:
                    sources.append({"type": "vehicle", "id": target_vehicle["id"], "label": f"Lịch sử bảo dưỡng xe {v_label}"})
            else:
                fallback_content = (
                    f"Theo lịch sử ghi nhận trên hệ thống ThreeH Workshop, xe {v_label} **chưa từng thay má phanh** tại xưởng "
                    "(các lần vào xưởng trước chỉ ghi nhận kiểm tra hệ thống phanh hoặc bảo dưỡng định kỳ).\n\n"
                    "Kỹ thuật viên khuyến nghị nên đo kiểm độ mòn thực tế của má phanh nếu xe đã vận hành trên 20.000 - 30.000 km kể từ lần kiểm tra gần nhất."
                )
                sources.append({"type": "vehicle", "id": target_vehicle["id"], "label": f"Hồ sơ xe: {v_label}"})

            narrated = ai_service.narrate_repair_history(question, target_vehicle, [brake_item] if brake_item else [], user.get("role", "Khách hàng"), fallback_content)
            return narrated, sources

        # 5. Phụ tùng thay trong lần bảo dưỡng gần nhất
        if is_latest_visit_parts_query:
            latest_ro = completed_ros[0] if completed_ros else None
            latest_parts = []
            if latest_ro:
                latest_parts = [p for p in parts if p.get("ro_id") == latest_ro["id"]]
                if not latest_parts and latest_ro.get("action_date"):
                    ro_date = str(latest_ro["action_date"])[:10]
                    latest_parts = [p for p in parts if p.get("date") == ro_date]

            if latest_parts:
                lines = []
                for idx, p in enumerate(latest_parts, start=1):
                    km_text = f" (ở mốc {p['km']:,} km)".replace(",", ".") if p.get("km") else ""
                    date_text = f" – ngày {p['date']}" if p.get("date") else ""
                    qty_text = f", số lượng {p['quantity']}" if p.get("quantity") and p["quantity"] > 1 else ""
                    lines.append(f"{idx}. {p['name']}{date_text}{qty_text}{km_text}")
                    if p.get("ro_id"):
                        sources.append({"type": "repair_order", "id": p["ro_id"], "label": f"Phiếu sửa chữa {p.get('ro_code') or p['ro_id']}: {p['name']}"})

                ro_date_str = f" vào ngày {str(latest_ro['action_date'])[:10]}" if latest_ro and latest_ro.get("action_date") else ""
                ro_code_str = f" (Phiếu sửa chữa {latest_ro['code']})" if latest_ro and latest_ro.get("code") else ""
                inv = db.execute("SELECT id, code, total, paid_amount, status FROM invoices WHERE repair_order_id=?", (latest_ro["id"],)).fetchone() if latest_ro else None
                cost_str = ""
                if latest_ro.get("total") or inv:
                    cost_amount = int(inv["total"]) if inv else int(latest_ro.get("total") or 0)
                    cost_str = f"\n\nTổng chi phí thanh toán cho lần bảo dưỡng này là {cost_amount:,} ₫".replace(",", ".")
                    if inv:
                        cost_str += f" (theo Hóa đơn {inv['code']}, trạng thái: {inv['status']})."
                        sources.append({"type": "invoice", "id": inv["id"], "label": f"Hóa đơn {inv['code']}: {cost_amount:,} ₫".replace(",", ".")})
                    else:
                        cost_str += f" (theo Phiếu sửa chữa {latest_ro['code']})."

                fallback_content = (
                    f"Trong lần bảo dưỡng gần nhất{ro_date_str}{ro_code_str}, xe {v_label} đã được thay thế các phụ tùng sau:\n\n"
                    + "\n".join(lines) + "\n\n"
                    "Các hạng mục này đã được nghiệm thu và hoàn thành bàn giao xe."
                    + cost_str
                )
            elif latest_ro:
                srv_in_latest = [s["name"] for s in data.get("services_performed", []) if s.get("ro_id") == latest_ro["id"]]
                srv_text = f" gồm: {', '.join(srv_in_latest)}" if srv_in_latest else ""
                ro_date_str = f" ngày {str(latest_ro['action_date'])[:10]}" if latest_ro.get("action_date") else ""
                fallback_content = (
                    f"Trong lần vào xưởng gần nhất{ro_date_str} (Phiếu sửa chữa {latest_ro.get('code')}), "
                    f"xe {v_label} chỉ thực hiện các dịch vụ kỹ thuật/kiểm tra{srv_text}, "
                    "chưa ghi nhận thay thế phụ tùng hay vật tư nào trong lần đó."
                )
                sources.append({"type": "repair_order", "id": latest_ro["id"], "label": f"Phiếu sửa chữa {latest_ro.get('code')}"})
            else:
                fallback_content = f"Hệ thống ThreeH Workshop chưa ghi nhận phiếu bảo dưỡng nào đã hoàn thành cho xe {v_label}."
                sources.append({"type": "vehicle", "id": target_vehicle["id"], "label": f"Hồ sơ xe: {v_label}"})

            narrated = ai_service.narrate_repair_history(question, target_vehicle, latest_parts, user.get("role", "Khách hàng"), fallback_content)
            return narrated, sources

        # 6. Tổng quan xe đã sửa những gì
        if is_general_repair_query:
            services = data.get("services_performed", [])
            total_orders = len(completed_ros) or total_ros or len(history_entries)

            srv_lines = []
            seen_srv_names = set()
            for s in services:
                if s["name"] not in seen_srv_names and len(srv_lines) < 6:
                    seen_srv_names.add(s["name"])
                    date_info = f" (gần nhất ngày {s['date']})" if s.get("date") else ""
                    srv_lines.append(f"- {s['name']}{date_info}")

            part_lines = []
            seen_p_names = set()
            for p in parts:
                if p["name"] not in seen_p_names and len(part_lines) < 6:
                    seen_p_names.add(p["name"])
                    date_info = f" (thay ngày {p['date']})" if p.get("date") else ""
                    part_lines.append(f"- {p['name']}{date_info}")

            srv_section = ("* Các dịch vụ kỹ thuật đã thực hiện:\n" + "\n".join(srv_lines) + "\n\n") if srv_lines else ""
            part_section = ("* Các phụ tùng, vật tư đã thay thế thực tế:\n" + "\n".join(part_lines) + "\n\n") if part_lines else ""

            fallback_content = (
                f"Theo hồ sơ trên hệ thống ThreeH Workshop, xe {v_label} đã có {total_orders} lần ghi nhận sửa chữa / dịch vụ đã hoàn thành:\n\n"
                + srv_section
                + part_section
                + "Hệ thống phân định rõ ràng giữa dịch vụ thực hiện và phụ tùng vật tư thay thế thực tế. "
                "Bạn có muốn xem chi tiết phụ tùng thay trong lần nào cụ thể không?"
            )
            for ro in completed_ros[:3]:
                sources.append({"type": "repair_order", "id": ro["id"], "label": f"Phiếu sửa chữa {ro.get('code') or ro['id']}"})
            if not sources:
                sources.append({"type": "vehicle", "id": target_vehicle["id"], "label": f"Hồ sơ xe: {v_label}"})

            narrated = ai_service.narrate_repair_history(question, target_vehicle, parts, user.get("role", "Khách hàng"), fallback_content)
            return narrated, sources

        # 7. Xe có phiếu sửa chữa nhưng chưa từng thay phụ tùng (chỉ làm dịch vụ/kiểm tra)
        if not parts:
            return AIResult(
                f"Qua hồ sơ trên hệ thống, xe {v_label} đã có {total_ros or len(history_entries)} lần vào xưởng, "
                "tuy nhiên các lần này chỉ thực hiện các dịch vụ kiểm tra, vệ sinh hoặc bảo dưỡng định kỳ, "
                "chưa ghi nhận thay thế phụ tùng hay vật tư nào.\n\n"
                "Nếu bạn cần xem chi tiết các dịch vụ đã thực hiện trong từng lần, vui lòng cho mình biết nhé.",
                "fallback", "local", ai_service.model, False
            ), [{"type": "vehicle", "id": target_vehicle["id"], "label": f"Hồ sơ xe: {v_label}"}]

        # 8. Mặc định: Hiển thị danh sách phụ tùng đã thay thế thực tế
        lines = []
        for idx, p in enumerate(parts[:10], start=1):
            km_text = f" (ở mốc {p['km']:,} km)".replace(",", ".") if p.get("km") else ""
            date_text = f" – ngày {p['date']}" if p.get("date") else ""
            qty_text = f", số lượng {p['quantity']}" if p.get("quantity") and p["quantity"] > 1 else ""
            lines.append(f"{idx}. {p['name']}{date_text}{qty_text}{km_text}")

            if p.get("ro_id"):
                sources.append({
                    "type": "repair_order",
                    "id": p["ro_id"],
                    "label": f"Phiếu sửa chữa {p.get('ro_code') or p['ro_id']}: {p['name']}"
                })

        more_text = f"\n(Và {len(parts) - 10} hạng mục phụ tùng khác trong các lần sửa trước)." if len(parts) > 10 else ""

        fallback_content = (
            f"Qua lịch sử sửa chữa được ghi nhận trên hệ thống, xe {v_label} của bạn đã có các hạng mục thay thế sau:\n\n"
            + "\n".join(lines) + more_text + "\n\n"
            "Ngoài ra, xe còn có các lần kiểm tra và bảo dưỡng khác. Những hạng mục trên được tổng hợp từ các phiếu sửa chữa đã ghi nhận hoàn thành.\n\n"
            "Bạn muốn xem chi tiết từng lần sửa chữa hay kiểm tra phụ tùng nào đã được thay gần đây nhất?"
        )

        recommendations = evaluate_maintenance_recommendations(db, target_vehicle, data, user)
        rec_text = format_recommendations_text(recommendations)
        if rec_text:
            fallback_content = (
                f"Qua lịch sử sửa chữa được ghi nhận trên hệ thống, xe {v_label} của bạn đã có các hạng mục thay thế sau:\n\n"
                + "\n".join(lines) + more_text + "\n\n"
                + rec_text.strip() + "\n\n"
                + "Những hạng mục trên được tổng hợp từ các phiếu sửa chữa đã ghi nhận hoàn thành. "
                + "Bạn có thể bấm nút bên dưới để đặt lịch kiểm tra/bảo dưỡng hoặc cho mình biết nếu cần hỗ trợ thêm."
            )

        if not sources:
            sources.append({"type": "vehicle", "id": target_vehicle["id"], "label": f"Lịch sử sửa chữa xe {v_label}"})

        narrated = ai_service.narrate_repair_history(question, target_vehicle, parts, user.get("role", "Khách hàng"), fallback_content)
        if rec_text and rec_text.strip() not in narrated.content:
            narrated.content = narrated.content + "\n\n" + rec_text.strip()
        narrated.maintenance_recommendations = recommendations
        return narrated, sources
    except Exception:
        return AIResult(
            "Chưa thể tra cứu lịch sử sửa chữa lúc này do hệ thống đang bận. Vui lòng thử lại sau.",
            "error", "local", ai_service.model
        ), []
