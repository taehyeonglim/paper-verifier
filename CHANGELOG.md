# Changelog

## Unreleased

- V2: Fail Phase 2 on incomplete/unknown result statuses and execution errors; upstream has no MAGI consensus adapter.
- V3: Reject missing configured inputs and unmatched manuscript globs; fail requested audits with zero references, numerical claims, or completed Phase-2 checks, including empty source text.
- V8: Parse the first JSON score object, accept only finite numbers in [0,1], and mark unscored semantic checks FAIL; invalid leading-dot JSON is now rejected.
- V1: Pin actual CLI/config manuscript and statistics loading with regressions; NERV-only --raw/--ground-truth flags remain explicit argparse errors upstream.
- V4: Preserve Unicode author keys, require whole author/year tokens, prefer DOI/title identity, and withhold ambiguous PDF attachments instead of selecting the shortest filename.
- V5: Preserve claim start/end offsets for p/CI/condition routing; legacy claims without offsets are routed only when their text occurs uniquely.
- V6: Preserve raw numeric tokens and compare each CI endpoint at its own printed precision, including trailing zeros and integer rounding; legacy raw_text remains supported.
- V7: Retain failed-parity/incomplete ground-truth rows with validation errors, report their claims as WARN, and exclude them from the usable-ground-truth gate.
- V9: Include summary-page FAIL (including a missing summary) in the CLI exit decision while preserving PASS/WARN exit behavior.

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
