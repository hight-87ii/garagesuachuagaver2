"""Tiện ích thời gian cho GarageAI.

- Lưu trữ: mọi mốc thời gian trong cơ sở dữ liệu là **UTC ISO-8601** dạng
  ``YYYY-MM-DDTHH:MM:SSZ``.
- Hiển thị: chuyển sang múi giờ Việt Nam (UTC+7) khi trả về API/UI.
"""

from datetime import date, datetime, timedelta, timezone

VN_TZ = timezone(timedelta(hours=7))
UTC_STORAGE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _parse(value) -> datetime | None:
    """Phân tích giá trị thời gian từ nhiều định dạng về datetime có múi giờ."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        moment = datetime(value.year, value.month, value.day)
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            moment = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y"):
                try:
                    moment = datetime.strptime(str(value).strip(), fmt)
                    break
                except ValueError:
                    continue
            if moment is None:
                return None
    if moment.tzinfo is None:
        # Giá trị cũ/không có múi giờ được coi là giờ Việt Nam.
        moment = moment.replace(tzinfo=VN_TZ)
    return moment


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_utc_iso() -> str:
    return now_utc().strftime(UTC_STORAGE_FORMAT)


def to_utc_iso(value) -> str:
    """Chuyển một giá trị thời gian (giờ VN nếu không có múi giờ) sang chuỗi UTC lưu trữ."""
    moment = _parse(value)
    if moment is None:
        return now_utc_iso()
    return moment.astimezone(timezone.utc).strftime(UTC_STORAGE_FORMAT)


def vn_datetime(value) -> datetime | None:
    moment = _parse(value)
    return moment.astimezone(VN_TZ) if moment else None


def vn_text(value) -> str | None:
    """Hiển thị ``YYYY-MM-DD HH:MM`` theo giờ Việt Nam."""
    moment = vn_datetime(value)
    return moment.strftime("%Y-%m-%d %H:%M") if moment else None


def vn_date(value) -> str | None:
    moment = vn_datetime(value)
    return moment.strftime("%Y-%m-%d") if moment else None


def vn_date_text(value) -> str:
    moment = vn_datetime(value)
    return moment.strftime("%d/%m/%Y") if moment else "—"
