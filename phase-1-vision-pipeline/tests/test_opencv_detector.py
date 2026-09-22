"""OpenCV link detection on synthetic diagrams (needs cv2)."""

import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402
from vision_pipeline.config.settings import OpenCVSettings  # noqa: E402
from vision_pipeline.geometry import Rect  # noqa: E402
from vision_pipeline.opencv.link_detector import LinkDetector  # noqa: E402
from vision_pipeline.opencv.preprocessing import MaskRegions  # noqa: E402
from vision_pipeline.schemas.raw import ImageInfo, RawOpenCV  # noqa: E402

DEV_A, DEV_B = Rect(50, 100, 130, 180), Rect(450, 100, 530, 180)
LABEL = Rect(200, 108, 320, 128)


def diagram(bg=255, fg=0):
    img = np.full((300, 600, 3), bg, np.uint8)
    for r in (DEV_A, DEV_B):
        cv2.rectangle(img, (int(r.x1), int(r.y1)), (int(r.x2), int(r.y2)), (fg,) * 3, 2)
        cv2.circle(
            img, (int((r.x1 + r.x2) / 2), int((r.y1 + r.y2) / 2)), 20, (fg,) * 3, 2
        )  # icon detail
    cv2.line(img, (130, 140), (450, 140), (fg,) * 3, 3)
    cv2.putText(img, "192.168.1.0/24", (205, 125), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (fg,) * 3, 1)
    return img


def detect(img, regions, **cfg):
    return LinkDetector(OpenCVSettings(**cfg)).detect_array(
        img, ImageInfo("x.png", 600, 300), regions
    )


FULL = MaskRegions([DEV_A, DEV_B], [LABEL])


def test_masked_detection_finds_one_clean_cable_with_both_endpoints():
    raw = detect(diagram(), FULL)
    (c,) = raw.candidates
    assert c.path_type == "single" and c.id == "link_candidate_001"
    (sx, sy), (ex, ey) = c.start, c.end
    assert abs(sx - 130) < 12 and abs(ex - 450) < 12 and abs(sy - 140) < 3 and abs(ey - 140) < 3
    assert c.confidence > 0.8 and c.quality["ink_support"] > 0.9


def test_cable_running_under_a_text_label_is_still_one_cable():
    img = diagram()
    cv2.rectangle(
        img, (int(LABEL.x1), 132), (int(LABEL.x2), 148), (255, 255, 255), -1
    )  # text box erases part of the cable
    text_on_cable = Rect(LABEL.x1, 132, LABEL.x2, 148)
    raw = detect(img, MaskRegions([DEV_A, DEV_B], [LABEL, text_on_cable]))
    (c,) = raw.candidates
    assert c.path_type == "single"
    assert c.quality["observed_fraction"] < 0.8  # part of the path was bridged, and says so


def test_output_round_trips_through_the_raw_schema():
    raw = detect(diagram(), FULL)
    again = RawOpenCV.from_dict(raw.to_dict())
    assert again.to_dict() == raw.to_dict()


def test_light_lines_on_dark_background_are_supported():
    raw = detect(diagram(bg=20, fg=235), FULL)
    assert len(raw.candidates) == 1 and raw.producer["inverted_polarity"] is True


def test_empty_image_gives_no_candidates():
    raw = detect(np.full((300, 600, 3), 255, np.uint8), MaskRegions())
    assert raw.candidates == []


def test_working_scale_is_mapped_back_to_original_coordinates():
    raw = detect(
        diagram(),
        FULL,
        working_max_side=300,
        hough_min_line_length=12,
        min_segment_length_px=10,
        min_path_length_px=15,
        join_dist_px=6,
    )
    (c,) = raw.candidates
    assert raw.producer["working_scale"] == 0.5
    assert abs(c.start[0] - 130) < 15 and abs(c.end[0] - 450) < 15  # original pixels, not half-size


def test_unmasked_run_reports_undetermined_endpoints_instead_of_inventing_them():
    raw = detect(diagram(), MaskRegions())
    assert raw.candidates, "expected noisy candidates without masking"
    for c in raw.candidates:
        if c.path_type in ("branched", "cycle"):
            assert c.start is None and c.end is None


def test_segment_cap_bounds_memory_on_a_busy_image_instead_of_crashing():
    # collinear merging is O(n^2) in memory (observed ~7GB at ~9,000 raw segments on a large,
    # unmasked real image). Above the cap, only the longest segments are kept before merging -
    # real cables are long, incidental noise is short - and the drop is recorded, never silent.
    img = diagram()
    rng = np.random.default_rng(0)
    for _ in range(150):  # a lot of short noise lines, comfortably over a tiny test cap
        x1, y1 = int(rng.integers(0, 600)), int(rng.integers(0, 300))
        x2, y2 = x1 + int(rng.integers(-12, 12)), y1 + int(rng.integers(-12, 12))
        cv2.line(img, (x1, y1), (x2, y2), (0, 0, 0), 1)
    raw = detect(
        img,
        MaskRegions(),
        max_segments_for_merge=25,
        hough_min_line_length=5,
        min_segment_length_px=3,
    )
    assert raw.stats["after_inside_device_filter"] > 25
    assert raw.stats["segments_dropped_scale_cap"] == raw.stats["after_inside_device_filter"] - 25
    assert raw.candidates, "should still produce a usable (if degraded) result, not just give up"


def test_segment_cap_does_not_trigger_on_a_normal_diagram():
    raw = detect(diagram(), FULL)  # far fewer segments than the default 6000 cap
    assert "segments_dropped_scale_cap" not in raw.stats
