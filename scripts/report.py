#!/usr/bin/env python3
"""Step 5 - Build the review report from the computed findings and proposals (no AI).

The report covers: summary vs the previous period, critical and
watch items each with their next step, opportunities, and data notes. Claude may rewrite the prose for the
reader, but every number must come from this report or the JSON it was built from.

Usage:
  python report.py --findings work/findings.json --client "Acme Dental" --out out/2026-10-11_review.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import ad_common as ad

NEXT_STEP = {  # fixed lookup table
    "cpa": "Review targeting and search terms/placements for this campaign.",
    "roas": "Review recent creative and landing page changes; check for tracking or attribution gaps.",
    "spend_pace": "Confirm the daily budget cap is set correctly on the platform.",
    "conversion_drop": "Check tracking/pixel setup before assuming this is a real performance change.",
    "zero_conversions": "Check tracking/pixel setup for this campaign.",
    "tracking_break": "Fix conversion tracking before judging any campaign on this platform.",
    "ctr_drop": "Refresh ad copy/creative; check ad status and new competitors.",
    "fatigue": "Rotate in new creatives; consider widening the audience.",
    "winner": "Consider giving it more budget.",
    "cpm": "Review audience size and placements.",
    "frequency_cap": "Set or lower the frequency cap, widen the audience or add creatives.",
}


def change(cur, prior, lower_is_better=False, neutral=False):
    if cur is None or prior in (None, 0):
        return ""
    d = cur / prior - 1
    arrow = "▲" if d > 0 else "▼" if d < 0 else "="
    if neutral or not d:
        return f" ({arrow} {abs(d) * 100:.0f}% vs previous period)"
    good = (d < 0) if lower_is_better else (d > 0)
    return f" ({arrow} {abs(d) * 100:.0f}%, {'better' if good else 'worse'})"


CSS = """
:root{--ink:#1f2933;--muted:#616e7c;--line:#e4e7eb;--bg:#f7f8fa;--crit:#b42318;--watch:#b54708;--opp:#027a48;--accent:#1d4ed8}
*{box-sizing:border-box}body{margin:0;font:15px/1.55 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}
.wrap{max-width:880px;margin:0 auto;padding:32px 20px 48px}
header{border-bottom:3px solid var(--accent);padding-bottom:14px;margin-bottom:22px}
header h1{margin:0;font-size:26px}header .sub{color:var(--muted);margin-top:4px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:18px 0 26px}
.kpi{background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px}
.kpi .l{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.kpi .v{font-size:22px;font-weight:650;margin-top:2px}.kpi .d{font-size:13px;color:var(--muted)}
.d.good{color:var(--opp)}.d.bad{color:var(--crit)}
section{background:#fff;border:1px solid var(--line);border-radius:10px;padding:16px 20px;margin-bottom:16px}
section h2{margin:0 0 10px;font-size:18px}section.critical h2{color:var(--crit)}section.watch h2{color:var(--watch)}
section.opportunities h2{color:var(--opp)}ul{margin:0;padding-left:20px}li{margin:6px 0}li ul li{margin:2px 0;color:var(--muted);list-style:circle}
p{margin:6px 0}footer{color:var(--muted);font-size:12px;margin-top:22px;border-top:1px solid var(--line);padding-top:12px}
@media print{body{background:#fff}section,.kpi{break-inside:avoid}}
"""


def _inline(text: str) -> str:
    import html as _h
    import re as _re
    t = _h.escape(text)
    return _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)


def _delta(cur, prior, lower_is_better=False, neutral=False):
    if cur is None or not prior:
        return "", ""
    d = cur / prior - 1
    txt = f"{'▲' if d > 0 else '▼' if d < 0 else '='} {abs(d) * 100:.0f}% vs previous"
    if neutral or not d:
        return txt, ""
    good = (d < 0) if lower_is_better else (d > 0)
    return txt, "good" if good else "bad"


def to_html(lines, f, client, agency):
    t, pt, per = f["totals"], f["prior_totals"] or {}, f["period"]
    tiles = [("Spend", ad.money(t["spend"]), *_delta(t["spend"], pt.get("spend"), neutral=True)),
             ("Conversions", f"{t['conversions']:.1f}", *_delta(t["conversions"], pt.get("conversions"))),
             ("Cost / conversion", ad.money(t["cpa"]), *_delta(t["cpa"], pt.get("cpa"), lower_is_better=True))]  # fmt: skip
    if t.get("roas"):
        tiles.append(("ROAS", f"{t['roas']:.2f}x", *_delta(t["roas"], pt.get("roas"))))
    c = f["counts"]
    tiles.append(("Campaigns", str(c["campaigns"]), f"{c['critical']} critical · {c['watch']} watch", ""))
    kpis = "".join(f'<div class="kpi"><div class="l">{l}</div><div class="v">{v}</div><div class="d {cls}">{d}</div></div>'
                   for l, v, d, cls in tiles)  # fmt: skip

    body, open_section, in_list, in_sub = [], False, False, False

    def close_lists():
        nonlocal in_list, in_sub
        if in_sub:
            body.append("</ul></li>")
            in_sub = False
        elif in_list:
            body.append("</li>")
        if in_list:
            body.append("</ul>")
            in_list = False

    started = False
    for ln in lines:
        if ln.strip() == "---":
            break  # the closing disclaimer is in the footer
        if ln.startswith("## "):
            started = True
            close_lists()
            if open_section:
                body.append("</section>")
            title = ln[3:]
            key = title.split(" (")[0].split(" —")[0].lower().replace(" ", "-")
            if key == "summary":
                open_section = False
                continue
            body.append(f'<section class="{key}"><h2>{_inline(title)}</h2>')
            open_section = True
        elif not started or ln.startswith("# ") or ln.startswith("**Period"):
            continue
        elif ln.startswith("  - "):
            if not in_sub:
                body.append("<ul>")
                in_sub = True
            body.append(f"<li>{_inline(ln[4:])}</li>")
        elif ln.startswith("- "):
            if not open_section:
                continue  # summary bullets are shown as tiles
            if in_sub:
                body.append("</ul></li>")
                in_sub = False
            elif in_list:
                body.append("</li>")
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{_inline(ln[2:])}")
        elif ln.strip() in ("", "---"):
            continue
        elif open_section:
            close_lists()
            body.append(f"<p>{_inline(ln)}</p>")
    close_lists()
    if open_section:
        body.append("</section>")
    import html as _h
    title = f"Ad spend review — {client}" if client else "Ad spend review"
    prepared = f"Prepared by {_h.escape(agency)} · " if agency else ""
    return (f"<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,"
            f"initial-scale=1'><title>{_h.escape(title)}</title><style>{CSS}</style></head><body><div class='wrap'>"
            f"<header><h1>{_h.escape(title)}</h1><div class='sub'>{per['from']} to {per['to']} ({per['days']} days) · compared "
            f"with {per['compared_with']['from']} to {per['compared_with']['to']}</div></header><div class='kpis'>{kpis}</div>"
            + "".join(body) +
            f"<footer>{prepared}Findings are computed from the ad platform exports with fixed thresholds against each "
            "campaign's own targets. Before/after comparisons are a rough read, not proof of cause. No changes were made "
            "in the ad accounts.</footer></div></body></html>")  # fmt: skip


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--findings", required=True)
    p.add_argument("--client", default="")
    p.add_argument("--out", required=True)
    p.add_argument("--format", choices=["md", "html"], default="", help="Default: from the --out extension")
    p.add_argument("--agency", default="", help="HTML: shown as 'Prepared by'")
    a = p.parse_args()

    f = json.loads(Path(a.findings).read_text())
    per, t, pt, c = f["period"], f["totals"], f["prior_totals"] or {}, f["counts"]
    L = [f"# Ad spend review{' — ' + a.client if a.client else ''}", "",
         f"**Period:** {per['from']} to {per['to']} ({per['days']} days), compared with {per['compared_with']['from']} to "
         f"{per['compared_with']['to']}.", "",
         "## Summary", "",
         f"- **Spend:** {ad.money(t['spend'])}{change(t['spend'], pt.get('spend'), neutral=True)}",
         f"- **Conversions:** {t['conversions']:.1f}{change(t['conversions'], pt.get('conversions'))}",
         f"- **Cost per conversion:** {ad.money(t['cpa'])}{change(t['cpa'], pt.get('cpa'), lower_is_better=True)}"]  # fmt: skip
    if t.get("roas"):
        L.append(f"- **ROAS:** {t['roas']:.2f}x{change(t['roas'], pt.get('roas'))}")
    L += [f"- **Campaigns:** {c['campaigns']} — {c['critical']} critical, {c['watch']} watch, {c['opportunity']} opportunities, "
          f"{c['on_target']} on target", ""]  # fmt: skip

    for sev, title in (("critical", "Critical"), ("watch", "Watch"), ("opportunity", "Opportunities")):
        items = [x for x in f["findings"] if x["severity"] == sev]
        L += [f"## {title} ({len(items)})", ""]
        if not items:
            L += ["None.", ""]
            continue
        for x in items:
            L.append(f"- **{x['campaign_name']}** ({x['platform']}): {x['message']}")
            L.append(f"  - Next step: {NEXT_STEP.get(x['metric'], 'Review manually.')}")
        L.append("")

    if f["data_notes"]:
        L += ["## Data notes", ""] + [f"- {n}" for n in f["data_notes"]] + [""]
    L += ["---", "Findings are computed from the platform exports with fixed thresholds; before/after comparisons are a "
          "rough read, not proof of cause."]  # fmt: skip

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fmt_ = a.format or ("html" if out.suffix.lower() in (".html", ".htm") else "md")
    if fmt_ == "html":
        out.write_text(to_html(L, f, a.client, a.agency), encoding="utf-8")
    else:
        out.write_text("\n".join(L), encoding="utf-8")
    ad.emit({"report": str(out), "lines": len(L)})


if __name__ == "__main__":
    main()
