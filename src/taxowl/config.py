"""Where the project's files live. Every stage imports its paths from here.

Paths only: a stage's own settings (model name, limits) stay with the stage that uses them.
Nothing here imports another taxowl module, so any file can import this one safely.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # this file is <root>/src/taxowl/config.py

# Inputs
DOCS = ROOT / "docs"                     # the source PDFs
MANIFEST = DOCS / "manifest.jsonl"       # one row per PDF: file, doc_type, number ...
OCR_DIR = DOCS / "ocr"                   # saved OCR text, tracked in git so it isn't redone

# What each stage produces
INGESTED = ROOT / "data" / "ingested"    # extractor: <file>.json per PDF
UNITS = ROOT / "data" / "units"          # splitter: <file>.jsonl, one Unit per line
CHUNKS = ROOT / "data" / "chunks.jsonl"  # chunker: one Chunk per line, what gets embedded
VLM_CACHE = ROOT / "data" / "cache" / "vlm"  # saved Gemini table answers, so they aren't paid for twice
