from collections import deque
from collections.abc import Iterator, Set

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
            (row_index, slot_index)
            for row_index, slots in enumerate(rows)
            for slot_index in range(len(slots))
            if self._is_ground(block, row_index, slot_index, None)
        )
        reachable = self._search_ground(row_lengths, ground, policy)
        receiving = frozenset(self._receiving_locations(block))
        accessible = frozenset(
            location for location in receiving
            if self._can_serve(block, location, reachable, policy)
        )
        accessible_occupied = frozenset(
            location for location in self._occupied_locations(block, ground)
            if self._can_serve(block, location, reachable, policy)
        )
        return LoaderAccessContext(
            block, policy, row_lengths, ground, reachable, receiving, accessible,
            accessible_occupied,
        )

    def evaluate(
        self,
        block: Block,
        proposal: PlacementProposal,
        policy: LoaderBorderAccessPolicy,
        *,
        context: LoaderAccessContext | None = None,
        preserve_future_loader_access: bool = True,
        ignore_full_stacks_for_loader_access: bool = False,
    ) -> LoaderAccessResult:
        self._validate_proposal(block, proposal)
        if context is None:
            context = self.prepare_context(block, policy)
        elif context.block is not block or context.policy != policy:
            raise ValueError("Loader access context belongs to a different block or policy.")

        destination = ReceivingLocation(proposal.row_index, proposal.slot_index, proposal.container_size)
        destination_accessible = self._can_serve(
            block, destination, context.reachable_ground, policy,
        )
        blocked = frozenset(
            (row_index, slot_index) for _, row_index, slot_index in proposal.footprint
            if (row_index, slot_index) in context.ground
        )
        # Identical ground means identical access for every surviving destination,
        # even if filling the top tier changes receiving-location eligibility.
        if not blocked:
            return LoaderAccessResult(destination_accessible=destination_accessible)

        reachable_after = self._reachable_after(context, blocked)
        occupied = context.accessible_occupied_locations
        receiving = frozenset()
        if preserve_future_loader_access:
            removed, _ = self._receiving_changes(block, proposal, context)
            receiving = context.accessible_locations - removed
        isolated = sorted(
            (location for location in occupied | receiving
             if not self._can_serve(block, location, reachable_after, policy)),
            key=lambda location: (location.row_index, location.slot_index, location.container_size),
        )
        return LoaderAccessResult(
            isolated_locations=tuple(location for location in isolated if location in receiving),
            destination_accessible=destination_accessible,
            isolated_occupied_locations=tuple(
                location for location in isolated
                if location in occupied
                and not (ignore_full_stacks_for_loader_access and self._is_full(block, location))
            ),
        )

    @staticmethod
    def _is_full(block: Block, location: ReceivingLocation) -> bool:
        row, slot = location.row_index, location.slot_index
        if block.getStack(row, slot).availableTierInt() is not None:
            return False
        return location.container_size == "20" or block.getStack(row, slot - 1).availableTierInt() is None

    @staticmethod
    def _occupied_locations(block: Block, ground: Set[Position]) -> Iterator[ReceivingLocation]:
        for row_index, slots in enumerate(block.getSlots()):
            for slot_index, stack in enumerate(slots):
                if (row_index, slot_index) in ground:
                    continue
                size = stack.getMode()
                if size == "0":
                    # An unrepaired floating stack may still have an unset mode.
                    size = next(item.getContSize() for item in stack.getContainers() if item is not None)
                if size == "20" or (size == "40" and slot_index % 2 == 1):
                    yield ReceivingLocation(row_index, slot_index, size)

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
                raise ValueError("Proposal tier must be the next available tier.")

    @staticmethod
    def _is_ground(
        block: Block, row_index: int, slot_index: int, proposal: PlacementProposal | None,
    ) -> bool:
        if proposal is not None and proposal.occupies((block.getId(), row_index, slot_index)):
            return False
        stack = block.getStack(row_index, slot_index)
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
        for row_index, slot_index in ground:
            on_entry_border = (
                (policy.above and row_index == 0)
                or (policy.below and row_index == len(row_lengths) - 1)
                or (policy.left and slot_index == 0)
                or (policy.right and slot_index == row_lengths[row_index] - 1)
            )
            position = (row_index, slot_index)
            if on_entry_border and position not in blocked:
                reachable.add(position)
                queue.append(position)

        while queue:
            row_index, slot_index = queue.popleft()
            for position in (
                (row_index - 1, slot_index), (row_index + 1, slot_index),
                (row_index, slot_index - 1), (row_index, slot_index + 1),
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
            (row_index, slot_index)
            for row_index, slots in enumerate(rows)
            for slot_index in range(len(slots))
            if self._is_ground(block, row_index, slot_index, proposal)
        )
        return set(self._search_ground(tuple(map(len, rows)), ground, policy))

    @staticmethod
    def _stack_state(
        block: Block, row_index: int, slot_index: int, proposal: PlacementProposal | None,
    ) -> tuple[str, int | None]:
        stack = block.getStack(row_index, slot_index)
        if stack.anomaly():
            return stack.getMode(), None
        if proposal is not None and proposal.occupies((block.getId(), row_index, slot_index)):
            next_tier = proposal.resulting_height
            if next_tier >= stack.getMaxTier():
                next_tier = None
            return proposal.container_size, next_tier
        return stack.getMode(), stack.availableTierInt()

    def _receiving_at(
        self, block: Block, row_index: int, slot_index: int,
        proposal: PlacementProposal | None,
    ) -> set[ReceivingLocation]:
        locations: set[ReceivingLocation] = set()
        mode, tier_index = self._stack_state(block, row_index, slot_index, proposal)
        if tier_index is None:
            return locations
        if mode in ("0", "20"):
            locations.add(ReceivingLocation(row_index, slot_index, "20"))
        if slot_index % 2 == 1 and mode in ("0", "40"):
            partner_mode, partner_tier = self._stack_state(block, row_index, slot_index - 1, proposal)
            if partner_mode in ("0", "40") and partner_tier == tier_index:
                locations.add(ReceivingLocation(row_index, slot_index, "40"))
        return locations

    def _receiving_locations(
        self, block: Block, proposal: PlacementProposal | None = None,
    ) -> set[ReceivingLocation]:
        return {
            location
            for row_index, slots in enumerate(block.getSlots())
            for slot_index in range(len(slots))
            for location in self._receiving_at(block, row_index, slot_index, proposal)
        }

    def _receiving_changes(
        self, block: Block, proposal: PlacementProposal, context: LoaderAccessContext,
    ) -> tuple[frozenset[ReceivingLocation], frozenset[ReceivingLocation]]:
        """Return removed/added destinations, inspecting only affected anchors."""
        slots = {slot_index for _, _, slot_index in proposal.footprint}
        # A changed even-indexed slot also affects its adjacent 40-foot anchor.
        slots.update(slot_index + 1 for slot_index in tuple(slots) if slot_index % 2 == 0)
        slots = {slot_index for slot_index in slots if slot_index < context.row_lengths[proposal.row_index]}
        before = context.receiving_locations & frozenset(
            ReceivingLocation(proposal.row_index, slot_index, container_size)
            for slot_index in slots for container_size in ("20", "40")
        )
        after = frozenset(
            location for slot_index in slots
            for location in self._receiving_at(block, proposal.row_index, slot_index, proposal)
        )
        return before - after, after - before

    @staticmethod
    def _can_serve(
        block: Block, location: ReceivingLocation,
        reachable: Set[Position], policy: LoaderBorderAccessPolicy,
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
