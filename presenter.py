import pandas as pd
from entities import Yard, Block, Stack, Container, Equipment, BadYardData, AssignResult
from utils import toIDSlotRow,toStrSlotRowTier
from typing import Callable


class Presenter:
    def __init__(self, out:Callable[...,None] = print):
        self.out = out
        pd.set_option('display.max_rows', None)  # Show all rows
        pd.set_option('display.max_columns', None)  # Show all columns
        pd.set_option('display.width', None)  # No line wrapping
        pd.set_option('display.max_colwidth', None)  # Show full cell content

    # ----- primitives -----
    def outContainer(self, container: Container) -> None:
        self.out("ID:", container.getId(),
              "| Principal:", container.getPrincipal(),
              "| Container Condition:", container.getContCondition(),
              "| Container Fill:", container.getContFill(),
              "| Container Size:", container.getContSize(),
              "| Container Grade:", container.getContGrade(),
              "| Pol:", container.getPol(),
              "| Pod:", container.getPod(),
              "| Voyage:", container.getVoyage(),
              "| Weight:", container.getWeight() if container.getWeight() is not None else "None",
              "| MoveTime:", container.getMoveTime(),
              "| CoordsStr:", container.getCoordsStr()[0], container.getCoordsStr()[1],container.getCoordsStr()[3],container.getCoordsStr()[2],container.getCoordsStr()[4])

    def outEquipment(self, equipment: Equipment) -> None:
        self.out(equipment.getCode(), "-", toIDSlotRow(equipment.getCoordsStr()))

    def outStackOccupancy(self, stack: Stack) -> None:
        # cannot find way to make this thing accept anything other than print as out
        self.out(f"{stack.occupancy()}{stack.getMode()[:1]} ", end = "")

    def outStackContents(self, stack: Stack) -> None:
        for c in stack.getContainers():
            self.out(f"{c if c is not None else "None"} " )
        self.out(f"\n")

class YardPresenter(Presenter):

    # ----- composites -----
    def outBlock(self, block: Block) -> None:
        self.out("ID:", block.getId(),
                 " Branch/Code:", block.getBranch() + "/" + block.getCode())
        rtg = block.getRTG()
        if rtg is not None:
            self.outEquipment(rtg)
        for loader in block.getLoaders():
            self.outEquipment(loader)
        for row_stacks in block.getSlots():
            for stack in row_stacks:
                self.outStackOccupancy(stack)
            self.out()

    def outYard(self, yard: Yard) -> None:
        for block in yard.blocks_by_id.values():
            self.outBlock(block)

    def outAssignResult(self, result: AssignResult|None) -> None:
        if result is None:
            self.out("No Space Found")
            return

        self.outContainer(result.container)
        self.out(result.parameter_scores)

        self.out("Max Param Score:", result.max_parameter_score)

        coordinates = result.getBestCoordinate()
        equipment = result.getBestEquipment()

        self.out(pd.DataFrame ({
            "Coordinate": [toStrSlotRowTier(coordinate) for coordinate in result.getCoords()],
            "Param ID": result.getStrParameters(),
            "Param Name": result.getParameterNames(),
            "Top Container ΔMass": result.getDeltaContainerMasses(),
            "Distance": result.getDistances(),
            "Size Cluster Multiplier": result.getSizeClusterMultipliers(),
            "Score": result.getScores()
        }))
        self.out("Container can be assigned to", toStrSlotRowTier(coordinates))
        self.out("using", equipment, "currently in", toIDSlotRow(equipment.getCoordsStr()))

class BadDataPresenter(Presenter):

    # ----- primitives -----
    def printImportErrors(self, baddata: BadYardData) -> None:
        self.out("\nInvalid Import Records:")
        for issue in baddata.getImportErrors():
            self.out(
                issue.category, "|", issue.reason, "|", repr(issue.record)
            )

    def printOverlappingContainers(self, baddata: BadYardData) -> None:
        self.out("\nOverlapping Containers:")
        for coordinates, containers in baddata.getOverlappingContainers().items():
            self.out(coordinates, [str(x) for x in containers])

    def printContainerCoordsInvalid(self, baddata: BadYardData) -> None:
        self.out("\nContainer Coordinates Invalid:")
        for x in baddata.getContainerCoordsInvalid():
            self.out(x.getId(), x.getCoordsStr())

    def printYPOutOfRange(self, baddata: BadYardData) -> None:
        self.out("\nYard Planning Out of Range:")
        for yp_item in baddata.getYPOutOfRange():
            self.out("param_id:",yp_item[0],"block_id:",yp_item[1],"row:",yp_item[2] + 1, "slot:",  yp_item[3] + 1)

    def printAnomalousStacks(self, baddata: BadYardData) -> None:
        self.out("\nAnomalous stacks:")
        for x in baddata.getAnomalousStacks():
            self.out(x.getCoords(), end = " ")
            self.outStackContents(x)

    def printIncompleteExistingContainers(self, baddata: BadYardData) -> None:
        self.out("\nIncomplete Existing Containers:")
        for x in baddata.getIncompleteExistingContainers():
            self.out(x.getId(), x.getCoordsStr(), "CONTSIZE:", repr(x.getContSize()))

    def printIncompleteInboundContainers(self, baddata: BadYardData) -> None:
        self.out("\nIncomplete Inbound Containers:")
        for x in baddata.getIncompleteInboundContainers():
            self.out(x.getId(), "CONTSIZE:", repr(x.getContSize()))

    def printDuplicateExistingContainerIDs(self, baddata: BadYardData) -> None:
        self.out("\nDuplicate Existing Container IDs:")
        for container in baddata.getDuplicateExistingContainerIDs():
            self.out(container.getId(), container.getCoordsStr(),
                     "CONTSIZE:", repr(container.getContSize()))

    def printDuplicateInboundContainerIDs(self, baddata: BadYardData) -> None:
        self.out("\nDuplicate Inbound Container IDs:")
        for container in baddata.getDuplicateInboundContainerIDs():
            self.out(container.getId(), "CONTSIZE:", repr(container.getContSize()))

    # ----- composites -----
    #print in the theoretical order of detection
    def print(self, baddata: BadYardData) -> None:
        if not baddata.anyBadData():
            self.out("No Bad Data")
            return

        if baddata.getImportErrors(): self.printImportErrors(baddata)
        if baddata.yp_out_of_range: self.printYPOutOfRange(baddata)
        if baddata.incomplete_existing_container:
            self.printIncompleteExistingContainers(baddata)
        if baddata.incomplete_inbound_container:
            self.printIncompleteInboundContainers(baddata)
        if baddata.duplicate_existing_container_i_ds:
            self.printDuplicateExistingContainerIDs(baddata)
        if baddata.duplicate_inbound_container_i_ds:
            self.printDuplicateInboundContainerIDs(baddata)
        if baddata.container_coords_invalid: self.printContainerCoordsInvalid(baddata)
        if baddata.overlapping_containers != {}: self.printOverlappingContainers(baddata)
        if baddata.anomalous_stacks: self.printAnomalousStacks(baddata)

    def printInbound(self, baddata: BadYardData) -> None:
        if baddata.getIncompleteInboundContainers():
            self.printIncompleteInboundContainers(baddata)
        if baddata.getDuplicateInboundContainerIDs():
            self.printDuplicateInboundContainerIDs(baddata)

    def printStats(self,baddata: BadYardData) -> None:
        if not baddata.anyBadData():
            self.out("No Bad Data")
            return

        self.out("Import Validation Errors:", baddata.getTotalImportErrors())
        self.out("Total Yard Planning Items:", baddata.getTotalYardPlanning())
        self.out("Yard Planning Errors:", baddata.getTotalYPOutOfRange())
        self.out("\nTotal Existing Containers:", baddata.getTotalContainers())
        self.out("Incomplete Existing Containers:", baddata.getTotalIncompleteExisting())
        self.out("Duplicate Existing Container IDs:", baddata.getTotalDuplicateExistingContainerIDs())
        self.out("Container Coords Invalid:", baddata.getTotalContainerCoordsInvalid())
        self.out("Overlapping Containers:", baddata.getTotalOverlapping())
        self.out("\nIncomplete Inbound Containers:", baddata.getTotalIncompleteInbound())
        self.out("Duplicate Inbound Container IDs:", baddata.getTotalDuplicateInboundContainerIDs())
        self.out("\nAnomalous Stacks:", baddata.getTotalAnomalousStacks())
