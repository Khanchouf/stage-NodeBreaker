# Node-Breaker Topological Planner

Planificateur de manœuvres pour postes électriques représentés en **Node/Breaker**.

Le projet cherche une séquence de changements d'état de disjoncteurs et sectionneurs permettant de passer d'une configuration initiale à une configuration cible, tout en respectant des contraintes logiques et topologiques inspirées de l'art de la manœuvre. La recherche principale est réalisée avec **A\***. Une validation électrique optionnelle peut ensuite rejouer le plan avec PyPowSyBl.

## 1. Principe général

```text
XIIDM initial + cible
        |
        v
Extraction Node/Breaker avec PyPowSyBl
        |
        v
Construction du PlanningProblem
        |
        v
TopologyEngine + contraintes de manœuvre
        |
        v
A*
        |
        v
Vérification symbolique indépendante
        |
        +----> export JSON / XIIDM / PDDL
        |
        +----> validation électrique optionnelle
               T0, STI_1, ..., STI_n
```

Chaque état détaillé est représenté par l'état ouvert/fermé des interrupteurs manipulables. Une action correspond à l'ouverture ou à la fermeture d'un seul appareil et a un coût unitaire.

## 2. Deux types de cible

### Cible détaillée

Le mode `plan` impose les positions finales des interrupteurs données par le XIIDM cible.

```bash
python run.py plan initial.xiidm target.xiidm CRENEP3 --heuristic expert
```

### Cible nodale

Le mode `plan-nodal` ne demande pas une configuration détaillée unique. Il projette la cible sur sa topologie nodale, énumère les configurations détaillées admissibles réalisant cette topologie, puis cherche la moins coûteuse.

```bash
python run.py plan-nodal initial.xiidm target.xiidm CRENEP3 --heuristic combined
```

L'optimalité globale est garantie uniquement si l'énumération des antécédents n'est pas tronquée et si chaque recherche A* est menée sans limite d'expansions.

## 3. Heuristiques disponibles

- `zero` : recherche uniforme ;
- `hamming` : nombre d'interrupteurs dont l'état diffère de la cible ;
- `expert` : Hamming renforcée par des bornes locales de transfert entre doubles jeux de barres ;
- `topological` : distance entre partitions nodales ;
- `combined` : maximum entre l'heuristique experte et l'heuristique topologique.

## 4. Contraintes de manœuvre

Le planificateur distingue notamment les disjoncteurs et sectionneurs, les cellules de départ/couplage/sectionnement, les appareils fixes ou manipulables, les équipements protégés et les indisponibilités temporaires.

Les règles de manœuvre sont vérifiées lors de la génération des successeurs A*. La connectivité est calculée par `TopologyEngine`.

## 5. Validation électrique

La validation électrique est **optionnelle** et intervient **après A\***.

```bash
python run.py plan initial.xiidm target.xiidm CRENEP3 \
  --heuristic expert \
  --electrical \
  --step-duration 30 \
  --electrical-output generated/CRENEP3_electrical.json
```

Pour les essais actuels, les critères prioritaires sont :

1. convergence du load-flow AC ;
2. respect des limites thermiques applicables aux états intermédiaires ;
3. contrôle du déphasage avant certaines fermetures lorsqu'un seuil est fourni.

```bash
--max-delta-angle <seuil_en_degres>
```

`--step-duration` représente la durée supposée d'un état intermédiaire et sert à sélectionner les limites thermiques temporaires applicables. Il ne s'agit pas d'une simulation dynamique.

## 6. Structure du dépôt

```text
.
├── run.py
├── planner/
├── pddl/
├── examples/
├── config/
├── data/
├── tests/
└── requirements.txt
```

Voir `planner/README.md` pour le moteur Python et `pddl/README.md` pour la formulation PDDL.

## 7. Installation

```bash
pip install -r requirements.txt
```

Dépendances principales : `networkx`, `pandas`, `pypowsybl`.

## 8. Sorties utiles

```bash
--output plan.json
--problem-json problem.json
--pddl-dir generated/pddl
--planned-network generated/final.xiidm
--electrical-output generated/electrical.json
```

Le JSON du plan contient notamment le coût, les états développés/générés, la séquence d'actions, les statistiques d'heuristique et les temps de calcul.

## 9. Visualisation initiale / cible

Le script `visualize_initial_target.py` génère deux schémas unifilaires SVG et une page HTML de comparaison :

```bash
python visualize_initial_target.py \
  data/initial.xiidm data/target.xiidm CRENEP3 \
  --output-dir generated/figures
```

Les SVG peuvent être insérés directement dans le rapport.

## 10. Limites actuelles

- La validation électrique est un rejeu **a posteriori** : si le meilleur plan topologique est électriquement invalide, A* ne cherche pas automatiquement le suivant.
- Le contrôle automatique de synchronisme dépend de l'identification des grandeurs électriques de part et d'autre de la fermeture.
- L'énumération exhaustive des antécédents d'une cible nodale est exponentielle dans le nombre d'interrupteurs manipulables.
- Le PDDL reste une formulation locale ; la connectivité transitive détaillée est gérée par le moteur Python.
