"""Layer separation, enforced from the import graph."""

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "vision_pipeline"


def imports_of(path: Path) -> set[str]:
    """Absolute dotted names of every module imported by ``path`` (relative imports resolved)."""
    rel = path.relative_to(PKG.parent).with_suffix("")
    pkg_parts = list(rel.parts[:-1])
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = pkg_parts[: len(pkg_parts) - (node.level - 1)] if node.level else []
            mod = ".".join(base + ([node.module] if node.module else []))
            out.add(mod)
            out.update(f"{mod}.{a.name}" for a in node.names)
    return out


def modules(sub: str):
    return [p for p in (PKG / sub).glob("*.py")]


def forbidden(sub: str, banned: list[str], allow: tuple[str, ...] = ()):
    bad = []
    for p in modules(sub):
        for imp in imports_of(p):
            if any(imp == b or imp.startswith(b + ".") for b in banned) and not any(
                imp == a or imp.startswith(a + ".") for a in allow
            ):
                bad.append(f"{p.name} imports {imp}")
    return bad


def test_yolo_knows_nothing_about_other_stages():
    assert (
        forbidden(
            "yolo",
            [
                "vision_pipeline.ocr",
                "vision_pipeline.opencv",
                "vision_pipeline.fusion",
                "vision_pipeline.topology",
            ],
        )
        == []
    )


def test_ocr_detector_and_parser_know_nothing_about_links_or_topology():
    assert (
        forbidden(
            "ocr",
            [
                "vision_pipeline.yolo",
                "vision_pipeline.opencv",
                "vision_pipeline.fusion",
                "vision_pipeline.topology",
            ],
        )
        == []
    )


def test_opencv_creates_no_topology_entities_and_does_not_import_other_detectors():
    assert (
        forbidden(
            "opencv",
            [
                "vision_pipeline.yolo",
                "vision_pipeline.ocr",
                "vision_pipeline.fusion",
                "vision_pipeline.topology",
            ],
        )
        == []
    )


def test_fusion_does_not_import_detectors_or_the_topology_package():
    # fusion may use the OCR *semantic* modules (parser, address arithmetic), never a detector
    assert (
        forbidden(
            "fusion",
            [
                "vision_pipeline.yolo",
                "vision_pipeline.opencv",
                "vision_pipeline.topology",
                "vision_pipeline.ocr.detector",
            ],
        )
        == []
    )


def test_topology_builder_reads_only_the_fusion_document():
    assert (
        forbidden(
            "topology",
            [
                "vision_pipeline.yolo",
                "vision_pipeline.opencv",
                "vision_pipeline.ocr.detector",
                "vision_pipeline.ocr.semantic_parser",
            ],
        )
        == []
    )
    tb = imports_of(PKG / "topology" / "topology_builder.py")
    assert not any(i.startswith("vision_pipeline.fusion") for i in tb)


def test_only_the_topology_builder_and_pipeline_write_topology_json():
    writers = []
    for p in PKG.rglob("*.py"):
        text = p.read_text()
        if "write_json" in text and ("topology" in p.name or "TOPOLOGY" in text):
            writers.append(p.name)
    assert sorted(writers) == ["pipeline.py", "topology_builder.py"]
    # the pipeline only ever hands topology output to the builder
    src = (PKG / "pipeline.py").read_text()
    assert "builder.write(topology, topology_out)" in src
    assert "write_json(topology" not in src


def test_no_llm_rag_or_iac_dependencies():
    banned = ("openai", "anthropic", "langgraph", "langchain", "terraform", "ansible", "faiss")
    for p in PKG.rglob("*.py"):
        for imp in imports_of(p):
            assert not imp.split(".")[0].lower().startswith(banned), f"{p.name}: {imp}"


def test_validation_works_on_the_json_contract_only():
    assert (
        forbidden(
            "validation",
            [
                "vision_pipeline.yolo",
                "vision_pipeline.ocr",
                "vision_pipeline.opencv",
                "vision_pipeline.fusion",
                "vision_pipeline.topology",
            ],
        )
        == []
    )
