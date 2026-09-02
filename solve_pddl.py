from unified_planning.io import PDDLReader
from unified_planning.shortcuts import get_environment
from up_enhsp.enhsp_planner import ENHSPEngine

get_environment().credits_stream = None

reader = PDDLReader()

problem = reader.parse_problem(
    "CRENEP3_PDDL/domain.pddl",
    "CRENEP3_PDDL/problem.pddl",
)

print("=" * 70)
print("PROBLEM LOADED")
print("=" * 70)
print(problem.kind)

# On utilise directement ENHSP, sans passer par OneshotPlanner.
# Ce sont les paramètres exacts de la variante BLIND-enhsp.
planner = ENHSPEngine(
    params="-s WAStar -h blind -ties larger_g"
)

result = planner.solve(problem)

print()
print("=" * 70)
print("RESULT")
print("=" * 70)

print("Status:", result.status)
print("Plan:", result.plan)

print()
print("=" * 70)
print("ENHSP LOGS")
print("=" * 70)

if result.log_messages:
    for message in result.log_messages:
        print(f"[{message.level}]")
        print(message.message)
else:
    print("Aucun log.")

