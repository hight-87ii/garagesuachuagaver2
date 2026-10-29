"""Schema cho module phương tiện (xe)."""

from datetime import date

from pydantic import ConfigDict, Field

from .common import RecordModel


class VehicleIn(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    plate: str = Field(min_length=5, max_length=20)
    make: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=1, max_length=60)
    year: int | None = Field(default=None, ge=1900, le=2100)
    vin: str = Field(default="", max_length=20)
    variant: str = Field(default="", max_length=80)
    engine_code: str = Field(default="", max_length=60)
    fuel_type: str = Field(default="", max_length=40)
    mileage: int | None = Field(default=None, ge=0)


class VehicleUpdate(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    make: str | None = Field(default=None, min_length=1, max_length=60)
    model: str | None = Field(default=None, min_length=1, max_length=60)
    year: int | None = Field(default=None, ge=1900, le=2100)
    vin: str | None = Field(default=None, max_length=20)
    variant: str | None = Field(default=None, max_length=80)
    engine_code: str | None = Field(default=None, max_length=60)
    fuel_type: str | None = Field(default=None, max_length=40)
    mileage: int | None = Field(default=None, ge=0)


class VehicleOut(RecordModel):
    id: int
    customer_id: int | None = None
    plate: str | None = None
    plate_normalized: str | None = None
    vin: str | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = None
    variant: str | None = None
    engine_code: str | None = None
    fuel_type: str | None = None
    mileage: int | None = None
    status: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    last_visit: str | None = None
    last_mileage: int | None = None
    last_service: str | None = None
    last_note: str | None = None
    history_count: int | None = None
    lifetime_value: int | None = None
    active_order_count: int | None = None
    appointment_count: int | None = None


class VehicleDetailOut(VehicleOut):
    customer_email: str | None = None
    customer_address: str | None = None
    history: list[dict] = Field(default_factory=list)
    appointments: list[dict] = Field(default_factory=list)
    orders: list[dict] = Field(default_factory=list)
    invoices: list[dict] = Field(default_factory=list)
    notes: list[dict] = Field(default_factory=list)


class VehicleHistoryOut(RecordModel):
    """Một dòng lịch sử sửa chữa, kèm liên kết phiếu sửa chữa nếu có."""

    id: int
    vehicle_id: int | None = None
    repair_order_id: int | None = None
    order_code: str | None = None
    order_status: str | None = None
    order_technician: str | None = None
    plate: str | None = None
    repaired_at: str | None = None
    mileage: int | None = None
    services: str | None = None
    note: str | None = None
    total: int | None = None
    source: str | None = None


class LinkVehicleIn(RecordModel):
    """Liên kết xe đã có với hồ sơ khách hàng."""

    model_config = ConfigDict(extra="forbid")

    vehicle_id: int
    move: bool = False
    note: str = Field(default="", max_length=500)


class MyVehicleOut(VehicleOut):
    history: list[dict] = Field(default_factory=list)
    orders: list[dict] = Field(default_factory=list)
    appointments: list[dict] = Field(default_factory=list)


class MyVehiclesOut(RecordModel):
    customer: dict
    vehicles: list[dict] = Field(default_factory=list)


class VehicleProfileUpdate(RecordModel):
    """Optional details; identifiers (VIN, plate, chassis/engine number) are never owner-editable."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    color: str | None = Field(default=None, max_length=60)
    mileage: int | None = Field(default=None, ge=0, le=10_000_000)
    first_registration_year: int | None = Field(default=None, ge=1900, le=2100)
    vehicle_type: str | None = Field(default=None, max_length=60)
    seat_count: int | None = Field(default=None, ge=1, le=60)
    door_count: int | None = Field(default=None, ge=1, le=10)
    engine_number: str | None = Field(default=None, max_length=80)
    transmission: str | None = Field(default=None, max_length=60)
    drivetrain: str | None = Field(default=None, max_length=60)
    displacement_cc: int | None = Field(default=None, gt=0, le=20_000)
    power_kw: float | None = Field(default=None, gt=0, le=3000)
    torque_nm: float | None = Field(default=None, gt=0, le=10000)
    fuel_consumption: str | None = Field(default=None, max_length=100)
    fuel_tank_liters: float | None = Field(default=None, gt=0, le=1000)
    tire_size: str | None = Field(default=None, max_length=60)
    tire_pressure: str | None = Field(default=None, max_length=100)
    oil_capacity_liters: float | None = Field(default=None, gt=0, le=100)
    oil_spec: str | None = Field(default=None, max_length=120)
    registration_info: str | None = Field(default=None, max_length=200)
    inspection_expires_at: date | None = None
    liability_insurance_expires_at: date | None = None
    comprehensive_insurance_expires_at: date | None = None
    next_service_at: date | None = None
    next_service_mileage: int | None = Field(default=None, ge=0, le=10_000_000)
    maintenance_source: str | None = Field(default=None, max_length=200)
    maintenance_items: str | None = Field(default=None, max_length=1000)
