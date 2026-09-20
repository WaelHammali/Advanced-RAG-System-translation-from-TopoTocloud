"""Standardised raw-detector schemas.

These three documents are the ONLY contract between the detectors and the fusion layer. Any
detector (YOLO, PaddleOCR, Hough) can be replaced by anything that writes the same JSON.

All coordinates are pixels in the ORIGINAL input image. Every document carries the same
``image`` block so the fusion engine can verify that the three producers agree.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..geometry import Point, Rect, Seg

SCHEMA_VERSION = "1.0"


class SchemaError(ValueError):
    """A raw document does not follow the standard schema."""


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise SchemaError(f"{where}: missing required key {key!r}")
    return d[key]


def _pt(value: Any, where: str) -> Point:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise SchemaError(f"{where}: expected [x, y], got {value!r}")
    return (float(value[0]), float(value[1]))


def _r(v: float) -> float:
    return round(float(v), 2)


# ------------------------------------------------------------------------------- image


@dataclass(frozen=True)
class ImageInfo:
    path: str
    width: int
    height: int

    @classmethod
    def from_dict(cls, d: dict[str, Any], where: str) -> ImageInfo:
        try:
            w, h = int(_need(d, "width", where)), int(_need(d, "height", where))
        except (TypeError, ValueError) as exc:
            raise SchemaError(f"{where}: width/height must be integers") from exc
        if w <= 0 or h <= 0:
            raise SchemaError(f"{where}: width/height must be positive")
        return cls(path=str(d.get("path", "")), width=w, height=h)

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "width": self.width, "height": self.height}


# ------------------------------------------------------------------------------- YOLO


@dataclass
class YoloDetection:
    id: str
    cls: str
    confidence: float
    bbox: Rect

    @property
    def center(self) -> Point:
        return self.bbox.center

    def to_dict(self) -> dict[str, Any]:
        cx, cy = self.bbox.center
        return {
            "id": self.id,
            "class": self.cls,
            "confidence": round(self.confidence, 4),
            "bbox": self.bbox.to_list(),
            "center": [_r(cx), _r(cy)],
        }


@dataclass
class RawYolo:
    image: ImageInfo
    detections: list[YoloDetection]
    producer: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RawYolo:
        image = ImageInfo.from_dict(_need(d, "image", "raw_yolo"), "raw_yolo.image")
        dets = []
        for i, item in enumerate(_need(d, "detections", "raw_yolo")):
            where = f"raw_yolo.detections[{i}]"
            conf = float(_need(item, "confidence", where))
            dets.append(
                YoloDetection(
                    id=str(_need(item, "id", where)),
                    cls=str(_need(item, "class", where)),
                    confidence=conf,
                    bbox=Rect.from_list(_need(item, "bbox", where)),
                )
            )
        _unique([x.id for x in dets], "raw_yolo detection")
        return cls(image=image, detections=dets, producer=dict(d.get("producer", {})))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "coordinate_system": "original_image_pixels",
            "image": self.image.to_dict(),
            "producer": self.producer,
            "class_names": self.producer.get("class_names", []),
            "detections": [x.to_dict() for x in self.detections],
        }


# -------------------------------------------------------------------------------- OCR


@dataclass
class OcrText:
    id: str
    text: str
    confidence: float
    bbox: Rect
    polygon: list[Point] | None = None

    @property
    def center(self) -> Point:
        return self.bbox.center

    def to_dict(self) -> dict[str, Any]:
        cx, cy = self.bbox.center
        out: dict[str, Any] = {
            "id": self.id,
            "text": self.text,
            "confidence": round(self.confidence, 4),
            "bbox": self.bbox.to_list(),
            "center": [_r(cx), _r(cy)],
        }
        out["polygon"] = [[_r(x), _r(y)] for x, y in self.polygon] if self.polygon else None
        return out


@dataclass
class RawOcr:
    image: ImageInfo
    texts: list[OcrText]
    producer: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RawOcr:
        image = ImageInfo.from_dict(_need(d, "image", "raw_ocr"), "raw_ocr.image")
        texts = []
        for i, item in enumerate(_need(d, "texts", "raw_ocr")):
            where = f"raw_ocr.texts[{i}]"
            poly = item.get("polygon")
            polygon = [_pt(p, where) for p in poly] if poly else None
            bbox = (
                Rect.from_list(item["bbox"])
                if "bbox" in item
                else (Rect.from_points(polygon) if polygon else None)
            )
            if bbox is None:
                raise SchemaError(f"{where}: needs 'bbox' or 'polygon'")
            texts.append(
                OcrText(
                    id=str(_need(item, "id", where)),
                    text=str(_need(item, "text", where)),
                    confidence=float(_need(item, "confidence", where)),
                    bbox=bbox,
                    polygon=polygon,
                )
            )
        _unique([t.id for t in texts], "raw_ocr text")
        return cls(image=image, texts=texts, producer=dict(d.get("producer", {})))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "coordinate_system": "original_image_pixels",
            "image": self.image.to_dict(),
            "producer": self.producer,
            "texts": [t.to_dict() for t in self.texts],
        }


# ----------------------------------------------------------------------------- OpenCV


@dataclass
class LinkCandidate:
    id: str
    segments: list[Seg]
    polyline: list[Point]
    #: "chain" (two open ends), "branched", "cycle" or "single"
    path_type: str
    start: Point | None
    end: Point | None
    endpoints: list[Point]
    confidence: float
    quality: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        def p(v: Point | None) -> list[float] | None:
            return None if v is None else [_r(v[0]), _r(v[1])]

        return {
            "id": self.id,
            "segments": [{"p1": p(s[0]), "p2": p(s[1])} for s in self.segments],
            "polyline": [p(q) for q in self.polyline],
            "path_type": self.path_type,
            "start": p(self.start),
            "end": p(self.end),
            "endpoints": [p(q) for q in self.endpoints],
            "confidence": round(self.confidence, 4),
            "quality": self.quality,
        }


@dataclass
class RawOpenCV:
    image: ImageInfo
    candidates: list[LinkCandidate]
    producer: dict[str, Any] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RawOpenCV:
        image = ImageInfo.from_dict(_need(d, "image", "raw_opencv"), "raw_opencv.image")
        cands = []
        for i, item in enumerate(_need(d, "link_candidates", "raw_opencv")):
            where = f"raw_opencv.link_candidates[{i}]"
            segs: list[Seg] = []
            for j, s in enumerate(_need(item, "segments", where)):
                segs.append(
                    (
                        _pt(_need(s, "p1", f"{where}.segments[{j}]"), where),
                        _pt(_need(s, "p2", f"{where}.segments[{j}]"), where),
                    )
                )
            start = item.get("start")
            end = item.get("end")
            cands.append(
                LinkCandidate(
                    id=str(_need(item, "id", where)),
                    segments=segs,
                    polyline=[_pt(q, where) for q in item.get("polyline", [])],
                    path_type=str(item.get("path_type", "chain")),
                    start=None if start is None else _pt(start, where),
                    end=None if end is None else _pt(end, where),
                    endpoints=[_pt(q, where) for q in item.get("endpoints", [])],
                    confidence=float(_need(item, "confidence", where)),
                    quality=dict(item.get("quality", {})),
                )
            )
        _unique([c.id for c in cands], "raw_opencv link candidate")
        return cls(
            image=image,
            candidates=cands,
            producer=dict(d.get("producer", {})),
            stats=dict(d.get("stats", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "coordinate_system": "original_image_pixels",
            "image": self.image.to_dict(),
            "producer": self.producer,
            "stats": self.stats,
            "link_candidates": [c.to_dict() for c in self.candidates],
        }


# ---------------------------------------------------------------------------------- io


def _unique(ids: list[str], what: str) -> None:
    seen: set[str] = set()
    for i in ids:
        if i in seen:
            raise SchemaError(f"duplicate {what} id {i!r}")
        seen.add(i)


def write_json(path: str | Path, data: dict[str, Any]) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
