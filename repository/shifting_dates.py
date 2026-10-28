"""Daily report dates use midnight WIB (UTC+7), independent of host timezone."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation

from .loader import InputError


WIB = timezone(timedelta(hours=7), "WIB")


def today_wib():
    return datetime.now(WIB).date()


def report_date(value, *, month=None, excel=False, date1904=False):
    text = "" if value is None else str(value).strip()
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            day = datetime.strptime(text, pattern).date()
        except ValueError:
            continue
        if month is None or day.strftime("%Y-%m") == month:
            return day
    if excel:
        try:
            serial = Decimal(text)
            if serial.is_finite() and serial == int(serial) and serial >= 0:
                epoch = date(1904, 1, 1) if date1904 else date(1899, 12, 30)
                day = epoch + timedelta(days=int(serial))
                if month is None or day.strftime("%Y-%m") == month:
                    return day
        except (InvalidOperation, ValueError, OverflowError):
            pass
    raise InputError(f"Invalid daily report date {value!r}; provide a date in the report month.")


def daily_boundaries(day):
    start = int(datetime.combine(day, time.min, WIB).timestamp())
    return start, start + 86400
