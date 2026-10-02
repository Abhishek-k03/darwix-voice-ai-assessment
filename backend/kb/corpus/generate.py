"""Regenerates data/sources/ (synthetic corpus). Run: uv run python -m kb.corpus.generate"""

from __future__ import annotations

from pathlib import Path

from . import id_multifinance, in_health, ph_life

ROOT = Path(__file__).resolve().parents[3] / "data" / "sources"


def main() -> None:
    for name, mod in (("in_health", in_health), ("ph_life", ph_life), ("id_multifinance", id_multifinance)):
        mod.build(ROOT / name)
        n = sum(1 for p in (ROOT / name).rglob("*") if p.is_file())
        print(f"{name}: {n} files")


if __name__ == "__main__":
    main()
