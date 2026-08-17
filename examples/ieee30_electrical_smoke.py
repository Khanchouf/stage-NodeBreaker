from __future__ import annotations

"""Electrical-only smoke test.

IEEE 30 is useful for AC load-flow and operational-limit checks, but its
standard factory is not a detailed Node-Breaker switching case. It is therefore
kept separate from the maneuver-planning demo.
"""

from planner.electrical import ElectricalValidationConfig, validate_electrical_state
from planner.xiidm import require_pypowsybl


if __name__ == "__main__":
    pp = require_pypowsybl()
    network = pp.network.create_ieee30()
    report = validate_electrical_state(
        network,
        "IEEE30_T0",
        ElectricalValidationConfig(),
    )
    print(report)
