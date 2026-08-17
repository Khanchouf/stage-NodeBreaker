from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .electrical import (
    ElectricalSequenceReport,
    ElectricalValidationConfig,
    validate_sequence_electrically,
)
from .model import NetworkState, PlanningProblem
from .search import Action, PlanningSession, apply_action


@dataclass(frozen=True, slots=True)
class VerifiedStep:
    index: int
    action: Action
    state: NetworkState
    valid: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SymbolicSequenceReport:
    valid: bool
    reached_detailed_goal: bool
    failed_step: int | None
    steps: tuple[VerifiedStep, ...]


@dataclass(frozen=True, slots=True)
class CompleteVerificationReport:
    symbolic: SymbolicSequenceReport
    electrical: ElectricalSequenceReport | None

    @property
    def valid(self) -> bool:
        return self.symbolic.valid and (
            self.electrical is None or self.electrical.valid
        )


def verify_plan(
    problem: PlanningProblem,
    actions: Iterable[Action],
    *,
    session: PlanningSession | None = None,
) -> SymbolicSequenceReport:
    session = session or PlanningSession(problem)
    state = session.initial_state
    steps: list[VerifiedStep] = []

    for index, action in enumerate(actions, start=1):
        assessment = session.assess_transition(state, action.switch_id, action.close)
        if not assessment.allowed:
            steps.append(
                VerifiedStep(index, action, state, False, assessment.reasons)
            )
            return SymbolicSequenceReport(False, False, index, tuple(steps))
        next_state = apply_action(problem, state, action)
        validation = session.validate_state(next_state)
        steps.append(
            VerifiedStep(index, action, next_state, validation.valid, validation.reasons)
        )
        if not validation.valid:
            return SymbolicSequenceReport(False, False, index, tuple(steps))
        state = next_state

    reached = state == session.target_state
    return SymbolicSequenceReport(reached, reached, None if reached else len(steps), tuple(steps))


def verify_plan_completely(
    problem: PlanningProblem,
    actions: Iterable[Action],
    *,
    network_or_path: Any | None = None,
    electrical_config: ElectricalValidationConfig | None = None,
    session: PlanningSession | None = None,
) -> CompleteVerificationReport:
    actions_tuple = tuple(actions)
    symbolic = verify_plan(problem, actions_tuple, session=session)
    if not symbolic.valid or network_or_path is None:
        return CompleteVerificationReport(symbolic, None)
    electrical = validate_sequence_electrically(
        network_or_path,
        problem,
        actions_tuple,
        electrical_config,
    )
    return CompleteVerificationReport(symbolic, electrical)
