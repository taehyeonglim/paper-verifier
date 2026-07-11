"""Regression tests: the paraphrase citation classifier must not fail open.

Background: dispatch_classify_citation used to report every failure mode
(missing codex CLI, parse failure, call failure) as "background-cite".
Since "background-cite" is in _VALID_PURPOSES, the augmented classifier
adopted it as a real verdict instead of falling back — demoting heuristic
finding/method-cite verdicts to background and skipping their paraphrase
evaluation entirely (a fail-open). Failures are now signalled with the
_CLASSIFY_UNKNOWN sentinel so the heuristic verdict is preserved. A genuine
LLM "background-cite" verdict must still be adopted (it corrects heuristic
over-classification); these tests pin that distinction.
"""
from __future__ import annotations

import sys
from pathlib import Path


from paper_verifier import paraphrase_match


def test_dispatch_classify_missing_cli_returns_sentinel(monkeypatch):
    """A missing codex CLI returns a sentinel that is not a valid purpose (blocks the fail-open)."""
    monkeypatch.setattr(paraphrase_match.shutil, "which", lambda _: None)
    purpose, reason = paraphrase_match.dispatch_classify_citation("s", "(A, 2020)")
    assert purpose == paraphrase_match._CLASSIFY_UNKNOWN
    assert purpose not in paraphrase_match._VALID_PURPOSES


def test_classify_augmented_preserves_heuristic_on_llm_failure():
    """An LLM failure (sentinel) preserves the heuristic finding-cite instead of demoting it to background."""
    def failing_llm(*a, **kw):
        return (paraphrase_match._CLASSIFY_UNKNOWN, "codex unavailable")

    purpose, used = paraphrase_match.classify_citation_purpose_augmented(
        paraphrase="Klepsch et al. (2017) showed that X correlates with Y",
        citation_type="parenthetical",
        raw_text="(Klepsch et al., 2017)",
        heuristic_purpose="finding-cite",
        llm_callable=failing_llm,
    )
    assert purpose == "finding-cite"   # preserved — not demoted to background
    assert used == "llm-fallback"


def test_classify_augmented_preserves_method_cite_on_llm_failure():
    """method-cite is preserved the same way (its evaluation must not be skipped)."""
    purpose, used = paraphrase_match.classify_citation_purpose_augmented(
        paraphrase="using the lme4 package (Bates et al., 2015)",
        citation_type="parenthetical",
        raw_text="(Bates et al., 2015)",
        heuristic_purpose="method-cite",
        llm_callable=lambda *a, **kw: (paraphrase_match._CLASSIFY_UNKNOWN, "fail"),
    )
    assert purpose == "method-cite"
    assert used == "llm-fallback"


def test_classify_augmented_still_adopts_genuine_background():
    """A genuine LLM background verdict is still adopted (corrects heuristic over-classification).

    Distinguishing the failure sentinel from a genuine "background-cite" is
    the crux of the fix.
    """
    def genuine_bg_llm(*a, **kw):
        return ("background-cite", '{"purpose":"background-cite","reason":"general"}')

    purpose, used = paraphrase_match.classify_citation_purpose_augmented(
        paraphrase="AI digital humans have been studied in education (Smith, 2023)",
        citation_type="parenthetical",
        raw_text="(Smith, 2023)",
        heuristic_purpose="finding-cite",
        llm_callable=genuine_bg_llm,
    )
    assert purpose == "background-cite"   # a genuine LLM verdict is adopted
    assert used == "llm"
