from pathlib import Path
import pypowsybl as pp


# ============================================================
# PARAMETRES
# ============================================================

SOURCE_FILE = Path("data/réseau.arc")

INITIAL_FILE = Path("data/CRENEP3_initial.xiidm")
TARGET_FILE = Path("data/CRENEP3_target_scenario1.xiidm")

VOLTAGE_LEVEL_ID = "CRENEP3"


# ============================================================
# SCENARIO 1 :
# TRANSFERT DU DEPART 3T.IND.1
#
# Barre 1  ---> Barre 2
#
# SA.1 : FERME -> OUVERT
# SA.2 : OUVERT -> FERME
# ============================================================


TARGET_SWITCH_STATES = {

    "CRENEP3_CRENE   3T.IND.1  SA.1": True,

    "CRENEP3_CRENE   3T.IND.1  SA.2": False,

}


# ============================================================
# SAUVEGARDE XIIDM
# ============================================================


def save_xiidm(network, path):

    xml = network.save_to_string("XIIDM")

    if not xml:
        raise RuntimeError(
            "Erreur lors de la sauvegarde XIIDM"
        )

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    path.write_text(
        xml,
        encoding="utf-8"
    )

    print(
        f"Fichier sauvegardé : {path}"
    )



# ============================================================
# VERIFICATION SWITCH
# ============================================================


def check_switch_exists(network, switch_id):

    switches = network.get_switches()

    if switch_id not in switches.index:

        print("\nSwitch introuvable :")
        print(switch_id)

        print("\nSwitches contenant T.IND.1 :")

        for sid in switches.index:

            if "T.IND.1" in sid:
                print(" -", sid)

        raise KeyError(
            f"Switch absent : {switch_id}"
        )



def print_switch(network, switch_id, prefix=""):

    switches = network.get_switches()

    state = bool(
        switches.loc[
            switch_id,
            "open"
        ]
    )

    print(
        prefix + switch_id
    )

    print(
        prefix +
        "    Etat : "
        +
        ("OUVERT" if state else "FERME")
    )



# ============================================================
# 1) CREATION INITIAL.XIIDM
# ============================================================


print("="*70)
print("1. CREATION INITIAL.XIIDM")
print("="*70)


if not SOURCE_FILE.exists():

    raise FileNotFoundError(
        SOURCE_FILE
    )


initial_network = pp.network.load(
    SOURCE_FILE
)


save_xiidm(
    initial_network,
    INITIAL_FILE
)



# ============================================================
# 2) CREATION TARGET
# ============================================================


print()
print("="*70)
print("2. CREATION TARGET.XIIDM")
print("="*70)


target_network = pp.network.load(
    SOURCE_FILE
)


print("\nEtat initial des switches modifiés :")

for switch_id in TARGET_SWITCH_STATES:

    check_switch_exists(
        target_network,
        switch_id
    )

    print_switch(
        target_network,
        switch_id,
        "  "
    )



# ============================================================
# 3) APPLICATION MODIFICATIONS
# ============================================================


print()
print("="*70)
print("3. MODIFICATION DES SWITCHES")
print("="*70)


for switch_id, target_state in TARGET_SWITCH_STATES.items():


    target_network.update_switches(
        id=switch_id,
        open=target_state
    )


    print(
        switch_id,
        "->",
        "OUVERT" if target_state else "FERME"
    )



# ============================================================
# 4) VERIFICATION
# ============================================================


print()
print("="*70)
print("4. VERIFICATION CIBLE")
print("="*70)


for switch_id, expected in TARGET_SWITCH_STATES.items():

    switches = target_network.get_switches()

    actual = bool(
        switches.loc[
            switch_id,
            "open"
        ]
    )

    print_switch(
        target_network,
        switch_id,
        "  "
    )

    if actual != expected:

        raise RuntimeError(
            f"Erreur sur {switch_id}"
        )



# ============================================================
# 5) SAUVEGARDE TARGET
# ============================================================


print()
print("="*70)
print("5. SAUVEGARDE TARGET.XIIDM")
print("="*70)


save_xiidm(
    target_network,
    TARGET_FILE
)



# ============================================================
# 6) RESUME
# ============================================================


print()
print("="*70)
print("SCENARIO CREE AVEC SUCCES")
print("="*70)


print(
    "Initial :",
    INITIAL_FILE
)

print(
    "Target  :",
    TARGET_FILE
)


