from dataclasses import dataclass


_ACCESS_STRENGTH = {"off": 0, "heuristic": 1, "feasibility": 2}


@dataclass(frozen=True)
class FeasibilitySettings:
    stacking_safety: bool = True
    # Keep the legacy switches for Python callers. Explicit modes take precedence.
    equipment_access: bool = True
    preserve_future_access: bool = True
    ignore_stacks_without_legal_next_tier: bool = False
    equipment_access_mode: str | None = None
    preserve_future_access_mode: str | None = None
    stacking_safety_mode: str | None = None
    stack_capacity_mode: str = "feasibility"
    destination_access_mode: str | None = None
    preserve_occupied_access_mode: str | None = None
    stacking_safety_maxima: int = 2
    stacking_safety_neighbor_up: bool = True
    stacking_safety_neighbor_down: bool = True
    stacking_safety_neighbor_left: bool = False
    stacking_safety_neighbor_right: bool = False
    stacking_safety_penalty_start: int | None = None

    def __post_init__(self) -> None:
        if type(self.stacking_safety_maxima) is not int or self.stacking_safety_maxima < 1:
            raise ValueError("stacking_safety_maxima must be a positive integer.")
        if self.stacking_safety_penalty_start is None:
            object.__setattr__(self, "stacking_safety_penalty_start", 0)
        if type(self.stacking_safety_penalty_start) is not int or not 0 <= self.stacking_safety_penalty_start < self.stacking_safety_maxima:
            raise ValueError("stacking_safety_penalty_start must be a non-negative integer below stacking_safety_maxima.")
        for name in (
            "stacking_safety", "equipment_access", "preserve_future_access",
            "ignore_stacks_without_legal_next_tier",
            "stacking_safety_neighbor_up", "stacking_safety_neighbor_down",
            "stacking_safety_neighbor_left", "stacking_safety_neighbor_right",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a boolean.")
        for name in (
            "stack_capacity_mode", "stacking_safety_mode", "equipment_access_mode",
            "destination_access_mode", "preserve_occupied_access_mode",
            "preserve_future_access_mode",
        ):
            value = getattr(self, name)
            if value is None and name != "stack_capacity_mode":
                continue
            if name == "stacking_safety_mode" and value == "combined":
                continue
            if not isinstance(value, str) or value not in _ACCESS_STRENGTH:
                choices = "'off', 'heuristic', 'feasibility', or 'combined'" if name == "stacking_safety_mode" else "'off', 'heuristic', or 'feasibility'"
                raise ValueError(f"{name} must be {choices}.")
        current = self.effective_occupied_access_mode
        future = self.effective_future_access_mode
        if self.preserve_occupied_access_mode is None and _ACCESS_STRENGTH[future] > _ACCESS_STRENGTH[current]:
            raise ValueError(
                f'preserve_future_access_mode = "{future}" exceeds '
                f'equipment_access_mode = "{current}". Future access must use the same or a weaker mode.'
            )

    @property
    def stacking_safety_neighbors(self) -> tuple[str, ...]:
        return tuple(direction for direction in ("up", "down", "left", "right")
                     if getattr(self, "stacking_safety_neighbor_" + direction))

    @property
    def effective_stacking_safety_mode(self) -> str:
        if self.stacking_safety_mode is not None:
            return self.stacking_safety_mode
        return "feasibility" if self.stacking_safety else "off"

    @property
    def effective_equipment_access_mode(self) -> str:
        if self.equipment_access_mode is not None:
            return self.equipment_access_mode
        return "feasibility" if self.equipment_access else "off"

    @property
    def effective_destination_access_mode(self) -> str:
        return self.destination_access_mode or self.effective_equipment_access_mode

    @property
    def effective_occupied_access_mode(self) -> str:
        return self.preserve_occupied_access_mode or self.effective_equipment_access_mode

    @property
    def effective_future_access_mode(self) -> str:
        if self.preserve_future_access_mode is not None:
            return self.preserve_future_access_mode
        return self.effective_occupied_access_mode if self.preserve_future_access else "off"

    @property
    def prioritize_current_access(self) -> bool:
        return self.effective_future_access_mode == self.effective_occupied_access_mode == "heuristic"

    @property
    def prioritize_destination_access(self) -> bool:
        return self.prioritize_current_access and self.destination_access_mode is None and (
            self.effective_destination_access_mode == "heuristic"
        )

    @property
    def equipment_access_modes(self) -> tuple[str, str, str]:
        return (self.effective_destination_access_mode, self.effective_occupied_access_mode,
                self.effective_future_access_mode)
