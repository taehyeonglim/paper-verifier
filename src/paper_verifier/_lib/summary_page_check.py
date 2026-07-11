"""summary.md one-page length check.

Some venues want the audit summary attached as a single page. This check
estimates page fit from the markdown line count instead of rendering a PDF
(a real page count would drag in pandoc + xelatex). Calibrated for an
A4 / 11pt / 1.5-line-spacing render:

  ≤70 lines: PASS (fits one page comfortably)
  71-85    : WARN (borderline — verify with an actual print/render)
  >85      : FAIL (likely exceeds one page)

Code blocks (```), tables (|) and blank lines all count as-is — they occupy
space in the rendered PDF too.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class PageCheckResult:
    path: str
    line_count: int
    threshold_pass: int = 70
    threshold_warn: int = 85
    status: str = "PASS"   # PASS / WARN / FAIL
    message: str = ""


def check_summary_page_count(
    summary_path: Path,
    threshold_pass: int = 70,
    threshold_warn: int = 85,
) -> PageCheckResult:
    """Estimate one-page fit of summary.md from its line count.

    Args:
        summary_path: path to summary.md
        threshold_pass: PASS at or below this many lines (default 70)
        threshold_warn: WARN at or below this, FAIL above (default 85)

    Returns:
        PageCheckResult — status + line_count + thresholds + message
    """
    if not summary_path.exists():
        return PageCheckResult(
            path=str(summary_path), line_count=0,
            threshold_pass=threshold_pass, threshold_warn=threshold_warn,
            status="FAIL",
            message=f"summary.md not found at {summary_path}",
        )
    text = summary_path.read_text(encoding="utf-8")
    # A trailing final newline is not a line (same behavior as wc -l).
    lines = text.splitlines()
    n = len(lines)
    if n <= threshold_pass:
        status = "PASS"
        msg = f"{n} lines ≤ {threshold_pass} — fits one page"
    elif n <= threshold_warn:
        status = "WARN"
        msg = (f"{n} lines (≤{threshold_warn}) — borderline one-page fit; verify with "
               "an actual render (tables/code blocks can grow in PDF).")
    else:
        status = "FAIL"
        msg = (f"{n} lines > {threshold_warn} — likely exceeds one page; trim the "
               "summary (shorten background prose or keep only the key tables).")
    return PageCheckResult(
        path=str(summary_path), line_count=n,
        threshold_pass=threshold_pass, threshold_warn=threshold_warn,
        status=status, message=msg,
    )


def to_record(result: PageCheckResult) -> dict:
    return asdict(result)
