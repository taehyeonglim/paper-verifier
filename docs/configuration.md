# Configuration reference

One TOML file (conventionally `paper-verifier.toml`) declares everything
project-specific. `examples/quickstart/paper-verifier.toml` is a working,
fully commented instance. Relative paths resolve against the config file's
directory; CLI flags override config values.

**Fail-safe defaults**: with no config, all domain knowledge is empty —
numerical claims route to MANUAL and the ground-truth gate hard-FAILs when
claims exist. The tool never silently passes what it cannot check.

## `[project]`

| Key | Type | Meaning |
|---|---|---|
| `name` | str | project label used in the manifest and summary |
| `manuscripts` | list[str] | manuscript files — literal paths or globs |
| `references` | path | APA-7 reference list (omit → citation audit skipped, loud WARN) |
| `stats` | path | statistics verification file (primary ground truth) |
| `summary_stats` | path | analysis summary (M/SD ground truth) |
| `reports_dir` | path | report root; a `<sha8>` run dir is created inside |

## `[library]`

| Key | Type | Meaning |
|---|---|---|
| `root` | path | local paper library scanned for PDF/fulltext attachment. File names must contain the first author's surname and the year, under `{YYYY}_{Author}_*` or `{Author}_{YYYY}_*`. Unset → every reference WARNs "not found". |

## `[stats]`

| Key | Type | Meaning |
|---|---|---|
| `condition_labels` | list[str] (exactly 2) | condition labels as written in prose, in summary-table column order. Required for M/SD/percent verification. Pick prose-unique tokens — matching is substring-based. |
| `percent_dvs` | list[str] | DVs measured on a percent scale (only these match `percent` claims) |
| `modifier_keywords` | list[str] | replaces the default marker list ("interaction", "×", "approached significance", "spearman", "correlation between"); a p-value near any marker is not compared against the main-effect ground truth. Add your factor names (e.g. "topic", "order"). |

### `[stats.dv_keywords]`

`dv = ["keyword", ...]` — prose keywords that identify a DV. A claim's DV is
inferred only when exactly one DV's keywords match its line (ambiguity →
MANUAL, by design).

### `[stats.dv_aliases]`

`"Row Label" = "dv"` — ground-truth-table row labels → canonical DV key.
This is also the non-English-support mechanism (`"참여도" = "engagement"`).

### `[stats.alpha]` / `[stats.n]`

Reliability values per DV and sample sizes per context
(`analytic`/`collected`/`excluded`/`power`/`pilot`). Convention: KR-20 /
"Test A" / "Test B" phrasing routes alpha claims to `learning_A`/`learning_B`
keys.

### `[stats.headings]`

Substring locators for the three ground-truth tables:
`p_table` (default `"1. p-value"`), `beta_table` (`"2. beta"`),
`wilcoxon_table` (`"3. Wilcoxon"`). Override to match your pipeline's
section titles, in any language.

### `[stats.summary_sections]` / `summary_dv_tables`

See [input-formats.md](input-formats.md) — heading→DV map for `M (SD)`
tables, and headings whose tables carry DV labels in column 0.

## `[llm]` (Phase 2 only)

| Key | Type | Meaning |
|---|---|---|
| `provider` | str | `"codex"` (default), `"claude"`, or `"none"` (disable Phase 2 judgments → MANUAL) |
| `argv` | list[str] | custom command overriding the preset; the prompt is piped to stdin and a small JSON object is read from stdout. Use this to pin a model. |
| `timeout` | int | per-call timeout in seconds (default 120) |

Presets do not pin a model — your CLI's default applies. Example pin:

```toml
[llm]
argv = ["codex", "exec", "--sandbox", "read-only", "--skip-git-repo-check",
        "-c", 'model="gpt-5.6-terra"', "-"]
```

An unavailable provider never fails the run: paraphrase checks degrade to
MANUAL with an explicit reason.
