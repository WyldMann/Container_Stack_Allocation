from .stack import Stack
from .container import DummyContainer
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

    def parameterCompliance(self) -> float | None:
        """Average each container's best normalized anchor-stack parameter score.

        Containers without parameters contribute zero. Empty blocks return None.
        Parameter criteria and nonnegative scores must remain as initialized.
        """
        total_compliance = 0.0
        container_count = 0

        for row_stacks in self.slots:
            for slot_index, stack in enumerate(row_stacks):
                for container in stack.getContainers():
                    if container is None or isinstance(container, DummyContainer):
                        continue
                    # Count 40-foot containers only at their odd-indexed anchor.
                    if container.getContSize() == "40" and slot_index % 2 == 0:
                        continue

                    total_compliance += max(
                        (parameter.compliance(container)
                         for parameter in stack.getParameters()),
                        default=0.0,
                    )
                    container_count += 1

        return total_compliance / container_count if container_count else None

    def getRTG(self) -> RTG | None: return self.rtg
    def setRTG(self, rtg: RTG): self.rtg = rtg

    def safeMaxima(
            self, row_index: int, slot_index: int, max_maxima: int = 2,
            *, neighbors: tuple[str, ...] = ("up", "down"),
    ) -> bool:
        """Allow placement within max_maxima tiers above an enabled neighbor.

        An isolated stack may reach max_maxima tiers without neighbor support.
        Up/down mean the previous/next row, matching the yard grid. Both cells
        along a 40-foot footprint are considered on each enabled row side.
        """
        stack = self.slots[row_index][slot_index]
        tier_index = stack.occupiedHeight()

        if tier_index < max_maxima: return True
        return self.pyramidHeightDifference(row_index, slot_index, neighbors=neighbors) <= max_maxima

    def pyramidHeightDifference(
            self, row_index: int, slot_index: int, *,
            neighbors: tuple[str, ...] = ("up", "down"),
            container_size: str | None = None,
    ) -> int:
        """Post-placement height above the tallest considered neighbor.

        Ground (height zero) supplies the baseline at edges, with no enabled
        neighbors, or where all considered neighbors are empty.
        """
        stack = self.slots[row_index][slot_index]
        mode = container_size if container_size is not None else stack.getMode()
        if stack.getEven() and mode == '40': raise IndexError

        first_slot = slot_index - 1 if mode == '40' else slot_index
        sides = {
            "up": tuple((row_index - 1, slot) for slot in range(first_slot, slot_index + 1)),
            "down": tuple((row_index + 1, slot) for slot in range(first_slot, slot_index + 1)),
            "left": ((row_index, first_slot - 1),),
            "right": ((row_index, slot_index + 1),),
        }
        support_height = max((
            self.slots[row][slot].occupiedHeight()
            for direction in neighbors for row, slot in sides[direction]
            if 0 <= row < len(self.slots) and 0 <= slot < len(self.slots[row])
        ), default=0)
        return max(0, stack.occupiedHeight() + 1 - support_height)

    #row1,slot1 must exist, row2,slot2 doesn't need to
    def compareTier(self,first_row_index:int,first_slot_index:int,second_row_index:int,second_slot_index:int) -> int:
        first_tier_index = self.slots[first_row_index][first_slot_index].occupiedHeight()
        # Negative indices are outside the block, not opposite-edge neighbors.
        if not 0 <= second_row_index < len(self.slots): return first_tier_index + 1
        if not 0 <= second_slot_index < len(self.slots[second_row_index]): return first_tier_index + 1
        neighbor = self.slots[second_row_index][second_slot_index]
        return first_tier_index - neighbor.occupiedHeight()
