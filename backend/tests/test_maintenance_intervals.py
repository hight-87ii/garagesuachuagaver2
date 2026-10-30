"""Chu kỳ thay dầu có cấu trúc: chỉ dùng bản ghi approved gắn bài published."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend import database
from backend.ai_service import AIService, ai_service
from backend.maintenance_interval import (
    _active_interval,
    _add_months,
    _compute_due,
    answer_maintenance_interval,
    build_maintenance_context,
    find_oil_interval,
)
from backend.timeutil import VN_TZ, vn_datetime
from backend.tests.test_conversations import API, chat_env, conversation, headers, say


@pytest.fixture
def vehicle_env(monkeypatch, tmp_path):
    """DB tạm có sẵn seed chu kỳ, kèm xe Seltos đủ cấu hình."""
    monkeypatch.setenv("CATALOG_MODE", "production")
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "maintenance.db")
    database.init_db()
    with database.connect() as db:
        vehicle = db.execute("SELECT * FROM vehicles ORDER BY id LIMIT 1").fetchone()
        db.execute(
            """UPDATE vehicles SET make='Kia',model='Seltos',year=2022,
                      engine_code='G4LD',mileage=50000 WHERE id=?""",
            (vehicle["id"],),
        )
        db.commit()
    return vehicle["id"]


def _vehicle(vehicle_id):
    with database.connect() as db:
        return dict(db.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone())


def _oil_history(vehicle_id, mileage, moment):
    with database.connect() as db:
        vehicle = db.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
        order_id = db.execute(
            """INSERT INTO repair_orders(code,vehicle_id,customer_id,plate,customer_name,
                                         status,status_code,completed_at)
               VALUES('OIL-SEED-1',?,?,?,'Khách test','Đã bàn giao','DELIVERED',?)""",
            (vehicle_id, vehicle["customer_id"], vehicle["plate"], moment),
        ).lastrowid
        db.execute(
            "INSERT INTO repair_order_items(repair_order_id,kind,name) "
            "VALUES(?,'Dịch vụ','Thay dầu động cơ')", (order_id,))
        db.execute(
            "INSERT INTO repair_history(vehicle_id,repair_order_id,plate,repaired_at,mileage,services) "
            "VALUES(?,?,?,?,?,?)",
            (vehicle_id, order_id, vehicle["plate"], moment, mileage, "Thay dầu động cơ"),
        )
        db.commit()


def test_seed_creates_approved_intervals_with_reviewed_articles(vehicle_env):
    with database.connect() as db:
        rows = db.execute(
            """SELECT mi.status,mi.approved_by,a.status AS article_status,
                      a.technical_reviewed_by
               FROM maintenance_intervals mi
               JOIN technical_articles a ON a.id=mi.article_id"""
        ).fetchall()
        assert len(rows) == 9
        for row in rows:
            assert row["status"] == "approved"
            assert row["approved_by"] is not None
            assert row["article_status"] == "published"
            assert row["technical_reviewed_by"] is not None


def test_seed_is_idempotent(vehicle_env):
    with database.connect() as db:
        before = db.execute("SELECT COUNT(*) FROM maintenance_intervals").fetchone()[0]
    database.init_db()
    with database.connect() as db:
        after = db.execute("SELECT COUNT(*) FROM maintenance_intervals").fetchone()[0]
        articles = db.execute(
            "SELECT COUNT(*) FROM technical_articles WHERE title LIKE 'Chu kỳ thay dầu%'"
        ).fetchone()[0]
    assert after == before == 9
    assert articles == 9


@pytest.mark.parametrize("make,model,year,engine,km,months", [
    ("Mazda", "CX-5", 2021, "SKYACTIV-G 2.0", 10000, 12),
    ("Toyota", "Camry", 2020, "M20A-FKS", 16000, 12),
    ("Kia", "Seltos", 2022, "G4LD", 10000, 12),
    ("Honda", "CR-V", 2019, "L15B7", None, 12),
    ("Hyundai", "Tucson", 2021, "G4NA", 5000, 3),
    ("Ford", "Ranger", 2021, "TDCi 2.0", 16000, 12),
    ("Mitsubishi", "Xpander", 2023, "4A91", 10000, 8),
    ("Toyota", "Vios", 2020, "2NR-FE", 5000, 6),
    ("Hyundai", "Accent", 2022, "G4FL", 5000, 3),
])
def test_find_interval_matches_demo_configuration(vehicle_env, make, model, year, engine,
                                                  km, months):
    with database.connect() as db:
        found = find_oil_interval(db, {"make": make, "model": model, "year": year,
                                       "engine_code": engine})
    assert found is not None
    assert (found["interval_km"], found["interval_months"]) == (km, months)
    assert found["engine_verified"] is True
    assert found["source_name"] and found["market"]


def test_electric_vehicle_and_wrong_year_do_not_match(vehicle_env):
    with database.connect() as db:
        assert find_oil_interval(db, {"make": "VinFast", "model": "VF8", "year": 2023,
                                      "engine_code": ""}) is None
        assert find_oil_interval(db, {"make": "Mazda", "model": "CX-5", "year": 2024,
                                      "engine_code": "SKYACTIV-G 2.0"}) is None
        assert find_oil_interval(db, {"make": "Mazda", "model": "CX-5", "year": 2021,
                                      "engine_code": "SKYACTIV-D 2.2"}) is None


def test_missing_engine_code_is_marked_unverified(vehicle_env):
    with database.connect() as db:
        found = find_oil_interval(db, {"make": "Kia", "model": "Seltos", "year": 2022,
                                       "engine_code": ""})
    assert found is not None and found["engine_verified"] is False
    assert found["engine_match"] == "unverified"


def test_ambiguous_engine_variants_without_engine_code_are_rejected(vehicle_env):
    with database.connect() as db:
        db.execute(
            """INSERT INTO maintenance_intervals
               (service_type,vehicle_make,vehicle_model,year_from,year_to,engine_code,
                market,interval_km,interval_months,source_name,article_id,status,approved_by)
               VALUES('engine_oil','Kia','Seltos',2020,2023,'G4NA','Việt Nam',5000,6,
                      'Nguồn thử',(SELECT article_id FROM maintenance_intervals WHERE id=3),
                      'approved',1)"""
        )
        db.commit()
        assert find_oil_interval(db, {"make": "Kia", "model": "Seltos", "year": 2022,
                                      "engine_code": ""}) is None


def test_pending_interval_or_unreviewed_article_is_ignored(vehicle_env):
    with database.connect() as db:
        interval = db.execute(
            "SELECT id,article_id FROM maintenance_intervals WHERE vehicle_model='Seltos'"
        ).fetchone()
        db.execute("UPDATE maintenance_intervals SET status='pending' WHERE id=?",
                   (interval["id"],))
        db.commit()
        assert find_oil_interval(db, {"make": "Kia", "model": "Seltos", "year": 2022,
                                      "engine_code": "G4LD"}) is None
        db.execute("UPDATE maintenance_intervals SET status='approved' WHERE id=?",
                   (interval["id"],))
        db.execute("UPDATE technical_articles SET technical_reviewed_by=NULL WHERE id=?",
                   (interval["article_id"],))
        db.commit()
        assert find_oil_interval(db, {"make": "Kia", "model": "Seltos", "year": 2022,
                                      "engine_code": "G4LD"}) is None


def test_due_uses_last_completed_oil_change(vehicle_env):
    moment = (datetime.now(VN_TZ) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _oil_history(vehicle_env, 45000, moment)
    vehicle = _vehicle(vehicle_env)
    with database.connect() as db:
        context = build_maintenance_context(db, "Bao lâu thì phải thay dầu?", vehicle, [])
    due = context["due"]
    assert context["interval"]["interval_km"] == 10000
    assert context["mileage_since_last_oil"] == 5000
    assert due["next_due_km"] == 55000
    assert due["km_remaining"] == 5000
    assert due["status"] == "not_due"
    expected_date = _add_months(vn_datetime(moment).date(), 12)
    assert due["next_due_date"] == expected_date.isoformat()
    assert 300 < due["days_remaining"] <= 400
    assert context["conclusion"] == "chưa đến hạn"


def test_overdue_interval_and_severe_basis(vehicle_env):
    moment = (datetime.now(VN_TZ) - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _oil_history(vehicle_env, 40000, moment)
    vehicle = _vehicle(vehicle_env)
    with database.connect() as db:
        context = build_maintenance_context(
            db, "Xe hay tắc đường, quãng ngắn thì khi nào thay dầu?", vehicle, [])
    assert context["active_interval"]["basis"] == "severe"
    assert context["active_interval"]["km"] == 5000
    assert context["due"]["next_due_km"] == 45000
    assert context["due"]["status"] == "overdue"
    assert context["conclusion"] == "đã đến hạn"


def test_active_interval_falls_back_to_normal_without_severe_data(vehicle_env):
    with database.connect() as db:
        interval = dict(db.execute(
            "SELECT * FROM maintenance_intervals WHERE vehicle_model='CR-V'").fetchone())
    active = _active_interval(interval, severe=True)
    assert active["basis"] == "normal"
    assert active["km"] is None and active["months"] == 12


def test_compute_due_handles_missing_history():
    due = _compute_due({"basis": "normal", "km": 10000, "months": 12}, None, 50000)
    assert due["status"] == "unknown"
    assert due["next_due_km"] is None


def test_offline_answer_states_market_and_source(vehicle_env, monkeypatch):
    monkeypatch.setattr(ai_service, "_generation_enabled", False, raising=False)
    moment = (datetime.now(VN_TZ) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _oil_history(vehicle_env, 45000, moment)
    vehicle = _vehicle(vehicle_env)
    offline = AIService(api_key="")
    assert offline._enabled is False
    with database.connect() as db:
        answer, sources = answer_maintenance_interval(
            db, "Bao lâu thì phải thay dầu?", vehicle)
        assert answer.status in ("success", "fallback", "clarification")
        assert "10.000 km" in answer.content
        assert "thị trường" in answer.content
        assert "55.000 km" in answer.content
        assert "Ấn Độ" in answer.content
        assert any(source["type"] == "maintenance_interval" for source in sources)
        assert any(source["type"] == "technical_article" for source in sources)
        assert all(source["type"] != "service" for source in sources)


def test_price_question_is_not_an_interval_question(vehicle_env):
    vehicle = _vehicle(vehicle_env)
    with database.connect() as db:
        assert answer_maintenance_interval(
            db, "Thay dầu động cơ hết bao nhiêu tiền?", vehicle) is None


def test_both_chat_apis_return_same_interval(chat_env, monkeypatch):
    client, vehicle_id = chat_env
    auth = headers(client)
    with database.connect() as db:
        db.execute("""UPDATE vehicles SET make='Kia',model='Seltos',year=2022,
                      engine_code='G4LD',mileage=50000 WHERE id=?""", (vehicle_id,))
        db.commit()
    moment = (datetime.now(VN_TZ) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _oil_history(vehicle_id, 45000, moment)
    monkeypatch.setattr(ai_service, "_generation_enabled", False, raising=False)
    question = "Bao lâu thì phải thay dầu động cơ?"
    old = client.post(f"{API}/ai/assistant/chat", headers=auth,
                      json={"question": question, "vehicle_id": vehicle_id}).json()
    conv = conversation(client, auth, vehicle_id, "maintenance-interval")
    new = say(client, auth, conv, question, "maintenance-interval-1")["result"]
    for result in (old, new):
        assert result["status"] in ("success", "fallback")
        assert "10.000 km" in result["result"]
        assert "55.000 km" in result["result"]
        assert "Ấn Độ" in result["result"]
        assert any(source["type"] == "maintenance_interval" for source in result["sources"])
        assert all(source["type"] != "service" for source in result["sources"])
        assert "**" not in result["result"]


def test_unverified_engine_answer_asks_to_check_vin(vehicle_env, monkeypatch):
    monkeypatch.setattr(ai_service, "_generation_enabled", False, raising=False)
    with database.connect() as db:
        db.execute("UPDATE vehicles SET engine_code='' WHERE id=?", (vehicle_env,))
        db.commit()
    vehicle = _vehicle(vehicle_env)
    with database.connect() as db:
        answer, _ = answer_maintenance_interval(db, "Bao lâu thì phải thay dầu?", vehicle)
    assert "mã động cơ" in answer.content
    assert "10.000 km" in answer.content
