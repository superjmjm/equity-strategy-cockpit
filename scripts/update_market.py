"""Refresh A-share benchmark (HS300 & CSI All Share) and 31 Shenwan Level-1 3Y turnover crowding percentiles."""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.store import MARKET_PATH, atomic_write_json

BEIJING = timezone(timedelta(hours=8))

# Standard 31 Shenwan Level-1 Industry Codes -> Exact Canonical Names
SW_L1_CODES = {
    "801010": "农林牧渔", "801030": "基础化工", "801040": "钢铁", "801050": "有色金属",
    "801080": "电子", "801110": "家用电器", "801120": "食品饮料", "801130": "纺织服饰",
    "801140": "轻工制造", "801150": "医药生物", "801160": "公用事业", "801170": "交通运输",
    "801180": "房地产", "801200": "商贸零售", "801210": "社会服务", "801230": "综合",
    "801710": "建筑材料", "801720": "建筑装饰", "801730": "电力设备", "801740": "国防军工",
    "801750": "计算机", "801760": "传媒", "801770": "通信", "801780": "银行",
    "801790": "非银金融", "801880": "汽车", "801890": "机械设备", "801950": "煤炭",
    "801960": "石油石化", "801970": "环保", "801980": "美容护理",
}


def percentile_rank(series: list[float], latest: float) -> float:
    if not series:
        return 50.0
    below = sum(1 for x in series if x <= latest)
    return round((below / len(series)) * 100.0, 1)


def _fetch_hs300_history(ak, cutoff_20w: str) -> list[dict]:
    """Fetch HS300 daily close via AKShare 1.20+ interfaces with resilient source fallbacks."""
    start_compact = cutoff_20w.replace("-", "")
    attempts = [
        ("index_zh_daily_sina", lambda fn: fn(symbol="sh000300")),
        ("index_zh_daily_tx", lambda fn: fn(symbol="sh000300")),
        ("index_zh_hist_em", lambda fn: fn(symbol="000300", period="daily", start_date=start_compact)),
        ("index_zh_a_hist", lambda fn: fn(symbol="000300", period="daily", start_date=start_compact)),
    ]
    errors: list[str] = []
    for fn_name, call in attempts:
        fn = getattr(ak, fn_name, None)
        if fn is None:
            continue
        try:
            df = call(fn)
            if df is None or df.empty:
                continue
            date_col = "日期" if "日期" in df.columns else "date"
            close_col = "收盘" if "收盘" in df.columns else "close"
            series = []
            for _, row in df.iterrows():
                d_str = str(row[date_col])[:10]
                if d_str < cutoff_20w:
                    continue
                series.append({"date": d_str, "close": round(float(row[close_col]), 2)})
            if series:
                series.sort(key=lambda x: x["date"])
                return series
        except Exception as exc:
            errors.append(f"{fn_name}:{type(exc).__name__}")
    raise RuntimeError(f"HS300 history fetch failed ({', '.join(errors) or 'no_interface'})")


def fetch_via_akshare() -> dict:
    import akshare as ak

    cutoff_3y = (datetime.now(BEIJING).date() - timedelta(days=365 * 3 + 15)).isoformat()
    cutoff_20w = (datetime.now(BEIJING).date() - timedelta(days=160)).isoformat()

    # 1) HS300 daily close for 12-week analyst trajectory overlay
    hs300_series = _fetch_hs300_history(ak, cutoff_20w)

    # 2) 31 Shenwan Level-1 daily turnover -> compute daily turnover share & 3Y percentile
    daily_sector_amt: dict[str, dict[str, float]] = {}
    latest_close_by_sec: dict[str, list[tuple[str, float]]] = {}

    for code, sw_name in SW_L1_CODES.items():
        df = ak.index_hist_sw(symbol=code, period="day")
        for _, row in df.iterrows():
            d_str = str(row["日期"])[:10]
            if d_str < cutoff_3y:
                continue
            amt = float(row["成交额"])
            cls_val = float(row["收盘"])
            daily_sector_amt.setdefault(d_str, {})[sw_name] = amt
            latest_close_by_sec.setdefault(sw_name, []).append((d_str, cls_val))

    complete_days = sorted(d for d, m in daily_sector_amt.items() if len(m) >= 28)
    if not complete_days:
        raise ValueError("Insufficient Shenwan Level-1 daily history returned")

    as_of = complete_days[-1]
    shares_history: dict[str, list[float]] = {name: [] for name in SW_L1_CODES.values()}
    for d_str in complete_days:
        day_map = daily_sector_amt[d_str]
        total_amt = sum(day_map.values())
        if total_amt <= 0:
            continue
        for sw_name, amt in day_map.items():
            shares_history[sw_name].append((amt / total_amt) * 100.0)

    crowding = {}
    for code, sw_name in SW_L1_CODES.items():
        hist = shares_history.get(sw_name, [])
        latest_share = round(hist[-1], 2) if hist else 0.0
        pct = percentile_rank(hist, hist[-1]) if hist else 50.0
        closes = sorted(latest_close_by_sec.get(sw_name, []))
        ret_5d = 0.0
        if len(closes) >= 6 and closes[-6][1] > 0:
            ret_5d = round(((closes[-1][1] / closes[-6][1]) - 1.0) * 100.0, 2)
        crowding[sw_name] = {
            "code": code + ".SI",
            "turnover_share_pct": latest_share,
            "crowding_percentile_3y": pct,
            "ret_5d_pct": ret_5d,
        }

    return {
        "as_of": as_of,
        "source_note": "申万宏源一级行业日度成交占比近3年历史分位 & 沪深300日线",
        "hs300_latest": hs300_series[-1]["close"] if hs300_series else None,
        "hs300_history": hs300_series[-90:],
        "sw_crowding": crowding,
    }


def import_wind_csv(csv_path: Path, existing: dict) -> dict:
    """Optional offline Wind CSV importer (columns: sector,turnover_share_pct,crowding_percentile_3y,ret_5d_pct)."""
    crowding = dict(existing.get("sw_crowding", {}))
    with csv_path.open("r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            sec = row["sector"].strip()
            if sec in SW_L1_CODES.values():
                crowding[sec] = {
                    "code": row.get("code", ""),
                    "turnover_share_pct": round(float(row["turnover_share_pct"]), 2),
                    "crowding_percentile_3y": round(float(row["crowding_percentile_3y"]), 1),
                    "ret_5d_pct": round(float(row.get("ret_5d_pct", 0.0)), 2),
                }
    return {
        **existing,
        "as_of": datetime.now(BEIJING).date().isoformat(),
        "source_note": "Wind 申万一级行业成交占比分位导入",
        "sw_crowding": crowding,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--import-wind-csv", type=Path, help="Import pre-computed Wind Shenwan crowding CSV")
    args = parser.parse_args()

    existing = json.loads(MARKET_PATH.read_bytes()) if MARKET_PATH.exists() else {}
    if args.import_wind_csv:
        updated = import_wind_csv(args.import_wind_csv, existing)
        atomic_write_json(MARKET_PATH, updated)
        print(f"Imported Wind CSV as_of={updated['as_of']}")
        return 0

    try:
        fresh = fetch_via_akshare()
    except Exception as exc:
        if existing:
            print(
                f"::warning::Market refresh skipped ({type(exc).__name__}: {str(exc)[:180]}); "
                f"retaining as_of={existing.get('as_of')}"
            )
            return 0
        raise

    if existing.get("as_of") and fresh["as_of"] < existing["as_of"]:
        print(f"Retaining newer market snapshot {existing['as_of']}")
        return 0

    if existing == fresh:
        print("Market benchmark unchanged.")
        return 0

    atomic_write_json(MARKET_PATH, fresh)
    print(f"MARKET_UPDATED as_of={fresh['as_of']} hs300={fresh['hs300_latest']} sectors={len(fresh['sw_crowding'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
