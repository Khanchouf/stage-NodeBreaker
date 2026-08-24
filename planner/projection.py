from __future__ import annotations

from dataclasses import dataclass

from .model import NetworkState, PlanningProblem
from .partition import NodalPartition, partition_distance
from .topology import TopologyEngine


@dataclass(slots=True)
class NodeBreakerProjection:
    """Projection π from detailed switch states to nodal topologies."""

    problem: PlanningProblem
    topology: TopologyEngine
    include_busbars: bool = True

    def __init__(
        self,
        problem: PlanningProblem,
        topology: TopologyEngine | None = None,
        *,
        include_busbars: bool = True,
    ) -> None:
        self.problem = problem
        self.topology = topology or TopologyEngine(problem)
        self.include_busbars = include_busbars

    def project(self, state: NetworkState) -> NodalPartition:
        return self.topology.nodal_partition(
            state,
            include_busbars=self.include_busbars,
        )

    __call__ = project

    def initial_partition(self) -> NodalPartition:
        return self.project(NetworkState.initial(self.problem))

    def detailed_target_partition(self) -> NodalPartition:
        return self.project(NetworkState.target(self.problem))

    def realizes(self, state: NetworkState, target: NodalPartition) -> bool:
        return self.project(state) == target

    def distance(self, state: NetworkState, target: NodalPartition) -> int:
        return partition_distance(self.project(state), target)
