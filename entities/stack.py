from .container import Container, DummyContainer
from .parameter import Parameter

class Stack:
    containers: list[Container | None]
    parameters: list[Parameter]
    max_tier: int
    coordinates: tuple[str,int,int]
    mode: str
    even: bool

    def __init__(self,
                 max_tier: int,
                 coordinates: tuple[str,int,int],
                 parameters = None):

        if parameters is None:
            parameters = []

        self.containers = [None] * max_tier
        self.parameters = parameters
        self.max_tier = max_tier
        self.coordinates = coordinates
        self.mode = '0'   # '0' = None, 'X' = removed, '20' = cont20, '40' = cont40. which cont type it serves
        self.even = self.coordinates[2] % 2 == 0     # cont40 is only assigned to evens in 1-based indexing, aka odd here

    def getContainers(self) -> list[Container | None]: return self.containers
    def getParameters(self) -> list[Parameter]: return self.parameters
    def getContainer(self, tier_index: int) -> Container | None: return self.containers[tier_index]
    def getMaxTier(self) -> int: return self.max_tier
    def getCoords(self) -> tuple[str,int,int]: return self.coordinates
    def getMode(self) -> str: return self.mode
    def getEven(self) -> bool: return self.even

    def setMode(self, mode: str): self.mode = mode

    def isTierEmpty(self, tier_index: int) -> bool:
        return self.containers[tier_index] is None

    def availableTierInt(self) -> int | None:
        for tier_index, container in enumerate(self.containers):
            if container is None:
                return tier_index
        return None

    #returns the highest container object, None if there's no container object
    def getTopContainer(self) -> Container | None:
        prev_container = None
        for container in self.containers:
            if container is None:
                return prev_container
            prev_container = container
        return prev_container

    def addContainer(self, container: Container, tier_index: int):
        if type(tier_index) is not int:
            raise TypeError("Tier must be an integer.")
        if self.mode == "X" or not 0 <= tier_index < len(self.containers):
            raise ValueError("Tier is outside an available stack.")

        container_size = container.getContSize()
        if container_size not in ("20", "40") or self.mode not in ("0", container_size):
            raise ValueError("Container size conflicts with stack mode.")
        if not self.isTierEmpty(tier_index):
            raise ValueError("Tier is already occupied.")

        self.containers[tier_index] = container
        if tier_index == 0:
            self.setMode(container_size)
    def replaceContainer(self, container: Container, tier_index: int):
        self.containers[tier_index] = container

    def removeContainer(self, tier_index: int):
        self.containers[tier_index] = None
    def addParameter(self, parameter: Parameter):
        self.parameters.append(parameter)

    # returns number of empty vacancies
    def vacancy(self):
        return self.containers.count(None)

    def occupancy(self):
        return self.max_tier - self.containers.count(None)

    # returns true if there's floating containers
    def anomaly(self):
        done_stacking = False
        for x in self.containers:
            if x is not None:
                if done_stacking: return True
            else: done_stacking = True
        return False

    def anomalyDummyFill(self,dummy: DummyContainer):
        start_stacking = False
        for x in reversed(range(len(self.containers))):
            if self.containers[x] is not None:
                start_stacking = True
            else:
                if start_stacking:
                    self.containers[x] = dummy
                    dummy.addCoordList(self.coordinates,x)

    # use this instead if return type is definitely a container and not None
    def getContainerOrRaise(self,tier_index:int) -> Container:
        container = self.containers[tier_index]
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

    def makeVoid(self):
        self.max_tier = 0
        self.containers = []
        self.mode = 'X'
