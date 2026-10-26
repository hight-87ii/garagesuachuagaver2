"""Schema cho module dịch vụ (danh mục xưởng)."""

from pydantic import ConfigDict, Field

from .common import RecordModel


class ServiceIn(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=120)
    category: str = Field(min_length=2, max_length=60)
    description: str = Field(default="", max_length=1000)
    price: int = Field(default=0, ge=0)
    duration_min: int = Field(default=60, ge=5, le=1440)


class ServiceUpdate(ServiceIn):
    active: bool = True


class ServicePatch(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=2, max_length=120)
    category: str | None = Field(default=None, min_length=2, max_length=60)
    description: str | None = Field(default=None, max_length=1000)
    price: int | None = Field(default=None, ge=0)
    duration_min: int | None = Field(default=None, ge=5, le=1440)
    active: bool | None = None


class ServiceOut(RecordModel):
    id: int
    code: str | None = None
    name: str | None = None
    category: str | None = None
    description: str | None = None
    price: int | None = None
    duration_min: int | None = None
    active: int | None = None
