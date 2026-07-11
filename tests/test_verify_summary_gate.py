"""Regression tests for write_summary_md (data-derived verdict) and the
table-ground-truth gate.

Background: an early revision of the summary hardcoded "0 numerical errors"
regardless of the actual results — a numerical-claim FAIL could occur while
the attached summary still read as all-clear (a reporting variant of
fail-open). These tests pin the verdict line to the computed FAIL breakdown.
"""
from __future__ import annotations

from paper_verifier.verify import write_summary_md, has_table_ground_truth
from paper_verifier.recompute_stats import VerificationResult, GroundTruthRow


def _vr(vid: str, ttype: str, status: str) -> VerificationResult:
    return VerificationResult(
        id=vid, target_type=ttype, target_id=vid,
        verifier="test", status=status, evidence="x",
    )


def test_summary_reports_numerical_fail_not_hardcoded_zero(tmp_path):
    """One numerical-claim FAIL must be reported as 1, never a hardcoded 0."""
    verifications = [
        _vr("vr-0001", "numerical-claim", "FAIL"),
        _vr("vr-0002", "in-text-citation", "FAIL"),
        _vr("vr-0003", "numerical-claim", "PASS"),
    ]
    write_summary_md(tmp_path, [], [], verifications, {}, "test1234")
    text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "numerical-claim 1, citation/reference 1" in text
    assert "numerical-claim 0" not in text  # no false all-clear


def test_summary_zero_numerical_fail_states_zero_explicitly(tmp_path):
    """Zero numerical FAILs are reported as exactly 0 (citation FAILs separate)."""
    verifications = [
        _vr("vr-0001", "in-text-citation", "FAIL"),
        _vr("vr-0002", "reference-entry", "FAIL"),
        _vr("vr-0003", "numerical-claim", "PASS"),
    ]
    write_summary_md(tmp_path, [], [], verifications, {}, "test1234")
    text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "numerical-claim 0, citation/reference 2" in text


def test_summary_counts_other_fail_types(tmp_path):
    """FAILs outside numerical/citation types (e.g. paraphrase) count as 'other'."""
    verifications = [
        _vr("vr-0001", "paraphrase-match", "FAIL"),
        _vr("vr-0002", "ground-truth", "FAIL"),
    ]
    write_summary_md(tmp_path, [], [], verifications, {}, "test1234")
    text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "other 2" in text


# ─── Table-ground-truth gate detection (prevents a vacuous gate) ─────────────
# Background: load_ground_truth seeds reliability (alpha) values independently
# of the statistics file, so primary_truth is never empty. If the gate decided
# on "not primary_truth" it could never fire (a vacuous no-op — this trap was
# hit twice). The gate must decide on table-derived statistical fields.

def test_has_table_gt_false_for_empty(tmp_path):
    """Empty dict → no table ground truth (gate must fire)."""
    assert has_table_ground_truth({}) is False


def test_has_table_gt_false_when_only_alpha_seeded(tmp_path):
    """Rows carrying only seeded alpha values → still no table ground truth.

    This is the discriminating case: with empty statistics tables the truth
    dict is non-empty because alpha is seeded — the gate must fire anyway.
    """
    only_alpha = {
        "learning_A": GroundTruthRow(dv="learning_A", alpha=0.689),
        "learning_B": GroundTruthRow(dv="learning_B", alpha=0.71),
    }
    assert has_table_ground_truth(only_alpha) is False


def test_has_table_gt_true_when_stat_field_present(tmp_path):
    """Any table-derived field (e.g. F) present → table ground truth exists."""
    with_stats = {
        "ECL": GroundTruthRow(dv="ECL", F=7.634, p_R=0.009),
        "learning_A": GroundTruthRow(dv="learning_A", alpha=0.689),
    }
    assert has_table_ground_truth(with_stats) is True
