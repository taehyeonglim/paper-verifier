"""Configuration loading and application.

paper-verifier keeps experiment-specific knowledge (DV keywords, reliability
values, sample sizes, table headings, condition labels, ...) out of the code.
A single TOML file declares that knowledge per project::

    [project]
    name = "my-paper"
    manuscripts = ["sections/*.md"]
    references = "references.md"
    stats = "statistics_verification.md"

    [stats.dv_keywords]
    engagement = ["engagement", "engagement score"]

    [stats.dv_aliases]
    "Engagement" = "engagement"

Design notes:

- ``apply()`` rebinds module-level globals in :mod:`paper_verifier.recompute_stats`
  instead of threading a config object through every function. Function
  signatures stay stable, which keeps the (large) regression-test surface
  untouched. Threading the config explicitly is a candidate for v0.2.
- Library defaults are intentionally EMPTY for the domain knowledge. Running
  without configuration routes numerical claims to MANUAL and trips the
  ground-truth gate (hard FAIL) rather than silently passing — fail-safe by
  default.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Default headings used to locate the three ground-truth tables in the
# statistics verification markdown (substring match, case-sensitive).
DEFAULT_TABLE_HEADINGS: dict[str, str] = {
    "p_table": "1. p-value",
    "beta_table": "2. beta",
    "wilcoxon_table": "3. Wilcoxon",
}

# Generic statistical-context markers: a p-value that sits next to one of these
# is not a condition main-effect p, so it must not be compared against the
# main-effect ground truth. Extend per project with factor names (e.g. "topic").
DEFAULT_MODIFIER_KEYWORDS: tuple[str, ...] = (
    "interaction",
    "×",
    "approached significance",
    "spearman",
    "correlation between",
)


@dataclass
class VerifierConfig:
    """Resolved configuration. All relative paths are anchored at ``base_dir``."""

    # [project]
    name: str = "manuscript"
    manuscripts: list[str] = field(default_factory=list)  # literal paths or globs
    references: Path | None = None
    stats: Path | None = None          # statistics verification md (primary ground truth)
    summary_stats: Path | None = None  # analysis summary md (M/SD ground truth)
    reports_dir: Path | None = None    # root for report output (a <sha8> subdir is appended)

    # [library]
    library_root: Path | None = None

    # [stats.*]
    dv_keywords: dict[str, list[str]] = field(default_factory=dict)
    dv_aliases: dict[str, str] = field(default_factory=dict)
    alpha: dict[str, float] = field(default_factory=dict)
    n: dict[str, int] = field(default_factory=dict)
    condition_labels: tuple[str, ...] = ()
    percent_dvs: frozenset[str] = frozenset()
    modifier_keywords: tuple[str, ...] = DEFAULT_MODIFIER_KEYWORDS
    headings: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_TABLE_HEADINGS))
    summary_sections: dict[str, str] = field(default_factory=dict)
    summary_dv_tables: list[str] = field(default_factory=list)

    # [llm]
    llm_provider: str = "codex"
    llm_argv: tuple[str, ...] = ()
    llm_timeout: int = 120

    # Anchor for relative paths (the config file's directory).
    base_dir: Path = field(default_factory=Path.cwd)


def _as_path(base: Path, value: Any) -> Path | None:
    if value is None:
        return None
    p = Path(str(value))
    return p if p.is_absolute() else (base / p)


def load(path: Path | str) -> VerifierConfig:
    """Load a ``paper-verifier.toml`` file. Relative paths resolve against its directory."""
    path = Path(path).resolve()
    with open(path, "rb") as f:
        raw: dict[str, Any] = tomllib.load(f)
    base = path.parent
    proj = raw.get("project", {})
    lib = raw.get("library", {})
    stats = raw.get("stats", {})
    llm = raw.get("llm", {})
    return VerifierConfig(
        name=str(proj.get("name", "manuscript")),
        manuscripts=[str(m) for m in proj.get("manuscripts", [])],
        references=_as_path(base, proj.get("references")),
        stats=_as_path(base, proj.get("stats")),
        summary_stats=_as_path(base, proj.get("summary_stats")),
        reports_dir=_as_path(base, proj.get("reports_dir")),
        library_root=_as_path(base, lib.get("root")),
        dv_keywords={k: [str(x) for x in v] for k, v in stats.get("dv_keywords", {}).items()},
        dv_aliases={str(k): str(v) for k, v in stats.get("dv_aliases", {}).items()},
        alpha={str(k): float(v) for k, v in stats.get("alpha", {}).items()},
        n={str(k): int(v) for k, v in stats.get("n", {}).items()},
        condition_labels=tuple(str(x) for x in stats.get("condition_labels", ())),
        percent_dvs=frozenset(str(x) for x in stats.get("percent_dvs", ())),
        modifier_keywords=tuple(
            str(x) for x in stats.get("modifier_keywords", DEFAULT_MODIFIER_KEYWORDS)
        ),
        headings={**DEFAULT_TABLE_HEADINGS,
                  **{str(k): str(v) for k, v in stats.get("headings", {}).items()}},
        summary_sections={str(k): str(v) for k, v in stats.get("summary_sections", {}).items()},
        summary_dv_tables=[str(x) for x in stats.get("summary_dv_tables", [])],
        llm_provider=str(llm.get("provider", "codex")),
        llm_argv=tuple(str(x) for x in llm.get("argv", ())),
        llm_timeout=int(llm.get("timeout", 120)),
        base_dir=base,
    )


def apply(cfg: VerifierConfig) -> None:
    """Rebind the domain-knowledge globals used by the verification modules.

    Idempotent; call with ``VerifierConfig()`` to restore library defaults.
    """
    from paper_verifier import llm, paraphrase_match, recompute_stats

    paraphrase_match._PROVIDER = llm.resolve(cfg.llm_provider, cfg.llm_argv)
    paraphrase_match._TIMEOUT = int(cfg.llm_timeout)

    recompute_stats.DV_KEYWORDS = dict(cfg.dv_keywords)
    recompute_stats.DV_ALIASES = dict(cfg.dv_aliases)
    recompute_stats.ALPHA_GROUND_TRUTH = dict(cfg.alpha)
    recompute_stats.N_GROUND_TRUTH = dict(cfg.n)
    recompute_stats.TABLE_HEADINGS = dict(cfg.headings)
    recompute_stats.SUMMARY_SECTIONS = dict(cfg.summary_sections)
    recompute_stats.SUMMARY_DV_TABLES = list(cfg.summary_dv_tables)
    recompute_stats.CONDITION_LABELS = tuple(cfg.condition_labels)
    recompute_stats.PERCENT_DVS = set(cfg.percent_dvs)
    recompute_stats.MODIFIER_KEYWORDS = tuple(cfg.modifier_keywords)
