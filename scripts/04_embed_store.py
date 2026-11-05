"""Put every chunk from data/chunks.jsonl into the store (src/taxowl/retrieval/store.py).

The store must be empty. To rebuild it, delete data/chroma/ by hand first.

Usage:
    uv run scripts/04_embed_store.py
"""

import json
import time

from taxowl.config import CHROMA, CHUNKS, ROOT
from taxowl.retrieval.store import build
from taxowl.schema import Chunk


def main() -> None:
    chunks = [Chunk(**json.loads(line)) for line in CHUNKS.open()]
    print(f"{len(chunks)} chunks read from {CHUNKS.relative_to(ROOT)}")

    start = time.perf_counter()
    stored = build(chunks)
    minutes = (time.perf_counter() - start) / 60

    print(f"\nthe store holds {stored} chunks ({minutes:.1f} minutes). Saved: {CHROMA.relative_to(ROOT)}")
    print("PASS" if stored == len(chunks) else f"FAIL: want {len(chunks)} chunks in the store")


if __name__ == "__main__":
    main()
