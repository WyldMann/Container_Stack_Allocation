def toIDSlotRowTier(coordinates: tuple[str,str,str,str])->tuple[str,str,str,str]:
    return coordinates[0], coordinates[2], coordinates[1], coordinates[3]
def toIDSlotRow(coordinates: tuple[str,str,str]) -> tuple[str,str,str]:
    return coordinates[0], coordinates[2], coordinates[1]
def toStrSlotRowTier(coordinates: tuple[str,int,int,int]) -> tuple[str,str,str,str]:
    return coordinates[0], str(coordinates[2] + 1), str(coordinates[1] + 1), str(coordinates[3] + 1)