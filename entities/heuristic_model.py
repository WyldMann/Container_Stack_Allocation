import math
from typing import Final

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
    def evaluate(self,deltaWeight:float|None, equipmentDistance:float):
        return self.deltaWeight(deltaWeight) * self.equipmentDistance(equipmentDistance)
