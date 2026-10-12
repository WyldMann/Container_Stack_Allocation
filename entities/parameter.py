from .container import Container

"""
missing parameters:
    container type: not in Parameter database
    operation type: not in Container database
"""

class Parameter:
    id: str
    name: str
    principal: str
    principal_score: int
    cont_condition: str
    cont_condition_score: int
    cont_fill: str
    cont_fill_score: int
    cont_size: str
    cont_size_score: int
    cont_grade: list[str]
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
    and_score: int|None

    def __init__(self,
                 PARAM_ID:str,
                 PARAM_NAME:str,
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
                 AND_SCORE:str = "",
                 **_kwargs):

        self.id = PARAM_ID
        self.name = PARAM_NAME
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
        self.cont_grade = CONT_GRADE.split(",")
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
        self.and_score = int(AND_SCORE) if AND_SCORE != '' else None

    def __str__(self): return self.id

    # getters
    def getId(self) -> str: return self.id
    def getName(self) -> str: return self.name
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
    def getContGrade(self) -> list[str]: return self.cont_grade
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

    @staticmethod
    def _matchesText(expected: str, actual: str) -> bool:
        return expected in ("", "ALL") or expected == actual

    def _evaluateCriteria(self, container: Container):
        # All comparisons within an entry must match to earn its score.
        criteria = (
            (
                self.principal_score,
                ((self.principal, container.getPrincipal()),),
            ),
            (
                self.cont_condition_score,
                ((self.cont_condition, container.getContCondition()),),
            ),
            (
                self.cont_fill_score,
                ((self.cont_fill, container.getContFill()),),
            ),
            (
                self.cont_size_score,
                ((self.cont_size, container.getContSize()),),
            ),
            (
                self.route_score,
                (
                    (self.pol, container.getPol()),
                    (self.pod, container.getPod()),
                ),
            ),
            (
                self.vessel_voyage_score,
                (
                    (self.vessel, container.getVessel()),
                    (self.voyage, container.getVoyage()),
                ),
            ),
        )

        for score, comparisons in criteria:
            # Ignore a criterion when all its expected values are blank.
            if not any(expected != "" for expected, _ in comparisons):
                continue
            matched = all(
                self._matchesText(expected, actual)
                for expected, actual in comparisons
            )
            yield matched, score

        # Grade uses membership rather than a single-value comparison.
        grades = [grade for grade in self.cont_grade if grade]
        if grades:
            matched = grades == ["ALL"] or container.getContGrade() in grades
            yield matched, self.cont_grade_score

        # Missing container weight does not impose a requirement in either mode.
        weight = container.getWeight()
        if weight is not None:
            matched = self.weight_start <= weight <= self.weight_end
            yield matched, self.weight_range_score

    def evaluate(self, container: Container) -> float:
        if self.and_score is None:
            return self.evaluateAdd(container)
        return self.evaluateAnd(container)

    def evaluateAdd(self, container: Container) -> float:
        total_score = 0
        total_possible = 0
        for matched, score in self._evaluateCriteria(container):
            total_possible += score
            if matched:
                total_score += score
        return total_score if total_possible != 0 else 0

    def evaluateAnd(self, container: Container) -> float:
        if self.and_score is None:
            return 0
        if all(matched for matched, _ in self._evaluateCriteria(container)):
            return self.and_score
        return 0
