"""Validity status: turn the checked detector rows into each circular's status, and put it on its chunks.

    candidates.csv (body rows, ok=y)  ->  status.json (one line per circular)  ->  chunks.jsonl + Chroma labels

Rules:
  - Only BODY rows count, and only rows a person marked ok=y. The body is the evidence (CBIC titles
    are a cross-check, used in recall.py); an unchecked row is not trusted yet.
  - Any withdrawn row -> the circular is withdrawn, `changed_by` = the circular(s) that withdrew it.
    Otherwise -> partly_modified, `changed_by` = every circular that changed a part of it.
  - Circulars with no row stay in_force. Acts, rules and other documents are never touched.

The store is updated in place: only the labels (metadata) change, the vectors and text stay, so
nothing is embedded again. Every `corpus-*` collection is updated (bge-m3 and bge-small).

03_split_chunk.py calls apply() before it saves, so rebuilding the chunks keeps the status.

    uv run python -m taxowl.validity.status
"""

import csv
import json
from collections import defaultdict

import chromadb

from taxowl.chunking.run import save
from taxowl.config import CHROMA, CHUNKS, ROOT
from taxowl.schema import Chunk
from taxowl.validity.detect import CANDIDATES, VALIDITY, load_circulars, norm

STATUS = VALIDITY / "status.json"   # normalised number -> {number, status, changed_by, rows}
CHANGES = ("withdrawn", "partly_modified")
EXAMPLES = ("37/11/2018", "125/44/2019")   # shown before/after: one withdrawn, one partly modified


def build_status() -> dict[str, dict]:
    """status.json from the checked body rows of candidates.csv."""
    circulars = load_circulars()
    found = defaultdict(lambda: defaultdict(set))   # target -> status -> {by}
    with CANDIDATES.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["ok"] == "y" and row["part"] == "body" and row["status"] in CHANGES and row["by"] in circulars:
                found[row["target"]][row["status"]].add(row["by"])

    status = {}
    for target, by_status in sorted(found.items()):
        kind = "withdrawn" if by_status["withdrawn"] else "partly_modified"
        by = sorted(by_status[kind], key=lambda n: circulars[n]["date"])   # oldest change first
        status[target] = {"number": circulars[target]["number"], "status": kind,
                          "changed_by": ", ".join(circulars[n]["number"] for n in by),
                          "by": by, "rows": sum(len(b) for b in by_status.values())}
    STATUS.write_text(json.dumps(status, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return status


def load_status() -> dict[str, dict]:
    return json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {}


def label(chunk: dict | Chunk, status: dict[str, dict]) -> tuple[str, str]:
    """(status, changed_by) for one chunk. Only circulars can be withdrawn or changed."""
    doc_type = chunk["doc_type"] if isinstance(chunk, dict) else chunk.doc_type
    number = chunk["doc_number"] if isinstance(chunk, dict) else chunk.doc_number
    s = status.get(norm(number)) if doc_type == "circular" else None
    return (s["status"], s["changed_by"]) if s else ("in_force", "")


def apply(chunks: list[Chunk], status: dict[str, dict] | None = None) -> int:
    """Set status and changed_by on every chunk (resetting the rest to in_force). Returns how many changed."""
    status = load_status() if status is None else status
    changed = 0
    for c in chunks:
        new = label(c, status)
        if new != (c.status, c.changed_by):
            c.status, c.changed_by = new
            changed += 1
    return changed


def read_chunks() -> list[Chunk]:
    """chunks.jsonl as Chunks. Files written before the rename carry `withdrawn_by` (always empty): dropped."""
    chunks = []
    for line in CHUNKS.open(encoding="utf-8"):
        row = json.loads(line)
        row.pop("withdrawn_by", None)
        chunks.append(Chunk(**row))
    return chunks


def update_stores(status: dict[str, dict]) -> dict[str, int]:
    """Change only the labels in every corpus-* collection. Returns chunks changed per collection."""
    client = chromadb.PersistentClient(path=str(CHROMA))
    result = {}
    for collection in client.list_collections():
        if not collection.name.startswith("corpus-"):
            continue
        got = collection.get(include=["metadatas"])
        ids, metadatas = [], []
        for chunk_id, meta in zip(got["ids"], got["metadatas"]):
            new_status, changed_by = label(meta, status)
            if (meta.get("status"), meta.get("changed_by")) != (new_status, changed_by) or "withdrawn_by" in meta:
                ids.append(chunk_id)
                # None removes the old key; Chroma merges the rest into the existing labels
                metadatas.append({"status": new_status, "changed_by": changed_by, "withdrawn_by": None})
        for i in range(0, len(ids), 500):
            collection.update(ids=ids[i:i + 500], metadatas=metadatas[i:i + 500])
        result[collection.name] = len(ids)
    return result


def show(chunks: list[Chunk], numbers: tuple[str, ...]) -> list[str]:
    """One line per example circular: its first chunk's status and changed_by."""
    lines = []
    for n in numbers:
        c = next((c for c in chunks if c.doc_type == "circular" and norm(c.doc_number) == n), None)
        if c:
            lines.append(f"  {c.chunk_id:32} status={c.status:16} changed_by={c.changed_by or '-'}")
    return lines


def main() -> None:
    status = build_status()
    kinds = defaultdict(int)
    for s in status.values():
        kinds[s["status"]] += 1
    print(f"{len(status)} circulars changed ({kinds['withdrawn']} withdrawn, {kinds['partly_modified']} partly modified)"
          f" -> {STATUS.relative_to(ROOT)}")

    # Chains: the circular that made the change was itself changed later. Kept as it is; shown to read.
    chains = [(t, b) for t, s in status.items() for b in s["by"] if b in status]
    print(f"\nchains ({len(chains)}): target <- by <- what changed `by`")
    for t, b in chains:
        print(f"  {t:12} {status[t]['status']:16} <- {b:12} {status[b]['status']:16} <- {', '.join(status[b]['by'])}")

    chunks = read_chunks()
    before = show(chunks, EXAMPLES)
    changed = apply(chunks, status)
    save(chunks)
    on = sum(c.status != "in_force" for c in chunks)
    print(f"\nchunks.jsonl: {changed} chunks relabelled, {on} of {len(chunks)} now not in_force -> "
          f"{CHUNKS.relative_to(ROOT)}")
    print("before:", *before, "after:", *show(chunks, EXAMPLES), sep="\n")

    print("\nstore (labels only, no embedding):")
    for name, n in update_stores(status).items():
        print(f"  {name}: {n} chunks updated")
    client = chromadb.PersistentClient(path=str(CHROMA))
    for collection in client.list_collections():
        if collection.name.startswith("corpus-"):
            left = collection.get(where={"status": {"$ne": "in_force"}}, include=[])
            print(f"  {collection.name}: {len(left['ids'])} chunks not in_force (want {on})"
                  f" {'PASS' if len(left['ids']) == on else 'FAIL'}")


if __name__ == "__main__":
    main()
