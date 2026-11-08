"""Ranking scores for one question: which ids came back (in order) against which ids are right.

Copied from LERAGS src/similarity/metrics.py, which the user wrote; only hit_at_k is new.
"""

import math


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Recall at k."""
    if not relevant:
        return 0.0
    top_k = retrieved[:k]
    hits = len(set(top_k) & relevant)
    return hits / len(relevant)


def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Precision at k."""
    top_k = retrieved[:k]
    hits = len(set(top_k) & relevant)
    return hits / len(top_k) if top_k else 0.0


def reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    """Reciprocal Rank."""
    for rank, doc in enumerate(retrieved, start=1):
        if doc in relevant:
            return 1 / rank
    return 0.0


def mrr(output: list[list[str]], rel_set: list[set[str]]) -> float:
    if len(output) != len(rel_set):
        raise ValueError("output and rel_set must have the same length")
    scores = [reciprocal_rank(r, g) for r, g in zip(output, rel_set)]
    return sum(scores) / len(scores) if scores else 0.0


def ndcg_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """nDCG at k."""
    top_k = retrieved[:k]
    dcg = 0.0
    for rank, doc in enumerate(top_k, start=1):
        if doc in relevant:
            dcg += 1 / math.log2(rank + 1)
    n_ideal = min(len(relevant), k)
    idcg = 0.0
    for rank in range(1, n_ideal + 1):
        idcg += 1 / math.log2(rank + 1)
    return dcg / idcg if idcg > 0 else 0.0


def hit_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Hit at k: 1.0 if any relevant id is in the top k, else 0.0. Added for taxowl: the headline score,
    because one right chunk is often enough to answer, while recall@k asks for all of them."""
    return 1.0 if set(retrieved[:k]) & relevant else 0.0


if __name__ == "__main__":
    r = ["doc_7", "doc_2", "doc_9", "doc_1", "doc_4"]
    g = {"doc_2", "doc_4", "doc_11"}
    print(recall_at_k(r, g, 5))  # 2 mile / 3 the
    print(recall_at_k(r, g, 2))  # top-2 mein sirf doc_2
    print(recall_at_k(r, set(), 5))
    print(precision_at_k(r, g, 5))  # 2 / 5
    print(precision_at_k(r, g, 2))  # 1 / 2
    print(precision_at_k(r, set(), 5))
    output = [
        ["a", "b", "c", "d", "e"],
        ["p", "q", "r"],
        ["x", "y"],
    ]
    rel_set = [
        {"b", "c", "g"},
        {"q"},
        {"z"},
    ]
    print(reciprocal_rank(r, g))  # doc_2 rank 2 par → 0.5
    print(mrr(output, rel_set))  # (0.5 + 0.5 + 0.0) / 3 = 0.333
    print(ndcg_at_k(r, g, 5))
    print(hit_at_k(r, g, 5))  # doc_2 top-5 mein hai → 1.0
    print(hit_at_k(r, {"doc_11"}, 5))  # nahi hai → 0.0
