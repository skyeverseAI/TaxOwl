"""Sample: ask a vision model (Jev Router on OpenRouter) whether a page has a nested table.

Why: find_nested.py decides "nested" from the table grid PyMuPDF draws. A vision model looks at the
page picture instead, so it's an independent second opinion. If the two agree on pages we checked by
eye, a VLM could judge uploaded PDFs later, where nobody has checked anything (plans/fde_plan.md).

How:
  1. Turn one PDF page into a PNG with PyMuPDF.
  2. Send it to `typesafe/jev-router` with a JSON schema, so the reply is {"nested": bool, "reason": str}.
     Jev Router picks the underlying model per request, so we print which model actually answered.
  3. Print the rule's verdict (find_nested.is_nested) next to the model's.

Default test pages (both checked by eye):
  circulars/2020/133-03-2020-GST.pdf page 5   nested (worked example inside an answer)
  circulars/2022/182-14-2022-GST.pdf page 13  NOT nested (two-row heading "Amount" -> CGST / SGST)

Usage:
    uv run ingestion/vlm_nested.py                     # the two default pages
    uv run ingestion/vlm_nested.py circulars/2020/136-06-2020-GST.pdf 4
Needs OPENROUTER_API_KEY in .env (project root).
"""

import base64
import json
import sys
import time
import urllib.request
from pathlib import Path

import pymupdf

from find_nested import is_nested

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
MODEL = "typesafe/jev-router"
URL = "https://openrouter.ai/api/v1/chat/completions"
DPI = 150  # readable for a model, small enough to upload quickly

DEFAULT_PAGES = [
    ("circulars/2020/133-03-2020-GST.pdf", 5),
    ("circulars/2022/182-14-2022-GST.pdf", 13),
]

PROMPT = """Look at this page from an Indian GST circular.

Does it contain a NESTED table: a complete table (its own rows and columns) drawn INSIDE one cell
of another table?

These are NOT nested:
- a two-row heading, e.g. "Amount" spanning "CGST | SGST" in the header;
- a full-width row that only labels a section of the table;
- two separate tables one after the other.

Answer only from what you see on the page."""

SCHEMA = {
    "name": "nested_check",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "nested": {"type": "boolean"},
            "reason": {"type": "string", "description": "one sentence: where the inner table is, or why there is none"},
        },
        "required": ["nested", "reason"],
        "additionalProperties": False,
    },
}


def load_key():
    # Tiny .env reader, so we don't add a dependency for one line. Never print the key.
    for line in (ROOT / ".env").read_text().splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "OPENROUTER_API_KEY":
            return value.strip().strip("\"'")
    sys.exit("OPENROUTER_API_KEY not found in .env")


def page_png(pdf, page_no):
    return pdf[page_no - 1].get_pixmap(dpi=DPI).tobytes("png")


def ask_model(png, key):
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}},
        ]}],
        "response_format": {"type": "json_schema", "json_schema": SCHEMA},
        "temperature": 0,
    }
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    })
    start = time.time()
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.load(resp)
    seconds = time.time() - start
    answer = json.loads(data["choices"][0]["message"]["content"])
    return answer, data.get("model", "?"), data.get("usage", {}), seconds


def main():
    pages = [(sys.argv[1], int(sys.argv[2]))] if len(sys.argv) == 3 else DEFAULT_PAGES
    key = load_key()
    for rel, page_no in pages:
        with pymupdf.open(DOCS / rel) as pdf:
            rule = any(is_nested(t) for t in pdf[page_no - 1].find_tables().tables)
            png = page_png(pdf, page_no)
        answer, used_model, usage, seconds = ask_model(png, key)
        agree = "agree" if answer["nested"] == rule else "DISAGREE"
        print(f"{rel}  page {page_no}")
        print(f"  rule (find_nested): {'nested' if rule else 'not nested'}")
        print(f"  model: {'nested' if answer['nested'] else 'not nested'}  -> {agree}")
        print(f"  reason: {answer['reason']}")
        print(f"  answered by {used_model} in {seconds:.1f}s, tokens {usage.get('total_tokens', '?')}"
              f", cost {usage.get('cost', '?')}\n")


if __name__ == "__main__":
    main()
