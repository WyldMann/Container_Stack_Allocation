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
        self.mode = '0'   # '0' = None, 'X' = removed, '20' = cont20, '40' = cont40. which cont type it serves
        self.even = self.coords[2] % 2 == 0     # cont40 is only assigned to evens in 1-based indexing, aka odd here

    def getContainers(self) -> list[Container | None]: return self.containers
    def getParameters(self) -> list[Parameter]: return self.parameters
    def getContainer(self, tier: int) -> Container | None: return self.containers[tier]
    def getMaxTier(self) -> int: return self.maxTier
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

    #returns the highest container object, None if there's no container object
    def getTopContainer(self) -> Container | None:
        prevContainer = None
        for container in self.containers:
            if container is None:
                return prevContainer
            prevContainer = container
        return prevContainer

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
        self.mode = 'X'

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