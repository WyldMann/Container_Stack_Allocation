from dataclasses import dataclass, field

from ..container import Container


@dataclass
class IncompleteContainers:
    containers: list[Container] = field(default_factory=list)

    def addContainer(self, container: Container) -> None:
        """Record a container already classified as incomplete."""
        if not any(item is container for item in self.containers):
            self.containers.append(container)

    def __len__(self) -> int:
        return len(self.containers)


@dataclass
class IncompleteInboundContainers(IncompleteContainers):
    @staticmethod
    def isInboundComplete(container: Container) -> bool:
        """Check inbound completeness without requiring coordinates."""
        container_id = container.getId()
        return (
            isinstance(container_id, str)
            and bool(container_id.strip())
            and container.getContSize() in ("20", "40")
        )

    def validateInboundAndRecord(self, container: Container) -> bool:
        """Validate an inbound container and record it if incomplete."""
        if self.isInboundComplete(container):
            return True

        self.addContainer(container)
        return False


@dataclass
class IncompleteExistingContainers(IncompleteContainers):
    @staticmethod
    def isExistingComplete(container: Container) -> bool:
        """Check an existing container input, including its coordinates."""
        return (
            container.getId() != ""
            and container.getContSize() in ("20", "40")
            and "" not in container.getCoordsStr()
        )

    def validateExistingAndRecord(self, container: Container) -> bool:
        """Validate an existing container input and record it if incomplete."""
        if self.isExistingComplete(container):
            return True

        self.addContainer(container)
        return False
