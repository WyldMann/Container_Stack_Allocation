import math
from config import HeuristicSettings

from .block import Block
from .container import Container
from .stack import Stack

class HeuristicModel:
    """Placement scoring using settings supplied at construction."""

    def __init__(self, settings: HeuristicSettings | None = None) -> None:
        self.settings = settings if settings is not None else HeuristicSettings()
        settings = self.settings
        self.W_DELTA_WEIGHT = settings.w_delta_weight
        self.HL_DELTA_WEIGHT = settings.hl_delta_weight
        self.LAMBDA_DELTA_WEIGHT = math.log(2) / self.HL_DELTA_WEIGHT
        self.W_EQUIPMENT_DISTANCE = settings.w_equipment_distance
        self.HL_EQUIPMENT_DISTANCE = settings.hl_equipment_distance
        self.LAMBDA_EQUIPMENT_DISTANCE = math.log(2) / self.HL_EQUIPMENT_DISTANCE
        self.MIN_VALUE = settings.min_value
        self.NO_DELTA_WEIGHT_VALUE = settings.no_delta_weight_value
        self.SIZE_CLUSTER_RADIUS = settings.size_cluster_radius
        self.HL_SIZE_CLUSTER_DISTANCE = settings.hl_size_cluster_distance
        self.SIZE_CLUSTER_PRIOR = settings.size_cluster_prior
        self.SIZE_CLUSTER_BIAS = settings.size_cluster_bias

    @staticmethod
    def compareTopWeight(container:Container, stack:Stack) -> float | None:
        topContainer = stack.getTopContainer()
        topWeight = None if topContainer is None else topContainer.getWeight()

        containerWeight = container.getWeight()
        if containerWeight is None or topWeight is None:
            return None
        else:
            return topWeight - containerWeight

    def sizeCluster(self, container: Container, block: Block,
                    coord: tuple[str,int,int,int]) -> float:
        """Return the clustering score multiplier from neighborhood affinity.

        Count stacks independently of height and paired 40-ft slots only once.
        Distances are measured between the closest cells of each footprint,
        within the candidate's block. Exclude its supporting footprint.
        """
        rows = block.getSlots()
        size = container.getContSize()
        candidate_slots = (coord[2] - 1, coord[2]) if size == '40' else (coord[2],)
        radius = self.SIZE_CLUSTER_RADIUS
        same = other = 0.0
        seen: set[tuple[int,int]] = set()

        for row in range(max(0, coord[1] - radius), min(len(rows), coord[1] + radius + 1)):
            for slot in range(max(0, min(candidate_slots) - radius),
                              min(len(rows[row]), max(candidate_slots) + radius + 1)):
                stack = rows[row][slot]
                mode = stack.getMode()
                if mode not in ('20', '40') or stack.occupancy() == 0:
                    continue
                anchor = slot if mode == '20' or not stack.getEven() else slot + 1
                key = (row, anchor)
                if key in seen:
                    continue
                seen.add(key)
                neighbor_slots = (anchor - 1, anchor) if mode == '40' else (anchor,)
                if row == coord[1] and any(s in candidate_slots for s in neighbor_slots):
                    continue
                distance = min(math.hypot(row - coord[1], s - c)
                               for s in neighbor_slots for c in candidate_slots)
                if distance > radius:
                    continue
                evidence = 2 ** (-distance / self.HL_SIZE_CLUSTER_DISTANCE)
                if mode == size:
                    same += evidence
                else:
                    other += evidence

        affinity = (same - other) / (same + other + self.SIZE_CLUSTER_PRIOR)
        multiplier = 2 ** (self.SIZE_CLUSTER_BIAS * affinity)
        return multiplier

    @staticmethod
    def decayFormula(lambda_: float, variable:float) -> float:
        return math.exp(-lambda_*variable)

    def deltaWeight(self,deltaWeight:float | None):
        if deltaWeight is None:
            return self.NO_DELTA_WEIGHT_VALUE
        if deltaWeight < 0:
            return self.MIN_VALUE

        else: return self.W_DELTA_WEIGHT * self.decayFormula(self.LAMBDA_DELTA_WEIGHT,deltaWeight)

    def equipmentDistance(self,equipmentDistance:float):
        if equipmentDistance == float('inf'):
            return self.MIN_VALUE
        else:
            return self.W_EQUIPMENT_DISTANCE * self.decayFormula(self.LAMBDA_EQUIPMENT_DISTANCE,equipmentDistance)

    #multiplicative weights
    def evaluate(self,deltaWeight:float|None, equipmentDistance:float,
                 sizeClusterMultiplier: float = 1.0) -> float:
        return (self.deltaWeight(deltaWeight)
                * self.equipmentDistance(equipmentDistance)
                * sizeClusterMultiplier)
