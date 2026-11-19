"""Tests for src/taxowl/retrieval/citations.py: reading sections, rules and circulars out of a question.
The reader drives the exact lookup, so a miss here means the right section is never fetched by number."""

from taxowl.retrieval.citations import Citation, read_citations


def test_section_with_subsection():
    # no law named -> CGST Act, and law_assumed says so (the answer must say it too)
    assert read_citations("What does section 16(4) say?") == [
        Citation("section", "16", ("4",), "CGST Act", law_assumed=True)
    ]


def test_range_is_listed_out():
    numbers = [c.number for c in read_citations("Compare sections 16 to 18")]
    assert numbers == ["16", "17", "18"]


def test_other_law_gives_no_citation():
    # better no exact hit than the CGST Act's section 10 for an Income-tax question
    assert read_citations("What does section 10 of the Income-tax Act say?") == []


def test_circular_number_is_read():
    assert read_citations("Is Circular 183/15/2022-GST still in force?") == [
        Citation("circular", "183/15/2022")
    ]


def test_date_is_not_a_circular():
    # 15/10/2024 has the same shape as a circular number; only "circular" or "-GST" makes it one
    assert read_citations("What changed on 15/10/2024?") == []
