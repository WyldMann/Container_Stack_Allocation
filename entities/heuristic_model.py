import math
from dataclasses import dataclass

@dataclass
class HeuristicModel:
    wDeltaWeight = 1
    hlDeltaWeight = 5000

    lambdaDeltaWeight = math.log(2) / hlDeltaWeight

    wEquipmentDistance = 1
    hlEquipmentDistance = 5

    lambdaEquipmentDistance = math.log(2) / hlEquipmentDistance

    @staticmethod
    def decayFormula(lambda_: float, variable:float) -> float:
        return math.exp(-lambda_*variable)

    def deltaWeight(self,deltaWeight:float):
        if deltaWeight < 0:
            return 0.01
        else: return self.wDeltaWeight * self.decayFormula(self.lambdaDeltaWeight,deltaWeight)

    def equipmentDistance(self,equipmentDistance:float):
        if equipmentDistance == float('inf'):
            return 0.01
        else:
            return self.wEquipmentDistance * self.decayFormula(self.lambdaEquipmentDistance,equipmentDistance)

    #multiplicative weights
    def evaluate(self,deltaWeight:float, equipmentDistance:float):
        return self.deltaWeight(deltaWeight) * self.equipmentDistance(equipmentDistance)