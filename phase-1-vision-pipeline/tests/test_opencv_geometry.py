"""Pure-geometry parts of the OpenCV stage (no cv2 needed) + geometry helpers."""

from __future__ import annotations

import math

from vision_pipeline.geometry import (
    Rect,
    clip_segment_to_rect,
    point_seg_distance,
    ray_rect_entry,
    reading_order_key,
    seg_rect_distance,
)
from vision_pipeline.opencv.path_reconstructor import reconstruct_paths
from vision_pipeline.opencv.segment_merger import merge_collinear

KW = dict(angle_tol_deg=4, perp_tol_px=6, gap_tol_px=20)


def test_fragments_of_one_line_merge():
    segs = [((0, 0), (100, 1)), ((105, 1), (200, 0)), ((190, 0), (320, 1))]
    (m,) = merge_collinear(segs, **KW)
    xs = sorted([m[0][0], m[1][0]])
    assert xs[0] < 2 and xs[1] > 318


def test_double_edge_of_a_thick_line_collapses_to_its_centre():
    segs = [((0, 0), (300, 0)), ((0, 4), (300, 4))]
    (m,) = merge_collinear(segs, **KW)
    assert abs(m[0][1] - 2) < 0.5 and abs(m[1][1] - 2) < 0.5


def test_parallel_lines_far_apart_do_not_merge():
    assert len(merge_collinear([((0, 0), (300, 0)), ((0, 40), (300, 40))], **KW)) == 2


def test_perpendicular_and_far_gap_do_not_merge():
    assert len(merge_collinear([((0, 0), (100, 0)), ((100, 0), (100, 100))], **KW)) == 2
    assert len(merge_collinear([((0, 0), (100, 0)), ((200, 0), (300, 0))], **KW)) == 2


def test_gap_covered_by_masked_text_is_bridged_but_open_gap_is_not():
    segs = [((0, 0), (100, 0)), ((220, 0), (320, 0))]
    text = [Rect(100, -10, 220, 10)]
    assert len(merge_collinear(segs, **KW)) == 2
    assert len(merge_collinear(segs, **KW, bridge_rects=text, max_bridge_px=400)) == 1
    assert (
        len(merge_collinear(segs, **KW, bridge_rects=[Rect(100, -10, 130, 10)], max_bridge_px=400))
        == 2
    )


def test_simple_chain_has_two_endpoints_ordered_left_to_right():
    (p,), dropped = reconstruct_paths([((10, 10), (100, 10)), ((104, 10), (200, 10))], join_dist=10)
    assert dropped == 0 and p.path_type == "chain"
    assert p.start == (10, 10) and abs(p.end[0] - 200) < 1e-6
    assert len(p.polyline) == 3


def test_l_shaped_cable_is_one_path():
    (p,), _ = reconstruct_paths([((0, 0), (100, 0)), ((100, 3), (100, 100))], join_dist=10)
    assert p.path_type == "chain" and p.start == (0, 0) and p.end == (100, 100)


def test_crossing_cables_are_not_joined():
    paths, _ = reconstruct_paths([((0, 50), (100, 50)), ((50, 0), (50, 100))], join_dist=10)
    assert len(paths) == 2 and all(p.path_type == "single" for p in paths)


def test_t_junction_is_branched_with_null_endpoints():
    (p,), _ = reconstruct_paths([((0, 50), (200, 50)), ((100, 0), (100, 47))], join_dist=10)
    assert p.path_type == "branched"
    assert p.start is None and p.end is None
    assert len(p.endpoints) == 3


def test_cables_docking_on_one_device_stay_separate_thanks_to_barrier():
    dev = Rect(100, 100, 160, 160)
    star = [((100, 130), (0, 130)), ((110, 100), (60, 0)), ((110, 160), (60, 260))]
    joined, _ = reconstruct_paths(star, join_dist=40)
    assert len(joined) == 1  # without a barrier they collapse
    separate, _ = reconstruct_paths(star, join_dist=40, barriers=[dev])
    assert len(separate) == 3 and all(p.path_type == "single" for p in separate)


def test_closed_loop_has_no_endpoints():
    sq = [((0, 0), (100, 0)), ((100, 0), (100, 100)), ((100, 100), (0, 100)), ((0, 100), (0, 0))]
    (p,), _ = reconstruct_paths(sq, join_dist=5)
    assert p.path_type == "cycle" and p.start is None and p.end is None


def test_short_paths_are_dropped_and_counted():
    paths, dropped = reconstruct_paths([((0, 0), (10, 0))], join_dist=5, min_path_length=30)
    assert paths == [] and dropped == 1


# ------------------------------------------------------------------ short-spur pruning


def test_short_spur_is_pruned_and_the_real_cable_recovered():
    # a real cable crossed by a short (30px) spur - e.g. an arrow drawn on a device icon that
    # YOLO missed, or a decoration crossing the cable - must not be discarded as "branched"
    cable = [((0, 0), (600, 0))]
    spur = [((300, 0), (300, -30))]
    (p,), _ = reconstruct_paths(cable + spur, join_dist=5, max_spur_px=45)
    assert p.path_type == "chain" and p.start == (0.0, 0.0) and p.end == (600.0, 0.0)
    assert p.pruned_spur_count == 1 and p.pruned_length_px == 30.0


def test_spur_pruning_disabled_by_default_leaves_it_branched():
    cable = [((0, 0), (600, 0))]
    spur = [((300, 0), (300, -30))]
    (p,), _ = reconstruct_paths(cable + spur, join_dist=5)  # max_spur_px defaults to 0
    assert p.path_type == "branched" and p.pruned_spur_count == 0


def test_a_genuine_long_branch_is_never_pruned():
    # a real 3-way junction (a hub/splitter actually drawn in the diagram) must stay branched,
    # never resolved by discarding one of its real arms
    cable = [((0, 0), (600, 0))]
    real_branch = [((300, 0), (300, -200))]
    (p,), _ = reconstruct_paths(cable + real_branch, join_dist=5, max_spur_px=45)
    assert p.path_type == "branched" and p.pruned_spur_count == 0


def test_two_short_spurs_on_the_same_cable_are_both_prunable():
    cable = [((0, 0), (600, 0))]
    spurs = [((290, 0), (290, -25)), ((310, 0), (310, 25))]
    (p,), _ = reconstruct_paths(cable + spurs, join_dist=5, max_spur_px=45)
    assert p.path_type == "chain" and p.start == (0.0, 0.0) and p.end == (600.0, 0.0)
    assert p.pruned_spur_count == 2


def test_pruning_that_does_not_fully_resolve_the_branch_is_abandoned():
    # one short, prunable spur plus one genuinely long branch (at a different point on the
    # cable): pruning the short spur alone still leaves 3 leaves (the long branch is still a
    # real junction) - nothing may be guessed, so the ENTIRE pruning attempt is abandoned and
    # the original, unpruned structure is reported
    cable = [((0, 0), (600, 0))]
    short_spur = [((290, 0), (290, -25))]
    long_branch = [((310, 0), (310, 200))]
    (p,), _ = reconstruct_paths(cable + short_spur + long_branch, join_dist=5, max_spur_px=45)
    assert p.path_type == "branched" and p.pruned_spur_count == 0
    assert len(p.endpoints) == 4


def test_pruning_a_short_cycle_spur_does_not_fabricate_a_chain():
    # a closed loop with a short dangling spur: removing the spur would leave a pure cycle (0
    # leaves), not a 2-leaf chain, so the whole pruning attempt is abandoned - never invent a
    # start/end on a loop
    sq = [((0, 0), (100, 0)), ((100, 0), (100, 100)), ((100, 100), (0, 100)), ((0, 100), (0, 0))]
    spur = [((0, 0), (-30, 0))]
    (p,), _ = reconstruct_paths(sq + spur, join_dist=5, max_spur_px=45)
    assert (
        p.path_type == "branched" and p.start is None and p.end is None and p.pruned_spur_count == 0
    )


# ---------------------------------------------------------------------------- geometry


def test_rect_gap_and_point_distance():
    a, b = Rect(0, 0, 10, 10), Rect(13, 14, 20, 20)
    assert a.gap_to(b) == 5.0 and a.gap_to(a) == 0.0
    assert a.point_distance((13, 14)) == 5.0 and a.point_distance((5, 5)) == 0.0


def test_segment_helpers():
    r = Rect(10, 10, 20, 20)
    assert clip_segment_to_rect(((0, 15), (30, 15)), r) == ((10, 15), (20, 15))
    assert clip_segment_to_rect(((0, 0), (5, 5)), r) is None
    assert seg_rect_distance(((0, 15), (5, 15)), r) == 5.0
    assert math.isclose(point_seg_distance((5, 5), ((0, 0), (10, 0))), 5.0)
    assert ray_rect_entry((0, 15), (1, 0), r) == 10.0
    assert ray_rect_entry((0, 15), (-1, 0), r) is None
    assert ray_rect_entry((15, 15), (1, 0), r) == 0.0


def test_reading_order_is_row_banded_and_deterministic():
    items = [
        ("b", Rect(200, 103, 220, 120)),
        ("a", Rect(100, 100, 120, 118)),
        ("c", Rect(100, 300, 120, 318)),
    ]
    assert reading_order_key(items) == ["a", "b", "c"]


def test_short_slightly_tilted_fragment_merges_into_a_long_line():
    # regression: the fragment's own extrapolated line drifts > tol at the far end of the long
    # segment, but the fragment itself lies within tol of the long line
    segs = [((138, 182), (402, 182)), ((339, 177), (402, 178)), ((142, 177), (172, 177))]
    assert len(merge_collinear(segs, **KW)) == 1


def test_reading_order_treats_thin_horizontal_items_with_jitter_as_one_row():
    cables = [("right", Rect(478, 178.2, 761, 178.6)), ("left", Rect(138, 179.9, 402, 180.1))]
    assert reading_order_key(cables) == ["left", "right"]


def test_rect_iou():
    a = Rect(0, 0, 10, 10)
    assert a.iou(a) == 1.0
    assert a.iou(Rect(20, 20, 30, 30)) == 0.0  # disjoint
    assert a.iou(Rect(10, 0, 20, 10)) == 0.0  # touching edge, zero area overlap
    b = Rect(5, 5, 15, 15)  # overlap 5x5=25, union 100+100-25=175
    assert math.isclose(a.iou(b), 25 / 175)
    assert a.iou(b) == b.iou(a)  # symmetric
