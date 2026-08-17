from collections import Counter

from planner.xiidm import problem_from_xiidm
from planner.model import CellKind, SwitchRole


# ============================================================
# PARAMETRES
# ============================================================

INITIAL = "data/initial.xiidm"

# On peut utiliser le même fichier comme cible :
# ici on veut uniquement tester l'extraction structurelle.
TARGET = "data/initial.xiidm"

VOLTAGE_LEVEL_ID = "COULAP7"


# ============================================================
# CREATION DU PROBLEME
# ============================================================

problem = problem_from_xiidm(
    INITIAL,
    TARGET,
    VOLTAGE_LEVEL_ID,
)


# ============================================================
# INFORMATIONS GENERALES
# ============================================================

print()
print("=" * 100)
print("DIAGNOSTIC STRUCTUREL NODE-BREAKER")
print("=" * 100)

print(f"Voltage Level : {VOLTAGE_LEVEL_ID}")
print(f"Busbars       : {len(problem.busbars)}")
print(f"Switches      : {len(problem.switches)}")
print(f"Equipements   : {len(problem.equipment)}")
print(f"Cellules      : {len(problem.cells)}")


# ============================================================
# BUSBAR SECTIONS
# ============================================================

print()
print("=" * 100)
print("BUSBAR SECTIONS DETECTEES")
print("=" * 100)

for busbar in problem.busbars:
    print(
        f"id={busbar.id} | "
        f"node={busbar.node} | "
        f"group={busbar.group} | "
        f"section={busbar.section}"
    )


# ============================================================
# STATISTIQUES SUR LES CELLULES
# ============================================================

print()
print("=" * 100)
print("TYPES DE CELLULES")
print("=" * 100)

cell_counts = Counter(
    cell.kind.value
    for cell in problem.cells
)

for kind, count in sorted(cell_counts.items()):
    print(f"{kind:20s} : {count}")


# ============================================================
# DETAIL DES CELLULES
# ============================================================

print()
print("=" * 100)
print("DETAIL DES CELLULES")
print("=" * 100)

for cell in problem.cells:

    print()
    print("-" * 100)

    print(
        f"CELLULE : {cell.id}"
    )

    print(
        f"TYPE    : {cell.kind.value}"
    )

    print(
        f"Busbars : {list(cell.busbar_ids)}"
    )

    print(
        f"Switches: {list(cell.switch_ids)}"
    )

    print(
        f"Breakers: {list(cell.breaker_ids)}"
    )

    print(
        f"Disconnectors: {list(cell.disconnector_ids)}"
    )

    print(
        f"Equipements: {list(cell.equipment_ids)}"
    )


# ============================================================
# CELLULES DE DEPART
# ============================================================

print()
print("=" * 100)
print("CELLULES DE DEPART DETECTEES")
print("=" * 100)

departure_cells = [
    cell
    for cell in problem.cells
    if cell.kind is CellKind.DEPARTURE
]

print(
    f"Nombre de départs détectés : "
    f"{len(departure_cells)}"
)

for cell in departure_cells:

    print()
    print(f"DEPART : {cell.id}")

    print(
        f"  Busbars       : "
        f"{list(cell.busbar_ids)}"
    )

    print(
        f"  Breakers      : "
        f"{list(cell.breaker_ids)}"
    )

    print(
        f"  Sectionneurs  : "
        f"{list(cell.disconnector_ids)}"
    )

    print(
        f"  Equipements   : "
        f"{list(cell.equipment_ids)}"
    )


# ============================================================
# CELLULES DE COUPLAGE
# ============================================================

print()
print("=" * 100)
print("CELLULES DE COUPLAGE DETECTEES")
print("=" * 100)

coupling_cells = [
    cell
    for cell in problem.cells
    if cell.kind is CellKind.COUPLING
]

print(
    f"Nombre de cellules de couplage : "
    f"{len(coupling_cells)}"
)

for cell in coupling_cells:

    print()
    print(f"COUPLAGE : {cell.id}")

    print(
        f"  Busbars      : "
        f"{list(cell.busbar_ids)}"
    )

    print(
        f"  Breakers     : "
        f"{list(cell.breaker_ids)}"
    )

    print(
        f"  Sectionneurs : "
        f"{list(cell.disconnector_ids)}"
    )

    print(
        f"  Tous switches: "
        f"{list(cell.switch_ids)}"
    )


# ============================================================
# CELLULES DE SECTIONNEMENT
# ============================================================

print()
print("=" * 100)
print("CELLULES DE SECTIONNEMENT DETECTEES")
print("=" * 100)

sectioning_cells = [
    cell
    for cell in problem.cells
    if cell.kind is CellKind.SECTIONING
]

print(
    f"Nombre de cellules de sectionnement : "
    f"{len(sectioning_cells)}"
)

for cell in sectioning_cells:

    print()
    print(f"SECTIONNEMENT : {cell.id}")

    print(
        f"  Busbars      : "
        f"{list(cell.busbar_ids)}"
    )

    print(
        f"  Breakers     : "
        f"{list(cell.breaker_ids)}"
    )

    print(
        f"  Sectionneurs : "
        f"{list(cell.disconnector_ids)}"
    )

    print(
        f"  Tous switches: "
        f"{list(cell.switch_ids)}"
    )


# ============================================================
# ROLES DES SWITCHES
# ============================================================

print()
print("=" * 100)
print("ROLES DES SWITCHES")
print("=" * 100)

role_counts = Counter(
    switch.role.value
    for switch in problem.switches
)

for role, count in sorted(role_counts.items()):
    print(
        f"{role:25s} : {count}"
    )


# ============================================================
# COUPLEURS
# ============================================================

print()
print("=" * 100)
print("SWITCHES IDENTIFIES COMME COUPLEURS")
print("=" * 100)

couplers = [
    switch
    for switch in problem.switches
    if switch.role is SwitchRole.COUPLER
]

for switch in couplers:

    print(
        f"{switch.id}"
    )

    print(
        f"  kind  = {switch.kind.value}"
    )

    print(
        f"  nodes = "
        f"{switch.node1} -- {switch.node2}"
    )

    print(
        f"  initial_closed = "
        f"{switch.initial_closed}"
    )


# ============================================================
# SECTIONNEMENT
# ============================================================

print()
print("=" * 100)
print("SWITCHES IDENTIFIES COMME SECTIONNEMENT")
print("=" * 100)

sectioning_switches = [
    switch
    for switch in problem.switches
    if switch.role is SwitchRole.SECTIONING
]

for switch in sectioning_switches:

    print(
        f"{switch.id}"
    )

    print(
        f"  kind  = {switch.kind.value}"
    )

    print(
        f"  nodes = "
        f"{switch.node1} -- {switch.node2}"
    )


# ============================================================
# SWITCHES NON CLASSIFIES / OTHER
# ============================================================

print()
print("=" * 100)
print("SWITCHES AVEC ROLE OTHER")
print("=" * 100)

others = [
    switch
    for switch in problem.switches
    if switch.role is SwitchRole.OTHER
]

print(
    f"Nombre : {len(others)}"
)

for switch in others:

    print(
        f"{switch.id} | "
        f"{switch.kind.value} | "
        f"{switch.node1} -- {switch.node2}"
    )


print()
print("=" * 100)
print("FIN DU DIAGNOSTIC")
print("=" * 100)
