from .stack import Stack
from .equipment import *

class Block:
    id: str
    branch: str
    code: str
    slots: list[list[Stack]]
    rtg: RTG|None
    loaders: list[Loader]
    pos_x: int
    pos_y: int

    def __init__(self,
                 BRANCH_ID: str,
                 BLOCK_ID: str,
                 BLOCK_CODE: str,
                 SLOT_COUNT: str,
                 ROW_COUNT: str,
                 MAX_TIER: str,
                 POS_X:str,
                 POS_Y:str,

                 **_kwargs
                 ):
        self.id = BLOCK_ID
        self.branch = BRANCH_ID
        self.code = BLOCK_CODE
        self.slots = []
        self.rtg = None
        self.loaders = []
        self.pos_x = int(POS_X)
        self.pos_y = int(POS_Y)

        # assign slots
        for row in range(int(ROW_COUNT)):
            stacks = []
            for slot in range(int(SLOT_COUNT)):
                stacks.append(Stack(int(MAX_TIER), (self.id,row,slot)))
            self.slots.append(stacks)

    def getId(self) -> str: return self.id
    def getBranch(self) -> str: return self.branch
    def getCode(self) -> str: return self.code
    def getSlots(self) -> list[list[Stack]]:return self.slots
    def getStack(self, row:int, slot:int) -> Stack: return self.slots[row][slot]
    def getPosX(self) -> int: return self.pos_x
    def getPosY(self) -> int: return self.pos_y
    def getLoaders(self) -> list[Loader]: return self.loaders
    def addLoader(self,loader: Loader): self.loaders.append(loader)
    def removeLoader(self,loader:Loader): self.loaders.remove(loader)

    def anomalies(self) -> list[Stack]:
        anomalies = []
        for slot in self.slots:
            for stack in slot:
                if stack.anomaly(): anomalies.append(stack)
        return anomalies
    def print(self):
        print("ID:",self.id," Branch/Code:",self.branch + "/" + self.getCode())
        if self.rtg is not None: self.rtg.print()
        if self.loaders: [x.print() for x in self.loaders]
        for slot in self.slots:
            for tier in slot:
                tier.printOccupancy()
            print()

    def getRTG(self) -> RTG | None: return self.rtg
    def setRTG(self, rtg: RTG): self.rtg = rtg

    # returns if true if it's safe to get put something a container in that stack
    def safeMaxima(self,row:int,slot:int) -> bool:
        maxMaxima = 2
        stack = self.slots[row][slot]
        tier = stack.availableTierInt()
        mode = stack.getMode()

        if tier < maxMaxima: return True

        # assumes that only odd-num stack40s are called, hence even-num stack40s raise error
        if stack.getEven() and mode == '40': raise IndexError

        # up
        if self.compareTier(row, slot, row + 1, slot) < maxMaxima:
            return True
        # down
        elif self.compareTier(row, slot, row - 1, slot) < maxMaxima:
            return True
        # right
        elif self.compareTier(row, slot, row, slot + 1) < maxMaxima:
            return True
        elif stack.getMode() == '20':
            # left for 20
            if self.compareTier(row, slot, row, slot - 1) < maxMaxima:
                return True
        # for 40
        elif stack.getMode() == '40':
            # left, left
            if self.compareTier(row, slot, row, slot - 2) < maxMaxima:
                return True
            # left, up
            elif self.compareTier(row, slot, row + 1, slot - 1) < maxMaxima:
                return True
            # left, down
            elif self.compareTier(row, slot, row - 1, slot - 1) < maxMaxima:
                return True
        return False

    #row1,slot1 must exist, row2,slot2 doesn't need to
    def compareTier(self,row1:int,slot1:int,row2:int,slot2:int) -> int:
        tier1 = self.slots[row1][slot1].availableTierInt()
        try:
            tier2 = self.slots[row2][slot2].availableTierInt()

            # stack2 is full or is removed_slot
            if tier2 is None:
                return tier1 - self.slots[row2][slot2].getMaxTier()
            # tier1 and tier2 is available
            elif tier1 is not None and tier2 is not None:
                return tier1 - tier2

        #stack2 is out of range
        except IndexError:
            pass
        return tier1 + 1