import math
from typing import Final

from .block import Block
from .container import Container
from .stack import Stack

class HeuristicModel:
    """Placement scoring with fixed constants; not runtime-configurable."""

    W_DELTA_WEIGHT: Final[float] = 10
    HL_DELTA_WEIGHT: Final[float] = 5000

    LAMBDA_DELTA_WEIGHT: Final[float] = math.log(2) / HL_DELTA_WEIGHT

    W_EQUIPMENT_DISTANCE: Final[float] = 10
    HL_EQUIPMENT_DISTANCE: Final[float] = 5

    LAMBDA_EQUIPMENT_DISTANCE: Final[float] = math.log(2) / HL_EQUIPMENT_DISTANCE

    MIN_VALUE: Final[float] = 0.001
    NO_DELTA_WEIGHT_VALUE: Final[float] = 0.1

    SIZE_CLUSTER_RADIUS: Final[int] = 3
    HL_SIZE_CLUSTER_DISTANCE: Final[float] = 1.5
    SIZE_CLUSTER_PRIOR: Final[float] = 2.0
    SIZE_CLUSTER_BIAS: Final[float] = 1.0

    @staticmethod
    def compareTopWeight(container:Container, stack:Stack) -> float | None:
        topContainer = stack.getTopContainer()
        topWeight = None if topContainer is None else topContainer.getWeight()

        containerWeight = container.getWeight()
        if containerWeight is None or topWeight is None:
            return None
        else:
            return topWeight - containerWeight

    def sizeAffinity(self, container: Container, block: Block,
                     coord: tuple[str,int,int,int]) -> float:
        """Distance-weighted size affinity of nearby occupied footprints.

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

        return (same - other) / (same + other + self.SIZE_CLUSTER_PRIOR)

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

    def sizeCluster(self, sizeAffinity: float) -> float:
        return 2 ** (self.SIZE_CLUSTER_BIAS * sizeAffinity)

    #multiplicative weights
    def evaluate(self,deltaWeight:float|None, equipmentDistance:float,
                 sizeAffinity: float = 0.0) -> float:
        return (self.deltaWeight(deltaWeight)
                * self.equipmentDistance(equipmentDistance)
                * self.sizeCluster(sizeAffinity))
