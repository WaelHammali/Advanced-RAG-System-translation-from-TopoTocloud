"""Command line interface.

    python -m vision_pipeline run    --image diagram.png [--weights W] [--output-dir D] [--config C]
    python -m vision_pipeline yolo   --image diagram.png            -> raw_yolo.json
    python -m vision_pipeline ocr    --image diagram.png            -> raw_ocr.json
    python -m vision_pipeline opencv --image diagram.png [--raw-yolo F --raw-ocr F] -> raw_opencv.json
    python -m vision_pipeline fuse   [--raw-yolo F --raw-ocr F --raw-opencv F]      -> fusion.json + topology.json + topology.simple.json
    python -m vision_pipeline validate [--input topology.simple.json] [--allow-ipv6-only]  -> report, exit 1 if invalid
    python -m vision_pipeline correct  --corrections fixes.json|'[...]' [--input F] [--output F]  -> corrected + re-validated
    python -m vision_pipeline print-config

``run`` is the default sub-command, so ``python -m vision_pipeline --image diagram.png`` works.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .config.settings import Settings
from .pipeline import Pipeline, output_paths
from .schemas.raw import RawOcr, RawYolo, read_json

COMMANDS = ("run", "yolo", "ocr", "opencv", "fuse", "validate", "correct", "print-config")


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="vision_pipeline",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser, image: bool = True) -> None:
        if image:
            p.add_argument("--image", required=True, help="input network diagram")
        p.add_argument("--output-dir", help="where the JSON files are written (default: ./outputs)")
        p.add_argument("--config", help="YAML/JSON file overriding settings and thresholds")

    p = sub.add_parser("run", help="full perception pipeline on one image")
    common(p)
    p.add_argument(
        "--weights",
        help="YOLO weights path (default models/yolo/best.pt, env TOPOFORGE_YOLO_WEIGHTS)",
    )
    p.add_argument(
        "--no-mask-devices",
        action="store_true",
        help="do not erase device interiors before line detection",
    )
    p.add_argument(
        "--no-mask-text", action="store_true", help="do not erase OCR text before line detection"
    )

    p = sub.add_parser("yolo", help="YOLO device detection only")
    common(p)
    p.add_argument("--weights")

    p = sub.add_parser("ocr", help="PaddleOCR only")
    common(p)

    p = sub.add_parser("opencv", help="OpenCV link detection only")
    common(p)
    p.add_argument("--raw-yolo", help="raw_yolo.json used to mask device interiors")
    p.add_argument("--raw-ocr", help="raw_ocr.json used to mask text")

    p = sub.add_parser("fuse", help="fusion + topology from existing raw JSON files")
    common(p, image=False)
    p.add_argument("--raw-yolo")
    p.add_argument("--raw-ocr")
    p.add_argument("--raw-opencv")

    p = sub.add_parser("validate", help="check topology.simple.json before it goes to the RAG")
    common(p, image=False)
    p.add_argument(
        "--input", help="minimal topology to check (default: <output-dir>/topology.simple.json)"
    )
    p.add_argument(
        "--report", help="also write the report here (default: <output-dir>/validation.json)"
    )
    p.add_argument(
        "--allow-ipv6-only",
        action="store_true",
        help="accept devices/links that only have IPv6 (the RAG itself requires IPv4)",
    )

    p = sub.add_parser(
        "correct", help="apply user corrections to topology.simple.json, then re-validate"
    )
    common(p, image=False)
    p.add_argument(
        "--corrections",
        required=True,
        help="JSON file with a list of corrections, or the JSON list itself (see validation.corrections)",
    )
    p.add_argument(
        "--input", help="minimal topology to correct (default: <output-dir>/topology.simple.json)"
    )
    p.add_argument("--output", help="where to write the corrected topology (default: in place)")
    p.add_argument(
        "--allow-ipv6-only", action="store_true", help="accept devices/links that only have IPv6"
    )

    p = sub.add_parser("print-config", help="print the effective settings and thresholds as JSON")
    common(p, image=False)
    p.add_argument("--weights")
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in COMMANDS and argv[0] not in ("-h", "--help", "-v", "--verbose"):
        argv.insert(0, "run")
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    settings = Settings.load(
        args.config, weights=getattr(args, "weights", None), output_dir=args.output_dir
    )
    if getattr(args, "no_mask_devices", False):
        settings.opencv.mask_devices = False
    if getattr(args, "no_mask_text", False):
        settings.opencv.mask_text = False
    try:
        return _dispatch(args, settings)
    except (
        FileNotFoundError,
        ValueError,
        RuntimeError,
    ) as exc:  # missing image/weights, bad JSON, missing deps
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _dispatch(args: argparse.Namespace, settings: Settings) -> int:
    paths = output_paths(settings.output_dir)
    pipe = Pipeline(settings)

    if args.command == "print-config":
        print(json.dumps(settings.to_dict(), indent=2))
    elif args.command == "run":
        pipe.run(args.image, settings.output_dir)
    elif args.command == "yolo":
        pipe.run_yolo(args.image, paths.raw_yolo)
    elif args.command == "ocr":
        pipe.run_ocr(args.image, paths.raw_ocr)
    elif args.command == "opencv":
        ry = RawYolo.from_dict(read_json(args.raw_yolo)) if args.raw_yolo else None
        ro = RawOcr.from_dict(read_json(args.raw_ocr)) if args.raw_ocr else None
        pipe.run_opencv(args.image, paths.raw_opencv, ry, ro)
    elif args.command == "fuse":
        pipe.fuse(
            args.raw_yolo or paths.raw_yolo,
            args.raw_ocr or paths.raw_ocr,
            args.raw_opencv or paths.raw_opencv,
            paths.fusion,
            paths.topology,
            paths.topology_simple,
        )
    elif args.command == "validate":
        report = pipe.validate_file(
            args.input or paths.topology_simple,
            args.report or paths.validation,
            require_ipv4=not args.allow_ipv6_only,
        )
        _print_report(report)
        return 0 if report["valid"] else 1
    elif args.command == "correct":
        text = args.corrections.strip()
        corrections = json.loads(text) if text.startswith("[") else read_json(args.corrections)
        result = pipe.correct_file(
            args.input or paths.topology_simple,
            corrections,
            args.output,
            require_ipv4=not args.allow_ipv6_only,
        )
        for a in result["applied"]:
            print(f"applied  #{a['index']}: " + "; ".join(a["changes"]))
        for r in result["rejected"]:
            print(f"REJECTED #{r['index']}: {r['code']}: {r['message']}")
        _print_report(result["report"])
        return 0 if result["report"]["valid"] and not result["rejected"] else 1
    return 0


def _print_report(report: dict) -> None:
    print(
        f"{report['status'].upper()}: {report['summary']['errors']} error(s), "
        f"{report['summary']['warnings']} warning(s)"
    )
    for issue in report["errors"] + report["warnings"]:
        print(f"  [{issue['severity']}] {issue['code']} at {issue['path']}: {issue['message']}")


if __name__ == "__main__":
    raise SystemExit(main())
