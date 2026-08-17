from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class SwitchKind(str, Enum):
    BREAKER = "BREAKER"
    DISCONNECTOR = "DISCONNECTOR"
    LOAD_BREAK_SWITCH = "LOAD_BREAK_SWITCH"


class SwitchRole(str, Enum):
    FEEDER_BREAKER = "FEEDER_BREAKER"
    FEEDER_DISCONNECTOR = "FEEDER_DISCONNECTOR"
    COUPLER = "COUPLER"
    SECTIONING = "SECTIONING"
    OTHER = "OTHER"


class EquipmentKind(str, Enum):
    LINE = "LINE"
    TWO_WINDINGS_TRANSFORMER = "TWO_WINDINGS_TRANSFORMER"
    THREE_WINDINGS_TRANSFORMER = "THREE_WINDINGS_TRANSFORMER"
    GENERATOR = "GENERATOR"
    BATTERY = "BATTERY"
    LOAD = "LOAD"
    DANGLING_LINE = "DANGLING_LINE"
    SHUNT = "SHUNT"
    STATIC_VAR_COMPENSATOR = "STATIC_VAR_COMPENSATOR"
    HVDC_CONVERTER = "HVDC_CONVERTER"
    OTHER = "OTHER"


class CellKind(str, Enum):
    DEPARTURE = "DEPARTURE"
    COUPLING = "COUPLING"
    SECTIONING = "SECTIONING"
    INTERNAL = "INTERNAL"
    OMNIBUS = "OMNIBUS"


class PlanningMode(str, Enum):
    SMOOTH = "SMOOTH"
    AGGRESSIVE = "AGGRESSIVE"


@dataclass(frozen=True, slots=True)
class BusbarSpec:
    id: str
    node: str
    group: str | None = None
    section: str | None = None


@dataclass(frozen=True, slots=True)
class EquipmentSpec:
    id: str
    kind: EquipmentKind
    nodes: tuple[str, ...]
    protected: bool = False
    source: bool = False
    load: bool = False


@dataclass(frozen=True, slots=True)
class SwitchSpec:
    id: str
    kind: SwitchKind
    node1: str
    node2: str
    initial_closed: bool
    target_closed: bool
    fixed: bool = False
    retained: bool = False
    role: SwitchRole = SwitchRole.OTHER
    voltage_level_id: str | None = None

    def operation_cost(self, close: bool) -> int:
        """Every primitive OPEN/CLOSE operation has unit cost."""
        del close
        return 1


@dataclass(frozen=True, slots=True)
class CellSpec:
    id: str
    kind: CellKind
    node_ids: frozenset[str]
    switch_ids: frozenset[str]
    equipment_ids: frozenset[str]
    busbar_ids: frozenset[str]
    breaker_ids: frozenset[str] = frozenset()
    disconnector_ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class PlanningConstraints:
    allow_protected_outage: bool = False
    allow_unsafe_multi_busbar: bool = False
    max_temporary_outages: int | None = 1
    enforce_disconnector_offload_rule: bool = True
    enforce_sectioning_rule: bool = True
    strict_sectioning_without_sources: bool = False
    require_exact_fixed_state: bool = True


@dataclass(frozen=True, slots=True)
class PlanningProblem:
    """Static description of a planning problem with one detailed target state."""

    name: str
    nodes: tuple[str, ...]
    internal_connections: tuple[tuple[str, str], ...]
    busbars: tuple[BusbarSpec, ...]
    equipment: tuple[EquipmentSpec, ...]
    switches: tuple[SwitchSpec, ...]
    cells: tuple[CellSpec, ...] = ()
    mode: PlanningMode = PlanningMode.SMOOTH
    constraints: PlanningConstraints = field(default_factory=PlanningConstraints)

    _switch_by_id: Mapping[str, SwitchSpec] = field(init=False, repr=False, compare=False)
    _switch_index: Mapping[str, int] = field(init=False, repr=False, compare=False)
    _equipment_by_id: Mapping[str, EquipmentSpec] = field(init=False, repr=False, compare=False)
    _busbar_by_id: Mapping[str, BusbarSpec] = field(init=False, repr=False, compare=False)
    _busbar_by_node: Mapping[str, BusbarSpec] = field(init=False, repr=False, compare=False)
    _cell_by_id: Mapping[str, CellSpec] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_switch_by_id", MappingProxyType({s.id: s for s in self.switches}))
        object.__setattr__(self, "_switch_index", MappingProxyType({s.id: i for i, s in enumerate(self.switches)}))
        object.__setattr__(self, "_equipment_by_id", MappingProxyType({e.id: e for e in self.equipment}))
        object.__setattr__(self, "_busbar_by_id", MappingProxyType({b.id: b for b in self.busbars}))
        object.__setattr__(self, "_busbar_by_node", MappingProxyType({b.node: b for b in self.busbars}))
        object.__setattr__(self, "_cell_by_id", MappingProxyType({c.id: c for c in self.cells}))
        self.validate()

    @property
    def switch_by_id(self) -> Mapping[str, SwitchSpec]:
        return self._switch_by_id

    @property
    def switch_index(self) -> Mapping[str, int]:
        return self._switch_index

    @property
    def equipment_by_id(self) -> Mapping[str, EquipmentSpec]:
        return self._equipment_by_id

    @property
    def busbar_by_id(self) -> Mapping[str, BusbarSpec]:
        return self._busbar_by_id

    @property
    def busbar_by_node(self) -> Mapping[str, BusbarSpec]:
        return self._busbar_by_node

    @property
    def cell_by_id(self) -> Mapping[str, CellSpec]:
        return self._cell_by_id

    def validate(self) -> None:
        if not self.switches:
            raise ValueError("Le problème doit contenir au moins un switch.")
        if len(set(self.nodes)) != len(self.nodes):
            raise ValueError("Les identifiants de nœuds doivent être uniques.")
        node_ids = set(self.nodes)

        if len(self._switch_by_id) != len(self.switches):
            raise ValueError("Les identifiants de switches doivent être uniques.")
        if len(self._equipment_by_id) != len(self.equipment):
            raise ValueError("Les identifiants d'équipements doivent être uniques.")
        if len(self._busbar_by_id) != len(self.busbars):
            raise ValueError("Les identifiants de barres doivent être uniques.")
        if len(self._busbar_by_node) != len(self.busbars):
            raise ValueError("Deux BusbarSpec ne peuvent pas partager le même nœud.")
        if len(self._cell_by_id) != len(self.cells):
            raise ValueError("Les identifiants de cellules doivent être uniques.")

        max_out = self.constraints.max_temporary_outages
        if max_out is not None and max_out < 0:
            raise ValueError("max_temporary_outages doit être positif, nul ou None.")

        for switch in self.switches:
            if switch.node1 not in node_ids or switch.node2 not in node_ids:
                raise ValueError(f"Le switch {switch.id} référence un nœud absent.")
            if (
                self.constraints.require_exact_fixed_state
                and switch.fixed
                and switch.initial_closed != switch.target_closed
            ):
                raise ValueError(
                    f"Le switch fixe {switch.id} diffère de la cible détaillée."
                )

        for node1, node2 in self.internal_connections:
            if node1 not in node_ids or node2 not in node_ids:
                raise ValueError("Une connexion interne référence un nœud absent.")

        for busbar in self.busbars:
            if busbar.node not in node_ids:
                raise ValueError(f"La barre {busbar.id} référence un nœud absent.")

        for equipment in self.equipment:
            if not equipment.nodes:
                raise ValueError(f"L'équipement {equipment.id} n'a aucun nœud.")
            missing = set(equipment.nodes) - node_ids
            if missing:
                raise ValueError(
                    f"L'équipement {equipment.id} référence des nœuds absents : {sorted(missing)}"
                )

        for cell in self.cells:
            unknown_nodes = set(cell.node_ids) - node_ids
            unknown_switches = set(cell.switch_ids) - set(self._switch_by_id)
            unknown_equipment = set(cell.equipment_ids) - set(self._equipment_by_id)
            unknown_busbars = set(cell.busbar_ids) - set(self._busbar_by_id)
            if unknown_nodes or unknown_switches or unknown_equipment or unknown_busbars:
                raise ValueError(
                    f"La cellule {cell.id} contient des références inconnues : "
                    f"nodes={sorted(unknown_nodes)}, switches={sorted(unknown_switches)}, "
                    f"equipment={sorted(unknown_equipment)}, busbars={sorted(unknown_busbars)}."
                )

            if not cell.breaker_ids <= cell.switch_ids:
                raise ValueError(
                    f"Les breaker_ids de {cell.id} doivent appartenir à switch_ids."
                )
            if not cell.disconnector_ids <= cell.switch_ids:
                raise ValueError(
                    f"Les disconnector_ids de {cell.id} doivent appartenir à switch_ids."
                )
            for switch_id in cell.breaker_ids:
                if self._switch_by_id[switch_id].kind is not SwitchKind.BREAKER:
                    raise ValueError(
                        f"{switch_id} est déclaré breaker dans {cell.id} mais n'est pas un BREAKER."
                    )
            for switch_id in cell.disconnector_ids:
                if self._switch_by_id[switch_id].kind is not SwitchKind.DISCONNECTOR:
                    raise ValueError(
                        f"{switch_id} est déclaré disconnector dans {cell.id} mais n'est pas un DISCONNECTOR."
                    )


@dataclass(frozen=True, slots=True)
class NetworkState:
    closed_bits: tuple[bool, ...]

    @classmethod
    def initial(cls, problem: PlanningProblem) -> "NetworkState":
        return cls(tuple(s.initial_closed for s in problem.switches))

    @classmethod
    def target(cls, problem: PlanningProblem) -> "NetworkState":
        return cls(tuple(s.target_closed for s in problem.switches))

    def is_closed(self, problem: PlanningProblem, switch_id: str) -> bool:
        return self.closed_bits[problem.switch_index[switch_id]]

    def with_switch(self, problem: PlanningProblem, switch_id: str, *, closed: bool) -> "NetworkState":
        index = problem.switch_index[switch_id]
        values = list(self.closed_bits)
        values[index] = closed
        return NetworkState(tuple(values))

    def as_dict(self, problem: PlanningProblem) -> dict[str, bool]:
        if len(self.closed_bits) != len(problem.switches):
            raise ValueError("La taille de NetworkState ne correspond pas au nombre de switches.")
        return {switch.id: self.closed_bits[i] for i, switch in enumerate(problem.switches)}
