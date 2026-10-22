from .container import Container

"""
missing parameters:
    container type: not in Parameter database
"""

class Parameter:
    parameter_id: str
    parameter_name: str
    principal: str
    principal_score: int
    container_condition: str
    container_condition_score: int
    container_fill: str
    container_fill_score: int
    operation_type: str
    operation_type_score: int
    container_size: str
    container_size_score: int
    container_grade: list[str]
    container_grade_score: int
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
    max_score: float

    def __init__(self,
                 parameter_id:str,
                 parameter_name:str,
                 principal:str,
                 principal_score:str,
                 container_condition:str,
                 container_condition_score:str,
                 container_fill:str,
                 container_fill_score:str,
                 container_size:str,
                 container_size_score:str,
                 container_grade:str,
                 container_grade_score:str,
                 pol:str,
                 pod:str,
                 vessel:str,
                 voyage:str,
                 weight_start:str,
                 weight_end:str,
                 vessel_voyage_score:str,
                 weight_range_score:str,
                 route_score:str,
                 and_score:str = "",
                 operation_type:str = "",
                 operation_type_score:str = "",
                 **_kwargs):

        self.parameter_id = parameter_id
        self.parameter_name = parameter_name
        self.principal = principal
        self.principal_score = int(principal_score) if principal_score != '' else 0
        self.container_condition = container_condition
        self.container_condition_score = int(container_condition_score) if container_condition_score != '' else 0
        self.container_fill = container_fill
        self.container_fill_score = int(container_fill_score) if container_fill_score != '' else 0
        self.operation_type = operation_type
        self.operation_type_score = int(operation_type_score) if operation_type_score != '' else 0
        self.container_size = container_size
        self.container_size_score = int(container_size_score) if container_size_score != '' else 0
        self.container_grade = container_grade.split(",")
        self.container_grade_score = int(container_grade_score) if container_grade_score != '' else 0
        self.pol = pol
        self.pod = pod
        self.vessel = vessel
        self.voyage = voyage
        self.weight_start = float(weight_start) if weight_start != '' else 0
        self.weight_end = float(weight_end) if weight_end != '' else float("inf")
        self.vessel_voyage_score = int(vessel_voyage_score) if vessel_voyage_score != '' else 0
        self.weight_range_score = int(weight_range_score) if weight_range_score != '' else 0
        self.route_score = int(route_score) if route_score != '' else 0
        self.and_score = int(and_score) if and_score != '' else None
        self.max_score = self._calculateMaxScore()

    def __str__(self): return self.parameter_id

    # getters
    def getId(self) -> str: return self.parameter_id
    def getName(self) -> str: return self.parameter_name
    def getPrincipal(self) -> str: return self.principal
    def getPrincipalScore(self) -> int: return self.principal_score
    def getCondCondition(self) -> str: return self.container_condition
    def getCondConditionScore(self) -> int: return self.container_condition_score
    def getCondFill(self) -> str: return self.container_fill
    def getCondFillScore(self) -> int: return self.container_fill_score
    def getOpType(self) -> str: return self.operation_type
    def getOpTypeScore(self) -> int: return self.operation_type_score
    def getContSize(self) -> str: return self.container_size
    def getContSizeScore(self) -> int: return self.container_size_score
    def getContGrade(self) -> list[str]: return self.container_grade
    def getContGradeScore(self) -> int: return self.container_grade_score
    def getPol(self) -> str: return self.pol
    def getPod(self) -> str: return self.pod
    def getVessel(self) -> str: return self.vessel
    def getVoyage(self) -> str: return self.voyage
    def getWeightStart(self) -> float: return self.weight_start
    def getWeightEnd(self) -> float: return self.weight_end
    def getVesselVoyageScore(self) -> int: return self.vessel_voyage_score
    def getWeightRangeScore(self) -> int: return self.weight_range_score
    def getRouteScore(self) -> int: return self.route_score
    def getMaxScore(self) -> float: return self.max_score

    def _calculateMaxScore(self) -> float:
        """Cache the fixed maximum; recalculate if criteria or scores change."""
        if self.and_score is not None:
            return float(self.and_score)

        criteria = (
            (self.principal_score, (self.principal,)),
            (self.container_condition_score, (self.container_condition,)),
            (self.container_fill_score, (self.container_fill,)),
            (self.operation_type_score, (self.operation_type,)),
            (self.container_size_score, (self.container_size,)),
            (self.route_score, (self.pol, self.pod)),
            (self.vessel_voyage_score, (self.vessel, self.voyage)),
            (self.container_grade_score, self.container_grade),
        )
        return float(
            sum(
                score
                for score, values in criteria
                if any(value != "" for value in values)
            )
            + self.weight_range_score
        )

    def compliance(self, container: Container) -> float:
        """Normalize evaluation using the cached maximum (nonnegative scores)."""
        if self.max_score <= 0:
            return 0.0
        return self.evaluate(container) / self.max_score

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
                self.container_condition_score,
                ((self.container_condition, container.getContCondition() or "AV"),),
            ),
            (
                self.container_fill_score,
                ((self.container_fill, container.getContFill()),),
            ),
            (
                self.operation_type_score,
                ((self.operation_type, container.getOpType()),),
            ),
            (
                self.container_size_score,
                ((self.container_size, container.getContSize()),),
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
        grades = [grade for grade in self.container_grade if grade]
        if grades:
            matched = grades == ["ALL"] or container.getContGrade() in grades
            yield matched, self.container_grade_score

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
