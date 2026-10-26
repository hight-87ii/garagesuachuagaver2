"""Chỉ mục FTS5 từ bản ghi nghiệp vụ; không chứa giá, tồn kho hay ghi chú nội bộ ở phạm vi khách."""

import re
import sqlite3

from .core.access import customer_scope_id
from .core.errors import BadRequestError, ForbiddenError, NotFoundError


def install_knowledge_index(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS knowledge_chunks (
        id INTEGER PRIMARY KEY,
        source_type TEXT NOT NULL CHECK(source_type IN ('service','part','repair_history')),
        source_id INTEGER NOT NULL,
        vehicle_id INTEGER,
        customer_id INTEGER,
        visibility TEXT NOT NULL CHECK(visibility IN ('public','customer','internal')),
        content TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        UNIQUE(source_type,source_id,visibility)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_owner ON knowledge_chunks(customer_id,vehicle_id,visibility)")
    db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
        content, content='knowledge_chunks', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
    )""")
    for event, body in (
        ("insert", "INSERT INTO knowledge_fts(rowid,content) VALUES(new.id,new.content);"),
        ("delete", "INSERT INTO knowledge_fts(knowledge_fts,rowid,content) VALUES('delete',old.id,old.content);"),
        ("update", "INSERT INTO knowledge_fts(knowledge_fts,rowid,content) VALUES('delete',old.id,old.content); INSERT INTO knowledge_fts(rowid,content) VALUES(new.id,new.content);"),
    ):
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS knowledge_chunks_{event} AFTER {event.upper()} ON knowledge_chunks BEGIN {body} END""")

    # Văn bản customer chỉ có dữ liệu lịch sử chung, tuyệt đối không lấy repair_history.note
    # (có thể chứa ghi chú kỹ thuật viên). Bản internal có thêm ghi chú cho nhân viên.
    history_insert = """
        INSERT INTO knowledge_chunks(source_type,source_id,vehicle_id,customer_id,visibility,content)
        SELECT 'repair_history',new.id,new.vehicle_id,v.customer_id,'customer',
               'Lịch sử sửa chữa xe ' || COALESCE(new.plate,'') || '. Ngày ' ||
               COALESCE(new.repaired_at,'') || '. Dịch vụ: ' || COALESCE(new.services,'') ||
               '. Số km: ' || COALESCE(CAST(new.mileage AS TEXT),'chưa ghi nhận') || '.'
        FROM vehicles v WHERE v.id=new.vehicle_id AND v.customer_id IS NOT NULL;
        INSERT INTO knowledge_chunks(source_type,source_id,vehicle_id,customer_id,visibility,content)
        SELECT 'repair_history',new.id,new.vehicle_id,v.customer_id,'internal',
               'Lịch sử sửa chữa xe ' || COALESCE(new.plate,'') || '. Ngày ' ||
               COALESCE(new.repaired_at,'') || '. Dịch vụ: ' || COALESCE(new.services,'') ||
               '. Số km: ' || COALESCE(CAST(new.mileage AS TEXT),'chưa ghi nhận') ||
               '. Ghi chú: ' || COALESCE(new.note,'') || '.'
        FROM vehicles v WHERE v.id=new.vehicle_id AND v.customer_id IS NOT NULL;
    """
    sources = {
        "services": ("service", "new.active=1", "'Dịch vụ ' || new.name || '. Nhóm: ' || new.category || '. Mô tả: ' || new.description"),
        "parts": ("part", "new.active=1", "'Phụ tùng ' || new.name || '. Mã: ' || new.code || '. Nhóm: ' || new.category || '. Tương thích theo danh mục: ' || new.compatible"),
    }
    for table, (kind, condition, content) in sources.items():
        insert = ("INSERT INTO knowledge_chunks(source_type,source_id,visibility,content) "
                  f"SELECT '{kind}',new.id,'public',{content} WHERE {condition};")
        db.execute(f"CREATE TRIGGER IF NOT EXISTS knowledge_{table}_insert AFTER INSERT ON {table} BEGIN {insert} END")
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS knowledge_{table}_update AFTER UPDATE ON {table}
            BEGIN DELETE FROM knowledge_chunks WHERE source_type='{kind}' AND source_id=old.id; {insert} END""")
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS knowledge_{table}_delete AFTER DELETE ON {table}
            BEGIN DELETE FROM knowledge_chunks WHERE source_type='{kind}' AND source_id=old.id; END""")
    db.execute(f"CREATE TRIGGER IF NOT EXISTS knowledge_history_insert AFTER INSERT ON repair_history BEGIN {history_insert} END")
    db.execute(f"""CREATE TRIGGER IF NOT EXISTS knowledge_history_update AFTER UPDATE ON repair_history
        BEGIN DELETE FROM knowledge_chunks WHERE source_type='repair_history' AND source_id=old.id;
        {history_insert} END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS knowledge_history_delete AFTER DELETE ON repair_history
        BEGIN DELETE FROM knowledge_chunks WHERE source_type='repair_history' AND source_id=old.id; END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS knowledge_vehicle_owner AFTER UPDATE OF customer_id ON vehicles
        BEGIN UPDATE knowledge_chunks SET customer_id=new.customer_id
        WHERE source_type='repair_history' AND vehicle_id=new.id; END""")

    # Migration cũ có dữ liệu trước khi trigger được cài. Tạo lại được, nhưng không gọi
    # khi phục vụ truy vấn để tránh quét toàn DB trên mỗi câu hỏi.
    rebuild_knowledge_index(db)


def rebuild_knowledge_index(db: sqlite3.Connection) -> None:
    """Tái tạo chỉ mục (dùng khi nâng cấp hoặc sửa dữ liệu ngoài API)."""
    db.execute("DELETE FROM knowledge_chunks")
    db.execute("""INSERT INTO knowledge_chunks(source_type,source_id,visibility,content)
        SELECT 'service',id,'public','Dịch vụ ' || name || '. Nhóm: ' || category || '. Mô tả: ' || description
        FROM services WHERE active=1""")
    db.execute("""INSERT INTO knowledge_chunks(source_type,source_id,visibility,content)
        SELECT 'part',id,'public','Phụ tùng ' || name || '. Mã: ' || code || '. Nhóm: ' || category ||
               '. Tương thích theo danh mục: ' || compatible FROM parts WHERE active=1""")
    db.execute("""INSERT INTO knowledge_chunks(source_type,source_id,vehicle_id,customer_id,visibility,content)
        SELECT 'repair_history',h.id,h.vehicle_id,v.customer_id,'customer',
               'Lịch sử sửa chữa xe ' || COALESCE(h.plate,'') || '. Ngày ' || COALESCE(h.repaired_at,'') ||
               '. Dịch vụ: ' || COALESCE(h.services,'') || '. Số km: ' ||
               COALESCE(CAST(h.mileage AS TEXT),'chưa ghi nhận') || '.'
        FROM repair_history h JOIN vehicles v ON v.id=h.vehicle_id WHERE v.customer_id IS NOT NULL""")
    db.execute("""INSERT INTO knowledge_chunks(source_type,source_id,vehicle_id,customer_id,visibility,content)
        SELECT 'repair_history',h.id,h.vehicle_id,v.customer_id,'internal',
               'Lịch sử sửa chữa xe ' || COALESCE(h.plate,'') || '. Ngày ' || COALESCE(h.repaired_at,'') ||
               '. Dịch vụ: ' || COALESCE(h.services,'') || '. Số km: ' ||
               COALESCE(CAST(h.mileage AS TEXT),'chưa ghi nhận') || '. Ghi chú: ' || COALESCE(h.note,'') || '.'
        FROM repair_history h JOIN vehicles v ON v.id=h.vehicle_id WHERE v.customer_id IS NOT NULL""")


def search_knowledge(db: sqlite3.Connection, user: dict, query: str, vehicle_id: int | None = None,
                     limit: int = 8, *, kind: str = "all") -> list[dict]:
    """Lọc tenant/visibility bằng SQL trước khi trả kết quả; không trả vector/metadata nội bộ."""
    if kind not in ("all", "public", "vehicle"):
        raise BadRequestError("Phạm vi tra cứu không hợp lệ")
    if vehicle_id is not None:
        row = db.execute("SELECT customer_id FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
        if not row:
            raise NotFoundError("Không tìm thấy xe")
        scope = customer_scope_id(db, user)
        if scope is not None and row["customer_id"] != scope:
            raise ForbiddenError("Bạn không có quyền truy cập dữ liệu xe này")
    else:
        scope = customer_scope_id(db, user)
    tokens = re.findall(r"[^\W_]+", query, flags=re.UNICODE)[:8]
    if not tokens:
        raise BadRequestError("Cần nhập từ khóa tìm kiếm")
    match = " OR ".join('"' + token.replace('"', '') + '"' for token in tokens)
    if kind == "public":
        access = "k.visibility='public' AND k.source_type IN ('service','part')"
        params: list = [match]
    elif kind == "vehicle":
        if vehicle_id is None:
            return []
        access = ("k.visibility='internal'" if scope is None and user.get("role") in
                  ("Admin", "Quản lý", "Kỹ thuật viên", "Lễ tân") else
                  "k.visibility='customer' AND k.customer_id=?" if scope is not None else "0=1")
        params = [match, scope] if scope is not None else [match]
        access += " AND k.source_type='repair_history'"
    elif scope is None:
        access = ("k.visibility IN ('public','internal')" if user.get("role") in
                  ("Admin", "Quản lý", "Kỹ thuật viên", "Lễ tân") else "k.visibility='public'")
        params: list = [match]
    else:
        # Không chọn xe => chỉ tài liệu công khai; không quét lịch sử của tất cả xe khách.
        access = ("(k.visibility='public' OR (k.visibility='customer' AND k.customer_id=?))"
                  if vehicle_id is not None else "k.visibility='public'")
        params = [match, scope] if vehicle_id is not None else [match]
    vehicle_filter = " AND (k.source_type!='repair_history' OR k.vehicle_id=?)" if vehicle_id else ""
    if vehicle_id:
        params.append(vehicle_id)
    params.append(max(1, min(limit, 20)))
    return [dict(row) for row in db.execute(
        "SELECT k.source_type,k.source_id,k.vehicle_id,k.content,k.updated_at "
        "FROM knowledge_fts f JOIN knowledge_chunks k ON k.id=f.rowid "
        f"WHERE knowledge_fts MATCH ? AND {access}{vehicle_filter} "
        "ORDER BY bm25(knowledge_fts),k.id DESC LIMIT ?", params,
    ).fetchall()]
