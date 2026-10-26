"""Tương thích import cũ cho bộ tra cứu lịch hẹn có kiểm soát."""

from .appointment_query import answer_appointment_question


def pending_appointments_reply(db, question: str, user: dict):
    return answer_appointment_question(db, question, user)
