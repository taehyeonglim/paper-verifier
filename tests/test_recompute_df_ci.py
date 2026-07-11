"""verify_claim correctness regressions — F df validation + digit-aware CI rounding.

- F df: F_stat verification did not check df1/df2, so an F value with the
  wrong df still passed.
- CI: a fixed absolute tolerance (0.01) accepted incorrectly rounded CI
  bounds; each bound must be a legitimate rounding of the raw expected value.
"""
from __future__ import annotations

import sys
from pathlib import Path


from paper_verifier import recompute_stats

# manipulation_check: F=7.634 df(1,36), CI=[0.167, 0.982]
FIXTURE = """---
type: statistics-verification
---

## 1. p-value verification (R vs scipy)

| DV | F | df1 | df2 | R p | scipy p | match |
|----|---|-----|-----|-----|---------|------|
| Manipulation Check | 7.634 | 1 | 36 | .008965 | .008966 | ✓ |

## 2. beta, SE, 95% CI verification

| DV | β | SE | 95% CI (Wald) | CI consistency |
|----|---|-----|--------------|----------|
| Manipulation Check | +0.574 | 0.208 | [0.167, 0.982] | ✓ |
"""


def _truth(tmp_path):
    md = tmp_path / "stat.md"
    md.write_text(FIXTURE, encoding="utf-8")
    return recompute_stats.load_ground_truth(md)


# ─── F df validation ──────────────────────────────────────────────────────

def test_F_wrong_df_fails_even_when_F_value_matches(tmp_path):
    """A correct F value with wrong df (2, 99) FAILs (previously only the F value was checked)."""
    truth = _truth(tmp_path)
    claim = {
        "id": "claim-df-1", "claim_type": "F_stat",
        "parsed_value": {"df1": 2, "df2": 99, "F": 7.63},  # F correct, df wrong
        "raw_text": "*F*(2, 99) = 7.63",
        "context_snippet": "manipulation check uncanniness F(2, 99) = 7.63",
    }
    vr = recompute_stats.verify_claim(claim, truth, idx=1)
    assert vr.status == "FAIL"
    assert "df mismatch" in vr.evidence


def test_F_correct_df_still_passes(tmp_path):
    """The exact df (1, 36) still passes (no false positives)."""
    truth = _truth(tmp_path)
    claim = {
        "id": "claim-df-2", "claim_type": "F_stat",
        "parsed_value": {"df1": 1, "df2": 36, "F": 7.63},
        "raw_text": "*F*(1, 36) = 7.63",
        "context_snippet": "manipulation check uncanniness F(1, 36) = 7.63",
    }
    vr = recompute_stats.verify_claim(claim, truth, idx=2)
    assert vr.status == "PASS"


def test_F_missing_df_does_not_false_fail(tmp_path):
    """A claim without df skips df validation instead of false-failing."""
    truth = _truth(tmp_path)
    claim = {
        "id": "claim-df-3", "claim_type": "F_stat",
        "parsed_value": {"F": 7.63},  # no df
        "raw_text": "F = 7.63",
        "context_snippet": "manipulation check uncanniness F = 7.63",
    }
    vr = recompute_stats.verify_claim(claim, truth, idx=3)
    assert vr.status == "PASS"


# ─── Digit-aware CI rounding ──────────────────────────────────────────────

def test_CI_wrong_rounding_fails(tmp_path):
    """[0.16, 0.98] differs from the correctly rounded [0.17, 0.98] -> FAIL (the old 0.01 tolerance passed it)."""
    truth = _truth(tmp_path)
    claim = {
        "id": "claim-ci-1", "claim_type": "CI_pair",
        "parsed_value": {"ci_low": 0.16, "ci_high": 0.98},
        "raw_text": "95% CI [0.16, 0.98]",
        "context_snippet": "manipulation check uncanniness 95% CI [0.16, 0.98]",
    }
    vr = recompute_stats.verify_claim(claim, truth, idx=4)
    assert vr.status == "FAIL"


def test_CI_correct_rounding_passes(tmp_path):
    """The correctly rounded [0.17, 0.98] passes (no false positives)."""
    truth = _truth(tmp_path)
    claim = {
        "id": "claim-ci-2", "claim_type": "CI_pair",
        "parsed_value": {"ci_low": 0.17, "ci_high": 0.98},
        "raw_text": "95% CI [0.17, 0.98]",
        "context_snippet": "manipulation check uncanniness 95% CI [0.17, 0.98]",
    }
    vr = recompute_stats.verify_claim(claim, truth, idx=5)
    assert vr.status == "PASS"


def test_digit_rounded_equal_helper():
    """Helper unit: half-ULP check against the raw value — bad roundings fail, half-way values round either way."""
    # 0.16 is 0.007 away from 0.167 (> 0.005): an invalid rounding -> FAIL. exp_r is the raw expected value.
    ok_bad, exp_r, digits = recompute_stats._digit_rounded_equal(0.16, 0.167, "[0.16, x]")
    assert digits == 2 and exp_r == 0.167 and ok_bad is False
    # 0.17 is a legitimate rounding of 0.167 -> PASS.
    ok_good, _, _ = recompute_stats._digit_rounded_equal(0.17, 0.167, "[0.17, x]")
    assert ok_good is True
    # half-way (0.435): both roundings (0.44 and 0.43) must be accepted (avoids round()-first false FAILs).
    ok_up, _, _ = recompute_stats._digit_rounded_equal(0.44, 0.435, "[0.44, x]")
    ok_down, _, _ = recompute_stats._digit_rounded_equal(0.43, 0.435, "[0.43, x]")
    assert ok_up is True and ok_down is True
