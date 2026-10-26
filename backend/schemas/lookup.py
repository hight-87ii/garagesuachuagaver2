"""Schema cho tra cứu & phát hiện trùng lặp (khách hàng / xe)."""

from .common import RecordModel


class LookupCustomer(RecordModel):
    id: int
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    vehicle_count: int | None = None
    plates: str | None = None
    last_visit: str | None = None
    lifetime_value: int | None = None


class LookupVehicle(RecordModel):
    id: int
    customer_id: int | None = None
    plate: str | None = None
    vin: str | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = None
    mileage: int | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    last_visit: str | None = None
    history_count: int | None = None
    match: str | None = None


class LookupOut(RecordModel):
    """Kết quả tra cứu: hồ sơ khách hàng và xe đã có trong hệ thống."""

    query: str | None = None
    customers: list[LookupCustomer] = []
    vehicles: list[LookupVehicle] = []
