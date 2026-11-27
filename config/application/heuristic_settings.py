import math
from dataclasses import dataclass, fields

BLOCK_STACKING_START_HALF_DISTANCE = 2.0


@dataclass(frozen=True)
class StackingStartPreference:
    axis: str
    position: int | None = None
    half_distance: float | None = None
    enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise TypeError("Stacking start enabled must be a boolean.")
        if self.axis not in ("off", "row", "slot"):
            raise ValueError("Stacking start must use 'off', 'row', or 'slot'.")
        if self.axis == "off":
            if self.enabled:
                raise ValueError("Choose a row or slot before enabling stacking start.")
            if self.position is not None or self.half_distance is not None:
                raise ValueError("A stacking start set to off cannot have a position or half-score distance.")
            return
        if type(self.position) is not int or self.position < 1:
            raise ValueError("Stacking start position must be a positive integer.")
        if self.half_distance is not None:
            if (type(self.half_distance) not in (int, float) or self.half_distance <= 0
                    or not math.isfinite(self.half_distance)):
                raise ValueError("Stacking start half-score distance must be a positive finite number.")


STACKING_START_OFF = StackingStartPreference("off")


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
    # Accept legacy yard-wide settings. Each block now controls its own scoring.
    enable_block_stacking_start: bool = False
    stacking_start_axis: str = "off"
    stacking_start_position: int = 1
    hl_stacking_start_distance: float = 2.0

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
            if name == "stacking_start_axis":
                if value not in ("off", "row", "slot"):
                    raise ValueError("stacking_start_axis must be 'off', 'row', or 'slot'.")
                continue
            if name == "stacking_start_position" and type(value) is not int:
                raise TypeError("stacking_start_position must be an integer.")
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
