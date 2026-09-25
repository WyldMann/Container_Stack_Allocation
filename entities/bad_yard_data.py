from .container import Container
from .stack import Stack

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

    def anyBadData(self) -> bool:
        return (self.yp_out_of_range != [] or
                self.incomplete_containers != [] or
                self.anomalous_stacks != [] or
                self.incomplete_containers != [] or
                self.container_coords_invalid != [] or
                self.overlapping_containers != {})

    #print in order of detection
    def print(self):
        if not self.anyBadData():
            print("No Bad Data")
            return

        if self.yp_out_of_range: self.printYPOutOfRange()
        if self.incomplete_containers: self.printIncompleteContainers()
        if self.container_coords_invalid: self.printContainerCoordsInvalid()
        if self.overlapping_containers != {}: self.printOverlappingContainers()
        if self.anomalous_stacks: self.printAnomalousStacks()

    def printStats(self):
        if not self.anyBadData():
            print("No Bad Data")
            return

        print("Total Yard Planning Items:", self.getTotalYardPlanning())
        print("Yard Planning Errors:", self.getTotalYPOutOfRange())
        print("\nTotal Containers:", self.getTotalContainers())
        print("Incomplete Containers:", self.getTotalIncomplete())
        print("Container Coords Invalid:", self.getTotalContainerCoordsInvalid())
        print("Overlapping Containers:", self.getTotalOverlapping())
        print("\nAnomalous Stacks:", self.getTotalAnomalousStacks())