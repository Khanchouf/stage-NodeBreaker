from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


def _canonical_blocks(blocks: Iterable[Iterable[str]]) -> tuple[frozenset[str], ...]:
    normalized: list[frozenset[str]] = []
    seen: set[str] = set()

    for raw_block in blocks:
        block = frozenset(str(item) for item in raw_block)
        if not block:
            raise ValueError("Une partition ne peut pas contenir de bloc vide.")
        overlap = seen.intersection(block)
        if overlap:
            raise ValueError(
                "Les blocs d'une partition doivent être disjoints ; "
                f"éléments répétés : {sorted(overlap)}."
            )
        seen.update(block)
        normalized.append(block)

    normalized.sort(key=lambda block: tuple(sorted(block)))
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class NodalPartition:
    """Canonical immutable partition of the observable electrical objects.

    The observable objects are represented by stable string identifiers.  In
    this project they are equipment terminals (and, by default, busbar
    sections), not the internal Node/Breaker connectivity nodes themselves.
    """

    blocks: tuple[frozenset[str], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "blocks", _canonical_blocks(self.blocks))

    @classmethod
    def from_blocks(cls, blocks: Iterable[Iterable[str]]) -> "NodalPartition":
        return cls(tuple(frozenset(str(item) for item in block) for block in blocks))

    @property
    def universe(self) -> frozenset[str]:
        return frozenset(item for block in self.blocks for item in block)

    def __len__(self) -> int:
        return len(self.blocks)

    def to_dict(self) -> dict[str, object]:
        return {
            "blocks": [sorted(block) for block in self.blocks],
            "observable_count": len(self.universe),
            "block_count": len(self.blocks),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "NodalPartition":
        raw_blocks = data.get("blocks", data.get("classes"))
        if raw_blocks is None:
            raise ValueError("Le JSON de topologie nodale doit contenir 'blocks' ou 'classes'.")
        if not isinstance(raw_blocks, Sequence) or isinstance(raw_blocks, (str, bytes)):
            raise ValueError("'blocks' doit être une liste de listes d'identifiants.")
        return cls.from_blocks(raw_blocks)  # type: ignore[arg-type]

    @classmethod
    def load(cls, path: str | Path) -> "NodalPartition":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> Path:
        output = Path(path)
        output.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return output


def _check_same_universe(p: NodalPartition, q: NodalPartition) -> None:
    if p.universe != q.universe:
        only_p = sorted(p.universe - q.universe)
        only_q = sorted(q.universe - p.universe)
        raise ValueError(
            "Les deux partitions doivent porter sur le même ensemble d'observables. "
            f"Uniquement dans P={only_p}, uniquement dans Q={only_q}."
        )


def join_partition(p: NodalPartition, q: NodalPartition) -> NodalPartition:
    """Return P ∨ Q, the least common coarsening of P and Q.

    Equivalently, it is the partition induced by the transitive closure of the
    union of the two equivalence relations associated with P and Q.
    """

    _check_same_universe(p, q)
    universe = sorted(p.universe)
    parent = {item: item for item in universe}
    rank = {item: 0 for item in universe}

    def find(item: str) -> str:
        root = item
        while parent[root] != root:
            root = parent[root]
        while parent[item] != item:
            nxt = parent[item]
            parent[item] = root
            item = nxt
        return root

    def union(left: str, right: str) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left == root_right:
            return
        if rank[root_left] < rank[root_right]:
            root_left, root_right = root_right, root_left
        parent[root_right] = root_left
        if rank[root_left] == rank[root_right]:
            rank[root_left] += 1

    for partition in (p, q):
        for block in partition.blocks:
            ordered = sorted(block)
            if not ordered:
                continue
            first = ordered[0]
            for item in ordered[1:]:
                union(first, item)

    groups: dict[str, set[str]] = {}
    for item in universe:
        groups.setdefault(find(item), set()).add(item)
    return NodalPartition.from_blocks(groups.values())


def partition_distance(p: NodalPartition, q: NodalPartition) -> int:
    """Minimum number of elementary merge/split operations from P to Q.

    An elementary merge combines exactly two blocks.  An elementary split
    separates exactly one block into exactly two blocks.  The closed form is

        d(P,Q) = |P| + |Q| - 2 |P ∨ Q|.
    """

    common = join_partition(p, q)
    return len(p) + len(q) - 2 * len(common)


# Backward-friendly short alias used in a few notebooks/report snippets.
Partition = NodalPartition
