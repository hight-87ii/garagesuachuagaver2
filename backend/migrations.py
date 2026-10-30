"""Hệ thống migration cho GarageAI.

Mỗi migration là một hàm nhận ``sqlite3.Connection`` và được áp dụng đúng một lần,
được ghi nhận trong bảng ``schema_migrations``. Migration cũ (legacy) được nâng cấp
tại chỗ bằng kỹ thuật "rebuild table" của SQLite: tạo bảng mới theo cấu trúc đích,
sao chép và chuyển đổi dữ liệu, xóa bảng cũ, đổi tên bảng mới.
"""

from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
SCHEMA_SQL = SCHEMA_PATH.read_text(encoding="utf-8")

NOW_SQL = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"


def utc(column: str) -> str:
    """Chuyển một cột thời gian giờ VN (legacy) sang UTC ISO-8601."""
    return (
        f"COALESCE(strftime('%Y-%m-%dT%H:%M:%SZ', NULLIF({column}, ''), '-7 hours'), {NOW_SQL})"
    )


def plate_norm(column: str) -> str:
    return (
        "UPPER(REPLACE(REPLACE(REPLACE(REPLACE("
        f"COALESCE({column}, ''), '-', ''), '.', ''), ' ', ''), '+', ''))"
    )


def table_exists(db, table: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def column_names(db, table: str) -> set[str]:
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}


def extract_create(table: str) -> str:
    """Lấy câu CREATE TABLE của một bảng từ schema.sql."""
    marker = f"CREATE TABLE IF NOT EXISTS {table} ("
    start = SCHEMA_SQL.index(marker)
    end = SCHEMA_SQL.index("\n);", start) + len("\n);")
    return SCHEMA_SQL[start:end]


def add_columns(db, table: str, columns: list[tuple[str, str]]) -> None:
    existing = column_names(db, table)
    for name, definition in columns:
        if name not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def rebuild(db, table: str, expressions: dict[str, str], where: str = "") -> None:
    """Tạo lại bảng theo cấu trúc đích và chuyển dữ liệu theo biểu thức cho trước."""
    target = f"{table}__new"
    create_sql = extract_create(table).replace(
        f"IF NOT EXISTS {table}", target, 1
    )
    db.execute(f"DROP TABLE IF EXISTS {target}")
    db.execute(create_sql)
    columns = list(expressions)
    db.execute(
        f"INSERT INTO {target}({', '.join(columns)}) "
        f"SELECT {', '.join(expressions[c] for c in columns)} FROM {table} {where}"
    )
    db.execute(f"DROP TABLE {table}")
    db.execute(f"ALTER TABLE {target} RENAME TO {table}")


# --------------------------------------------------------------------------------------
# Migration 001 - tạo toàn bộ bảng theo cấu trúc đích
# --------------------------------------------------------------------------------------
def iter_statements(script: str):
    """Tách script SQL thành từng câu lệnh (không dùng executescript vì nó tự COMMIT)."""
    import sqlite3

    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                yield statement
            buffer = ""
    if buffer.strip():
        yield buffer.strip()


def migration_001(db) -> None:
    for statement in iter_statements(SCHEMA_SQL):
        db.execute(statement)


# --------------------------------------------------------------------------------------
# Migration 002 - nâng cấp dữ liệu từ cấu trúc cũ sang cấu trúc đích
# --------------------------------------------------------------------------------------
def migration_002(db) -> None:
    # Bổ sung các cột legacy từng được thêm động trước đây để rebuild đọc được.
    if table_exists(db, "customers"):
        add_columns(db, "customers", [
            ("address", "address TEXT NOT NULL DEFAULT ''"),
            ("note", "note TEXT NOT NULL DEFAULT ''"),
            ("created_at", "created_at TEXT NOT NULL DEFAULT ''"),
        ])
    if table_exists(db, "repair_orders"):
        add_columns(db, "repair_orders", [
            ("priority", "priority TEXT NOT NULL DEFAULT 'Bình thường'"),
            ("km_in", "km_in INTEGER"),
            ("created_at", "created_at TEXT NOT NULL DEFAULT ''"),
        ])

    # 1) Danh mục dịch vụ: service_catalog -> services
    if table_exists(db, "service_catalog"):
        if not db.execute("SELECT 1 FROM services LIMIT 1").fetchone():
            db.execute(
                f"""
                INSERT INTO services(name, category, description, price, duration_min, active, created_at, updated_at)
                SELECT name,
                       COALESCE(NULLIF(category, ''), 'Bảo dưỡng'),
                       COALESCE(description, ''),
                       CAST(ROUND(COALESCE(price, 0)) AS INTEGER),
                       CASE WHEN COALESCE(duration, 0) > 0 THEN duration ELSE 60 END,
                       CASE WHEN COALESCE(active, 1) = 1 THEN 1 ELSE 0 END,
                       {NOW_SQL}, {NOW_SQL}
                FROM service_catalog
                """
            )
        db.execute("DROP TABLE service_catalog")

    # 2) Kho phụ tùng: parts_inventory -> parts
    if table_exists(db, "parts_inventory"):
        if not db.execute("SELECT 1 FROM parts LIMIT 1").fetchone():
            db.execute(
                f"""
                INSERT INTO parts(code, name, category, compatible, unit, cost_price, sell_price,
                                  stock, min_stock, supplier, active, created_at, updated_at)
                SELECT code, name, COALESCE(NULLIF(category, ''), 'Phụ tùng'),
                       COALESCE(compatible, ''), 'cái', 0,
                       CAST(ROUND(COALESCE(unit_price, 0)) AS INTEGER),
                       CAST(COALESCE(stock, 0) AS INTEGER),
                       CAST(COALESCE(min_stock, 3) AS INTEGER),
                       COALESCE(supplier, ''),
                       CASE WHEN COALESCE(active, 1) = 1 THEN 1 ELSE 0 END,
                       {NOW_SQL}, {NOW_SQL}
                FROM parts_inventory
                """
            )
        db.execute("DROP TABLE parts_inventory")

    # 3) users: thêm status/phone/algo, bỏ cờ active
    if "status" not in column_names(db, "users"):
        rebuild(db, "users", {
            "id": "id",
            "full_name": "full_name",
            "email": "email",
            "phone": "NULL",
            "password_hash": "password_hash",
            "password_algo": "'pbkdf2_sha256'",
            "role": "role",
            "status": "CASE WHEN active = 1 THEN 'active' ELSE 'locked' END",
            "created_at": utc("created_at"),
            "updated_at": utc("created_at"),
        })

    # 4) customers
    if "status" not in column_names(db, "customers"):
        rebuild(db, "customers", {
            "id": "id",
            "name": "name",
            "phone": "phone",
            "email": "email",
            "address": "COALESCE(address, '')",
            "note": "COALESCE(note, '')",
            "status": "'active'",
            "created_at": utc("created_at"),
            "updated_at": utc("created_at"),
        })

    # 5) vehicles: thêm plate_normalized/vin/mileage/status
    if "plate_normalized" not in column_names(db, "vehicles"):
        rebuild(db, "vehicles", {
            "id": "id",
            "customer_id": "customer_id",
            "plate": "plate",
            "plate_normalized": plate_norm("plate"),
            "vin": "NULL",
            "make": "make",
            "model": "model",
            "year": "year",
            "color": "NULL",
            "mileage": "NULL",
            "status": "'active'",
            "created_at": f"{NOW_SQL}",
            "updated_at": f"{NOW_SQL}",
        })

    # 6) appointments: gắn vehicle_id/customer_id, chuyển thời gian sang UTC
    if "vehicle_id" not in column_names(db, "appointments"):
        rebuild(db, "appointments", {
            "id": "id",
            "customer_id": (
                "(SELECT v.customer_id FROM vehicles v "
                f"WHERE {plate_norm('v.plate')} = {plate_norm('appointments.plate')} LIMIT 1)"
            ),
            "vehicle_id": (
                "(SELECT v.id FROM vehicles v "
                f"WHERE {plate_norm('v.plate')} = {plate_norm('appointments.plate')} LIMIT 1)"
            ),
            "customer_name": "customer_name",
            "plate": "plate",
            "service": "service",
            "reason": "''",
            "note": "''",
            "appointment_at": utc("appointment_at"),
            "duration_min": "60",
            "status": "status",
            "created_by": "NULL",
            "created_at": f"{NOW_SQL}",
            "updated_at": f"{NOW_SQL}",
        })

    # 7) repair_orders: gắn khóa ngoại xe/khách/kỹ thuật viên
    if "vehicle_id" not in column_names(db, "repair_orders"):
        rebuild(db, "repair_orders", {
            "id": "id",
            "code": "code",
            "customer_id": (
                "(SELECT v.customer_id FROM vehicles v "
                f"WHERE {plate_norm('v.plate')} = {plate_norm('repair_orders.plate')} LIMIT 1)"
            ),
            "vehicle_id": (
                "(SELECT v.id FROM vehicles v "
                f"WHERE {plate_norm('v.plate')} = {plate_norm('repair_orders.plate')} LIMIT 1)"
            ),
            "plate": "plate",
            "customer_name": (
                "COALESCE((SELECT c.name FROM customers c JOIN vehicles v ON v.customer_id = c.id "
                f"WHERE {plate_norm('v.plate')} = {plate_norm('repair_orders.plate')} LIMIT 1), '')"
            ),
            "advisor_id": "NULL",
            "technician_id": (
                "(SELECT u.id FROM users u WHERE u.full_name = repair_orders.technician "
                "AND u.role = 'Kỹ thuật viên' LIMIT 1)"
            ),
            "technician": "technician",
            "status": "status",
            "priority": "COALESCE(NULLIF(priority, ''), 'Bình thường')",
            "km_in": "km_in",
            "note": "COALESCE(note, '')",
            "total": "CAST(ROUND(COALESCE(total, 0)) AS INTEGER)",
            "opened_at": utc("created_at"),
            "closed_at": (
                f"CASE WHEN status IN ('Hoàn thành', 'Đã hủy') THEN {utc('created_at')} ELSE NULL END"
            ),
            "created_at": utc("created_at"),
            "updated_at": utc("created_at"),
        })

    # 8) repair_order_items: thêm liên kết dịch vụ và thành tiền
    if "line_total" not in column_names(db, "repair_order_items"):
        rebuild(db, "repair_order_items", {
            "id": "id",
            "repair_order_id": "repair_order_id",
            "service_id": (
                "(SELECT s.id FROM services s WHERE s.name = repair_order_items.name LIMIT 1)"
            ),
            "kind": "kind",
            "name": "name",
            "quantity": "quantity",
            "unit_price": "CAST(ROUND(COALESCE(unit_price, 0)) AS INTEGER)",
            "line_total": (
                "CAST(ROUND(COALESCE(quantity, 0) * COALESCE(unit_price, 0)) AS INTEGER)"
            ),
            "created_at": f"{NOW_SQL}",
        })

    # 9) invoices: mã hóa đơn, số tiền đã thu
    if "code" not in column_names(db, "invoices"):
        rebuild(db, "invoices", {
            "id": "id",
            "code": "'HD-' || printf('%04d', id)",
            "repair_order_id": "repair_order_id",
            "quote_id": "NULL",
            "subtotal": "CAST(ROUND(COALESCE(subtotal, 0)) AS INTEGER)",
            "discount": "0",
            "tax": "CAST(ROUND(COALESCE(tax, 0)) AS INTEGER)",
            "total": "CAST(ROUND(COALESCE(total, 0)) AS INTEGER)",
            "paid_amount": (
                "CASE status "
                "WHEN 'Đã thanh toán' THEN CAST(ROUND(COALESCE(total, 0)) AS INTEGER) "
                "WHEN 'Thanh toán một phần' THEN CAST(ROUND(COALESCE(total, 0) / 2.0) AS INTEGER) "
                "ELSE 0 END"
            ),
            "status": "status",
            "issued_at": f"{NOW_SQL}",
            "due_at": "NULL",
            "note": "''",
            "created_by": "NULL",
            "created_at": f"{NOW_SQL}",
            "updated_at": f"{NOW_SQL}",
        })

    # 10) repair_history: gắn vehicle_id, chuẩn hóa tiền
    if "vehicle_id" not in column_names(db, "repair_history"):
        rebuild(db, "repair_history", {
            "id": "id",
            "vehicle_id": (
                "(SELECT v.id FROM vehicles v "
                f"WHERE {plate_norm('v.plate')} = {plate_norm('repair_history.plate')} LIMIT 1)"
            ),
            "repair_order_id": "NULL",
            "plate": "plate",
            "repaired_at": "repaired_at",
            "mileage": "mileage",
            "services": "services",
            "note": "COALESCE(note, '')",
            "total": "CAST(ROUND(COALESCE(total, 0)) AS INTEGER)",
            "created_at": f"{NOW_SQL}",
        })


# --------------------------------------------------------------------------------------
# Migration 003 - chỉ mục và ràng buộc bảo vệ dữ liệu
# --------------------------------------------------------------------------------------
INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS ix_users_role ON users(role)",
    "CREATE INDEX IF NOT EXISTS ix_users_status ON users(status)",
    "CREATE INDEX IF NOT EXISTS ix_customers_name ON customers(name)",
    "CREATE INDEX IF NOT EXISTS ix_customers_phone ON customers(phone)",
    "CREATE INDEX IF NOT EXISTS ix_customers_email ON customers(email)",
    "CREATE INDEX IF NOT EXISTS ix_vehicles_plate_norm ON vehicles(plate_normalized)",
    "CREATE INDEX IF NOT EXISTS ix_vehicles_customer ON vehicles(customer_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_vehicles_vin ON vehicles(vin) WHERE vin IS NOT NULL AND vin <> ''",
    "CREATE INDEX IF NOT EXISTS ix_services_category ON services(category)",
    "CREATE INDEX IF NOT EXISTS ix_services_active ON services(active)",
    "CREATE INDEX IF NOT EXISTS ix_parts_category ON parts(category)",
    "CREATE INDEX IF NOT EXISTS ix_parts_name ON parts(name)",
    "CREATE INDEX IF NOT EXISTS ix_parts_stock ON parts(stock)",
    "CREATE INDEX IF NOT EXISTS ix_appointments_at ON appointments(appointment_at)",
    "CREATE INDEX IF NOT EXISTS ix_appointments_status ON appointments(status)",
    "CREATE INDEX IF NOT EXISTS ix_appointments_vehicle ON appointments(vehicle_id)",
    "CREATE INDEX IF NOT EXISTS ix_appointments_customer ON appointments(customer_id)",
    "CREATE INDEX IF NOT EXISTS ix_repair_orders_status ON repair_orders(status)",
    "CREATE INDEX IF NOT EXISTS ix_repair_orders_vehicle ON repair_orders(vehicle_id)",
    "CREATE INDEX IF NOT EXISTS ix_repair_orders_customer ON repair_orders(customer_id)",
    "CREATE INDEX IF NOT EXISTS ix_repair_orders_technician ON repair_orders(technician_id)",
    "CREATE INDEX IF NOT EXISTS ix_repair_orders_plate ON repair_orders(plate)",
    "CREATE INDEX IF NOT EXISTS ix_repair_orders_status_code ON repair_orders(status_code)",
    "CREATE INDEX IF NOT EXISTS ix_repair_order_status_history_order "
    "ON repair_order_status_history(repair_order_id)",
    "CREATE INDEX IF NOT EXISTS ix_repair_order_status_history_created "
    "ON repair_order_status_history(created_at)",
    "CREATE INDEX IF NOT EXISTS ix_repair_order_items_order ON repair_order_items(repair_order_id)",
    "CREATE INDEX IF NOT EXISTS ix_repair_order_items_service ON repair_order_items(service_id)",
    "CREATE INDEX IF NOT EXISTS ix_repair_order_parts_order ON repair_order_parts(repair_order_id)",
    "CREATE INDEX IF NOT EXISTS ix_repair_order_parts_part ON repair_order_parts(part_id)",
    "CREATE INDEX IF NOT EXISTS ix_repair_notes_order ON repair_notes(repair_order_id)",
    "CREATE INDEX IF NOT EXISTS ix_quotes_order ON quotes(repair_order_id)",
    "CREATE INDEX IF NOT EXISTS ix_quotes_status ON quotes(status)",
    "CREATE INDEX IF NOT EXISTS ix_quote_items_quote ON quote_items(quote_id)",
    "CREATE INDEX IF NOT EXISTS ix_invoices_status ON invoices(status)",
    "CREATE INDEX IF NOT EXISTS ix_invoices_order ON invoices(repair_order_id)",
    "CREATE INDEX IF NOT EXISTS ix_invoices_issued ON invoices(issued_at)",
    "CREATE INDEX IF NOT EXISTS ix_payments_invoice ON payments(invoice_id)",
    "CREATE INDEX IF NOT EXISTS ix_payments_paid_at ON payments(paid_at)",
    "CREATE INDEX IF NOT EXISTS ix_repair_history_vehicle ON repair_history(vehicle_id)",
    "CREATE INDEX IF NOT EXISTS ix_repair_history_plate ON repair_history(plate)",
    "CREATE INDEX IF NOT EXISTS ix_repair_history_date ON repair_history(repaired_at)",
    "CREATE INDEX IF NOT EXISTS ix_audit_logs_entity ON audit_logs(entity_type, entity_id)",
    "CREATE INDEX IF NOT EXISTS ix_audit_logs_user ON audit_logs(user_id)",
    "CREATE INDEX IF NOT EXISTS ix_audit_logs_created ON audit_logs(created_at)",
    "CREATE INDEX IF NOT EXISTS ix_ai_interactions_task ON ai_interactions(task_type)",
    "CREATE INDEX IF NOT EXISTS ix_ai_interactions_created ON ai_interactions(created_at)",
]

GUARD_STATEMENTS = [
    # Không xóa cứng dữ liệu tài chính / lịch sử quan trọng.
    """CREATE TRIGGER IF NOT EXISTS trg_invoices_block_delete
       BEFORE DELETE ON invoices
       BEGIN SELECT RAISE(ABORT, 'Không được xóa cứng hóa đơn, hãy chuyển trạng thái Đã hủy'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_payments_block_delete
       BEFORE DELETE ON payments
       BEGIN SELECT RAISE(ABORT, 'Không được xóa cứng giao dịch thanh toán'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_audit_block_delete
       BEFORE DELETE ON audit_logs
       BEGIN SELECT RAISE(ABORT, 'Không được xóa cứng nhật ký hệ thống'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_ai_block_delete
       BEFORE DELETE ON ai_interactions
       BEGIN SELECT RAISE(ABORT, 'Không được xóa cứng nhật ký AI'); END""",
    # Lịch sử trạng thái phiếu là bằng chứng nghiệp vụ: chỉ được ghi thêm.
    """CREATE TRIGGER IF NOT EXISTS trg_order_status_history_block_update
       BEFORE UPDATE ON repair_order_status_history
       BEGIN SELECT RAISE(ABORT, 'Không được sửa lịch sử trạng thái phiếu'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_order_status_history_block_delete
       BEFORE DELETE ON repair_order_status_history
       BEGIN SELECT RAISE(ABORT, 'Không được xóa lịch sử trạng thái phiếu'); END""",
    # Tự động cập nhật updated_at.
    """CREATE TRIGGER IF NOT EXISTS trg_users_touch AFTER UPDATE ON users FOR EACH ROW
       WHEN NEW.updated_at IS OLD.updated_at
       BEGIN UPDATE users SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = OLD.id; END""",
    """CREATE TRIGGER IF NOT EXISTS trg_customers_touch AFTER UPDATE ON customers FOR EACH ROW
       WHEN NEW.updated_at IS OLD.updated_at
       BEGIN UPDATE customers SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = OLD.id; END""",
    """CREATE TRIGGER IF NOT EXISTS trg_vehicles_touch AFTER UPDATE ON vehicles FOR EACH ROW
       WHEN NEW.updated_at IS OLD.updated_at
       BEGIN UPDATE vehicles SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = OLD.id; END""",
    """CREATE TRIGGER IF NOT EXISTS trg_services_touch AFTER UPDATE ON services FOR EACH ROW
       WHEN NEW.updated_at IS OLD.updated_at
       BEGIN UPDATE services SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = OLD.id; END""",
    """CREATE TRIGGER IF NOT EXISTS trg_parts_touch AFTER UPDATE ON parts FOR EACH ROW
       WHEN NEW.updated_at IS OLD.updated_at
       BEGIN UPDATE parts SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = OLD.id; END""",
    """CREATE TRIGGER IF NOT EXISTS trg_appointments_touch AFTER UPDATE ON appointments FOR EACH ROW
       WHEN NEW.updated_at IS OLD.updated_at
       BEGIN UPDATE appointments SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = OLD.id; END""",
    """CREATE TRIGGER IF NOT EXISTS trg_repair_orders_touch AFTER UPDATE ON repair_orders FOR EACH ROW
       WHEN NEW.updated_at IS OLD.updated_at
       BEGIN UPDATE repair_orders SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = OLD.id; END""",
    """CREATE TRIGGER IF NOT EXISTS trg_invoices_touch AFTER UPDATE ON invoices FOR EACH ROW
       WHEN NEW.updated_at IS OLD.updated_at
       BEGIN UPDATE invoices SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = OLD.id; END""",
    """CREATE TRIGGER IF NOT EXISTS trg_quotes_touch AFTER UPDATE ON quotes FOR EACH ROW
       WHEN NEW.updated_at IS OLD.updated_at
       BEGIN UPDATE quotes SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = OLD.id; END""",
]


def migration_003(db) -> None:
    for statement in INDEX_STATEMENTS:
        db.execute(statement)
    for statement in GUARD_STATEMENTS:
        db.execute(statement)


# --------------------------------------------------------------------------------------
# Migration 004 - liên kết lịch sử sửa chữa với phiếu sửa chữa
# --------------------------------------------------------------------------------------
# Mỗi phiếu sửa chữa hoàn thành chỉ sinh tối đa một dòng lịch sử (chống ghi trùng khi
# người dùng bấm "Hoàn thành" nhiều lần).
HISTORY_LINK_STATEMENTS = [
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_repair_history_order "
    "ON repair_history(repair_order_id) WHERE repair_order_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_repair_history_mileage ON repair_history(vehicle_id, mileage)",
]


def migration_004(db) -> None:
    for statement in HISTORY_LINK_STATEMENTS:
        db.execute(statement)


# --------------------------------------------------------------------------------------
# Migration 005 - điều phối lịch hẹn: nguồn lực, kỹ thuật viên, liên kết phiếu tiếp nhận
# --------------------------------------------------------------------------------------
# Nguồn lực là cấu hình tùy chọn: garage chỉ kiểm tra trùng nguồn lực khi có ít nhất
# một nguồn lực đang hoạt động trong bảng ``resources``.
RESOURCE_DEFAULTS = [
    ("KHOANG-1", "Khoang sửa 1", "Khoang sửa", 1, "Khoang tiêu chuẩn cho xe 4 - 7 chỗ"),
    ("KHOANG-2", "Khoang sửa 2", "Khoang sửa", 1, "Khoang gầm, hệ thống phanh"),
    ("CAU-NANG-1", "Cầu nâng 1", "Cầu nâng", 1, "Cầu nâng hai trụ"),
]

APPOINTMENT_SCHEDULING_COLUMNS = [
    ("technician", "technician TEXT NOT NULL DEFAULT ''"),
    (
        "technician_id",
        "technician_id INTEGER REFERENCES users(id) ON UPDATE CASCADE ON DELETE SET NULL",
    ),
    (
        "resource_id",
        "resource_id INTEGER REFERENCES resources(id) ON UPDATE CASCADE ON DELETE SET NULL",
    ),
    (
        "repair_order_id",
        "repair_order_id INTEGER REFERENCES repair_orders(id) "
        "ON UPDATE CASCADE ON DELETE SET NULL",
    ),
    ("confirmed_at", "confirmed_at TEXT"),
    ("cancelled_at", "cancelled_at TEXT"),
    ("cancel_reason", "cancel_reason TEXT NOT NULL DEFAULT ''"),
]

APPOINTMENT_SCHEDULING_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS ix_resources_active ON resources(active)",
    "CREATE INDEX IF NOT EXISTS ix_appointments_technician ON appointments(technician_id)",
    "CREATE INDEX IF NOT EXISTS ix_appointments_resource_at "
    "ON appointments(resource_id, appointment_at)",
    # Một lịch hẹn chỉ gắn với một phiếu tiếp nhận và ngược lại (chống tạo phiếu trùng).
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_appointments_repair_order "
    "ON appointments(repair_order_id) WHERE repair_order_id IS NOT NULL",
]


def migration_005(db) -> None:
    # Tạo bảng nguồn lực trước khi thêm khóa ngoại tham chiếu tới nó.
    if not table_exists(db, "resources"):
        db.execute(extract_create("resources"))
    add_columns(db, "appointments", APPOINTMENT_SCHEDULING_COLUMNS)
    for statement in APPOINTMENT_SCHEDULING_STATEMENTS:
        db.execute(statement)
    if db.execute("SELECT COUNT(*) FROM resources").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO resources(code, name, kind, capacity, note) VALUES(?, ?, ?, ?, ?)",
            RESOURCE_DEFAULTS,
        )


def migration_006(db) -> None:
    """Cho phép nhiều lịch hẹn của cùng một xe trỏ tới một phiếu đang mở.

    Lịch hẹn thứ hai của cùng xe được tiếp nhận vào đúng phiếu đã có
    (``reused_existing``) thay vì tạo phiếu trùng, nên không thể giữ ràng buộc
    unique một-một giữa ``repair_order_id`` và lịch hẹn.
    """
    db.execute("DROP INDEX IF EXISTS ux_appointments_repair_order")
    db.execute(
        "CREATE INDEX IF NOT EXISTS ix_appointments_repair_order "
        "ON appointments(repair_order_id) WHERE repair_order_id IS NOT NULL"
    )


# --------------------------------------------------------------------------------------
# Migration 007 - luồng trạng thái phiếu sửa chữa và lịch sử trạng thái
# --------------------------------------------------------------------------------------
REPAIR_ORDER_WORKFLOW_COLUMNS = [
    ("status_code", "status_code TEXT NOT NULL DEFAULT 'RECEIVED'"),
    ("initial_condition", "initial_condition TEXT NOT NULL DEFAULT ''"),
    ("customer_request", "customer_request TEXT NOT NULL DEFAULT ''"),
    ("inspection_notes", "inspection_notes TEXT NOT NULL DEFAULT ''"),
    ("cancel_reason", "cancel_reason TEXT NOT NULL DEFAULT ''"),
    ("received_at", "received_at TEXT"),
    ("completed_at", "completed_at TEXT"),
    ("delivered_at", "delivered_at TEXT"),
]


def _workflow_status_code_sql(column: str = "status") -> str:
    return (
        "CASE {column} "
        "WHEN 'Tiếp nhận' THEN 'RECEIVED' "
        "WHEN 'Kiểm tra' THEN 'INSPECTING' "
        "WHEN 'Đang kiểm tra' THEN 'INSPECTING' "
        "WHEN 'Đã báo giá' THEN 'QUOTED' "
        "WHEN 'Đã duyệt' THEN 'APPROVED' "
        "WHEN 'Đang sửa' THEN 'IN_PROGRESS' "
        "WHEN 'Chờ phụ tùng' THEN 'WAITING_FOR_PARTS' "
        "WHEN 'Tạm dừng' THEN 'ON_HOLD' "
        "WHEN 'Hoàn thành' THEN 'COMPLETED' "
        "WHEN 'Đã bàn giao' THEN 'DELIVERED' "
        "WHEN 'Đã hủy' THEN 'CANCELLED' "
        "ELSE 'RECEIVED' END"
    ).format(column=column)


def _workflow_status_label_sql(column: str = "status") -> str:
    return (
        "CASE {column} "
        "WHEN 'Kiểm tra' THEN 'Đang kiểm tra' "
        "WHEN 'Tiếp nhận' THEN 'Tiếp nhận' "
        "WHEN 'Đang kiểm tra' THEN 'Đang kiểm tra' "
        "WHEN 'Đã báo giá' THEN 'Đã báo giá' "
        "WHEN 'Đã duyệt' THEN 'Đã duyệt' "
        "WHEN 'Đang sửa' THEN 'Đang sửa' "
        "WHEN 'Chờ phụ tùng' THEN 'Chờ phụ tùng' "
        "WHEN 'Tạm dừng' THEN 'Tạm dừng' "
        "WHEN 'Hoàn thành' THEN 'Hoàn thành' "
        "WHEN 'Đã bàn giao' THEN 'Đã bàn giao' "
        "WHEN 'Đã hủy' THEN 'Đã hủy' "
        "ELSE 'Tiếp nhận' END"
    ).format(column=column)


REPAIR_ORDER_WORKFLOW_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_repair_orders_status ON repair_orders(status)",
    "CREATE INDEX IF NOT EXISTS ix_repair_orders_status_code ON repair_orders(status_code)",
    "CREATE INDEX IF NOT EXISTS ix_repair_orders_vehicle ON repair_orders(vehicle_id)",
    "CREATE INDEX IF NOT EXISTS ix_repair_orders_customer ON repair_orders(customer_id)",
    "CREATE INDEX IF NOT EXISTS ix_repair_orders_technician ON repair_orders(technician_id)",
    "CREATE INDEX IF NOT EXISTS ix_repair_orders_plate ON repair_orders(plate)",
    "CREATE INDEX IF NOT EXISTS ix_repair_order_status_history_order "
    "ON repair_order_status_history(repair_order_id)",
    "CREATE INDEX IF NOT EXISTS ix_repair_order_status_history_created "
    "ON repair_order_status_history(created_at)",
]

REPAIR_ORDER_WORKFLOW_GUARDS = [
    """CREATE TRIGGER IF NOT EXISTS trg_repair_orders_touch AFTER UPDATE ON repair_orders
       FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
       BEGIN UPDATE repair_orders SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
       WHERE id = OLD.id; END""",
    """CREATE TRIGGER IF NOT EXISTS trg_order_status_history_block_update
       BEFORE UPDATE ON repair_order_status_history
       BEGIN SELECT RAISE(ABORT, 'Không được sửa lịch sử trạng thái phiếu'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_order_status_history_block_delete
       BEFORE DELETE ON repair_order_status_history
       BEGIN SELECT RAISE(ABORT, 'Không được xóa lịch sử trạng thái phiếu'); END""",
]


def migration_007(db) -> None:
    """Mở rộng phiếu sửa chữa: trạng thái chuẩn, dữ liệu tiếp nhận và lịch sử."""
    add_columns(db, "repair_orders", REPAIR_ORDER_WORKFLOW_COLUMNS)
    rebuild(db, "repair_orders", {
        "id": "id",
        "code": "code",
        "customer_id": "customer_id",
        "vehicle_id": "vehicle_id",
        "plate": "plate",
        "customer_name": "COALESCE(customer_name, '')",
        "advisor_id": "advisor_id",
        "technician_id": "technician_id",
        "technician": "COALESCE(technician, '')",
        "status": _workflow_status_label_sql("status"),
        "status_code": _workflow_status_code_sql("status"),
        "priority": "COALESCE(NULLIF(priority, ''), 'Bình thường')",
        "km_in": "km_in",
        "note": "COALESCE(note, '')",
        "initial_condition": "COALESCE(NULLIF(initial_condition, ''), note, '')",
        "customer_request": "COALESCE(NULLIF(customer_request, ''), note, '')",
        "inspection_notes": "COALESCE(NULLIF(inspection_notes, ''), note, '')",
        "cancel_reason": "COALESCE(cancel_reason, '')",
        "total": "CAST(ROUND(COALESCE(total, 0)) AS INTEGER)",
        "received_at": "COALESCE(received_at, opened_at)",
        "opened_at": f"COALESCE(opened_at, created_at, {NOW_SQL})",
        "completed_at": (
            "COALESCE(completed_at, CASE WHEN status IN ('Hoàn thành', 'Đã bàn giao') "
            "THEN closed_at END)"
        ),
        "delivered_at": "delivered_at",
        "closed_at": "closed_at",
        "created_at": f"COALESCE(created_at, {NOW_SQL})",
        "updated_at": f"COALESCE(updated_at, {NOW_SQL})",
    })
    if not table_exists(db, "repair_order_status_history"):
        db.execute(extract_create("repair_order_status_history"))

    for statement in REPAIR_ORDER_WORKFLOW_INDEXES:
        db.execute(statement)
    for statement in REPAIR_ORDER_WORKFLOW_GUARDS:
        db.execute(statement)

    # Mỗi phiếu cũ có một dòng lịch sử khởi tạo để UI không hiển thị lịch sử rỗng.
    db.execute(
        """
        INSERT INTO repair_order_status_history
            (repair_order_id, from_status, to_status, note, changed_by, changed_by_name, created_at)
        SELECT r.id, '', COALESCE(NULLIF(r.status_code, ''), 'RECEIVED'), 'Khởi tạo phiếu',
               r.advisor_id,
               COALESCE((SELECT u.full_name FROM users u WHERE u.id = r.advisor_id), ''),
               COALESCE(r.received_at, r.opened_at, r.created_at, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        FROM repair_orders r
        WHERE NOT EXISTS (
            SELECT 1 FROM repair_order_status_history h WHERE h.repair_order_id = r.id
        )
        """
    )


# Migration 008 - sổ giao dịch kho và khóa idempotency
def migration_008(db) -> None:
    """Ghi nhận mọi lần nhập/xuất/hoàn kho bằng khóa duy nhất."""
    if not table_exists(db, "inventory_transactions"):
        db.execute(extract_create("inventory_transactions"))
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_inventory_transactions_key "
        "ON inventory_transactions(idempotency_key) WHERE idempotency_key IS NOT NULL"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS ix_inventory_transactions_part "
        "ON inventory_transactions(part_id, created_at)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS ix_inventory_transactions_order "
        "ON inventory_transactions(repair_order_id, created_at)"
    )


# Migration 009 - báo giá hiệu lực, snapshot hóa đơn và idempotency thanh toán
def migration_009(db) -> None:
    add_columns(db, "quotes", [
        ("tax_rate", "tax_rate REAL NOT NULL DEFAULT 0.08"),
        ("valid_until", "valid_until TEXT"),
    ])
    add_columns(db, "payments", [("idempotency_key", "idempotency_key TEXT")])
    if not table_exists(db, "invoice_items"):
        db.execute(extract_create("invoice_items"))
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_payments_invoice_reference "
        "ON payments(invoice_id, reference_code) WHERE reference_code IS NOT NULL AND reference_code <> ''"
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_payments_idempotency_key "
        "ON payments(idempotency_key) WHERE idempotency_key IS NOT NULL"
    )
    db.execute("CREATE INDEX IF NOT EXISTS ix_invoice_items_invoice ON invoice_items(invoice_id)")


def migration_010(db) -> None:
    if not table_exists(db, "system_settings"):
        db.execute(extract_create("system_settings"))
    db.executemany(
        "INSERT OR IGNORE INTO system_settings(key, value) VALUES(?, ?)",
        [("garage_name", "ThreeH Workshop"), ("garage_phone", ""), ("garage_address", ""),
         ("invoice_prefix", "HD"), ("quote_valid_days", "7")],
    )


def migration_011(db) -> None:
    if not table_exists(db, "user_preferences"):
        db.execute(extract_create("user_preferences"))


def migration_012(db) -> None:
    """Bổ sung snapshot hạng mục cho hóa đơn cũ."""
    db.execute(
        """UPDATE invoices SET quote_id=(SELECT q.id FROM quotes q
           WHERE q.repair_order_id=invoices.repair_order_id AND q.status='Đã duyệt'
           ORDER BY q.version DESC,q.id DESC LIMIT 1)
           WHERE quote_id IS NULL AND EXISTS(SELECT 1 FROM quotes q
           WHERE q.repair_order_id=invoices.repair_order_id AND q.status='Đã duyệt')"""
    )
    db.execute(
        """INSERT INTO invoice_items(invoice_id,quote_item_id,kind,name,quantity,unit_price,line_total)
           SELECT i.id,qi.id,qi.kind,qi.name,qi.quantity,qi.unit_price,qi.line_total
           FROM invoices i JOIN quote_items qi ON qi.quote_id=i.quote_id
           WHERE NOT EXISTS(SELECT 1 FROM invoice_items ii WHERE ii.invoice_id=i.id)"""
    )
    db.execute(
        """INSERT INTO invoice_items(invoice_id,kind,name,quantity,unit_price,line_total)
           SELECT i.id,roi.kind,roi.name,roi.quantity,roi.unit_price,roi.line_total
           FROM invoices i JOIN repair_order_items roi ON roi.repair_order_id=i.repair_order_id
           WHERE i.quote_id IS NULL AND NOT EXISTS(
               SELECT 1 FROM invoice_items ii WHERE ii.invoice_id=i.id)"""
    )
    db.execute(
        """INSERT INTO invoice_items(invoice_id,kind,name,quantity,unit_price,line_total)
           SELECT i.id,'Phụ tùng',rop.name,rop.quantity,rop.unit_price,rop.line_total
           FROM invoices i JOIN repair_order_parts rop ON rop.repair_order_id=i.repair_order_id
           WHERE i.quote_id IS NULL AND NOT EXISTS(
               SELECT 1 FROM invoice_items ii WHERE ii.invoice_id=i.id AND ii.name=rop.name)"""
    )


def migration_013(db) -> None:
    if not table_exists(db, "appointment_part_requests"):
        db.execute(extract_create("appointment_part_requests"))
    db.execute("CREATE INDEX IF NOT EXISTS idx_appointment_part_requests_appointment ON appointment_part_requests(appointment_id)")


def migration_014(db) -> None:
    from .knowledge import install_knowledge_index

    install_knowledge_index(db)


def migration_015(db) -> None:
    """Thuộc tính cấu hình xe và quy tắc tương thích đã được nhân viên kiểm tra."""
    add_columns(db, "vehicles", [
        ("variant", "variant TEXT NOT NULL DEFAULT ''"),
        ("engine_code", "engine_code TEXT NOT NULL DEFAULT ''"),
        ("fuel_type", "fuel_type TEXT NOT NULL DEFAULT ''"),
    ])
    if not table_exists(db, "part_fitments"):
        db.execute(extract_create("part_fitments"))
    db.execute("CREATE INDEX IF NOT EXISTS ix_part_fitments_part ON part_fitments(part_id)")
    db.execute("CREATE INDEX IF NOT EXISTS ix_part_fitments_make_model ON part_fitments(make, model)")


def migration_016(db) -> None:
    """Thêm hình thức ghi nhận quét mã tại quầy; giữ nguyên giao dịch lịch sử."""
    definition = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='payments'").fetchone()[0]
    if "Quét mã cửa hàng" not in definition:
        rebuild(db, "payments", {column: column for column in (
            "id", "invoice_id", "method", "amount", "idempotency_key", "reference_code",
            "paid_at", "received_by", "note", "created_at",
        )})
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_payments_invoice_reference "
               "ON payments(invoice_id, reference_code) WHERE reference_code IS NOT NULL AND reference_code <> ''")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_payments_idempotency_key "
               "ON payments(idempotency_key) WHERE idempotency_key IS NOT NULL")
    db.execute("CREATE INDEX IF NOT EXISTS ix_payments_invoice ON payments(invoice_id)")
    db.execute("CREATE INDEX IF NOT EXISTS ix_payments_paid_at ON payments(paid_at)")


def migration_017(db) -> None:
    """Thời gian thực tế do kỹ thuật viên nhập và snapshot ước tính trên chứng từ."""
    add_columns(db, "repair_order_items", [
        ("actual_duration_min", "actual_duration_min INTEGER CHECK (actual_duration_min IS NULL OR actual_duration_min > 0)"),
    ])
    for table in ("quotes", "invoices"):
        add_columns(db, table, [
            ("estimated_duration_min", "estimated_duration_min INTEGER CHECK (estimated_duration_min IS NULL OR estimated_duration_min > 0)"),
        ])
    for table in ("quote_items", "invoice_items"):
        add_columns(db, table, [
            ("estimated_duration_min", "estimated_duration_min INTEGER CHECK (estimated_duration_min IS NULL OR estimated_duration_min > 0)"),
            ("estimate_source", "estimate_source TEXT CHECK (estimate_source IS NULL OR estimate_source IN ('catalog','history'))"),
        ])


def migration_018(db) -> None:
    """Lưu toàn bộ lịch sử hội thoại theo chủ tài khoản; xóa một hội thoại cascade tin nhắn."""
    for table in ("ai_conversations", "ai_messages"):
        if not table_exists(db, table):
            db.execute(extract_create(table))
    db.execute("CREATE INDEX IF NOT EXISTS ix_ai_conversations_user_updated "
               "ON ai_conversations(user_id, updated_at DESC, id DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS ix_ai_messages_conversation "
               "ON ai_messages(conversation_id, id)")


def migration_019(db) -> None:
    """Phân biệt giao dịch hợp lệ với thất bại, hủy và hoàn tiền."""
    add_columns(db, "payments", [
        ("status", "status TEXT NOT NULL DEFAULT 'completed' "
                   "CHECK (status IN ('completed','failed','voided','refunded'))"),
    ])
    db.execute("CREATE INDEX IF NOT EXISTS ix_payments_status ON payments(status)")


def migration_020(db) -> None:
    """Bài kỹ thuật duyệt thủ công; FTS chỉ lập chỉ mục bài đã xuất bản."""
    db.execute("""CREATE TABLE IF NOT EXISTS technical_articles (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        symptoms TEXT NOT NULL,
        content TEXT NOT NULL,
        safety TEXT NOT NULL DEFAULT '',
        source_name TEXT NOT NULL,
        source_url TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published')),
        created_by INTEGER NOT NULL REFERENCES users(id),
        reviewed_by INTEGER REFERENCES users(id),
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    )""")
    db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS technical_fts USING fts5(
        title, symptoms, content, content='technical_articles', content_rowid='id',
        tokenize='unicode61 remove_diacritics 2'
    )""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS technical_insert AFTER INSERT ON technical_articles
        WHEN new.status='published' BEGIN
        INSERT INTO technical_fts(rowid,title,symptoms,content)
        VALUES(new.id,new.title,new.symptoms,new.content); END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS technical_delete AFTER DELETE ON technical_articles
        WHEN old.status='published' BEGIN
        INSERT INTO technical_fts(technical_fts,rowid,title,symptoms,content)
        VALUES('delete',old.id,old.title,old.symptoms,old.content); END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS technical_update AFTER UPDATE ON technical_articles BEGIN
        INSERT INTO technical_fts(technical_fts,rowid,title,symptoms,content)
        SELECT 'delete',old.id,old.title,old.symptoms,old.content WHERE old.status='published';
        INSERT INTO technical_fts(rowid,title,symptoms,content)
        SELECT new.id,new.title,new.symptoms,new.content WHERE new.status='published'; END""")


def migration_021(db) -> None:
    """Thông số xe áp dụng và dấu vết duyệt kỹ thuật; giữ nguyên bài/người duyệt cũ."""
    add_columns(db, "technical_articles", [
        ("vehicle_make", "vehicle_make TEXT NOT NULL DEFAULT ''"),
        ("vehicle_model", "vehicle_model TEXT NOT NULL DEFAULT ''"),
        ("year_from", "year_from INTEGER CHECK(year_from IS NULL OR year_from BETWEEN 1950 AND 2100)"),
        ("year_to", "year_to INTEGER CHECK(year_to IS NULL OR year_to BETWEEN 1950 AND 2100)"),
        ("engine_code", "engine_code TEXT NOT NULL DEFAULT ''"),
        ("document_version", "document_version TEXT NOT NULL DEFAULT ''"),
        ("technical_reviewed_by", "technical_reviewed_by INTEGER REFERENCES users(id)"),
        ("technical_reviewed_at", "technical_reviewed_at TEXT"),
        ("safety_level", "safety_level TEXT NOT NULL DEFAULT 'medium' "
                         "CHECK(safety_level IN ('low','medium','high','critical'))"),
    ])
    db.execute("CREATE INDEX IF NOT EXISTS ix_technical_applicability "
               "ON technical_articles(status,vehicle_make,vehicle_model,year_from,year_to,engine_code)")
    # Gán mức ban đầu cho bài mẫu; không gán người hoặc ngày duyệt kỹ thuật giả.
    db.execute("""UPDATE technical_articles SET safety_level=CASE
        WHEN source_url LIKE '%car-overheating-8-causes%' THEN 'critical'
        WHEN source_url LIKE '%11-ways-to-know-you-may-need-new-brakes%'
          OR source_url LIKE '%steering-suspension%'
          OR source_url LIKE '%common-suspension-problems%'
          OR source_url LIKE '%vehicle-safety/tires%'
          OR source_url LIKE '%check-engine-light-common-causes%' THEN 'high'
        WHEN source_url LIKE '%car-air-conditioning-repair-troubleshooting%' THEN 'low'
        ELSE 'medium' END
        WHERE reviewed_by IS NULL AND status='published' AND source_url IN (
          'https://www.firestonecompleteautocare.com/repair/steering-suspension',
          'https://www.aaa.com/autorepair/articles/11-ways-to-know-you-may-need-new-brakes',
          'https://www.nhtsa.gov/vehicle-safety/tires',
          'https://www.firestonecompleteautocare.com/blog/maintenance/common-suspension-problems',
          'https://www.firestonecompleteautocare.com/blog/maintenance/car-air-conditioning-repair-troubleshooting',
          'https://www.aaa.com/autorepair/articles/14-reasons-why-your-car-wont-start',
          'https://www.firestonecompleteautocare.com/blog/maintenance/why-is-my-car-shaking/',
          'https://www.aaa.com/autorepair/articles/buying-car/the-check-engine-light-common-causes-and-how-to-fix-it',
          'https://www.aaa.com/autorepair/articles/car-overheating-8-causes-and-solutions')""")


def migration_022(db) -> None:
    """Tệp nguồn và các đoạn RAG tách riêng; FTS chỉ trả khi bài mẹ được xuất bản."""
    db.execute("""CREATE TABLE IF NOT EXISTS technical_documents (
        article_id INTEGER PRIMARY KEY REFERENCES technical_articles(id) ON DELETE CASCADE,
        filename TEXT NOT NULL, mime_type TEXT NOT NULL, sha256 TEXT NOT NULL,
        data BLOB NOT NULL, extracted_text TEXT NOT NULL,
        uploaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS technical_chunks (
        id INTEGER PRIMARY KEY,
        article_id INTEGER NOT NULL REFERENCES technical_articles(id) ON DELETE CASCADE,
        chunk_index INTEGER NOT NULL, content TEXT NOT NULL,
        UNIQUE(article_id,chunk_index)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS ix_technical_chunks_article ON technical_chunks(article_id,chunk_index)")
    db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS technical_chunk_fts USING fts5(
        content, content='technical_chunks', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
    )""")
    for event, body in (
        ("insert", "INSERT INTO technical_chunk_fts(rowid,content) VALUES(new.id,new.content);"),
        ("delete", "INSERT INTO technical_chunk_fts(technical_chunk_fts,rowid,content) VALUES('delete',old.id,old.content);"),
        ("update", "INSERT INTO technical_chunk_fts(technical_chunk_fts,rowid,content) VALUES('delete',old.id,old.content); INSERT INTO technical_chunk_fts(rowid,content) VALUES(new.id,new.content);"),
    ):
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS technical_chunks_{event} AFTER {event.upper()}
            ON technical_chunks BEGIN {body} END""")
    from .technical_documents import index_article_chunks
    for article in db.execute("SELECT id,content FROM technical_articles").fetchall():
        index_article_chunks(db, article["id"], article["content"])


def migration_023(db) -> None:
    """Lập chỉ mục đoạn cho bài nhập trước khi có tính năng tải tài liệu."""
    from .technical_documents import index_article_chunks
    for article in db.execute("""SELECT a.id,a.content FROM technical_articles a
        WHERE NOT EXISTS(SELECT 1 FROM technical_chunks c WHERE c.article_id=a.id)""").fetchall():
        index_article_chunks(db, article["id"], article["content"])


def migration_024(db) -> None:
    """Ca sửa chữa ẩn danh ở trạng thái nháp; không tự đưa hồ sơ khách vào RAG."""
    db.execute("""CREATE TABLE IF NOT EXISTS repair_knowledge_cases (
        id INTEGER PRIMARY KEY,
        repair_order_id INTEGER NOT NULL UNIQUE REFERENCES repair_orders(id) ON DELETE CASCADE,
        vehicle_id INTEGER REFERENCES vehicles(id) ON DELETE SET NULL,
        vehicle_make TEXT NOT NULL DEFAULT '', vehicle_model TEXT NOT NULL DEFAULT '',
        vehicle_year INTEGER, engine_code TEXT NOT NULL DEFAULT '',
        customer_symptoms TEXT NOT NULL DEFAULT '', inspection_findings TEXT NOT NULL DEFAULT '',
        confirmed_cause TEXT NOT NULL DEFAULT '', work_done TEXT NOT NULL DEFAULT '',
        outcome TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published')),
        technician_reviewed_by INTEGER REFERENCES users(id), technician_reviewed_at TEXT,
        published_by INTEGER REFERENCES users(id), published_at TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS ix_repair_cases_vehicle "
               "ON repair_knowledge_cases(status,vehicle_make,vehicle_model,vehicle_year,engine_code)")
    db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS repair_case_fts USING fts5(
        customer_symptoms,inspection_findings,confirmed_cause,work_done,outcome,
        content='repair_knowledge_cases',content_rowid='id',tokenize='unicode61 remove_diacritics 2'
    )""")
    fields = "customer_symptoms,inspection_findings,confirmed_cause,work_done,outcome"
    db.execute(f"""CREATE TRIGGER IF NOT EXISTS case_insert AFTER INSERT ON repair_knowledge_cases
        WHEN new.status='published' BEGIN INSERT INTO repair_case_fts(rowid,{fields})
        VALUES(new.id,new.customer_symptoms,new.inspection_findings,new.confirmed_cause,new.work_done,new.outcome); END""")
    db.execute(f"""CREATE TRIGGER IF NOT EXISTS case_delete AFTER DELETE ON repair_knowledge_cases
        WHEN old.status='published' BEGIN INSERT INTO repair_case_fts(repair_case_fts,rowid,{fields})
        VALUES('delete',old.id,old.customer_symptoms,old.inspection_findings,old.confirmed_cause,old.work_done,old.outcome); END""")
    db.execute(f"""CREATE TRIGGER IF NOT EXISTS case_update AFTER UPDATE ON repair_knowledge_cases BEGIN
        INSERT INTO repair_case_fts(repair_case_fts,rowid,{fields})
        SELECT 'delete',old.id,old.customer_symptoms,old.inspection_findings,old.confirmed_cause,old.work_done,old.outcome
        WHERE old.status='published';
        INSERT INTO repair_case_fts(rowid,{fields})
        SELECT new.id,new.customer_symptoms,new.inspection_findings,new.confirmed_cause,new.work_done,new.outcome
        WHERE new.status='published'; END""")
    from .repair_knowledge import capture_completed_case
    for row in db.execute("""SELECT id FROM repair_orders
        WHERE status_code IN ('COMPLETED','DELIVERED') AND vehicle_id IS NOT NULL""").fetchall():
        capture_completed_case(db, row["id"])


def migration_025(db) -> None:
    """Lịch sử bất biến và phiên bản cho quy trình duyệt bài kỹ thuật."""
    add_columns(db, "technical_articles", [
        ("revision", "revision INTEGER NOT NULL DEFAULT 1"),
        ("deleted_at", "deleted_at TEXT"),
        ("withdrawn_at", "withdrawn_at TEXT"),
    ])
    db.execute("""CREATE TABLE IF NOT EXISTS technical_article_history (
        id INTEGER PRIMARY KEY, article_id INTEGER NOT NULL REFERENCES technical_articles(id),
        revision INTEGER NOT NULL, action TEXT NOT NULL, actor_id INTEGER REFERENCES users(id),
        reason TEXT NOT NULL DEFAULT '', snapshot TEXT NOT NULL,
        document_filename TEXT, document_mime TEXT, document_sha256 TEXT, document_data BLOB,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS ix_technical_history_article ON technical_article_history(article_id,id DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS ix_technical_articles_list ON technical_articles(deleted_at,status,updated_at DESC)")


def migration_026(db) -> None:
    """Vector cục bộ, tách khỏi chỉ mục FTS và dữ liệu tài liệu gốc."""
    db.execute("""CREATE TABLE IF NOT EXISTS knowledge_vectors (
        model TEXT NOT NULL, source_type TEXT NOT NULL
            CHECK(source_type IN ('technical_chunk','repair_case')),
        source_id INTEGER NOT NULL, content_hash TEXT NOT NULL,
        dimensions INTEGER NOT NULL CHECK(dimensions > 0), embedding BLOB NOT NULL,
        indexed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        PRIMARY KEY(model,source_type,source_id)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_vectors_source ON knowledge_vectors(source_type,source_id)")
    # Thu hồi và thay nội dung phải vô hiệu hóa vector ngay, không đợi lần chạy index tiếp theo.
    db.execute("""CREATE TRIGGER IF NOT EXISTS vectors_article_update AFTER UPDATE ON technical_articles
        BEGIN DELETE FROM knowledge_vectors WHERE source_type='technical_chunk' AND source_id IN
            (SELECT id FROM technical_chunks WHERE article_id=old.id); END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS vectors_article_delete BEFORE DELETE ON technical_articles
        BEGIN DELETE FROM knowledge_vectors WHERE source_type='technical_chunk' AND source_id IN
            (SELECT id FROM technical_chunks WHERE article_id=old.id); END""")
    for event in ("UPDATE", "DELETE"):
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS vectors_chunk_{event.lower()} BEFORE {event} ON technical_chunks
            BEGIN DELETE FROM knowledge_vectors WHERE source_type='technical_chunk' AND source_id=old.id; END""")
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS vectors_case_{event.lower()} BEFORE {event} ON repair_knowledge_cases
            BEGIN DELETE FROM knowledge_vectors WHERE source_type='repair_case' AND source_id=old.id; END""")


def migration_027(db) -> None:
    """Explicit approval for a catalog selling price; legacy prices stay unapproved.

    A changed parts.sell_price never matches the approved snapshot and must be
    reviewed again. No existing price or stock is modified by this migration.
    """
    db.execute("""CREATE TABLE IF NOT EXISTS part_price_approvals (
        part_id INTEGER PRIMARY KEY REFERENCES parts(id) ON DELETE CASCADE,
        approved_sell_price INTEGER NOT NULL CHECK(approved_sell_price > 0),
        approved_by INTEGER NOT NULL REFERENCES users(id),
        source TEXT NOT NULL CHECK(length(trim(source)) > 0),
        approved_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    )""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS part_price_approval_invalidate
        AFTER UPDATE OF sell_price ON parts
        WHEN new.sell_price IS NOT old.sell_price
        BEGIN DELETE FROM part_price_approvals WHERE part_id=new.id; END""")


def migration_028(db) -> None:
    """Optional owner-facing vehicle profile; no technical values are inferred or backfilled."""
    db.execute("""CREATE TABLE IF NOT EXISTS vehicle_profiles (
        vehicle_id INTEGER PRIMARY KEY REFERENCES vehicles(id) ON DELETE CASCADE,
        first_registration_year INTEGER CHECK(first_registration_year BETWEEN 1900 AND 2100),
        vehicle_type TEXT, seat_count INTEGER CHECK(seat_count BETWEEN 1 AND 60),
        door_count INTEGER CHECK(door_count BETWEEN 1 AND 10),
        transmission TEXT, drivetrain TEXT, displacement_cc INTEGER CHECK(displacement_cc > 0),
        power_kw REAL CHECK(power_kw > 0), torque_nm REAL CHECK(torque_nm > 0),
        fuel_consumption TEXT, fuel_tank_liters REAL CHECK(fuel_tank_liters > 0),
        tire_size TEXT, tire_pressure TEXT, oil_capacity_liters REAL CHECK(oil_capacity_liters > 0),
        oil_spec TEXT, registration_info TEXT,
        inspection_expires_at TEXT, liability_insurance_expires_at TEXT,
        comprehensive_insurance_expires_at TEXT,
        mileage_updated_at TEXT,
        next_service_at TEXT, next_service_mileage INTEGER CHECK(next_service_mileage >= 0),
        maintenance_source TEXT, maintenance_items TEXT,
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    )""")


def migration_029(db) -> None:
    """Preserve all historical documents and odometer readings, including demo records."""
    add_columns(db, "vehicle_profiles", [("maintenance_items", "maintenance_items TEXT")])


def migration_030(db) -> None:
    """Store the engine serial separately from the engine model/code."""
    add_columns(db, "vehicle_profiles", [("engine_number", "engine_number TEXT")])


def migration_031(db) -> None:
    """Keep catalogue limitations explicit instead of overloading compatibility text."""
    add_columns(db, "parts", [
        ("compatibility_accuracy", "compatibility_accuracy TEXT NOT NULL DEFAULT ''"),
        ("usage_requirements", "usage_requirements TEXT NOT NULL DEFAULT ''"),
        ("price_note", "price_note TEXT NOT NULL DEFAULT ''"),
        ("supplier_note", "supplier_note TEXT NOT NULL DEFAULT ''"),
    ])


def migration_032(db) -> None:
    """Hybrid part knowledge: technical text is searchable; live business fields stay in DB."""
    add_columns(db, "parts", [
        ("technical_description", "technical_description TEXT NOT NULL DEFAULT ''"),
        ("technical_specs", "technical_specs TEXT NOT NULL DEFAULT ''"),
        ("usage_instructions", "usage_instructions TEXT NOT NULL DEFAULT ''"),
    ])
    # SQLite cannot alter the source_type CHECK constraint in place.
    for trigger in ("vectors_article_update", "vectors_article_delete",
                    "vectors_chunk_update", "vectors_chunk_delete",
                    "vectors_case_update", "vectors_case_delete"):
        db.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    db.execute("ALTER TABLE knowledge_vectors RENAME TO knowledge_vectors_v1")
    db.execute("""CREATE TABLE knowledge_vectors (
        model TEXT NOT NULL, source_type TEXT NOT NULL
            CHECK(source_type IN ('technical_chunk','repair_case','part_catalog')),
        source_id INTEGER NOT NULL, content_hash TEXT NOT NULL,
        dimensions INTEGER NOT NULL CHECK(dimensions > 0), embedding BLOB NOT NULL,
        indexed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        PRIMARY KEY(model,source_type,source_id)
    )""")
    db.execute("""INSERT INTO knowledge_vectors(model,source_type,source_id,content_hash,
        dimensions,embedding,indexed_at) SELECT model,source_type,source_id,content_hash,
        dimensions,embedding,indexed_at FROM knowledge_vectors_v1""")
    db.execute("DROP TABLE knowledge_vectors_v1")
    db.execute("CREATE INDEX ix_knowledge_vectors_source ON knowledge_vectors(source_type,source_id)")
    db.execute("""CREATE TABLE part_knowledge_documents (
        part_id INTEGER PRIMARY KEY REFERENCES parts(id) ON DELETE CASCADE,
        content TEXT NOT NULL, content_hash TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    )""")
    db.execute("""CREATE VIRTUAL TABLE part_knowledge_fts USING fts5(
        content, content='part_knowledge_documents', content_rowid='part_id',
        tokenize='unicode61 remove_diacritics 2')""")
    db.execute("""CREATE TRIGGER part_knowledge_fts_insert AFTER INSERT ON part_knowledge_documents
        BEGIN INSERT INTO part_knowledge_fts(rowid,content) VALUES(new.part_id,new.content); END""")
    db.execute("""CREATE TRIGGER part_knowledge_fts_delete AFTER DELETE ON part_knowledge_documents
        BEGIN INSERT INTO part_knowledge_fts(part_knowledge_fts,rowid,content)
             VALUES('delete',old.part_id,old.content); END""")
    db.execute("""CREATE TRIGGER part_knowledge_fts_update AFTER UPDATE ON part_knowledge_documents
        BEGIN INSERT INTO part_knowledge_fts(part_knowledge_fts,rowid,content)
             VALUES('delete',old.part_id,old.content);
             INSERT INTO part_knowledge_fts(rowid,content) VALUES(new.part_id,new.content); END""")
    db.execute("""CREATE TABLE part_knowledge_index_jobs (
        part_id INTEGER PRIMARY KEY REFERENCES parts(id) ON DELETE CASCADE,
        content_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending'
            CHECK(status IN ('pending','processing','completed','failed')),
        attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    )""")
    # Backfill lexical documents only; embeddings remain incremental pending jobs.
    db.execute("""INSERT INTO part_knowledge_documents(part_id,content,content_hash)
        SELECT id,
          'Mã phụ tùng: '||code||'. Tên phụ tùng: '||name||
          CASE WHEN trim(category)<>'' THEN '. Nhóm: '||category ELSE '' END||
          CASE WHEN trim(technical_description)<>'' THEN '. Mô tả kỹ thuật: '||technical_description ELSE '' END||
          CASE WHEN trim(technical_specs)<>'' THEN '. Thông số kỹ thuật: '||technical_specs ELSE '' END||
          CASE WHEN trim(usage_instructions)<>'' THEN '. Hướng dẫn sử dụng: '||usage_instructions ELSE '' END||
          CASE WHEN trim(usage_requirements)<>'' THEN '. Yêu cầu sử dụng: '||usage_requirements ELSE '' END,
          lower(hex(randomblob(32)))
        FROM parts WHERE active=1""")
    db.execute("""INSERT INTO part_knowledge_index_jobs(part_id,content_hash,status)
        SELECT part_id,content_hash,'pending' FROM part_knowledge_documents""")
    db.execute("""CREATE TRIGGER vectors_article_update AFTER UPDATE ON technical_articles
        BEGIN DELETE FROM knowledge_vectors WHERE source_type='technical_chunk' AND source_id IN
            (SELECT id FROM technical_chunks WHERE article_id=old.id); END""")
    db.execute("""CREATE TRIGGER vectors_article_delete BEFORE DELETE ON technical_articles
        BEGIN DELETE FROM knowledge_vectors WHERE source_type='technical_chunk' AND source_id IN
            (SELECT id FROM technical_chunks WHERE article_id=old.id); END""")
    for event in ("UPDATE", "DELETE"):
        db.execute(f"""CREATE TRIGGER vectors_chunk_{event.lower()} BEFORE {event} ON technical_chunks
            BEGIN DELETE FROM knowledge_vectors WHERE source_type='technical_chunk' AND source_id=old.id; END""")
        db.execute(f"""CREATE TRIGGER vectors_case_{event.lower()} BEFORE {event} ON repair_knowledge_cases
            BEGIN DELETE FROM knowledge_vectors WHERE source_type='repair_case' AND source_id=old.id; END""")
    db.execute("""CREATE TRIGGER vectors_part_deactivate AFTER UPDATE OF active ON parts
        WHEN new.active=0 BEGIN
          DELETE FROM knowledge_vectors WHERE source_type='part_catalog' AND source_id=new.id;
          DELETE FROM part_knowledge_documents WHERE part_id=new.id;
          DELETE FROM part_knowledge_index_jobs WHERE part_id=new.id;
        END""")
    db.execute("""CREATE TRIGGER vectors_part_technical_update AFTER UPDATE OF
        code,name,category,technical_description,technical_specs,usage_instructions,usage_requirements
        ON parts WHEN old.code IS NOT new.code OR old.name IS NOT new.name OR
          old.category IS NOT new.category OR old.technical_description IS NOT new.technical_description OR
          old.technical_specs IS NOT new.technical_specs OR
          old.usage_instructions IS NOT new.usage_instructions OR
          old.usage_requirements IS NOT new.usage_requirements BEGIN
          DELETE FROM knowledge_vectors WHERE source_type='part_catalog' AND source_id=new.id;
        END""")
    db.execute("""CREATE TRIGGER vectors_part_delete BEFORE DELETE ON parts BEGIN
          DELETE FROM knowledge_vectors WHERE source_type='part_catalog' AND source_id=old.id;
          DELETE FROM part_knowledge_documents WHERE part_id=old.id;
          DELETE FROM part_knowledge_index_jobs WHERE part_id=old.id;
        END""")


def migration_033(db) -> None:
    """Chu kỳ bảo dưỡng có cấu trúc; chỉ bản ghi approved gắn bài published mới dùng."""
    db.execute("""CREATE TABLE IF NOT EXISTS maintenance_intervals (
        id INTEGER PRIMARY KEY,
        service_type TEXT NOT NULL DEFAULT 'engine_oil'
            CHECK(service_type IN ('engine_oil')),
        vehicle_make TEXT NOT NULL,
        vehicle_model TEXT NOT NULL,
        year_from INTEGER CHECK(year_from IS NULL OR year_from BETWEEN 1950 AND 2100),
        year_to INTEGER CHECK(year_to IS NULL OR year_to BETWEEN 1950 AND 2100),
        engine_code TEXT NOT NULL DEFAULT '',
        market TEXT NOT NULL DEFAULT '',
        interval_km INTEGER CHECK(interval_km IS NULL OR interval_km > 0),
        interval_months INTEGER CHECK(interval_months IS NULL OR interval_months > 0),
        severe_interval_km INTEGER CHECK(severe_interval_km IS NULL OR severe_interval_km > 0),
        severe_interval_months INTEGER
            CHECK(severe_interval_months IS NULL OR severe_interval_months > 0),
        conditions_note TEXT NOT NULL DEFAULT '',
        oil_spec TEXT NOT NULL DEFAULT '',
        source_name TEXT NOT NULL,
        source_url TEXT NOT NULL DEFAULT '',
        document_version TEXT NOT NULL DEFAULT '',
        article_id INTEGER REFERENCES technical_articles(id) ON DELETE SET NULL,
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK(status IN ('pending','approved','retired')),
        approved_by INTEGER REFERENCES users(id),
        approved_at TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        UNIQUE(service_type,vehicle_make,vehicle_model,year_from,year_to,engine_code,market)
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS ix_maintenance_intervals_lookup
        ON maintenance_intervals(status,service_type,vehicle_make,vehicle_model,
                                 year_from,year_to,engine_code)""")


def migration_034(db) -> None:
    """Bổ sung danh mục phụ tùng chuẩn và bảng tra cứu fitment chi tiết cho các dòng xe phổ biến."""
    from .popular_vehicle_fitments import seed_popular_vehicle_fitments

    seed_popular_vehicle_fitments(db)


MIGRATIONS = [
    (1, "001_initial_schema", migration_001),
    (2, "002_upgrade_legacy_core", migration_002),
    (3, "003_indexes_and_guards", migration_003),
    (4, "004_vehicle_history_link", migration_004),
    (5, "005_appointment_scheduling", migration_005),
    (6, "006_appointment_reuse_order", migration_006),
    (7, "007_repair_order_workflow", migration_007),
    (8, "008_inventory_transactions", migration_008),
    (9, "009_quote_invoice_payment_integrity", migration_009),
    (10, "010_system_settings", migration_010),
    (11, "011_user_preferences", migration_011),
    (12, "012_invoice_item_backfill", migration_012),
    (13, "013_appointment_part_requests", migration_013),
    (14, "014_knowledge_fts", migration_014),
    (15, "015_vehicle_specs_and_part_fitments", migration_015),
    (16, "016_counter_qr_payment", migration_016),
    (17, "017_service_time_snapshots", migration_017),
    (18, "018_ai_conversations", migration_018),
    (19, "019_payment_lifecycle", migration_019),
    (20, "020_technical_articles", migration_020),
    (21, "021_technical_applicability_and_review", migration_021),
    (22, "022_technical_documents_and_chunks", migration_022),
    (23, "023_technical_article_chunk_backfill", migration_023),
    (24, "024_repair_knowledge_cases", migration_024),
    (25, "025_technical_article_revisions", migration_025),
    (26, "026_local_knowledge_vectors", migration_026),
    (27, "027_part_price_approvals", migration_027),
    (28, "028_vehicle_profiles", migration_028),
    (29, "029_repair_demo_vehicle_history", migration_029),
    (30, "030_vehicle_engine_number", migration_030),
    (31, "031_part_data_notes", migration_031),
    (32, "032_hybrid_part_knowledge", migration_032),
    (33, "033_maintenance_intervals", migration_033),
    (34, "034_popular_vehicle_part_fitments", migration_034),
]


def run_migrations(db) -> list[str]:
    """Áp dụng mọi migration chưa chạy. Trả về danh sách migration đã áp dụng."""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
        """
    )
    applied = {row[0] for row in db.execute("SELECT version FROM schema_migrations").fetchall()}
    executed: list[str] = []
    for version, name, migrate in MIGRATIONS:
        if version in applied:
            continue
        db.execute("PRAGMA foreign_keys = OFF")
        db.execute("BEGIN")
        try:
            migrate(db)
            db.execute(
                "INSERT INTO schema_migrations(version, name) VALUES(?, ?)", (version, name)
            )
            db.execute("COMMIT")
        except Exception:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.execute("PRAGMA foreign_keys = ON")
        executed.append(name)
    return executed
