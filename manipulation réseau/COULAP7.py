from pathlib import Path
import re
import pypowsybl as pp


# ============================================================
# PARAMETRES
# ============================================================

SOURCE_FILE = Path("data/réseau.arc")

INITIAL_FILE = Path("data/COULAP7_initial.xiidm")
TARGET_FILE = Path("data/COULAP7_target_max_transfer.xiidm")

VOLTAGE_LEVEL_ID = "COULAP7"


# ============================================================
# OPTIONS
# ============================================================

# On exclut les coupleurs de la cible détaillée.
EXCLUDE_COUPLERS = True

# Sécurité :
# COULAP7 contient environ 123 switches.
# Si on récupère beaucoup plus, c'est probablement qu'on
# travaille accidentellement sur tout le réseau.
MAX_EXPECTED_SWITCHES = 200


# ============================================================
# SAUVEGARDE XIIDM
# ============================================================

def save_xiidm(network, path: Path):

    xml = network.save_to_string("XIIDM")

    if not xml:
        raise RuntimeError(
            f"Erreur lors de la sauvegarde XIIDM : {path}"
        )

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    path.write_text(
        xml,
        encoding="utf-8"
    )

    print(f"Fichier sauvegardé : {path}")


# ============================================================
# 1) CHARGEMENT DU RESEAU SOURCE
# ============================================================

print()
print("=" * 80)
print("1. CHARGEMENT DU RESEAU SOURCE")
print("=" * 80)

if not SOURCE_FILE.exists():
    raise FileNotFoundError(
        f"Fichier introuvable : {SOURCE_FILE}"
    )

network = pp.network.load(
    SOURCE_FILE
)

print("Réseau chargé.")


# ============================================================
# 2) VERIFICATION DE COULAP7
# ============================================================

print()
print("=" * 80)
print("2. VERIFICATION DU VOLTAGE LEVEL")
print("=" * 80)

voltage_levels = network.get_voltage_levels()

if VOLTAGE_LEVEL_ID not in voltage_levels.index:
    raise KeyError(
        f"Voltage level absent : {VOLTAGE_LEVEL_ID}"
    )

print(
    f"Voltage level trouvé : {VOLTAGE_LEVEL_ID}"
)


# ============================================================
# 3) CREATION DU FICHIER INITIAL
# ============================================================

print()
print("=" * 80)
print("3. CREATION DE INITIAL.XIIDM")
print("=" * 80)

save_xiidm(
    network,
    INITIAL_FILE
)


# ============================================================
# 4) CREATION INDEPENDANTE DE LA CIBLE
# ============================================================

print()
print("=" * 80)
print("4. CREATION DU RESEAU CIBLE")
print("=" * 80)

# On recharge directement le XIIDM initial.
# C'est généralement plus rapide que de reparser le .arc.

target_network = pp.network.load(
    INITIAL_FILE
)


# ============================================================
# 5) RECUPERATION DES SWITCHES DE COULAP7 UNIQUEMENT
# ============================================================

print()
print("=" * 80)
print("5. SWITCHES DU VOLTAGE LEVEL COULAP7")
print("=" * 80)

topology = target_network.get_node_breaker_topology(
    VOLTAGE_LEVEL_ID
)

vl_switches = topology.switches

print(
    f"Nombre de switches dans {VOLTAGE_LEVEL_ID} : "
    f"{len(vl_switches)}"
)

if len(vl_switches) > MAX_EXPECTED_SWITCHES:
    raise RuntimeError(
        f"Nombre de switches anormal : {len(vl_switches)}\n"
        f"On attend environ 123 switches pour {VOLTAGE_LEVEL_ID}.\n"
        "Le script est interrompu pour éviter de modifier tout le réseau."
    )


# Table globale PyPowSyBl uniquement pour récupérer :
#
#     open
#     kind
#
# MAIS on ne parcourra ensuite QUE les IDs de COULAP7.

all_switches = target_network.get_switches()


# ============================================================
# 6) DETECTION AUTOMATIQUE DES PAIRES SA.1 / SA.2
# ============================================================

print()
print("=" * 80)
print("6. DETECTION DES CELLULES TRANSFERABLES")
print("=" * 80)

# On ne cherche que les IDs terminant EXACTEMENT par :
#
#     SA.1
#     SA.2
#
# Donc on n'inclut pas :
#
#     SA.1A
#     SA.1B
#     SA.2A
#     SA.2B
#     SA.3
#     SA.1F
#     SA.2F
#
# Ces équipements ont des structures différentes et seront
# laissés tranquilles pour ce premier gros scénario.

pattern = re.compile(
    r"^(.*)\s+SA\.(1|2)$"
)

groups = {}


for switch_id in vl_switches.index:

    # --------------------------------------------------------
    # Vérification que le switch existe aussi dans la table
    # globale PyPowSyBl.
    # --------------------------------------------------------

    if switch_id not in all_switches.index:
        continue

    row = all_switches.loc[
        switch_id
    ]

    # --------------------------------------------------------
    # Seulement les sectionneurs.
    # --------------------------------------------------------

    if str(row["kind"]).upper() != "DISCONNECTOR":
        continue

    match = pattern.match(
        switch_id
    )

    if match is None:
        continue

    base = match.group(1)
    selector_number = match.group(2)

    # --------------------------------------------------------
    # On ne touche pas aux coupleurs.
    # --------------------------------------------------------

    if (
        EXCLUDE_COUPLERS
        and "COUPL" in base.upper()
    ):
        continue

    groups.setdefault(
        base,
        {}
    )

    groups[base][
        selector_number
    ] = switch_id


# ============================================================
# 7) IDENTIFICATION DES VRAIES CELLULES A TRANSFERER
# ============================================================

print()
print("=" * 80)
print("7. ANALYSE DES PAIRES")
print("=" * 80)

selected_cells = []

TARGET_SWITCH_STATES = {}


for base, selectors in groups.items():

    # Il faut impérativement avoir SA.1 ET SA.2.

    if (
        "1" not in selectors
        or "2" not in selectors
    ):
        continue

    sa1 = selectors["1"]
    sa2 = selectors["2"]

    open_sa1 = bool(
        all_switches.loc[
            sa1,
            "open"
        ]
    )

    open_sa2 = bool(
        all_switches.loc[
            sa2,
            "open"
        ]
    )

    # --------------------------------------------------------
    # On veut seulement une vraie situation d'aiguillage :
    #
    # SA.1 fermé / SA.2 ouvert
    #
    # ou
    #
    # SA.1 ouvert / SA.2 fermé
    #
    # Dans PyPowSyBl :
    #
    # open=True  -> OUVERT
    # open=False -> FERME
    #
    # Donc les deux états doivent être différents.
    # --------------------------------------------------------

    if open_sa1 == open_sa2:

        print(
            f"[IGNORE] {base}: "
            f"SA.1={open_sa1}, "
            f"SA.2={open_sa2}"
        )

        continue

    # --------------------------------------------------------
    # TRANSFERT :
    #
    # on inverse les deux états.
    # --------------------------------------------------------

    target_sa1 = open_sa2
    target_sa2 = open_sa1

    TARGET_SWITCH_STATES[
        sa1
    ] = target_sa1

    TARGET_SWITCH_STATES[
        sa2
    ] = target_sa2

    selected_cells.append(
        (
            base,
            sa1,
            sa2,
            open_sa1,
            open_sa2,
            target_sa1,
            target_sa2
        )
    )


# ============================================================
# 8) AFFICHAGE DU SCENARIO
# ============================================================

print()
print("=" * 80)
print("8. SCENARIO DETECTE")
print("=" * 80)

print(
    f"Cellules transférables : {len(selected_cells)}"
)

print(
    f"Switches à modifier    : {len(TARGET_SWITCH_STATES)}"
)

print()


for i, (
    base,
    sa1,
    sa2,
    old1,
    old2,
    new1,
    new2
) in enumerate(
    selected_cells,
    start=1
):

    print(
        f"[CELLULE {i}] {base}"
    )

    print(
        "   SA.1 :",
        "OUVERT" if old1 else "FERME",
        "->",
        "OUVERT" if new1 else "FERME"
    )

    print(
        "   SA.2 :",
        "OUVERT" if old2 else "FERME",
        "->",
        "OUVERT" if new2 else "FERME"
    )

    print()


# ============================================================
# 9) CONTROLES DE SECURITE
# ============================================================

print()
print("=" * 80)
print("9. CONTROLES")
print("=" * 80)


# On ne doit jamais modifier plus de switches que le voltage
# level lui-même.

if len(TARGET_SWITCH_STATES) > len(vl_switches):
    raise RuntimeError(
        "ERREUR : davantage de switches à modifier "
        "que de switches présents dans COULAP7."
    )


# Chaque cellule doit apporter exactement deux modifications.

if len(TARGET_SWITCH_STATES) != 2 * len(selected_cells):
    raise RuntimeError(
        "Incohérence entre le nombre de cellules "
        "et le nombre de switches."
    )


print("Contrôles OK.")

print(
    f"{len(selected_cells)} cellules"
)

print(
    f"{len(TARGET_SWITCH_STATES)} switches ciblés"
)


# ============================================================
# 10) APPLICATION DES MODIFICATIONS
# ============================================================

print()
print("=" * 80)
print("10. APPLICATION DES MODIFICATIONS")
print("=" * 80)


for switch_id, target_open in TARGET_SWITCH_STATES.items():

    target_network.update_switches(
        id=switch_id,
        open=target_open
    )


print(
    f"{len(TARGET_SWITCH_STATES)} modifications appliquées."
)


# ============================================================
# 11) VERIFICATION IMMEDIATE
# ============================================================

print()
print("=" * 80)
print("11. VERIFICATION DES MODIFICATIONS")
print("=" * 80)

modified_switches = target_network.get_switches()

verified_changes = 0


for switch_id, expected_open in TARGET_SWITCH_STATES.items():

    actual_open = bool(
        modified_switches.loc[
            switch_id,
            "open"
        ]
    )

    initial_open = bool(
        all_switches.loc[
            switch_id,
            "open"
        ]
    )

    if actual_open != expected_open:
        raise RuntimeError(
            f"Erreur sur {switch_id}\n"
            f"Attendu : open={expected_open}\n"
            f"Obtenu  : open={actual_open}"
        )

    if initial_open != actual_open:
        verified_changes += 1


print(
    f"Modifications effectivement vérifiées : "
    f"{verified_changes}"
)


# ============================================================
# 12) SAUVEGARDE TARGET
# ============================================================

print()
print("=" * 80)
print("12. SAUVEGARDE TARGET.XIIDM")
print("=" * 80)

save_xiidm(
    target_network,
    TARGET_FILE
)


# ============================================================
# 13) RECHARGEMENT DE CONTROLE
# ============================================================

print()
print("=" * 80)
print("13. RECHARGEMENT FINAL")
print("=" * 80)

initial_check = pp.network.load(
    INITIAL_FILE
)

target_check = pp.network.load(
    TARGET_FILE
)

initial_all = initial_check.get_switches()
target_all = target_check.get_switches()

target_topology = target_check.get_node_breaker_topology(
    VOLTAGE_LEVEL_ID
)


# ============================================================
# 14) CALCUL EXACT DU HAMMING SUR COULAP7 UNIQUEMENT
# ============================================================

print()
print("=" * 80)
print("14. DIFFERENCES INITIAL / TARGET SUR COULAP7")
print("=" * 80)

changed_switches = []


for switch_id in target_topology.switches.index:

    initial_open = bool(
        initial_all.loc[
            switch_id,
            "open"
        ]
    )

    target_open = bool(
        target_all.loc[
            switch_id,
            "open"
        ]
    )

    if initial_open != target_open:

        changed_switches.append(
            switch_id
        )

        print(
            repr(switch_id)
        )

        print(
            "    ",
            "OUVERT" if initial_open else "FERME",
            "->",
            "OUVERT" if target_open else "FERME"
        )


# ============================================================
# 15) VERIFICATION FINALE
# ============================================================

if len(changed_switches) != len(TARGET_SWITCH_STATES):

    raise RuntimeError(
        "\nIncohérence dans la cible finale.\n"
        f"Demandé : {len(TARGET_SWITCH_STATES)} modifications\n"
        f"Observé : {len(changed_switches)} modifications"
    )


# ============================================================
# 16) RESUME
# ============================================================

print()
print("=" * 80)
print("SCENARIO COULAP7 CREE AVEC SUCCES")
print("=" * 80)

print(
    "Voltage level          :",
    VOLTAGE_LEVEL_ID
)

print(
    "Nombre de switches VL  :",
    len(vl_switches)
)

print(
    "Initial                :",
    INITIAL_FILE
)

print(
    "Target                 :",
    TARGET_FILE
)

print(
    "Cellules transférées   :",
    len(selected_cells)
)

print(
    "Switches modifiés      :",
    len(changed_switches)
)

print(
    "Hamming détaillé       :",
    len(changed_switches)
)

print()
print("Cible prête pour A*.")


