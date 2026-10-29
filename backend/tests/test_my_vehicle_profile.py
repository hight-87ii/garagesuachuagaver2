"""Owner profile updates never grant access to another vehicle or verified technical data."""

from backend import database
from backend.api.v1.ai import _vehicle_context
from backend.tests.test_conversations import API, chat_env, conversation, headers, say
from backend.migrations import migration_029


def test_customer_profile_persists_and_denies_identity_or_technical_changes(chat_env):
    client, vehicle_id = chat_env
    owner = headers(client)
    path = f"{API}/my-vehicles/{vehicle_id}/profile"
    before = client.get(f"{API}/my-vehicles", headers=owner).json()
    assert next(v for v in before["vehicles"] if v["id"] == vehicle_id)["profile"] == {}
    updated = client.patch(path, headers=owner, json={
        "mileage": 45400, "color": "Xanh", "inspection_expires_at": "2027-12-31",
        "seat_count": 5,
    })
    assert updated.status_code == 200, updated.text
    after = next(v for v in client.get(f"{API}/my-vehicles", headers=owner).json()["vehicles"] if v["id"] == vehicle_id)
    assert after["mileage"] == 45400 and after["color"] == "Xanh"
    assert after["profile"]["inspection_expires_at"] == "2027-12-31"
    assert after["profile"]["seat_count"] == 5
    assert after["profile"]["mileage_updated_at"]
    assert client.patch(path, headers=owner, json={"mileage": 100}).status_code == 400
    with database.connect() as db:
        db.execute("UPDATE vehicles SET year=2022 WHERE id=?", (vehicle_id,))
        db.commit()
    assert client.patch(path, headers=owner, json={"first_registration_year": 2020}).status_code == 400
    assert client.patch(path, headers=owner, json={"vin": "FORGED"}).status_code == 422
    assert client.patch(path, headers=owner, json={"tire_pressure": "35 psi"}).status_code == 400
    assert client.patch(f"{API}/my-vehicles/{vehicle_id+10000}/profile", headers=owner,
                        json={"color": "Đỏ"}).status_code == 404


def test_garage_verified_plan_requires_source_and_is_scoped(chat_env):
    client, vehicle_id = chat_env
    owner = headers(client)
    manager = headers(client, "manager@garage.vn", "Manager@123")
    path = f"{API}/vehicles/{vehicle_id}/profile"
    assert client.patch(path, headers=owner, json={"next_service_mileage": 50000}).status_code == 403
    cashier = headers(client, "cashier@garage.vn", "Cashier@123")
    assert client.patch(path, headers=cashier, json={"tire_size": "205/55R16"}).status_code == 403
    assert client.patch(path, headers=manager, json={"next_service_mileage": 50000}).status_code == 400
    saved = client.patch(path, headers=manager, json={
        "next_service_mileage": 50000, "maintenance_source": "Lịch bảo dưỡng đã đối chiếu",
        "tire_size": "205/55R16",
    })
    assert saved.status_code == 200, saved.text
    own = next(v for v in client.get(f"{API}/my-vehicles", headers=owner).json()["vehicles"] if v["id"] == vehicle_id)
    assert own["profile"]["next_service_mileage"] == 50000
    assert own["profile"]["tire_size"] == "205/55R16"
    with database.connect() as db:
        vehicle = db.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
        context = _vehicle_context(db, vehicle, False)
    assert context["technical_specs"]["tire_size"] == "205/55R16"
    assert "registration_info" not in context["technical_specs"]
    assert client.patch(f"{API}/my-vehicles/{vehicle_id}/profile", headers=owner,
                        json={"next_service_mileage": 30000}).status_code == 400
    question = "Xe còn bao nhiêu km nữa đến kỳ bảo dưỡng?"
    direct = client.post(f"{API}/ai/assistant/chat", headers=owner,
                         json={"question": question, "vehicle_id": vehicle_id})
    threaded = say(client, owner, conversation(client, owner, vehicle_id, "maintenance-plan"),
                   question, "maintenance-plan-question")["result"]
    assert direct.status_code == 200
    for answer in (direct.json(), threaded):
        assert "50.000 km" in answer["result"]
        assert "Lịch bảo dưỡng đã đối chiếu" in answer["result"]
        assert answer["sources"][0]["id"] == vehicle_id


def test_new_demo_history_does_not_assign_other_brand_parts_or_reverse_mileage(chat_env):
    with database.connect() as db:
        ford = db.execute("SELECT id FROM vehicles WHERE plate='20C-189.56'").fetchone()
        if not ford:
            return  # the fixture may disable optional demo customer records
        rows = db.execute("SELECT repaired_at,mileage,services FROM repair_history WHERE vehicle_id=? ORDER BY repaired_at",
                          (ford["id"],)).fetchall()
        assert not any(any(name in row["services"] for name in ("Bugi Kia Seltos", "Lọc dầu Mazda", "Má phanh trước Toyota"))
                       for row in rows)
        readings = [row["mileage"] for row in rows if row["mileage"] is not None]
        assert readings == sorted(readings)


def test_suspicious_history_is_flagged_without_changing_source(chat_env):
    client, vehicle_id = chat_env
    owner = headers(client)
    with database.connect() as db:
        vehicle = db.execute("SELECT plate FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
        db.execute("INSERT INTO repair_history(vehicle_id,plate,repaired_at,mileage,services,total) "
                   "VALUES(?,?,?,?,?,?)", (vehicle_id, vehicle["plate"], "2025-02-01", 47000,
                                         "Lọc dầu Mazda CX-5", 120000))
        db.commit()
        before = db.execute("SELECT id,services,mileage FROM repair_history WHERE vehicle_id=? "
                            "AND services='Lọc dầu Mazda CX-5'", (vehicle_id,)).fetchone()
        assert before
        migration_029(db)
        db.commit()
    response = client.get(f"{API}/my-vehicles", headers=owner)
    assert response.status_code == 200
    row = next(v for v in response.json()["vehicles"] if v["id"] == vehicle_id)
    match = next(h for h in row["history"] if h["id"] == before["id"])
    assert match["services"] == before["services"] and match["mileage"] == before["mileage"]
    assert any("hãng xe khác" in warning for warning in match["review_flags"])
    with database.connect() as db:
        after = db.execute("SELECT services,mileage FROM repair_history WHERE id=?", (before["id"],)).fetchone()
        assert after["services"] == before["services"] and after["mileage"] == before["mileage"]


def test_multiple_vehicles_are_isolated_and_other_customer_cannot_edit(chat_env):
    client, first_id = chat_env
    owner = headers(client)
    with database.connect() as db:
        customer = db.execute("SELECT customer_id FROM vehicles WHERE id=?", (first_id,)).fetchone()[0]
        second_id = db.execute("INSERT INTO vehicles(customer_id,plate,plate_normalized,make,model) "
                               "VALUES(?, 'SECOND-OWNER', 'SECONDOWNER', 'Ford', 'Ranger')",
                               (customer,)).lastrowid
        other_id = db.execute("SELECT id FROM vehicles WHERE customer_id<>? LIMIT 1", (customer,)).fetchone()[0]
        db.commit()
    response = client.get(f"{API}/my-vehicles", headers=owner)
    ids = {vehicle["id"] for vehicle in response.json()["vehicles"]}
    assert first_id in ids and second_id in ids and other_id not in ids
    denied = client.patch(f"{API}/my-vehicles/{other_id}/profile", headers=owner,
                          json={"mileage": 50000})
    assert denied.status_code == 403
