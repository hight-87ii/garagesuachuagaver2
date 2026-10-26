"""Hạ tầng dùng chung cho backend GarageAI (core layer).

Bao gồm: cấu hình, xử lý lỗi thống nhất, phân trang, truy cập dữ liệu,
phụ thuộc xác thực/phân quyền, kiểm soát truy cập theo bản ghi (chống IDOR),
ghi nhật ký kiểm toán và cấu hình logging an toàn.
"""
