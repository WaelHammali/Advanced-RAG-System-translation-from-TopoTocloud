"""YOLO / PaddleOCR wrappers exercised with fakes (the real libraries are optional)."""

import numpy as np
import pytest
from vision_pipeline.config.settings import OcrSettings, YoloSettings
from vision_pipeline.geometry import Rect
from vision_pipeline.ocr.detector import OcrDetector, parse_paddle_output
from vision_pipeline.schemas.raw import ImageInfo, RawOcr, RawYolo
from vision_pipeline.yolo.detector import (
    WeightsNotFoundError,
    YoloDetector,
    assign_ids,
    results_to_detections,
)

INFO = ImageInfo("d.png", 640, 480)
IMG = np.full((480, 640, 3), 255, np.uint8)


# ------------------------------------------------------------------------------- YOLO


class FakeBoxes:
    def __init__(self, xyxy, conf, cls):
        self.xyxy, self.conf, self.cls = (
            np.array(xyxy, float),
            np.array(conf, float),
            np.array(cls, float),
        )

    def __len__(self):
        return len(self.conf)


class FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes


class FakeYolo:
    names = {0: "router", 1: "switch", 2: "pc"}  # whatever the trained model says

    def __init__(self, xyxy, conf, cls):
        self.result, self.kwargs = FakeResult(FakeBoxes(xyxy, conf, cls)), None

    def predict(self, source, **kwargs):
        self.kwargs = kwargs
        assert source.shape == (480, 640, 3)
        return [self.result]


def test_yolo_reads_class_names_from_the_model_and_writes_standard_schema():
    model = FakeYolo(
        [[300, 50, 380, 130], [50, 50, 130, 130], [-5, 400, 60, 500]], [0.9, 0.8, 0.7], [1, 0, 2]
    )
    raw = YoloDetector(YoloSettings(confidence=0.3, iou=0.5), model=model).detect_array(IMG, INFO)
    assert model.kwargs["conf"] == 0.3 and model.kwargs["iou"] == 0.5
    assert [(d.id, d.cls) for d in raw.detections] == [
        ("device_001", "router"),
        ("device_002", "switch"),
        ("device_003", "pc"),
    ]  # reading order, not model order
    assert raw.detections[2].bbox == Rect(0, 400, 60, 480)  # clipped to the image
    assert raw.producer["class_names"] == ["router", "switch", "pc"]
    d = raw.to_dict()["detections"][0]
    assert set(d) == {"id", "class", "confidence", "bbox", "center"} and d["center"] == [90.0, 90.0]
    assert RawYolo.from_dict(raw.to_dict()).to_dict() == raw.to_dict()


def test_yolo_no_detections():
    model = FakeYolo(np.zeros((0, 4)), [], [])
    assert YoloDetector(YoloSettings(), model=model).detect_array(IMG, INFO).detections == []


def test_class_names_as_list():
    dets = results_to_detections(FakeResult(FakeBoxes([[0, 0, 5, 5]], [0.5], [1])), ["a", "b"])
    assert dets[0].cls == "b"
    assert assign_ids(dets)[0].id == "device_001"


def test_missing_weights_gives_actionable_error(tmp_path):
    with pytest.raises(WeightsNotFoundError) as e:
        YoloDetector(YoloSettings(weights_path=str(tmp_path / "nope.pt"))).load()
    assert "nope.pt" in str(e.value) and "--weights" in str(e.value)


# -------------------------------------------------------------------------------- OCR

POLY = [[10, 20], [110, 20], [110, 40], [10, 40]]


class FakePaddle3:
    def predict(self, img):
        return [
            {
                "rec_texts": ["R1", "  ", "192.168.1.1/24"],
                "rec_scores": [0.99, 0.9, 0.95],
                "rec_polys": [
                    np.array(POLY),
                    np.array(POLY),
                    np.array([[20, 60], [220, 60], [220, 90], [20, 90]]),
                ],
            }
        ]


class FakePaddle2:
    def ocr(self, img, cls=False):
        return [
            [
                [POLY, ("R1", 0.99)],
                [[[20, 60], [220, 60], [220, 90], [20, 90]], ("192.168.1.1/24", 0.95)],
            ]
        ]


@pytest.mark.parametrize("engine", [FakePaddle3(), FakePaddle2()])
def test_ocr_handles_paddle_2x_and_3x_output(engine):
    raw = OcrDetector(OcrSettings(), engine=engine).detect_array(IMG, INFO)
    assert [(t.id, t.text) for t in raw.texts] == [
        ("text_001", "R1"),
        ("text_002", "192.168.1.1/24"),
    ]
    assert raw.texts[0].bbox == Rect(10, 20, 110, 40)
    d = raw.to_dict()["texts"][0]
    assert set(d) == {"id", "text", "confidence", "bbox", "center", "polygon"}
    assert RawOcr.from_dict(raw.to_dict()).to_dict() == raw.to_dict()


def test_ocr_upscale_is_mapped_back_to_original_coordinates():
    seen = {}

    class Engine:
        def predict(self, img):
            seen["shape"] = img.shape
            return [
                {
                    "rec_texts": ["R1"],
                    "rec_scores": [0.9],
                    "rec_polys": [np.array([[20, 40], [220, 40], [220, 80], [20, 80]])],
                }
            ]

    pytest.importorskip("cv2")
    raw = OcrDetector(OcrSettings(upscale=2.0), engine=Engine()).detect_array(IMG, INFO)
    assert seen["shape"][:2] == (960, 1280)
    assert raw.texts[0].bbox == Rect(10, 20, 110, 40)


def test_ocr_min_confidence_filter():
    raw = OcrDetector(OcrSettings(min_confidence=0.97), engine=FakePaddle3()).detect_array(
        IMG, INFO
    )
    assert [t.text for t in raw.texts] == ["R1"]


def test_parse_paddle_output_empty_cases():
    assert parse_paddle_output(None) == []
    assert parse_paddle_output([None]) == []
    assert parse_paddle_output([{"rec_texts": [], "rec_scores": [], "rec_polys": []}]) == []
