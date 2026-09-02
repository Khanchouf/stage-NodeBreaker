from pathlib import Path
import pypowsybl as pp


# ============================================================
# PARAMETRES
# ============================================================

SOURCE_FILE = Path("data/réseau.arc")

INITIAL_FILE = Path("data/CRENEP3_initial.xiidm")
TARGET_FILE = Path("data/CRENEP3_target_chaotic.xiidm")

VOLTAGE_LEVEL_ID = "CRENEP3"


# ============================================================
# SCENARIO CHAOTIQUE CONTROLE
# ============================================================
#
# On transfère plusieurs départs entre les deux barres.
#
# IMPORTANT :
#   open=True  -> switch OUVERT
#   open=False -> switch FERME
#
# Les disjoncteurs ne sont PAS modifiés dans l'état final.
# A* devra déterminer les manœuvres intermédiaires nécessaires.
#
# ------------------------------------------------------------
# 1) T.IND.1
#    Initial : SA.1 fermé / SA.2 ouvert
#    Cible   : SA.1 ouvert / SA.2 fermé
#
# 2) ARCIS.2
#    Initial : SA.1 fermé / SA.2 ouvert
#    Cible   : SA.1 ouvert / SA.2 fermé
#
# 3) TRO.E.1
#    Initial : SA.1 fermé / SA.2 ouvert
#    Cible   : SA.1 ouvert / SA.2 fermé
#
# 4) AVREU.1
#    Initial : SA.1 ouvert / SA.2 fermé
#    Cible   : SA.1 fermé / SA.2 ouvert
#
# 5) H.CLO.1
#    Initial : SA.1 fermé / SA.2 ouvert
#    Cible   : SA.1 ouvert / SA.2 fermé
#
# ============================================================


TARGET_SWITCH_STATES = {

    # --------------------------------------------------------
    # T.IND.1 : barre 1 -> barre 2
    # --------------------------------------------------------
    "CRENEP3_CRENE   3T.IND.1  SA.1": True,
    "CRENEP3_CRENE   3T.IND.1  SA.2": False,

    # --------------------------------------------------------
    # ARCIS.2 : barre 1 -> barre 2
    # --------------------------------------------------------
    "CRENEP3_CRENE   3ARCIS.2  SA.1": True,
    "CRENEP3_CRENE   3ARCIS.2  SA.2": False,

    # --------------------------------------------------------
    # TRO.E.1 : barre 1 -> barre 2
    # --------------------------------------------------------
    "CRENEP3_CRENE   3TRO.E.1  SA.1": True,
    "CRENEP3_CRENE   3TRO.E.1  SA.2": False,

    # --------------------------------------------------------
    # AVREU.1 : barre 2 -> barre 1
    # --------------------------------------------------------
    "CRENEP3_CRENE   3AVREU.1  SA.1": False,
    "CRENEP3_CRENE   3AVREU.1  SA.2": True,

    # --------------------------------------------------------
    # H.CLO.1 : barre 1 -> barre 2
    # --------------------------------------------------------
    "CRENEP3_CRENE   3H.CLO.1  SA.1": True,
    "CRENEP3_CRENE   3H.CLO.1  SA.2": False,
}


# ============================================================
# SAUVEGARDE XIIDM
# ============================================================

def save_xiidm(network, path: Path) -> None:

    xml = network.save_to_string("XIIDM")

    if not xml:
        raise RuntimeError(
            f"La sérialisation XIIDM de {path} a produit une chaîne vide."
        )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        xml,
        encoding="utf-8",
    )

    print(f"Fichier sauvegardé : {path}")
    print(f"Taille XML         : {len(xml):,} caractères")


# ============================================================
# INFORMATIONS DU VOLTAGE LEVEL
# ============================================================

def print_voltage_level_info(
    network,
    voltage_level_id: str,
    label: str,
) -> None:

    voltage_levels = network.get_voltage_levels()

    if voltage_level_id not in voltage_levels.index:
        raise ValueError(
            f"VoltageLevel {voltage_level_id!r} absent du réseau {label}."
        )

    row = voltage_levels.loc[voltage_level_id]

    print()
    print(label)
    print("-" * 70)
    print(f"VoltageLevel      : {voltage_level_id}")

    if "nominal_v" in row.index:
        print(f"Tension nominale  : {row['nominal_v']} kV")

    try:
        topology = network.get_node_breaker_topology(
            voltage_level_id
        )

        print("Topologie         : NODE_BREAKER")
        print(f"Nombre de nœuds   : {len(topology.nodes)}")
        print(f"Nombre de switches: {len(topology.switches)}")

    except Exception as exc:
        raise RuntimeError(
            f"Impossible d'obtenir la topologie Node-Breaker "
            f"de {voltage_level_id}: {exc}"
        ) from exc


# ============================================================
# VERIFICATION DES SWITCHES
# ============================================================

def check_switch_exists(
    network,
    switch_id: str,
) -> None:

    switches = network.get_switches()

    if switch_id not in switches.index:

        print()
        print("Switch introuvable :")
        print(repr(switch_id))

        # On essaie d'afficher quelques identifiants proches
        token = switch_id.split("  SA.")[0].split("_")[-1]

        print()
        print("Switches potentiellement correspondants :")

        found = False

        for sid in switches.index:
            if token.strip() in sid:
                print("  ", repr(sid))
                found = True

        if not found:
            print("  Aucun identifiant proche trouvé.")

        raise KeyError(
            f"Switch absent : {switch_id}"
        )


def get_switch_open_state(
    network,
    switch_id: str,
) -> bool:

    switches = network.get_switches()

    return bool(
        switches.loc[
            switch_id,
            "open",
        ]
    )


def print_switch_state(
    network,
    switch_id: str,
    prefix: str = "",
) -> None:

    state = get_switch_open_state(
        network,
        switch_id,
    )

    human_state = (
        "OUVERT"
        if state
        else "FERME"
    )

    print(f"{prefix}{switch_id}")
    print(
        f"{prefix}    open={state} -> {human_state}"
    )


# ============================================================
# 1. CHARGEMENT DU RESEAU SOURCE
# ============================================================

print()
print("=" * 80)
print("1. CHARGEMENT DU RESEAU SOURCE")
print("=" * 80)

if not SOURCE_FILE.exists():
    raise FileNotFoundError(
        f"Fichier source introuvable : {SOURCE_FILE}"
    )

initial_network = pp.network.load(
    SOURCE_FILE
)

print(
    f"Réseau chargé depuis : {SOURCE_FILE}"
)

print_voltage_level_info(
    initial_network,
    VOLTAGE_LEVEL_ID,
    "RESEAU SOURCE",
)


# ============================================================
# 2. CREATION DE INITIAL.XIIDM
# ============================================================

print()
print("=" * 80)
print("2. CREATION DE INITIAL.XIIDM")
print("=" * 80)

save_xiidm(
    initial_network,
    INITIAL_FILE,
)


# ============================================================
# 3. CREATION INDEPENDANTE DU RESEAU CIBLE
# ============================================================

print()
print("=" * 80)
print("3. CREATION DU RESEAU CIBLE")
print("=" * 80)

# On recharge la source afin que initial et target
# soient construits indépendamment à partir du même réseau.
target_network = pp.network.load(
    SOURCE_FILE
)

print(
    "Le réseau source a été rechargé pour construire la cible."
)


# ============================================================
# 4. VERIFICATION DES IDS ET ETATS INITIAUX
# ============================================================

print()
print("=" * 80)
print("4. ETATS AVANT MODIFICATION")
print("=" * 80)

for switch_id in TARGET_SWITCH_STATES:

    check_switch_exists(
        target_network,
        switch_id,
    )

    print_switch_state(
        target_network,
        switch_id,
        prefix="  ",
    )


# ============================================================
# 5. APPLICATION DES MODIFICATIONS
# ============================================================

print()
print("=" * 80)
print("5. APPLICATION DES MODIFICATIONS")
print("=" * 80)

effective_changes = 0

for switch_id, target_open_state in TARGET_SWITCH_STATES.items():

    old_state = get_switch_open_state(
        target_network,
        switch_id,
    )

    target_network.update_switches(
        id=switch_id,
        open=target_open_state,
    )

    if old_state != target_open_state:
        effective_changes += 1

    old_text = (
        "OUVERT"
        if old_state
        else "FERME"
    )

    new_text = (
        "OUVERT"
        if target_open_state
        else "FERME"
    )

    print()
    print(switch_id)
    print(f"    {old_text} -> {new_text}")


# ============================================================
# 6. VERIFICATION IMMEDIATE DES MODIFICATIONS
# ============================================================

print()
print("=" * 80)
print("6. VERIFICATION DE LA CONFIGURATION CIBLE")
print("=" * 80)

for switch_id, expected_open in TARGET_SWITCH_STATES.items():

    actual_open = get_switch_open_state(
        target_network,
        switch_id,
    )

    print_switch_state(
        target_network,
        switch_id,
        prefix="  ",
    )

    if actual_open != expected_open:

        raise RuntimeError(
            f"Erreur pour {switch_id}: "
            f"attendu open={expected_open}, "
            f"obtenu open={actual_open}."
        )


# ============================================================
# 7. SAUVEGARDE DE TARGET.XIIDM
# ============================================================

print()
print("=" * 80)
print("7. SAUVEGARDE DE TARGET.XIIDM")
print("=" * 80)

save_xiidm(
    target_network,
    TARGET_FILE,
)


# ============================================================
# 8. RECHARGEMENT POUR VERIFICATION
# ============================================================

print()
print("=" * 80)
print("8. RECHARGEMENT INITIAL / TARGET")
print("=" * 80)

initial_check = pp.network.load(
    INITIAL_FILE
)

target_check = pp.network.load(
    TARGET_FILE
)

print_voltage_level_info(
    initial_check,
    VOLTAGE_LEVEL_ID,
    "INITIAL.XIIDM",
)

print_voltage_level_info(
    target_check,
    VOLTAGE_LEVEL_ID,
    "TARGET.XIIDM",
)


# ============================================================
# 9. COMPARAISON DETAILLEE INITIAL / TARGET
# ============================================================

print()
print("=" * 80)
print("9. DIFFERENCES INITIAL / TARGET")
print("=" * 80)

initial_switches = initial_check.get_switches()
target_switches = target_check.get_switches()

verified_changes = 0

for switch_id in TARGET_SWITCH_STATES:

    initial_open = bool(
        initial_switches.loc[
            switch_id,
            "open",
        ]
    )

    target_open = bool(
        target_switches.loc[
            switch_id,
            "open",
        ]
    )

    initial_text = (
        "OUVERT"
        if initial_open
        else "FERME"
    )

    target_text = (
        "OUVERT"
        if target_open
        else "FERME"
    )

    print()
    print(switch_id)
    print(f"    initial : {initial_text}")
    print(f"    target  : {target_text}")

    if initial_open != target_open:
        verified_changes += 1


# ============================================================
# 10. VERIFICATION STRUCTURELLE
# ============================================================

print()
print("=" * 80)
print("10. VERIFICATION STRUCTURELLE")
print("=" * 80)

initial_vls = initial_check.get_voltage_levels()
target_vls = target_check.get_voltage_levels()

initial_nominal_v = float(
    initial_vls.loc[
        VOLTAGE_LEVEL_ID,
        "nominal_v",
    ]
)

target_nominal_v = float(
    target_vls.loc[
        VOLTAGE_LEVEL_ID,
        "nominal_v",
    ]
)

if initial_nominal_v != target_nominal_v:

    raise RuntimeError(
        "Les tensions nominales initiale et cible sont différentes."
    )


initial_topology = (
    initial_check.get_node_breaker_topology(
        VOLTAGE_LEVEL_ID
    )
)

target_topology = (
    target_check.get_node_breaker_topology(
        VOLTAGE_LEVEL_ID
    )
)

initial_switch_ids = set(
    initial_topology.switches.index
)

target_switch_ids = set(
    target_topology.switches.index
)

if initial_switch_ids != target_switch_ids:

    missing_target = (
        initial_switch_ids
        - target_switch_ids
    )

    missing_initial = (
        target_switch_ids
        - initial_switch_ids
    )

    raise RuntimeError(
        "Les réseaux initial et cible n'ont pas "
        "le même ensemble de switches.\n"
        f"Absents de target : {missing_target}\n"
        f"Absents de initial: {missing_initial}"
    )


# ============================================================
# 11. RESUME FINAL
# ============================================================

print()
print("=" * 80)
print("SCENARIO CHAOTIQUE CREE AVEC SUCCES")
print("=" * 80)

print(f"Voltage level          : {VOLTAGE_LEVEL_ID}")
print(f"Initial                : {INITIAL_FILE}")
print(f"Target                 : {TARGET_FILE}")
print(f"Switches ciblés        : {len(TARGET_SWITCH_STATES)}")
print(f"Modifications effectives: {verified_changes}")

print()
print("✓ Même VoltageLevel")
print("✓ Même tension nominale")
print("✓ Même topologie physique Node-Breaker")
print("✓ Même ensemble de switches")
print("✓ Etats cibles vérifiés")

print()
print("Le fichier est prêt pour les tests A*.")
