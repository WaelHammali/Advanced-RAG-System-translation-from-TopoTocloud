"""End-to-end run on a synthetic diagram: real OpenCV + fusion + topology, fake YOLO/OCR.

YOLO and PaddleOCR are replaced by detectors that report the ground-truth boxes (the real
models are optional dependencies); everything downstream of them is the real code path,
including writing the five JSON files and reading the raw ones back from disk.
"""

import json

import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402
from examples.synthetic_demo import build  # noqa: E402
from vision_pipeline.cli import main  # noqa: E402
from vision_pipeline.config.settings import Settings  # noqa: E402
from vision_pipeline.pipeline import Pipeline  # noqa: E402
from vision_pipeline.schemas.raw import ImageInfo, RawOcr, RawYolo  # noqa: E402


def test_full_pipeline_writes_all_five_files_and_reconstructs_the_network(tmp_path):
    path, fy, fo = build(tmp_path)
    out = tmp_path / "outputs"
    topo = Pipeline(Settings(), yolo_detector=fy, ocr_detector=fo).run(path, out)

    for name in ("raw_yolo", "raw_ocr", "raw_opencv", "fusion", "topology", "topology.simple"):
        assert (out / f"{name}.json").is_file(), name
    assert json.loads((out / "topology.json").read_text()) == json.loads(json.dumps(topo))

    by_type = {d["type"]: d for d in topo["devices"]}
    assert [d["name"] for d in topo["devices"]] == ["R1", "SW1", "PC1"]
    assert len(topo["links"]) == 2
    l1, l2 = topo["links"]
    assert (l1["source"], l1["target"]) == ("device_001", "device_002")
    assert (l2["source"], l2["target"]) == ("device_002", "device_003")
    assert (
        l1["network"]["network_address"] == "192.168.1.0" and l1["network"]["prefix_length"] == 24
    )
    assert l2["network"] == {
        "network_address": "10.0.0.0",
        "prefix_length": 30,
        "subnet_mask": "255.255.255.252",
    }

    assert by_type["router"]["network"]["ip_address"] == "192.168.1.1"
    assert by_type["pc"]["network"]["ip_address"] == "10.0.0.2"
    # the switch has two links and two suffixes -> two addresses, one on each link
    sw = {a["link_id"]: a["ip_address"] for a in by_type["switch"]["addresses"]}
    assert sw == {l1["id"]: "192.168.1.2", l2["id"]: "10.0.0.1"}
    assert by_type["switch"]["network"]["ip_address"] is None  # multi-homed: no scalar guess
    assert topo["unresolved"] == []


def test_fuse_subcommand_rebuilds_topology_from_the_raw_files(tmp_path):
    path, fy, fo = build(tmp_path)
    out = tmp_path / "outputs"
    first = Pipeline(Settings(), yolo_detector=fy, ocr_detector=fo).run(path, out)
    (out / "topology.json").unlink()
    (out / "fusion.json").unlink()
    simple_before = (out / "topology.simple.json").read_text()
    (out / "topology.simple.json").unlink()
    assert main(["fuse", "--output-dir", str(out)]) == 0
    assert json.loads((out / "topology.json").read_text()) == json.loads(json.dumps(first))
    assert (out / "topology.simple.json").read_text() == simple_before


def test_fusion_json_is_traceable(tmp_path):
    path, fy, fo = build(tmp_path)
    out = tmp_path / "outputs"
    Pipeline(Settings(), yolo_detector=fy, ocr_detector=fo).run(path, out)
    f = json.loads((out / "fusion.json").read_text())
    for key in (
        "raw_references",
        "ocr_classifications",
        "ocr_groups",
        "device_name_associations",
        "address_associations",
        "host_suffix_associations",
        "cable_candidates",
        "cable_endpoint_associations",
        "network_label_associations",
        "resolved_addresses",
        "ambiguous",
        "unresolved",
        "graph",
        "config",
        "warnings",
    ):
        assert key in f, key
    resolved = [r for r in f["resolved_addresses"] if r["status"] == "resolved"]
    assert len(resolved) == 4
    assert all(
        r["provenance"]["sources"] == ["ocr", "opencv", "fusion", "address_resolver"]
        for r in resolved
    )


def test_pipeline_without_any_diagram_content_gives_an_empty_but_valid_topology(tmp_path):
    path = tmp_path / "blank.png"
    cv2.imwrite(str(path), np.full((200, 300, 3), 255, np.uint8))
    info = ImageInfo(str(path), 300, 200)

    class NoYolo:
        def detect(self, p):
            return RawYolo(info, [])

    class NoOcr:
        def detect(self, p):
            return RawOcr(info, [])

    topo = Pipeline(Settings(), yolo_detector=NoYolo(), ocr_detector=NoOcr()).run(
        path, tmp_path / "o"
    )
    assert topo["devices"] == [] and topo["links"] == [] and topo["unresolved"] == []


def test_outputs_validate_against_the_json_schemas(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    from pathlib import Path

    schema_dir = Path(__file__).resolve().parents[1] / "vision_pipeline" / "schemas" / "json"
    path, fy, fo = build(tmp_path)
    out = tmp_path / "outputs"
    Pipeline(Settings(), yolo_detector=fy, ocr_detector=fo).run(path, out)
    for raw, schema in (
        ("raw_yolo", "raw_yolo"),
        ("raw_ocr", "raw_ocr"),
        ("raw_opencv", "raw_opencv"),
        ("topology", "topology"),
        ("topology.simple", "topology_simple"),
    ):
        jsonschema.validate(
            json.loads((out / f"{raw}.json").read_text()),
            json.loads((schema_dir / f"{schema}.schema.json").read_text()),
        )
