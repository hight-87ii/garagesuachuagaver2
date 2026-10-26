"""Schema cho module xác thực (authentication) và phân quyền."""

from pydantic import ConfigDict, Field, field_validator

from .common import RecordModel

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RegisterIn(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    full_name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=120, pattern=EMAIL_PATTERN)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str = Field(min_length=5, max_length=120)
    password: str = Field(min_length=1, max_length=128)


class PasswordChangeIn(RecordModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def not_same_as_current(cls, value: str, info):
        if info.data.get("current_password") == value:
            raise ValueError("Mật khẩu mới phải khác mật khẩu hiện tại")
        return value


class UserOut(RecordModel):
    id: int
    full_name: str
    email: str
    role: str
    status: str | None = None
    permissions: list[str] = Field(default_factory=list)


class LoginOut(RecordModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class RbacOut(RecordModel):
    roles: dict[str, list[str]]
    permissions: dict[str, str]


class UserCreateIn(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    full_name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=120, pattern=EMAIL_PATTERN)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(min_length=2, max_length=40)


class UserUpdateIn(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    full_name: str | None = Field(default=None, min_length=2, max_length=80)
    role: str | None = Field(default=None, min_length=2, max_length=40)
    status: str | None = Field(default=None, pattern="^(active|locked|disabled)$")


class UserSettingsIn(RecordModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    full_name: str = Field(min_length=2, max_length=80)
    phone: str = Field(default="", max_length=30)
    language: str = Field(default="Tiếng Việt", max_length=30)
    notify_appointment: bool = True
    notify_repair: bool = True
    notify_promotion: bool = False
