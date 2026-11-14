"""When was each Act/Rules chunk last amended? So an answer can say "the law changed after this circular".

A circular explains a provision as it stood on its date. Circular 123/42/2019 explains rule 36(4)'s 5%
limit; rule 36(4) was substituted w.e.f. 01.01.2022. The retriever brings the provision's CURRENT text
(retrieval/retriever.py, cited()), but the model doesn't compare the two by itself (trap dev-018,
2026-11-13). So our code compares the dates, and the label tells the model:

    [S11] CGST Rules, rule 36(4) (CURRENT TEXT; AMENDED on 2022-01-01, AFTER Circular 123/42/2019-GST ...)

The dates come from the footnotes the splitter already keeps on each Unit (`amended_by`):
  ICAI (CGST/IGST Rules, IGST/UTGST/Compensation Acts):
      'Substituted vide Notification No. 40/2021 - CT dated 29.12.2021, w.e.f. 01.01.2022. Words: "(4) No ..."'
      The note carries the new words, so a date goes only on the chunk that holds them: sub-rule level.
  India Code (CGST Act):
      'Ins. by Act 13 of 2021, s. 109 (w.e.f. 1-1-2022).'
      No words, so every chunk of the section gets all its dates: section level (`amended_scope`).

A change's date is the later of when it took effect and when it was made: a retrospective change
(Act 15 of 2024, w.e.f. 1-07-2017) still came after a 2019 circular. Omissions ("Words: (deleted)")
leave no words to find, so they are not dated on a chunk. Chunks get `amended_on` ("2022-01-01, 2024-10-08",
oldest first) and `amended_scope` ("text" or "section"). Only labels change, in chunks.jsonl and every
corpus-* collection; nothing is embedded again. 03_split_chunk.py calls apply() so a rebuild keeps them.

    uv run python -m taxowl.validity.amended
"""

import json
import re
from datetime import date

import chromadb

from taxowl.chunking.run import save
from taxowl.config import CHROMA, CHUNKS, ROOT, UNITS
from taxowl.schema import Chunk
from taxowl.validity.status import read_chunks

LAWS = ("act", "rules")
EFFECT = re.compile(r"w\.?\s?e\.?\s?f\.?\s*(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", re.I)
MADE = re.compile(r"dated\s+(?:the\s+)?(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", re.I)
ACT_YEAR = re.compile(r"\bAct\s+\d+\s+of\s+(\d{4})")
WORDS = re.compile(r'Words:\s*"(.+)"', re.S)
SAMPLE = 60       # first letters/digits of the new words looked for in a chunk
SHORTEST = 12     # fewer than this ("section 74") could match anywhere
EXAMPLES = ("cgst-rules-2017:rule-36:4", "act-12-of-2017:section-16:2")


def as_date(match: re.Match | None) -> date | None:
    if not match:
        return None
    d, m, y = (int(g) for g in match.groups())
    try:
        return date(y, m, d)
    except ValueError:
        return None


def note_date(note: str) -> date | None:
    """The later of when a change took effect and when it was made (an Act's year if no day)."""
    effect, made = as_date(EFFECT.search(note)), as_date(MADE.search(note))
    if not made and (year := ACT_YEAR.search(note)):
        made = date(int(year.group(1)), 1, 1)
    dates = [d for d in (effect, made) if d]
    return max(dates) if dates else None


def letters(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def unit_notes() -> dict[str, list[tuple[date, str]]]:
    """unit_id -> [(date, new words or "")] for every Act/Rules unit with dated notes."""
    notes = {}
    for path in UNITS.glob("*.jsonl"):
        if path.name.endswith(".tables.jsonl"):
            continue
        for line in path.open(encoding="utf-8"):
            unit = json.loads(line)
            found = []
            for note in unit.get("amended_by", []):
                when = note_date(note)
                if when:
                    words = WORDS.search(note)
                    found.append((when, letters(words.group(1))[:SAMPLE] if words else ""))
            if found:
                notes[unit["unit_id"]] = found
    return notes


def dates_for(chunk: Chunk, notes: dict[str, list[tuple[date, str]]]) -> tuple[str, str]:
    """(amended_on, amended_scope) for one chunk; ("", "") if none or not a law."""
    if chunk.doc_type not in LAWS or chunk.unit_id not in notes:
        return "", ""
    found = notes[chunk.unit_id]
    if any(words for _, words in found):   # ICAI: the note names the new words
        text = letters(chunk.text)
        dates = {when for when, words in found if len(words) >= SHORTEST and words in text}
        scope = "text"
    else:                                   # India Code: no words, the whole section
        dates = {when for when, _ in found}
        scope = "section"
    return (", ".join(d.isoformat() for d in sorted(dates)), scope) if dates else ("", "")


def apply(chunks: list[Chunk], notes: dict | None = None) -> int:
    """Set amended_on/amended_scope on every chunk. Returns how many changed."""
    notes = unit_notes() if notes is None else notes
    changed = 0
    for c in chunks:
        new = dates_for(c, notes)
        if new != (c.amended_on, c.amended_scope):
            c.amended_on, c.amended_scope = new
            changed += 1
    return changed


def update_stores(chunks: list[Chunk]) -> dict[str, int]:
    """Copy amended_on/amended_scope into every corpus-* collection. Returns chunks changed per collection."""
    by_id = {c.chunk_id: c for c in chunks}
    client = chromadb.PersistentClient(path=str(CHROMA))
    result = {}
    for collection in client.list_collections():
        if not collection.name.startswith("corpus-"):
            continue
        got = collection.get(include=["metadatas"])
        ids, metadatas = [], []
        for chunk_id, meta in zip(got["ids"], got["metadatas"]):
            c = by_id.get(chunk_id)
            if c and (meta.get("amended_on"), meta.get("amended_scope")) != (c.amended_on, c.amended_scope):
                ids.append(chunk_id)
                metadatas.append({"amended_on": c.amended_on, "amended_scope": c.amended_scope})
        for i in range(0, len(ids), 500):
            collection.update(ids=ids[i:i + 500], metadatas=metadatas[i:i + 500])
        result[collection.name] = len(ids)
    return result


def main() -> None:
    chunks = read_chunks()
    changed = apply(chunks)
    save(chunks)
    laws = [c for c in chunks if c.doc_type in LAWS]
    dated = [c for c in laws if c.amended_on]
    print(f"chunks.jsonl: {changed} relabelled; {len(dated)} of {len(laws)} Act/Rules chunks carry dates "
          f"({sum(c.amended_scope == 'text' for c in dated)} at text level, "
          f"{sum(c.amended_scope == 'section' for c in dated)} at section level) -> {CHUNKS.relative_to(ROOT)}")
    for c in chunks:
        if c.chunk_id in EXAMPLES:
            print(f"  {c.chunk_id:32} {c.amended_scope:8} {c.amended_on}")

    print("\nstore (labels only, no embedding):")
    for name, n in update_stores(chunks).items():
        print(f"  {name}: {n} chunks updated")
    client = chromadb.PersistentClient(path=str(CHROMA))
    for collection in client.list_collections():
        if collection.name.startswith("corpus-"):
            left = collection.get(where={"amended_on": {"$ne": ""}}, include=[])
            print(f"  {collection.name}: {len(left['ids'])} chunks with dates (want {len(dated)})"
                  f" {'PASS' if len(left['ids']) == len(dated) else 'FAIL'}")


if __name__ == "__main__":
    main()
