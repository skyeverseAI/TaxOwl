"""Web search, for one gap the documents can't fill: TODAY's GST rate.

Rates live in rate notifications, which the corpus doesn't hold, and they change (GST 2.0, 22 Sep 2025;
tobacco, 1 Feb 2026). A circular from 2021 says "12%"; the rate today may be 5%. So a rate question also
gets the top web results, as extra sources labelled WEB, after the PDF sources:

    question ── has a rate word? ── no ──> PDF sources only (every other question: unchanged, repeatable)
                     │ yes
                     ▼
    the model writes a short English search query   (a Hinglish question finds nothing as it is)
                     ▼
    Tavily search (advanced), pages from the past year only, top 4
                     ▼
    [S9] WEB: taxguru.in, searched 2026-11-13, past year only (a web page, not an official document)
         <title>
         <the page's text that matched: what the answer may quote>

If the search fails or finds nothing, the answer gets RATE_NOTE from our code (not the model): the
documents' rate may be out of date.

Why no site list: official pages and big tax sites rank their 2018-2021 pages first; a time limit works
better than trusting a site.
Why Tavily (langchain-tavily, LangChain's maintained integration): free DuckDuckGo search (ddgs) was tried
first and on 2026-11-13 found nothing on 1 search in 3, then nothing at all after ~15 searches (rate
limited). Tavily is made for LLM apps: it returns the page's matching text, not a one-line snippet, and
takes time_range. Free tier: 1000 searches a month. Key: TAVILY_API_KEY in .env or the environment.

    uv run python -m taxowl.answer.web "Mere khet ki drip-wali sinchai line par CGST kitna lagega?"
"""

import re
import sys
from datetime import date
from urllib.parse import urlparse

from taxowl.answer.generator import get_llm
from taxowl.ingestion.vlm import load_key

# rate, rates, %, percent, HSN, "how much GST", "CGST kitna", "kitni GST" ...
RATE = re.compile(r"\brates?\b|%|\bpercent\b|\bhsn\b|\bslab\b"
                  r"|how much (gst|tax|cgst|sgst|igst)|\bkitn[aie]\b.{0,20}\b(gst|tax|cgst|sgst|igst)\b"
                  r"|\b(gst|tax|cgst|sgst|igst)\b.{0,20}\bkitn[aie]\b", re.I)
KEEP = 4             # results kept (the user's choice: the top 3-4)
TIME_RANGE = "year"  # older pages give pre-2025 rates
# "basic" gave a medical blog and a YouTube video for tobacco; "advanced" gave busy.in, taxguru and the rate
# table (2026-11-13). It costs 2 credits a search: ~500 searches a month on the free tier.
DEPTH = "advanced"
# posts and videos, not pages that state a rate with its source (facebook and instagram came up for drip irrigation)
SOCIAL = ["facebook.com", "instagram.com", "youtube.com", "x.com", "twitter.com", "linkedin.com"]
LONGEST = 800        # characters of a page's text given to the model

QUERY_PROMPT = ("Write a short English web search query (at most 12 words) to find the current Indian GST rate "
                "that this question asks about. Reply with the query only.\n\nQuestion: {question}")
RATE_NOTE = ("Note: the rate above is from the documents' own dates. GST rates were revised from "
             "22 September 2025 and later; check the latest rate notification before relying on it.")


def wants_web(question: str) -> bool:
    return bool(RATE.search(question))


def search_query(question: str) -> str:
    """The question as a short English query. Always the cloud model: a few paise, and the local
    model may not be running."""
    reply = get_llm("cloud").invoke(QUERY_PROMPT.format(question=question))
    return reply.content.strip().strip('"')


def search(query: str) -> list[dict]:
    """Top KEEP results from the past year: {url, site, title, text}. [] if there is no key or the search fails."""
    from langchain_tavily import TavilySearch

    key = load_key("TAVILY_API_KEY")
    if not key:
        print("web search skipped: no TAVILY_API_KEY", file=sys.stderr)
        return []
    try:
        found = TavilySearch(max_results=KEEP, time_range=TIME_RANGE, search_depth=DEPTH,
                             exclude_domains=SOCIAL, tavily_api_key=key).invoke({"query": query})
    except Exception as e:  # network, quota: answer from the PDFs alone, with RATE_NOTE
        print(f"web search failed: {e}", file=sys.stderr)
        return []
    if not isinstance(found, dict):  # the tool returns an error message as text
        print(f"web search failed: {found}", file=sys.stderr)
        return []
    return [{"url": r["url"], "site": urlparse(r["url"]).netloc.removeprefix("www."),
             "title": r.get("title", ""), "text": " ".join(r.get("content", "").split())[:LONGEST]}
            for r in found.get("results", [])]


def web_sources(question: str, first_number: int) -> list[dict]:
    """Web results as sources, numbered on from the PDF sources (same [S#] markers, so the checks
    and the app treat them alike; the WEB label is what sets them apart)."""
    if not wants_web(question):
        return []
    results = search(search_query(question))
    today = date.today().isoformat()
    return [{"number": n, "url": r["url"], "chunk_id": "", "law_assumed": "", "doc_number": "", "location": "",
             "web": True,
             "label": f"WEB: {r['site']}, searched {today}, past {TIME_RANGE} only (a web page, not an official document)",
             "text": f"{r['title']}\n{r['text']}"}
            for n, r in enumerate(results, first_number)]


def rate_note(question: str, sources: list[dict]) -> str:
    """RATE_NOTE for a rate question that got no web source; "" otherwise. Added by code, not left to the model."""
    return RATE_NOTE if wants_web(question) and not any(s.get("web") for s in sources) else ""


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "Mere khet ki drip-wali sinchai line ke side-pipes par CGST kitna lagega?"
    print("rate question:", wants_web(q))
    if wants_web(q):
        print("query:", search_query(q))
        for s in web_sources(q, 1):
            print(f"\n[S{s['number']}] {s['label']}\n{s['url']}\n{s['text']}")
