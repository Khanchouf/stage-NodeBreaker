import pypowsybl as pp

NETWORK_FILE = "data/initial.xiidm"
VOLTAGE_LEVEL = ".A.ZA 6"

network = pp.network.load(NETWORK_FILE)

network.write_single_line_diagram_svg(
    VOLTAGE_LEVEL,
    ".A.ZA 6_single_line.svg",
)

print("Schéma généré : .A.ZA 6_single_line.svg")

