"""The whole answer step: question -> retrieve -> label -> generate -> check.

Same shape as evals_project/src/rag_pipeline.py, with one step more (check):

    from taxowl.answer.pipeline import answer
    result = answer("What does section 16(4) say?", which="cloud")
    result["answer"], result["sources"], result["checks"], result["seconds"], result["cost_inr"]

Differs from evals_project (why, in short):
  - step 2 gives every chunk a label, "[S1] CGST Act ..., section 16(4), p.23": in a legal answer
    the citation is the product, and the model can only cite what it can see. Our code writes the
    label from the chunk's metadata, never the model, so every [S1] leads to a real chunk and its link
  - a token budget for the local model, which reads far less than a cloud model
  - time with perf_counter, not LangSmith's @traceable (LangSmith isn't set up here; decide at eval time)

Try it on the 10 test questions: uv run experiments/try_answer.py
"""

import time
from functools import lru_cache

from langchain_core.documents import Document

from taxowl.answer.check import check, cited_numbers
from taxowl.answer.generator import generate
from taxowl.answer.web import rate_note, web_sources
from taxowl.retrieval.retriever import make_retriever

# Sources are added in the retriever's order (exact first) until this many bge tokens. None = all.
# 25 chunks x 400 tokens is ~10k at most: fine for the cloud model, too much for the local 7B one.
BUDGET = {"cloud": None, "local": 6000}


@lru_cache(maxsize=1)
def get_retriever():
    """Load the store once, not once per question."""
    return make_retriever()


def label(doc: Document) -> str:
    """'The Central Goods and Services Tax Act, 2017, section 16(4), p.23 (law assumed)'
       'Circular 238/32/2024-GST, dated 2024-10-15, para 4, p.2-3'
    'Circular 37/11/2018-GST, para 2, p.1 (WITHDRAWN by Circular 125/44/2019 - GST)'
    A flagged circular (its file had splitter warnings) shows only the page: its para numbers may be
    off (decided 2026-11-04). OCR isn't shown: the flag is per document, so every Act and Rules chunk
    has it, which would say nothing."""
    m = doc.metadata
    if m["doc_type"] in ("act", "rules"):
        name = m["title"]  # "Act 12 of 2017" is the number; the title says which Act
    elif m["doc_number"] == m["title"]:  # a document with no number of its own
        name = f"{m['doc_type'].capitalize()}: {m['title'][:80]}"
    elif m["doc_number"].lower().startswith(m["doc_type"]):  # "Instruction No. 01/2022-GST"
        name = m["doc_number"]
    else:
        name = f"{m['doc_type'].capitalize()} {m['doc_number']}"

    where = m["location"]
    if where.startswith("para") and not m["quality_ok"]:
        where = ""
    pages = f"p.{m['page_start']}" + (f"-{m['page_end']}" if m["page_end"] != m["page_start"] else "")
    dated = f"dated {m['doc_date']}" if m.get("doc_date") else ""   # so an old rate can be seen as old
    text = ", ".join(part for part in (name, dated, where, pages) if part)
    text += " (law assumed)" if m.get("law_assumed") else ""
    # validity/status.py: the model must see it to say it, and the reader to trust the citation
    if m.get("status") == "withdrawn":
        text += f" (WITHDRAWN by Circular {m['changed_by']})"
    elif m.get("status") == "partly_modified":
        text += f" (partly modified by Circular {m['changed_by']})"
    # retrieval/retriever.py cited(): a provision a circular explains, as the law reads now
    if m.get("found_by") == "cited":
        text += f" (CURRENT TEXT of the provision explained by Circular {m['cited_by']})"
        text += amended_after(m)
    return text


def amended_after(m: dict) -> str:
    """' (AMENDED on 2022-01-01, AFTER Circular 123/42/2019-GST dated 2019-11-11 ...)', or "".
    Our code compares the dates (validity/amended.py), not the model: given both texts, the model
    answered from the old circular and never said the rule had changed (trap dev-018, 2026-11-13)."""
    since = m.get("cited_since", "")
    # Only dates found in this chunk's own words: the CGST Act's dates are per section, and "section 17(5)
    # amended 2025" next to a circular on rule 36(4) was noise (trap dev-018, 2026-11-14)
    if m.get("amended_scope") != "text":
        return ""
    later = [d for d in m.get("amended_on", "").split(", ") if d and since and d > since]
    if not later:
        return ""
    return (f" (AMENDED on {', '.join(later)}, AFTER Circular {m['cited_oldest']} dated {since}:"
            f" what that circular says may be out of date)")


def amended_note(text: str, sources: list[dict]) -> str:
    """'⚠ Note: CGST Rules rule 36(4) was amended after Circular 123/42/2019-GST (dated 2019-11-11), which
    this answer uses: on 2022-01-01, ... Check its current text [S11].', one line per provision, or "".

    Added by our code, like rate_note: given the AMENDED label and a prompt rule that said "you must",
    the model still answered from the old circular and said nothing (traps dev-006, dev-018, 2026-11-13).
    Three filters keep it from warning about changes that don't matter (2026-11-14):
      1. only dates found in the provision's own words (amended_scope "text"), not a whole Act section
      2. only circulars the ANSWER cites, and only dates after that circular's date: a 2023 circular
         already explains the 2022 rule, so the 2022 change is not news to it
      3. never a withdrawn circular: its label already says it is not the law
    A whole rule in one chunk (rule 21) still gets every date, even if the clause the circular explains
    didn't change; so the note says "may be out of date", not "is wrong".
    One line per provision: a provision split over two chunks (rule 45 in [S11] and [S12]) gave two
    identical lines (pipeline eval claude-015, 2026-11-18); now one line names both [S11][S12]."""
    used = cited_numbers(text)
    circulars = [s for s in sources if s["number"] in used and s.get("doc_type") in ("circular", "instruction")
                 and s.get("status") != "withdrawn" and s.get("doc_date")]
    notes: dict[tuple, list[int]] = {}   # (provision, circular, its date, later dates) -> source numbers
    for p in sources:
        if p.get("amended_scope") != "text" or not p.get("cited_by"):
            continue
        explains = [c for c in circulars if c["doc_number"] in p["cited_by"].split(", ")]
        if not explains:
            continue
        oldest = min(explains, key=lambda c: c["doc_date"])
        later = [d for d in p["amended_on"].split(", ") if d > oldest["doc_date"]]
        if later:
            key = (p["provision"], oldest["doc_number"], oldest["doc_date"], ", ".join(later))
            notes.setdefault(key, []).append(p["number"])
    return "\n\n".join(
        f"⚠ Note: {provision} was amended after Circular {circular} (dated {dated}), which this answer "
        f"uses: on {on}. What the circular says may be out of date; check its current text "
        + "".join(f"[S{n}]" for n in numbers) + "."
        for (provision, circular, dated, on), numbers in notes.items())


def pick(docs: list[Document], budget: int | None) -> list[Document]:
    """The chunks that fit the budget, in order. The first one is always kept."""
    if budget is None:
        return docs
    kept, used = [], 0
    for doc in docs:
        tokens = doc.metadata.get("token_count", 0)
        if kept and used + tokens > budget:
            break
        kept.append(doc)
        used += tokens
    return kept


def assumed_law(doc: Document) -> str:
    """The law the retriever took because the question named none, or "". It only ever assumes
    the CGST Act (for a section) or the CGST Rules (for a rule)."""
    if not doc.metadata.get("law_assumed"):
        return ""
    return "CGST Rules" if doc.metadata["doc_type"] == "rules" else "CGST Act"


def assumed(sources: list[dict]) -> str:
    """"CGST Act", "CGST Rules", "CGST Act and CGST Rules", or "" (nothing assumed)."""
    laws = list(dict.fromkeys(s["law_assumed"] for s in sources if s["law_assumed"]))
    return " and ".join(laws)


def get_sources(question: str, budget: int | None = None) -> list[dict]:
    """Steps 1 and 2. Kept apart from answer() so the UI retrieves once and gives both models
    the same sources (a fair comparison)."""
    # 1. RETRIEVE: exact chunks for named citations, then 5 by meaning
    docs = pick(get_retriever().invoke(question), budget)

    # 2. LABEL, then 2b. WEB: a rate question also gets the top web results (answer/web.py), numbered on
    sources = to_sources(docs)
    return sources + web_sources(question, len(sources) + 1)


def to_sources(docs: list[Document]) -> list[dict]:
    """Step 2, LABEL: number each chunk and put its label above its text. Its own function so the
    generator eval can label the GOLD chunks exactly as the app labels retrieved ones."""
    return [{"number": n, "label": label(doc), "url": doc.metadata["official_url"],
             "chunk_id": doc.id, "law_assumed": assumed_law(doc),
             "doc_number": doc.metadata["doc_number"], "location": doc.metadata["location"],  # for evals
             # for amended_note(): which circulars, and which provisions changed after them
             "doc_type": doc.metadata["doc_type"], "doc_date": doc.metadata.get("doc_date", ""),
             "status": doc.metadata.get("status", ""), "provision": doc.metadata.get("citation", ""),
             "cited_by": doc.metadata.get("cited_by", ""), "amended_on": doc.metadata.get("amended_on", ""),
             "amended_scope": doc.metadata.get("amended_scope", ""),
             "text": doc.page_content}
               for n, doc in enumerate(docs, 1)]


def has_web(sources: list[dict]) -> bool:
    return any(s.get("web") for s in sources)


def as_text(sources: list[dict]) -> str:
    """What the model reads: '[S1] <label>' then the chunk's text, for every source."""
    return "\n\n".join(f"[S{s['number']}] {s['label']}\n{s['text']}" for s in sources)


def answer(question: str, which: str = "cloud") -> dict:
    start = time.perf_counter()

    # 1-2. RETRIEVE and LABEL
    sources = get_sources(question, BUDGET[which])

    # 3. GENERATE: the answer, from these sources only
    reply = generate(question, as_text(sources), which, assumed(sources), has_web(sources))
    model_text = reply["text"]   # before our notes: the pipeline eval tells a refusal by this text
    note = rate_note(question, sources)   # a rate question the web couldn't help with: say the rate may be old
    if note:
        reply["text"] += f"\n\n{note}"
    note = amended_note(reply["text"], sources)   # a cited circular explains a rule changed since
    if note:
        reply["text"] += f"\n\n{note}"

    # 4. CHECK: no made-up source, no citation that isn't in a cited source
    checks = check(reply["text"], sources, question)

    return {
        "question": question,
        "model": which,
        "answer": reply["text"],
        "model_text": model_text,
        "sources": sources,
        "checks": checks,
        "seconds": round(time.perf_counter() - start, 1),
        "input_tokens": reply["input_tokens"],
        "output_tokens": reply["output_tokens"],
        "cost_inr": reply["cost_inr"],
    }


if __name__ == "__main__":
    result = answer("What does section 16(4) say about the time limit for claiming ITC?")
    print(result["answer"], "\n")
    for s in result["sources"]:
        print(f"[S{s['number']}] {s['label']}")
    print("\nchecks:", [(c["name"], c["passed"]) for c in result["checks"]])
    print(f"{result['seconds']} s, ₹{result['cost_inr']}")
