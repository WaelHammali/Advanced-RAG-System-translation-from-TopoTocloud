"""Image preprocessing for link detection: grayscale, polarity, optional masking, edges.

Masking is OPTIONAL and driven by plain rectangles (so it does not depend on YOLO/OCR code):

* device interiors are erased but a border ring is kept (``device_ring_ratio``), so cables
  that reach a device still end near its outline;
* OCR text boxes are erased (with a small pad) so glyph strokes do not become "lines".

Everything here works at the *working scale*; the caller maps results back to original
coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from ..config.settings import OpenCVSettings
from ..geometry import Rect


@dataclass
class MaskRegions:
    """Rectangles in ORIGINAL image coordinates."""

    device_boxes: list[Rect] = field(default_factory=list)
    text_boxes: list[Rect] = field(default_factory=list)


@dataclass
class Prepared:
    gray: np.ndarray  # dark-ink-on-light polarity, masks filled with background
    ink: np.ndarray  # uint8, 255 where ink (after masking)
    edges: np.ndarray  # Canny edges (after masking)
    mask_map: np.ndarray  # uint8, 255 where pixels were erased by a mask
    scale: float  # working / original
    device_rects: list[Rect]  # working-scale device boxes (unshrunk)
    text_rects: list[Rect]  # working-scale, padded text boxes
    inverted_polarity: bool


def _scaled(r: Rect, s: float) -> Rect:
    return Rect(r.x1 * s, r.y1 * s, r.x2 * s, r.y2 * s)


def _fill(img: np.ndarray, r: Rect, value: int) -> None:
    h, w = img.shape[:2]
    x1, y1 = max(0, int(np.floor(r.x1))), max(0, int(np.floor(r.y1)))
    x2, y2 = min(w, int(np.ceil(r.x2))), min(h, int(np.ceil(r.y2)))
    if x2 > x1 and y2 > y1:
        img[y1:y2, x1:x2] = value


def prepare(
    image_bgr: np.ndarray, cfg: OpenCVSettings, regions: MaskRegions | None = None
) -> Prepared:
    regions = regions or MaskRegions()
    h, w = image_bgr.shape[:2]
    scale = 1.0
    if cfg.working_max_side and max(h, w) > cfg.working_max_side:
        scale = cfg.working_max_side / float(max(h, w))
        image_bgr = cv2.resize(image_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    inverted = bool(np.median(gray) < 110)  # light lines on dark background -> flip
    if inverted:
        gray = 255 - gray
    background = int(np.median(gray))
    k = cfg.blur_kernel | 1  # must be odd
    blurred = cv2.GaussianBlur(gray, (k, k), 0) if cfg.blur_kernel > 1 else gray.copy()

    mask_map = np.zeros_like(gray)
    device_rects = [_scaled(r, scale) for r in regions.device_boxes]
    text_rects = [_scaled(r, scale).expand(cfg.text_mask_pad_px) for r in regions.text_boxes]

    if cfg.mask_devices:
        for r in device_rects:
            inner = r.shrink_ratio(cfg.device_ring_ratio, cfg.device_ring_min_px)
            if inner is not None:
                _fill(mask_map, inner, 255)
    if cfg.mask_text:
        for r in text_rects:
            _fill(mask_map, r, 255)

    blurred[mask_map > 0] = background
    _, ink = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    ink[mask_map > 0] = 0
    edges = cv2.Canny(blurred, cfg.canny_low, cfg.canny_high)
    edges[mask_map > 0] = 0
    return Prepared(
        gray=blurred,
        ink=ink,
        edges=edges,
        mask_map=mask_map,
        scale=scale,
        device_rects=device_rects,
        text_rects=text_rects,
        inverted_polarity=inverted,
    )
