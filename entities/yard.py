from .container import Container, DummyContainer
from .parameter import Parameter

class Stack:
    containers: list[Container | None]
    parameters: list[Parameter]
    maxTier: int
    coords: tuple[str,int,int]
    mode: str
    even: bool

    def __init__(self,
                 maxTier: int,
                 coords: tuple[str,int,int],
                 parameters = None):

        if parameters is None:
            parameters = []

        self.containers = [None] * maxTier
        self.parameters = parameters
        self.maxTier = maxTier
        self.coords = coords
        self.mode = '0'   # '0' = None, '20' = cont20, '40' = cont40. which cont type it serves
        self.even = self.coords[2] % 2 == 0     # cont40 is only assigned to evens in 1-based indexing, aka odd here

    def getContainers(self) -> list[Container | None]: return self.containers
    def getParameters(self) -> list[Parameter]: return self.parameters
    def getContainer(self, tier: int) -> Container | None: return self.containers[tier]
    def getCoords(self) -> tuple[str,int,int]: return self.coords
    def getMode(self) -> str: return self.mode
    def getEven(self) -> bool: return self.even

    def setMode(self, mode: str): self.mode = mode

    def isTierEmpty(self, tier: int) -> bool:
        return self.containers[tier] is None

    def availableTierInt(self) -> int | None:
        for tierInt, container in enumerate(self.containers):
            if container is None:
                return tierInt
        return None

    def addContainer(self, container: Container, tier: int):
        # if first container in stack, set its mode
        if tier == 0:
            mode = container.getContSize()
            self.setMode(mode)
        if self.isTierEmpty(tier):
            self.containers[tier] = container
        else:
            raise NotImplementedError
    def replaceContainer(self, container: Container, tier: int):
        self.containers[tier] = container

    def removeContainer(self, tier: int):
        self.containers[tier] = None
    def addParameter(self, parameter: Parameter):
        self.parameters.append(parameter)

    # returns number of empty vacancies
    def vacancy(self):
        return self.containers.count(None)

    def occupancy(self):
        return self.maxTier - self.containers.count(None)

    # returns true if there's floating containers
    def anomaly(self):
        doneStacking = False
        for x in self.containers:
            if x is not None:
                if doneStacking: return True
            else: doneStacking = True
        return False

    def anomalyDummyFill(self,dummy: DummyContainer):
        startStacking = False
        for x in reversed(range(len(self.containers))):
            if self.containers[x] is not None:
                startStacking = True
            else:
                if startStacking:
                    self.containers[x] = dummy
                    dummy.addCoordList(self.coords,x)

    # use this instead if return type is definitely a container and not None
    def getContainerTrue(self,tier:int) -> Container:
        container = self.containers[tier]
        if container is not None:
            return container
        else:
            raise NotImplementedError

    # used when correcting anomaly
    def normalize(self):
            while self.anomaly():
                for x in range(len(self.containers) - 1):

                    # a roundabout way to swap values, without raising possible type mismatch
                    container = self.containers[x + 1]
                    if self.containers[x] is None and container is not None:
                        self.containers[x] = container
                        self.containers[x + 1] = None
                        container.setTierInt(x)     #update container tier

    # returns tier score
    def score(self,container) -> float | None:
        return max(x.evaluate(container) for x in self.parameters) if self.parameters != [] else 0

    def makeVoid(self):
        self.maxTier = 0
        self.containers = []

    def printVacancy(self):
        print(self.vacancy(), end = " ")

    def printOccupancy(self):
        print(self.occupancy(), self.getMode()[0], end = " ", sep = "")

    def printContents(self):
        for x in self.containers:
            if x is not None:
                print(x, end = " ")
            else:
                print("None", end = " ")
        print()

class Block:
    id: str
    branch: str
    code: str
    slots: list[list[Stack]]

    def __init__(self,
                 BRANCH_ID: str,
                 BLOCK_ID: str,
                 BLOCK_CODE: str,
                 SLOT_COUNT: str,
                 ROW_COUNT: str,
                 MAX_TIER: str,

                 **_kwargs
                 ):
        self.id = BLOCK_ID
        self.branch = BRANCH_ID
        self.code = BLOCK_CODE
        self.slots = []
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
    def anomalies(self) -> list[Stack]:
        anomalies = []
        for slot in self.slots:
            for stack in slot:
                if stack.anomaly(): anomalies.append(stack)
        return anomalies
    def print(self):
        print("ID:",self.id," Branch/Code:",self.branch + "/" + self.getCode())
        for slot in self.slots:
            for tier in slot:
                tier.printOccupancy()
            print()

# in this scope, there's only one yard
class Yard:
    blocks_by_id: dict[str,Block]
    blocks_by_code: dict[tuple[str,str], Block] # {(BRANCH_ID,BLOCK_CODE): Block}
    params: dict[str,Parameter]
    bad_data: BadYardData
    containers: dict[str,Container]
    dummy: DummyContainer

    #block and parameters input: {"args":"values",...}
    #removed_slots_input: [(block_id, row_no, slot_no),...]
    #yard planning: {param_id:[(block_id, row_no, slot_no),[...],...],...}
    def __init__(self,
                 yard_block_input: list[dict[str,str]],
                 removed_slots_input: list[tuple[str,int,int]] | None = None,
                 parameters_input: list[dict[str,str]] | None = None,
                 yard_planning_input: dict[str,list[tuple[str,int,int]]] | None = None,
                 container_input: list[dict[str,str]] | None = None) -> None:

        if removed_slots_input is None: removed_slots_input = []
        if parameters_input is None: parameters_input = []
        if yard_planning_input is None: yard_planning_input = {}
        if container_input is None: container_input = []

        self.bad_data = BadYardData(sum(len(yp) for yp in yard_planning_input.values()),len(container_input))
        self.dummy = DummyContainer()

        # initialize blocks and constructs 2 dict attributes to keep track
        self.blocks_by_id = {}
        self.blocks_by_code = {}

        for inp in yard_block_input:
            block = Block(**inp)
            self.blocks_by_id[block.getId()] = block
            self.blocks_by_code[(block.getBranch(),block.getCode())] = block

        # remove the slots as per input
        for removed_slot in removed_slots_input:
            self.blocks_by_id[removed_slot[0]].getStack(removed_slot[1],removed_slot[2]).makeVoid()

        # initializes and stores Parameters
        self.params = {}
        for inp in parameters_input:
            param_id = Parameter(**inp)
            self.params[param_id.getId()] = param_id

        # add parameters into stacks
        for param_id in yard_planning_input:
            parameter = self.params[param_id]
            #stack: (block_id, row_no, slot_no)
            for stack in yard_planning_input[param_id]:
                try:
                    self.blocks_by_id[stack[0]].getStack(stack[1],stack[2]).addParameter(parameter)
                except IndexError:
                    self.bad_data.addYPOutOfRange((param_id,stack[0],stack[1],stack[2]))

        # input containers already in the batabase
        self.containers = {}
        for inp in container_input:
            container = Container(**inp)

            # No containers in container_input can be incomplete
            if container.isIncomplete():
                self.bad_data.addIncompleteContainer(container)
                continue

            self.addContainerInput(container)

        self.anomalyCheck()

    def getBadData(self) -> BadYardData: return self.bad_data

    def getBlockByID(self, block_id:str) -> Block:
        return self.blocks_by_id[block_id]
    def getBlockByCode(self, branch:str,code:str) -> Block:
        return self.blocks_by_code[(branch,code)]

    def getBlockBranchCodebyID(self, block_id:str) -> tuple[str,str]:
        return self.blocks_by_id[block_id].getBranch(), self.blocks_by_id[block_id].getCode()
    def getBlockIDbyCode(self, block_id:str) -> str:
        return self.blocks_by_id[block_id].getId()

    def addContainerInput(self,container: Container):
        # validate coordsStr can be found. Otherwise, mark bad_data and move on
        try:
            coordsInt = container.getCoordsInt()
            stack = self.blocks_by_code[(coordsInt[0], coordsInt[1])].getStack(coordsInt[2], coordsInt[3])
            tier = coordsInt[4]
            stackIsEmpty = stack.isTierEmpty(tier)

            # cont40 handling
            stack2 = stack
            stackIsEmpty2 = stackIsEmpty
            if container.getContSize() == '40':
                # cont40 can only be put on (int) odd indexes.
                if stack.getMode() == '20' or stack.getEven():
                    raise IndexError
                stack2 = self.blocks_by_code[(coordsInt[0], coordsInt[1])].getStack(coordsInt[2], coordsInt[3] - 1)
                stackIsEmpty2 = stack2.isTierEmpty(tier)
            # cont20 cannot be put on cont40 stacks
            else:
                if stack.getMode() == '40':
                    raise IndexError

        except (IndexError, KeyError, ValueError):
            self.bad_data.addContainerCoordsInvalid(container)
            return

        # if tier is occupied, the one with most recent move_time takes highest precedence
        if not (stackIsEmpty and stackIsEmpty2):
            # existing container is newer. current container is ignored or current container is 40 cuz i'm not handling that.
            # too much goes into cont40 placement to consider this
            existing_container = stack.getContainerTrue(tier)
            if container.getMoveTime() < existing_container.getMoveTime() and container.getContSize() == '40':
                old_container, new_container = container, existing_container
            # current container is newer. remove existing_container from container dict and add current container to the container dict and the stack
            else:
                old_container, new_container = existing_container, container
                del self.containers[existing_container.getId()]
                self.containers[new_container.getId()] = new_container

            stack.replaceContainer(new_container, tier)
            self.bad_data.addOverlappingContainer(old_container, new_container)

        else:
            stack.addContainer(container, tier)
            if container.getContSize() == '40':
                stack2.addContainer(container, tier)
            self.containers[container.getId()] = container

    def addContainerByCoords(self,container: Container,coords:tuple[str,int,int,int]):
        # add container to the stack
        self.getBlockByID(coords[0]).getStack(coords[1],coords[2]).addContainer(container,coords[3])
        # if containerType = 40 add also add to the next stack
        if container.getContSize() == '40':
            self.getBlockByID(coords[0]).getStack(coords[1],coords[2] - 1).addContainer(container,coords[3])

        # add new coords to container
        container.setCoordsInt(self.getBlockBranchCodebyID(coords[0])+(coords[1],coords[2],coords[3],))

    def anomalyCheck(self):
        for block in self.blocks_by_id.values():
            for stack in block.anomalies():
                self.bad_data.addAnomalousStack(stack)

    # method 1: drop all flying containers
    def fixAnomalies(self):
        while len(self.bad_data.getAnomalousStacks()) != 0:
            self.bad_data.popAnomalousStack().normalize()

    # method 2: fit in dummy containers
    def fillDummyContainer(self) -> None:
        while len(self.bad_data.getAnomalousStacks()) != 0:
            self.bad_data.popAnomalousStack().anomalyDummyFill(self.dummy)

    def print(self):
        for block_id in self.blocks_by_id:
            self.blocks_by_id[block_id].print()

    def assignContainer(self,container: Container):
        coords = ('',-1,-1,-1)
        maxScore = -float("inf")

        for block in self.blocks_by_id.values():
            for row in block.getSlots():
                for slot,stack in enumerate(row):

                    tier = stack.availableTierInt()

                    # if stack is fully occupied
                    if tier is None: continue

                    # must not conflict with stack.mode
                    if container.getContSize() == '40' and stack.getMode() == '20': continue
                    elif container.getContSize() == '20' and stack.getMode() == '40': continue

                    # contsize 40 must be assigned to odd only
                    if container.getContSize() == '40' and stack.getEven(): continue

                    currentCoords = stack.getCoords()
                    # if contsize 40, next slot must be able to accomodate
                    # though if everything goes well it already should be
                    if container.getContSize() == '40':
                        try:
                            # second stack should already be '20
                            currentCoords2 = row[slot - 1]
                        except IndexError:
                            print("uh oh")
                            continue
                        if currentCoords2.availableTierInt() != tier:
                            continue

                    currentScore = stack.score(container)
                    if currentScore is None: continue
                    elif maxScore < currentScore:
                        maxScore = currentScore
                        coords = currentCoords + (tier,)
        if coords == ('',-1,-1,-1):
            print("No Space Found")
            container.print()
            self.print()
            input()

        else:
            self.addContainerByCoords(container,coords)


class BadYardData:
    overlapping_containers: dict[tuple[str,str,str,str,str],set[Container]]
    anomalous_stacks: list[Stack]
    incomplete_containers: list[Container]
    yp_out_of_range: list[tuple[str,str,int,int]]
    container_coords_invalid: list[Container]
    total_yp: int
    total_containers: int

    def __init__(self, total_params: int, total_containers: int):
        self.overlapping_containers = {}
        self.anomalous_stacks = []
        self.incomplete_containers = []
        self.yp_out_of_range = []
        self.container_coords_invalid = []
        self.total_yp = total_params
        self.total_containers = total_containers

    def getAnomalousStacks(self) -> list[Stack]:
        return self.anomalous_stacks
    def getOverlappingContainers(self) -> dict[tuple[str,str,str,str,str],set[Container]]:
        return self.overlapping_containers
    def getIncompleteContainers(self) -> list[Container]:
        return self.incomplete_containers
    def getYPOutOfRange(self) -> list[tuple[str,str,int,int]]:
        return self.yp_out_of_range
    def getContainerCoordsInvalid(self) -> list[Container]:
        return self.container_coords_invalid

    def getTotalYardPlanning(self) -> int:
        return self.total_yp
    def getTotalContainers(self) -> int:
        return self.total_containers
    def getTotalOverlapping(self) -> int:
        return len(self.overlapping_containers)
    def getTotalIncomplete(self) -> int:
        return len(self.incomplete_containers)
    def getTotalYPOutOfRange(self) -> int:
        return len(self.yp_out_of_range)
    def getTotalContainerCoordsInvalid(self) -> int:
        return len(self.container_coords_invalid)
    def getTotalAnomalousStacks(self) -> int:
        return len(self.anomalous_stacks)

    def addOverlappingContainer(self, container1: Container, container2: Container):
        coords = container1.getCoordsStrTuple()
        if coords in self.overlapping_containers:
            self.overlapping_containers[coords].update({container1, container2})
        else:
            self.overlapping_containers[coords] = {container1, container2}
    def addIncompleteContainer(self, container: Container):
        self.incomplete_containers.append(container)
    def addYPOutOfRange(self,yp_item: tuple[str,str,int,int]):
        self.yp_out_of_range.append(yp_item)
    def addContainerCoordsInvalid(self,container:Container):
        self.container_coords_invalid.append(container)
    def addAnomalousStack(self,stack: Stack): self.anomalous_stacks.append(stack)
    def popAnomalousStack(self) -> Stack: return self.anomalous_stacks.pop()


    def printOverlappingContainers(self):
        print("\nOverlapping Containers:")
        for coords, containers in self.overlapping_containers.items():
            print(coords, [str(x) for x in containers])

    def printContainerCoordsInvalid(self):
        print("\nContainer Coordinates Invalid:")
        for x in self.container_coords_invalid:
            print(x.getId(), x.getCoordsStr())

    def printYPOutOfRange(self):
        print("\nYard Planning Out of Range:")
        for yp_item in self.yp_out_of_range:
            print("param_id:",yp_item[0],"block_id:",yp_item[1],"row:",yp_item[2] + 1, "slot:",  yp_item[3] + 1)

    def printAnomalousStacks(self):
        print("\nAnomalous stacks:")
        for x in self.anomalous_stacks:
            print(x.getCoords(), end = " ")
            x.printContents()

    def printIncompleteContainers(self):
        print("\nIncomplete containers:")
        for x in self.incomplete_containers:
            print(x, x.getCoordsStr())

    def bad_data(self) -> bool:
        return (self.overlapping_containers != []
                or self.anomalous_stacks != []
                or self.incomplete_containers != []
                or self.yp_out_of_range != [])

    #print in order of detection
    def print(self):
        if self.yp_out_of_range: self.printYPOutOfRange()
        if self.incomplete_containers: self.printIncompleteContainers()
        if self.container_coords_invalid: self.printContainerCoordsInvalid()
        if self.overlapping_containers != {}: self.printOverlappingContainers()
        if self.anomalous_stacks: self.printAnomalousStacks()

    def printStats(self):
        print("Total Yard Planning Items:", self.total_yp)
        print("Yard Planning Errors:", self.getTotalYPOutOfRange())
        print("\nTotal Containers:", self.total_containers)
        print("Incomplete Containers:", self.getTotalIncomplete())
        print("Container Coords Invalid:", self.getTotalContainerCoordsInvalid())
        print("Overlapping Containers:", self.getTotalOverlapping())
        print("\nAnomalous Stacks:", self.getTotalAnomalousStacks())