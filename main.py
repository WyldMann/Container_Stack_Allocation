from filewriter import ContainerFileWriter

from config import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_INPUT_CONFIG_FILE,
    load_config,
    load_input_config,
)

from repository import load_yard_inputs
from repository.branch_repository import BranchDirectory
from repository.operations_input import load_operations
from repository.sql_connection import input_connection
from entities import Yard, Container
from entities.bad_yard_data import PlacementRejected
from presenter import YardPresenter, BadDataPresenter

settings = load_config(DEFAULT_CONFIG_FILE)
input_settings = load_input_config(DEFAULT_INPUT_CONFIG_FILE)
with input_connection(input_settings) as connection:
    inputs = load_yard_inputs(input_settings, include_shifting=False, connection=connection)
    shifting_summary = []
    inbound_container_records = inputs["inbound_containers"]

    yard = Yard(
        yard_blocks_input=inputs["yard_blocks"],
        removed_slots_input=inputs["removed_slots"],
        parameters_input=inputs["parameters"],
        yard_planning_input=inputs["yard_planning"],
        containers_input=inputs["existing_containers"],
        equipment_input=inputs["master_equipment"],
        equipment_locations_input=inputs["equipment_history"],
        feasibility_settings=settings.feasibility,
        heuristic_settings=settings.heuristic,
    )
    if (input_settings.get("shifting_source") == "sql"
            or input_settings.get("shifting_summary_file") is not None):
        shifting_summary = load_operations(
            input_settings, BranchDirectory(inputs["terminal_branches"]), yard.blocks_by_id,
            connection=connection,
        )
        inputs["shifting_summary"] = shifting_summary
yard_presenter = YardPresenter()
yard_presenter.outYard(yard)

if yard.bad_data.anyBadData():
    BadDataPresenter().print(yard.bad_data)
    BadDataPresenter().printStats(yard.bad_data)
else: print("All good.")

skip = False
for x in inbound_container_records:
    print("\n Press Enter to continue. Anything else to skip.")
    if not skip:
        inp = input()
        if inp != "":
            skip = True
    new_container = Container(**({"container_size": ""} | x))

    try:
        result = yard.assign_and_place(new_container)
    except PlacementRejected as error:
        print(f"Container {new_container.getId()} was not placed: {error}")
        continue

    yard_presenter.outAssignResult(result)
    yard_presenter.outYard(yard)

BadDataPresenter().printInbound(yard.bad_data)

container_writer = ContainerFileWriter(
    input_settings["output_file"],
    branch_codes=BranchDirectory(inputs["terminal_branches"]).codes_by_id
)
yard_presenter.outParameterCompliance(yard)
container_writer.writeCSV(yard)
