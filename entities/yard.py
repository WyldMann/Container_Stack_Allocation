import math

from config import FeasibilitySettings, HeuristicSettings

from .assign_result import AssignResult, CandidateEvaluation
from .heuristic_model import HeuristicModel
from .container import Container, DummyContainer
from .parameter import Parameter
from .equipment import RTG,Loader,Equipment
from .stack import Stack
from .block import Block
from .feasibility import PlacementFeasibility, LoaderBorderAccessPolicy

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
    model: HeuristicModel

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
                 equipment_history:dict[str,tuple[str,str,int,int]] | None = None,
                 loader_access_policies: dict[str, LoaderBorderAccessPolicy] | None = None,
                 feasibility_settings: FeasibilitySettings | None = None,
                 heuristic_settings: HeuristicSettings | None = None) -> None:

        if removed_slots_input is None: removed_slots_input = []
        if parameters_input is None: parameters_input = []
        if yard_planning_input is None: yard_planning_input = {}
        if container_input is None: container_input = []
        if master_equipment is None: master_equipment = []
        if equipment_history is None: equipment_history = {}

        self.feasibility = PlacementFeasibility(settings=feasibility_settings)
        self.model = HeuristicModel(settings=heuristic_settings)
        self.loader_access_policies = (
            dict(loader_access_policies) if loader_access_policies is not None else {}
        )

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
            container = Container(**({"CONTSIZE": ""} | inp))

            if not self.bad_data.incompleteExistingContainer.validateExistingAndRecord(
                container
            ):
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

    def addContainerInput(self, container: Container):
        def reject():
            self.bad_data.addContainerCoordsInvalid(container)

        # Validate coordinates and both slots before modifying yard state.
        try:
            branch, code, row, slot, tier = container.getCoordsInt()
            block = self.getBlockByCode(branch, code)
            rows = block.getSlots()
            size = container.getContSize()

            if size not in ("20", "40"):
                reject()
                return

            if not 0 <= row < len(rows):
                reject()
                return

            if not 0 <= slot < len(rows[row]):
                reject()
                return

            # A 40-foot container uses an odd zero-based anchor and
            # the immediately preceding slot.
            if size == "40":
                if slot == 0 or slot % 2 == 0:
                    reject()
                    return
                slots = (slot, slot - 1)
            else:
                slots = (slot,)

            stacks = [block.getStack(row, index) for index in slots]

            for stack in stacks:
                if not 0 <= tier < stack.getMaxTier():
                    reject()
                    return

                if stack.getMode() not in ("0", size):
                    reject()
                    return

                # Floating containers may exist in a stack whose mode
                # is still "0", so inspect its contents as well.
                if any(
                    item is not None and item.getContSize() != size
                    for item in stack.getContainers()
                ):
                    reject()
                    return

            # One container ID must not occupy two separate locations.
            registered = self.containers.get(container.getId())
            if registered is not None:
                if registered.getCoordsInt() != (branch, code, row, slot, tier):
                    reject()
                    return
                if registered.getContSize() != size:
                    reject()
                    return

        except (KeyError, IndexError, TypeError, ValueError):
            reject()
            return

        occupants: list[Container] = []
        for stack in stacks:
            occupant = stack.getContainer(tier)
            if occupant is not None:
                occupants.append(occupant)

        if occupants:
            if size == "40":
                # Preserve existing containers, including when only
                # the partner slot is occupied.
                for existing in set(occupants):
                    self.bad_data.addOverlappingContainer(container, existing)
                return

            existing = occupants[0]

            if container.getMoveTime() < existing.getMoveTime():
                self.bad_data.addOverlappingContainer(container, existing)
                return

            # Incoming 20-foot container wins on newer or equal time.
            stacks[0].replaceContainer(container, tier)
            del self.containers[existing.getId()]
            self.containers[container.getId()] = container
            self.bad_data.addOverlappingContainer(existing, container)
            return

        # Every destination has passed validation and is empty.
        for stack in stacks:
            stack.addContainer(container, tier)

        self.containers[container.getId()] = container

    def _commitPlacement(self, container, proposal, movement=None):
        stacks = [self.getStack(*coord) for coord in proposal.footprint]
        stack_before = [
            (stack, list(stack.getContainers()), stack.getMode())
            for stack in stacks
        ]
        registry_before = dict(self.containers)
        coords_before = container.getCoordsStr()
        coords_values_before = list(coords_before)

        if movement is not None:
            equipment, source, destination = movement
            equipment_before = equipment.getCoords()
            master_before = list(self.masterLoader)
            blocks = {
                block.getId(): block
                for block in (source, destination)
            }
            membership_before = [
                (block, list(block.getLoaders()))
                for block in blocks.values()
            ]

        try:
            for stack in stacks:
                stack.addContainer(container, proposal.tier)
            container.setCoordsInt(
                self.getBlockBranchCodebyID(proposal.block_id)
                + (proposal.row, proposal.slot, proposal.tier)
            )
            self.addContainer(container)
            if movement is not None:
                self.moveEquipment(
                    equipment,
                    (proposal.block_id, proposal.row, proposal.slot),
                )
        except Exception:
            # Restore directly without calling update methods that may fail.
            for stack, contents, mode in stack_before:
                stack.containers[:] = contents
                stack.mode = mode
            self.containers.clear()
            self.containers.update(registry_before)
            coords_before[:] = coords_values_before
            container.coordsStr = coords_before
            if movement is not None:
                equipment.coords = equipment_before
                self.masterLoader[:] = master_before
                for block, loaders in membership_before:
                    block.loaders[:] = loaders
            raise

    def addContainerByCoords(self, container, coords):
        proposal = self.bad_data.validateInboundDestination(
            container,
            coords,
            blocks_by_id=self.blocks_by_id,
            registered_containers=self.containers,
            feasibility=self.feasibility,
            loader_policies=self.loader_access_policies,
        )
        self._commitPlacement(container, proposal)

    def addContainer(self,container):
        self.containers[container.getId()] = container

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

    def distanceBetweenBlock(self, blockID1: str, blockID2: str) -> float:
        block1 = self.blocks_by_id[blockID1]
        block2 = self.blocks_by_id[blockID2]
        return math.sqrt((block1.getPosX() - block2.getPosX()) ** 2 + (block1.getPosY() - block2.getPosY()) ** 2)

    def getStack(self, blockID: str, row: int, slot:int) -> Stack:
        return self.getBlockByID(blockID).getStack(row, slot)

    def findCoordsCandidates(self, container: Container) -> tuple[float,dict[str,float],list[tuple[str,int,int,int]]]:
        maxScore : float = 0
        coordsCandidates : list[tuple[str,int,int,int]] = []

        #evaluate params first
        contScores : dict[str,float] = {}
        for param in self.params.values():
            contScores[str(param)] = param.evaluate(container)
        contScores = dict(sorted(contScores.items(), key=lambda item: item[1], reverse=True))

        for block in self.blocks_by_id.values():
            loader_policy = self.loader_access_policies.get(block.getId())
            # This loop only evaluates candidates; no context survives a placement.
            loader_context = self.feasibility.prepare_loader_context(block, loader_policy)
            for row, slots in enumerate(block.getSlots()):
                for slot,stack in enumerate(slots):

                    # feasibility check
                    result = self.feasibility.evaluate(
                        container, block, row, slot,
                        loader_policy=loader_policy,
                        loader_context=loader_context,
                    )
                    currentCoords = result.coordinates
                    if currentCoords is None: continue

                    # candidate scoring
                    currentScore = max(
                        (contScores[str(param)] for param in stack.getParameters()),
                        default=0,
                    )

                    # if tie
                    if maxScore == currentScore:
                        # if container has no fulfillable parameters, put it in stacks with no parameters
                        if maxScore == 0:
                            if not stack.getParameters():
                                coordsCandidates.append(currentCoords)
                        # if container has fulfilabe parameters, stack is another candidate
                        else:
                            coordsCandidates.append(currentCoords)
                    # if new stack with better higher parameter score is found, reset coordscandidates with new max parameter score
                    elif maxScore < currentScore:
                        maxScore = currentScore
                        coordsCandidates = [currentCoords]
        return maxScore,contScores,coordsCandidates

    def assignContainer(self, container) -> AssignResult | None:
        self.bad_data.validateInboundContainer(container, self.containers)
        maxScore, contScores, coordsCandidates = self.findCoordsCandidates(container)
        if not coordsCandidates:
            return None
        return AssignResult(
            container,
            contScores,
            maxScore,
            self.bestCoordCandidate(container, coordsCandidates),
        )

    def placeContainerWithAssignResult(self, result: AssignResult) -> None:
        self.placeContainer(result.container, result.getBestCoordinate(), result.getBestEquipment())

    def placeContainer(self, container, coords, equipment):
        validated = self.bad_data.validateInboundPlacement(
            container,
            coords,
            equipment,
            blocks_by_id=self.blocks_by_id,
            registered_containers=self.containers,
            master_loaders=self.masterLoader,
            feasibility=self.feasibility,
            loader_policies=self.loader_access_policies,
        )
        self._commitPlacement(
            container,
            validated.proposal,
            (
                validated.equipment,
                validated.source_block,
                validated.destination_block,
            ),
        )

    def moveEquipment(
        self,
        equipment: Equipment,
        coords: tuple[str, int, int],
    ) -> None:
        """Move registered equipment, including outside its block's storage grid.

        The block identifies membership; row and slot describe a simulated
        position and may be negative or beyond the block's storage dimensions.
        """
        source, destination = self.bad_data.validateEquipmentMove(
            equipment,
            coords,
            blocks_by_id=self.blocks_by_id,
            master_loaders=self.masterLoader,
        )
        block_id, row, slot = coords
        if source is destination:
            equipment.inBlockMove(row, slot)
        else:
            source.removeLoader(equipment)
            destination.addLoader(equipment)
            equipment.outBlockMove(block_id, row, slot)

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

    # returns deltaWeight, equipment, distance, multiplier, modelScore
    # attribute of candidateEvaluation other than coord and param
    def modelEval(self, container:Container, coord: tuple[str,int,int,int]) -> tuple[float|None,Equipment,float,float,float]:
        stack = self.getStack(coord[0],coord[1],coord[2])
        deltaWeight = self.model.compareTopWeight(container,stack)
        equipment, distance = self.nearestEquipmentDistance(coord[0],coord[1],coord[2])
        multiplier = self.model.sizeCluster(container, self.getBlockByID(coord[0]), coord)
        return (deltaWeight, equipment, distance, multiplier,
                self.model.evaluate(deltaWeight, distance, multiplier))

    # returns a list of CandidateEvaluation with highest eval_score to lowest
    def bestCoordCandidate(self,container, coordsCandidates: list[tuple[str,int,int,int]]) -> list[CandidateEvaluation]:
        # [(coord,eval_score)...] sorted from highest to lowest eval_score
        sortedCandidateEvaluations = sorted(
            [CandidateEvaluation(coord,
                self.getStack(coord[0],coord[1],coord[2]).getParameters(),
                                 *self.modelEval(container,coord)) for coord in coordsCandidates],
            key = lambda candidate: candidate.eval_score,
            reverse = True
        )
        return sortedCandidateEvaluations

    def assign_and_place(self,container) -> AssignResult | None:
        result = self.assignContainer(container)
        if result is not None: self.placeContainerWithAssignResult(result)
        return result
