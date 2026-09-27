"""Robustness regressions — malformed JSONL/claim fail-safes + paraphrase score validation."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from paper_verifier import recompute_stats, paraphrase_match
from paper_verifier._lib import jsonl_io


# ─── Malformed JSONL lines are skipped instead of crashing ────────────────

def test_read_all_skips_malformed_line_without_crash(tmp_path):
    p = tmp_path / "data.jsonl"
    p.write_text(
        '{"a": 1}\n'
        'this is not json\n'          # malformed
        '{"b": 2}\n',
        encoding="utf-8",
    )
    recs = list(jsonl_io.read_all(p))   # would raise here if malformed lines crashed the reader
    assert recs == [{"a": 1}, {"b": 2}]  # valid lines only; the malformed one is skipped


# ─── Claims missing required keys yield WARN instead of KeyError ──────────

def test_verify_claim_malformed_missing_keys_returns_warn():
    vr = recompute_stats.verify_claim({"id": "claim-x"}, {}, idx=1)  # no claim_type / parsed_value
    assert vr.status == "WARN"
    assert "Malformed" in vr.evidence


def test_verify_claim_empty_dict_returns_warn():
    vr = recompute_stats.verify_claim({}, {}, idx=2)
    assert vr.status == "WARN"   # does not crash


# ─── Paraphrase score: returncode + range validation ──────────────────────

class _Result:
    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def _mock_codex(monkeypatch, stdout, returncode=0):
    monkeypatch.setattr(paraphrase_match.shutil, "which", lambda _: "/usr/local/bin/codex")
    monkeypatch.setattr(paraphrase_match.subprocess, "run",
                        lambda *a, **kw: _Result(stdout, returncode))


def test_paraphrase_score_valid(monkeypatch):
    _mock_codex(monkeypatch, '{"score": 0.85, "reason": "close"}')
    score, _ = paraphrase_match.dispatch_paraphrase_check("a", "b")
    assert score == 0.85


def test_paraphrase_score_out_of_range_rejected(monkeypatch):
    """A score of 10 is out of range -> -1.0 sentinel; prevents a false PASS."""
    _mock_codex(monkeypatch, '{"score": 10, "reason": "hallucinated"}')
    score, reason = paraphrase_match.dispatch_paraphrase_check("a", "b")
    assert score == -1.0
    assert "out of range" in reason


def test_paraphrase_score_nonzero_returncode_rejected(monkeypatch):
    """A nonzero exit code is not trusted even if stdout carries a stale score."""
    _mock_codex(monkeypatch, '{"score": 1.0}', returncode=1)
    score, reason = paraphrase_match.dispatch_paraphrase_check("a", "b")
    assert score == -1.0
    assert "rc=1" in reason


def test_paraphrase_score_leading_dot_rejected(monkeypatch):
    """Leading-dot floats (.91) are invalid JSON and must not become scores."""
    _mock_codex(monkeypatch, '{"score": .91}')
    score, _ = paraphrase_match.dispatch_paraphrase_check("a", "b")
    assert score == -1.0


@pytest.mark.parametrize(("response", "expected"), [
    ('{"score": 1e-3}', 0.001),
    ('{"score": 0.85}', 0.85),
    ('Answer:\n```json\n{"score": 0.85}\n```\nDone.', 0.85),
    ('{"score": 0.85, "reason": "braces } {", "details": {"ok": true}} after {"score": 1}', 0.85),
    ('{"score": 0}', 0.0),
    ('{"score": 1}', 1.0),
])
def test_paraphrase_score_json_numbers(monkeypatch, response, expected):
    _mock_codex(monkeypatch, response)
    score, _ = paraphrase_match.dispatch_paraphrase_check("a", "b")
    assert score == expected


@pytest.mark.parametrize("response", [
    '{"score": "high"}', '{"score": "0.85"}', '{"score": 1.5}',
    'score: 0.85', '{"score": NaN}', '{"score": Infinity}',
    '{"score": true}', '{"score": null}', '{}', '{"score": -0.5}',
    '{"score": 0.85', '{"score": 0.85oops}',
])
def test_invalid_paraphrase_json_rejected(monkeypatch, response):
    _mock_codex(monkeypatch, response)
    score, _ = paraphrase_match.dispatch_paraphrase_check("a", "b")
    assert score == -1.0


@pytest.mark.parametrize("response", ['{"score": "high"}', '{"score": 1.5}', 'not JSON', None])
def test_score_parse_failure_produces_failed_match(monkeypatch, tmp_path, response):
    from paper_verifier.doi_audit import InTextCitation
    from paper_verifier.pdf_attach import SourcePDF

    _mock_codex(monkeypatch, response)
    source = tmp_path / "source.md"
    source.write_text("The source reports a specific finding." if response is not None else "", encoding="utf-8")
    if response is None:
        def unexpected_call(*args, **kwargs):
            pytest.fail("An empty source must not be sent to the LLM")
        monkeypatch.setattr(paraphrase_match.subprocess, "run", unexpected_call)
    citation = InTextCitation(
        id="cite-1", manuscript_id="m-1", section="results", line=1,
        raw_text="(Kim, 2024)", citation_type="parenthetical", first_author_last="Kim",
        year=2024, ref_id="Kim2024", context_paraphrase="A specific finding.",
        citation_purpose="finding-cite",
    )
    pdf = SourcePDF(id="pdf-1", ref_id="Kim2024", pdf_path=str(source))
    matches = paraphrase_match.match_paraphrases([citation], [pdf], [], augment_with_llm=False)
    assert len(matches) == 1
    assert matches[0].status == "FAIL"
    assert matches[0].score is None
