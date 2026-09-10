import math


class Equipment:
    code: str
    coords: tuple[str,int,int]
    def __init__(self,
                 code: str,
                 coords: tuple[str,int,int] = ('',-1,-1)):
        self.code = code
        self.coords = coords
    def getCode(self) -> str: return self.code
    def getCoords(self) -> tuple[str,int,int]: return self.coords
    def getCoordsStr(self) -> tuple[str,str,str]: return self.coords[0],str(self.coords[1] + 1),str(self.coords[2] + 1)

class RTG(Equipment):
    def __init__(self,code:str,coords:tuple[str,int,int]) -> None:
        super().__init__(code,coords)
    def moveRTG (self, row:int, slot:int):
        self.coords = (self.coords[0],row,slot)
    def rtgDistance (self,row:int,slot:int) -> float:
        return math.sqrt((row - self.coords[1]) ** 2 + (row - self.coords[2]) ** 2)