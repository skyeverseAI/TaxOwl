"""Tests for wants_web() in src/taxowl/answer/web.py: which questions also search the web for today's rate.
A miss gives an old rate from a 2017 document; a false hit spends a paid search on a law question."""

import pytest

from taxowl.answer.web import wants_web


@pytest.mark.parametrize("question", [
    "GST rate on tobacco",
    "CGST kitna lagega on cement?",
    "How much GST on a used car?",
])
def test_rate_question_goes_to_web(question):
    assert wants_web(question)

# A law question must not spend a paid web search.
def test_law_question_does_not_go_to_web():
    assert not wants_web("What does section 16 say?")

