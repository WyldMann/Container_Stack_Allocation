import math


class Equipment:
    equipment_code: str
    coordinates: tuple[str,int,int]
    def __init__(self,
                 equipment_code: str,
                 coordinates: tuple[str,int,int] = ('',-1,-1)):
        self.equipment_code = equipment_code
        self.coordinates = coordinates
    def __str__(self): return self.equipment_code
    def getCode(self) -> str: return self.equipment_code
    def getCoords(self) -> tuple[str,int,int]: return self.coordinates
    def getCoordsStr(self) -> tuple[str,str,str]: return self.coordinates[0],str(self.coordinates[1] + 1),str(self.coordinates[2] + 1)
    def inBlockMove (self, row_index:int, slot_index:int):
        self.coordinates = (self.coordinates[0],row_index,slot_index)
    def inBlockDistance (self, row_index:int, slot_index:int) -> float:
        return math.sqrt((row_index - self.coordinates[1]) ** 2 + (slot_index - self.coordinates[2]) ** 2)

class RTG(Equipment):
    def __init__(self,equipment_code:str,coordinates:tuple[str,int,int]) -> None:
        super().__init__(equipment_code,coordinates)

class Loader(Equipment):
    def __init__(self,equipment_code:str,coordinates:tuple[str,int,int]) -> None:
        super().__init__(equipment_code,coordinates)
    def outBlockMove (self, block_id:str, row_index:int, slot_index:int):
        self.coordinates = (block_id,row_index,slot_index)