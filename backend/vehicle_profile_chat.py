"""Verified maintenance milestones from the selected owner's vehicle; never model-generated."""

from datetime import date, datetime

from .ai_service import AIResult, ai_service
from .timeutil import VN_TZ


def answer_maintenance_plan(db, question: str, vehicle):
    text = ai_service._normalize_vi(question)
    if not any(term in text for term in ("ky bao duong", "lan bao duong tiep", "bao nhieu km nua", "bao duong tiep theo")):
        return None
    if not vehicle:
        return AIResult("Vui lòng chọn xe của bạn để tra lịch bảo dưỡng đã lưu.",
                        "clarification", "local", ai_service.model, True), []
    plan = db.execute("SELECT next_service_at,next_service_mileage,maintenance_source,maintenance_items FROM vehicle_profiles WHERE vehicle_id=?",
                      (vehicle["id"],)).fetchone()
    if not plan or not plan["maintenance_source"] or not (plan["next_service_at"] or plan["next_service_mileage"] is not None):
        return AIResult("Chưa có lịch bảo dưỡng được garage xác minh cho xe này. Cần đối chiếu sổ bảo dưỡng và số km thực tế.",
                        "no_data", "local", ai_service.model, True), []
    current = vehicle["mileage"]
    parts = []
    if plan["next_service_mileage"] is not None:
        parts.append(f"Mốc đã lưu: {plan['next_service_mileage']:,} km".replace(",", "."))
        if current is not None:
            remaining = plan["next_service_mileage"] - current
            parts.append((f"Còn {remaining:,} km theo số km hiện tại" if remaining > 0 else
                          "Đã đạt hoặc vượt mốc km đã lưu").replace(",", "."))
    if plan["next_service_at"]:
        parts.append(f"Ngày dự kiến: {plan['next_service_at']}")
        if date.fromisoformat(plan["next_service_at"]) < datetime.now(VN_TZ).date():
            parts.append("Đã qua ngày dự kiến")
    if (plan["maintenance_items"] or "").strip():
        parts.append(f"Hạng mục đã lưu: {plan['maintenance_items'].strip()}")
    answer = "; ".join(parts) + f". Nguồn: {plan['maintenance_source']}. Đây là lịch dự kiến, không phải lịch hẹn đã được xác nhận."
    return (AIResult(answer, "fallback", "local", ai_service.model),
            [{"type": "vehicle", "id": vehicle["id"], "label": "Lịch bảo dưỡng đã lưu trong hồ sơ xe"}])
