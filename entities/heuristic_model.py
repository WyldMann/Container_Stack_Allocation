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
        self.w_delta_weight = settings.w_delta_weight
        self.hl_delta_weight = settings.hl_delta_weight
        self.lambda_delta_weight = math.log(2) / self.hl_delta_weight
        self.w_equipment_distance = settings.w_equipment_distance
        self.hl_equipment_distance = settings.hl_equipment_distance
        self.lambda_equipment_distance = math.log(2) / self.hl_equipment_distance
        self.min_value = settings.min_value
        self.no_delta_weight_value = settings.no_delta_weight_value
        self.size_cluster_radius = settings.size_cluster_radius
        self.hl_size_cluster_distance = settings.hl_size_cluster_distance
        self.size_cluster_prior = settings.size_cluster_prior
        self.size_cluster_bias = settings.size_cluster_bias

    @staticmethod
    def compareTopWeight(container:Container, stack:Stack) -> float | None:
        top_container = stack.getTopContainer()
        top_weight = None if top_container is None else top_container.getWeight()

        container_weight = container.getWeight()
        if container_weight is None or top_weight is None:
            return None
        else:
            return top_weight - container_weight

    def sizeCluster(self, container: Container, block: Block,
                    coordinate: tuple[str,int,int,int]) -> float:
        """Return the clustering score multiplier from neighborhood affinity.

        Count stacks independently of height and paired 40-ft slots only once.
        Distances are measured between the closest cells of each footprint,
        within the candidate's block. Exclude its supporting footprint.
        """
        rows = block.getSlots()
        container_size = container.getContSize()
        candidate_slots = (coordinate[2] - 1, coordinate[2]) if container_size == '40' else (coordinate[2],)
        radius = self.size_cluster_radius
        same = other = 0.0
        seen: set[tuple[int,int]] = set()

        for row_index in range(max(0, coordinate[1] - radius), min(len(rows), coordinate[1] + radius + 1)):
            for slot_index in range(max(0, min(candidate_slots) - radius),
                              min(len(rows[row_index]), max(candidate_slots) + radius + 1)):
                stack = rows[row_index][slot_index]
                mode = stack.getMode()
                if mode not in ('20', '40') or stack.occupancy() == 0:
                    continue
                anchor = slot_index if mode == '20' or not stack.getEven() else slot_index + 1
                key = (row_index, anchor)
                if key in seen:
                    continue
                seen.add(key)
                neighbor_slots = (anchor - 1, anchor) if mode == '40' else (anchor,)
                if row_index == coordinate[1] and any(s in candidate_slots for s in neighbor_slots):
                    continue
                distance = min(math.hypot(row_index - coordinate[1], s - c)
                               for s in neighbor_slots for c in candidate_slots)
                if distance > radius:
                    continue
                evidence = 2 ** (-distance / self.hl_size_cluster_distance)
                if mode == container_size:
                    same += evidence
                else:
                    other += evidence

        affinity = (same - other) / (same + other + self.size_cluster_prior)
        multiplier = 2 ** (self.size_cluster_bias * affinity)
        return multiplier

    @staticmethod
    def decayFormula(lambda_: float, variable:float) -> float:
        return math.exp(-lambda_*variable)

    def deltaWeight(self,delta_weight:float | None):
        if delta_weight is None:
            return self.no_delta_weight_value
        if delta_weight < 0:
            return self.min_value

        else: return self.w_delta_weight * self.decayFormula(self.lambda_delta_weight,delta_weight)

    def equipmentDistance(self,equipment_distance:float):
        if equipment_distance == float('inf'):
            return self.min_value
        else:
            return self.w_equipment_distance * self.decayFormula(self.lambda_equipment_distance,equipment_distance)

    #multiplicative weights
    def evaluate(self,delta_weight:float|None, equipment_distance:float,
                 size_cluster_multiplier: float = 1.0) -> float:
        return (self.deltaWeight(delta_weight)
                * self.equipmentDistance(equipment_distance)
                * size_cluster_multiplier)
