# -*- coding: utf-8 -*-
"""Module Smart Maintenance Recommendation – Gợi ý bảo dưỡng thông minh.

Phân tích số kilomet và thời gian sử dụng phụ tùng từ hồ sơ sửa chữa
để đưa ra khuyến nghị bảo dưỡng chính xác, phòng tránh gợi ý trùng lặp
với lịch hẹn tương lai, và phân biệt rõ kiểm tra độ mòn (má phanh) với thay thế.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .ai_service import ai_service
from .maintenance_interval import find_oil_interval


def get_active_future_appointments(db: sqlite3.Connection, vehicle_id: int) -> list[dict]:
    """Lấy danh sách các lịch hẹn tương lai đang chờ hoặc đã xác nhận của phương tiện."""
    rows = db.execute(
        """SELECT id, vehicle_id, service, appointment_at, status, note, reason
           FROM appointments
           WHERE vehicle_id = ?
             AND status IN ('Đang chờ', 'Đã xác nhận', 'pending', 'confirmed')
             AND appointment_at >= datetime('now', '-1 hour')
           ORDER BY appointment_at ASC""",
        (vehicle_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def has_matching_appointment(active_appointments: list[dict], category: str) -> bool:
    """Kiểm tra xem phương tiện đã có lịch hẹn tương lai cho hạng mục này chưa."""
    for appt in active_appointments:
        svc_norm = ai_service._normalize_vi(appt.get("service") or "")
        reason_norm = ai_service._normalize_vi(appt.get("reason") or "")
        note_norm = ai_service._normalize_vi(appt.get("note") or "")
        combined = f"{svc_norm} {reason_norm} {note_norm}"

        if category == "oil_change":
            if any(term in combined for term in ("dau", "nhot", "oil", "bao duong")):
                return True
        elif category == "brake_pads":
            if any(term in combined for term in ("phanh", "brake")):
                return True
        elif category == "oil_filter":
            if any(term in combined for term in ("loc dau", "oil filter")):
                return True
        elif category == "air_filter":
            if any(term in combined for term in ("loc gio", "air filter")):
                return True
    return False


def evaluate_maintenance_recommendations(
    db: sqlite3.Connection,
    vehicle: dict | None,
    history_data: dict[str, Any],
    user: dict,
) -> list[dict[str, Any]]:
    """Đánh giá và tạo danh sách gợi ý bảo dưỡng thông minh dựa trên dữ liệu thực tế."""
    if not vehicle:
        return []

    vehicle_id = vehicle.get("id")
    plate = vehicle.get("plate", "")
    current_km = vehicle.get("mileage")

    # Kịch bản 4: Thiếu số kilomet hiện tại
    if current_km is None or current_km <= 0:
        return [{
            "category": "mileage",
            "item_name": "Thông tin số kilomet",
            "action_type": "update_mileage",
            "action_label": "Cập nhật số km",
            "service_id": 6,
            "service_name": "Kiểm tra tổng quát",
            "vehicle_id": vehicle_id,
            "vehicle_plate": plate,
            "missing_mileage": True,
            "status": "warning",
            "recommendation_text": (
                "Xe hiện chưa có thông tin số kilomet hiện tại trên hệ thống. "
                "Quý khách vui lòng cập nhật số km hoặc mang xe đến garage để kiểm tra chính xác các mốc bảo dưỡng định kỳ."
            ),
        }]

    parts = history_data.get("parts_replaced") or []

    # Kịch bản 5: Không có lịch sử thay phụ tùng -> không suy đoán
    if not parts:
        return []

    # Kiểm tra số km bất thường (current_km < last_km)
    recorded_kms = [p["km"] for p in parts if p.get("km") is not None]
    if recorded_kms:
        max_past_km = max(recorded_kms)
        if current_km < max_past_km:
            return [{
                "category": "mileage_anomaly",
                "item_name": "Cảnh báo số kilomet",
                "action_type": "check_odometer",
                "action_label": "Kiểm tra đồng hồ",
                "service_id": 6,
                "service_name": "Kiểm tra tổng quát",
                "vehicle_id": vehicle_id,
                "vehicle_plate": plate,
                "current_km": current_km,
                "last_km": max_past_km,
                "mileage_anomaly": True,
                "status": "warning",
                "recommendation_text": (
                    f"Cảnh báo số kilomet: Số km hiện tại ({current_km:,} km) nhỏ hơn số km tại lần sửa chữa trước "
                    f"({max_past_km:,} km). Quý khách vui lòng kiểm tra lại đồng hồ công-tơ-mét hoặc liên hệ cố vấn dịch vụ để đối chiếu."
                ),
            }]

    # Lấy lịch hẹn tương lai để chống gợi ý trùng lặp (Kịch bản 8)
    active_appointments = get_active_future_appointments(db, vehicle_id) if vehicle_id else []

    recommendations: list[dict[str, Any]] = []

    # 1. Đánh giá Dầu động cơ (Kịch bản 1, 2, 7)
    oil_parts = [
        p for p in parts
        if any(term in ai_service._normalize_vi(p["name"]) for term in (
            "dau dong co", "dau may", "dau nhot", "5w-", "0w-", "10w-", "nhot dong co"
        )) and p.get("km") is not None
    ]
    if oil_parts:
        latest_oil = oil_parts[0]
        last_km = latest_oil["km"]
        used_km = current_km - last_km

        # Tra cứu chu kỳ đã duyệt
        verified_interval = find_oil_interval(db, vehicle)
        if verified_interval:
            interval_km = verified_interval["interval_km"]
            source_name = verified_interval.get("source_name") or f"Khuyến nghị kỹ thuật {vehicle.get('make', '')} {vehicle.get('model', '')}"
            source_type = "verified"
        else:
            # Kịch bản 7: Chưa có chu kỳ xác minh từ hãng
            interval_km = 5000
            source_name = "Mốc tiêu chuẩn garage (cần kỹ thuật viên xác nhận theo phẩm cấp dầu)"
            source_type = "standard"

        if used_km >= interval_km:
            if not has_matching_appointment(active_appointments, "oil_change"):
                recommendations.append({
                    "category": "oil_change",
                    "item_name": "Dầu động cơ",
                    "action_type": "replace",
                    "action_label": "Đặt lịch thay dầu động cơ",
                    "last_km": last_km,
                    "last_date": latest_oil.get("date"),
                    "current_km": current_km,
                    "used_km": used_km,
                    "interval_km": interval_km,
                    "source_type": source_type,
                    "source_name": source_name,
                    "service_id": 2,
                    "service_name": "Thay dầu động cơ",
                    "vehicle_id": vehicle_id,
                    "vehicle_plate": plate,
                    "status": "due",
                    "recommendation_text": (
                        f"Dầu động cơ đã sử dụng {used_km:,} km (kể từ mốc {last_km:,} km ngày {latest_oil.get('date', '')}). "
                        f"Đã vượt chu kỳ khuyến nghị ({interval_km:,} km - nguồn: {source_name}). "
                        "Quý khách nên kiểm tra và thay dầu động cơ định kỳ để bảo vệ động cơ xe."
                    ),
                })
        elif used_km >= int(interval_km * 0.85):
            if not has_matching_appointment(active_appointments, "oil_change"):
                recommendations.append({
                    "category": "oil_change",
                    "item_name": "Dầu động cơ",
                    "action_type": "replace",
                    "action_label": "Đặt lịch thay dầu động cơ",
                    "last_km": last_km,
                    "last_date": latest_oil.get("date"),
                    "current_km": current_km,
                    "used_km": used_km,
                    "interval_km": interval_km,
                    "source_type": source_type,
                    "source_name": source_name,
                    "service_id": 2,
                    "service_name": "Thay dầu động cơ",
                    "vehicle_id": vehicle_id,
                    "vehicle_plate": plate,
                    "status": "warning",
                    "recommendation_text": (
                        f"Dầu động cơ đã sử dụng {used_km:,} km (kể từ mốc {last_km:,} km). "
                        f"Sắp đến chu kỳ khuyến nghị ({interval_km:,} km - nguồn: {source_name}). "
                        "Quý khách có thể sắp xếp đặt lịch kiểm tra hoặc thay dầu trong thời gian tới."
                    ),
                })

    # 2. Đánh giá Má phanh (Kịch bản 3: Ngưỡng 20.000 km CHỈ NHẮC KIỂM TRA ĐỘ MÒN, TUYỆT ĐỐI KHÔNG MẶC ĐỊNH THAY THẾ)
    brake_parts = [
        p for p in parts
        if any(term in ai_service._normalize_vi(p["name"]) for term in (
            "ma phanh", "bo phanh", "bo thang", "brake pad", "ma phanh truoc", "ma phanh sau"
        )) and p.get("km") is not None
    ]
    if brake_parts:
        latest_brake = brake_parts[0]
        last_km = latest_brake["km"]
        used_km = current_km - last_km

        if used_km >= 20000:
            if not has_matching_appointment(active_appointments, "brake_pads"):
                recommendations.append({
                    "category": "brake_pads",
                    "item_name": "Má phanh",
                    "action_type": "inspect_wear",
                    "action_label": "Đặt lịch kiểm tra má phanh",
                    "last_km": last_km,
                    "last_date": latest_brake.get("date"),
                    "current_km": current_km,
                    "used_km": used_km,
                    "interval_km": 20000,
                    "source_type": "standard",
                    "source_name": "Mốc kiểm tra an toàn định kỳ hệ thống phanh (20.000 km)",
                    "service_id": 3,
                    "service_name": "Kiểm tra hệ thống phanh",
                    "vehicle_id": vehicle_id,
                    "vehicle_plate": plate,
                    "status": "inspect",
                    "recommendation_text": (
                        f"Má phanh đã hoạt động {used_km:,} km kể từ lần thay trước tại {last_km:,} km (ngày {latest_brake.get('date', '')}). "
                        "Theo mốc an toàn sau mỗi 20.000 km, quý khách nên đặt lịch kiểm tra độ mòn má phanh và an toàn hệ thống phanh. "
                        "Lưu ý: Kỹ thuật viên sẽ đo độ dày thực tế của má phanh tại xưởng, không mặc định thay thế."
                    ),
                })

    # 3. Đánh giá Lọc dầu động cơ (thường 10.000 km)
    filter_parts = [
        p for p in parts
        if "loc dau" in ai_service._normalize_vi(p["name"]) and p.get("km") is not None
    ]
    if filter_parts:
        latest_filter = filter_parts[0]
        last_km = latest_filter["km"]
        used_km = current_km - last_km

        if used_km >= 10000:
            if not has_matching_appointment(active_appointments, "oil_filter") and not any(r["category"] == "oil_change" for r in recommendations):
                recommendations.append({
                    "category": "oil_filter",
                    "item_name": "Lọc dầu động cơ",
                    "action_type": "replace",
                    "action_label": "Đặt lịch thay lọc dầu",
                    "last_km": last_km,
                    "last_date": latest_filter.get("date"),
                    "current_km": current_km,
                    "used_km": used_km,
                    "interval_km": 10000,
                    "source_type": "standard",
                    "source_name": "Chu kỳ thay lọc dầu định kỳ (10.000 km)",
                    "service_id": 12,
                    "service_name": "Thay lọc dầu động cơ",
                    "vehicle_id": vehicle_id,
                    "vehicle_plate": plate,
                    "status": "due",
                    "recommendation_text": (
                        f"Lọc dầu động cơ đã sử dụng {used_km:,} km kể từ mốc {last_km:,} km. "
                        "Khuyến nghị thay lọc dầu định kỳ sau mỗi 10.000 km (hoặc mỗi 2 lần thay dầu máy)."
                    ),
                })

    return recommendations


def format_recommendations_text(recommendations: list[dict[str, Any]]) -> str:
    """Tạo đoạn văn tóm tắt gợi ý bảo dưỡng đưa vào câu trả lời AI."""
    if not recommendations:
        return ""

    lines = ["**Gợi ý bảo dưỡng thông minh cho xe của bạn:**"]
    for rec in recommendations:
        if rec.get("missing_mileage") or rec.get("mileage_anomaly"):
            lines.append(f"• {rec['recommendation_text']}")
        else:
            lines.append(f"• **{rec['item_name']}**: {rec['recommendation_text']}")

    return "\n\n" + "\n\n".join(lines)

