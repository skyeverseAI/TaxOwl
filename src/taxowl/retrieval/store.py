"""The store: each chunk's vector, text and labels, saved in Chroma under data/chroma/.

Rebuilt whole from data/chunks.jsonl, not updated piece by piece: simpler, and no old chunk can stay
behind. Deleting the old store is a manual step for now, so build() stops if it finds one.
"""

from langchain_chroma import Chroma
from langchain_core.documents import Document

from taxowl.config import CHROMA
from taxowl.retrieval.embedder import get_embedder
from taxowl.schema import Chunk

COLLECTION = "corpus-bge-small"  # model in the name: two models' vectors can't be compared
BATCH = 512                      # chunks embedded and saved at one time


def get_store() -> Chroma:
    """The store, created empty if it isn't there. Cosine: the same score as embedder.similarity."""
    return Chroma(collection_name=COLLECTION, embedding_function=get_embedder(),
                  persist_directory=str(CHROMA), collection_metadata={"hnsw:space": "cosine"})


def count(store: Chroma) -> int:
    """How many chunks it holds. LangChain's wrapper has no public count, so we ask Chroma directly."""
    return store._collection.count()


def build(chunks: list[Chunk]) -> int:
    """Embed the chunks and save them in an empty store. Returns how many the store now holds."""
    store = get_store()
    if count(store):
        raise RuntimeError(f"{CHROMA} already holds {count(store)} chunks. Delete that folder first.")
    for start in range(0, len(chunks), BATCH):
        batch = chunks[start:start + BATCH]
        docs = [Document(page_content=c.text, metadata=c.metadata()) for c in batch]
        store.add_documents(docs, ids=[c.chunk_id for c in batch])
        print(f"{start + len(batch)} of {len(chunks)} chunks saved")
    return count(store)
