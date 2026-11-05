"""B8: random chunks to compare with their PDF pages by eye. Reads data/chunks.jsonl, writes
data/runs/chunk_sample.txt. A fixed seed, so the same chunks come back unless the chunks change.

Run: uv run python experiments/sample_chunks.py
"""

import json
import random

from taxowl.config import CHUNKS, ROOT

SAMPLE = 10
SEED = 2026
OUT = ROOT / "data" / "runs" / "chunk_sample.txt"


def main() -> None:
    chunks = [json.loads(line) for line in CHUNKS.open()]
    out = []
    for n, c in enumerate(random.Random(SEED).sample(chunks, SAMPLE), 1):
        out.append(f"{'=' * 90}\n{n}. {c['chunk_id']} | {c['kind']} | {c['token_count']} tokens\n"
                   f"Citation: {c['doc_number']}, {c['location']}\n"
                   f"PDF: {c['official_url']}\nPages: {c['page_start']}-{c['page_end']} | signed by: {c['signed_by']}\n"
                   f"\n{c['text']}\n")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out))
    print(f"{SAMPLE} chunks of {len(chunks)}: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
