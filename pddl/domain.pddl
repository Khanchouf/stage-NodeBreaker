;; Enriched but deliberately local Node-Breaker domain.
;; Expensive transitive graph predicates (reachability/path-without-switch) are
;; intentionally left to the Python TopologyEngine.

(define (domain node-breaker-detailed-planning)
  (:requirements
    :strips :typing :negative-preconditions :adl :conditional-effects
    :fluents :action-costs :equality
  )

  (:types
    node
    busbar-node equipment-node internal-node - node
    switch
    breaker disconnector load-break-switch - switch
    cell departure-cell coupling-cell sectioning-cell omnibus-cell internal-cell - cell
    busbar
    equipment
  )

  (:predicates
    ;; Dynamic switch state
    (closed ?s - switch)
    (fixed ?s - switch)

    ;; Static Node-Breaker structure
    (endpoint-1 ?s - switch ?n - node)
    (endpoint-2 ?s - switch ?n - node)
    (internal-link ?n1 - node ?n2 - node)
    (busbar-at ?b - busbar ?n - busbar-node)
    (equipment-at ?e - equipment ?n - equipment-node)

    ;; Functional structure
    (in-cell ?s - switch ?c - cell)
    (contains-equipment ?c - cell ?e - equipment)
    (protects ?b - breaker ?c - cell)
    (load-break-protects ?s - load-break-switch ?c - cell)
    (disconnector-to-bar ?d - disconnector ?c - cell ?b - busbar)
    (cell-connected-to ?c - cell ?b - busbar)

    ;; Local derived state maintained by actions
    (cell-isolated ?c - cell)
    (cell-prepared ?c - cell)
    (cell-in-service ?c - cell)
    (double-connected ?c - cell)

    ;; Bus coupling metadata
    (couples ?s - switch ?b1 - busbar ?b2 - busbar)
    (bars-coupled ?b1 - busbar ?b2 - busbar)

    ;; Equipment properties and local operational constraints
    (protected-equipment ?e - equipment)
    (source-equipment ?e - equipment)
    (load-equipment ?e - equipment)
    (protected-cell ?c - cell)
    (tracks-temporary-outage ?c - cell)

    ;; Sectioning is only enabled when externally authorized/generated.
    (sectioning-device ?s - disconnector)
    (sectioning-authorized ?s - disconnector)

    ;; Metadata: the resulting plan still requires electrical replay.
    (requires-synchronism-check ?s - switch)
    (requires-electrical-replay ?s - switch)
  )

  (:functions
    (total-cost)
    (temporary-outages)
    (max-temporary-outages)
  )

  (:action open-breaker
    :parameters (?b - breaker ?c - cell)
    :precondition (and
      (protects ?b ?c)
      (closed ?b)
      (not (fixed ?b))
      (not (protected-cell ?c))
      (cell-in-service ?c)
      (or
        (not (tracks-temporary-outage ?c))
        (< (temporary-outages) (max-temporary-outages))
      )
    )
    :effect (and
      (not (closed ?b))
      (cell-isolated ?c)
      (not (cell-in-service ?c))
      (when (tracks-temporary-outage ?c) (increase (temporary-outages) 1))
      (increase (total-cost) 1)
    )
  )

  (:action close-breaker
    :parameters (?b - breaker ?c - cell)
    :precondition (and
      (protects ?b ?c)
      (not (closed ?b))
      (not (fixed ?b))
      (cell-prepared ?c)
    )
    :effect (and
      (closed ?b)
      (not (cell-isolated ?c))
      (cell-in-service ?c)
      (when (tracks-temporary-outage ?c) (decrease (temporary-outages) 1))
      (increase (total-cost) 1)
    )
  )

  (:action open-load-break-switch
    :parameters (?s - load-break-switch ?c - cell)
    :precondition (and
      (load-break-protects ?s ?c)
      (closed ?s)
      (not (fixed ?s))
      (not (protected-cell ?c))
    )
    :effect (and
      (not (closed ?s))
      (cell-isolated ?c)
      (not (cell-in-service ?c))
      (increase (total-cost) 1)
    )
  )

  (:action close-load-break-switch
    :parameters (?s - load-break-switch ?c - cell)
    :precondition (and
      (load-break-protects ?s ?c)
      (not (closed ?s))
      (not (fixed ?s))
      (cell-prepared ?c)
    )
    :effect (and
      (closed ?s)
      (not (cell-isolated ?c))
      (cell-in-service ?c)
      (increase (total-cost) 1)
    )
  )

  ;; Long-loop / isolated-cell disconnector operations.
  (:action close-disconnector-isolated
    :parameters (?d - disconnector ?c - cell ?b - busbar)
    :precondition (and
      (disconnector-to-bar ?d ?c ?b)
      (not (closed ?d))
      (not (fixed ?d))
      (cell-isolated ?c)
      (not (cell-prepared ?c))
    )
    :effect (and
      (closed ?d)
      (cell-connected-to ?c ?b)
      (cell-prepared ?c)
      (increase (total-cost) 1)
    )
  )

  (:action open-disconnector-isolated
    :parameters (?d - disconnector ?c - cell ?b - busbar)
    :precondition (and
      (disconnector-to-bar ?d ?c ?b)
      (closed ?d)
      (not (fixed ?d))
      (cell-isolated ?c)
    )
    :effect (and
      (not (closed ?d))
      (not (cell-connected-to ?c ?b))
      (not (cell-prepared ?c))
      (increase (total-cost) 1)
    )
  )

  ;; Short-loop transfer using an explicitly represented direct bus coupling.
  (:action close-disconnector-short-loop
    :parameters (?d - disconnector ?c - cell ?target - busbar ?current - busbar)
    :precondition (and
      (disconnector-to-bar ?d ?c ?target)
      (not (closed ?d))
      (not (fixed ?d))
      (cell-in-service ?c)
      (cell-connected-to ?c ?current)
      (bars-coupled ?current ?target)
      (not (double-connected ?c))
    )
    :effect (and
      (closed ?d)
      (cell-connected-to ?c ?target)
      (double-connected ?c)
      (increase (total-cost) 1)
    )
  )

  (:action open-disconnector-short-loop
    :parameters (?d - disconnector ?c - cell ?old - busbar ?kept - busbar)
    :precondition (and
      (disconnector-to-bar ?d ?c ?old)
      (closed ?d)
      (not (fixed ?d))
      (double-connected ?c)
      (cell-connected-to ?c ?kept)
      (bars-coupled ?old ?kept)
    )
    :effect (and
      (not (closed ?d))
      (not (cell-connected-to ?c ?old))
      (not (double-connected ?c))
      (cell-prepared ?c)
      (increase (total-cost) 1)
    )
  )

  (:action close-coupler-breaker
    :parameters (?s - breaker ?b1 - busbar ?b2 - busbar)
    :precondition (and
      (couples ?s ?b1 ?b2)
      (not (closed ?s))
      (not (fixed ?s))
    )
    :effect (and
      (closed ?s)
      (bars-coupled ?b1 ?b2)
      (bars-coupled ?b2 ?b1)
      (increase (total-cost) 1)
    )
  )

  (:action open-coupler-breaker
    :parameters (?s - breaker ?b1 - busbar ?b2 - busbar)
    :precondition (and
      (couples ?s ?b1 ?b2)
      (closed ?s)
      (not (fixed ?s))
      (forall (?c - cell) (not (double-connected ?c)))
    )
    :effect (and
      (not (closed ?s))
      (not (bars-coupled ?b1 ?b2))
      (not (bars-coupled ?b2 ?b1))
      (increase (total-cost) 1)
    )
  )

  (:action open-sectioning-switch
    :parameters (?s - disconnector)
    :precondition (and
      (sectioning-device ?s)
      (sectioning-authorized ?s)
      (closed ?s)
      (not (fixed ?s))
    )
    :effect (and
      (not (closed ?s))
      (increase (total-cost) 1)
    )
  )

  (:action close-sectioning-switch
    :parameters (?s - disconnector)
    :precondition (and
      (sectioning-device ?s)
      (sectioning-authorized ?s)
      (not (closed ?s))
      (not (fixed ?s))
    )
    :effect (and
      (closed ?s)
      (increase (total-cost) 1)
    )
  )
)
