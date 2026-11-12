"""Shared helpers for the ad-spend-review skill. Standard library only.

The core rule: deciding WHAT counts as a problem is deterministic code with
thresholds a person can read and tune. Claude narrates numbers this code computed.
It never invents a number.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

METRIC_COLUMNS = ["platform", "date", "campaign_id", "campaign_name", "spend", "clicks", "impressions",
                  "conversions", "revenue", "reach", "frequency"]  # fmt: skip

DEFAULT_THRESHOLDS = {
    # Every value is a multiplier against a campaign's OWN target or budget, never a dollar figure,
    # so the same config works whether a target CPA is $5 or $500.
    "cpa": {"warning_multiplier": 1.25, "critical_multiplier": 1.5},
    "roas": {"warning_multiplier": 0.85, "critical_multiplier": 0.65},
    "spend_pace": {"warning_multiplier": 1.15, "critical_multiplier": 1.30},
    "conversion_volume": {"warning_ratio": 0.5, "critical_ratio": 0.25},
    "zero_conversion_alert": {"min_spend_to_trigger": 50},
    # Added for the skill:
    "ctr_drop": {"warning_ratio": 0.7, "min_impressions": 1000},
    "fatigue": {"frequency_at_least": 3.0, "ctr_ratio_at_most": 0.8},
    "winner": {"cpa_at_most": 0.8, "roas_at_least": 1.2, "pace_at_least": 0.9},
    "wasted_search_term": {"spend_vs_target_cpa": 1.0, "min_spend": 25, "min_clicks": 5},
    "budget_shift": {"max_share_of_budget": 0.2},
    # Small numbers are noisy: below this many conversions in the period, CPA/ROAS problems are
    # reported as "watch (low volume)" and never trigger a budget cut.
    "sample_size": {"min_conversions_for_judgment": 10},
    # Campaigns with goal=awareness are judged on CPM and frequency instead of conversions.
    "awareness": {"cpm_warning_multiplier": 1.25, "cpm_critical_multiplier": 1.5, "default_max_frequency": 4.0},
    # Words that usually mean "not a buyer" in search terms. Presets add or remove words.
    "junk_words": {"add": [], "remove": []},
}

BASE_JUNK_WORDS = ["jobs?", "careers?", "hiring", "salary", "salaries", "school", "course", "courses", "training",
                   "degree", "certification", "free", "diy", "how to", "youtube", "reddit", "wikipedia", "definition",
                   "meaning", "internship", "pdf", "template"]  # fmt: skip


def junk_words(cfg: dict) -> list[str]:
    remove = {w.lower() for w in cfg.get("junk_words", {}).get("remove", [])}
    words = [w for w in BASE_JUNK_WORDS if w.lower() not in remove and w.rstrip("s?").lower() not in remove]
    return words + [w for w in cfg.get("junk_words", {}).get("add", []) if w not in words]


PRESETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "presets"


def load_preset(name: str) -> dict:
    path = PRESETS_DIR / f"{name}.json"
    if not path.exists():
        die(f"Unknown preset {name!r}. Choose from: {', '.join(sorted(p.stem for p in PRESETS_DIR.glob('*.json')))}")
    return json.loads(path.read_text())


def load_thresholds(path: str | None) -> dict:
    cfg = json.loads(json.dumps(DEFAULT_THRESHOLDS))
    if path and Path(path).exists():
        for key, values in json.loads(Path(path).read_text()).items():
            if key.startswith("_"):
                continue
            cfg.setdefault(key, {}).update(values)
    return cfg


# ---------------------------------------------------------------- parsing


def num(value, default: float = 0.0) -> float:
    """'$1,234.56' / '1.234' / '--' / '' / '12.5%' / '(3.00)' -> float."""
    text = str(value if value is not None else "").strip()
    if text in ("", "--", "-", "—", "N/A", "n/a", " --"):
        return default
    neg = text.startswith("(") and text.endswith(")")
    text = re.sub(r"[^\d.\-eE]", "", text.strip("()"))
    if text in ("", "-", "."):
        return default
    try:
        v = float(text)
    except ValueError:
        return default
    return -v if neg else v


DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y", "%d/%m/%Y", "%a, %b %d, %Y",
                "%Y/%m/%d", "%d %b %Y"]  # fmt: skip


def parse_date(value: str, fmt: str = "") -> date | None:
    text = str(value or "").strip()
    for f in [fmt] if fmt else DATE_FORMATS:
        try:
            return datetime.strptime(text, f).date()
        except ValueError:
            continue
    return None


def read_rows(path) -> list[list[str]]:
    data = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            if enc == "utf-16" and "\x00" in text:
                continue
            break
        except UnicodeDecodeError:
            continue
    delimiter = "\t" if text.count("\t") > text.count(",") else ","
    return [r for r in csv.reader(text.splitlines(), delimiter=delimiter)]


def read_csv(path) -> list[dict]:
    if not Path(path).exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def write_csv(path, rows: list[dict], columns: list[str]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: _safe(r.get(c, "")) for c in columns})
    os.replace(tmp, path)


def _safe(v):
    if isinstance(v, str) and v[:1] in ("=", "+", "@") and not re.fullmatch(r"[+-]?[\d.]+", v):
        return "'" + v
    return v


def read_metrics(path) -> list[dict]:
    rows = read_csv(path)
    for r in rows:
        r["date"] = date.fromisoformat(r["date"])
        for k in ("spend", "clicks", "impressions", "conversions", "revenue", "reach", "frequency"):
            r[k] = num(r.get(k))
    return rows


def load_targets(path) -> dict[str, dict]:
    """campaign key (id or lower-cased name) -> {target_cpa, target_roas, daily_budget, goal}."""
    out = {}
    for r in read_csv(path) if path else []:
        t = {k: num(r.get(k)) or None for k in ("target_cpa", "target_roas", "daily_budget", "target_cpm", "max_frequency")}
        t["goal"] = (r.get("goal") or ("roas" if t["target_roas"] and not t["target_cpa"] else "cpa")).strip().lower()
        if t["goal"] not in ("cpa", "roas", "awareness"):
            die(f"targets.csv: goal must be cpa, roas or awareness (got {t['goal']!r} for {r.get('campaign_name')})")
        for key in (r.get("campaign_id", ""), r.get("campaign_name", "")):
            if key and key.strip():
                out[key.strip().lower()] = t
    return out


def targets_for(targets: dict, row: dict) -> dict:
    return targets.get(str(row["campaign_id"]).lower()) or targets.get(row["campaign_name"].strip().lower()) or {}


# ---------------------------------------------------------------- formatting & output


def money(v: float | None) -> str:
    return "n/a" if v is None else f"${v:,.2f}"


def pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def safe_div(a: float, b: float) -> float | None:
    return None if not b else a / b


def die(message: str, code: int = 1):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(code)


def emit(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))
