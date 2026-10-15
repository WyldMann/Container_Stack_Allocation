from dataclasses import dataclass

from .parameter import Parameter
from .equipment import Equipment
from .container import Container

@dataclass
class CandidateEvaluation:
    coordinates: tuple[str, int, int, int]
    parameters: list[Parameter]
    delta_container_mass: float | None
    equipment: Equipment
    distance: float
    size_cluster_multiplier: float
    evaluation_score: float

    def getStrParameter(self) -> list[str]:
        return [str(x) for x in self.parameters]

@dataclass
class AssignResult:
    container: Container
    parameter_scores: dict[str,float]
    max_parameter_score: float
    sorted_candidate_evaluations: list[CandidateEvaluation]

    def getBestCandidate(self) -> CandidateEvaluation:
        return self.sorted_candidate_evaluations[0]
    def getBestCoordinate(self) -> tuple[str, int, int, int]:
        return self.getBestCandidate().coordinates
    def getStrParameters(self) -> list[list[str]]:
        return [x.getStrParameter() for x in self.sorted_candidate_evaluations]
    def getParameterNames(self) -> list[list[str]]:
        return [[parameter.getName() for parameter in candidate.parameters]
                for candidate in self.sorted_candidate_evaluations]
    def getBestEquipment(self) -> Equipment:
        return self.getBestCandidate().equipment
    def getCoords(self) -> list[tuple[str,int,int,int]]:
        return [x.coordinates for x in self.sorted_candidate_evaluations]
    def getDeltaContainerMasses(self) -> list[float|None]:
        return [x.delta_container_mass for x in self.sorted_candidate_evaluations]
    def getEquipments(self) -> list[Equipment]:
        return [x.equipment for x in self.sorted_candidate_evaluations]
    def getDistances(self) -> list[float]:
        return [x.distance for x in self.sorted_candidate_evaluations]
    def getScores(self) -> list[float]:
        return [x.evaluation_score for x  in self.sorted_candidate_evaluations]
    def getSizeClusterMultipliers(self) -> list[float]:
        return [x.size_cluster_multiplier for x in self.sorted_candidate_evaluations]
