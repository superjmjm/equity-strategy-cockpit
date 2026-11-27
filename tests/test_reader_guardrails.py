"""Unit tests for Stage 0 indexing, cover-line filtering, and Stage 2 deterministic guardrails."""
import unittest

import pymupdf as fitz
from jsonschema import validate

from engine.contract import STAGE2
from engine.reader import cover_only, finish_equity_report
from engine.source import index_pdf, select_chart_pages_base64


class TestReaderGuardrails(unittest.TestCase):
    def _make_sample_pdf(self) -> bytes:
        doc = fitz.open()
        p1 = doc.new_page()
        p1.insert_textbox(
            fitz.Rect(50, 50, 540, 720),
            "证券研究报告\n证券分析师：张三\n执业编号：S0000521010001\n\n一、大势配置展望\n\n"
            "伴随化债落地，我们预计上证指数运行区间在3250至3480点，建议超配半导体。",
            fontsize=11,
            fontname="china-s",
        )
        raw = doc.tobytes()
        doc.close()
        return raw

    def test_cover_only_filter(self):
        self.assertTrue(cover_only("证券研究报告\n证券分析师：李四\n执业编号：S1234567890123"))
        self.assertFalse(cover_only("证券分析师：李四\n本周建议提升权益仓位至高配。"))

    def test_stage0_and_finish_guardrails(self):
        pdf = self._make_sample_pdf()
        idx = index_pdf(pdf)
        self.assertGreaterEqual(len(idx["paragraphs"]), 2)
        body_pid = idx["paragraphs"][-1]["pid"]
        cover_pid = idx["paragraphs"][0]["pid"]

        # Valid Stage 2 output with one hallucinated index target (9999) to verify non-destructive nulling
        mock_review = {
            "report_meta": {"archetype": "regular_periodic", "one_line_takeaway": "看多跨年窗口"},
            "market_stance_slot": {
                "stance_tier": "structural_bull",
                "position_guidance": "high_overweight",
                "self_declared_shift": "turn_more_positive",
                "marginal_shift_note": "较上期中性上调",
                "index_target": {"index_name": "上证指数", "point_floor": 3250, "point_ceiling": 9999},
                "vote_eligible": True,
                "thesis_summary": "化债落地提振预期",
                "evidence_pids": [cover_pid, body_pid],
            },
            "ddm_driver_slots": {
                "earnings_macro_slot": None,
                "liquidity_chip_slot": None,
                "policy_risk_slot": {
                    "direction": "bullish_support",
                    "canonical_topic": "fiscal_debt_resolution",
                    "claim_summary": "化债资金落地",
                    "vote_eligible": True,
                    "evidence_pids": [body_pid],
                },
            },
            "style_slots": {"size_style_slot": None, "valuation_style_slot": None},
            "sector_allocation_slot": {
                "overweight_lines": [
                    {
                        "sw_level1_list": ["电子"],
                        "canonical_narrative": "ai_compute_semicon_autonomy",
                        "raw_theme_phrase": "国产半导体",
                        "catalyst_logic": "扩产提速",
                        "vote_eligible": True,
                        "evidence_pids": [body_pid],
                    }
                ],
                "cautious_lines": [],
            },
            "data_nuggets_slot": [],
            "catalysts_slot": [],
            "golden_stocks_slot": [
                {
                    "stock_name": "北方华创",
                    "stock_code": "INVALID_CODE",
                    "sw_level1": "电子",
                    "portfolio_role": "core_bellwether",
                    "recommend_logic": "设备龙头",
                    "evidence_pids": [body_pid],
                }
            ],
            "risk_invalidator_slot": None,
        }
        validate(mock_review, STAGE2)

        meta = {
            "broker": "中信证券",
            "series": "A股策略聚焦",
            "series_role": "flagship",
            "title": "测试报告",
            "report_date": "2026-11-24",
            "week_mon": "2026-11-23",
            "is_core": True,
        }
        out = finish_equity_report(meta, idx, mock_review)

        # Card preserved, invalid 9999 ceiling nulled out cleanly, cover_only pid stripped!
        self.assertIsNotNone(out["market_stance_slot"])
        self.assertIsNone(out["market_stance_slot"]["index_target"])
        self.assertEqual(len(out["numeric_warnings"]), 1)
        self.assertEqual(out["market_stance_slot"]["evidence_pids"], [body_pid])
        # Invalid stock code sanitized to None while keeping stock entry
        self.assertIsNone(out["golden_stocks_slot"][0]["stock_code"])
        self.assertEqual(out["golden_stocks_slot"][0]["stock_name"], "北方华创")

    def test_valid_index_target_preserved(self):
        pdf = self._make_sample_pdf()
        idx = index_pdf(pdf)
        body_pid = idx["paragraphs"][-1]["pid"]
        mock_review = {
            "report_meta": {"archetype": "regular_periodic", "one_line_takeaway": "看多"},
            "market_stance_slot": {
                "stance_tier": "structural_bull",
                "position_guidance": "high_overweight",
                "self_declared_shift": "maintain_stance",
                "marginal_shift_note": None,
                "index_target": {"index_name": "上证指数", "point_floor": 3250, "point_ceiling": 3480},
                "vote_eligible": True,
                "thesis_summary": "区间3250-3480",
                "evidence_pids": [body_pid],
            },
            "ddm_driver_slots": {"earnings_macro_slot": None, "liquidity_chip_slot": None, "policy_risk_slot": None},
            "style_slots": {"size_style_slot": None, "valuation_style_slot": None},
            "sector_allocation_slot": {"overweight_lines": [], "cautious_lines": []},
            "data_nuggets_slot": [],
            "catalysts_slot": [],
            "golden_stocks_slot": [],
            "risk_invalidator_slot": None,
        }
        out = finish_equity_report({"broker": "申万宏源证券", "report_date": "2026-11-24"}, idx, mock_review)
        self.assertEqual(
            out["market_stance_slot"]["index_target"],
            {"index_name": "上证指数", "point_floor": 3250.0, "point_ceiling": 3480.0},
        )
        # Ensure selective vision doesn't crash on plain PDFs
        imgs = select_chart_pages_base64(pdf, idx, max_pages=4)
        self.assertIsInstance(imgs, list)


if __name__ == "__main__":
    unittest.main()
