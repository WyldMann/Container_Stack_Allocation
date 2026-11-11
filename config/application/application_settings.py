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
                "stacking_safety": settings.stacking_safety,
                "loader_access_mode": settings.effective_loader_access_mode,
                "preserve_future_loader_access_mode": settings.effective_future_loader_access_mode,
                "ignore_full_stacks_for_loader_access": settings.ignore_full_stacks_for_loader_access,
            },
            "heuristic": asdict(self.heuristic),
        }
