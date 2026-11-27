"""Two-pass anchored model reader + selective chart vision + deterministic Python guardrails."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import unicodedata

from jsonschema import validate

from .contract import STAGE1, STAGE2, STAGE3
from .prompts import S1, S2, S3
from .source import context, index_pdf, select_chart_pages_base64

DEFAULT_MODEL = "gpt-6.2-sol"
S1_EFFORT = "medium"
S2_EFFORT = "high"
S3_EFFORT = "high"

INDEX_BOUNDS = {
    "上证指数": (2000.0, 6500.0),
    "沪深300": (2000.0, 7500.0),
    "万得全A": (2500.0, 9500.0),
    "创业板指": (1000.0, 5000.0),
    "中证A500": (2000.0, 7500.0),
}

NUMBER_RE = re.compile(r"(?<![\d.])(\d{3,5}(?:\.\d+)?)(?![\d.])")

COVER_LINE = re.compile(
    r"(?:(?:证券研究报告|(?:A股|权益|投资|市场)?策略(?:周报|专题|报告|定期报告)?|(?:报告日期|发布日期)\s*[:：]?|[/／])\s*)*"
    r"(?:\d{4}[.年/-]\d{1,2}[.月/-]\d{1,2}日?)?"
    r"|(?:证券分析师|分析师|研究助理|联系人)\s*[:：]?\s*[\u4e00-\u9fff·、\s]{2,16}"
    r"|(?:SAC\s*)?(?:证书编号|执业编号|执业证书编号)\s*[:：]?\s*S\d{10,15}"
    r"|(?:邮箱\s*[:：]\s*)?[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"
    r"|(?:电话|联系电话)\s*[:：]\s*[\d+() -]{7,22}"
    r"|免责声明[。:]?|请务必阅读正文之后的免责条款部分。?"
)


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


def cover_only(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return bool(lines) and all(COVER_LINE.fullmatch(line) for line in lines)


def ask_openai(model: str, effort: str, stage: str, prompt: str, payload: dict, schema: dict, images: list[dict] | None = None):
    """Invoke OpenAI reasoning model without temperature parameter; supports optional chart images."""
    from openai import OpenAI

    user_content: str | list[dict]
    if images:
        user_content = [{"type": "text", "text": encode(payload)}]
        for img in images:
            user_content.append({"type": "text", "text": f"[附：原报告第 {img['page']} 页图表快照]"})
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": img["data_url"], "detail": "high"},
                }
            )
    else:
        user_content = encode(payload)

    with OpenAI(timeout=300, max_retries=1) as client:
        response = client.chat.completions.create(
            model=model,
            reasoning_effort=effort,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": stage, "strict": True, "schema": schema},
            },
        )
    result = response.choices[0]
    if result.finish_reason != "stop" or result.message.refusal:
        raise ValueError(f"{stage} incomplete: {result.finish_reason}")
    return json.loads(result.message.content), {
        "request_id": response.id,
        "model": response.model,
        "requested_model": model,
        "reasoning_effort": effort,
        "vision_pages": [img["page"] for img in (images or [])],
        "usage": response.usage.model_dump() if response.usage else None,
    }


def open_cache(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=600)
    db.execute(
        "CREATE TABLE IF NOT EXISTS calls(key TEXT PRIMARY KEY, response TEXT NOT NULL, receipt TEXT NOT NULL)"
    )
    return db


def cached_call(db, model, effort, stage, prompt, payload, schema, offline=False, invoke=ask_openai, images=None):
    img_pages = [img["page"] for img in (images or [])]
    key = digest([model, effort, stage, prompt, payload, schema, img_pages])
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("SELECT response, receipt FROM calls WHERE key=?", (key,)).fetchone()
        if row:
            data, receipt = map(json.loads, row)
        else:
            if offline:
                raise ValueError("Missing frozen response for " + stage)
            data, receipt = invoke(model, effort, stage, prompt, payload, schema, images=images)
            validate(data, schema)
            db.execute("INSERT INTO calls VALUES(?,?,?)", (key, encode(data), encode(receipt)))
        validate(data, schema)
        db.commit()
        return data, dict(receipt, input_hash=key)
    except BaseException:
        db.rollback()
        raise


def _clean_pids(raw_pids: list[str], by_pid: dict[str, dict]) -> list[str]:
    valid = [pid for pid in dict.fromkeys(raw_pids) if pid in by_pid]
    if len(valid) >= 2:
        non_cover = [pid for pid in valid if not cover_only(by_pid[pid]["text"])]
        return non_cover or valid
    return valid


def _hydrate_evidence(pids: list[str], by_pid: dict[str, dict]) -> list[dict]:
    result = []
    for pid in pids:
        p = by_pid[pid]
        txt = p["text"].strip()
        result.append(
            {
                "pid": pid,
                "page": p["page"],
                "heading": p.get("heading", ""),
                "text": txt[:260],
                "truncated": len(txt) > 260,
            }
        )
    return result


def _validate_index_target(target: dict | None, paragraphs: list[dict]) -> tuple[dict | None, str | None]:
    if target is None:
        return None, None
    idx_name = target.get("index_name")
    low, high = target.get("point_floor"), target.get("point_ceiling")
    if low is None and high is None:
        return None, None
    bounds = INDEX_BOUNDS.get(idx_name)
    if not bounds:
        return None, "unknown_index"
    lo_b, hi_b = bounds

    found_numbers: set[Decimal] = set()
    for p in paragraphs:
        norm = unicodedata.normalize("NFKC", p["text"]).replace(",", "")
        for m in NUMBER_RE.findall(norm):
            try:
                found_numbers.add(Decimal(m))
            except InvalidOperation:
                pass

    def check_val(v):
        if v is None:
            return None, True
        if not (lo_b <= float(v) <= hi_b):
            return None, False
        try:
            dec = Decimal(str(v))
        except InvalidOperation:
            return None, False
        # Accept exact match or integer match if float formatted as 3200.0 vs 3200
        if dec in found_numbers or Decimal(str(int(v))) in found_numbers:
            return float(v), True
        return None, False

    v_low, ok_low = check_val(low)
    v_high, ok_high = check_val(high)
    if not ok_low or not ok_high or (v_low is None and v_high is None):
        return None, f"unverified_index_target:{idx_name}:{low}-{high}"
    if v_low is not None and v_high is not None and v_high < v_low:
        v_low, v_high = v_high, v_low
    return {"index_name": idx_name, "point_floor": v_low, "point_ceiling": v_high}, None


def finish_equity_report(meta: dict, index: dict, review: dict) -> dict:
    """Apply deterministic existence & physical-bounds guardrails without dropping valid text cards."""
    by_pid = {p["pid"]: p for p in index["paragraphs"]}
    warnings: list[str] = []
    intercepted: list[str] = []

    # 1) Market stance slot
    stance_out = None
    raw_stance = review.get("market_stance_slot")
    if raw_stance is not None:
        pids = _clean_pids(raw_stance["evidence_pids"], by_pid)
        if pids:
            stance_out = json.loads(encode(raw_stance))
            checked_target, warn = _validate_index_target(
                stance_out.get("index_target"), context(index, pids)
            )
            if warn:
                warnings.append(warn)
            stance_out["index_target"] = checked_target
            stance_out["evidence_pids"] = pids
            stance_out["evidence"] = _hydrate_evidence(pids, by_pid)
        else:
            intercepted.append("market_stance_slot:no_valid_pids")

    # 2) DDM driver slots
    ddm_out = {}
    for slot_key in ("earnings_macro_slot", "liquidity_chip_slot", "policy_risk_slot"):
        raw_ddm = review["ddm_driver_slots"].get(slot_key)
        if raw_ddm is None:
            ddm_out[slot_key] = None
            continue
        pids = _clean_pids(raw_ddm["evidence_pids"], by_pid)
        if pids:
            item = json.loads(encode(raw_ddm))
            item["evidence_pids"] = pids
            item["evidence"] = _hydrate_evidence(pids, by_pid)
            ddm_out[slot_key] = item
        else:
            ddm_out[slot_key] = None
            intercepted.append(f"{slot_key}:no_valid_pids")

    # 3) Style slots
    style_out = {}
    for s_key in ("size_style_slot", "valuation_style_slot"):
        raw_style = review["style_slots"].get(s_key)
        if raw_style is None:
            style_out[s_key] = None
            continue
        pids = _clean_pids(raw_style["evidence_pids"], by_pid)
        if pids:
            item = json.loads(encode(raw_style))
            item["evidence_pids"] = pids
            item["evidence"] = _hydrate_evidence(pids, by_pid)
            style_out[s_key] = item
        else:
            style_out[s_key] = None
            intercepted.append(f"{s_key}:no_valid_pids")

    # 4) Sector allocation lines (dedup + slice bounds)
    def clean_sector_list(items: list[dict], limit: int) -> list[dict]:
        cleaned = []
        seen_keys = set()
        for raw_sec in items:
            pids = _clean_pids(raw_sec["evidence_pids"], by_pid)
            sw_list = list(dict.fromkeys(raw_sec.get("sw_level1_list") or []))[:3]
            if not pids or not sw_list:
                continue
            dedup_key = (tuple(sw_list), raw_sec["canonical_narrative"], raw_sec["raw_theme_phrase"].strip())
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            sec = json.loads(encode(raw_sec))
            sec["sw_level1_list"] = sw_list
            sec["evidence_pids"] = pids
            sec["evidence"] = _hydrate_evidence(pids, by_pid)
            cleaned.append(sec)
            if len(cleaned) >= limit:
                break
        return cleaned

    sector_out = {
        "overweight_lines": clean_sector_list(review["sector_allocation_slot"]["overweight_lines"], 6),
        "cautious_lines": clean_sector_list(review["sector_allocation_slot"]["cautious_lines"], 4),
    }

    # 5) Data nuggets (max 3)
    nuggets_out = []
    for raw_nug in review.get("data_nuggets_slot", []):
        pids = _clean_pids(raw_nug["evidence_pids"], by_pid)
        if not pids:
            continue
        nug = json.loads(encode(raw_nug))
        nug["evidence_pids"] = pids
        nug["evidence"] = _hydrate_evidence(pids, by_pid)
        nug["primary_page"] = nug["evidence"][0]["page"]
        nuggets_out.append(nug)
        if len(nuggets_out) >= 3:
            break

    # 6) Catalysts (max 4)
    catalysts_out = []
    for raw_cat in review.get("catalysts_slot", []):
        pids = _clean_pids(raw_cat["evidence_pids"], by_pid)
        if not pids:
            continue
        cat = json.loads(encode(raw_cat))
        cat["evidence_pids"] = pids
        cat["evidence"] = _hydrate_evidence(pids, by_pid)
        catalysts_out.append(cat)
        if len(catalysts_out) >= 4:
            break

    # 7) Golden stocks (max 15, clean stock code format)
    stocks_out = []
    seen_stocks = set()
    for raw_stk in review.get("golden_stocks_slot", []):
        pids = _clean_pids(raw_stk["evidence_pids"], by_pid)
        name = raw_stk["stock_name"].strip()
        if not pids or not name or name in seen_stocks:
            continue
        seen_stocks.add(name)
        stk = json.loads(encode(raw_stk))
        code = (stk.get("stock_code") or "").strip().upper()
        if code and not re.fullmatch(r"\d{6}(?:\.(?:SH|SZ|BJ))?|\d{4,5}\.HK", code):
            code = None
        stk["stock_code"] = code or None
        stk["evidence_pids"] = pids
        stk["evidence"] = _hydrate_evidence(pids, by_pid)
        stocks_out.append(stk)
        if len(stocks_out) >= 15:
            break

    # 8) Risk invalidator
    risk_out = None
    raw_risk = review.get("risk_invalidator_slot")
    if raw_risk is not None:
        pids = _clean_pids(raw_risk["evidence_pids"], by_pid)
        if pids:
            risk_out = {
                "risk_summary": raw_risk["risk_summary"],
                "evidence_pids": pids,
                "evidence": _hydrate_evidence(pids, by_pid),
            }

    return {
        **meta,
        "report_id": index["report_id"],
        "total_pages": index.get("total_pages", 0),
        "report_meta": review["report_meta"],
        "market_stance_slot": stance_out,
        "ddm_driver_slots": ddm_out,
        "style_slots": style_out,
        "sector_allocation_slot": sector_out,
        "data_nuggets_slot": nuggets_out,
        "catalysts_slot": catalysts_out,
        "golden_stocks_slot": stocks_out,
        "risk_invalidator_slot": risk_out,
        "numeric_warnings": warnings,
        "intercepted_slots": intercepted,
    }


def read_report(
    pdf_bytes: bytes,
    meta: dict,
    db: sqlite3.Connection,
    *,
    previous_issue_context: dict | None = None,
    model: str | None = None,
    enable_vision: bool = True,
    offline: bool = False,
    invoke=ask_openai,
) -> dict:
    active_model = model or os.environ.get("OPENAI_MODEL", "").strip() or DEFAULT_MODEL
    idx = index_pdf(pdf_bytes)
    if not idx["paragraphs"]:
        raise ValueError("Stage0: no extractable text in PDF")

    chart_images = select_chart_pages_base64(pdf_bytes, idx, max_pages=6) if enable_vision else []

    # Shared prefix `paragraphs` placed first in payload keys via sort_keys for OpenAI Prompt Caching
    base_packet = {"paragraphs": idx["paragraphs"], "report": meta}
    first, r1 = cached_call(
        db, active_model, S1_EFFORT, "equity_stage1", S1, base_packet, STAGE1,
        offline=offline, invoke=invoke, images=chart_images,
    )

    s2_packet = {
        "paragraphs": idx["paragraphs"],
        "report": meta,
        "stage1_candidates": first["candidates"],
        "stage1_chart_observations": first.get("chart_observations", []),
        "previous_issue_context": previous_issue_context,
    }
    review, r2 = cached_call(
        db, active_model, S2_EFFORT, "equity_stage2", S2, s2_packet, STAGE2,
        offline=offline, invoke=invoke, images=None,
    )

    public_doc = finish_equity_report(meta, idx, review)
    return {
        "output": public_doc,
        "s0": idx,
        "s1": first,
        "s2": review,
        "receipts": [r1, r2],
    }


def synthesize_weekly(
    weekly_payload: dict,
    *,
    model: str | None = None,
    invoke=ask_openai,
) -> tuple[dict, dict]:
    """Run Stage 3 Buy-Side Chief Strategist cross-broker synthesis."""
    active_model = model or os.environ.get("OPENAI_MODEL", "").strip() or DEFAULT_MODEL
    data, receipt = invoke(active_model, S3_EFFORT, "equity_stage3_weekly", S3, weekly_payload, STAGE3, images=None)
    validate(data, STAGE3)
    return data, receipt
