# Statement of need (JOSS paper skeleton)

> Working draft toward a JOSS (`paper.md`) submission. Sections follow the
> JOSS review criteria; numbers cite the real-world validation runs.

## Summary

`paper-verifier` is a deterministic audit tool for academic manuscripts. It
cross-checks every statistical claim in the text (F, p, β, CI, effect sizes,
reliability, sample sizes, means/SDs, percentages) against the authors' own
pre-computed analysis outputs, and audits citation integrity end-to-end
(reference list ↔ in-text citations ↔ attached source documents). An LLM is
optionally consulted for exactly one judgment — whether a paraphrase
semantically matches the cited source — and never for numbers.

## Statement of need

Between the analysis pipeline and the submitted PDF sits a long chain of
manual transcription: numbers are copied into prose, rounded, revised, and
reshuffled across drafts. Existing tools check *internal* consistency of
reported statistics (statcheck recomputes p from test statistics and degrees
of freedom) but cannot know whether the reported numbers match what the
authors' analysis actually produced — a transcription error that is
internally consistent passes every such check. Citation integrity has the
same gap: reference managers format entries but do not verify that every
in-text citation resolves, that every listed reference is actually cited, or
that a paraphrase still says what the cited paper said.

`paper-verifier` closes this gap by treating the authors' own cross-validated
analysis outputs as ground truth and diffing the manuscript against them 1:1,
with rounding-aware comparison at the manuscript's printed precision, and by
auditing the citation graph deterministically. It is fail-safe by design:
anything it cannot check is surfaced as MANUAL, an empty ground truth is a
hard failure rather than a silent pass, and the exit code makes the audit a
CI gate for manuscripts.

## State of the field

- **statcheck** (Epskamp & Nuijten) — recomputes p-values from reported test
  statistics; complementary (internal consistency vs. ground-truth
  consistency), no citation auditing.
- Reference managers (Zotero, EndNote) — format and deduplicate references;
  no manuscript-side claim or citation-graph verification.
- LLM-based manuscript checkers — flexible but non-deterministic; unsuited
  as the arbiter of numerical correctness.

## Functionality (validation)

Battle-tested on a real conference manuscript and its journal extension
(numbers from the production runs): 348 verification targets audited in one
run — 298 numerical claims across 15 claim types, 23 references, 56 in-text
citations — with zero numerical errors confirmed and one dangling citation
caught in a revision; ground truth was an R lme4 ↔ scipy cross-validated
table set (8/8 parity). The audit was reused unchanged for the journal
extension (41 references, 64 citations).

## TODO before submission

- [ ] Convert to `paper.md` + `paper.bib` in JOSS format
- [ ] Archive a tagged release (Zenodo DOI)
- [ ] Add author ORCID + affiliation
