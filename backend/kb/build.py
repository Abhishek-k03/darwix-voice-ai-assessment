"""KB build orchestrator. Run: uv run python -m kb.build [--include-external] [--no-index]

sources -> extract -> clean -> quarantine -> normalize -> block dedupe -> chunk -> PII redact -> classify
-> supersede -> near-dup merge -> stable IDs/versions -> conflicts -> records.jsonl + report -> Chroma index
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from . import clean, conflicts, dedupe, index
from .chunk import chunk_doc
from .extract import FILE_EXTRACTORS, ExtractionError, LocalSite, web_docs
from .normalize import Normalizer
from .pii import CUSTOMER_RECORD_MIN_TYPES, PERSON_CONTEXT_DOC_TYPES, PIIScrubber
from .retriever import KB_DIR
from .schema import Issue, KBRecord, RawDoc

ROOT = Path(__file__).resolve().parents[2]
SOURCES_ROOT = ROOT / "data" / "sources"
CONFIG = Path(__file__).parent / "config"
logger = logging.getLogger("kb.build")


def _load(name: str) -> dict:
    return yaml.safe_load((CONFIG / name).read_text(encoding="utf-8"))


def extract_all(cfg: dict, include_external: bool) -> tuple[list[RawDoc], list[Issue], dict, dict]:
    docs: list[RawDoc] = []
    issues: list[Issue] = []
    src_by_id: dict[str, dict] = {}
    stats: Counter = Counter()
    with LocalSite(SOURCES_ROOT) as site:
        jobs = [(m, mc["language"], s) for m, mc in cfg["markets"].items() for s in mc["sources"]]
        if include_external:
            jobs += [(s["market"], "en", s) for s in cfg.get("external", [])]
        for market, lang, src in jobs:
            src_by_id[src["id"]] = src
            if src["type"] == "web":
                base = "" if src["seeds"][0].startswith("http") else site.base_url
                got, failures = web_docs(src, market, lang, base)
                stats["boilerplate_blocks_removed"] += clean.remove_site_boilerplate(got)
                stats["web_chrome_chars_removed"] += sum(d.meta.get("chrome_chars_removed", 0) for d in got)
                docs += got
                stats["web_pages_extracted"] += len(got)
                for url, reason in failures:
                    issues.append(Issue(kind="extraction_failure", source_id=src["id"], uri=url, detail=reason))
                continue
            path = SOURCES_ROOT / src["path"]
            try:
                doc = FILE_EXTRACTORS[src["type"]](path, src, market, lang, SOURCES_ROOT)
                stats["running_header_footer_lines_removed"] += doc.meta.get("running_lines_removed", 0)
                docs.append(doc)
                stats[f"{src['type']}_extracted"] += 1
            except ExtractionError as exc:
                issues.append(Issue(kind="extraction_failure", source_id=src["id"], uri=src["path"], detail=str(exc)))
            except Exception as exc:  # noqa: BLE001 — a broken file must not abort the build
                issues.append(Issue(kind="extraction_failure", source_id=src["id"], uri=src["path"],
                                    detail=f"{type(exc).__name__}: {exc}"))
    return docs, issues, src_by_id, dict(stats)


def mark_superseded(docs: list[RawDoc]) -> list[str]:
    groups: dict[str, list[RawDoc]] = defaultdict(list)
    for d in docs:
        if d.type != "web":
            groups[d.doc_group].append(d)
    superseded = []
    for group in groups.values():
        dated = [d for d in group if d.effective_date]
        if len(dated) < 2:
            continue
        newest = max(dated, key=lambda d: d.effective_date)
        for d in dated:
            if d is not newest:
                d.status = "superseded"
                superseded.append(f"{d.uri} (superseded by {newest.uri})")
    return superseded


def build(include_external: bool = False, write_vectors: bool = True, out_dir: Path = KB_DIR) -> dict:
    t0 = time.perf_counter()
    cfg, norm_cfg, taxonomy = _load("sources.yaml"), _load("normalization.yaml"), _load("taxonomy.yaml")
    docs, issues, src_by_id, stats = extract_all(cfg, include_external)
    stats.update({k: v for k, v in clean.clean_docs(docs, norm_cfg.get("glyph_repairs", {})).items()})

    scrubber = PIIScrubber(norm_cfg.get("pii_allow_list", []))
    kept_docs = []
    for d in docs:
        if d.doc_type == "form_field":
            types = {r.entity_type for r in scrubber.analyze("\n".join(b.text for b in d.blocks), person_context=True)}
            if len(types) >= CUSTOMER_RECORD_MIN_TYPES:
                issues.append(Issue(kind="quarantined", source_id=d.source_id, uri=d.uri,
                                    detail=f"customer record with personal data ({', '.join(sorted(types))}); excluded from KB"))
                continue
        kept_docs.append(d)
    docs = kept_docs

    normalizer = Normalizer(norm_cfg, taxonomy)
    aliases: dict[str, set[str]] = {}
    for d in docs:
        doc_issues, hits = normalizer.normalize_doc(d)
        issues += doc_issues
        aliases[d.uri] = hits
        stats["terminology_variants_normalized"] = stats.get("terminology_variants_normalized", 0) + len(hits)

    superseded = mark_superseded(docs)
    stats["duplicate_blocks_removed"] = dedupe.dedupe_blocks(docs)

    records: list[KBRecord] = []
    for d in docs:
        src = src_by_id[d.source_id]
        flagged: set[tuple] = set()
        if d.doc_type == "premium_table":
            table_issues, flagged = conflicts.check_series(d, src)
            issues += table_issues
        for r in chunk_doc(d, src, normalizer, flagged):
            r.content, pii_types = scrubber.redact(r.content, r.doc_type in PERSON_CONTEXT_DOC_TYPES)
            r.pii, r.pii_types = bool(pii_types), pii_types
            r.category = normalizer.categorize(r.title, r.content, r.doc_type)
            r.subcategory = r.source.section
            r.product = normalizer.product(r.title, r.content, r.market)
            r.tags = sorted(aliases.get(d.uri, set()))
            records.append(r)

    records, merged = dedupe.near_dedupe(records)
    stats["near_duplicate_records_merged"] = len(merged)

    prev_path = out_dir / "manifest.json"
    prev = json.loads(prev_path.read_text(encoding="utf-8")) if prev_path.exists() else None
    manifest, change = index.assign_ids(records, prev)
    found_conflicts = conflicts.detect_conflicts(records, taxonomy.get("facts", {}))
    for c in found_conflicts:
        issues.append(Issue(kind="conflict", source_id="multiple", uri=c["authoritative_source"],
                            detail=f"{c['market']}.{c['fact']}: values "
                                   f"{sorted({v['value'] for v in c['values']})}; resolved to {c['resolution']} "
                                   f"from {c['authoritative_record']}"))

    out_dir.mkdir(parents=True, exist_ok=True)
    index.write_jsonl(out_dir / "records.jsonl", records)
    if write_vectors:
        manifest["collection"] = index.write_index(records, manifest["kb_version"], out_dir / "index")
    prev_log = json.loads((out_dir / "changelog.json").read_text(encoding="utf-8")) if (out_dir / "changelog.json").exists() else []
    if not prev or change["added"] or change["updated"] or change["removed"]:
        prev_log.append(change)
    (out_dir / "changelog.json").write_text(json.dumps(prev_log, indent=2), encoding="utf-8")
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    report = {
        "kb_version": manifest["kb_version"], "built_at": manifest["built_at"],
        "duration_s": round(time.perf_counter() - t0, 1), "stats": stats,
        "records_total": len(records), "records_active": sum(r.status == "active" for r in records),
        "by_market": Counter(r.market for r in records), "by_doc_type": Counter(r.doc_type for r in records),
        "by_category": Counter(r.category for r in records),
        "pii_records": [{"record_id": r.record_id, "types": r.pii_types} for r in records if r.pii],
        "superseded_docs": superseded,
        "near_duplicates": [{"dropped": f"{a.source.uri} › {a.title}", "kept": b.record_id} for a, b in merged],
        "conflicts": found_conflicts, "issues": [i.model_dump() for i in issues], "changes": change,
    }
    (out_dir / "build_report.json").write_text(json.dumps(report, indent=2, default=list), encoding="utf-8")
    (out_dir / "build_report.md").write_text(render_report(report), encoding="utf-8")
    return report


def render_report(rep: dict) -> str:
    s = rep["stats"]
    lines = [f"# KB build report — v{rep['kb_version']}", "",
             f"Built {rep['built_at']} in {rep['duration_s']}s. Records: {rep['records_total']} "
             f"({rep['records_active']} active).", "", "## Pipeline statistics", ""]
    lines += [f"- {k.replace('_', ' ')}: {v}" for k, v in s.items()]
    lines += ["", "## Records", "", "| market | count |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rep["by_market"].items()]
    lines += ["", "| doc_type | count |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rep["by_doc_type"].items()]
    lines += ["", "## Extraction failures, quarantines and source errors", "", "| kind | source | uri | detail |", "|---|---|---|---|"]
    lines += [f"| {i['kind']} | {i['source_id']} | {i['uri']} | {i['detail']} |" for i in rep["issues"]]
    lines += ["", "## Conflicts (resolved by authority, then recency)", ""]
    for c in rep["conflicts"]:
        lines.append(f"- **{c['market']}.{c['fact']}** → {c['resolution']} ({c['authoritative_record']}, {c['authoritative_source']})")
        lines += [f"  - {v['value']} — {v['record_id']} [{v['source']}, authority {v['authority']}]: “{v['evidence']}”" for v in c["values"]]
    lines += ["", "## Superseded documents", ""] + [f"- {x}" for x in rep["superseded_docs"]]
    lines += ["", "## Near-duplicates merged", ""] + [f"- {x['dropped']} → kept {x['kept']}" for x in rep["near_duplicates"]]
    lines += ["", "## Records containing redacted PII", ""] + [f"- {x['record_id']}: {', '.join(x['types'])}" for x in rep["pii_records"]]
    ch = rep["changes"]
    lines += ["", "## Changes vs previous build", "", f"- added: {len(ch['added'])}", f"- updated: {len(ch['updated'])}",
              f"- removed: {len(ch['removed'])}", ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-external", action="store_true", help="also crawl the public reference page")
    ap.add_argument("--no-index", action="store_true", help="skip embedding/indexing")
    ap.add_argument("--if-missing", action="store_true", help="only build when the active index is absent (containers)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    if a.if_missing and (KB_DIR / "manifest.json").exists():
        m = json.loads((KB_DIR / "manifest.json").read_text(encoding="utf-8"))
        try:
            index.client(KB_DIR / "index").get_collection(index.collection_name(m["kb_version"]))
            print(f"KB v{m['kb_version']} index present, skipping build")
            return
        except Exception:  # noqa: BLE001 — missing collection -> build
            pass
    rep = build(include_external=a.include_external, write_vectors=not a.no_index)
    print(f"KB v{rep['kb_version']}: {rep['records_active']} active / {rep['records_total']} records, "
          f"{len(rep['issues'])} issues, {len(rep['conflicts'])} conflicts, {rep['duration_s']}s")


if __name__ == "__main__":
    main()
