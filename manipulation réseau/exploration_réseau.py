from pathlib import Path

import pandas as pd
import pypowsybl as pp


# ============================================================
# PARAMETRES
# ============================================================

NETWORK_FILE = Path("data/réseau.arc")

OUTPUT_DIR = Path("generated")

OUTPUT_CSV = OUTPUT_DIR / "voltage_levels_scan.csv"


# ============================================================
# VERIFICATION DU FICHIER SOURCE
# ============================================================

if not NETWORK_FILE.exists():
    raise FileNotFoundError(
        f"Fichier réseau introuvable : {NETWORK_FILE}"
    )


# ============================================================
# CREATION DU DOSSIER DE SORTIE
# ============================================================

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# CHARGEMENT DU RESEAU
# ============================================================

print()
print("=" * 80)
print("CHARGEMENT DU RESEAU")
print("=" * 80)

network = pp.network.load(
    NETWORK_FILE
)

print(
    f"Réseau chargé avec succès : {NETWORK_FILE}"
)


# ============================================================
# RECUPERATION DES VOLTAGE LEVELS
# ============================================================

voltage_levels = network.get_voltage_levels()

print()
print(
    f"Nombre total de VoltageLevels dans le réseau : "
    f"{len(voltage_levels)}"
)


# ============================================================
# ANALYSE DES VOLTAGE LEVELS
# ============================================================

rows = []

print()
print("=" * 80)
print("ANALYSE DES VOLTAGE LEVELS NODE-BREAKER")
print("=" * 80)

for index, (vl_id, vl_row) in enumerate(
    voltage_levels.iterrows(),
    start=1,
):

    try:
        topology = network.get_node_breaker_topology(
            vl_id
        )

    except Exception:
        # Certains VoltageLevels peuvent ne pas être exploitables
        # via une topologie Node-Breaker.
        continue

    nodes = topology.nodes
    switches = topology.switches

    # --------------------------------------------------------
    # On ignore les VoltageLevels sans switches
    # --------------------------------------------------------

    if switches.empty:
        continue

    # --------------------------------------------------------
    # Tension nominale
    # --------------------------------------------------------

    if "nominal_v" in vl_row.index:
        nominal_v = float(
            vl_row["nominal_v"]
        )
    else:
        nominal_v = None

    # --------------------------------------------------------
    # Sous-station
    # --------------------------------------------------------

    if "substation_id" in vl_row.index:
        substation_id = vl_row[
            "substation_id"
        ]
    else:
        substation_id = None

    # --------------------------------------------------------
    # Nom
    # --------------------------------------------------------

    if "name" in vl_row.index:
        voltage_level_name = vl_row[
            "name"
        ]
    else:
        voltage_level_name = None

    # --------------------------------------------------------
    # Comptage des switches par type
    # --------------------------------------------------------

    if "kind" in switches.columns:

        breakers = int(
            (
                switches["kind"]
                == "BREAKER"
            ).sum()
        )

        disconnectors = int(
            (
                switches["kind"]
                == "DISCONNECTOR"
            ).sum()
        )

        load_break_switches = int(
            (
                switches["kind"]
                == "LOAD_BREAK_SWITCH"
            ).sum()
        )

    else:

        breakers = 0
        disconnectors = 0
        load_break_switches = 0

    # --------------------------------------------------------
    # Nombre de switches ouverts / fermes
    # --------------------------------------------------------

    if "open" in switches.columns:

        open_switches = int(
            switches["open"].sum()
        )

        closed_switches = int(
            len(switches)
            - open_switches
        )

    else:

        open_switches = 0
        closed_switches = 0

    # --------------------------------------------------------
    # Nombre de Busbar Sections
    # --------------------------------------------------------

    if "connectable_type" in nodes.columns:

        busbar_sections = int(
            (
                nodes["connectable_type"]
                == "BUSBAR_SECTION"
            ).sum()
        )

    else:

        busbar_sections = 0

    # --------------------------------------------------------
    # Nombre d'equipements par type
    # --------------------------------------------------------

    if "connectable_type" in nodes.columns:

        connectable_types = (
            nodes["connectable_type"]
            .value_counts()
        )

        loads = int(
            connectable_types.get(
                "LOAD",
                0,
            )
        )

        lines = int(
            connectable_types.get(
                "LINE",
                0,
            )
        )

        generators = int(
            connectable_types.get(
                "GENERATOR",
                0,
            )
        )

        transformers_2w = int(
            connectable_types.get(
                "TWO_WINDINGS_TRANSFORMER",
                0,
            )
        )

        transformers_3w = int(
            connectable_types.get(
                "THREE_WINDINGS_TRANSFORMER",
                0,
            )
        )

    else:

        loads = 0
        lines = 0
        generators = 0
        transformers_2w = 0
        transformers_3w = 0

    # --------------------------------------------------------
    # Score simple d'interet pour nos tests
    #
    # Ce score n'est pas une grandeur electrique.
    # Il sert uniquement à classer les VoltageLevels
    # potentiellement interessants pour le benchmark.
    # --------------------------------------------------------

    complexity_score = (
        len(switches)
        + 2 * busbar_sections
        + breakers
    )

    # --------------------------------------------------------
    # Stockage
    # --------------------------------------------------------

    rows.append(
        {
            "voltage_level_id":
                vl_id,

            "name":
                voltage_level_name,

            "substation_id":
                substation_id,

            "nominal_v_kv":
                nominal_v,

            "nodes":
                len(nodes),

            "switches":
                len(switches),

            "breakers":
                breakers,

            "disconnectors":
                disconnectors,

            "load_break_switches":
                load_break_switches,

            "open_switches":
                open_switches,

            "closed_switches":
                closed_switches,

            "busbar_sections":
                busbar_sections,

            "loads":
                loads,

            "lines":
                lines,

            "generators":
                generators,

            "two_windings_transformers":
                transformers_2w,

            "three_windings_transformers":
                transformers_3w,

            "complexity_score":
                complexity_score,
        }
    )


# ============================================================
# CREATION DU DATAFRAME
# ============================================================

df = pd.DataFrame(
    rows
)

if df.empty:
    raise RuntimeError(
        "Aucun VoltageLevel Node-Breaker "
        "avec switches n'a été trouvé."
    )


# ============================================================
# TRI PAR NOMBRE DE SWITCHES
# ============================================================

df = df.sort_values(
    by=[
        "switches",
        "busbar_sections",
        "breakers",
    ],
    ascending=[
        False,
        False,
        False,
    ],
)


# ============================================================
# SAUVEGARDE CSV COMPLETE
# ============================================================

df.to_csv(
    OUTPUT_CSV,
    index=False,
    encoding="utf-8-sig",
)

print()
print("=" * 80)
print("RESULTATS")
print("=" * 80)

print(
    f"VoltageLevels Node-Breaker analysés : "
    f"{len(df)}"
)

print(
    f"CSV complet sauvegardé dans : "
    f"{OUTPUT_CSV}"
)


# ============================================================
# AFFICHAGE DES 20 PLUS GROS
# ============================================================

columns_to_display = [
    "voltage_level_id",
    "nominal_v_kv",
    "nodes",
    "switches",
    "breakers",
    "disconnectors",
    "busbar_sections",
]

print()
print("=" * 120)
print("20 VOLTAGE LEVELS AVEC LE PLUS DE SWITCHES")
print("=" * 120)

print(
    df[
        columns_to_display
    ]
    .head(20)
    .to_string(
        index=False
    )
)


# ============================================================
# CANDIDATS INTERESSANTS POUR LE BENCHMARK
#
# On cherche ici :
# - au moins 2 Busbar Sections
# - entre 20 et 60 switches
#
# Ces seuils sont uniquement des critères de sélection
# pour les futurs tests.
# ============================================================

benchmark_candidates = df[
    (df["busbar_sections"] >= 2)
    &
    (df["switches"] >= 20)
    &
    (df["switches"] <= 60)
].copy()


print()
print("=" * 120)
print("CANDIDATS POUR UN BENCHMARK A*")
print("=" * 120)

if benchmark_candidates.empty:

    print(
        "Aucun VoltageLevel trouvé avec "
        "2 barres ou plus et entre 20 et 60 switches."
    )

else:

    benchmark_columns = [
        "voltage_level_id",
        "nominal_v_kv",
        "switches",
        "breakers",
        "disconnectors",
        "busbar_sections",
        "complexity_score",
    ]

    print(
        benchmark_candidates[
            benchmark_columns
        ]
        .head(20)
        .to_string(
            index=False
        )
    )


# ============================================================
# SAUVEGARDE D'UN CSV SUPPLEMENTAIRE AVEC
# UNIQUEMENT LES CANDIDATS INTERESSANTS
# ============================================================

CANDIDATES_CSV = (
    OUTPUT_DIR
    / "voltage_levels_candidates.csv"
)

benchmark_candidates.to_csv(
    CANDIDATES_CSV,
    index=False,
    encoding="utf-8-sig",
)

print()
print(
    "CSV des candidats sauvegardé dans : "
    f"{CANDIDATES_CSV}"
)


# ============================================================
# STATISTIQUES GENERALES
# ============================================================

print()
print("=" * 80)
print("STATISTIQUES GENERALES")
print("=" * 80)

print(
    f"Nombre minimal de switches : "
    f"{df['switches'].min()}"
)

print(
    f"Nombre maximal de switches : "
    f"{df['switches'].max()}"
)

print(
    f"Nombre moyen de switches   : "
    f"{df['switches'].mean():.2f}"
)

print(
    f"Nombre médian de switches  : "
    f"{df['switches'].median():.2f}"
)

print(
    f"VoltageLevels avec >= 2 Busbar Sections : "
    f"{(df['busbar_sections'] >= 2).sum()}"
)


print()
print("=" * 80)
print("FIN")
print("=" * 80)

print(
    "Tu peux maintenant ouvrir :"
)

print(
    f"  {OUTPUT_CSV}"
)

print(
    "ou uniquement les candidats :"
)

print(
    f"  {CANDIDATES_CSV}"
)
