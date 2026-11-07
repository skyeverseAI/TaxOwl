"""Checks on an answer, by plain rules (no second model call).

    check(answer_text, sources, question) -> [{"name": ..., "passed": True/False, "why": ...}, ...]

  made_up_source   every [S#] in the answer is in the source list
  cites_or_refuses an answer with no [S#] must be the refusal sentence
  no_new_citation  every section, rule or circular the answer names is in a cited source:
                   the "never invent a legal citation" rule, checked with the same reader and
                   lookup the retriever uses. A citation the question itself names is skipped:
                   repeating the user's words isn't inventing one (hard-03, 2026-11-07)
  mixed_refusal    the refusal sentence never comes after an answer
  says_assumed     if a law was assumed, the answer says which; if none was, it doesn't claim one

A failed check doesn't hide the answer (v1): it's shown as a warning and counted at eval time.
Kept out of pipeline.py so the eval runner can reuse it as it is.
"""

import re

from taxowl.answer.generator import REFUSAL
from taxowl.retrieval.citations import read_citations
from taxowl.retrieval.lookup import lookup
from taxowl.retrieval.retriever import describe

MARKER = re.compile(r"\[S(\d+)\]")


def result(name: str, passed: bool, why: str = "") -> dict:
    return {"name": name, "passed": passed, "why": why}


def cited_numbers(text: str) -> set[int]:
    """'... [S1][S3] ...' -> {1, 3}"""
    return {int(n) for n in MARKER.findall(text)}


def supported(citation, cited_sources: list[dict]) -> bool:
    """True if a cited source holds this citation (lookup leads to it), or mentions it in its text:
    a circular that says "section 79" may be cited for section 79 without being section 79 itself."""
    if {d.id for d in lookup(citation, limit=None)} & {s["chunk_id"] for s in cited_sources}:
        return True
    if citation.kind == "circular":
        mention = re.compile(re.escape(citation.number))
    else:
        mention = re.compile(rf"\b{citation.kind}s?\s+{re.escape(citation.number)}\b", re.IGNORECASE)
    return any(mention.search(s["text"]) for s in cited_sources)


def check(text: str, sources: list[dict], question: str = "") -> list[dict]:
    """`sources` is pipeline.py's list: {"number", "label", "url", "chunk_id", "law_assumed", "text"}.
    `law_assumed` is the assumed law's name ("CGST Rules") or ""."""
    numbers = {s["number"] for s in sources}
    cited = cited_numbers(text)
    refused = text.strip().strip("*_\"' ") == REFUSAL  # Markdown may bold or quote it
    checks = []

    unknown = sorted(cited - numbers)
    checks.append(result("made_up_source", not unknown,
                         f"no such source: {', '.join(f'S{n}' for n in unknown)}" if unknown else ""))

    checks.append(result("cites_or_refuses", bool(cited) or refused,
                         "" if cited or refused else "no [S#] marker and not the refusal sentence"))

    cited_sources = [s for s in sources if s["number"] in cited]
    asked = {(c.kind, c.number) for c in read_citations(question)}
    missing = [c for c in read_citations(text)
               if (c.kind, c.number) not in asked and not supported(c, cited_sources)]
    checks.append(result("no_new_citation", not missing,
                         "not in a cited source: " + "; ".join(describe(c) for c in missing) if missing else ""))

    # The refusal sentence must stand alone: an answer followed by it is a guess (seen 2026-11-07)
    mixed = REFUSAL in text and not refused
    checks.append(result("mixed_refusal", not mixed, "an answer and the refusal sentence together" if mixed else ""))

    laws = [law for law in dict.fromkeys(s["law_assumed"] for s in sources) if law]
    if laws and not refused:
        said = all(law in text for law in laws) and "assum" in text.lower()
        checks.append(result("says_assumed", said,
                             "" if said else f"{' and '.join(laws)} assumed but not said"))
    elif not laws:
        claimed = "assumed you mean" in text.lower()
        checks.append(result("says_assumed", not claimed,
                             "says a law was assumed, but none was" if claimed else ""))
    return checks
