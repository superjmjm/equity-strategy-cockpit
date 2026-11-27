"""Unit tests for Experience 7 multi-series priority dedup, shifts, and snapshot generation."""
import unittest

from scripts.build_snapshot import aggregate_week_view, build_full_snapshot, compute_broker_profiles
from scripts.seed_generator import build_demo_market, build_demo_reports


class TestSnapshotBuilder(unittest.TestCase):
    def test_multi_series_same_week_one_vote_dedup(self):
        """If Huatai publishes both a flagship weekly and a flow sub-report in the same week,
        stance votes once (from flagship) while DDM slots complement each other cleanly."""
        market = build_demo_market()
        r_flagship = {
            "report_id": "ht_flagship_01",
            "broker": "华泰证券",
            "series": "策略国内周报",
            "series_role": "flagship",
            "title": "底部夯实",
            "report_date": "2026-11-23",
            "week_mon": "2026-11-23",
            "is_core": True,
            "report_meta": {"archetype": "regular_periodic", "one_line_takeaway": "看多"},
            "market_stance_slot": {
                "stance_tier": "structural_bull",
                "position_guidance": "high_overweight",
                "self_declared_shift": "maintain_stance",
                "marginal_shift_note": None,
                "index_target": None,
                "vote_eligible": True,
                "thesis_summary": "主周报定调结构偏多",
                "evidence_pids": ["P1-S1"],
                "evidence": [{"page": 1, "pid": "P1-S1", "heading": "摘要", "text": "结构偏多", "truncated": False}],
            },
            "ddm_driver_slots": {
                "earnings_macro_slot": {
                    "direction": "bullish_support",
                    "canonical_topic": "credit_m1_pulse",
                    "claim_summary": "M1回升",
                    "vote_eligible": True,
                    "evidence_pids": ["P2-S1"],
                    "evidence": [{"page": 2, "pid": "P2-S1", "heading": "正文", "text": "M1回升", "truncated": False}],
                },
                "liquidity_chip_slot": None,
                "policy_risk_slot": None,
            },
            "style_slots": {"size_style_slot": None, "valuation_style_slot": None},
            "sector_allocation_slot": {
                "overweight_lines": [
                    {
                        "sw_level1_list": ["电子"],
                        "canonical_narrative": "ai_compute_semicon_autonomy",
                        "raw_theme_phrase": "半导体",
                        "catalyst_logic": "订单上修",
                        "vote_eligible": True,
                        "evidence_pids": ["P3-S1"],
                        "evidence": [{"page": 3, "pid": "P3-S1", "heading": "行业", "text": "超配电子", "truncated": False}],
                    }
                ],
                "cautious_lines": [],
            },
            "data_nuggets_slot": [],
            "catalysts_slot": [],
            "golden_stocks_slot": [],
            "risk_invalidator_slot": None,
        }
        r_flow = {
            "report_id": "ht_flow_02",
            "broker": "华泰证券",
            "series": "策略资金透视",
            "series_role": "flow",
            "title": "托底资金流入",
            "report_date": "2026-11-24",
            "week_mon": "2026-11-23",
            "is_core": True,
            "report_meta": {"archetype": "liquidity_crowding", "one_line_takeaway": "ETF净流入"},
            "market_stance_slot": None,  # Sub-report has null stance — must NOT clobber flagship!
            "ddm_driver_slots": {
                "earnings_macro_slot": None,
                "liquidity_chip_slot": {
                    "direction": "bullish_support",
                    "canonical_topic": "etf_institutional_inflow",
                    "claim_summary": "ETF流入300亿",
                    "vote_eligible": True,
                    "evidence_pids": ["P1-S2"],
                    "evidence": [{"page": 1, "pid": "P1-S2", "heading": "资金", "text": "ETF流入", "truncated": False}],
                },
                "policy_risk_slot": None,
            },
            "style_slots": {"size_style_slot": None, "valuation_style_slot": None},
            "sector_allocation_slot": {
                "overweight_lines": [
                    {
                        "sw_level1_list": ["电子"],
                        "canonical_narrative": "ai_compute_semicon_autonomy",
                        "raw_theme_phrase": "算力ETF",
                        "catalyst_logic": "ETF加仓",
                        "vote_eligible": True,
                        "evidence_pids": ["P2-S2"],
                        "evidence": [{"page": 2, "pid": "P2-S2", "heading": "行业", "text": "电子流入", "truncated": False}],
                    }
                ],
                "cautious_lines": [],
            },
            "data_nuggets_slot": [],
            "catalysts_slot": [],
            "golden_stocks_slot": [],
            "risk_invalidator_slot": None,
        }
        reports = [r_flagship, r_flow]
        profiles = compute_broker_profiles(reports, ["2026-11-23"], market["hs300_history"])
        wk = aggregate_week_view("2026-11-23", None, reports, profiles, market)

        # Exactly 1 voter in thermometer, and both earnings & liquidity DDM slots merged!
        self.assertEqual(wk["thermometer"]["all"]["total_voters"], 1)
        self.assertEqual(len(wk["ddm_claims"]), 2)
        # Electronics counted once (100% of 1 unique broker, NOT 200%!)
        elec = next(s for s in wk["sector_matrix"] if s["sw_name"] == "电子")
        self.assertEqual(elec["count_ow_all"], 1)
        self.assertEqual(elec["consensus_all"], 100.0)

    def test_demo_snapshot_end_to_end(self):
        snap = build_full_snapshot(run_stage3=False)
        self.assertTrue(snap["demo_mode"])
        latest = snap["latest_week"]
        wk = snap["weeks"][latest]
        self.assertGreaterEqual(len(wk["marginal_shifts"]), 3)
        # Verify fresh vs crowded golden stock differentiation
        statuses = {s["stock_name"]: s["status"] for s in wk["golden_stocks"]}
        self.assertEqual(statuses.get("北方华创"), "crowded")
        self.assertEqual(statuses.get("先导智能"), "fresh")


if __name__ == "__main__":
    unittest.main()
