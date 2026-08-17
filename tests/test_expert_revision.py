from collections import deque

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
from planner.search import PlanningSession, astar_search, expert_heuristic_details


def three_departure_problem() -> PlanningProblem:
    switches = []
    equipment = []
    cells = []
    nodes = ["B1", "B2"]

    for i in range(3):
        x = f"X{i}"
        terminal = f"E{i}"
        nodes.extend([x, terminal])
        sa1 = f"SA{i}_1"
        sa2 = f"SA{i}_2"
        dj = f"DJ{i}"

        if i < 2:
            initial = (True, False)
            target = (False, True)
        else:
            initial = (False, True)
            target = (True, False)

        switches.extend(
            [
                SwitchSpec(
                    sa1,
                    SwitchKind.DISCONNECTOR,
                    "B1",
                    x,
                    initial[0],
                    target[0],
                    role=SwitchRole.FEEDER_DISCONNECTOR,
                ),
                SwitchSpec(
                    sa2,
                    SwitchKind.DISCONNECTOR,
                    "B2",
                    x,
                    initial[1],
                    target[1],
                    role=SwitchRole.FEEDER_DISCONNECTOR,
                ),
                SwitchSpec(
                    dj,
                    SwitchKind.BREAKER,
                    x,
                    terminal,
                    True,
                    True,
                    role=SwitchRole.FEEDER_BREAKER,
                ),
            ]
        )
        equipment.append(EquipmentSpec(f"LINE{i}", EquipmentKind.LINE, (terminal,)))
        cells.append(
            CellSpec(
                f"DEP{i}",
                CellKind.DEPARTURE,
                frozenset({x, terminal}),
                frozenset({sa1, sa2, dj}),
                frozenset({f"LINE{i}"}),
                frozenset({"BBS1", "BBS2"}),
                frozenset({dj}),
                frozenset({sa1, sa2}),
            )
        )

    return PlanningProblem(
        name="three_departures",
        nodes=tuple(nodes),
        internal_connections=(),
        busbars=(BusbarSpec("BBS1", "B1"), BusbarSpec("BBS2", "B2")),
        equipment=tuple(equipment),
        switches=tuple(switches),
        cells=tuple(cells),
        constraints=PlanningConstraints(max_temporary_outages=1),
    )


def realistic_coupler_problem(*, coupler_breaker_closed: bool) -> PlanningProblem:
    switches = (
        SwitchSpec(
            "SA1", SwitchKind.DISCONNECTOR, "B1", "X", True, False,
            role=SwitchRole.FEEDER_DISCONNECTOR,
        ),
        SwitchSpec(
            "SA2", SwitchKind.DISCONNECTOR, "B2", "X", False, True,
            role=SwitchRole.FEEDER_DISCONNECTOR,
        ),
        SwitchSpec(
            "DJ", SwitchKind.BREAKER, "X", "E", True, True,
            role=SwitchRole.FEEDER_BREAKER,
        ),
        SwitchSpec(
            "CSA1", SwitchKind.DISCONNECTOR, "B1", "C1", True, True,
            role=SwitchRole.COUPLER,
        ),
        SwitchSpec(
            "CDJ", SwitchKind.BREAKER, "C1", "C2",
            coupler_breaker_closed, coupler_breaker_closed,
            role=SwitchRole.COUPLER,
        ),
        SwitchSpec(
            "CSA2", SwitchKind.DISCONNECTOR, "C2", "B2", True, True,
            role=SwitchRole.COUPLER,
        ),
    )
    cells = (
        CellSpec(
            "DEP", CellKind.DEPARTURE,
            frozenset({"X", "E"}),
            frozenset({"SA1", "SA2", "DJ"}),
            frozenset({"LINE"}),
            frozenset({"BBS1", "BBS2"}),
            frozenset({"DJ"}),
            frozenset({"SA1", "SA2"}),
        ),
        CellSpec(
            "COUP", CellKind.COUPLING,
            frozenset({"C1", "C2"}),
            frozenset({"CSA1", "CDJ", "CSA2"}),
            frozenset(),
            frozenset({"BBS1", "BBS2"}),
            frozenset({"CDJ"}),
            frozenset({"CSA1", "CSA2"}),
        ),
    )
    return PlanningProblem(
        name="realistic_coupler",
        nodes=("B1", "B2", "X", "E", "C1", "C2"),
        internal_connections=(),
        busbars=(BusbarSpec("BBS1", "B1"), BusbarSpec("BBS2", "B2")),
        equipment=(EquipmentSpec("LINE", EquipmentKind.LINE, ("E",)),),
        switches=switches,
        cells=cells,
        constraints=PlanningConstraints(max_temporary_outages=1),
    )


def test_expert_is_stronger_for_three_departures_without_transfer_path():
    problem = three_departure_problem()
    session = PlanningSession(problem)
    details = expert_heuristic_details(session.initial_state, problem, session.topology)

    assert details["hamming"] == 6
    assert details["expert"] == 12

    hamming = astar_search(problem, heuristic="hamming")
    expert = astar_search(problem, heuristic="expert")
    zero = astar_search(problem, heuristic="zero")

    assert zero.total_cost == hamming.total_cost == expert.total_cost == 12
    assert expert.expanded_states < hamming.expanded_states


def test_realistic_sa_breaker_sa_coupler_is_detected_as_transfer_path():
    open_coupler = realistic_coupler_problem(coupler_breaker_closed=False)
    session_open = PlanningSession(open_coupler)
    details_open = expert_heuristic_details(
        session_open.initial_state, open_coupler, session_open.topology
    )
    assert details_open["expert"] == 4
    assert details_open["groups"][0]["transfer_extra_beyond_hamming"] == 2

    closed_coupler = realistic_coupler_problem(coupler_breaker_closed=True)
    session_closed = PlanningSession(closed_coupler)
    details_closed = expert_heuristic_details(
        session_closed.initial_state, closed_coupler, session_closed.topology
    )
    assert details_closed["hamming"] == 2
    assert details_closed["expert"] == 2
    assert details_closed["groups"][0]["transfer_extra_beyond_hamming"] == 0
    assert astar_search(closed_coupler, heuristic="expert").total_cost == 2


def test_expert_is_consistent_on_all_reachable_three_departure_states():
    problem = three_departure_problem()
    session = PlanningSession(problem)
    queue = deque([session.initial_state])
    seen = {session.initial_state}

    while queue:
        state = queue.popleft()
        h_state = session.heuristic("expert", state)
        for action, successor in session.applicable_actions(state):
            h_successor = session.heuristic("expert", successor)
            assert h_state <= action.cost + h_successor
            if successor not in seen:
                seen.add(successor)
                queue.append(successor)

    assert len(seen) == 56
