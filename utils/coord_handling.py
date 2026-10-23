def toBranchCodeSlotRowTier(coordinates: list[str] | tuple[str, ...]) -> tuple[str, str, str, str, str]:
    """Reorder one-based strings without parsing incomplete or invalid values."""
    return coordinates[0], coordinates[1], coordinates[3], coordinates[2], coordinates[4]

def toIDSlotRowTier(coordinates: tuple[str,str,str,str])->tuple[str,str,str,str]:
    return coordinates[0], coordinates[2], coordinates[1], coordinates[3]
def toIDSlotRow(coordinates: tuple[str,str,str]) -> tuple[str,str,str]:
    return coordinates[0], coordinates[2], coordinates[1]

def toStrSlotRow(coordinates: tuple[str, int, int]) -> tuple[str, str, str]:
    """Display zero-based stack coordinates as one-based block, slot, row."""
    return coordinates[0], str(coordinates[2] + 1), str(coordinates[1] + 1)

def toStrSlotRowTier(coordinates: tuple[str,int,int,int]) -> tuple[str,str,str,str]:
    return coordinates[0], str(coordinates[2] + 1), str(coordinates[1] + 1), str(coordinates[3] + 1)
