#!/usr/bin/env python3
"""Set up a client folder in one step, from an industry preset.

Creates:
  <dir>/client/client.json      name, preset, brand words, agency name, review length
  <dir>/client/thresholds.json  the preset's full thresholds (tune here, per client)
  <dir>/client/targets.csv      one row per campaign to fill in (goal, targets, daily budget)
  <dir>/exports/                drop the platform exports here
  <dir>/work/  <dir>/out/

Presets: lead_gen, local_services, ecommerce, b2b, saas_trial  (see references/presets.md)

Usage:
  python setup_client.py --dir clients/bright-smile --name "Bright Smile Dental" --preset lead_gen \
      --brand "bright smile" --agency "Monaak Services"
  python setup_client.py --list-presets
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import ad_common as ad


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir")
    p.add_argument("--name")
    p.add_argument("--preset", default="lead_gen")
    p.add_argument("--brand", default="", help="Comma-separated brand words")
    p.add_argument("--agency", default="", help="Shown on the client report as 'Prepared by'")
    p.add_argument("--campaigns", default="", help="Optional comma-separated campaign names to pre-fill targets.csv")
    p.add_argument("--force", action="store_true", help="Overwrite an existing client.json/thresholds.json")
    p.add_argument("--list-presets", action="store_true")
    a = p.parse_args()

    if a.list_presets:
        out = {}
        for f in sorted(ad.PRESETS_DIR.glob("*.json")):
            pr = json.loads(f.read_text())
            out[f.stem] = {"label": pr["_label"], "for": pr["_description"], "review_days": pr["_review_days"],
                           "default_goal": pr["_goal"]}  # fmt: skip
        ad.emit(out)
        return
    if not a.dir or not a.name:
        ad.die("--dir and --name are required")

    preset = ad.load_preset(a.preset)
    root = Path(a.dir)
    for sub in ("client", "exports", "work", "out"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    cj = root / "client" / "client.json"
    if cj.exists() and not a.force:
        ad.die(f"{cj} already exists. Use --force to overwrite.")

    thresholds = {"_preset": a.preset, "_about": "Tuned from the preset. Multipliers are against each campaign's own "
                  "target or budget."}  # fmt: skip
    for k, v in ad.DEFAULT_THRESHOLDS.items():
        thresholds[k] = dict(v)
    for k, v in preset.items():
        if not k.startswith("_"):
            thresholds.setdefault(k, {}).update(v)
    (root / "client" / "thresholds.json").write_text(json.dumps(thresholds, indent=2))

    client = {"name": a.name, "preset": a.preset, "brand": [b.strip() for b in a.brand.split(",") if b.strip()],
              "agency": a.agency, "review_days": preset["_review_days"], "default_goal": preset["_goal"]}  # fmt: skip
    cj.write_text(json.dumps(client, indent=2))

    targets = root / "client" / "targets.csv"
    if not targets.exists():
        goal = preset["_goal"]
        names = [c.strip() for c in a.campaigns.split(",") if c.strip()] or ["<campaign name exactly as in the export>"]
        rows = [{"campaign_name": n, "goal": goal, "target_cpa": "", "target_roas": "", "daily_budget": "",
                 "target_cpm": "", "max_frequency": ""} for n in names]  # fmt: skip
        ad.write_csv(targets, rows, ["campaign_name", "goal", "target_cpa", "target_roas", "daily_budget", "target_cpm", "max_frequency"])

    ad.emit({"client": a.name, "preset": preset["_label"], "folder": str(root), "review_days": preset["_review_days"],
             "preset_notes": preset.get("_notes", []),
             "next": [f"Fill in {targets} (goal: cpa / roas / awareness, targets, daily budget).",
                      f"Put the platform exports in {root / 'exports'} (see references/exporting.md).",
                      f"Run: python scripts/run_review.py --client-dir {root}"]})  # fmt: skip


if __name__ == "__main__":
    main()
