"""YOLO device detection.

Responsibility: find network devices. Nothing else - no OCR, no IP parsing, no links.

Class names are read from the loaded model (``model.names``); no class list is hard-coded.
Ultralytics returns boxes in the coordinate system of the array it was given, i.e. the
ORIGINAL image, regardless of the internal ``imgsz`` letterboxing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..config.settings import YoloSettings
from ..geometry import Rect, reading_order_key
from ..image_io import image_info, load_image_bgr
from ..schemas.raw import RawYolo, YoloDetection


class WeightsNotFoundError(FileNotFoundError):
    pass


def _to_numpy(x: Any) -> np.ndarray:
    if hasattr(x, "cpu"):
        x = x.cpu()
    if hasattr(x, "numpy"):
        x = x.numpy()
    return np.asarray(x)


def results_to_detections(result: Any, names: dict[int, str] | list[str]) -> list[YoloDetection]:
    """Convert one ultralytics ``Results`` object into unnumbered detections (ids assigned later)."""
    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return []
    xyxy = _to_numpy(boxes.xyxy).reshape(-1, 4)
    conf = _to_numpy(boxes.conf).reshape(-1)
    cls = _to_numpy(boxes.cls).reshape(-1).astype(int)
    name_of = (lambda i: names[i]) if isinstance(names, dict) else (lambda i: names[i])
    out = []
    for (x1, y1, x2, y2), c, k in zip(xyxy, conf, cls):
        out.append(
            YoloDetection(
                id="",
                cls=str(name_of(int(k))),
                confidence=float(c),
                bbox=Rect(float(x1), float(y1), float(x2), float(y2)),
            )
        )
    return out


def assign_ids(dets: list[YoloDetection]) -> list[YoloDetection]:
    """Deterministic ``device_001``... ids in reading order (top-to-bottom, left-to-right)."""
    order = reading_order_key([(str(i), d.bbox) for i, d in enumerate(dets)])
    out = []
    for n, key in enumerate(order, start=1):
        d = dets[int(key)]
        out.append(
            YoloDetection(id=f"device_{n:03d}", cls=d.cls, confidence=d.confidence, bbox=d.bbox)
        )
    return out


class YoloDetector:
    def __init__(self, settings: YoloSettings, model: Any | None = None) -> None:
        self.settings = settings
        self._model = model  # injectable for tests / alternative back-ends

    def load(self) -> Any:
        if self._model is not None:
            return self._model
        weights = Path(self.settings.weights_path)
        if not weights.is_file():
            raise WeightsNotFoundError(
                f"YOLO weights not found at {weights}. Put your trained weights there, or set "
                f"--weights / env TOPOFORGE_YOLO_WEIGHTS / yolo.weights_path in the config file."
            )
        try:
            from ultralytics import YOLO
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise RuntimeError("ultralytics is not installed (pip install ultralytics)") from exc
        self._model = YOLO(str(weights))
        return self._model

    @property
    def class_names(self) -> list[str]:
        names = self.load().names
        return [names[i] for i in sorted(names)] if isinstance(names, dict) else list(names)

    def detect(self, image_path: str | Path) -> RawYolo:
        image = load_image_bgr(image_path)
        return self.detect_array(image, image_info(image_path, image))

    def detect_array(self, image: np.ndarray, info) -> RawYolo:
        model = self.load()
        s = self.settings
        kwargs: dict[str, Any] = dict(
            conf=s.confidence,
            iou=s.iou,
            imgsz=s.image_size,
            max_det=s.max_detections,
            verbose=False,
        )
        if s.device:
            kwargs["device"] = s.device
        results = model.predict(source=image, **kwargs)
        dets = results_to_detections(results[0], model.names) if len(results) else []
        h, w = image.shape[:2]
        dets = [
            YoloDetection(id="", cls=d.cls, confidence=d.confidence, bbox=d.bbox.clip(w, h))
            for d in dets
        ]
        dets = [d for d in dets if d.bbox.w > 0 and d.bbox.h > 0]
        return RawYolo(
            image=info,
            detections=assign_ids(dets),
            producer={
                "name": "ultralytics-yolo",
                "weights": str(self.settings.weights_path),
                "class_names": self.class_names,
                "confidence_floor": s.confidence,
                "iou": s.iou,
                "image_size": s.image_size,
            },
        )
