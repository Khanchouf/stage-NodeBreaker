from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import combinations
from typing import Callable, Iterator

from .model import NetworkState, PlanningProblem
from .partition import NodalPartition
from .projection import NodeBreakerProjection
from .topology import TopologyEngine


@dataclass(frozen=True, slots=True)
class AntecedentEnumeration:
    """Exact explicit fibre π^{-1}(T*) restricted to admissible fixed states."""

    target_partition: NodalPartition
    states: tuple[NetworkState, ...]
    assignments_checked: int
    projection_matches: int
    invalid_projection_matches: int
    truncated: bool = False

    @property
    def count(self) -> int:
        return len(self.states)


def _candidate_states_by_hamming_from_initial(
    problem: PlanningProblem,
) -> Iterator[NetworkState]:
    """Enumerate every detailed state compatible with fixed switches exactly once.

    The order is increasing Hamming distance from the initial detailed state.
    This does not change exactness; it only tends to expose nearby antecedents
    earlier when the explicit fibre is large.
    """

    initial = NetworkState.initial(problem)
    movable_indices = tuple(
        index for index, switch in enumerate(problem.switches) if not switch.fixed
    )

    for distance in range(len(movable_indices) + 1):
        for flipped in combinations(movable_indices, distance):
            bits = list(initial.closed_bits)
            for index in flipped:
                bits[index] = not bits[index]
            yield NetworkState(tuple(bits))


def enumerate_antecedents(
    problem: PlanningProblem,
    target_partition: NodalPartition,
    *,
    topology: TopologyEngine | None = None,
    projection: NodeBreakerProjection | None = None,
    state_validator: Callable[[NetworkState], bool] | None = None,
    max_assignments: int | None = None,
) -> AntecedentEnumeration:
    """Explicitly enumerate the fibre π^{-1}(T*).

    By default no artificial limit is applied: all 2^m configurations of the
    m non-fixed switches are considered.  ``max_assignments`` is only a safety
    valve for experiments; when it is reached the result is marked truncated
    and must not be advertised as globally exhaustive.
    """

    topology = topology or TopologyEngine(problem)
    projection = projection or NodeBreakerProjection(problem, topology)

    expected_universe = projection.initial_partition().universe
    if target_partition.universe != expected_universe:
        missing = sorted(expected_universe - target_partition.universe)
        extra = sorted(target_partition.universe - expected_universe)
        raise ValueError(
            "La topologie cible ne porte pas sur les mêmes observables que le réseau. "
            f"Manquants={missing}, supplémentaires={extra}."
        )

    accepted: list[NetworkState] = []
    assignments_checked = 0
    projection_matches = 0
    invalid_projection_matches = 0
    truncated = False

    for state in _candidate_states_by_hamming_from_initial(problem):
        if max_assignments is not None and assignments_checked >= max_assignments:
            truncated = True
            break
        assignments_checked += 1

        if projection.project(state) != target_partition:
            continue
        projection_matches += 1

        if state_validator is not None and not state_validator(state):
            invalid_projection_matches += 1
            continue
        accepted.append(state)

    return AntecedentEnumeration(
        target_partition=target_partition,
        states=tuple(accepted),
        assignments_checked=assignments_checked,
        projection_matches=projection_matches,
        invalid_projection_matches=invalid_projection_matches,
        truncated=truncated,
    )


def retarget_problem(
    problem: PlanningProblem,
    target_state: NetworkState,
    *,
    name: str | None = None,
) -> PlanningProblem:
    """Clone a problem while making ``target_state`` its detailed target.

    This is the bridge that lets the existing detailed A* and the existing
    Hamming/expert heuristics be reused unchanged for every antecedent.
    """

    if len(target_state.closed_bits) != len(problem.switches):
        raise ValueError("La taille de l'antécédent ne correspond pas au nombre de switches.")

    switches = tuple(
        replace(switch, target_closed=target_state.closed_bits[index])
        for index, switch in enumerate(problem.switches)
    )
    return replace(
        problem,
        name=name or problem.name,
        switches=switches,
    )
