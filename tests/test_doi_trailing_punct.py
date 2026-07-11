"""DOI trailing-punctuation stripping + status overclaim regressions.

- Trailing period: the sentence-final period of a reference entry
  (`...doi.org/10.9999/wrong.`) was absorbed into the DOI value, capturing
  `10.9999/wrong.`; it is now stripped from the end only.
- Status: a merely present DOI string was labelled "verified" — an overclaim
  before any registry lookup — and is now labelled "doi-present".
"""
from __future__ import annotations

import sys
from pathlib import Path


from paper_verifier import doi_audit

FIXTURE = """---
total_references: 2
---

# References

Wrong, A. B. (2099). A deliberately crafted reference for the trailing period test. *Test Journal*, *1*(1), 1–2. https://doi.org/10.9999/wrong.

Internal, C. D. (2098). Reference whose DOI legitimately contains internal dots. *Another Journal*, *2*(2), 3–4. https://doi.org/10.1000/xyz.123
"""


def _refs(tmp_path):
    md = tmp_path / "refs.md"
    md.write_text(FIXTURE, encoding="utf-8")
    return doi_audit.parse_references(md)


def test_trailing_period_stripped_from_doi(tmp_path):
    """The sentence-final period of a reference entry is stripped from the DOI."""
    refs = _refs(tmp_path)
    wrong = next(r for r in refs if r.id == "Wrong2099")
    assert wrong.doi == "10.9999/wrong"          # trailing '.' removed
    assert not wrong.doi.endswith(".")


def test_internal_dots_preserved(tmp_path):
    """Legitimate dots inside a DOI (10.1000/xyz.123) are preserved — only the end is stripped."""
    refs = _refs(tmp_path)
    internal = next(r for r in refs if r.id == "Internal2098")
    assert internal.doi == "10.1000/xyz.123"


def test_doi_present_not_overclaimed_as_verified(tmp_path):
    """A present DOI string is labelled 'doi-present' — never 'verified' before a registry lookup."""
    refs = _refs(tmp_path)
    wrong = next(r for r in refs if r.id == "Wrong2099")
    assert wrong.status == "doi-present"
    assert wrong.status != "verified"
    assert wrong.crossref_match == "unchecked"   # records that no lookup actually ran
