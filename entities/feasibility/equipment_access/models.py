from dataclasses import dataclass

Position = tuple[int, int]


@dataclass(frozen=True)
class BlockBorderAccessPolicy:
    """Borders providing entry and exterior working space for ground equipment."""

    above: bool = True
    below: bool = True
    left: bool = True
    right: bool = True


@dataclass(frozen=True)
class ReceivingLocation:
    """An equipment service location, identified by its anchor and size."""

    row_index: int
    slot_index: int
    container_size: str


@dataclass(frozen=True)
class EquipmentAccessResult:
    isolated_locations: tuple[ReceivingLocation, ...] = ()
    destination_accessible: bool = True
    isolated_occupied_locations: tuple[ReceivingLocation, ...] = ()

    @property
    def allowed(self) -> bool:
        return (
            self.destination_accessible
            and not self.isolated_occupied_locations
            and not self.isolated_locations
        )
