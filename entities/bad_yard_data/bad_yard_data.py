from dataclasses import dataclass

from ..block import Block
from ..container import Container
from ..equipment import Equipment, Loader, RTG
from ..feasibility import PlacementProposal
from .incomplete_containers import (
    IncompleteExistingContainers,
    IncompleteInboundContainers,
)
from ..stack import Stack


class PlacementRejected(ValueError):
    """An inbound placement failed validation before changing yard state."""


@dataclass(frozen=True)
class ValidatedInboundPlacement:
    proposal: PlacementProposal
    equipment: Equipment
    source_block: Block
    destination_block: Block


class BadYardData:
    overlapping_containers: dict[tuple[str,str,str,str,str],set[Container]]
    anomalous_stacks: list[Stack]
    incomplete_existing_container: IncompleteExistingContainers
    incomplete_inbound_container: IncompleteInboundContainers
    duplicate_existing_container_i_ds: list[Container]
    duplicate_inbound_container_i_ds: list[Container]
    yp_out_of_range: list[tuple[str,str,int,int]]
    container_coords_invalid: list[Container]
    total_yp: int
    total_containers: int

    def __init__(self, total_params: int, total_containers: int):
        self.overlapping_containers = {}
        self.anomalous_stacks = []
        self.incomplete_existing_container = IncompleteExistingContainers()
        self.incomplete_inbound_container = IncompleteInboundContainers()
        self.duplicate_existing_container_i_ds = []
        self.duplicate_inbound_container_i_ds = []
        self.yp_out_of_range = []
        self.container_coords_invalid = []
        self.total_yp = total_params
        self.total_containers = total_containers

    def validateInboundAndRecord(self, container: Container) -> bool:
        return self.incomplete_inbound_container.validateInboundAndRecord(
            container
        )

    def requireInboundComplete(self, container: Container) -> None:
        if not self.validateInboundAndRecord(container):
            raise PlacementRejected(
                "Inbound container requires an ID and size 20 or 40."
            )

    def validateExistingContainerIDAndRecord(
        self, container: Container, registered_containers,
    ) -> bool:
        if container.getId() not in registered_containers:
            return True
        self.addDuplicateExistingContainerID(container)
        return False

    def validateInboundContainerIDAndRecord(
        self, container: Container, registered_containers,
    ) -> bool:
        if container.getId() not in registered_containers:
            return True
        self.addDuplicateInboundContainerID(container)
        return False

    def validateInboundContainer(
        self,
        container: Container,
        registered_containers,
    ) -> None:
        self.requireInboundComplete(container)
        if not self.validateInboundContainerIDAndRecord(container, registered_containers):
            raise PlacementRejected(
                "Container ID is already registered in this yard."
            )

    def validateInboundDestination(
        self,
        container,
        coordinates,
        *,
        blocks_by_id,
        registered_containers,
        feasibility,
        loader_policies,
    ) -> PlacementProposal:
        self.validateInboundContainer(container, registered_containers)
        try:
            block_id, row_index, slot_index, tier_index = coordinates
            proposal = PlacementProposal(
                block_id, row_index, slot_index, tier_index, container.getContSize()
            )
            block = blocks_by_id[block_id]
        except (TypeError, ValueError, KeyError) as error:
            raise PlacementRejected(f"Invalid destination: {error}") from error

        # Evaluate against current state, including configured safety rules.
        result = feasibility.evaluate(
            container,
            block,
            row_index,
            slot_index,
            loader_policy=loader_policies.get(block_id),
        )
        if not result.feasible:
            raise PlacementRejected(
                f"Placement rejected: {result.rejection_reason.value}"
            )
        if result.coordinates != proposal.coordinates:
            raise PlacementRejected(
                "Destination tier changed; assign the container again."
            )

        for _, r, s in proposal.footprint:
            stack = block.getStack(r, s)
            if stack.anomaly():
                raise PlacementRejected(
                    "Repair floating containers before placing here."
                )
            if not stack.isTierEmpty(tier_index):
                raise PlacementRejected("A destination tier is already occupied.")
        return proposal

    @staticmethod
    def validateEquipmentMove(
        equipment,
        coordinates,
        *,
        blocks_by_id,
        master_loaders,
    ) -> tuple[Block, Block]:
        if not isinstance(equipment, (RTG, Loader)):
            raise TypeError("Unsupported equipment type.")
        block_id, row_index, slot_index = coordinates
        if type(row_index) is not int or type(slot_index) is not int:
            raise ValueError("Equipment row and slot must be integers.")

        source = blocks_by_id[equipment.getCoords()[0]]
        destination = blocks_by_id[block_id]
        if isinstance(equipment, RTG):
            if source.getRTG() is not equipment:
                raise ValueError("RTG is not registered in its source block.")
            if source is not destination:
                raise ValueError("RTG cannot move between blocks.")
        else:
            if equipment not in master_loaders:
                raise ValueError("Loader is not registered in this yard.")
            if source.getLoaders().count(equipment) != 1:
                raise ValueError("Loader source-block registration is inconsistent.")
            if source is not destination and equipment in destination.getLoaders():
                raise ValueError(
                    "Loader is already registered in the destination block."
                )
        return source, destination

    def validateInboundPlacement(
        self,
        container,
        coordinates,
        equipment,
        *,
        blocks_by_id,
        registered_containers,
        master_loaders,
        feasibility,
        loader_policies,
    ) -> ValidatedInboundPlacement:
        proposal = self.validateInboundDestination(
            container,
            coordinates,
            blocks_by_id=blocks_by_id,
            registered_containers=registered_containers,
            feasibility=feasibility,
            loader_policies=loader_policies,
        )
        try:
            source, destination = self.validateEquipmentMove(
                equipment,
                (proposal.block_id, proposal.row_index, proposal.slot_index),
                blocks_by_id=blocks_by_id,
                master_loaders=master_loaders,
            )
        except (TypeError, ValueError, KeyError) as error:
            raise PlacementRejected(str(error)) from error
        return ValidatedInboundPlacement(
            proposal, equipment, source, destination
        )

    def getAnomalousStacks(self) -> list[Stack]:
        return self.anomalous_stacks
    def getOverlappingContainers(self) -> dict[tuple[str,str,str,str,str],set[Container]]:
        return self.overlapping_containers
    def getIncompleteExistingContainers(self) -> list[Container]:
        return self.incomplete_existing_container.containers
    def getIncompleteInboundContainers(self) -> list[Container]:
        return self.incomplete_inbound_container.containers
    def getDuplicateExistingContainerIDs(self) -> list[Container]:
        return self.duplicate_existing_container_i_ds
    def getDuplicateInboundContainerIDs(self) -> list[Container]:
        return self.duplicate_inbound_container_i_ds
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
        return len(self.incomplete_existing_container)
    def getTotalIncompleteInbound(self) -> int:
        return len(self.incomplete_inbound_container)
    def getTotalDuplicateExistingContainerIDs(self) -> int:
        return len(self.duplicate_existing_container_i_ds)
    def getTotalDuplicateInboundContainerIDs(self) -> int:
        return len(self.duplicate_inbound_container_i_ds)
    def getTotalYPOutOfRange(self) -> int:
        return len(self.yp_out_of_range)
    def getTotalContainerCoordsInvalid(self) -> int:
        return len(self.container_coords_invalid)
    def getTotalAnomalousStacks(self) -> int:
        return len(self.anomalous_stacks)

    def addOverlappingContainer(self, container1: Container, container2: Container):
        coordinates = container1.getCoordsStrTuple()
        if coordinates in self.overlapping_containers:
            self.overlapping_containers[coordinates].update({container1, container2})
        else:
            self.overlapping_containers[coordinates] = {container1, container2}
    def addIncompleteExistingContainer(self, container: Container):
        self.incomplete_existing_container.addContainer(container)
    def addIncompleteInboundContainer(self, container: Container):
        self.incomplete_inbound_container.addContainer(container)
    def addDuplicateExistingContainerID(self, container: Container) -> None:
        if not any(item is container for item in self.duplicate_existing_container_i_ds):
            self.duplicate_existing_container_i_ds.append(container)
    def addDuplicateInboundContainerID(self, container: Container) -> None:
        if not any(item is container for item in self.duplicate_inbound_container_i_ds):
            self.duplicate_inbound_container_i_ds.append(container)
    def addYPOutOfRange(self,yp_item: tuple[str,str,int,int]):
        self.yp_out_of_range.append(yp_item)
    def addContainerCoordsInvalid(self,container:Container):
        self.container_coords_invalid.append(container)
    def addAnomalousStack(self,stack: Stack): self.anomalous_stacks.append(stack)
    # Disabled: only anomaly repair consumed recorded stacks.
    # def popAnomalousStack(self) -> Stack: return self.anomalous_stacks.pop()

    def anyBadData(self) -> bool:
        return bool(
            self.yp_out_of_range
            or self.incomplete_existing_container
            or self.incomplete_inbound_container
            or self.duplicate_existing_container_i_ds
            or self.duplicate_inbound_container_i_ds
            or self.anomalous_stacks
            or self.container_coords_invalid
            or self.overlapping_containers
        )
