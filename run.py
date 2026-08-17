from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from pddl.generator import export_pddl
from planner.electrical import ElectricalValidationConfig, validate_sequence_electrically
from planner.io import electrical_report_to_dict, search_result_to_dict, write_problem
from planner.search import PlanningSession, astar_search, expert_heuristic_details
from planner.verification import verify_plan
from planner.xiidm import problem_from_xiidm, save_planned_network


def _problem_from_args(args):
    return problem_from_xiidm(
        args.initial,
        args.target,
        args.voltage_level,
        overlay=args.overlay,
    )


def cmd_plan(args) -> int:
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

    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)

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
            ElectricalValidationConfig(
                provider=args.provider,
                expected_step_duration_s=args.step_duration,
                max_closing_voltage_difference_kv=args.max_delta_v,
                max_closing_angle_difference_deg=args.max_delta_angle,
            ),
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="A* Node-Breaker détaillé avec validation PyPowSyBl"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Planifier depuis deux réseaux XIIDM")
    plan.add_argument("initial")
    plan.add_argument("target")
    plan.add_argument("voltage_level")
    plan.add_argument("--overlay")
    plan.add_argument(
        "--heuristic",
        choices=["zero", "hamming", "expert"],
        default="hamming",
    )
    plan.add_argument("--max-expansions", type=int)
    plan.add_argument("--output")
    plan.add_argument("--problem-json")
    plan.add_argument("--pddl-dir")
    plan.add_argument("--planned-network")
    plan.add_argument("--electrical", action="store_true")
    plan.add_argument("--electrical-output")
    plan.add_argument("--provider", default="")
    plan.add_argument("--step-duration", type=int, default=30)
    plan.add_argument("--max-delta-v", type=float)
    plan.add_argument("--max-delta-angle", type=float)
    plan.set_defaults(func=cmd_plan)

    pddl = sub.add_parser("pddl", help="Exporter le domaine et le problème PDDL")
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
