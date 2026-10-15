"""
Warning:
    this class must not reference Stack or it will cause circular dependency and by extension, circ. import.
    if implementing any sort of coords removal, remember to remove second coords for 40-ft Container
"""
from datetime import datetime
from utils.parse_datetime import parse_datetime
from utils.parse_optional_finite_float import parse_optional_finite_float


class Container:
    container_id: str

    #tier: Stack
    #tierHeight: int

    principal: str
    container_condition: str
    container_fill: str
    container_size: str
    container_grade: str
    pol: str
    pod: str
    vessel: str
    voyage: str
    weight: float | None
    # One-based coordinate strings: branch ID, block code, row, slot, tier.
    coordinates_str: list[str]
    move_time: datetime

    def __init__(self,
                 container_id: str,
                 principal: str,
                 container_condition: str,
                 container_fill: str,
                 container_size: str,
                 container_grade: str,
                 pol: str,
                 pod: str,
                 vessel: str,
                 voyage: str,
                 weight: str,

                 move_time: str,

                 branch_id: str | None = None,
                 block_code: str | None = None,
                 slot_no: str | None = None,
                 row_no: str | None = None,
                 tier_no: str | None = None,

                 operation_type: str = "",
                 pot: str = "",
                 vessel_operator: str = "",
                 **_kwargs
                 ):

        self.container_id = container_id
        self.principal = principal
        self.container_condition = container_condition
        self.container_fill = container_fill
        self.operation_type = operation_type
        self.pot = pot
        self.vessel_operator = vessel_operator
        self.move_time_raw = move_time
        self.container_size = container_size
        self.container_grade = container_grade
        self.pol = pol
        self.pod = pod
        self.vessel = vessel
        self.voyage = voyage
        self.weight = parse_optional_finite_float(weight)
        self.move_time = parse_datetime(move_time)

        if branch_id is None: branch_id = ""
        if block_code is None: block_code = ""
        if slot_no is None: slot_no = ""
        if row_no is None: row_no = ""
        if tier_no is None: tier_no = ""

        self.coordinates_str = [branch_id, block_code, row_no, slot_no, tier_no]

    def getId(self) -> str:
        return self.container_id

    def getPrincipal(self) -> str:
        return self.principal

    def getContCondition(self) -> str:
        return self.container_condition

    def getContFill(self) -> str:
        return self.container_fill

    def getOpType(self) -> str:
        return self.operation_type

    def getPot(self) -> str:
        return self.pot

    def getVesselOperator(self) -> str:
        return self.vessel_operator

    def getMoveTimeRaw(self) -> str:
        return self.move_time_raw

    def getContSize(self) -> str:
        return self.container_size

    def getContGrade(self) -> str:
        return self.container_grade

    def getPol(self) -> str:
        return self.pol

    def getPod(self) -> str:
        return self.pod

    def getVessel(self) -> str:
        return self.vessel

    def getVoyage(self) -> str:
        return self.voyage

    def getWeight(self) -> float | None:
        return self.weight

    def getMoveTime(self) -> datetime:
        return self.move_time

    def getCoordsStr(self) -> list[str]:
        return self.coordinates_str

    def setCoordsStr(self, branch_id: str, block_code: str, row_no: str, slot_no: str, tier_no: str):
        self.coordinates_str = [branch_id, block_code, row_no, slot_no, tier_no]

    def getCoordsStrTuple(self) -> tuple[str, str, str, str, str]:
        return self.coordinates_str[0], self.coordinates_str[1], self.coordinates_str[2], self.coordinates_str[3], self.coordinates_str[4]

    # Integer coordinates use zero-based row, slot, and tier indices.
    def getCoordsInt(self) -> tuple[str, str, int, int, int]:
        return self.coordinates_str[0], self.coordinates_str[1], int(self.coordinates_str[2]) - 1, int(self.coordinates_str[3]) - 1, int(
            self.coordinates_str[4]) - 1

    def setCoordsInt(self, coordinates: tuple[str, str, int, int, int]):
        self.coordinates_str = [coordinates[0], coordinates[1], str(coordinates[2] + 1), str(coordinates[3] + 1),
                          str(coordinates[4] + 1)]

    # Disabled: tier-only movement was used solely by anomaly repair.
    # def setTierInt(self, tier_index: int):
    #     self.coordinates_str[4] = str(tier_index + 1)

    def __str__(self):
        return self.container_id


# special container to be filled in gaps of anomalous stacks
class DummyContainer(Container):
    #[(block_id,row,slot,tier),...]
    coordinates_list: set[tuple[str, str, str, str]]

    def __init__(self):
        super().__init__(
            container_id="DUMMY", principal="", container_condition="",
            container_fill="", container_size="", container_grade="",
            pol="", pod="", vessel="", voyage="", weight="", move_time="",
        )
        self.coordinates_list = set()

    # Disabled: coordinate helpers belonged to the unused dummy-repair path.
    # def addCoordList(self, coordinates: tuple[str, int, int], tier_index: int):
    #     self.coordinates_list.add((coordinates[0], str(coordinates[1] + 1), str(coordinates[2] + 1), str(tier_index + 1)))

    # def removeCoordList(self, coordinates: tuple[str, str, str, str]): self.coordinates_list.remove(coordinates)

    # def replaceDummy(self, container: Container, block_id: str):
    #     container_coords = container.getCoordsStr()
    #     self.removeCoordList((block_id, container_coords[2], container_coords[3], container_coords[4]))

    # def getCoordsList(self) -> set[tuple[str, str, str, str]]: return self.coordinates_list
