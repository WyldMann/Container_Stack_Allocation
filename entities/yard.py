from .container import Container
from .parameter import Parameter

class Stack:
    containers: list[Container | None]
    parameters: list[Parameter]
    maxTier: int

    def __init__(self,
                 maxTier: int,
                 parameters = None):

        if parameters is None:
            parameters = []

        self.containers = [None for x in range(maxTier)]
        self.parameters = parameters
        self.maxTier = maxTier

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

    def print(self):
        print(self.vacancy(), end = " ")


class Block:
    id: str
    tiers: list[list[Stack]]

    def __init__(self,
                 BLOCK_CODE: str,
                 SLOT_COUNT: str,
                 ROW_COUNT: str,
                 MAX_TIER: str,

                 **kwargs
                 ):
        self.id = BLOCK_CODE
        self.tiers = [[Stack(int(MAX_TIER))
                       for slot in range(int(SLOT_COUNT))]
                      for row in range(int(ROW_COUNT))]

        #todo: removed tiers

    def getId(self) -> str: return self.id
    def getTiers(self) -> list[list[Stack]]:return self.tiers
    def anomaly(self) -> list[tuple[int,int]]:
        anomalies = []
        for x,row in enumerate(self.tiers):
            for y,tier in enumerate(row):
                anomalies.append((x,y))
        return anomalies

    def print(self):
        for slot in self.tiers:
            for tier in slot:
                tier.print()
            print()



# in this scope, there's only one yard
class Yard:
    blocks: list[Block]
    def __init__(self,yard_block_input: list[dict[str,str]]):
        self.blocks = []
        for block in yard_block_input:
            self.blocks.append(Block(**block))

    def anomalies(self) -> dict[str,list[tuple[int,int]]]:
        result = {}
        for block in self.blocks:
            result[block.getId()] = block.anomaly()
        return result

    def print(self):
        for block in self.blocks:
            print(block.getId())
            block.print()