import pypowsybl as pp

NETWORK_FILE = "data/initial.xiidm"
VOLTAGE_LEVEL = "CRENEP3"

network = pp.network.load(NETWORK_FILE)

network.write_single_line_diagram_svg(
    VOLTAGE_LEVEL,
    "CRENEP3_single_line.svg",
)

print("Schéma généré : CRENEP3_single_line.svg")

