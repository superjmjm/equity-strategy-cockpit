"""SOP Step 3: 50+ real positive & negative NXNY titles testing one-broker-one-rule intake."""
import unittest

from scripts.report_scope import (
    classify_equity_title,
    infer_week_mon,
    manual_identity,
    non_pdf_suffix,
    weekly_broker,
)


class TestEquityReportScope(unittest.TestCase):
    def test_real_positive_nxny_titles(self):
        positives = [
            # (title, pages, expected_broker, expected_series)
            ("6539200-申万宏源-策略一周回顾展望：各种风险正被充分定价-261121", 9, "申万宏源证券", "策略一周回顾展望"),
            ("6539150-申万宏源-行业比较周跟踪：A股估值及行业中观景气跟踪周报-261122", 6, "申万宏源证券", "行业比较周跟踪"),
            ("6539410-广发证券-周末五分钟全知道(11月第3期)：当前红利资产估值还有多少空间？-261122", 25, "广发证券", "周末五分钟全知道"),
            ("6521000-广发证券-资配月度展望(主观篇)：剥极则复-261106", 22, "广发证券", "资配月度展望"),
            ("6525001-国泰海通证券-中国权益策略周报：机会是等出来的-261108", 17, "国泰海通证券", "中国权益策略周报"),
            ("6540110-国泰君安-A股策略周报：跨年布局正当时-261124", 18, "国泰海通证券", "中国权益策略周报"),
            ("6540111-海通证券-中观景气跟踪11月第4期：AI硬件涨价趋势走弱-261125", 11, "国泰海通证券", "中观景气跟踪"),
            ("6525009-国泰海通证券-投资者微观行为洞察手册11月第1期：ETF持续大幅流入-261108", 27, "国泰海通证券", "投资者微观行为洞察"),
            ("6539675-华泰证券-策略国内周报-资金透视：托底资金持续流入-261124", 17, "华泰证券", "策略资金透视"),
            ("6531010-华泰证券-策略国内周报：底部仍待夯实-261115", 6, "华泰证券", "策略国内周报"),
            ("6538001-华泰证券-策略：底部区域孕育布局机会-261122", 5, "华泰证券", "策略国内周报"),
            ("6524002-华泰证券-国内周报：底部初具，静待接力-261108", 6, "华泰证券", "策略国内周报"),
            ("6531020-华泰证券-策略月报：内需消费景气或底部反转——中观景气与战术配置月报-261115", 28, "华泰证券", "中观景气与战术配置月报"),
            ("6539601-招商证券-A股投资策略周报(1115)：赎回、贴水与加息预期-261115", 35, "招商证券", "A股投资策略周报"),
            ("6539602-招商证券-A股趋势与风格定量观察：短期平台震荡概率仍较大-261115", 8, "招商证券", "A股趋势与风格定量观察"),
            ("6540152-招商证券-金融市场流动性与监管动态周报：保险资金三季度权益资产配比创10年新高-261125", 10, "招商证券", "金融市场流动性周报"),
            ("6538200-中信建投-策略周思考：紧盯流动性，静待转机-261122", 20, "中信建投证券", "策略周思考"),
            ("6538201-中信建投-策略周报2026年11月第3期：哪些热点有望继续上涨？-261123", 26, "中信建投证券", "策略周思考"),
            ("6534100-中信建投-一周策略回顾与展望-261118", 12, "中信建投证券", "策略周思考"),
            ("6538202-中信建投-策略市场周鉴：海外流动性冲击蔓延-261123", 15, "中信建投证券", "策略市场周鉴"),
            ("6538203-中信建投-流动性周观察11月第4期：ETF资金流入超过1800亿元-261123", 24, "中信建投证券", "流动性周观察"),
            ("6532001-中金公司-A股策略：如何研判A股市场底部？-261116", 2, "中金公司", "A股策略周报"),
            ("6531800-天风证券-A股策略周报：PPI高点或现-261115", 14, "天风证券", "A股策略周报"),
            ("6531900-国金证券-A股策略周报：最黑暗处最光明-261115", 8, "国金证券", "A股策略周报"),
            ("6511080-国金证券-十一月策略及金股：不完美的底部-261030", 15, "国金证券", "月度策略及金股"),
            ("6540900-国联民生证券-A股策略周报：盈利驱动接力估值修复-261128", 16, "国联民生证券", "A股策略周报"),
            ("6540901-国联民生-行业比较周报：拥挤度回落后的科技与红利再平衡-261128", 12, "国联民生证券", "策略行业比较"),
        ]
        for title, pages, exp_broker, exp_series in positives:
            with self.subTest(title=title):
                res = weekly_broker(title, pages=pages, channel="hc")
                self.assertEqual(res, (exp_broker, exp_series))

    def test_real_negative_traps_rejected(self):
        negatives = [
            # Fixed income / cross-listed bond reports in stype_hc
            ("6531111-广发证券-周策略图谱：赎回潮与技术面共振的债市策略研判-261114", 37, "hc"),
            ("6538926-国信证券-2027年度债券投资策略：转型无熊市-261124", 30, "hc"),
            ("6521009-招商证券-利率策略周报：10年国债下破1.6%要止盈么-261108", 18, "hc"),
            ("6540902-国联民生证券-债券策略周报：继续关注超长债机会-261123", 12, "hc"),
            ("6540903-国联民生证券-资产配置周策略：赎回扰动或有反复，信用债ETF如何把握修复机会-261125", 10, "hc"),
            ("6540904-国联民生证券-进出口观察系列：内需能接续多少？-261125", 4, "hc"),
            # Huatai 22-page Macro '国内周报' disguised under same prefix as 6-page Equity '国内周报'!
            ("6524099-华泰证券-国内周报：“双十一”初现结构性亮点-261108", 22, "hc"),
            ("6538005-华泰证券-宏观国内周报：财政支出回升待传导至投资端-261122", 22, "hc"),
            ("6538006-华泰证券-策略海外周报：短期密集压力或已接近峰值-261122", 15, "hc"),
            # Pruned non-top-11 brokers must be rejected
            ("6538101-国信证券-11月第3周立体投资策略周报：融资压力显化，稳市资金托底-261123", 18, "hc"),
            ("6537001-浙商证券-A股市场运行周报第119期：当前位置不必过度悲观-261120", 13, "hc"),
            ("6538111-东方证券-策略周度思考：全球需求预期下修-261122", 8, "hc"),
            ("6538099-开源证券-投资策略周报：风险逐步释放，等待布局时机-261122", 9, "hc"),
            ("6539103-东吴证券-策略周报：银行走到哪一步了？-261124", 7, "hc"),
            # Overseas / US / HK / BSE / ESG / Non-PDF traps
            ("6538750-东吴证券-策略周评：美股短期超卖，会技术性反弹吗？——美股周观点-261124", 8, "hc"),
            ("6515066-国盛证券-海外市场：关注地缘扰动——2026年11月港股金股推荐-261102", 16, "hc"),
            ("6539222-申万宏源-北交所策略周报：输入性风险冲击市场-261123", 14, "hc"),
            ("6538804-银河证券-ESG策略周度报告：全球电气化投资空间有多大？-261123", 12, "hc"),
            ("6531999-华福证券-【华福策略】市场状态高频数据库——11月第2周-261116.xlsx", 0, "hc"),
            # Wrong channel (qh bond channel)
            ("6539200-申万宏源-策略一周回顾展望：各种风险正被充分定价-261121", 9, "qh"),
        ]
        for title, pages, ch in negatives:
            with self.subTest(title=title):
                self.assertIsNone(classify_equity_title(title, pages=pages, channel=ch))

    def test_non_pdf_suffix_detector(self):
        self.assertEqual(non_pdf_suffix("国泰海通-策略底稿-261124.xlsx"), "xlsx")
        self.assertEqual(non_pdf_suffix("数据表.XLSM"), "xlsm")
        self.assertIsNone(non_pdf_suffix("6539200-申万宏源-策略一周回顾展望-261121.pdf"))

    def test_manual_drive_filenames(self):
        m1 = manual_identity("A股策略聚焦 20261124 - 化债落地缓释尾部担忧.pdf")
        self.assertEqual(m1["broker"], "中信证券")
        self.assertEqual(m1["report_date"], "2026-11-24")

        m1_nospace = manual_identity("A股策略聚焦20261122—A股的估值洼地体现在哪？.pdf")
        self.assertEqual(m1_nospace["broker"], "中信证券")
        self.assertEqual(m1_nospace["report_date"], "2026-11-22")

        m2 = manual_identity("国联民生证券-20261128-把握跨年配置窗口.pdf")
        self.assertEqual(m2["broker"], "国联民生证券")
        self.assertEqual(m2["report_date"], "2026-11-28")

        m3 = manual_identity("中金公司-12月金股组合推荐-261128.pdf")
        self.assertEqual(m3["broker"], "中金公司")
        self.assertEqual(m3["series_role"], "golden")

        # Pruned brokers and standard NXNY prefixed PDFs should NOT match manual_identity
        self.assertIsNone(manual_identity("兴业证券-20261124-把握跨年配置窗口.pdf"))
        self.assertIsNone(manual_identity("6539200-申万宏源-策略一周回顾展望-261121.pdf"))

    def test_weekend_monday_alignment(self):
        # Saturday 2026-11-21 & Sunday 2026-11-22 -> Next Monday 2026-11-23
        self.assertEqual(infer_week_mon("2026-11-21"), "2026-11-23")
        self.assertEqual(infer_week_mon("2026-11-22"), "2026-11-23")
        # Monday 2026-11-23 & Wednesday 2026-11-25 -> Same Monday 2026-11-23
        self.assertEqual(infer_week_mon("2026-11-23"), "2026-11-23")
        self.assertEqual(infer_week_mon("2026-11-25"), "2026-11-23")


if __name__ == "__main__":
    unittest.main()
