from __future__ import annotations

import random
from pathlib import Path

import pypowsybl as pp

from planner.search import PlanningSession
from planner.xiidm import (
    apply_plan_to_network,
    problem_from_xiidm,
)


# ============================================================
# CONFIGURATION
# ============================================================

INITIAL = "data/CRENEP3_initial.xiidm"
VOLTAGE_LEVEL = "CRENEP3"
OUTPUT = "data/CRENEP3_target_30.xiidm"

COUNT = 30
SEED = 42
MAX_NODES = 100_000

# Si tu utilises un overlay :
OVERLAY = None

# Exemple :
# OVERLAY = "config/crenep3_overlay.json"


def find_distinct_valid_actions(
    problem,
    n_switches: int,
    seed: int,
    max_nodes: int,
):
    """
    Cherche une séquence de manoeuvres symboliquement valides
    portant sur des switchs tous distincts.

    L'état final diffère donc de l'état initial sur exactement
    n_switches switchs.
    """
    rng = random.Random(seed)

    session = PlanningSession(problem)
    initial_state = session.initial_state

    explored = 0

    def dfs(state, actions, used_switches):
        nonlocal explored

        if len(actions) == n_switches:
            return actions, state

        if explored >= max_nodes:
            return None

        explored += 1

        candidates = []

        for action, successor in session.applicable_actions(state):
            if action.switch_id in used_switches:
                continue

            candidates.append(
                (action, successor)
            )

        rng.shuffle(candidates)

        for action, successor in candidates:
            result = dfs(
                successor,
                actions + [action],
                used_switches | {action.switch_id},
            )

            if result is not None:
                return result

        return None

    result = dfs(
        initial_state,
        [],
        set(),
    )

    if result is None:
        raise RuntimeError(
            f"Impossible de construire une séquence de "
            f"{n_switches} manoeuvres distinctes après "
            f"{explored} états explorés."
        )

    actions, final_state = result

    return actions, final_state, explored


def main():
    initial_path = Path(INITIAL)
    output_path = Path(OUTPUT)

    if not initial_path.exists():
        raise FileNotFoundError(
            f"Fichier initial introuvable : {initial_path.resolve()}"
        )

    print("=" * 70)
    print("GÉNÉRATION D'UNE CIBLE À 30 SWITCHS MODIFIÉS")
    print("=" * 70)

    print()
    print(f"Réseau initial : {initial_path}")
    print(f"Voltage level  : {VOLTAGE_LEVEL}")
    print(f"Sortie         : {output_path}")
    print(f"Nombre voulu   : {COUNT}")
    print(f"Seed           : {SEED}")

    print()
    print("=" * 70)
    print("CONSTRUCTION DU PROBLÈME")
    print("=" * 70)

    # T0 est temporairement utilisé comme cible uniquement
    # pour construire le modèle topologique.
    problem = problem_from_xiidm(
        initial_path,
        initial_path,
        VOLTAGE_LEVEL,
        overlay=OVERLAY,
    )

    movable = [
        switch
        for switch in problem.switches
        if not switch.fixed
    ]

    print(
        f"Nombre total de switchs : "
        f"{len(problem.switches)}"
    )

    print(
        f"Switchs modifiables      : "
        f"{len(movable)}"
    )

    if COUNT > len(movable):
        raise ValueError(
            f"Il n'y a que {len(movable)} switchs modifiables, "
            f"donc impossible d'en modifier {COUNT}."
        )

    print()
    print("=" * 70)
    print("RECHERCHE D'UNE SÉQUENCE VALIDE")
    print("=" * 70)

    actions, final_state, explored = find_distinct_valid_actions(
        problem,
        n_switches=COUNT,
        seed=SEED,
        max_nodes=MAX_NODES,
    )

    print()
    print(
        f"Séquence trouvée après "
        f"{explored} états explorés."
    )

    print()
    print("=" * 70)
    print("MANŒUVRES UTILISÉES POUR CONSTRUIRE LA CIBLE")
    print("=" * 70)

    for i, action in enumerate(actions, start=1):
        switch = problem.switch_by_id[
            action.switch_id
        ]

        print(
            f"{i:02d}. "
            f"{action.operation.value:<5} "
            f"{action.switch_id} "
            f"[{switch.kind.value} / {switch.role.value}]"
        )

    initial_bits = tuple(
        switch.initial_closed
        for switch in problem.switches
    )

    final_bits = final_state.closed_bits

    changed = [
        switch.id
        for switch, initial, final in zip(
            problem.switches,
            initial_bits,
            final_bits,
            strict=True,
        )
        if initial != final
    ]

    print()
    print("=" * 70)
    print("VÉRIFICATION DE LA CIBLE")
    print("=" * 70)

    print(
        f"Nombre de switchs différents : "
        f"{len(changed)}"
    )

    print(
        f"Distance de Hamming : "
        f"{len(changed)}"
    )

    if len(changed) != COUNT:
        raise RuntimeError(
            f"La cible contient {len(changed)} modifications "
            f"au lieu de {COUNT}."
        )

    print()
    print("Switchs modifiés :")

    for switch_id in changed:
        switch = problem.switch_by_id[
            switch_id
        ]

        initial_closed = (
            switch.initial_closed
        )

        final_closed = (
            final_state.is_closed(
                problem,
                switch_id,
            )
        )

        initial_text = (
            "FERMÉ"
            if initial_closed
            else "OUVERT"
        )

        final_text = (
            "FERMÉ"
            if final_closed
            else "OUVERT"
        )

        print(
            f"  {switch_id}"
            f" : {initial_text}"
            f" -> {final_text}"
        )

    print()
    print("=" * 70)
    print("ÉCRITURE DU FICHIER XIIDM")
    print("=" * 70)

    network = pp.network.load(
        str(initial_path)
    )

    apply_plan_to_network(
        network,
        actions,
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    network.save(
        str(output_path),
        format="XIIDM",
    )

    print()
    print(
        f"Cible créée : "
        f"{output_path.resolve()}"
    )

    print()
    print("=" * 70)
    print("VÉRIFICATION DU XIIDM SAUVEGARDÉ")
    print("=" * 70)

    initial_network = pp.network.load(
        str(initial_path)
    )

    target_network = pp.network.load(
        str(output_path)
    )

    initial_topology = (
        initial_network
        .get_node_breaker_topology(
            VOLTAGE_LEVEL
        )
    )

    target_topology = (
        target_network
        .get_node_breaker_topology(
            VOLTAGE_LEVEL
        )
    )

    initial_switches = (
        initial_topology.switches
    )

    target_switches = (
        target_topology.switches
    )

    hamming = sum(
        bool(
            initial_switches.loc[
                sid,
                "open",
            ]
        )
        !=
        bool(
            target_switches.loc[
                sid,
                "open",
            ]
        )
        for sid in initial_switches.index
    )

    print(
        f"Distance de Hamming dans "
        f"les fichiers XIIDM : {hamming}"
    )

    if hamming != COUNT:
        raise RuntimeError(
            f"Erreur : le fichier final présente "
            f"{hamming} différences au lieu de {COUNT}."
        )

    print()
    print("=" * 70)
    print("SUCCÈS")
    print("=" * 70)

    print(
        f"La cible CRENEP3 diffère de T0 "
        f"sur exactement {COUNT} switchs."
    )

    print(
        f"Une séquence valide de "
        f"{len(actions)} manoeuvres est connue."
    )

    print()
    print(
        f"Fichier cible : "
        f"{output_path.resolve()}"
    )


if __name__ == "__main__":
    main()

