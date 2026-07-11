"""Unit tests for ReferenceEntry parsing, InTextCitation extraction, and linking."""
from __future__ import annotations

import sys
from pathlib import Path


from paper_verifier import doi_audit


FIXTURE_REFS_MD = """---
total_references: 3
---

# References (APA 7th edition)

Klepsch, M., Schmitz, F., & Seufert, T. (2017). Development and validation of two scales measuring intrinsic, extraneous, and germane cognitive load. *Frontiers in Psychology*, *8*, 1997. https://doi.org/10.3389/fpsyg.2017.01997

Bates, D., Mächler, M., Bolker, B., & Walker, S. (2015). Fitting linear mixed-effects models using lme4. *Journal of Statistical Software*, *67*(1), 1–48. https://doi.org/10.18637/jss.v067.i01

Henderson, K., & Schroeder, R. (2021). [TBD-DOI: title unknown]. *Computers & Education*.

> 검토 필요: 이 entry는 DOI/title 미확인 (editorial note in Korean — must be skipped as a blockquote).
"""


def test_parse_references_extracts_three_entries(tmp_path):
    md = tmp_path / "refs.md"
    md.write_text(FIXTURE_REFS_MD, encoding="utf-8")
    refs = doi_audit.parse_references(md)
    ids = sorted([r.id for r in refs])
    # Exactly 3 entries (frontmatter / heading / blockquote lines are skipped)
    assert len(refs) == 3
    assert "Klepsch2017" in ids
    assert "Bates2015" in ids
    assert "Henderson2021" in ids


def test_parse_references_extracts_doi(tmp_path):
    md = tmp_path / "refs.md"
    md.write_text(FIXTURE_REFS_MD, encoding="utf-8")
    refs = doi_audit.parse_references(md)
    klepsch = next(r for r in refs if r.id == "Klepsch2017")
    assert klepsch.doi == "10.3389/fpsyg.2017.01997"
    assert klepsch.year == 2017
    assert klepsch.first_author_last == "Klepsch"
    # A present DOI string is not registry-verified, so the status is
    # "doi-present" (labelling it "verified" would be an overclaim)
    assert klepsch.status == "doi-present"


def test_parse_references_tbd_doi_status(tmp_path):
    md = tmp_path / "refs.md"
    md.write_text(FIXTURE_REFS_MD, encoding="utf-8")
    refs = doi_audit.parse_references(md)
    hs = next(r for r in refs if r.id == "Henderson2021")
    assert hs.status == "tbd-doi"
    assert hs.doi is None


def test_extract_parenthetical_citation():
    text = "Cognitive load was measured with Klepsch et al.'s (2017) eight items, as also shown by (Bates et al., 2015)."
    cites = doi_audit.extract_citations(text, "mss-001", "methods")
    types = [c.citation_type for c in cites]
    assert "narrative" in types  # Klepsch et al. (2017)
    assert "parenthetical" in types  # (Bates et al., 2015)
    bates = next(c for c in cites if c.citation_type == "parenthetical")
    assert bates.first_author_last == "Bates"
    assert bates.year == 2015


def test_extract_narrative_citation():
    text = "Klepsch et al. (2017) developed the three-factor instrument."
    cites = doi_audit.extract_citations(text, "mss-001", "methods")
    narrative = [c for c in cites if c.citation_type == "narrative"]
    assert len(narrative) == 1
    assert narrative[0].first_author_last == "Klepsch"
    assert narrative[0].year == 2017


def test_link_citations_resolves_to_ref(tmp_path):
    md = tmp_path / "refs.md"
    md.write_text(FIXTURE_REFS_MD, encoding="utf-8")
    refs = doi_audit.parse_references(md)
    text = "Klepsch et al. (2017) developed the instrument, used together with (Bates et al., 2015)."
    cites = doi_audit.extract_citations(text, "mss-001", "methods")
    cites, orphans, dangling = doi_audit.link_citations(cites, refs)
    # Both citations resolve to refs
    linked = [c for c in cites if c.ref_id is not None]
    assert len(linked) >= 2
    # Henderson is never cited in the body -> orphan
    assert "Henderson2021" in orphans
    # No dangling citations
    assert dangling == []


def test_link_citations_detects_dangling():
    refs = []  # empty ref list
    cites = doi_audit.extract_citations("(Klepsch et al., 2017)", "mss-001", "methods")
    cites, orphans, dangling = doi_audit.link_citations(cites, refs)
    assert orphans == []
    assert len(dangling) >= 1


def test_extract_citations_skips_blockquote_editorial_memo():
    """Citations inside `>` blockquote lines (editorial memos) are not extracted.

    Guards against a bug where a correction memo quoted in a blockquote
    (`> **...**: (Pataranutaporn et al., 2022) → ...`) was absorbed as a
    paraphrase-evaluation target.
    """
    text = (
        "Klepsch et al. (2017) developed the three-factor instrument.\n"
        "> **본문 정정 필요**: (Pataranutaporn et al., 2022) → (Pataranutaporn et al., 2021)\n"
        "Bates et al. (2015) provided the lme4 package.\n"
    )
    cites = doi_audit.extract_citations(text, "mss-001", "introduction")
    authors = sorted([c.first_author_last for c in cites])
    # Pataranutaporn (blockquote) is excluded; only Klepsch + Bates from normal lines
    assert "Klepsch" in authors
    assert "Bates" in authors
    assert "Pataranutaporn" not in authors


def test_extract_citations_skips_indented_blockquote():
    """A line whose first non-whitespace character is `>` still counts as a blockquote."""
    text = (
        "Normal line cites (Author, 2020).\n"
        "    > Indented blockquote with (Smith, 2019).\n"
    )
    cites = doi_audit.extract_citations(text, "mss-001", "intro")
    authors = sorted([c.first_author_last for c in cites])
    assert "Author" in authors
    assert "Smith" not in authors


def test_extract_citations_non_blockquote_with_gt_inline_preserved():
    """A `>` appearing mid-line (not at line start) must not suppress extraction."""
    text = "Effect size d_z > 0.4 was observed (Klepsch et al., 2017).\n"
    cites = doi_audit.extract_citations(text, "mss-001", "results")
    authors = [c.first_author_last for c in cites]
    assert "Klepsch" in authors


# ─── Multi-citation parentheticals split into separate citations ───────


def test_multi_citation_paren_splits_two_authors():
    """`(Author A et al., 2022; Author B et al., 2024)` yields two separate citations."""
    text = "Studies (Pataranutaporn et al., 2022; Xu et al., 2024) suggest that ..."
    cites = doi_audit.extract_citations(text, "mss-001", "intro")
    authors_years = sorted([(c.first_author_last, c.year) for c in cites])
    assert ("Pataranutaporn", 2022) in authors_years
    assert ("Xu", 2024) in authors_years
    assert len(authors_years) == 2


def test_multi_citation_paren_splits_three_authors():
    text = "Several studies (Zhang et al., 2023; Henderson & Schroeder, 2021; Beege et al., 2023) ..."
    cites = doi_audit.extract_citations(text, "mss-001", "intro")
    authors_years = sorted([(c.first_author_last, c.year) for c in cites])
    assert ("Zhang", 2023) in authors_years
    assert ("Henderson", 2021) in authors_years
    assert ("Beege", 2023) in authors_years
    assert len(authors_years) == 3


def test_paren_with_abbrev_prefix_extracts_real_author():
    """`(CTML; Mayer, 2009)` extracts Mayer 2009; the abbreviation prefix is skipped."""
    text = "The Cognitive Theory of Multimedia Learning (CTML; Mayer, 2009) frames learners ..."
    cites = doi_audit.extract_citations(text, "mss-001", "intro")
    parenthetical = [c for c in cites if c.citation_type == "parenthetical"]
    authors_years = sorted([(c.first_author_last, c.year) for c in parenthetical])
    assert ("Mayer", 2009) in authors_years
    # The CTML prefix is not an author (the sub-citation pattern fails to match, so it is skipped)
    assert "CTML" not in [a for a, _ in authors_years]


def test_paren_with_page_numbering_extracts_author_year():
    """`(Klepsch et al., 2017, p. 14)` extracts Klepsch 2017; the page suffix is ignored."""
    text = "As stated (Klepsch et al., 2017, p. 14), cognitive load ..."
    cites = doi_audit.extract_citations(text, "mss-001", "intro")
    authors_years = sorted([(c.first_author_last, c.year) for c in cites if c.citation_type == "parenthetical"])
    assert ("Klepsch", 2017) in authors_years


def test_paren_with_ampersand_two_authors_extracts_first():
    """`(Klepsch & Schmitz, 2017)` extracts Klepsch 2017 (first author only)."""
    text = "Earlier work (Klepsch & Schmitz, 2017) on instrument validation ..."
    cites = doi_audit.extract_citations(text, "mss-001", "intro")
    authors_years = [(c.first_author_last, c.year) for c in cites if c.citation_type == "parenthetical"]
    assert ("Klepsch", 2017) in authors_years
    # The second author (Schmitz) gets no separate citation; matching keys on the first author
    assert "Schmitz" not in [a for a, _ in authors_years]


def test_paren_with_year_letter_suffix():
    """`(Mayer, 2009a)` extracts Mayer 2009 (the letter suffix is stripped from the year)."""
    text = "Earlier (Mayer, 2009a) and later (Mayer, 2014) work ..."
    cites = doi_audit.extract_citations(text, "mss-001", "intro")
    parenthetical = [c for c in cites if c.citation_type == "parenthetical"]
    authors_years = sorted([(c.first_author_last, c.year) for c in parenthetical])
    assert ("Mayer", 2009) in authors_years
    assert ("Mayer", 2014) in authors_years


def test_paren_single_author_unchanged():
    """Plain single-entry parentheticals like `(Mayer, 2014)` still work (no regression)."""
    text = "Recent work (Mayer, 2014) builds on this."
    cites = doi_audit.extract_citations(text, "mss-001", "intro")
    parenthetical = [c for c in cites if c.citation_type == "parenthetical"]
    assert len(parenthetical) == 1
    assert parenthetical[0].first_author_last == "Mayer"
    assert parenthetical[0].year == 2014


def test_paren_non_citation_does_not_match():
    """Non-citation parentheticals (sample sizes, idioms, bare abbreviations) do not match."""
    text = "The sample (N = 38) showed (in fact) significant (DHAs) effects."
    cites = doi_audit.extract_citations(text, "mss-001", "results")
    parenthetical = [c for c in cites if c.citation_type == "parenthetical"]
    assert parenthetical == []


# ─── Year alternatives (`YYYY/YYYY`, republished works) ────────────────


def test_paren_with_year_alternative_captures_both():
    """`(Mori, 1970/2012)` parses as year=1970 with year_alt=2012."""
    text = "Uncanny valley theory (Mori, 1970/2012) provides a framework."
    cites = doi_audit.extract_citations(text, "mss-001", "intro")
    parenthetical = [c for c in cites if c.citation_type == "parenthetical"]
    assert len(parenthetical) == 1
    assert parenthetical[0].first_author_last == "Mori"
    assert parenthetical[0].year == 1970
    assert parenthetical[0].year_alt == 2012


def test_narrative_with_year_alternative_captures_both():
    """Narrative `Mori (1970/2012)` parses as year=1970 with year_alt=2012."""
    text = "Mori (1970/2012) proposed the uncanny valley."
    cites = doi_audit.extract_citations(text, "mss-001", "intro")
    narrative = [c for c in cites if c.citation_type == "narrative"]
    assert len(narrative) >= 1
    mori = next(c for c in narrative if c.first_author_last == "Mori")
    assert mori.year == 1970
    assert mori.year_alt == 2012


def test_link_citations_uses_year_alt_fallback(tmp_path):
    """A ref listed as `Mori (2012)` still matches an in-text `Mori, 1970/2012` via year_alt."""
    refs_md = tmp_path / "refs.md"
    refs_md.write_text(
        "---\ntotal_references: 1\n---\n\n"
        "# References\n\n"
        "Mori, M. (2012). The uncanny valley. *IEEE Robotics & Automation Magazine*, *19*(2), 98–100. "
        "https://doi.org/10.1109/MRA.2012.2192811 (Original work published 1970)\n",
        encoding="utf-8",
    )
    refs = doi_audit.parse_references(refs_md)
    assert any(r.id == "Mori2012" for r in refs)

    # The in-text citation uses the 1970/2012 notation
    text = "Theory (Mori, 1970/2012) was foundational."
    cites = doi_audit.extract_citations(text, "mss-001", "intro")
    cites, orphans, dangling = doi_audit.link_citations(cites, refs)
    mori_cite = next(c for c in cites if c.first_author_last == "Mori")
    # ref_id resolves through the year_alt fallback
    assert mori_cite.ref_id == "Mori2012"
    assert "Mori2012" not in orphans
    assert mori_cite.id not in dangling


def test_link_citations_year_alt_only_used_when_primary_fails():
    """The primary year (Klepsch, 2017) matches ref Klepsch2017 directly; no year_alt fallback involved."""
    refs = [
        doi_audit.ReferenceEntry(
            id="Klepsch2017", raw_text="", authors_raw="Klepsch, M.",
            first_author_last="Klepsch", year=2017, title="t",
        ),
    ]
    text = "(Klepsch et al., 2017) developed."
    cites = doi_audit.extract_citations(text, "mss-001", "intro")
    cites, orphans, dangling = doi_audit.link_citations(cites, refs)
    assert cites[0].ref_id == "Klepsch2017"
    assert cites[0].year_alt is None  # single year, no alternative


def test_year_alt_in_multi_citation_paren():
    """`(Mori, 1970/2012; Diel & MacDorman, 2022)` splits in two and keeps Mori's year_alt."""
    text = "Uncanny valley work (Mori, 1970/2012; Diel & MacDorman, 2022) ..."
    cites = doi_audit.extract_citations(text, "mss-001", "intro")
    parenthetical = [c for c in cites if c.citation_type == "parenthetical"]
    mori = next(c for c in parenthetical if c.first_author_last == "Mori")
    diel = next(c for c in parenthetical if c.first_author_last == "Diel")
    assert mori.year == 1970 and mori.year_alt == 2012
    assert diel.year == 2022 and diel.year_alt is None


# ─── Citation purpose classification (heuristic) ───────────────────────


def test_classify_finding_cite_narrative_with_verb():
    """Narrative citation with a finding verb ("showed") -> finding-cite."""
    p = doi_audit.classify_citation_purpose(
        paraphrase="Klepsch et al. (2017) showed that cognitive load varies.",
        citation_type="narrative",
        raw_text="Klepsch et al. (2017)",
    )
    assert p == "finding-cite"


def test_classify_finding_cite_parenthetical_with_verb():
    """Parenthetical citation with a finding verb in the paraphrase -> finding-cite."""
    p = doi_audit.classify_citation_purpose(
        paraphrase="Reduced dwell time was observed in HQ avatars (Klepsch et al., 2017).",
        citation_type="parenthetical",
        raw_text="(Klepsch et al., 2017)",
    )
    assert p == "finding-cite"


def test_classify_method_cite():
    """A "measured with ... instrument" paraphrase -> method-cite."""
    p = doi_audit.classify_citation_purpose(
        paraphrase="Cognitive load was measured with Klepsch et al.'s (2017) eight-item instrument.",
        citation_type="narrative",
        raw_text="Klepsch et al.'s (2017)",
    )
    assert p == "method-cite"


def test_classify_theory_cite_with_abbrev_prefix():
    """An abbreviation prefix as in `(CTML; Mayer, 2009)` -> theory-cite."""
    p = doi_audit.classify_citation_purpose(
        paraphrase="The Cognitive Theory of Multimedia Learning (CTML; Mayer, 2009) frames learners.",
        citation_type="parenthetical",
        raw_text="(CTML; Mayer, 2009)",
    )
    assert p == "theory-cite"


def test_classify_theory_cite_keyword():
    """'theory'/'framework' keywords in the paraphrase -> theory-cite."""
    p = doi_audit.classify_citation_purpose(
        paraphrase="Uncanny valley theory (Mori, 1970/2012) provides a framework.",
        citation_type="parenthetical",
        raw_text="(Mori, 1970/2012)",
    )
    assert p == "theory-cite"


def test_classify_background_cite_default():
    """Generic background statement with no finding/method/theory keywords."""
    p = doi_audit.classify_citation_purpose(
        paraphrase="DHAs are increasingly used in online learning (Pataranutaporn et al., 2022; Xu et al., 2024).",
        citation_type="parenthetical",
        raw_text="(Pataranutaporn et al., 2022; Xu et al., 2024)",
    )
    # 'used' appears, but with no method noun (instrument/scale/...) alongside
    # it, the citation stays background
    assert p == "background-cite"


def test_classify_self_reported_not_finding_cite():
    """'reported' inside a phrase like 'self-reported outcomes' is not a finding verb (blocks a false positive)."""
    p = doi_audit.classify_citation_purpose(
        paraphrase="Self-reported outcomes (Klepsch et al., 2017) and process indicators were collected.",
        citation_type="parenthetical",
        raw_text="(Klepsch et al., 2017)",
    )
    # none of method/theory/finding match, so it falls back to background-cite
    assert p != "finding-cite"


def test_classify_extract_citations_assigns_purpose():
    """extract_citations populates InTextCitation.citation_purpose."""
    text = (
        "Klepsch et al. (2017) demonstrated cognitive load effects.\n"
        "We measured load with Klepsch et al.'s (2017) instrument.\n"
        "The CTML framework (CTML; Mayer, 2009) frames learners.\n"
        "DHAs are common (Foo et al., 2022; Bar et al., 2024).\n"
    )
    cites = doi_audit.extract_citations(text, "mss-001", "intro")
    by_author = {c.first_author_last: c for c in cites}
    # line 1: narrative + demonstrated → finding-cite
    # line 2: narrative + measured + instrument → method-cite
    # line 3: paren with abbrev prefix → theory-cite (paren cite)
    # line 4: paren without finding/method/theory → background-cite
    purposes = {c.first_author_last: c.citation_purpose for c in cites}
    # The first Klepsch narrative (line 1) is finding-cite
    klepsch_narratives = [c for c in cites if c.first_author_last == "Klepsch" and c.citation_type == "narrative"]
    assert any(c.citation_purpose == "finding-cite" for c in klepsch_narratives)
    assert any(c.citation_purpose == "method-cite" for c in klepsch_narratives)
    # CTML prefix → Mayer theory-cite
    mayer = [c for c in cites if c.first_author_last == "Mayer"]
    assert mayer and mayer[0].citation_purpose == "theory-cite"
    # Foo/Bar → background-cite
    foo = [c for c in cites if c.first_author_last == "Foo"]
    assert foo and foo[0].citation_purpose == "background-cite"
