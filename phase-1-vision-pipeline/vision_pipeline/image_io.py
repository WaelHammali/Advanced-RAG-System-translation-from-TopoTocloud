"""Single place where the input image is read, so YOLO, OCR and OpenCV all see the same pixels
and therefore the same width/height/coordinate system."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .schemas.raw import ImageInfo


def load_image_bgr(path: str | Path) -> np.ndarray:
    """Read an image as 3-channel BGR uint8. Transparent pixels are composited on white
    (diagrams exported with a transparent background would otherwise turn black)."""
    import cv2

    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"input image not found: {p}")
    img = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"could not decode image: {p}")
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.dtype != np.uint8:
        img = cv2.convertScaleAbs(img, alpha=255.0 / max(float(img.max()), 1.0))
    if img.shape[2] == 4:
        alpha = img[:, :, 3:4].astype(np.float32) / 255.0
        rgb = img[:, :, :3].astype(np.float32)
        img = (rgb * alpha + 255.0 * (1.0 - alpha)).astype(np.uint8)
    return np.ascontiguousarray(img[:, :, :3])


def image_info(path: str | Path, image: np.ndarray) -> ImageInfo:
    h, w = image.shape[:2]
    return ImageInfo(path=str(path), width=int(w), height=int(h))
