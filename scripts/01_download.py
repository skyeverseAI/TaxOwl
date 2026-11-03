"""Download GST circulars, instructions and recent notifications from the CBIC tax-information portal.

The portal (taxinformation.cbic.gov.in) is a JavaScript app. Behind it is a JSON API:
  - a "list" endpoint gives every document's metadata (number, title, date, id)
  - a "download" endpoint gives one PDF, base64-encoded inside JSON: {"data": "<base64>"}

Files are saved as docs/<doc_type>/<year>/<number>.pdf, and one row per file goes into
docs/manifest.jsonl (paths in it are relative to docs/). Re-running only downloads what is missing or broken.

Usage:
    python3 scripts/01_download.py              # everything
    python3 scripts/01_download.py --limit 3    # first 3 of each type (quick test)
"""

import argparse
import base64
import hashlib
import json
import re
import ssl
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://taxinformation.cbic.gov.in/api"
GST_TAX_ID = 1000001
NOTIFICATIONS_AFTER = "2026-03-31"  # the ICAI Rules PDF already covers everything up to this date
DELAY_SECONDS = 1.0                 # pause between downloads, to be polite to the server
RETRIES = 5
INTERMEDIATE_CERT_URL = "http://crt.sectigo.com/SectigoPublicServerAuthenticationCAOVR36.crt"
PORTAL_PAGE = {"circulars": "explore-circulars", "instructions": "explore-instructions",
               "notifications": "explore-notification"}

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs"

# The Act and the Rules are not on the portal in a current form, so they were downloaded by hand
# (see plans/plan_ingestion.md, section A). They are listed here so the manifest covers every file.
# "as_of" is the date the consolidated text is up to date with.
MANUAL_DOCS = [
    {"doc_type": "act", "number": "Act 12 of 2017",
     "title": "The Central Goods and Services Tax Act, 2017 (as amended)",
     "date": "2026-06-11", "as_of": "2026-06-11", "file": "GST_act.pdf",
     "official_url": "https://www.indiacode.nic.in/indiacode/bitstream/123456789/15689/1/A2017-12.pdf",
     "publisher": "India Code (Legislative Department)", "official": True},
    {"doc_type": "rules", "number": "CGST Rules, 2017",
     "title": "GST Act(s) and Rule(s) - Bare Law, 12th edition (parts used: CGST Rules, IGST Act, IGST Rules, UTGST Act, Compensation Act; pages in src/taxowl/splitting/known_docs.json)",
     "date": "2026-04-15", "as_of": "2026-03-31", "file": "GST Act(s) and Rule(s)-Bare Law.pdf",
     "official_url": "https://idtc.icai.org",
     "publisher": "ICAI GST & Indirect Taxes Committee", "official": False},
]


def make_ssl_context():
    """The CBIC server sends its own certificate but not the 'middle' (intermediate) one that links it to a
    trusted root, so Python refuses the connection. Browsers and curl fetch the missing one themselves; we do
    the same, from the address written inside the certificate. This is safe: the chain must still end at a
    root that Python already trusts, so a fake intermediate would be rejected."""
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(INTERMEDIATE_CERT_URL, timeout=60) as resp:
        ctx.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(resp.read()))
    return ctx


SSL_CONTEXT = None


def get_json(url):
    """GET a URL and parse JSON. Retries with growing waits, because the CBIC server often drops connections."""
    global SSL_CONTEXT
    if SSL_CONTEXT is None:
        SSL_CONTEXT = make_ssl_context()
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120, context=SSL_CONTEXT) as resp:
                return json.loads(resp.read())
        except Exception as e:
            if attempt == RETRIES:
                raise
            wait = 2 ** attempt
            print(f"    retry {attempt}/{RETRIES - 1} in {wait}s ({e})")
            time.sleep(wait)


def list_circulars():
    rows = get_json(f"{API}/cbic-circular-msts/fetchAllCircularsByTaxId/{GST_TAX_ID}")
    return [
        {"doc_type": "circulars", "endpoint": "cbic-circular-msts", "id": r["id"],
         "number": r["circularNo"], "title": r["circularName"], "date": r["circularDt"]}
        for r in rows
        if r["circularCategory"] == "Circulars CGST"  # skip the few IGST / cess circulars (out of v1 scope)
    ]


def list_instructions():
    # The year-wise endpoint the website uses returns errors, but the plain list returns
    # every instruction for every tax in one go, so we keep only GST.
    rows = get_json(f"{API}/cbic-instruction-msts")
    return [
        {"doc_type": "instructions", "endpoint": "cbic-instruction-msts", "id": r["id"],
         "number": r["instructionNo"], "title": r["instructionName"], "date": r["instructionDt"]}
        for r in rows
        if (r.get("tax") or {}).get("id") == GST_TAX_ID
    ]


def list_notifications():
    rows = get_json(f"{API}/cbic-notification-msts/fetchNotificationByCategory/{GST_TAX_ID}/Central%20Tax")
    return [
        {"doc_type": "notifications", "endpoint": "cbic-notification-msts", "id": r["id"],
         "number": r["notificationNo"], "title": r["notificationName"], "date": r["notificationDt"]}
        for r in rows
        if (r.get("notificationDt") or "")[:10] > NOTIFICATIONS_AFTER
    ]


def safe_name(d):
    """'164/20/2021-GST' -> '164-20-2021-GST' (slashes and odd characters are not allowed in file names).
    Some guidelines have no number, so for those we use the start of the title."""
    text = (d["number"] or "").strip() or (d["title"] or "")[:60]
    return re.sub(r"[^A-Za-z0-9.-]+", "-", text).strip("-") or "unnamed"


def plan_paths(docs, out):
    """Give each document a path <out>/<type>/<year>/<number>.pdf. If two share a number
    (e.g. several 'Corrigendum' entries), add the portal id to keep them apart."""
    seen = set()
    for d in sorted(docs, key=lambda d: d["id"]):
        year = (d["date"] or "")[:4] or "unknown-year"
        path = out / d["doc_type"] / year / f"{safe_name(d)}.pdf"
        if path in seen:
            path = path.with_name(f"{path.stem}_{d['id']}.pdf")
        seen.add(path)
        d["path"] = path


def is_complete_pdf(data):
    """A real PDF starts with %PDF and ends with %%EOF. A cut-off download fails the second check."""
    return data[:4] == b"%PDF" and b"%%EOF" in data[-1024:]


def download(d):
    resp = get_json(f"{API}/{d['endpoint']}/download/{d['id']}/ENG")
    b64 = resp.get("data") or resp.get("pdfData")
    if not b64:
        raise ValueError("no file in the response")
    return base64.b64decode(b64)


def progress(i, total, start, width=20):
    """A text progress bar like: [#####---------------]  25%  78/312  ~6 min left.
    The time left is a guess from the average time per file so far."""
    filled = width * i // total
    bar = "#" * filled + "-" * (width - filled)
    per_file = (time.time() - start) / max(i - 1, 1)
    left = per_file * (total - i + 1)
    eta = f"~{round(left / 60)} min left" if left >= 60 else f"~{round(left)} s left"
    if i == 1:
        eta = "estimating..."
    return f"[{bar}] {100 * i // total:3d}%  {i}/{total}  {eta}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="download only the first N of each type (for testing)")
    parser.add_argument("--out", type=Path, default=OUT, help="folder to save into (default: docs/)")
    args = parser.parse_args()
    out = args.out.resolve()

    docs = []
    for name, lister in [("circulars", list_circulars), ("instructions", list_instructions),
                         ("notifications", list_notifications)]:
        found = lister()
        print(f"{name}: {len(found)} listed")
        docs += found[: args.limit] if args.limit else found
    plan_paths(docs, out)

    rows, failed = [], []
    start = time.time()
    for i, d in enumerate(docs, 1):
        path = d["path"]
        label = f"{progress(i, len(docs), start)}  {path.relative_to(out)}"
        if path.exists() and is_complete_pdf(path.read_bytes()):
            data = path.read_bytes()
            print(f"{label}  already have it")
        else:
            try:
                data = download(d)
                if not is_complete_pdf(data):
                    raise ValueError("downloaded file is not a complete PDF")
            except Exception as e:
                print(f"{label}  FAILED: {e}")
                failed.append(d)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            print(f"{label}  saved ({len(data) // 1024} KB)")
            time.sleep(DELAY_SECONDS)

        rows.append({
            "doc_type": d["doc_type"], "number": d["number"], "title": d["title"],
            "date": (d["date"] or "")[:10], "portal_id": d["id"],
            "official_url": f"https://taxinformation.cbic.gov.in/content-page/{PORTAL_PAGE[d['doc_type']]}",
            "download_api": f"{API}/{d['endpoint']}/download/{d['id']}/ENG",
            "file": str(path.relative_to(out)), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })

    for m in MANUAL_DOCS:
        path = out / m["file"]
        if not path.exists():
            print(f"  missing hand-downloaded file: {path} (see MANUAL_DOCS in this script)")
            failed.append({"doc_type": m["doc_type"], "number": m["number"], "id": None})
            continue
        data = path.read_bytes()
        rows.append({**m, "portal_id": None, "download_api": None, "bytes": len(data),
                     "sha256": hashlib.sha256(data).hexdigest(),
                     "fetched_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")})

    with (out / "manifest.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\nDone: {len(rows)} files in the manifest, {len(failed)} failed.")
    for d in failed:
        print(f"  failed: {d['doc_type']} {d['number']} (id {d['id']})")
    if failed:
        print("Run the script again to retry the failed ones.")


if __name__ == "__main__":
    main()
