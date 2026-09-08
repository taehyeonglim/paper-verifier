"""Ground-truth loading + claim ↔ ground-truth matching unit tests.

A statistics-verification fixture written to a temp file exercises parsing
accuracy.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from paper_verifier import recompute_stats, verify


# Section-1 row keeps the Korean label "조작점검" on purpose: it regression-tests
# the multilingual dv_aliases mapping (the same DV appears as "Manipulation
# Check" in sections 2-3 and must merge into one GroundTruthRow).
FIXTURE_VERIFICATION_MD = """---
type: statistics-verification
---

# Statistics cross-verification (N=38)

## 1. p-value verification (R vs scipy)

| DV | F | df1 | df2 | R p | scipy p | match |
|----|---|-----|-----|-----|---------|------|
| 조작점검 | 7.634 | 1 | 36 | .008965 | .008966 | ✓ |
| ECL | 0.493 | 1 | 36 | .487223 | .487107 | ✓ |
| ET Face Dwell | 10.255 | 1 | 35 | .002901 | .002901 | ✓ |

## 2. beta, SE, 95% CI verification

| DV | β | SE | 95% CI (Wald) | CI consistency |
|----|---|-----|--------------|----------|
| Manipulation Check | +0.574 | 0.208 | [0.167, 0.982] | ✓ |
| ET Face Dwell | -4.161 | 1.300 | [-6.709, -1.614] | ✓ |

## 3. Wilcoxon + effect sizes

| DV | V | p | r (rank-biserial) | r 95% CI | dz (Cohen) | dz 95% CI | n |
|----|---|---|---|---|---|---|---|
| Manipulation Check | 455.0 | .007223 | +0.529 | [0.221, 0.742] | 0.440 | [0.104, 0.770] | 38 |
| ET Face Dwell | 188.0 | .008305 | -0.493 | [-0.728, -0.153] | -0.468 | [-0.800, -0.130] | 38 |
"""


def test_load_ground_truth_parses_three_sections(tmp_path):
    md = tmp_path / "stat.md"
    md.write_text(FIXTURE_VERIFICATION_MD, encoding="utf-8")
    truth = recompute_stats.load_ground_truth(md)
    assert "manipulation_check" in truth
    assert "ECL" in truth
    assert "ET_face_dwell" in truth

    mc = truth["manipulation_check"]
    assert abs(mc.F - 7.634) < 1e-6
    assert mc.df1 == 1 and mc.df2 == 36
    assert abs(mc.p_R - 0.008965) < 1e-7
    assert abs(mc.beta - 0.574) < 1e-6
    assert abs(mc.SE - 0.208) < 1e-6
    assert abs(mc.CI_low - 0.167) < 1e-6
    assert abs(mc.CI_high - 0.982) < 1e-6
    assert abs(mc.V - 455.0) < 1e-6
    assert abs(mc.dz - 0.440) < 1e-6
    assert mc.parity == "✓"


def test_verify_F_stat_passes(tmp_path):
    md = tmp_path / "stat.md"
    md.write_text(FIXTURE_VERIFICATION_MD, encoding="utf-8")
    truth = recompute_stats.load_ground_truth(md)

    claim = {
        "id": "claim-0001",
        "claim_type": "F_stat",
        "parsed_value": {"df1": 1, "df2": 36, "F": 7.63},
        "raw_text": "*F*(1, 36) = 7.63",
        "context_snippet": "The manipulation check confirmed the intended direction, F(1, 36) = 7.63",
    }
    vr = recompute_stats.verify_claim(claim, truth, idx=1)
    assert vr.status == "PASS"
    assert vr.matched_dv == "manipulation_check"


def test_verify_F_stat_fails_with_wrong_value(tmp_path):
    md = tmp_path / "stat.md"
    md.write_text(FIXTURE_VERIFICATION_MD, encoding="utf-8")
    truth = recompute_stats.load_ground_truth(md)

    claim = {
        "id": "claim-0002",
        "claim_type": "F_stat",
        "parsed_value": {"df1": 1, "df2": 36, "F": 6.50},  # wrong by 1.13
        "raw_text": "*F*(1, 36) = 6.50",
        "context_snippet": "manipulation check uncanniness F(1, 36) = 6.50",
    }
    vr = recompute_stats.verify_claim(claim, truth, idx=2)
    assert vr.status == "FAIL"
    assert vr.matched_dv == "manipulation_check"


def test_verify_beta_with_typographic_minus(tmp_path):
    md = tmp_path / "stat.md"
    md.write_text(FIXTURE_VERIFICATION_MD, encoding="utf-8")
    truth = recompute_stats.load_ground_truth(md)

    claim = {
        "id": "claim-0003",
        "claim_type": "beta",
        "parsed_value": {"beta": -4.16},
        "raw_text": "β = −4.16",
        "context_snippet": "Dwell time on the avatar's face β = −4.16",
    }
    vr = recompute_stats.verify_claim(claim, truth, idx=3)
    assert vr.status == "PASS"
    assert vr.matched_dv == "ET_face_dwell"


def test_verify_dv_inference_failure_returns_manual(tmp_path):
    md = tmp_path / "stat.md"
    md.write_text(FIXTURE_VERIFICATION_MD, encoding="utf-8")
    truth = recompute_stats.load_ground_truth(md)

    claim = {
        "id": "claim-0004",
        "claim_type": "F_stat",
        "parsed_value": {"df1": 1, "df2": 36, "F": 7.63},
        "raw_text": "F(1, 36) = 7.63",
        "context_snippet": "Some unrelated context without DV keyword",
    }
    vr = recompute_stats.verify_claim(claim, truth, idx=4)
    assert vr.status == "MANUAL"
    assert vr.matched_dv is None


def test_verify_CI_pair_passes(tmp_path):
    md = tmp_path / "stat.md"
    md.write_text(FIXTURE_VERIFICATION_MD, encoding="utf-8")
    truth = recompute_stats.load_ground_truth(md)

    claim = {
        "id": "claim-0005",
        "claim_type": "CI_pair",
        "parsed_value": {"ci_low": 0.17, "ci_high": 0.98},
        "raw_text": "95% CI [0.17, 0.98]",
        "context_snippet": "manipulation check uncanniness 95% CI [0.17, 0.98]",
    }
    vr = recompute_stats.verify_claim(claim, truth, idx=5)
    assert vr.status == "PASS"
    assert vr.matched_dv == "manipulation_check"


def test_verify_unknown_claim_type_returns_manual(tmp_path):
    md = tmp_path / "stat.md"
    md.write_text(FIXTURE_VERIFICATION_MD, encoding="utf-8")
    truth = recompute_stats.load_ground_truth(md)

    claim = {
        "id": "claim-0006",
        "claim_type": "M_mean",
        "parsed_value": {"M": 4.52},
        "raw_text": "*M* = 4.52",
        "context_snippet": "manipulation check uncanniness M = 4.52",
    }
    vr = recompute_stats.verify_claim(claim, truth, idx=6)
    assert vr.status == "MANUAL"


@pytest.mark.parametrize("row", [
    "| Manipulation Check | 7.634 | 1 | 36 | .008965 | .008966 | ✗ |",
    "| Manipulation Check | 7.634 | 1 | 36 | .008965 | .008966 | |",
    "| Manipulation Check | 7.634 | 1 | 36 | .008965 | — | ✓ |",
    "| Manipulation Check | 7.634 | 1 | | .008965 | .008966 | ✓ |",
    "| Manipulation Check | 7.634 | 1 | 36 | .008965 |",
    "| Manipulation Check | 7.634 | 1 | 36 | .008965 | NaN | ✓ |",
])
def test_unvalidated_ground_truth_row_never_passes(tmp_path, row):
    md = tmp_path / "stats.md"
    md.write_text(
        "## 1. p-value verification\n\n"
        "| DV | F | df1 | df2 | R p | scipy p | match |\n"
        "|----|---|-----|-----|-----|---------|------|\n" + row + "\n", encoding="utf-8",
    )
    truth = recompute_stats.load_ground_truth(md)
    assert truth["manipulation_check"].validation_errors
    assert verify.has_table_ground_truth(truth) is False
    result = recompute_stats.verify_claim({
        "id": "claim-1", "claim_type": "F_stat",
        "parsed_value": {"df1": 1, "df2": 36, "F": 7.63},
        "raw_text": "F(1, 36) = 7.63", "context_snippet": "manipulation check F(1, 36) = 7.63",
    }, truth, 1)
    assert result.status == "WARN"
    assert "Ground truth invalid" in result.evidence
    assert "not verified" in result.evidence


@pytest.mark.parametrize(("original", "replacement", "table"), [
    ("| +0.574 | 0.208 |", "| +0.574 | — |", "beta table"),
    ("[0.167, 0.982] | ✓", "[0.167, 0.982] | ✗", "beta table"),
    ("455.0 | .007223", "455.0 | —", "Wilcoxon table"),
])
def test_invalid_supplementary_table_row_cannot_supply_a_pass(tmp_path, original, replacement, table):
    md = tmp_path / "stats.md"
    md.write_text(FIXTURE_VERIFICATION_MD.replace(original, replacement), encoding="utf-8")
    truth = recompute_stats.load_ground_truth(md)
    result = recompute_stats.verify_claim({
        "id": "claim-1", "claim_type": "F_stat", "parsed_value": {"F": 7.63},
        "raw_text": "F = 7.63", "context_snippet": "manipulation check F = 7.63",
    }, truth, 1)
    assert result.status == "WARN"
    assert table in result.evidence
