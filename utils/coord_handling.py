def toIDSlotRowTier(blockID_row_slot_tier: tuple[str,str,str,str])->tuple[str,str,str,str]:
    return blockID_row_slot_tier[0], blockID_row_slot_tier[2], blockID_row_slot_tier[1], blockID_row_slot_tier[3]
def toIDSlotRow(blockID_row_slot: tuple[str,str,str]) -> tuple[str,str,str]:
    return blockID_row_slot[0], blockID_row_slot[2], blockID_row_slot[1]
def toStrSlotRowTier(blockID_rowInt_slotInt_tierInt: tuple[str,int,int,int]) -> tuple[str,str,str,str]:
    return blockID_rowInt_slotInt_tierInt[0], str(blockID_rowInt_slotInt_tierInt[2] + 1), str(blockID_rowInt_slotInt_tierInt[1] + 1), str(blockID_rowInt_slotInt_tierInt[3] + 1)