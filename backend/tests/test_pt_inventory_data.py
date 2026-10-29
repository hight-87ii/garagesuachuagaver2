from backend import database
from backend.pt_inventory_data import OUT_OF_STOCK_CODES, inventory_rows, upsert_pt_inventory


def test_pt_inventory_has_200_rows_and_is_idempotent(monkeypatch, tmp_path):
    rows = list(inventory_rows())
    assert len(rows) == 200
    assert rows[0][:3] == ("PT001", "Lọc dầu động cơ", "Bảo dưỡng – lọc")
    assert rows[0][5:7] == (90000, 110000)
    assert rows[99][:3] == ("PT100", "Mâm ép ly hợp", "Hộp số – ly hợp")
    assert rows[99][5:7] == (2690000, 3500000)
    assert rows[-1][:3] == ("PT200", "Bình nước rửa kính", "Gạt mưa")
    assert rows[-1][5:7] == (260000, 350000)
    assert rows[116][4] == "chai"  # dầu hộp số
    assert rows[128][4] == "sợi"   # ống dầu phanh
    assert "không khẳng định" in rows[0][10]
    assert "VIN" in rows[0][11]
    assert "không phải báo giá thị trường" in rows[0][12]
    assert "nhà cung cấp thực tế" in rows[0][13]
    assert all(row[6] >= row[5] >= 0 and row[8] >= 0 for row in rows)
    assert {row[0] for row in rows if row[7] == 0} == OUT_OF_STOCK_CODES
    assert all(row[7] >= 1 for row in rows if row[0] not in OUT_OF_STOCK_CODES)

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "pt.db")
    database.init_db()
    with database.connect() as db:
        assert upsert_pt_inventory(db) == (200, 0)
        assert upsert_pt_inventory(db) == (0, 200)
        assert db.execute("SELECT count(*) FROM parts WHERE code BETWEEN 'PT001' AND 'PT200'").fetchone()[0] == 200
        assert db.execute("SELECT count(*) FROM part_fitments WHERE part_id IN "
                          "(SELECT id FROM parts WHERE code BETWEEN 'PT001' AND 'PT200')").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM part_price_approvals WHERE part_id IN "
                          "(SELECT id FROM parts WHERE code BETWEEN 'PT001' AND 'PT200')").fetchone()[0] == 0
        assert db.execute("""SELECT count(*) FROM parts WHERE code BETWEEN 'PT001' AND 'PT200'
            AND compatibility_accuracy<>'' AND usage_requirements<>''
            AND price_note<>'' AND supplier_note<>''""").fetchone()[0] == 200
        assert db.execute("""SELECT count(*) FROM parts
            WHERE code BETWEEN 'PT001' AND 'PT200' AND stock=0""").fetchone()[0] == 5
        assert db.execute("""SELECT count(*) FROM parts
            WHERE code BETWEEN 'PT001' AND 'PT200' AND stock<1 AND stock<>0""").fetchone()[0] == 0
        db.commit()
