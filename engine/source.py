"""Stage 0: Zero-truncation PDF paragraph indexing + selective chart-page image rendering."""
from __future__ import annotations

import base64
from collections import Counter
import hashlib
import io
import re
from pypdf import PdfReader

DISCLAIMER_MARKERS = (
    "分析师承诺",
    "分析师声明",
    "免责声明",
    "重要声明",
    "投资评级说明",
    "法律声明",
    "版权声明",
)
CHART_CAPTION_RE = re.compile(r"(?:图\s*表?\s*\d+|表\s*\d+|资料来源\s*[：:]|数据来源\s*[：:])")


def key(text: str) -> str:
    return re.sub(r"\s+", "", text)


def section_level(line: str) -> int | None:
    if len(line) > 85 or re.search(r"[。！？；]|[.·…]{3,}", line):
        return None
    if re.match(r"^[一二三四五六七八九十]+[、.．]", line):
        return 1
    if re.match(r"^[（(][一二三四五六七八九十]+[)）]", line):
        return 2
    match = re.match(r"^(\d+(?:\.\d+)*)(?:[.、．]\s*|\s+)(?=[^\d%])", line)
    return len(match[1].split(".")) if match else None


def bookmark_paths(reader: PdfReader) -> dict[int, list[tuple[str, ...]]]:
    pages: dict[int, list[tuple[str, ...]]] = {}

    def visit(nodes, parents=()):
        current = parents
        for node in nodes:
            if isinstance(node, list):
                visit(node, current)
                continue
            title = str(getattr(node, "title", "")).strip()
            current = parents + (title,) if title else parents
            try:
                page = reader.get_destination_page_number(node)
            except Exception:
                page = None
            if page is not None and page >= 0 and current:
                pages.setdefault(page, []).append(current)

    try:
        visit(reader.outline)
    except Exception:
        pass
    return pages


def index_pdf(data: bytes) -> dict:
    """Extract ordered [P{page}-S{serial}] paragraphs with inherited headings."""
    reader = PdfReader(io.BytesIO(data))
    outlines = bookmark_paths(reader)
    pages, diagnostics = [], []
    margin_counts: Counter[str] = Counter()

    for number, page in enumerate(reader.pages, 1):
        fonts: dict[str, float] = {}
        sizes: Counter[float] = Counter()

        def remember(text, cm, tm, font, size):
            for line in text.splitlines():
                label = key(line)
                if label:
                    fonts[label] = max(fonts.get(label, 0.0), float(size or 0.0))
                    sizes[float(size or 0.0)] += len(label)

        try:
            raw = page.extract_text(visitor_text=remember) or ""
        except Exception:
            raw = page.extract_text() or ""
        lines = raw.splitlines()
        nonempty = [key(line) for line in lines if key(line)]
        margin_counts.update(set(nonempty[:3] + nonempty[-2:]))
        pages.append((lines, fonts, sizes.most_common(1)[0][0] if sizes else 0.0))

        has_image = False
        try:
            resources = page.get("/Resources")
            objects = resources.get_object().get("/XObject") if resources else None
            has_image = bool(
                objects
                and any(
                    ref.get_object().get("/Subtype") == "/Image"
                    for ref in objects.get_object().values()
                )
            )
        except Exception:
            has_image = False

        is_disclaimer = number > 1 and sum(m in raw for m in DISCLAIMER_MARKERS) >= 2
        has_chart_caption = bool(CHART_CAPTION_RE.search(raw))
        diagnostics.append(
            dict(
                page=number,
                text_chars=len(raw),
                has_image=has_image,
                has_chart_caption=has_chart_caption,
                is_disclaimer=is_disclaimer,
                text_missing=not raw.strip(),
            )
        )

    paragraphs, path = [], []
    for number, (lines, fonts, body) in enumerate(pages, 1):
        paths = outlines.get(number - 1, [])
        titles = {key(p[-1]): p for p in paths if p}
        if paths and not any(key(line) in titles for line in lines):
            path = list(paths[0])
        serial, chunks = 0, []

        def flush():
            nonlocal serial
            if chunks:
                serial += 1
                paragraphs.append(
                    dict(
                        pid=f"P{number}-S{serial}",
                        page=number,
                        text="\n".join(chunks),
                        heading=" / ".join(path) or "正文（尚无章节标题）",
                    )
                )
                chunks.clear()

        for line in lines:
            clean, label = line.strip(), key(line)
            if not clean:
                flush()
                continue
            level = section_level(clean)
            larger = (
                body
                and fonts.get(label, 0.0) > 1.15 * body
                and len(label) <= 65
                and not re.search(r"[。！？；]|[.·…]{3,}", clean)
            )
            if label in titles:
                flush()
                path = list(titles[label])
            elif (level or larger) and margin_counts[label] < 3:
                flush()
                depth = level or (2 if path else 1)
                path = path[: depth - 1] + [clean]
            elif re.match(r"^[⚫●■◆❖•]|^\s*[（(]\d+[)）]", clean):
                flush()
            chunks.append(line)
            if label in titles or ((level or larger) and margin_counts[label] < 3):
                flush()
        flush()
        diagnostics[number - 1]["paragraphs"] = serial

    return dict(
        report_id=hashlib.sha256(data).hexdigest(),
        total_pages=len(reader.pages),
        paragraphs=paragraphs,
        pages=diagnostics,
    )


def select_chart_pages_base64(data: bytes, index: dict, max_pages: int = 6) -> list[dict]:
    """Render up to `max_pages` chart-bearing body pages as compact JPEG data URLs for Stage 1 Vision."""
    if max_pages <= 0:
        return []
    try:
        import pymupdf as fitz  # PyMuPDF
    except ImportError:
        return []

    candidates = []
    total = index.get("total_pages", len(index.get("pages", [])))
    for diag in index.get("pages", []):
        pnum = diag["page"]
        if diag.get("is_disclaimer"):
            continue
        if total >= 5 and pnum == total:
            continue
        score = 0
        if diag.get("has_image") and diag.get("has_chart_caption"):
            score += 4
        elif diag.get("has_image"):
            score += 2
        elif diag.get("has_chart_caption"):
            score += 1
        if pnum > 1:
            score += 1
        if score >= 2:
            candidates.append((score, pnum))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    chosen_pages = sorted(pnum for _, pnum in candidates[:max_pages])
    if not chosen_pages:
        return []

    rendered = []
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            for pnum in chosen_pages:
                page = doc[pnum - 1]
                pix = page.get_pixmap(dpi=125, alpha=False)
                img_bytes = pix.tobytes("jpeg", jpg_quality=76)
                b64 = base64.b64encode(img_bytes).decode("ascii")
                rendered.append({"page": pnum, "data_url": f"data:image/jpeg;base64,{b64}"})
        finally:
            doc.close()
    except Exception:
        return []
    return rendered


def context(index: dict, pids: list[str]) -> list[dict]:
    rows = index["paragraphs"]
    pos = {p["pid"]: i for i, p in enumerate(rows)}
    selected: set[int] = set()
    for pid in pids:
        if pid in pos:
            i = pos[pid]
            selected.update(range(max(0, i - 1), min(len(rows), i + 2)))
    return [rows[i] for i in sorted(selected)]
