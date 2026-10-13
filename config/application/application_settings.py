from dataclasses import dataclass, field

from .feasibility_settings import FeasibilitySettings
from .heuristic_settings import HeuristicSettings


@dataclass(frozen=True)
class ApplicationSettings:
    feasibility: FeasibilitySettings = field(default_factory=FeasibilitySettings)
    heuristic: HeuristicSettings = field(default_factory=HeuristicSettings)
