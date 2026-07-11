# Changelog

## 0.1.0 — 2026-07-11

First public release, extracted from a private research-automation system
where it audited a real conference manuscript (348 verification targets,
0 numerical errors, 1 dangling citation caught) and its journal extension.

- Deterministic Phase 1: numerical-claim extraction (15 claim types,
  APA-7-aware), rounding-aware diff against user-supplied ground-truth
  tables, ground-truth gate (empty truth + claims present → hard FAIL),
  APA-7 reference parsing, citation graph audit (orphan/dangling),
  local-library PDF attachment with fuzzy-year WARN.
- Opt-in Phase 2: paraphrase semantic matching via a pluggable local LLM
  CLI (codex/claude presets, custom argv, `none` to disable); purpose-based
  thresholds; strict fail-safes (returncode, score range, classification
  sentinel).
- TOML configuration for all domain knowledge (DV keywords/aliases,
  reliability, sample sizes, condition labels, table headings) — empty,
  fail-safe library defaults; non-English analysis outputs supported via
  aliases and heading overrides.
- 147-test suite (no network, no LLM required), synthetic quickstart
  example, CI (test matrix + quickstart integration + package check),
  PyPI Trusted Publishing release workflow.
