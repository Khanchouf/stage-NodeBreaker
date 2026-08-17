import pytest

from planner.model import (
    BusbarSpec,
    PlanningConstraints,
    PlanningProblem,
    SwitchKind,
    SwitchSpec,
)


def test_negative_temporary_outage_limit_is_rejected():
    with pytest.raises(ValueError, match="max_temporary_outages"):
        PlanningProblem(
            name="bad_limit",
            nodes=("A", "B"),
            internal_connections=(),
            busbars=(BusbarSpec("BBS", "A"),),
            equipment=(),
            switches=(SwitchSpec("S", SwitchKind.BREAKER, "A", "B", True, True),),
            constraints=PlanningConstraints(max_temporary_outages=-1),
        )


def test_duplicate_busbar_nodes_are_rejected():
    with pytest.raises(ValueError, match="partager le même nœud"):
        PlanningProblem(
            name="duplicate_busbar_node",
            nodes=("A", "B"),
            internal_connections=(),
            busbars=(BusbarSpec("BBS1", "A"), BusbarSpec("BBS2", "A")),
            equipment=(),
            switches=(SwitchSpec("S", SwitchKind.BREAKER, "A", "B", True, True),),
        )
