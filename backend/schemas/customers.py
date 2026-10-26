"""Schema cho module khách hàng."""

from pydantic import ConfigDict, Field

from .common import RecordModel


class CustomerIn(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=6, max_length=30)
    email: str = Field(default="", max_length=120)
    address: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=1000)


class CustomerUpdate(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, min_length=6, max_length=30)
    email: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


class CustomerOut(RecordModel):
    id: int
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    note: str | None = None
    status: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    vehicle_count: int | None = None
    plates: str | None = None
    vins: str | None = None
    last_visit: str | None = None
    last_mileage: int | None = None
    last_service: str | None = None
    last_note: str | None = None
    lifetime_value: int | None = None
    appointment_count: int | None = None


class CustomerDetailOut(CustomerOut):
    vehicles: list[dict] = Field(default_factory=list)
    history: list[dict] = Field(default_factory=list)
    notes: list[dict] = Field(default_factory=list)
    appointments: list[dict] = Field(default_factory=list)
