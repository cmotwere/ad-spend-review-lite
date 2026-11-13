#!/usr/bin/env python3
"""Step 1 - Turn ad platform exports into one standard metrics file.

Reads a Google Ads, Meta Ads Manager or Microsoft Advertising export (CSV or tab-separated, with
or without the title lines the platforms put above the header) and appends the rows to
work/metrics.csv in one schema:
    platform,date,campaign_id,campaign_name,spend,clicks,impressions,conversions,revenue,reach,frequency
Re-importing the same day for the same campaign replaces the old row (no double counting).
"Total" rows are skipped.

Search term / keyword reports are detected automatically and written to work/search_terms.csv:
    platform,search_term,match_type,campaign_name,ad_group,spend,clicks,impressions,conversions,revenue

The export must be broken down BY DAY (Google: Segment > Day; Meta: Breakdown > By time > Day),
except search term reports, which can cover the whole period.

Usage:
  python normalize_export.py --input google_campaigns.csv --work work/
  python normalize_export.py --input meta.csv --work work/ --platform meta_ads
  python normalize_export.py --input export.csv --show-columns           # see how headers were read
  python normalize_export.py --input x.csv --work work/ --mapping '{"spend":"Cost (Converted currency)"}'
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import ad_common as ad

# Standard field -> header names seen in common exports (compared lower-case, currency suffix removed).
ALIASES = {
    "date": ["day", "date", "reporting starts", "time period", "gregorian date"],
    "campaign_name": ["campaign", "campaign name", "campaign_name"],
    "campaign_id": ["campaign id", "campaign_id"],
    "spend": ["cost", "amount spent", "spend", "spent"],
    "clicks": ["clicks", "link clicks", "clicks (all)"],
    "impressions": ["impr.", "impressions", "impr"],
    "conversions": ["conversions", "results", "purchases", "conv.", "leads", "all conv."],
    "revenue": ["conv. value", "conversion value", "purchases conversion value", "website purchases conversion value",
                "revenue", "conv. value (by conv. time)", "total conv. value"],  # fmt: skip
    "reach": ["reach"],
    "frequency": ["frequency"],
    "search_term": ["search term", "search query", "search terms"],
    "keyword": ["keyword", "search keyword"],
    "match_type": ["match type", "search terms match type", "keyword match type"],
    "ad_group": ["ad group", "ad group name", "ad set name", "ad set"],
}
PLATFORM_HINTS = {
    "meta_ads": ["amount spent", "reporting starts", "ad set name", "reach", "frequency", "results"],
    "google_ads": ["impr.", "conv. value", "conv.", "search term"],
    "microsoft_ads": ["gregorian date", "spend"],
}


def clean(h: str) -> str:
    h = re.sub(r"\((?:usd|eur|gbp|cad|aud|ghs|converted currency)\)", "", h.strip().lower())
    return " ".join(h.replace("﻿", "").split())


def find_header(rows: list[list[str]]) -> int:
    wanted = set(ALIASES["campaign_name"] + ALIASES["search_term"] + ALIASES["spend"])
    for i, r in enumerate(rows[:15]):
        cells = {clean(c) for c in r}
        if len(cells & wanted) >= 2 or ({"campaign", "cost"} <= cells):
            return i
    ad.die("Couldn't find the header row (needs a Campaign and a Cost/Amount spent column). Try --show-columns.")


def map_columns(headers: list[str], override: dict) -> dict[str, int]:
    cleaned = [clean(h) for h in headers]
    idx = {}
    for field, names in ALIASES.items():
        if field in override:
            name = clean(override[field])
            if name not in cleaned:
                ad.die(f"--mapping: column {override[field]!r} not found. Headers: {headers}")
            idx[field] = cleaned.index(name)
            continue
        for n in names:  # first alias wins, so more specific names are listed first
            if n in cleaned:
                idx[field] = cleaned.index(n)
                break
    return idx


def detect_platform(headers: list[str]) -> str:
    cleaned = {clean(h) for h in headers}
    scores = {p: len(cleaned & set(h)) for p, h in PLATFORM_HINTS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else "unknown"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True)
    p.add_argument("--work", help="Work folder holding metrics.csv / search_terms.csv")
    p.add_argument("--platform", choices=["google_ads", "meta_ads", "microsoft_ads", "other"])
    p.add_argument("--mapping", default="", help="JSON: standard field -> header name, to override guesses")
    p.add_argument("--date", help="For a single-day export with no date column: YYYY-MM-DD")
    p.add_argument("--show-columns", action="store_true")
    a = p.parse_args()

    rows = ad.read_rows(a.input)
    h = find_header(rows)
    headers, body = rows[h], rows[h + 1 :]
    override = json.loads(a.mapping) if a.mapping else {}
    cols = map_columns(headers, override)
    platform = a.platform or detect_platform(headers)
    kind = "search_terms" if ("search_term" in cols or "keyword" in cols) else "campaigns"

    if a.show_columns:
        ad.emit({"header_row": h + 1, "headers": headers, "platform": platform, "kind": kind,
                 "mapped": {f: headers[i] for f, i in cols.items()},
                 "missing": [f for f in ("date", "campaign_name", "spend", "clicks", "impressions", "conversions")
                             if f not in cols]})  # fmt: skip
        return
    if not a.work:
        ad.die("--work is required")
    for need in ("campaign_name", "spend"):
        if need not in cols:
            ad.die(f"No column found for {need}. Pass --mapping '{{\"{need}\": \"<header>\"}}' (see --show-columns).")

    def cell(r, field):
        i = cols.get(field)
        return r[i].strip() if i is not None and i < len(r) else ""

    work = Path(a.work)
    skipped, bad_dates = 0, []
    if kind == "search_terms":
        out = []
        for r in body:
            term = cell(r, "search_term") or cell(r, "keyword")
            if not term or term.lower().startswith("total") or not cell(r, "campaign_name"):
                skipped += 1
                continue
            out.append({"platform": platform, "search_term": term, "match_type": cell(r, "match_type"),
                        "campaign_name": cell(r, "campaign_name"), "ad_group": cell(r, "ad_group"),
                        "spend": ad.num(cell(r, "spend")), "clicks": ad.num(cell(r, "clicks")),
                        "impressions": ad.num(cell(r, "impressions")), "conversions": ad.num(cell(r, "conversions")),
                        "revenue": ad.num(cell(r, "revenue"))})  # fmt: skip
        cols_out = ["platform", "search_term", "match_type", "campaign_name", "ad_group", "spend", "clicks",
                    "impressions", "conversions", "revenue"]  # fmt: skip
        ad.write_csv(work / "search_terms.csv", out, cols_out)
        ad.emit({"kind": "search_terms", "platform": platform, "rows": len(out), "skipped": skipped,
                 "spend": ad.money(sum(r["spend"] for r in out)), "file": str(work / "search_terms.csv")})  # fmt: skip
        return

    if "date" not in cols and not a.date:
        ad.die("No date column. Export the report broken down by day, or pass --date for a single day.")
    fixed_date = ad.parse_date(a.date) if a.date else None
    date_values = [cell(r, "date") for r in body if cell(r, "date")]
    fmt = next((f for f in ad.DATE_FORMATS if date_values and all(ad.parse_date(v, f) for v in date_values
                if not v.lower().startswith("total"))), "")  # fmt: skip

    new = {}
    for r in body:
        name = cell(r, "campaign_name")
        if not name or name.lower().startswith("total") or (cell(r, "date").lower().startswith("total")):
            skipped += 1
            continue
        d = fixed_date or ad.parse_date(cell(r, "date"), fmt)
        if d is None:
            bad_dates.append(cell(r, "date"))
            continue
        cid = cell(r, "campaign_id") or name
        spend, clicks, impr = ad.num(cell(r, "spend")), ad.num(cell(r, "clicks")), ad.num(cell(r, "impressions"))
        key = (platform, d.isoformat(), cid)
        row = new.setdefault(key, {"platform": platform, "date": d.isoformat(), "campaign_id": cid, "campaign_name": name,
                                   "spend": 0.0, "clicks": 0.0, "impressions": 0.0, "conversions": 0.0,
                                   "revenue": 0.0, "reach": 0.0, "freq_x_impr": 0.0})  # fmt: skip
        # several rows for one campaign-day (e.g. split by device or ad set) are added together
        row["spend"] += spend
        row["clicks"] += clicks
        row["impressions"] += impr
        row["conversions"] += ad.num(cell(r, "conversions"))
        row["revenue"] += ad.num(cell(r, "revenue"))
        row["reach"] += ad.num(cell(r, "reach"))
        row["freq_x_impr"] += ad.num(cell(r, "frequency")) * impr
    for row in new.values():
        row["frequency"] = round(row["freq_x_impr"] / row["impressions"], 2) if row["impressions"] and row["freq_x_impr"] else ""
        for k in ("spend", "revenue"):
            row[k] = round(row[k], 2)

    path = work / "metrics.csv"
    existing = {(r["platform"], r["date"], r["campaign_id"]): r for r in ad.read_csv(path)}
    replaced = sum(k in existing for k in new)
    existing.update(new)
    out = sorted(existing.values(), key=lambda r: (r["date"], r["platform"], r["campaign_name"]))
    ad.write_csv(path, out, ad.METRIC_COLUMNS)
    dates = sorted({k[1] for k in new})
    ad.emit({"kind": "campaigns", "platform": platform, "campaign_days": len(new), "replaced_existing": replaced,
             "campaigns": len({k[2] for k in new}), "date_range": [dates[0], dates[-1]] if dates else None,
             "spend": ad.money(sum(r["spend"] for r in new.values())),
             "conversions": round(sum(r["conversions"] for r in new.values()), 1),
             "skipped_total_rows": skipped, "unreadable_dates": bad_dates[:10],
             "missing_columns": [f for f in ("conversions", "revenue", "clicks", "impressions") if f not in cols],
             "file": str(path)})  # fmt: skip


if __name__ == "__main__":
    main()
