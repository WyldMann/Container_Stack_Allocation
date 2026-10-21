from typing import ContextManager, Iterator, Protocol, Sequence


class InputError(ValueError):
    """Source columns or values do not match the expected input."""


class Loader(Protocol):
    """Acquire raw rows; mapping and conversion belong to the repository."""

    @property
    def source(self) -> str: ...

    def open(self) -> ContextManager[tuple[
        Sequence[str] | None, Iterator[tuple[str, dict[str, object]]]
    ]]: ...
