"""verify_claim DV/context routing regressions — N/α guard ordering + Wilcoxon p routing.

- Guard ordering: the sample-size (N) and reliability (α) branches used to sit
  behind the main-DV inference guard, so claims like 'N = 38' or 'Cronbach α'
  with no main-DV keyword fell to MANUAL before reaching their own branch.
  alpha/N are now exempt from that guard.
- Wilcoxon p: every p_value used to be compared against the F-test p (gt.p_R),
  turning correct Wilcoxon p values into false FAILs. Wilcoxon-context p must
  compare against the Wilcoxon ground truth (gt.p_wil) instead.
"""
from __future__ import annotations

import sys
from pathlib import Path


from paper_verifier import recompute_stats

# manipulation_check: p_R=.008965 (F test), p_wil=.007223 (Wilcoxon)
FIXTURE_P = """---
type: statistics-verification
---

## 1. p-value verification (R vs scipy)

| DV | F | df1 | df2 | R p | scipy p | match |
|----|---|-----|-----|-----|---------|------|
| Manipulation Check | 7.634 | 1 | 36 | .008965 | .008966 | ✓ |

## 3. Wilcoxon + effect sizes

| DV | V | p | r (rank-biserial) | r 95% CI | dz (Cohen) | dz 95% CI | n |
|----|---|---|---|---|---|---|---|
| Manipulation Check | 455.0 | .007223 | +0.529 | [0.221, 0.742] | 0.440 | [0.104, 0.770] | 38 |
"""


def _truth(tmp_path):
    md = tmp_path / "stat.md"
    md.write_text(FIXTURE_P, encoding="utf-8")
    return recompute_stats.load_ground_truth(md)


# ─── N / alpha guard ordering ─────────────────────────────────────────────

def test_N_claim_reaches_branch_without_main_dv_keyword():
    """'analytic sample of N = 38' reaches the N branch without a main-DV keyword -> PASS.

    With truth={} no main DV can match, so before the guard-ordering fix this
    claim was trapped as MANUAL by the guard.
    """
    claim = {
        "id": "claim-n-1", "claim_type": "N",
        "parsed_value": {"N": 38},
        "raw_text": "N = 38",
        "context_snippet": "yielding a final analytic sample of N = 38 after exclusions",
    }
    vr = recompute_stats.verify_claim(claim, {}, idx=1)
    assert vr.status == "PASS"
    assert vr.matched_dv == "analytic"


def test_alpha_claim_reaches_branch_without_main_dv_keyword():
    """'Test A (KR-20) α = .01' reaches the alpha branch without a main-DV keyword -> learning_A PASS."""
    claim = {
        "id": "claim-a-1", "claim_type": "alpha",
        "parsed_value": {"alpha": 0.01},
        "raw_text": "α = .01",
        "context_snippet": "reliability for Test A (KR-20) was α = .01",
    }
    vr = recompute_stats.verify_claim(claim, {}, idx=2)
    assert vr.status == "PASS"
    assert vr.matched_dv == "learning_A"


def test_N_genuinely_wrong_value_fails(tmp_path):
    """An N (37) that matches no context's ground truth genuinely FAILs."""
    claim = {
        "id": "claim-n-2", "claim_type": "N",
        "parsed_value": {"N": 37},   # not in {38,40,2,34,8}
        "raw_text": "N = 37",
        "context_snippet": "final analytic sample of N = 37",
    }
    vr = recompute_stats.verify_claim(claim, {}, idx=3)
    assert vr.status == "FAIL"


def test_N_value_matching_other_context_is_manual_not_fail(tmp_path):
    """N=40 classified as analytic but valid for 'collected' may be a misrouted context -> MANUAL (no false FAIL)."""
    claim = {
        "id": "claim-n-3", "claim_type": "N",
        "parsed_value": {"N": 40},   # analytic gt is 38, but 40 is the valid 'collected' value
        "raw_text": "N = 40",
        "context_snippet": "final analytic sample of N = 40",
    }
    vr = recompute_stats.verify_claim(claim, {}, idx=4)
    assert vr.status == "MANUAL"


def test_alpha_value_matching_other_dv_is_manual_not_fail(tmp_path):
    """α=0.689 classified as learning_A but valid for manipulation_check -> MANUAL (no false FAIL)."""
    claim = {
        "id": "claim-a-2", "claim_type": "alpha",
        "parsed_value": {"alpha": 0.689},   # learning_A gt is 0.01, but 0.689 is the valid manipulation_check α
        "raw_text": "α = .689",
        "context_snippet": "reliability for Test A was α = .689",
    }
    vr = recompute_stats.verify_claim(claim, {}, idx=5)
    assert vr.status == "MANUAL"


# ─── Wilcoxon p routing ───────────────────────────────────────────────────

def test_wilcoxon_p_compared_against_p_wil_not_p_R(tmp_path):
    """Wilcoxon-context p compares against gt.p_wil (.007223), so .007 passes (against p_R ≈ .009 it would falsely FAIL)."""
    truth = _truth(tmp_path)
    claim = {
        "id": "claim-p-1", "claim_type": "p_value",
        "parsed_value": {"p": 0.007},
        "raw_text": "Wilcoxon *V* = 455, *p* = .007",
        "context_snippet": "manipulation check Wilcoxon *V* = 455, *p* = .007",
    }
    vr = recompute_stats.verify_claim(claim, truth, idx=4)
    assert vr.status == "PASS"


def test_ftest_p_still_compared_against_p_R(tmp_path):
    """Non-Wilcoxon p still compares against gt.p_R (.008965) (no false positives)."""
    truth = _truth(tmp_path)
    claim = {
        "id": "claim-p-2", "claim_type": "p_value",
        "parsed_value": {"p": 0.009},
        "raw_text": "*p* = .009",
        "context_snippet": "manipulation check main effect *F*(1, 36) = 7.63, *p* = .009",
    }
    vr = recompute_stats.verify_claim(claim, truth, idx=5)
    assert vr.status == "PASS"


def test_wilcoxon_routing_positional_on_mixed_line(tmp_path):
    """When an F-test p (.009) and a Wilcoxon p (.007) share a line, each routes by position to p_R / p_wil.

    Guards against line-level 'wilcoxon' detection misrouting the F-test p to
    p_wil as well.
    """
    truth = _truth(tmp_path)
    line = "manipulation check *F*(1, 36) = 7.63, *p* = .009, Wilcoxon *V* = 455, *p* = .007"
    f_claim = {
        "id": "c-fp", "claim_type": "p_value", "parsed_value": {"p": 0.009},
        "raw_text": "*p* = .009", "context_snippet": line,
    }
    wil_claim = {
        "id": "c-wp", "claim_type": "p_value", "parsed_value": {"p": 0.007},
        "raw_text": "*p* = .007", "context_snippet": line,
    }
    vf = recompute_stats.verify_claim(f_claim, truth, idx=10)
    vw = recompute_stats.verify_claim(wil_claim, truth, idx=11)
    assert vf.status == "PASS"   # .009 -> gt.p_R (.008965): nearest preceding marker is the F test
    assert vw.status == "PASS"   # .007 -> gt.p_wil (.007223): nearest preceding marker is Wilcoxon


def test_wilcoxon_p_would_fail_against_p_R(tmp_path):
    """Control case: .007 in a non-Wilcoxon context still FAILs against p_R.

    (|.007 - .008965| = .00197 > tolerance — confirms the routing, not a
    loosened tolerance, is what rescues the Wilcoxon case.)
    """
    truth = _truth(tmp_path)
    claim = {
        "id": "claim-p-3", "claim_type": "p_value",
        "parsed_value": {"p": 0.007},
        "raw_text": "*p* = .007",
        "context_snippet": "manipulation check main effect *p* = .007",  # not a Wilcoxon context
    }
    vr = recompute_stats.verify_claim(claim, truth, idx=6)
    assert vr.status == "FAIL"
