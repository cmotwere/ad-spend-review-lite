# Industry presets

Pick the preset that matches how the business makes money. It sets the review length, how much
evidence is needed before calling something a problem, how quickly search terms count as
waste, and which words mean "not a buyer". Everything is written into the client's
`thresholds.json`, so you can still tune it per client afterwards.

```bash
python scripts/setup_client.py --list-presets
python scripts/setup_client.py --dir clients/<slug> --name "<Business>" --preset <preset> --brand "<brand words>" --agency "<your agency>"
```

| preset | for | review | goal | what's different |
|---|---|---|---|---|
| `lead_gen` | service businesses getting forms, calls or bookings: dental, legal, medical, home services, real estate, education | 7 days | cpa | the default thresholds |
| `local_services` | small local businesses on Google Search / Local Services: plumbers, HVAC, cleaners, salons, auto repair | 7 days | cpa | waste is flagged sooner (small budgets); words like apprentice, wholesale and parts store count as junk |
| `ecommerce` | online stores judged on revenue | 7 days | roas | more room before a search term counts as waste (shoppers browse); **"free" is not junk** (free shipping); "used" and "repair" are |
| `b2b` | long sales cycles and expensive leads: software sales, consulting, manufacturing, high-ticket services | 30 days | cpa | needs less volume to judge, conversion drops must be bigger to alarm, and words like "what is", "examples" and "student" are junk |
| `saas_trial` | software with free trials or freemium sign-ups | 14 days | cpa | **"free" is not junk** (free trial); crack, torrent, login and cancel are |

## Choosing when it's not obvious

- **A business that both sells online and takes leads**, such as a furniture store with
  showroom bookings: use `ecommerce` and set lead-generating campaigns to `goal=cpa` in
  targets.csv. Goals are per campaign, and the preset only sets defaults.
- **Seasonal businesses** (pools, tax prep, holiday retail): use the closest preset and
  compare with the same period last year during peaks:
  `run_review.py --from 2026-06-01 --to 2026-06-07 --compare-from 2025-06-02 --compare-to 2025-06-08`.
- **Brand awareness campaigns**, in any preset: set `goal=awareness` with `target_cpm` (cost per
  1,000 impressions) and `max_frequency` in targets.csv. They are judged on reach cost and
  frequency, and are left out of the conversion and tracking checks.
- **Very small budgets** (under about $20/day per campaign): problems will mostly show as "low
  confidence". That's honest. Review monthly instead (`--from`/`--to` over 30 days).

## The low-confidence rule (all presets)

A CPA or ROAS problem is only marked **critical**, and only gets a budget cut, when there's
enough evidence. For CPA goals, the spend must have been enough to buy at least
`min_conversions_for_judgment` conversions at target (10 for lead_gen). Below that it's
**watch (low confidence)** and the proposal is to review, not cut.

The rule uses spend, not actual conversions, on purpose. A failing campaign has few
conversions *because* it's failing, so counting actual conversions would hide exactly the
campaigns that are wasting money.
