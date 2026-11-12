#!/usr/bin/env python3
"""Run the whole review in one command for a client folder made by setup_client.py.

  1. imports every .csv/.tsv in <client-dir>/exports (re-importing is safe: days are replaced)
  2. evaluates the review period (default: the preset's review length, ending on the last day in the data)
  3. writes the report as Markdown and as a client-ready HTML page in <client-dir>/out

Each step is a separate script, so any step can still be run on its own.

Usage:
  python run_review.py --client-dir clients/bright-smile
  python run_review.py --client-dir clients/bright-smile --from 2026-10-22 --to 2026-10-28
  python run_review.py --client-dir clients/acme-pools --from 2026-06-01 --to 2026-06-07 \
      --compare-from 2025-06-02 --compare-to 2025-06-08          # seasonal: vs same week last year
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import ad_common as ad

HERE = Path(__file__).resolve().parent
FULL_VERSION_NOTE = (
    "Search term reports are imported but not analysed in the lite edition. The full Ad Spend Review "
    "adds wasted search-term analysis, capped and reversible change proposals, a decision log and a "
    "follow-up of every approved change: https://monaakservices.com"
)


def run(script: str, *args: str, allow_fail: bool = False) -> dict:
    cmd = [sys.executable, str(HERE / script), *args]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 and not allow_fail:
        ad.die(f"{script} failed:\n{res.stderr.strip() or res.stdout.strip()}")
    try:
        start = res.stdout.index("{")
        return json.loads(res.stdout[start:])
    except ValueError:
        return {"raw": res.stdout.strip(), "error": res.stderr.strip()}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--client-dir", required=True)
    p.add_argument("--from", dest="start", default="")
    p.add_argument("--to", dest="end", default="")
    p.add_argument("--compare-from", default="")
    p.add_argument("--compare-to", default="")
    p.add_argument("--skip-import", action="store_true")
    a = p.parse_args()

    root = Path(a.client_dir)
    cdir, work, out, exports = root / "client", root / "work", root / "out", root / "exports"
    cj = cdir / "client.json"
    if not cj.exists():
        ad.die(f"No {cj}. Run setup_client.py first.")
    client = json.loads(cj.read_text())
    thresholds, targets = cdir / "thresholds.json", cdir / "targets.csv"
    steps = {}

    # 1. import
    if not a.skip_import:
        files = sorted([f for f in exports.glob("*") if f.suffix.lower() in (".csv", ".tsv", ".txt")])
        if not files and not (work / "metrics.csv").exists():
            ad.die(f"No exports in {exports}. See references/exporting.md.")
        imported = []
        for f in files:
            r = run("normalize_export.py", "--input", str(f), "--work", str(work), allow_fail=True)
            if "kind" not in r:
                imported.append({"file": f.name, "error": r.get("error") or r.get("raw")})
                continue
            imported.append({"file": f.name, "kind": r["kind"], "platform": r["platform"],
                             "rows": r.get("campaign_days", r.get("rows")), "missing_columns": r.get("missing_columns", [])})  # fmt: skip
        steps["imported"] = imported
        if any("error" in i for i in imported):
            steps["import_warning"] = "Some files couldn't be read; run normalize_export.py --show-columns on them."
        if any(i.get("kind") == "search_terms" for i in imported):
            steps["search_terms_note"] = FULL_VERSION_NOTE

    # 2. period
    rows = ad.read_metrics(work / "metrics.csv")
    if not rows:
        ad.die("No campaign data imported.")
    last = max(r["date"] for r in rows)
    end = a.end or last.isoformat()
    start = a.start or (ad.parse_date(end) - timedelta(days=int(client.get("review_days", 7)) - 1)).isoformat()
    period = ["--from", start, "--to", end]
    compare = ["--compare-from", a.compare_from, "--compare-to", a.compare_to] if a.compare_from and a.compare_to else []

    # 3. evaluate
    findings = work / f"findings_{end}.json"
    ev = run("evaluate.py", "--metrics", str(work / "metrics.csv"), "--targets", str(targets), "--thresholds", str(thresholds),
             *period, *compare, "--out", str(findings))  # fmt: skip
    steps["evaluate"] = {"counts": ev["counts"], "data_notes": ev["data_notes"]}

    # 4. report
    md = out / f"{end}_review.md"
    rep_args = ["--findings", str(findings), "--client", client["name"]]
    run("report.py", *rep_args, "--out", str(md))
    html = out / f"{end}_review.html"
    run("report.py", *rep_args, "--out", str(html), "--format", "html", "--agency", client.get("agency", ""))

    ad.emit({"client": client["name"], "preset": client.get("preset"), "period": {"from": start, "to": end},
             **steps, "top_findings": ev["findings"][:8], "report_markdown": str(md), "report_html": str(html),
             "next": "Read the report with the person and lead with the 2-3 findings that matter most."})  # fmt: skip


if __name__ == "__main__":
    main()
