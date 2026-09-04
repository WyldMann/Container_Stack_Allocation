"""
Warning:
    this class must not reference Stack or it will cause circular dependency and by extension, circ. import.
"""
from datetime import datetime
from utils.parse_datetime import parse_datetime


class Container:
    id: str

    #tier: Stack
    #tierHeight: int

    principal: str
    cont_condition: str
    cont_fill: str
    cont_size: str
    cont_grade: str
    pol: str
    pod: str
    vessel: str
    voyage: str
    weight: float| None
    # coords = [Branch, Block, Row, Slot, Tier]
    coords: list[str]
    move_time: datetime

    def __init__(self,
                 CONTNO:str,
                 PRINCIPAL:str,
                 DMG_FLAG:str,
                 FULLMT:str,
                 # OPERATION_TYPE:str,
                 CONTSIZE:str,
                 CONT_GRADE:str,
                 POL:str,
                 POD:str,
                 VESSEL_OPERATOR:str,
                 VESSEL_VOYAGE:str,
                 WEIGHT:str,

                 MOVE_TIME: str,

                 BRANCH:str|None = None,
                 BLOK:str | None = None,
                 SLOT:str | None = None,
                 ROW:str | None = None,
                 TIER:str | None = None,

                 #TIER: Stack,
                 #TIERHEIGHT: int,

                 **_kwargs
                 ):

        self.id = CONTNO
        self.principal = PRINCIPAL
        self.cont_condition = DMG_FLAG
        self.cont_fill = FULLMT
        #self.op_type = OPERATION_TYPE
        self.cont_size = CONTSIZE
        self.cont_grade = CONT_GRADE
        self.pol = POL
        self.pod = POD
        self.vessel = VESSEL_OPERATOR
        self.voyage = VESSEL_VOYAGE
        self.weight = float(WEIGHT) if WEIGHT != '' else None
        self.move_time = parse_datetime(MOVE_TIME)

        if BRANCH is None: BRANCH = ""
        if BLOK is None: BLOK = ""
        if SLOT is None: SLOT = ""
        if ROW is None: ROW = ""
        if TIER is None: TIER = ""

        self.coords = [BRANCH,BLOK,ROW,SLOT,TIER]

    def getId(self) -> str: return self.id
    def getPrincipal(self) -> str: return self.principal
    def getContCondition(self) -> str: return self.cont_condition
    def getContFill(self) -> str: return self.cont_fill
    #def getOpType(self) -> str: return self.op_type
    def getContSize(self) -> str: return self.cont_size
    def getContGrade(self) -> str: return self.cont_grade
    def getPol(self) -> str: return self.pol
    def getPod(self) -> str: return self.pod
    def getVessel(self) -> str: return self.vessel
    def getVoyage(self) -> str: return self.voyage
    def getWeight(self) -> float|None: return self.weight
    def getMoveTime(self) -> datetime: return self.move_time
    def getCoords(self) -> list[str]: return self.coords
    def setCoords(self, branch:str, block: str, row: str, slot: str, tier: str):
        self.coords = [branch,block, row, slot, tier]
    def getCoordsTuple(self) -> tuple[str,str,str,str,str]:
        return self.coords[0],self.coords[1],self.coords[2],self.coords[3],self.coords[4]

    # coordsInt changes relevant data to str/int and follows 0-based indexing instead of database's 1-based indexing
    def getCoordsInt(self) -> tuple[str,str,int,int,int]:
        return self.coords[0],self.coords[1],int(self.coords[2]) - 1,int(self.coords[3]) - 1,int(self.coords[4]) - 1
    def setCoordsInt(self, coordsInt: tuple[str,str,int,int,int]):
        self.coords = [coordsInt[0], coordsInt[1],str(coordsInt[2] + 1),str(coordsInt[3] + 1),str(coordsInt[4] + 1)]

    # same goes for tierInt for coords[3]
    def setTierInt(self,tierInt: int):
        self.coords[4] = str(tierInt + 1)

    def isIncomplete(self) -> bool: return "" in self.coords or self.id == ""

    def __str__(self):
        return self.id

# special container to be filled in gaps of anomalous stacks
class DummyContainer(Container):
    #[(block_id,row,slot,tier),...]
    coordsList:set[tuple[str,str,str,str]]

    def __init__(self):
        super().__init__("DUMMY","","","","","","","","","","","","","","","","")
        self.coordsList = set()
    def addCoordList(self,coords:tuple[str,int,int],tier:int):
        self.coordsList.add((coords[0], str(coords[1] + 1), str(coords[2] + 1),str(tier + 1)))

    def removeCoordList(self,coords:tuple[str,str,str,str]): self.coordsList.remove(coords)

    def replaceDummy(self,container:Container,blockID:str):
        containerCoords = container.getCoords()
        self.removeCoordList((blockID,containerCoords[2],containerCoords[3],containerCoords[4]))

    def getCoordsList(self) -> set[tuple[str,str,str,str]]: return self.coordsList

    def printCoordsList(self):
        for coords in self.coordsList:
            print(coords)