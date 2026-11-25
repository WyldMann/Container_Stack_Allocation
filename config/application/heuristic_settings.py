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
    # Legacy values supply either independent setting when it is omitted.
    size_cluster_radius: int = 3
    hl_size_cluster_distance: float = 1.5
    size_cluster_prior: float = 2.0
    size_cluster_bias: float = 1.0
    size_cluster_reward_radius: float | None = None
    hl_size_cluster_reward_distance: float | None = None
    size_cluster_reward_prior: float | None = None
    size_cluster_reward_bias: float | None = None
    size_cluster_penalty_radius: int | None = None
    hl_size_cluster_penalty_distance: float | None = None
    size_cluster_penalty_prior: float | None = None
    size_cluster_penalty_bias: float | None = None
    enable_delta_container_mass: bool = True
    enable_equipment_distance: bool = True
    enable_size_cluster: bool = True
    enable_size_cluster_reward: bool | None = None
    enable_size_cluster_penalty: bool | None = None
    unreachable_destination_multiplier: float = 0.25
    occupied_access_loss_weight: float = 1.0
    future_access_loss_weight: float = 1.0
    unsafe_stacking_multiplier: float = 0.25
    stacking_safety_limit_multiplier: float | None = None
    overcapacity_tier_multiplier: float = 0.01
    heavier_container_fallback_score: float | None = None
    equipment_outside_block_fallback_score: float | None = None
    scan_order: str = "slot_wise"

    def __post_init__(self) -> None:
        if self.stacking_safety_limit_multiplier is None:
            object.__setattr__(self, "stacking_safety_limit_multiplier", self.unsafe_stacking_multiplier)
        for term in ("reward", "penalty"):
            name = f"enable_size_cluster_{term}"
            if getattr(self, name) is None:
                object.__setattr__(self, name, self.enable_size_cluster)
            for parameter in ("radius", "prior", "bias"):
                name = f"size_cluster_{term}_{parameter}"
                if getattr(self, name) is None:
                    object.__setattr__(self, name, getattr(self, f"size_cluster_{parameter}"))
            name = f"hl_size_cluster_{term}_distance"
            if getattr(self, name) is None:
                object.__setattr__(self, name, self.hl_size_cluster_distance)

        radius_names = ("size_cluster_radius", "size_cluster_reward_radius", "size_cluster_penalty_radius")
        for name in radius_names:
            radius = getattr(self, name)
            if name == "size_cluster_reward_radius":
                if type(radius) not in (int, float):
                    raise TypeError(f"{name} must be numeric.")
                if type(radius) is float and not math.isfinite(radius):
                    raise ValueError(f"{name} must be finite.")
            elif type(radius) is not int:
                raise TypeError(f"{name} must be an integer.")
            if radius < 0:
                raise ValueError(f"{name} must be non-negative.")

        for field in fields(self):
            name = field.name
            value = getattr(self, name)
            if name == "scan_order":
                if value not in ("row_wise", "slot_wise"):
                    raise ValueError("scan_order must be 'row_wise' or 'slot_wise'.")
                continue
            if value is None and name in (
                "heavier_container_fallback_score", "equipment_outside_block_fallback_score",
            ):
                continue
            if field.type is bool or name in ("enable_size_cluster_reward", "enable_size_cluster_penalty"):
                if type(value) is not bool:
                    raise TypeError(f"{name} must be a boolean.")
                continue
            if name in radius_names:
                continue
            if type(value) not in (int, float):
                raise TypeError(f"{name} must be numeric.")
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError(f"{name} must be finite.")
            if name in (
                "unreachable_destination_multiplier", "unsafe_stacking_multiplier",
                "stacking_safety_limit_multiplier",
                "overcapacity_tier_multiplier",
            ):
                if not 0 <= value <= 1:
                    raise ValueError(f"{name} must be between 0 and 1.")
            elif name in (
                "size_cluster_bias", "size_cluster_reward_bias", "size_cluster_penalty_bias",
                "occupied_access_loss_weight",
                "future_access_loss_weight", "no_delta_container_mass_value",
                "heavier_container_fallback_score",
            ):
                if value < 0:
                    raise ValueError(f"{name} must be non-negative.")
            elif value <= 0:
                raise ValueError(f"{name} must be positive.")
