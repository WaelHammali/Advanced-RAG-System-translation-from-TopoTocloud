#!/usr/bin/env python3
"""Validate documentation artifacts; never deploy or claim retrieval accuracy."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "kb"
MANIFEST = KB / "manifest.json"
CORPUS_VERSION = "2.2.0"
CORE = ["CORE-001", "CORE-002", "CORE-003"]
FIELDS = {
    "Rule-ID",
    "Kind",
    "Mode",
    "Status",
    "Keywords",
    "Applies",
    "Required",
    "Forbidden",
    "Expected",
    "Verify",
    "Sources",
    "Related",
}


def actual_chunker():
    """Load only the repository's pure chunker, avoiding ML imports/downloads."""
    config = ast.parse((ROOT / "config.py").read_text(encoding="utf-8"))
    limit = next(
        ast.literal_eval(node.value)
        for node in config.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "MAX_CHARS_PER_CHUNK" for t in node.targets)
    )
    source = ast.parse((ROOT / "retriever.py").read_text(encoding="utf-8"))
    nodes = [
        node
        for node in source.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef))
        and node.name in {"KBChunk", "_chunk_markdown"}
    ]
    if len(nodes) != 2:
        raise ValueError("Cannot find the actual KBChunk and Markdown chunker")
    module = ast.Module(body=nodes, type_ignores=[])
    env = {"__name__": __name__, "dataclass": dataclass, "MAX_CHARS_PER_CHUNK": limit}
    exec(compile(module, str(ROOT / "retriever.py"), "exec"), env)
    return env["_chunk_markdown"], limit


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def validate(refresh: bool) -> dict:
    errors = []
    source_doc = json.loads((ROOT / "docs/sources.json").read_text())
    sources = {item["id"] for item in source_doc["sources"]}
    if len(sources) != len(source_doc["sources"]):
        errors.append("Duplicate source IDs")
    for item in source_doc["sources"]:
        if item["id"] != "PROJECT" and not str(item.get("url", "")).startswith("https://"):
            errors.append(f"Invalid source URL: {item['id']}")
    chunker, limit = actual_chunker()
    records, files, seen = [], [], set()
    for path in sorted(KB.rglob("*.md")):
        content = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT).as_posix()
        files.append({"path": relative, "sha256": digest(path.read_bytes())})
        chunks = chunker(str(path))
        headings = [line for line in content.splitlines() if line.startswith("#")]
        if len(chunks) != len(headings):
            errors.append(f"{relative}: split, empty or orphan chunk")
        for chunk in chunks:
            match = re.fullmatch(r"## \[([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\] (.+)", chunk.heading)
            if not match:
                errors.append(f"{relative}: invalid heading {chunk.heading!r}")
                continue
            rid, title = match.groups()
            pairs = []
            for line in chunk.text.splitlines()[1:]:
                if not line.strip():
                    continue
                if ": " not in line:
                    errors.append(f"{relative}/{rid}: malformed field")
                    continue
                pairs.append(line.split(": ", 1))
            fields = dict(pairs)
            if set(fields) != FIELDS or len(pairs) != len(FIELDS):
                errors.append(f"{rid}: missing, duplicate or unknown fields")
            if fields.get("Rule-ID") != rid or rid in seen:
                errors.append(f"{rid}: duplicate/mismatched rule ID")
            seen.add(rid)
            if any(not value.strip() for value in fields.values()):
                errors.append(f"{rid}: empty field")
            if fields.get("Kind") not in {"rule", "example"}:
                errors.append(f"{rid}: invalid kind")
            if fields.get("Mode") not in {"behavioral_lab", "cloud_native", "all"}:
                errors.append(f"{rid}: invalid mode")
            if fields.get("Status") != "target_specification":
                errors.append(f"{rid}: target status missing")
            if len(chunk.text) > limit:
                errors.append(f"{rid}: exceeds actual chunk limit {limit}")
            source_ids = fields.get("Sources", "").split(", ")
            if set(source_ids) - sources:
                errors.append(f"{rid}: unknown source IDs")
            records.append(
                {
                    "id": rid,
                    "path": relative,
                    "title": title,
                    "kind": fields.get("Kind"),
                    "mode": fields.get("Mode"),
                    "characters": len(chunk.text),
                    "sha256": digest(chunk.text.encode()),
                    "sources": source_ids,
                    "related": fields.get("Related", "").split(", "),
                }
            )
    for record in records:
        missing = set(record["related"]) - seen
        if missing:
            errors.append(f"{record['id']}: unknown related IDs {sorted(missing)}")
    if set(CORE) - seen:
        errors.append("Missing mandatory core records")

    cases_path = ROOT / "evaluations/rag_cases.jsonl"
    case_ids, cases = set(), []
    for line_number, line in enumerate(cases_path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        case = json.loads(line)
        cid = case.get("id")
        if not cid or cid in case_ids:
            errors.append(f"Case line {line_number}: duplicate/missing ID")
        case_ids.add(cid)
        if not case.get("prompt") or not case.get("must_include") or not case.get("must_not"):
            errors.append(f"{cid}: incomplete evaluation assertions")
        if case.get("expected_prediction") not in {"pass", "fail", "unknown", "unsupported"}:
            errors.append(f"{cid}: invalid prediction")
        if case.get("mode") != "behavioral_lab":
            errors.append(f"{cid}: expected behavioral mode")
        groups = case.get("required_rule_groups", [])
        if not groups or any(not g or set(g) - seen for g in groups):
            errors.append(f"{cid}: invalid/unknown retrieval rule group")
        cases.append(case)

    # Local file links in authored docs/README must resolve. Anchor semantics
    # and remote URLs are reviewed separately; this makes no network requests.
    for path in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]:
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text()):
            if "://" in target or target.startswith("#"):
                continue
            target = unquote(target.removeprefix("<").removesuffix(">").split("#", 1)[0])
            resolved = path.parent / target
            if resolved == MANIFEST and refresh:
                continue
            if not resolved.exists():
                errors.append(f"{path.name}: broken local link {target}")

    manifest = {
        "schema_version": "1.0",
        "corpus_version": CORPUS_VERSION,
        "status": "target_specification",
        "default_mode": "behavioral_lab",
        "reviewed_on": source_doc["reviewed_on"],
        "specification": "docs/NETWORK_TRANSLATION_SPEC.md",
        "source_register": "docs/sources.json",
        "evaluation_cases": "evaluations/rag_cases.jsonl",
        "mandatory_context_ids": CORE,
        "chunker": {"path": "retriever.py", "function": "_chunk_markdown", "max_characters": limit},
        "files": files,
        "records": records,
    }
    if not errors and refresh:
        MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    elif not refresh:
        if not MANIFEST.exists() or json.loads(MANIFEST.read_text()) != manifest:
            errors.append("Manifest stale/missing: review changes then run --refresh-manifest")
    if errors:
        raise ValueError("\n".join(errors))
    return {
        "status": "pass",
        "markdown_files": len(files),
        "records": len(records),
        "examples": sum(r["kind"] == "example" for r in records),
        "evaluation_cases": len(cases),
        "largest_record_characters": max(r["characters"] for r in records),
        "chunk_limit_characters": limit,
        "manifest_refreshed": refresh,
        "checks": "structure, actual chunker, IDs, references, local links, manifest hashes",
        "not_tested": "embedding tokenization, retrieval quality, model answers, live network behavior",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh-manifest",
        action="store_true",
        help="Write the reviewed corpus inventory after structural validation",
    )
    args = parser.parse_args()
    try:
        print(json.dumps(validate(args.refresh_manifest), indent=2))
    except (ValueError, OSError, KeyError, StopIteration) as error:
        print(f"Knowledge validation failed:\n{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
