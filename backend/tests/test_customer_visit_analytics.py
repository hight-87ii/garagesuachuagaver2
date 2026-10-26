import sqlite3
from datetime import datetime

import pytest

from backend.customer_visit_analytics import (
    DENIED, answer_customer_visit_question, parse_customer_visit_question,
)
from backend.timeutil import VN_TZ


NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=VN_TZ)


def database():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE repair_orders(
          id INTEGER PRIMARY KEY, code TEXT NOT NULL, customer_id INTEGER,
          status TEXT NOT NULL, status_code TEXT, received_at TEXT
        );
        INSERT INTO customers VALUES(1,'Tên trùng'),(2,'Tên trùng'),(3,'Khách C');
    """)
    return db


@pytest.mark.parametrize("question,period,min_visits,exact", [
    ("Những khách nào hay tới garage?", "12 tháng qua", 1, None),
    ("Top 10 khách đến garage nhiều nhất trong 6 tháng qua?", "6 tháng qua", 1, None),
    ("Khách nào quay lại ít nhất 3 lần trong năm nay?", "năm nay", 3, None),
    ("Liệt kê khách đến ít nhất 5 lần trong 12 tháng qua.", "12 tháng qua", 5, None),
    ("Khách nào đến đúng 3 lần trong tháng này?", "tháng này", 3, 3),
])
def test_intent_period_and_threshold(question, period, min_visits, exact):
    plan = parse_customer_visit_question(question, NOW)
    assert plan is not None
    assert (plan.period_label, plan.min_visits, plan.exact_visits) == (period, min_visits, exact)


def test_top_limit_is_parameterized_and_clamped():
    assert parse_customer_visit_question("Top 1 khách đến garage nhiều nhất", NOW).limit == 1
    plan = parse_customer_visit_question("Top 99 khách đến garage nhiều nhất", NOW)
    assert plan.limit == 20 and plan.requested_limit == 99


def test_aggregation_boundaries_cancelled_missing_invalid_and_stable_ties():
    db = database()
    rows = [
        (1, "PSC-1", 1, "Tiếp nhận", "RECEIVED", "2026-10-01T00:00:00Z"),
        (2, "PSC-2", 1, "Hoàn thành", "COMPLETED", "2026-10-02T00:00:00Z"),
        (3, "PSC-3", 2, "Tiếp nhận", "RECEIVED", "2026-10-03T00:00:00Z"),
        (4, "PSC-4", 2, "Đã hủy", "CANCELLED", "2026-10-04T00:00:00Z"),
        (5, "PSC-5", 3, "Tiếp nhận", "RECEIVED", "2026-10-05 07:00:00"),  # 00:00Z
        (6, "PSC-6", None, "Tiếp nhận", "RECEIVED", "2026-10-06T00:00:00Z"),
        (7, "PSC-7", 999, "Tiếp nhận", "RECEIVED", "2026-10-07T00:00:00Z"),
        (8, "PSC-8", 1, "Tiếp nhận", "RECEIVED", None),
        (9, "PSC-9", 1, "Tiếp nhận", "RECEIVED", "2026-10-26T05:00:00Z"),  # end, excluded
        (10, "PSC-10", 2, "Tiếp nhận", "RECEIVED", "2026-09-30T17:00:00Z"), # start, included
        (11, "PSC-11", 3, "Tiếp nhận", "RECEIVED", "2026-09-30T16:59:59Z"),
    ]
    db.executemany("INSERT INTO repair_orders VALUES(?,?,?,?,?,?)", rows)
    reply = answer_customer_visit_question(
        db, "Top 20 khách đến garage nhiều nhất trong tháng này?", {"role": "Admin"}, NOW)
    result = reply.analytics
    assert [(row["customer_id"], row["visit_count"]) for row in result["results"]] == [(1, 2), (2, 2), (3, 1)]
    assert result["results"][0]["repair_order_ids"] == [1, 2]
    assert result["data_quality"] == {
        "excluded_cancelled_orders": 1, "orders_missing_received_at": 1,
        "orders_missing_customer_id": 1, "orders_invalid_customer_id": 1,
    }
    assert all("phone" not in row and "email" not in row and "address" not in row
               for row in result["results"])


def test_exact_count_and_no_data():
    db = database()
    db.executemany("INSERT INTO repair_orders VALUES(?,?,?,?,?,?)", [
        (1, "PSC-1", 1, "Tiếp nhận", "RECEIVED", "2026-10-01T00:00:00Z"),
        (2, "PSC-2", 1, "Tiếp nhận", "RECEIVED", "2026-10-02T00:00:00Z"),
        (3, "PSC-3", 2, "Tiếp nhận", "RECEIVED", "2026-10-03T00:00:00Z"),
    ])
    exact = answer_customer_visit_question(db, "Khách nào đến đúng 2 lần trong tháng này?",
                                           {"role": "Quản lý"}, NOW)
    assert [row["customer_id"] for row in exact.analytics["results"]] == [1]
    empty = answer_customer_visit_question(db, "Khách nào đến đúng 9 lần trong tháng này?",
                                           {"role": "Admin"}, NOW)
    assert empty.result.status == "no_data" and empty.result.no_data


@pytest.mark.parametrize("role,allowed", [
    ("Admin", True), ("Quản lý", True), ("Lễ tân", False),
    ("Kỹ thuật viên", False), ("Thu ngân", False), ("Khách hàng", False),
])
def test_permissions_follow_configured_global_scope(role, allowed):
    db = database()
    reply = answer_customer_visit_question(db, "Những khách nào hay tới garage?", {"role": role}, NOW)
    assert (reply.analytics is not None) is allowed
    if not allowed:
        assert reply.result.status == "denied" and reply.result.content == DENIED


def test_denied_before_database_query():
    class MustNotQuery:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("Không được đọc dữ liệu trước kiểm tra quyền")

    reply = answer_customer_visit_question(MustNotQuery(), "Những khách nào hay tới garage?",
                                           {"role": "Khách hàng"}, NOW)
    assert reply.result.status == "denied"
