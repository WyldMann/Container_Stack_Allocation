from datetime import datetime

def parse_datetime(value: str) -> datetime | None:
    formats = [
        "%d-%m-%Y %H:%M",  # 26-08-2026 11:25
        "%d/%m/%Y %H:%M",  # 7/8/2026 8:28
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            print(str, "DateTime not recognized")
    return None
