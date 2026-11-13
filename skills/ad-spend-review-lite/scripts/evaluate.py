#!/usr/bin/env python3
"""Step 2 - Find what's wrong (and what's working). Deterministic: no AI.

Compares each campaign over the review period with its OWN targets (targets.csv) and with the
period just before it (same length). One day = a daily check; 7 days = a weekly review.

Checks (all thresholds in thresholds.json, as multipliers of each campaign's own target):
  cpa             CPA >= 1.25x target (watch) / 1.5x (critical)
  roas            ROAS <= 0.85x target (watch) / 0.65x (critical)
  spend_pace      spend >= 1.15x budget for the period (watch) / 1.3x (critical)
  conversion_drop conversions fell 50%+ (watch) / 75%+ (critical) vs the prior period
  zero_conversions spent >= $50 per day of the period with no conversions (critical)
  tracking_break  a whole platform recorded 0 conversions while spending, after converting before
  ctr_drop        CTR fell 30%+ vs the prior period (>= 1,000 impressions) (watch)
  fatigue         Meta: frequency >= 3 and CTR down 20%+ (watch) - the audience is tired of the ads
  awareness       goal=awareness campaigns: CPM >= 1.25x target_cpm (watch) / 1.5x (critical), frequency above
                  max_frequency (watch); conversion checks are skipped for them
  low volume      when the spend could only buy < 10 conversions at target (preset-dependent), CPA/ROAS problems
                  are only "watch (low confidence)" and never trigger a budget cut
  winner          beating target (CPA <= 0.8x or ROAS >= 1.2x) while spending >= 90% of budget:
                  probably held back by budget (an opportunity, not a problem)

Usage:
  python evaluate.py --metrics work/metrics.csv --targets client/targets.csv --from 2026-10-05 --to 2026-10-11 \
      [--thresholds client/thresholds.json] [--out work/findings.json]
  python evaluate.py --metrics work/metrics.csv --targets client/targets.csv --date 2026-10-11   # daily check
  # seasonal business: compare with the same week last year instead of the week before
  python evaluate.py ... --from 2026-11-23 --to 2026-11-29 --compare-from 2025-11-24 --compare-to 2025-11-30
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import ad_common as ad

ORDER = {"critical": 0, "watch": 1, "opportunity": 2, "info": 3}


def aggregate(rows: list[dict]) -> dict:
    s = {k: sum(r[k] for r in rows) for k in ("spend", "clicks", "impressions", "conversions", "revenue")}
    fi = sum(r["frequency"] * r["impressions"] for r in rows if r["frequency"])
    fimp = sum(r["impressions"] for r in rows if r["frequency"])
    s["frequency"] = round(fi / fimp, 2) if fimp else None
    s["cpa"] = round(s["spend"] / s["conversions"], 2) if s["conversions"] else None
    s["roas"] = round(s["revenue"] / s["spend"], 2) if s["spend"] and s["revenue"] else None
    s["ctr"] = s["clicks"] / s["impressions"] if s["impressions"] else None
    s["cvr"] = s["conversions"] / s["clicks"] if s["clicks"] else None
    s["cpc"] = round(s["spend"] / s["clicks"], 2) if s["clicks"] else None
    s["cpm"] = round(s["spend"] / s["impressions"] * 1000, 2) if s["impressions"] else None
    s["days"] = len({r["date"] for r in rows})
    return s


def evaluate_awareness(findings, camp, cur, prior, t, cfg, pace, days):
    """Brand/reach campaigns: judged on cost per 1,000 impressions and frequency, not conversions."""
    aw = cfg["awareness"]
    tcpm = t.get("target_cpm")
    if tcpm and cur["cpm"] is not None:
        ratio = cur["cpm"] / tcpm
        for sev, mult in (("critical", aw["cpm_critical_multiplier"]), ("watch", aw["cpm_warning_multiplier"])):
            if ratio >= mult:
                flag(findings, camp, "cpm", sev, f"CPM is {ad.money(cur['cpm'])}, {round((ratio - 1) * 100)}% above target "
                     f"({ad.money(tcpm)}): reach is getting expensive.", cpm=cur["cpm"], target_cpm=tcpm)  # fmt: skip
                break
    cap = t.get("max_frequency") or aw["default_max_frequency"]
    if cur["frequency"] and cur["frequency"] > cap:
        flag(findings, camp, "frequency_cap", "watch", f"Frequency {cur['frequency']:.1f} is above the cap of {cap:.1f}: "
             "the same people are seeing the ads too often.", frequency=cur["frequency"], max_frequency=cap)  # fmt: skip
    if pace is not None and pace >= cfg["spend_pace"]["warning_multiplier"]:
        sev = "critical" if pace >= cfg["spend_pace"]["critical_multiplier"] else "watch"
        flag(findings, camp, "spend_pace", sev, f"Spent {ad.money(cur['spend'])} against a {ad.money(t['daily_budget'] * days)} "
             f"budget for the period ({round((pace - 1) * 100)}% over).", spend=cur["spend"],
             budget_for_period=round(t["daily_budget"] * days, 2))  # fmt: skip
    if prior and prior["ctr"] and cur["ctr"] is not None and cur["impressions"] >= cfg["ctr_drop"]["min_impressions"]:
        if cur["ctr"] / prior["ctr"] <= cfg["ctr_drop"]["warning_ratio"]:
            flag(findings, camp, "ctr_drop", "watch", f"CTR fell from {ad.pct(prior['ctr'])} to {ad.pct(cur['ctr'])}.",
                 ctr=round(cur["ctr"], 4), prior_ctr=round(prior["ctr"], 4))  # fmt: skip


def flag(findings, camp, metric, severity, message, **numbers):
    findings.append({"platform": camp["platform"], "campaign_id": camp["campaign_id"],
                     "campaign_name": camp["campaign_name"], "metric": metric, "severity": severity,
                     "message": message, "numbers": numbers})  # fmt: skip


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--metrics", required=True)
    p.add_argument("--targets", default="")
    p.add_argument("--thresholds", default="")
    p.add_argument("--from", dest="start")
    p.add_argument("--to", dest="end")
    p.add_argument("--date")
    p.add_argument("--compare-from", default="", help="Compare with this period instead of the one just before")
    p.add_argument("--compare-to", default="")
    p.add_argument("--out", default="")
    a = p.parse_args()

    cfg = ad.load_thresholds(a.thresholds)
    rows = ad.read_metrics(a.metrics)
    if not rows:
        ad.die(f"No metrics in {a.metrics}. Run normalize_export.py first.")
    if a.date:
        start = end = date.fromisoformat(a.date)
    elif a.start and a.end:
        start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    else:
        end = max(r["date"] for r in rows)
        start = end - timedelta(days=6)
    days = (end - start).days + 1
    prior_start, prior_end = start - timedelta(days=days), start - timedelta(days=1)
    if a.compare_from and a.compare_to:
        prior_start, prior_end = date.fromisoformat(a.compare_from), date.fromisoformat(a.compare_to)
    min_conv = cfg["sample_size"]["min_conversions_for_judgment"]
    aw = cfg["awareness"]
    targets = ad.load_targets(a.targets)

    by_camp = defaultdict(lambda: {"cur": [], "prior": []})
    meta = {}
    for r in rows:
        key = (r["platform"], r["campaign_id"])
        meta[key] = r
        if start <= r["date"] <= end:
            by_camp[key]["cur"].append(r)
        elif prior_start <= r["date"] <= prior_end:
            by_camp[key]["prior"].append(r)

    findings, campaigns, notes = [], [], []
    missing_days = []
    for key, parts in sorted(by_camp.items(), key=lambda kv: meta[kv[0]]["campaign_name"]):
        if not parts["cur"]:
            continue
        camp = meta[key]
        cur, prior = aggregate(parts["cur"]), aggregate(parts["prior"]) if parts["prior"] else None
        t = ad.targets_for(targets, camp)
        if cur["days"] < days:
            missing_days.append(f"{camp['campaign_name']}: {cur['days']} of {days} days")
        summary = {"platform": camp["platform"], "campaign_id": camp["campaign_id"], "campaign_name": camp["campaign_name"],
                   **{k: cur[k] for k in ("spend", "clicks", "impressions", "conversions", "revenue", "cpa", "roas",
                                           "ctr", "cpc", "cvr", "frequency", "cpm")},
                   "target_cpa": t.get("target_cpa"), "target_roas": t.get("target_roas"),
                   "daily_budget": t.get("daily_budget"), "goal": t.get("goal"), "target_cpm": t.get("target_cpm"),
                   "prior": {k: prior[k] for k in ("spend", "conversions", "cpa", "roas", "ctr")} if prior else None}  # fmt: skip
        campaigns.append(summary)
        if not t:
            notes.append(f"No targets for '{camp['campaign_name']}': only trend checks were run. Add it to targets.csv.")
        budget = t.get("daily_budget")
        pace = cur["spend"] / (budget * days) if budget else None
        summary["pace"] = round(pace, 3) if pace is not None else None

        if t.get("goal") == "awareness":
            evaluate_awareness(findings, camp, cur, prior, t, cfg, pace, days)
            continue
        # Evidence size = conversions the spend SHOULD have bought at target. Judging by actual conversions would
        # hide exactly the campaigns that are doing badly (few conversions is the problem, not a lack of data).
        tc_, tr_ = t.get("target_cpa"), t.get("target_roas")
        if tc_ and t.get("goal") != "roas":
            evidence = cur["spend"] / tc_
        else:
            evidence = cur["conversions"] + (prior["conversions"] if prior else 0)
        low = evidence < min_conv
        low_note = (f" (low confidence: spend only buys about {evidence:.0f} conversions at target)" if low and tc_
                    and t.get("goal") != "roas" else f" (low confidence: only {evidence:.0f} conversions)" if low else "")
        winner_low = cur["conversions"] < min_conv

        # --- CPA ---
        tc = t.get("target_cpa")
        if tc and cur["cpa"] is not None and t.get("goal") != "roas":
            ratio = cur["cpa"] / tc
            for sev, mult in (("critical", cfg["cpa"]["critical_multiplier"]), ("watch", cfg["cpa"]["warning_multiplier"])):
                if ratio >= mult:
                    flag(findings, camp, "cpa", "watch" if low else sev, f"CPA is {ad.money(cur['cpa'])}, {round((ratio - 1) * 100)}% above "
                         f"target ({ad.money(tc)}).{low_note}", cpa=cur["cpa"], target_cpa=tc, spend=cur["spend"],
                         conversions=cur["conversions"], low_volume=low)  # fmt: skip
                    break
        # --- ROAS (low is bad) ---
        tr = t.get("target_roas")
        if tr and cur["roas"] is not None and t.get("goal") != "cpa":
            ratio = cur["roas"] / tr
            for sev, mult in (("critical", cfg["roas"]["critical_multiplier"]), ("watch", cfg["roas"]["warning_multiplier"])):
                if ratio <= mult:
                    flag(findings, camp, "roas", "watch" if low else sev, f"ROAS is {cur['roas']:.2f}x, {round((1 - ratio) * 100)}% below target "
                         f"({tr:.2f}x).{low_note}", roas=cur["roas"], target_roas=tr, spend=cur["spend"], revenue=cur["revenue"],
                         low_volume=low)  # fmt: skip
                    break
        # --- Spend pace (over the whole period) ---
        if pace is not None:
            for sev, mult in (("critical", cfg["spend_pace"]["critical_multiplier"]), ("watch", cfg["spend_pace"]["warning_multiplier"])):
                if pace >= mult:
                    flag(findings, camp, "spend_pace", sev, f"Spent {ad.money(cur['spend'])} against a "
                         f"{ad.money(budget * days)} budget for the period ({round((pace - 1) * 100)}% over).",
                         spend=cur["spend"], budget_for_period=round(budget * days, 2))  # fmt: skip
                    break
        # --- Conversion drop vs prior period ---
        if prior and prior["conversions"] > 0:
            ratio = cur["conversions"] / prior["conversions"]
            small = prior["conversions"] < min_conv and cur["conversions"] > 0  # 6 -> 2 is noise, 6 -> 0 is not
            for sev, r_ in (("critical", cfg["conversion_volume"]["critical_ratio"]), ("watch", cfg["conversion_volume"]["warning_ratio"])):
                if ratio <= r_:
                    flag(findings, camp, "conversion_drop", "watch" if small else sev, f"Conversions dropped {round((1 - ratio) * 100)}% "
                         f"({prior['conversions']:.1f} -> {cur['conversions']:.1f}) vs the previous {days} day(s). A drop "
                         "this sharp is often a tracking break, not a real performance change.",
                         conversions=cur["conversions"], prior_conversions=prior["conversions"])  # fmt: skip
                    break
        # --- Zero conversions with real spend ---
        min_spend = cfg["zero_conversion_alert"]["min_spend_to_trigger"] * days
        if cur["conversions"] == 0 and cur["spend"] >= min_spend:
            flag(findings, camp, "zero_conversions", "critical", f"Spent {ad.money(cur['spend'])} with zero recorded "
                 "conversions. Check tracking/pixel setup before assuming this is a targeting problem.", spend=cur["spend"])  # fmt: skip
        # --- CTR drop ---
        if prior and prior["ctr"] and cur["ctr"] is not None and cur["impressions"] >= cfg["ctr_drop"]["min_impressions"]:
            ratio = cur["ctr"] / prior["ctr"]
            if ratio <= cfg["ctr_drop"]["warning_ratio"]:
                flag(findings, camp, "ctr_drop", "watch", f"CTR fell from {ad.pct(prior['ctr'])} to {ad.pct(cur['ctr'])} "
                     f"({round((1 - ratio) * 100)}% lower).", ctr=round(cur["ctr"], 4), prior_ctr=round(prior["ctr"], 4))  # fmt: skip
        # --- Creative fatigue (Meta) ---
        if cur["frequency"] and prior and prior["ctr"] and cur["ctr"] is not None:
            if cur["frequency"] >= cfg["fatigue"]["frequency_at_least"] and cur["ctr"] / prior["ctr"] <= cfg["fatigue"]["ctr_ratio_at_most"]:
                flag(findings, camp, "fatigue", "watch", f"Frequency {cur['frequency']:.1f} (people see the ads "
                     f"{cur['frequency']:.1f} times on average) while CTR fell to {ad.pct(cur['ctr'])}: likely creative fatigue.",
                     frequency=cur["frequency"], ctr=round(cur["ctr"], 4), prior_ctr=round(prior["ctr"], 4))  # fmt: skip
        # --- Winner held back by budget ---
        w = cfg["winner"]
        beating = (tc and cur["cpa"] is not None and cur["cpa"] <= tc * w["cpa_at_most"] and t.get("goal") != "roas") or \
                  (tr and cur["roas"] is not None and cur["roas"] >= tr * w["roas_at_least"] and t.get("goal") != "cpa")  # fmt: skip
        has_problem = any(x["campaign_id"] == camp["campaign_id"] and x["platform"] == camp["platform"]
                          and x["severity"] in ("critical", "watch") for x in findings)  # fmt: skip
        if beating and winner_low:
            beating = False  # too few conversions to call it a winner
        if beating and pace is not None and pace >= w["pace_at_least"] and has_problem:
            notes.append(f"'{camp['campaign_name']}' beats its target but also has a warning, so it isn't listed as an "
                         "opportunity until that's resolved.")  # fmt: skip
        elif beating and pace is not None and pace >= w["pace_at_least"]:
            flag(findings, camp, "winner", "opportunity", f"Beating target ({'CPA ' + ad.money(cur['cpa']) if cur['cpa'] else ''}"
                 f"{' / ROAS ' + format(cur['roas'], '.2f') + 'x' if cur['roas'] else ''}) while using {round(pace * 100)}% of "
                 "budget: likely held back by budget.", cpa=cur["cpa"], roas=cur["roas"], pace=round(pace, 3),
                 daily_budget=budget)  # fmt: skip

    # --- Platform-wide tracking break ---
    by_platform = defaultdict(lambda: {"cur_spend": 0, "cur_conv": 0, "prior_conv": 0})
    for c in campaigns:
        if c.get("goal") == "awareness":
            continue  # awareness campaigns aren't expected to convert
        bp = by_platform[c["platform"]]
        bp["cur_spend"] += c["spend"]
        bp["cur_conv"] += c["conversions"]
        bp["prior_conv"] += (c["prior"] or {}).get("conversions", 0) or 0
    for plat, bp in by_platform.items():
        if bp["cur_conv"] == 0 and bp["cur_spend"] > 0 and bp["prior_conv"] > 0:
            findings.append({"platform": plat, "campaign_id": "*", "campaign_name": f"All {plat} campaigns",
                             "metric": "tracking_break", "severity": "critical",
                             "message": f"Every {plat} campaign recorded 0 conversions on {ad.money(bp['cur_spend'])} spend, "
                                        f"after {bp['prior_conv']:.0f} the period before. Conversion tracking is almost "
                                        "certainly broken: fix it before judging any campaign.",
                             "numbers": {"spend": round(bp["cur_spend"], 2), "prior_conversions": bp["prior_conv"]}})  # fmt: skip

    findings.sort(key=lambda f: (ORDER[f["severity"]], f["campaign_name"], f["metric"]))
    flagged = {f["campaign_id"] for f in findings if f["severity"] in ("critical", "watch")}
    tot = aggregate([r for parts in by_camp.values() for r in parts["cur"]])
    ptot = aggregate([r for parts in by_camp.values() for r in parts["prior"]]) if any(p["prior"] for p in by_camp.values()) else None
    if missing_days:
        notes.append("Some campaigns don't have data for every day of the period: " + "; ".join(missing_days[:8]))
    if not ptot:
        notes.append("No data for the previous period, so drop/trend checks were skipped.")
    result = {
        "period": {"from": start.isoformat(), "to": end.isoformat(), "days": days,
                   "compared_with": {"from": prior_start.isoformat(), "to": prior_end.isoformat()}},
        "totals": {k: tot[k] for k in ("spend", "conversions", "revenue", "cpa", "roas", "ctr")},
        "prior_totals": {k: ptot[k] for k in ("spend", "conversions", "revenue", "cpa", "roas", "ctr")} if ptot else None,
        "counts": {s: sum(f["severity"] == s for f in findings) for s in ("critical", "watch", "opportunity")}
                  | {"on_target": sum(c["campaign_id"] not in flagged for c in campaigns), "campaigns": len(campaigns)},
        "findings": findings,
        "campaigns": campaigns,
        "data_notes": notes,
    }  # fmt: skip
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(__import__("json").dumps(result, indent=2, default=str))
    ad.emit({k: result[k] for k in ("period", "totals", "counts", "data_notes")} |
            {"findings": [f"[{f['severity']}] {f['campaign_name']}: {f['message']}" for f in findings],
             "saved_to": a.out or "(not saved: pass --out)"})  # fmt: skip


if __name__ == "__main__":
    main()
