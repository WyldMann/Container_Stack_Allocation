from datetime import datetime

def parse_datetime(value: str) -> datetime:
    if not value or not value.strip():
        return datetime.min

    formats = [
        "%d-%m-%Y %H:%M",
        "%d/%m/%Y %H:%M",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    raise ValueError(f"Invalid datetime format: {value}")