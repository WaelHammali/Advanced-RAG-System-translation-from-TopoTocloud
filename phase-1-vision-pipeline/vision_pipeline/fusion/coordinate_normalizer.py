"""Pass 1 - coordinate normalisation.

The detectors are required to write ORIGINAL-image coordinates (see ``schemas.raw``). This
pass does not rescale anything - guessing a scale factor would be inventing data. It
verifies that the three documents describe the same image, and clips boxes that stick out of
it, reporting every deviation as a warning.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config.thresholds import Thresholds
from ..geometry import Rect
from ..schemas.raw import (
    ImageInfo,
    LinkCandidate,
    OcrText,
    RawOcr,
    RawOpenCV,
    RawYolo,
    YoloDetection,
)


class CoordinateMismatchError(ValueError):
    """The raw documents do not share one image coordinate system."""


@dataclass
class NormalizedInputs:
    image: ImageInfo
    devices: list[YoloDetection]
    texts: list[OcrText]
    candidates: list[LinkCandidate]
    warnings: list[dict] = field(default_factory=list)


def normalize_coordinates(
    yolo: RawYolo, ocr: RawOcr, cv: RawOpenCV, thresholds: Thresholds
) -> NormalizedInputs:
    sizes = {
        "raw_yolo": (yolo.image.width, yolo.image.height),
        "raw_ocr": (ocr.image.width, ocr.image.height),
        "raw_opencv": (cv.image.width, cv.image.height),
    }
    if len(set(sizes.values())) != 1:
        raise CoordinateMismatchError(
            "raw documents disagree on the image size (width, height): "
            + ", ".join(f"{k}={v}" for k, v in sizes.items())
            + ". Every detector must report ORIGINAL-image coordinates for the same image."
        )
    image = yolo.image
    w, h = image.width, image.height
    tol = thresholds.bbox_out_of_bounds_tolerance_px
    warnings: list[dict] = []

    def fit(box: Rect, kind: str, ident: str) -> Rect | None:
        clipped = box.clip(w, h)
        overshoot = max(-box.x1, -box.y1, box.x2 - w, box.y2 - h)
        if overshoot > tol:
            warnings.append(
                {
                    "code": "bbox_outside_image",
                    "kind": kind,
                    "id": ident,
                    "overshoot_px": round(overshoot, 2),
                }
            )
        if clipped.w <= 0 or clipped.h <= 0:
            warnings.append({"code": "bbox_empty_after_clip", "kind": kind, "id": ident})
            return None
        return clipped

    devices = []
    for d in yolo.detections:
        b = fit(d.bbox, "device", d.id)
        if b is not None:
            devices.append(YoloDetection(d.id, d.cls, d.confidence, b))
    devices = _deduplicate_devices(devices, thresholds.duplicate_detection_iou, warnings)
    texts = []
    for t in ocr.texts:
        b = fit(t.bbox, "text", t.id)
        if b is not None:
            texts.append(OcrText(t.id, t.text, t.confidence, b, t.polygon))

    def pt_out(p: tuple[float, float] | None) -> bool:
        return p is not None and (p[0] < -tol or p[1] < -tol or p[0] > w + tol or p[1] > h + tol)

    candidates = []
    for c in cv.candidates:
        pts = [p for s in c.segments for p in s]
        if any(pt_out(p) for p in pts):
            warnings.append(
                {"code": "link_geometry_outside_image", "kind": "link_candidate", "id": c.id}
            )
        candidates.append(c)
    return NormalizedInputs(
        image=image, devices=devices, texts=texts, candidates=candidates, warnings=warnings
    )


def _deduplicate_devices(
    devices: list[YoloDetection], iou_threshold: float, warnings: list[dict]
) -> list[YoloDetection]:
    """Collapse near-duplicate detections of one physical device into one.

    Two overlapping YOLO boxes for the same icon (e.g. classified once as "router" and once
    as "switch") would otherwise leave every nearby text association "ambiguous" - the name and
    address end up null on BOTH, even though the diagram clearly names the device. This runs
    before any association, so it fixes the root cause instead of patching around it. The
    higher-confidence detection is kept; the other is never silently discarded without a trace.
    """
    dropped: set[str] = set()
    for d in sorted(devices, key=lambda x: (-x.confidence, x.id)):
        if d.id in dropped:
            continue
        for other in devices:
            if other.id == d.id or other.id in dropped:
                continue
            ov = d.bbox.iou(other.bbox)
            if ov >= iou_threshold:
                dropped.add(other.id)
                warnings.append(
                    {
                        "code": "duplicate_device_detection_dropped",
                        "kind": "device",
                        "id": other.id,
                        "kept_id": d.id,
                        "iou": round(ov, 3),
                    }
                )
    return [d for d in devices if d.id not in dropped]
