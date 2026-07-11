"""Unit tests for the summary.md one-page length check."""
from __future__ import annotations

from pathlib import Path

from paper_verifier._lib.summary_page_check import (
    check_summary_page_count, PageCheckResult,
)


def _write_summary(tmp_path: Path, n_lines: int) -> Path:
    p = tmp_path / "summary.md"
    p.write_text("\n".join([f"line {i}" for i in range(n_lines)]), encoding="utf-8")
    return p


def test_pass_when_under_threshold(tmp_path):
    p = _write_summary(tmp_path, 50)
    r = check_summary_page_count(p)
    assert r.status == "PASS"
    assert r.line_count == 50
    assert "fits one page" in r.message


def test_warn_when_in_borderline_zone(tmp_path):
    p = _write_summary(tmp_path, 75)  # threshold_pass=70 < 75 ≤ threshold_warn=85
    r = check_summary_page_count(p)
    assert r.status == "WARN"
    assert "borderline" in r.message


def test_fail_when_over_warn_threshold(tmp_path):
    p = _write_summary(tmp_path, 100)
    r = check_summary_page_count(p)
    assert r.status == "FAIL"
    assert "exceeds one page" in r.message


def test_handles_missing_file(tmp_path):
    p = tmp_path / "nonexistent.md"
    r = check_summary_page_count(p)
    assert r.status == "FAIL"
    assert "not found" in r.message


def test_at_threshold_pass_boundary(tmp_path):
    """Exactly threshold_pass=70 lines is PASS (≤ is inclusive)."""
    p = _write_summary(tmp_path, 70)
    r = check_summary_page_count(p)
    assert r.status == "PASS"


def test_custom_thresholds(tmp_path):
    """Thresholds can be overridden per call."""
    p = _write_summary(tmp_path, 50)
    r = check_summary_page_count(p, threshold_pass=40, threshold_warn=60)
    assert r.status == "WARN"  # 50 > 40 (pass) but ≤ 60 (warn)
    assert r.threshold_pass == 40
    assert r.threshold_warn == 60
