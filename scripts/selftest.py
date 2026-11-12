#!/usr/bin/env python3
"""Self-test: runs the review on the bundled sample (a dental practice with planted problems)
in a temporary folder and checks that every planted problem is found. Takes a few seconds.

Usage:
  python selftest.py            # prints PASS/FAIL per check; exit code 0 when all pass
  python selftest.py --keep     # keep the temporary client folder to look at the reports
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE.parent / "assets" / "sample"


def sh(*args):
    r = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True)
    if r.returncode:
        print(r.stderr or r.stdout)
        sys.exit(f"selftest: {args[0]} failed")
    return json.loads(r.stdout[r.stdout.index("{"):])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="adreview_lite_selftest_"))
    client = tmp / "bright-smile"
    sh(HERE / "setup_client.py", "--dir", client, "--name", "Bright Smile Dental", "--preset", "lead_gen",
       "--brand", "bright smile", "--agency", "Selftest Agency")  # fmt: skip
    shutil.copy(SAMPLE / "targets.csv", client / "client" / "targets.csv")
    for f in ("google_ads_campaigns.csv", "meta_ads_campaigns.csv"):
        shutil.copy(SAMPLE / f, client / "exports" / f)
    res = sh(HERE / "run_review.py", "--client-dir", client, "--from", "2026-10-22", "--to", "2026-10-28")

    findings = json.loads((client / "work" / "findings_2026-10-28.json").read_text())["findings"]
    has = lambda camp, metric, sev=None: any(  # noqa: E731
        x["campaign_name"] == camp and x["metric"] == metric and (sev is None or x["severity"] == sev) for x in findings)
    html = (client / "out" / "2026-10-28_review.html").read_text(encoding="utf-8")

    checks = [
        ("imports: 2 files read", len([i for i in res["imported"] if "error" not in i]) == 2),
        ("tracking: Retargeting conversion drop is critical", has("Meta - Retargeting", "conversion_drop", "critical")),
        ("overspend: Performance Max spend pace is critical", has("Performance Max - New Patients", "spend_pace", "critical")),
        ("CPA: Dental Implants over target is critical", has("Search - Dental Implants", "cpa", "critical")),
        ("fatigue: Whitening Offer flagged", has("Meta - Whitening Offer", "fatigue")),
        ("fatigued campaign is not called an opportunity", not has("Meta - Whitening Offer", "winner")),
        ("winner: Emergency Dentist is an opportunity", has("Search - Emergency Dentist", "winner", "opportunity")),
        ("report: HTML written with agency name", "Prepared by Selftest Agency" in html and "Critical (3)" in html),
        ("report: no proposal section in the lite edition", "Proposed changes" not in html),
    ]  # fmt: skip
    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    passed = sum(ok for _, ok in checks)
    print(f"\n{passed}/{len(checks)} checks passed.")
    if a.keep:
        print(f"Client folder kept at: {client}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(0 if passed == len(checks) else 1)


if __name__ == "__main__":
    main()
