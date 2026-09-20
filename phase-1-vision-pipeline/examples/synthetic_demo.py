"""Runnable demo that needs neither YOLO weights nor PaddleOCR.

Draws a small diagram (R1 --- SW1 --- PC1, network labels on the cables, abbreviated host
suffixes at the cable ends), then runs the REAL OpenCV stage, Fusion Engine and Topology
Builder. YOLO and OCR are replaced by stand-ins that report the drawn ground truth.

    python -m examples.synthetic_demo            # writes outputs/demo/*.json and demo_diagram.png
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
from vision_pipeline.config.settings import Settings
from vision_pipeline.geometry import Rect
from vision_pipeline.pipeline import Pipeline
from vision_pipeline.schemas.raw import ImageInfo, OcrText, RawOcr, RawYolo, YoloDetection

W, H = 900, 400
FONT = cv2.FONT_HERSHEY_SIMPLEX


def _text(img: np.ndarray, s: str, origin: tuple[int, int], scale: float = 0.55) -> Rect:
    cv2.putText(img, s, origin, FONT, scale, (0, 0, 0), 1, cv2.LINE_AA)
    (w, h), base = cv2.getTextSize(s, FONT, scale, 1)
    return Rect(origin[0], origin[1] - h, origin[0] + w, origin[1] + base)


def build(out_dir: Path):
    """Returns (image_path, fake_yolo, fake_ocr)."""
    img = np.full((H, W, 3), 255, np.uint8)
    devs = {
        "router": Rect(60, 140, 140, 220),
        "switch": Rect(400, 140, 480, 220),
        "pc": Rect(760, 140, 840, 220),
    }
    dets = []
    for i, (cls, r) in enumerate(devs.items(), start=1):
        cv2.rectangle(img, (int(r.x1), int(r.y1)), (int(r.x2), int(r.y2)), (0, 0, 0), 2)
        cv2.circle(img, (int(r.center[0]), int(r.center[1])), 22, (0, 0, 0), 2)
        dets.append(YoloDetection(f"device_{i:03d}", cls, 0.96, r))
    cv2.line(img, (140, 180), (400, 180), (0, 0, 0), 3)
    cv2.line(img, (480, 180), (760, 180), (0, 0, 0), 3)
    labels = [
        ("R1", (86, 250)),
        ("SW1", (426, 250)),
        ("PC1", (786, 250)),
        ("192.168.1.0/24", (170, 165)),
        ("10.0.0.0/30", (540, 165)),
        (".1", (146, 165)),
        (".2", (376, 165)),
        (".1", (486, 165)),
        (".2", (738, 165)),
    ]
    texts = [(s, _text(img, s, xy)) for s, xy in labels]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "demo_diagram.png"
    cv2.imwrite(str(path), img)

    info = ImageInfo(str(path), W, H)
    ocr = RawOcr(
        info, [OcrText(f"text_{i:03d}", s, 0.97, b) for i, (s, b) in enumerate(texts, start=1)]
    )
    yolo = RawYolo(info, dets)

    class StandInYolo:
        def detect(self, image_path):
            return yolo

    class StandInOcr:
        def detect(self, image_path):
            return ocr

    return path, StandInYolo(), StandInOcr()


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("outputs") / "demo"
    path, yolo, ocr = build(out)
    topology = Pipeline(Settings(), yolo_detector=yolo, ocr_detector=ocr).run(path, out)
    print(json.dumps(topology, indent=2)[:3000], "\n... full files in", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
