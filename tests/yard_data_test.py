from pathlib import Path

from repository import Repository, RemovedSlotsRepository
from entities import Container, Parameter, Yard, Block, Stack

yard_repo = Repository(Path(__file__).parent.parent / "data"/
                       "_TRM_MST_YARD_BLOCK__202608271123.csv").readCSV()
removed_slot = RemovedSlotsRepository(Path(__file__).parent.parent / "data" /
                                      "_TRM_MST_YARD_BLOCK_REMOVED_SLOT__202608271123.csv").readCSVTuple()


yard = Yard(yard_repo,removed_slot)

yard.print()