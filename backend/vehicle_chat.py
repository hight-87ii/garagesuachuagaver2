"""Tương thích import cũ cho bộ tra cứu khách hàng–xe đã kiểm soát."""

from .customer_vehicle_query import answer_customer_vehicle_question


def customer_vehicles_reply(db, question: str, user: dict):
    return answer_customer_vehicle_question(db, question, user)
