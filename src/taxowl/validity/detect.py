"""Withdrawal detector: which circular was withdrawn or changed, and by which one.

Circulars say it themselves, in three places:
    body of the new circular    127/46/2019: "hereby withdraws, ab-initio, Circular No. 107/26/2019"
                                125/44/2019: "in supersession of earlier Circulars viz. 17/17/2017, 24/24/2017, ..."
    CBIC's title of the old one  94/13/2019: "... Rescinded vide Circular No. 125/44/2019"
    a passing mention elsewhere  135/05/2020: "Circular 37/11/2018 ... was rescinded being subsumed in 125/44/2019"

Two steps:
  1. find (free, regex): a window of text around a change word (withdraw, rescind, supersede, amend,
     modify, omit, substitute) that also holds a circular number. The word alone isn't enough:
     "withdrawal of SLP" or "order deemed withdrawn" are about other things and have no circular number.
  2. judge (Jev, a few cents at most): for each (window, circular) pair, a choice question:
     withdrawn as a whole / partly modified / not (only mentioned). And a second one: which circular did it.
     Regex finds the place; Jev reads the sentence. Each answer comes with its probability.

The output is a list for a person to check (the `ok` column), not the final status: the checked list
gives the detector's precision, and the next step turns it into each chunk's status.

    uv run python -m taxowl.validity.detect --dry-run   # step 1 only: how many pairs, no Jev
    uv run python -m taxowl.validity.detect             # both steps -> data/validity/candidates.csv

Jev's answers are saved in data/validity/jev_answers.jsonl, so a rerun asks only new pairs.
Why no agent (LangGraph): the steps are fixed and the same for every circular; nothing for a model to plan.
"""

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict

from taxowl.config import CHUNKS, MANIFEST, ROOT

VALIDITY = ROOT / "data" / "validity"
CANDIDATES = VALIDITY / "candidates.csv"   # judged as a change: the list to check by hand
REJECTED = VALIDITY / "rejected.csv"       # judged "not": skim the unsure ones for misses
ANSWERS = VALIDITY / "jev_answers.jsonl"   # cache: pair key -> Jev's answer

WORDS = re.compile(r"withdr\w*|rescind\w*|supersed\w*|supersession|amend\w*|modif\w*|omitted|substitut\w*", re.I)
# 107/26/2019, 70/44/2018 -GST, 212/6/2024. Not 39/2018-Central Tax (a notification: two parts).
NUMBER = re.compile(r"(?<![\d/])(\d{1,3})\s*/\s*(\d{1,3})\s*/\s*(20\d\d)(?![\d/])")
REACH = 300          # characters kept on each side of a change word, at least
LONGEST = 1500       # ...and up to this many after it, to finish the sentence (a long list of circulars)
# A full stop that ends a sentence: next comes a capital, a bracket or the end. Not "viz.", "No.", "dt." etc.
SENTENCE_END = re.compile(r"(?<!\bviz)(?<!\bNo)(?<!\bNos)(?<!\bdt)(?<!\bRs)(?<!\bSr)(?<!\bSl)(?<!\bS)"
                          r"(?<!\bvs)(?<!\bi\.e)(?<!\be\.g)\.(?=\s+[A-Z(\"“]|\s*$)")
UNSURE = 0.6         # Jev confidence below this is marked "unsure" for the person checking


def norm(text: str) -> str | None:
    """'70/44/2018 -GST' -> '70/44/2018'; '212/06/2024-GST' -> '212/6/2024' (so both spellings match)."""
    m = NUMBER.search(text or "")
    return f"{int(m[1])}/{int(m[2])}/{m[3]}" if m else None


def load_circulars() -> dict[str, dict]:
    """Every circular in the corpus: normalised number -> its manifest row. Only these can get a status."""
    found = {}
    for row in map(json.loads, MANIFEST.open(encoding="utf-8")):
        if row["doc_type"] == "circulars" and norm(row["number"]):
            found[norm(row["number"])] = row
    return found


# ---------------------------------------------------------------- step 1: find

def windows(text: str) -> list[str]:
    """The text around each change word, with nearby ones merged into one window.
    The window runs to the end of the change word's sentence: 125/44/2019 lists eight superseded circulars
    in one sentence, and a fixed 300 characters cut the last one (94/13/2019) off."""
    spans = []
    for m in WORDS.finditer(text):
        stop = SENTENCE_END.search(text, m.end(), m.end() + LONGEST)
        start = max(0, m.start() - REACH)
        end = min(len(text), max(m.end() + REACH, stop.end() if stop else 0))
        if spans and start <= spans[-1][1]:
            spans[-1][1] = end
        else:
            spans.append([start, end])
    return [" ".join(text[a:b].split()) for a, b in spans]


def sources(circulars: dict[str, dict]) -> list[dict]:
    """Where to look: each circular's CBIC title once, and the body of every circular and instruction chunk
    (without its first line, which repeats the title in every chunk)."""
    out = [{"doc": number, "doc_label": f"Circular No. {row['number']} dated {row['date']}", "self": number,
            "part": "title", "chunk_id": "", "text": row["title"]}
           for number, row in circulars.items()]
    for chunk in map(json.loads, CHUNKS.open(encoding="utf-8")):
        if chunk["doc_type"] not in ("circular", "instruction"):
            continue
        body = chunk["text"].split("\n", 1)[1] if "\n" in chunk["text"] else chunk["text"]
        own = norm(chunk["doc_number"]) if chunk["doc_type"] == "circular" else None
        name = "Circular No." if chunk["doc_type"] == "circular" else ""
        out.append({"doc": own or chunk["doc_number"], "self": own, "part": "body", "chunk_id": chunk["chunk_id"],
                    "doc_label": f"{name} {chunk['doc_number']} dated {chunk['doc_date']}".strip(),
                    "text": body})
    return out


def find(circulars: dict[str, dict]) -> tuple[list[dict], Counter]:
    """(window, circular) pairs to judge. A window with no circular number of the corpus is skipped.
    The document's own number is a target too: its CBIC title says "Rescinded vide Circular No. Y"."""
    pairs, seen, counts = [], set(), Counter()
    for source in sources(circulars):
        for window in windows(source["text"]):
            counts["windows"] += 1
            numbers = {norm(m[0]) for m in NUMBER.finditer(window)}
            known = {n for n in numbers if n in circulars} - {source["self"]}
            counts["numbers not in corpus"] += len(numbers - set(circulars) - {source["self"]})
            if not known:
                counts["windows without a corpus circular number (skipped)"] += 1
                continue
            for target in sorted(known | ({source["self"]} if source["self"] else set())):
                key = (target, window)
                if key in seen:  # the same sentence in two chunks (a table and its text)
                    continue
                seen.add(key)
                others = sorted((known | {source["self"]}) - {target, None})
                pairs.append({**source, "window": window, "target": target, "others": others})
    counts["pairs"] = len(pairs)
    return pairs, counts


# ---------------------------------------------------------------- step 2: judge

def questions(pair: dict) -> tuple[dict, dict, dict[str, str]]:
    """Jev's state and two choice questions. Returns (state, questions, option key -> circular number)."""
    from deepeval.models.system_one.schema import ChoiceQuestion

    target = pair["target"]
    state = {"document": pair["doc_label"], "part": "CBIC's title of the document" if pair["part"] == "title"
             else "text of the document", "text": pair["window"]}
    status = ChoiceQuestion(
        instructions=f"What does the text say about Circular No. {target}?",
        options={
            "withdrawn": f"Circular {target} as a whole is withdrawn, rescinded, superseded or replaced "
                         "(from now on, or ab initio).",
            "partly_modified": f"Only part of Circular {target} is amended, modified, substituted or omitted "
                               "(a para, an entry, a date, an officer); the rest of it stays in force.",
            "not": f"Circular {target} is only mentioned or relied on; or what is withdrawn or amended is "
                   "something else (an appeal, an SLP, a notice, an order, a notification, the Act, an option).",
        })
    by_options, by_numbers = {}, {}
    if pair["self"] and pair["self"] != target:
        by_options["this"] = f"{pair['doc_label']}, the document itself"
        by_numbers["this"] = pair["self"]
    for i, number in enumerate(n for n in pair["others"] if n != pair["self"]):
        by_options[f"c{i}"] = f"Circular No. {number}"
        by_numbers[f"c{i}"] = number
    by_options["unclear"] = "The text doesn't say which circular does it"
    by = ChoiceQuestion(instructions=f"If Circular {target} is withdrawn or changed, which circular does it?",
                        options=by_options)
    return state, {"status": status, "by": by}, by_numbers


def pair_key(state: dict, asked: dict) -> str:
    """Same state and same questions -> same key, so a cached answer is reused only for the same ask."""
    text = json.dumps({"state": state, "q": {k: q.model_dump() for k, q in asked.items()}}, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def judge(pairs: list[dict]) -> list[dict]:
    """Ask Jev about every pair (or reuse a saved answer). Adds status, by, probabilities to each pair."""
    from taxowl.jev import make_jev

    VALIDITY.mkdir(parents=True, exist_ok=True)
    cache = {}
    if ANSWERS.exists():
        cache = {row["key"]: row for row in map(json.loads, ANSWERS.open(encoding="utf-8"))}
    jev, cost, asked_now = None, 0.0, 0
    with ANSWERS.open("a", encoding="utf-8") as saved:
        for i, pair in enumerate(pairs, 1):
            state, asked, by_numbers = questions(pair)
            key = pair_key(state, asked)
            if key not in cache:
                jev = jev or make_jev()
                try:
                    answers, spent = jev.decide(state, asked)
                except Exception as error:  # one failed call shouldn't lose the rest; it shows in the CSV
                    pair.update(status="error", by="", p_status="", confidence="", note=str(error)[:200])
                    continue
                cost += spent or 0
                asked_now += 1
                row = {"key": key,
                       "status": answers.choices["status"].choice,
                       "p_status": answers.choices["status"].probabilities,
                       "confidence": answers.choices["status"].confidence,
                       "by": answers.choices["by"].choice, "p_by": answers.choices["by"].probabilities}
                cache[key] = row
                saved.write(json.dumps(row) + "\n")
            row = cache[key]
            pair.update(status=row["status"], p_status=round(row["p_status"][row["status"]], 3),
                        confidence=round(row["confidence"], 3), by=by_numbers.get(row["by"], row["by"]), note="")
            if i % 25 == 0:
                print(f"  {i} of {len(pairs)} judged")
    print(f"Jev asked {asked_now} new pairs (others from {ANSWERS.relative_to(ROOT)}), cost ${cost:.4f}")
    return pairs


# ---------------------------------------------------------------- output

COLUMNS = ["ok", "target", "status", "by", "p_status", "confidence", "unsure", "doc", "part", "chunk_id",
           "window", "note"]


def check_key(row: dict) -> tuple:
    """What a person's y/n is about: this target, this status, by this circular, in this part of this doc.
    Not the window text, so a check survives a change in window size."""
    return row["target"], row["status"], row["by"], row["doc"], row["part"]


def old_checks() -> dict[tuple, tuple[str, str]]:
    """The y/n (and note) already filled in candidates.csv, so a rerun doesn't wipe them.
    A key whose old rows disagree is left out: that row is checked again."""
    if not CANDIDATES.exists():
        return {}
    seen = defaultdict(set)
    with CANDIDATES.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["ok"] in ("y", "n"):
                seen[check_key(row)].add((row["ok"], row["note"]))
    return {key: next(iter(v)) for key, v in seen.items() if len({ok for ok, _ in v}) == 1}


def write(pairs: list[dict]) -> None:
    """Changes into candidates.csv (to check), "not" into rejected.csv (to skim), both easy to open in a sheet.
    Earlier y/n in candidates.csv are carried over; rows without one are new and need a check."""
    order = {"withdrawn": 0, "partly_modified": 1, "error": 2, "not": 3}
    pairs.sort(key=lambda p: (order.get(p.get("status"), 9), p["target"], p["doc"]))
    checks = old_checks()
    for pair in pairs:
        conf = pair.get("confidence")
        pair["unsure"] = "unsure" if isinstance(conf, float) and conf < UNSURE else ""
        pair["ok"], pair["note"] = checks.get(check_key(pair), ("", pair.get("note", "")))
    changes = [p for p in pairs if p.get("status") != "not"]
    print(f"checks carried over: {sum(1 for p in changes if p['ok'])}, "
          f"rows to check: {sum(1 for p in changes if not p['ok'])}")
    for path, rows in ((CANDIDATES, [p for p in pairs if p.get("status") != "not"]),
                       (REJECTED, [p for p in pairs if p.get("status") == "not"])):
        with path.open("w", newline="", encoding="utf-8") as f:
            out = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
            out.writeheader()
            out.writerows(rows)
        print(f"{len(rows):>4} rows -> {path.relative_to(ROOT)}")


def summary(pairs: list[dict]) -> None:
    """How many circulars come out withdrawn or changed, counting each circular once."""
    by_target = defaultdict(set)
    for pair in pairs:
        by_target[pair["target"]].add(pair.get("status"))
    withdrawn = {t for t, s in by_target.items() if "withdrawn" in s}
    partly = {t for t, s in by_target.items() if "partly_modified" in s} - withdrawn
    print(f"\ncirculars judged withdrawn: {len(withdrawn)}, partly modified: {len(partly)} "
          f"(of {len(by_target)} looked at)")
    print("pairs by status:", dict(Counter(p.get("status") for p in pairs)))
    print("unsure (confidence < {UNSURE}):".replace("{UNSURE}", str(UNSURE)),
          sum(1 for p in pairs if isinstance(p.get("confidence"), float) and p["confidence"] < UNSURE))


def main() -> None:
    parser = argparse.ArgumentParser(description="Find withdrawn / changed circulars (regex finds, Jev judges)")
    parser.add_argument("--dry-run", action="store_true", help="find the pairs and stop: no Jev, no cost")
    parser.add_argument("--limit", type=int, help="judge only the first N pairs (a cheap first look)")
    args = parser.parse_args()

    circulars = load_circulars()
    pairs, counts = find(circulars)
    print(f"{len(circulars)} circulars in the corpus")
    for name, n in counts.items():
        print(f"  {name}: {n}")

    if args.dry_run:
        print("\nexamples:")
        for pair in pairs[:: max(1, len(pairs) // 8)][:8]:
            print(f"  [{pair['doc']} {pair['part']}] target {pair['target']}: {pair['window'][:160]}")
        return

    if args.limit:
        pairs = pairs[:args.limit]
    judge(pairs)
    VALIDITY.mkdir(parents=True, exist_ok=True)
    write(pairs)
    summary(pairs)


if __name__ == "__main__":
    main()
