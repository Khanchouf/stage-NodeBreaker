from planner.model import (
    BusbarSpec,
    CellKind,
    CellSpec,
    EquipmentKind,
    EquipmentSpec,
    PlanningConstraints,
    PlanningProblem,
    SwitchKind,
    SwitchRole,
    SwitchSpec,
)


def double_busbar_problem() -> PlanningProblem:
    switches = (
        SwitchSpec(
            "SA_B1", SwitchKind.DISCONNECTOR, "B1", "X", True, False,
            role=SwitchRole.FEEDER_DISCONNECTOR,
        ),
        SwitchSpec(
            "SA_B2", SwitchKind.DISCONNECTOR, "B2", "X", False, True,
            role=SwitchRole.FEEDER_DISCONNECTOR,
        ),
        SwitchSpec(
            "DJ", SwitchKind.BREAKER, "X", "E", True, True,
            role=SwitchRole.FEEDER_BREAKER,
        ),
        SwitchSpec(
            "C", SwitchKind.BREAKER, "B1", "B2", False, False,
            role=SwitchRole.COUPLER,
        ),
    )
    cells = (
        CellSpec(
            "DEP",
            CellKind.DEPARTURE,
            frozenset({"X", "E"}),
            frozenset({"SA_B1", "SA_B2", "DJ"}),
            frozenset({"LINE"}),
            frozenset({"BBS1", "BBS2"}),
            frozenset({"DJ"}),
            frozenset({"SA_B1", "SA_B2"}),
        ),
        CellSpec(
            "COUP",
            CellKind.COUPLING,
            frozenset(),
            frozenset({"C"}),
            frozenset(),
            frozenset({"BBS1", "BBS2"}),
            frozenset({"C"}),
            frozenset(),
        ),
    )
    return PlanningProblem(
        name="double_busbar",
        nodes=("B1", "B2", "X", "E"),
        internal_connections=(),
        busbars=(BusbarSpec("BBS1", "B1"), BusbarSpec("BBS2", "B2")),
        equipment=(EquipmentSpec("LINE", EquipmentKind.LINE, ("E",), source=True),),
        switches=switches,
        cells=cells,
        constraints=PlanningConstraints(max_temporary_outages=1),
    )
