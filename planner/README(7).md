# `planner/` — moteur de planification

Le dossier `planner` contient le cœur du projet : représentation du poste Node/Breaker, calcul topologique, règles de manœuvre, recherche A*, projection nodale et validation.

## 1. Organisation

```text
planner/
├── model.py
├── xiidm.py
├── topology.py
├── search.py
├── verification.py
├── electrical.py
├── partition.py
├── projection.py
├── antecedents.py
├── io.py
└── __init__.py
```

## 2. Modèle détaillé

`model.py` définit notamment `SwitchSpec`, `EquipmentSpec`, `BusbarSpec`, `CellSpec`, `PlanningProblem` et `NetworkState`.

Un état est immuable et une action modifie un seul interrupteur. Le coût d'une manœuvre vaut actuellement 1.

## 3. Import XIIDM

`xiidm.py` utilise PyPowSyBl pour lire la topologie Node/Breaker d'un niveau de tension :

```python
problem_from_xiidm(initial, target, voltage_level_id, overlay=...)
```

L'extraction récupère les nœuds, interrupteurs, Busbar Sections et équipements. Un overlay peut préciser les appareils fixes/manipulables, rôles, équipements protégés et contraintes.

## 4. Moteur topologique

`TopologyEngine` fournit notamment :

- les composantes connexes ;
- les jeux de barres atteints par une cellule ;
- la connectivité en excluant un interrupteur ;
- la connectivité extérieure à une cellule ;
- la partition nodale ;
- une borne de coût pour une connexion auxiliaire.

Les calculs coûteux sont mémoïsés pendant A*.

## 5. Règles de manœuvre

`PlanningSession` dans `search.py` décide quelles actions sont applicables.

Les règles empêchent notamment la modification d'un appareil fixe, certaines manœuvres de sectionneurs sous disjoncteur fermé, des couplages non autorisés de jeux de barres, des indisponibilités temporaires excessives et la perte d'équipements protégés.

Les transferts de barres peuvent être autorisés lorsqu'un chemin parallèle rend la manœuvre topologiquement admissible.

## 6. Recherche A*

`astar_search` utilise :

\[
f(x)=g(x)+h(x).
\]

Heuristiques disponibles :

```text
zero
hamming
expert
topological
combined
```

La Hamming est :

\[
h_H(x)=\sum_s \mathbf{1}[x_s\neq x_s^\star].
\]

L'heuristique experte renforce cette borne sur certaines cellules à double jeu de barres en tenant compte du coût minimal certifié d'une coupure ou d'un transfert temporaire.

La version combinée utilise :

\[
h_{combined}(x)=\max(h_{expert}(x),h_{topological}(x)).
\]

## 7. Cible nodale

`projection.py` projette un état détaillé vers sa partition nodale. Le mode nodal cherche :

\[
\min_{x_f\in\pi^{-1}(T^\star)} d_M(x_0,x_f).
\]

`antecedents.py` énumère les configurations détaillées réalisant la cible et `astar_over_antecedents` exécute A* vers chaque antécédent admissible.

Une troncature avec `--max-assignments` supprime la garantie d'optimalité globale.

## 8. Vérification symbolique

`verification.py` rejoue indépendamment toutes les actions trouvées par A* et vérifie la validité des transitions ainsi que l'état final.

## 9. Validation électrique

`electrical.py` est appelé **après A\*** et rejoue :

```text
T0 -> STI_1 -> STI_2 -> ... -> STI_n
```

Pour les essais actuels, les contrôles prioritaires sont :

- convergence du load-flow AC ;
- limites thermiques `CURRENT`, `ACTIVE_POWER` et `APPARENT_POWER` lorsqu'elles sont disponibles ;
- déphasage avant les fermetures nécessitant un contrôle de synchronisme.

Les limites temporaires sont sélectionnées selon `expected_step_duration_s`.

Cette séparation évite d'exécuter un load-flow sur chaque état généré par A*.

## 10. Utilisation minimale

```python
from planner.xiidm import problem_from_xiidm
from planner.search import astar_search

problem = problem_from_xiidm(
    "initial.xiidm",
    "target.xiidm",
    "CRENEP3",
)

result = astar_search(problem, heuristic="expert")
```

Pour l'utilisation normale, `run.py` reste le point d'entrée recommandé.
