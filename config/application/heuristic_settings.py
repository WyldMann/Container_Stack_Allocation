import math
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class HeuristicSettings:
    # Default values; options supplied in config.toml override these.
    w_delta_container_mass: float = 10.0
    hl_delta_container_mass: float = 5000.0
    w_equipment_distance: float = 10.0
    hl_equipment_distance: float = 5.0
    min_value: float = 0.001
    no_delta_container_mass_value: float = 0.1
    size_cluster_radius: int = 3
    hl_size_cluster_distance: float = 1.5
    size_cluster_prior: float = 2.0
    size_cluster_bias: float = 1.0
    enable_delta_container_mass: bool = True
    enable_equipment_distance: bool = True
    enable_size_cluster: bool = True

    def __post_init__(self) -> None:
        radius = self.size_cluster_radius
        if type(radius) is not int:
            raise TypeError("size_cluster_radius must be an integer.")
        if radius < 0:
            raise ValueError("size_cluster_radius must be non-negative.")

        for field in fields(self):
            name = field.name
            value = getattr(self, name)
            if field.type is bool:
                if type(value) is not bool:
                    raise TypeError(f"{name} must be a boolean.")
                continue
            if name == "size_cluster_radius":
                continue
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
