from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from pddl.generator import export_pddl
from planner.electrical import ElectricalValidationConfig, validate_sequence_electrically
from planner.io import electrical_report_to_dict, search_result_to_dict, write_problem
from planner.search import astar_search
from planner.xiidm import problem_from_networks, require_pypowsybl


VOLTAGE_LEVEL_ID = "S1VL2"
OLD_DISCONNECTOR = "S1VL2_BBS1_TWT_DISCONNECTOR"
NEW_DISCONNECTOR = "S1VL2_BBS2_TWT_DISCONNECTOR"
FEEDER_BREAKER = "S1VL2_TWT_BREAKER"


def build_demo(output_dir: str | Path = "generated/four_substations") -> dict:
    """Create a real Node-Breaker example without a hand-written problem JSON."""
    pp = require_pypowsybl()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    initial = pp.network.create_four_substations_node_breaker_network()
    target = pp.network.create_four_substations_node_breaker_network()
    available = set(initial.get_switches().index)
    required = {OLD_DISCONNECTOR, NEW_DISCONNECTOR, FEEDER_BREAKER}
    missing = required - available
    if missing:
        raise RuntimeError(f"La version PyPowSyBl ne contient pas les switches attendus : {sorted(missing)}")

    # Transfer the transformer bay from BBS1 to BBS2. The breaker keeps its
    # target state; A* may use it temporarily if the short-loop path is absent.
    target.update_switches(
        id=[OLD_DISCONNECTOR, NEW_DISCONNECTOR],
        open=[True, False],
    )
    overlay = {
        "name": "four_substations_S1VL2_TWT_transfer",
        "mode": "SMOOTH",
        "movable_switches": [OLD_DISCONNECTOR, NEW_DISCONNECTOR, FEEDER_BREAKER],
        "protected_equipment": [],
        "constraints": {
            "allow_protected_outage": False,
            "allow_unsafe_multi_busbar": False,
            "max_temporary_outages": 1,
            "enforce_disconnector_offload_rule": True,
            "enforce_sectioning_rule": True,
            "strict_sectioning_without_sources": False,
        },
        "busbars": {
            "S1VL2_BBS1": {"group": "B1", "section": "S1"},
            "S1VL2_BBS2": {"group": "B2", "section": "S1"},
        },
    }
    problem = problem_from_networks(
        initial,
        target,
        VOLTAGE_LEVEL_ID,
        overlay=overlay,
    )
    result = astar_search(problem, heuristic="hamming")

    initial_path = output / "initial_four_substations.xiidm"
    target_path = output / "target_four_substations.xiidm"
    initial.save(initial_path, format="XIIDM")
    target.save(target_path, format="XIIDM")
    write_problem(output / "extracted_problem.json", problem)
    (output / "plan.json").write_text(
        json.dumps(search_result_to_dict(problem, result), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    export_pddl(problem, output / "pddl")

    electrical = None
    if result.found:
        electrical = validate_sequence_electrically(
            initial,
            problem,
            result.actions,
            ElectricalValidationConfig(expected_step_duration_s=30),
        )
        (output / "electrical_report.json").write_text(
            json.dumps(electrical_report_to_dict(electrical), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return {
        "output_dir": str(output),
        "plan_found": result.found,
        "total_cost": result.total_cost,
        "actions": [str(action) for action in result.actions],
        "electrically_valid": electrical.valid if electrical is not None else None,
        "cache_statistics": asdict(result.cache_statistics),
    }


if __name__ == "__main__":
    print(json.dumps(build_demo(), indent=2, ensure_ascii=False))
