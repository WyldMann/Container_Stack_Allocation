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
        self.enable_delta_container_mass = settings.enable_delta_container_mass
        self.enable_equipment_distance = settings.enable_equipment_distance
        self.enable_size_cluster = settings.enable_size_cluster
        self.w_delta_container_mass = settings.w_delta_container_mass
        self.hl_delta_container_mass = settings.hl_delta_container_mass
        self.lambda_delta_container_mass = math.log(2) / self.hl_delta_container_mass
        self.w_equipment_distance = settings.w_equipment_distance
        self.hl_equipment_distance = settings.hl_equipment_distance
        self.lambda_equipment_distance = math.log(2) / self.hl_equipment_distance
        self.min_value = settings.min_value
        self.no_delta_container_mass_value = settings.no_delta_container_mass_value
        self.size_cluster_radius = settings.size_cluster_radius
        self.hl_size_cluster_distance = settings.hl_size_cluster_distance
        self.size_cluster_prior = settings.size_cluster_prior
        self.size_cluster_bias = settings.size_cluster_bias

    @staticmethod
    def compareTopContainerMass(container:Container, stack:Stack) -> float | None:
        """Return supporting top-container mass minus incoming container mass."""
        top_container = stack.getTopContainer()
        top_container_mass = None if top_container is None else top_container.getWeight()

        container_mass = container.getWeight()
        if container_mass is None or top_container_mass is None:
            return None
        else:
            return top_container_mass - container_mass

    def sizeCluster(self, container: Container, block: Block,
                    coordinate: tuple[str,int,int,int]) -> float:
        """Return the clustering score multiplier from neighborhood affinity.

        Count stacks independently of height and paired 40-ft slots only once.
        Distances are measured between the closest cells of each footprint,
        within the candidate's block. Exclude its supporting footprint.
        """
        if not self.enable_size_cluster:
            return 1.0

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

    def deltaContainerMass(self, delta_container_mass: float | None) -> float:
        if not self.enable_delta_container_mass:
            return 1.0

        if delta_container_mass is None:
            return self.no_delta_container_mass_value
        if delta_container_mass < 0:
            return self.min_value

        else:
            return self.w_delta_container_mass * self.decayFormula(
                self.lambda_delta_container_mass, delta_container_mass,
            )

    def equipmentDistance(self, equipment_distance: float) -> float:
        if not self.enable_equipment_distance:
            return 1.0

        if equipment_distance == float('inf'):
            return self.min_value
        else:
            return self.w_equipment_distance * self.decayFormula(self.lambda_equipment_distance,equipment_distance)

    #multiplicative weights
    def evaluate(self,delta_container_mass:float|None, equipment_distance:float,
                 size_cluster_multiplier: float = 1.0) -> float:
        cluster_score = size_cluster_multiplier if self.enable_size_cluster else 1.0
        return (self.deltaContainerMass(delta_container_mass)
                * self.equipmentDistance(equipment_distance)
                * cluster_score)
