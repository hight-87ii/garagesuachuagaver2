"""Tiện ích tiền tệ cho GarageAI.

Quy ước: mọi giá trị tiền được lưu trong cơ sở dữ liệu dưới dạng **số nguyên đồng**
(đơn vị nhỏ nhất của VND). Không dùng kiểu floating-point để tính tiền; các phép
tính trung gian dùng :class:`decimal.Decimal` rồi làm tròn về đồng.
"""

import os
from decimal import Decimal, ROUND_HALF_UP

VND = Decimal("1")
DEFAULT_TAX_RATE = Decimal(os.getenv("QUOTE_TAX_RATE", "0.08"))
DEFAULT_DISCOUNT_RATE = Decimal(os.getenv("QUOTE_DRAFT_DISCOUNT_RATE", "0"))
if not Decimal("0") <= DEFAULT_TAX_RATE <= Decimal("1"):
    raise ValueError("QUOTE_TAX_RATE phải nằm trong khoảng 0..1")
if not Decimal("0") <= DEFAULT_DISCOUNT_RATE <= Decimal("1"):
    raise ValueError("QUOTE_DRAFT_DISCOUNT_RATE phải nằm trong khoảng 0..1")


def to_vnd(value) -> int:
    """Chuẩn hóa một giá trị tiền bất kỳ về số nguyên đồng."""
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        value = Decimal(str(value))
    elif not isinstance(value, Decimal):
        value = Decimal(str(value).replace(",", "").replace(" ", ""))
    return int(value.quantize(VND, rounding=ROUND_HALF_UP))


def as_decimal(value) -> Decimal:
    """Trả về Decimal đồng để thực hiện phép tính an toàn."""
    return Decimal(to_vnd(value))


def line_total(quantity, unit_price) -> int:
    """Thành tiền một dòng = số lượng × đơn giá (đã làm tròn về đồng)."""
    if quantity is None or unit_price is None:
        return 0
    quantity_decimal = Decimal(str(quantity))
    return to_vnd(quantity_decimal * as_decimal(unit_price))


def tax_for(subtotal, rate=DEFAULT_TAX_RATE) -> int:
    """Tiền thuế = tạm tính × thuế suất."""
    return to_vnd(as_decimal(subtotal) * Decimal(str(rate)))


def with_tax(subtotal, rate=DEFAULT_TAX_RATE) -> tuple[int, int, int]:
    """Trả về bộ (tạm tính, thuế, tổng) đều là số nguyên đồng."""
    base = to_vnd(subtotal)
    tax = tax_for(base, rate)
    return base, tax, base + tax
