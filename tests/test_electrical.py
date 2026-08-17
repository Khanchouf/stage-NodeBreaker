from types import SimpleNamespace

import pandas as pd

import planner.electrical as electrical
from planner.electrical import ElectricalValidationConfig, validate_electrical_state
from planner.search import astar_search

from .helpers import double_busbar_problem


class FakeNetwork:
    def __init__(self, current=80.0):
        self.current = current
        self.switches = {}

    def update_switches(self, *, id, open):
        self.switches[id] = open

    def get_buses(self, attributes=None):
        del attributes
        return pd.DataFrame(
            {"v_mag": [225.0], "v_angle": [0.0], "voltage_level_id": ["VL"]},
            index=["BUS"],
        )

    def get_voltage_levels(self, attributes=None):
        del attributes
        return pd.DataFrame(
            {"nominal_v": [225.0], "low_voltage_limit": [220.0], "high_voltage_limit": [240.0]},
            index=["VL"],
        )

    def get_loading_limits(self, all_attributes=False):
        del all_attributes
        return pd.DataFrame(
            {
                "element_id": ["L"],
                "element_type": ["LINE"],
                "side": ["ONE"],
                "type": ["CURRENT"],
                "value": [100.0],
                "acceptable_duration": [-1],
            }
        )

    def get_lines(self, attributes=None, all_attributes=False):
        del attributes, all_attributes
        return pd.DataFrame(
            {"p1": [10.0], "q1": [2.0], "i1": [self.current], "p2": [-10.0], "q2": [-2.0], "i2": [self.current]},
            index=["L"],
        )

    def get_2_windings_transformers(self, **kwargs):
        del kwargs
        return pd.DataFrame()

    def get_3_windings_transformers(self, **kwargs):
        del kwargs
        return pd.DataFrame()

    def get_boundary_lines(self, **kwargs):
        del kwargs
        return pd.DataFrame()


def fake_loadflow(network, config):
    del network, config
    return [SimpleNamespace(status=SimpleNamespace(name="CONVERGED"))]


def test_electrical_state_accepts_valid_limits():
    report = validate_electrical_state(
        FakeNetwork(80.0), "T0", ElectricalValidationConfig(), loadflow_runner=fake_loadflow
    )
    assert report.valid
    assert report.converged


def test_electrical_state_detects_thermal_current_violation():
    report = validate_electrical_state(
        FakeNetwork(120.0), "T0", ElectricalValidationConfig(), loadflow_runner=fake_loadflow
    )
    assert not report.valid
    assert any(v.category == "CURRENT_LIMIT" for v in report.violations)


def test_sequence_replays_switches(monkeypatch):
    problem = double_busbar_problem()
    result = astar_search(problem)
    network = FakeNetwork(80.0)
    monkeypatch.setattr(electrical, "load_network_copy", lambda _: network)
    report = electrical.validate_sequence_electrically(
        network,
        problem,
        result.actions,
        loadflow_runner=fake_loadflow,
    )
    assert report.valid
    assert len(report.state_reports) == len(result.actions) + 1
    assert network.switches
