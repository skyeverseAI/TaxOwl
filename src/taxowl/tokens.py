"""Counting tokens the way the embedder does. Shared by the splitter, the chunker and the embedder.

It lives on its own so the chunker needs nothing from the splitter (a step towards making the
chunker a reusable package in v2). Nothing here imports another taxowl module.
"""

from functools import lru_cache

from tokenizers import Tokenizer

EMBEDDER = "BAAI/bge-small-en-v1.5"  # the tokenizer must be the embedder's own, or the counts are wrong


@lru_cache(maxsize=1)
def tokenizer() -> Tokenizer:
    """Loaded once (from the Hugging Face cache; downloaded the first time on a new machine)."""
    return Tokenizer.from_pretrained(EMBEDDER)


def count_tokens(text: str) -> int:
    """Tokens as bge-small counts them, without its [CLS]/[SEP] markers. bge reads at most 512."""
    return len(tokenizer().encode(text, add_special_tokens=False).ids)
