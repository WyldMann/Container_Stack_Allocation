from collections import deque
from collections.abc import Set

from ...block import Block
from ..placement_proposal import PlacementProposal
from .context import LoaderAccessContext
from .models import (
    LoaderAccessResult,
    LoaderBorderAccessPolicy,
    Position,
    ReceivingLocation,
)


class LoaderAccessRule:
    """Check destination access and new isolation without modifying a block.

    Assumes contiguous stacks and a proposal that has already passed
    basic placement checks. Movement uses a single-cell grid model;
    vehicle dimensions and turning clearance are not modeled.
    """

    def prepare_context(
        self, block: Block, policy: LoaderBorderAccessPolicy,
    ) -> LoaderAccessContext:
        """Prepare baseline data; reuse only while the block remains unchanged."""
        rows = block.getSlots()
        row_lengths = tuple(len(slots) for slots in rows)
        ground = frozenset(
            (row, slot)
            for row, slots in enumerate(rows)
            for slot in range(len(slots))
            if self._is_ground(block, row, slot, None)
        )
        reachable = self._search_ground(row_lengths, ground, policy)
        receiving = frozenset(self._receiving_locations(block))
        accessible = frozenset(
            location for location in receiving
            if self._can_serve(block, location, reachable, policy)
        )
        return LoaderAccessContext(
            block, policy, row_lengths, ground, reachable, receiving, accessible,
        )

    def evaluate(
        self,
        block: Block,
        proposal: PlacementProposal,
        policy: LoaderBorderAccessPolicy,
        *,
        context: LoaderAccessContext | None = None,
    ) -> LoaderAccessResult:
        self._validate_proposal(block, proposal)
        if context is None:
            context = self.prepare_context(block, policy)
        elif context.block is not block or context.policy != policy:
            raise ValueError("Loader access context belongs to a different block or policy.")

        destination = ReceivingLocation(proposal.row, proposal.slot, proposal.size)
        destination_accessible = self._can_serve(
            block, destination, context.reachable_ground, policy,
        )
        blocked = frozenset(
            (row, slot) for _, row, slot in proposal.footprint
            if (row, slot) in context.ground
        )
        # Identical ground means identical access for every surviving destination,
        # even if filling the top tier changes receiving-location eligibility.
        if not blocked:
            return LoaderAccessResult(destination_accessible=destination_accessible)

        reachable_after = self._reachable_after(context, blocked)
        removed, _ = self._receiving_changes(block, proposal, context)
        isolated = (
            location for location in context.accessible_locations - removed
            if not self._can_serve(block, location, reachable_after, policy)
        )
        return LoaderAccessResult(
            isolated_locations=tuple(sorted(
                isolated, key=lambda location: (location.row, location.slot, location.size),
            )),
            destination_accessible=destination_accessible,
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
                raise ValueError("Proposal tier must be the next available tier.")

    @staticmethod
    def _is_ground(
        block: Block, row: int, slot: int, proposal: PlacementProposal | None,
    ) -> bool:
        if proposal is not None and proposal.occupies((block.getId(), row, slot)):
            return False
        stack = block.getStack(row, slot)
        # Removed slots are clear ground, never receiving destinations.
        return stack.getMode() == "X" or stack.occupancy() == 0

    @staticmethod
    def _search_ground(
        row_lengths: tuple[int, ...],
        ground: frozenset[Position],
        policy: LoaderBorderAccessPolicy,
        blocked: frozenset[Position] = frozenset(),
    ) -> frozenset[Position]:
        reachable: set[Position] = set()
        queue: deque[Position] = deque()
        for row, slot in ground:
            on_entry_border = (
                (policy.above and row == 0)
                or (policy.below and row == len(row_lengths) - 1)
                or (policy.left and slot == 0)
                or (policy.right and slot == row_lengths[row] - 1)
            )
            position = (row, slot)
            if on_entry_border and position not in blocked:
                reachable.add(position)
                queue.append(position)

        while queue:
            row, slot = queue.popleft()
            for position in (
                (row - 1, slot), (row + 1, slot),
                (row, slot - 1), (row, slot + 1),
            ):
                if position in reachable or position in blocked:
                    continue
                # Membership also excludes out-of-bounds cells.
                if position in ground:
                    reachable.add(position)
                    queue.append(position)
        return frozenset(reachable)

    def _reachable_after(
        self, context: LoaderAccessContext, blocked: frozenset[Position],
    ) -> frozenset[Position]:
        return self._search_ground(
            context.row_lengths, context.ground, context.policy, blocked,
        )

    def _reachable_ground(
        self, block: Block, policy: LoaderBorderAccessPolicy,
        proposal: PlacementProposal | None = None,
    ) -> set[Position]:
        """Calculate standalone reachability, also used by diagnostic callers."""
        rows = block.getSlots()
        ground = frozenset(
            (row, slot)
            for row, slots in enumerate(rows)
            for slot in range(len(slots))
            if self._is_ground(block, row, slot, proposal)
        )
        return set(self._search_ground(tuple(map(len, rows)), ground, policy))

    @staticmethod
    def _stack_state(
        block: Block, row: int, slot: int, proposal: PlacementProposal | None,
    ) -> tuple[str, int | None]:
        stack = block.getStack(row, slot)
        if proposal is not None and proposal.occupies((block.getId(), row, slot)):
            next_tier = proposal.resulting_height
            if next_tier >= stack.getMaxTier():
                next_tier = None
            return proposal.size, next_tier
        return stack.getMode(), stack.availableTierInt()

    def _receiving_at(
        self, block: Block, row: int, slot: int,
        proposal: PlacementProposal | None,
    ) -> set[ReceivingLocation]:
        locations: set[ReceivingLocation] = set()
        mode, tier = self._stack_state(block, row, slot, proposal)
        if tier is None:
            return locations
        if mode in ("0", "20"):
            locations.add(ReceivingLocation(row, slot, "20"))
        if slot % 2 == 1 and mode in ("0", "40"):
            partner_mode, partner_tier = self._stack_state(block, row, slot - 1, proposal)
            if partner_mode in ("0", "40") and partner_tier == tier:
                locations.add(ReceivingLocation(row, slot, "40"))
        return locations

    def _receiving_locations(
        self, block: Block, proposal: PlacementProposal | None = None,
    ) -> set[ReceivingLocation]:
        return {
            location
            for row, slots in enumerate(block.getSlots())
            for slot in range(len(slots))
            for location in self._receiving_at(block, row, slot, proposal)
        }

    def _receiving_changes(
        self, block: Block, proposal: PlacementProposal, context: LoaderAccessContext,
    ) -> tuple[frozenset[ReceivingLocation], frozenset[ReceivingLocation]]:
        """Return removed/added destinations, inspecting only affected anchors."""
        slots = {slot for _, _, slot in proposal.footprint}
        # A changed even-indexed slot also affects its adjacent 40-foot anchor.
        slots.update(slot + 1 for slot in tuple(slots) if slot % 2 == 0)
        slots = {slot for slot in slots if slot < context.row_lengths[proposal.row]}
        before = context.receiving_locations & frozenset(
            ReceivingLocation(proposal.row, slot, size)
            for slot in slots for size in ("20", "40")
        )
        after = frozenset(
            location for slot in slots
            for location in self._receiving_at(block, proposal.row, slot, proposal)
        )
        return before - after, after - before

    @staticmethod
    def _can_serve(
        block: Block, location: ReceivingLocation,
        reachable: Set[Position], policy: LoaderBorderAccessPolicy,
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
