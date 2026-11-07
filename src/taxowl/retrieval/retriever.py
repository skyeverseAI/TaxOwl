"""Question -> chunks: the law it names first, then the closest in meaning.

    "What does section 16(4) say?"  -> section 16(4)'s chunk (found by its label), then 5 by meaning
    "Can I claim ITC on a car?"     -> no citation, so only the 5 by meaning

Each returned chunk is a copy, labelled in its metadata:
    found_by      "exact" or "meaning"
    citation      "CGST Act section 16(4)" (exact only), what the question named
    law_assumed   True when the question named no law and the CGST Act was taken (exact only)
    distance      how far in meaning, lower is closer (meaning only)

The retriever knows nothing about GST. It is given two functions: one reads citations from a
question, the other finds a citation's chunks. `make_retriever()` gives it taxowl's GST pair. Merging
the two lists is our own code, not LangChain's EnsembleRetriever: that one mixes lists by rank
score, and an exact hit must never be pushed below a merely similar chunk.

Check it by eye: uv run experiments/try_search.py
"""

from typing import Callable

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStore

from taxowl.retrieval.citations import Citation, read_citations
from taxowl.retrieval.lookup import lookup
from taxowl.retrieval.store import get_store

MEANING_CHUNKS = 5   # always added, even after exact hits: the question may ask more than the citation holds
EXACT_CHUNKS = 20    # all citations together; each citation's own limit is in lookup (MAX_CHUNKS)


def describe(citation: Citation) -> str:
    """Citation("section", "17", ("5", "g"), "CGST Act") -> 'CGST Act section 17(5)(g)'."""
    parts = "".join(f"({part})" for part in citation.path)
    return " ".join(p for p in (citation.law, citation.kind, citation.number + parts) if p)


def labelled(document: Document, **labels) -> Document:
    """A copy with labels added. Never change the original: lookup keeps its documents in a cache."""
    return Document(page_content=document.page_content, metadata={**document.metadata, **labels},
                    id=document.id)


def share(found: list[list[Document]], cap: int) -> list[list[Document]]:
    """Cut each citation's chunks so all together fit in `cap`, taking one from each in turn.
    Three citations with 10 chunks each and a cap of 20 -> 7, 7 and 6, each still in reading order;
    a citation with only 2 chunks leaves its unused room to the others."""
    taken = [0] * len(found)
    left = cap
    while left > 0:
        moved = False
        for i, documents in enumerate(found):
            if left and taken[i] < len(documents):
                taken[i] += 1
                left -= 1
                moved = True
        if not moved:
            break
    return [documents[:n] for documents, n in zip(found, taken)]


class LawRetriever(BaseRetriever):
    """Exact chunks for the citations a question names, then MEANING_CHUNKS more by meaning."""

    store: VectorStore
    read: Callable[[str], list[Citation]]                # question -> citations
    find: Callable[[Citation], list[Document]]           # citation -> its chunks, in order
    meaning_chunks: int = MEANING_CHUNKS
    exact_chunks: int = EXACT_CHUNKS

    def exact(self, question: str) -> list[Document]:
        """Chunks for each citation, the room shared out, each chunk listed once."""
        citations = self.read(question)
        kept = share([self.find(citation) for citation in citations], self.exact_chunks)
        seen, results = set(), []
        for citation, documents in zip(citations, kept):
            for document in documents:
                if document.id not in seen:
                    seen.add(document.id)
                    results.append(labelled(document, found_by="exact", citation=describe(citation),
                                            law_assumed=citation.law_assumed))
        return results

    def meaning(self, question: str, skip: set[str]) -> list[Document]:
        """The closest chunks by meaning, leaving out ones the exact list already has."""
        found = self.store.similarity_search_with_score(question, k=self.meaning_chunks + len(skip))
        new = [(document, distance) for document, distance in found if document.id not in skip]
        return [labelled(document, found_by="meaning", distance=round(distance, 3))
                for document, distance in new[:self.meaning_chunks]]

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun
                                ) -> list[Document]:
        exact = self.exact(query)
        return exact + self.meaning(query, {document.id for document in exact})


def make_retriever() -> LawRetriever:
    """taxowl's retriever: the GST citation reader and lookup, over the Chroma store."""
    return LawRetriever(store=get_store(), read=read_citations, find=lookup)
