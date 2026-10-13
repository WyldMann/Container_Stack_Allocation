from .stack import Stack
from .equipment import *

class Block:
    block_id: str
    branch_id: str
    block_code: str
    slots: list[list[Stack]]
    rtg: RTG|None
    loaders: list[Loader]
    pos_x: int
    pos_y: int

    def __init__(self,
                 branch_id: str,
                 block_id: str,
                 block_code: str,
                 slot_count: str,
                 row_count: str,
                 max_tier: str,
                 pos_x:str,
                 pos_y:str,

                 **_kwargs
                 ):
        self.block_id = block_id
        self.branch_id = branch_id
        self.block_code = block_code
        self.slots = []
        self.rtg = None
        self.loaders = []
        self.pos_x = int(pos_x)
        self.pos_y = int(pos_y)

        # assign slots
        for row_index in range(int(row_count)):
            stacks = []
            for slot_index in range(int(slot_count)):
                stacks.append(Stack(int(max_tier), (self.block_id,row_index,slot_index)))
            self.slots.append(stacks)

    def getId(self) -> str: return self.block_id
    def getBranch(self) -> str: return self.branch_id
    def getCode(self) -> str: return self.block_code
    def getSlots(self) -> list[list[Stack]]:return self.slots
    def getStack(self, row_index:int, slot_index:int) -> Stack: return self.slots[row_index][slot_index]
    def getPosX(self) -> int: return self.pos_x
    def getPosY(self) -> int: return self.pos_y
    def getLoaders(self) -> list[Loader]: return self.loaders
    def addLoader(self,loader: Loader): self.loaders.append(loader)
    def removeLoader(self,loader:Loader): self.loaders.remove(loader)

    def anomalies(self) -> list[Stack]:
        anomalies = []
        for row_stacks in self.slots:
            for stack in row_stacks:
                if stack.anomaly(): anomalies.append(stack)
        return anomalies

    def getRTG(self) -> RTG | None: return self.rtg
    def setRTG(self, rtg: RTG): self.rtg = rtg

    # returns if true if it's safe to get put something a container in that stack
    def safeMaxima(self,row_index:int,slot_index:int) -> bool:
        max_maxima = 2
        stack = self.slots[row_index][slot_index]
        tier_index = stack.availableTierInt()
        mode = stack.getMode()

        if tier_index < max_maxima: return True

        # assumes that only odd-num stack40s are called, hence even-num stack40s raise error
        if stack.getEven() and mode == '40': raise IndexError

        # up
        if self.compareTier(row_index, slot_index, row_index + 1, slot_index) < max_maxima:
            return True
        # down
        elif self.compareTier(row_index, slot_index, row_index - 1, slot_index) < max_maxima:
            return True
        # right
        elif self.compareTier(row_index, slot_index, row_index, slot_index + 1) < max_maxima:
            return True
        elif stack.getMode() == '20':
            # left for 20
            if self.compareTier(row_index, slot_index, row_index, slot_index - 1) < max_maxima:
                return True
        # for 40
        elif stack.getMode() == '40':
            # left, left
            if self.compareTier(row_index, slot_index, row_index, slot_index - 2) < max_maxima:
                return True
            # left, up
            elif self.compareTier(row_index, slot_index, row_index + 1, slot_index - 1) < max_maxima:
                return True
            # left, down
            elif self.compareTier(row_index, slot_index, row_index - 1, slot_index - 1) < max_maxima:
                return True
        return False

    #row1,slot1 must exist, row2,slot2 doesn't need to
    def compareTier(self,first_row_index:int,first_slot_index:int,second_row_index:int,second_slot_index:int) -> int:
        first_tier_index = self.slots[first_row_index][first_slot_index].availableTierInt()
        # Negative indices are outside the block, not opposite-edge neighbors.
        if not 0 <= second_row_index < len(self.slots): return first_tier_index + 1
        if not 0 <= second_slot_index < len(self.slots[second_row_index]): return first_tier_index + 1
        try:
            second_tier_index = self.slots[second_row_index][second_slot_index].availableTierInt()

            # stack2 is full or is removed_slot
            if second_tier_index is None:
                return first_tier_index - self.slots[second_row_index][second_slot_index].getMaxTier()
            # tier1 and tier2 is available
            elif first_tier_index is not None and second_tier_index is not None:
                return first_tier_index - second_tier_index

        #stack2 is out of range
        except IndexError:
            pass
        return first_tier_index + 1
