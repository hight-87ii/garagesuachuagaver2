"""Tách nhóm legacy 'Gầm - lốp' thành 'Gầm' và 'Lốp' trong dữ liệu hiện có."""

from backend.database import connect, transaction


def split_categories(db):
    with transaction(db):
        tire_services = db.execute(
            """UPDATE services SET category='Lốp' WHERE category='Gầm - lốp'
               AND (name LIKE '%lốp%' OR name LIKE '%bánh xe%')"""
        ).rowcount
        chassis_services = db.execute(
            "UPDATE services SET category='Gầm' WHERE category='Gầm - lốp'"
        ).rowcount
        tire_parts = db.execute(
            """UPDATE parts SET category='Lốp' WHERE category='Gầm - lốp'
               AND (code LIKE 'DEMO-TIRE-%' OR name LIKE 'Lốp %')"""
        ).rowcount
        chassis_parts = db.execute(
            "UPDATE parts SET category='Gầm' WHERE category='Gầm - lốp'"
        ).rowcount
    return tire_services, chassis_services, tire_parts, chassis_parts


if __name__ == "__main__":
    db = connect()
    try:
        result = split_categories(db)
        print("Updated services (tires/chassis):", result[0], result[1])
        print("Updated parts (tires/chassis):", result[2], result[3])
    finally:
        db.close()
