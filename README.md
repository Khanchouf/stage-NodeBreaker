# Node-Breaker Planner v3

Planificateur A* pour transformer une configuration **Node-Breaker détaillée** `T0` en une configuration détaillée `T1`, avec :

- coûts unitaires : une ouverture ou une fermeture coûte `1` ;
- contraintes logiques et topologiques pendant A* ;
- mémoïsation des composantes, connectivités et validations ;
- rejeu électrique PyPowSyBl de `T0`, puis de chaque `STI` ;
- export PDDL enrichi, mais sans fermeture transitive coûteuse du graphe ;
- exemple principal construit depuis `create_four_substations_node_breaker_network()`.

## Architecture

```text
node_breaker_planner_v3/
├── planner/
│   ├── model.py          # Modèle immuable, cible toujours DETAILED
│   ├── topology.py       # TopologyEngine et caches de connectivité
│   ├── search.py         # Contraintes, heuristiques et A*
│   ├── verification.py   # Rejeu symbolique et orchestration complète
│   ├── electrical.py     # Rejeu PyPowSyBl, AC, tension et limites I/P/S
│   ├── xiidm.py          # Extraction directe depuis deux Network/XIIDM
│   └── io.py             # JSON facultatif pour inspection et rapports
├── pddl/
│   ├── domain.pddl
│   └── generator.py
├── examples/
│   ├── four_substations_demo.py
│   └── ieee30_electrical_smoke.py
├── tests/
└── run.py
```

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

PyPowSyBl 1.15 prend en charge Python 3.10 à 3.14.

## Pipeline principal sans JSON obligatoire

```text
initial.xiidm + target.xiidm
              ↓
problem_from_xiidm()
              ↓
PlanningProblem en mémoire
              ↓
A* topologique
              ↓
rejeu symbolique
              ↓
rejeu électrique PyPowSyBl sur T0 et chaque STI
```

Le JSON extrait peut être produit pour inspection, mais il n’est pas nécessaire à la recherche.

## Lancer le démonstrateur PyPowSyBl réel

```powershell
python run.py demo-four-substations --output-dir generated\four_substations
```

Le script :

1. crée deux réseaux avec `pp.network.create_four_substations_node_breaker_network()` ;
2. transfère la travée du transformateur de `S1VL2_BBS1` vers `S1VL2_BBS2` ;
3. extrait directement le problème depuis les deux objets `Network` ;
4. lance A* ;
5. sauvegarde les deux XIIDM, le plan et le PDDL ;
6. rejoue chaque manœuvre avec un load-flow AC.

Les switches utilisés sont :

```text
S1VL2_BBS1_TWT_DISCONNECTOR
S1VL2_BBS2_TWT_DISCONNECTOR
S1VL2_TWT_BREAKER
```

Le disjoncteur conserve le même état cible, mais A* peut l’utiliser temporairement si aucune boucle courte n’est disponible.

## Planifier deux fichiers XIIDM

```powershell
python run.py plan initial.xiidm target.xiidm S1VL2 `
  --overlay config\my_overlay.json `
  --heuristic hamming `
  --output generated\plan.json `
  --problem-json generated\problem.json `
  --pddl-dir generated\pddl `
  --planned-network generated\planned.xiidm
```

Avec validation électrique :

```powershell
python run.py plan initial.xiidm target.xiidm S1VL2 `
  --overlay config\my_overlay.json `
  --electrical `
  --electrical-output generated\electrical_report.json `
  --step-duration 30
```

## But toujours détaillé

Le but est uniquement :

```math
\forall s,\quad x_s = x_s^\star.
```

Il n’existe plus de `GoalMode.NODAL` ni de `target_partition`.

## A* et optimalité

L’heuristique par défaut est Hamming :

```math
h(s)=\sum_e \mathbf 1[x_e(s)\neq x_e^\star].
```

Chaque action modifie un seul switch et coûte `1`. Hamming est donc admissible et cohérente. Le plan trouvé minimise le nombre de manœuvres dans le modèle logique et topologique.

Heuristiques disponibles :

```text
zero       Uniform-Cost Search, référence exacte
hamming    choix recommandé
expert     borne double jeu de barres certifiée, repli sur Hamming
```

## Programmation dynamique et mémoïsation

`TopologyEngine` conserve :

```text
state -> TopologySnapshot
(state, switches exclus) -> composantes connexes
(state, cellule exclue, barres) -> connectivité extérieure
```

`PlanningSession` conserve :

```text
(state, action) -> précondition de transition
state -> validité topologique
(state, heuristique) -> valeur h
state -> meilleur coût g dans A*
```

La boucle critique n’utilise pas NetworkX pour recalculer les composantes. Elle parcourt des listes d’adjacence d’indices entiers. Un `nx.MultiGraph` n’est matérialisé que pour l’inspection et le débogage.

Les statistiques sont ajoutées au résultat :

```json
{
  "snapshot_hits": 42,
  "snapshot_misses": 18,
  "excluded_hits": 11,
  "excluded_misses": 7
}
```

## Validation électrique

`planner/electrical.py` charge ou clone le réseau une seule fois, puis applique les actions en mémoire :

```python
network.update_switches(id=action.switch_id, open=True_or_false)
```

Pour chaque étape :

```text
pré-état
  └── contrôles de fermeture/synchronisme lorsque les données sont accessibles
application de la manœuvre
  └── pp.loadflow.run_ac(network)
      ├── convergence de toutes les composantes
      ├── tensions par rapport aux limites du VoltageLevel
      └── I / P / S par rapport aux loading limits applicables à la durée du STI
```

Les limites temporaires sont prises en compte avec `acceptable_duration`. Pour un STI de durée `d`, le validateur choisit l’enveloppe la plus élevée parmi les limites permanentes ou temporaires valables au moins `d` secondes.

### Limite importante

PyPowSyBl ne fournit pas nécessairement un courant exploitable directement pour chaque sectionneur interne idéal. La règle du sectionneur hors charge reste donc principalement topologique :

- disjoncteur de la cellule ouvert ; ou
- chemin parallèle déjà établi.

Le load-flow valide ensuite l’état obtenu et les branches surveillées.

## PDDL enrichi

Le PDDL contient désormais :

- les nœuds Node-Breaker ;
- les extrémités des switches ;
- les connexions internes ;
- les nœuds des barres et équipements ;
- les types d’équipements source/charge/protégé ;
- les cellules et leurs organes ;
- les `LOAD_BREAK_SWITCH` ;
- un compteur de coupures temporaires ;
- les coûts unitaires ;
- le but détaillé exact.

Il n’encode volontairement pas :

```text
reachable(node1, node2)
reachable-without-switch(...)
reachable-outside-cell(...)
```

Ces prédicats produiraient un grounding de taille proche de `|V|²|S|` ou `|V|²|C|`. Les contraintes de chemin restent donc dans le moteur Python.

Les sectionnements ne sont activés dans le PDDL que si la règle dynamique Python est désactivée ou qu’ils sont autorisés extérieurement. Le PDDL reste conservateur.

## IEEE 30

`examples/ieee30_electrical_smoke.py` exécute la validation électrique sur IEEE 30. Le cas IEEE 30 standard reste un modèle bus-level et ne constitue pas un bon exemple de séquences DJ/sectionneurs. Le cas `four_substations` est utilisé pour le planificateur car sa topologie est réellement Node-Breaker.

## Tests

```powershell
pytest -q
```

Les tests couvrent :

- optimalité Hamming contre Uniform-Cost Search ;
- rejeu symbolique ;
- cache des snapshots et connectivités exclues ;
- préservation des arêtes parallèles avec `MultiGraph` ;
- tension et violation de courant simulées ;
- rejeu de chaque STI ;
- PDDL enrichi ;
- test PyPowSyBl réel automatiquement ignoré si la bibliothèque n’est pas installée.
