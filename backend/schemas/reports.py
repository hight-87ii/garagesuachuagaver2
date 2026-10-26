"""Schema cho module báo cáo (reports)."""

from pydantic import Field

from .common import RecordModel


class MetricsOut(RecordModel):
    appointments: int = 0
    in_progress: int = 0
    completed: int = 0
    revenue: int = 0
    growth: float = 0.0


class DashboardOut(RecordModel):
    metrics: MetricsOut
    appointments: list[dict] = Field(default_factory=list)
    repair_orders: list[dict] = Field(default_factory=list)
    revenue: list[int] = Field(default_factory=list)


class RevenuePointOut(RecordModel):
    day: str
    invoices: int
    revenue: int


class RevenueReportOut(RecordModel):
    days: int
    points: list[RevenuePointOut] = Field(default_factory=list)
    total_revenue: int = 0
    total_invoices: int = 0


class WorkloadOut(RecordModel):
    status: str
    count: int


class InventoryReportOut(RecordModel):
    total_items: int = 0
    total_stock: int = 0
    stock_value: int = 0
    low_stock: int = 0
    low_stock_items: list[dict] = Field(default_factory=list)
