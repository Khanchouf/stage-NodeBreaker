from planner.model import NetworkState
from planner.topology import TopologyEngine

from .helpers import double_busbar_problem


def test_snapshot_and_excluded_connectivity_are_memoized():
    problem = double_busbar_problem()
    engine = TopologyEngine(problem)
    state = NetworkState.initial(problem)
    assert engine.snapshot(state) is engine.snapshot(state)
    engine.connected_without_switch(state, "SA_B1")
    engine.connected_without_switch(state, "SA_B1")
    stats = engine.statistics()
    assert stats.snapshot_hits >= 1
    assert stats.snapshot_misses == 1
    assert stats.excluded_hits >= 1
    assert stats.excluded_misses >= 1


def test_multigraph_materialization_preserves_switch_keys():
    problem = double_busbar_problem()
    engine = TopologyEngine(problem)
    graph = engine.conductive_graph(NetworkState.initial(problem))
    assert graph.has_edge("B1", "X", key="SA_B1")
