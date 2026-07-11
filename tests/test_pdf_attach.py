"""SourcePDF attachment unit tests.

Fake PDF files created under tmp_path exercise the matching heuristics.
"""
from __future__ import annotations

import sys
from pathlib import Path


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


def test_find_pdf_prefers_shortest_name(tmp_path):
    lib = tmp_path / "library"
    lib.mkdir()
    (lib / "2017_Klepsch_short.pdf").write_bytes(b"%PDF")
    (lib / "2017_Klepsch_a_much_longer_alternative_filename.pdf").write_bytes(b"%PDF")
    result = pdf_attach.find_pdf_for_ref("Klepsch", 2017, library_root=lib)
    assert result is not None
    assert "short" in result.name


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
