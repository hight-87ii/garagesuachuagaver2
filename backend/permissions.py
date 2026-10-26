"""Phân quyền theo vai trò (RBAC - Role-Based Access Control).

Mỗi vai trò được gán một tập quyền (permission). Backend dùng bảng này để
kiểm tra quyền truy cập (authorization); frontend dùng bảng tương đương để
điều hướng giao diện (routing) và hiển thị dashboard theo vai trò.
"""

# Quyền gắn với từng chức năng của hệ thống (khoá dùng chung với frontend).
PERMISSIONS: dict[str, str] = {
    "dashboard": "Xem tổng quan",
    "appointments": "Quản lý lịch hẹn",
    "appointment.view": "Xem lịch hẹn được phép truy cập",
    "appointment.view_all": "Xem tất cả lịch hẹn trong phạm vi được cấp",
    "appointment.view_status": "Xem trạng thái lịch hẹn",
    "appointment.view_statistics": "Xem thống kê lịch hẹn",
    "appointment.view_details": "Xem chi tiết lịch hẹn",
    "appointment.check_availability": "Kiểm tra tải khung giờ",
    "appointment.recommend_reschedule": "Xem đề xuất đổi lịch",
    "appointment.reschedule": "Đổi lịch hẹn",
    "appointment.manage": "Quản lý lịch hẹn",
    "repair_orders": "Quản lý phiếu sửa chữa",
    "customers": "Quản lý khách hàng",
    "vehicles": "Quản lý phương tiện",
    "customer.view": "Xem thông tin khách hàng",
    "customer.view_all": "Xem danh sách khách hàng trong phạm vi được phép",
    "vehicle.view": "Xem thông tin xe",
    "vehicle.view_all": "Xem danh sách xe trong phạm vi được phép",
    "customer_vehicle.view": "Tra cứu quan hệ khách hàng và xe",
    "customer_vehicle.view_all": "Tra cứu danh sách khách hàng và xe trong phạm vi được phép",
    "services": "Quản lý dịch vụ",
    "inventory": "Quản lý kho phụ tùng",
    "inventory.view": "Xem số lượng tồn kho",
    "inventory.view_all": "Xem toàn bộ kho hiện có",
    "inventory.view_low_stock": "Xem mặt hàng sắp hết",
    "inventory.view_statistics": "Xem thống kê tồn kho",
    "inventory.view_stock_value": "Xem giá trị tồn kho",
    "inventory.view_transactions": "Xem giao dịch kho",
    "inventory.recommend_restock": "Xem đề xuất bổ sung",
    "inventory.manage": "Điều chỉnh kho",
    "invoices": "Quản lý hóa đơn",
    "invoice.view": "Xem thông tin hóa đơn",
    "invoice.view_amount": "Xem số tiền hóa đơn và thanh toán",
    "invoice.view_debt": "Xem công nợ hóa đơn",
    "invoice.view_all": "Xem tất cả hóa đơn được quản lý",
    "invoice.calculate": "Tính tổng hóa đơn và công nợ",
    "staff": "Quản lý nhân viên",
    "my_vehicles": "Xem xe của tôi",
    "reports": "Tra cứu lịch sử và báo cáo",
    "technical_review": "Duyệt chuyên môn bài kỹ thuật",
}

# Vai trò -> tập quyền. "*" nghĩa là toàn quyền.
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "Admin": {"*"},
    "Quản lý": {
        "dashboard", "appointments", "repair_orders", "customers",
        "vehicles", "services", "inventory", "inventory.view", "inventory.view_all",
        "inventory.view_low_stock", "inventory.view_statistics", "inventory.view_stock_value",
        "inventory.view_transactions", "inventory.recommend_restock", "inventory.manage",
        "invoices", "staff",
        "reports", "invoice.view", "invoice.view_amount", "invoice.view_debt",
        "invoice.view_all", "invoice.calculate", "customer.view", "customer.view_all",
        "vehicle.view", "vehicle.view_all", "customer_vehicle.view", "customer_vehicle.view_all",
        "appointment.view", "appointment.view_all", "appointment.view_status",
        "appointment.view_statistics", "appointment.view_details",
        "appointment.check_availability", "appointment.recommend_reschedule",
        "appointment.reschedule", "appointment.manage",
        "technical_review",
    },
    "Lễ tân": {"dashboard", "appointments", "customers", "vehicles", "services",
                "customer.view", "customer.view_all", "vehicle.view", "vehicle.view_all",
                "customer_vehicle.view", "customer_vehicle.view_all", "appointment.view",
                 "appointment.view_all", "appointment.view_status", "appointment.view_statistics",
                 "appointment.view_details", "appointment.check_availability",
                 "appointment.recommend_reschedule", "appointment.reschedule", "appointment.manage"},
    "Kỹ thuật viên": {"dashboard", "repair_orders", "vehicles", "inventory",
                        "inventory.view", "inventory.view_all", "inventory.view_low_stock",
                        "inventory.view_statistics", "inventory.recommend_restock", "inventory.manage",
                        "vehicle.view", "vehicle.view_all", "technical_review"},
    "Thu ngân": {"dashboard", "invoices", "customers", "vehicles", "invoice.view",
                  "invoice.view_amount", "invoice.view_debt", "invoice.view_all",
                  "invoice.calculate", "customer.view", "customer.view_all", "vehicle.view",
                  "vehicle.view_all", "customer_vehicle.view", "customer_vehicle.view_all"},
    "Khách hàng": {"dashboard", "appointments", "my_vehicles", "invoices",
                    "invoice.view", "invoice.view_amount", "invoice.view_debt",
                    "customer.view", "vehicle.view", "customer_vehicle.view",
                    "appointment.view", "appointment.view_status",
                    "appointment.view_statistics", "appointment.view_details"},
}

# Trang mặc định (điểm đáp) sau khi đăng nhập, theo vai trò.
ROLE_HOME: dict[str, str] = {
    "Admin": "dashboard",
    "Quản lý": "dashboard",
    "Lễ tân": "appointments",
    "Kỹ thuật viên": "repair_orders",
    "Thu ngân": "invoices",
    "Khách hàng": "dashboard",
}


def permissions_for(role: str) -> list[str]:
    """Trả về danh sách quyền (đã sắp xếp) của một vai trò."""
    return sorted(ROLE_PERMISSIONS.get(role, set()))


def has_permission(role: str, permission: str) -> bool:
    """Kiểm tra một vai trò có quyền cụ thể hay không."""
    granted = ROLE_PERMISSIONS.get(role, set())
    return "*" in granted or permission in granted
