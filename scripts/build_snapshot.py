"""Deterministic static snapshot.json builder + Experience 7 multi-series dedup + Stage 3 synthesis."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.reader import synthesize_weekly
from scripts.report_scope import CORE_BROKERS, ROLE_PRIORITY, covered_broker, infer_week_mon, is_core_broker, series_role_for
from scripts.store import (
    DEMO_SEED_PATH,
    MARKET_PATH,
    SYNTHESIS_CACHE_PATH,
    atomic_write_json,
    load_all_reports,
)

CN = timezone(timedelta(hours=8))

STANCE_META = {
    "aggressive_bull": {"label": "积极进攻 (高仓位)", "short": "积极进攻", "score": 2, "bar_pct": 88, "tone": "bull"},
    "structural_bull": {"label": "结构性偏多 (哑铃/轮动)", "short": "结构偏多", "score": 1, "bar_pct": 68, "tone": "struct"},
    "neutral_range": {"label": "中性震荡 (高低切整固)", "short": "中性整固", "score": 0, "bar_pct": 48, "tone": "neutral"},
    "defensive_cautious": {"label": "防御谨慎 (控仓避险)", "short": "防御谨慎", "score": -1, "bar_pct": 26, "tone": "bear"},
}

DDM_TOPIC_LABELS = {
    "credit_m1_pulse": "社融与M1企业现金流活化",
    "ppi_earnings_roe": "PPI价格传导与全A盈利斜率",
    "supply_capex_clearing": "中游Capex收缩与供给侧出清",
    "domestic_demand_property": "地产企稳与内需实物工作量",
    "etf_institutional_inflow": "宽基ETF申购与险资长线托底",
    "retail_leverage_sentiment": "两融活跃资金与散户情绪",
    "crowding_year_end_rebalance": "局部换手过热与岁末考核结账",
    "fed_fx_foreign_flow": "美联储利率、汇率与外资流向",
    "fiscal_debt_resolution": "10万亿化债落地与财政扩张预期",
    "consumption_new_productivity_policy": "以旧换新补贴与新质生产力政策",
    "capital_market_soe_reform": "市值管理新规与破净央企重估",
    "tariff_geopolitics_risk": "海外关税清单与科技出口管制",
    "other_specific_driver": "其他独立边际驱动因素",
}

NARRATIVE_LABELS = {
    "ai_compute_semicon_autonomy": "国产算力与半导体自主可控",
    "ai_application_smart_hardware": "AI端侧硬件与Agent应用",
    "solid_battery_new_energy_turnaround": "固态电池与锂电排产反转",
    "supply_clearing_anti_involution": "顺周期供给侧出清/反内卷",
    "trade_in_service_consumption": "以旧换新与服务消费扩容",
    "high_dividend_soe_valuation": "高股息红利与破净央企重估",
    "debt_relief_fiscal_beneficiary": "地方化债与G端回款修复",
    "ma_restructuring_tech_reform": "科创并购重组与资产注入",
    "non_us_grid_machinery_export": "非美电网与工程机械出海",
    "north_america_export_chain": "欧美外需出口链",
    "robotics_low_altitude_new_tech": "人形机器人与低空经济",
    "healthcare_innovative_drug": "创新药与医疗设备更新",
    "cyclical_resources_gold": "上游资源品与贵金属",
    "pure_sector_fundamental": "行业景气业绩主线",
    "other_emergent_theme": "新兴细分主题",
}

ROLE_LABELS = {
    "core_bellwether": "主线核心中军 / 业绩锚",
    "turnaround_alpha": "底部困境反转 + 新催化先锋",
    "growth_elasticity": "高景气成长弹性先锋",
    "dividend_defensive": "高股息稳健搭台底仓",
    "policy_theme": "化债/市值管理政策重估",
}


def week_meta(mon_str: str) -> dict:
    d = date.fromisoformat(mon_str)
    iso_y, iso_w, _ = d.isocalendar()
    sun = d + timedelta(days=6)
    return {
        "week_mon": mon_str,
        "label": f"{iso_y} W{iso_w:02d} ({d.strftime('%m.%d')}–{sun.strftime('%m.%d')})",
        "short": f"W{iso_w:02d}",
    }


def _std(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    mean = sum(vals) / len(vals)
    return math.sqrt(sum((x - mean) ** 2 for x in vals) / (len(vals) - 1))


def report_priority(r: dict, has_vote: bool = True) -> tuple:
    role = r.get("series_role") or series_role_for(r["broker"], r.get("series", ""))
    archetype_bonus = 1 if r.get("report_meta", {}).get("archetype") == "regular_periodic" else 0
    return (
        ROLE_PRIORITY.get(role, 1),
        archetype_bonus,
        1 if has_vote else 0,
        r.get("report_date", ""),
        r.get("report_id", ""),
    )


def compute_broker_profiles(reports: list[dict], all_weeks: list[str], hs300_history: list[dict]) -> dict[str, dict]:
    """Compute objective persona tag & 12-week stance trajectory overlaid with HS300 close."""
    recent_weeks = all_weeks[-12:]
    hs_sorted = sorted(hs300_history, key=lambda x: x["date"])

    def hs_for_week(mon_str: str) -> float | None:
        sun_str = (date.fromisoformat(mon_str) + timedelta(days=6)).isoformat()
        val = None
        for pt in hs_sorted:
            if pt["date"] <= sun_str:
                val = pt["close"]
            else:
                break
        return val

    # Best stance per (broker, week)
    stance_by_bw: dict[tuple[str, str], dict] = {}
    ddm_counts: dict[str, Counter] = defaultdict(Counter)

    for r in reports:
        b = covered_broker(r["broker"]) or r["broker"]
        w = r.get("week_mon") or infer_week_mon(r["report_date"])
        st = r.get("market_stance_slot")
        if st:
            key = (b, w)
            cand = {"report": r, "stance": st}
            if key not in stance_by_bw or report_priority(r, st.get("vote_eligible", False)) > report_priority(
                stance_by_bw[key]["report"], stance_by_bw[key]["stance"].get("vote_eligible", False)
            ):
                stance_by_bw[key] = cand
        ddm = r.get("ddm_driver_slots") or {}
        for k in ("earnings_macro_slot", "liquidity_chip_slot", "policy_risk_slot"):
            if ddm.get(k):
                ddm_counts[b][k] += 1

    brokers = sorted({covered_broker(r["broker"]) or r["broker"] for r in reports})
    profiles = {}
    for b in brokers:
        scores = []
        traj = []
        for w in recent_weeks:
            entry = stance_by_bw.get((b, w))
            hs_val = hs_for_week(w)
            if entry:
                tier = entry["stance"]["stance_tier"]
                meta = STANCE_META[tier]
                scores.append(float(meta["score"]))
                traj.append({
                    "week": week_meta(w)["short"],
                    "week_mon": w,
                    "stance_tier": tier,
                    "stance_label": meta["short"],
                    "score": meta["score"],
                    "bar_pct": meta["bar_pct"],
                    "hs300_close": hs_val,
                })
            else:
                traj.append({
                    "week": week_meta(w)["short"],
                    "week_mon": w,
                    "stance_tier": None,
                    "stance_label": "未发报",
                    "score": None,
                    "bar_pct": 0,
                    "hs300_close": hs_val,
                })

        mean_s = sum(scores) / len(scores) if scores else 0.5
        std_s = _std(scores)
        tot_ddm = sum(ddm_counts[b].values()) or 1
        liq_ratio = ddm_counts[b]["liquidity_chip_slot"] / tot_ddm

        if len(scores) >= 2 and mean_s >= 1.35 and std_s < 0.55:
            persona = "常年偏多型 · 降温需高度警惕"
            is_perma_bull = True
        elif len(scores) >= 2 and std_s >= 0.75:
            persona = "波段择时型 · 赔率胜率框架"
            is_perma_bull = False
        elif liq_ratio >= 0.45 and tot_ddm >= 2:
            persona = "微观资金与ETF跟踪派"
            is_perma_bull = False
        else:
            persona = "大势均衡与政策配置派"
            is_perma_bull = False

        profiles[b] = {
            "broker": b,
            "is_core": is_core_broker(b),
            "persona": persona,
            "is_perma_bull": is_perma_bull,
            "mean_stance_score": round(mean_s, 2),
            "trajectory_12w": traj,
        }
    return profiles


def aggregate_week_view(
    target_week: str,
    prev_week: str | None,
    reports: list[dict],
    profiles: dict[str, dict],
    market_data: dict,
    *,
    run_stage3: bool = False,
    synthesis_cache: dict | None = None,
) -> dict:
    """Aggregate one observation week with Experience 7 same-broker same-dimension dedup."""
    week_reports = [r for r in reports if (r.get("week_mon") or infer_week_mon(r["report_date"])) == target_week]
    prev_reports = (
        [r for r in reports if (r.get("week_mon") or infer_week_mon(r["report_date"])) == prev_week]
        if prev_week
        else []
    )

    # 1) Dedup market_stance_slot per broker
    def dedup_stance(rep_list: list[dict]) -> dict[str, tuple[dict, dict]]:
        best: dict[str, tuple[dict, dict]] = {}
        for r in rep_list:
            st = r.get("market_stance_slot")
            if not st:
                continue
            b = covered_broker(r["broker"]) or r["broker"]
            if b not in best or report_priority(r, st.get("vote_eligible", False)) > report_priority(
                best[b][0], best[b][1].get("vote_eligible", False)
            ):
                best[b] = (r, st)
        return best

    curr_stances = dedup_stance(week_reports)
    prev_stances = dedup_stance(prev_reports)

    def calc_thermometer(pool_mode: str) -> dict:
        counts = {k: 0 for k in STANCE_META}
        voters = []
        for b, (rep, st) in curr_stances.items():
            if not st.get("vote_eligible", True):
                continue
            if pool_mode == "core" and not is_core_broker(b):
                continue
            counts[st["stance_tier"]] += 1
            voters.append(b)
        total = sum(counts.values())
        segments = []
        for k, meta in STANCE_META.items():
            c = counts[k]
            pct = round((c / total) * 100.0, 1) if total else 0.0
            segments.append({
                "tier": k,
                "label": meta["label"],
                "short": meta["short"],
                "tone": meta["tone"],
                "count": c,
                "pct": pct,
            })
        return {"total_voters": total, "segments": segments}

    thermometer = {
        "all": calc_thermometer("all"),
        "core": calc_thermometer("core"),
    }

    # 2) Marginal Shift Radar (comparing curr_stances vs prev_stances + self_declared_shift)
    shifts = []
    for b, (rep, st) in curr_stances.items():
        prof = profiles.get(b, {})
        prev_pair = prev_stances.get(b)
        prev_tier = prev_pair[1]["stance_tier"] if prev_pair else None
        curr_tier = st["stance_tier"]
        self_shift = st.get("self_declared_shift", "unspecified")

        tier_changed = prev_tier is not None and prev_tier != curr_tier
        explicit_pivot = self_shift in ("turn_more_positive", "turn_more_cautious", "pivot_style_or_structure")
        if not (tier_changed or explicit_pivot):
            continue

        curr_score = STANCE_META[curr_tier]["score"]
        prev_score = STANCE_META[prev_tier]["score"] if prev_tier else curr_score
        if curr_score > prev_score or self_shift == "turn_more_positive":
            direction = "bull"
            badge = "↑ 边际上调"
        elif curr_score < prev_score or self_shift == "turn_more_cautious":
            direction = "bear"
            badge = "⚠ 反常降温预警" if prof.get("is_perma_bull") else "↓ 边际降温"
        else:
            direction = "bull"
            badge = "↺ 结构切换"

        shifts.append({
            "id": f"shift-{rep['report_id'][:12]}",
            "broker": b,
            "is_core": is_core_broker(b),
            "persona": prof.get("persona", "大势配置派"),
            "from_label": STANCE_META[prev_tier]["short"] if prev_tier else "前期基准",
            "to_label": STANCE_META[curr_tier]["short"],
            "direction": direction,
            "signal_badge": badge,
            "summary": st.get("marginal_shift_note") or st["thesis_summary"],
            "thesis_summary": st["thesis_summary"],
            "index_target": st.get("index_target"),
            "report_id": rep["report_id"],
            "report_title": rep["title"],
            "report_date": rep["report_date"],
            "drive_file_id": rep.get("drive_file_id"),
            "evidence": st.get("evidence", []),
            "schema_preview": {
                "level": "大势仓位定调",
                "ddm": "全局多空权重",
                "delta": f"{STANCE_META[prev_tier]['short'] if prev_tier else '前期'} → {STANCE_META[curr_tier]['short']}",
                "framework": rep.get("series", "策略周报"),
            },
        })

    shifts.sort(key=lambda s: (0 if "反常" in s["signal_badge"] else 1, 0 if s["is_core"] else 1, s["broker"]))

    # 3) DDM 3-Factor Bull/Bear Argument Collider (1 vote per broker per DDM pillar)
    pillar_names = {
        "earnings_macro_slot": ("earnings", "分子端 · 盈利与宏观"),
        "liquidity_chip_slot": ("liquidity", "分母端 · 流动性与筹码"),
        "policy_risk_slot": ("risk", "分母端 · 政策与风险偏好"),
    }
    ddm_dedup: dict[tuple[str, str], tuple[dict, dict]] = {}
    for r in week_reports:
        b = covered_broker(r["broker"]) or r["broker"]
        ddm_map = r.get("ddm_driver_slots") or {}
        for slot_k in pillar_names:
            sub = ddm_map.get(slot_k)
            if not sub:
                continue
            key = (b, slot_k)
            if key not in ddm_dedup or report_priority(r, sub.get("vote_eligible", False)) > report_priority(
                ddm_dedup[key][0], ddm_dedup[key][1].get("vote_eligible", False)
            ):
                ddm_dedup[key] = (r, sub)

    ddm_clusters: dict[tuple[str, str, str], list[tuple[str, dict, dict]]] = defaultdict(list)
    for (b, slot_k), (rep, sub) in ddm_dedup.items():
        if sub["direction"] == "neutral_watch":
            continue
        side = "bull" if sub["direction"] == "bullish_support" else "bear"
        ddm_clusters[(slot_k, side, sub["canonical_topic"])].append((b, rep, sub))

    ddm_claims = []
    for (slot_k, side, topic), members in ddm_clusters.items():
        # Sort so core flagship broker claim serves as lead headline
        members.sort(key=lambda m: (0 if is_core_broker(m[0]) else 1, m[0]))
        lead_b, lead_rep, lead_sub = members[0]
        p_code, p_label = pillar_names[slot_k]
        brokers_all = [f"{m[0].removesuffix('证券')}★" if is_core_broker(m[0]) else m[0].removesuffix("证券") for m in members]
        brokers_core = [f"{m[0].removesuffix('证券')}★" for m in members if is_core_broker(m[0])]
        ddm_claims.append({
            "id": f"ddm-{p_code}-{side}-{topic}",
            "side": side,
            "pillar": p_code,
            "pillar_label": p_label,
            "topic_label": DDM_TOPIC_LABELS.get(topic, topic),
            "title": lead_sub["claim_summary"],
            "brokers_all": brokers_all,
            "brokers_core": brokers_core,
            "lead_broker": lead_b,
            "report_id": lead_rep["report_id"],
            "report_title": lead_rep["title"],
            "report_date": lead_rep["report_date"],
            "drive_file_id": lead_rep.get("drive_file_id"),
            "evidence": lead_sub.get("evidence", []),
            "member_quotes": [
                {
                    "broker": m[0],
                    "is_core": is_core_broker(m[0]),
                    "claim": m[2]["claim_summary"],
                    "report_title": m[1]["title"],
                    "page": m[2]["evidence"][0]["page"] if m[2].get("evidence") else 1,
                }
                for m in members
            ],
            "schema_preview": {
                "level": "DDM 核心因子论据",
                "ddm": p_label,
                "delta": "做多支撑 ↑" if side == "bull" else "掣肘顾虑 ↓",
                "framework": DDM_TOPIC_LABELS.get(topic, topic),
            },
        })
    ddm_claims.sort(key=lambda c: (-len(c["brokers_all"]), c["pillar"]))

    # 4) Sector x Narrative Crowding Matrix (1 vote per broker per SW sector)
    def collect_sector_votes(rep_list: list[dict]):
        ow_by_sec: dict[str, dict[str, tuple[dict, dict]]] = defaultdict(dict)
        caut_by_sec: dict[str, dict[str, tuple[dict, dict]]] = defaultdict(dict)
        for r in rep_list:
            b = covered_broker(r["broker"]) or r["broker"]
            alloc = r.get("sector_allocation_slot") or {}
            for line in alloc.get("overweight_lines", []):
                if not line.get("vote_eligible", True):
                    continue
                for sw in line.get("sw_level1_list", []):
                    if b not in ow_by_sec[sw] or report_priority(r, True) > report_priority(ow_by_sec[sw][b][0], True):
                        ow_by_sec[sw][b] = (r, line)
            for line in alloc.get("cautious_lines", []):
                if not line.get("vote_eligible", True):
                    continue
                for sw in line.get("sw_level1_list", []):
                    if b not in caut_by_sec[sw] or report_priority(r, True) > report_priority(caut_by_sec[sw][b][0], True):
                        caut_by_sec[sw][b] = (r, line)
        return ow_by_sec, caut_by_sec

    curr_ow, curr_caut = collect_sector_votes(week_reports)
    prev_ow, _ = collect_sector_votes(prev_reports)

    active_brokers_all = {covered_broker(r["broker"]) or r["broker"] for r in week_reports}
    active_brokers_core = {b for b in active_brokers_all if is_core_broker(b)}
    denom_all = max(len(active_brokers_all), 1)
    denom_core = max(len(active_brokers_core), 1)
    sw_crowding_map = market_data.get("sw_crowding", {})

    all_mentioned_sw = sorted(set(curr_ow.keys()) | set(curr_caut.keys()))
    sector_matrix = []
    for sw in all_mentioned_sw:
        ow_brokers_all = set(curr_ow.get(sw, {}).keys())
        ow_brokers_core = {b for b in ow_brokers_all if is_core_broker(b)}
        prev_brokers_all = set(prev_ow.get(sw, {}).keys())
        prev_brokers_core = {b for b in prev_brokers_all if is_core_broker(b)}

        caut_brokers_all = set(curr_caut.get(sw, {}).keys())
        caut_brokers_core = {b for b in caut_brokers_all if is_core_broker(b)}

        cons_all = round((len(ow_brokers_all) / denom_all) * 100.0, 1)
        cons_core = round((len(ow_brokers_core) / denom_core) * 100.0, 1)
        # Net weekly marginal change: new overweights minus prev overweights minus cautious warnings
        delta_all = len(ow_brokers_all) - len(prev_brokers_all) - (len(caut_brokers_all) if not prev_reports else 0)
        delta_core = len(ow_brokers_core) - len(prev_brokers_core) - (len(caut_brokers_core) if not prev_reports else 0)
        if prev_reports and caut_brokers_all and delta_all == 0:
            delta_all = -len(caut_brokers_all)
        if prev_reports and caut_brokers_core and delta_core == 0:
            delta_core = -len(caut_brokers_core)

        ow_entries = list(curr_ow.get(sw, {}).items())
        caut_entries = list(curr_caut.get(sw, {}).items())
        ow_entries.sort(key=lambda x: (0 if is_core_broker(x[0]) else 1, x[0]))
        caut_entries.sort(key=lambda x: (0 if is_core_broker(x[0]) else 1, x[0]))

        narratives = Counter(item[1][1]["canonical_narrative"] for item in ow_entries + caut_entries)
        top_narr = narratives.most_common(1)[0][0] if narratives else "pure_sector_fundamental"
        raw_phrases = list(dict.fromkeys(
            item[1][1]["raw_theme_phrase"] for item in ow_entries + caut_entries if item[1][1].get("raw_theme_phrase")
        ))[:6]

        crowd_info = sw_crowding_map.get(sw, {"turnover_share_pct": 2.0, "crowding_percentile_3y": 50.0, "ret_5d_pct": 0.0})
        cpct = crowd_info["crowding_percentile_3y"]
        if cpct >= 75:
            crowd_label = f"成交占比 {cpct}% 分位 · 偏拥挤预警"
        elif cpct <= 35:
            crowd_label = f"成交占比 {cpct}% 分位 · 低位筹码干净"
        else:
            crowd_label = f"成交占比 {cpct}% 分位 · 适中健康"

        if cons_all >= 45 and delta_all >= 0:
            quad = "右上：强共识·升温主线"
            qtone = "bull"
        elif cons_all < 45 and delta_all > 0:
            quad = "★ 左上：低共识·新升温Alpha"
            qtone = "info"
        elif cons_all >= 45 and delta_all < 0:
            quad = "右下：强共识·分歧降温"
            qtone = "warn"
        else:
            quad = "左下：低共识·规避降温"
            qtone = "bear"

        lead_entry = (ow_entries or caut_entries)[0]
        lead_b, (lead_rep, lead_line) = lead_entry

        bull_text = (
            "；".join(f"【{b.removesuffix('证券')}{'★' if is_core_broker(b) else ''}】{ln['catalyst_logic']}" for b, (_, ln) in ow_entries[:3])
            if ow_entries else "本周暂无卖方将其列为首选超配主线。"
        )
        bear_text = (
            "；".join(f"【{b.removesuffix('证券')}{'★' if is_core_broker(b) else ''}】{ln['catalyst_logic']}" for b, (_, ln) in caut_entries[:3])
            if caut_entries else "本周暂未见卖方明确提示兑现或规避。"
        )

        sector_matrix.append({
            "id": f"sec-{sw}",
            "sw_name": sw,
            "narrative_label": NARRATIVE_LABELS.get(top_narr, top_narr),
            "short_label": f"{sw}·{raw_phrases[0][:6]}" if raw_phrases else sw,
            "raw_themes": raw_phrases or [sw],
            "consensus_all": cons_all,
            "consensus_core": cons_core,
            "count_ow_all": len(ow_brokers_all),
            "count_ow_core": len(ow_brokers_core),
            "delta_all": delta_all,
            "delta_core": delta_core,
            "crowding_pct": cpct,
            "turnover_share_pct": crowd_info["turnover_share_pct"],
            "ret_5d_pct": crowd_info["ret_5d_pct"],
            "crowding_status": crowd_label,
            "quadrant": quad,
            "quadrant_tone": qtone,
            "weight_radius": min(18, 9 + len(ow_brokers_all) * 2),
            "bull_logic": bull_text,
            "bear_logic": bear_text,
            "lead_broker": lead_b,
            "report_id": lead_rep["report_id"],
            "report_title": lead_rep["title"],
            "report_date": lead_rep["report_date"],
            "drive_file_id": lead_rep.get("drive_file_id"),
            "evidence": lead_line.get("evidence", []),
            "schema_preview": {
                "level": "中观行业×叙事映射",
                "ddm": f"申万一级：{sw}",
                "delta": f"共识 {cons_all}% / 周边际 {delta_all:+d}家",
                "framework": NARRATIVE_LABELS.get(top_narr, top_narr),
            },
        })

    sector_matrix.sort(key=lambda x: (-x["consensus_all"], -x["delta_all"]))

    # 5) Data Nuggets & Catalysts
    nuggets = []
    for r in week_reports:
        b = covered_broker(r["broker"]) or r["broker"]
        for idx_n, nug in enumerate(r.get("data_nuggets_slot", [])):
            nuggets.append({
                "id": f"nug-{r['report_id'][:10]}-{idx_n}",
                "category": nug["category"],
                "category_label": {
                    "flow_crowding": "资金与筹码结构",
                    "meso_fundamental": "中观景气与供给侧",
                    "valuation_calendar": "估值与日历效应",
                }.get(nug["category"], "数据抓手"),
                "metric_phrase": nug["metric_phrase"],
                "implication": nug["forward_implication"],
                "chart_likely_on_page": nug.get("chart_likely_on_page", False),
                "primary_page": nug.get("primary_page") or (nug["evidence"][0]["page"] if nug.get("evidence") else 1),
                "broker": b,
                "is_core": is_core_broker(b),
                "report_id": r["report_id"],
                "report_title": r["title"],
                "report_date": r["report_date"],
                "drive_file_id": r.get("drive_file_id"),
                "evidence": nug.get("evidence", []),
                "schema_preview": {
                    "level": "去水词增量数据",
                    "ddm": nug["category"],
                    "delta": nug["metric_phrase"][:22],
                    "framework": f"原报告 P.{nug.get('primary_page', 1)} 图表/数据定位",
                },
            })
    nuggets.sort(key=lambda n: (0 if n["is_core"] else 1, 0 if n["chart_likely_on_page"] else 1))

    catalysts = []
    seen_cat_titles = set()
    for r in week_reports:
        b = covered_broker(r["broker"]) or r["broker"]
        for cat in r.get("catalysts_slot", []):
            norm_t = cat["event_title"].strip()
            if norm_t in seen_cat_titles:
                continue
            seen_cat_titles.add(norm_t)
            catalysts.append({
                "time_window": cat["time_window"],
                "event_title": norm_t,
                "scenario_impact": cat["scenario_impact"],
                "broker": b,
                "is_core": is_core_broker(b),
            })
    catalysts.sort(key=lambda c: c["time_window"])

    # 6) Golden Stocks Resonance Pool (Fresh vs Crowded across recent 30 days vs prior window)
    target_monday = date.fromisoformat(target_week)
    recent_cutoff = (target_monday - timedelta(days=28)).isoformat()
    older_cutoff = (target_monday - timedelta(days=65)).isoformat()

    prior_stock_names = {
        stk["stock_name"].strip()
        for r in reports
        if older_cutoff <= r["report_date"] < target_week
        for stk in r.get("golden_stocks_slot", [])
    }

    stock_groups: dict[str, dict[str, tuple[dict, dict]]] = defaultdict(dict)
    for r in reports:
        if not (recent_cutoff <= r["report_date"] <= (target_monday + timedelta(days=6)).isoformat()):
            continue
        b = covered_broker(r["broker"]) or r["broker"]
        for stk in r.get("golden_stocks_slot", []):
            sname = stk["stock_name"].strip()
            # Latest pick from each broker wins
            if b not in stock_groups[sname] or r["report_date"] >= stock_groups[sname][b][0]["report_date"]:
                stock_groups[sname][b] = (r, stk)

    golden_stocks = []
    for sname, broker_map in stock_groups.items():
        entries = sorted(broker_map.items(), key=lambda x: (0 if is_core_broker(x[0]) else 1, x[0]))
        lead_b, (lead_rep, lead_stk) = entries[0]
        count_all = len(entries)
        count_core = sum(1 for b, _ in entries if is_core_broker(b))
        is_fresh = sname not in prior_stock_names
        status = "crowded" if count_all >= 3 and not is_fresh else ("fresh" if is_fresh else "normal")
        if count_all >= 3 and not is_fresh:
            status_label = f"🔥 {count_all}家扎堆金股 (核心池{count_core}家)"
        elif is_fresh:
            status_label = f"★ 本期新进标的 ({count_all}家调入)"
        else:
            status_label = f"持续跟踪 ({count_all}家推荐)"

        golden_stocks.append({
            "id": f"stk-{hashlib.md5(sname.encode()).hexdigest()[:10]}",
            "stock_name": sname,
            "stock_code": lead_stk.get("stock_code") or "—",
            "sw_level1": lead_stk["sw_level1"],
            "status": status,
            "status_label": status_label,
            "count_all": count_all,
            "count_core": count_core,
            "brokers_all": [f"{b.removesuffix('证券')}{'★' if is_core_broker(b) else ''}" for b, _ in entries],
            "brokers_core": [f"{b.removesuffix('证券')}★" for b, _ in entries if is_core_broker(b)],
            "role_label": ROLE_LABELS.get(lead_stk["portfolio_role"], lead_stk["portfolio_role"]),
            "logic": "；".join(f"【{b.removesuffix('证券')}】{st['recommend_logic']}" for b, (_, st) in entries[:3]),
            "lead_broker": lead_b,
            "report_id": lead_rep["report_id"],
            "report_title": lead_rep["title"],
            "report_date": lead_rep["report_date"],
            "drive_file_id": lead_rep.get("drive_file_id"),
            "evidence": lead_stk.get("evidence", []),
            "schema_preview": {
                "level": "月度金股与标的池",
                "ddm": f"申万：{lead_stk['sw_level1']}",
                "delta": status_label,
                "framework": ROLE_LABELS.get(lead_stk["portfolio_role"], "策略金股"),
            },
        })
    golden_stocks.sort(key=lambda s: (0 if s["status"] == "fresh" else 1, -s["count_all"], s["stock_name"]))

    # 7) Stage 3 Weekly Chief Strategist Synthesis (cached by hash of week's report IDs)
    week_sig = hashlib.sha256(
        json.dumps(sorted(r["report_id"] for r in week_reports)).encode()
    ).hexdigest()[:20]

    synthesis = (synthesis_cache or {}).get(week_sig)
    if not synthesis and run_stage3 and os.environ.get("OPENAI_API_KEY", "").strip() and week_reports:
        s3_input = {
            "week": target_week,
            "thermometer": thermometer,
            "candidate_shifts": [
                {"broker": s["broker"], "is_core": s["is_core"], "persona": s["persona"], "change": f"{s['from_label']}->{s['to_label']}", "summary": s["summary"]}
                for s in shifts
            ],
            "ddm_Bull_vs_Bear": [{"side": c["side"], "pillar": c["pillar_label"], "brokers": c["brokers_all"], "claim": c["title"]} for c in ddm_claims],
            "raw_sector_themes": [
                {"broker": r["broker"], "overweights": [x["raw_theme_phrase"] for x in r.get("sector_allocation_slot", {}).get("overweight_lines", [])]}
                for r in week_reports
            ],
        }
        try:
            synthesis, _ = synthesize_weekly(s3_input)
            if synthesis_cache is not None:
                synthesis_cache[week_sig] = synthesis
        except Exception as exc:
            print(f"::warning::Stage 3 weekly synthesis fallback triggered ({type(exc).__name__})")

    if not synthesis:
        bull_top = next((c["title"] for c in ddm_claims if c["side"] == "bull"), "政策底与流动性托底明确")
        bear_top = next((c["title"] for c in ddm_claims if c["side"] == "bear"), "局部换手率偏高与基本面传导时滞")
        synthesis = {
            "executive_clash_summary": f"多空核心分歧聚焦于「政策预期抢跑」与「岁末筹码考核」：看多阵营立足于 {bull_top[:42]}；谨慎阵营则聚焦 {bear_top[:42]}。",
            "core_vs_all_divergence_note": (
                f"全样本 {thermometer['all']['total_voters']} 家投票机构偏多占主导；切换至 ★核心首席白名单 ({thermometer['core']['total_voters']}家) 后，"
                "需重点跟踪常年多头降档整固与均衡派由守转攻的结构性分化信号。"
            ),
            "verified_shifts": [],
            "emergent_narratives": [],
        }

    return {
        "week_info": week_meta(target_week),
        "report_count": len(week_reports),
        "broker_count_all": len(active_brokers_all),
        "broker_count_core": len(active_brokers_core),
        "synthesis": synthesis,
        "thermometer": thermometer,
        "marginal_shifts": shifts,
        "ddm_claims": ddm_claims,
        "sector_matrix": sector_matrix,
        "data_nuggets": nuggets,
        "catalysts": catalysts,
        "golden_stocks": golden_stocks,
    }


def build_full_snapshot(*, run_stage3: bool = False) -> dict:
    real_reports = load_all_reports()
    demo_mode = len(real_reports) == 0
    if demo_mode:
        if not DEMO_SEED_PATH.exists():
            from scripts.seed_generator import main as seed_main
            seed_main()
        reports = json.loads(DEMO_SEED_PATH.read_bytes())
    else:
        reports = real_reports

    if MARKET_PATH.exists():
        market_data = json.loads(MARKET_PATH.read_bytes())
    else:
        from scripts.seed_generator import build_demo_market
        market_data = build_demo_market()

    synthesis_cache = json.loads(SYNTHESIS_CACHE_PATH.read_bytes()) if SYNTHESIS_CACHE_PATH.exists() else {}
    cache_before = json.dumps(synthesis_cache, sort_keys=True)

    all_weeks = sorted({r.get("week_mon") or infer_week_mon(r["report_date"]) for r in reports})
    profiles = compute_broker_profiles(reports, all_weeks, market_data.get("hs300_history", []))

    recent_weeks = all_weeks[-8:]
    weeks_payload = {}
    for idx, w in enumerate(recent_weeks):
        prev_w = all_weeks[all_weeks.index(w) - 1] if all_weeks.index(w) > 0 else None
        is_latest = idx == len(recent_weeks) - 1
        weeks_payload[w] = aggregate_week_view(
            w,
            prev_w,
            reports,
            profiles,
            market_data,
            run_stage3=(run_stage3 and is_latest and not demo_mode),
            synthesis_cache=synthesis_cache,
        )

    if not demo_mode and json.dumps(synthesis_cache, sort_keys=True) != cache_before:
        atomic_write_json(SYNTHESIS_CACHE_PATH, synthesis_cache)

    return {
        "schema_version": "equity-cockpit-v1",
        "generated_at": datetime.now(CN).strftime("%Y-%m-%d %H:%M BJT"),
        "demo_mode": demo_mode,
        "total_archived_reports": len(reports),
        "core_whitelist": list(CORE_BROKERS),
        "market_benchmark": {
            "as_of": market_data.get("as_of"),
            "hs300_latest": market_data.get("hs300_latest"),
            "source_note": market_data.get("source_note"),
        },
        "available_weeks": [week_meta(w) for w in reversed(recent_weeks)],
        "latest_week": recent_weeks[-1] if recent_weeks else None,
        "broker_profiles": profiles,
        "weeks": weeks_payload,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "web" / "snapshot.json")
    parser.add_argument("--run-stage3", action="store_true", help="Invoke Stage 3 LLM synthesis for uncached latest week")
    args = parser.parse_args()

    doc = build_full_snapshot(run_stage3=args.run_stage3)
    atomic_write_json(args.output, doc)
    print(
        f"SNAPSHOT_BUILT output={args.output} demo_mode={doc['demo_mode']} "
        f"weeks={len(doc['available_weeks'])} reports={doc['total_archived_reports']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
