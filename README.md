# paper-verifier

[![CI](https://github.com/taehyeonglim/paper-verifier/actions/workflows/ci.yml/badge.svg)](https://github.com/taehyeonglim/paper-verifier/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/paper-verifier)](https://pypi.org/project/paper-verifier/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**English** | [한국어](README.ko.md)

**Deterministic manuscript audit**: cross-check every statistical claim in
your manuscript against your *own* analysis outputs, and audit citation
integrity end-to-end — before a reviewer (or a reader) does.

Between your analysis pipeline and the submitted PDF sits a long chain of
manual transcription: numbers get copied into prose, rounded, revised, and
reshuffled across drafts. `paper-verifier` diffs the manuscript against the
numbers your pipeline actually produced, and verifies that the reference
list, the in-text citations, and the cited sources still agree with each
other. Python does all the checking; an LLM is (optionally) consulted for
exactly one thing — paraphrase semantics — and **never for numbers**.

## What it checks

**Statistical claims** (Phase 1, deterministic)
- Extracts 15 claim types from prose — `*F*(1, 28) = 5.21`, `*p* = .030`,
  `β`, `95% CI [...]`, `d_z`, `η²`, `α`, `N`, `*V*`, `*M*`/`*SD*`, `%`, `*r*` —
  APA-7 italics, typographic minus, and unicode glyphs included.
- Diffs each claim 1:1 against your ground-truth tables with
  **rounding-aware precision**: a claim passes only if it is a valid rounding
  of the true value at the manuscript's own printed decimal places.
- Guards against false alarms: multi-DV ambiguity, interaction/correlation
  contexts, effect-size CIs vs β CIs, condition misattribution — anything
  undecidable becomes MANUAL, never a fake PASS or FAIL.
- **Ground-truth gate**: if claims exist but no usable ground truth is
  configured, the run hard-FAILs instead of silently passing.

**Citation integrity** (Phase 1, deterministic)
- Parses APA-7 reference lists; extracts parenthetical, narrative, and
  semicolon-prefixed in-text citations (unicode surnames included).
- Cross-matches the citation graph: **orphans** (listed, never cited) and
  **danglings** (cited, not listed) are flagged.
- Attaches local source PDFs/fulltexts by author+year (±1-year fuzzy matches
  are WARNed, not certified).

**Paraphrase semantics** (Phase 2, opt-in)
- For substantive citations, extracts the relevant passage from the attached
  source and asks a local LLM CLI whether your paraphrase still says what the
  source says (purpose-based thresholds; background acknowledgments are
  skipped). No provider available → MANUAL, never a crash.

## Quickstart (3 minutes)

```bash
pip install paper-verifier
git clone https://github.com/taehyeonglim/paper-verifier
cd paper-verifier/examples/quickstart

paper-verify --config paper-verifier.toml --phase 1 --output-summary
```

Expected output on the bundled synthetic study (an "AI tutor vs static text"
experiment where every number is consistent by construction):

```
verification status:
  PASS       27
  WARN        8      # 5 PDFs not configured, 2 orphan refs, 1 TBD-DOI — all intentional demos
# exit code 0
```

Now break it on purpose — misspell a cited author and fake a p-value:

```bash
sed -i '' 's/(Novak, 2024)/(Nowak, 2024)/' manuscript.md   # macOS; drop '' on Linux
sed -i '' 's/\*p\* = .030/\*p\* = .041/' manuscript.md
paper-verify --config paper-verifier.toml --phase 1 ; echo "exit=$?"
```

```
FAIL  p_value claim=0.041 vs gt=0.030214 (digits=3, delta=0.0108)
FAIL  Dangling citation: (Nowak, 2024) — no matching ref entry
exit=1
```

That exit code makes it a CI gate: wire `paper-verify` into your manuscript
repository and an edit that contradicts your analysis breaks the build.

To use it on your paper, copy `examples/quickstart/paper-verifier.toml` and
declare your files and DV vocabulary — see
[docs/configuration.md](docs/configuration.md) and
[docs/input-formats.md](docs/input-formats.md).

## Real-world use

This tool was extracted from a research-automation system where it audited a
real conference manuscript and its journal extension:

- **348 verification targets** in one run — 298 numerical claims across 15
  claim types, 23 references, 56 in-text citations — with **0 numerical
  errors** confirmed against an R lme4 ↔ scipy cross-validated ground truth
  (8/8 parity), and **1 dangling citation caught** in a revision pass.
- The same audit was **reused unchanged for the journal extension** (41
  references, 64 in-text citations).

## vs. statcheck

[statcheck](https://github.com/MicheleNuijten/statcheck) recomputes p-values
from reported test statistics and flags *internal* inconsistencies.
`paper-verifier` answers a different question: **do the reported numbers
match what your analysis actually produced?** A transcription error that is
internally consistent sails through statcheck but fails here; a reporting
inconsistency with correct transcription does the reverse. Use both —
they're complementary. `paper-verifier` additionally audits the citation
graph and source attachment, which statcheck does not cover.

## Claude Code agents

The [`agents/`](agents/) directory ships two ready-made
[Claude Code](https://claude.com/claude-code) subagent definitions —
`paper-data-verifier` (statistics) and `paper-citation-auditor` (citations) —
that drive this CLI and interpret its reports. Copy them into your project's
`.claude/agents/` to use them.

## Configuration in one glance

```toml
[project]
manuscripts = ["sections/*.md"]
references  = "references.md"
stats       = "statistics_verification.md"   # your cross-validated analysis outputs

[stats]
condition_labels = ["AI", "TEXT"]

[stats.dv_keywords]
engagement = ["engagement"]

[stats.dv_aliases]
"Engagement" = "engagement"     # table row labels → DV keys
"참여도" = "engagement"          # non-English outputs: just declare the labels

[llm]
provider = "none"               # Phase 2 off; "codex"/"claude"/custom argv to enable
```

Everything domain-specific lives in this file; library defaults are empty and
fail-safe. Full reference: [docs/configuration.md](docs/configuration.md).

## Limitations (honest edition)

- It is a **comparator, not a recomputer**: ground truth comes from *your*
  analysis outputs in a fixed three-table markdown schema
  ([docs/input-formats.md](docs/input-formats.md)) — it does not rerun your
  models, and it inherits whatever is wrong in your tables. Cross-validate
  them (two implementations) before trusting the audit.
- Claim extraction is regex over lines: unusual formatting can hide a claim
  (silent miss) — skim `claims.jsonl` once to see what it caught.
- DOI checks are **presence-only** (never resolved against a registry).
- Phase 2 requires a local LLM CLI and inherits its nondeterminism; scores
  gate FAIL/PASS but every judgment is archived for review.
- Windows is untested (pathlib throughout, so it *should* work — reports
  welcome). Python ≥ 3.11.

## Citing

If this tool is useful in your research workflow, see
[CITATION.cff](CITATION.cff) (GitHub's "Cite this repository" button works).
A JOSS submission is planned — [docs/statement-of-need.md](docs/statement-of-need.md).

## License

[MIT](LICENSE) © 2026 Taehyeong Lim
