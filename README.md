# Ad Spend Review (lite)

A free Claude skill that checks your Google Ads, Meta and Microsoft Ads campaigns against your
own targets and writes a client-ready report, from the CSV exports you can already download.
**No API access, no ad account logins, and it never changes anything in your accounts.**

## What it checks

- **Cost per lead or sale against target** for every campaign, with thresholds tied to each
  campaign's own target, so the same rules work for a $5 lead and a $500 lead.
- **Return on ad spend** against target, for e-commerce.
- **Overspending** beyond the daily budget.
- **Broken conversion tracking**: a sudden conversion drop is flagged as a tracking problem first,
  so you don't cut a campaign that's actually working.
- **Creative fatigue** on Meta: people seeing the same ad too often while clicks fall.
- **Hidden winners**: campaigns beating target but held back by budget.
- **Awareness campaigns**, judged on reach cost and frequency rather than conversions.

Industry presets: lead generation, local services, e-commerce, B2B / high-ticket and SaaS free
trials. The scripts need only Python 3.9+, with no extra packages.

## Try it in 30 seconds

```bash
python skills/ad-spend-review-lite/scripts/selftest.py
```

It reviews a bundled sample dental practice with planted problems and shows each one being found
(9/9 checks).

## Example

Ask Claude: *"Review last week's ad spend for Bright Smile Dental. The exports are in
clients/bright-smile/exports."* It imports the files, runs the checks, and writes a report like
this (excerpt from the bundled sample):

```
Summary
- Spend: $3,861.18 (▲ 9% vs previous period)
- Conversions: 75.6 (▼ 27%, worse)
- Cost per conversion: $51.07 (▲ 50%, worse)

Critical (3)
- Meta - Retargeting: Conversions dropped 100% (22.0 -> 0.0) vs the previous 7 days.
  A drop this sharp is often a tracking break, not a real performance change.
  Next step: Check tracking/pixel setup before assuming this is a real performance change.
- Performance Max - New Patients: Spent $943.76 against a $700.00 budget (35% over).
  Next step: Confirm the daily budget cap is set correctly on the platform.
- Search - Dental Implants: CPA is $211.74, 76% above target ($120.00).
  Next step: Review targeting and search terms/placements for this campaign.

Opportunities (2)
- Search - Emergency Dentist: Beating target (CPA $39.83) while using 98% of budget:
  likely held back by budget.
```

The same report is also written as a client-ready HTML page with your agency's name on it.

## Install

The skill is the [`skills/ad-spend-review-lite/`](skills/ad-spend-review-lite) folder.

- **Claude Code:** copy that folder to `~/.claude/skills/ad-spend-review-lite/` (or your
  project's `.claude/skills/`), then ask Claude to "review my ad spend".
- **claude.ai:** zip that folder and upload it under Settings → Capabilities → Skills.
- **MCP Market and other agents** that support the open SKILL.md format: point them at
  `https://github.com/cmotwere/ad-spend-review-lite/tree/main/skills/ad-spend-review-lite`.

Then follow its `SKILL.md`: set up a client, drop the exports into its `exports/` folder, and run the
review. `references/exporting.md` shows exactly which reports to download from each platform.

## Lite vs full

| | Lite (this repo, free) | Full Ad Spend Review |
|---|---|---|
| Imports Google, Meta, Microsoft and other CSV exports | ✓ | ✓ |
| All campaign checks and industry presets | ✓ | ✓ |
| Client-ready HTML report with your agency name | ✓ | ✓ |
| Wasted search-term analysis (job seekers, DIY, "free"...) with brand protection | | ✓ |
| Specific change proposals: budget moves capped at 20%, each with an undo step | | ✓ |
| Decision log per client | | ✓ |
| Follow-up a week later on whether each approved change worked | | ✓ |
| Agency license (unlimited clients) | | ✓ |

The full version, and a done-for-you weekly review service, are available from
**Monaak Services**: https://monaakservices.com · monaakservices@gmail.com

## License

MIT. See [LICENSE](LICENSE).
