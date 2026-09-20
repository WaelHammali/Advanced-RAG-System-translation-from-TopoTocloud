"""Raw line-segment detection: HoughLinesP (primary) and LSD (optional, secondary)."""

from __future__ import annotations

import logging
import math

import cv2
import numpy as np

from ..config.settings import OpenCVSettings
from ..geometry import Seg
from .preprocessing import Prepared

log = logging.getLogger(__name__)


def detect_segments(prep: Prepared, cfg: OpenCVSettings) -> list[Seg]:
    source = prep.ink if cfg.edge_source == "threshold" else prep.edges
    segs = _hough(source, cfg)
    if cfg.use_lsd:
        segs.extend(_lsd(prep, cfg))
    return segs


def _hough(binary: np.ndarray, cfg: OpenCVSettings) -> list[Seg]:
    lines = cv2.HoughLinesP(
        binary,
        cfg.hough_rho,
        math.radians(cfg.hough_theta_deg),
        cfg.hough_threshold,
        minLineLength=cfg.hough_min_line_length,
        maxLineGap=cfg.hough_max_line_gap,
    )
    if lines is None:
        return []
    return [
        ((float(x1), float(y1)), (float(x2), float(y2))) for x1, y1, x2, y2 in lines.reshape(-1, 4)
    ]


def _lsd(prep: Prepared, cfg: OpenCVSettings) -> list[Seg]:
    try:
        lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
    except (AttributeError, cv2.error):  # LSD is missing from some OpenCV builds
        log.warning("LSD requested but unavailable in this OpenCV build; skipping")
        return []
    lines = lsd.detect(prep.gray)[0]
    if lines is None:
        return []
    out = []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        cx, cy = int(round((x1 + x2) / 2)), int(round((y1 + y2) / 2))
        h, w = prep.mask_map.shape
        if 0 <= cy < h and 0 <= cx < w and prep.mask_map[cy, cx] > 0:
            continue  # LSD runs on the gray image, so re-apply the masks
        out.append(((float(x1), float(y1)), (float(x2), float(y2))))
    return out
