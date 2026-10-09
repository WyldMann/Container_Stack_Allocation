from dataclasses import dataclass

from .parameter import Parameter
from .equipment import Equipment
from .container import Container

@dataclass
class CandidateEvaluation:
    coords: tuple[str, int, int, int]
    param: list[Parameter]
    delta_weight: float | None
    equipment: Equipment
    distance: float
    size_cluster_multiplier: float
    eval_score: float

    def getStrParameter(self) -> list[str]:
        return [str(x) for x in self.param]

@dataclass
class AssignResult:
    container: Container
    cont_scores: dict[str,float]
    max_param_score: float
    sortedCandidateEvaluations: list[CandidateEvaluation]

    def getBestCandidate(self) -> CandidateEvaluation:
        return self.sortedCandidateEvaluations[0]
    def getBestCoordinate(self) -> tuple[str, int, int, int]:
        return self.getBestCandidate().coords
    def getStrParameters(self) -> list[list[str]]:
        return [x.getStrParameter() for x in self.sortedCandidateEvaluations]
    def getParameterNames(self) -> list[list[str]]:
        return [[parameter.getName() for parameter in candidate.param]
                for candidate in self.sortedCandidateEvaluations]
    def getBestEquipment(self) -> Equipment:
        return self.getBestCandidate().equipment
    def getCoords(self) -> list[tuple[str,int,int,int]]:
        return [x.coords for x in self.sortedCandidateEvaluations]
    def getDeltaWeights(self) -> list[float|None]:
        return [x.delta_weight for x in self.sortedCandidateEvaluations]
    def getEquipments(self) -> list[Equipment]:
        return [x.equipment for x in self.sortedCandidateEvaluations]
    def getDistances(self) -> list[float]:
        return [x.distance for x in self.sortedCandidateEvaluations]
    def getScores(self) -> list[float]:
        return [x.eval_score for x  in self.sortedCandidateEvaluations]
    def getSizeClusterMultipliers(self) -> list[float]:
        return [x.size_cluster_multiplier for x in self.sortedCandidateEvaluations]
