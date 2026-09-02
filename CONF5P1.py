import random
from pathlib import Path

import pypowsybl as pp


# ============================================================
# CONFIGURATION
# ============================================================

INITIAL = "data/initial.xiidm"
OUTPUT = "data/target_CONF5P1_7.xiidm"

VOLTAGE_LEVEL = "CONF5P1"

COUNT = 7
SEED = 42


# ============================================================
# CHARGEMENT
# ============================================================

network = pp.network.load(INITIAL)

topology = network.get_node_breaker_topology(
    VOLTAGE_LEVEL
)

switches = topology.switches


print("=" * 70)
print("CONF5P1 - GENERATION DE LA CIBLE")
print("=" * 70)

print(f"Nombre de switchs : {len(switches)}")
print(f"Nombre a modifier : {COUNT}")


if COUNT > len(switches):
    raise ValueError(
        f"Impossible de modifier {COUNT} switchs : "
        f"le poste n'en contient que {len(switches)}."
    )


# ============================================================
# SELECTION ALEATOIRE
# ============================================================

random.seed(SEED)

switch_ids = list(switches.index)

selected = random.sample(
    switch_ids,
    COUNT,
)


# ============================================================
# MODIFICATION
# ============================================================

print()
print("=" * 70)
print("SWITCHS MODIFIES")
print("=" * 70)


for i, switch_id in enumerate(
    selected,
    start=1,
):

    row = switches.loc[switch_id]

    old_open = bool(row["open"])
    new_open = not old_open

    network.update_switches(
        id=switch_id,
        open=new_open,
    )

    print(
        f"{i:02d}. "
        f"{switch_id} | "
        f"{'OUVERT' if old_open else 'FERME'}"
        f" -> "
        f"{'OUVERT' if new_open else 'FERME'}"
    )


# ============================================================
# SAUVEGARDE
# ============================================================

output_path = Path(OUTPUT)

output_path.parent.mkdir(
    parents=True,
    exist_ok=True,
)

network.save(
    str(output_path),
    format="XIIDM",
)


# ============================================================
# VERIFICATION
# ============================================================

initial_network = pp.network.load(
    INITIAL
)

target_network = pp.network.load(
    str(output_path)
)

initial_switches = (
    initial_network
    .get_node_breaker_topology(
        VOLTAGE_LEVEL
    )
    .switches
)

target_switches = (
    target_network
    .get_node_breaker_topology(
        VOLTAGE_LEVEL
    )
    .switches
)


changed = []

for switch_id in initial_switches.index:

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

    if initial_open != target_open:
        changed.append(
            switch_id
        )


print()
print("=" * 70)
print("RESULTAT")
print("=" * 70)

print(
    f"Switchs differents : "
    f"{len(changed)}"
)

print(
    f"Distance de Hamming : "
    f"{len(changed)}"
)

print(
    f"Fichier cible : "
    f"{output_path.resolve()}"
)


if len(changed) != COUNT:
    raise RuntimeError(
        f"Erreur : {len(changed)} switchs "
        f"differents au lieu de {COUNT}."
    )


print()
print("SUCCES")











#DIfference entre les 2 reseaux target 6 et 7 

import pypowsybl as pp


INITIAL = "data/initial.xiidm"
TARGET_6 = "data/target_CONF5P1_6.xiidm"
TARGET_7 = "data/target_CONF5P1_7.xiidm"

VOLTAGE_LEVEL = "CONF5P1"


def get_switches(path):
    network = pp.network.load(path)

    topology = network.get_node_breaker_topology(
        VOLTAGE_LEVEL
    )

    return topology.switches


def find_differences(initial_switches, target_switches):
    differences = []

    for switch_id in initial_switches.index:

        initial_open = bool(
            initial_switches.loc[
                switch_id,
                "open"
            ]
        )

        target_open = bool(
            target_switches.loc[
                switch_id,
                "open"
            ]
        )

        if initial_open != target_open:

            differences.append(
                {
                    "id": switch_id,
                    "kind": initial_switches.loc[
                        switch_id,
                        "kind"
                    ],
                    "initial_open": initial_open,
                    "target_open": target_open,
                }
            )

    return differences


initial_switches = get_switches(
    INITIAL
)

target_6_switches = get_switches(
    TARGET_6
)

target_7_switches = get_switches(
    TARGET_7
)


diff_6 = find_differences(
    initial_switches,
    target_6_switches
)

diff_7 = find_differences(
    initial_switches,
    target_7_switches
)


print("=" * 80)
print("TARGET COUNT = 6")
print("=" * 80)

for i, item in enumerate(
    diff_6,
    start=1
):

    initial_state = (
        "OUVERT"
        if item["initial_open"]
        else "FERME"
    )

    target_state = (
        "OUVERT"
        if item["target_open"]
        else "FERME"
    )

    print(
        f"{i:02d}. "
        f"{item['id']} | "
        f"{item['kind']} | "
        f"{initial_state} -> {target_state}"
    )


print()
print(
    "Nombre de différences :",
    len(diff_6)
)


print()
print("=" * 80)
print("TARGET COUNT = 7")
print("=" * 80)

for i, item in enumerate(
    diff_7,
    start=1
):

    initial_state = (
        "OUVERT"
        if item["initial_open"]
        else "FERME"
    )

    target_state = (
        "OUVERT"
        if item["target_open"]
        else "FERME"
    )

    print(
        f"{i:02d}. "
        f"{item['id']} | "
        f"{item['kind']} | "
        f"{initial_state} -> {target_state}"
    )


print()
print(
    "Nombre de différences :",
    len(diff_7)
)


ids_6 = {
    item["id"]
    for item in diff_6
}

ids_7 = {
    item["id"]
    for item in diff_7
}


added = ids_7 - ids_6

removed = ids_6 - ids_7

common = ids_6 & ids_7


print()
print("=" * 80)
print("COMPARAISON TARGET 6 / TARGET 7")
print("=" * 80)

print()
print(
    f"Switchs communs : "
    f"{len(common)}"
)

for switch_id in sorted(common):
    print(
        "  ",
        switch_id
    )


print()
print(
    f"Présents uniquement dans TARGET 7 : "
    f"{len(added)}"
)

for switch_id in sorted(added):

    row = initial_switches.loc[
        switch_id
    ]

    print(
        f"  {switch_id} | "
        f"{row['kind']}"
    )


print()
print(
    f"Présents uniquement dans TARGET 6 : "
    f"{len(removed)}"
)

for switch_id in sorted(removed):

    row = initial_switches.loc[
        switch_id
    ]

    print(
        f"  {switch_id} | "
        f"{row['kind']}"
    )



