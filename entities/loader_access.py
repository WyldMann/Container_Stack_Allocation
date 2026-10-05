from collections import deque
from dataclasses import dataclass

from .block import Block
from .placement_proposal import PlacementProposal

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

    @property
    def allowed(self) -> bool:
        return not self.isolated_locations


class LoaderAccessRule:
    """Detect newly isolated receiving locations without modifying a block.

    Assumes contiguous stacks and a proposal that has already passed
    basic placement checks. Movement uses a single-cell grid model;
    vehicle dimensions and turning clearance are not modeled.
    """

    def evaluate(
            self,
            block: Block,
            proposal: PlacementProposal,
            policy: LoaderBorderAccessPolicy,
    ) -> LoaderAccessResult:

        self._validate_proposal(block, proposal)
        reachable_before = self._reachable_ground(block, policy)
        reachable_after = self._reachable_ground(block, policy, proposal)
        receiving_before = self._receiving_locations(block)
        receiving_after = self._receiving_locations(block, proposal)
        isolated = []

        # Only protect destinations that retain capacity afterward.
        for location in receiving_before & receiving_after:
            accessible_before = self._can_serve(
                block, location, reachable_before, policy
            )
            accessible_after = self._can_serve(
                block, location, reachable_after, policy
            )
            if accessible_before and not accessible_after:
                isolated.append(location)

        return LoaderAccessResult(
            isolated_locations=tuple(
                sorted(
                    isolated,
                    key=lambda isolatedLocation: (
                        isolatedLocation.row, isolatedLocation.slot, isolatedLocation.size
                    ),
                )
            )
        )

    @staticmethod
    def _validate_proposal(block: Block, proposal: PlacementProposal) -> None:
        if proposal.block_id != block.getId():
            raise ValueError("Proposal belongs to a different block.")

        rows = block.getSlots()
        for _, row, slot in proposal.footprint:
            if not 0 <= row < len(rows):
                raise ValueError("Proposal row is outside the block.")
            if not 0 <= slot < len(rows[row]):
                raise ValueError("Proposal slot is outside the block.")

            stack = rows[row][slot]
            if stack.getMode() not in ("0", proposal.size):
                raise ValueError("Proposal conflicts with stack mode.")
            if stack.availableTierInt() != proposal.tier:
                raise ValueError(
                    "Proposal tier must be the next available tier."
                )

    @staticmethod
    def _is_ground(
            block: Block,
            row: int,
            slot: int,
            proposal: PlacementProposal | None,
    ) -> bool:
        if proposal is not None and proposal.occupies(
                (block.getId(), row, slot)
        ):
            return False
        stack = block.getStack(row, slot)
        # Removed slots are clear ground, never receiving destinations.
        return stack.getMode() == "X" or stack.occupancy() == 0

    def _reachable_ground(
            self,
            block: Block,
            policy: LoaderBorderAccessPolicy,
            proposal: PlacementProposal | None = None,
    ) -> set[Position]:
        rows = block.getSlots()
        reachable: set[Position] = set()
        queue: deque[Position] = deque()

        for row, slots in enumerate(rows):
            for slot in range(len(slots)):
                on_entry_border = (
                        (policy.above and row == 0)
                        or (policy.below and row == len(rows) - 1)
                        or (policy.left and slot == 0)
                        or (policy.right and slot == len(slots) - 1)
                )
                if on_entry_border and self._is_ground(
                        block, row, slot, proposal
                ):
                    position = (row, slot)
                    reachable.add(position)
                    queue.append(position)

        while queue:
            row, slot = queue.popleft()
            for next_row, next_slot in (
                    (row - 1, slot), (row + 1, slot),
                    (row, slot - 1), (row, slot + 1),
            ):
                if not 0 <= next_row < len(rows):
                    continue
                if not 0 <= next_slot < len(rows[next_row]):
                    continue
                position = (next_row, next_slot)
                if position in reachable:
                    continue
                if self._is_ground(block, next_row, next_slot, proposal):
                    reachable.add(position)
                    queue.append(position)
        return reachable

    @staticmethod
    def _stack_state(
            block: Block,
            row: int,
            slot: int,
            proposal: PlacementProposal | None,
    ) -> tuple[str, int | None]:
        """Return mode and next available tier for the chosen state."""
        stack = block.getStack(row, slot)
        if proposal is not None and proposal.occupies(
                (block.getId(), row, slot)
        ):
            next_tier = proposal.resulting_height
            if next_tier >= stack.getMaxTier():
                next_tier = None
            return proposal.size, next_tier
        return stack.getMode(), stack.availableTierInt()

    def _receiving_locations(
            self,
            block: Block,
            proposal: PlacementProposal | None = None,
    ) -> set[ReceivingLocation]:
        locations: set[ReceivingLocation] = set()
        for row, slots in enumerate(block.getSlots()):
            for slot in range(len(slots)):
                mode, tier = self._stack_state(block, row, slot, proposal)
                if tier is None:
                    continue
                if mode in ("0", "20"):
                    locations.add(ReceivingLocation(row, slot, "20"))
                if slot % 2 == 1 and mode in ("0", "40"):
                    partner_mode, partner_tier = self._stack_state(
                        block, row, slot - 1, proposal
                    )
                    if partner_mode in ("0", "40") and partner_tier == tier:
                        locations.add(ReceivingLocation(row, slot, "40"))
        return locations

    @staticmethod
    def _can_serve(
            block: Block,
            location: ReceivingLocation,
            reachable: set[Position],
            policy: LoaderBorderAccessPolicy,
    ) -> bool:
        row_count = len(block.getSlots())
        working_slots = (
            (location.slot,) if location.size == "20"
            else (location.slot - 1, location.slot)
        )
        for working_row in (location.row - 1, location.row + 1):
            # Slot borders provide entry, but not direct service.
            if working_row == -1:
                if policy.above:
                    return True
                continue
            if working_row == row_count:
                if policy.below:
                    return True
                continue
            if all((working_row, slot) in reachable for slot in working_slots):
                return True
        return False
