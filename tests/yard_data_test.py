from pathlib import Path

from repository import Repository
from entities import Container, Parameter, Yard, Block, Tier

yard = Yard(Repository(
    Path(__file__).parent.parent / "data"/ "_TRM_MST_YARD_BLOCK__202608271123.csv")
            .readCSV())

yard.print()