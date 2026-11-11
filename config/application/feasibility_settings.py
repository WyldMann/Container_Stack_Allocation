from dataclasses import dataclass


@dataclass(frozen=True)
class FeasibilitySettings:
    stacking_safety: bool = True
    loader_access: bool = True
    preserve_future_loader_access: bool = True
    ignore_full_stacks_for_loader_access: bool = False

    def __post_init__(self) -> None:
        for name in (
            "stacking_safety", "loader_access", "preserve_future_loader_access",
            "ignore_full_stacks_for_loader_access",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a boolean.")
