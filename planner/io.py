from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .electrical import ElectricalSequenceReport
from .model import (
    BusbarSpec,
    CellKind,
    CellSpec,
    EquipmentKind,
    EquipmentSpec,
    PlanningConstraints,
    PlanningMode,
    PlanningProblem,
    SwitchKind,
    SwitchRole,
    SwitchSpec,
)
from .search import SearchResult


def problem_to_dict(problem: PlanningProblem) -> dict[str, Any]:
    return {
        "name": problem.name,
        "goal": "DETAILED",
        "mode": problem.mode.value,
        "constraints": {
            field: getattr(problem.constraints, field)
            for field in problem.constraints.__dataclass_fields__
        },
        "nodes": list(problem.nodes),
        "internal_connections": [list(edge) for edge in problem.internal_connections],
        "busbars": [
            {"id": b.id, "node": b.node, "group": b.group, "section": b.section}
            for b in problem.busbars
        ],
        "equipment": [
            {
                "id": e.id,
                "kind": e.kind.value,
                "nodes": list(e.nodes),
                "protected": e.protected,
                "source": e.source,
                "load": e.load,
            }
            for e in problem.equipment
        ],
        "switches": [
            {
                "id": s.id,
                "kind": s.kind.value,
                "role": s.role.value,
                "node1": s.node1,
                "node2": s.node2,
                "initial_closed": s.initial_closed,
                "target_closed": s.target_closed,
                "fixed": s.fixed,
                "retained": s.retained,
                "voltage_level_id": s.voltage_level_id,
            }
            for s in problem.switches
        ],
        "cells": [
            {
                "id": c.id,
                "kind": c.kind.value,
                "node_ids": sorted(c.node_ids),
                "switch_ids": sorted(c.switch_ids),
                "equipment_ids": sorted(c.equipment_ids),
                "busbar_ids": sorted(c.busbar_ids),
                "breaker_ids": sorted(c.breaker_ids),
                "disconnector_ids": sorted(c.disconnector_ids),
            }
            for c in problem.cells
        ],
    }


def problem_from_dict(data: dict[str, Any]) -> PlanningProblem:
    if str(data.get("goal", "DETAILED")).upper() != "DETAILED":
        raise ValueError("La version v3 accepte uniquement un but DETAILED.")
    constraints_data = data.get("constraints", {})
    constraints = PlanningConstraints(
        **{
            key: constraints_data.get(key, field.default)
            for key, field in PlanningConstraints.__dataclass_fields__.items()
        }
    )
    return PlanningProblem(
        name=data.get("name", "node_breaker_problem"),
        nodes=tuple(str(node) for node in data["nodes"]),
        internal_connections=tuple(
            (str(edge[0]), str(edge[1])) for edge in data.get("internal_connections", [])
        ),
        busbars=tuple(
            BusbarSpec(str(item["id"]), str(item["node"]), item.get("group"), item.get("section"))
            for item in data.get("busbars", [])
        ),
        equipment=tuple(
            EquipmentSpec(
                str(item["id"]),
                EquipmentKind(str(item.get("kind", "OTHER")).upper()),
                tuple(str(node) for node in item["nodes"]),
                bool(item.get("protected", False)),
                bool(item.get("source", False)),
                bool(item.get("load", False)),
            )
            for item in data.get("equipment", [])
        ),
        switches=tuple(
            SwitchSpec(
                str(item["id"]),
                SwitchKind(str(item.get("kind", "BREAKER")).upper()),
                str(item["node1"]),
                str(item["node2"]),
                bool(item["initial_closed"]),
                bool(item["target_closed"]),
                bool(item.get("fixed", False)),
                bool(item.get("retained", False)),
                SwitchRole(str(item.get("role", "OTHER")).upper()),
                item.get("voltage_level_id"),
            )
            for item in data.get("switches", [])
        ),
        cells=tuple(
            CellSpec(
                str(item["id"]),
                CellKind(str(item.get("kind", "INTERNAL")).upper()),
                frozenset(map(str, item.get("node_ids", []))),
                frozenset(map(str, item.get("switch_ids", []))),
                frozenset(map(str, item.get("equipment_ids", []))),
                frozenset(map(str, item.get("busbar_ids", []))),
                frozenset(map(str, item.get("breaker_ids", []))),
                frozenset(map(str, item.get("disconnector_ids", []))),
            )
            for item in data.get("cells", [])
        ),
        mode=PlanningMode(str(data.get("mode", "SMOOTH")).upper()),
        constraints=constraints,
    )


def load_problem(path: str | Path) -> PlanningProblem:
    return problem_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def write_problem(path: str | Path, problem: PlanningProblem) -> Path:
    output = Path(path)
    output.write_text(json.dumps(problem_to_dict(problem), indent=2, ensure_ascii=False), encoding="utf-8")
    return output


def search_result_to_dict(problem: PlanningProblem, result: SearchResult) -> dict[str, Any]:
    return {
        "problem": problem.name,
        "goal": "DETAILED",
        "found": result.found,
        "total_cost": result.total_cost,
        "expanded_states": result.expanded_states,
        "generated_states": result.generated_states,
        "reopened_states": result.reopened_states,
        "cache_statistics": asdict(result.cache_statistics),
        "message": result.message,
        "steps": [
            {
                "index": index,
                "operation": action.operation.value,
                "switch_id": action.switch_id,
                "cost": action.cost,
                "reason": action.reason,
                "warnings": list(action.warnings),
                "required_future_checks": list(action.required_future_checks),
                "switch_states": result.states[index].as_dict(problem),
            }
            for index, action in enumerate(result.actions, start=1)
        ],
    }


def electrical_report_to_dict(report: ElectricalSequenceReport) -> dict[str, Any]:
    return {
        "valid": report.valid,
        "failed_step": report.failed_step,
        "transition_reports": [
            {
                "step_index": item.step_index,
                "switch_id": item.switch_id,
                "valid": item.valid,
                "warnings": list(item.warnings),
                "violations": [asdict(violation) for violation in item.violations],
            }
            for item in report.transition_reports
        ],
        "state_reports": [
            {
                "state_name": item.state_name,
                "converged": item.converged,
                "valid": item.valid,
                "component_statuses": list(item.component_statuses),
                "warnings": list(item.warnings),
                "violations": [asdict(violation) for violation in item.violations],
            }
            for item in report.state_reports
        ],
    }
