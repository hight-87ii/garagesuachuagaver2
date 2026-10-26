"""Schema cho module phụ tùng và kho."""

from pydantic import ConfigDict, Field, model_validator

from .common import RecordModel


class PartIn(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=120)
    category: str = Field(default="Phụ tùng", max_length=60)
    compatible: str = Field(default="", max_length=200)
    unit: str = Field(default="cái", max_length=20)
    cost_price: int = Field(default=0, ge=0)
    sell_price: int = Field(default=0, ge=0)
    stock: int = Field(default=0, ge=0)
    min_stock: int = Field(default=3, ge=0)
    supplier: str = Field(default="", max_length=120)


class PartStockIn(RecordModel):
    model_config = ConfigDict(extra="forbid")

    amount: int = Field(gt=0, le=10000)


class PartFitmentIn(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    make: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=1, max_length=60)
    year_from: int | None = Field(default=None, ge=1900, le=2100)
    year_to: int | None = Field(default=None, ge=1900, le=2100)
    variant: str = Field(default="", max_length=80)
    engine_code: str = Field(default="", max_length=60)
    fuel_type: str = Field(default="", max_length=40)
    note: str = Field(default="", max_length=250)

    @model_validator(mode="after")
    def check_years(self):
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("Năm bắt đầu không được sau năm kết thúc")
        return self


class PartFitmentsIn(RecordModel):
    model_config = ConfigDict(extra="forbid")
    fitments: list[PartFitmentIn] = Field(max_length=100)


class PartUpdate(RecordModel):
    """Các trường quản lý mã/phụ tùng; tồn kho chỉ thay đổi qua giao dịch kho."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str | None = Field(default=None, min_length=2, max_length=40)
    name: str | None = Field(default=None, min_length=2, max_length=120)
    category: str | None = Field(default=None, max_length=60)
    compatible: str | None = Field(default=None, max_length=200)
    unit: str | None = Field(default=None, max_length=20)
    cost_price: int | None = Field(default=None, ge=0)
    sell_price: int | None = Field(default=None, ge=0)
    min_stock: int | None = Field(default=None, ge=0)
    supplier: str | None = Field(default=None, max_length=120)
    active: bool | None = None


class PartOut(RecordModel):
    id: int
    code: str | None = None
    name: str | None = None
    category: str | None = None
    compatible: str | None = None
    unit: str | None = None
    cost_price: int | None = None
    sell_price: int | None = None
    stock: int | None = None
    min_stock: int | None = None
    supplier: str | None = None
    active: int | None = None
