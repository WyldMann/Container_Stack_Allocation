"""Original loader-access algorithm, retained only for equivalence checks.

Keep the reference independent of production access helpers so optimizations
cannot silently change both sides of a comparison.
"""

from collections import deque
from dataclasses import dataclass

from entities.block import Block
from entities.feasibility.placement_proposal import PlacementProposal
from entities.feasibility.placement_feasibility import PlacementFeasibility, RejectionReason

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

    row_index: int
    slot_index: int
    container_size: str


@dataclass(frozen=True)
class LoaderAccessResult:
    isolated_locations: tuple[ReceivingLocation, ...] = ()
    destination_accessible: bool = True

    @property
    def allowed(self) -> bool:
        return self.destination_accessible and not self.isolated_locations


class LoaderAccessRule:
    """Check destination access and new isolation without modifying a block.

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
        destination = ReceivingLocation(proposal.row_index, proposal.slot_index, proposal.container_size)
        destination_accessible = self._can_serve(
            block, destination, reachable_before, policy
        )
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
                    key=lambda isolated_location: (
                        isolated_location.row_index, isolated_location.slot_index, isolated_location.container_size
                    ),
                )
            ),
            destination_accessible=destination_accessible,
        )

    @staticmethod
    def _validate_proposal(block: Block, proposal: PlacementProposal) -> None:
        if proposal.block_id != block.getId():
            raise ValueError("Proposal belongs to a different block.")

        rows = block.getSlots()
        for _, row_index, slot_index in proposal.footprint:
            if not 0 <= row_index < len(rows):
                raise ValueError("Proposal row is outside the block.")
            if not 0 <= slot_index < len(rows[row_index]):
                raise ValueError("Proposal slot is outside the block.")

            stack = rows[row_index][slot_index]
            if stack.getMode() not in ("0", proposal.container_size):
                raise ValueError("Proposal conflicts with stack mode.")
            if stack.availableTierInt() != proposal.tier_index:
                raise ValueError(
                    "Proposal tier must be the next available tier."
                )

    @staticmethod
    def _is_ground(
            block: Block,
            row_index: int,
            slot_index: int,
            proposal: PlacementProposal | None,
    ) -> bool:
        if proposal is not None and proposal.occupies(
                (block.getId(), row_index, slot_index)
        ):
            return False
        stack = block.getStack(row_index, slot_index)
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

        for row_index, slots in enumerate(rows):
            for slot_index in range(len(slots)):
                on_entry_border = (
                        (policy.above and row_index == 0)
                        or (policy.below and row_index == len(rows) - 1)
                        or (policy.left and slot_index == 0)
                        or (policy.right and slot_index == len(slots) - 1)
                )
                if on_entry_border and self._is_ground(
                        block, row_index, slot_index, proposal
                ):
                    position = (row_index, slot_index)
                    reachable.add(position)
                    queue.append(position)

        while queue:
            row_index, slot_index = queue.popleft()
            for next_row, next_slot in (
                    (row_index - 1, slot_index), (row_index + 1, slot_index),
                    (row_index, slot_index - 1), (row_index, slot_index + 1),
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
            row_index: int,
            slot_index: int,
            proposal: PlacementProposal | None,
    ) -> tuple[str, int | None]:
        """Return mode and next available tier for the chosen state."""
        stack = block.getStack(row_index, slot_index)
        if proposal is not None and proposal.occupies(
                (block.getId(), row_index, slot_index)
        ):
            next_tier = proposal.resulting_height
            if next_tier >= stack.getMaxTier():
                next_tier = None
            return proposal.container_size, next_tier
        return stack.getMode(), stack.availableTierInt()

    def _receiving_locations(
            self,
            block: Block,
            proposal: PlacementProposal | None = None,
    ) -> set[ReceivingLocation]:
        locations: set[ReceivingLocation] = set()
        for row_index, slots in enumerate(block.getSlots()):
            for slot_index in range(len(slots)):
                mode, tier_index = self._stack_state(block, row_index, slot_index, proposal)
                if tier_index is None:
                    continue
                if mode in ("0", "20"):
                    locations.add(ReceivingLocation(row_index, slot_index, "20"))
                if slot_index % 2 == 1 and mode in ("0", "40"):
                    partner_mode, partner_tier = self._stack_state(
                        block, row_index, slot_index - 1, proposal
                    )
                    if partner_mode in ("0", "40") and partner_tier == tier_index:
                        locations.add(ReceivingLocation(row_index, slot_index, "40"))
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
            (location.slot_index,) if location.container_size == "20"
            else (location.slot_index - 1, location.slot_index)
        )
        for working_row in (location.row_index - 1, location.row_index + 1):
            # Slot borders provide entry, but not direct service.
            if working_row == -1:
                if policy.above:
                    return True
                continue
            if working_row == row_count:
                if policy.below:
                    return True
                continue
            if all((working_row, slot_index) in reachable for slot_index in working_slots):
                return True
        return False


class ReferencePlacementFeasibility(PlacementFeasibility):
    """Use the original access rule through the current candidate-search API."""

    def __init__(self, settings=None):
        super().__init__(settings)
        self.loader_access = LoaderAccessRule()

    def prepare_loader_context(self, block, loader_policy=None):
        return None

    def _check_loader_access(self, block, proposal, policy, context=None):
        if block.getRTG() is not None:
            return None
        if policy is None:
            policy = LoaderBorderAccessPolicy()
        result = self.loader_access.evaluate(block, proposal, policy)
        if not result.destination_accessible:
            return RejectionReason.LOADER_DESTINATION_INACCESSIBLE
        if result.isolated_locations:
            return RejectionReason.LOADER_ACCESS_BLOCKED
        return None
