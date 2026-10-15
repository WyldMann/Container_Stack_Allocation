import math

from config import FeasibilitySettings, HeuristicSettings

from .assign_result import AssignResult, CandidateEvaluation
from .heuristic_model import HeuristicModel
from .container import Container, DummyContainer
from .parameter import Parameter
from .equipment import RTG,Loader,Equipment
from .stack import Stack
from .block import Block
from .feasibility import PlacementFeasibility, PlacementProposal, LoaderBorderAccessPolicy

from .bad_yard_data import BadYardData

# in this scope, there's only one yard
class Yard:
    blocks_by_id: dict[str,Block]
    blocks_by_code: dict[tuple[str,str], Block] # {(branch_id, block_code): Block}
    parameters: dict[str,Parameter]
    bad_data: BadYardData
    containers: dict[str,Container]
    dummy: DummyContainer
    master_loaders: list[Loader]
    model: HeuristicModel

    #block and parameters input: {"args":"values",...}
    #removed_slots_input: [(block_id, row_index, slot_index),...]
    #yard planning: {parameter_id:[(block_id, row_index, slot_index),...],...}
    def __init__(self,
                 yard_blocks_input: list[dict[str,str]],
                 removed_slots_input: list[tuple[str,int,int]] | None = None,
                 parameters_input: list[dict[str,str]] | None = None,
                 yard_planning_input: dict[str,list[tuple[str,int,int]]] | None = None,
                 containers_input: list[dict[str,str]] | None = None,
                 equipment_input: list[dict[str,str]] | None = None,
                 equipment_locations_input:dict[str,tuple[str,str,int,int]] | None = None,
                 loader_access_policies: dict[str, LoaderBorderAccessPolicy] | None = None,
                 feasibility_settings: FeasibilitySettings | None = None,
                 heuristic_settings: HeuristicSettings | None = None) -> None:

        if removed_slots_input is None: removed_slots_input = []
        if parameters_input is None: parameters_input = []
        if yard_planning_input is None: yard_planning_input = {}
        if containers_input is None: containers_input = []
        if equipment_input is None: equipment_input = []
        if equipment_locations_input is None: equipment_locations_input = {}

        self.feasibility = PlacementFeasibility(settings=feasibility_settings)
        self.model = HeuristicModel(settings=heuristic_settings)
        self.loader_access_policies = (
            dict(loader_access_policies) if loader_access_policies is not None else {}
        )

        self.bad_data = BadYardData(sum(len(yp) for yp in yard_planning_input.values()),len(containers_input))
        self.dummy = DummyContainer()

        # initialize blocks and constructs 2 dict attributes to keep track
        self.blocks_by_id = {}
        self.blocks_by_code = {}

        for inp in yard_blocks_input:
            block = Block(**inp)
            self.blocks_by_id[block.getId()] = block
            self.blocks_by_code[(block.getBranch(),block.getCode())] = block

        # remove the slots as per input
        for removed_slot in removed_slots_input:
            self.blocks_by_id[removed_slot[0]].getStack(removed_slot[1],removed_slot[2]).makeVoid()

        # assigns equipments
        self.master_loaders = []
        self.inputEquipment(equipment_input, equipment_locations_input)

        # initializes and stores Parameters
        self.parameters = {}
        for inp in parameters_input:
            parameter = Parameter(**inp)
            self.parameters[parameter.getId()] = parameter

        # add parameters into stacks
        for parameter_id in yard_planning_input:
            parameter = self.parameters[parameter_id]
            #stack: (block_id, row_index, slot_index)
            for stack in yard_planning_input[parameter_id]:
                try:
                    self.blocks_by_id[stack[0]].getStack(stack[1],stack[2]).addParameter(parameter)
                except IndexError:
                    self.bad_data.addYPOutOfRange((parameter_id,stack[0],stack[1],stack[2]))

        # input containers already in the batabase
        self.containers = {}
        for inp in containers_input:
            container = Container(**({"container_size": ""} | inp))

            if not self.bad_data.incomplete_existing_container.validateExistingAndRecord(
                container
            ):
                continue

            self.addContainerInput(container)

        self.anomalyCheck()

    def inputEquipment(self,
                       equipment_input: list[dict[str,str]],
                       equipment_locations_input: dict[str,tuple[str,str,int,int]]):
        for equipment in equipment_input:

            equipment_code = equipment["equipment_code"]

            try:
                location_by_code = equipment_locations_input[equipment_code]
                block = self.getBlockByCode(location_by_code[0], location_by_code[1])
                coordinates = (self.getBlockIDbyCode(location_by_code[0], location_by_code[1]),
                          location_by_code[2],
                          location_by_code[3])
            except KeyError:
                continue

            # if equipment is RTG
            # assumes there's only one RTG
            if equipment["equipment_type"] == "RTG":
                block.rtg = RTG(equipment_code, coordinates)

            # if equipment is loader
            # can be more than one loader in one block
            else:
                loader = Loader(equipment_code, coordinates)
                block.addLoader(loader)
                self.master_loaders.append(loader)

    def loadersByBlockID(self,block_id: str) -> list[Loader]:
        return [loader for loader in self.master_loaders if loader.getCoords()[0] == block_id]

    def getBadData(self) -> BadYardData: return self.bad_data

    def getBlockByID(self, block_id:str) -> Block:
        return self.blocks_by_id[block_id]
    def getBlockByCode(self, branch_id:str,block_code:str) -> Block:
        return self.blocks_by_code[(branch_id,block_code)]

    def getBlockBranchCodebyID(self, block_id:str) -> tuple[str,str]:
        return self.blocks_by_id[block_id].getBranch(), self.blocks_by_id[block_id].getCode()
    def getBlockIDbyCode(self, branch_id:str,block_code:str) -> str:
        return self.blocks_by_code[(branch_id,block_code)].getId()

    def addContainerInput(self, container: Container):
        def reject():
            self.bad_data.addContainerCoordsInvalid(container)

        # Validate coordinates and both slots before modifying yard state.
        try:
            if not self.bad_data.validateExistingContainerIDAndRecord(
                container, self.containers,
            ):
                return

            branch_id, block_code, row_index, slot_index, tier_index = container.getCoordsInt()
            block = self.getBlockByCode(branch_id, block_code)
            rows = block.getSlots()
            container_size = container.getContSize()

            if container_size not in ("20", "40"):
                reject()
                return

            if not 0 <= row_index < len(rows):
                reject()
                return

            if not 0 <= slot_index < len(rows[row_index]):
                reject()
                return

            # A 40-foot container uses an odd zero-based anchor and
            # the immediately preceding slot.
            if container_size == "40":
                if slot_index == 0 or slot_index % 2 == 0:
                    reject()
                    return
                slots = (slot_index, slot_index - 1)
            else:
                slots = (slot_index,)

            stacks = [block.getStack(row_index, index) for index in slots]

            for stack in stacks:
                if not 0 <= tier_index < stack.getMaxTier():
                    reject()
                    return

                if stack.getMode() not in ("0", container_size):
                    reject()
                    return

                # Floating containers may exist in a stack whose mode
                # is still "0", so inspect its contents as well.
                if any(
                    item is not None and item.getContSize() != container_size
                    for item in stack.getContainers()
                ):
                    reject()
                    return

        except (KeyError, IndexError, TypeError, ValueError):
            reject()
            return

        occupants: list[Container] = []
        for stack in stacks:
            occupant = stack.getContainer(tier_index)
            if occupant is not None:
                occupants.append(occupant)

        if occupants:
            if container_size == "40":
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
            stacks[0].replaceContainer(container, tier_index)
            del self.containers[existing.getId()]
            self.containers[container.getId()] = container
            self.bad_data.addOverlappingContainer(existing, container)
            return

        # Every destination has passed validation and is empty.
        for stack in stacks:
            stack.addContainer(container, tier_index)

        self.containers[container.getId()] = container

    def _commitPlacement(
        self,
        container: Container,
        proposal: PlacementProposal,
        movement: tuple[Equipment, Block, Block] | None = None,
    ) -> None:
        stacks = [self.getStack(*coordinate) for coordinate in proposal.footprint]
        stack_before = [
            (stack, list(stack.getContainers()), stack.getMode())
            for stack in stacks
        ]
        registry_before = dict(self.containers)
        coords_before = container.getCoordsStr()
        coords_values_before = list(coords_before)

        equipment_snapshot = None
        if movement is not None:
            equipment, source, destination = movement
            blocks = {
                block.getId(): block
                for block in (source, destination)
            }
            equipment_snapshot = (
                equipment,
                equipment.getCoords(),
                list(self.master_loaders),
                [(block, list(block.getLoaders())) for block in blocks.values()],
            )

        try:
            for stack in stacks:
                stack.addContainer(container, proposal.tier_index)
            container.setCoordsInt(
                self.getBlockBranchCodebyID(proposal.block_id)
                + (proposal.row_index, proposal.slot_index, proposal.tier_index)
            )
            self.addContainer(container)
            if movement is not None:
                self.moveEquipment(
                    movement[0],
                    (proposal.block_id, proposal.row_index, proposal.slot_index),
                )
        except Exception:
            # Restore directly without calling update methods that may fail.
            for stack, contents, mode in stack_before:
                stack.containers[:] = contents
                stack.mode = mode
            self.containers.clear()
            self.containers.update(registry_before)
            coords_before[:] = coords_values_before
            container.coordinates_str = coords_before
            if equipment_snapshot is not None:
                equipment, equipment_before, master_before, membership_before = equipment_snapshot
                equipment.coordinates = equipment_before
                self.master_loaders[:] = master_before
                for block, loaders in membership_before:
                    block.loaders[:] = loaders
            raise

    def addContainerByCoords(self, container, coordinates):
        proposal = self.bad_data.validateInboundDestination(
            container,
            coordinates,
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

    # Disabled: unused repair leaves stack modes inconsistent with contents.
    # def fixAnomalies(self):
    #     while len(self.bad_data.getAnomalousStacks()) != 0:
    #         self.bad_data.popAnomalousStack().normalize()

    # Disabled: dummy repair leaves stack modes inconsistent with contents.
    # def fillDummyContainer(self) -> None:
    #     while len(self.bad_data.getAnomalousStacks()) != 0:
    #         self.bad_data.popAnomalousStack().anomalyDummyFill(self.dummy)

    def distanceBetweenBlock(self, first_block_id: str, second_block_id: str) -> float:
        block1 = self.blocks_by_id[first_block_id]
        block2 = self.blocks_by_id[second_block_id]
        return math.sqrt((block1.getPosX() - block2.getPosX()) ** 2 + (block1.getPosY() - block2.getPosY()) ** 2)

    def getStack(self, block_id: str, row_index: int, slot_index:int) -> Stack:
        return self.getBlockByID(block_id).getStack(row_index, slot_index)

    def findCoordsCandidates(self, container: Container) -> tuple[float,dict[str,float],list[tuple[str,int,int,int]]]:
        max_score : float = 0
        candidate_coordinates : list[tuple[str,int,int,int]] = []

        #evaluate params first
        parameter_scores : dict[str,float] = {}
        for parameter in self.parameters.values():
            parameter_scores[str(parameter)] = parameter.evaluate(container)
        parameter_scores = dict(sorted(parameter_scores.items(), key=lambda item: item[1], reverse=True))

        for block in self.blocks_by_id.values():
            loader_policy = self.loader_access_policies.get(block.getId())
            # This loop only evaluates candidates; no context survives a placement.
            loader_context = self.feasibility.prepare_loader_context(block, loader_policy)
            for row_index, slots in enumerate(block.getSlots()):
                for slot_index,stack in enumerate(slots):

                    # feasibility check
                    result = self.feasibility.evaluate(
                        container, block, row_index, slot_index,
                        loader_policy=loader_policy,
                        loader_context=loader_context,
                    )
                    current_coords = result.coordinates
                    if current_coords is None: continue

                    # candidate scoring
                    current_score = max(
                        (parameter_scores[str(parameter)] for parameter in stack.getParameters()),
                        default=0,
                    )

                    # if tie
                    if max_score == current_score:
                        # if container has no fulfillable parameters, put it in stacks with no parameters
                        if max_score == 0:
                            if not stack.getParameters():
                                candidate_coordinates.append(current_coords)
                        # if container has fulfilabe parameters, stack is another candidate
                        else:
                            candidate_coordinates.append(current_coords)
                    # if new stack with better higher parameter score is found, reset coordscandidates with new max parameter score
                    elif max_score < current_score:
                        max_score = current_score
                        candidate_coordinates = [current_coords]
        return max_score,parameter_scores,candidate_coordinates

    def assignContainer(self, container) -> AssignResult | None:
        self.bad_data.validateInboundContainer(container, self.containers)
        max_score, parameter_scores, candidate_coordinates = self.findCoordsCandidates(container)
        if not candidate_coordinates:
            return None
        return AssignResult(
            container,
            parameter_scores,
            max_score,
            self.bestCoordCandidate(container, candidate_coordinates),
        )

    def placeContainerWithAssignResult(self, result: AssignResult) -> None:
        self.placeContainer(result.container, result.getBestCoordinate(), result.getBestEquipment())

    def placeContainer(self, container, coordinates, equipment):
        validated = self.bad_data.validateInboundPlacement(
            container,
            coordinates,
            equipment,
            blocks_by_id=self.blocks_by_id,
            registered_containers=self.containers,
            master_loaders=self.master_loaders,
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
        coordinates: tuple[str, int, int],
    ) -> None:
        """Move registered equipment, including outside its block's storage grid.

        The block identifies membership; row and slot describe a simulated
        position and may be negative or beyond the block's storage dimensions.
        """
        source, destination = self.bad_data.validateEquipmentMove(
            equipment,
            coordinates,
            blocks_by_id=self.blocks_by_id,
            master_loaders=self.master_loaders,
        )
        block_id, row_index, slot_index = coordinates
        if source is destination:
            equipment.inBlockMove(row_index, slot_index)
        elif isinstance(equipment, Loader):
            source.removeLoader(equipment)
            destination.addLoader(equipment)
            equipment.outBlockMove(block_id, row_index, slot_index)
        else:
            raise ValueError("Only loaders can move between blocks.")

    # nearest equipment and its distance for a stack coord (without tier)
    def nearestEquipmentDistance(self,block_id: str, row_index: int, slot_index: int) -> tuple[Equipment,float]:
        block = self.getBlockByID(block_id)
        # if no RTG is present use loaders
        if block.rtg is None:
            loaders = block.getLoaders()
            # if loader is present in block
            if loaders:
                return  min(((loader,loader.inBlockDistance(row_index,slot_index)) for loader in loaders), key = lambda x : x[1])
            # else find loader in the nearest block
            else:
                return min(self.master_loaders, key = lambda loader: self.distanceBetweenBlock(block_id,loader.getCoordsStr()[0])),float("inf")
        else:
            return block.rtg, block.rtg.inBlockDistance(row_index, slot_index)

    # returns deltaWeight, equipment, distance, multiplier, modelScore
    # attribute of candidateEvaluation other than coord and param
    def modelEval(self, container:Container, coordinate: tuple[str,int,int,int]) -> tuple[float|None,Equipment,float,float,float]:
        stack = self.getStack(coordinate[0],coordinate[1],coordinate[2])
        delta_weight = self.model.compareTopWeight(container,stack)
        equipment, distance = self.nearestEquipmentDistance(coordinate[0],coordinate[1],coordinate[2])
        multiplier = self.model.sizeCluster(container, self.getBlockByID(coordinate[0]), coordinate)
        return (delta_weight, equipment, distance, multiplier,
                self.model.evaluate(delta_weight, distance, multiplier))

    # returns a list of CandidateEvaluation with highest eval_score to lowest
    def bestCoordCandidate(self,container, candidate_coordinates: list[tuple[str,int,int,int]]) -> list[CandidateEvaluation]:
        # [(coord,eval_score)...] sorted from highest to lowest eval_score
        sorted_candidate_evaluations = sorted(
            [CandidateEvaluation(coordinate,
                self.getStack(coordinate[0],coordinate[1],coordinate[2]).getParameters(),
                                 *self.modelEval(container,coordinate)) for coordinate in candidate_coordinates],
            key = lambda candidate: candidate.evaluation_score,
            reverse = True
        )
        return sorted_candidate_evaluations

    def assign_and_place(self,container) -> AssignResult | None:
        result = self.assignContainer(container)
        if result is not None: self.placeContainerWithAssignResult(result)
        return result
