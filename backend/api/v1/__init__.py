"""Phiên bản 1 của API GarageAI (/api/v1).

Mỗi module nghiệp vụ nằm trong một tệp riêng và được gom lại ở đây.
"""

from fastapi import APIRouter

from . import (
    ai,
    conversations,
    appointments,
    audit,
    auth,
    customers,
    invoices,
    notifications,
    parts,
    quotes,
    repair_orders,
    repair_cases,
    reports,
    services,
    vehicles,
    users,
    system_settings,
    technical_knowledge,
)

api_v1 = APIRouter()
api_v1.include_router(auth.router)
api_v1.include_router(auth.rbac_router)
api_v1.include_router(reports.router)
api_v1.include_router(appointments.router)
api_v1.include_router(vehicles.router)
api_v1.include_router(vehicles.my_router)
api_v1.include_router(customers.router)
api_v1.include_router(customers.lookup_router)
api_v1.include_router(repair_orders.router)
api_v1.include_router(repair_cases.router)
api_v1.include_router(quotes.router)
api_v1.include_router(parts.router)
api_v1.include_router(services.router)
api_v1.include_router(invoices.router)
api_v1.include_router(invoices.payments_router)
api_v1.include_router(notifications.router)
api_v1.include_router(audit.router)
api_v1.include_router(ai.router)
api_v1.include_router(conversations.router)
api_v1.include_router(technical_knowledge.router)
api_v1.include_router(users.router)
api_v1.include_router(system_settings.router)

__all__ = ["api_v1"]
