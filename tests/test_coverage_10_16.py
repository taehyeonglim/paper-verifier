"""Coverage regressions — η² claim extraction + PDF page_hint windowing."""
from __future__ import annotations

import sys
import types
from pathlib import Path


from paper_verifier import claim_parser, paraphrase_match


# ─── η² extraction ────────────────────────────────────────────────────────

def test_claim_parser_extracts_eta_squared(tmp_path):
    """η² = .12 is extracted as an eta_squared claim (the pattern used to be missing)."""
    p = tmp_path / "doc.md"
    p.write_text("The main effect was large, η² = .12 in this analysis.", encoding="utf-8")
    claims = claim_parser.extract_from_file(p, "m1", "results")
    assert "eta_squared" in [c.claim_type for c in claims]


def test_claim_parser_extracts_partial_eta_squared(tmp_path):
    """The partial η² form is extracted as well."""
    p = tmp_path / "doc.md"
    p.write_text("A moderate effect, partial η² = .06 was observed.", encoding="utf-8")
    claims = claim_parser.extract_from_file(p, "m1", "results")
    assert "eta_squared" in [c.claim_type for c in claims]


# ─── PDF page_hint ────────────────────────────────────────────────────────

class _Page:
    def __init__(self, txt):
        self._t = txt

    def extract_text(self):
        return self._t


class _PDFCtx:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _install_fake_pdfplumber(monkeypatch, n_pages):
    pages = [_Page(("PAGEMARK%02d " % i) * 60) for i in range(n_pages)]
    mod = types.ModuleType("pdfplumber")
    mod.open = lambda path: _PDFCtx(pages)
    monkeypatch.setitem(sys.modules, "pdfplumber", mod)


def test_page_hint_reads_around_hinted_page(monkeypatch, tmp_path):
    """With page_hint=18 on a 20-page PDF, pages around the hint (16-18) are read — beyond the default 15-page window."""
    _install_fake_pdfplumber(monkeypatch, n_pages=20)
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    result = paraphrase_match.extract_quote_from_pdf(pdf, keywords=None, page_hint=18)
    assert "PAGEMARK16" in result          # pages around the hint are read
    assert "PAGEMARK00" not in result       # not the leading pages


def test_no_page_hint_reads_leading_pages(monkeypatch, tmp_path):
    """Without page_hint the leading pages are read (backward compatible)."""
    _install_fake_pdfplumber(monkeypatch, n_pages=20)
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    result = paraphrase_match.extract_quote_from_pdf(pdf, keywords=None, page_hint=None)
    assert "PAGEMARK00" in result           # reads from the front
    assert "PAGEMARK18" not in result        # nothing beyond the 15-page window
