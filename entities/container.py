"""
Warning:
    this class must not reference Stack or it will cause circular dependency and by extension, circ. import.
"""

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
    weight: float
    # coords = [Block, Row, Slot, Tier]
    coords: list[str|None]

    def __init__(self,
                 CONTNO:str,
                 PRINCIPAL:str,
                 DMG_FLG:str,
                 FULLMT:str,
                 # OPERATION_TYPE:str,
                 CONTSIZE:str,
                 CONT_GRADE:str,
                 POL:str,
                 POD:str,
                 VESSEL_OPERATOR:str,
                 VESSEL_VOYAGE:str,
                 WEIGHT:str,

                 BLOK:str | None = None,
                 SLOT:str | None = None,
                 ROW:str | None = None,
                 TIER:str | None = None,

                 #TIER: Stack,
                 #TIERHEIGHT: int,

                 **kwargs
                 ):

        self.id = CONTNO
        self.principal = PRINCIPAL
        self.cont_condition = DMG_FLG
        self.cont_fill = FULLMT
        #self.op_type = OPERATION_TYPE
        self.cont_size = CONTSIZE
        self.cont_grade = CONT_GRADE
        self.pol = POL
        self.pod = POD
        self.vessel = VESSEL_OPERATOR
        self.voyage = VESSEL_VOYAGE
        self.weight = float(WEIGHT)
        if BLOK is not None or SLOT is not None or ROW is not None or TIER is not None:
            self.coords = [BLOK, ROW, SLOT, TIER]
        else: self.coords = []

        """ shouldn't need tier
        # only modifies this class's tier attr.
        # change the tier.containers outside of this class to avoid circular dependence
        if TIER.isEmpty(TIERHEIGHT):
            self.tier = TIER
            self.tierHeight = TIERHEIGHT
        else: print("Occupied")
        """

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
    def getWeight(self) -> float: return self.weight
    def getCoords(self) -> list[str|None]: return self.coords

    def setCoords(self, block: str, row: str, slot: str, tier: str): self.coords = [block, row, slot, tier]

    def isIncomplete(self) -> bool: return "" in self.coords

    def __str__(self):
        return self.id