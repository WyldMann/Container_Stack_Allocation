from dataclasses import dataclass


_ACCESS_STRENGTH = {"off": 0, "heuristic": 1, "feasibility": 2}


@dataclass(frozen=True)
class FeasibilitySettings:
    stacking_safety: bool = True
    # Keep the legacy switches for Python callers. Explicit modes take precedence.
    loader_access: bool = True
    preserve_future_loader_access: bool = True
    ignore_full_stacks_for_loader_access: bool = False
    loader_access_mode: str | None = None
    preserve_future_loader_access_mode: str | None = None
    stacking_safety_mode: str | None = None
    stack_capacity_mode: str = "feasibility"

    def __post_init__(self) -> None:
        for name in (
            "stacking_safety", "loader_access", "preserve_future_loader_access",
            "ignore_full_stacks_for_loader_access",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a boolean.")
        for name in ("stack_capacity_mode", "stacking_safety_mode", "loader_access_mode", "preserve_future_loader_access_mode"):
            value = getattr(self, name)
            if value is None and name != "stack_capacity_mode":
                continue
            if not isinstance(value, str) or value not in _ACCESS_STRENGTH:
                raise ValueError(f"{name} must be 'off', 'heuristic', or 'feasibility'.")
        current = self.effective_loader_access_mode
        future = self.effective_future_loader_access_mode
        if _ACCESS_STRENGTH[future] > _ACCESS_STRENGTH[current]:
            raise ValueError(
                f'preserve_future_loader_access_mode = "{future}" exceeds '
                f'loader_access_mode = "{current}". Future access must use the same or a weaker mode.'
            )

    @property
    def effective_stacking_safety_mode(self) -> str:
        if self.stacking_safety_mode is not None:
            return self.stacking_safety_mode
        return "feasibility" if self.stacking_safety else "off"

    @property
    def effective_loader_access_mode(self) -> str:
        if self.loader_access_mode is not None:
            return self.loader_access_mode
        return "feasibility" if self.loader_access else "off"

    @property
    def effective_future_loader_access_mode(self) -> str:
        if self.preserve_future_loader_access_mode is not None:
            return self.preserve_future_loader_access_mode
        return self.effective_loader_access_mode if self.preserve_future_loader_access else "off"

    @property
    def prioritize_current_loader_access(self) -> bool:
        return self.effective_future_loader_access_mode == self.effective_loader_access_mode == "heuristic"
