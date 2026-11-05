"""ExtractedDoc -> list[Unit]: cut each document where the law itself divides it
(plans/stage2_splitchunk.md, part A; checklist in to-do-list.md). One splitter per document
family: act.py, icai.py (the ICAI Rules), circulars.py. Every splitter ends with finish(), so the fields that
are the same for all of them are filled the same way."""

import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from taxowl.config import MANIFEST
from taxowl.schema import Unit
from taxowl.tokens import count_tokens

KNOWN_DOCS = Path(__file__).with_name("known_docs.json")  # facts about one specific file (A3)


def known_parts(doc_file: str) -> list[dict]:
    """The parts of a known multi-law PDF, from known_docs.json: name, type, pages [first, last],
    and the word its units start with ("Rule" / "Section"). [] for any other file."""
    return json.loads(KNOWN_DOCS.read_text()).get(doc_file, {}).get("parts", [])


def manifest_row(doc_file: str) -> dict:
    """This document's row in docs/manifest.jsonl (number, sha256, official_url, ...)."""
    for row in map(json.loads, MANIFEST.open()):
        if row["file"] == doc_file:
            return row
    raise KeyError(f"{doc_file} is not in {MANIFEST.name}")


@lru_cache(maxsize=1)
def number_counts() -> Counter:
    """How many files in the manifest carry each document number."""
    return Counter(row["number"] for row in map(json.loads, MANIFEST.open()))


def slug(text: str) -> str:
    """'Act 12 of 2017' -> 'act-12-of-2017'; 'section 2(52)' -> 'section-2-52'."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def finish(units: list[Unit], doc_file: str, part: str = "") -> list[str]:
    """Fill unit_id, source_sha256 and token_count on every unit. Returns problems found
    (for the splitter's self-check): an id used twice would make two units collide in the store.
    `part`: for a PDF holding several laws, the part's name from known_docs.json ("IGST Rules,
    2017"), so its ids differ from another part's ("igst-rules-2017:rule-2"). Otherwise the
    manifest's number names the document ("act-12-of-2017:section-16")."""
    row = manifest_row(doc_file)
    # A blank or shared number ("Corrigendum" on 11 files) can't name a document: the path can.
    shared = not row["number"] or number_counts()[row["number"]] > 1
    doc_key = slug(part or (str(Path(doc_file).with_suffix("")) if shared else row["number"]))
    for u in units:
        u.unit_id = f"{doc_key}:{slug(u.location)}"
        u.source_sha256 = row["sha256"]
        u.token_count = count_tokens(u.text)
    seen, repeated = set(), []
    for u in units:
        if u.unit_id in seen:
            repeated.append(u.unit_id)
        seen.add(u.unit_id)
    return [f"unit_id used twice: {repeated[:5]}"] if repeated else []
