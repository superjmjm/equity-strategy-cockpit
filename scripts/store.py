"""Sharded report storage helper (data/reports/YYYY-MM/<sha16>.json) to prevent Git rebase conflicts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "data" / "reports"
SYNTHESIS_CACHE_PATH = ROOT / "data" / "synthesis_cache.json"
MARKET_PATH = ROOT / "data" / "market_benchmark.json"
DEMO_SEED_PATH = ROOT / "data" / "demo_seed.json"


def atomic_write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, suffix=".tmp", mode="w", encoding="utf-8", delete=False
    ) as f:
        tmp = Path(f.name)
        try:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=False, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            f.close()
            tmp.unlink(missing_ok=True)
            raise
    os.replace(tmp, path)


def shard_path_for(report: dict) -> Path:
    ym = str(report["report_date"])[:7]
    rid = str(report["report_id"])
    return REPORTS_DIR / ym / f"{rid[:16]}.json"


def save_report(report: dict) -> Path:
    target = shard_path_for(report)
    atomic_write_json(target, report)
    return target


def load_all_reports() -> list[dict]:
    if not REPORTS_DIR.exists():
        return []
    records = []
    for path in sorted(REPORTS_DIR.rglob("*.json")):
        if path.name.startswith("."):
            continue
        records.append(json.loads(path.read_bytes()))
    records.sort(key=lambda r: (r.get("report_date", ""), r.get("report_id", "")))
    return records


def previous_issue_for(broker: str, report_date: str, reports: list[dict]) -> dict | None:
    """Find the most recent prior report of the same broker to inject as cross-week diff context."""
    priors = [
        r for r in reports
        if r.get("broker") == broker and r.get("report_date", "") < report_date
    ]
    if not priors:
        return None
    # Prefer prior flagship reports with a stated stance if multiple exist in recent window
    priors.sort(
        key=lambda r: (
            r.get("report_date", ""),
            1 if r.get("market_stance_slot") else 0,
        )
    )
    prev = priors[-1]
    stance = prev.get("market_stance_slot") or {}
    overweights = [
        {
            "sw": item.get("sw_level1_list", []),
            "theme": item.get("raw_theme_phrase", ""),
        }
        for item in (prev.get("sector_allocation_slot", {}).get("overweight_lines") or [])[:4]
    ]
    return {
        "prev_report_date": prev.get("report_date"),
        "prev_title": prev.get("title"),
        "prev_one_line_takeaway": prev.get("report_meta", {}).get("one_line_takeaway"),
        "prev_stance_tier": stance.get("stance_tier"),
        "prev_position_guidance": stance.get("position_guidance"),
        "prev_thesis_summary": stance.get("thesis_summary"),
        "prev_overweight_themes": overweights,
    }
