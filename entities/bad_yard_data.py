from .container import Container
from .incomplete_containers import (
    IncompleteExistingContainers,
    IncompleteInboundContainers,
)
from .stack import Stack

class BadYardData:
    overlapping_containers: dict[tuple[str,str,str,str,str],set[Container]]
    anomalous_stacks: list[Stack]
    incompleteExistingContainer: IncompleteExistingContainers
    incompleteInboundContainer: IncompleteInboundContainers
    yp_out_of_range: list[tuple[str,str,int,int]]
    container_coords_invalid: list[Container]
    total_yp: int
    total_containers: int

    def __init__(self, total_params: int, total_containers: int):
        self.overlapping_containers = {}
        self.anomalous_stacks = []
        self.incompleteExistingContainer = IncompleteExistingContainers()
        self.incompleteInboundContainer = IncompleteInboundContainers()
        self.yp_out_of_range = []
        self.container_coords_invalid = []
        self.total_yp = total_params
        self.total_containers = total_containers

    def getAnomalousStacks(self) -> list[Stack]:
        return self.anomalous_stacks
    def getOverlappingContainers(self) -> dict[tuple[str,str,str,str,str],set[Container]]:
        return self.overlapping_containers
    def getIncompleteExistingContainers(self) -> list[Container]:
        return self.incompleteExistingContainer.containers
    def getIncompleteInboundContainers(self) -> list[Container]:
        return self.incompleteInboundContainer.containers
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
    def getTotalIncompleteExisting(self) -> int:
        return len(self.incompleteExistingContainer)
    def getTotalIncompleteInbound(self) -> int:
        return len(self.incompleteInboundContainer)
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
    def addIncompleteExistingContainer(self, container: Container):
        self.incompleteExistingContainer.addContainer(container)
    def addIncompleteInboundContainer(self, container: Container):
        self.incompleteInboundContainer.addContainer(container)
    def addYPOutOfRange(self,yp_item: tuple[str,str,int,int]):
        self.yp_out_of_range.append(yp_item)
    def addContainerCoordsInvalid(self,container:Container):
        self.container_coords_invalid.append(container)
    def addAnomalousStack(self,stack: Stack): self.anomalous_stacks.append(stack)
    def popAnomalousStack(self) -> Stack: return self.anomalous_stacks.pop()

    def anyBadData(self) -> bool:
        return bool(
            self.yp_out_of_range
            or self.incompleteExistingContainer
            or self.incompleteInboundContainer
            or self.anomalous_stacks
            or self.container_coords_invalid
            or self.overlapping_containers
        )
