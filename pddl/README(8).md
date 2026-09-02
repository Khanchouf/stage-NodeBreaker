# `pddl/` — formulation PDDL

Le dossier `pddl` fournit une seconde représentation du problème en **Planning Domain Definition Language (PDDL)**. Elle est complémentaire du planificateur A* Python.

## 1. Fichiers

```text
pddl/
├── domain.pddl
├── generator.py
└── __init__.py
```

## 2. Domaine

`domain.pddl` décrit les disjoncteurs, sectionneurs, cellules, jeux de barres, équipements, états ouvert/fermé et plusieurs relations locales de sécurité.

Les actions couvrent notamment l'ouverture/fermeture de disjoncteurs, sectionneurs isolés, sectionneurs en boucle courte, coupleurs et appareils de sectionnement.

Chaque manœuvre augmente `total-cost` de 1.

## 3. Génération d'un problème

`generator.py` transforme un `PlanningProblem` en instance PDDL.

```bash
python run.py pddl \
  initial.xiidm target.xiidm CRENEP3 \
  generated/pddl
```

## 4. Relation avec A*

```text
              PlanningProblem
              /             \
             v               v
       A* Python          PDDL export
             |               |
             v               v
    planner spécialisé   planner générique
```

Le moteur Python calcule dynamiquement la connectivité Node/Breaker avec `TopologyEngine`. Le domaine PDDL reste volontairement plus local et n'encode pas toute la connectivité transitive.

Le PDDL n'est donc pas une traduction ligne par ligne de `search.py`, mais une formulation alternative du même problème métier.

## 5. Cible et coût

Le PDDL exporté correspond actuellement à une **cible détaillée**. Dans le mode nodal Python, l'antécédent détaillé sélectionné peut ensuite être exporté.

```lisp
(:metric minimize (total-cost))
```

## 6. Validation électrique

Le domaine PDDL n'exécute pas de load-flow. La validation physique reste assurée par PyPowSyBl après l'obtention d'une séquence de manœuvres.

## 7. Usage du dossier PDDL

Cette partie sert principalement à :

- comparer A* à un planificateur générique ;
- rendre explicites les préconditions et effets ;
- expérimenter d'autres heuristiques de planification.

Pour les calculs topologiques fins, le moteur Python reste la référence.
