import pypowsybl.network as pp


# ============================
# PARAMETRES
# ============================


Network = "data/réseau.arc"

VOLTAGE_LEVEL_ID = "CONF5P1"


# ============================
# CHARGEMENT DU RESEAU
# ============================

network = pp.load(Network)


# ============================
# INFORMATIONS VOLTAGE LEVEL
# ============================

print("="*80)
print(f"VOLTAGE LEVEL : {VOLTAGE_LEVEL_ID}")
print("="*80)


voltage_levels = network.get_voltage_levels()

if VOLTAGE_LEVEL_ID not in voltage_levels.index:
    raise ValueError(
        f"Voltage level {VOLTAGE_LEVEL_ID} introuvable"
    )


vl = voltage_levels.loc[VOLTAGE_LEVEL_ID]

print(vl)


# ============================
# SWITCHES DU VOLTAGE LEVEL
# ============================

print("\n")
print("="*80)
print("ORGANES DE COUPURE")
print("="*80)


switches = network.get_switches()

# Les switches dont le voltage level apparaît dans la ligne
for switch_id, row in switches.iterrows():

    vl1 = row.get("voltage_level_id")
    vl2 = row.get("voltage_level_id_2")

    if vl1 == VOLTAGE_LEVEL_ID or vl2 == VOLTAGE_LEVEL_ID:

        print("\n--------------------------------")
        print("ID :", switch_id)

        print("Type :", row.get("kind"))

        print(
            "Etat :",
            "OUVERT" if row.get("open") else "FERME"
        )

        print(row)


# ============================
# EQUIPEMENTS DU VOLTAGE LEVEL
# ============================

print("\n")
print("="*80)
print("EQUIPEMENTS CONNECTES")
print("="*80)


for name, dataframe in [
    ("LIGNES", network.get_lines()),
    ("TRANSFORMATEURS", network.get_2_windings_transformers()),
    ("INJECTIONS", network.get_generators()),
    ("CHARGES", network.get_loads()),
]:

    print("\n---", name, "---")

    for equipment_id, row in dataframe.iterrows():

        if (
            row.get("voltage_level1_id") == VOLTAGE_LEVEL_ID
            or row.get("voltage_level2_id") == VOLTAGE_LEVEL_ID
            or row.get("voltage_level_id") == VOLTAGE_LEVEL_ID
        ):
            print(equipment_id)


# ============================
# BUSBAR SECTIONS
# ============================

print("\n")
print("="*80)
print("BUSBAR SECTIONS")
print("="*80)

busbars = network.get_busbar_sections()

for busbar_id, row in busbars.iterrows():

    if row.get("voltage_level_id") == VOLTAGE_LEVEL_ID:
        print("\n--------------------------------")
        print("ID :", busbar_id)
        print(row)

