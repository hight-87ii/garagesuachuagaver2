"""Điểm vào ứng dụng FastAPI của GarageAI.

Ứng dụng chỉ chịu trách nhiệm lắp ghép: cấu hình middleware, đăng ký bộ xử lý
lỗi thống nhất và gắn các module nghiệp vụ dưới tiền tố có phiên bản ``/api/v1``.
Toàn bộ logic nghiệp vụ nằm trong gói ``backend/api/v1``.
"""

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from .api.v1 import api_v1
from .core.config import API_PREFIX, API_VERSION, APP_TITLE, APP_VERSION, CORS_ORIGINS
from .core.errors import register_exception_handlers
from .core.logging import AccessLogMiddleware, configure_logging
from .database import init_db
from .middleware import ApiVersionMiddleware

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title=APP_TITLE,
    version=APP_VERSION,
    lifespan=lifespan,
    description="API quản lý garage sửa chữa ô tô — phiên bản v1 (đường dẫn chuẩn: /api/v1).",
)

# Thứ tự middleware: CORS ngoài cùng, rồi đến chuyển phiên bản, rồi ghi log truy cập.
app.add_middleware(AccessLogMiddleware)
app.add_middleware(ApiVersionMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(api_v1, prefix=f"{API_PREFIX}/{API_VERSION}")


@app.get("/health", tags=["Health"])
def health() -> dict:
    return {
        "status": "ok",
        "service": "garage-ai",
        "version": APP_VERSION,
        "api_version": API_VERSION,
    }
