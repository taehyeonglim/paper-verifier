"""Unit tests for paraphrase_match — frontmatter stripping + keyword windowing.

Real LLM calls are never exercised: functions are tested in isolation with
mocks. The only call-path behavior pinned here is that
dispatch_paraphrase_check degrades gracefully to (-1.0, message) when the
codex CLI is not installed.
"""
from __future__ import annotations

import sys
from pathlib import Path


from paper_verifier import paraphrase_match


FIXTURE_MD_SURROGATE = """---
title: Development and Validation of Two Instruments Measuring Cognitive Load
citekey: klepsch2017
authors: ["Melina Klepsch", "Florian Schmitz", "Tina Seufert"]
year: 2017
venue: Frontiers in Psychology
doi: 10.3389/fpsyg.2017.01997
---

# Abstract

Self-report measures of cognitive load are widely used in educational research,
but their validity has been questioned. Learners may not consciously detect
their own attentional shifts, and explicit ratings can diverge from in-the-moment
processing. This paper develops two instruments measuring intrinsic, extraneous,
and germane cognitive load with sound psychometric properties.

# Introduction

Eye-tracking provides direct evidence of where and how long visual attention is
deployed, complementing self-report by capturing in-the-moment processing that
participants may not be consciously aware of. Several studies have shown that
self-report and eye-tracking can diverge meaningfully, suggesting that combining
both is more informative than either alone.
"""


FIXTURE_NO_FRONTMATTER = """# Heading

Just plain body text without any YAML header. Should pass through unchanged.
"""


def test_strip_frontmatter_md_surrogate():
    out = paraphrase_match.strip_frontmatter(FIXTURE_MD_SURROGATE)
    assert not out.startswith("---")
    assert "title:" not in out.split("\n")[0]  # YAML key not in first body line
    assert "# Abstract" in out
    assert "Self-report measures" in out


def test_strip_frontmatter_no_header_passthrough():
    out = paraphrase_match.strip_frontmatter(FIXTURE_NO_FRONTMATTER)
    assert out == FIXTURE_NO_FRONTMATTER


def test_strip_frontmatter_empty_string():
    assert paraphrase_match.strip_frontmatter("") == ""


def test_extract_keywords_filters_stopwords():
    paraphrase = "Self-report measures alone may not adequately capture these effects."
    kws = paraphrase_match.extract_keywords(paraphrase)
    kws_lower = [k.lower() for k in kws]
    # stopwords (may, not, these) are excluded
    assert "may" not in kws_lower
    assert "not" not in kws_lower
    assert "these" not in kws_lower
    # meaningful keywords are retained
    assert any("self" in k.lower() or "report" in k.lower() for k in kws)
    assert "capture" in kws_lower or "effects" in kws_lower


def test_extract_keywords_max_cap():
    paraphrase = " ".join(f"word{i:02d}" for i in range(30))
    # "wordNN" tokens are long enough for the length filter...
    kws = paraphrase_match.extract_keywords(paraphrase, max_keywords=8)
    # ...but word00~word29 contain digits, so the \b[A-Za-z][A-Za-z\-]{3,}\b
    # regex drops them. Reinforce with letter-only words:
    paraphrase2 = " ".join([
        "cognitive", "attention", "processing", "self", "report", "measures",
        "validation", "instrument", "psychology", "extraneous", "intrinsic",
    ])
    kws2 = paraphrase_match.extract_keywords(paraphrase2, max_keywords=5)
    assert len(kws2) <= 5
    assert "cognitive" in [k.lower() for k in kws2]


def test_find_keyword_window_locates_match():
    text = (
        "A long body. " * 100 +
        "This special section talks about cognitive load and self-report. " +
        "More filler. " * 100
    )
    keywords = ["cognitive", "self-report", "load"]
    window = paraphrase_match.find_keyword_window(text, keywords, window_size=400)
    assert window is not None
    assert "cognitive" in window.lower()


def test_find_keyword_window_short_text_passthrough():
    text = "Short text containing cognitive load discussion."
    window = paraphrase_match.find_keyword_window(text, ["cognitive"], window_size=1000)
    assert window == text


def test_find_keyword_window_no_match_returns_none():
    text = "totally unrelated body content " * 50
    window = paraphrase_match.find_keyword_window(text, ["quantum", "relativity"], window_size=400)
    assert window is None


def test_extract_quote_from_pdf_md_surrogate_skips_frontmatter(tmp_path):
    md = tmp_path / "klepsch.md"
    md.write_text(FIXTURE_MD_SURROGATE, encoding="utf-8")
    keywords = ["self-report", "cognitive", "validity"]
    quote = paraphrase_match.extract_quote_from_pdf(md, keywords=keywords)
    # frontmatter YAML must not leak into the quote
    assert "citekey:" not in quote
    assert "doi:" not in quote
    # body text must be present
    assert "self-report" in quote.lower() or "cognitive load" in quote.lower()


def test_extract_quote_from_pdf_md_no_keywords_fallback(tmp_path):
    md = tmp_path / "klepsch.md"
    md.write_text(FIXTURE_MD_SURROGATE, encoding="utf-8")
    quote = paraphrase_match.extract_quote_from_pdf(md, keywords=None)
    # the fallback also uses the first ~3000 chars of the frontmatter-stripped body
    assert "citekey:" not in quote
    assert "Abstract" in quote


def test_dispatch_codex_handles_missing_cli_gracefully(monkeypatch):
    monkeypatch.setattr(paraphrase_match.shutil, "which", lambda _: None)
    score, reason = paraphrase_match.dispatch_paraphrase_check("a", "b")
    assert score == -1.0
    assert "not available" in reason


# ─── Purpose-specific thresholds + background-cite skip ────────────────


def test_threshold_for_finding_cite_strict():
    assert paraphrase_match.threshold_for("finding-cite") == 0.85


def test_threshold_for_method_and_theory_loose():
    assert paraphrase_match.threshold_for("method-cite") == 0.40
    assert paraphrase_match.threshold_for("theory-cite") == 0.40


def test_threshold_for_background_skip():
    assert paraphrase_match.threshold_for("background-cite") is None


def test_match_paraphrases_skips_background_cite_codex_call(monkeypatch, tmp_path):
    """background-cite makes no LLM call -> MANUAL with threshold_applied=None."""
    from paper_verifier.doi_audit import InTextCitation, ReferenceEntry
    from paper_verifier import pdf_attach

    # any LLM dispatch would prove the skip policy broken
    called = {"count": 0}

    def fake_dispatch(*args, **kwargs):
        called["count"] += 1
        return 0.95, "should not be called"

    monkeypatch.setattr(paraphrase_match, "dispatch_paraphrase_check", fake_dispatch)

    # fixture pdf
    pdf_file = tmp_path / "klepsch.md"
    pdf_file.write_text("# Body\nsome body text", encoding="utf-8")

    cite = InTextCitation(
        id="cite-0001", manuscript_id="mss-001", section="intro", line=1,
        raw_text="(Klepsch et al., 2017)", citation_type="parenthetical",
        first_author_last="Klepsch", year=2017, ref_id="Klepsch2017",
        context_paraphrase="DHAs are widely used (Klepsch et al., 2017; Foo et al., 2020).",
        citation_purpose="background-cite",
    )
    pdf = pdf_attach.SourcePDF(
        id="pdf-0001", ref_id="Klepsch2017", pdf_path=str(pdf_file), source_kind="library",
    )
    matches = paraphrase_match.match_paraphrases([cite], [pdf], [], augment_with_llm=False)
    assert len(matches) == 1
    assert matches[0].status == "MANUAL"
    assert matches[0].citation_purpose == "background-cite"
    assert matches[0].threshold_applied is None
    assert called["count"] == 0  # no LLM call was made


def test_match_paraphrases_method_cite_uses_loose_threshold(monkeypatch, tmp_path):
    """method-cite applies the loose 0.40 threshold, so a 0.5 score passes."""
    from paper_verifier.doi_audit import InTextCitation
    from paper_verifier import pdf_attach

    monkeypatch.setattr(paraphrase_match, "dispatch_paraphrase_check",
                        lambda *a, **kw: (0.5, ""))

    pdf_file = tmp_path / "klepsch.md"
    pdf_file.write_text("# Body", encoding="utf-8")

    cite = InTextCitation(
        id="cite-0001", manuscript_id="mss-001", section="methods", line=1,
        raw_text="(Klepsch et al., 2017)", citation_type="parenthetical",
        first_author_last="Klepsch", year=2017, ref_id="Klepsch2017",
        context_paraphrase="Cognitive load measured with Klepsch et al.'s (2017) instrument.",
        citation_purpose="method-cite",
    )
    pdf = pdf_attach.SourcePDF(
        id="pdf-0001", ref_id="Klepsch2017", pdf_path=str(pdf_file), source_kind="library",
    )
    matches = paraphrase_match.match_paraphrases([cite], [pdf], [], augment_with_llm=False)
    assert matches[0].status == "PASS"  # 0.5 >= 0.40
    assert matches[0].threshold_applied == 0.40


def test_match_paraphrases_finding_cite_strict_threshold(monkeypatch, tmp_path):
    """finding-cite applies the strict 0.85 threshold, so a 0.5 score fails."""
    from paper_verifier.doi_audit import InTextCitation
    from paper_verifier import pdf_attach

    monkeypatch.setattr(paraphrase_match, "dispatch_paraphrase_check",
                        lambda *a, **kw: (0.5, ""))

    pdf_file = tmp_path / "klepsch.md"
    pdf_file.write_text("# Body", encoding="utf-8")

    cite = InTextCitation(
        id="cite-0001", manuscript_id="mss-001", section="results", line=1,
        raw_text="(Klepsch et al., 2017)", citation_type="parenthetical",
        first_author_last="Klepsch", year=2017, ref_id="Klepsch2017",
        context_paraphrase="Reduced dwell time was observed (Klepsch et al., 2017).",
        citation_purpose="finding-cite",
    )
    pdf = pdf_attach.SourcePDF(
        id="pdf-0001", ref_id="Klepsch2017", pdf_path=str(pdf_file), source_kind="library",
    )
    matches = paraphrase_match.match_paraphrases([cite], [pdf], [], augment_with_llm=False)
    assert matches[0].status == "FAIL"
    assert matches[0].threshold_applied == 0.85


def test_dispatch_runs_configured_provider_argv_verbatim(monkeypatch):
    """The configured [llm] argv (incl. any model pin) must run exactly as declared."""
    from paper_verifier import config

    custom = ("mycli", "--flag", 'model="pinned-model"', "-")
    config.apply(config.VerifierConfig(llm_provider="custom", llm_argv=custom))
    monkeypatch.setattr(paraphrase_match.shutil, "which", lambda _: "/usr/local/bin/mycli")
    captured_args = {}

    class _Result:
        stdout = '{"score": 0.91, "reason": "ok"}'

    def fake_run(args, **kwargs):
        captured_args["args"] = args
        return _Result()

    monkeypatch.setattr(paraphrase_match.subprocess, "run", fake_run)
    score, raw = paraphrase_match.dispatch_paraphrase_check("a", "b")
    assert score == 0.91
    assert captured_args["args"] == list(custom)


# ─── LLM-augmented citation classifier ─────────────────────────────────


def test_classify_augmented_skips_llm_for_background_cite():
    """A heuristic background-cite verdict skips the LLM (spot-checks showed the heuristic is reliable for this class)."""
    purpose, used = paraphrase_match.classify_citation_purpose_augmented(
        paraphrase="AI digital humans have been studied in education (Smith, 2023).",
        citation_type="parenthetical",
        raw_text="(Smith, 2023)",
        heuristic_purpose="background-cite",
        llm_callable=lambda *a, **kw: ("finding-cite", "should-not-be-called"),
    )
    assert purpose == "background-cite"
    assert used == "heuristic"


def test_classify_augmented_skips_llm_for_theory_cite():
    """A heuristic theory-cite verdict skips the LLM (abbreviation-prefix detection is reliable)."""
    purpose, used = paraphrase_match.classify_citation_purpose_augmented(
        paraphrase="Cognitive Theory of Multimedia Learning (CTML; Mayer, 2009).",
        citation_type="parenthetical",
        raw_text="(CTML; Mayer, 2009)",
        heuristic_purpose="theory-cite",
        llm_callable=lambda *a, **kw: ("background-cite", "should-not-be-called"),
    )
    assert purpose == "theory-cite"
    assert used == "heuristic"


def test_classify_augmented_calls_llm_for_method_cite():
    """A heuristic method-cite verdict is delegated to the LLM — the heuristic over-classifies this class."""
    called = []

    def fake_llm(paraphrase, raw, ctype):
        called.append((paraphrase, raw, ctype))
        return ("background-cite", '{"purpose":"background-cite","reason":"general"}')

    purpose, used = paraphrase_match.classify_citation_purpose_augmented(
        paraphrase="Digital human avatars have been increasingly used in online learning (Pataranutaporn, 2022).",
        citation_type="parenthetical",
        raw_text="(Pataranutaporn et al., 2022)",
        heuristic_purpose="method-cite",
        llm_callable=fake_llm,
    )
    # the LLM demotes it to background, correcting the over-classification
    assert purpose == "background-cite"
    assert used == "llm"
    assert len(called) == 1


def test_classify_augmented_calls_llm_for_finding_cite():
    """A heuristic finding-cite verdict is also delegated to the LLM (it must tell the manuscript's own study design apart from a cited paper's finding)."""
    def fake_llm(*a, **kw):
        return ("background-cite", '{"purpose":"background-cite"}')

    purpose, used = paraphrase_match.classify_citation_purpose_augmented(
        paraphrase="The present exploratory study addresses gaps by comparing HQ and LQ avatars (Klepsch, 2017).",
        citation_type="parenthetical",
        raw_text="(Klepsch et al., 2017)",
        heuristic_purpose="finding-cite",
        llm_callable=fake_llm,
    )
    assert purpose == "background-cite"
    assert used == "llm"


def test_classify_augmented_cache_avoids_repeat_calls():
    """A second call with the same (paraphrase, raw) pair is a cache hit — saves LLM cost."""
    call_count = {"n": 0}

    def counting_llm(p, r, ct):
        call_count["n"] += 1
        return ("method-cite", "raw")

    cache: dict = {}
    p1, u1 = paraphrase_match.classify_citation_purpose_augmented(
        paraphrase="used the lme4 package for analysis (Bates, 2015).",
        citation_type="parenthetical",
        raw_text="(Bates et al., 2015)",
        heuristic_purpose="method-cite",
        llm_callable=counting_llm,
        cache=cache,
    )
    p2, u2 = paraphrase_match.classify_citation_purpose_augmented(
        paraphrase="used the lme4 package for analysis (Bates, 2015).",
        citation_type="parenthetical",
        raw_text="(Bates et al., 2015)",
        heuristic_purpose="method-cite",
        llm_callable=counting_llm,
        cache=cache,
    )
    assert call_count["n"] == 1  # second call hits the cache
    assert p1 == p2 == "method-cite"
    assert u1 == "llm"
    assert u2 == "llm-cached"


def test_classify_augmented_llm_invalid_response_fallback():
    """An invalid LLM purpose keeps the heuristic verdict and marks classifier_used='llm-fallback'."""
    def bad_llm(*a, **kw):
        return ("unknown-purpose", "garbled response")

    purpose, used = paraphrase_match.classify_citation_purpose_augmented(
        paraphrase="some paraphrase",
        citation_type="parenthetical",
        raw_text="(X, 2024)",
        heuristic_purpose="method-cite",
        llm_callable=bad_llm,
    )
    # heuristic verdict preserved (defensive fallback)
    assert purpose == "method-cite"
    assert used == "llm-fallback"


def test_dispatch_classify_citation_handles_missing_cli(monkeypatch):
    """A missing codex CLI returns the (_CLASSIFY_UNKNOWN sentinel, reason) fail-safe.

    It used to return "background-cite" — a fail-open that demoted heuristic
    finding/method verdicts to background and skipped their evaluation. The
    sentinel is not a valid purpose, so the heuristic verdict is preserved.
    """
    monkeypatch.setattr(paraphrase_match.shutil, "which", lambda _: None)
    purpose, raw = paraphrase_match.dispatch_classify_citation(
        "p", "(Author, 2024)", "parenthetical",
    )
    assert purpose == paraphrase_match._CLASSIFY_UNKNOWN
    assert purpose not in paraphrase_match._VALID_PURPOSES
    assert "not available" in raw


def test_dispatch_classify_citation_parses_purpose_field(monkeypatch):
    """Parses {"purpose":"finding-cite", ...} from provider stdout."""
    monkeypatch.setattr(paraphrase_match.shutil, "which", lambda _: "/usr/local/bin/codex")

    class _R:
        stdout = '{"purpose":"finding-cite","reason":"empirical finding cited"}'

    monkeypatch.setattr(paraphrase_match.subprocess, "run", lambda *a, **kw: _R())
    purpose, raw = paraphrase_match.dispatch_classify_citation(
        "Klepsch (2017) showed X correlates with Y.",
        "(Klepsch et al., 2017)",
        "narrative",
    )
    assert purpose == "finding-cite"


def test_dispatch_classify_uses_default_codex_preset(monkeypatch):
    """Default provider (codex preset) runs its argv verbatim, prompt via stdin."""
    monkeypatch.setattr(paraphrase_match.shutil, "which", lambda _: "/usr/local/bin/codex")
    captured = {}

    class _R:
        stdout = '{"purpose":"background-cite"}'

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["input"] = kwargs.get("input")
        return _R()

    monkeypatch.setattr(paraphrase_match.subprocess, "run", fake_run)
    paraphrase_match.dispatch_classify_citation("p", "raw", "parenthetical")
    from paper_verifier import llm
    assert captured["args"] == list(llm.PRESETS["codex"].argv)
    assert captured["args"][-1] == "-"          # prompt goes to stdin
    assert "Classify" in captured["input"]


def test_match_paraphrases_augment_with_llm_demotes_method_to_background(monkeypatch, tmp_path):
    """End-to-end: heuristic method-cite, demoted to background by the LLM, skips the paraphrase call -> MANUAL."""
    from paper_verifier.doi_audit import InTextCitation
    from paper_verifier import pdf_attach

    # Mock LLM classifier: always demotes to background
    monkeypatch.setattr(
        paraphrase_match, "dispatch_classify_citation",
        lambda p, r, ct: ("background-cite", '{"purpose":"background-cite"}'),
    )
    # Mock paraphrase check: counts calls (there must be none)
    paraphrase_called = {"n": 0}
    def counting_para(*a, **kw):
        paraphrase_called["n"] += 1
        return (0.9, "")
    monkeypatch.setattr(paraphrase_match, "dispatch_paraphrase_check", counting_para)

    pdf_file = tmp_path / "x.md"
    pdf_file.write_text("# Body", encoding="utf-8")

    cite = InTextCitation(
        id="cite-0001", manuscript_id="mss-001", section="intro", line=1,
        raw_text="(Pataranutaporn et al., 2022)", citation_type="parenthetical",
        first_author_last="Pataranutaporn", year=2022, ref_id="Pataranutaporn2022",
        context_paraphrase="Digital human avatars have been increasingly used in online learning.",
        citation_purpose="method-cite",  # heuristic verdict (an over-classification)
    )
    pdf = pdf_attach.SourcePDF(
        id="pdf-0001", ref_id="Pataranutaporn2022", pdf_path=str(pdf_file), source_kind="library",
    )

    matches = paraphrase_match.match_paraphrases(
        [cite], [pdf], [], augment_with_llm=True,
    )
    assert len(matches) == 1
    # demoted to background -> threshold None -> MANUAL, and no paraphrase call
    assert matches[0].citation_purpose == "background-cite"
    assert matches[0].status == "MANUAL"
    assert matches[0].threshold_applied is None
    assert paraphrase_called["n"] == 0  # the paraphrase check itself is skipped
