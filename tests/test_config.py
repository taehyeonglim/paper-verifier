"""config.load / config.apply unit tests."""
from __future__ import annotations

from pathlib import Path

from paper_verifier import config, recompute_stats

TOML = """
[project]
name = "demo-paper"
manuscripts = ["sections/*.md", "extra.md"]
references = "references.md"
stats = "gt/statistics_verification.md"
summary_stats = "gt/analysis_summary.md"
reports_dir = "out"

[library]
root = "papers"

[stats]
condition_labels = ["AI", "TEXT"]
percent_dvs = ["quiz"]
modifier_keywords = ["interaction", "moderation"]

[stats.dv_keywords]
engagement = ["engagement", "engagement score"]
quiz = ["quiz score"]

[stats.dv_aliases]
"Engagement" = "engagement"
"참여도" = "engagement"

[stats.alpha]
engagement = 0.81

[stats.n]
analytic = 30

[stats.headings]
p_table = "1. p-value check"

[stats.summary_sections]
"3.1 Engagement" = "engagement"

[llm]
provider = "claude"
timeout = 60
"""


def _write_cfg(tmp_path: Path) -> Path:
    p = tmp_path / "paper-verifier.toml"
    p.write_text(TOML, encoding="utf-8")
    return p


def test_load_resolves_paths_relative_to_config_dir(tmp_path):
    cfg = config.load(_write_cfg(tmp_path))
    assert cfg.references == tmp_path / "references.md"
    assert cfg.stats == tmp_path / "gt/statistics_verification.md"
    assert cfg.summary_stats == tmp_path / "gt/analysis_summary.md"
    assert cfg.reports_dir == tmp_path / "out"
    assert cfg.library_root == tmp_path / "papers"
    assert cfg.base_dir == tmp_path
    # manuscripts stay as raw specs (globs expand at run time)
    assert cfg.manuscripts == ["sections/*.md", "extra.md"]


def test_load_parses_stats_maps_with_types(tmp_path):
    cfg = config.load(_write_cfg(tmp_path))
    assert cfg.dv_keywords == {"engagement": ["engagement", "engagement score"],
                               "quiz": ["quiz score"]}
    assert cfg.dv_aliases["참여도"] == "engagement"
    assert cfg.alpha == {"engagement": 0.81}
    assert cfg.n == {"analytic": 30}
    assert cfg.condition_labels == ("AI", "TEXT")
    assert cfg.percent_dvs == frozenset({"quiz"})
    assert cfg.modifier_keywords == ("interaction", "moderation")
    assert cfg.llm_provider == "claude"
    assert cfg.llm_timeout == 60


def test_headings_merge_with_defaults(tmp_path):
    cfg = config.load(_write_cfg(tmp_path))
    assert cfg.headings["p_table"] == "1. p-value check"      # overridden
    assert cfg.headings["beta_table"] == "2. beta"            # default kept
    assert cfg.headings["wilcoxon_table"] == "3. Wilcoxon"    # default kept


def test_apply_rebinds_globals_and_defaults_restore(tmp_path):
    cfg = config.load(_write_cfg(tmp_path))
    config.apply(cfg)
    assert recompute_stats.DV_KEYWORDS["engagement"] == ["engagement", "engagement score"]
    assert recompute_stats.CONDITION_LABELS == ("AI", "TEXT")
    assert recompute_stats.PERCENT_DVS == {"quiz"}
    config.apply(config.VerifierConfig())
    assert recompute_stats.DV_KEYWORDS == {}
    assert recompute_stats.CONDITION_LABELS == ()


def test_llm_provider_none_disables_gracefully():
    from paper_verifier import paraphrase_match

    config.apply(config.VerifierConfig(llm_provider="none"))
    assert paraphrase_match._PROVIDER is None
    score, _reason = paraphrase_match.dispatch_paraphrase_check("a", "b")
    assert score == -1.0  # routes to MANUAL downstream
    purpose, _ = paraphrase_match.dispatch_classify_citation("a", "b")
    assert purpose == "unknown"  # sentinel → heuristic preserved


def test_llm_unknown_provider_fails_loudly():
    import pytest

    with pytest.raises(ValueError, match="unknown \\[llm\\].provider"):
        config.apply(config.VerifierConfig(llm_provider="does-not-exist"))


def test_library_defaults_are_empty_fail_safe():
    cfg = config.VerifierConfig()
    assert cfg.dv_keywords == {}
    assert cfg.dv_aliases == {}
    assert cfg.alpha == {}
    assert cfg.n == {}
    assert cfg.condition_labels == ()
    assert cfg.percent_dvs == frozenset()
    # headings keep usable defaults (they locate tables, not domain values)
    assert cfg.headings == config.DEFAULT_TABLE_HEADINGS
