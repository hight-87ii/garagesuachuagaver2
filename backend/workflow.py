"""Máy trạng thái của phiếu sửa chữa.

Luồng chuẩn::

    RECEIVED → INSPECTING → QUOTED → APPROVED → IN_PROGRESS → COMPLETED → DELIVERED

Các trạng thái nhánh: ``WAITING_FOR_PARTS``, ``ON_HOLD``, ``CANCELLED``.

Mỗi lần chuyển trạng thái đều được kiểm tra:

* chỉ cho phép chuyển theo đúng cạnh của đồ thị trạng thái;
* kiểm tra điều kiện nghiệp vụ của trạng thái đích (dữ liệu tiếp nhận, báo giá,
  phân công kỹ thuật viên, hóa đơn đã thanh toán trước khi bàn giao...);
* ghi lại một dòng lịch sử không thể sửa/xóa.

Module này không phụ thuộc FastAPI để có thể kiểm thử và tái sử dụng.
"""

import sqlite3
from typing import Any

from .core.errors import BadRequestError
from .domain import record_repair_history
from .timeutil import now_utc_iso

#: Định nghĩa trạng thái chuẩn. ``step`` dùng cho thanh tiến trình trên UI.
STATUS_DEFINITIONS: dict[str, dict[str, Any]] = {
    "RECEIVED": {
        "label": "Tiếp nhận",
        "description": "Xe đã vào xưởng, chờ kiểm tra.",
        "step": 1,
        "terminal": False,
    },
    "INSPECTING": {
        "label": "Đang kiểm tra",
        "description": "Kỹ thuật viên kiểm tra tình trạng thực tế của xe.",
        "step": 2,
        "terminal": False,
    },
    "QUOTED": {
        "label": "Đã báo giá",
        "description": "Đã lập báo giá và gửi khách hàng xem xét.",
        "step": 3,
        "terminal": False,
    },
    "APPROVED": {
        "label": "Đã duyệt",
        "description": "Khách hàng đã duyệt báo giá, sẵn sàng thi công.",
        "step": 4,
        "terminal": False,
    },
    "IN_PROGRESS": {
        "label": "Đang sửa",
        "description": "Xe đang được kỹ thuật viên thi công.",
        "step": 5,
        "terminal": False,
    },
    "WAITING_FOR_PARTS": {
        "label": "Chờ phụ tùng",
        "description": "Tạm dừng thi công để chờ bổ sung phụ tùng.",
        "step": 5,
        "terminal": False,
    },
    "ON_HOLD": {
        "label": "Tạm dừng",
        "description": "Phiếu đang tạm dừng, cần lý do cụ thể.",
        "step": 5,
        "terminal": False,
    },
    "COMPLETED": {
        "label": "Hoàn thành",
        "description": "Công việc đã xong, chờ lập hóa đơn và bàn giao.",
        "step": 6,
        "terminal": False,
    },
    "DELIVERED": {
        "label": "Đã bàn giao",
        "description": "Xe đã được bàn giao cho khách và hóa đơn đã thanh toán.",
        "step": 7,
        "terminal": True,
    },
    "CANCELLED": {
        "label": "Đã hủy",
        "description": "Phiếu đã hủy, không thể tiếp tục thi công.",
        "step": 0,
        "terminal": True,
    },
}

STATUS_CODES = tuple(STATUS_DEFINITIONS)
STATUS_LABELS = {code: meta["label"] for code, meta in STATUS_DEFINITIONS.items()}
LABEL_TO_CODE = {label: code for code, label in STATUS_LABELS.items()}
# Nhãn cũ trước khi có luồng trạng thái đầy đủ.
LABEL_TO_CODE["Kiểm tra"] = "INSPECTING"
_LABEL_LOOKUP = {label.casefold(): code for label, code in LABEL_TO_CODE.items()}

#: Các cạnh hợp lệ của đồ thị trạng thái. Không có cạnh RECEIVED → DELIVERED.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "RECEIVED": ("INSPECTING", "CANCELLED"),
    "INSPECTING": ("QUOTED", "ON_HOLD", "CANCELLED"),
    "QUOTED": ("INSPECTING", "APPROVED", "ON_HOLD", "CANCELLED"),
    "APPROVED": ("IN_PROGRESS", "ON_HOLD", "CANCELLED"),
    "IN_PROGRESS": ("WAITING_FOR_PARTS", "ON_HOLD", "COMPLETED", "CANCELLED"),
    "WAITING_FOR_PARTS": ("IN_PROGRESS", "ON_HOLD", "CANCELLED"),
    "ON_HOLD": (
        "INSPECTING",
        "QUOTED",
        "APPROVED",
        "IN_PROGRESS",
        "WAITING_FOR_PARTS",
        "CANCELLED",
    ),
    "COMPLETED": ("DELIVERED",),
    "DELIVERED": (),
    "CANCELLED": (),
}

#: Trạng thái cần nhập lý do khi chuyển tới.
NOTE_REQUIRED = frozenset({"CANCELLED", "ON_HOLD", "WAITING_FOR_PARTS"})

#: Các trạng thái được phép sửa nội dung phiếu.
EDITABLE_STATUS_CODES = frozenset(
    {"RECEIVED", "INSPECTING", "QUOTED", "APPROVED", "IN_PROGRESS", "WAITING_FOR_PARTS", "ON_HOLD"}
)

#: Trạng thái phiếu còn chiếm thời gian của kỹ thuật viên.
OPEN_ORDER_CODES = frozenset(
    {"RECEIVED", "INSPECTING", "QUOTED", "APPROVED", "IN_PROGRESS", "WAITING_FOR_PARTS", "ON_HOLD"}
)


def status_label(code: str | None) -> str:
    """Nhãn tiếng Việt của một mã trạng thái."""
    return STATUS_LABELS.get((code or "").upper(), "")


def resolve_status_code(value: Any, field: str = "Trạng thái") -> str:
    """Chuẩn hóa mã trạng thái hoặc nhãn cũ sang mã chuẩn."""
    text = str(value or "").strip()
    if not text:
        raise BadRequestError(f"{field} không được để trống")
    code = text.upper()
    if code in STATUS_DEFINITIONS:
        return code
    code = LABEL_TO_CODE.get(text) or _LABEL_LOOKUP.get(text.casefold())
    if code:
        return code
    raise BadRequestError(
        f"{field} không hợp lệ: {text}",
        details={"allowed": list(STATUS_CODES)},
    )


def order_status_code(order: dict | sqlite3.Row) -> str:
    """Lấy mã trạng thái của phiếu, tương thích dữ liệu cũ chỉ có cột ``status``."""
    row = dict(order)
    code = str(row.get("status_code") or "").strip().upper()
    if code in STATUS_DEFINITIONS:
        return code
    return resolve_status_code(row.get("status") or "RECEIVED")


def allowed_targets(code: str) -> tuple[str, ...]:
    return TRANSITIONS.get(code, ())


def workflow_definition() -> dict:
    """Mô tả công khai của máy trạng thái cho client/UI."""
    return {
        "statuses": [
            {
                "code": code,
                "label": meta["label"],
                "description": meta["description"],
                "step": meta["step"],
                "terminal": meta["terminal"],
            }
            for code, meta in STATUS_DEFINITIONS.items()
        ],
        "transitions": {
            code: [
                {"code": target, "label": status_label(target)}
                for target in targets
            ]
            for code, targets in TRANSITIONS.items()
        },
        "note_required": sorted(NOTE_REQUIRED),
        "sensitive_actions": {
            "approve_quote": "Admin/Quản lý duyệt báo giá; báo giá phải có hạng mục và tổng tiền > 0.",
            "complete": "Phải có kỹ thuật viên, hạng mục/phụ tùng, ghi chú kiểm tra và báo giá đã duyệt.",
            "deliver": "Phải có hóa đơn của phiếu và hóa đơn đã thanh toán đầy đủ.",
            "cancel": "Phải nhập lý do; không được còn hóa đơn chưa hủy.",
        },
    }


def _quote_state(db: sqlite3.Connection, order_id: int) -> dict:
    """Thông tin báo giá mới nhất/phù hợp nhất của phiếu."""
    rows = [
        dict(row)
        for row in db.execute(
            "SELECT id, version, status, total, valid_until FROM quotes "
            "WHERE repair_order_id=? ORDER BY version DESC, id DESC",
            (order_id,),
        ).fetchall()
    ]
    now = now_utc_iso()
    for row in rows:
        if row.get("valid_until") and row["valid_until"] <= now and row["status"] not in ("Từ chối", "Hết hiệu lực"):
            row["status"] = "Hết hiệu lực"
    approved = next((row for row in rows if row["status"] == "Đã duyệt"), None)
    open_quote = next(
        (row for row in rows if row["status"] in ("Nháp", "Chờ duyệt")), None
    )
    ready = next(
        (
            row
            for row in rows
            if row["status"] in ("Nháp", "Chờ duyệt", "Đã duyệt")
            and int(row["total"] or 0) > 0
        ),
        None,
    )
    return {
        "latest": rows[0] if rows else None,
        "approved": approved,
        "open": open_quote,
        "ready": ready,
    }


def _invoice_state(db: sqlite3.Connection, order_id: int) -> dict:
    rows = [
        dict(row)
        for row in db.execute(
            "SELECT id, code, status, total, paid_amount FROM invoices "
            "WHERE repair_order_id=? ORDER BY id DESC",
            (order_id,),
        ).fetchall()
    ]
    active = [row for row in rows if row["status"] != "Đã hủy"]
    paid = [
        row
        for row in active
        if row["status"] == "Đã thanh toán"
        and int(row["paid_amount"] or 0) >= int(row["total"] or 0)
    ]
    return {"all": rows, "active": active, "paid": paid}


def _blocker(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def transition_blockers(
    db: sqlite3.Connection, order: dict | sqlite3.Row, target_code: str
) -> list[dict]:
    """Trả về danh sách điều kiện chưa đạt để chuyển sang ``target_code``."""
    row = dict(order)
    current = order_status_code(row)
    target = resolve_status_code(target_code, "Trạng thái đích")
    if target == current:
        return [_blocker("same_status", "Phiếu đã ở trạng thái này.")]
    if target not in TRANSITIONS.get(current, ()):
        return [
            _blocker(
                "invalid_transition",
                f"Không thể chuyển từ “{status_label(current)}” sang "
                f"“{status_label(target)}”.",
            )
        ]

    blockers: list[dict] = []
    quotes = _quote_state(db, int(row["id"]))
    invoice = _invoice_state(db, int(row["id"]))

    if target in ("INSPECTING", "QUOTED", "APPROVED", "IN_PROGRESS", "WAITING_FOR_PARTS", "COMPLETED"):
        if row.get("km_in") is None:
            blockers.append(_blocker("missing_mileage", "Chưa ghi số km tại thời điểm tiếp nhận."))
        if not str(row.get("initial_condition") or "").strip():
            blockers.append(_blocker("missing_condition", "Chưa ghi tình trạng ban đầu của xe."))
        if not str(row.get("customer_request") or "").strip():
            blockers.append(_blocker("missing_request", "Chưa ghi yêu cầu của khách hàng."))
        if not str(row.get("technician") or "").strip():
            blockers.append(_blocker("missing_technician", "Chưa phân công kỹ thuật viên."))

    if target in ("QUOTED", "APPROVED", "IN_PROGRESS", "WAITING_FOR_PARTS", "COMPLETED"):
        if not str(row.get("inspection_notes") or "").strip():
            blockers.append(_blocker("missing_inspection", "Chưa ghi chú kiểm tra kỹ thuật."))

    if target in ("QUOTED", "APPROVED", "IN_PROGRESS", "WAITING_FOR_PARTS", "COMPLETED"):
        if not quotes["ready"]:
            blockers.append(_blocker("missing_quote", "Chưa có báo giá hợp lệ (có hạng mục và tổng tiền > 0)."))

    if target in ("APPROVED", "COMPLETED"):
        if not quotes["approved"]:
            blockers.append(_blocker("quote_not_approved", "Báo giá của phiếu chưa được duyệt."))
        elif quotes["open"] and quotes["approved"].get("version", 0) < quotes["open"].get("version", 0):
            blockers.append(
                _blocker("newer_quote_open", "Có báo giá mới hơn chưa được duyệt. Hãy xử lý báo giá mới trước.")
            )

    if target in ("IN_PROGRESS", "WAITING_FOR_PARTS", "COMPLETED"):
        if not quotes["approved"]:
            blockers.append(_blocker("quote_not_approved", "Báo giá của phiếu chưa được duyệt."))

    if target == "COMPLETED":
        items = int(
            db.execute(
                "SELECT COUNT(*) FROM repair_order_items WHERE repair_order_id=?",
                (row["id"],),
            ).fetchone()[0]
        )
        parts = int(
            db.execute(
                "SELECT COUNT(*) FROM repair_order_parts WHERE repair_order_id=?",
                (row["id"],),
            ).fetchone()[0]
        )
        if items + parts == 0:
            blockers.append(_blocker("missing_items", "Chưa có hạng mục dịch vụ hoặc phụ tùng đã dùng."))

    if target == "DELIVERED":
        if not invoice["active"]:
            blockers.append(_blocker("missing_invoice", "Chưa có hóa đơn cho phiếu sửa chữa."))
        elif not invoice["paid"] and int(row.get("total") or 0) > 0:
            blockers.append(_blocker("invoice_unpaid", "Hóa đơn chưa được thanh toán đầy đủ."))

    if target == "CANCELLED":
        if invoice["active"]:
            blockers.append(
                _blocker(
                    "active_invoice",
                    "Phiếu còn hóa đơn chưa hủy. Hãy hủy hóa đơn trước khi hủy phiếu.",
                )
            )

    return blockers


def transition_payload(db: sqlite3.Connection, order: dict | sqlite3.Row) -> dict:
    """Trạng thái hiện tại + các bước chuyển hợp lệ kèm điều kiện còn thiếu."""
    current = order_status_code(order)
    transitions = []
    for target in allowed_targets(current):
        blockers = transition_blockers(db, order, target)
        transitions.append(
            {
                "code": target,
                "label": status_label(target),
                "enabled": not blockers,
                "blockers": blockers,
            }
        )
    return {
        "status_code": current,
        "status": status_label(current),
        "allowed_transitions": transitions,
    }


def ensure_status_history(
    db: sqlite3.Connection, order_id: int, order: dict | sqlite3.Row | None = None
) -> None:
    """Bảo đảm phiếu có dòng lịch sử khởi tạo (kể cả dữ liệu seed/cũ)."""
    row = dict(order) if order is not None else None
    if row is None:
        found = db.execute("SELECT * FROM repair_orders WHERE id=?", (order_id,)).fetchone()
        if not found:
            return
        row = dict(found)
    if db.execute(
        "SELECT 1 FROM repair_order_status_history WHERE repair_order_id=? LIMIT 1",
        (order_id,),
    ).fetchone():
        return
    code = order_status_code(row)
    author_id = row.get("advisor_id")
    author_name = ""
    if author_id:
        user = db.execute("SELECT full_name FROM users WHERE id=?", (author_id,)).fetchone()
        author_name = user["full_name"] if user else ""
    db.execute(
        "INSERT INTO repair_order_status_history"
        "(repair_order_id, from_status, to_status, note, changed_by, changed_by_name, created_at) "
        "VALUES(?, '', ?, 'Khởi tạo phiếu', ?, ?, ?)",
        (
            order_id,
            code,
            author_id,
            author_name,
            row.get("received_at") or row.get("opened_at") or now_utc_iso(),
        ),
    )


def change_status(
    db: sqlite3.Connection,
    order_id: int,
    target_code: str,
    note: str,
    user: dict,
) -> dict:
    """Chuyển trạng thái phiếu trong transaction hiện tại.

    Hàm ném ``BadRequestError`` nếu cạnh không hợp lệ hoặc chưa đủ điều kiện.
    """
    order_row = db.execute("SELECT * FROM repair_orders WHERE id=?", (order_id,)).fetchone()
    if not order_row:
        raise BadRequestError("Không tìm thấy phiếu sửa chữa")
    order = dict(order_row)
    current = order_status_code(order)
    target = resolve_status_code(target_code, "Trạng thái đích")
    note = (note or "").strip()

    if target in NOTE_REQUIRED and len(note) < 2:
        raise BadRequestError(
            "Vui lòng nhập lý do khi chuyển sang trạng thái này.",
            details={"field": "note", "min_length": 2},
        )

    blockers = transition_blockers(db, order, target)
    if blockers:
        raise BadRequestError(
            "Chưa đủ điều kiện chuyển trạng thái: "
            + " ".join(item["message"] for item in blockers),
            details={"blockers": blockers},
        )

    ensure_status_history(db, order_id, order)
    now = now_utc_iso()
    fields = ["status=?", "status_code=?"]
    params: list[Any] = [status_label(target), target]
    if target == "COMPLETED":
        fields.extend(["completed_at=?", "closed_at=COALESCE(closed_at, ?)"])
        params.extend([now, now])
    elif target == "DELIVERED":
        fields.extend(["delivered_at=?", "closed_at=COALESCE(closed_at, ?)"])
        params.extend([now, now])
    elif target == "CANCELLED":
        fields.extend(["closed_at=?", "cancel_reason=?"])
        params.extend([now, note])
    db.execute(
        f"UPDATE repair_orders SET {', '.join(fields)} WHERE id=?",
        (*params, order_id),
    )
    db.execute(
        "INSERT INTO repair_order_status_history"
        "(repair_order_id, from_status, to_status, note, changed_by, changed_by_name, created_at) "
        "VALUES(?, ?, ?, ?, ?, ?, ?)",
        (
            order_id,
            current,
            target,
            note,
            user.get("id"),
            user.get("full_name", ""),
            now,
        ),
    )
    if target == "COMPLETED":
        record_repair_history(db, order_id)
        from .repair_knowledge import capture_completed_case
        capture_completed_case(db, order_id)
    return dict(db.execute("SELECT * FROM repair_orders WHERE id=?", (order_id,)).fetchone())


def history_for(db: sqlite3.Connection, order_id: int, order: dict | None = None) -> list[dict]:
    """Lịch sử trạng thái theo thứ tự thời gian, kèm nhãn tiếng Việt."""
    ensure_status_history(db, order_id, order)
    rows = [
        dict(row)
        for row in db.execute(
            "SELECT * FROM repair_order_status_history "
            "WHERE repair_order_id=? ORDER BY id",
            (order_id,),
        ).fetchall()
    ]
    for row in rows:
        row["from_status_label"] = status_label(row.get("from_status"))
        row["to_status_label"] = status_label(row.get("to_status"))
    return rows
