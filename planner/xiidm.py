from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .model import (
    BusbarSpec,
    EquipmentKind,
    EquipmentSpec,
    PlanningConstraints,
    PlanningMode,
    PlanningProblem,
    SwitchKind,
    SwitchRole,
    SwitchSpec,
)
from .search import Action
from .topology import derive_cells, infer_switch_roles


_SOURCE_TYPES = {
    "LINE",
    "TWO_WINDINGS_TRANSFORMER",
    "THREE_WINDINGS_TRANSFORMER",
    "DANGLING_LINE",
    "GENERATOR",
    "BATTERY",
    "VSC_CONVERTER_STATION",
}
_LOAD_TYPES = {"LOAD"}


def require_pypowsybl():
    try:
        import pypowsybl as pp
    except ImportError as exc:
        raise RuntimeError(
            "PyPowSyBl n'est pas installé. Utilisez `pip install pypowsybl`."
        ) from exc
    return pp


def _load_overlay(overlay: Mapping[str, Any] | str | Path | None) -> dict[str, Any]:
    if overlay is None:
        return {}
    if isinstance(overlay, Mapping):
        return dict(overlay)
    return json.loads(Path(overlay).read_text(encoding="utf-8"))


def _switch_kind(value: Any) -> SwitchKind:
    value = str(value).upper()
    if value == "BREAKER":
        return SwitchKind.BREAKER
    if value == "DISCONNECTOR":
        return SwitchKind.DISCONNECTOR
    return SwitchKind.LOAD_BREAK_SWITCH


def _equipment_kind(value: Any) -> EquipmentKind:
    aliases = {
        "LINE": EquipmentKind.LINE,
        "TWO_WINDINGS_TRANSFORMER": EquipmentKind.TWO_WINDINGS_TRANSFORMER,
        "THREE_WINDINGS_TRANSFORMER": EquipmentKind.THREE_WINDINGS_TRANSFORMER,
        "GENERATOR": EquipmentKind.GENERATOR,
        "BATTERY": EquipmentKind.BATTERY,
        "LOAD": EquipmentKind.LOAD,
        "DANGLING_LINE": EquipmentKind.DANGLING_LINE,
        "SHUNT_COMPENSATOR": EquipmentKind.SHUNT,
        "STATIC_VAR_COMPENSATOR": EquipmentKind.STATIC_VAR_COMPENSATOR,
        "VSC_CONVERTER_STATION": EquipmentKind.HVDC_CONVERTER,
    }
    return aliases.get(str(value).upper(), EquipmentKind.OTHER)


def _explicit_role(
    switch_id: str,
    kind: SwitchKind,
    node1: str,
    node2: str,
    busbar_nodes: set[str],
    overlay: dict[str, Any],
) -> SwitchRole:
    configured = overlay.get("switch_roles", {}).get(switch_id)
    if configured is not None:
        return SwitchRole(str(configured).upper())
    if node1 in busbar_nodes and node2 in busbar_nodes:
        return SwitchRole.COUPLER if kind is not SwitchKind.DISCONNECTOR else SwitchRole.SECTIONING
    return SwitchRole.OTHER


def problem_from_networks(
    initial_network: Any,
    target_network: Any,
    voltage_level_id: str,
    *,
    overlay: Mapping[str, Any] | str | Path | None = None,
) -> PlanningProblem:
    """Extract a detailed planning problem directly from two Network objects."""
    overlay_data = _load_overlay(overlay)
    initial_topology = initial_network.get_node_breaker_topology(voltage_level_id)
    target_topology = target_network.get_node_breaker_topology(voltage_level_id)
    initial_switches = initial_topology.switches
    target_switches = target_topology.switches

    if set(initial_switches.index) != set(target_switches.index):
        raise ValueError("Les réseaux initial et cible n'ont pas les mêmes switches.")
    if set(initial_topology.nodes.index) != set(target_topology.nodes.index):
        raise ValueError("Les réseaux initial et cible n'ont pas les mêmes nœuds Node-Breaker.")

    node_name = {
        raw_node: f"{voltage_level_id}__N{raw_node}"
        for raw_node in initial_topology.nodes.index
    }
    nodes = tuple(node_name[node] for node in initial_topology.nodes.index)

    busbars: list[BusbarSpec] = []
    equipment_nodes: dict[str, list[str]] = {}
    equipment_types: dict[str, str] = {}
    for raw_node, row in initial_topology.nodes.iterrows():
        connectable_id = row.get("connectable_id")
        connectable_type = str(row.get("connectable_type") or "").upper()
        if connectable_id is None or str(connectable_id).lower() == "nan" or not str(connectable_id):
            continue
        connectable_id = str(connectable_id)
        if connectable_type == "BUSBAR_SECTION":
            metadata = overlay_data.get("busbars", {}).get(connectable_id, {})
            busbars.append(
                BusbarSpec(
                    connectable_id,
                    node_name[raw_node],
                    metadata.get("group"),
                    metadata.get("section"),
                )
            )
        else:
            equipment_nodes.setdefault(connectable_id, []).append(node_name[raw_node])
            equipment_types[connectable_id] = connectable_type

    protected = set(overlay_data.get("protected_equipment", []))
    forced_sources = set(overlay_data.get("source_equipment", []))
    forced_loads = set(overlay_data.get("load_equipment", []))
    equipment = tuple(
        EquipmentSpec(
            equipment_id,
            _equipment_kind(equipment_types[equipment_id]),
            tuple(nodes_for_equipment),
            protected=equipment_id in protected,
            source=(
                equipment_id in forced_sources
                or equipment_types[equipment_id] in _SOURCE_TYPES
            ),
            load=(
                equipment_id in forced_loads
                or equipment_types[equipment_id] in _LOAD_TYPES
            ),
        )
        for equipment_id, nodes_for_equipment in sorted(equipment_nodes.items())
    )

    busbar_nodes = {busbar.node for busbar in busbars}
    explicitly_fixed = set(overlay_data.get("fixed_switches", []))
    movable_config = overlay_data.get("movable_switches")
    movable = set(movable_config) if movable_config is not None else None
    switches: list[SwitchSpec] = []
    for switch_id, row in initial_switches.iterrows():
        target_row = target_switches.loc[switch_id]
        raw_node1, raw_node2 = row["node1"], row["node2"]
        target_endpoints = {target_row["node1"], target_row["node2"]}
        if target_endpoints != {raw_node1, raw_node2}:
            raise ValueError(f"Les extrémités de {switch_id} diffèrent entre T0 et T1.")
        node1, node2 = node_name[raw_node1], node_name[raw_node2]
        kind = _switch_kind(row["kind"])
        fixed = str(switch_id) in explicitly_fixed or (
            movable is not None and str(switch_id) not in movable
        )
        switches.append(
            SwitchSpec(
                id=str(switch_id),
                kind=kind,
                node1=node1,
                node2=node2,
                initial_closed=not bool(row["open"]),
                target_closed=not bool(target_row["open"]),
                fixed=fixed,
                retained=bool(row.get("retained", False)),
                role=_explicit_role(
                    str(switch_id), kind, node1, node2, busbar_nodes, overlay_data
                ),
                voltage_level_id=voltage_level_id,
            )
        )

    internal_connections = tuple(
        (node_name[row["node1"]], node_name[row["node2"]])
        for _, row in initial_topology.internal_connections.iterrows()
    )
    constraints_data = overlay_data.get("constraints", {})
    constraints = PlanningConstraints(
        allow_protected_outage=constraints_data.get("allow_protected_outage", False),
        allow_unsafe_multi_busbar=constraints_data.get("allow_unsafe_multi_busbar", False),
        max_temporary_outages=constraints_data.get("max_temporary_outages", 1),
        enforce_disconnector_offload_rule=constraints_data.get(
            "enforce_disconnector_offload_rule", True
        ),
        enforce_sectioning_rule=constraints_data.get("enforce_sectioning_rule", True),
        strict_sectioning_without_sources=constraints_data.get(
            "strict_sectioning_without_sources", False
        ),
        require_exact_fixed_state=True,
    )
    preliminary = PlanningProblem(
        name=overlay_data.get("name", f"{voltage_level_id}_detailed_plan"),
        nodes=nodes,
        internal_connections=internal_connections,
        busbars=tuple(busbars),
        equipment=equipment,
        switches=tuple(switches),
        mode=PlanningMode(str(overlay_data.get("mode", "SMOOTH")).upper()),
        constraints=constraints,
    )
    cells = derive_cells(preliminary)
    roles = infer_switch_roles(preliminary, cells)
    return PlanningProblem(
        name=preliminary.name,
        nodes=preliminary.nodes,
        internal_connections=preliminary.internal_connections,
        busbars=preliminary.busbars,
        equipment=preliminary.equipment,
        switches=roles,
        cells=cells,
        mode=preliminary.mode,
        constraints=preliminary.constraints,
    )


def problem_from_xiidm(
    initial_path: str | Path,
    target_path: str | Path,
    voltage_level_id: str,
    *,
    overlay: Mapping[str, Any] | str | Path | None = None,
) -> PlanningProblem:
    pp = require_pypowsybl()
    initial = pp.network.load(str(initial_path))
    target = pp.network.load(str(target_path))
    return problem_from_networks(initial, target, voltage_level_id, overlay=overlay)


def apply_plan_to_network(network: Any, actions: tuple[Action, ...] | list[Action]) -> Any:
    for action in actions:
        network.update_switches(
            id=action.switch_id,
            open=action.operation.value == "OPEN",
        )
    return network


def save_planned_network(
    initial_path: str | Path,
    actions: tuple[Action, ...] | list[Action],
    output_path: str | Path,
) -> Path:
    pp = require_pypowsybl()
    network = pp.network.load(str(initial_path))
    apply_plan_to_network(network, actions)
    output = Path(output_path)
    network.save(output, format="XIIDM")
    return output
