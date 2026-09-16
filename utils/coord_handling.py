def toIDSlotRowTier(coord: tuple[str,str,str,str])->tuple[str,str,str,str]:
    return coord[0], coord[2], coord[1], coord[3]
def toIDSlotRow(coord: tuple[str,str,str]) -> tuple[str,str,str]:
    return coord[0], coord[2], coord[1]
def strRowSlotTier(coord: tuple[str,int,int,int]) -> tuple[str,str,str,str]:
    return coord[0], str(coord[2] + 1), str(coord[1] + 1), str(coord[3] + 1)