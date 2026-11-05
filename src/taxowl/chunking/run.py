"""One way in for chunking: one file's units and tables -> its final chunks (B3, B4, B6, B7 in to-do-list.md).

    chunk_file(row, units, tables) -> (chunks, problems)

chunker.py and tables.py only cut. This file decides what goes in: signatures and letterheads stay
out of search (the signer's name is kept as a label), a tiny paragraph joins a neighbour, every chunk gets a context header
and its labels. `amended_by` and `history` never enter a chunk; unit_id is the way back to them.
"""

import json
import re
from collections import Counter
from dataclasses import asdict
from functools import lru_cache

from taxowl.chunking.chunker import MAX_TOKENS, SMALL, cut
from taxowl.chunking.tables import cut_table
from taxowl.config import CHUNKS, INGESTED
from taxowl.schema import Chunk, Unit
from taxowl.splitting import known_parts, number_counts, slug
from taxowl.tokens import count_tokens

DOC_TYPE = {"act": "act", "rules": "rules", "circulars": "circular",
            "instructions": "instruction", "notifications": "notification"}
LOCATION_ROOM = 12  # a piece's citation can be longer than its unit's: "section 110(4)(ii)-(iv)"
FINISHED_WORDS = 4  # a tiny paragraph with this many words and a full stop is a sentence, not a title
HEADER_ROOM = 80    # joining backwards keeps this free, so the longest header still fits
TITLE_MAX = 40      # tokens of a document's title or a heading in the context header
OUT_OF_SEARCH = ("signature", "letterhead")  # no law in them: who signed and to whom, not what it says
NOT_A_NAME = re.compile(r"^yours\b|@|^(?:tel|email|e-mail|fax|phone|copy)\b", re.I)


def document_of(row: dict, unit: Unit) -> tuple[str, str, str]:
    """-> (doc_type, number, title). A compilation's unit belongs to its part: "IGST Act, 2017"."""
    for part in known_parts(row["file"]):
        if unit.unit_id.startswith(slug(part["name"]) + ":"):
            return part["type"], part["name"], part["name"]
    title = re.sub(r"\s*\(as amended\)\s*$", "", row["title"])
    # A blank or shared number ("Corrigendum" on 11 files) can't be cited: the title says which one.
    shared = not row["number"] or number_counts()[row["number"]] > 1
    number = re.sub(r"\s*([/-])\s*", r"\1", row["number"])  # the portal writes "80/54 /2018-GST"
    return DOC_TYPE[row["doc_type"]], title if shared else number, title


def header(doc: tuple[str, str, str], unit: Unit, location: str, table: bool = False) -> str:
    """`CGST Rules, 2017, rule 7: Rate of tax ...` or `Circular 238/32/2024-GST — <subject> — para 4`.
    It goes into the chunk's text: it helps search, and it tells the LLM what it is reading."""
    doc_type, number, title = doc
    where = location + (", table" if table else "")
    if doc_type in ("act", "rules"):
        return f"{title}, {where}" + (f": {shorten(unit.heading)}" if unit.heading else "")
    word = doc_type.capitalize()
    if number == title:  # no number of its own: the subject below says which document
        label = word
    else:
        label = number if number.lower().startswith(word.lower()) else f"{word} {number}"
    # The portal's title, not the subject the splitter found: that can run on into the first para.
    return f"{label} — {shorten(title)} — {where}"


@lru_cache(maxsize=None)
def shorten(text: str) -> str:
    """A long title would fill every chunk of its document, so a header keeps only its start.
    The full title stays in the chunk's `title` label."""
    if count_tokens(text) <= TITLE_MAX:
        return text
    words = text.split()
    while words and count_tokens(" ".join(words)) > TITLE_MAX:
        words.pop()
    return " ".join(words) + " ..."


def signed_by(units: list[Unit]) -> str:
    """Who signed: "Sanjay Mangal, Principal Commissioner (GST)". Name and designation only."""
    sign = next((u for u in units if u.location == "signature"), None)
    if not sign:
        return ""
    lines = [l.strip() for l in sign.text.split("\n") if l.strip() and not NOT_A_NAME.search(l.strip())]
    return ", ".join(l.strip("()") if l.startswith("(") else l for l in lines[:2])


def text_groups(units: list[Unit]) -> list[list[Unit]]:
    """Units to chunk together. A tiny paragraph is mostly a topic's title ("5. Treated sewage water
    attracts Nil rate of GST:"), so it joins the paragraph after it. If it's a finished sentence
    ("7.5 Non-laminated woven bags would be ..."), it ends the topic before it, so it joins that one
    if the two fit. Sections and rules never join."""
    groups, waiting = [], []
    for u in units:
        if u.location in OUT_OF_SEARCH:
            continue
        is_para = u.unit_type == "paragraph" and u.location.startswith("para")
        if is_para and u.token_count < SMALL:
            finished = u.text.rstrip().endswith(".") and len(u.text.split()) >= FINISHED_WORDS
            before = groups[-1] if groups else []
            if finished and not waiting and before and before[-1].location.startswith("para") \
                    and sum(x.token_count for x in before) + u.token_count <= MAX_TOKENS - HEADER_ROOM:
                before.append(u)
            else:
                waiting.append(u)
        elif is_para:
            groups.append(waiting + [u])
            waiting = []
        else:
            if waiting:
                groups.append(waiting)
                waiting = []
            groups.append([u])
    if waiting:
        groups.append(waiting)
    return groups


def squeeze(text: str) -> list[str]:
    return text.split()


def chunk_file(row: dict, units: list[Unit], tables: list[dict]) -> tuple[list[Chunk], list[str]]:
    """One manifest row, with its units and tables -> (chunks, problems: text a chunk lost)."""
    doc = json.loads((INGESTED / f"{row['file']}.json").read_text())
    signer = signed_by(units)
    url = row.get("download_api") or row["official_url"]  # the file itself, where the portal gives one
    chunks, problems = [], []

    def make(unit, chunk_id, text, kind, location, first, last, table_id=""):
        doc_type, number, title = document_of(row, unit)
        return Chunk(chunk_id=chunk_id, text=text, kind=kind, doc_type=doc_type, doc_number=number,
                     doc_date=row["date"], title=title, official_url=url, location=location,
                     page_start=first, page_end=last, table_id=table_id, ocr=doc["ocr"],
                     quality_ok=not doc["quality"], source_sha256=row["sha256"],
                     unit_id=unit.unit_id, signed_by=signer, token_count=count_tokens(text))

    for group in text_groups(units):
        main = group[-1]
        d = document_of(row, main)
        text = "\n".join(u.text for u in group)
        reserve = count_tokens(header(d, main, main.location)) + LOCATION_ROOM
        pieces = cut(text, main.location, reserve)
        if len(group) > 1:  # a joined paragraph: the first piece starts in the tiny one
            start = group[0].location
            pieces[0].location = f"{start}-{pieces[0].location.removeprefix('para ')}"
        if squeeze(" ".join(" ".join(p.lines) for p in pieces)) != squeeze(text):
            problems.append(f"{main.unit_id}: pieces don't add up to the unit's text")
        for k, p in enumerate(pieces, 1):
            chunk_id = main.unit_id if len(pieces) == 1 else f"{main.unit_id}:{k}"
            chunks.append(make(main, chunk_id, f"{header(d, main, p.location)}\n{p.text}", "text",
                               p.location, group[0].page_start, main.page_end))

    by_id = {u.unit_id: u for u in units}
    for t in tables:
        unit = by_id[t["unit_id"]]
        d = document_of(row, unit)
        head = header(d, unit, unit.location, table=True)
        for k, p in enumerate(cut_table(t, count_tokens(head)), 1):
            chunks.append(make(unit, f"{slug(t['table_id'])}:{k}", f"{head}\n{p.text}", "table",
                               unit.location, p.page_start, p.page_end, t["table_id"]))
    return chunks, problems


def check_chunks(chunks: list[Chunk]) -> dict[str, str]:
    """B7, over all files together: what must hold before anything is embedded."""
    problems = {}
    over = [c.chunk_id for c in chunks if c.token_count > MAX_TOKENS]
    if over:
        problems["over_limit"] = f"{len(over)}: {over[:5]}"
    empty = [c.chunk_id for c in chunks if "\n" not in c.text or not c.text.split("\n", 1)[1].strip()]
    if empty:
        problems["empty"] = f"{len(empty)}: {empty[:5]}"
    repeated = [k for k, n in Counter(c.chunk_id for c in chunks).items() if n > 1]
    if repeated:
        problems["ids_repeated"] = f"{len(repeated)}: {repeated[:5]}"
    for field in ("official_url", "status", "location", "unit_id", "doc_number"):
        blank = [c.chunk_id for c in chunks if not getattr(c, field)]
        if blank:
            problems[f"no_{field}"] = f"{len(blank)}: {blank[:5]}"
    return problems


def save(chunks: list[Chunk]) -> None:
    """data/chunks.jsonl, one Chunk per line: what the embedding step reads."""
    CHUNKS.parent.mkdir(parents=True, exist_ok=True)
    CHUNKS.write_text("".join(json.dumps(asdict(c), ensure_ascii=False) + "\n" for c in chunks))
