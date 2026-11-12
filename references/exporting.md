# Getting the data out of the ad platforms

The skill works from report exports, so no API access or credentials are needed. Ask for these
files covering the **review period plus the same number of days before it** (for example the
last 14 days for a weekly review).

Menu names change from time to time. If a step below doesn't match what the person sees,
describe what the report needs to contain rather than insisting on the click path.

## Google Ads: campaign report (required)

What it must contain: **one row per campaign per day**, with Campaign, Campaign ID, Day, Cost,
Clicks, Impr., Conversions and Conv. value.

1. Go to Campaigns, then set the date range (for example, the last 14 days).
2. Segment by time: **Day**.
3. Use Columns to make sure Cost, Clicks, Impr., Conversions and Conv. value are shown.
4. Download as CSV, or as Excel saved as CSV.

The title lines above the header and the "Total" rows at the bottom are fine, because the script
skips them.

## Meta Ads Manager: campaign report (required for Meta)

What it must contain: **one row per campaign per day**, with Campaign name, Amount spent,
Impressions, Reach, Frequency, Link clicks, Results (or the conversion column the business uses,
such as Leads or Purchases) and, for e-commerce, Purchases conversion value.

1. In Ads Manager, go to Campaigns and set the date range.
2. Breakdown → By time → **Day**.
3. Columns → Customize columns: add the fields above.
4. Export as a .csv file.

**"Results" varies by campaign.** It means leads for a lead campaign and purchases for a sales
campaign. If campaigns mix objectives, use the specific column the business counts (such as
"Leads" or "Purchases") and map it:
`--mapping '{"conversions": "Leads"}'`.

## Microsoft Advertising

Use a campaign performance report with time unit **Day** that includes Spend, Clicks,
Impressions, Conversions and Revenue. It is detected the same way as the others.

## Anything else (TikTok, LinkedIn, etc.)

Any CSV works if it has one row per campaign per day with spend, clicks, impressions and
conversions. Run `normalize_export.py --show-columns`, then `--mapping` any columns that weren't
recognized, and pass `--platform other`.

## Targets: the one thing exports don't contain

Platforms report what happened, not what the business wants. Ask the person for each
campaign's **goal** and fill in `client/targets.csv` (created by `setup_client.py`; `assets/targets_template.csv` shows examples):

| column | meaning |
|---|---|
| campaign_name | exactly as in the export (or use campaign_id) |
| goal | `cpa` for lead or booking businesses, `roas` for e-commerce, `awareness` for reach or brand campaigns |
| target_cpa | what a conversion is worth paying, in dollars |
| target_roas | revenue per $1 of spend that counts as success, for example 4 for 4x |
| daily_budget | the daily budget set in the platform |
| target_cpm | awareness campaigns only: target cost per 1,000 impressions |
| max_frequency | awareness campaigns only: the most times one person should see the ads in the period (default 4) |

If the person doesn't know their target CPA, help them work it out. For a lead business it's
roughly: average customer value × gross margin × close rate from lead to customer, minus a
safety margin. Treat it as a starting point and say so. If targets are missing, the skill still
runs the trend checks (drops, CTR, fatigue, tracking) but can't judge whether CPA or ROAS is
good.

**Keep `daily_budget` in targets.csv in step with the platform** whenever a budget changes.
