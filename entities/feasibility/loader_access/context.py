from dataclasses import dataclass

from ...block import Block
from .models import LoaderBorderAccessPolicy, Position, ReceivingLocation


@dataclass(frozen=True)
class LoaderAccessContext:
    """Immutable access data for one read-only candidate search.

    The block reference establishes ownership; it does not freeze the block.
    Discard this context before changing block state or its access policy.
    Same-block mutations are deliberately not tracked by this snapshot.
    """

    block: Block
    policy: LoaderBorderAccessPolicy
    row_lengths: tuple[int, ...]
    ground: frozenset[Position]
    reachable_ground: frozenset[Position]
    receiving_locations: frozenset[ReceivingLocation]
    accessible_locations: frozenset[ReceivingLocation]
