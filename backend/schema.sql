-- GarageAI - sơ đồ cơ sở dữ liệu đích (SQLite)
-- Quy ước:
--   * Tiền tệ: INTEGER đồng (VND), có CHECK >= 0, không dùng floating-point.
--   * Thời gian: TEXT ISO-8601 UTC 'YYYY-MM-DDTHH:MM:SSZ', hiển thị theo giờ VN (UTC+7).
--   * Khóa chính: INTEGER PRIMARY KEY AUTOINCREMENT.
--   * Xóa mềm: cột status/deleted_at thay cho xóa cứng với dữ liệu quan trọng.

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT,
    password_hash TEXT NOT NULL,
    password_algo TEXT NOT NULL DEFAULT 'pbkdf2_sha256',
    role TEXT NOT NULL DEFAULT 'Lễ tân'
        CHECK (role IN ('Admin', 'Quản lý', 'Lễ tân', 'Kỹ thuật viên', 'Thu ngân', 'Khách hàng')),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'locked', 'disabled')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT,
    address TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'archived')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL
        REFERENCES customers(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    plate TEXT NOT NULL,
    plate_normalized TEXT NOT NULL,
    vin TEXT,
    make TEXT NOT NULL,
    model TEXT NOT NULL,
    year INTEGER CHECK (year IS NULL OR (year BETWEEN 1900 AND 2100)),
    variant TEXT NOT NULL DEFAULT '',
    engine_code TEXT NOT NULL DEFAULT '',
    fuel_type TEXT NOT NULL DEFAULT '',
    color TEXT,
    mileage INTEGER CHECK (mileage IS NULL OR mileage >= 0),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'archived')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL DEFAULT 'Bảo dưỡng',
    description TEXT NOT NULL DEFAULT '',
    price INTEGER NOT NULL DEFAULT 0 CHECK (price >= 0),
    duration_min INTEGER NOT NULL DEFAULT 60 CHECK (duration_min > 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'Phụ tùng',
    compatible TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT 'cái',
    cost_price INTEGER NOT NULL DEFAULT 0 CHECK (cost_price >= 0),
    sell_price INTEGER NOT NULL DEFAULT 0 CHECK (sell_price >= 0),
    stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    min_stock INTEGER NOT NULL DEFAULT 3 CHECK (min_stock >= 0),
    supplier TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Quy tắc lắp vừa được nhân viên xác nhận theo mã phụ tùng; dữ liệu compatible cũ
-- chỉ là mô tả gợi ý và không được tự động chuyển thành quy tắc đã xác nhận.
CREATE TABLE IF NOT EXISTS part_fitments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    make TEXT NOT NULL,
    model TEXT NOT NULL,
    year_from INTEGER CHECK (year_from IS NULL OR year_from BETWEEN 1900 AND 2100),
    year_to INTEGER CHECK (year_to IS NULL OR year_to BETWEEN 1900 AND 2100),
    variant TEXT NOT NULL DEFAULT '',
    engine_code TEXT NOT NULL DEFAULT '',
    fuel_type TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    CHECK (year_from IS NULL OR year_to IS NULL OR year_from <= year_to)
);

CREATE TABLE IF NOT EXISTS inventory_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT UNIQUE,
    operation TEXT NOT NULL CHECK (operation IN ('STOCK_IN', 'CONSUME', 'REVERSE')),
    part_id INTEGER NOT NULL REFERENCES parts(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    repair_order_id INTEGER REFERENCES repair_orders(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    repair_order_part_id INTEGER REFERENCES repair_order_parts(id) ON UPDATE CASCADE ON DELETE SET NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    stock_after INTEGER NOT NULL CHECK (stock_after >= 0),
    created_by INTEGER REFERENCES users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Nguồn lực của garage (khoang sửa, cầu nâng, phòng dịch vụ...). Khi có ít nhất
-- một nguồn lực đang hoạt động, hệ thống kiểm tra trùng lịch theo nguồn lực.
CREATE TABLE IF NOT EXISTS resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'Khoang sửa'
        CHECK (kind IN ('Khoang sửa', 'Cầu nâng', 'Phòng dịch vụ', 'Thiết bị')),
    capacity INTEGER NOT NULL DEFAULT 1 CHECK (capacity > 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER REFERENCES customers(id) ON UPDATE CASCADE ON DELETE SET NULL,
    vehicle_id INTEGER REFERENCES vehicles(id) ON UPDATE CASCADE ON DELETE SET NULL,
    customer_name TEXT NOT NULL,
    plate TEXT NOT NULL,
    service TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    appointment_at TEXT NOT NULL,
    duration_min INTEGER NOT NULL DEFAULT 60 CHECK (duration_min > 0),
    status TEXT NOT NULL DEFAULT 'Đang chờ'
        CHECK (status IN ('Đang chờ', 'Đã xác nhận', 'Đã tiếp nhận', 'Đã hủy')),
    technician TEXT NOT NULL DEFAULT '',
    technician_id INTEGER REFERENCES users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    resource_id INTEGER REFERENCES resources(id) ON UPDATE CASCADE ON DELETE SET NULL,
    repair_order_id INTEGER REFERENCES repair_orders(id) ON UPDATE CASCADE ON DELETE SET NULL,
    confirmed_at TEXT,
    cancelled_at TEXT,
    cancel_reason TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS appointment_part_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    appointment_id INTEGER NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
    part_id INTEGER REFERENCES parts(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity BETWEEN 1 AND 20),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS repair_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    customer_id INTEGER REFERENCES customers(id) ON UPDATE CASCADE ON DELETE SET NULL,
    vehicle_id INTEGER REFERENCES vehicles(id) ON UPDATE CASCADE ON DELETE SET NULL,
    plate TEXT NOT NULL,
    customer_name TEXT NOT NULL DEFAULT '',
    advisor_id INTEGER REFERENCES users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    technician_id INTEGER REFERENCES users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    technician TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'Tiếp nhận'
        CHECK (status IN (
            'Tiếp nhận', 'Đang kiểm tra', 'Đã báo giá', 'Đã duyệt', 'Đang sửa',
            'Chờ phụ tùng', 'Tạm dừng', 'Hoàn thành', 'Đã bàn giao', 'Đã hủy'
        )),
    status_code TEXT NOT NULL DEFAULT 'RECEIVED'
        CHECK (status_code IN (
            'RECEIVED', 'INSPECTING', 'QUOTED', 'APPROVED', 'IN_PROGRESS',
            'WAITING_FOR_PARTS', 'ON_HOLD', 'COMPLETED', 'DELIVERED', 'CANCELLED'
        )),
    priority TEXT NOT NULL DEFAULT 'Bình thường'
        CHECK (priority IN ('Thấp', 'Bình thường', 'Cao', 'Gấp')),
    km_in INTEGER CHECK (km_in IS NULL OR km_in >= 0),
    note TEXT NOT NULL DEFAULT '',
    initial_condition TEXT NOT NULL DEFAULT '',
    customer_request TEXT NOT NULL DEFAULT '',
    inspection_notes TEXT NOT NULL DEFAULT '',
    cancel_reason TEXT NOT NULL DEFAULT '',
    total INTEGER NOT NULL DEFAULT 0 CHECK (total >= 0),
    received_at TEXT,
    opened_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at TEXT,
    delivered_at TEXT,
    closed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS repair_order_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repair_order_id INTEGER NOT NULL
        REFERENCES repair_orders(id) ON UPDATE CASCADE ON DELETE CASCADE,
    from_status TEXT NOT NULL DEFAULT '',
    to_status TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    changed_by INTEGER REFERENCES users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    changed_by_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS repair_order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repair_order_id INTEGER NOT NULL
        REFERENCES repair_orders(id) ON UPDATE CASCADE ON DELETE CASCADE,
    service_id INTEGER REFERENCES services(id) ON UPDATE CASCADE ON DELETE SET NULL,
    kind TEXT NOT NULL DEFAULT 'Dịch vụ' CHECK (kind IN ('Dịch vụ', 'Phụ tùng')),
    name TEXT NOT NULL,
    quantity NUMERIC NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit_price INTEGER NOT NULL DEFAULT 0 CHECK (unit_price >= 0),
    line_total INTEGER NOT NULL DEFAULT 0 CHECK (line_total >= 0),
    actual_duration_min INTEGER CHECK (actual_duration_min IS NULL OR actual_duration_min > 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS repair_order_parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repair_order_id INTEGER NOT NULL
        REFERENCES repair_orders(id) ON UPDATE CASCADE ON DELETE CASCADE,
    part_id INTEGER NOT NULL REFERENCES parts(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    name TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit_price INTEGER NOT NULL DEFAULT 0 CHECK (unit_price >= 0),
    line_total INTEGER NOT NULL DEFAULT 0 CHECK (line_total >= 0),
    created_by INTEGER REFERENCES users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS repair_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repair_order_id INTEGER NOT NULL
        REFERENCES repair_orders(id) ON UPDATE CASCADE ON DELETE CASCADE,
    author_id INTEGER REFERENCES users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    author_name TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    repair_order_id INTEGER NOT NULL
        REFERENCES repair_orders(id) ON UPDATE CASCADE ON DELETE CASCADE,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    status TEXT NOT NULL DEFAULT 'Nháp'
        CHECK (status IN ('Nháp', 'Chờ duyệt', 'Đã duyệt', 'Từ chối', 'Hết hiệu lực')),
    subtotal INTEGER NOT NULL DEFAULT 0 CHECK (subtotal >= 0),
    discount INTEGER NOT NULL DEFAULT 0 CHECK (discount >= 0),
    tax INTEGER NOT NULL DEFAULT 0 CHECK (tax >= 0),
    total INTEGER NOT NULL DEFAULT 0 CHECK (total >= 0),
    estimated_duration_min INTEGER CHECK (estimated_duration_min IS NULL OR estimated_duration_min > 0),
    tax_rate REAL NOT NULL DEFAULT 0.08 CHECK (tax_rate >= 0 AND tax_rate <= 1),
    valid_until TEXT,
    note TEXT NOT NULL DEFAULT '',
    approved_by INTEGER REFERENCES users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    approved_at TEXT,
    created_by INTEGER REFERENCES users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (repair_order_id, version)
);

CREATE TABLE IF NOT EXISTS quote_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_id INTEGER NOT NULL REFERENCES quotes(id) ON UPDATE CASCADE ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'Dịch vụ' CHECK (kind IN ('Dịch vụ', 'Phụ tùng')),
    service_id INTEGER REFERENCES services(id) ON UPDATE CASCADE ON DELETE SET NULL,
    part_id INTEGER REFERENCES parts(id) ON UPDATE CASCADE ON DELETE SET NULL,
    name TEXT NOT NULL,
    quantity NUMERIC NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit_price INTEGER NOT NULL DEFAULT 0 CHECK (unit_price >= 0),
    line_total INTEGER NOT NULL DEFAULT 0 CHECK (line_total >= 0),
    estimated_duration_min INTEGER CHECK (estimated_duration_min IS NULL OR estimated_duration_min > 0),
    estimate_source TEXT CHECK (estimate_source IS NULL OR estimate_source IN ('catalog','history'))
);

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    repair_order_id INTEGER NOT NULL
        REFERENCES repair_orders(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    quote_id INTEGER REFERENCES quotes(id) ON UPDATE CASCADE ON DELETE SET NULL,
    subtotal INTEGER NOT NULL DEFAULT 0 CHECK (subtotal >= 0),
    discount INTEGER NOT NULL DEFAULT 0 CHECK (discount >= 0),
    tax INTEGER NOT NULL DEFAULT 0 CHECK (tax >= 0),
    total INTEGER NOT NULL DEFAULT 0 CHECK (total >= 0),
    paid_amount INTEGER NOT NULL DEFAULT 0 CHECK (paid_amount >= 0),
    estimated_duration_min INTEGER CHECK (estimated_duration_min IS NULL OR estimated_duration_min > 0),
    status TEXT NOT NULL DEFAULT 'Chưa thanh toán'
        CHECK (status IN ('Chưa thanh toán', 'Thanh toán một phần', 'Đã thanh toán', 'Đã hủy')),
    issued_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    due_at TEXT,
    note TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS invoice_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    quote_item_id INTEGER REFERENCES quote_items(id) ON UPDATE CASCADE ON DELETE SET NULL,
    kind TEXT NOT NULL DEFAULT 'Dịch vụ' CHECK (kind IN ('Dịch vụ', 'Phụ tùng')),
    name TEXT NOT NULL,
    quantity NUMERIC NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit_price INTEGER NOT NULL DEFAULT 0 CHECK (unit_price >= 0),
    line_total INTEGER NOT NULL DEFAULT 0 CHECK (line_total >= 0),
    estimated_duration_min INTEGER CHECK (estimated_duration_min IS NULL OR estimated_duration_min > 0),
    estimate_source TEXT CHECK (estimate_source IS NULL OR estimate_source IN ('catalog','history'))
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL
        REFERENCES invoices(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    method TEXT NOT NULL DEFAULT 'Tiền mặt'
        CHECK (method IN ('Tiền mặt', 'Quét mã cửa hàng', 'Chuyển khoản', 'Thẻ', 'Ví điện tử')),
    amount INTEGER NOT NULL CHECK (amount > 0),
    status TEXT NOT NULL DEFAULT 'completed'
        CHECK (status IN ('completed', 'failed', 'voided', 'refunded')),
    idempotency_key TEXT UNIQUE,
    reference_code TEXT,
    paid_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    received_by INTEGER REFERENCES users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS repair_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id INTEGER REFERENCES vehicles(id) ON UPDATE CASCADE ON DELETE SET NULL,
    repair_order_id INTEGER REFERENCES repair_orders(id) ON UPDATE CASCADE ON DELETE SET NULL,
    plate TEXT NOT NULL,
    repaired_at TEXT NOT NULL,
    mileage INTEGER CHECK (mileage IS NULL OR mileage >= 0),
    services TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    total INTEGER NOT NULL DEFAULT 0 CHECK (total >= 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    actor_email TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    detail TEXT NOT NULL DEFAULT '{}',
    ip TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS ai_interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    task_type TEXT NOT NULL
        CHECK (task_type IN ('summary', 'explain', 'estimate', 'other')),
    ref_type TEXT NOT NULL DEFAULT '',
    ref_id TEXT,
    status TEXT NOT NULL DEFAULT 'success'
        CHECK (status IN ('success', 'fallback', 'error')),
    provider TEXT NOT NULL DEFAULT 'openai',
    model TEXT NOT NULL DEFAULT '',
    prompt_hash TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{}',
    latency_ms INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS ai_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    vehicle_id INTEGER REFERENCES vehicles(id) ON DELETE SET NULL,
    title TEXT NOT NULL DEFAULT 'Cuộc trò chuyện mới',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    client_key TEXT NOT NULL,
    context_summary TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (user_id, client_key)
);

CREATE TABLE IF NOT EXISTS ai_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('pending', 'completed', 'failed')),
    request_id TEXT,
    in_reply_to INTEGER REFERENCES ai_messages(id) ON DELETE CASCADE,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (conversation_id, request_id),
    UNIQUE (in_reply_to)
);

CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT '',
    updated_by INTEGER REFERENCES users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON UPDATE CASCADE ON DELETE CASCADE,
    language TEXT NOT NULL DEFAULT 'Tiếng Việt',
    notify_appointment INTEGER NOT NULL DEFAULT 1 CHECK (notify_appointment IN (0,1)),
    notify_repair INTEGER NOT NULL DEFAULT 1 CHECK (notify_repair IN (0,1)),
    notify_promotion INTEGER NOT NULL DEFAULT 0 CHECK (notify_promotion IN (0,1)),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
