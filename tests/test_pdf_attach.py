"""SourcePDF attachment unit tests.

Fake PDF files created under tmp_path exercise the matching heuristics.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from paper_verifier import pdf_attach
from paper_verifier.doi_audit import ReferenceEntry


def test_find_pdf_by_author_year(tmp_path):
    lib = tmp_path / "library"
    lib.mkdir()
    (lib / "2017_Klepsch_cognitive_load.pdf").write_bytes(b"%PDF")
    result = pdf_attach.find_pdf_for_ref("Klepsch", 2017, library_root=lib)
    assert result is not None
    assert result.name == "2017_Klepsch_cognitive_load.pdf"


def test_find_pdf_not_found(tmp_path):
    lib = tmp_path / "library"
    lib.mkdir()
    result = pdf_attach.find_pdf_for_ref("Klepsch", 2017, library_root=lib)
    assert result is None


def test_find_pdf_withholds_ambiguous_author_year(tmp_path):
    lib = tmp_path / "library"
    lib.mkdir()
    (lib / "2017_Klepsch_short.pdf").write_bytes(b"%PDF")
    (lib / "2017_Klepsch_a_much_longer_alternative_filename.pdf").write_bytes(b"%PDF")
    result = pdf_attach.find_pdf_for_ref("Klepsch", 2017, library_root=lib)
    assert result is None
    ref = ReferenceEntry(id="Klepsch2017", raw_text="", authors_raw="Klepsch, M.",
                         first_author_last="Klepsch", year=2017, title="t")
    pdf = pdf_attach.attach_pdfs([ref], library_root=lib)[0]
    assert pdf.source_kind == "ambiguous"
    assert pdf.pdf_path is None
    assert ref.pdf_attached is False


def test_attach_pdfs_marks_pdf_attached(tmp_path):
    lib = tmp_path / "library"
    lib.mkdir()
    (lib / "2017_Klepsch.pdf").write_bytes(b"%PDF")
    refs = [
        ReferenceEntry(id="Klepsch2017", raw_text="", authors_raw="Klepsch, M.", first_author_last="Klepsch", year=2017, title="t"),
        ReferenceEntry(id="MissingAuthor2099", raw_text="", authors_raw="Nobody, X.", first_author_last="Nobody", year=2099, title="t"),
    ]
    pdfs = pdf_attach.attach_pdfs(refs, library_root=lib)
    assert len(pdfs) == 2
    assert pdfs[0].pdf_path is not None
    assert pdfs[1].pdf_path is None
    assert pdfs[1].source_kind == "not-found"
    assert refs[0].pdf_attached is True
    assert refs[1].pdf_attached is False


def test_attach_pdfs_fuzzy_year_flagged(tmp_path):
    """A ±1-year match is flagged source_kind=library-collected-yearfuzzy (not treated as certain)."""
    lib = tmp_path / "library"
    lib.mkdir()
    (lib / "2022_Pataranutaporn_avatar.pdf").write_bytes(b"%PDF")   # ref year is 2021 -> ±1 fuzzy
    refs = [ReferenceEntry(id="Pataranutaporn2021", raw_text="",
                           authors_raw="Pataranutaporn, P.", first_author_last="Pataranutaporn",
                           year=2021, title="t")]
    pdfs = pdf_attach.attach_pdfs(refs, library_root=lib)
    assert pdfs[0].pdf_path is not None
    assert pdfs[0].source_kind == "library-collected-yearfuzzy"


def test_attach_pdfs_exact_year_not_flagged(tmp_path):
    """An exact-year match stays library-collected (no false flag)."""
    lib = tmp_path / "library"
    lib.mkdir()
    (lib / "2021_Pataranutaporn_avatar.pdf").write_bytes(b"%PDF")
    refs = [ReferenceEntry(id="Pataranutaporn2021", raw_text="",
                           authors_raw="Pataranutaporn, P.", first_author_last="Pataranutaporn",
                           year=2021, title="t")]
    pdfs = pdf_attach.attach_pdfs(refs, library_root=lib)
    assert pdfs[0].source_kind == "library-collected"


@pytest.mark.parametrize("author", ["김", "王", "山田", "García"])
def test_unicode_author_is_preserved(tmp_path, author):
    expected = tmp_path / f"2024_{author}_study.pdf"
    expected.write_bytes(b"%PDF")
    (tmp_path / "2024_Other_study.pdf").write_bytes(b"%PDF")
    assert pdf_attach._normalize(author)
    assert pdf_attach.find_pdf_for_ref(author, 2024, tmp_path) == expected


@pytest.mark.parametrize("author", ["", "---", "   ", "Li"])
def test_empty_or_partial_author_key_does_not_match(tmp_path, author):
    (tmp_path / "2024_Williams_study.pdf").write_bytes(b"%PDF")
    assert pdf_attach.find_pdf_for_ref(author, 2024, tmp_path) is None


def test_year_requires_complete_token(tmp_path):
    (tmp_path / "120240_Kim_study.pdf").write_bytes(b"%PDF")
    assert pdf_attach.find_pdf_for_ref("Kim", 2024, tmp_path) is None


@pytest.mark.parametrize("identity", ["title", "doi"])
def test_identity_disambiguates_author_year(tmp_path, identity):
    expected = tmp_path / "2024_Kim_cognitive_load.md"
    expected.write_text('---\ndoi: "10.1000/correct"\n---\n# Body', encoding="utf-8")
    (tmp_path / "2024_Kim_short.pdf").write_bytes(b"%PDF")
    ref = ReferenceEntry(
        id="Kim2024", raw_text="", authors_raw="Kim, J.", first_author_last="Kim", year=2024,
        title="Cognitive load" if identity == "title" else "t",
        doi="10.1000/correct" if identity == "doi" else None,
    )
    pdf = pdf_attach.attach_pdfs([ref], tmp_path)[0]
    assert pdf.pdf_path == str(expected.resolve())
    assert pdf.source_kind == "library-collected"
    assert ref.pdf_attached is True


def test_explicit_doi_conflict_prevents_author_year_fallback(tmp_path):
    (tmp_path / "2024_Kim_study.md").write_text(
        "---\ndoi: 10.1000/wrong\n---\nCites https://doi.org/10.1000/correct", encoding="utf-8",
    )
    ref = ReferenceEntry(id="Kim2024", raw_text="", authors_raw="Kim, J.",
                         first_author_last="Kim", year=2024, title="t", doi="10.1000/correct")
    pdf = pdf_attach.attach_pdfs([ref], tmp_path)[0]
    assert pdf.pdf_path is None
    assert ref.pdf_attached is False


def test_title_tokens_do_not_override_an_unrelated_author(tmp_path):
    (tmp_path / "2024_Other_cognitive_load.pdf").write_bytes(b"%PDF")
    ref = ReferenceEntry(id="Kim2024", raw_text="", authors_raw="Kim, J.",
                         first_author_last="Kim", year=2024, title="Cognitive load")
    assert pdf_attach.attach_pdfs([ref], tmp_path)[0].pdf_path is None


def test_doi_identity_takes_precedence_over_title_tokens(tmp_path):
    expected = tmp_path / "source.md"
    expected.write_text("---\ndoi: 10.1000/correct\n---\n# Body", encoding="utf-8")
    (tmp_path / "2024_Kim_cognitive_load.pdf").write_bytes(b"%PDF")
    ref = ReferenceEntry(id="Kim2024", raw_text="", authors_raw="Kim, J.",
                         first_author_last="Kim", year=2024, title="Cognitive load", doi="10.1000/correct")
    assert pdf_attach.attach_pdfs([ref], tmp_path)[0].pdf_path == str(expected.resolve())
