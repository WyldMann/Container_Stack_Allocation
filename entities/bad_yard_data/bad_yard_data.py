from copy import deepcopy
from dataclasses import dataclass

from ..block import Block
from ..container import Container
from ..equipment import Equipment, Loader, RTG
from ..feasibility import PlacementProposal
from ..parameter import Parameter
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


@dataclass(frozen=True)
class ImportIssue:
    category: str
    record: object
    reason: str


class BadYardData:
    overlapping_containers: dict[tuple[str,str,str,str,str],set[Container]]
    anomalous_stacks: list[Stack]
    incomplete_existing_container: IncompleteExistingContainers
    incomplete_inbound_container: IncompleteInboundContainers
    duplicate_existing_container_i_ds: list[Container]
    duplicate_inbound_container_i_ds: list[Container]
    yp_out_of_range: list[tuple[str,str,int,int]]
    container_coords_invalid: list[Container]
    import_errors: list[ImportIssue]
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
        self.import_errors = []
        self.total_yp = total_params
        self.total_containers = total_containers

    def _rejectImport(self, category: str, record: object, reason: str) -> None:
        self.import_errors.append(
            ImportIssue(category, deepcopy(record), reason)
        )

    @staticmethod
    def _validImportID(value: object) -> bool:
        return isinstance(value, str) and bool(value.strip())

    def validateBlockAndRecord(
        self,
        record: dict[str, str],
        blocks_by_id: dict[str, Block],
        blocks_by_code: dict[tuple[str, str], Block],
    ) -> Block | None:
        if not isinstance(record, dict):
            return self._rejectImport("block", record, "Expected a dictionary.")

        for field in ("block_id", "branch_id", "block_code"):
            if not self._validImportID(record.get(field)):
                return self._rejectImport(
                    "block", record, f"{field} must be a nonblank string."
                )

        if record["block_id"] in blocks_by_id:
            return self._rejectImport("block", record, "Duplicate block ID.")

        code = (record["branch_id"], record["block_code"])
        if code in blocks_by_code:
            return self._rejectImport(
                "block", record, "Duplicate branch/block code."
            )

        for field in ("row_count", "slot_count", "max_tier"):
            value = record.get(field)
            try:
                valid = type(value) in (str, int) and int(value) > 0
            except ValueError:
                valid = False
            if not valid:
                return self._rejectImport(
                    "block", record, f"{field} must be a positive integer."
                )

        try:
            return Block(**record)
        except (TypeError, ValueError) as error:
            return self._rejectImport("block", record, str(error))

    def validateParameterAndRecord(
        self,
        record: dict[str, str],
        parameters: dict[str, Parameter],
    ) -> Parameter | None:
        if not isinstance(record, dict):
            return self._rejectImport(
                "parameter", record, "Expected a dictionary."
            )
        if not self._validImportID(record.get("parameter_id")):
            return self._rejectImport(
                "parameter", record, "Parameter ID must be a nonblank string."
            )
        if record["parameter_id"] in parameters:
            return self._rejectImport(
                "parameter", record, "Duplicate parameter ID."
            )
        if any(not isinstance(value, str) for value in record.values()):
            return self._rejectImport(
                "parameter", record, "Parameter input values must be strings."
            )
        try:
            return Parameter(**record)
        except (TypeError, ValueError) as error:
            return self._rejectImport("parameter", record, str(error))

    def _validateImportStack(
        self,
        category: str,
        location: tuple[str, int, int],
        blocks_by_id: dict[str, Block],
        *,
        parameter_id: str | None = None,
    ) -> Stack | None:
        record = (
            {"parameter_id": parameter_id, "location": location}
            if parameter_id is not None else location
        )
        if not isinstance(location, (tuple, list)) or len(location) != 3:
            return self._rejectImport(
                category, record, "Expected (block_id, row_index, slot_index)."
            )

        block_id, row_index, slot_index = location
        if not self._validImportID(block_id) or block_id not in blocks_by_id:
            return self._rejectImport(
                category, record, f"Unknown block ID: {block_id!r}."
            )
        if type(row_index) is not int or type(slot_index) is not int:
            return self._rejectImport(
                category, record, "Row and slot indices must be integers."
            )

        rows = blocks_by_id[block_id].getSlots()
        # Check before indexing so negative coordinates cannot wrap around.
        if not (
            0 <= row_index < len(rows)
            and 0 <= slot_index < len(rows[row_index])
        ):
            if parameter_id is not None:
                self.addYPOutOfRange(
                    (parameter_id, block_id, row_index, slot_index)
                )
                return None
            return self._rejectImport(
                category, record, "Storage coordinates are outside the block."
            )
        return rows[row_index][slot_index]

    def validateRemovedSlotAndRecord(
        self,
        location: tuple[str, int, int],
        blocks_by_id: dict[str, Block],
    ) -> Stack | None:
        return self._validateImportStack(
            "removed_slot", location, blocks_by_id
        )

    def validateYardPlanningAndRecord(
        self,
        parameter_id: str,
        location: tuple[str, int, int],
        parameters: dict[str, Parameter],
        blocks_by_id: dict[str, Block],
    ) -> tuple[Parameter, Stack] | None:
        if (
            not self._validImportID(parameter_id)
            or parameter_id not in parameters
        ):
            return self._rejectImport(
                "yard_planning",
                {"parameter_id": parameter_id, "location": location},
                f"Unknown parameter ID: {parameter_id!r}.",
            )

        stack = self._validateImportStack(
            "yard_planning", location, blocks_by_id,
            parameter_id=parameter_id,
        )
        if stack is None:
            return None
        return parameters[parameter_id], stack

    def getImportErrors(self) -> tuple[ImportIssue, ...]:
        return tuple(self.import_errors)

    def getTotalImportErrors(self) -> int:
        return len(self.import_errors)

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
            self.import_errors
            or self.yp_out_of_range
            or self.incomplete_existing_container
            or self.incomplete_inbound_container
            or self.duplicate_existing_container_i_ds
            or self.duplicate_inbound_container_i_ds
            or self.anomalous_stacks
            or self.container_coords_invalid
            or self.overlapping_containers
        )
