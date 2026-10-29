"""Quy tắc hiệu lực chung cho báo giá; NULL là chưa xác định, không phải vô hạn."""

from .timeutil import now_utc_iso, vn_text


def validity_state(valid_until: str | None, now: str | None = None) -> str:
    if not valid_until:
        return "unknown"
    return "expired" if (now or now_utc_iso()) >= valid_until else "valid"


def approval_validity_error(valid_until: str | None, now: str | None = None) -> str | None:
    state = validity_state(valid_until, now)
    if state == "unknown":
        return "Báo giá chưa có hạn hiệu lực xác định. Vui lòng tạo phiên bản báo giá mới."
    if state == "expired":
        return (f"Báo giá đã hết hiệu lực từ ngày {vn_text(valid_until)} (giờ Việt Nam). "
                "Không thể duyệt; vui lòng tạo báo giá mới.")
    return None
