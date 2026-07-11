"""Match manuscript NumericalClaims against statistical ground truth.

This module recomputes nothing itself: it treats an already cross-validated
statistics-verification document (e.g. R lme4 vs scipy parity tables) as
ground truth and diffs each manuscript claim against it 1:1.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# Manuscript-prose keywords that identify a DV → standardized DV name.
# Intentionally empty by default: declare per project via [stats.dv_keywords]
# (see paper_verifier.config). Without keywords, DV inference fails and claims
# route to MANUAL — fail-safe, never a silent false PASS.
DV_KEYWORDS: dict[str, list[str]] = {}


@dataclass
class GroundTruthRow:
    dv: str
    F: Optional[float] = None
    df1: Optional[int] = None
    df2: Optional[int] = None
    p_R: Optional[float] = None
    p_scipy: Optional[float] = None
    beta: Optional[float] = None
    SE: Optional[float] = None
    CI_low: Optional[float] = None
    CI_high: Optional[float] = None
    V: Optional[float] = None
    p_wil: Optional[float] = None
    r: Optional[float] = None
    dz: Optional[float] = None
    parity: str = "unknown"  # ✓ / ✗
    # Auxiliary ground truth (merged from the analysis-summary document)
    M_HQ: Optional[float] = None
    SD_HQ: Optional[float] = None
    M_LQ: Optional[float] = None
    SD_LQ: Optional[float] = None
    alpha: Optional[float] = None


# Reliability (Cronbach α / KR-20) ground truth keyed by DV — [stats.alpha].
# Convention: KR-20 / "Test A" / "Test B" phrasing routes to learning_A / learning_B keys.
ALPHA_GROUND_TRUTH: dict[str, float] = {}

# Sample sizes keyed by context (analytic / collected / excluded / power / pilot) — [stats.n].
N_GROUND_TRUTH: dict[str, int] = {}


@dataclass
class VerificationResult:
    id: str
    target_type: str         # numerical-claim
    target_id: str           # claim-NNNN
    verifier: str            # python-recompute
    status: str              # PASS / FAIL / WARN / MANUAL
    evidence: str
    expected_value: Optional[float] = None
    computed_value: Optional[float] = None
    delta: Optional[float] = None
    matched_dv: Optional[str] = None


# ─── Statistics-verification markdown parsing ──────────────────────────

# Markdown table row (leading `|`, cells, trailing `|`)
_TABLE_ROW = re.compile(r"^\|(.+)\|\s*$")


def _parse_md_table_section(md_text: str, header_keyword: str) -> list[list[str]]:
    """Read the markdown table that follows a heading; return rows as cell lists."""
    rows: list[list[str]] = []
    in_table = False
    seen_heading = False
    for line in md_text.splitlines():
        if header_keyword in line:
            seen_heading = True
            continue
        if not seen_heading:
            continue
        m = _TABLE_ROW.match(line)
        if m:
            cells = [c.strip() for c in m.group(1).split("|")]
            # ignore the separator row (---)
            if all(set(c) <= {"-", ":", " "} for c in cells):
                in_table = True
                continue
            if in_table:
                rows.append(cells)
        else:
            if in_table:
                break  # end of table
    return rows


def _to_float(s: str) -> Optional[float]:
    s = s.strip().replace("−", "-")
    s = re.sub(r"[*]", "", s)
    if not s or s in {"—", "-", "✓", "✗", "N/A"}:
        return None
    if s.startswith("."):
        s = "0" + s
    try:
        return float(s)
    except ValueError:
        return None


# Row labels used in ground-truth tables → standardized DV key — [stats.dv_aliases].
# This is how non-English analysis outputs are supported: map each row label
# (in whatever language your stats pipeline emits) to its canonical DV key.
DV_ALIASES: dict[str, str] = {}

# Markdown headings locating the three ground-truth tables (substring match) — [stats.headings].
TABLE_HEADINGS: dict[str, str] = {
    "p_table": "1. p-value",
    "beta_table": "2. beta",
    "wilcoxon_table": "3. Wilcoxon",
}

# Analysis-summary section heading → DV, for M (SD) tables — [stats.summary_sections].
SUMMARY_SECTIONS: dict[str, str] = {}

# Analysis-summary headings whose table rows carry the DV label in column 0 — [stats.summary_dv_tables].
SUMMARY_DV_TABLES: list[str] = []

# Exactly two condition labels as they appear in prose (e.g. ["HQ", "LQ"]).
# Order must match the summary-table column order — [stats.condition_labels].
CONDITION_LABELS: tuple[str, ...] = ()

# DVs measured on a percent scale (the only valid targets for percent claims) — [stats.percent_dvs].
PERCENT_DVS: set[str] = set()


def load_ground_truth(verification_md: Path) -> dict[str, GroundTruthRow]:
    """Parse the statistics verification markdown into a per-DV ground-truth dict.

    Table locations come from TABLE_HEADINGS; row labels resolve to canonical
    DV keys via DV_ALIASES. Rows with unmapped labels are skipped.
    """
    text = verification_md.read_text(encoding="utf-8")
    truth: dict[str, GroundTruthRow] = {}

    # Table 1: p-values (R vs scipy cross-check)
    p_rows = _parse_md_table_section(text, TABLE_HEADINGS["p_table"])
    for row in p_rows:
        if len(row) < 7:
            continue
        std_name = DV_ALIASES.get(row[0])
        if not std_name:
            continue
        truth[std_name] = GroundTruthRow(
            dv=std_name,
            F=_to_float(row[1]),
            df1=int(row[2]) if row[2].isdigit() else None,
            df2=int(row[3]) if row[3].isdigit() else None,
            p_R=_to_float(row[4]),
            p_scipy=_to_float(row[5]),
            parity="✓" if "✓" in row[6] else "✗",
        )

    # Table 2: β, SE, 95% CI
    beta_rows = _parse_md_table_section(text, TABLE_HEADINGS["beta_table"])
    for row in beta_rows:
        if len(row) < 4:
            continue
        std_name = DV_ALIASES.get(row[0])
        if not std_name:
            continue
        rec = truth.setdefault(std_name, GroundTruthRow(dv=std_name))
        rec.beta = _to_float(row[1])
        rec.SE = _to_float(row[2])
        # CI cell: `[0.167, 0.982]`
        ci_match = re.search(r"\[\s*([+\-−.\d]+)\s*,\s*([+\-−.\d]+)\s*\]", row[3])
        if ci_match:
            rec.CI_low = _to_float(ci_match.group(1))
            rec.CI_high = _to_float(ci_match.group(2))

    # Table 3: Wilcoxon + effect sizes
    wil_rows = _parse_md_table_section(text, TABLE_HEADINGS["wilcoxon_table"])
    for row in wil_rows:
        if len(row) < 8:
            continue
        std_name = DV_ALIASES.get(row[0])
        if not std_name:
            continue
        rec = truth.setdefault(std_name, GroundTruthRow(dv=std_name))
        rec.V = _to_float(row[1])
        rec.p_wil = _to_float(row[2])
        rec.r = _to_float(row[3])
        # dz sits in column index 5
        rec.dz = _to_float(row[5]) if len(row) > 5 else None

    # Seed reliability ground truth (independent of the tables above)
    for dv, alpha in ALPHA_GROUND_TRUTH.items():
        rec = truth.setdefault(dv, GroundTruthRow(dv=dv))
        rec.alpha = alpha
    return truth


def merge_analysis_summary(truth: dict[str, GroundTruthRow], summary_md: Path) -> dict[str, GroundTruthRow]:
    """Merge M/SD ground truth from an analysis-summary markdown.

    Two table shapes are supported (columns follow CONDITION_LABELS order —
    column 1 = first label, column 2 = second label):

    - SUMMARY_SECTIONS: heading → one DV; rows look like
      ``| M (SD) | 3.95 (1.02) | 4.52 (0.99) | ... |``
    - SUMMARY_DV_TABLES: headings whose rows carry the DV label in column 0,
      resolved via DV_ALIASES; rows look like
      ``| ICL | 3.42 (1.06) | 3.57 (1.08) | ... |``
    """
    if not summary_md.exists():
        return truth
    text = summary_md.read_text(encoding="utf-8")

    def _merge_cells(rec: GroundTruthRow, row: list[str]) -> None:
        # (value, slot): column 1 → first condition (HQ slot), column 2 → second (LQ slot)
        for cell, slot in [(row[1], "A"), (row[2], "B")]:
            m = re.match(r"([+\-−.\d]+)%?\s*\(([+\-−.\d]+)\)", cell.strip())
            if not m:
                continue
            mean_val = _to_float(m.group(1))
            sd_val = _to_float(m.group(2))
            if slot == "A":
                rec.M_HQ = mean_val
                rec.SD_HQ = sd_val
            else:
                rec.M_LQ = mean_val
                rec.SD_LQ = sd_val

    # Shape 1: one section heading per DV, M-row format
    for header, dv in SUMMARY_SECTIONS.items():
        rows = _parse_md_table_section(text, header)
        for row in rows:
            if len(row) < 3 or "M" not in row[0]:
                continue
            _merge_cells(truth.setdefault(dv, GroundTruthRow(dv=dv)), row)

    # Shape 2: DV label in column 0 (bold markers stripped), alias-resolved
    for header in SUMMARY_DV_TABLES:
        for row in _parse_md_table_section(text, header):
            if len(row) < 3:
                continue
            std = DV_ALIASES.get(row[0].replace("*", "").strip())
            if not std:
                continue
            _merge_cells(truth.setdefault(std, GroundTruthRow(dv=std)), row)
    return truth


# ─── Claim ↔ ground-truth matching ─────────────────────────────────────


def _infer_dv(claim_snippet: str) -> Optional[str]:
    """Infer which DV a claim is about from its context snippet.

    Multiple matched DVs mean the line is ambiguous → None (routes to MANUAL).
    This blocks false positives on multi-DV lines like "for ECL ...; for ICL ...".
    """
    s = claim_snippet.lower()
    matched: list[str] = []
    for dv, keywords in DV_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in s:
                matched.append(dv)
                break  # count each DV once, however many of its keywords hit
    if len(matched) == 1:
        return matched[0]
    # ambiguous (2+ DVs) — route to MANUAL
    return None


# A p-value near one of these markers is not a condition main-effect p, so it
# must not be compared against the main-effect ground truth. The default covers
# generic statistical contexts; extend per project with your factor names
# (e.g. "topic", "order") via [stats.modifier_keywords].
MODIFIER_KEYWORDS: tuple[str, ...] = (
    "interaction", "×", "approached significance",
    "spearman", "correlation between",
)


def _approx_equal(a: float, b: float, tol: float = 0.001) -> bool:
    """Absolute tolerance at the third decimal place."""
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _last_match_pos(text: str, pattern: str) -> int:
    """Start of the last match of pattern in text (-1 if none) — for position-based routing."""
    last = -1
    for m in re.finditer(pattern, text):
        last = m.start()
    return last


def _digit_rounded_equal(observed, expected, raw_text: str):
    """Judge "is this a valid rounding?" at the precision printed in the manuscript.

    observed (the printed value) passes iff it is within half a unit in the last
    printed decimal place of the raw expected value: |observed - expected| <= 0.5 ULP.
    A fixed absolute tolerance (0.01) was too loose — it let a mis-rounded CI bound
    (0.167 printed as 0.16) pass. Rounding expected first is wrong too: at exact
    halves like 0.435, Python's float rounding goes one way only and would false-FAIL
    the equally valid opposite rounding (0.44 in print). Half-ULP against the raw
    value fixes both. Returns (ok, expected, digits); None inputs → (False, ...).
    """
    digits = 0
    m = re.search(r"\.(\d+)", raw_text or "")
    if m:
        digits = len(m.group(1))
    if observed is None or expected is None:
        return False, expected, digits
    tol = 10 ** (-digits) * 0.5 + 1e-9 if digits > 0 else 1e-9
    ok = abs(observed - expected) <= tol
    return ok, expected, digits


def _round_to(a: float, digits: int) -> float:
    return round(a, digits)


def verify_claim(claim: dict, truth_by_dv: dict[str, GroundTruthRow], idx: int) -> VerificationResult:
    """Match one NumericalClaim against ground truth; return a VerificationResult."""
    # Malformed claims (missing required keys) become WARN results, not KeyError crashes.
    ctype = claim.get("claim_type")
    parsed = claim.get("parsed_value")
    if ctype is None or parsed is None:
        return VerificationResult(
            id=f"vr-{idx:04d}", target_type="numerical-claim",
            target_id=claim.get("id", f"claim-{idx:04d}"),
            verifier="python-recompute", status="WARN",
            evidence="Malformed claim: missing claim_type/parsed_value — not verified",
        )
    snippet = claim.get("context_snippet", "") + " " + claim.get("raw_text", "")
    dv = _infer_dv(snippet)
    result_id = f"vr-{idx:04d}"

    # Guard 1: p_value with op != "=" or near a modifier keyword — not a main-effect comparison
    if ctype == "p_value":
        op = parsed.get("op")
        if op and op != "=":
            return VerificationResult(
                id=result_id, target_type="numerical-claim", target_id=claim["id"],
                verifier="python-recompute", status="MANUAL",
                evidence=f"p_value uses op={op!r} (not strict equality) — bound or threshold claim, not a fact to match",
                matched_dv=dv,
            )
        snip_low = snippet.lower()
        if any(kw in snip_low for kw in MODIFIER_KEYWORDS):
            return VerificationResult(
                id=result_id, target_type="numerical-claim", target_id=claim["id"],
                verifier="python-recompute", status="MANUAL",
                evidence="p_value near modifier keyword (Topic/Order/interaction/etc.) — not a condition main-effect p",
                matched_dv=dv,
            )

    # alpha / N resolve their ground truth via their own context keywords (KR-20/test/
    # pilot/analytic/...), not via main-DV inference (ALPHA_GROUND_TRUTH / N_GROUND_TRUTH).
    # Without this exemption from the DV guard, a keyword-less 'N = 38' or 'Cronbach α'
    # would drop to MANUAL before ever reaching its own branch.
    if ctype not in ("alpha", "N") and (dv is None or dv not in truth_by_dv):
        return VerificationResult(
            id=result_id, target_type="numerical-claim", target_id=claim["id"],
            verifier="python-recompute", status="MANUAL",
            evidence=f"DV inference failed for claim_type={ctype} (no keyword matched)",
            matched_dv=None,
        )

    # alpha/N never touch gt below — .get() keeps a missing dv None-safe (no KeyError).
    gt = truth_by_dv.get(dv)
    # Extract expected per claim type
    expected: Optional[float] = None
    observed: Optional[float] = None
    if ctype == "F_stat":
        expected = gt.F
        observed = parsed.get("F")
        # Verify df1/df2 as well: a matching F value with different df is a different
        # test (different DV/model) and must FAIL. Comparing F alone once let
        # F(2,99)=7.63 pass against a ground truth of F(1,36)=7.634.
        claim_df1, claim_df2 = parsed.get("df1"), parsed.get("df2")
        df_mismatch = (
            (gt.df1 is not None and claim_df1 is not None and claim_df1 != gt.df1)
            or (gt.df2 is not None and claim_df2 is not None and claim_df2 != gt.df2)
        )
        if df_mismatch:
            return VerificationResult(
                id=result_id, target_type="numerical-claim", target_id=claim["id"],
                verifier="python-recompute", status="FAIL",
                evidence=(f"F df mismatch: claim F({claim_df1},{claim_df2})={observed} "
                          f"vs ground truth F({gt.df1},{gt.df2})={expected} for {dv}"),
                expected_value=expected, computed_value=observed, matched_dv=dv,
            )
    elif ctype == "p_value":
        # A Wilcoxon p must compare against gt.p_wil, not the F-test p (gt.p_R). On
        # mixed lines (F-test p and Wilcoxon p together), merely spotting 'wilcoxon'
        # anywhere would misroute the F-test p too — so route by position: whichever
        # statistic marker (Wilcoxon/V vs F) appears last before this p wins; with no
        # marker, default to p_R (bare p's are usually F-test main effects). The scope
        # extends through this p's raw_text so a marker inside it (e.g. a whole
        # "Wilcoxon V=…, p=…") still counts.
        raw_p = claim.get("raw_text", "")
        _pos = snippet.find(raw_p)
        _scope = (snippet[:_pos + len(raw_p)] if _pos >= 0 else snippet).lower()
        _wil = max(_scope.rfind("wilcoxon"), _scope.rfind("*v*"),
                   _last_match_pos(_scope, r"(?<![a-z])v\s*="))
        _f = max(_scope.rfind("*f*"), _last_match_pos(_scope, r"(?<![a-z])f\s*\("))
        expected = gt.p_wil if _wil > _f else gt.p_R
        observed = parsed.get("p")
    elif ctype == "beta":
        expected = gt.beta
        observed = parsed.get("beta")
    elif ctype == "effect_dz":
        expected = gt.dz
        observed = parsed.get("dz")
    elif ctype == "V_wilcoxon":
        expected = gt.V
        observed = parsed.get("V")
    elif ctype == "r_corr":
        expected = gt.r
        observed = parsed.get("r")
    elif ctype == "p_adj":
        # Adjusted p needs its own ground truth — absent from the verification tables
        return VerificationResult(
            id=result_id, target_type="numerical-claim", target_id=claim["id"],
            verifier="python-recompute", status="MANUAL",
            evidence="Holm adjusted p — ground truth not in statistics_verification.md, requires Holm recomputation",
            matched_dv=dv,
        )
    elif ctype == "CI_pair":
        # Guard 1: detect d_z CI patterns — `*d_z* = X [low, high]` / `dz = X [low, high]`.
        # Ground-truth CIs are β CIs, so an effect-size CI is not comparable → MANUAL.
        snip_low = snippet.lower()
        # Both d_z notations count: underscore (*d_z*) and subscript markup (*d*~z~).
        # Missing the `*d*~z~` form would compare a d_z CI against the β-CI ground
        # truth and produce a false FAIL.
        if "d_z" in snip_low or " dz " in snip_low or "*d_z*" in snippet or "~z~" in snippet:
            return VerificationResult(
                id=result_id, target_type="numerical-claim", target_id=claim["id"],
                verifier="python-recompute", status="MANUAL",
                evidence="CI near d_z keyword — effect-size CI, not β CI (ground truth)",
                matched_dv=dv,
            )
        # Guard 2: position-based — with 2+ CI pairs on a line, the second and later
        # ones are presumed effect-size CIs (the β CI is normally printed first).
        # Decisive on table rows.
        raw = claim.get("raw_text", "")
        raw_pos = snippet.find(raw)
        if raw_pos > 0:
            prior_cis = re.findall(r"\[\s*[+\-−.\d]+\s*,\s*[+\-−.\d]+\s*\]", snippet[:raw_pos])
            if len(prior_cis) >= 1:
                return VerificationResult(
                    id=result_id, target_type="numerical-claim", target_id=claim["id"],
                    verifier="python-recompute", status="MANUAL",
                    evidence=f"CI is at position {len(prior_cis)+1} on the line — likely effect-size CI, not β CI",
                    matched_dv=dv,
                )
        # A CI matches as a (low, high) pair
        observed_low = parsed.get("ci_low")
        observed_high = parsed.get("ci_high")
        if gt.CI_low is None or gt.CI_high is None:
            return VerificationResult(
                id=result_id, target_type="numerical-claim", target_id=claim["id"],
                verifier="python-recompute", status="MANUAL",
                evidence=f"CI ground truth unavailable for {dv}",
                matched_dv=dv,
            )
        if observed_low is None or observed_high is None:
            return VerificationResult(
                id=result_id, target_type="numerical-claim", target_id=claim["id"],
                verifier="python-recompute", status="WARN",
                evidence=f"CI observed bound missing: [{observed_low}, {observed_high}]",
                matched_dv=dv,
            )
        # Half-ULP at the printed precision, not a fixed 0.01 tolerance (valid-rounding test).
        raw = claim.get("raw_text", "")
        ok_low, _, digits = _digit_rounded_equal(observed_low, gt.CI_low, raw)
        ok_high, _, _ = _digit_rounded_equal(observed_high, gt.CI_high, raw)
        status = "PASS" if (ok_low and ok_high) else "FAIL"
        return VerificationResult(
            id=result_id, target_type="numerical-claim", target_id=claim["id"],
            verifier="python-recompute", status=status,
            evidence=(f"CI claim=[{observed_low}, {observed_high}] "
                      f"gt=[{gt.CI_low}, {gt.CI_high}] (digits={digits})"),
            matched_dv=dv,
        )
    elif ctype == "alpha":
        # α (Cronbach / KR-20) — infer the target, then match against ALPHA_GROUND_TRUTH
        observed = parsed.get("alpha")
        # "KR-20" / "Test A/B" phrasing routes to the learning_A/B keys
        snip_low = snippet.lower()
        alpha_dv = dv
        if "kr-20" in snip_low or "test a" in snip_low:
            alpha_dv = "learning_A"
        elif "test b" in snip_low or "test b)" in snip_low:
            alpha_dv = "learning_B"
        elif "learning" in snip_low and observed and observed < 0.05:
            # a very low α in a "learning" context → the Test A key
            alpha_dv = "learning_A"
        gt_alpha = ALPHA_GROUND_TRUTH.get(alpha_dv) if alpha_dv else None
        if gt_alpha is None:
            return VerificationResult(
                id=result_id, target_type="numerical-claim", target_id=claim["id"],
                verifier="python-recompute", status="MANUAL",
                evidence=f"alpha DV inference failed (snippet keyword fallback)",
                matched_dv=alpha_dv,
            )
        delta = abs(gt_alpha - observed)
        if delta <= 0.001:
            status = "PASS"
        elif any(abs(a - observed) <= 0.001 for a in ALPHA_GROUND_TRUTH.values()):
            # Fail-safe: observed equals some other DV's valid alpha, so the crude
            # keyword routing may have misread the context. Demote to MANUAL (human
            # review) instead of FAIL (which would assert a manuscript error).
            status = "MANUAL"
        else:
            status = "FAIL"
        return VerificationResult(
            id=result_id, target_type="numerical-claim", target_id=claim["id"],
            verifier="python-recompute", status=status,
            evidence=(f"alpha {alpha_dv}: claim={observed} expected={gt_alpha}"
                      + (" (matches another DV's alpha — likely context misclassification)"
                         if status == "MANUAL" else "")),
            expected_value=gt_alpha, computed_value=observed, delta=delta,
            matched_dv=alpha_dv,
        )
    elif ctype == "N":
        # N value — classify by context keywords
        observed = parsed.get("N")
        snip_low = snippet.lower()
        n_context = None
        if "pilot" in snip_low:
            n_context = "pilot"
        elif "g*power" in snip_low or "g power" in snip_low or "a priori" in snip_low:
            n_context = "power"
        elif "analytic" in snip_low or "final" in snip_low or "yielding" in snip_low or "excluded" in snip_low:
            n_context = "analytic"
        elif "recruited" in snip_low or "collected" in snip_low:
            n_context = "collected"
        else:
            # No context keyword: accept only if the value matches the analytic N.
            n_context = ("analytic"
                         if "analytic" in N_GROUND_TRUTH and observed == N_GROUND_TRUTH["analytic"]
                         else None)
        gt_n = N_GROUND_TRUTH.get(n_context) if n_context else None
        if gt_n is None:
            return VerificationResult(
                id=result_id, target_type="numerical-claim", target_id=claim["id"],
                verifier="python-recompute", status="MANUAL",
                evidence=f"N context inference failed (observed={observed})",
                matched_dv=dv,
            )
        if observed == gt_n:
            status = "PASS"
        elif observed in N_GROUND_TRUTH.values():
            # Fail-safe: the value equals another context's valid N — possible misrouting → MANUAL.
            status = "MANUAL"
        else:
            status = "FAIL"
        return VerificationResult(
            id=result_id, target_type="numerical-claim", target_id=claim["id"],
            verifier="python-recompute", status=status,
            evidence=(f"N {n_context}: claim={observed} expected={gt_n}"
                      + (" (matches another context's N — likely misclassification)"
                         if status == "MANUAL" else "")),
            expected_value=float(gt_n), computed_value=float(observed),
            matched_dv=n_context,
        )
    elif ctype in ("M_mean", "SD", "percent"):
        # Percent unit guard: only DVs declared percent-scaled may match percent
        # claims (a Likert/count DV compared against a % value is meaningless).
        if ctype == "percent":
            if dv not in PERCENT_DVS:
                return VerificationResult(
                    id=result_id, target_type="numerical-claim", target_id=claim["id"],
                    verifier="python-recompute", status="MANUAL",
                    evidence=(f"percent unit mismatch — dv={dv} not declared percent-scaled "
                              f"(see [stats.percent_dvs])"),
                    matched_dv=dv,
                )
        # M/SD/percent are reported per condition. The condition is inferred from
        # the nearest condition label BEFORE the claim in prose, e.g.
        # `under HQ (M = 8.52%, SD = 9.23) than under LQ (M = 4.60%, ...)`.
        if len(CONDITION_LABELS) != 2:
            return VerificationResult(
                id=result_id, target_type="numerical-claim", target_id=claim["id"],
                verifier="python-recompute", status="MANUAL",
                evidence=(f"{ctype} needs exactly two condition labels "
                          f"(see [stats.condition_labels]) — not configured"),
                matched_dv=dv,
            )
        label_a, label_b = CONDITION_LABELS  # order matches summary-table columns
        raw = claim.get("raw_text", "")
        raw_pos = snippet.find(raw)
        mod = None
        if raw_pos >= 0:
            before_text = snippet[:raw_pos].lower()
            last_a = before_text.rfind(label_a.lower())
            last_b = before_text.rfind(label_b.lower())
            if last_a > last_b:
                mod = label_a
            elif last_b > last_a:
                mod = label_b
        if mod is None or dv is None:
            return VerificationResult(
                id=result_id, target_type="numerical-claim", target_id=claim["id"],
                verifier="python-recompute", status="MANUAL",
                evidence=f"{ctype} condition context inference failed",
                matched_dv=dv,
            )
        gt = truth_by_dv.get(dv)
        if gt is None:
            return VerificationResult(
                id=result_id, target_type="numerical-claim", target_id=claim["id"],
                verifier="python-recompute", status="MANUAL",
                evidence=f"{ctype} no ground truth for dv={dv}",
                matched_dv=dv,
            )
        # First condition label → slot A (M_HQ/SD_HQ fields), second → slot B.
        if ctype == "M_mean" or ctype == "percent":
            expected = gt.M_HQ if mod == label_a else gt.M_LQ
            observed = parsed.get("M") if ctype == "M_mean" else parsed.get("pct")
        else:  # SD
            expected = gt.SD_HQ if mod == label_a else gt.SD_LQ
            observed = parsed.get("SD")
        if expected is None or observed is None:
            return VerificationResult(
                id=result_id, target_type="numerical-claim", target_id=claim["id"],
                verifier="python-recompute", status="MANUAL",
                evidence=f"{ctype} ground truth/observed missing (dv={dv}, mod={mod})",
                matched_dv=dv,
            )
        # Decimal digits as printed in the manuscript
        digits = 0
        m = re.search(r"\.(\d+)", claim.get("raw_text", ""))
        if m:
            digits = len(m.group(1))
        if digits > 0:
            expected_round = round(expected, digits)
        else:
            expected_round = expected
        delta = abs(expected_round - observed)
        tol = 10 ** (-digits) * 0.5 + 1e-9 if digits > 0 else 0.05
        status = "PASS" if delta <= tol else "FAIL"
        return VerificationResult(
            id=result_id, target_type="numerical-claim", target_id=claim["id"],
            verifier="python-recompute", status=status,
            evidence=f"{ctype} {dv} {mod}: claim={observed} expected={expected_round}",
            expected_value=expected, computed_value=observed, delta=delta,
            matched_dv=f"{dv}_{mod}",
        )
    else:
        # Remaining claim types have no ground truth yet — MANUAL
        return VerificationResult(
            id=result_id, target_type="numerical-claim", target_id=claim["id"],
            verifier="python-recompute", status="MANUAL",
            evidence=f"claim_type={ctype} ground truth not yet integrated",
            matched_dv=dv,
        )

    if expected is None or observed is None:
        return VerificationResult(
            id=result_id, target_type="numerical-claim", target_id=claim["id"],
            verifier="python-recompute", status="WARN",
            evidence=f"Missing value: expected={expected}, observed={observed}",
            expected_value=expected, computed_value=observed,
            matched_dv=dv,
        )

    # Same valid-rounding criterion as _digit_rounded_equal: half-ULP against the raw
    # value at the printed precision. Rounding expected first would false-FAIL the
    # opposite-but-equally-valid rounding at exact halves like 0.435 (Python float
    # rounding goes one way only) — a defect that would lurk for F/p/β alike.
    digits = 0
    for s in (claim.get("raw_text", ""),):
        m = re.search(r"\.(\d+)", s)
        if m:
            digits = max(digits, len(m.group(1)))
    delta = abs(observed - expected)
    tol = 10 ** (-digits) * 0.5 + 1e-9 if digits > 0 else 1e-9
    status = "PASS" if delta <= tol else "FAIL"
    return VerificationResult(
        id=result_id, target_type="numerical-claim", target_id=claim["id"],
        verifier="python-recompute", status=status,
        evidence=f"{ctype} claim={observed} vs gt={expected} (digits={digits}, delta={delta:.4f})",
        expected_value=expected, computed_value=observed, delta=delta,
        matched_dv=dv,
    )


def to_records(results: list[VerificationResult]) -> list[dict]:
    return [asdict(r) for r in results]
