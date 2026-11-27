"""Strict OpenAI Structured Output contracts (strict=True) for Equity Strategy Stage 1, 2 & 3."""
from __future__ import annotations


def obj(**fields):
    return {
        "type": "object",
        "properties": fields,
        "required": list(fields),
        "additionalProperties": False,
    }


def array(item, description: str | None = None):
    res = {"type": "array", "items": item}
    if description:
        res["description"] = description
    return res


def enum(*values, description: str | None = None):
    res = {"type": "string", "enum": list(values)}
    if description:
        res["description"] = description
    return res


def nullable(schema):
    return {"anyOf": [{"type": "null"}, schema]}


TEXT = {"type": "string"}
NULL_TEXT = {"type": ["string", "null"]}
NULL_NUMBER = {"type": ["number", "null"]}
BOOL = {"type": "boolean"}
PIDS = array(TEXT)

SW_LEVEL1_SECTORS = (
    "农林牧渔", "基础化工", "钢铁", "有色金属", "电子", "家用电器", "食品饮料",
    "纺织服饰", "轻工制造", "医药生物", "公用事业", "交通运输", "房地产", "商贸零售",
    "社会服务", "综合", "建筑材料", "建筑装饰", "电力设备", "国防军工", "计算机",
    "传媒", "通信", "银行", "非银金融", "汽车", "机械设备", "煤炭", "石油石化",
    "环保", "美容护理",
)

DDM_TOPICS = (
    "credit_m1_pulse",
    "ppi_earnings_roe",
    "supply_capex_clearing",
    "domestic_demand_property",
    "etf_institutional_inflow",
    "retail_leverage_sentiment",
    "crowding_year_end_rebalance",
    "fed_fx_foreign_flow",
    "fiscal_debt_resolution",
    "consumption_new_productivity_policy",
    "capital_market_soe_reform",
    "tariff_geopolitics_risk",
    "other_specific_driver",
)

CANONICAL_NARRATIVES = (
    "ai_compute_semicon_autonomy",
    "ai_application_smart_hardware",
    "solid_battery_new_energy_turnaround",
    "supply_clearing_anti_involution",
    "trade_in_service_consumption",
    "high_dividend_soe_valuation",
    "debt_relief_fiscal_beneficiary",
    "ma_restructuring_tech_reform",
    "non_us_grid_machinery_export",
    "north_america_export_chain",
    "robotics_low_altitude_new_tech",
    "healthcare_innovative_drug",
    "cyclical_resources_gold",
    "pure_sector_fundamental",
    "other_emergent_theme",
)

# ==================== STAGE 1: High-Recall Candidate Sweep ====================
STAGE1_CANDIDATE = obj(
    dimension=enum("macro_stance", "ddm_driver", "style", "sector_theme", "data_nugget", "catalyst", "golden_stock", "risk"),
    core_judgment=TEXT,
    target_entities=TEXT,
    numbers_noted=array(obj(raw_number=TEXT, meaning=TEXT)),
    is_forward_looking=BOOL,
    pids=PIDS,
)

STAGE1 = obj(
    candidates=array(STAGE1_CANDIDATE),
    chart_observations=array(obj(page={"type": "integer"}, chart_finding=TEXT)),
)

# ==================== STAGE 2: Named Nullable Slots (Strict Audit) ====================
INDEX_TARGET = obj(
    index_name=enum("上证指数", "沪深300", "万得全A", "创业板指", "中证A500"),
    point_floor=NULL_NUMBER,
    point_ceiling=NULL_NUMBER,
)

MARKET_STANCE = obj(
    stance_tier=enum(
        "aggressive_bull",
        "structural_bull",
        "neutral_range",
        "defensive_cautious",
    ),
    position_guidance=enum(
        "high_overweight",
        "medium_standard",
        "low_defensive",
        "barbell_balanced",
        "unspecified",
    ),
    self_declared_shift=enum(
        "turn_more_positive",
        "turn_more_cautious",
        "pivot_style_or_structure",
        "maintain_stance",
        "unspecified",
    ),
    marginal_shift_note=NULL_TEXT,
    index_target=nullable(INDEX_TARGET),
    vote_eligible=BOOL,
    thesis_summary=TEXT,
    evidence_pids=PIDS,
)

DDM_SLOT = obj(
    direction=enum("bullish_support", "bearish_drag", "neutral_watch"),
    canonical_topic=enum(*DDM_TOPICS),
    claim_summary=TEXT,
    vote_eligible=BOOL,
    evidence_pids=PIDS,
)

SIZE_STYLE = obj(
    preference=enum("large_cap", "mid_cap", "small_micro_cap", "balanced"),
    vote_eligible=BOOL,
    rationale=TEXT,
    evidence_pids=PIDS,
)

VALUATION_STYLE = obj(
    preference=enum(
        "growth_tech",
        "value_dividend",
        "cyclical_turnaround",
        "quality_core_assets",
        "barbell_tech_dividend",
    ),
    vote_eligible=BOOL,
    rationale=TEXT,
    evidence_pids=PIDS,
)

SECTOR_LINE_ITEM = obj(
    sw_level1_list=array({"$ref": "#/$defs/sw_level1_enum"}),
    canonical_narrative=enum(*CANONICAL_NARRATIVES),
    raw_theme_phrase=TEXT,
    catalyst_logic=TEXT,
    vote_eligible=BOOL,
    evidence_pids=PIDS,
)

DATA_NUGGET = obj(
    category=enum("flow_crowding", "meso_fundamental", "valuation_calendar"),
    metric_phrase=TEXT,
    forward_implication=TEXT,
    chart_likely_on_page=BOOL,
    evidence_pids=PIDS,
)

CATALYST_ITEM = obj(
    time_window=TEXT,
    event_title=TEXT,
    scenario_impact=TEXT,
    evidence_pids=PIDS,
)

GOLDEN_STOCK_ITEM = obj(
    stock_name=TEXT,
    stock_code=NULL_TEXT,
    sw_level1={"$ref": "#/$defs/sw_level1_enum"},
    portfolio_role=enum(
        "core_bellwether",
        "turnaround_alpha",
        "growth_elasticity",
        "dividend_defensive",
        "policy_theme",
    ),
    recommend_logic=TEXT,
    evidence_pids=PIDS,
)

RISK_SLOT = obj(
    risk_summary=TEXT,
    evidence_pids=PIDS,
)

STAGE2 = obj(
    report_meta=obj(
        archetype=enum(
            "regular_periodic",
            "thematic_comparative",
            "liquidity_crowding",
            "golden_stocks_monthly",
            "policy_event_flash",
        ),
        one_line_takeaway=TEXT,
    ),
    market_stance_slot=nullable(MARKET_STANCE),
    ddm_driver_slots=obj(
        earnings_macro_slot={"$ref": "#/$defs/nullable_ddm_slot"},
        liquidity_chip_slot={"$ref": "#/$defs/nullable_ddm_slot"},
        policy_risk_slot={"$ref": "#/$defs/nullable_ddm_slot"},
    ),
    style_slots=obj(
        size_style_slot=nullable(SIZE_STYLE),
        valuation_style_slot=nullable(VALUATION_STYLE),
    ),
    sector_allocation_slot=obj(
        overweight_lines=array({"$ref": "#/$defs/sector_line_item"}),
        cautious_lines=array({"$ref": "#/$defs/sector_line_item"}),
    ),
    data_nuggets_slot=array(DATA_NUGGET),
    catalysts_slot=array(CATALYST_ITEM),
    golden_stocks_slot=array(GOLDEN_STOCK_ITEM),
    risk_invalidator_slot=nullable(RISK_SLOT),
)

STAGE2["$defs"] = {
    "nullable_ddm_slot": nullable(DDM_SLOT),
    "sector_line_item": SECTOR_LINE_ITEM,
    "sw_level1_enum": enum(*SW_LEVEL1_SECTORS),
}

# ==================== STAGE 3: Weekly Cross-Broker Buy-Side Synthesis ====================
STAGE3 = obj(
    executive_clash_summary=TEXT,
    core_vs_all_divergence_note=TEXT,
    verified_shifts=array(
        obj(
            broker=TEXT,
            is_genuine_shift=BOOL,
            buy_side_interpretation=TEXT,
        )
    ),
    emergent_narratives=array(
        obj(
            cluster_title=TEXT,
            sw_sectors=array(enum(*SW_LEVEL1_SECTORS)),
            supporting_brokers=array(TEXT),
            alpha_rationale=TEXT,
        )
    ),
)
