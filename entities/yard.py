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

    def getId(self) -> str: return self.id
    def getCode(self) -> str: return self.code
    def getSlots(self) -> list[list[Stack]]:return self.slots
    def getStack(self, row:int, slot:int) -> Stack: return self.slots[row][slot]
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
    blocks_by_id: dict[str,Block]
    blocks_by_code: dict[str, Block]
    params: dict[str,Parameter]
    bad_data: BadYardData
    containers: dict[str,Container]

    #block and parameters input: {"args":"values",...}
    #removed_slots_input: [(block_id, row_no, slot_no),...]
    #yard planning: {param_id:[(block_id, row_no, slot_no),[...],...],...}
    def __init__(self,
                 yard_block_input: list[dict[str,str]],
                 removed_slots_input:list[tuple[str,int,int]] | None = None,
                 parameters_input: list[dict[str,str]] | None = None,
                 yard_planning_input:dict[str,list[tuple[str,int,int]]] | None = None,
                 container_input: list[dict[str,str]] | None = None) -> None:

        if removed_slots_input is None: removed_slots_input = []
        if parameters_input is None: parameters_input = []
        if yard_planning_input is None: yard_planning_input = {}
        if container_input is None: container_input = []

        self.bad_data = BadYardData()

        # initialize blocks and constructs 2 dict attributes to keep track
        self.blocks_by_id = {}
        self.blocks_by_code = {}

        for inp in yard_block_input:
            block = Block(**inp)
            self.blocks_by_id[block.getId()] = block
            self.blocks_by_code[block.getCode()] = block

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

        self.containers = {}
        for inp in container_input:
            container = Container(**inp)

            # No containers in container_input can be incomplete
            if container.isIncomplete():
                self.bad_data.addIncompleteContainer(container)
                continue

            coordsInt = container.getCoordsInt()

            # validate coords can be found. Otherwise, mark bad_data and move on
            try:
                stack = self.blocks_by_code[coordsInt[0]].getStack(coordsInt[1],coordsInt[2])
                tier = coordsInt[3]
                stackIsEmpty = stack.isEmpty(coordsInt[3])
            except (IndexError,KeyError):
                self.bad_data.addContainerCoordsInvalid(container)
                continue


            # disregard container if coords already occupied
            if not stackIsEmpty:
                self.bad_data.addOverlappingContainer(container, stack.getContainer(tier))
            else:
                stack.addContainer(container,tier)
                self.containers[container.getId()] = container

        #todo: flying container implementation
    def getBadData(self) -> BadYardData: return self.bad_data

    def anomalies(self) -> dict[str,list[tuple[int,int]]]:
        result = {}
        for block_id in self.blocks_by_id:
            result[block_id] = self.blocks_by_id[block_id].anomaly()
        return result

    def print(self):
        for block_id in self.blocks_by_id:
            print(block_id)
            self.blocks_by_id[block_id].print()

class BadYardData:
    overlapping_containers: list[tuple[Container,Container|None]]   # None type added for type check purposes. if it's None, something is wrong.
    anomalous_stack: list[Stack]
    incomplete_containers: list[Container]
    yp_out_of_range: list[tuple[str,str,int,int]]
    container_coords_invalid: list[Container]

    def __init__(self):
        self.overlapping_containers = []
        self.anomalous_stack = []
        self.incomplete_containers = []
        self.yp_out_of_range = []
        self.container_coords_invalid = []

    def addOverlappingContainer(self, container1: Container, container2: Container | None):
        print("Bad Data Detected: Overlapping Container")
        self.overlapping_containers.append((container1, container2))
    def addFlyingContainer(self, stack: Stack):
        self.anomalous_stack.append(stack)
    def addIncompleteContainer(self, container: Container):
        print("Bad Data Detected: IncompleteContainer")
        self.incomplete_containers.append(container)
    def addYPOutOfRange(self,yp_item: tuple[str,str,int,int]):
        print("Bad Data Detected: YPOutOfRange")
        self.yp_out_of_range.append(yp_item)
    def addContainerCoordsInvalid(self,container:Container):
        print("Bad Data Detected: Container Coordinates Invalid")
        self.container_coords_invalid.append(container)

    def printContainerCoordsInvalid(self):
        print("Container Coordinates Invalid:")
        for x in self.container_coords_invalid:
            print(x.getId(),x.getCoords())

    def printYPOutOfRange(self):
        print("Yard Planning Out of Range:")
        for yp_item in self.yp_out_of_range:
            print("param_id:",yp_item[0],"block_id:",yp_item[1],"row:",yp_item[2] + 1, "slot:",  yp_item[3] + 1)

    def bad_data(self) -> bool:
        return (self.overlapping_containers != []
                or self.anomalous_stack != []
                or self.incomplete_containers != []
                or self.yp_out_of_range != [])

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
        if self.yp_out_of_range: self.printYPOutOfRange()
        if self.container_coords_invalid: self.printContainerCoordsInvalid()
