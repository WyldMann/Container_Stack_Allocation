import math

import pandas as pd

from .heuristic_model import HeuristicModel
from .container import Container, DummyContainer
from .parameter import Parameter
from .equipment import RTG,Loader,Equipment
from .stack import Stack
from .block import Block
from utils import *

from .bad_yard_data import BadYardData

# in this scope, there's only one yard
class Yard:
    blocks_by_id: dict[str,Block]
    blocks_by_code: dict[tuple[str,str], Block] # {(BRANCH_ID,BLOCK_CODE): Block}
    params: dict[str,Parameter]
    bad_data: BadYardData
    containers: dict[str,Container]
    dummy: DummyContainer
    masterLoader: list[Loader]
    model = HeuristicModel()

    #block and parameters input: {"args":"values",...}
    #removed_slots_input: [(block_id, row_no, slot_no),...]
    #yard planning: {param_id:[(block_id, row_no, slot_no),[...],...],...}
    def __init__(self,
                 yard_block_input: list[dict[str,str]],
                 removed_slots_input: list[tuple[str,int,int]] | None = None,
                 parameters_input: list[dict[str,str]] | None = None,
                 yard_planning_input: dict[str,list[tuple[str,int,int]]] | None = None,
                 container_input: list[dict[str,str]] | None = None,
                 master_equipment: list[dict[str,str]] | None = None,
                 equipment_history:dict[str,tuple[str,str,int,int]] | None = None) -> None:

        if removed_slots_input is None: removed_slots_input = []
        if parameters_input is None: parameters_input = []
        if yard_planning_input is None: yard_planning_input = {}
        if container_input is None: container_input = []
        if master_equipment is None: master_equipment = []
        if equipment_history is None: equipment_history = {}

        self.bad_data = BadYardData(sum(len(yp) for yp in yard_planning_input.values()),len(container_input))
        self.dummy = DummyContainer()

        # initialize blocks and constructs 2 dict attributes to keep track
        self.blocks_by_id = {}
        self.blocks_by_code = {}

        for inp in yard_block_input:
            block = Block(**inp)
            self.blocks_by_id[block.getId()] = block
            self.blocks_by_code[(block.getBranch(),block.getCode())] = block

        # remove the slots as per input
        for removed_slot in removed_slots_input:
            self.blocks_by_id[removed_slot[0]].getStack(removed_slot[1],removed_slot[2]).makeVoid()

        # assigns equipments
        self.masterLoader = []
        self.inputEquipment(master_equipment, equipment_history)

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

        # input containers already in the batabase
        self.containers = {}
        for inp in container_input:
            container = Container(**inp)

            # No containers in container_input can be incomplete
            if container.isIncomplete():
                self.bad_data.addIncompleteContainer(container)
                continue

            self.addContainerInput(container)

        self.anomalyCheck()

    def inputEquipment(self,
                       master_equipment: list[dict[str,str]],
                       history_move: dict[str,tuple[str,str,int,int]]):
        for equipment in master_equipment:

            equipment_code = equipment["EQUIPMENT_CODE"]

            try:
                coordsBranchCode = history_move[equipment_code]
                block = self.getBlockByCode(coordsBranchCode[0], coordsBranchCode[1])
                coords = (self.getBlockIDbyCode(coordsBranchCode[0], coordsBranchCode[1]),
                          coordsBranchCode[2],
                          coordsBranchCode[3])
            except KeyError:
                continue

            # if equipment is RTG
            # assumes there's only one RTG
            if equipment["EQUIPMENT_TYPE"] == "RTG":
                block.rtg = RTG(equipment_code, coords)

            # if equipment is loader
            # can be more than one loader in one block
            else:
                loader = Loader(equipment_code, coords)
                block.addLoader(loader)
                self.masterLoader.append(loader)

    def loadersByBlockID(self,blockID: str) -> list[Loader]:
        return [loader for loader in self.masterLoader if loader.getCoords()[0] == blockID]

    def getBadData(self) -> BadYardData: return self.bad_data

    def getBlockByID(self, block_id:str) -> Block:
        return self.blocks_by_id[block_id]
    def getBlockByCode(self, branch:str,code:str) -> Block:
        return self.blocks_by_code[(branch,code)]

    def getBlockBranchCodebyID(self, block_id:str) -> tuple[str,str]:
        return self.blocks_by_id[block_id].getBranch(), self.blocks_by_id[block_id].getCode()
    def getBlockIDbyCode(self, block_branch:str,block_code:str) -> str:
        return self.blocks_by_code[(block_branch,block_code)].getId()

    def addContainerInput(self,container: Container):
        # validate coordsStr can be found. Otherwise, mark bad_data and move on
        try:
            coordsInt = container.getCoordsInt()
            stack = self.blocks_by_code[(coordsInt[0], coordsInt[1])].getStack(coordsInt[2], coordsInt[3])
            tier = coordsInt[4]
            stackIsEmpty = stack.isTierEmpty(tier)

            # cont40 handling
            stack2 = stack
            stackIsEmpty2 = stackIsEmpty
            if container.getContSize() == '40':
                # cont40 can only be put on (int) odd indexes.
                if stack.getMode() == '20' or stack.getEven():
                    raise IndexError
                stack2 = self.blocks_by_code[(coordsInt[0], coordsInt[1])].getStack(coordsInt[2], coordsInt[3] - 1)
                stackIsEmpty2 = stack2.isTierEmpty(tier)
            # cont20 cannot be put on cont40 stacks
            else:
                if stack.getMode() == '40':
                    raise IndexError

        except (IndexError, KeyError, ValueError):
            self.bad_data.addContainerCoordsInvalid(container)
            return

        # if tier is occupied, the one with most recent move_time takes highest precedence
        if not (stackIsEmpty and stackIsEmpty2):
            # existing container is newer. current container is ignored or current container is 40 cuz i'm not handling that.
            # too much goes into cont40 placement to consider this
            existing_container = stack.getContainerTrue(tier)
            if container.getMoveTime() < existing_container.getMoveTime() and container.getContSize() == '40':
                old_container, new_container = container, existing_container
            # current container is newer. remove existing_container from container dict and add current container to the container dict and the stack
            else:
                old_container, new_container = existing_container, container
                del self.containers[existing_container.getId()]
                self.containers[new_container.getId()] = new_container

            stack.replaceContainer(new_container, tier)
            self.bad_data.addOverlappingContainer(old_container, new_container)

        else:
            stack.addContainer(container, tier)
            if container.getContSize() == '40':
                stack2.addContainer(container, tier)
            self.containers[container.getId()] = container

    def addContainerByCoords(self,container: Container,coords:tuple[str,int,int,int]):
        # add container to the stack
        self.getBlockByID(coords[0]).getStack(coords[1],coords[2]).addContainer(container,coords[3])
        # if containerType = 40 add also add to the next stack
        if container.getContSize() == '40':
            self.getBlockByID(coords[0]).getStack(coords[1],coords[2] - 1).addContainer(container,coords[3])

        # add new coords to container
        container.setCoordsInt(self.getBlockBranchCodebyID(coords[0])+(coords[1],coords[2],coords[3],))

    def anomalyCheck(self):
        for block in self.blocks_by_id.values():
            for stack in block.anomalies():
                self.bad_data.addAnomalousStack(stack)

    # method 1: drop all flying containers
    def fixAnomalies(self):
        while len(self.bad_data.getAnomalousStacks()) != 0:
            self.bad_data.popAnomalousStack().normalize()

    # method 2: fit in dummy containers
    def fillDummyContainer(self) -> None:
        while len(self.bad_data.getAnomalousStacks()) != 0:
            self.bad_data.popAnomalousStack().anomalyDummyFill(self.dummy)

    def print(self):
        for block_id in self.blocks_by_id:
            self.blocks_by_id[block_id].print()

    def distanceBetweenBlock(self, blockID1: str, blockID2: str) -> float:
        block1 = self.blocks_by_id[blockID1]
        block2 = self.blocks_by_id[blockID2]
        return math.sqrt((block1.getPosX() - block2.getPosX()) ** 2 + (block1.getPosY() - block2.getPosY()) ** 2)

    def getStack (self, blockID: str, row: int, slot:int) -> Stack:
        return self.getBlockByID(blockID).getStack(row, slot)

    def assignContainer(self,container: Container):
        maxScore = 0
        coordsCandidates = []

        #evaluate params first
        contScores = {}
        for param in self.params.values():
            contScores[str(param)] = param.evaluate(container)
        contScores = dict(sorted(contScores.items(), key=lambda item: item[1], reverse=True))

        for block in self.blocks_by_id.values():
            for row, slots in enumerate(block.getSlots()):
                for slot,stack in enumerate(slots):

                    tier = stack.availableTierInt()

                    # if stack is fully occupied
                    if tier is None: continue

                    # must not conflict with stack.mode
                    if container.getContSize() == '40' and stack.getMode() == '20': continue
                    elif container.getContSize() == '20' and stack.getMode() == '40': continue

                    # contsize 40 must be assigned to odd only
                    if container.getContSize() == '40' and stack.getEven(): continue

                    currentCoords = stack.getCoords()
                    # if contsize 40, next slot must be able to accomodate
                    # though if everything goes well it already should be
                    if container.getContSize() == '40':
                        try:
                            # second stack should already be '20
                            currentCoords2 = slots[slot - 1]
                        except IndexError:
                            print("uh oh")
                            continue
                        if currentCoords2.availableTierInt() != tier:
                            continue

                    # safeMaxima for pyramid safety stacking
                    if block.safeMaxima(currentCoords[1],currentCoords[2]):

                        currentScore = max((contScores[str(param)] for param in stack.getParameters()), default = 0)

                        # currentScore is none if stack is full
                        if currentScore is None: continue

                        # if tie
                        elif maxScore == currentScore:
                            # if container has no fulfillable parameters, put it in stacks with no parameters
                            if maxScore == 0:
                                if not stack.getParameters():
                                    coordsCandidates.append(currentCoords + (tier,))
                            # if container has fulfilabe parameters, stack is another candidate
                            else:
                                coordsCandidates.append(currentCoords + (tier,))
                        # if new stack with better higher score is found, reset coordscandidates with new max score
                        elif maxScore < currentScore:
                            maxScore = currentScore
                            coordsCandidates = [currentCoords + (tier,)]
        if not coordsCandidates:
            print("No Space Found")
            container.print()
            self.print()
            input()
        else:

            # Visualization pre-assignment
            container.print()

            # param visualization
            # track cases in which container has params fulfilled, but must be placed in stack with no params

            print(contScores)
            print("Max Achievable Score:", maxScore)

            # coord with the nearest equipment
            coords = self.bestCoordCandidate(container,coordsCandidates)
            equipment = self.nearestEquipmentDistance(coords[0],coords[1],coords[2])[0]
            # coords = tuple[str,int,int,int] of the best coordCandidate
            # equipment object used.

            print("Using", equipment, "from", toIDSlotRow(equipment.getCoordsStr()))

            self.addContainerByCoords(container,coords)

            # equipment is RTG
            if isinstance(equipment,RTG):
                equipment.inBlockMove(coords[1], coords[2])
            # equipment is Loader
            elif isinstance(equipment,Loader):
                # if change blocks, change block.loaders
                if coords[0] != equipment.getCoords()[0]:
                    self.blocks_by_id[coords[0]].addLoader(equipment)
                    self.blocks_by_id[equipment.getCoords()[0]].removeLoader(equipment)
                    equipment.outBlockMove(coords[0],coords[1], coords[2])
                else:
                    equipment.inBlockMove(coords[1], coords[2])

            # Visualization after assignment
            print("Container assigned to", toStrSlotRowTier(coords))
            print()

            self.print()
            # Visualization end

    # coords (with tier) with the nearest equipment distance
    def coordsWithNearestEquipment (self, coords: list[tuple[str,int,int,int]]) -> tuple[Equipment,tuple[str,int,int,int]]:
        minCoord = coords[0]
        minEquipment, minDistance = self.nearestEquipmentDistance(minCoord[0],minCoord[1],minCoord[2])
        for coord in coords[1:]:
            equipment, distance = self.nearestEquipmentDistance(coord[0],coord[1],coord[2])
            if minDistance > distance:
                minEquipment = equipment
                minDistance = distance
                minCoord = coord

        return minEquipment, minCoord

    # nearest equipment and its distance for a stack coord (without tier)
    def nearestEquipmentDistance(self,blockID: str, row: int, slot: int) -> tuple[Equipment,float]:
        block = self.getBlockByID(blockID)
        # if no RTG is present use loaders
        if block.rtg is None:
            loaders = block.getLoaders()
            # if loader is present in block
            if loaders:
                return  min(((loader,loader.inBlockDistance(row,slot)) for loader in loaders), key = lambda x : x[1])
            # else find loader in the nearest block
            else:
                return min(self.masterLoader, key = lambda loader: self.distanceBetweenBlock(blockID,loader.getCoordsStr()[0])),float("inf")
        else:
            return block.rtg, block.rtg.inBlockDistance(row, slot)

    @staticmethod
    def compareTopWeight(container:Container, stack:Stack) -> float | None:
        topContainer = stack.getTopContainer()
        topWeight = None if topContainer is None else topContainer.getWeight()

        containerWeight = container.getWeight()
        if containerWeight is None or topWeight is None:
            return None
        else:
            return topWeight - containerWeight

    # returns equipment, modelScore
    def modelEval(self, container:Container, coord: tuple[str,int,int,int]) -> tuple[Equipment, float]:
        stack = self.getStack(coord[0],coord[1],coord[2])
        deltaWeight = self.compareTopWeight(container,stack)
        distance = self.nearestEquipmentDistance(coord[0],coord[1],coord[2])
        return distance[0], self.model.evaluate(deltaWeight, distance[1])

    def bestCoordCandidate(self,container, coordsCandidates: list[tuple[str,int,int,int]]):
        evaluated_coords_candidates = sorted(
            [(coord,self.modelEval(container,coord)[1]) for coord in coordsCandidates],
            key = lambda candidate: candidate[1],
            reverse = True
        )

        coordinates = [coord for coord,score in evaluated_coords_candidates]
        scores = [score for coord,score in evaluated_coords_candidates]

        #visualization start

        pd.set_option('display.max_rows', None)  # Show all rows
        pd.set_option('display.max_columns', None)  # Show all columns
        pd.set_option('display.width', None)  # No line wrapping
        pd.set_option('display.max_colwidth', None)  # Show full cell content

        print(pd.DataFrame ({
            "Coordinate": [toStrSlotRowTier(coord) for coord in coordinates],
            "Parameter": [self.getStack(coord[0],coord[1],coord[2]).getParameters() for coord in coordinates],
            "deltaWeight": [self.compareTopWeight(container,self.getStack(coord[0],coord[1],coord[2])) for coord in coordinates],
            "distance": [self.nearestEquipmentDistance(coord[0],coord[1],coord[2])[1] for coord in coordinates],
            "Eval Score": scores
        }))

        return coordinates[0]