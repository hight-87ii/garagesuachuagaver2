"""Tên hàng thực tế không được coi là tồn kho/giá/fitment thực tế của garage."""

from backend import database
from backend.market_parts import MARKET_PARTS, import_market_parts


def test_market_parts_import_is_idempotent_and_inactive(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "market.db")
    database.init_db()
    with database.connect() as db:
        assert import_market_parts(db) == len(MARKET_PARTS)
        assert import_market_parts(db) == 0
        rows = db.execute("""SELECT id,code,name,sell_price,stock,active FROM parts
                             WHERE code LIKE 'REF-%' ORDER BY code""").fetchall()
        assert len(rows) == len(MARKET_PARTS)
        assert all(row["active"] == row["stock"] == row["sell_price"] == 0 for row in rows)
        assert db.execute("""SELECT count(*) FROM part_fitments
            WHERE part_id IN (SELECT id FROM parts WHERE code LIKE 'REF-%')""").fetchone()[0] == 0
        assert db.execute("""SELECT count(*) FROM part_price_approvals
            WHERE part_id IN (SELECT id FROM parts WHERE code LIKE 'REF-%')""").fetchone()[0] == 0
        db.commit()
