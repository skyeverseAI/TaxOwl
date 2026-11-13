"""Question -> chunks: the law it names first, then the closest in meaning.

    "What does section 16(4) say?"  -> section 16(4)'s chunk (found by its label), then 5 by meaning
    "Can I claim ITC on a car?"     -> no citation, so only the 5 by meaning

Each returned chunk is a copy, labelled in its metadata:
    found_by      "exact" or "meaning"
    citation      "CGST Act section 16(4)" (exact only), what the question named
    law_assumed   True when the question named no law and the CGST Act was taken (exact only)
    distance      how far in meaning, lower is closer (meaning only)

A named citation's chunks are ordered by closeness to the question, not by page: "Circular 231/25/2024"
has 15 chunks, and the para that answers (4.4) came 8th in page order (Baseline 1, 2026-11-08). All of a
citation's chunks are compared first, then the closest PER_CITATION are kept, so the answer can't be cut
off by a page-order limit.

The retriever knows nothing about GST. It is given two functions: one reads citations from a
question, the other finds a citation's chunks. `make_retriever()` gives it taxowl's GST pair. Merging
the two lists is our own code, not LangChain's EnsembleRetriever: that one mixes lists by rank
score, and an exact hit must never be pushed below a merely similar chunk.

Withdrawn circulars are left out of the meaning search (`meaning_filter`): an old rule must not answer a
question it no longer governs. A circular the question NAMES is still returned, withdrawn or not: "what
does 37/11/2018 say?" is answered with "withdrawn by 125/44/2019", not with a refusal. Partly modified
circulars stay everywhere; their label says what changed them (answer/pipeline.py).

Cited provisions (`cited_from`): a circular explains a rule as it stood on the circular's date. Circular
123/42/2019 explains rule 36(4)'s 2019 limit; the rule was changed in 2022. The rule's current text is
in the store, but meaning search can't find it: "ITC limit" and "No input tax credit shall be availed...
unless" are far apart (not in the top 300 for trap dev-018, 2026-11-13). The circulars name it, though:
every returned circular chunk is read with the same citation reader, the CITED_PROVISIONS cited by the
most chunks are looked up, and their closest CITED_CHUNKS are added last, labelled found_by "cited".
The model then sees the old explanation AND the law as it stands now.

Check it by eye: uv run experiments/try_search.py
"""

from dataclasses import replace
from typing import Callable

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStore

from taxowl.retrieval.citations import Citation, read_citations
from taxowl.retrieval.embedder import similarity
from taxowl.retrieval.lookup import lookup
from taxowl.retrieval.store import get_store

MEANING_CHUNKS = 8   # always added, even after exact hits: the question may ask more than the citation holds
EXACT_CHUNKS = 20    # all citations together
PER_CITATION = 10    # one citation's closest chunks (was lookup's MAX_CHUNKS, taken in page order)
CITED_PROVISIONS = 3  # sections/rules the returned circulars cite most, followed to their current text
CITED_CHUNKS = 4      # all followed provisions together

_VECTORS: dict[str, list[float]] = {}  # chunk id -> its vector, so a chunk is embedded once per run


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
    Three citations with 10 chunks each and a cap of 20 -> 7, 7 and 6, each keeping its closest ones;
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
    find: Callable[[Citation], list[Document]]           # citation -> all its chunks (the retriever orders them)
    meaning_chunks: int = MEANING_CHUNKS
    exact_chunks: int = EXACT_CHUNKS
    per_citation: int = PER_CITATION
    meaning_filter: dict | None = None                   # a Chroma `where` for the meaning search only
    cited_from: tuple[str, ...] = ()                     # doc types whose citations are followed; () = off
    cited_provisions: int = CITED_PROVISIONS
    cited_chunks: int = CITED_CHUNKS

    def closest(self, question: str, documents: list[Document]) -> list[Document]:
        """A citation's chunks, closest to the question first. The vectors are made with the store's
        own embedder, so the order matches what meaning search would give."""
        if len(documents) < 2:
            return documents
        embedder = self.store.embeddings
        new = [d for d in documents if d.id not in _VECTORS]
        if new:
            for document, vector in zip(new, embedder.embed_documents([d.page_content for d in new])):
                _VECTORS[document.id] = vector
        query = embedder.embed_query(question)
        return sorted(documents, key=lambda d: similarity(query, _VECTORS[d.id]), reverse=True)

    def exact(self, question: str) -> list[Document]:
        """Chunks for each citation, the room shared out, each chunk listed once."""
        citations = self.read(question)
        found = [self.closest(question, self.find(citation))[:self.per_citation] for citation in citations]
        kept = share(found, self.exact_chunks)
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
        found = self.store.similarity_search_with_score(question, k=self.meaning_chunks + len(skip),
                                                        filter=self.meaning_filter)
        new = [(document, distance) for document, distance in found if document.id not in skip]
        return [labelled(document, found_by="meaning", distance=round(distance, 3))
                for document, distance in new[:self.meaning_chunks]]

    def cited(self, question: str, documents: list[Document]) -> list[Document]:
        """The current text of the sections/rules the returned circulars cite most.
        Counted once per chunk; ties go to the one cited first (higher up the list)."""
        counts: dict[Citation, int] = {}
        cited_by: dict[Citation, list[str]] = {}
        for document in documents:
            if document.metadata.get("doc_type") not in self.cited_from:
                continue
            for citation in self.read(document.page_content):
                if citation.kind == "circular":
                    continue
                # "rule 36(4)" and "rule 36(4) of the CGST Rules" are the same provision
                citation = replace(citation, law_assumed=False)
                counts[citation] = counts.get(citation, 0) + 1
                cited_by.setdefault(citation, []).append(document.metadata["doc_number"])
        top = sorted(counts, key=lambda c: -counts[c])[:self.cited_provisions]   # stable: ties keep first-seen
        have = {document.id for document in documents}
        found = [[d for d in self.closest(question, self.find(c)) if d.id not in have] for c in top]
        results, seen = [], set()
        for citation, kept in zip(top, share(found, self.cited_chunks)):
            for document in kept:
                if document.id not in seen:
                    seen.add(document.id)
                    results.append(labelled(document, found_by="cited", citation=describe(citation),
                                            law_assumed=False,
                                            cited_by=", ".join(dict.fromkeys(cited_by[citation]))))
        return results

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun
                                ) -> list[Document]:
        exact = self.exact(query)
        found = exact + self.meaning(query, {document.id for document in exact})
        return found + (self.cited(query, found) if self.cited_from else [])


NOT_WITHDRAWN = {"status": {"$ne": "withdrawn"}}   # labels from validity/status.py


def make_retriever() -> LawRetriever:
    """taxowl's retriever: the GST citation reader and lookup, over the Chroma store. Lookup gives all
    of a citation's chunks (no limit); the retriever orders them and keeps PER_CITATION."""
    return LawRetriever(store=get_store(), read=read_citations,
                        find=lambda citation: lookup(citation, limit=None), meaning_filter=NOT_WITHDRAWN,
                        cited_from=("circular", "instruction"))   # the Act and Rules ARE the current text
