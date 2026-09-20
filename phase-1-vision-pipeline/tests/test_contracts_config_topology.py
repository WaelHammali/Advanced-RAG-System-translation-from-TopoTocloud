"""Coordinate normalisation, raw-schema validation, config loading, topology validation."""

import json

import helpers as h
import pytest
from vision_pipeline.config.settings import ENV_WEIGHTS, Settings
from vision_pipeline.config.thresholds import Thresholds
from vision_pipeline.fusion.coordinate_normalizer import (
    CoordinateMismatchError,
    normalize_coordinates,
)
from vision_pipeline.schemas.raw import ImageInfo, RawOcr, RawOpenCV, RawYolo, SchemaError
from vision_pipeline.topology.topology_builder import (
    TopologyBuilder,
    TopologyValidationError,
    validate_topology,
)

# ------------------------------------------------------------------------- pass 1


def test_mismatched_image_sizes_are_refused():
    y = h.yolo([("router", (10, 10, 50, 50))])
    o = h.ocr([])
    o.image = ImageInfo("d.png", 1600, 800)  # e.g. OCR reported coordinates of an upscaled copy
    with pytest.raises(CoordinateMismatchError) as e:
        normalize_coordinates(y, o, h.opencv(), Thresholds())
    assert "raw_ocr=(1600, 800)" in str(e.value)


def test_out_of_bounds_boxes_are_clipped_with_a_warning():
    y = h.yolo([("router", (-30, 10, 50, 50)), ("pc", (900, 900, 950, 950))])
    inp = normalize_coordinates(y, h.ocr([]), h.opencv(), Thresholds())
    assert [d.id for d in inp.devices] == ["device_001"] and inp.devices[0].bbox.x1 == 0
    assert {w["code"] for w in inp.warnings} == {"bbox_outside_image", "bbox_empty_after_clip"}


# ----------------------------------------------------------------- raw schema loading


def test_raw_schema_rejects_bad_documents():
    with pytest.raises(SchemaError):
        RawYolo.from_dict({"image": {"width": 10, "height": 10}, "detections": [{"id": "d1"}]})
    with pytest.raises(SchemaError):
        RawOcr.from_dict({"image": {"width": 0, "height": 10}, "texts": []})
    with pytest.raises(SchemaError):
        RawOcr.from_dict(
            {
                "image": {"width": 10, "height": 10},
                "texts": [
                    {"id": "t", "text": "a", "confidence": 1, "bbox": [0, 0, 1, 1]},
                    {"id": "t", "text": "b", "confidence": 1, "bbox": [0, 0, 1, 1]},
                ],
            }
        )
    with pytest.raises(SchemaError):
        RawOpenCV.from_dict(
            {
                "image": {"width": 10, "height": 10},
                "link_candidates": [
                    {"id": "l", "segments": [{"p1": [1, 2, 3], "p2": [0, 0]}], "confidence": 0.5}
                ],
            }
        )


def test_link_candidate_null_endpoints_survive_round_trip():
    doc = {
        "image": {"width": 10, "height": 10},
        "link_candidates": [
            {
                "id": "l1",
                "segments": [{"p1": [0, 0], "p2": [5, 5]}],
                "start": None,
                "end": None,
                "path_type": "branched",
                "confidence": 0.5,
            }
        ],
    }
    c = RawOpenCV.from_dict(doc).candidates[0]
    assert c.start is None and c.end is None
    assert c.to_dict()["start"] is None and c.to_dict()["end"] is None


# ----------------------------------------------------------------------------- config


def test_weights_path_precedence_default_file_env_cli(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_WEIGHTS, raising=False)
    assert Settings.load().yolo.weights_path.endswith("models/yolo/best.pt")
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        "yolo:\n  weights_path: /from/file.pt\n  confidence: 0.4\nthresholds:\n  link:\n    missing_endpoint_penalty: 0.5\n"
    )
    s = Settings.load(cfg)
    assert (s.yolo.weights_path, s.yolo.confidence, s.thresholds.link.missing_endpoint_penalty) == (
        "/from/file.pt",
        0.4,
        0.5,
    )
    monkeypatch.setenv(ENV_WEIGHTS, "/from/env.pt")
    assert Settings.load(cfg).yolo.weights_path == "/from/env.pt"
    assert Settings.load(cfg, weights="/from/cli.pt").yolo.weights_path == "/from/cli.pt"


def test_unknown_config_key_is_an_error_not_silently_ignored(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"thresholds": {"nope": 1}}))
    with pytest.raises(KeyError):
        Settings.load(cfg)


def test_settings_round_trip_to_dict():
    d = Settings().to_dict()
    assert d["thresholds"]["endpoint_to_device"]["tier"]["high"] == 0.75
    assert d["opencv"]["mask_devices"] is True


# ------------------------------------------------------------------------- topology


def _good():
    y = h.yolo([("router", (100, 100, 180, 180))])
    return h.run(
        y,
        h.ocr([("R1", (128, 186, 152, 202)), ("192.168.1.1/24", (100, 206, 180, 222))]),
        h.opencv(),
    )[1]


def test_topology_shape_matches_the_specification():
    t = _good()
    assert set(t) == {"schema_version", "metadata", "devices", "links", "unresolved"}
    assert t["metadata"] == {
        "image": "diagram.png",
        "width": 800,
        "height": 400,
        "pipeline_version": t["metadata"]["pipeline_version"],
        "source": "fusion.json",
    }
    d = t["devices"][0]
    assert set(d["network"]) == {
        "ip_address",
        "prefix_length",
        "subnet_mask",
        "network_address",
        "host_suffix",
    }
    assert set(d["confidence"]) == {"device_detection", "name", "network_information", "overall"}
    assert "bbox" not in d  # the topology describes the network, not pixels


def test_validation_catches_inconsistent_arithmetic():
    t = _good()
    t["devices"][0]["network"]["subnet_mask"] = "255.255.0.0"
    with pytest.raises(TopologyValidationError, match="does not match prefix"):
        validate_topology(t)
    t = _good()
    t["devices"][0]["network"]["network_address"] = "192.168.2.0"
    with pytest.raises(TopologyValidationError, match="network_address"):
        validate_topology(t)


def test_validation_rejects_ip_without_provenance_and_dangling_links():
    t = _good()
    t["devices"][0]["addresses"][0]["provenance"] = {}
    with pytest.raises(TopologyValidationError, match="without provenance"):
        validate_topology(t)
    t = _good()
    t["links"].append(
        {
            "id": "link_001",
            "source": "device_999",
            "target": None,
            "network": {"network_address": None, "prefix_length": None, "subnet_mask": None},
        }
    )
    with pytest.raises(TopologyValidationError, match="not a device"):
        validate_topology(t)


def test_topology_builder_needs_a_graph():
    with pytest.raises(TopologyValidationError):
        TopologyBuilder().build({"image": {"path": "x.png", "width": 1, "height": 1}})


def test_unclassified_text_stays_out_of_topology_but_in_fusion():
    y = h.yolo([("router", (100, 100, 180, 180))])
    res, topo = h.run(y, h.ocr([("Figure 1: lab", (10, 300, 200, 320))]), h.opencv())
    assert topo["unresolved"] == []
    assert any(u["kind"] == "text" for u in res.to_document()["unresolved"])
