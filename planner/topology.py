from __future__ import annotations

import heapq
from dataclasses import dataclass, replace
from math import inf
from typing import Iterable

import networkx as nx

from .model import (
    CellKind,
    CellSpec,
    NetworkState,
    PlanningProblem,
    SwitchKind,
    SwitchRole,
)


@dataclass(frozen=True, slots=True)
class CacheStatistics:
    snapshot_hits: int
    snapshot_misses: int
    excluded_hits: int
    excluded_misses: int
    outside_cell_hits: int
    outside_cell_misses: int


@dataclass(frozen=True, slots=True)
class TopologySnapshot:
    component_by_node: tuple[int, ...]
    nodes_by_component: tuple[frozenset[int], ...]
    busbars_by_component: tuple[frozenset[str], ...]
    equipment_by_component: tuple[frozenset[str], ...]
    source_components: frozenset[int]

    def connected_indices(self, node1: int, node2: int) -> bool:
        return self.component_by_node[node1] == self.component_by_node[node2]


@dataclass(frozen=True, slots=True)
class TopologyContext:
    node_ids: tuple[str, ...]
    node_index: dict[str, int]
    internal_neighbors: tuple[tuple[int, ...], ...]
    incident_switches: tuple[tuple[int, ...], ...]
    switch_endpoints: tuple[tuple[int, int], ...]
    equipment_nodes: dict[str, tuple[int, ...]]
    busbar_node_to_id: dict[int, str]
    source_nodes: frozenset[int]
    cells: tuple[CellSpec, ...]
    switch_cells: dict[str, tuple[CellSpec, ...]]


def derive_cells(problem: PlanningProblem) -> tuple[CellSpec, ...]:
    """Derive functional cells from the static Node-Breaker graph.

    Busbar-section nodes are removed from the structural graph. Every remaining
    connected component is a cell candidate. A component containing equipment
    is a departure/omnibus cell; a component adjacent to at least two busbars
    and containing no equipment is a coupling cell. Direct busbar-to-busbar
    switches are handled separately.
    """

    if problem.cells:
        return problem.cells

    structural = nx.MultiGraph()
    structural.add_nodes_from(problem.nodes)
    for edge_index, (node1, node2) in enumerate(problem.internal_connections):
        structural.add_edge(node1, node2, key=f"IC_{edge_index}", kind="INTERNAL")
    for switch in problem.switches:
        structural.add_edge(
            switch.node1,
            switch.node2,
            key=switch.id,
            kind="SWITCH",
            switch_id=switch.id,
        )

    busbar_nodes = set(problem.busbar_by_node)
    reduced = structural.copy()
    reduced.remove_nodes_from(busbar_nodes)
    cells: list[CellSpec] = []

    for component_index, component in enumerate(nx.connected_components(reduced), start=1):
        component_nodes = frozenset(component)
        switch_ids = {
            switch.id
            for switch in problem.switches
            if switch.node1 in component_nodes or switch.node2 in component_nodes
        }
        equipment_ids = {
            equipment.id
            for equipment in problem.equipment
            if set(equipment.nodes) & component_nodes
        }
        adjacent_busbars = {
            busbar.id
            for busbar in problem.busbars
            if any(
                (switch.node1 == busbar.node and switch.node2 in component_nodes)
                or (switch.node2 == busbar.node and switch.node1 in component_nodes)
                for switch in problem.switches
            )
        }

        if equipment_ids:
            kind = CellKind.OMNIBUS if len(equipment_ids) > 1 else CellKind.DEPARTURE
        elif len(adjacent_busbars) >= 2:
            # A no-equipment component joining busbars is a coupling/sectioning
            # structure. If it only contains disconnectors explicitly tagged as
            # sectioning, preserve that semantic; otherwise call it coupling.
            candidate_switches = [problem.switch_by_id[sid] for sid in switch_ids]
            if candidate_switches and all(
                sw.kind is SwitchKind.DISCONNECTOR
                and sw.role is SwitchRole.SECTIONING
                for sw in candidate_switches
            ):
                kind = CellKind.SECTIONING
            else:
                kind = CellKind.COUPLING
        else:
            kind = CellKind.INTERNAL

        breakers = {
            switch_id
            for switch_id in switch_ids
            if problem.switch_by_id[switch_id].kind is SwitchKind.BREAKER
        }
        disconnectors = {
            switch_id
            for switch_id in switch_ids
            if problem.switch_by_id[switch_id].kind is SwitchKind.DISCONNECTOR
        }
        cells.append(
            CellSpec(
                id=f"CELL_{component_index}",
                kind=kind,
                node_ids=component_nodes,
                switch_ids=frozenset(switch_ids),
                equipment_ids=frozenset(equipment_ids),
                busbar_ids=frozenset(adjacent_busbars),
                breaker_ids=frozenset(breakers),
                disconnector_ids=frozenset(disconnectors),
            )
        )

    handled = set().union(*(cell.switch_ids for cell in cells), set())
    for switch in problem.switches:
        if switch.id in handled:
            continue
        if switch.node1 not in busbar_nodes or switch.node2 not in busbar_nodes:
            continue
        busbars = frozenset(
            {
                problem.busbar_by_node[switch.node1].id,
                problem.busbar_by_node[switch.node2].id,
            }
        )
        kind = CellKind.SECTIONING if switch.role is SwitchRole.SECTIONING else CellKind.COUPLING
        cells.append(
            CellSpec(
                id=f"CELL_{len(cells) + 1}",
                kind=kind,
                node_ids=frozenset(),
                switch_ids=frozenset({switch.id}),
                equipment_ids=frozenset(),
                busbar_ids=busbars,
                breaker_ids=(
                    frozenset({switch.id})
                    if switch.kind is SwitchKind.BREAKER
                    else frozenset()
                ),
                disconnector_ids=(
                    frozenset({switch.id})
                    if switch.kind is SwitchKind.DISCONNECTOR
                    else frozenset()
                ),
            )
        )
    return tuple(cells)


def infer_switch_roles(
    problem: PlanningProblem,
    cells: tuple[CellSpec, ...] | None = None,
) -> tuple:
    cells = cells or derive_cells(problem)
    inferred: dict[str, SwitchRole] = {}
    busbar_nodes = set(problem.busbar_by_node)
    for cell in cells:
        if cell.kind in {CellKind.DEPARTURE, CellKind.OMNIBUS}:
            for switch_id in cell.breaker_ids:
                inferred.setdefault(switch_id, SwitchRole.FEEDER_BREAKER)
            for switch_id in cell.disconnector_ids:
                switch = problem.switch_by_id[switch_id]
                if switch.node1 in busbar_nodes or switch.node2 in busbar_nodes:
                    inferred.setdefault(switch_id, SwitchRole.FEEDER_DISCONNECTOR)
        elif cell.kind is CellKind.COUPLING:
            for switch_id in cell.switch_ids:
                inferred.setdefault(switch_id, SwitchRole.COUPLER)
        elif cell.kind is CellKind.SECTIONING:
            for switch_id in cell.switch_ids:
                inferred.setdefault(switch_id, SwitchRole.SECTIONING)
    return tuple(
        replace(
            switch,
            role=(
                inferred.get(switch.id, switch.role)
                if switch.role is SwitchRole.OTHER
                else switch.role
            ),
        )
        for switch in problem.switches
    )


def build_context(problem: PlanningProblem) -> TopologyContext:
    node_index = {node: index for index, node in enumerate(problem.nodes)}
    internal_neighbors: list[list[int]] = [[] for _ in problem.nodes]
    for node1, node2 in problem.internal_connections:
        u, v = node_index[node1], node_index[node2]
        internal_neighbors[u].append(v)
        internal_neighbors[v].append(u)

    switch_endpoints = tuple(
        (node_index[switch.node1], node_index[switch.node2])
        for switch in problem.switches
    )
    incident_switches: list[list[int]] = [[] for _ in problem.nodes]
    for switch_index, (u, v) in enumerate(switch_endpoints):
        incident_switches[u].append(switch_index)
        incident_switches[v].append(switch_index)

    cells = derive_cells(problem)
    switch_cells_mutable: dict[str, list[CellSpec]] = {switch.id: [] for switch in problem.switches}
    for cell in cells:
        for switch_id in cell.switch_ids:
            switch_cells_mutable.setdefault(switch_id, []).append(cell)

    return TopologyContext(
        node_ids=problem.nodes,
        node_index=node_index,
        internal_neighbors=tuple(tuple(values) for values in internal_neighbors),
        incident_switches=tuple(tuple(values) for values in incident_switches),
        switch_endpoints=switch_endpoints,
        equipment_nodes={
            equipment.id: tuple(node_index[node] for node in equipment.nodes)
            for equipment in problem.equipment
        },
        busbar_node_to_id={node_index[busbar.node]: busbar.id for busbar in problem.busbars},
        source_nodes=frozenset(
            node_index[node]
            for equipment in problem.equipment
            if equipment.source
            for node in equipment.nodes
        ),
        cells=cells,
        switch_cells={key: tuple(value) for key, value in switch_cells_mutable.items()},
    )


class TopologyEngine:
    """Memoized topology service shared by A*, validation and heuristics."""

    def __init__(self, problem: PlanningProblem):
        self.problem = problem
        self.context = build_context(problem)
        self._snapshot_cache: dict[tuple[bool, ...], TopologySnapshot] = {}
        self._excluded_cache: dict[tuple[tuple[bool, ...], tuple[int, ...]], tuple[int, ...]] = {}
        self._outside_cell_cache: dict[
            tuple[tuple[bool, ...], str, tuple[str, ...]], bool
        ] = {}
        self._aux_connection_cache: dict[
            tuple[tuple[bool, ...], str, str, tuple[int, ...]], int | None
        ] = {}
        self._snapshot_hits = 0
        self._snapshot_misses = 0
        self._excluded_hits = 0
        self._excluded_misses = 0
        self._outside_hits = 0
        self._outside_misses = 0

    def statistics(self) -> CacheStatistics:
        return CacheStatistics(
            self._snapshot_hits,
            self._snapshot_misses,
            self._excluded_hits,
            self._excluded_misses,
            self._outside_hits,
            self._outside_misses,
        )

    def _components(
        self,
        state: NetworkState,
        excluded_switch_indices: tuple[int, ...] = (),
    ) -> tuple[int, ...]:
        excluded_switch_indices = tuple(sorted(set(excluded_switch_indices)))
        key = (state.closed_bits, excluded_switch_indices)
        if excluded_switch_indices and key in self._excluded_cache:
            self._excluded_hits += 1
            return self._excluded_cache[key]
        if excluded_switch_indices:
            self._excluded_misses += 1

        excluded = set(excluded_switch_indices)
        component = [-1] * len(self.context.node_ids)
        current_component = 0
        for start in range(len(component)):
            if component[start] != -1:
                continue
            component[start] = current_component
            stack = [start]
            while stack:
                node = stack.pop()
                for neighbor in self.context.internal_neighbors[node]:
                    if component[neighbor] == -1:
                        component[neighbor] = current_component
                        stack.append(neighbor)
                for switch_index in self.context.incident_switches[node]:
                    if switch_index in excluded or not state.closed_bits[switch_index]:
                        continue
                    u, v = self.context.switch_endpoints[switch_index]
                    neighbor = v if node == u else u
                    if component[neighbor] == -1:
                        component[neighbor] = current_component
                        stack.append(neighbor)
            current_component += 1
        result = tuple(component)
        if excluded_switch_indices:
            self._excluded_cache[key] = result
        return result

    def snapshot(self, state: NetworkState) -> TopologySnapshot:
        cached = self._snapshot_cache.get(state.closed_bits)
        if cached is not None:
            self._snapshot_hits += 1
            return cached
        self._snapshot_misses += 1
        component_by_node = self._components(state)
        count = max(component_by_node, default=-1) + 1
        nodes_by_component_mutable: list[set[int]] = [set() for _ in range(count)]
        for node, component in enumerate(component_by_node):
            nodes_by_component_mutable[component].add(node)

        busbars_mutable: list[set[str]] = [set() for _ in range(count)]
        for node, busbar_id in self.context.busbar_node_to_id.items():
            busbars_mutable[component_by_node[node]].add(busbar_id)

        equipment_mutable: list[set[str]] = [set() for _ in range(count)]
        for equipment_id, nodes in self.context.equipment_nodes.items():
            for component in {component_by_node[node] for node in nodes}:
                equipment_mutable[component].add(equipment_id)

        source_components = frozenset(component_by_node[node] for node in self.context.source_nodes)
        result = TopologySnapshot(
            component_by_node=component_by_node,
            nodes_by_component=tuple(frozenset(nodes) for nodes in nodes_by_component_mutable),
            busbars_by_component=tuple(frozenset(values) for values in busbars_mutable),
            equipment_by_component=tuple(frozenset(values) for values in equipment_mutable),
            source_components=source_components,
        )
        self._snapshot_cache[state.closed_bits] = result
        return result

    def connected(self, state: NetworkState, node1: str, node2: str) -> bool:
        snap = self.snapshot(state)
        return snap.connected_indices(
            self.context.node_index[node1],
            self.context.node_index[node2],
        )

    def equipment_busbars(self, state: NetworkState, equipment_id: str) -> frozenset[str]:
        snap = self.snapshot(state)
        values: set[str] = set()
        for node in self.context.equipment_nodes[equipment_id]:
            values.update(snap.busbars_by_component[snap.component_by_node[node]])
        return frozenset(values)

    def equipment_in_service(self, state: NetworkState, equipment_id: str) -> bool:
        return bool(self.equipment_busbars(state, equipment_id))

    def equipment_supplied(self, state: NetworkState, equipment_id: str) -> bool:
        """Legacy helper kept for diagnostics, not a hard A* constraint."""
        snap = self.snapshot(state)
        if not snap.source_components:
            return self.equipment_in_service(state, equipment_id)
        return any(
            snap.component_by_node[node] in snap.source_components
            for node in self.context.equipment_nodes[equipment_id]
        )

    def connected_without_switch(self, state: NetworkState, switch_id: str) -> bool:
        switch_index = self.problem.switch_index[switch_id]
        components = self._components(state, (switch_index,))
        u, v = self.context.switch_endpoints[switch_index]
        return components[u] == components[v]

    def side_has_source_without_switch(
        self,
        state: NetworkState,
        switch_id: str,
        side_node: str,
    ) -> bool:
        switch_index = self.problem.switch_index[switch_id]
        components = self._components(state, (switch_index,))
        side_component = components[self.context.node_index[side_node]]
        return any(components[node] == side_component for node in self.context.source_nodes)

    def cell_busbars_reached(self, state: NetworkState, cell: CellSpec) -> frozenset[str]:
        reached: set[str] = set()
        for equipment_id in cell.equipment_ids:
            reached.update(self.equipment_busbars(state, equipment_id))
        return frozenset(reached)

    def busbars_connected_outside_cell(
        self,
        state: NetworkState,
        cell: CellSpec,
        busbar_ids: Iterable[str],
    ) -> bool:
        ids = tuple(sorted(set(busbar_ids)))
        if len(ids) <= 1:
            return True
        cache_key = (state.closed_bits, cell.id, ids)
        if cache_key in self._outside_cell_cache:
            self._outside_hits += 1
            return self._outside_cell_cache[cache_key]
        self._outside_misses += 1
        excluded = tuple(sorted(self.problem.switch_index[sid] for sid in cell.switch_ids))
        components = self._components(state, excluded)
        nodes = [
            self.context.node_index[self.problem.busbar_by_id[busbar_id].node]
            for busbar_id in ids
        ]
        result = all(components[nodes[0]] == components[node] for node in nodes[1:])
        self._outside_cell_cache[cache_key] = result
        return result

    def minimum_auxiliary_connection_cost(
        self,
        state: NetworkState,
        busbar_id1: str,
        busbar_id2: str,
        *,
        excluded_switch_ids: Iterable[str] = (),
    ) -> int | None:
        """Optimistic extra-operation cost to connect two busbars.

        This method is used only by the expert heuristic. It builds a relaxed
        connectivity problem in which logical switching constraints are ignored.
        Therefore the returned value is a lower bound, not an executable plan.

        Edge cost is measured *in addition to the global Hamming bound*:
        - an already closed switch costs 0;
        - an open switch that must be closed in the target costs 0 because that
          closing operation is already counted by Hamming;
        - an open switch whose target is also open costs 2: it must be closed to
          establish the temporary path and reopened to reach the target;
        - an open fixed switch cannot be used.
        Internal permanent connections cost 0.
        """

        if busbar_id1 == busbar_id2:
            return 0
        if busbar_id1 not in self.problem.busbar_by_id or busbar_id2 not in self.problem.busbar_by_id:
            raise KeyError("Busbar inconnu dans minimum_auxiliary_connection_cost.")

        left, right = sorted((busbar_id1, busbar_id2))
        excluded_indices = tuple(
            sorted(
                {
                    self.problem.switch_index[sid]
                    for sid in excluded_switch_ids
                    if sid in self.problem.switch_index
                }
            )
        )
        cache_key = (state.closed_bits, left, right, excluded_indices)
        if cache_key in self._aux_connection_cache:
            return self._aux_connection_cache[cache_key]

        source = self.context.node_index[self.problem.busbar_by_id[left].node]
        target = self.context.node_index[self.problem.busbar_by_id[right].node]
        excluded = set(excluded_indices)

        distance = [inf] * len(self.context.node_ids)
        distance[source] = 0
        queue: list[tuple[int, int]] = [(0, source)]

        while queue:
            cost, node = heapq.heappop(queue)
            if cost != distance[node]:
                continue
            if node == target:
                result = int(cost)
                self._aux_connection_cache[cache_key] = result
                return result

            for neighbor in self.context.internal_neighbors[node]:
                if cost < distance[neighbor]:
                    distance[neighbor] = cost
                    heapq.heappush(queue, (cost, neighbor))

            for switch_index in self.context.incident_switches[node]:
                if switch_index in excluded:
                    continue
                u, v = self.context.switch_endpoints[switch_index]
                neighbor = v if node == u else u
                switch = self.problem.switches[switch_index]

                if state.closed_bits[switch_index]:
                    edge_cost = 0
                elif switch.fixed:
                    continue
                elif switch.target_closed:
                    edge_cost = 0
                else:
                    edge_cost = 2

                candidate = cost + edge_cost
                if candidate < distance[neighbor]:
                    distance[neighbor] = candidate
                    heapq.heappush(queue, (candidate, neighbor))

        self._aux_connection_cache[cache_key] = None
        return None

    def conductive_graph(self, state: NetworkState) -> nx.MultiGraph:
        """Materialize a graph only for inspection/debugging, not for the hot loop."""
        graph = nx.MultiGraph()
        graph.add_nodes_from(self.problem.nodes)
        for index, (node1, node2) in enumerate(self.problem.internal_connections):
            graph.add_edge(node1, node2, key=f"IC_{index}", edge_type="INTERNAL")
        for index, switch in enumerate(self.problem.switches):
            if state.closed_bits[index]:
                graph.add_edge(
                    switch.node1,
                    switch.node2,
                    key=switch.id,
                    edge_type="SWITCH",
                    switch_id=switch.id,
                    kind=switch.kind.value,
                )
        return graph
