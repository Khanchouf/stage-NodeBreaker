from planner.search import PlanningSession, astar_search
from planner.verification import verify_plan

from .helpers import double_busbar_problem


def test_astar_returns_optimal_detailed_plan():
    problem = double_busbar_problem()
    result = astar_search(problem, heuristic="hamming")
    reference = astar_search(problem, heuristic="zero")
    assert result.found
    assert result.total_cost == 4
    assert result.total_cost == reference.total_cost
    assert result.states[-1].as_dict(problem) == {
        "SA_B1": False,
        "SA_B2": True,
        "DJ": True,
        "C": False,
    }
    assert verify_plan(problem, result.actions).valid


def test_expert_bound_preserves_optimal_cost():
    problem = double_busbar_problem()
    result = astar_search(problem, heuristic="expert")
    assert result.found
    assert result.total_cost == 4


def test_validation_is_memoized():
    problem = double_busbar_problem()
    session = PlanningSession(problem)
    first = session.validate_state(session.initial_state)
    second = session.validate_state(session.initial_state)
    assert first is second
