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
                "stacking_safety_maxima": settings.stacking_safety_maxima,
                "stacking_safety_penalty_start": settings.stacking_safety_penalty_start,
                **{"stacking_safety_neighbor_" + direction: getattr(settings, "stacking_safety_neighbor_" + direction)
                   for direction in ("up", "down", "left", "right")},
                "stack_capacity_mode": settings.stack_capacity_mode,
                **({"equipment_access_mode": settings.effective_equipment_access_mode}
                   if settings.destination_access_mode is None
                   or settings.preserve_occupied_access_mode is None else {}),
                **({"destination_access_mode": settings.destination_access_mode}
                   if settings.destination_access_mode is not None else {}),
                **({"preserve_occupied_access_mode": settings.preserve_occupied_access_mode}
                   if settings.preserve_occupied_access_mode is not None else {}),
                "preserve_future_access_mode": settings.effective_future_access_mode,
                "ignore_stacks_without_legal_next_tier": settings.ignore_stacks_without_legal_next_tier,
                "reach_stacker_20ft_side_access": settings.reach_stacker_20ft_side_access,
            },
            "heuristic": {name: value for name, value in asdict(self.heuristic).items() if value is not None},
        }
