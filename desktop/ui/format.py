"""Display formatting shared by the screens."""

from decimal import Decimal, InvalidOperation


def money(value) -> str:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "—"
    return f"${amount:,.2f}"


def rating(average, count: int) -> str:
    if not count:
        return "No reviews yet"
    try:
        avg = float(average)
    except (TypeError, ValueError):
        avg = 0.0
    full = int(round(avg))
    stars = "★" * full + "☆" * (5 - full)
    return f"{stars}  {avg:.1f} ({count})"


def availability(available: bool, stock: int | None = None) -> str:
    if not available:
        return "Out of stock"
    if stock is not None and stock <= 5:
        return f"Only {stock} left"
    return "In stock"
