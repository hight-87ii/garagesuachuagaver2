"""Các tập giá trị (enum) dùng chung, khớp với ràng buộc CHECK trong CSDL."""

from typing import Literal

AppointmentStatus = Literal["Đang chờ", "Đã xác nhận", "Đã tiếp nhận", "Đã hủy"]
RepairOrderStatus = Literal[
    "Tiếp nhận",
    "Đang kiểm tra",
    "Đã báo giá",
    "Đã duyệt",
    "Đang sửa",
    "Chờ phụ tùng",
    "Tạm dừng",
    "Hoàn thành",
    "Đã bàn giao",
    "Đã hủy",
]
RepairOrderStatusCode = Literal[
    "RECEIVED",
    "INSPECTING",
    "QUOTED",
    "APPROVED",
    "IN_PROGRESS",
    "WAITING_FOR_PARTS",
    "ON_HOLD",
    "COMPLETED",
    "DELIVERED",
    "CANCELLED",
]
Priority = Literal["Thấp", "Bình thường", "Cao", "Gấp"]
InvoiceStatus = Literal["Chưa thanh toán", "Thanh toán một phần", "Đã thanh toán", "Đã hủy"]
PaymentMethod = Literal["Tiền mặt", "Chuyển khoản", "Thẻ", "Ví điện tử"]
QuoteStatus = Literal["Nháp", "Chờ duyệt", "Đã duyệt", "Từ chối", "Hết hiệu lực"]
ItemKind = Literal["Dịch vụ", "Phụ tùng"]
AITask = Literal["summary", "explain", "estimate"]
