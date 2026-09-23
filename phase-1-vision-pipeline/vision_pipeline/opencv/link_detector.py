"""OpenCV link detection: image -> logical cable candidates (``raw_opencv.json``).

Pipeline::

    preprocess (gray, polarity, optional device/text masks, Canny)
      -> HoughLinesP (+ optional LSD)
      -> drop fragments lying fully inside a device (icon outlines)
      -> merge collinear fragments (bridging masked text)
      -> length filter
      -> path reconstruction (junctions / T-junctions, device barriers)
      -> geometric confidence
      -> map back to ORIGINAL coordinates

This module knows nothing about topology: it reports cable-shaped geometry with honest
endpoints (``None`` when an endpoint cannot be determined) and a geometric quality score.
"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

from ..config.settings import OpenCVSettings
from ..geometry import Rect, Seg, clamp01, reading_order_key, seg_length
from ..image_io import image_info, load_image_bgr
from ..schemas.raw import ImageInfo, LinkCandidate, RawOpenCV
from .line_detector import detect_segments
from .path_reconstructor import PathCandidate, reconstruct_paths
from .preprocessing import MaskRegions, Prepared, prepare
from .segment_merger import merge_collinear


class LinkDetector:
    def __init__(self, settings: OpenCVSettings) -> None:
        self.cfg = settings

    def detect(self, image_path: str | Path, regions: MaskRegions | None = None) -> RawOpenCV:
        image = load_image_bgr(image_path)
        return self.detect_array(image, image_info(image_path, image), regions)

    def detect_array(
        self, image: np.ndarray, info: ImageInfo, regions: MaskRegions | None = None
    ) -> RawOpenCV:
        cfg = self.cfg
        prep = prepare(image, cfg, regions)
        s = prep.scale
        stats: dict[str, int | float] = {}

        raw = detect_segments(prep, cfg)
        stats["raw_segments"] = len(raw)

        if cfg.drop_segments_inside_devices and prep.device_rects:
            raw = _drop_inside(raw, prep.device_rects, cfg.inside_device_tolerance_px)
        stats["after_inside_device_filter"] = len(raw)

        if cfg.max_segments_for_merge and len(raw) > cfg.max_segments_for_merge:
            # merge_collinear is O(n^2) in memory; an unmasked or very busy image can otherwise
            # exhaust memory (observed ~7GB at ~9,000 segments). Keep the longest segments -
            # real cables are long, incidental noise is short - and say so, never silently.
            stats["segments_dropped_scale_cap"] = len(raw) - cfg.max_segments_for_merge
            raw = sorted(raw, key=seg_length, reverse=True)[: cfg.max_segments_for_merge]

        merged = merge_collinear(
            raw,
            angle_tol_deg=cfg.merge_angle_tol_deg,
            perp_tol_px=cfg.merge_perp_tol_px,
            gap_tol_px=cfg.merge_gap_tol_px,
            bridge_rects=prep.text_rects if cfg.mask_text else (),
            bridge_coverage=cfg.bridge_coverage,
            max_bridge_px=cfg.max_bridge_px,
        )
        merged = [m for m in merged if seg_length(m) >= cfg.min_segment_length_px]
        if cfg.drop_segments_inside_devices and prep.device_rects:
            merged = _drop_inside(merged, prep.device_rects, cfg.inside_device_tolerance_px)
        stats["merged_segments"] = len(merged)

        barriers = (
            [r.expand(cfg.barrier_margin_px) for r in prep.device_rects]
            if cfg.respect_device_barriers
            else []
        )
        paths, dropped = reconstruct_paths(
            merged,
            join_dist=cfg.join_dist_px,
            barriers=barriers,
            min_path_length=cfg.min_path_length_px,
            max_spur_px=cfg.prune_spur_max_px,
        )
        stats["paths"] = len(paths)
        stats["paths_dropped_too_short"] = dropped
        stats["paths_recovered_from_spur_pruning"] = sum(1 for p in paths if p.pruned_spur_count)

        h, w = image.shape[:2]
        diag = math.hypot(w, h) * s
        ink_dilated = _dilate(prep.ink, cfg.ink_dilate_px)
        scored = [(p, *_quality(p, prep, ink_dilated, cfg, diag)) for p in paths]

        inv = 1.0 / s
        cands = [self._to_candidate(p, conf, q, inv) for p, conf, q in scored]
        order = reading_order_key([(str(i), _bounds(c)) for i, c in enumerate(cands)])
        final = []
        for n, key in enumerate(order, start=1):
            c = cands[int(key)]
            c.id = f"link_candidate_{n:03d}"
            final.append(c)

        producer = {
            "name": "opencv-hough",
            "edge_source": cfg.edge_source,
            "lsd": cfg.use_lsd,
            "masked_devices": bool(cfg.mask_devices and prep.device_rects),
            "masked_text": bool(cfg.mask_text and prep.text_rects),
            "working_scale": round(s, 6),
            "inverted_polarity": prep.inverted_polarity,
        }
        return RawOpenCV(image=info, candidates=final, producer=producer, stats=stats)

    @staticmethod
    def _to_candidate(p: PathCandidate, conf: float, quality: dict, inv: float) -> LinkCandidate:
        def up(pt):
            return None if pt is None else (pt[0] * inv, pt[1] * inv)

        return LinkCandidate(
            id="",
            segments=[(up(a), up(b)) for a, b in p.segments],
            polyline=[up(q) for q in p.polyline],
            path_type=p.path_type,
            start=up(p.start),
            end=up(p.end),
            endpoints=[up(q) for q in p.endpoints],
            confidence=conf,
            quality={
                **quality,
                "length_px": round(quality["length_px"] * inv, 2),
                "pruned_length_px": round(quality["pruned_length_px"] * inv, 2),
            },
        )


# ------------------------------------------------------------------------------ helpers


def regions_from_raw(devices: list[Rect], texts: list[Rect]) -> MaskRegions:
    return MaskRegions(device_boxes=list(devices), text_boxes=list(texts))


def _dilate(binary: np.ndarray, px: int) -> np.ndarray:
    if px <= 0:
        return binary
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (2 * px + 1, 2 * px + 1))
    return cv2.dilate(binary, k)


def _drop_inside(segs: list[Seg], rects: list[Rect], tol: float) -> list[Seg]:
    out = []
    for s in segs:
        box = Rect.from_points(s)
        if any(r.contains_rect(box, tol=tol) for r in rects):
            continue
        out.append(s)
    return out


def _bounds(c: LinkCandidate) -> Rect:
    pts = [p for seg in c.segments for p in seg]
    return Rect.from_points(pts)


def _quality(
    path: PathCandidate, prep: Prepared, ink_dilated: np.ndarray, cfg: OpenCVSettings, diag: float
) -> tuple[float, dict]:
    """Geometric confidence in [0, 1] and its components (working-scale pixels)."""
    h, w = ink_dilated.shape
    total = unmasked = hits = 0
    for a, b in path.segments:
        n = max(2, int(seg_length((a, b)) / cfg.ink_sample_step_px))
        xs = np.rint(np.linspace(a[0], b[0], n + 1)).astype(int)
        ys = np.rint(np.linspace(a[1], b[1], n + 1)).astype(int)
        inb = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
        xs, ys = xs[inb], ys[inb]
        total += len(xs)
        free = prep.mask_map[ys, xs] == 0
        unmasked += int(free.sum())
        hits += int((ink_dilated[ys, xs][free] > 0).sum())
    ink_support = hits / unmasked if unmasked else 0.0
    observed = unmasked / total if total else 0.0
    length = path.length
    length_score = clamp01(length / max(cfg.good_length_fraction * diag, 1.0))
    endpoint_score = (
        1.0 if path.start is not None and path.end is not None else cfg.undetermined_endpoints_score
    )
    conf = clamp01(
        cfg.weight_ink_support * ink_support
        + cfg.weight_length * length_score
        + cfg.weight_coverage * observed
        + cfg.weight_endpoints * endpoint_score
    )
    if path.pruned_spur_count:
        # this chain only exists because one or more short, junction-forming spurs (icon-detail
        # noise) were discarded - be less confident about it than an already-clean chain
        conf = clamp01(conf * cfg.spur_pruned_confidence_factor)
    return conf, {
        "ink_support": round(ink_support, 4),
        "observed_fraction": round(observed, 4),
        "length_score": round(length_score, 4),
        "endpoint_score": round(endpoint_score, 4),
        "length_px": length,
        "pruned_spur_count": path.pruned_spur_count,
        "pruned_length_px": round(path.pruned_length_px, 2),
    }
