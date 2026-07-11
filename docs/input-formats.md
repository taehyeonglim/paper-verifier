# Input formats

All inputs are plain markdown. The `examples/quickstart/` files are working
samples of every format below.

## Manuscript (`--manuscript`, `[project].manuscripts`)

Any markdown prose. Claims are extracted line by line with APA-7-aware
patterns:

| Pattern | Claim type |
|---|---|
| `*F*(1, 28) = 5.21` (asterisks optional) | F_stat |
| `*p* = .030`, `p < .001` | p_value (`p_adj` matched first) |
| `β = 0.51` | beta |
| `d_z = 0.43`, `*d_z* = −0.13` | effect_dz |
| `α = .81` | alpha |
| `η² = .12`, `partial η² = .06` | eta_squared |
| `N = 30` (no italics) | N |
| `*V* = 312` | V_wilcoxon |
| `*M* = 5.42` / `*SD* = 0.83` (asterisks required) | M_mean / SD |
| `[0.07, 0.95]` | CI_pair |
| `78.4%` (decimal required) | percent |
| `*r* = .41` | r_corr |

Because extraction is per line, keep a claim and its context (DV keyword,
condition label) on the same line. A file whose name contains
`proceeding`/`combined`/`full` is treated as a combined manuscript and is
skipped for extraction whenever individual section files are also present
(no double counting).

## Reference list (`--references`)

APA-7 entries separated by blank lines, optionally preceded by YAML
frontmatter. Per entry:

- `Author, A., & Coauthor, B. (YYYY). Title. *Journal*, ...` — the first
  author's surname and year form the citation-matching key.
- A `https://doi.org/...` URL anywhere in the entry records the DOI
  (presence only — never resolved against a registry).
- `[TBD-DOI ...]` or `tbd:` marks a pending DOI → WARN.
- Lines starting with `>` are editorial notes and are skipped.

## Statistics verification file (`--stats`) — primary ground truth

Markdown tables located by heading substring (`[stats.headings]`; defaults
shown). Row labels resolve through `[stats.dv_aliases]`.

```markdown
## 1. p-value verification            ← headings key: p_table
| DV | F | df1 | df2 | R p | scipy p | match |

## 2. beta, SE, 95% CI                ← beta_table
| DV | β | SE | 95% CI | consistency |     (CI cell: `[low, high]`)

## 3. Wilcoxon + effect sizes         ← wilcoxon_table
| DV | V | p | r | r CI | dz | dz CI | n |  (dz is column 6)
```

This file is meant to be *produced by your own analysis pipeline* — ideally
cross-validated (e.g. R lme4 vs a scipy reimplementation) so the manuscript
is checked against numbers that two independent implementations agree on.

## Analysis summary (`--summary-stats`) — M/SD ground truth

Two supported table shapes; columns follow `[stats.condition_labels]` order:

- `[stats.summary_sections]` maps a heading to one DV; the table's `M (SD)`
  row carries `mean (sd)` cells per condition.
- `[stats.summary_dv_tables]` lists headings whose tables carry the DV label
  in column 0 (resolved via aliases).

```markdown
## 3.1 Engagement
| Metric | AI | TEXT |
|--------|----|------|
| M (SD) | 5.42 (0.83) | 4.91 (0.95) |
```

## Non-English analysis outputs

Nothing requires English inputs: table headings are configurable strings and
row labels go through `dv_aliases`, so a statistics file emitted in Korean
(or any language) works by declaring its headings and labels in the config.
