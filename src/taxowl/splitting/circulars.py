"""Circulars, instructions and notifications -> one Unit per numbered paragraph (to-do-list.md, A5).

What a circular looks like (238/32/2024, p.1; checked with the user 2026-11-04):
  Circular No. 238/32/2024-GST / F. No. ... / Government of India ... / dated ... / To, ... /
  Madam/Sir,                                   -> one "other" unit: letterhead
  Subject: Clarification of various doubts ... -> the subject: every unit's `parent`
  Based on the recommendations of ...          -> para 1 (CBIC prints no "1." here; only 44 of
                                                  310 files have one)
  1.2 Subsequently, ...                        -> para 1.2
  5. It is requested that ...                  -> para 5
  (Sanjay Mangal) / Principal Commissioner     -> one "other" unit: signature
  Annexure-I ...                               -> one unit per annexure
The subject can run over lines ("Sub– Clarification ... food in" / "Anganwadis and Schools
-reg.", 149/05/2021) and is written "Subject:", "Sub:", "Sub.-", "Sub–".

A line starts a paragraph only if its number comes next in order ("1.2" after para 1, "2." or
"2.1" after "1.3"), as in act.py, so a "5." inside a sentence or a list can't. A file with no
numbered paragraph (a corrigendum) becomes one unit, with a warning. Tables (56 circulars hold
their clarifications in an "Issue | Clarification" table) are linked to the paragraph that starts
above them on their page, as in icai.py; the chunker makes their row views (B5).

Run:  uv run python -m taxowl.splitting.circulars                 (all 312 files)
      uv run python -m taxowl.splitting.circulars <file under docs/> (one file, printed in full)
Out:  data/units/<file>.jsonl per file (+ <file>.tables.jsonl when it has tables), a summary,
      and the files whose self-check failed.
"""

import json
import re
import sys
from collections import Counter
from dataclasses import asdict

import pymupdf

from taxowl.config import DOCS, INGESTED, MANIFEST, UNITS
from taxowl.schema import Unit
from taxowl.splitting import finish
from taxowl.splitting.icai import key, lines_with_y, table_top, words

TYPES = ("circulars", "instructions", "notifications")
SUBJECT = re.compile(r"^(?:Subject|Sub)\s*[:.\-–—]+\s*", re.I)
SUBJECT_END = re.compile(r"(?:\.|\breg\.?|\bregarding)\s*[\-–—]?\s*$", re.I)
SALUTATION = re.compile(r"^(?:Madam\s*/\s*Sir|Sir\s*/\s*Madam|Sir|Madam|Dear\s+[\w ]+)\s*,?$", re.I)
PARA = re.compile(r"^(\d{1,2})\.(?:(\d{1,2})\.?)?(?:\s|$|(?<=\d)(?=[A-Z]))")  # "2. ", "2.1 ", "2.1. ", "2.1Sanction"
SIGN = re.compile(r"^(?:\(\s*[A-Z][A-Za-z .]{2,40}\)|Yours\s+(?:faithfully|sincerely),?)$", re.I)
ANNEX = re.compile(r"^Annex(?:ure)?\b", re.I)


def comes_next(cur: tuple[int, int | None], new: tuple[int, int | None]) -> bool:
    """Does paragraph `new` follow `cur`? One number may be skipped (a deleted paragraph).
    (1, None) -> (1, 2) is fine: the unnumbered first paragraph is 1.1 in effect (238/32/2024)."""
    (major, minor), (n_major, n_minor) = cur, new
    if n_major == major and n_minor is not None:
        return (minor or 0) < n_minor <= (minor or 1) + 2
    return n_major in (major + 1, major + 2) and n_minor in (None, 1)


def number(m: re.Match) -> tuple[int, int | None]:
    return int(m.group(1)), int(m.group(2)) if m.group(2) else None


def label(n: tuple[int, int | None]) -> str:
    return f"para {n[0]}" + (f".{n[1]}" if n[1] is not None else "")


def para_starts(body: list[tuple[int, str]]) -> set[int]:
    """Which numbered lines start a paragraph: the longest run of numbers that each come next
    (comes_next), not the first run met. A list of issues at the top ("1. ... 16. Applicability
    of GST on tickets ...", 177/09/2022) is a short run; the real paragraphs (2, 2.1 ... 17.5)
    are a longer one, so the list stays inside para 1. Only lines before the signature count."""
    end = next((k for k, (_, l) in enumerate(body) if k and SIGN.match(l)), len(body))
    cands = [(k, number(m)) for k, (_, l) in enumerate(body[:end]) if (m := PARA.match(l))]
    best: list[tuple[int, int]] = []  # per candidate: (length of the longest run ending here, previous)
    for a, (k, n) in enumerate(cands):
        first = (k == 0 and comes_next((0, None), n)) or comes_next((1, None), n)
        length, prev = (1, -1) if first else (0, -1)
        for b in range(a):
            if best[b][0] and best[b][0] + 1 > length and comes_next(cands[b][1], n):
                length, prev = best[b][0] + 1, b
        best.append((length, prev))
    if not best or not max(l for l, _ in best):
        return set()
    a = max(range(len(best)), key=lambda x: best[x][0])
    out = set()
    while a != -1:
        out.add(cands[a][0])
        a = best[a][1]
    return out


def split(doc: dict) -> tuple[list[Unit], list[dict], dict, list[str]]:
    """ExtractedDoc -> (units, tables linked to them, self-check problems, warnings)."""
    f = doc["file"]
    lines = [(i + 1, l.strip()) for i, page in enumerate(doc["pages"]) for l in page.split("\n") if l.strip()]
    warnings: list[str] = []
    units: list[Unit] = []

    def unit(unit_type, location, heading, piece, parent=""):
        if piece:
            units.append(Unit(unit_type, f, location, heading, "\n".join(l for _, l in piece),
                              piece[0][0], piece[-1][0], parent=parent))

    # 1. Letterhead and subject.
    i = next((k for k, (_, l) in enumerate(lines) if SUBJECT.match(l)), None)
    subject = ""
    if i is not None:
        j = i
        while not SUBJECT_END.search(lines[j][1]) and j + 1 < len(lines) and j < i + 3 \
                and not SALUTATION.match(lines[j + 1][1]) and not PARA.match(lines[j + 1][1]):
            j += 1
        subject = " ".join(SUBJECT.sub("", l, count=1) if k == i else l
                           for k, (_, l) in enumerate(lines[i:j + 1], start=i)).strip()
        head, body = lines[:i], lines[j + 1:]
        while body and SALUTATION.match(body[0][1]):  # "Madam/Sir," after the subject
            head, body = head + body[:1], body[1:]
        head_subject = lines[i:j + 1]
    else:
        warnings.append("no subject line found")
        s = next((k for k, (_, l) in enumerate(lines) if SALUTATION.match(l)), None)
        head, body, head_subject = (lines[:s + 1], lines[s + 1:], []) if s is not None else ([], lines, [])
    unit("other", "letterhead", "Letterhead, addressees and subject", head + head_subject)

    # 2. Paragraphs, then the signature and any annexures.
    cur, block, loc, gaps, numbered = (0, None), [], "para 1", [], 0
    tail: list[tuple[str, str, list]] = []  # (type, location, lines) after the last paragraph
    starts = para_starts(body)
    for k, (page, line) in enumerate(body):
        if tail:
            if ANNEX.match(line):
                tail.append(("paragraph", f"annexure {sum(t[1].startswith('annexure') for t in tail) + 1}", []))
            tail[-1][2].append((page, line))
            continue
        if SIGN.match(line) and block:
            unit("paragraph", loc, "", block, subject)
            block = []
            tail.append(("other", "signature", [(page, line)]))
            continue
        if k in starts:
            new = number(PARA.match(line))
            if block:
                unit("paragraph", loc, "", block, subject)
            if new[0] > cur[0] + 1 and cur != (0, None) or (new[0] == cur[0] and new[1] and new[1] > (cur[1] or 1) + 1):
                gaps.append(f"{label(new)} after {label(cur)}")
            cur, block, loc = new, [], label(new)
            numbered += 1
        elif cur == (0, None) and not block:
            cur = (1, None)  # text before any number: the unnumbered para 1
        block.append((page, line))
    if block:
        unit("paragraph", loc, "", block, subject)
    for kind, location, piece in tail:
        if location == "signature":  # the name and a few short lines (designation, office)
            cut = next((k for k, (_, l) in enumerate(piece[1:], 1) if len(l) > 80 or PARA.match(l)), len(piece))
            cut = min(cut, 6)
            unit("other", "signature", "Signature", piece[:cut])
            if piece[cut:]:
                unit("other", "after signature", "Copy to, endorsements", piece[cut:])
        else:
            unit(kind, location, piece[0][1][:80], piece, subject)
    if not numbered:
        warnings.append("no numbered paragraph: the body is one unit")
    warnings += [f"gap: {g}" for g in gaps]

    tables = link_tables(units, doc)
    problems = self_check(units, lines, tables)
    if found := finish(units, f):
        problems["finish"] = "; ".join(found)
    for t in tables:
        t["unit_id"] = t.pop("owner").unit_id
    return units, tables, problems, warnings


def link_tables(units: list[Unit], doc: dict) -> list[dict]:
    """Each table -> the paragraph that starts above it on its page, else the one running on
    from an earlier page (as in icai.py). Scans have no text layer to measure: page only."""
    if not doc["tables"]:
        return []
    pdf = pymupdf.open(DOCS / doc["file"])
    out = []
    for t in doc["tables"]:
        if not t["row_pages"]:
            continue
        p = min(t["row_pages"])
        page = pdf[p - 1]
        top = table_top(t, page)
        # A line's key joined with the next two: the PDF often prints "4." and "Further, ..."
        # as separate pieces at the same height, so the paragraph's start spans pieces.
        pieces = [(y, key(text)) for y, text in lines_with_y(page)]
        ys = [(y, "".join(k for _, k in pieces[n:n + 3])) for n, (y, _) in enumerate(pieces)]
        starts = []
        for u in units:
            if u.page_start == p and u.unit_type == "paragraph":
                first = key(u.text.split("\n", 1)[0])[:30]
                y = next((y for y, k in ys if first and k.startswith(first[:20])), None)
                if y is not None:
                    starts.append((y, u))
        above = [u for y, u in sorted(starts, key=lambda s: s[0]) if top is not None and y < top]
        earlier = [u for u in units if u.page_start < p and u.unit_type == "paragraph"]
        owner = above[-1] if above else (earlier[-1] if earlier else
                                         next((u for u in units if u.unit_type == "paragraph"), units[-1]))
        owner.table_ids.append(t["table_id"])
        out.append({"table_id": t["table_id"], "owner": owner, "pages": sorted(set(t["row_pages"])),
                    "headings": [" ".join(str(h).split()) for h in t["headings"] or []],
                    "rows": [[" ".join(str(c).split()) for c in row] for row in t["rows"]]})
    return out


def self_check(units: list[Unit], lines: list[tuple[int, str]], tables: list[dict]) -> dict[str, str]:
    problems = {}
    body = "\n".join(l for _, l in lines)
    kept, text_only = Counter(), Counter()
    for u in units:
        kept += words(" ".join([u.heading, u.parent, u.text]))
        text_only += words(u.text)
    if lost := words(body) - kept:
        problems["words_lost"] = f"{sum(lost.values())}, e.g. {lost.most_common(6)}"
    if doubled := text_only - words(body):
        problems["words_doubled"] = f"{sum(doubled.values())}, e.g. {doubled.most_common(6)}"
    wrong = [u.location for u in units if u.unit_type == "paragraph" and u.location.startswith("para ")
             and u.location != "para 1" and not u.text.startswith(u.location.removeprefix("para "))]
    if wrong:
        problems["wrong_start"] = f"{len(wrong)}: {wrong[:4]}"
    return problems


def manifest_files() -> list[dict]:
    return [r for r in map(json.loads, MANIFEST.open()) if r["doc_type"] in TYPES]


def main() -> None:
    green, red, reset = ("\033[32m", "\033[31m", "\033[0m") if sys.stdout.isatty() else ("", "", "")
    one = sys.argv[1] if len(sys.argv) > 1 else None
    rows = [r for r in manifest_files() if not one or r["file"] == one]
    totals, failed, warned, missing, sizes = Counter(), [], Counter(), [], []
    for r in rows:
        path = INGESTED / f"{r['file']}.json"
        if not path.exists():
            missing.append(r["file"])
            continue
        units, tables, problems, warnings = split(json.loads(path.read_text()))
        out = UNITS / f"{r['file']}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join(json.dumps(asdict(u), ensure_ascii=False) + "\n" for u in units))
        if tables:
            (UNITS / f"{r['file']}.tables.jsonl").write_text(
                "".join(json.dumps(t, ensure_ascii=False) + "\n" for t in tables))
        totals[r["doc_type"]] += 1
        totals["units"] += len(units)
        totals["tables"] += len(tables)
        sizes += [u.token_count for u in units if u.unit_type == "paragraph"]
        for w in warnings:
            warned[w.split(":")[0]] += 1
        if problems:
            failed.append((r["file"], problems))
        if one:
            for u in units:
                print(f"--- {u.location} | {u.unit_type} | p.{u.page_start}-{u.page_end} | {u.unit_id} | "
                      f"{u.token_count} tokens | tables {len(u.table_ids)}")
                print("    " + u.text[:200].replace("\n", " ") + (" ..." if len(u.text) > 200 else ""))
            print(f"\nsubject: {units[0].parent if units and units[0].parent else (units[1].parent if len(units) > 1 else '')}")
            print("warnings:", warnings or "none")

    print(f"\nfiles {sum(totals[t] for t in TYPES)} (" + ", ".join(f"{t} {totals[t]}" for t in TYPES) + f"); "
          f"units {totals['units']}; tables linked {totals['tables']}")
    if missing:
        print(f"{red}not extracted yet{reset}: {len(missing)}, e.g. {missing[:3]}")
    print("warnings, files per kind:", dict(warned.most_common()))
    if sizes:
        s = sorted(sizes)
        print(f"paragraph tokens: median {s[len(s) // 2]}, largest {s[-3:][::-1]}, over 512: {sum(x > 512 for x in s)} of {len(s)}")
    print(f"\nself-check: {green}all passed{reset}" if not failed else f"\nself-check failed in {len(failed)} files:")
    for file, problems in failed[:15]:
        print(f"  {red}{file}{reset}: {problems}")


if __name__ == "__main__":
    main()
