from utils import coord_handling
import math


class Equipment:
    code: str
    coords: tuple[str,int,int]
    def __init__(self,
                 code: str,
                 coords: tuple[str,int,int] = ('',-1,-1)):
        self.code = code
        self.coords = coords
    def __str__(self): return self.code
    def getCode(self) -> str: return self.code
    def getCoords(self) -> tuple[str,int,int]: return self.coords
    def getCoordsStr(self) -> tuple[str,str,str]: return self.coords[0],str(self.coords[1] + 1),str(self.coords[2] + 1)
    def inBlockMove (self, row:int, slot:int):
        self.coords = (self.coords[0],row,slot)
    def inBlockDistance (self, row:int, slot:int) -> float:
        return math.sqrt((row - self.coords[1]) ** 2 + (slot - self.coords[2]) ** 2)
    def print(self):
        print(self.code,"-", coord_handling.toIDSlotRow(self.getCoordsStr()))

class RTG(Equipment):
    def __init__(self,code:str,coords:tuple[str,int,int]) -> None:
        super().__init__(code,coords)

class Loader(Equipment):
    def __init__(self,code:str,coords:tuple[str,int,int]) -> None:
        super().__init__(code,coords)
    def outBlockMove (self, block:str, row:int, slot:int):
        self.coords = (block,row,slot)