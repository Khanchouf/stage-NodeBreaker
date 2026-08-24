from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from pddl.generator import export_pddl
from planner.electrical import ElectricalValidationConfig, validate_sequence_electrically
from planner.io import electrical_report_to_dict, search_result_to_dict, write_problem
from planner.model import NetworkState
from planner.partition import NodalPartition
from planner.projection import NodeBreakerProjection
from planner.search import (
    PlanningSession,
    astar_over_antecedents,
    astar_search,
    expert_heuristic_details,
)
from planner.topology import TopologyEngine
from planner.verification import verify_plan
from planner.xiidm import problem_from_xiidm, save_planned_network


HEURISTIC_CHOICES = ["zero", "hamming", "expert", "topological", "combined"]


def _problem_from_args(args):
    return problem_from_xiidm(
        args.initial,
        args.target,
        args.voltage_level,
        overlay=args.overlay,
    )


def _electrical_config_from_args(args) -> ElectricalValidationConfig:
    return ElectricalValidationConfig(
        provider=args.provider,
        expected_step_duration_s=args.step_duration,
        max_closing_voltage_difference_kv=args.max_delta_v,
        max_closing_angle_difference_deg=args.max_delta_angle,
    )


def _write_or_print_payload(payload: dict, output: str | None) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if output:
        Path(output).write_text(text, encoding="utf-8")
    print(text)


def cmd_plan(args) -> int:
    """Original v3 detailed-target planning mode, kept for comparison."""

    total_start = perf_counter()

    problem_start = perf_counter()
    problem = _problem_from_args(args)
    problem_time = perf_counter() - problem_start

    session_start = perf_counter()
    session = PlanningSession(problem)
    session_time = perf_counter() - session_start

    search_start = perf_counter()
    result = astar_search(
        problem,
        heuristic=args.heuristic,
        max_expansions=args.max_expansions,
        session=session,
    )
    search_time = perf_counter() - search_start

    initial_details = expert_heuristic_details(
        session.initial_state,
        problem,
        session.topology,
    )

    payload = search_result_to_dict(problem, result)
    payload["heuristic"] = {
        "selected": args.heuristic,
        "initial_value": session.heuristic(args.heuristic, session.initial_state),
        "initial_hamming": initial_details["hamming"],
        "initial_expert": initial_details["expert"],
        "expert_initial_breakdown": initial_details,
        "statistics": session.heuristic_statistics(),
    }
    payload["performance"] = {
        "problem_construction_time_seconds": problem_time,
        "planning_session_setup_time_seconds": session_time,
        "search_time_seconds": search_time,
        "planner_time_seconds": session_time + search_time,
        "elapsed_until_plan_seconds": perf_counter() - total_start,
    }

    _write_or_print_payload(payload, args.output)

    print("\n" + "=" * 72)
    print("PERFORMANCES")
    print("=" * 72)
    print(f"Construction problème : {problem_time:.6f} s")
    print(f"Initialisation session : {session_time:.6f} s")
    print(f"Recherche A*           : {search_time:.6f} s")
    print(f"Planner (session+A*)   : {session_time + search_time:.6f} s")
    print("=" * 72)
    print(
        f"Heuristique T0         : Hamming={initial_details['hamming']} | "
        f"Expert={initial_details['expert']}"
    )
    if args.heuristic == "expert":
        stats = session.heuristic_statistics()
        print(
            "Expert évalué          : "
            f"{stats['expert_evaluations']} états, "
            f"plus fort que Hamming sur {stats['expert_stronger_than_hamming']} états"
        )
    print("=" * 72)

    if not result.found:
        return 2

    verify_start = perf_counter()
    symbolic = verify_plan(problem, result.actions)
    verify_time = perf_counter() - verify_start
    print(f"Vérification symbolique: {verify_time:.6f} s")

    if not symbolic.valid:
        print("Le rejeu symbolique indépendant a échoué.")
        return 3

    if args.problem_json:
        write_problem(args.problem_json, problem)
    if args.pddl_dir:
        export_pddl(problem, args.pddl_dir)
    if args.planned_network:
        save_planned_network(args.initial, result.actions, args.planned_network)

    if args.electrical:
        electrical_start = perf_counter()
        electrical = validate_sequence_electrically(
            args.initial,
            problem,
            result.actions,
            _electrical_config_from_args(args),
        )
        electrical_time = perf_counter() - electrical_start
        electrical_payload = electrical_report_to_dict(electrical)
        electrical_payload["performance"] = {
            "electrical_validation_time_seconds": electrical_time,
        }
        electrical_text = json.dumps(electrical_payload, indent=2, ensure_ascii=False)
        if args.electrical_output:
            Path(args.electrical_output).write_text(electrical_text, encoding="utf-8")
        print(electrical_text)
        print(f"Validation électrique  : {electrical_time:.6f} s")
        if not electrical.valid:
            return 4

    print(f"Temps total commande   : {perf_counter() - total_start:.6f} s")
    return 0


def _build_nodal_base_problem_and_target(args):
    """Build the static Node/Breaker problem and the nodal target T*.

    ``args.target`` may be either:
      * a XIIDM network: its detailed switch state is projected once to obtain
        T*, then forgotten as a unique detailed goal;
      * a JSON nodal partition: the initial XIIDM is used on both sides only to
        construct the static Node/Breaker graph, and T* is read from JSON.
    """

    target_path = Path(args.target)
    if target_path.suffix.lower() == ".json":
        problem = problem_from_xiidm(
            args.initial,
            args.initial,
            args.voltage_level,
            overlay=args.overlay,
        )
        target_partition = NodalPartition.load(target_path)
    else:
        # Build the planning model from T0 alone so that a detailed switch
        # position present in the XIIDM target is never imposed as the final
        # detailed goal.  In particular, an overlay may legitimately declare a
        # switch fixed even when the supplied target XIIDM happens to place it
        # differently: only the nodal topology of that XIIDM matters here.
        problem = problem_from_xiidm(
            args.initial,
            args.initial,
            args.voltage_level,
            overlay=args.overlay,
        )
        target_extraction_problem = problem_from_xiidm(
            args.initial,
            args.target,
            args.voltage_level,
            overlay=None,
        )
        target_projection = NodeBreakerProjection(
            target_extraction_problem,
            TopologyEngine(target_extraction_problem),
        )
        target_partition = target_projection.detailed_target_partition()

    return problem, target_partition


def _antecedent_summary_to_dict(problem, item) -> dict[str, object]:
    return {
        "target_switch_states": item.target_state.as_dict(problem),
        "found": item.found,
        "total_cost": item.total_cost,
        "expanded_states": item.expanded_states,
        "generated_states": item.generated_states,
        "reopened_states": item.reopened_states,
        "message": item.message,
    }


def cmd_plan_nodal(args) -> int:
    """New formulation: enumerate π^{-1}(T*) and run detailed A* on each goal."""

    total_start = perf_counter()

    problem_start = perf_counter()
    base_problem, target_partition = _build_nodal_base_problem_and_target(args)
    problem_time = perf_counter() - problem_start

    if args.write_target_partition:
        target_partition.save(args.write_target_partition)

    search_start = perf_counter()
    nodal_result = astar_over_antecedents(
        base_problem,
        target_partition,
        heuristic=args.heuristic,
        max_expansions=args.max_expansions,
        max_assignments=args.max_assignments,
    )
    search_time = perf_counter() - search_start

    payload: dict[str, object] = {
        "problem": base_problem.name,
        "goal": "NODAL",
        "target_partition": target_partition.to_dict(),
        "found": nodal_result.found,
        "message": nodal_result.message,
        "exact_global_optimum_guaranteed": nodal_result.exact_global_optimum_guaranteed,
        "antecedent_generation": {
            "assignments_checked": nodal_result.antecedents.assignments_checked,
            "projection_matches": nodal_result.antecedents.projection_matches,
            "invalid_projection_matches": nodal_result.antecedents.invalid_projection_matches,
            "admissible_antecedents": nodal_result.antecedents.count,
            "truncated": nodal_result.antecedents.truncated,
        },
        "search_totals": {
            "attempted_antecedents": nodal_result.attempted_antecedents,
            "solved_antecedents": nodal_result.solved_antecedents,
            "expanded_states": nodal_result.total_expanded_states,
            "generated_states": nodal_result.total_generated_states,
            "reopened_states": nodal_result.total_reopened_states,
        },
        "heuristic": args.heuristic,
        "performance": {
            "problem_and_target_construction_time_seconds": problem_time,
            "antecedent_generation_and_all_astar_time_seconds": search_time,
            "elapsed_until_plan_seconds": perf_counter() - total_start,
        },
    }

    if args.include_antecedent_details:
        payload["antecedents"] = [
            _antecedent_summary_to_dict(base_problem, item)
            for item in nodal_result.summaries
        ]

    if nodal_result.best_result is not None and nodal_result.best_problem is not None:
        best_payload = search_result_to_dict(
            nodal_result.best_problem,
            nodal_result.best_result,
        )
        best_payload["goal"] = "SELECTED_DETAILED_ANTECEDENT"
        payload["best_solution"] = best_payload
        payload["best_detailed_target"] = (
            nodal_result.best_target_state.as_dict(nodal_result.best_problem)
            if nodal_result.best_target_state is not None
            else None
        )

        best_session = PlanningSession(nodal_result.best_problem)
        best_details = expert_heuristic_details(
            best_session.initial_state,
            nodal_result.best_problem,
            best_session.topology,
        )
        payload["best_target_initial_heuristics"] = {
            "hamming": best_details["hamming"],
            "expert": best_details["expert"],
            "topological": best_session.heuristic(
                "topological", best_session.initial_state
            ),
            "combined": best_session.heuristic("combined", best_session.initial_state),
        }

    _write_or_print_payload(payload, args.output)

    print("\n" + "=" * 72)
    print("PLANIFICATION VERS CIBLE NODALE")
    print("=" * 72)
    print(f"Affectations testées    : {nodal_result.antecedents.assignments_checked}")
    print(f"Antécédents nodaux      : {nodal_result.antecedents.projection_matches}")
    print(f"Antécédents admissibles : {nodal_result.antecedents.count}")
    print(f"A* exécutés             : {nodal_result.attempted_antecedents}")
    print(f"A* avec solution        : {nodal_result.solved_antecedents}")
    print(f"Temps total recherche   : {search_time:.6f} s")
    if nodal_result.best_result is not None:
        print(f"Coût optimal retenu     : {nodal_result.best_result.total_cost}")
    print(
        "Optimalité globale      : "
        + ("GARANTIE" if nodal_result.exact_global_optimum_guaranteed else "NON GARANTIE")
    )
    print("=" * 72)

    if not nodal_result.found or nodal_result.best_result is None or nodal_result.best_problem is None:
        return 2

    best_problem = nodal_result.best_problem
    best_result = nodal_result.best_result

    # Independent replay against the selected detailed antecedent.  Since that
    # antecedent projects to T*, this also verifies the nodal goal.
    verify_start = perf_counter()
    symbolic = verify_plan(best_problem, best_result.actions)
    verify_time = perf_counter() - verify_start
    print(f"Vérification symbolique: {verify_time:.6f} s")
    if not symbolic.valid:
        print("Le rejeu symbolique indépendant a échoué.")
        return 3

    final_partition = NodeBreakerProjection(best_problem).project(best_result.states[-1])
    if final_partition != target_partition:
        print("ERREUR : l'état final détaillé ne réalise pas la topologie nodale cible.")
        return 3

    if args.problem_json:
        # The exported problem is the selected detailed antecedent problem used
        # by the winning A* run.  The nodal target remains available in --output.
        write_problem(args.problem_json, best_problem)
    if args.pddl_dir:
        # PDDL remains a detailed-target formulation: export the selected
        # antecedent, not the abstract nodal goal.
        export_pddl(best_problem, args.pddl_dir)
    if args.planned_network:
        save_planned_network(args.initial, best_result.actions, args.planned_network)

    if args.electrical:
        electrical_start = perf_counter()
        electrical = validate_sequence_electrically(
            args.initial,
            best_problem,
            best_result.actions,
            _electrical_config_from_args(args),
        )
        electrical_time = perf_counter() - electrical_start
        electrical_payload = electrical_report_to_dict(electrical)
        electrical_payload["performance"] = {
            "electrical_validation_time_seconds": electrical_time,
        }
        electrical_text = json.dumps(electrical_payload, indent=2, ensure_ascii=False)
        if args.electrical_output:
            Path(args.electrical_output).write_text(electrical_text, encoding="utf-8")
        print(electrical_text)
        print(f"Validation électrique  : {electrical_time:.6f} s")
        if not electrical.valid:
            return 4

    print(f"Temps total commande   : {perf_counter() - total_start:.6f} s")
    return 0


def cmd_pddl(args) -> int:
    problem = _problem_from_args(args)
    domain, instance = export_pddl(problem, args.output_dir)
    print(domain)
    print(instance)
    return 0


def cmd_demo(args) -> int:
    from examples.four_substations_demo import build_demo

    print(json.dumps(build_demo(args.output_dir), indent=2, ensure_ascii=False))
    return 0


def _add_common_planning_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--overlay")
    parser.add_argument(
        "--heuristic",
        choices=HEURISTIC_CHOICES,
        default="hamming",
    )
    parser.add_argument("--max-expansions", type=int)
    parser.add_argument("--output")
    parser.add_argument("--problem-json")
    parser.add_argument("--pddl-dir")
    parser.add_argument("--planned-network")
    parser.add_argument("--electrical", action="store_true")
    parser.add_argument("--electrical-output")
    parser.add_argument("--provider", default="")
    parser.add_argument("--step-duration", type=int, default=30)
    parser.add_argument("--max-delta-v", type=float)
    parser.add_argument("--max-delta-angle", type=float)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Planificateur A* Node-Breaker : cible détaillée historique ou "
            "cible nodale résolue par énumération des antécédents."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Mode historique : cible XIIDM détaillée")
    plan.add_argument("initial")
    plan.add_argument("target")
    plan.add_argument("voltage_level")
    _add_common_planning_options(plan)
    plan.set_defaults(func=cmd_plan)

    nodal = sub.add_parser(
        "plan-nodal",
        help=(
            "Cible nodale : calcule pi^-1(T*) puis exécute A* vers chacun des "
            "antécédents admissibles"
        ),
    )
    nodal.add_argument("initial")
    nodal.add_argument(
        "target",
        help=(
            "XIIDM dont seule la topologie nodale est utilisée, ou JSON contenant "
            "directement les blocs de T*"
        ),
    )
    nodal.add_argument("voltage_level")
    _add_common_planning_options(nodal)
    nodal.set_defaults(heuristic="expert")
    nodal.add_argument(
        "--max-assignments",
        type=int,
        help=(
            "Limiter volontairement l'énumération des états détaillés. Sans cette "
            "option, toute la fibre est recherchée exactement."
        ),
    )
    nodal.add_argument(
        "--write-target-partition",
        help="Écrire T* au format JSON (utile pour réutiliser ensuite une cible nodale pure).",
    )
    nodal.add_argument(
        "--include-antecedent-details",
        action="store_true",
        help="Inclure les statistiques de chaque A* dans le JSON de sortie.",
    )
    nodal.set_defaults(func=cmd_plan_nodal)

    pddl = sub.add_parser("pddl", help="Exporter le domaine et le problème PDDL détaillé")
    pddl.add_argument("initial")
    pddl.add_argument("target")
    pddl.add_argument("voltage_level")
    pddl.add_argument("output_dir")
    pddl.add_argument("--overlay")
    pddl.set_defaults(func=cmd_pddl)

    demo = sub.add_parser("demo-four-substations", help="Créer et tester le cas PyPowSyBl réel")
    demo.add_argument("--output-dir", default="generated/four_substations")
    demo.set_defaults(func=cmd_demo)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
