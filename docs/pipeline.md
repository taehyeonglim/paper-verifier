# Pipeline

`paper-verify` runs a fixed sequence. Phase 1 is fully deterministic; Phase 2
adds one LLM-judged step.

```
1. ingest            manuscripts → sha256 manifest (manifest.json)
2. claim extraction  regex over prose → claims.jsonl
3. ground truth      statistics tables + summary stats → per-DV truth
   └─ GATE: claims exist but no table-derived truth → hard FAIL vr-0000
4. claim diff        each claim vs truth → verifications.jsonl
5. citation audit    references.md ↔ in-text citations → references.jsonl,
                     citations.jsonl (+ orphan/dangling verifications)
6. pdf attach        references ↔ local library → source_pdfs.jsonl
7. [phase 2] paraphrase semantic match via LLM CLI → paraphrase_matches.jsonl
8. summary           console counts (+ summary.md with --output-summary)
```

## Statuses

| Status | Meaning |
|---|---|
| `PASS` | claim matches ground truth within the manuscript's own rounding precision |
| `FAIL` | contradiction (wrong value, wrong df, dangling citation, empty ground truth gate, below-threshold paraphrase) |
| `WARN` | attention needed, not a contradiction (orphan reference, TBD-DOI, missing PDF, fuzzy-year PDF match) |
| `MANUAL` | cannot be decided deterministically (no DV keyword matched, no ground truth for this claim type, ambiguous context) |

## Exit code contract

`paper-verify` exits **1 if any verification target is FAIL**, else 0 — WARN
and MANUAL never fail a run. This makes the tool CI-friendly: wire it into a
pre-submission check and a manuscript edit that contradicts your analysis
breaks the build.

## The ground-truth gate

If the manuscript contains numerical claims but the statistics file yields no
table-derived ground truth (missing file, wrong headings, unmapped row
labels), the run hard-FAILs with `verifier: ground-truth-gate` instead of
letting every claim silently drain to MANUAL. A red gate usually means
`[stats.headings]` or `[stats.dv_aliases]` doesn't match your statistics
file — fix the config, don't remove the gate.

## Matching precision

A claim PASSes when it is a **valid rounding** of the ground-truth value at
the manuscript's own printed precision: `|observed − expected| ≤ 0.5 ULP` of
the printed decimal places (half-way values round both ways). A fixed
absolute tolerance would accept mis-rounded values; rounding the expected
value first would falsely fail exact halves.

## Report directory

Each run writes to `<reports_dir>/<sha8>/` where `sha8` derives from the
manuscript file hashes — the same manuscript bytes always map to the same
directory, and any edit produces a new one.

| File | Content |
|---|---|
| `manifest.json` | ingested files, sha256, word counts |
| `claims.jsonl` | extracted numerical claims |
| `references.jsonl` / `citations.jsonl` | parsed reference list / in-text citations |
| `source_pdfs.jsonl` | per-reference attachment results |
| `verifications.jsonl` | one record per verification target (the audit) |
| `paraphrase_matches.jsonl` | phase 2 only |
| `summary.md` | human-readable summary (`--output-summary`) |

`verifications.jsonl` is written once after the deterministic stages and
rewritten after Phase 2, so downstream tools can consume the Phase-1 state
even when Phase 2 runs.
