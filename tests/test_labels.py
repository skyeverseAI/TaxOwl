"""Tests for label() in src/taxowl/answer/pipeline.py: the line shown above each source.
The model reads it to say "withdrawn" or "law assumed", and the user reads it to trust the citation."""

from langchain_core.documents import Document

from taxowl.answer.pipeline import label


def source(**metadata) -> Document:
    """A chunk with only the labels label() reads; the text doesn't matter here."""
    base = {"quality_ok": True, "page_start": 1, "page_end": 1}
    return Document(page_content="", metadata=base | metadata)


def test_withdrawn_circular_says_so():
    # the most costly mistake: a withdrawn circular shown as the law in force
    doc = source(doc_type="circular", doc_number="37/11/2018-GST", title="Clarification on export",
                 location="para 2", status="withdrawn", changed_by="125/44/2019 - GST")
    assert label(doc) == "Circular 37/11/2018-GST, para 2, p.1 (WITHDRAWN by Circular 125/44/2019 - GST)"


def test_assumed_law_is_shown():
    doc = source(doc_type="act", doc_number="Act 12 of 2017",
                 title="The Central Goods and Services Tax Act, 2017",
                 location="section 16(4)", page_start=23, page_end=23, law_assumed=True)
    assert label(doc) == "The Central Goods and Services Tax Act, 2017, section 16(4), p.23 (law assumed)"


def test_date_and_page_range():
    doc = source(doc_type="circular", doc_number="238/32/2024-GST", title="Clarification on ITC",
                 doc_date="2024-10-15", location="para 4", page_start=2, page_end=3)
    assert label(doc) == "Circular 238/32/2024-GST, dated 2024-10-15, para 4, p.2-3"
