from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path

import pandas as pd
import pypowsybl as pp

from planner.xiidm import problem_from_xiidm


# ============================================================
# CONFIGURATION
# ============================================================

INITIAL = "data/initial.xiidm"
VOLTAGE_LEVEL = "CONF5P1"

OUTPUT = "data/CONF5P1_structure.json"


# ============================================================
# UTILITAIRES JSON
# ============================================================

def json_value(value):
    """Convertit les objets Python/Pandas du projet en valeurs JSON."""
    if value is None:
        return None

    if isinstance(value, Enum):
        return value.value

    if is_dataclass(value):
        return {
            key: json_value(val)
            for key, val in asdict(value).items()
        }

    if isinstance(value, dict):
        return {
            str(key): json_value(val)
            for key, val in value.items()
        }

    if isinstance(value, (list, tuple, set, frozenset)):
        return [
            json_value(val)
            for val in value
        ]

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass

    return value


def dataframe_to_records(df):
    """Transforme un DataFrame indexé en dictionnaire JSON."""
    result = []

    for index, row in df.iterrows():
        record = {
            "id": json_value(index)
        }

        for column in df.columns:
            record[str(column)] = json_value(
                row[column]
            )

        result.append(record)

    return result


# ============================================================
# GRAPHE TOPOLOGIQUE
# ============================================================

def build_adjacency(
    nodes,
    switches,
    internal_connections,
):
    """
    Construit les voisins de chaque noeud.

    On distingue :
    - les connexions internes permanentes ;
    - les switchs ;
    - l'état ouvert/fermé du switch.
    """

    adjacency = {
        str(node_id): []
        for node_id in nodes.index
    }

    for _, row in internal_connections.iterrows():
        node1 = str(row["node1"])
        node2 = str(row["node2"])

        adjacency.setdefault(
            node1,
            []
        ).append(
            {
                "node": node2,
                "connection_type": "INTERNAL",
                "switch_id": None,
                "switch_kind": None,
                "open": False,
            }
        )

        adjacency.setdefault(
            node2,
            []
        ).append(
            {
                "node": node1,
                "connection_type": "INTERNAL",
                "switch_id": None,
                "switch_kind": None,
                "open": False,
            }
        )

    for switch_id, row in switches.iterrows():
        node1 = str(row["node1"])
        node2 = str(row["node2"])

        kind = str(row["kind"])
        is_open = bool(row["open"])

        edge1 = {
            "node": node2,
            "connection_type": "SWITCH",
            "switch_id": str(switch_id),
            "switch_kind": kind,
            "open": is_open,
        }

        edge2 = {
            "node": node1,
            "connection_type": "SWITCH",
            "switch_id": str(switch_id),
            "switch_kind": kind,
            "open": is_open,
        }

        adjacency.setdefault(
            node1,
            []
        ).append(edge1)

        adjacency.setdefault(
            node2,
            []
        ).append(edge2)

    return adjacency


def connected_components(
    nodes,
    switches,
    internal_connections,
):
    """
    Calcule les composantes connexes de l'état électrique courant.

    Les connexions internes sont toujours actives.
    Seuls les switchs fermés sont utilisés.
    """

    graph = {
        str(node_id): set()
        for node_id in nodes.index
    }

    for _, row in internal_connections.iterrows():
        node1 = str(row["node1"])
        node2 = str(row["node2"])

        graph[node1].add(node2)
        graph[node2].add(node1)

    for _, row in switches.iterrows():
        if bool(row["open"]):
            continue

        node1 = str(row["node1"])
        node2 = str(row["node2"])

        graph[node1].add(node2)
        graph[node2].add(node1)

    visited = set()
    components = []

    for start in graph:

        if start in visited:
            continue

        stack = [start]
        component = []

        while stack:

            node = stack.pop()

            if node in visited:
                continue

            visited.add(node)
            component.append(node)

            for neighbor in graph[node]:

                if neighbor not in visited:
                    stack.append(neighbor)

        components.append(
            sorted(component)
        )

    components.sort(
        key=len,
        reverse=True,
    )

    return components


# ============================================================
# EXTRACTION DES EQUIPEMENTS
# ============================================================

def extract_connectables(nodes):
    """
    Regroupe les noeuds par équipement/connectable XIIDM.
    """

    connectables = {}

    for node_id, row in nodes.iterrows():

        connectable_id = row.get(
            "connectable_id"
        )

        connectable_type = row.get(
            "connectable_type"
        )

        if connectable_id is None:
            continue

        try:
            if pd.isna(connectable_id):
                continue
        except Exception:
            pass

        connectable_id = str(
            connectable_id
        )

        if not connectable_id:
            continue

        if connectable_id not in connectables:
            connectables[
                connectable_id
            ] = {
                "id": connectable_id,
                "type": (
                    None
                    if pd.isna(connectable_type)
                    else str(connectable_type)
                ),
                "nodes": [],
            }

        connectables[
            connectable_id
        ]["nodes"].append(
            str(node_id)
        )

    return sorted(
        connectables.values(),
        key=lambda item: (
            str(item["type"]),
            item["id"],
        ),
    )


# ============================================================
# MAIN
# ============================================================

def main():

    initial_path = Path(INITIAL)
    output_path = Path(OUTPUT)

    if not initial_path.exists():
        raise FileNotFoundError(
            f"Fichier introuvable : "
            f"{initial_path.resolve()}"
        )

    print("=" * 75)
    print(
        f"EXTRACTION DE LA STRUCTURE DE {VOLTAGE_LEVEL}"
    )
    print("=" * 75)

    # --------------------------------------------------------
    # XIIDM / PyPowSyBl
    # --------------------------------------------------------

    network = pp.network.load(
        str(initial_path)
    )

    topology = (
        network
        .get_node_breaker_topology(
            VOLTAGE_LEVEL
        )
    )

    nodes = topology.nodes
    switches = topology.switches
    internal_connections = (
        topology.internal_connections
    )

    connectables = extract_connectables(
        nodes
    )

    busbars = [
        item
        for item in connectables
        if item["type"] == "BUSBAR_SECTION"
    ]

    equipment = [
        item
        for item in connectables
        if item["type"] != "BUSBAR_SECTION"
    ]

    adjacency = build_adjacency(
        nodes,
        switches,
        internal_connections,
    )

    components = connected_components(
        nodes,
        switches,
        internal_connections,
    )

    # --------------------------------------------------------
    # ANALYSE DU PLANNER
    # --------------------------------------------------------

    print(
        "Construction de la représentation "
        "utilisée par le planner..."
    )

    # T0 = target uniquement pour reconstruire le modèle.
    # Aucune recherche n'est effectuée.
    problem = problem_from_xiidm(
        initial_path,
        initial_path,
        VOLTAGE_LEVEL,
    )

    planner_switches = []

    for switch in problem.switches:

        planner_switches.append(
            {
                "id": switch.id,
                "kind": switch.kind.value,
                "role": switch.role.value,
                "node1": switch.node1,
                "node2": switch.node2,
                "initial_closed": switch.initial_closed,
                "fixed": switch.fixed,
                "retained": switch.retained,
            }
        )

    planner_busbars = []

    for busbar in problem.busbars:

        planner_busbars.append(
            {
                "id": busbar.id,
                "node": busbar.node,
                "group": busbar.group,
                "section": busbar.section,
            }
        )

    planner_equipment = []

    for eq in problem.equipment:

        planner_equipment.append(
            {
                "id": eq.id,
                "kind": eq.kind.value,
                "nodes": list(eq.nodes),
                "protected": eq.protected,
                "source": eq.source,
                "load": eq.load,
            }
        )

    planner_cells = []

    for cell in problem.cells:

        planner_cells.append(
        {
            "id": cell.id,
            "kind": cell.kind.value,
            "node_ids": sorted(cell.node_ids),
            "switch_ids": sorted(cell.switch_ids),
            "breaker_ids": sorted(cell.breaker_ids),
            "disconnector_ids": sorted(cell.disconnector_ids),
            "equipment_ids": sorted(cell.equipment_ids),
            "busbar_ids": sorted(cell.busbar_ids),
        }
    )



    # --------------------------------------------------------
    # STATISTIQUES
    # --------------------------------------------------------

    switch_kind_counts = {}

    for _, row in switches.iterrows():

        kind = str(row["kind"])

        switch_kind_counts[kind] = (
            switch_kind_counts.get(
                kind,
                0,
            )
            + 1
        )

    role_counts = {}

    for switch in problem.switches:

        role = switch.role.value

        role_counts[role] = (
            role_counts.get(
                role,
                0,
            )
            + 1
        )

    cell_kind_counts = {}

    for cell in problem.cells:

        kind = cell.kind.value

        cell_kind_counts[kind] = (
            cell_kind_counts.get(
                kind,
                0,
            )
            + 1
        )

    # --------------------------------------------------------
    # JSON FINAL
    # --------------------------------------------------------

    result = {

        "metadata": {
            "network_file": str(
                initial_path.resolve()
            ),
            "voltage_level_id": (
                VOLTAGE_LEVEL
            ),
        },

        "summary": {
            "nodes": len(nodes),
            "switches": len(switches),
            "internal_connections": len(
                internal_connections
            ),
            "busbar_sections": len(
                busbars
            ),
            "connectables": len(
                connectables
            ),
            "equipment": len(
                equipment
            ),
            "planner_cells": len(
                problem.cells
            ),
            "connected_components": len(
                components
            ),
            "switch_kinds": (
                switch_kind_counts
            ),
            "planner_switch_roles": (
                role_counts
            ),
            "planner_cell_kinds": (
                cell_kind_counts
            ),
        },

        # ====================================================
        # TOPOLOGIE XIIDM BRUTE
        # ====================================================

        "xiidm_topology": {

            "nodes": dataframe_to_records(
                nodes
            ),

            "switches": dataframe_to_records(
                switches
            ),

            "internal_connections":
                dataframe_to_records(
                    internal_connections
                ),

            "busbar_sections":
                busbars,

            "equipment":
                equipment,

            "connectables":
                connectables,

            "adjacency":
                adjacency,

            "connected_components": [
                {
                    "index": index,
                    "size": len(component),
                    "nodes": component,
                }
                for index, component
                in enumerate(
                    components,
                    start=1,
                )
            ],
        },

        # ====================================================
        # INTERPRETATION DU PLANNER
        # ====================================================

        "planner_topology": {

            "nodes": list(
                problem.nodes
            ),

            "internal_connections": [
                list(connection)
                for connection
                in problem.internal_connections
            ],

            "busbars":
                planner_busbars,

            "equipment":
                planner_equipment,

            "switches":
                planner_switches,

            "cells":
                planner_cells,
        },
    }

    # --------------------------------------------------------
    # ECRITURE
    # --------------------------------------------------------

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            json_value(result),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 75)
    print("RÉSUMÉ")
    print("=" * 75)

    print(
        f"Nœuds                 : "
        f"{len(nodes)}"
    )

    print(
        f"Switchs               : "
        f"{len(switches)}"
    )

    print(
        f"Connexions internes   : "
        f"{len(internal_connections)}"
    )

    print(
        f"Busbar sections       : "
        f"{len(busbars)}"
    )

    print(
        f"Équipements           : "
        f"{len(equipment)}"
    )

    print(
        f"Cellules détectées    : "
        f"{len(problem.cells)}"
    )

    print()

    print(
        "Types de switchs :",
        switch_kind_counts,
    )

    print(
        "Rôles détectés :",
        role_counts,
    )

    print(
        "Types de cellules :",
        cell_kind_counts,
    )

    print()

    print("=" * 75)
    print("SUCCÈS")
    print("=" * 75)

    print(
        f"Structure complète écrite dans :\n"
        f"{output_path.resolve()}"
    )


if __name__ == "__main__":
    main()

