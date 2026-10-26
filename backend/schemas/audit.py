"""Schema cho nhật ký kiểm toán và tương tác AI."""

from .common import RecordModel


class AuditLogOut(RecordModel):
    id: int
    user_id: int | None = None
    actor_email: str | None = None
    action: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    detail: str | None = None
    ip: str | None = None
    created_at: str | None = None


class AIInteractionOut(RecordModel):
    id: int
    user_id: int | None = None
    task_type: str | None = None
    ref_type: str | None = None
    ref_id: str | None = None
    status: str | None = None
    provider: str | None = None
    model: str | None = None
    prompt_hash: str | None = None
    metadata: str | None = None
    latency_ms: int | None = None
    created_at: str | None = None
