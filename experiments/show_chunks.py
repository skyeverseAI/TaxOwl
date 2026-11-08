"""Show the chunks of one document (or one part of it), to pick or check gold chunk ids by eye.

    uv run experiments/show_chunks.py "162/18/2021" "para 3"
    uv run experiments/show_chunks.py "CGST Rules" "rule 37"
    uv run experiments/show_chunks.py "Act 12 of 2017" "section 17(5)" --full

The first argument is any part of the document number (Act 12 of 2017 = the CGST Act, CGST Rules, 2017,
IGST Act, 2017, a circular number ...). The second, optional, is the start of the location label.
Reads data/chunks.jsonl only: no store, no model, so it answers at once.
"""

import argparse
import json

from taxowl.config import CHUNKS

PREVIEW_LINES = 4


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("doc", help="part of the document number, e.g. 162/18/2021 or 'CGST Rules'")
    parser.add_argument("location", nargs="?", default="", help="start of the location, e.g. 'para 3' or 'rule 37'")
    parser.add_argument("--full", action="store_true", help="print the whole text, not the first lines")
    args = parser.parse_args()

    found = 0
    with open(CHUNKS, encoding="utf-8") as f:
        for line in f:
            chunk = json.loads(line)
            if args.doc.lower() not in chunk["doc_number"].lower():
                continue
            if not chunk["location"].startswith(args.location):
                continue
            found += 1
            body = chunk["text"].split("\n", 1)[-1].strip()  # the first line is the header, not the law
            lines = body.splitlines() if args.full else body.splitlines()[:PREVIEW_LINES]
            print(f"\n{chunk['chunk_id']}   {chunk['location']}   p.{chunk['page_start']}-{chunk['page_end']}"
                  f"   {chunk['kind']}   (section/para: {chunk['unit_id']})")
            for text in lines:
                print(f"    {text}")
    print(f"\n{found} chunks")


if __name__ == "__main__":
    main()
