"""NumericalClaim regex unit tests.

Covers the core notation patterns sampled from real APA-style manuscripts.
"""
from __future__ import annotations

import sys
from pathlib import Path


from paper_verifier import claim_parser


def _types(claims):
    return [c.claim_type for c in claims]


def test_F_stat_apa_italics():
    text = "The manipulation check confirmed the intended direction, *F*(1, 36) = 7.63, *p* = .009."
    claims = claim_parser.extract_from_text(text, "mss-001", "results")
    types = _types(claims)
    assert "F_stat" in types
    f_claim = next(c for c in claims if c.claim_type == "F_stat")
    assert f_claim.parsed_value["df1"] == 1
    assert f_claim.parsed_value["df2"] == 36
    assert abs(f_claim.parsed_value["F"] - 7.63) < 1e-6
    assert "p_value" in types


def test_beta_with_typographic_minus():
    text = "β = −4.16, 95% CI [−6.71, −1.61]"
    claims = claim_parser.extract_from_text(text, "mss-001", "results")
    types = _types(claims)
    assert "beta" in types
    b = next(c for c in claims if c.claim_type == "beta")
    assert abs(b.parsed_value["beta"] - (-4.16)) < 1e-6


def test_dz_underscore_form():
    text = "*d_z* = 0.44 [0.10, 0.77]"
    claims = claim_parser.extract_from_text(text, "mss-001", "results")
    types = _types(claims)
    assert "effect_dz" in types
    dz = next(c for c in claims if c.claim_type == "effect_dz")
    assert abs(dz.parsed_value["dz"] - 0.44) < 1e-6


def test_alpha_cronbach():
    text = "Cronbach α = .689 in the present sample."
    claims = claim_parser.extract_from_text(text, "mss-001", "methods")
    a = next(c for c in claims if c.claim_type == "alpha")
    assert abs(a.parsed_value["alpha"] - 0.689) < 1e-6


def test_N_capitalized_only():
    text = "yielding a final analytic sample of N = 38"
    claims = claim_parser.extract_from_text(text, "mss-001", "methods")
    n = next(c for c in claims if c.claim_type == "N")
    assert n.parsed_value["N"] == 38


def test_V_wilcoxon():
    text = "Wilcoxon *V* = 455, *p* = .007"
    claims = claim_parser.extract_from_text(text, "mss-001", "results")
    types = _types(claims)
    assert "V_wilcoxon" in types
    v = next(c for c in claims if c.claim_type == "V_wilcoxon")
    assert abs(v.parsed_value["V"] - 455.0) < 1e-6


def test_CI_pair_negative_bounds():
    text = "95% CI [−6.71, −1.61]"
    claims = claim_parser.extract_from_text(text, "mss-001", "results")
    ci = next(c for c in claims if c.claim_type == "CI_pair")
    assert abs(ci.parsed_value["ci_low"] - (-6.71)) < 1e-6
    assert abs(ci.parsed_value["ci_high"] - (-1.61)) < 1e-6


def test_percent_with_decimal():
    text = "Dwell time on the avatar's face was significantly higher under HQ (*M* = 8.52%, *SD* = 9.23)"
    claims = claim_parser.extract_from_text(text, "mss-001", "results")
    types = _types(claims)
    assert "percent" in types
    assert "M_mean" in types
    assert "SD" in types
    pct = [c for c in claims if c.claim_type == "percent"]
    assert any(abs(p.parsed_value["pct"] - 8.52) < 1e-6 for p in pct)


def test_p_adj_separate_from_p():
    text = "*p* = .003, Holm *p_adj* = .009"
    claims = claim_parser.extract_from_text(text, "mss-001", "results")
    types = _types(claims)
    assert "p_value" in types
    assert "p_adj" in types
    pa = next(c for c in claims if c.claim_type == "p_adj")
    assert abs(pa.parsed_value["p_adj"] - 0.009) < 1e-6


def test_rho_spearman():
    text = "ρ = −.108, *p* = .517"
    claims = claim_parser.extract_from_text(text, "mss-001", "results")
    r = next(c for c in claims if c.claim_type == "rho")
    assert abs(r.parsed_value["rho"] - (-0.108)) < 1e-6


def test_IRR_glmm():
    text = "Negative Binomial GLMM confirmed IRR = 0.71, 95% CI [0.51, 1.00]"
    claims = claim_parser.extract_from_text(text, "mss-001", "results")
    irr = next(c for c in claims if c.claim_type == "IRR")
    assert abs(irr.parsed_value["IRR"] - 0.71) < 1e-6


def test_extract_assigns_sequential_ids():
    text = "*F*(1, 36) = 7.63, *p* = .009"
    claims = claim_parser.extract_from_text(text, "mss-001", "results", starting_idx=42)
    ids = [c.id for c in claims]
    assert ids[0] == "claim-0042"
    assert all(i.startswith("claim-") for i in ids)
