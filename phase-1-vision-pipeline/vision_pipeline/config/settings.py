"""Runtime settings: paths, model parameters, OpenCV parameters.

Precedence (lowest to highest): defaults < config file (YAML/JSON) < environment < CLI.

YOLO weights path: ``settings.yolo.weights_path``; environment ``TOPOFORGE_YOLO_WEIGHTS``;
CLI ``--weights``. Default: ``models/yolo/best.pt`` (relative to the project root).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .thresholds import Thresholds, apply_overrides, to_dict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEIGHTS = PROJECT_ROOT / "models" / "yolo" / "best.pt"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs"

ENV_WEIGHTS = "TOPOFORGE_YOLO_WEIGHTS"
ENV_OUTPUT_DIR = "TOPOFORGE_OUTPUT_DIR"


@dataclass
class YoloSettings:
    weights_path: str = str(DEFAULT_WEIGHTS)
    #: detector-level confidence floor. Kept low: uncertainty is preserved, not discarded.
    confidence: float = 0.25
    iou: float = 0.45
    #: passed to ultralytics; boxes are always mapped back to the original image
    image_size: int = 640
    #: "cpu", "cuda:0", ... ; None lets ultralytics choose
    device: str | None = None
    max_detections: int = 300


@dataclass
class OcrSettings:
    language: str = "en"
    #: OCR results below this are dropped by the detector. 0 keeps everything.
    min_confidence: float = 0.0
    #: image is upscaled by this factor before OCR; boxes are mapped back. 1.0 = off.
    upscale: float = 1.0
    #: extra kwargs forwarded verbatim to the PaddleOCR constructor. oneDNN is off by default:
    #: PaddlePaddle 3.3 crashes on CPU with it ("ConvertPirAttribute2RuntimeAttribute").
    paddle_kwargs: dict[str, Any] = field(default_factory=lambda: {"enable_mkldnn": False})


@dataclass
class OpenCVSettings:
    # -- preprocessing
    #: process at most this many pixels on the long side (0 = original size). Results are
    #: mapped back to original coordinates before being written.
    working_max_side: int = 0
    blur_kernel: int = 3
    #: "canny" (default) or "threshold" (Hough on the ink mask)
    edge_source: str = "canny"
    canny_low: int = 50
    canny_high: int = 150
    # -- masking (optional; needs raw_yolo / raw_ocr as mask sources)
    mask_devices: bool = True
    #: interior of each device bbox is erased, keeping a border ring of this fraction
    device_ring_ratio: float = 0.12
    device_ring_min_px: float = 3.0
    mask_text: bool = True
    text_mask_pad_px: float = 2.0
    # -- Hough
    hough_threshold: int = 40
    hough_min_line_length: int = 25
    hough_max_line_gap: int = 8
    hough_rho: float = 1.0
    hough_theta_deg: float = 1.0
    use_lsd: bool = False
    # -- filtering
    min_segment_length_px: float = 20.0
    #: segments fully inside a device bbox are icon outlines, not cables
    drop_segments_inside_devices: bool = True
    inside_device_tolerance_px: float = 2.0
    #: collinear merging compares every raw segment pair, i.e. O(n^2) memory (~7GB observed at
    #: ~9,000 segments on an unmasked 5000x3500 image). Above this count, only the longest
    #: segments are kept before merging - real cables are long, incidental noise is short - and
    #: the drop is recorded in raw_opencv.json's `stats`, never silent. 0 disables the cap.
    max_segments_for_merge: int = 6000
    # -- collinear merging
    merge_angle_tol_deg: float = 4.0
    merge_perp_tol_px: float = 6.0
    merge_gap_tol_px: float = 20.0
    #: gaps that lie (>= bridge_coverage) inside masked text may be bridged up to this length
    max_bridge_px: float = 400.0
    bridge_coverage: float = 0.8
    # -- path reconstruction
    join_dist_px: float = 10.0
    #: endpoints inside a device region are never joined to other cables
    respect_device_barriers: bool = True
    barrier_margin_px: float = 6.0
    min_path_length_px: float = 30.0
    # -- geometric confidence
    ink_sample_step_px: float = 3.0
    ink_dilate_px: int = 2
    #: length (as a fraction of the image diagonal) at which the length score saturates
    good_length_fraction: float = 0.06
    weight_ink_support: float = 0.40
    weight_length: float = 0.20
    #: share given to the fraction of the path actually observed (not bridged through masks)
    weight_coverage: float = 0.20
    weight_endpoints: float = 0.20
    #: endpoint score for paths whose endpoints cannot be determined (branched / cycle)
    undetermined_endpoints_score: float = 0.30


@dataclass
class Settings:
    yolo: YoloSettings = field(default_factory=YoloSettings)
    ocr: OcrSettings = field(default_factory=OcrSettings)
    opencv: OpenCVSettings = field(default_factory=OpenCVSettings)
    thresholds: Thresholds = field(default_factory=Thresholds)
    output_dir: str = str(DEFAULT_OUTPUT_DIR)
    #: optional regex overriding the built-in device-name pattern
    device_name_pattern: str | None = None
    #: optional regex overriding the built-in link-type/interface ignore list (Ethernet,
    #: GigabitEthernet0/1, Gi0/1, Fa0/0, Vlan10, ...). Matching text is always classified
    #: "unknown": never a device name, never grouped, never in topology.json.
    link_type_pattern: str | None = None
    #: model class -> type name used in the minimal RAG file (topology.simple.json) only.
    #: topology.json keeps the model's own class name.
    device_type_aliases: dict[str, str] = field(default_factory=lambda: {"desktop": "pc"})

    # ---------------------------------------------------------------------- loading
    @classmethod
    def load(
        cls,
        config_file: str | os.PathLike[str] | None = None,
        *,
        weights: str | None = None,
        output_dir: str | None = None,
    ) -> Settings:
        settings = cls()
        if config_file:
            apply_overrides(settings, _read_config(Path(config_file)))
        env_weights = os.environ.get(ENV_WEIGHTS)
        if env_weights:
            settings.yolo.weights_path = env_weights
        env_out = os.environ.get(ENV_OUTPUT_DIR)
        if env_out:
            settings.output_dir = env_out
        if weights:
            settings.yolo.weights_path = weights
        if output_dir:
            settings.output_dir = output_dir
        return settings

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)


def _read_config(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        import yaml  # local import: only needed when a YAML config is used

        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"config file {path} must contain a mapping at the top level")
    return data
