from pathlib import Path
import pypowsybl as pp


# ============================================================
# PARAMETRES
# ============================================================

INITIAL_FILE = Path("data/COULAP7_initial.xiidm")
TARGET_FILE = Path("data/COULAP7_target_temp_overhead.xiidm")

VOLTAGE_LEVEL_ID = "COULAP7"


# ============================================================
# CELLULE TESTEE : P.COR.1
# ============================================================

SA1_ID = "COULAP7_COULA   7P.COR.1  SA.1"
SA2_ID = "COULAP7_COULA   7P.COR.1  SA.2"
DJ_ID  = "COULAP7_COULA   7P.COR.1  DJ"


# ============================================================
# CHARGEMENT
# ============================================================

print("=" * 70)
print("1. CHARGEMENT DE L'ETAT INITIAL")
print("=" * 70)

if not INITIAL_FILE.exists():
    raise FileNotFoundError(INITIAL_FILE)

network = pp.network.load(INITIAL_FILE)

switches = network.get_switches()


# ============================================================
# VERIFICATION DES IDs
# ============================================================

for switch_id in [SA1_ID, SA2_ID, DJ_ID]:

    if switch_id not in switches.index:
        raise KeyError(
            f"Switch introuvable : {repr(switch_id)}"
        )


# ============================================================
# ETATS INITIAUX
# ============================================================

sa1_open = bool(
    switches.loc[SA1_ID, "open"]
)

sa2_open = bool(
    switches.loc[SA2_ID, "open"]
)

dj_open = bool(
    switches.loc[DJ_ID, "open"]
)


print()
print("Etat initial P.COR.1 :")

print(
    "SA.1 :",
    "OUVERT" if sa1_open else "FERME"
)

print(
    "SA.2 :",
    "OUVERT" if sa2_open else "FERME"
)

print(
    "DJ   :",
    "OUVERT" if dj_open else "FERME"
)


# ============================================================
# VERIFICATION DU CAS ATTENDU
# ============================================================
#
# D'après COULAP7 :
#
# SA.1 = ouverte
# SA.2 = fermée
# DJ   = fermé
#
# PyPowSyBl :
#
# open=True  -> ouvert
# open=False -> fermé
# ============================================================

if not sa1_open:
    raise RuntimeError(
        "SA.1 devrait être ouverte dans l'état initial."
    )

if sa2_open:
    raise RuntimeError(
        "SA.2 devrait être fermée dans l'état initial."
    )

if dj_open:
    raise RuntimeError(
        "Le DJ devrait être fermé dans l'état initial."
    )


# ============================================================
# CREATION DE LA CIBLE
# ============================================================

print()
print("=" * 70)
print("2. CREATION DE LA CIBLE")
print("=" * 70)

# On ouvre uniquement SA.2.
#
# SA.1 reste ouverte.
# DJ reste fermé.
#
# Donc :
#
# Hamming(initial, target) = 1
#
# mais la manoeuvre devrait nécessiter :
#
# OPEN DJ
# OPEN SA.2
# CLOSE DJ
#
# donc coût attendu ≈ 3.

network.update_switches(
    id=SA2_ID,
    open=True
)


# ============================================================
# VERIFICATION
# ============================================================

target_switches = network.get_switches()

target_sa1 = bool(
    target_switches.loc[SA1_ID, "open"]
)

target_sa2 = bool(
    target_switches.loc[SA2_ID, "open"]
)

target_dj = bool(
    target_switches.loc[DJ_ID, "open"]
)


print()
print("Etat cible P.COR.1 :")

print(
    "SA.1 :",
    "OUVERT" if target_sa1 else "FERME"
)

print(
    "SA.2 :",
    "OUVERT" if target_sa2 else "FERME"
)

print(
    "DJ   :",
    "OUVERT" if target_dj else "FERME"
)


# ============================================================
# CALCUL DU HAMMING
# ============================================================

initial_states = {
    SA1_ID: sa1_open,
    SA2_ID: sa2_open,
    DJ_ID: dj_open,
}

target_states = {
    SA1_ID: target_sa1,
    SA2_ID: target_sa2,
    DJ_ID: target_dj,
}

hamming = sum(
    initial_states[switch_id]
    != target_states[switch_id]
    for switch_id in initial_states
)


print()
print(
    "Distance de Hamming locale :",
    hamming
)

if hamming != 1:
    raise RuntimeError(
        f"Hamming inattendu : {hamming}"
    )


# ============================================================
# SAUVEGARDE
# ============================================================

print()
print("=" * 70)
print("3. SAUVEGARDE")
print("=" * 70)

xml = network.save_to_string("XIIDM")

TARGET_FILE.parent.mkdir(
    parents=True,
    exist_ok=True
)

TARGET_FILE.write_text(
    xml,
    encoding="utf-8"
)

print(
    f"Target sauvegardé : {TARGET_FILE}"
)


# ============================================================
# RECHARGEMENT FINAL
# ============================================================

check = pp.network.load(
    TARGET_FILE
)

check_switches = check.get_switches()

if not bool(
    check_switches.loc[SA2_ID, "open"]
):
    raise RuntimeError(
        "La cible n'a pas été correctement sauvegardée."
    )


print()
print("=" * 70)
print("SCENARIO CREE")
print("=" * 70)

print(
    "Initial :",
    INITIAL_FILE
)

print(
    "Target  :",
    TARGET_FILE
)

print(
    "Hamming attendu : 1"
)

print(
    "Coût attendu si boucle longue nécessaire : 3"
)

print()
print(
    "Séquence attendue :"
)

print(
    "1. OPEN  P.COR.1 DJ"
)

print(
    "2. OPEN  P.COR.1 SA.2"
)

print(
    "3. CLOSE P.COR.1 DJ"
)

