from dataclasses import dataclass


@dataclass(frozen=True)
class FeasibilitySettings:
    stacking_safety: bool = True
    loader_access: bool = True

    def __post_init__(self) -> None:
        for name in ("stacking_safety", "loader_access"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a boolean.")
