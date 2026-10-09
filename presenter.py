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
        for row in block.getSlots():
            for stack in row:
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
        self.out(result.cont_scores)

        self.out("Max Param Score:", result.max_param_score)

        coords = result.getBestCoordinate()
        equipment = result.getBestEquipment()

        self.out(pd.DataFrame ({
            "Coordinate": [toStrSlotRowTier(coord) for coord in result.getCoords()],
            "Param ID": result.getStrParameters(),
            "Param Name": result.getParameterNames(),
            "Top Container ΔWeight": result.getDeltaWeights(),
            "Distance": result.getDistances(),
            "Size Cluster Multiplier": result.getSizeClusterMultipliers(),
            "Score": result.getScores()
        }))
        self.out("Container can be assigned to", toStrSlotRowTier(coords))
        self.out("using", equipment, "currently in", toIDSlotRow(equipment.getCoordsStr()))

class BadDataPresenter(Presenter):

    # ----- primitives -----
    def printOverlappingContainers(self,overlapping_containers: dict[tuple[str,str,str,str,str],set[Container]]) -> None:
        self.out("\nOverlapping Containers:")
        for coords, containers in overlapping_containers.items():
            self.out(coords, [str(x) for x in containers])

    def printContainerCoordsInvalid(self, container_coords_invalid: list[Container]) -> None:
        self.out("\nContainer Coordinates Invalid:")
        for x in container_coords_invalid:
            self.out(x.getId(), x.getCoordsStr())

    def printYPOutOfRange(self, yp_out_of_range: list[tuple[str,str,int,int]]) -> None:
        self.out("\nYard Planning Out of Range:")
        for yp_item in yp_out_of_range:
            self.out("param_id:",yp_item[0],"block_id:",yp_item[1],"row:",yp_item[2] + 1, "slot:",  yp_item[3] + 1)

    def printAnomalousStacks(self, anomalous_stacks: list[Stack]) -> None:
        self.out("\nAnomalous stacks:")
        for x in anomalous_stacks:
            self.out(x.getCoords(), end = " ")
            self.outStackContents(x)

    def printIncompleteContainers(self,incomplete_containers: list[Container]) -> None:
        self.out("\nIncomplete containers:")
        for x in incomplete_containers:
            self.out(x, x.getCoordsStr())

    # ----- composites -----
    #print in the theoretical order of detection
    def print(self, baddata: BadYardData) -> None:
        if not baddata.anyBadData():
            self.out("No Bad Data")
            return

        if baddata.yp_out_of_range: self.printYPOutOfRange(baddata.yp_out_of_range)
        if baddata.incomplete_containers: self.printIncompleteContainers(baddata.incomplete_containers)
        if baddata.container_coords_invalid: self.printContainerCoordsInvalid(baddata.container_coords_invalid)
        if baddata.overlapping_containers != {}: self.printOverlappingContainers(baddata.overlapping_containers)
        if baddata.anomalous_stacks: self.printAnomalousStacks(baddata.anomalous_stacks)

    def printStats(self,baddata: BadYardData) -> None:
        if not baddata.anyBadData():
            self.out("No Bad Data")
            return

        self.out("Total Yard Planning Items:", baddata.getTotalYardPlanning())
        self.out("Yard Planning Errors:", baddata.getTotalYPOutOfRange())
        self.out("\nTotal Containers:", baddata.getTotalContainers())
        self.out("Incomplete Containers:", baddata.getTotalIncomplete())
        self.out("Container Coords Invalid:", baddata.getTotalContainerCoordsInvalid())
        self.out("Overlapping Containers:", baddata.getTotalOverlapping())
        self.out("\nAnomalous Stacks:", baddata.getTotalAnomalousStacks())
