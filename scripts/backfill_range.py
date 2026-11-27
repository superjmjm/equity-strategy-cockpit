"""Date-range inventory (dry_run) and gentle quota-safe backfill for Equity Strategy reports."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import report_io as io
from scripts.report_scope import BROKERS, covered_broker, published_issues, weekly_broker, weekly_issue
from scripts.store import load_all_reports

STATE = Path(os.environ.get("RUNNER_TEMP", ".")) / "equity-range-inventory.json"


def parameters():
    dates = []
    for key in ("START_DATE", "END_DATE"):
        value = os.environ[key].strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError(f"Invalid {key}: expected YYYY-MM-DD")
        dates.append(date.fromisoformat(value))
    if dates[0] > dates[1]:
        raise ValueError("start_date must precede or equal end_date")
    raw = os.environ.get("BROKERS", "").strip()
    brokers = list(dict.fromkeys(covered_broker(s) for s in raw.split(",") if s.strip())) if raw else list(BROKERS)
    if any(b not in BROKERS for b in brokers):
        raise ValueError(f"Unknown or manual-only broker in automatic backfill: {brokers}")
    limit = int(os.environ.get("MAX_DOWNLOADS", "5"))
    if not 1 <= limit <= 15:
        raise ValueError("max_downloads must be in 1..15 (3-5 recommended for gentle backfill)")
    return *dates, brokers, limit


def source_id(filename: str) -> str | None:
    match = re.match(r"^(\d+)-", filename)
    return match[1] if match else None


def scan_hc_range(start: date, end: date, brokers: list[str], ignored: dict, rows: dict, hits: dict, skipped: dict) -> int:
    page = 1
    fingerprints = set()
    channel = "hc"
    with io.make_http_session() as session:
        while True:
            suffix = "" if page == 1 else f"_p{page}"
            url = f"{io.LIST_BASE}/stype_{channel}{suffix}/"
            response = session.get(url, timeout=45)
            response.raise_for_status()
            body = response.content.decode("utf8")
            uploads = []
            identifiers = []

            def observe(rid, title, day, upload, extension):
                uploads.append(upload)
                identifiers.append(rid)
                extension = extension or ignored.get(rid)
                if not extension:
                    return
                clean = re.sub(r"\." + re.escape(extension) + r"(?![a-z0-9])", "", title, flags=re.I)
                stamp = re.search(r"-(\d{6})$", clean)
                if not day and stamp:
                    try:
                        day = datetime.strptime(stamp[1], "%y%m%d").date()
                    except ValueError:
                        day = None
                broker = weekly_broker(clean, channel=channel)
                if broker and broker[0] in brokers and day and start <= day <= end:
                    skipped[broker[0]].add(rid)
                    ignored[rid] = extension
                    hits[broker[0]].add(rid)

            items = io.parse_listing(body, observe=observe)
            fingerprint = frozenset(identifiers)
            if fingerprint in fingerprints:
                raise ValueError(f"Repeated {channel} listing page {page}")
            fingerprints.add(fingerprint)

            for rid, (title, day, _, pages) in items.items():
                broker = weekly_broker(title, pages=pages, channel=channel)
                if day and start <= day <= end and broker and broker[0] in brokers and rid not in ignored:
                    hits[broker[0]].add(rid)
                    rows.setdefault(rid, (broker[0], title, pages, channel))

            if uploads and all(d and d < start for d in uploads):
                return page
            links = {
                int(n)
                for n in re.findall(
                    rf"""href\s*=\s*["'](?:https://www\.nxny\.com)?/stype_{channel}_p(\d+)/["']""",
                    body,
                )
            }
            if not any(n > page for n in links):
                return page
            if page + 1 not in links:
                raise ValueError(f"Missing {channel} listing page after {page}")
            page += 1
            time.sleep(io.PAGE_SLEEP_SECONDS)


def run() -> int:
    start, end, brokers, limit = parameters()
    dry = os.environ.get("DRY_RUN", "false").lower() == "true"
    initial = load_all_reports()
    digests = {r["report_id"] for r in initial}
    ids = {source_id(r.get("source_file", "")) for r in initial} - {None}
    names = {r.get("source_file", "") for r in initial}

    before = defaultdict(list)
    for r in initial:
        if r["broker"] in brokers and start.isoformat() <= r["report_date"] <= end.isoformat():
            before[r["broker"]].append(r["report_id"])

    known_issues = published_issues(initial)
    archives = {}
    archive_counts = defaultdict(list)
    drive = io.drive_service()

    for row in io.list_pdfs(drive, io.env("GDRIVE_FOLDER_ID")):
        name = row["name"]
        props = row.get("appProperties", {})
        rid = props.get("nxny_id") or source_id(name)
        digest = row.get("sha256Checksum") or props.get("sha256")
        stamp = re.search(r"-(\d{6})\.pdf$", name, re.I)
        broker = weekly_broker(name)
        if not stamp or not broker or broker[0] not in brokers:
            continue
        day = datetime.strptime(stamp[1], "%y%m%d").date()
        issue_key = (*broker, day.isoformat())
        if not start <= day <= end or rid in ids or digest in digests or name in names or issue_key in known_issues:
            continue
        if "/" in name or "\\" in name:
            raise ValueError("Unsafe archive filename")
        known_issues.add(issue_key)
        archives[row["id"]] = (name, digest, row)
        archive_counts[broker[0]].append(name)
        names.add(name)
        if rid:
            ids.add(rid)
        if digest:
            digests.add(digest)

    rows, hits, skipped = {}, defaultdict(set), defaultdict(set)
    ignored_path = io.ROOT / "ignored_nxny_ids.json"
    ignored = json.loads(ignored_path.read_bytes()) if ignored_path.exists() else {}
    scanned_pages = scan_hc_range(start, end, brokers, ignored, rows, hits, skipped)

    candidates = {}
    for rid, row in rows.items():
        broker, title, page_count, channel = row
        if rid in ids or f"{rid}-{io.name_for(title)}.pdf" in names:
            continue
        key = weekly_issue(title, pages=page_count, channel=channel)
        if not key or key in known_issues:
            continue
        known_issues.add(key)
        candidates[rid] = row

    state = dict(
        before=before,
        archive=archive_counts,
        candidates={b: [rid for rid, row in candidates.items() if row[0] == b] for b in brokers},
        hits={b: sorted(hits[b]) for b in brokers},
        skipped={b: sorted(skipped[b]) for b in brokers},
        pages={"hc": scanned_pages},
    )

    def checkpoint():
        STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf8")

    checkpoint()
    if dry:
        return 0

    io.INBOX.mkdir(exist_ok=True)
    manifest = {}
    for file_id, (name, digest, meta) in archives.items():
        raw = io.download_cached(drive, meta)
        if digest and hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Archive digest mismatch")
        io.save_recovered(name, raw)
        manifest[name] = {"drive_file_id": file_id, "channel": "hc"}

    partial = False
    for rid, (broker, title, pages, channel) in list(candidates.items())[:limit]:
        name = f"{rid}-{io.name_for(title)}.pdf"
        try:
            raw = io.valid(io.fetch_nxny(rid))
        except io.NonPDFReport as exc:
            ignored[rid] = str(exc)
            state["skipped"][broker].append(rid)
            checkpoint()
            continue
        except Exception as exc:
            reason = str(exc) if isinstance(exc, io.NXNYDownloadError) else type(exc).__name__
            print(f"::warning::Download incomplete for {rid}: {reason}")
            partial = True
            break
        io.save_recovered(name, raw)
        io.backup(drive, io.env("GDRIVE_FOLDER_ID"), [io.INBOX / name])
        manifest[name] = dict(title=title, pages=pages, channel=channel)

    io.save_ignored_ids(ignored)
    if manifest:
        (io.INBOX / "listing.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf8")
    return 2 if partial else 0


def summary() -> int:
    start, end, brokers, _ = parameters()
    dry = os.environ.get("DRY_RUN", "false").lower() == "true"
    lines = [f"### {start} 至 {end} · " + ("只读盘点 (Dry Run)" if dry else "补录执行结果")]
    if not STATE.exists():
        lines.append("盘点未完成，请查看上方失败步骤日志。")
    else:
        s = json.loads(STATE.read_bytes())
        committed = os.environ.get("COMMITTED") == "true"
        records = load_all_reports() if committed else []
        lines += [
            f"NXNY `/stype_hc/` 扫描页数：{s['pages']}（待恢复/待下载列为执行前盘点）。",
            "",
            "| 券商 | 此前已入库 | 本次新增入库 | Drive 待恢复 | NXNY 待下载 | 非PDF已跳过 | 源站列表未见 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for b in brokers:
            old = s["before"].get(b, [])
            new = sum(
                r["broker"] == b
                and start.isoformat() <= r["report_date"] <= end.isoformat()
                and r["report_id"] not in old
                for r in records
            )
            lines.append(
                f"| {b} | {len(old)} | {new} | {len(s['archive'].get(b, []))} | "
                f"{len(s['candidates'][b])} | {len(s['skipped'][b])} | {'是' if not s['hits'][b] else '—'} |"
            )
    result = "\n".join(lines)
    print(result)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf8") as out:
            print(result, file=out)
    return 0


if __name__ == "__main__":
    sys.exit(summary() if sys.argv[1:] == ["summary"] else run())
