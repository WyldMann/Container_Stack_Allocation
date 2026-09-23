import math
from dataclasses import dataclass

@dataclass
class HeuristicModel:
    wDeltaWeight = 10
    hlDeltaWeight = 5000

    lambdaDeltaWeight = math.log(2) / hlDeltaWeight

    wEquipmentDistance = 10
    hlEquipmentDistance = 5

    lambdaEquipmentDistance = math.log(2) / hlEquipmentDistance

    min_value = 0.001
    no_delta_weight_value = 0.1

    @staticmethod
    def decayFormula(lambda_: float, variable:float) -> float:
        return math.exp(-lambda_*variable)

    def deltaWeight(self,deltaWeight:float | None):
        if deltaWeight is None:
            return self.no_delta_weight_value
        if deltaWeight < 0:
            return self.min_value

        else: return self.wDeltaWeight * self.decayFormula(self.lambdaDeltaWeight,deltaWeight)

    def equipmentDistance(self,equipmentDistance:float):
        if equipmentDistance == float('inf'):
            return self.min_value
        else:
            return self.wEquipmentDistance * self.decayFormula(self.lambdaEquipmentDistance,equipmentDistance)

    #multiplicative weights
    def evaluate(self,deltaWeight:float, equipmentDistance:float):
        return self.deltaWeight(deltaWeight) * self.equipmentDistance(equipmentDistance)