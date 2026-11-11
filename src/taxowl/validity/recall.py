"""Detector recall: of the changes CBIC itself wrote in its titles, how many does the detector find in the BODY?

CBIC's titles carry a status note on some circulars. That is a free answer key:
    94/13/2019 title:  "... Rescinded vide Circular No. 125/44/2019"   -> 94/13/2019 withdrawn by 125/44/2019
    253/10/2025 title: "Regarding withdrawal of circular No. 212/6/2024" -> 212/6/2024 withdrawn by 253/10/2025
    49/23/2018 title:  "Seeks to modify Circular No. 41/15/2018"         -> 41/15/2018 partly modified by 49/23/2018

Only body rows count as found: a user's uploaded PDF has no CBIC title, so the body is the real test.
Matching the title key against title rows would be checking the key against itself.

Each miss gets a reason, so the fix is clear:
    "Jev said ..."      a window was found but judged wrong (prompt or model problem)
    "no window"         regex never put the two numbers in one window (window too short, or no change word)

    uv run python -m taxowl.validity.recall    # needs candidates.csv and rejected.csv from detect.py

Writes data/validity/title_key.csv (the key, with an `ok` column for a person to check once).
"""

import csv
import re

from taxowl.config import ROOT
from taxowl.validity.detect import CANDIDATES, NUMBER, REJECTED, VALIDITY, load_circulars, norm

KEY = VALIDITY / "title_key.csv"
OWN_STATUS = re.compile(r"rescinded vide|superseded vide|withdrawn vide", re.I)  # note on the OLD circular
WITHDRAWS = re.compile(r"withdr\w*|rescind\w*|supersed\w*", re.I)                 # NEW circular withdraws one
MODIFIES = re.compile(r"modif\w*|amend\w*", re.I)                                 # NEW circular changes one


def title_key(circulars: dict[str, dict]) -> list[dict]:
    """(target, status, by) pairs read from CBIC's titles. Numbers outside the corpus are skipped."""
    key = []
    for number, row in circulars.items():
        title = row["title"]
        others = [n for n in (norm(m[0]) for m in NUMBER.finditer(title)) if n in circulars and n != number]
        if not others:
            continue
        if OWN_STATUS.search(title):            # "Rescinded vide Circular No. Y": this one is the target
            pairs = [(number, "withdrawn", others[0])]
        elif WITHDRAWS.search(title):           # "Seeks to withdraw Circular No. X": this one does it
            pairs = [(n, "withdrawn", number) for n in others]
        elif MODIFIES.search(title):            # "Seeks to modify / Amendment to Circular No. X"
            pairs = [(n, "partly_modified", number) for n in others]
        else:
            continue
        key += [{"target": t, "status": s, "by": b, "title_of": number, "title": title} for t, s, b in pairs]
    return sorted(key, key=lambda k: (k["status"], k["target"]))


def read(path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def check(pair: dict, body: list[dict]) -> tuple[bool, str]:
    """Found if a body row (not marked wrong by the checker) has the same target and the same `by`.
    Otherwise say why: what Jev answered on the closest window, or that no window held both numbers."""
    target, by = pair["target"], pair["by"]
    for row in body:
        if row["target"] == target and row["by"] == by and row["status"] != "not" and row.get("ok") != "n":
            status_note = "" if row["status"] == pair["status"] else f" (detector says {row['status']})"
            return True, f"in {row['doc']} body{status_note}"
    near = [r for r in body if r["target"] == target and by in (r["doc"], r["by"])]
    if near:
        r = near[0]
        return False, f"Jev said {r['status']}, by {r['by']} (window in {r['doc']}{', marked n' if r.get('ok') == 'n' else ''})"
    return False, "no window held both numbers"


def main() -> None:
    circulars = load_circulars()
    key = title_key(circulars)
    with KEY.open("w", newline="", encoding="utf-8") as f:
        out = csv.DictWriter(f, fieldnames=["ok", "target", "status", "by", "title_of", "title"])
        out.writeheader()
        out.writerows({"ok": "", **k} for k in key)
    print(f"{len(key)} pairs in the title key -> {KEY.relative_to(ROOT)} (check the `ok` column once)\n")

    body = [r for r in read(CANDIDATES) + read(REJECTED) if r["part"] == "body"]
    found = 0
    print(f"{'':2} {'target':12} {'status':16} {'by':12} result")
    for pair in key:
        hit, why = check(pair, body)
        found += hit
        print(f"{'✓' if hit else '✗':2} {pair['target']:12} {pair['status']:16} {pair['by']:12} {why}")

    print(f"\nrecall (body only): {found}/{len(key)} = {found / len(key):.2f}" if key else "\nno key pairs")
    for status in ("withdrawn", "partly_modified"):
        part = [p for p in key if p["status"] == status]
        hits = sum(check(p, body)[0] for p in part)
        if part:
            print(f"  {status:16} {hits}/{len(part)}")


if __name__ == "__main__":
    main()
