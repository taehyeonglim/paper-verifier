"""Manuscript audit verifier — CLI entry.

Usage:
    paper-verify --config paper-verifier.toml --phase 1 --output-summary

    # or fully via flags:
    paper-verify --manuscript "sections/*.md" \\
        --references references.md \\
        --stats statistics_verification.md

Phase 1 is fully deterministic: numerical-claim extraction, ground-truth
cross-check, reference/citation graph audit, local PDF attachment.
Phase 2 additionally delegates paraphrase semantic matching to a local LLM
CLI (optional; results degrade to MANUAL when no LLM is available).

Exit code: 1 if any verification target FAILed, else 0.
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from paper_verifier import claim_parser, config, doi_audit, ingest, pdf_attach
from paper_verifier import paraphrase_match, recompute_stats
from paper_verifier._lib import jsonl_io


# Ground-truth fields that only ever come from the statistics tables.
# ALPHA_GROUND_TRUTH is seeded independently of the file, so its presence must
# not count as "we have table ground truth".
_TABLE_GT_FIELDS = ("F", "p_R", "p_scipy", "beta", "SE",
                    "CI_low", "CI_high", "V", "p_wil", "r", "dz")


def has_table_ground_truth(primary_truth: dict) -> bool:
    """Whether any table-derived statistical field is present in the ground truth.

    load_ground_truth seeds reliability (alpha) values independently of the
    statistics file, so primary_truth can be non-empty even when the tables
    were empty or stale. Deciding the gate on ``not primary_truth`` would be
    vacuous (it could never fire); deciding on table-derived fields makes the
    gate detect exactly the fail-open it exists to prevent: F/p/β/dz/CI claims
    all silently draining to MANUAL.
    """
    return any(
        any(getattr(row, f, None) is not None for f in _TABLE_GT_FIELDS)
        for row in primary_truth.values()
    )


def _expand_spec(spec: str, base: Path) -> list[Path]:
    """Expand one manuscript spec (literal path or glob) against a base dir."""
    p = Path(spec)
    if not p.is_absolute():
        p = base / p
    if any(ch in spec for ch in "*?["):
        return [Path(m) for m in sorted(_glob.glob(str(p), recursive=True))]
    return [p]


def _display(path: Path) -> str:
    """Render a path relative to cwd when possible (shorter console output)."""
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="paper-verify",
        description="Deterministic manuscript audit: statistical claims vs your "
                    "own analysis outputs + reference/citation integrity.",
    )
    parser.add_argument("--config", type=Path, default=None,
                        help="paper-verifier.toml with project paths and domain knowledge.")
    parser.add_argument("--manuscript", action="append", default=None, metavar="PATH",
                        help="Manuscript .md file or glob (repeatable). "
                             "Overrides [project].manuscripts in the config.")
    parser.add_argument("--references", type=Path, default=None,
                        help="Reference list .md (APA 7 entries).")
    parser.add_argument("--stats", type=Path, default=None,
                        help="Statistics verification .md — primary ground-truth tables.")
    parser.add_argument("--summary-stats", type=Path, default=None,
                        help="Analysis summary .md — supplementary M/SD ground truth.")
    parser.add_argument("--phase", type=int, default=1, choices=[1, 2],
                        help="1 = deterministic only (default), 2 = + LLM paraphrase matching.")
    parser.add_argument("--output-summary", action="store_true",
                        help="Write a human-readable summary.md into the reports dir.")
    parser.add_argument("--check-summary-length", action="store_true",
                        help="Check that summary.md stays within a one-page line budget.")
    parser.add_argument("--reports-dir", type=Path, default=None,
                        help="Exact reports directory (default: <root>/.paper-verifier/<sha8>).")
    args = parser.parse_args(argv)

    cfg = config.load(args.config) if args.config else config.VerifierConfig()
    config.apply(cfg)

    # ── Resolve inputs (CLI > config) ────────────────────────────────────
    if args.manuscript:
        specs, spec_base = list(args.manuscript), Path.cwd()
    else:
        specs, spec_base = list(cfg.manuscripts), cfg.base_dir
    manuscript_paths: list[Path] = []
    seen: set[Path] = set()
    for spec in specs:
        for p in _expand_spec(str(spec), spec_base):
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                manuscript_paths.append(rp)
    if not manuscript_paths:
        parser.error("no manuscript files specified "
                     "(use --manuscript or [project].manuscripts in --config)")
    missing = [p for p in manuscript_paths if not p.exists()]
    if missing:
        parser.error("manuscript file(s) not found: "
                     + ", ".join(str(p) for p in missing))

    refs_path = args.references or cfg.references
    if refs_path is None:
        print("WARN: no references file configured — reference/citation audit SKIPPED",
              file=sys.stderr)
    elif not refs_path.exists():
        print(f"WARN: references file not found ({refs_path}) — "
              "reference/citation audit SKIPPED", file=sys.stderr)
        refs_path = None

    stats_path = args.stats or cfg.stats
    summary_stats_path = args.summary_stats or cfg.summary_stats

    # ── 1. Ingest ────────────────────────────────────────────────────────
    manuscripts = ingest.ingest_files(manuscript_paths)
    manifest = ingest.to_manifest(manuscripts, project=cfg.name)
    sha_prefix = manifest["manifest_sha256_prefix8"]
    if args.reports_dir is not None:
        reports_dir = args.reports_dir
    elif cfg.reports_dir is not None:
        reports_dir = cfg.reports_dir / sha_prefix
    else:
        reports_dir = Path.cwd() / ".paper-verifier" / sha_prefix
    reports_dir.mkdir(parents=True, exist_ok=True)

    (reports_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # A combined manuscript file duplicates the individual sections, so
    # extracting from both would double-count every claim/citation. When any
    # content section is present, the combined file is skipped for extraction
    # (section labels win); a lone combined file is extracted as-is.
    _CONTENT_SECTIONS = {"intro", "methods", "results", "discussion", "conclusion"}
    _has_content_sections = any(m.section in _CONTENT_SECTIONS for m in manuscripts)

    def _skip_duplicate_combined(m) -> bool:
        return _has_content_sections and m.section == "combined"

    # ── 2. Numerical claim extraction ────────────────────────────────────
    all_claims: list = []
    claim_idx = 1
    for m in manuscripts:
        if _skip_duplicate_combined(m):
            continue
        path = Path(m.file_path)
        if not path.exists():
            continue
        claims = claim_parser.extract_from_file(path, m.id, m.section)
        for c in claims:
            c.id = f"claim-{claim_idx:04d}"
            claim_idx += 1
        all_claims.extend(claims)
    jsonl_io.write_all(reports_dir / "claims.jsonl",
                        claim_parser.to_records(all_claims))

    # ── 3. Ground truth load + claim verification ────────────────────────
    # primary_truth comes from the statistics verification tables (the
    # cross-validated F/p/β/dz/CI ground truth). The supplementary summary
    # only fills M/SD/percent, so it is tracked separately. Unreadable or
    # missing files converge to "no primary truth" and are handled by the
    # gate below instead of crashing (fail-safe).
    if stats_path is None:
        print("WARN: no statistical ground truth configured (--stats) — "
              "numerical claims cannot be verified", file=sys.stderr)
        primary_truth = {}
    else:
        try:
            primary_truth = recompute_stats.load_ground_truth(stats_path)
        except (OSError, ValueError) as e:
            print(f"WARN: primary ground truth unreadable ({stats_path}): {e}",
                  file=sys.stderr)
            primary_truth = {}
    has_table_gt = has_table_ground_truth(primary_truth)
    if stats_path is not None and not has_table_gt:
        print(f"WARN: primary statistical ground truth empty/stale from {stats_path}",
              file=sys.stderr)
    truth = dict(primary_truth)
    if summary_stats_path is not None and summary_stats_path.exists():
        truth = recompute_stats.merge_analysis_summary(truth, summary_stats_path)

    verifications = []
    # Ground-truth gate: statistical claims exist but no table-derived ground
    # truth is available → hard FAIL. Without this gate every F/p/β/dz/CI claim
    # would silently drain to MANUAL (fail-open) while the run still exits 0.
    if not has_table_gt and all_claims:
        gt_label = str(stats_path) if stats_path is not None else "<not configured>"
        verifications.append(recompute_stats.VerificationResult(
            id="vr-0000", target_type="ground-truth",
            target_id=gt_label,
            verifier="ground-truth-gate", status="FAIL",
            evidence=(f"Primary statistical ground truth (cross-validated tables) "
                      f"empty/stale ({gt_label}); {len(all_claims)} numerical claim(s) "
                      f"lack ground truth — fail-open prevented"),
        ))
    for i, c in enumerate(all_claims, 1):
        vr = recompute_stats.verify_claim(asdict(c), truth, i)
        verifications.append(vr)

    # ── 4. Reference/citation audit + PDF attachment ─────────────────────
    refs: list = []
    citations: list = []
    orphans: list = []
    dangling: list = []
    pdfs: list = []
    if refs_path is not None:
        refs = doi_audit.parse_references(refs_path)
        cite_idx = 1
        for m in manuscripts:
            if m.section == "refs":  # the reference list itself is not prose
                continue
            if _skip_duplicate_combined(m):
                continue
            path = Path(m.file_path)
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            new_cites = doi_audit.extract_citations(text, m.id, m.section, starting_idx=cite_idx)
            cite_idx += len(new_cites)
            citations.extend(new_cites)
        citations, orphans, dangling = doi_audit.link_citations(citations, refs)

        pdfs = pdf_attach.attach_pdfs(refs, library_root=cfg.library_root)

        jsonl_io.write_all(reports_dir / "references.jsonl",
                            doi_audit.to_ref_records(refs))
        jsonl_io.write_all(reports_dir / "citations.jsonl",
                            doi_audit.to_cite_records(citations))
        jsonl_io.write_all(reports_dir / "source_pdfs.jsonl",
                            pdf_attach.to_records(pdfs))

        next_vr = len(verifications) + 1
        for r in refs:
            if r.status == "tbd-doi":
                status = "WARN"
                evidence = f"TBD-DOI: {r.notes or 'DOI not identified yet — resolve manually'}"
            elif r.doi is None and r.status != "software":
                status = "WARN"
                evidence = "DOI missing and not a software citation — resolve via Crossref/publisher"
            else:
                status = "PASS"
                # DOI presence is a string check only — it is NOT resolved
                # against a registry, so evidence must not overclaim.
                evidence = (f"DOI present (string only, not resolved against registry): {r.doi}"
                            if r.doi else "Software citation")
            verifications.append(recompute_stats.VerificationResult(
                id=f"vr-{next_vr:04d}", target_type="reference-entry", target_id=r.id,
                verifier="doi-audit", status=status, evidence=evidence,
            ))
            next_vr += 1
        for c in citations:
            if c.ref_id is None:
                verifications.append(recompute_stats.VerificationResult(
                    id=f"vr-{next_vr:04d}", target_type="in-text-citation",
                    target_id=c.id, verifier="citation-graph", status="FAIL",
                    evidence=f"Dangling citation: ({c.first_author_last}, {c.year}) — no matching ref entry",
                ))
                next_vr += 1
        for orphan_id in orphans:
            verifications.append(recompute_stats.VerificationResult(
                id=f"vr-{next_vr:04d}", target_type="reference-entry",
                target_id=orphan_id, verifier="citation-graph", status="WARN",
                evidence="Orphan reference — listed but not cited in body",
            ))
            next_vr += 1
        for pdf in pdfs:
            if pdf.pdf_path and pdf.source_kind == "library-collected-yearfuzzy":
                # ±1-year fuzzy match may be a different paper — WARN, not PASS.
                status = "WARN"
                evidence = (f"PDF attached via ±1yr fuzzy match (verify it's the right paper): "
                            f"{pdf.pdf_path}")
            elif pdf.pdf_path:
                status = "PASS"
                evidence = f"PDF attached: {pdf.pdf_path}"
            else:
                status = "WARN"
                evidence = ("PDF/fulltext not found under the library root — "
                            "attach manually or configure [library].root")
            verifications.append(recompute_stats.VerificationResult(
                id=f"vr-{next_vr:04d}", target_type="reference-entry",
                target_id=pdf.ref_id, verifier="pdf-attach", status=status,
                evidence=evidence,
            ))
            next_vr += 1

    # Phase 2 reads verifications.jsonl as input, so the Phase-1 state must be
    # on disk before Phase 2 runs (a later rewrite adds the Phase-2 results).
    jsonl_io.write_all(reports_dir / "verifications.jsonl",
                        recompute_stats.to_records(verifications))

    # ── Phase 2: LLM paraphrase semantic matching (opt-in) ───────────────
    if args.phase >= 2 and refs and citations:
        para_matches = paraphrase_match.match_paraphrases(citations, pdfs, refs)
        if para_matches:
            jsonl_io.write_all(reports_dir / "paraphrase_matches.jsonl",
                                paraphrase_match.to_records(para_matches))
            print(f"\nparaphrase matches: {len(para_matches)}")
            para_status_counts = Counter(m.status for m in para_matches)
            for st, n in para_status_counts.most_common():
                print(f"  {st:8s} {n:>4d}")
            # Fold paraphrase results into verifications so a paraphrase FAIL
            # is reflected in the exit code and the summary, with each match's
            # own status (not an ad-hoc score bucket).
            for pm in para_matches:
                verifications.append(recompute_stats.VerificationResult(
                    id=f"vr-{len(verifications) + 1:04d}",
                    target_type="paraphrase-match", target_id=pm.citation_id,
                    verifier=pm.verifier, status=pm.status,
                    evidence=f"paraphrase score={pm.score} ref={pm.ref_id}",
                ))

    # Rewrite with the Phase-2 additions included (final state).
    jsonl_io.write_all(reports_dir / "verifications.jsonl",
                        recompute_stats.to_records(verifications))

    # ── 5. Console summary ───────────────────────────────────────────────
    status_counts = Counter(v.status for v in verifications)
    type_counts = Counter(c.claim_type for c in all_claims)

    print(f"\n=== Manuscript Audit — Phase {args.phase} ===")
    print(f"manifest sha: {sha_prefix}")
    print(f"manuscripts:  {len(manuscripts)}")
    print(f"claims:       {len(all_claims)}")
    print(f"verifications: {len(verifications)}")
    print()
    print("claim_type distribution:")
    for ct, n in type_counts.most_common():
        print(f"  {ct:18s} {n:>4d}")
    print()
    print("verification status:")
    for st, n in status_counts.most_common():
        print(f"  {st:8s} {n:>4d}")
    print()
    print(f"reports dir: {_display(reports_dir)}")

    if args.output_summary:
        write_summary_md(reports_dir, manuscripts, all_claims, verifications, truth,
                         sha_prefix, project=cfg.name,
                         stats_label=str(stats_path) if stats_path else None)
        print(f"summary.md: {_display(reports_dir / 'summary.md')}")

    if args.check_summary_length:
        from paper_verifier._lib.summary_page_check import check_summary_page_count
        summary_md = reports_dir / "summary.md"
        page_check = check_summary_page_count(summary_md)
        print("\n=== summary.md length check ===")
        print(f"  lines:  {page_check.line_count}")
        print(f"  status: {page_check.status}")
        print(f"  msg:    {page_check.message}")

    fail_count = status_counts.get("FAIL", 0)
    return 0 if fail_count == 0 else 1


def write_summary_md(reports_dir, manuscripts, claims, verifications, truth,
                     sha_prefix, project: str = "manuscript",
                     stats_label: str | None = None):
    from collections import Counter
    status_counts = Counter(v.status for v in verifications)
    type_counts = Counter(c.claim_type for c in claims)
    dv_counts = Counter(v.matched_dv for v in verifications if v.matched_dv)

    pass_n = status_counts.get("PASS", 0)
    fail_n = status_counts.get("FAIL", 0)
    warn_n = status_counts.get("WARN", 0)
    manual_n = status_counts.get("MANUAL", 0)
    total = len(verifications)
    pass_pct = (100.0 * pass_n / total) if total else 0.0

    # The verdict line is derived from the actual FAIL composition. A previous
    # revision hardcoded "0 numerical errors" regardless of results, which
    # could lull a human reader while numerical FAILs existed — the breakdown
    # below must always be computed, never asserted.
    numerical_fail = sum(1 for v in verifications
                         if v.status == "FAIL" and v.target_type == "numerical-claim")
    citation_fail = sum(1 for v in verifications
                        if v.status == "FAIL"
                        and v.target_type in ("in-text-citation", "reference-entry"))
    other_fail = fail_n - numerical_fail - citation_fail
    fail_breakdown = f"numerical-claim {numerical_fail}, citation/reference {citation_fail}"
    if other_fail:
        fail_breakdown += f", other {other_fail}"
    lines = [
        f"# Manuscript Audit Summary — {project}",
        "",
        f"- generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- manifest sha prefix: `{sha_prefix}`",
        f"- target: {project} ({len(manuscripts)} file(s))",
        f"- ground truth: {stats_label or 'not configured'}",
        "",
        "## Verdict",
        "",
        "This report cross-checks the manuscript's statistical claims and its",
        "reference/citation integrity against pre-computed analysis outputs.",
        f"Of {total} verification targets, {fail_n} FAILed ({pass_pct:.1f}% PASS).",
        f"FAIL breakdown: {fail_breakdown}.",
        f"{manual_n} MANUAL items — claims outside the ground-truth sweep "
        "(spot-check recommended).",
        "",
        "## Pass rate",
        "",
        f"- PASS: {pass_n} / {total} ({pass_pct:.1f}%)",
        f"- FAIL: {fail_n}",
        f"- WARN: {warn_n}",
        f"- MANUAL review needed: {manual_n}",
        "",
        "## NumericalClaim distribution",
        "",
        "| claim_type | count |",
        "|---|---|",
    ]
    for ct, n in type_counts.most_common():
        lines.append(f"| {ct} | {n} |")
    lines += [
        "",
        "## DV match distribution",
        "",
        "| DV | matched claims |",
        "|---|---|",
    ]
    for dv, n in dv_counts.most_common():
        lines.append(f"| {dv} | {n} |")
    lines += [
        "",
        "## Ground truth coverage",
        "",
        f"- DV with ground truth: {len(truth)} ({', '.join(sorted(truth.keys()))})",
        "",
        "## FAIL detail",
        "",
    ]
    fails = [v for v in verifications if v.status == "FAIL"]
    if not fails:
        lines.append("(none — 0 FAIL)")
    else:
        for v in fails[:20]:
            lines.append(f"- `{v.target_id}` ({v.matched_dv}) {v.evidence}")
        if len(fails) > 20:
            lines.append(f"  ... and {len(fails) - 20} more")
    lines += [
        "",
        "## MANUAL review",
        "",
        f"`{manual_n}` items, by claim_type:",
        "",
    ]
    manual_by_type = Counter()
    for v in verifications:
        if v.status == "MANUAL":
            cid = v.target_id
            claim = next((c for c in claims if c.id == cid), None)
            if claim:
                manual_by_type[claim.claim_type] += 1
    for ct, n in manual_by_type.most_common():
        lines.append(f"- {ct}: {n}")
    lines += [
        "",
        "## Notes",
        "",
        "- MANUAL items (e.g. M_mean/SD/percent/N/alpha) usually need ground truth "
        "added to the summary-stats file, or a quick human spot-check.",
        "- Adjusted p-values (p_adj) need their own recomputed ground truth and are "
        "always routed to MANUAL.",
        "",
    ]
    (reports_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
