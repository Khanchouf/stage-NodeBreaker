from __future__ import annotations

import heapq
from dataclasses import dataclass
from enum import Enum
from itertools import count
from math import inf
from typing import Callable, Iterable

from .antecedents import AntecedentEnumeration, enumerate_antecedents, retarget_problem
from .partition import NodalPartition, partition_distance
from .projection import NodeBreakerProjection
from .model import (
    CellKind,
    NetworkState,
    PlanningMode,
    PlanningProblem,
    SwitchKind,
    SwitchRole,
)
from .topology import CacheStatistics, TopologyEngine


@dataclass(frozen=True, slots=True)
class ValidationResult:
    valid: bool
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TransitionAssessment:
    allowed: bool
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    required_future_checks: tuple[str, ...] = ()


class Operation(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"


@dataclass(frozen=True, slots=True)
class Action:
    operation: Operation
    switch_id: str
    cost: int = 1
    reason: str = ""
    warnings: tuple[str, ...] = ()
    required_future_checks: tuple[str, ...] = ()

    @property
    def close(self) -> bool:
        return self.operation is Operation.CLOSE

    def __str__(self) -> str:
        return f"{self.operation.value} {self.switch_id}"


@dataclass(frozen=True, slots=True)
class SearchResult:
    found: bool
    actions: tuple[Action, ...]
    states: tuple[NetworkState, ...]
    total_cost: int | None
    expanded_states: int
    generated_states: int
    reopened_states: int
    cache_statistics: CacheStatistics
    message: str = ""


@dataclass(frozen=True, slots=True)
class AntecedentSearchSummary:
    target_state: NetworkState
    found: bool
    total_cost: int | None
    expanded_states: int
    generated_states: int
    reopened_states: int
    message: str = ""


@dataclass(frozen=True, slots=True)
class NodalSearchResult:
    """Result of the exact "enumerate fibre, then A*" formulation."""

    found: bool
    target_partition: NodalPartition
    antecedents: AntecedentEnumeration
    best_target_state: NetworkState | None
    best_problem: PlanningProblem | None
    best_result: SearchResult | None
    summaries: tuple[AntecedentSearchSummary, ...]
    attempted_antecedents: int
    solved_antecedents: int
    total_expanded_states: int
    total_generated_states: int
    total_reopened_states: int
    exact_global_optimum_guaranteed: bool
    message: str = ""


Heuristic = Callable[[NetworkState, PlanningProblem, TopologyEngine], int]


def apply_action(problem: PlanningProblem, state: NetworkState, action: Action) -> NetworkState:
    return state.with_switch(problem, action.switch_id, closed=action.close)


def _action_reason(problem: PlanningProblem, switch_id: str, close: bool) -> str:
    switch = problem.switch_by_id[switch_id]
    verb = "Fermeture" if close else "Ouverture"
    labels = {
        SwitchRole.COUPLER: "du coupleur",
        SwitchRole.SECTIONING: "du sectionnement",
        SwitchRole.FEEDER_BREAKER: "du disjoncteur de départ",
        SwitchRole.FEEDER_DISCONNECTOR: "du sectionneur d'aiguillage",
    }
    return f"{verb} {labels.get(switch.role, 'du switch')} {switch_id}."


class PlanningSession:
    """Owns all memoization tables used during one A* run."""

    def __init__(self, problem: PlanningProblem, topology: TopologyEngine | None = None):
        self.problem = problem
        self.topology = topology or TopologyEngine(problem)
        self.initial_state = NetworkState.initial(problem)
        self.target_state = NetworkState.target(problem)
        self.initially_served = frozenset(
            equipment.id
            for equipment in problem.equipment
            if self.topology.equipment_in_service(self.initial_state, equipment.id)
        )
        self._transition_cache: dict[
            tuple[tuple[bool, ...], str, bool], TransitionAssessment
        ] = {}
        self._validation_cache: dict[tuple[bool, ...], ValidationResult] = {}
        self._heuristic_cache: dict[tuple[str, tuple[bool, ...]], int] = {}
        self._heuristic_evaluations: dict[str, int] = {}
        self._expert_stronger_evaluations = 0
        self._expert_equal_evaluations = 0

    def assess_transition(
        self,
        state: NetworkState,
        switch_id: str,
        close: bool,
    ) -> TransitionAssessment:
        cache_key = (state.closed_bits, switch_id, close)
        cached = self._transition_cache.get(cache_key)
        if cached is not None:
            return cached

        switch = self.problem.switch_by_id[switch_id]
        if state.is_closed(self.problem, switch_id) == close:
            result = TransitionAssessment(False, ("Action sans effet.",))
        elif switch.fixed:
            result = TransitionAssessment(False, ("Organe déclaré fixe.",))
        elif switch.kind in {SwitchKind.BREAKER, SwitchKind.LOAD_BREAK_SWITCH}:
            checks = ()
            if close and not self.topology.connected(state, switch.node1, switch.node2):
                checks = ("SYNCHRONISM_OR_VOLTAGE_CHECK",)
            result = TransitionAssessment(True, required_future_checks=checks)
        elif switch.kind is not SwitchKind.DISCONNECTOR:
            result = TransitionAssessment(True)
        else:
            result = self._assess_disconnector(state, switch_id, close)

        self._transition_cache[cache_key] = result
        return result

    def _assess_disconnector(
        self,
        state: NetworkState,
        switch_id: str,
        close: bool,
    ) -> TransitionAssessment:
        cells = self.topology.context.switch_cells.get(switch_id, ())
        departure_cells = tuple(
            cell for cell in cells if cell.kind in {CellKind.DEPARTURE, CellKind.OMNIBUS}
        )

        if departure_cells and self.problem.constraints.enforce_disconnector_offload_rule:
            # A multi-breaker cell is considered offloaded only when all of its
            # breakers are open. The former "any breaker open" test was unsafe.
            offloaded_cells = tuple(
                cell
                for cell in departure_cells
                if cell.breaker_ids
                and all(
                    not state.is_closed(self.problem, breaker_id)
                    for breaker_id in cell.breaker_ids
                )
            )

            if offloaded_cells:
                if not close:
                    return TransitionAssessment(True)

                busbar_nodes = set(self.problem.busbar_by_node)
                for cell in offloaded_cells:
                    other_closed_selector = any(
                        other_id != switch_id
                        and state.is_closed(self.problem, other_id)
                        and (
                            self.problem.switch_by_id[other_id].node1 in busbar_nodes
                            or self.problem.switch_by_id[other_id].node2 in busbar_nodes
                        )
                        for other_id in cell.disconnector_ids
                    )
                    if (
                        not other_closed_selector
                        or self.topology.connected_without_switch(state, switch_id)
                    ):
                        return TransitionAssessment(True)

                return TransitionAssessment(
                    False,
                    (
                        "DJ ouvert mais ancien aiguillage encore fermé : le sectionneur "
                        "établirait lui-même le couplage des barres.",
                    ),
                )

            if self.topology.connected_without_switch(state, switch_id):
                return TransitionAssessment(
                    True,
                    warnings=("Sectionneur manœuvré en boucle topologiquement fermée.",),
                )
            return TransitionAssessment(
                False,
                ("Sectionneur de départ manœuvré avec DJ fermé sans chemin parallèle.",),
            )

        special_cells = tuple(
            cell for cell in cells if cell.kind in {CellKind.COUPLING, CellKind.SECTIONING}
        )
        if special_cells and self.problem.constraints.enforce_sectioning_rule:
            if self.topology.connected_without_switch(state, switch_id):
                return TransitionAssessment(True)

            switch = self.problem.switch_by_id[switch_id]
            side1_source = self.topology.side_has_source_without_switch(
                state, switch_id, switch.node1
            )
            side2_source = self.topology.side_has_source_without_switch(
                state, switch_id, switch.node2
            )
            has_sources = bool(self.topology.context.source_nodes)

            if has_sources and not (side1_source and side2_source):
                return TransitionAssessment(True)
            if not has_sources and not self.problem.constraints.strict_sectioning_without_sources:
                return TransitionAssessment(
                    True,
                    warnings=("Aucune source déclarée : contrôle électrique reporté.",),
                    required_future_checks=("SECTIONING_ENERGIZATION_CHECK",),
                )
            return TransitionAssessment(
                False,
                ("Sectionnement par sectionneur avec deux côtés topologiquement alimentés.",),
            )

        return TransitionAssessment(True)

    def validate_state(self, state: NetworkState) -> ValidationResult:
        cached = self._validation_cache.get(state.closed_bits)
        if cached is not None:
            return cached

        reasons: list[str] = []
        warnings: list[str] = []

        for switch in self.problem.switches:
            if switch.fixed and state.is_closed(self.problem, switch.id) != switch.initial_closed:
                reasons.append(f"Le switch fixe {switch.id} a changé d'état.")

        temporary_out = {
            equipment_id
            for equipment_id in self.initially_served
            if not self.topology.equipment_in_service(state, equipment_id)
        }
        max_out = self.problem.constraints.max_temporary_outages
        if self.problem.mode is PlanningMode.AGGRESSIVE:
            max_out = None
        if max_out is not None and len(temporary_out) > max_out:
            reasons.append(
                f"Trop d'équipements temporairement hors service : {sorted(temporary_out)} "
                f"(limite {max_out})."
            )

        if not self.problem.constraints.allow_protected_outage:
            for equipment in self.problem.equipment:
                if equipment.protected and not self.topology.equipment_in_service(state, equipment.id):
                    reasons.append(f"Équipement protégé hors service : {equipment.id}.")

        # Important: there is deliberately no hard "unsupplied island" rule
        # here. The old source-based approximation rejected legitimate
        # temporary feeder outages on real XIIDM networks. Actual energization
        # is deferred to the electrical validation layer.

        if not self.problem.constraints.allow_unsafe_multi_busbar:
            for cell in self.topology.context.cells:
                if cell.kind not in {CellKind.DEPARTURE, CellKind.OMNIBUS}:
                    continue
                reached = self.topology.cell_busbars_reached(state, cell)
                if len(reached) > 1 and not self.topology.busbars_connected_outside_cell(
                    state, cell, reached
                ):
                    reasons.append(
                        f"La cellule {cell.id} raccorde plusieurs barres non couplées "
                        f"extérieurement : {sorted(reached)}."
                    )

        result = ValidationResult(not reasons, tuple(reasons), tuple(warnings))
        self._validation_cache[state.closed_bits] = result
        return result

    def applicable_actions(self, state: NetworkState) -> Iterable[tuple[Action, NetworkState]]:
        for switch in self.problem.switches:
            close = not state.is_closed(self.problem, switch.id)
            assessment = self.assess_transition(state, switch.id, close)
            if not assessment.allowed:
                continue

            action = Action(
                operation=Operation.CLOSE if close else Operation.OPEN,
                switch_id=switch.id,
                cost=switch.operation_cost(close),
                reason=_action_reason(self.problem, switch.id, close),
                warnings=assessment.warnings,
                required_future_checks=assessment.required_future_checks,
            )
            successor = apply_action(self.problem, state, action)
            if self.validate_state(successor).valid:
                yield action, successor

    def heuristic(self, name: str, state: NetworkState) -> int:
        key = (name, state.closed_bits)
        if key not in self._heuristic_cache:
            heuristic = HEURISTICS[name]
            value = heuristic(state, self.problem, self.topology)
            self._heuristic_cache[key] = value
            self._heuristic_evaluations[name] = self._heuristic_evaluations.get(name, 0) + 1

            if name == "expert":
                hamming = hamming_heuristic(state, self.problem, self.topology)
                if value > hamming:
                    self._expert_stronger_evaluations += 1
                else:
                    self._expert_equal_evaluations += 1

        return self._heuristic_cache[key]

    def heuristic_statistics(self) -> dict[str, int]:
        return {
            "zero_evaluations": self._heuristic_evaluations.get("zero", 0),
            "hamming_evaluations": self._heuristic_evaluations.get("hamming", 0),
            "expert_evaluations": self._heuristic_evaluations.get("expert", 0),
            "topological_evaluations": self._heuristic_evaluations.get("topological", 0),
            "combined_evaluations": self._heuristic_evaluations.get("combined", 0),
            "expert_stronger_than_hamming": self._expert_stronger_evaluations,
            "expert_equal_to_hamming": self._expert_equal_evaluations,
        }


def zero_heuristic(
    state: NetworkState,
    problem: PlanningProblem,
    topology: TopologyEngine,
) -> int:
    del state, problem, topology
    return 0


def hamming_heuristic(
    state: NetworkState,
    problem: PlanningProblem,
    topology: TopologyEngine,
) -> int:
    del topology
    return sum(
        1
        for switch, current in zip(problem.switches, state.closed_bits, strict=True)
        if current != switch.target_closed
    )


def topological_heuristic(
    state: NetworkState,
    problem: PlanningProblem,
    topology: TopologyEngine,
) -> int:
    """Nodal partition distance to the detailed target's nodal topology.

    During nodal planning, ``problem`` has already been retargeted to one
    antecedent of T*.  Every such antecedent projects to the same T*, so this
    value is independent of which antecedent is currently being solved.
    """

    current = topology.nodal_partition(state)
    target = topology.nodal_partition(NetworkState.target(problem))
    return partition_distance(current, target)


def combined_heuristic(
    state: NetworkState,
    problem: PlanningProblem,
    topology: TopologyEngine,
) -> int:
    return max(
        expert_double_busbar_heuristic(state, problem, topology),
        topological_heuristic(state, problem, topology),
    )


def _selector_disconnectors(
    problem: PlanningProblem,
    cell,
) -> tuple[str, ...]:
    busbar_nodes = set(problem.busbar_by_node)
    return tuple(
        switch_id
        for switch_id in sorted(cell.disconnector_ids)
        if (
            problem.switch_by_id[switch_id].node1 in busbar_nodes
            or problem.switch_by_id[switch_id].node2 in busbar_nodes
        )
    )


def expert_heuristic_details(
    state: NetworkState,
    problem: PlanningProblem,
    topology: TopologyEngine,
) -> dict[str, object]:
    """Return the certified expert lower-bound breakdown for one state.

    The bound starts from Hamming and adds only operations that are not already
    counted there. For each certified double-busbar departure group, two
    relaxed strategies are compared:

    * CUT: each departure whose breaker is closed both now and at the target
      needs an auxiliary OPEN+CLOSE pair (+2) if sectionneur manoeuvres are made
      by cutting the feeder;
    * TRANSFER: establish an external parallel connection between the two
      busbars. ``TopologyEngine.minimum_auxiliary_connection_cost`` computes an
      optimistic extra cost beyond Hamming. It counts only auxiliary operations
      that are not already counted by Hamming, so it remains a lower bound.

    The minimum of these two strategy bounds is still a lower bound. Several
    cells sharing the same busbar pair are grouped together so that a common
    coupling path is counted only once. If several distinct busbar pairs exist,
    their extra bounds are combined by ``max`` rather than by ``sum`` to avoid
    double-counting shared auxiliary operations.
    """

    hamming = hamming_heuristic(state, problem, topology)

    if not problem.constraints.enforce_disconnector_offload_rule:
        return {
            "hamming": hamming,
            "expert": hamming,
            "certified": False,
            "reason": "disconnector_offload_rule_disabled",
            "groups": [],
        }

    if problem.constraints.allow_unsafe_multi_busbar:
        return {
            "hamming": hamming,
            "expert": hamming,
            "certified": False,
            "reason": "unsafe_multi_busbar_allowed",
            "groups": [],
        }

    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}

    for cell in topology.context.cells:
        if cell.kind is not CellKind.DEPARTURE:
            continue
        if len(cell.breaker_ids) != 1 or len(cell.busbar_ids) != 2:
            continue

        selector_ids = _selector_disconnectors(problem, cell)
        if len(selector_ids) < 2:
            continue

        mismatched_selectors = tuple(
            switch_id
            for switch_id in selector_ids
            if state.is_closed(problem, switch_id)
            != problem.switch_by_id[switch_id].target_closed
        )
        if not mismatched_selectors:
            continue

        breaker_id = next(iter(cell.breaker_ids))
        breaker = problem.switch_by_id[breaker_id]
        current_breaker_closed = state.is_closed(problem, breaker_id)

        # Extra beyond Hamming. If the breaker is closed now and must also be
        # closed at the goal, a cut-based manoeuvre needs OPEN + CLOSE, neither
        # of which is counted by Hamming.
        cut_extra = int(current_breaker_closed and breaker.target_closed) * 2
        pair = tuple(sorted(cell.busbar_ids))
        grouped.setdefault(pair, []).append(
            {
                "cell_id": cell.id,
                "breaker_id": breaker_id,
                "selector_mismatches": list(mismatched_selectors),
                "cut_extra": cut_extra,
            }
        )

    if not grouped:
        return {
            "hamming": hamming,
            "expert": hamming,
            "certified": False,
            "reason": "no_certified_active_double_busbar_departure",
            "groups": [],
        }

    # A parallel transfer is searched outside all feeder cells. Allowing an
    # arbitrary departure itself to act as a coupler would contradict the
    # default multi-busbar safety rule.
    excluded_feeder_switches: set[str] = set()
    for cell in topology.context.cells:
        if cell.kind in {CellKind.DEPARTURE, CellKind.OMNIBUS}:
            excluded_feeder_switches.update(cell.switch_ids)

    group_details: list[dict[str, object]] = []
    group_extra_bounds: list[int] = []

    for pair, cells in sorted(grouped.items()):
        cut_extra = sum(int(item["cut_extra"]) for item in cells)
        transfer_extra = topology.minimum_auxiliary_connection_cost(
            state,
            pair[0],
            pair[1],
            excluded_switch_ids=excluded_feeder_switches,
        )

        if transfer_extra is None:
            selected_extra = cut_extra
            selected_strategy = "CUT_ONLY_CERTIFIED"
        elif transfer_extra < cut_extra:
            selected_extra = transfer_extra
            selected_strategy = "TRANSFER_LOWER_BOUND"
        elif cut_extra < transfer_extra:
            selected_extra = cut_extra
            selected_strategy = "CUT_LOWER_BOUND"
        else:
            selected_extra = cut_extra
            selected_strategy = "CUT_OR_TRANSFER_EQUAL"

        group_extra_bounds.append(selected_extra)
        group_details.append(
            {
                "busbars": list(pair),
                "cells": cells,
                "cut_extra_beyond_hamming": cut_extra,
                "transfer_extra_beyond_hamming": transfer_extra,
                "selected_extra_beyond_hamming": selected_extra,
                "selected_strategy": selected_strategy,
            }
        )

    # Distinct busbar-pair strategies may share auxiliary switches. Taking the
    # maximum is conservative; summing them could overestimate.
    extra = max(group_extra_bounds, default=0)
    expert = hamming + extra

    return {
        "hamming": hamming,
        "expert": max(hamming, expert),
        "certified": True,
        "reason": "certified_local_cut_transfer_bound",
        "groups": group_details,
    }


def expert_double_busbar_heuristic(
    state: NetworkState,
    problem: PlanningProblem,
    topology: TopologyEngine,
) -> int:
    return int(expert_heuristic_details(state, problem, topology)["expert"])


HEURISTICS: dict[str, Heuristic] = {
    "zero": zero_heuristic,
    "hamming": hamming_heuristic,
    "expert": expert_double_busbar_heuristic,
    "topological": topological_heuristic,
    "combined": combined_heuristic,
}


def astar_search(
    problem: PlanningProblem,
    *,
    heuristic: str = "hamming",
    max_expansions: int | None = None,
    session: PlanningSession | None = None,
) -> SearchResult:
    if heuristic not in HEURISTICS:
        raise ValueError(f"Heuristique inconnue : {heuristic}")

    session = session or PlanningSession(problem)
    initial = session.initial_state
    target = session.target_state

    if not session.validate_state(initial).valid:
        return SearchResult(
            False,
            (),
            (initial,),
            None,
            0,
            0,
            0,
            session.topology.statistics(),
            "L'état initial viole les contraintes topologiques.",
        )
    if initial == target:
        return SearchResult(
            True,
            (),
            (initial,),
            0,
            0,
            0,
            0,
            session.topology.statistics(),
        )

    serial = count()

    # Heap order: f first, then larger g (i.e. smaller h) on ties. This is a
    # standard A* tie-break that is particularly important when a strong expert
    # heuristic gives the same f to many states along an optimal path.
    open_heap: list[tuple[int, int, int, NetworkState]] = []
    best_g: dict[NetworkState, int] = {initial: 0}
    parent: dict[NetworkState, tuple[NetworkState, Action]] = {}
    closed_g: dict[NetworkState, int] = {}

    heapq.heappush(
        open_heap,
        (session.heuristic(heuristic, initial), 0, next(serial), initial),
    )

    expanded = generated = reopened = 0

    while open_heap:
        _, neg_g, _, state = heapq.heappop(open_heap)
        g = -neg_g

        if g != best_g.get(state):
            continue

        previous_closed = closed_g.get(state)
        if previous_closed is not None and g >= previous_closed:
            continue
        if previous_closed is not None:
            reopened += 1
        closed_g[state] = g

        if state == target:
            actions, states = _reconstruct(initial, state, parent)
            return SearchResult(
                True,
                actions,
                states,
                g,
                expanded,
                generated,
                reopened,
                session.topology.statistics(),
            )

        if max_expansions is not None and expanded >= max_expansions:
            break

        expanded += 1

        for action, successor in session.applicable_actions(state):
            generated += 1
            new_g = g + action.cost
            if new_g >= best_g.get(successor, inf):
                continue

            best_g[successor] = new_g
            parent[successor] = (state, action)
            h = session.heuristic(heuristic, successor)
            heapq.heappush(
                open_heap,
                (
                    new_g + h,
                    -new_g,
                    next(serial),
                    successor,
                ),
            )

    return SearchResult(
        False,
        (),
        (initial,),
        None,
        expanded,
        generated,
        reopened,
        session.topology.statistics(),
        "Aucun plan trouvé dans la limite de recherche.",
    )


def astar_over_antecedents(
    problem: PlanningProblem,
    target_partition: NodalPartition,
    *,
    heuristic: str = "expert",
    max_expansions: int | None = None,
    max_assignments: int | None = None,
) -> NodalSearchResult:
    """Solve min_{xf in pi^-1(T*)} d_M(x0, xf) exactly when uncapped.

    The fibre is explicitly enumerated.  A fresh detailed target problem is
    then created for every admissible antecedent, allowing the existing A* and
    the existing Hamming/expert heuristic machinery to be reused unchanged.

    With ``max_assignments is None`` and ``max_expansions is None``, every
    admissible antecedent is considered and every A* run is complete; the best
    returned cost is therefore the global optimum over the nodal target fibre.
    """

    if heuristic not in HEURISTICS:
        raise ValueError(f"Heuristique inconnue : {heuristic}")

    base_topology = TopologyEngine(problem)
    base_session = PlanningSession(problem, topology=base_topology)
    projection = NodeBreakerProjection(problem, base_topology)

    antecedents = enumerate_antecedents(
        problem,
        target_partition,
        topology=base_topology,
        projection=projection,
        state_validator=lambda state: base_session.validate_state(state).valid,
        max_assignments=max_assignments,
    )

    summaries: list[AntecedentSearchSummary] = []
    best_target: NetworkState | None = None
    best_problem: PlanningProblem | None = None
    best_result: SearchResult | None = None
    solved = 0
    total_expanded = 0
    total_generated = 0
    total_reopened = 0

    for index, target_state in enumerate(antecedents.states, start=1):
        target_problem = retarget_problem(
            problem,
            target_state,
            name=f"{problem.name}__nodal_antecedent_{index}",
        )
        result = astar_search(
            target_problem,
            heuristic=heuristic,
            max_expansions=max_expansions,
        )
        total_expanded += result.expanded_states
        total_generated += result.generated_states
        total_reopened += result.reopened_states
        if result.found:
            solved += 1

        summaries.append(
            AntecedentSearchSummary(
                target_state=target_state,
                found=result.found,
                total_cost=result.total_cost,
                expanded_states=result.expanded_states,
                generated_states=result.generated_states,
                reopened_states=result.reopened_states,
                message=result.message,
            )
        )

        if not result.found or result.total_cost is None:
            continue
        if (
            best_result is None
            or best_result.total_cost is None
            or result.total_cost < best_result.total_cost
            or (
                result.total_cost == best_result.total_cost
                and result.expanded_states < best_result.expanded_states
            )
        ):
            best_target = target_state
            best_problem = target_problem
            best_result = result

    exact = not antecedents.truncated and max_expansions is None

    if not antecedents.states:
        message = (
            "Aucun antécédent admissible de la topologie nodale cible n'a été trouvé."
        )
    elif best_result is None:
        message = "Des antécédents existent, mais aucun plan n'a été trouvé."
    elif exact:
        message = (
            "Optimum global obtenu sur tous les antécédents admissibles de la "
            "topologie nodale cible."
        )
    else:
        message = (
            "Meilleure solution trouvée dans une recherche limitée ; l'optimalité "
            "globale sur toute la fibre n'est pas garantie."
        )

    return NodalSearchResult(
        found=best_result is not None,
        target_partition=target_partition,
        antecedents=antecedents,
        best_target_state=best_target,
        best_problem=best_problem,
        best_result=best_result,
        summaries=tuple(summaries),
        attempted_antecedents=len(antecedents.states),
        solved_antecedents=solved,
        total_expanded_states=total_expanded,
        total_generated_states=total_generated,
        total_reopened_states=total_reopened,
        exact_global_optimum_guaranteed=exact and best_result is not None,
        message=message,
    )


def _reconstruct(
    initial: NetworkState,
    goal: NetworkState,
    parent: dict[NetworkState, tuple[NetworkState, Action]],
) -> tuple[tuple[Action, ...], tuple[NetworkState, ...]]:
    actions_reversed: list[Action] = []
    states_reversed: list[NetworkState] = [goal]
    state = goal
    while state != initial:
        previous, action = parent[state]
        actions_reversed.append(action)
        states_reversed.append(previous)
        state = previous
    return tuple(reversed(actions_reversed)), tuple(reversed(states_reversed))
