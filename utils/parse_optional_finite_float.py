import math


def parse_optional_finite_float(raw) -> float | None:
    """Return a finite float, or None for missing or invalid input."""
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value
