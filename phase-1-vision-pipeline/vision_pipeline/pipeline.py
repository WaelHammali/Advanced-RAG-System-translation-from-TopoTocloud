"""Pipeline orchestration. Contains no algorithms: it wires the modules together.

    image -> YOLO      -> raw_yolo.json  --+
    image -> PaddleOCR -> raw_ocr.json   --+--> Fusion Engine -> fusion.json -> Topology Builder -> topology.json
    image -> OpenCV    -> raw_opencv.json -+     (reads the three JSON files back from disk)

    topology.simple.json (the RAG input) -> validator -> validation.json (what is wrong, where)
                         <- user corrections (correct_file), checked again until valid

OpenCV optionally uses raw_yolo / raw_ocr rectangles as masks, so it runs after them.
Detectors are injectable, so any of them can be replaced by anything implementing the same
``detect_array`` / ``detect`` contract and writing the standard raw schema.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config.settings import Settings
from .fusion.fusion_engine import FusionEngine
from .image_io import load_image_bgr
from .schemas.raw import RawOcr, RawOpenCV, RawYolo, read_json, write_json
from .topology.graph_builder import build_graph
from .topology.topology_builder import TopologyBuilder
from .validation import validate
from .validation.corrections import apply_corrections

log = logging.getLogger("vision_pipeline")

RAW_YOLO, RAW_OCR, RAW_OPENCV = "raw_yolo.json", "raw_ocr.json", "raw_opencv.json"
FUSION, TOPOLOGY, TOPOLOGY_SIMPLE = "fusion.json", "topology.json", "topology.simple.json"
VALIDATION = "validation.json"
#: the minimal form exactly as detected, kept the first time user corrections overwrite it
TOPOLOGY_SIMPLE_DETECTED = "topology.simple.detected.json"


@dataclass
class PipelinePaths:
    raw_yolo: Path
    raw_ocr: Path
    raw_opencv: Path
    fusion: Path
    topology: Path
    topology_simple: Path
    validation: Path


def output_paths(out_dir: str | Path) -> PipelinePaths:
    d = Path(out_dir)
    return PipelinePaths(
        d / RAW_YOLO,
        d / RAW_OCR,
        d / RAW_OPENCV,
        d / FUSION,
        d / TOPOLOGY,
        d / TOPOLOGY_SIMPLE,
        d / VALIDATION,
    )


def clear_outputs(paths: PipelinePaths) -> None:
    """Remove every output file of a previous run before a new one starts.

    Without this, a run that fails partway (bad weights, a crash mid-stage, ...) leaves the
    *previous* successful run's ``topology.json`` sitting there looking like a valid result for
    whatever image is being processed now. Something reading the output directory has no way to
    tell a fresh, complete result from a stale one - so a new attempt must never leave a partial
    or old file set behind: either every file is quantifiably from the same successful run, or
    none of them exist.
    """
    for p in (
        paths.raw_yolo,
        paths.raw_ocr,
        paths.raw_opencv,
        paths.fusion,
        paths.topology,
        paths.topology_simple,
        paths.validation,
        paths.topology_simple.with_name(TOPOLOGY_SIMPLE_DETECTED),
    ):
        p.unlink(missing_ok=True)


class Pipeline:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        yolo_detector: Any | None = None,
        ocr_detector: Any | None = None,
        link_detector: Any | None = None,
    ) -> None:
        self.settings = settings or Settings.load()
        self._yolo, self._ocr, self._links = yolo_detector, ocr_detector, link_detector

    # -------------------------------------------------------------- lazy detector access
    @property
    def yolo(self):
        if self._yolo is None:
            from .yolo.detector import YoloDetector

            self._yolo = YoloDetector(self.settings.yolo)
        return self._yolo

    @property
    def ocr(self):
        if self._ocr is None:
            from .ocr.detector import OcrDetector

            self._ocr = OcrDetector(self.settings.ocr)
        return self._ocr

    @property
    def links(self):
        if self._links is None:
            from .opencv.link_detector import LinkDetector

            self._links = LinkDetector(self.settings.opencv)
        return self._links

    # ------------------------------------------------------------------------ stages
    def run_yolo(self, image_path: str | Path, out: Path) -> RawYolo:
        raw = self.yolo.detect(image_path)
        write_json(out, raw.to_dict())
        log.info("YOLO: %d devices -> %s", len(raw.detections), out)
        return raw

    def run_ocr(self, image_path: str | Path, out: Path) -> RawOcr:
        raw = self.ocr.detect(image_path)
        write_json(out, raw.to_dict())
        log.info("OCR: %d text regions -> %s", len(raw.texts), out)
        return raw

    def run_opencv(
        self,
        image_path: str | Path,
        out: Path,
        raw_yolo: RawYolo | None = None,
        raw_ocr: RawOcr | None = None,
    ) -> RawOpenCV:
        from .opencv.preprocessing import MaskRegions

        cfg = self.settings.opencv
        regions = MaskRegions(
            device_boxes=[d.bbox for d in raw_yolo.detections]
            if raw_yolo and cfg.mask_devices
            else [],
            text_boxes=[t.bbox for t in raw_ocr.texts] if raw_ocr and cfg.mask_text else [],
        )
        raw = self.links.detect(image_path, regions)
        write_json(out, raw.to_dict())
        log.info("OpenCV: %d link candidates -> %s", len(raw.candidates), out)
        return raw

    def fuse(
        self,
        raw_yolo: str | Path,
        raw_ocr: str | Path,
        raw_opencv: str | Path,
        fusion_out: str | Path,
        topology_out: str | Path,
        topology_simple_out: str | Path | None = None,
    ) -> dict[str, Any]:
        """Fusion + Topology Builder from the three raw JSON files (the standard contract).

        Writes topology.json (rich, stored), topology.simple.json (minimal form for the RAG) and
        validation.json (the pre-RAG check of that minimal form). Returns the rich topology."""
        yolo = RawYolo.from_dict(read_json(raw_yolo))
        ocr = RawOcr.from_dict(read_json(raw_ocr))
        cv = RawOpenCV.from_dict(read_json(raw_opencv))
        engine = FusionEngine(
            self.settings.thresholds,
            graph_builder=build_graph,
            device_name_pattern=self.settings.device_name_pattern,
            link_type_pattern=self.settings.link_type_pattern,
        )
        result = engine.run(yolo, ocr, cv)
        fusion_doc = result.to_document()
        write_json(fusion_out, fusion_doc)
        builder = TopologyBuilder(self.settings.device_type_aliases)
        topology = builder.build(fusion_doc)  # the ONLY place topology.json is created
        builder.write(topology, topology_out)
        simple_out = topology_simple_out or Path(topology_out).with_name(TOPOLOGY_SIMPLE)
        simple = builder.build_simple(topology)
        builder.write_simple(simple, simple_out)  # what the RAG receives
        report = validate(simple)
        write_json(Path(simple_out).with_name(VALIDATION), report)
        log.info(
            "Validation: %s (%d errors, %d warnings)",
            report["status"],
            report["summary"]["errors"],
            report["summary"]["warnings"],
        )
        log.info(
            "Fusion -> %s ; Topology -> %s ; RAG input -> %s (%d devices, %d links, %d unresolved)",
            fusion_out,
            topology_out,
            simple_out,
            len(topology["devices"]),
            len(topology["links"]),
            len(topology["unresolved"]),
        )
        return topology

    def validate_file(
        self,
        simple_path: str | Path,
        report_out: str | Path | None = None,
        *,
        require_ipv4: bool = True,
    ) -> dict[str, Any]:
        """Validate an existing topology.simple.json (e.g. after hand edits); optionally write the report."""
        report = validate(read_json(simple_path), require_ipv4=require_ipv4)
        if report_out is not None:
            write_json(report_out, report)
        return report

    def correct_file(
        self,
        simple_path: str | Path,
        corrections: list[dict[str, Any]],
        simple_out: str | Path | None = None,
        report_out: str | Path | None = None,
        *,
        require_ipv4: bool = True,
    ) -> dict[str, Any]:
        """Apply user corrections to topology.simple.json, write it back and re-validate.

        Writes in place unless ``simple_out`` is given; the first time a file is overwritten the
        detected original is kept next to it as topology.simple.detected.json."""
        original = read_json(simple_path)
        result = apply_corrections(original, corrections, require_ipv4=require_ipv4)
        out = Path(simple_out or simple_path)
        detected = out.with_name(TOPOLOGY_SIMPLE_DETECTED)
        if out.resolve() == Path(simple_path).resolve() and not detected.exists():
            write_json(detected, original)
        TopologyBuilder(self.settings.device_type_aliases).write_simple(result["topology"], out)
        write_json(report_out or out.with_name(VALIDATION), result["report"])
        log.info(
            "Corrections: %d applied, %d rejected -> %s ; validation: %s",
            len(result["applied"]),
            len(result["rejected"]),
            out,
            result["report"]["status"],
        )
        return result

    # -------------------------------------------------------------------- full run
    def run(self, image_path: str | Path, output_dir: str | Path | None = None) -> dict[str, Any]:
        paths = output_paths(output_dir or self.settings.output_dir)
        clear_outputs(paths)  # never let a failed run leave a previous run's files behind
        image = load_image_bgr(image_path)  # fail early on a bad image, before loading any model
        log.info("image %s (%dx%d)", image_path, image.shape[1], image.shape[0])
        raw_yolo = self.run_yolo(image_path, paths.raw_yolo)
        raw_ocr = self.run_ocr(image_path, paths.raw_ocr)
        self.run_opencv(image_path, paths.raw_opencv, raw_yolo, raw_ocr)
        return self.fuse(
            paths.raw_yolo,
            paths.raw_ocr,
            paths.raw_opencv,
            paths.fusion,
            paths.topology,
            paths.topology_simple,
        )
