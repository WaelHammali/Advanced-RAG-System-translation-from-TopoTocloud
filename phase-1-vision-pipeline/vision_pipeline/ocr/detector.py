"""PaddleOCR text detection.

Responsibility: report every text region with its recognised string, confidence and
geometry, in ORIGINAL image coordinates. No semantics: whether a string is an IP address is
the semantic parser's job.

Both the PaddleOCR 3.x API (``predict`` -> dict-like results with ``rec_texts`` /
``rec_scores`` / ``rec_polys``) and the 2.x API (``ocr`` -> ``[[poly, (text, score)], ...]``)
are supported. Document unwarping / orientation correction is disabled on 3.x because it
would change the coordinate system.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..config.settings import OcrSettings
from ..geometry import Rect, reading_order_key
from ..image_io import image_info, load_image_bgr
from ..schemas.raw import OcrText, RawOcr

Polygon = list[tuple[float, float]]


def parse_paddle_output(raw: Any) -> list[tuple[str, float, Polygon]]:
    """Normalise PaddleOCR 2.x / 3.x output to ``[(text, confidence, polygon), ...]``."""
    out: list[tuple[str, float, Polygon]] = []
    if raw is None:
        return out
    pages = raw if isinstance(raw, (list, tuple)) else [raw]
    for page in pages:
        if page is None:
            continue
        # ---- 3.x: dict-like page
        if hasattr(page, "keys") or hasattr(page, "get"):
            data = page
            if "res" in data:  # some versions nest under {"res": {...}}
                data = data["res"]
            texts = list(data.get("rec_texts") or [])
            scores = list(data.get("rec_scores") or [])
            polys = data.get("rec_polys")
            if polys is None or len(polys) == 0:
                polys = data.get("dt_polys")
            polys = list(polys) if polys is not None else []
            for text, score, poly in zip(texts, scores, polys):
                pts = [(float(x), float(y)) for x, y in np.asarray(poly).reshape(-1, 2)]
                out.append((str(text), float(score), pts))
            continue
        # ---- 2.x: list of [poly, (text, score)]
        for line in page:
            poly, rec = line[0], line[1]
            pts = [(float(x), float(y)) for x, y in np.asarray(poly).reshape(-1, 2)]
            out.append((str(rec[0]), float(rec[1]), pts))
    return out


class OcrDetector:
    def __init__(self, settings: OcrSettings, engine: Any | None = None) -> None:
        self.settings = settings
        self._engine = engine  # injectable for tests / alternative OCR back-ends

    def load(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise RuntimeError(
                "paddleocr is not installed (pip install paddlepaddle paddleocr)"
            ) from exc
        extra = dict(self.settings.paddle_kwargs)
        try:  # PaddleOCR 3.x
            self._engine = PaddleOCR(
                lang=self.settings.language,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                **extra,
            )
        except (TypeError, ValueError):  # PaddleOCR 2.x
            self._engine = PaddleOCR(
                lang=self.settings.language, use_angle_cls=False, show_log=False, **extra
            )
        return self._engine

    def detect(self, image_path: str) -> RawOcr:
        image = load_image_bgr(image_path)
        return self.detect_array(image, image_info(image_path, image))

    def detect_array(self, image: np.ndarray, info) -> RawOcr:
        engine = self.load()
        scale = float(self.settings.upscale)
        work = image
        if scale != 1.0:
            import cv2

            work = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        raw = engine.predict(work) if hasattr(engine, "predict") else engine.ocr(work, cls=False)
        h, w = image.shape[:2]

        found: list[tuple[str, float, Polygon, Rect]] = []
        for text, conf, poly in parse_paddle_output(raw):
            if not text.strip() or conf < self.settings.min_confidence:
                continue
            poly = [(x / scale, y / scale) for x, y in poly]  # back to ORIGINAL coordinates
            box = Rect.from_points(poly).clip(w, h)
            if box.w <= 0 or box.h <= 0:
                continue
            found.append((text, conf, poly, box))

        order = reading_order_key([(str(i), f[3]) for i, f in enumerate(found)])
        texts = []
        for n, key in enumerate(order, start=1):
            text, conf, poly, box = found[int(key)]
            texts.append(
                OcrText(id=f"text_{n:03d}", text=text, confidence=conf, bbox=box, polygon=poly)
            )
        return RawOcr(
            image=info,
            texts=texts,
            producer={
                "name": "paddleocr",
                "language": self.settings.language,
                "upscale": scale,
                "min_confidence": self.settings.min_confidence,
            },
        )
