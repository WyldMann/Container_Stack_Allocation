from dataclasses import dataclass


StackCoordinates = tuple[str, int, int]
PlacementCoordinates = tuple[str, int, int, int]


@dataclass(frozen=True)
class PlacementProposal:
    """Describe an intended placement without modifying yard state.

    Row, slot, and tier use zero-based indexing.

    A 40-foot container occupies its odd-indexed anchor slot
    and the preceding slot.

    Construction validates the proposal's structure only.
    Availability, bounds, size compatibility, and support must
    be checked against the block separately.
    """

    block_id: str
    row: int
    slot: int
    tier: int
    size: str

    def __post_init__(self) -> None:
        if not isinstance(self.block_id, str) or not self.block_id.strip():
            raise ValueError("Block ID must be a non-empty string.")

        for name in ("row", "slot", "tier"):
            value = getattr(self, name)
            if type(value) is not int:
                raise TypeError(f"{name} must be an integer.")
            if value < 0:
                raise ValueError(f"{name} must be non-negative.")

        if self.size not in ("20", "40"):
            raise ValueError("Container size must be '20' or '40'.")

        if self.size == "40" and self.slot % 2 == 0:
            raise ValueError(
                "A 40-foot container requires an odd-indexed anchor slot."
            )

    @property
    def coordinates(self) -> PlacementCoordinates:
        """Return the anchor's block, row, slot, and tier."""
        return self.block_id, self.row, self.slot, self.tier

    @property
    def footprint(self) -> tuple[StackCoordinates, ...]:
        """Return every stack occupied by the proposed container."""
        anchor = (self.block_id, self.row, self.slot)

        if self.size == "20":
            return (anchor,)

        partner = (self.block_id, self.row, self.slot - 1)
        return partner, anchor

    @property
    def resulting_height(self) -> int:
        """Return occupied tier count after a valid top placement.

        Assumes contiguous supporting tiers and placement at
        the next available tier in every footprint stack.
        """
        return self.tier + 1

    def occupies(self, coordinates: StackCoordinates) -> bool:
        """Return whether a stack is part of the placement footprint."""
        return coordinates in self.footprint
