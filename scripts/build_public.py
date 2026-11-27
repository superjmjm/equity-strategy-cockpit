"""Package clean static files (index.html, styles.css, app.js, snapshot.json) for GitHub Pages."""
from __future__ import annotations

import argparse
from pathlib import Path
from shutil import copyfile
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_snapshot import build_full_snapshot
from scripts.store import atomic_write_json


def build_public(destination: Path, *, run_stage3: bool = False) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    snap = build_full_snapshot(run_stage3=run_stage3)
    atomic_write_json(destination / "snapshot.json", snap)
    web_dir = ROOT / "web"
    for name in ("index.html", "styles.css", "app.js"):
        copyfile(web_dir / name, destination / name)
    (destination / ".nojekyll").write_text("", encoding="utf-8")
    print(f"PUBLIC_STAGED dir={destination} demo_mode={snap['demo_mode']} latest_week={snap['latest_week']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--run-stage3", action="store_true")
    args = parser.parse_args()
    build_public(args.destination, run_stage3=args.run_stage3)
