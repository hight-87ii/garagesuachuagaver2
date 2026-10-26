"""Cấu hình ứng dụng (đọc từ biến môi trường, có giá trị mặc định an toàn)."""

import os

# Phiên bản API: mọi endpoint nghiệp vụ được phục vụ dưới /api/v1.
API_PREFIX = "/api"
API_VERSION = "v1"
APP_TITLE = "ThreeH Workshop API"
APP_VERSION = "2.1.0"


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    return ["http://localhost:5173", "http://127.0.0.1:5173"]


CORS_ORIGINS = _cors_origins()

DEFAULT_PAGE_SIZE = int(os.getenv("API_PAGE_SIZE", "50"))
MAX_PAGE_SIZE = int(os.getenv("API_MAX_PAGE_SIZE", "200"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Lịch làm việc của garage (giờ Việt Nam) dùng để kiểm tra lịch hẹn.
# WORKING_DAYS theo ISO-8601: 1 = Thứ 2 ... 7 = Chủ nhật.
WORKING_DAYS = os.getenv("GARAGE_WORKING_DAYS", "1,2,3,4,5,6")
WORKING_START = os.getenv("GARAGE_WORKING_START", "07:30")
WORKING_END = os.getenv("GARAGE_WORKING_END", "18:00")
APPOINTMENT_OVERLOAD_THRESHOLD = max(1, int(os.getenv("APPOINTMENT_OVERLOAD_THRESHOLD", "3")))
APPOINTMENT_LOAD_SLOT_MINUTES = max(30, min(120, int(os.getenv("APPOINTMENT_LOAD_SLOT_MINUTES", "60"))))
