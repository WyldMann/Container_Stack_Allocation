from dataclasses import dataclass, field

from .container import Container


@dataclass
class IncompleteContainers:
    containers: list[Container] = field(default_factory=list)

    @staticmethod
    def isInboundComplete(container: Container) -> bool:
        """Check inbound completeness without requiring coordinates."""
        return (
            container.getId() != ""
            and container.getContSize() in ("20", "40")
        )

    @classmethod
    def isExistingComplete(cls, container: Container) -> bool:
        """Check an existing container input, including its coordinates."""
        return (
            cls.isInboundComplete(container)
            and "" not in container.getCoordsStr()
        )

    def addContainer(self, container: Container) -> None:
        """Record a container already classified as incomplete."""
        self.containers.append(container)

    def validateExistingAndRecord(self, container: Container) -> bool:
        """Validate an existing container input and record it if incomplete."""
        if self.isExistingComplete(container):
            return True

        self.addContainer(container)
        return False

    def validateInboundAndRecord(self, container: Container) -> bool:
        """Validate an inbound container and record it if incomplete."""
        if self.isInboundComplete(container):
            return True

        self.addContainer(container)
        return False

    def __len__(self) -> int:
        return len(self.containers)
