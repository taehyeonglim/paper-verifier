"""NumericalClaim regex extraction — APA 7 italic-asterisk style + typographic minus."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path


# Accept typographic minus (U+2212), ASCII hyphen, and plus signs
SIGN = r"[+−\-]?"
# Match every numeric form: `5`, `5.0`, `0.05`, `.05`, `−.05`, `−0.05`, `−5`
NUM = rf"({SIGN}\d*\.?\d+)"
DOT_NUM = NUM  # alias kept for compatibility


# Each pattern is a (regex, claim_type, value_keys) tuple;
# value_keys maps capture groups, in order, to parameter names.
PATTERNS: list[tuple[str, str, list[str]]] = [
    # F(df1, df2) = value   — italic asterisks optional
    (
        rf"\*?F\*?\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*=\s*{NUM}",
        "F_stat",
        ["df1", "df2", "F"],
    ),
    # p_adj = .009  (p_adj is tried before plain p)
    (
        rf"\*?p[_ ]?adj\*?\s*=\s*{DOT_NUM}",
        "p_adj",
        ["p_adj"],
    ),
    # p = .009 or p < .001
    (
        rf"\*?p\*?\s*([=<>])\s*{DOT_NUM}",
        "p_value",
        ["op", "p"],
    ),
    # β = 0.57 or β = −4.16
    (
        rf"β\s*=\s*{NUM}",
        "beta",
        ["beta"],
    ),
    # d_z = 0.44 or *d_z* = −0.13 — underscore form
    (
        rf"\*?d[_ ]?z\*?\s*=\s*{NUM}",
        "effect_dz",
        ["dz"],
    ),
    # α = .689  (Cronbach alpha + significance alpha)
    (
        rf"α\s*=\s*{DOT_NUM}",
        "alpha",
        ["alpha"],
    ),
    # η² / ηp² / partial η² = .12  (effect size). No ground-truth integration yet, so
    # verify surfaces these as MANUAL — still better than the silent miss (false
    # negative) of having no pattern at all.
    (
        rf"(?:partial\s+)?η\s*[ₚp]?\s*[²2]?\s*=\s*{DOT_NUM}",
        "eta_squared",
        ["eta_sq"],
    ),
    # N = 38  — capitalized N standalone (word boundary)
    (
        rf"\bN\s*=\s*(\d+)",
        "N",
        ["N"],
    ),
    # V = 455.0  — Wilcoxon V (italic optional)
    (
        rf"\*?V\*?\s*=\s*{NUM}",
        "V_wilcoxon",
        ["V"],
    ),
    # M = 4.52
    (
        rf"\*M\*\s*=\s*{NUM}",
        "M_mean",
        ["M"],
    ),
    # SD = 0.99
    (
        rf"\*SD\*\s*=\s*{NUM}",
        "SD",
        ["SD"],
    ),
    # 95% CI [0.17, 0.98]
    (
        rf"\[\s*{NUM}\s*,\s*{NUM}\s*\]",
        "CI_pair",
        ["ci_low", "ci_high"],
    ),
    # 8.52%  / 88.6%
    (
        rf"(\d+\.\d+)\s*%",
        "percent",
        ["pct"],
    ),
    # ρ = −.108  (Spearman rho) — supports the leading-dot form (`.108`)
    (
        rf"ρ\s*=\s*{DOT_NUM}",
        "rho",
        ["rho"],
    ),
    # IRR = 0.71
    (
        rf"IRR\s*=\s*{NUM}",
        "IRR",
        ["IRR"],
    ),
    # *r* = .53  — italic asterisk wrapping (rank-biserial / correlation)
    (
        rf"\*r\*\s*=\s*{DOT_NUM}",
        "r_corr",
        ["r"],
    ),
]


@dataclass
class NumericalClaim:
    id: str
    manuscript_id: str
    section: str
    line: int
    raw_text: str
    claim_type: str
    parsed_value: dict = field(default_factory=dict)
    context_snippet: str = ""
    # Zero-based, half-open character offsets in the original line/context_snippet.
    # Optional for compatibility with older callers and serialized claims.
    start: int | None = None
    end: int | None = None
    raw_values: dict[str, str] = field(default_factory=dict)


def _normalize_minus(num_str: str) -> float:
    """typographic minus U+2212 → ASCII '-', leading '.' → '0.', then float."""
    s = num_str.replace("−", "-").strip()
    if s.startswith("."):
        s = "0" + s
    elif s.startswith("-.") or s.startswith("+."):
        s = s[0] + "0" + s[1:]
    return float(s)


def extract_from_text(
    text: str,
    manuscript_id: str,
    section: str,
    starting_idx: int = 1,
) -> list[NumericalClaim]:
    claims: list[NumericalClaim] = []
    next_idx = starting_idx
    for line_num, line in enumerate(text.splitlines(), 1):
        for pattern, claim_type, value_keys in PATTERNS:
            for m in re.finditer(pattern, line):
                groups = m.groups()
                if len(groups) != len(value_keys):
                    continue
                parsed = {}
                for key, val in zip(value_keys, groups):
                    if val is None:
                        continue
                    if key in ("op",):
                        parsed[key] = val
                    elif key in ("df1", "df2", "N"):
                        try:
                            parsed[key] = int(val)
                        except ValueError:
                            parsed[key] = val
                    else:
                        try:
                            parsed[key] = _normalize_minus(val)
                        except ValueError:
                            parsed[key] = val
                # Context snippet: keep the whole line so the multi-DV ambiguity guard can see it
                claims.append(
                    NumericalClaim(
                        id=f"claim-{next_idx:04d}",
                        manuscript_id=manuscript_id,
                        section=section,
                        line=line_num,
                        raw_text=m.group(0),
                        claim_type=claim_type,
                        parsed_value=parsed,
                        context_snippet=line,
                        start=m.start(),
                        end=m.end(),
                        raw_values={key: val for key, val in zip(value_keys, groups) if val is not None},
                    )
                )
                next_idx += 1
    return claims


def extract_from_file(path: Path, manuscript_id: str, section: str) -> list[NumericalClaim]:
    text = path.read_text(encoding="utf-8")
    return extract_from_text(text, manuscript_id, section)


def to_records(claims: list[NumericalClaim]) -> list[dict]:
    return [asdict(c) for c in claims]
