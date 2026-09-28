from argparse import ArgumentError
from datetime import datetime

def parse_datetime(value: str) -> datetime:
    if not value or value == "" or not value.strip():
        return datetime.min

    # value is in Unix Timestamp
    try:
        value_unix = int(value)
    except ValueError:
        pass
    else:
        # Unix seconds
        try:
            return datetime.fromtimestamp(value_unix)
        # Unix ms
        except OSError:
            return datetime.fromtimestamp(value_unix/1000)

    # value is in String
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