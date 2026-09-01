from .container import Container
from .parameter import Parameter

class Stack:
    containers: list[Container | None]
    parameters: list[Parameter]
    maxTier: int
    coords: tuple[str,int,int]

    def __init__(self,
                 maxTier: int,
                 coords: tuple[str,int,int],
                 parameters = None):

        if parameters is None:
            parameters = []

        self.containers = [None for x in range(maxTier)]
        self.parameters = parameters
        self.maxTier = maxTier
        self.coords = coords

    def getContainers(self) -> list[Container | None]: return self.containers
    def getParameters(self) -> list[Parameter] | None: return self.parameters
    def getContainer(self, tier: int) -> Container | None: return self.containers[tier]

    def isEmpty(self,tier: int) -> bool:
        return self.containers[tier] is None

    def addContainer(self, container: Container, tier: int):
        if self.isEmpty(tier):
            self.containers[tier] = container
            container.setCoords(self.coords[0], str(self.coords[1]), str(self.coords[2]), str(tier))
        else:
            print("Occupied")

    def removeContainer(self, tier: int):
        self.containers[tier] = None
    def addParameter(self, parameter: Parameter):
        self.parameters.append(parameter)



    # returns number of empty vacancies
    def vacancy(self):
        return self.containers.count(None)

    # returns true if there's floating containers
    def anomaly(self):
        doneStacking = False
        for x in self.containers:
            if x is not None:
                if doneStacking: return True
                else: doneStacking = True
        return False

    # returns tier score
    def score(self,container):
        return max(x.evaluate(container) for x in self.parameters)

    def makeVoid(self):
        self.maxTier = 0
        self.containers = []

    def printVacancy(self):
        print(self.vacancy(), end = " ")

    def printContents(self):
        for x in self.containers:
            if x is not None:
                print(x, end = " ")
            else:
                print("None", end = " ")
        print()

class Block:
    id: str
    code: str
    slots: list[list[Stack]]

    def __init__(self,
                 BLOCK_ID: str,
                 BLOCK_CODE: str,
                 SLOT_COUNT: str,
                 ROW_COUNT: str,
                 MAX_TIER: str,

                 **kwargs
                 ):

        self.id = BLOCK_ID
        self.code = BLOCK_CODE
        self.slots = []
        for row in range(int(ROW_COUNT)):
            stacks = []
            for slot in range(int(SLOT_COUNT)):
                stacks.append(Stack(int(MAX_TIER), (self.code,row,slot)))
            self.slots.append(stacks)
        #todo: removed slots

    def getId(self) -> str: return self.id
    def getCode(self) -> str: return self.code
    def getSlots(self) -> list[list[Stack]]:return self.slots
    def anomaly(self) -> list[tuple[int,int]]:
        anomalies = []
        for x,row in enumerate(self.slots):
            for y,tier in enumerate(row):
                anomalies.append((x,y))
        return anomalies
    def print(self):
        for slot in self.slots:
            for tier in slot:
                tier.printVacancy()
            print()



# in this scope, there's only one yard
class Yard:
    blocks: list[Block]
    #removed_slots_input: (block_no, row_no, slots_no)
    def __init__(self,yard_block_input: list[dict[str,str]], removed_slots_input:list[tuple[str,int,int]]) -> None:
        self.blocks = []
        for block in yard_block_input:
            self.blocks.append(Block(**block))

        for removed_slot in removed_slots_input:
            for block in self.blocks:
                if block.getId() == removed_slot[0]:
                    block.getSlots()[removed_slot[1]-1][removed_slot[2]-1].makeVoid()
                    break


        #todo parameters, containers, removed slots

    def anomalies(self) -> dict[str,list[tuple[int,int]]]:
        result = {}
        for block in self.blocks:
            result[block.getId()] = block.anomaly()
        return result

    def print(self):
        for block in self.blocks:
            print(block.getId())
            block.print()

class BadYardData:
    overlapping_containers: list[tuple[Container,Container]]
    anomalous_stack: list[Stack]
    incomplete_containers: list[Container]

    def __init__(self):
        self.overlapping_containers = []
        self.anomalous_stack = []
        self.incomplete_containers = []
    def addOverlappingContainer(self, container1: Container, container2: Container):
        self.overlapping_containers.append((container1, container2))
    def addFlyingContainer(self, stack: Stack):
        self.anomalous_stack.append(stack)
    def addIncompleteContainer(self, container: Container):
        self.incomplete_containers.append(container)

    def bad_data(self) -> bool:
        return (self.overlapping_containers != []
                or self.anomalous_stack != []
                or self.incomplete_containers != [])

    def print(self):
        if self.overlapping_containers:
            print("Overlapping containers:")
            for x in self.overlapping_containers:
                print(x)
        if self.anomalous_stack:
            print("Anomalous stacks:")
            for x in self.anomalous_stack:
                x.printContents()
        if self.incomplete_containers:
            print("Incomplete containers:")
            for x in self.incomplete_containers:
                print(x,x.getCoords())
