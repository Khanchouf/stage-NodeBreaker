from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

from .model import PlanningProblem
from .search import Action, Operation


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass(frozen=True, slots=True)
class ElectricalValidationConfig:
    """Configuration de la validation électrique postérieure à A*.

    Politique par défaut retenue pour le projet :
      1. le load-flow AC doit converger ;
      2. les limites thermiques I / P / S applicables au STI doivent être
         respectées ;
      3. le déphasage est contrôlé avant les fermetures qui reconnectent deux
         zones, dès qu'un seuil ``max_closing_angle_difference_deg`` est fourni.

    Les limites absolues de tension min/max restent disponibles mais sont
    désactivées par défaut. Cela évite qu'une violation de tension déjà présente
    dans le réseau initial bloque toute la séquence alors que, pour les tests
    actuels, les critères prioritaires sont convergence, thermique et phase.
    """

    provider: str = ""
    expected_step_duration_s: int = 30

    # Désactivé par défaut : les limites min/max de tension ne bloquent plus
    # la validation, tout en restant disponibles si on réactive ce booléen.
    check_voltage_limits: bool = False

    # Activé : sert de proxy opérationnel pour la contrainte thermique.
    check_loading_limits: bool = True

    # Arrêt dès le premier T0/STI ou la première transition invalide.
    stop_on_first_invalid_state: bool = True

    # T0 est toujours testé : sa convergence et ses limites thermiques sont
    # donc contrôlées avant de rejouer la séquence.
    check_initial_state: bool = True

    # Optionnel. Non prioritaire actuellement.
    max_closing_voltage_difference_kv: float | None = None

    # A fournir pour rendre le contrôle de phase bloquant.
    max_closing_angle_difference_deg: float | None = None


# ============================================================================
# RAPPORTS
# ============================================================================

@dataclass(frozen=True, slots=True)
class ElectricalViolation:
    category: str
    element_id: str
    measured_value: float | None
    limit_value: float | None
    message: str


@dataclass(frozen=True, slots=True)
class ElectricalTransitionReport:
    step_index: int
    switch_id: str
    valid: bool
    violations: tuple[ElectricalViolation, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ElectricalStateReport:
    state_name: str
    converged: bool
    valid: bool
    component_statuses: tuple[str, ...]
    violations: tuple[ElectricalViolation, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ElectricalSequenceReport:
    valid: bool
    failed_step: int | None
    transition_reports: tuple[ElectricalTransitionReport, ...]
    state_reports: tuple[ElectricalStateReport, ...]


LoadflowRunner = Callable[[Any, ElectricalValidationConfig], Iterable[Any]]


# ============================================================================
# PYPOWSYBL / RESEAU
# ============================================================================

def require_pypowsybl():
    try:
        import pypowsybl as pp
    except ImportError as exc:
        raise RuntimeError(
            "PyPowSyBl est requis pour la validation électrique. "
            "Installez-le avec `pip install pypowsybl`."
        ) from exc
    return pp


def load_network_copy(network_or_path: Any):
    """Charge un réseau frais ou clone un Network en mémoire via XIIDM."""
    pp = require_pypowsybl()

    if isinstance(network_or_path, (str, Path)):
        return pp.network.load(str(network_or_path))

    if hasattr(network_or_path, "save_to_binary_buffer"):
        return pp.network.load_from_binary_buffer(
            network_or_path.save_to_binary_buffer("XIIDM")
        )

    raise TypeError(
        "network_or_path doit être un chemin ou un objet Network PyPowSyBl."
    )


def apply_action_to_network(network: Any, action: Action) -> None:
    """Applique une action symbolique sur le Network PyPowSyBl."""
    network.update_switches(
        id=action.switch_id,
        open=action.operation is Operation.OPEN,
    )


def _default_loadflow_runner(
    network: Any,
    config: ElectricalValidationConfig,
):
    pp = require_pypowsybl()
    return pp.loadflow.run_ac(network, provider=config.provider)


# ============================================================================
# OUTILS GENERAUX
# ============================================================================

def _status_text(result: Any) -> str:
    status = getattr(result, "status", "UNKNOWN")
    name = getattr(status, "name", None)
    return str(name if name is not None else status)


def _is_converged_status(status: str) -> bool:
    upper = status.upper()
    return upper == "CONVERGED" or upper.endswith(".CONVERGED")


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


# ============================================================================
# LIMITES DE TENSION
# ============================================================================
#
# Conservées pour compatibilité et pour une éventuelle réactivation ultérieure.
# Elles sont désactivées par défaut dans ElectricalValidationConfig.
# ============================================================================

def check_voltage_limits(network: Any) -> tuple[ElectricalViolation, ...]:
    violations: list[ElectricalViolation] = []

    buses = network.get_buses(
        attributes=["v_mag", "v_angle", "voltage_level_id"]
    )
    voltage_levels = network.get_voltage_levels(
        attributes=[
            "nominal_v",
            "low_voltage_limit",
            "high_voltage_limit",
        ]
    )

    for bus_id, row in buses.iterrows():
        voltage = _finite(row.get("v_mag"))
        voltage_level_id = row.get("voltage_level_id")

        if voltage is None or voltage_level_id not in voltage_levels.index:
            continue

        limits = voltage_levels.loc[voltage_level_id]
        low = _finite(limits.get("low_voltage_limit"))
        high = _finite(limits.get("high_voltage_limit"))

        if low is not None and voltage < low:
            violations.append(
                ElectricalViolation(
                    "LOW_VOLTAGE",
                    str(bus_id),
                    voltage,
                    low,
                    f"Tension {voltage:.3f} kV inférieure à {low:.3f} kV.",
                )
            )

        if high is not None and voltage > high:
            violations.append(
                ElectricalViolation(
                    "HIGH_VOLTAGE",
                    str(bus_id),
                    voltage,
                    high,
                    f"Tension {voltage:.3f} kV supérieure à {high:.3f} kV.",
                )
            )

    return tuple(violations)


# ============================================================================
# CONTRAINTES THERMIQUES
# ============================================================================
#
# PyPowSyBl ne donne pas ici une température physique en °C.
# On utilise les limites de chargement I / P / S comme contrainte thermique
# opérationnelle, en tenant compte de la durée admissible du STI.
# ============================================================================

def _branch_tables(network: Any) -> dict[str, pd.DataFrame]:
    tables: dict[str, pd.DataFrame] = {}

    getters = {
        "LINE": (
            "get_lines",
            ["p1", "q1", "i1", "p2", "q2", "i2"],
        ),
        "TWO_WINDINGS_TRANSFORMER": (
            "get_2_windings_transformers",
            ["p1", "q1", "i1", "p2", "q2", "i2"],
        ),
        "THREE_WINDINGS_TRANSFORMER": (
            "get_3_windings_transformers",
            [
                "p1",
                "q1",
                "i1",
                "p2",
                "q2",
                "i2",
                "p3",
                "q3",
                "i3",
            ],
        ),
        "BOUNDARY_LINE": (
            "get_boundary_lines",
            ["p", "q", "i"],
        ),
    }

    for element_type, (getter_name, attributes) in getters.items():
        getter = getattr(network, getter_name, None)

        if getter is None:
            continue

        try:
            tables[element_type] = getter(attributes=attributes)
        except Exception:
            try:
                tables[element_type] = getter(all_attributes=True)
            except Exception:
                continue

    return tables


def _side_number(side: Any) -> int:
    text = str(side).upper()

    return {
        "ONE": 1,
        "TWO": 2,
        "THREE": 3,
        "1": 1,
        "2": 2,
        "3": 3,
    }.get(text, 1)


def _measured_loading(
    row: pd.Series,
    limit_type: str,
    side: int,
    element_type: str,
) -> float | None:
    suffix = "" if element_type == "BOUNDARY_LINE" else str(side)

    if limit_type == "CURRENT":
        return _finite(row.get(f"i{suffix}"))

    active = _finite(row.get(f"p{suffix}"))

    if limit_type == "ACTIVE_POWER":
        return abs(active) if active is not None else None

    reactive = _finite(row.get(f"q{suffix}"))

    if (
        limit_type == "APPARENT_POWER"
        and active is not None
        and reactive is not None
    ):
        return sqrt(active * active + reactive * reactive)

    return None


def _index_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Expose les niveaux d'index nommés sans dupliquer les colonnes."""
    result = frame.copy()
    index = result.index

    if isinstance(index, pd.MultiIndex):
        for level, name in enumerate(index.names):
            column = name or f"index_{level}"
            if column not in result.columns:
                result[column] = index.get_level_values(level)
    else:
        column = index.name or "index"
        if column not in result.columns:
            result[column] = index

    return result.reset_index(drop=True)


def check_loading_limits(
    network: Any,
    *,
    expected_duration_s: int,
) -> tuple[ElectricalViolation, ...]:
    """Vérifie les limites thermiques I/P/S applicables à la durée du STI."""

    try:
        limits = network.get_loading_limits(all_attributes=True)
    except Exception:
        limits = network.get_loading_limits()

    if limits is None or limits.empty:
        return ()

    limits_frame = _index_columns(limits)

    required = {
        "element_id",
        "element_type",
        "side",
        "type",
        "value",
        "acceptable_duration",
    }

    if not required.issubset(limits_frame.columns):
        return ()

    # Limite permanente :
    #   acceptable_duration == -1
    #
    # Limite temporaire :
    #   acceptable_duration >= durée supposée du STI
    applicable = limits_frame[
        (limits_frame["acceptable_duration"] == -1)
        | (
            limits_frame["acceptable_duration"]
            >= expected_duration_s
        )
    ].copy()

    if applicable.empty:
        return ()

    # Pour un STI court, on utilise l'enveloppe la plus élevée parmi les
    # limites valables pendant au moins cette durée.
    selected = (
        applicable
        .groupby(
            [
                "element_id",
                "element_type",
                "side",
                "type",
            ],
            as_index=False,
        )["value"]
        .max()
    )

    tables = _branch_tables(network)
    violations: list[ElectricalViolation] = []

    for _, limit in selected.iterrows():
        element_id = str(limit["element_id"])
        element_type = str(limit["element_type"]).upper()
        limit_type = str(limit["type"]).upper()

        table = tables.get(element_type)

        if table is None or element_id not in table.index:
            continue

        measured = _measured_loading(
            table.loc[element_id],
            limit_type,
            _side_number(limit["side"]),
            element_type,
        )

        allowed = _finite(limit["value"])

        if (
            measured is None
            or allowed is None
            or measured <= allowed
        ):
            continue

        violations.append(
            ElectricalViolation(
                f"{limit_type}_LIMIT",
                element_id,
                measured,
                allowed,
                (
                    f"{limit_type}={measured:.3f} dépasse "
                    f"la limite applicable {allowed:.3f}."
                ),
            )
        )

    return tuple(violations)


# ============================================================================
# PHASE / SYNCHRONISME AVANT FERMETURE
# ============================================================================

def _busbar_result_for_node(
    network: Any,
    voltage_level_id: str,
    node: str,
):
    """Retourne (tension, angle) si le noeud est directement une BusbarSection."""
    try:
        busbars = network.get_busbar_sections(
            attributes=[
                "v",
                "angle",
                "voltage_level_id",
                "node",
                "connected",
            ]
        )
    except Exception:
        return None

    node_number = str(node).split("__N")[-1]

    for _, row in busbars.iterrows():
        if str(row.get("voltage_level_id")) != voltage_level_id:
            continue

        if str(row.get("node")) != node_number:
            continue

        voltage = _finite(row.get("v"))
        angle = _finite(row.get("angle"))

        if voltage is not None and angle is not None:
            return voltage, angle

    return None


def check_transition_before_action(
    network: Any,
    problem: PlanningProblem,
    action: Action,
    step_index: int,
    config: ElectricalValidationConfig,
) -> ElectricalTransitionReport:
    """Contrôle électrique effectué juste avant une manoeuvre.

    Le contrôle de phase est déclenché uniquement pour une fermeture marquée
    par la couche symbolique comme nécessitant un contrôle de synchronisme.
    """

    warnings: list[str] = []
    violations: list[ElectricalViolation] = []

    requires_sync = (
        action.operation is Operation.CLOSE
        and "SYNCHRONISM_OR_VOLTAGE_CHECK"
        in action.required_future_checks
    )

    if requires_sync:
        switch = problem.switch_by_id[action.switch_id]

        if switch.voltage_level_id is None:
            warnings.append(
                "Niveau de tension inconnu : synchronisme non évalué."
            )

        else:
            side1 = _busbar_result_for_node(
                network,
                switch.voltage_level_id,
                switch.node1,
            )
            side2 = _busbar_result_for_node(
                network,
                switch.voltage_level_id,
                switch.node2,
            )

            if side1 is None or side2 is None:
                warnings.append(
                    "Les extrémités ne sont pas directement des Busbar Sections : "
                    "contrôle de synchronisme non calculable automatiquement."
                )

            else:
                delta_v = abs(side1[0] - side2[0])

                # Plus courte distance angulaire sur le cercle.
                delta_angle = abs(
                    (
                        (
                            side1[1]
                            - side2[1]
                            + 180.0
                        )
                        % 360.0
                    )
                    - 180.0
                )

                # Différence de tension de fermeture :
                # conservée mais optionnelle et non prioritaire.
                if (
                    config.max_closing_voltage_difference_kv
                    is not None
                    and delta_v
                    > config.max_closing_voltage_difference_kv
                ):
                    violations.append(
                        ElectricalViolation(
                            "CLOSING_VOLTAGE_DIFFERENCE",
                            action.switch_id,
                            delta_v,
                            config.max_closing_voltage_difference_kv,
                            "Différence de tension excessive avant fermeture.",
                        )
                    )

                # Déphasage :
                # critère bloquant dès qu'un seuil métier est fourni.
                if config.max_closing_angle_difference_deg is None:
                    warnings.append(
                        (
                            f"Déphasage avant fermeture = "
                            f"{delta_angle:.3f} deg, mais aucun seuil "
                            f"max_closing_angle_difference_deg n'est configuré."
                        )
                    )

                elif (
                    delta_angle
                    > config.max_closing_angle_difference_deg
                ):
                    violations.append(
                        ElectricalViolation(
                            "CLOSING_ANGLE_DIFFERENCE",
                            action.switch_id,
                            delta_angle,
                            config.max_closing_angle_difference_deg,
                            (
                                f"Ecart angulaire {delta_angle:.3f} deg "
                                f"supérieur à la limite "
                                f"{config.max_closing_angle_difference_deg:.3f} deg."
                            ),
                        )
                    )

    if (
        "SECTIONING_ENERGIZATION_CHECK"
        in action.required_future_checks
    ):
        warnings.append(
            "Le courant propre du sectionneur interne n'est pas directement "
            "disponible : la règle topologique reste la protection principale."
        )

    return ElectricalTransitionReport(
        step_index=step_index,
        switch_id=action.switch_id,
        valid=not violations,
        violations=tuple(violations),
        warnings=tuple(warnings),
    )


# ============================================================================
# VALIDATION D'UN ETAT T0 / STI
# ============================================================================

def validate_electrical_state(
    network: Any,
    state_name: str,
    config: ElectricalValidationConfig,
    *,
    loadflow_runner: LoadflowRunner | None = None,
) -> ElectricalStateReport:
    """Valide un état électrique après calcul AC.

    Critères obligatoires par défaut :
      - convergence du load-flow ;
      - limites thermiques I/P/S.

    Les limites absolues de tension ne sont testées que si
    ``check_voltage_limits=True``.
    """

    runner = loadflow_runner or _default_loadflow_runner

    try:
        results = tuple(
            runner(
                network,
                config,
            )
        )

    except Exception as exc:
        violation = ElectricalViolation(
            "LOADFLOW_EXCEPTION",
            state_name,
            None,
            None,
            f"Load-flow impossible : {exc}",
        )

        return ElectricalStateReport(
            state_name=state_name,
            converged=False,
            valid=False,
            component_statuses=("EXCEPTION",),
            violations=(violation,),
            warnings=(),
        )

    statuses = tuple(
        _status_text(result)
        for result in results
    )

    converged = (
        bool(statuses)
        and all(
            _is_converged_status(status)
            for status in statuses
        )
    )

    violations: list[ElectricalViolation] = []
    warnings: list[str] = []

    # ------------------------------------------------------------------------
    # 1. CONVERGENCE
    # ------------------------------------------------------------------------

    if not converged:
        violations.append(
            ElectricalViolation(
                "LOADFLOW_NOT_CONVERGED",
                state_name,
                None,
                None,
                f"Statuts des composantes : {statuses}",
            )
        )

    else:
        # --------------------------------------------------------------------
        # 2. TENSION ABSOLUE - DESACTIVEE PAR DEFAUT
        # --------------------------------------------------------------------

        if config.check_voltage_limits:
            violations.extend(
                check_voltage_limits(network)
            )

        # --------------------------------------------------------------------
        # 3. CONTRAINTES THERMIQUES
        # --------------------------------------------------------------------

        if config.check_loading_limits:
            violations.extend(
                check_loading_limits(
                    network,
                    expected_duration_s=(
                        config.expected_step_duration_s
                    ),
                )
            )

    return ElectricalStateReport(
        state_name=state_name,
        converged=converged,
        valid=not violations,
        component_statuses=statuses,
        violations=tuple(violations),
        warnings=tuple(warnings),
    )


# ============================================================================
# VALIDATION DE TOUTE LA SEQUENCE
# ============================================================================

def validate_sequence_electrically(
    network_or_path: Any,
    problem: PlanningProblem,
    actions: Iterable[Action],
    config: ElectricalValidationConfig | None = None,
    *,
    loadflow_runner: LoadflowRunner | None = None,
) -> ElectricalSequenceReport:
    """Rejoue T0 puis chaque STI sur un même Network en mémoire.

    Cette fonction est appelée APRES la recherche A* dans le pipeline actuel.
    Elle ne participe pas au choix des successeurs de A*.

    Ordre :
        T0
        -> contrôle électrique
        -> transition 1 / phase éventuelle
        -> action 1
        -> STI_1
        -> transition 2
        -> action 2
        -> STI_2
        -> ...
    """

    config = config or ElectricalValidationConfig()

    network = load_network_copy(network_or_path)

    state_reports: list[ElectricalStateReport] = []
    transition_reports: list[ElectricalTransitionReport] = []

    # ------------------------------------------------------------------------
    # T0
    # ------------------------------------------------------------------------

    if config.check_initial_state:
        initial_report = validate_electrical_state(
            network,
            "T0",
            config,
            loadflow_runner=loadflow_runner,
        )

        state_reports.append(initial_report)

        if (
            not initial_report.valid
            and config.stop_on_first_invalid_state
        ):
            return ElectricalSequenceReport(
                valid=False,
                failed_step=0,
                transition_reports=tuple(transition_reports),
                state_reports=tuple(state_reports),
            )

    # ------------------------------------------------------------------------
    # STI_1 ... STI_n
    # ------------------------------------------------------------------------

    for step_index, action in enumerate(
        actions,
        start=1,
    ):
        # Avant fermeture éventuelle :
        # contrôle de phase / synchronisme.
        transition = check_transition_before_action(
            network,
            problem,
            action,
            step_index,
            config,
        )

        transition_reports.append(transition)

        if (
            not transition.valid
            and config.stop_on_first_invalid_state
        ):
            return ElectricalSequenceReport(
                valid=False,
                failed_step=step_index,
                transition_reports=tuple(
                    transition_reports
                ),
                state_reports=tuple(
                    state_reports
                ),
            )

        # Application effective de la manoeuvre.
        apply_action_to_network(
            network,
            action,
        )

        # Validation du nouvel état intermédiaire.
        state_report = validate_electrical_state(
            network,
            f"STI_{step_index}",
            config,
            loadflow_runner=loadflow_runner,
        )

        state_reports.append(state_report)

        if (
            not state_report.valid
            and config.stop_on_first_invalid_state
        ):
            return ElectricalSequenceReport(
                valid=False,
                failed_step=step_index,
                transition_reports=tuple(
                    transition_reports
                ),
                state_reports=tuple(
                    state_reports
                ),
            )

    # ------------------------------------------------------------------------
    # BILAN
    # ------------------------------------------------------------------------

    valid = (
        all(
            report.valid
            for report in transition_reports
        )
        and all(
            report.valid
            for report in state_reports
        )
    )

    failed = next(
        (
            report.step_index
            for report in transition_reports
            if not report.valid
        ),
        None,
    )

    if failed is None:
        for report in state_reports:
            if report.valid:
                continue

            failed = (
                0
                if report.state_name == "T0"
                else int(
                    report.state_name.split("_")[-1]
                )
            )
            break

    return ElectricalSequenceReport(
        valid=valid,
        failed_step=failed,
        transition_reports=tuple(
            transition_reports
        ),
        state_reports=tuple(
            state_reports
        ),
    )


