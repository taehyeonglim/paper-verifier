"""CLI end-to-end tests against synthetic files in tmp_path.

Covers the --manuscript regression (files passed on the CLI must actually be
ingested — a legacy version ignored them in favor of a hardcoded file set),
the no-ground-truth gate, and config-file-driven runs.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from paper_verifier import ingest, verify
from paper_verifier._lib import jsonl_io

STATS_MD = """
## 1. p-value verification (R vs scipy)

| DV | F | df1 | df2 | R p | scipy p | match |
|----|---|-----|-----|-----|---------|------|
| Manipulation Check | 7.634 | 1 | 36 | .008965 | .008966 | ✓ |
"""

REFS_MD = """---
total_references: 2
---

Kim, J. (2024). A study of things. *Journal of Stuff*, 1(1), 1-10.
https://doi.org/10.1000/example.2024.001

Lee, S. (2023). Another study. *Journal of Stuff*, 2(2), 11-20.
https://doi.org/10.1000/example.2023.002
"""


MIN_CFG_TOML = """
[stats.dv_keywords]
manipulation_check = ["uncanniness", "manipulation check"]

[stats.dv_aliases]
"Manipulation Check" = "manipulation_check"
"""


def _write_min_cfg(tmp_path):
    """Domain knowledge only (no paths) — files still come from CLI flags."""
    p = tmp_path / "min.toml"
    p.write_text(MIN_CFG_TOML, encoding="utf-8")
    return p


def test_manuscript_flags_are_actually_ingested(tmp_path):
    """Regression: every --manuscript file must contribute claims."""
    a = tmp_path / "results_a.md"
    a.write_text("The manipulation check showed *F*(1, 36) = 7.63.", encoding="utf-8")
    b = tmp_path / "results_b.md"
    b.write_text("For uncanniness, *p* = .009 was observed.", encoding="utf-8")
    stats = tmp_path / "stats.md"
    stats.write_text(STATS_MD, encoding="utf-8")
    out = tmp_path / "reports"

    rc = verify.main(["--config", str(_write_min_cfg(tmp_path)),
                      "--manuscript", str(a), "--manuscript", str(b),
                      "--stats", str(stats), "--reports-dir", str(out)])
    assert rc == 0

    claims = list(jsonl_io.read_all(out / "claims.jsonl"))
    sources = {c["manuscript_id"] for c in claims}
    assert len(sources) == 2, f"claims must come from both files, got {claims}"
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["files"]) == 2


def test_manuscript_glob_expansion(tmp_path):
    (tmp_path / "sec1_results.md").write_text("uncanniness *F*(1, 36) = 7.63", encoding="utf-8")
    (tmp_path / "sec2_discussion.md").write_text("no numbers here", encoding="utf-8")
    stats = tmp_path / "stats.md"
    stats.write_text(STATS_MD, encoding="utf-8")
    out = tmp_path / "reports"

    rc = verify.main(["--config", str(_write_min_cfg(tmp_path)),
                      "--manuscript", str(tmp_path / "sec*.md"),
                      "--stats", str(stats), "--reports-dir", str(out)])
    assert rc == 0
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["files"]) == 2


def test_no_manuscript_is_a_usage_error():
    with pytest.raises(SystemExit) as e:
        verify.main([])
    assert e.value.code == 2  # argparse usage error


@pytest.mark.parametrize("flag", ["--raw", "--ground-truth"])
def test_nerv_only_input_flags_are_explicitly_rejected(flag, capsys):
    """Upstream has no raw-CSV adapter; unsupported inputs must not be ignored."""
    with pytest.raises(SystemExit) as exc:
        verify.main([flag, "unused.csv"])
    assert exc.value.code == 2
    assert f"unrecognized arguments: {flag} unused.csv" in capsys.readouterr().err


def test_cli_inputs_override_config_in_actual_loaders(tmp_path):
    """CLI manuscript/stats paths override even missing configured defaults."""
    cfg = tmp_path / "paper.toml"
    cfg.write_text(
        '[project]\nmanuscripts = ["unused.md"]\nstats = "unused-stats.md"\n'
        + MIN_CFG_TOML, encoding="utf-8",
    )
    manuscript = tmp_path / "chosen.md"
    manuscript.write_text("uncanniness *F*(1, 36) = 7.63", encoding="utf-8")
    stats = tmp_path / "chosen-stats.md"
    stats.write_text(STATS_MD, encoding="utf-8")
    reports = tmp_path / "reports"
    rc = verify.main(["--config", str(cfg), "--manuscript", str(manuscript),
                      "--stats", str(stats), "--reports-dir", str(reports)])
    assert rc == 0
    manifest = json.loads((reports / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["files"]) == 1
    assert manifest["files"][0]["file_path"] == str(manuscript)
    results = list(jsonl_io.read_all(reports / "verifications.jsonl"))
    assert len(results) == 1
    assert results[0]["status"] == "PASS"
    assert results[0]["expected_value"] == 7.634


def test_gate_fires_without_ground_truth(tmp_path):
    """Statistical claims + no --stats → ground-truth gate hard FAIL (exit 1)."""
    m = tmp_path / "results.md"
    m.write_text("The manipulation check showed *F*(1, 36) = 7.63.", encoding="utf-8")
    out = tmp_path / "reports"

    rc = verify.main(["--manuscript", str(m), "--reports-dir", str(out)])
    assert rc == 1
    vrs = list(jsonl_io.read_all(out / "verifications.jsonl"))
    gate = [v for v in vrs if v["verifier"] == "ground-truth-gate"]
    assert len(gate) == 1 and gate[0]["status"] == "FAIL"


def test_references_only_run_passes(tmp_path):
    """Citation audit works without any statistical ground truth."""
    m = tmp_path / "body.md"
    m.write_text("Prior work (Kim, 2024) and follow-ups (Lee, 2023) agree.",
                 encoding="utf-8")
    refs = tmp_path / "references.md"
    refs.write_text(REFS_MD, encoding="utf-8")
    out = tmp_path / "reports"

    rc = verify.main(["--manuscript", str(m), "--references", str(refs),
                      "--reports-dir", str(out)])
    assert rc == 0
    refs_out = list(jsonl_io.read_all(out / "references.jsonl"))
    assert len(refs_out) == 2
    cites = list(jsonl_io.read_all(out / "citations.jsonl"))
    assert len(cites) == 2


def test_config_file_end_to_end(tmp_path):
    (tmp_path / "sections").mkdir()
    (tmp_path / "sections" / "results.md").write_text(
        "uncanniness *F*(1, 36) = 7.63", encoding="utf-8")
    (tmp_path / "stats.md").write_text(STATS_MD, encoding="utf-8")
    toml = tmp_path / "paper-verifier.toml"
    toml.write_text(
        """
[project]
name = "cfg-demo"
manuscripts = ["sections/*.md"]
stats = "stats.md"
reports_dir = "out"

[stats.dv_keywords]
manipulation_check = ["uncanniness", "manipulation check"]

[stats.dv_aliases]
"Manipulation Check" = "manipulation_check"
""",
        encoding="utf-8",
    )
    rc = verify.main(["--config", str(toml)])
    assert rc == 0
    run_dirs = list((tmp_path / "out").iterdir())
    assert len(run_dirs) == 1  # reports under <reports_dir>/<sha8>
    manifest = json.loads((run_dirs[0] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["project"] == "cfg-demo"


def test_infer_section_labels():
    assert ingest.infer_section(Path("introduction_en_v1.md")) == "intro"
    assert ingest.infer_section(Path("methods.md")) == "methods"
    assert ingest.infer_section(Path("results_final.md")) == "results"
    assert ingest.infer_section(Path("discussion.md")) == "discussion"
    assert ingest.infer_section(Path("conclusion.md")) == "conclusion"
    assert ingest.infer_section(Path("references_apa7.md")) == "refs"
    assert ingest.infer_section(Path("proceedings_v1.md")) == "combined"
    assert ingest.infer_section(Path("full_manuscript.md")) == "combined"
    assert ingest.infer_section(Path("notes.md")) == "body"
