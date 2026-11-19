"""Tests for src/taxowl/answer/check.py: the parts that need no store and no key."""

from taxowl.answer.check import cited_numbers, is_refusal
from taxowl.answer.generator import REFUSAL


def test_cited_numbers_reads_markers():
    assert cited_numbers("ITC is allowed [S1][S3].") == {1, 3}


def test_bare_S1_is_not_a_citation():
    # only the [S#] form counts; "S1" in plain text is not a citation
    assert cited_numbers("see S1 and S2") == set()


def test_refusal_in_bold_still_counts():
    # the model sometimes wraps the sentence in markdown
    assert is_refusal(f"**{REFUSAL}**")


def test_answer_plus_refusal_is_not_a_refusal():
    # an answer followed by the refusal sentence is a guess, not a refusal
    assert not is_refusal(f"ITC is allowed [S1]. {REFUSAL}")
