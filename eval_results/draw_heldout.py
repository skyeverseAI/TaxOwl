"""Draw held-out pages for a second gold set, to test whether the extractor overfits the first one.

Why: extract.py's rules were tuned until eval_results/gold/ingestion_gold.json passed 256/256. A score on the
pages you tuned on only shows the rules fit those pages. Pages the rules have never seen show
whether they generalize.

How:
  - Pages are drawn at random with a fixed seed, so nobody picks easy pages by accident, and
    anyone who reruns this gets the same pages.
  - The draw is split by kind, so every kind of page is covered (see HOW_MANY).
  - No file from the first gold set is used, and each drawn file gives only one page.
  - Each page is saved as an image, because the gold checks are written from the page image,
    never from an extractor's output.

Usage:
    uv run eval_results/draw_heldout.py              # the first held-out draw (seed 2026)
    uv run eval_results/draw_heldout.py --seed 2027  # a fresh draw, skipping every file already in a gold set
Writes eval_results/draws/heldout_draw.json and eval_results/pages/heldout_pages/*.png (or heldout_draw_<seed>.json and
heldout_pages_<seed>/ for another seed), then prints the drawn pages.
"""

import csv
import json
import random
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
GOLD = ROOT / "eval_results" / "gold" / "ingestion_gold.json"
TABLE_REPORT = ROOT / "eval_results" / "draws" / "table_report.csv"
SCAN_REPORT = ROOT / "eval_results" / "draws" / "scan_report.csv"
OUT = ROOT / "eval_results" / "draws" / "heldout_draw.json"
IMAGES = ROOT / "eval_results" / "pages" / "heldout_pages"

SEED = 2026
HOW_MANY = {"table": 5, "scan": 1, "plain": 2, "act": 1, "rules": 1}
DPI = 150

ACT = "GST_act.pdf"
RULES = "GST Act(s) and Rule(s)-Bare Law.pdf"
ACT_PAGES = (10, 124)    # section 1 to section 174; the Schedules (p.125 on) are left out
RULES_PAGES = (186, 363)  # rule 1 to rule 164; the IGST Rules and the rest of the book are left out


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def table_pages(file):
    """Pages of a PDF where PyMuPDF finds at least one table."""
    with pymupdf.open(DOCS / file) as pdf:
        return [i + 1 for i, page in enumerate(pdf) if page.find_tables().tables]


def page_count(file):
    with pymupdf.open(DOCS / file) as pdf:
        return len(pdf)


def draw(rng, gold_files, gold_pages):
    status = {r["file"]: r["status"] for r in read_csv(SCAN_REPORT)}
    tables = {r["file"]: int(r["tables_found"]) for r in read_csv(TABLE_REPORT)}
    unused = [f for f in sorted(status) if f not in gold_files and f not in (ACT, RULES)]
    born_digital = [f for f in unused if status[f] == "ok"]

    picks = []

    # Table pages: walk the table files in random order, one table page from each.
    pool = [f for f in born_digital if tables.get(f, 0) > 0]
    rng.shuffle(pool)
    for file in pool:
        if sum(p["kind"] == "table" for p in picks) == HOW_MANY["table"]:
            break
        pages = table_pages(file)
        if pages:
            picks.append({"kind": "table", "file": file, "page": rng.choice(pages)})

    # Scans and plain pages: random file, random page.
    for kind, pool in [("scan", [f for f in unused if status[f] == "scan"]),
                       ("plain", [f for f in born_digital if tables.get(f, 0) == 0])]:
        if len(pool) < HOW_MANY[kind]:
            # Only 8 scans, and seeds 2026-2033 used one each: from seed 2034 a scan already in a
            # gold set gives a page no gold set has. (Not taken when unused files remain, so the
            # older seeds still draw the same pages.)
            used = sorted(f for f in status if status[f] == "scan" and f in gold_files) if kind == "scan" else []
            for file in rng.sample(used, HOW_MANY[kind] - len(pool)):
                fresh = [p for p in range(1, page_count(file) + 1) if p not in gold_pages.get(file, set())]
                if fresh:
                    picks.append({"kind": kind, "file": file, "page": rng.choice(fresh)})
            pool = pool[:HOW_MANY[kind]]
        for file in rng.sample(pool, min(HOW_MANY[kind], len(pool))):
            picks.append({"kind": kind, "file": file, "page": rng.randint(1, page_count(file))})

    # The Act and the Rules: random page inside the given range, skipping the gold page.
    for kind, file, (first, last) in [("act", ACT, ACT_PAGES), ("rules", RULES, RULES_PAGES)]:
        pages = [p for p in range(first, last + 1) if p not in gold_pages.get(file, set())]
        for page in rng.sample(pages, HOW_MANY[kind]):
            picks.append({"kind": kind, "file": file, "page": page})

    return picks


def save_images(picks, images):
    images.mkdir(exist_ok=True)
    for i, p in enumerate(picks, 1):
        name = f"{i:02d}-{p['kind']}-{Path(p['file']).stem}-p{p['page']}.png"
        with pymupdf.open(DOCS / p["file"]) as pdf:
            pdf[p["page"] - 1].get_pixmap(dpi=DPI).save(images / name)
        p["image"] = f"eval_results/{images.name}/{name}"


def main():
    # A new seed is a fresh draw (after fixes, the old held-out pages count as seen). It goes to
    # its own files, and skips the files of every existing gold set: eval_results/gold/ingestion_*.json.
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else SEED
    out, images = (OUT, IMAGES) if seed == SEED else (
        OUT.with_name(f"heldout_draw_{seed}.json"), IMAGES.with_name(f"heldout_pages_{seed}"))

    gold = [c for path in sorted(GOLD.parent.glob("ingestion_*.json")) for c in json.loads(path.read_text())["pages"]]
    gold_files = {c["file"] for c in gold}
    gold_pages = {}
    for c in gold:
        gold_pages.setdefault(c["file"], set()).update(c["pages"])

    picks = draw(random.Random(seed), gold_files, gold_pages)
    save_images(picks, images)
    out.write_text(json.dumps({"seed": seed, "pages": picks}, indent=2) + "\n")

    for p in picks:
        print(f"{p['kind']:<6} p.{p['page']:<4} {p['file']}")
    print(f"\n{len(picks)} pages -> {out.relative_to(ROOT)}, images in {images.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
