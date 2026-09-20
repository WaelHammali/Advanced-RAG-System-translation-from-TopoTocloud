"""Builders for hand-made raw documents, so fusion tests do not need YOLO/PaddleOCR/OpenCV."""

from __future__ import annotations

from typing import Any

from vision_pipeline.fusion.fusion_engine import FusionEngine, FusionResult
from vision_pipeline.geometry import Rect
from vision_pipeline.schemas.raw import (
    ImageInfo,
    LinkCandidate,
    OcrText,
    RawOcr,
    RawOpenCV,
    RawYolo,
    YoloDetection,
)
from vision_pipeline.topology.graph_builder import build_graph
from vision_pipeline.topology.topology_builder import TopologyBuilder

W, H = 800, 400
IMAGE = ImageInfo("diagram.png", W, H)


def yolo(
    devices: list[tuple[str, tuple[float, float, float, float]]], conf: float = 0.95
) -> RawYolo:
    dets = [
        YoloDetection(f"device_{i:03d}", cls, conf, Rect.from_list(box))
        for i, (cls, box) in enumerate(devices, start=1)
    ]
    return RawYolo(IMAGE, dets)


def ocr(texts: list[tuple[str, tuple[float, float, float, float]]], conf: float = 0.95) -> RawOcr:
    return RawOcr(
        IMAGE,
        [
            OcrText(f"text_{i:03d}", t, conf, Rect.from_list(box))
            for i, (t, box) in enumerate(texts, start=1)
        ],
    )


def link(
    polyline: list[tuple[float, float]],
    conf: float = 0.9,
    cid: str | None = None,
    path_type: str = "chain",
) -> LinkCandidate:
    segs = list(zip(polyline[:-1], polyline[1:]))
    return LinkCandidate(
        cid or "link_candidate_001",
        segs,
        list(polyline),
        path_type,
        polyline[0],
        polyline[-1],
        [polyline[0], polyline[-1]],
        conf,
    )


def opencv(links: list[LinkCandidate] | None = None) -> RawOpenCV:
    links = links or []
    for i, lk in enumerate(links, start=1):
        if lk.id == "link_candidate_001" and i > 1:
            lk.id = f"link_candidate_{i:03d}"
    return RawOpenCV(IMAGE, links)


def run(y: RawYolo, o: RawOcr, c: RawOpenCV, **kw: Any) -> tuple[FusionResult, dict[str, Any]]:
    result = FusionEngine(graph_builder=build_graph, **kw).run(y, o, c)
    doc = result.to_document()
    return result, TopologyBuilder().build(doc)


def device(topo: dict[str, Any], dev_id: str) -> dict[str, Any]:
    return next(d for d in topo["devices"] if d["id"] == dev_id)
