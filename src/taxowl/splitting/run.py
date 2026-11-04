"""One way in for every splitter (to-do-list.md, A6): a file and its doc_type -> units.

    split_file("circulars/2024/238-32-2024-GST.pdf", "circulars") -> Split(units, tables, problems, warnings)

The three splitters grew their own shapes (act.split, icai.split_part per part, circulars.split);
this file gives them one, so the runner (scripts/03_split_chunk.py) and, later, the upload path
and the server call the same function. A new document family is one more line in split_file().
The splitters' own main() stay for development: icai.py's runs its held-out test and table gold.
"""

import json
from dataclasses import asdict, dataclass, field

import pymupdf

from taxowl.config import DOCS, INGESTED, UNITS
from taxowl.schema import Unit
from taxowl.splitting import act, circulars, icai, known_parts


@dataclass
class Split:
    units: list[Unit]
    tables: list[dict] = field(default_factory=list)  # each with its unit_id; saved as <file>.tables.jsonl
    problems: dict[str, str] = field(default_factory=dict)  # self-check failures: something is wrong
    warnings: list[str] = field(default_factory=list)  # odd but kept: a gap in numbering, no subject ...


def split_file(doc_file: str, doc_type: str) -> Split:
    """The extractor's output for this file -> its units, by the splitter for its doc_type."""
    doc = json.loads((INGESTED / f"{doc_file}.json").read_text())
    if doc_type == "act":
        units, problems = act.split(doc)
        return Split(units, problems=problems, warnings=[f"{u.location}: {w}" for u in units for w in u.warnings])
    if doc_type == "rules":  # a compilation: one split per part listed in known_docs.json
        pdf, out = pymupdf.open(DOCS / doc_file), Split([])
        for part in known_parts(doc_file):
            units, problems, warnings, info = icai.split_part(doc, pdf, part)
            out.units += units
            out.tables += info["tables"]
            out.problems.update({f"{part['name']}: {k}": v for k, v in problems.items()})
            out.warnings += [f"{part['name']}: {w}" for w in warnings]
        return out
    if doc_type in circulars.TYPES:
        units, tables, problems, warnings = circulars.split(doc)
        return Split(units, tables, problems, warnings)
    raise ValueError(f"no splitter for doc_type {doc_type!r} ({doc_file})")


def save(doc_file: str, result: Split) -> None:
    """data/units/<file>.jsonl, one Unit per line; <file>.tables.jsonl when it has tables."""
    out = UNITS / f"{doc_file}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(asdict(u), ensure_ascii=False) + "\n" for u in result.units))
    if result.tables:
        (UNITS / f"{doc_file}.tables.jsonl").write_text(
            "".join(json.dumps(t, ensure_ascii=False) + "\n" for t in result.tables))
