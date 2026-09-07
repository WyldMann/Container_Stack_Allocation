from .container import Container

"""
missing parameters:
    container type: not in Parameter database
    operation type: not in Container database
"""

class Parameter:
    id: str
    principal: str
    principal_score: int
    cont_condition: str
    cont_condition_score: int
    cont_fill: str
    cont_fill_score: int
    cont_size: str
    cont_size_score: int
    cont_grade: str
    cont_grade_score: int
    pol: str
    pod: str
    vessel: str
    voyage: str
    weight_start: float
    weight_end: float
    vessel_voyage_score: int
    weight_range_score: int
    route_score: int

    def __init__(self,
                 PARAM_ID:str,
                 PRINCIPAL:str,
                 PRINCIPAL_SCORE:str,
                 CONT_CONDITION:str,
                 CONT_CONDITION_SCORE:str,
                 CONT_FILL:str,
                 CONT_FILL_SCORE:str,
                 # OPERATION_TYPE:str,
                 # OPERATION_TYPE_SCORE:str,
                 CONT_SIZE:str,
                 CONT_SIZE_SCORE:int,
                 CONT_GRADE:str,
                 CONT_GRADE_SCORE:str,
                 POL:str,
                 POD:str,
                 VESSEL:str,
                 VOYAGE:str,
                 WEIGHT_START:str,
                 WEIGHT_END:str,
                 VESSEL_VOYAGE_SCORE:str,
                 WEIGHT_RANGE_SCORE:str,
                 ROUTE_SCORE:str,
                 **_kwargs):

        self.id = PARAM_ID
        self.principal = PRINCIPAL
        self.principal_score = int(PRINCIPAL_SCORE) if PRINCIPAL_SCORE != '' else 0
        self.cont_condition = CONT_CONDITION
        self.cont_condition_score = int(CONT_CONDITION_SCORE) if CONT_CONDITION_SCORE != '' else 0
        self.cont_fill = CONT_FILL
        self.cont_fill_score = int(CONT_FILL_SCORE) if CONT_FILL_SCORE != '' else 0
        # self.op_type = OPERATION_TYPE
        # self.op_type_score = int(OPERATION_TYPE_SCORE) if OPERATION_TYPE_SCORE != '' else 0
        self.cont_size = CONT_SIZE
        self.cont_size_score = int(CONT_SIZE_SCORE) if CONT_SIZE_SCORE != '' else 0
        self.cont_grade = CONT_GRADE
        self.cont_grade_score = int(CONT_GRADE_SCORE) if CONT_GRADE_SCORE != '' else 0
        self.pol = POL
        self.pod = POD
        self.vessel = VESSEL
        self.voyage = VOYAGE
        self.weight_start = float(WEIGHT_START) if WEIGHT_START != '' else 0
        self.weight_end = float(WEIGHT_END) if WEIGHT_END != '' else float("inf")
        self.vessel_voyage_score = int(VESSEL_VOYAGE_SCORE) if VESSEL_VOYAGE_SCORE != '' else 0
        self.weight_range_score = int(WEIGHT_RANGE_SCORE) if WEIGHT_RANGE_SCORE != '' else 0
        self.route_score = int(ROUTE_SCORE) if ROUTE_SCORE != '' else 0

    def __str__(self): return self.id

    # getters
    def getId(self) -> str: return self.id
    def getPrincipal(self) -> str: return self.principal
    def getPrincipalScore(self) -> int: return self.principal_score
    def getCondCondition(self) -> str: return self.cont_condition
    def getCondConditionScore(self) -> int: return self.cont_condition_score
    def getCondFill(self) -> str: return self.cont_fill
    def getCondFillScore(self) -> int: return self.cont_fill_score
    # def getOpType(self) -> str: return self.op_type
    # def getOpTypeScore(self) -> int: return self.op_type_score
    def getContSize(self) -> str: return self.cont_size
    def getContSizeScore(self) -> int: return self.cont_size_score
    def getContGrade(self) -> str: return self.cont_grade
    def getContGradeScore(self) -> int: return self.cont_grade_score
    def getPol(self) -> str: return self.pol
    def getPod(self) -> str: return self.pod
    def getVessel(self) -> str: return self.vessel
    def getVoyage(self) -> str: return self.voyage
    def getWeightStart(self) -> float: return self.weight_start
    def getWeightEnd(self) -> float: return self.weight_end
    def getVesselVoyageScore(self) -> int: return self.vessel_voyage_score
    def getWeightRangeScore(self) -> int: return self.weight_range_score
    def getRouteScore(self) -> int: return self.route_score


    def evaluate(self, container: Container) -> float:

        totalScore = 0
        totalParam = 0

        if self.principal != '':
            if self.principal == "ALL" or self.principal == container.getPrincipal():
                totalScore += self.principal_score
            totalParam += self.principal_score

        if self.cont_condition != '':
            if self.principal == "ALL" or self.cont_condition == container.getContCondition():
                totalScore += self.cont_condition_score
            totalParam += self.cont_condition_score

        if self.cont_fill != '':
            if self.principal == "ALL" or self.cont_fill == container.getContFill():
                totalScore += self.cont_fill_score
            totalParam += self.cont_fill_score

        """
        if self.op_type != '':
            if self.principal == "ALL" or self.op_type != container.getOpType():
                totalScore += self.op_type_score
            totalParam += self.op_type_score
        """

        if self.cont_size != '':
            if self.principal == "ALL" or self.cont_size == container.getContSize():
                totalScore += self.cont_size_score
            totalParam += self.cont_size_score

        if self.cont_grade != '':
            if self.principal == "ALL" or self.cont_grade == container.getContGrade():
                totalScore += self.cont_grade_score
            totalParam += self.cont_grade_score

        # if container.pod == "" but self.pod != ""?
        if self.pol != '' or self.pod != '':
            if ((self.pol == "ALL" or self.pol == container.getPol() or self.pol == "") and
                    (self.pod == "ALL" or self.pod == container.getPod() or self.pod == "")):
                totalScore += self.route_score
            totalParam += self.route_score

        # vessel voyage
        if self.vessel != '' or self.voyage != '':
            if ((self.vessel == "ALL" or self.vessel == container.getVessel() or self.vessel == "") and
                    (self.voyage == "ALL" or self.voyage == container.getPod() or self.voyage == "")):
                totalScore += self.vessel_voyage_score
            totalParam += self.vessel_voyage_score

        # weight range
        if container.getWeight() is not None:
            if self.weight_start <= container.getWeight() <= self.weight_end:
                totalScore += self.weight_range_score
            totalParam += self.weight_range_score

        if totalParam == 0:
            return 0
        else:
            return totalScore/totalParam * 100

