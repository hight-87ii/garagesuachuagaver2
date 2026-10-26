from pydantic import ConfigDict, Field

from .common import RecordModel


class SystemSettingsUpdate(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    garage_name: str = Field(min_length=2, max_length=120)
    garage_phone: str = Field(default="", max_length=30)
    garage_address: str = Field(default="", max_length=250)
    invoice_prefix: str = Field(default="HD", min_length=1, max_length=10)
    quote_valid_days: int = Field(default=7, ge=1, le=90)
