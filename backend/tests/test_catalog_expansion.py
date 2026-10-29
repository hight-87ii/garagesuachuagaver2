"""Kiểm tra dịch vụ mở rộng không tạo lại phụ tùng DEMO đã bị xóa."""

from backend import database
from backend.catalog_expansion import CATALOG_SERVICES, catalog_parts, fill_empty_stock_once


def test_expanded_catalog_is_idempotent_and_preserves_edits(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "catalog.db")
    database.init_db()
    db = database.connect()
    try:
        assert db.execute("SELECT count(*) FROM services").fetchone()[0] == 70
        assert db.execute("SELECT count(*) FROM parts").fetchone()[0] == 18
        assert len(CATALOG_SERVICES) == 50
        assert list(catalog_parts()) == []
        assert db.execute("SELECT count(*) FROM parts WHERE code LIKE 'DEMO-%' OR lower(name) LIKE '%(mẫu)%'").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM parts WHERE category='Gầm - lốp'").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM services WHERE category='Gầm - lốp'").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM parts WHERE category='Lốp'").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM parts WHERE trim(compatible)=''").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM parts WHERE stock=0").fetchone()[0] == 0
        db.execute("UPDATE services SET price=777000, duration_min=77 WHERE name='Thay má phanh trước'")
        db.execute("UPDATE parts SET stock=0 WHERE code='LF10-14-302'")
        assert fill_empty_stock_once(db) == 1
        db.execute("UPDATE parts SET stock=0 WHERE code='LF10-14-302'")
    finally:
        db.close()

    database.init_db()
    db = database.connect()
    try:
        assert db.execute("SELECT count(*) FROM services").fetchone()[0] == 70
        assert db.execute("SELECT count(*) FROM parts").fetchone()[0] == 18
        assert tuple(db.execute("SELECT price, duration_min FROM services WHERE name='Thay má phanh trước'").fetchone()) == (777000, 77)
        assert db.execute("SELECT stock FROM parts WHERE code='LF10-14-302'").fetchone()[0] == 0
    finally:
        db.close()
