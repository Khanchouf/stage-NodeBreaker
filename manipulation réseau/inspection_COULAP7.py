from pathlib import Path
import pypowsybl as pp

# ============================================================
# PARAMETRES
# ============================================================

SOURCE_FILE = Path("data/réseau.arc")
TARGET_FILE = Path("data/target.xiidm")

# Mets ici le VoltageLevel que tu as choisi
VOLTAGE_LEVEL_ID = "COULAP7"


# ============================================================
# 1. CHARGEMENT DU RESEAU
# ============================================================

network = pp.network.load(SOURCE_FILE)

print(f"Réseau chargé : {SOURCE_FILE}")


# ============================================================
# 2. AFFICHAGE DU VOLTAGE LEVEL
# ============================================================

topology = network.get_node_breaker_topology(
    VOLTAGE_LEVEL_ID
)

print()
print("=" * 100)
print(f"VOLTAGE LEVEL : {VOLTAGE_LEVEL_ID}")
print("=" * 100)

print("\nNODES :")
print(topology.nodes.to_string())

print("\nSWITCHES :")
print(topology.switches.to_string())
