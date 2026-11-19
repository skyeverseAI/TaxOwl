"""Text -> vectors: lists of numbers, close together when two texts mean similar things.

Which model: the TAXOWL_EMBEDDER environment variable, one of MODELS (default bge-m3: it beat
bge-small on the test set, 0.81 vs 0.69 hit@5; Evaluations/Retriever_Evals/Final.md). An env var,
not a flag, because the store is opened deep inside lookup, the retriever, the evals and the app.
    TAXOWL_EMBEDDER=bge-m3 uv run python -m taxowl.retrieval.embedder
Each model has its own collection in the store (store.py), so switching never mixes vectors.

LangChain's HuggingFaceEmbeddings does the work. bge treats the two sides differently:
    get_embedder().embed_documents(texts)   what we store: the text as it is
    get_embedder().embed_query(question)    what comes looking: the model's instruction goes in front

Check it (needs data/chunks.jsonl):
    uv run python -m taxowl.retrieval.embedder
"""

import json
import os
from functools import lru_cache

from langchain_huggingface import HuggingFaceEmbeddings

from taxowl.config import CHUNKS

# name on Hugging Face, vector length, and what goes in front of a question (from each model card)
MODELS = {
    "bge-small": {"name": "BAAI/bge-small-en-v1.5", "dimensions": 384,
                  "query_prefix": "Represent this sentence for searching relevant passages: "},
    # multilingual (100+ languages), reads up to 8192 tokens, needs no question prefix; ~2.3 GB
    "bge-m3": {"name": "BAAI/bge-m3", "dimensions": 1024, "query_prefix": ""},
}
MODEL = os.environ.get("TAXOWL_EMBEDDER", "bge-m3")
if MODEL not in MODELS:
    raise SystemExit(f"TAXOWL_EMBEDDER={MODEL!r}: choose one of {sorted(MODELS)}")
EMBEDDER = MODELS[MODEL]["name"]
DIMENSIONS = MODELS[MODEL]["dimensions"]
QUERY_PREFIX = MODELS[MODEL]["query_prefix"]
BATCH = 32        # texts turned into vectors at one time
DEVICE = "cpu"    # the server may have no GPU, so the Mac runs the same way


@lru_cache(maxsize=1)
def get_embedder() -> HuggingFaceEmbeddings:
    """Loaded once: loading is slow, and every question would otherwise pay for it.
    Normalised: every vector has length 1, so comparing two looks only at direction (meaning),
    not at how long the text was."""
    return HuggingFaceEmbeddings(
        model_name=EMBEDDER,
        model_kwargs={"device": DEVICE},
        encode_kwargs={"normalize_embeddings": True, "batch_size": BATCH},
        query_encode_kwargs={"normalize_embeddings": True, "prompt": QUERY_PREFIX},
    )


def similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity. For vectors of length 1 it's just this sum: higher = closer in meaning."""
    return sum(x * y for x, y in zip(a, b))


def main() -> None:
    question = "What document is needed to transport goods?"
    wanted = {"cgst-rules-2017:rule-138:1": "related (rule 138, e-way bill)",
              "155-11-2021-gst-table-1:1": "unrelated (GST rate on sprinklers)"}
    found = {}
    for row in map(json.loads, CHUNKS.open()):
        if row["chunk_id"] in wanted:
            found[row["chunk_id"]] = row["text"]

    embedder = get_embedder()
    query = embedder.embed_query(question)
    related, unrelated = embedder.embed_documents([found[chunk_id] for chunk_id in wanted])
    near, far = similarity(query, related), similarity(query, unrelated)

    print(f"question: {question}")
    print(f"vector length: {len(query)} numbers (want {DIMENSIONS})")
    for chunk_id, label, score in zip(wanted, wanted.values(), (near, far)):
        print(f"  {score:.3f}  {label}  [{chunk_id}]")
    passed = len(query) == DIMENSIONS and near > far
    print(f"model: {EMBEDDER}")
    print("PASS" if passed else f"FAIL: want {DIMENSIONS} numbers, and the related chunk scoring higher")


if __name__ == "__main__":
    main()
