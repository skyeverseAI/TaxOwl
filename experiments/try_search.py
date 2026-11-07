"""Quick check by eye: ask the retriever a few questions and print every chunk it returns.

Not the eval: these questions were drafted with ChatGPT, so they never join the test split.
Each line shows how the chunk was found: "exact" (the question named it) or "meaning" (with its
distance, lower is closer).

Usage:
    uv run experiments/try_search.py
"""

from taxowl.retrieval.retriever import make_retriever

# (question, the source we expect; "none" means the answer isn't in our documents)
QUESTIONS = [
    ("What does section 16(4) of the CGST Act say about the time limit for claiming input tax credit?",
     "CGST Act, section 16(4)"),
    ("What does rule 36(4) of the CGST Rules require before a buyer can claim input tax credit on supplier invoices?",
     "CGST Rules, rule 36(4)"),
    ("I bought a machine for my business. Can I claim GST paid on it if I use it partly for personal purposes?",
     "CGST Act, section 17(1)"),
    ("I charged GST by mistake as an unregistered seller; what should I do with the tax I collected?",
     "CGST Act, section 76 (also section 32(1))"),
    ("I issued an invoice before delivering the goods, but the order was later cancelled; how do I adjust the GST?",
     "CGST Act, section 34, or Circular 137/07/2020-GST, table row 1"),
    ("A customer's goods were sent to the wrong state and tax was paid under the wrong type of GST; how can the customer get the tax back?",
     "Circular 162/18/2021-GST"),
    ("If an advertising agency buys hoarding space across several states for a government campaign, how is the service value split among the states?",
     "IGST Rules, rule 3"),
    ("What tax rates apply to eligible composition-scheme businesses under rule 7, and which business categories do the rates cover?",
     "CGST Rules, rule 7, table"),
    ("What is the income-tax deduction available for charitable donations to an approved institution?",
     "none (Income-tax Act)"),
    ("Is a GST demand legally valid after the High Court's ruling in the taxpayer's case?",
     "none (court judgments)"),
]


def show(document) -> str:
    """One line per chunk: how it was found, then where it comes from."""
    m = document.metadata
    if m["found_by"] == "exact":
        how = f"exact    [{m['citation']}{', law assumed' if m['law_assumed'] else ''}]"
    else:
        how = f"meaning  {m['distance']:.3f}"
    return f"{how}  {m['doc_number']}, {m['location']}, p.{m['page_start']}-{m['page_end']} ({m['kind']})"


def main() -> None:
    retriever = make_retriever()
    for number, (question, expected) in enumerate(QUESTIONS, 1):
        print(f"\n{number}. {question}\n   expected: {expected}")
        for document in retriever.invoke(question):
            print(f"   {show(document)}")


if __name__ == "__main__":
    main()
