from pathlib import Path

import pypowsybl as pp


# ============================================================
# PARAMETRES
# ============================================================

SOURCE_FILE = Path("data/réseau.arc")

INITIAL_FILE = Path("data/initial.xiidm")
TARGET_FILE = Path("data/target.xiidm")

VOLTAGE_LEVEL_ID = ".A.ZA 6"


# ============================================================
# MODIFICATIONS A APPLIQUER A LA CIBLE
#
# ATTENTION :
#
# open=True  -> switch OUVERT
# open=False -> switch FERME
#
# Ici on transfère trois départs :
#
# ACAM   : barre 1 -> barre 2
# AVEZT1 : barre 1 -> barre 2
# AVEZT2 : barre 2 -> barre 1
# ============================================================

TARGET_SWITCH_STATES = {
    # --------------------------------------------------------
    # ACAM
    # --------------------------------------------------------
    ".A.ZA 6_.A.ZA 6 .ACAM.1_DCS SA.1": True,
    ".A.ZA 6_.A.ZA 6 .ACAM.1_DCS SA.2": False,

    # --------------------------------------------------------
    # AVEZT1
    # --------------------------------------------------------
    ".A.ZA 6_.A.ZA 6 .AVEZT1_DCS SA.1": True,
    ".A.ZA 6_.A.ZA 6 .AVEZT1_DCS SA.2": False,

    # --------------------------------------------------------
    # AVEZT2
    # --------------------------------------------------------
    ".A.ZA 6_.A.ZA 6 .AVEZT2_DCS SA.1": False,
    ".A.ZA 6_.A.ZA 6 .AVEZT2_DCS SA.2": True,
}


# ============================================================
# FONCTIONS
# ============================================================

def save_xiidm(network, path: Path) -> None:
    """
    Sauvegarde robuste du réseau au format XIIDM.

    On utilise save_to_string() puis write_text() car cette
    méthode a déjà été vérifiée sur le réseau ARC utilisé ici.
    """

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

    print(
        f"Fichier sauvegardé : {path}"
    )
    print(
        f"Taille XML         : {len(xml):,} caractères"
    )


def print_voltage_level_info(
    network,
    voltage_level_id: str,
    label: str,
) -> None:
    """
    Affiche les principales informations du VoltageLevel.
    """

    voltage_levels = network.get_voltage_levels()

    if voltage_level_id not in voltage_levels.index:
        raise ValueError(
            f"VoltageLevel {voltage_level_id!r} absent du réseau {label}."
        )

    row = voltage_levels.loc[voltage_level_id]

    print()
    print(label)
    print("-" * 60)
    print(
        f"VoltageLevel      : {voltage_level_id}"
    )

    if "nominal_v" in row.index:
        print(
            f"Tension nominale  : {row['nominal_v']} kV"
        )

    # Vérification pratique de l'existence de la topologie Node-Breaker.
    try:
        topology = network.get_node_breaker_topology(
            voltage_level_id
        )

        print(
            "Topologie         : NODE_BREAKER"
        )

        print(
            f"Nombre de nœuds   : {len(topology.nodes)}"
        )

        print(
            f"Nombre de switches: {len(topology.switches)}"
        )

    except Exception as exc:
        print(
            "Topologie Node-Breaker : NON DISPONIBLE"
        )

        raise RuntimeError(
            f"Impossible d'obtenir la topologie Node-Breaker "
            f"de {voltage_level_id}: {exc}"
        ) from exc


def check_switch_exists(
    network,
    switch_id: str,
) -> None:
    """
    Vérifie que le switch existe avant de le modifier.
    """

    switches = network.get_switches()

    if switch_id not in switches.index:
        raise KeyError(
            f"Switch introuvable : {switch_id}"
        )


def print_switch_state(
    network,
    switch_id: str,
    prefix: str = "",
) -> None:
    """
    Affiche l'état open/closed d'un switch.
    """

    switches = network.get_switches()

    state = bool(
        switches.loc[
            switch_id,
            "open",
        ]
    )

    human_state = (
        "OUVERT"
        if state
        else "FERME"
    )

    print(
        f"{prefix}{switch_id}"
    )

    print(
        f"{prefix}    open={state} -> {human_state}"
    )


# ============================================================
# CREATION DE INITIAL.XIIDM
# ============================================================

print()
print("=" * 70)
print("1. CHARGEMENT DU RESEAU SOURCE")
print("=" * 70)

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
    "RESEAU INITIAL",
)


print()
print("=" * 70)
print("2. SAUVEGARDE DE INITIAL.XIIDM")
print("=" * 70)

save_xiidm(
    initial_network,
    INITIAL_FILE,
)


# ============================================================
# CREATION DU RESEAU CIBLE
#
# On recharge le .arc au lieu de modifier initial_network.
# Ainsi les deux réseaux sont créés indépendamment depuis
# exactement la même situation source.
# ============================================================

print()
print("=" * 70)
print("3. CREATION DU RESEAU CIBLE")
print("=" * 70)

target_network = pp.network.load(
    SOURCE_FILE
)

print(
    "Le réseau source a été rechargé pour construire la cible."
)


# ============================================================
# AFFICHAGE DES ETATS AVANT MODIFICATION
# ============================================================

print()
print("Etats AVANT modification :")
print("-" * 70)

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
# APPLICATION DES MODIFICATIONS
# ============================================================

print()
print("=" * 70)
print("4. MODIFICATION DES SWITCHES")
print("=" * 70)

for switch_id, target_open_state in TARGET_SWITCH_STATES.items():

    target_network.update_switches(
        id=switch_id,
        open=target_open_state,
    )

    state_text = (
        "OUVERT"
        if target_open_state
        else "FERME"
    )

    print(
        f"{switch_id}"
    )

    print(
        f"    -> {state_text}"
    )


# ============================================================
# VERIFICATION IMMEDIATE DES MODIFICATIONS
# ============================================================

print()
print("Etats APRES modification :")
print("-" * 70)

for switch_id, expected_open in TARGET_SWITCH_STATES.items():

    switches = target_network.get_switches()

    actual_open = bool(
        switches.loc[
            switch_id,
            "open",
        ]
    )

    print_switch_state(
        target_network,
        switch_id,
        prefix="  ",
    )

    if actual_open != expected_open:
        raise RuntimeError(
            f"Erreur de modification pour {switch_id}: "
            f"attendu open={expected_open}, "
            f"obtenu open={actual_open}."
        )


# ============================================================
# SAUVEGARDE TARGET.XIIDM
# ============================================================

print()
print("=" * 70)
print("5. SAUVEGARDE DE TARGET.XIIDM")
print("=" * 70)

save_xiidm(
    target_network,
    TARGET_FILE,
)


# ============================================================
# RECHARGEMENT DES DEUX XIIDM
# ============================================================

print()
print("=" * 70)
print("6. RECHARGEMENT DES DEUX XIIDM")
print("=" * 70)

initial_check = pp.network.load(
    INITIAL_FILE
)

target_check = pp.network.load(
    TARGET_FILE
)

print(
    f"Initial rechargé : {INITIAL_FILE}"
)

print(
    f"Target rechargé  : {TARGET_FILE}"
)


# ============================================================
# INFORMATIONS VOLTAGE LEVEL
# ============================================================

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
# COMPARAISON INITIAL / TARGET
# ============================================================

print()
print("=" * 70)
print("7. COMPARAISON INITIAL / TARGET")
print("=" * 70)

initial_switches = initial_check.get_switches()
target_switches = target_check.get_switches()

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
    print(
        switch_id
    )

    print(
        f"    initial : {initial_text}"
    )

    print(
        f"    target  : {target_text}"
    )


# ============================================================
# VERIFICATION DES TENSIONS NOMINALES
# ============================================================

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

print()
print("=" * 70)
print("8. VERIFICATION FINALE")
print("=" * 70)

print(
    f"Tension initiale : {initial_nominal_v} kV"
)

print(
    f"Tension cible    : {target_nominal_v} kV"
)

if initial_nominal_v != target_nominal_v:
    raise RuntimeError(
        "Les tensions nominales des deux VoltageLevels sont différentes."
    )


# ============================================================
# VERIFICATION DU NOMBRE DE SWITCHES
# ============================================================

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
        "Les topologies initiale et cible ne contiennent "
        "pas les mêmes switches.\n"
        f"Absents de target : {missing_target}\n"
        f"Absents de initial: {missing_initial}"
    )


print(
    "✓ Même VoltageLevel"
)

print(
    "✓ Même tension nominale"
)

print(
    "✓ Topologie Node-Breaker disponible dans les deux fichiers"
)

print(
    "✓ Même ensemble de switches"
)

print(
    "✓ Modifications cible vérifiées"
)

print()
print(
    "Création des fichiers terminée avec succès."
)

print(
    f"Initial : {INITIAL_FILE}"
)

print(
    f"Target  : {TARGET_FILE}"
)




