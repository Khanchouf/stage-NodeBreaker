import pytest

pp = pytest.importorskip("pypowsybl")

from planner.search import astar_search
from planner.xiidm import problem_from_networks


def test_four_substations_network_extraction_and_search():
    initial = pp.network.create_four_substations_node_breaker_network()
    target = pp.network.create_four_substations_node_breaker_network()
    old = "S1VL2_BBS1_TWT_DISCONNECTOR"
    new = "S1VL2_BBS2_TWT_DISCONNECTOR"
    breaker = "S1VL2_TWT_BREAKER"
    target.update_switches(id=[old, new], open=[True, False])
    problem = problem_from_networks(
        initial,
        target,
        "S1VL2",
        overlay={"movable_switches": [old, new, breaker]},
    )
    result = astar_search(problem)
    assert result.found
    assert result.states[-1] == result.states[-1].target(problem)
