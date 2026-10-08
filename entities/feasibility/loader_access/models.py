from dataclasses import dataclass

Position = tuple[int, int]


@dataclass(frozen=True)
class LoaderBorderAccessPolicy:
    """Borders providing loader entry and exterior working space."""

    above: bool = True
    below: bool = True
    left: bool = True
    right: bool = True


@dataclass(frozen=True)
class ReceivingLocation:
    """A potential destination, identified by its anchor and size."""

    row: int
    slot: int
    size: str


@dataclass(frozen=True)
class LoaderAccessResult:
    isolated_locations: tuple[ReceivingLocation, ...] = ()
    destination_accessible: bool = True

    @property
    def allowed(self) -> bool:
        return self.destination_accessible and not self.isolated_locations
