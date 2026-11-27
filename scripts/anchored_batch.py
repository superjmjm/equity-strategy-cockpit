"""Batch reader for inbox/archived PDFs with cross-week previous_issue_context injection."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.reader import open_cache, read_report
from scripts.report_io import INBOX, download_cached, drive_service, env, list_pdfs
from scripts.report_scope import classify_equity_title, infer_week_mon, is_core_broker, manual_identity
from scripts.store import load_all_reports, previous_issue_for, save_report


def establish_identity(filename: str, listing_meta: dict | None = None) -> dict:
    manual = manual_identity(filename)
    if manual:
        return {
            **manual,
            "week_mon": infer_week_mon(manual["report_date"]),
            "is_core": is_core_broker(manual["broker"]),
        }
    listing_meta = listing_meta or {}
    title = listing_meta.get("title", filename)
    classified = classify_equity_title(
        title, pages=listing_meta.get("pages"), channel=listing_meta.get("channel", "hc")
    )
    match = re.fullmatch(r"(?:\d+-)?[^-]+-(.+)-(\d{6})(?:\.pdf)?", title, re.I)
    if not classified or not match:
        raise ValueError(f"Cannot establish eligible equity strategy series from: {filename}")
    broker, series, role = classified
    day = datetime.strptime(match[2], "%y%m%d").date().isoformat()
    return {
        "broker": broker,
        "series": series,
        "series_role": role,
        "title": match[1].strip(),
        "report_date": day,
        "week_mon": infer_week_mon(day),
        "is_core": is_core_broker(broker),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-id", action="append", default=[])
    parser.add_argument("--no-vision", action="store_true", help="Disable selective chart-page vision pass")
    args = parser.parse_args()

    all_reports = load_all_reports()
    known_hashes = {r["report_id"] for r in all_reports}
    manifest_path = INBOX / "listing.json"
    listing = json.loads(manifest_path.read_bytes()) if not args.archive_id and manifest_path.exists() else {}

    inputs: list[tuple[str, bytes, str | None]] = []
    if args.archive_id:
        drive = drive_service()
        rows = list_pdfs(drive, env("GDRIVE_FOLDER_ID"))
        for rid in args.archive_id:
            matched = [
                r for r in rows
                if r.get("appProperties", {}).get("nxny_id") == rid or r["name"].startswith(rid + "-")
            ]
            if len(matched) != 1:
                raise ValueError(f"Unique archive entry not found for ID {rid}")
            row = matched[0]
            inputs.append((row["name"], download_cached(drive, row), row["id"]))
    else:
        for path in sorted(INBOX.glob("*.pdf")):
            meta_row = listing.get(path.name, {})
            inputs.append((path.name, path.read_bytes(), meta_row.get("drive_file_id")))

    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        cache = open_cache(Path(tmp) / "calls.sqlite")
        try:
            for filename, raw, drive_file_id in inputs:
                rid = hashlib.sha256(raw).hexdigest()
                if rid in known_hashes:
                    continue
                try:
                    meta = establish_identity(filename, listing.get(filename))
                    prev_ctx = previous_issue_for(meta["broker"], meta["report_date"], all_reports)
                    result = read_report(
                        raw,
                        meta,
                        cache,
                        previous_issue_context=prev_ctx,
                        enable_vision=not args.no_vision,
                    )
                    report_doc = result["output"]
                    report_doc["source_file"] = filename
                    if drive_file_id:
                        report_doc["drive_file_id"] = drive_file_id
                    if filename in listing and listing[filename].get("pages"):
                        report_doc["listing_pages"] = listing[filename]["pages"]
                    assert report_doc["report_id"] == rid

                    shard_file = save_report(report_doc)
                    all_reports.append(report_doc)
                    known_hashes.add(rid)
                    stance_tier = (report_doc.get("market_stance_slot") or {}).get("stance_tier", "null")
                    ow_count = len(report_doc.get("sector_allocation_slot", {}).get("overweight_lines", []))
                    print(
                        f"EQUITY_EXTRACTED file={filename} shard={shard_file.relative_to(ROOT)} "
                        f"stance={stance_tier} overweights={ow_count} "
                        f"vision_pages={result['receipts'][0].get('vision_pages', [])} "
                        f"model={result['receipts'][1]['model']}"
                    )
                except Exception as exc:
                    print("::error::", filename, type(exc).__name__, str(exc)[:240])
                    failed += 1
        finally:
            cache.close()
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
