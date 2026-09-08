"""CLI completion gates: incomplete work must not produce a successful run."""
from __future__ import annotations

import pytest

from paper_verifier import paraphrase_match, verify
from paper_verifier._lib import jsonl_io


@pytest.fixture
def phase2_run(tmp_path):
    manuscript = tmp_path / "body.md"
    manuscript.write_text("Prior work (Kim, 2024) supports this finding.", encoding="utf-8")
    refs = tmp_path / "references.md"
    refs.write_text(
        "Kim, J. (2024). A study of things. *Journal of Stuff*, 1(1), 1-10.\n"
        "https://doi.org/10.1000/example.2024.001\n", encoding="utf-8",
    )
    reports = tmp_path / "reports"
    return ["--manuscript", str(manuscript), "--references", str(refs),
            "--phase", "2", "--reports-dir", str(reports)], reports


@pytest.mark.parametrize("status", ["INSUFFICIENT", None, "unexpected", "PENDING", "ERROR"])
def test_unknown_phase2_status_fails(monkeypatch, phase2_run, status):
    argv, reports = phase2_run
    match = paraphrase_match.ParaphraseMatch(
        id="para-1", citation_id="cite-1", ref_id="Kim2024", pdf_path=None,
        paraphrase_text="claim", extracted_quote="quote", score=1.0, status=status,
    )
    monkeypatch.setattr(paraphrase_match, "match_paraphrases", lambda *a: [match])
    assert verify.main(argv) == 1
    results = list(jsonl_io.read_all(reports / "verifications.jsonl"))
    result = next(v for v in results if v["target_type"] == "paraphrase-match")
    assert result["status"] == "FAIL"
    assert "incomplete/unknown" in result["evidence"]


def test_phase2_execution_error_fails(monkeypatch, phase2_run, capsys):
    def failed(*args):
        raise RuntimeError("provider unavailable")

    argv, reports = phase2_run
    monkeypatch.setattr(paraphrase_match, "match_paraphrases", failed)
    assert verify.main(argv) == 1
    assert "Phase 2 failed: provider unavailable" in capsys.readouterr().err
    results = list(jsonl_io.read_all(reports / "verifications.jsonl"))
    assert any(v["verifier"] == "phase-2-gate" and v["status"] == "FAIL" for v in results)


@pytest.mark.parametrize("flag", ["--references", "--stats", "--summary-stats", "--config", "--manuscript"])
def test_missing_explicit_input_is_usage_error(tmp_path, capsys, flag):
    manuscript = tmp_path / "body.md"
    manuscript.write_text("Plain prose.", encoding="utf-8")
    missing = tmp_path / "missing.md"
    with pytest.raises(SystemExit) as exc:
        verify.main(["--manuscript", str(manuscript), flag, str(missing),
                     "--reports-dir", str(tmp_path / "reports")])
    assert exc.value.code == 2
    assert str(missing) in capsys.readouterr().err
    assert not (tmp_path / "reports").exists()


@pytest.mark.parametrize("field", ["references", "stats", "summary_stats"])
def test_missing_configured_input_is_usage_error(tmp_path, capsys, field):
    (tmp_path / "body.md").write_text("Plain prose.", encoding="utf-8")
    cfg = tmp_path / "paper.toml"
    cfg.write_text(f'[project]\nmanuscripts = ["body.md"]\n{field} = "missing.md"\n', encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        verify.main(["--config", str(cfg), "--reports-dir", str(tmp_path / "reports")])
    assert exc.value.code == 2
    assert "missing.md" in capsys.readouterr().err


def test_unmatched_glob_rejected_even_with_valid_manuscript(tmp_path, capsys):
    manuscript = tmp_path / "body.md"
    manuscript.write_text("Plain prose.", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        verify.main(["--manuscript", str(manuscript), "--manuscript", str(tmp_path / "missing*.md")])
    assert exc.value.code == 2
    assert "matched no files" in capsys.readouterr().err


@pytest.mark.parametrize(("flag", "reason"), [
    ("--references", "0 references parsed"),
    ("--stats", "0 numerical claims extracted"),
    ("--summary-stats", "0 numerical claims extracted"),
])
def test_requested_phase1_audit_requires_coverage(tmp_path, capsys, flag, reason):
    manuscript = tmp_path / "body.md"
    manuscript.write_text("Plain prose.", encoding="utf-8")
    source = tmp_path / "input.md"
    source.write_text("No parseable rows.", encoding="utf-8")
    reports = tmp_path / "reports"
    assert verify.main(["--manuscript", str(manuscript), flag, str(source),
                        "--reports-dir", str(reports)]) == 1
    assert reason in capsys.readouterr().err
    results = list(jsonl_io.read_all(reports / "verifications.jsonl"))
    assert any(v["verifier"] == "coverage-gate" and v["status"] == "FAIL" for v in results)


@pytest.mark.parametrize("unavailable", ["references", "citations", "matches", "scores"])
def test_requested_phase2_requires_completed_check(monkeypatch, phase2_run, capsys, unavailable):
    argv, reports = phase2_run
    matches = []
    if unavailable == "references":
        index = argv.index("--references")
        del argv[index:index + 2]
    elif unavailable == "citations":
        from pathlib import Path
        Path(argv[argv.index("--manuscript") + 1]).write_text("Plain prose.", encoding="utf-8")
    elif unavailable == "scores":
        matches = [paraphrase_match.ParaphraseMatch(
            id="para-1", citation_id="cite-1", ref_id="Kim2024", pdf_path=None,
            paraphrase_text="claim", extracted_quote="", score=None, status="MANUAL",
        )]
    monkeypatch.setattr(paraphrase_match, "match_paraphrases", lambda *a: matches)
    assert verify.main(argv) == 1
    assert "Phase 2 requested but 0 semantic checks completed" in capsys.readouterr().err
    results = list(jsonl_io.read_all(reports / "verifications.jsonl"))
    assert any(v["target_id"] == "phase-2" and v["status"] == "FAIL" for v in results)


def test_completed_phase2_can_succeed(monkeypatch, phase2_run):
    argv, _ = phase2_run
    match = paraphrase_match.ParaphraseMatch(
        id="para-1", citation_id="cite-1", ref_id="Kim2024", pdf_path=None,
        paraphrase_text="claim", extracted_quote="quote", score=0.9, status="PASS",
    )
    monkeypatch.setattr(paraphrase_match, "match_paraphrases", lambda *a: [match])
    assert verify.main(argv) == 0


@pytest.mark.parametrize("score", [None, "0.9", float("nan"), float("inf"), 1.5, True])
def test_phase2_pass_without_valid_score_is_rejected(monkeypatch, phase2_run, score):
    argv, reports = phase2_run
    match = paraphrase_match.ParaphraseMatch(
        id="para-1", citation_id="cite-1", ref_id="Kim2024", pdf_path=None,
        paraphrase_text="claim", extracted_quote="quote", score=score, status="PASS",
    )
    monkeypatch.setattr(paraphrase_match, "match_paraphrases", lambda *a: [match])
    assert verify.main(argv) == 1
    results = list(jsonl_io.read_all(reports / "verifications.jsonl"))
    result = next(v for v in results if v["target_type"] == "paraphrase-match")
    assert result["status"] == "FAIL"
    assert "invalid/missing semantic score" in result["evidence"]


@pytest.mark.parametrize(("lines", "status", "rc"), [
    (86, "FAIL", 1), (85, "WARN", 0), (70, "PASS", 0), (None, "FAIL", 1),
])
def test_summary_page_status_controls_exit_code(tmp_path, capsys, lines, status, rc):
    manuscript = tmp_path / "body.md"
    manuscript.write_text("Plain prose.", encoding="utf-8")
    reports = tmp_path / "reports"
    reports.mkdir()
    if lines is not None:
        (reports / "summary.md").write_text("line\n" * lines, encoding="utf-8")
    assert verify.main(["--manuscript", str(manuscript), "--reports-dir", str(reports),
                        "--check-summary-length"]) == rc
    assert f"status: {status}" in capsys.readouterr().out
    assert list(jsonl_io.read_all(reports / "verifications.jsonl")) == []
