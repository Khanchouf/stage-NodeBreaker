from __future__ import annotations

import re
import shutil
from pathlib import Path

from planner.model import CellKind, NetworkState, PlanningProblem, SwitchKind, SwitchRole
from planner.topology import TopologyEngine


def pddl_name(value: str) -> str:
    """Convert an arbitrary identifier into a PDDL-safe symbol."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "-", str(value))
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"X-{cleaned}"
    return cleaned.upper()


def _literal_closed(switch_name: str, closed: bool) -> str:
    return f"(closed {switch_name})" if closed else f"(not (closed {switch_name}))"


def build_problem_text(problem: PlanningProblem) -> str:
    """Build the detailed-target PDDL problem associated with a PlanningProblem."""
    topology = TopologyEngine(problem)
    initial = NetworkState.initial(problem)
    target = NetworkState.target(problem)

    objects: dict[str, list[str]] = {
        "breaker": [],
        "disconnector": [],
        "load-break-switch": [],
        "departure-cell": [],
        "coupling-cell": [],
        "sectioning-cell": [],
        "omnibus-cell": [],
        "internal-cell": [],
        "busbar": [pddl_name(busbar.id) for busbar in problem.busbars],
        "equipment": [pddl_name(item.id) for item in problem.equipment],
        "busbar-node": [],
        "equipment-node": [],
        "internal-node": [],
    }

    busbar_nodes = set(problem.busbar_by_node)
    equipment_nodes = {node for item in problem.equipment for node in item.nodes}

    for node in problem.nodes:
        if node in busbar_nodes:
            objects["busbar-node"].append(pddl_name(node))
        elif node in equipment_nodes:
            objects["equipment-node"].append(pddl_name(node))
        else:
            objects["internal-node"].append(pddl_name(node))

    for switch in problem.switches:
        type_name = {
            SwitchKind.BREAKER: "breaker",
            SwitchKind.DISCONNECTOR: "disconnector",
            SwitchKind.LOAD_BREAK_SWITCH: "load-break-switch",
        }[switch.kind]
        objects[type_name].append(pddl_name(switch.id))

    for cell in problem.cells:
        type_name = {
            CellKind.DEPARTURE: "departure-cell",
            CellKind.COUPLING: "coupling-cell",
            CellKind.SECTIONING: "sectioning-cell",
            CellKind.OMNIBUS: "omnibus-cell",
            CellKind.INTERNAL: "internal-cell",
        }[cell.kind]
        objects[type_name].append(pddl_name(cell.id))

    init: list[str] = [
        "(= (total-cost) 0)",
        "(= (temporary-outages) 0)",
    ]

    max_out = problem.constraints.max_temporary_outages
    if problem.mode.value == "AGGRESSIVE" or max_out is None:
        max_out = max(1, len(problem.equipment))
    init.append(f"(= (max-temporary-outages) {max_out})")

    for switch in problem.switches:
        sid = pddl_name(switch.id)
        init.append(f"(endpoint-1 {sid} {pddl_name(switch.node1)})")
        init.append(f"(endpoint-2 {sid} {pddl_name(switch.node2)})")

        if initial.is_closed(problem, switch.id):
            init.append(f"(closed {sid})")
        if switch.fixed:
            init.append(f"(fixed {sid})")

        init.append(f"(requires-electrical-replay {sid})")

        if switch.kind in {SwitchKind.BREAKER, SwitchKind.LOAD_BREAK_SWITCH}:
            init.append(f"(requires-synchronism-check {sid})")

        if switch.role is SwitchRole.SECTIONING and switch.kind is SwitchKind.DISCONNECTOR:
            init.append(f"(sectioning-device {sid})")
            if not problem.constraints.enforce_sectioning_rule:
                init.append(f"(sectioning-authorized {sid})")

    for node1, node2 in problem.internal_connections:
        n1, n2 = pddl_name(node1), pddl_name(node2)
        init.extend(
            [
                f"(internal-link {n1} {n2})",
                f"(internal-link {n2} {n1})",
            ]
        )

    for busbar in problem.busbars:
        init.append(
            f"(busbar-at {pddl_name(busbar.id)} {pddl_name(busbar.node)})"
        )

    for equipment in problem.equipment:
        eid = pddl_name(equipment.id)
        for node in equipment.nodes:
            init.append(f"(equipment-at {eid} {pddl_name(node)})")

        if equipment.protected:
            init.append(f"(protected-equipment {eid})")
        if equipment.source:
            init.append(f"(source-equipment {eid})")
        if equipment.load:
            init.append(f"(load-equipment {eid})")

    initially_served = {
        item.id
        for item in problem.equipment
        if topology.equipment_in_service(initial, item.id)
    }

    for cell in problem.cells:
        cid = pddl_name(cell.id)

        for switch_id in cell.switch_ids:
            init.append(f"(in-cell {pddl_name(switch_id)} {cid})")

        for equipment_id in cell.equipment_ids:
            init.append(f"(contains-equipment {cid} {pddl_name(equipment_id)})")

        for switch_id in cell.switch_ids:
            switch = problem.switch_by_id[switch_id]
            if switch.kind is SwitchKind.BREAKER:
                init.append(f"(protects {pddl_name(switch_id)} {cid})")
            elif switch.kind is SwitchKind.LOAD_BREAK_SWITCH:
                init.append(f"(load-break-protects {pddl_name(switch_id)} {cid})")

        reached = topology.cell_busbars_reached(initial, cell)
        for busbar_id in reached:
            init.append(f"(cell-connected-to {cid} {pddl_name(busbar_id)})")

        breaker_closed = any(
            initial.is_closed(problem, sid)
            for sid in cell.breaker_ids
        )

        if breaker_closed and reached:
            init.append(f"(cell-in-service {cid})")
        if cell.breaker_ids and not breaker_closed:
            init.append(f"(cell-isolated {cid})")
        if len(reached) == 1:
            init.append(f"(cell-prepared {cid})")
        if len(reached) > 1:
            init.append(f"(double-connected {cid})")

        if (
            not problem.constraints.allow_protected_outage
            and any(
                problem.equipment_by_id[eid].protected
                for eid in cell.equipment_ids
            )
        ):
            init.append(f"(protected-cell {cid})")

        if cell.equipment_ids & initially_served:
            init.append(f"(tracks-temporary-outage {cid})")

        for disconnector_id in cell.disconnector_ids:
            switch = problem.switch_by_id[disconnector_id]
            for busbar in problem.busbars:
                if busbar.node in {switch.node1, switch.node2}:
                    init.append(
                        f"(disconnector-to-bar {pddl_name(disconnector_id)} "
                        f"{cid} {pddl_name(busbar.id)})"
                    )

    for switch in problem.switches:
        if switch.role is not SwitchRole.COUPLER:
            continue

        adjacent = [
            busbar.id
            for busbar in problem.busbars
            if busbar.node in {switch.node1, switch.node2}
        ]

        if len(adjacent) != 2:
            continue

        sid = pddl_name(switch.id)
        b1 = pddl_name(adjacent[0])
        b2 = pddl_name(adjacent[1])

        init.append(f"(couples {sid} {b1} {b2})")
        if initial.is_closed(problem, switch.id):
            init.extend(
                [
                    f"(bars-coupled {b1} {b2})",
                    f"(bars-coupled {b2} {b1})",
                ]
            )

    goals = [
        _literal_closed(
            pddl_name(switch.id),
            target.is_closed(problem, switch.id),
        )
        for switch in problem.switches
    ]

    object_lines = [
        f"    {' '.join(values)} - {type_name}"
        for type_name, values in objects.items()
        if values
    ]

    return "\n".join(
        [
            f"(define (problem {pddl_name(problem.name)})",
            "  (:domain node-breaker-detailed-planning)",
            "  (:objects",
            *object_lines,
            "  )",
            "  (:init",
            *[f"    {item}" for item in init],
            "  )",
            "  (:goal (and",
            *[f"    {goal}" for goal in goals],
            "  ))",
            "  (:metric minimize (total-cost))",
            ")",
            "",
        ]
    )


def export_pddl(problem: PlanningProblem, output_dir: str | Path) -> tuple[Path, Path]:
    """Export domain.pddl and the generated detailed-target problem.pddl."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    domain_output = output / "domain.pddl"
    problem_output = output / "problem.pddl"
    source_domain = Path(__file__).with_name("domain.pddl")

    if not source_domain.exists():
        raise FileNotFoundError(f"Domaine PDDL introuvable : {source_domain}")

    shutil.copyfile(source_domain, domain_output)
    problem_output.write_text(build_problem_text(problem), encoding="utf-8")

    return domain_output, problem_output


