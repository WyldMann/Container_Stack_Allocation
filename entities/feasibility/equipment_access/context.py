from dataclasses import dataclass

from ...block import Block
from .models import BlockBorderAccessPolicy, Position, ReceivingLocation


@dataclass(frozen=True)
class EquipmentAccessContext:
    """Immutable access data for one read-only candidate search.

    The block reference establishes ownership; it does not freeze the block.
    Discard this context before changing block state, its access policy, or
    the fleet's side-access capability.
    Same-block mutations are deliberately not tracked by this snapshot.
    """

    block: Block
    policy: BlockBorderAccessPolicy
    row_lengths: tuple[int, ...]
    ground: frozenset[Position]
    reachable_ground: frozenset[Position]
    receiving_locations: frozenset[ReceivingLocation]
    accessible_locations: frozenset[ReceivingLocation]
    accessible_occupied_locations: frozenset[ReceivingLocation]
    allow_overcapacity: bool = False
    twenty_foot_side_access: bool = False
