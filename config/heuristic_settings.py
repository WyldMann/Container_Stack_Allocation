import math
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class HeuristicSettings:
    w_delta_weight: float = 10.0
    hl_delta_weight: float = 5000.0
    w_equipment_distance: float = 10.0
    hl_equipment_distance: float = 5.0
    min_value: float = 0.001
    no_delta_weight_value: float = 0.1
    size_cluster_radius: int = 3
    hl_size_cluster_distance: float = 1.5
    size_cluster_prior: float = 2.0
    size_cluster_bias: float = 1.0

    def __post_init__(self) -> None:
        radius = self.size_cluster_radius
        if type(radius) is not int:
            raise TypeError("size_cluster_radius must be an integer.")
        if radius < 0:
            raise ValueError("size_cluster_radius must be non-negative.")

        for field in fields(self):
            name = field.name
            if name == "size_cluster_radius":
                continue
            value = getattr(self, name)
            if type(value) not in (int, float):
                raise TypeError(f"{name} must be numeric.")
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError(f"{name} must be finite.")
            if name == "size_cluster_bias":
                if value < 0:
                    raise ValueError(f"{name} must be non-negative.")
            elif value <= 0:
                raise ValueError(f"{name} must be positive.")
