"""Same-author same-year references (2024a/2024b) must stay distinct.

Background: reference/citation years were parsed as bare integers, dropping
the letter suffix, so both refs collapsed onto one `Smith2024` slug and
ref-index key — the later ref overwrote the earlier one, and 2024a/2024b
citations matched the same ref. The suffix is preserved in slugs and keys so
the refs are handled separately.
"""
from __future__ import annotations

import sys
from pathlib import Path


from paper_verifier import doi_audit

REFS_SUFFIX = """---
total_references: 2
---

# References

Smith, A. B. (2024a). First distinct paper by Smith in twenty twenty four. *Journal A*, *1*(1), 1–2. https://doi.org/10.1000/aaa

Smith, A. B. (2024b). Second distinct paper by Smith in twenty twenty four. *Journal B*, *2*(2), 3–4. https://doi.org/10.1000/bbb
"""


def _refs(tmp_path, md):
    p = tmp_path / "refs.md"
    p.write_text(md, encoding="utf-8")
    return doi_audit.parse_references(p)


def test_suffixed_refs_get_distinct_slugs(tmp_path):
    """2024a/2024b parse into distinct slugs without colliding."""
    refs = _refs(tmp_path, REFS_SUFFIX)
    ids = sorted(r.id for r in refs)
    assert ids == ["Smith2024a", "Smith2024b"]
    assert len(refs) == 2


def test_suffixed_citations_link_to_correct_refs(tmp_path):
    """(Smith, 2024a) and (Smith, 2024b) each link to the correct ref (no slug collapse)."""
    refs = _refs(tmp_path, REFS_SUFFIX)
    text = "As shown (Smith, 2024a) and also (Smith, 2024b) in separate works."
    cites = doi_audit.extract_citations(text, "m1", "intro")
    linked, orphans, dangling = doi_audit.link_citations(cites, refs)
    a = next(c for c in linked if "2024a" in c.raw_text)
    b = next(c for c in linked if "2024b" in c.raw_text)
    assert a.ref_id == "Smith2024a"
    assert b.ref_id == "Smith2024b"
    assert a.ref_id != b.ref_id
    assert not dangling
    assert not orphans   # both refs are cited


def test_bare_citation_with_ambiguous_suffixed_refs_is_dangling(tmp_path):
    """A bare (Smith, 2024) with two suffixed refs is ambiguous -> dangling (prevents a wrong match)."""
    refs = _refs(tmp_path, REFS_SUFFIX)
    text = "A vague reference (Smith, 2024) without any suffix here."
    cites = doi_audit.extract_citations(text, "m1", "intro")
    linked, orphans, dangling = doi_audit.link_citations(cites, refs)
    assert len(dangling) == 1


def test_bare_citation_single_ref_still_matches(tmp_path):
    """A single unsuffixed ref still matches a bare citation (backward compatible)."""
    md = """---
total_references: 1
---

# References

Jones, C. (2020). A single distinct paper by Jones. *Journal*, *5*(1), 1–10. https://doi.org/10.1000/jones
"""
    refs = _refs(tmp_path, md)
    text = "Prior work (Jones, 2020) established the baseline."
    cites = doi_audit.extract_citations(text, "m1", "intro")
    linked, orphans, dangling = doi_audit.link_citations(cites, refs)
    assert linked[0].ref_id == "Jones2020"
    assert not dangling
