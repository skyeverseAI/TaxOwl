"""The store: each chunk's vector, text and labels, saved in Chroma under data/chroma/.

Rebuilt whole from data/chunks.jsonl, not updated piece by piece: simpler, and no old chunk can stay
behind. Deleting the old store is a manual step for now, so build() stops if it finds one.

On the server the store isn't in git (it holds the sources' text), so ensure_store() downloads it once
from a PRIVATE Hugging Face dataset, named by TAXOWL_STORE_REPO, with the HF_TOKEN secret. On the Mac
data/chroma is already there and nothing happens.
"""

import os

from langchain_chroma import Chroma
from langchain_core.documents import Document

from taxowl.config import CHROMA
from taxowl.retrieval.embedder import MODEL, get_embedder
from taxowl.schema import Chunk

COLLECTION = f"corpus-{MODEL}"   # model in the name: two models' vectors can't be compared
BATCH = 512                      # chunks embedded and saved at one time
# HNSW is Chroma's approximate search index; ef_search = how many candidates it keeps while searching.
# At Chroma's 100, 2 of 40 dev questions changed between runs and 3 missed a chunk exact search found.
# At 500, all 40 matched exact search in 6 of 6 runs (2026-11-08, Evaluations/Retriever_Evals/).
EF_SEARCH = 500


def ensure_store() -> None:
    """Download data/chroma from the private dataset if it isn't here yet. huggingface_hub directly, not
    LangChain: this is a file download, which LangChain has nothing for."""
    if (CHROMA / "chroma.sqlite3").exists():
        return
    repo = os.environ.get("TAXOWL_STORE_REPO")
    if not repo:
        raise RuntimeError(f"No store in {CHROMA}. Build it (uv run python scripts/04_embed_store.py) or set "
                           "TAXOWL_STORE_REPO (+ HF_TOKEN) to download it.")
    from huggingface_hub import snapshot_download  # only the server needs it
    snapshot_download(repo, repo_type="dataset", local_dir=CHROMA, token=os.environ.get("HF_TOKEN"))


def get_store() -> Chroma:
    """The store, created empty if it isn't there. Cosine: the same score as embedder.similarity.
    collection_configuration applies when the collection is created; the existing store was set to
    ef_search 500 once with collection.modify()."""
    return Chroma(collection_name=COLLECTION, embedding_function=get_embedder(),
                  persist_directory=str(CHROMA), collection_metadata={"hnsw:space": "cosine"},
                  collection_configuration={"hnsw": {"ef_search": EF_SEARCH}})


def count(store: Chroma) -> int:
    """How many chunks it holds. LangChain's wrapper has no public count, so we ask Chroma directly."""
    return store._collection.count()


def build(chunks: list[Chunk]) -> int:
    """Embed the chunks and save them in an empty store. Returns how many the store now holds."""
    store = get_store()
    if count(store):
        raise RuntimeError(f"{COLLECTION} in {CHROMA} already holds {count(store)} chunks. "
                           "Delete that folder first (it holds every model's collection).")
    for start in range(0, len(chunks), BATCH):
        batch = chunks[start:start + BATCH]
        docs = [Document(page_content=c.text, metadata=c.metadata()) for c in batch]
        store.add_documents(docs, ids=[c.chunk_id for c in batch])
        print(f"{start + len(batch)} of {len(chunks)} chunks saved")
    return count(store)
