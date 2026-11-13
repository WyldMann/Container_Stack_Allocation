from dataclasses import asdict, dataclass, field

from .feasibility_settings import FeasibilitySettings
from .heuristic_settings import HeuristicSettings


@dataclass(frozen=True)
class ApplicationSettings:
    feasibility: FeasibilitySettings = field(default_factory=FeasibilitySettings)
    heuristic: HeuristicSettings = field(default_factory=HeuristicSettings)

    def to_document(self) -> dict:
        settings = self.feasibility
        return {
            "feasibility": {
                "stacking_safety_mode": settings.effective_stacking_safety_mode,
                "stack_capacity_mode": settings.stack_capacity_mode,
                **({"loader_access_mode": settings.effective_loader_access_mode}
                   if settings.loader_destination_access_mode is None
                   or settings.preserve_occupied_loader_access_mode is None else {}),
                **({"loader_destination_access_mode": settings.loader_destination_access_mode}
                   if settings.loader_destination_access_mode is not None else {}),
                **({"preserve_occupied_loader_access_mode": settings.preserve_occupied_loader_access_mode}
                   if settings.preserve_occupied_loader_access_mode is not None else {}),
                "preserve_future_loader_access_mode": settings.effective_future_loader_access_mode,
                "ignore_full_stacks_for_loader_access": settings.ignore_full_stacks_for_loader_access,
            },
            "heuristic": asdict(self.heuristic),
        }
