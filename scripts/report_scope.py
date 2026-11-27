"""One-broker-one-rule intake filter for A-share Equity Strategy reports (NXNY + Drive manual)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import re

# Core buy-side analyst whitelist (default 10 flagship teams)
CORE_BROKERS = (
    "中信证券",
    "申万宏源证券",
    "广发证券",
    "国泰海通证券",
    "中金公司",
    "华泰证券",
    "兴业证券",
    "中信建投证券",
    "招商证券",
    "国信证券",
)

# Manual / hybrid Drive drop-in brokers (exempt from NXNY ID prefix requirement)
MANUAL_BROKERS = ("中信证券", "兴业证券", "中金公司", "长江证券")

# Series priority weight for Experience 7 same-week same-dimension deduplication
ROLE_PRIORITY = {
    "flagship": 4,  # 综合大势主策略周报
    "meso": 3,      # 行业比较 / 风格配置周月报
    "flow": 2,      # 微观资金 / 拥挤度周报
    "golden": 1,    # 月度金股组合报告
}

# Empirically audited on NXNY /stype_hc/ (Nov 2026): (series_name, role, pattern)
_SERIES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "申万宏源证券": (
        ("策略一周回顾展望", "flagship", r"^策略一周回顾展望(?:[：:\-—]|$)"),
        ("行业比较周跟踪", "meso", r"^行业比较周跟踪[：:\-—]"),
    ),
    "广发证券": (
        ("周末五分钟全知道", "flagship", r"^周末五分钟全知道(?:[(（][^）)]*[)）])?[：:\-—]"),
        ("资配月度展望", "meso", r"^资配月度展望[(（]主观篇[)）][：:\-—]"),
    ),
    "国泰海通证券": (
        ("中国权益策略周报", "flagship", r"^(?:中国权益|A股)策略周报[：:\-—]"),
        ("中观景气跟踪", "meso", r"^中观景气跟踪.*?(?:第\d+[期周])?[：:\-—]"),
        ("投资者微观行为洞察", "flow", r"^投资者微观行为洞察手册.*?[：:\-—]"),
    ),
    "华泰证券": (
        ("策略国内周报", "flagship", r"^策略国内周报(?![-—]资金透视)[：:\-—]|^策略[：:]|^国内周报[：:]"),
        ("策略资金透视", "flow", r"^策略国内周报[-—]资金透视[：:\-—]"),
        ("中观景气与战术配置月报", "meso", r"^策略月报[：:].*中观景气"),
    ),
    "招商证券": (
        ("A股投资策略周报", "flagship", r"^A股投资策略周报(?:[(（]\d+[)）])?[：:\-—]"),
        ("A股趋势与风格定量观察", "meso", r"^A股趋势与风格定量观察[：:\-—]"),
        ("行业景气观察", "meso", r"^行业景气观察(?:[(（]\d+[)）])?[：:\-—]"),
        ("金融市场流动性周报", "flow", r"^金融市场流动性与监管动态周报[：:\-—]"),
    ),
    "中信建投证券": (
        ("策略周思考", "flagship", r"^(?:策略周思考|一周策略回顾与展望|策略周报\d*年?\d*月?第?\d*期?)(?:[：:\-—]|$)"),
        ("策略市场周鉴", "meso", r"^(?:策略市场周鉴|行业比较动态追踪.*?)[：:\-—]"),
        ("流动性周观察", "flow", r"^流动性周观察.*?[：:\-—]"),
    ),
    "中金公司": (
        ("A股策略周报", "flagship", r"^(?:A股策略|中国策略简评)[：:\-—]"),
        ("行业配置月报", "meso", r"^\d{1,2}月行业配置[：:\-—]"),
    ),
    "国信证券": (
        ("立体投资策略周报", "flagship", r"^(?:.*?[—\-]+)?\d*月?第?\d*周?立体投资策略周报(?:[：:\-—]|$)"),
        ("月度金股汇总", "golden", r"^策略快评[：:].*金股"),
    ),
    "浙商证券": (
        ("A股市场运行周报", "flagship", r"^A股市场运行周报第?\d*期?[：:\-—]"),
        ("板块轮动月报", "meso", r"^板块轮动月报.*?[：:\-—]"),
    ),
    "东方证券": (
        ("策略周度思考", "flagship", r"^策略周度思考[：:\-—]"),
        ("A股风格及行业配置周报", "meso", r"^(?:A股风格及行业配置周报|主题策略周报)[：:\-—]"),
    ),
    "华创证券": (
        ("策略周聚焦", "flagship", r"^【(?:策略周报|华创策略)】(?:策略周聚焦)?[：:\-—]?"),
        ("流动性与拥挤度温度计", "flow", r"^流动性&交易拥挤度&投资者温度计周报[：:\-—]"),
    ),
    "东吴证券": (
        ("策略周评", "flagship", r"^(?:策略周评|策略周报)[：:](?!.*(?:美股|港股|恒科|恒指))"),
        ("主题与产业趋势周展望", "meso", r"^每周主题、产业趋势交易复盘和展望[：:\-—]"),
        ("月度金股", "golden", r"^策略深度报告[：:].*金股"),
    ),
    "开源证券": (
        ("投资策略周报", "flagship", r"^投资策略周报[：:\-—]"),
        ("月度金股", "golden", r"^策略投资专题[：:]开源金股"),
    ),
    "天风证券": (
        ("A股策略周报", "flagship", r"^A股策略周报[：:\-—]"),
        ("政策与大类资产周观察", "meso", r"^政策与大类资产配置周观察[：:\-—]"),
    ),
    "平安证券": (
        ("A股策略周报", "flagship", r"^A股策略周报[：:\-—]"),
        ("A股资金温度计", "flow", r"^A股资金温度计.*?[：:\-—]"),
    ),
    "国金证券": (
        ("A股策略周报", "flagship", r"^A股策略周报[：:\-—]"),
        ("月度策略及金股", "golden", r"^(?:[一二三四五六七八九十\d]+月)策略及金股[：:\-—]"),
    ),
    "光大证券": (
        ("策略周专题", "flagship", r"^策略周专题.*?[：:\-—]"),
    ),
    "国盛证券": (
        ("中观景气周报", "meso", r"^行业配置定期[-—]中观景气周报[：:\-—]"),
    ),
    "财通证券": (
        ("A股流动性周报", "flow", r"^流动性周报[：:].*(?:A股|ETF|两融)"),
    ),
}

BROKERS = tuple(_SERIES)
ALL_BROKERS = tuple(dict.fromkeys((*CORE_BROKERS, *BROKERS, *MANUAL_BROKERS)))

_ALIASES = {
    **dict.fromkeys(("国联民生", "民生证券", "民生", "国联证券"), "国联民生证券"),
    **dict.fromkeys(("国泰海通", "国泰君安", "国泰君安证券", "国君", "海通证券", "海通"), "国泰海通证券"),
    **dict.fromkeys(("申万宏源", "申万宏源研究", "上海申银万国证券研究所", "申万"), "申万宏源证券"),
    **dict.fromkeys(("中信建投", "建投"), "中信建投证券"),
    **dict.fromkeys(("中信", "中信证券", "亮马桥"), "中信证券"),
    **dict.fromkeys(("中金", "中金公司"), "中金公司"),
    **dict.fromkeys(("兴业", "兴证", "兴业证券"), "兴业证券"),
    **dict.fromkeys(("长江", "长江证券"), "长江证券"),
    **{broker.removesuffix("证券"): broker for broker in BROKERS},
    **{broker: broker for broker in ALL_BROKERS},
}

_COMPANY_SUFFIX = re.compile(r"(?:股份有限公司|有限责任公司|有限公司)$")

_EXCLUSIONS = (
    "债券", "债市", "固收", "固定收益", "利率周报", "利率策略", "转债", "可转债", "REIT",
    "信用债", "城投", "二永", "美债", "美元债", "美股", "港股金股", "海外宏观", "海外策略",
    "北交所", "新三板", "新股", "ESG", "纯债", "国债期货", "周策略图谱",
)

_GOLDEN_STOCK_GENERIC = re.compile(
    r"(?:十大金股|\d{1,2}月(?:份|度)?(?:A股(?:市场)?)?金股|[一二三四五六七八九十]+月(?:份|度)?金股)"
)

_NON_PDF_SUFFIX = re.compile(
    r"\.(xlsx|xlsm|xlsb|xls|csv|tsv|zip|rar|7z|docx|docm|doc|pptx|ppt|txt|html|htm|xml|json|ods|odt|wps)(?![a-z0-9])",
    re.IGNORECASE,
)


def non_pdf_suffix(name: str) -> str | None:
    match = _NON_PDF_SUFFIX.search(name)
    return match[1].lower() if match else None


def covered_broker(name: str) -> str | None:
    cleaned = _COMPANY_SUFFIX.sub("", name.strip())
    return _ALIASES.get(cleaned)


def is_core_broker(broker: str) -> bool:
    canonical = covered_broker(broker) or broker
    return canonical in CORE_BROKERS


def infer_week_mon(report_date_str: str) -> str:
    """Experience 7: Saturday (5) & Sunday (6) reports forecast the upcoming Monday week."""
    d = date.fromisoformat(report_date_str)
    if d.weekday() in (5, 6):
        return (d + timedelta(days=7 - d.weekday())).isoformat()
    return (d - timedelta(days=d.weekday())).isoformat()


def series_role_for(broker: str, series_name: str) -> str:
    for s_name, role, _ in _SERIES.get(broker, ()):
        if s_name == series_name:
            return role
    if "金股" in series_name:
        return "golden"
    return "flagship"


def classify_equity_title(title: str, *, pages: int | None = None, channel: str = "hc") -> tuple[str, str, str] | None:
    """Return (broker, series_name, role) for an eligible NXNY equity strategy report, else None."""
    if non_pdf_suffix(title) or channel != "hc":
        return None
    clean = re.sub(r"^\d+-", "", title.strip())
    clean = re.sub(r"\.pdf$", "", clean, flags=re.I)
    publisher, sep, subject = clean.partition("-")
    if not sep:
        return None
    stamp = re.search(r"-(\d{6})$", subject)
    if stamp:
        subject = subject[: stamp.start()]
    subject = subject.strip()
    broker = covered_broker(publisher)
    if not broker:
        return None

    normalized = re.sub(r"\s+", "", subject).upper()
    if any(ex.upper() in normalized for ex in _EXCLUSIONS):
        return None

    # Broker-specific series rules
    for series_name, role, pattern in _SERIES.get(broker, ()):
        if re.search(pattern, subject):
            # Experience 4: Huatai bare '国内周报：' can be 6p Equity Strategy or 22p Macro!
            if broker == "华泰证券" and subject.startswith("国内周报") and pages is not None and pages > 14:
                return None
            return broker, series_name, role

    # Generic monthly golden stock fallback for any covered broker
    if (broker in _SERIES or broker in MANUAL_BROKERS) and _GOLDEN_STOCK_GENERIC.search(subject):
        return broker, "月度金股组合", "golden"

    return None


def weekly_broker(title: str, *, pages: int | None = None, channel: str = "hc") -> tuple[str, str] | None:
    res = classify_equity_title(title, pages=pages, channel=channel)
    return (res[0], res[1]) if res else None


def manual_identity(filename: str) -> dict[str, str] | None:
    """Experience 5: Native filename recognizer for manual Google Drive PDF uploads (e.g. 中信/兴业/中金)."""
    if not filename.lower().endswith(".pdf") or non_pdf_suffix(filename) or any(c in filename for c in "/\\"):
        return None
    # Skip standard NXNY numeric-prefixed files so they follow normal archive path
    if re.match(r"^\d{5,12}-", filename):
        return None
    stem = filename[:-4].strip()

    # Pattern A: 中信原生格式 e.g. "A股策略聚焦 20261124 - 化债落地..." or "每周市场策略聚焦 20261124：..."
    citic_native = re.fullmatch(
        r"(?:亮马桥策略聚焦|A股策略聚焦|每周市场策略聚焦)\s*(\d{8})\s*[-‐‑‒–—―－:：]+\s*(.+)",
        stem,
    )
    if citic_native and citic_native[2].strip():
        day = datetime.strptime(citic_native[1], "%Y%m%d").date()
        return {
            "broker": "中信证券",
            "series": "A股策略聚焦",
            "series_role": "flagship",
            "title": citic_native[2].strip(),
            "report_date": day.isoformat(),
        }

    # Pattern B: "<券商名>-<日期>-<标题>.pdf" or "<券商名>-<标题>-<日期>.pdf"
    publisher, sep, rest = stem.partition("-")
    if not sep:
        return None
    broker = covered_broker(publisher)
    if not broker:
        return None

    for pattern in (
        r"(?P<day>\d{8}|\d{6})\s*[-_：:]\s*(?P<title>.+)",
        r"(?P<title>.+?)\s*[-_]\s*(?P<day>\d{8}|\d{6})",
    ):
        match = re.fullmatch(pattern, rest.strip())
        if match:
            raw_day = match["day"]
            day = datetime.strptime(raw_day, "%Y%m%d" if len(raw_day) == 8 else "%y%m%d").date()
            subj = match["title"].strip()
            role = "golden" if "金股" in subj else "flagship"
            series = "月度金股组合" if role == "golden" else "策略周报(手传)"
            return {
                "broker": broker,
                "series": series,
                "series_role": role,
                "title": subj,
                "report_date": day.isoformat(),
            }
    return None


def published_issues(records: list[dict]) -> set[tuple[str | None, str, str]]:
    return {
        (covered_broker(r.get("broker", "")), r["series"], r["report_date"])
        for r in records
        if r.get("series") and r.get("report_date") and not r.get("is_demo")
    }


def weekly_issue(title: str, *, pages: int | None = None, channel: str = "hc") -> tuple[str, str, str] | None:
    classification = weekly_broker(title, pages=pages, channel=channel)
    stamp = re.search(r"-(\d{6})(?:\.pdf)?$", title, re.I)
    if classification and stamp:
        try:
            day = datetime.strptime(stamp[1], "%y%m%d").date().isoformat()
            return (*classification, day)
        except ValueError:
            return None
    return None
