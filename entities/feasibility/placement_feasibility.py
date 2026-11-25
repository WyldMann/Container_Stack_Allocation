from dataclasses import dataclass, replace
from enum import Enum

from config import FeasibilitySettings

from ..block import Block
from ..container import Container
from ..equipment import Loader
from .equipment_access import (
    EquipmentAccessContext, EquipmentAccessResult, EquipmentAccessRule, BlockBorderAccessPolicy, ReceivingLocation,
)
from .placement_proposal import PlacementProposal
from ..stack import Stack

Coordinates = tuple[str, int, int, int]


class RejectionReason(Enum):
    UNSUPPORTED_SIZE = "unsupported_size"
    INVALID_LOCATION = "invalid_location"
    STACK_UNAVAILABLE = "stack_unavailable"
    SIZE_CONFLICT = "size_conflict"
    INVALID_FORTY_FOOT_ANCHOR = "invalid_forty_foot_anchor"
    PARTNER_SIZE_CONFLICT = "partner_size_conflict"
    PARTNER_TIER_MISMATCH = "partner_tier_mismatch"
    ANOMALOUS_STACK = "anomalous_stack"
    UNSAFE_STACKING = "unsafe_stacking"
    DESTINATION_INACCESSIBLE = "destination_inaccessible"
    OCCUPIED_ACCESS_BLOCKED = "occupied_access_blocked"
    FUTURE_ACCESS_BLOCKED = "future_access_blocked"


@dataclass(frozen=True)
class FeasibilityResult:
    coordinates: Coordinates | None = None
    rejection_reason: RejectionReason | None = None
    equipment_access: EquipmentAccessResult | None = None

    def __post_init__(self) -> None:
        # Exactly one outcome must be supplied.
        if (self.coordinates is None) == (self.rejection_reason is None):
            raise ValueError("Supply either coordinates or a rejection reason.")

    @property
    def feasible(self) -> bool:
        return self.coordinates is not None


class PlacementFeasibility:
    """Evaluate placement rules without modifying the yard."""

    def __init__(self, settings: FeasibilitySettings | None = None) -> None:
        self.settings = settings if settings is not None else FeasibilitySettings()
        self.equipment_access = EquipmentAccessRule(
            allow_overcapacity=self.settings.stack_capacity_mode != "feasibility",
        )

    def prepare_access_context(
        self,
        block: Block,
        border_policy: BlockBorderAccessPolicy | None = None,
        *, twenty_foot_side_access: bool = False,
    ) -> EquipmentAccessContext | None:
        """Prepare one block's access data for a read-only candidate search."""
        if all(mode == "off" for mode in self.settings.equipment_access_modes) or block.getRTG() is not None:
            return None
        if border_policy is None:
            border_policy = BlockBorderAccessPolicy()
        twenty_foot_side_access = twenty_foot_side_access or any(
            loader.twenty_foot_side_access for loader in block.getLoaders()
        )
        return self.equipment_access.prepare_context(
            block, border_policy, twenty_foot_side_access=twenty_foot_side_access,
        )

    def evaluate(
            self,
            container: Container,
            block: Block,
            row_index: int,
            slot_index: int,
            *,
            border_policy: BlockBorderAccessPolicy | None = None,
            access_context: EquipmentAccessContext | None = None,
            include_access_heuristics: bool = True,
            loader_selected: bool = False,
            loader: Loader | None = None,
            twenty_foot_side_access: bool = False,
    ) -> FeasibilityResult:
        proposal = self._next_placement(block, row_index, slot_index, container.getContSize())
        if isinstance(proposal, RejectionReason):
            return FeasibilityResult(rejection_reason=proposal)

        destination_mode, occupied_mode, future_mode = self.settings.equipment_access_modes
        active_modes = ("feasibility", "heuristic") if include_access_heuristics else ("feasibility",)
        access = None
        # The block's RTG serves by default unless a loader was explicitly selected.
        if (loader_selected or loader is not None or block.getRTG() is None) and any(
            mode in active_modes for mode in (destination_mode, occupied_mode, future_mode)
        ):
            access = self._evaluate_equipment_access(
                block, proposal, border_policy, access_context,
                check_future=future_mode in active_modes,
                twenty_foot_side_access=(twenty_foot_side_access
                                        or any(item.twenty_foot_side_access for item in block.getLoaders())
                                        or (loader is not None and loader.twenty_foot_side_access)),
                destination_side_access=None if loader is None else loader.twenty_foot_side_access,
            )
        if access is not None:
            reason = self._access_rejection(access, destination_mode, occupied_mode, future_mode)
            if reason is not None:
                return FeasibilityResult(rejection_reason=reason, equipment_access=access)

        return FeasibilityResult(coordinates=proposal.coordinates, equipment_access=access)

    def _next_placement(
        self, block: Block, row_index: int, slot_index: int, container_size: str,
    ) -> PlacementProposal | RejectionReason:
        """Check whether the next tier is usable under the hard stacking rules."""
        if container_size not in ("20", "40"):
            return RejectionReason.UNSUPPORTED_SIZE

        rows = block.getSlots()
        if not 0 <= row_index < len(rows) or not 0 <= slot_index < len(rows[row_index]):
            return RejectionReason.INVALID_LOCATION

        slots = rows[row_index]
        stack = slots[slot_index]
        allow_overcapacity = self.settings.stack_capacity_mode != "feasibility"
        tier_index = stack.availableTierInt(allow_overcapacity=allow_overcapacity)
        if tier_index is None:
            return RejectionReason.STACK_UNAVAILABLE

        if stack.getMode() not in ("0", container_size):
            return RejectionReason.SIZE_CONFLICT

        if container_size == "40":
            reason = self._check_forty_foot_pair(slots, stack, slot_index, tier_index, allow_overcapacity)
            if reason is not None:
                return reason

        proposal = PlacementProposal(block.getId(), row_index, slot_index, tier_index, container_size)
        if any(block.getStack(row, slot).anomaly() for _, row, slot in proposal.footprint):
            return RejectionReason.ANOMALOUS_STACK

        if not self._passes_pyramid_limit(block, proposal):
            return RejectionReason.UNSAFE_STACKING
        return proposal

    def _evaluate_equipment_access(
        self,
        block: Block,
        proposal: PlacementProposal,
        policy: BlockBorderAccessPolicy | None,
        context: EquipmentAccessContext | None = None,
        *,
        check_future: bool,
        twenty_foot_side_access: bool = False,
        destination_side_access: bool | None = None,
    ) -> EquipmentAccessResult:
        if policy is None:
            policy = BlockBorderAccessPolicy()
        access = self.equipment_access.evaluate(
            block, proposal, policy, context=context,
            preserve_future_access=check_future,
            twenty_foot_side_access=twenty_foot_side_access,
            destination_side_access=destination_side_access,
        )
        ignore_infeasible = self.settings.ignore_stacks_without_legal_next_tier
        locations_to_check = set(access.isolated_locations)
        if ignore_infeasible:
            locations_to_check.update(access.isolated_occupied_locations)
        if not locations_to_check:
            return access

        infeasible = {
            location for location in locations_to_check
            if isinstance(self._next_placement(
                block, location.row_index, location.slot_index, location.container_size,
            ), RejectionReason)
        }
        future_infeasible = infeasible
        destination = ReceivingLocation(proposal.row_index, proposal.slot_index, proposal.container_size)
        if destination in access.isolated_locations:
            # The access rule has checked the remaining room in the footprint.
            # Neighbor support stays the same when the footprint itself grows.
            following = replace(proposal, tier_index=proposal.resulting_height)
            if not self._passes_pyramid_limit(block, following):
                future_infeasible = infeasible | {destination}

        return replace(
            access,
            isolated_locations=tuple(
                location for location in access.isolated_locations if location not in future_infeasible
            ),
            isolated_occupied_locations=tuple(
                location for location in access.isolated_occupied_locations
                if not ignore_infeasible or location not in infeasible
            ),
        )

    @staticmethod
    def _access_rejection(
        result: EquipmentAccessResult, destination_mode: str, occupied_mode: str, future_mode: str,
    ) -> RejectionReason | None:
        if destination_mode == "feasibility" and not result.destination_accessible:
            return RejectionReason.DESTINATION_INACCESSIBLE
        if occupied_mode == "feasibility" and result.isolated_occupied_locations:
            return RejectionReason.OCCUPIED_ACCESS_BLOCKED
        if future_mode == "feasibility" and result.isolated_locations:
            return RejectionReason.FUTURE_ACCESS_BLOCKED
        return None

    @staticmethod
    def _check_forty_foot_pair(
            slots: list[Stack],
            stack: Stack,
            slot_index: int,
            tier_index: int,
            allow_overcapacity: bool,
    ) -> RejectionReason | None:
        if stack.getEven() or slot_index == 0:
            return RejectionReason.INVALID_FORTY_FOOT_ANCHOR

        partner = slots[slot_index - 1]
        if partner.getMode() not in ("0", "40"):
            return RejectionReason.PARTNER_SIZE_CONFLICT

        if partner.availableTierInt(allow_overcapacity=allow_overcapacity) != tier_index:
            return RejectionReason.PARTNER_TIER_MISMATCH

        return None

    def _passes_pyramid_limit(self, block: Block, proposal: PlacementProposal) -> bool:
        if self.settings.effective_stacking_safety_mode not in ("feasibility", "combined"):
            return True
        return block.pyramidHeightDifference(
            proposal.row_index, proposal.slot_index, container_size=proposal.container_size,
            neighbors=self.settings.stacking_safety_neighbors,
            resulting_height=proposal.resulting_height,
        ) <= self.settings.stacking_safety_maxima
