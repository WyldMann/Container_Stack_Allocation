from .yard import Block, Tier
from .container import Container

#todo: think how to implement this so I can still track where a container is. without inducing class import. if too hard, fuck it. put all classes into one file.

class ContainerPlacement:
    container: Container
    block: Block
    tier: Tier
    heightPlacement: int