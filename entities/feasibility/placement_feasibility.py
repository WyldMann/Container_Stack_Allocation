from dataclasses import dataclass
from enum import Enum

from config import FeasibilitySettings

from ..block import Block
from ..container import Container
from .loader_access import LoaderAccessContext, LoaderAccessRule, LoaderBorderAccessPolicy
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
    UNSAFE_STACKING = "unsafe_stacking"
    LOADER_DESTINATION_INACCESSIBLE = "loader_destination_inaccessible"
    LOADER_ACCESS_BLOCKED = "loader_access_blocked"


@dataclass(frozen=True)
class FeasibilityResult:
    coordinates: Coordinates | None = None
    rejection_reason: RejectionReason | None = None

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
        self.loader_access = LoaderAccessRule()

    def prepare_loader_context(
        self,
        block: Block,
        loader_policy: LoaderBorderAccessPolicy | None = None,
    ) -> LoaderAccessContext | None:
        """Prepare one block's access data for a read-only candidate search."""
        if not self.settings.loader_access or block.getRTG() is not None:
            return None
        if loader_policy is None:
            loader_policy = LoaderBorderAccessPolicy()
        return self.loader_access.prepare_context(block, loader_policy)

    def evaluate(
            self,
            container: Container,
            block: Block,
            row_index: int,
            slot_index: int,
            *,
            loader_policy: LoaderBorderAccessPolicy | None = None,
            loader_context: LoaderAccessContext | None = None,
    ) -> FeasibilityResult:
        container_size = container.getContSize()
        if container_size not in ("20", "40"):
            return FeasibilityResult(
                rejection_reason=RejectionReason.UNSUPPORTED_SIZE
            )

        rows = block.getSlots()
        if not 0 <= row_index < len(rows):
            return FeasibilityResult(
                rejection_reason=RejectionReason.INVALID_LOCATION
            )

        slots = rows[row_index]
        if not 0 <= slot_index < len(slots):
            return FeasibilityResult(
                rejection_reason=RejectionReason.INVALID_LOCATION
            )

        stack = slots[slot_index]
        tier_index = stack.availableTierInt()
        if tier_index is None:
            return FeasibilityResult(
                rejection_reason=RejectionReason.STACK_UNAVAILABLE
            )

        reason = self._check_size_compatibility(container_size, stack)
        if reason is not None:
            return FeasibilityResult(rejection_reason=reason)

        if container_size == "40":
            reason = self._check_forty_foot_pair(slots, stack, slot_index, tier_index)
            if reason is not None:
                return FeasibilityResult(rejection_reason=reason)

        proposal = PlacementProposal(
            block_id=block.getId(),
            row_index=row_index,
            slot_index=slot_index,
            tier_index=tier_index,
            container_size=container_size,
        )

        if self.settings.stacking_safety:
            reason = self._check_stacking_safety(block, proposal)
            if reason is not None:
                return FeasibilityResult(rejection_reason=reason)

        if self.settings.loader_access:
            reason = self._check_loader_access(block, proposal, loader_policy, loader_context)
            if reason is not None:
                return FeasibilityResult(rejection_reason=reason)

        return FeasibilityResult(coordinates=proposal.coordinates)

    def _check_loader_access(
        self,
        block: Block,
        proposal: PlacementProposal,
        policy: LoaderBorderAccessPolicy | None,
        context: LoaderAccessContext | None = None,
    ) -> RejectionReason | None:
        # Matches equipment selection: a block's RTG serves all its candidates.
        if block.getRTG() is not None:
            return None
        if policy is None:
            policy = LoaderBorderAccessPolicy()
        result = self.loader_access.evaluate(block, proposal, policy, context=context)
        if not result.destination_accessible:
            return RejectionReason.LOADER_DESTINATION_INACCESSIBLE
        if result.isolated_locations:
            return RejectionReason.LOADER_ACCESS_BLOCKED
        return None

    @staticmethod
    def _check_size_compatibility(
            container_size: str,
            stack: Stack,
    ) -> RejectionReason | None:
        mode = stack.getMode()
        if (container_size == "40" and mode == "20") or (
                container_size == "20" and mode == "40"
        ):
            return RejectionReason.SIZE_CONFLICT
        return None

    @staticmethod
    def _check_forty_foot_pair(
            slots: list[Stack],
            stack: Stack,
            slot_index: int,
            tier_index: int,
    ) -> RejectionReason | None:
        if stack.getEven() or slot_index == 0:
            return RejectionReason.INVALID_FORTY_FOOT_ANCHOR

        partner = slots[slot_index - 1]
        if partner.getMode() not in ("0", "40"):
            return RejectionReason.PARTNER_SIZE_CONFLICT

        if partner.availableTierInt() != tier_index:
            return RejectionReason.PARTNER_TIER_MISMATCH

        return None

    @staticmethod
    def _check_stacking_safety(
            block: Block,
            proposal: PlacementProposal,
    ) -> RejectionReason | None:
        if not block.safeMaxima(proposal.row_index, proposal.slot_index):
            return RejectionReason.UNSAFE_STACKING
        return None
