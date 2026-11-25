"""Standalone equipment access algorithm for equivalence checks.

Keep the reference independent of production access helpers so optimizations
cannot silently change both sides of a comparison.
"""

from collections import deque
from dataclasses import dataclass

from entities.block import Block
from entities.container import DummyContainer
from entities.feasibility.placement_proposal import PlacementProposal
from entities.feasibility.placement_feasibility import PlacementFeasibility

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
    """A potential destination, identified by its anchor and size."""

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
            and not self.isolated_locations
            and not self.isolated_occupied_locations
        )


class EquipmentAccessRule:
    """Check destination access and new isolation without modifying a block.

    Assumes contiguous stacks and a proposal that has already passed
    basic placement checks. Movement uses a single-cell grid model;
    vehicle dimensions and turning clearance are not modeled.
    """

    def evaluate(
            self,
            block: Block,
            proposal: PlacementProposal,
            policy: BlockBorderAccessPolicy,
            *,
            preserve_future_access: bool = True,
            twenty_foot_side_access: bool = False,
            destination_side_access: bool | None = None,
    ) -> EquipmentAccessResult:

        self._validate_proposal(block, proposal)
        reachable_before = self._reachable_ground(block, policy)
        destination = ReceivingLocation(proposal.row_index, proposal.slot_index, proposal.container_size)
        destination_accessible = self._can_serve(
            block, destination, reachable_before, policy,
            twenty_foot_side_access=(twenty_foot_side_access if destination_side_access is None
                                    else destination_side_access),
        )
        reachable_after = self._reachable_ground(block, policy, proposal)
        isolated = []

        if preserve_future_access:
            receiving_before = self._receiving_locations(block)
            receiving_after = self._receiving_locations(block, proposal)
            # Only protect destinations that retain capacity afterward.
            for location in receiving_before & receiving_after:
                accessible_before = self._can_serve(
                    block, location, reachable_before, policy, twenty_foot_side_access=twenty_foot_side_access,
                )
                accessible_after = self._can_serve(
                    block, location, reachable_after, policy, twenty_foot_side_access=twenty_foot_side_access,
                )
                if accessible_before and not accessible_after:
                    isolated.append(location)

        isolated_occupied = []
        for row_index, row in enumerate(block.getSlots()):
            for slot_index, stack in enumerate(row):
                if stack.occupancy() == 0 or stack.getMode() == "X":
                    continue
                container = next((item for item in stack.getContainers()
                                  if item is not None and not isinstance(item, DummyContainer)), None)
                size = stack.getMode() if container is None else container.getContSize()
                if size not in ("20", "40"):
                    continue
                if size == "40" and slot_index % 2 == 0:
                    continue
                location = ReceivingLocation(row_index, slot_index, size)
                if (self._can_serve(block, location, reachable_before, policy,
                                   twenty_foot_side_access=twenty_foot_side_access)
                        and not self._can_serve(block, location, reachable_after, policy,
                                                twenty_foot_side_access=twenty_foot_side_access)):
                    isolated_occupied.append(location)

        return EquipmentAccessResult(
            isolated_locations=tuple(
                sorted(
                    isolated,
                    key=lambda isolated_location: (
                        isolated_location.row_index, isolated_location.slot_index, isolated_location.container_size
                    ),
                )
            ),
            destination_accessible=destination_accessible,
            isolated_occupied_locations=tuple(isolated_occupied),
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
            policy: BlockBorderAccessPolicy,
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
            for slot_index, stack in enumerate(slots):
                if stack.anomaly():
                    continue
                mode, tier_index = self._stack_state(block, row_index, slot_index, proposal)
                if tier_index is None:
                    continue
                if mode in ("0", "20"):
                    locations.add(ReceivingLocation(row_index, slot_index, "20"))
                if slot_index % 2 == 1 and mode in ("0", "40") and not slots[slot_index - 1].anomaly():
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
            policy: BlockBorderAccessPolicy,
            *, twenty_foot_side_access: bool = False,
    ) -> bool:
        row_count = len(block.getSlots())
        working_slots = (
            (location.slot_index,) if location.container_size == "20"
            else (location.slot_index - 1, location.slot_index)
        )
        for working_row in (location.row_index - 1, location.row_index + 1):
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
        # Keep this formulation independent of the production side checks.
        if location.container_size == "20" and twenty_foot_side_access:
            for working_slot, exterior_open in (
                (location.slot_index - 1, policy.left),
                (location.slot_index + 1, policy.right),
            ):
                if 0 <= working_slot < len(block.getSlots()[location.row_index]):
                    if (location.row_index, working_slot) in reachable:
                        return True
                elif exterior_open:
                    return True
        return False


class ReferencePlacementFeasibility(PlacementFeasibility):
    """Use the standalone access rule through the candidate-search API."""

    def __init__(self, settings=None):
        super().__init__(settings)
        self.equipment_access = EquipmentAccessRule()

    def prepare_access_context(self, block, border_policy=None, *, twenty_foot_side_access=False):
        return None

    def _evaluate_equipment_access(
        self, block, proposal, policy, context=None, *, check_future,
        twenty_foot_side_access=False, destination_side_access=None,
    ):
        if policy is None:
            policy = BlockBorderAccessPolicy()
        return self.equipment_access.evaluate(
            block, proposal, policy,
            preserve_future_access=check_future,
            twenty_foot_side_access=twenty_foot_side_access,
            destination_side_access=destination_side_access,
        )
