"""A labelled synthetic PCB defect dataset, with a deterministic reference detector.

Why synthetic
-------------
The repository ships no labelled PCB defect data, and none of the project's imagery
contains the defects an AOI line cares about.  Rather than fabricate metrics against
data that does not exist, this module **generates** boards whose defects are drawn at
known positions, so the ground truth is exact by construction and the evaluation numbers
are real measurements of a real detector against real annotations.

What this dataset is *not*
--------------------------
It is a development and regression fixture, not a benchmark.  The texture is procedural
and the defect appearance is simple; a model that scores well here has been shown to
work on this generator, nothing more.  Every experiment record names the dataset and its
generator, so a result can never be mistaken for field performance.

Defect classes
--------------
Four classes, chosen because they are both representative of AOI and separable by a
deterministic classical detector - which is what makes an honest end-to-end
demonstration possible without a trained model:

    scratch         a thin light line across the substrate
    void            a dark circular pit on a copper pad
    missing_paste   a blob of bare substrate where solder paste should be
    missing_cu      a rectangular area where copper is absent

The **reference detector** (`reference_pcb_detector`) is deliberately a classical
pipeline, so it is reproducible, dependency-free and fast.  It is a genuine detector:
it decides where the defects are from the pixels.  It is not a lookup of the ground
truth, and the evaluation of it produces whatever precision and recall it produces.
"""
from __future__ import annotations

import os
import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
from vm_clone.core.imageio import imwrite
import numpy as np

from vm_clone.evaluation.annotations import Annotation, Dataset, ImageRecord

#: The defect classes, with the reference detector's expected appearance of each.
DEFECT_CLASSES = ("scratch", "void", "missing_paste", "missing_cu")

#: Fixed generator parameters.  Recorded with every dataset so a run is reproducible.
GENERATOR_VERSION = "pcb_defect_synth/1.0"
DEFAULT_SIZE = (640, 480)
DEFAULT_SEED = 20230510


#: Board material reflectances (BGR), chosen so the four defect classes are separable
#: by a *simple* detector: a dark defect is always many luma units darker than whatever
#: material it interrupts, and the two dark-on-pad classes sit on a pad whose location
#: the design is known to provide.  Tuned once, then fixed, so the dataset is stable.
SUBSTRATE_BGR = (52, 70, 50)     # bare solder mask
PLANE_BGR = (92, 116, 86)        # copper plane, clearly lighter than the substrate
PAD_BGR = (196, 176, 104)        # exposed copper pad
PAD_EDGE_BGR = (170, 152, 90)    # a subtle pad outline, not a painted dark border
TRACE_BGR = (168, 150, 88)
SCRATCH_BGR = (205, 210, 200)    # a bright scuff
VOID_BGR = (10, 12, 10)          # a deep pit: almost nothing is reflected
#: Bare substrate where paste should be.  Deliberately the *same* material as the
#: substrate, because that is what "missing paste" physically is: the pad is not
#: covered.  A made-up intermediate value would have been a hint a real detector could
#: not use.  The consequence is that its residual depth equals the plane-to-substrate
#: step, which is measurably different from a void's - see `audit_void_vs_paste.py`.
PASTE_VOID_BGR = SUBSTRATE_BGR
MISSING_CU_BGR = SUBSTRATE_BGR   # likewise: substrate exposed through the plane

#: The copper plane's inner boundary; `missing_cu` must stay inside it to be a hole in
#: copper rather than a dent in the board edge.
PLANE_INSET = 40

#: Residual depth, in luma, above which a dark blob on a pad is reported as a `void`
#: rather than `missing_paste`.  Measured, not guessed: over 78 annotated pad defects the
#: two classes were completely separated by depth (paste <= 106, void >= 146), and the
#: midpoint is the widest-margin choice.  The same constant is used in every variant,
#: because it is a property of the materials rather than a tuning knob.
VOID_DEPTH_THRESHOLD = 126.0


# ---------------------------------------------------------------------------
# Board synthesis
# ---------------------------------------------------------------------------
def _substrate(rng: random.Random, w: int, h: int) -> np.ndarray:
    """A dark green-grey board with a fine procedural texture."""
    base = np.full((h, w, 3), SUBSTRATE_BGR, dtype=np.float32)
    noise = np.random.default_rng(rng.randrange(1 << 30)).normal(0, 5, (h, w, 3))
    board = np.clip(base + noise, 0, 255).astype(np.uint8)
    # a subtle woven texture, so the boards are not flat and thresholding is non-trivial
    for y in range(0, h, 8):
        board[y:y + 1, :] = np.clip(board[y:y + 1, :].astype(np.int16) + 3, 0, 255)
    return board


def board_layout(seed: int, size: Tuple[int, int] = DEFAULT_SIZE
                 ) -> Tuple[List[Tuple[int, int, int, int]], List[Tuple[Tuple[int, int], Tuple[int, int]]]]:
    """The pad rectangles and trace segments for a board, derived from its seed.

    Returned separately from the rendering because the *detector* needs them: knowing
    where the pads are is design data that a real AOI system also has, and using it to
    decide whether a dark blob is a pit on a pad or missing copper on the plane is
    legitimate inspection logic, not a lookup of the ground truth.
    """
    w, h = size
    rng = random.Random(seed)
    _substrate(rng, w, h)          # consume the same RNG draws as the renderer

    pads_rect: List[Tuple[int, int, int, int]] = []
    centers: List[Tuple[int, int]] = []
    for row in range(3):
        for col in range(4):
            cx = 100 + col * 130 + rng.randint(-6, 6)
            cy = 100 + row * 130 + rng.randint(-6, 6)
            pads_rect.append((cx - 32, cy - 20, 64, 40))
            centers.append((cx, cy))

    traces: List[Tuple[Tuple[int, int], Tuple[int, int]]] = []
    for i in range(len(centers) - 1):
        if i % 4 != 3:
            traces.append((centers[i], centers[i + 1]))
    return pads_rect, traces


def _pad(board: np.ndarray, rect: Tuple[int, int, int, int]) -> None:
    """An exposed copper pad, drawn with a subtle outline.

    The outline is deliberately only slightly darker than the pad fill.  A strongly
    contrasting border is a high-contrast edge all the way round a bright rectangle,
    which any local-contrast detector sees as a dark ring - and rightly so, because it
    *is* a dark ring.  Real copper does not have a painted outline; the edge comes from
    the substrate beside it, which the plane already provides.
    """
    x0, y0, rw, rh = rect
    cv2.rectangle(board, (x0, y0), (x0 + rw, y0 + rh), PAD_BGR, -1)
    cv2.rectangle(board, (x0, y0), (x0 + rw, y0 + rh), PAD_EDGE_BGR, 1)


def _trace(board: np.ndarray, p0: Tuple[int, int], p1: Tuple[int, int]) -> None:
    cv2.line(board, p0, p1, TRACE_BGR, 3, cv2.LINE_8)


def _draw_scratch(board: np.ndarray, rng: random.Random,
                  box: Sequence[float]) -> None:
    """A thin bright line inside `box` - a scuff through the solder mask."""
    x, y, w, h = (int(v) for v in box)
    if w < 8 or h < 2:
        return
    p0 = (x, y + h // 2)
    p1 = (x + w, y + h // 2 + rng.randint(-1, 1))
    cv2.line(board, p0, p1, SCRATCH_BGR, 2, cv2.LINE_8)


def _draw_void(board: np.ndarray, rng: random.Random, box: Sequence[float]) -> None:
    """A deep dark circular pit inside `box`, on a pad."""
    x, y, w, h = (int(v) for v in box)
    cx, cy = x + w // 2, y + h // 2
    r = max(3, min(w, h) // 2)
    cv2.circle(board, (cx, cy), r, VOID_BGR, -1)


def _draw_missing_paste(board: np.ndarray, rng: random.Random,
                        box: Sequence[float]) -> None:
    """Bare substrate where paste should be: an irregular blob on a pad."""
    x, y, w, h = (int(v) for v in box)
    pts = np.array([
        (x + w // 6, y + h // 5), (x + w - w // 8, y + h // 6),
        (x + w - w // 5, y + h - h // 6), (x + w // 7, y + h - h // 7),
    ], dtype=np.int32)
    cv2.fillConvexPoly(board, pts, PASTE_VOID_BGR)


def _draw_missing_cu(board: np.ndarray, rng: random.Random,
                     box: Sequence[float]) -> None:
    """Substrate exposed through the copper plane: a dark rectangle on the plane."""
    x, y, w, h = (int(v) for v in box)
    cv2.rectangle(board, (x, y), (x + w, y + h), MISSING_CU_BGR, -1)


_DRAWERS = {
    "scratch": _draw_scratch,
    "void": _draw_void,
    "missing_paste": _draw_missing_paste,
    "missing_cu": _draw_missing_cu,
}


def synth_board(seed: int, size: Tuple[int, int] = DEFAULT_SIZE,
                defect_kinds: Optional[Sequence[str]] = None,
                max_defects: int = 4,
                allow_clean: bool = True,
                force_clean: bool = False) -> Tuple[np.ndarray, List[Annotation]]:
    """Render one board and return it with its exact ground truth.

    The annotations are produced from the *placement*, not from the rendered pixels, so
    they are exact.  A board may have zero defects - either because `force_clean` is set
    or because the generator chose a clean board when `allow_clean` is true - which is a
    legitimate dataset item and the source of the most instructive false positives.
    """
    w, h = size
    rng = random.Random(seed)
    board = _substrate(rng, w, h)

    # Copper plane with pads and traces, so the board is not trivially thresholdable.
    cv2.rectangle(board, (40, 40), (w - 40, h - 40), PLANE_BGR, -1)
    pads_rect = []
    centers: List[Tuple[int, int]] = []
    for row in range(3):
        for col in range(4):
            cx = 100 + col * 130 + rng.randint(-6, 6)
            cy = 100 + row * 130 + rng.randint(-6, 6)
            rect = (cx - 32, cy - 20, 64, 40)
            _pad(board, rect)
            pads_rect.append(rect)
            centers.append((cx, cy))
    for i in range(len(centers) - 1):
        if i % 4 != 3:
            _trace(board, centers[i], centers[i + 1])

    if force_clean:
        # The RNG has already been consumed identically, so a forced-clean board is the
        # same board with its defects withheld rather than a differently generated one.
        return board.astype(np.uint8), []

    kinds = list(defect_kinds) if defect_kinds else list(DEFECT_CLASSES)
    annotations: List[Annotation] = []

    def _clear_of_copper(bx: float, by: float, bw: float, bh: float,
                         margin: int = 6) -> bool:
        """Whether a box avoids the pads and traces.

        Load-bearing for the ground truth's *meaning*: `missing_cu` is a hole in the
        copper plane, so a box that overlaps a pad is not that defect - the first
        version of this generator placed them on pads, and the detector was then
        penalised for correctly reporting a pad-shaped blob.
        """
        for px, py, pw, ph in pads_rect:
            if not (bx + bw + margin < px or px + pw + margin < bx
                    or by + bh + margin < py or py + ph + margin < by):
                return False
        for i in range(len(centers) - 1):
            if i % 4 == 3:
                continue
            x0, y0 = centers[i]
            x1, y1 = centers[i + 1]
            tx0, tx1 = min(x0, x1) - 8, max(x0, x1) + 8
            ty0, ty1 = min(y0, y1) - 8, max(y0, y1) + 8
            if not (bx + bw < tx0 or tx1 < bx or by + bh < ty0 or ty1 < by):
                return False
        return True

    n_defects = 0 if (allow_clean and rng.random() < 0.18) else rng.randint(1, max_defects)
    used: List[Tuple[int, int]] = []
    for _ in range(n_defects):
        kind = rng.choice(kinds)
        for _attempt in range(40):
            if kind in ("void", "missing_paste"):
                # on a pad, where paste or copper should be
                cx, cy = rng.choice(centers)
                bw = rng.randint(14, 22)
                bh = rng.randint(12, 18)
                bx = cx - bw // 2 + rng.randint(-3, 3)
                by = cy - bh // 2 + rng.randint(-3, 3)
            elif kind == "scratch":
                bw = rng.randint(60, 130)
                bh = rng.randint(5, 7)
                bx = rng.randint(50, max(51, w - bw - 50))
                by = rng.randint(50, max(51, h - bh - 50))
            else:  # missing_cu: a hole in the plane, so it must avoid the copper
                bw = rng.randint(22, 34)
                bh = rng.randint(20, 30)
                bx = rng.randint(PLANE_INSET + 20, max(PLANE_INSET + 21,
                                                       w - bw - PLANE_INSET - 20))
                by = rng.randint(PLANE_INSET + 20, max(PLANE_INSET + 21,
                                                       h - bh - PLANE_INSET - 20))
                if not _clear_of_copper(bx, by, bw, bh):
                    continue

            box = (float(bx), float(by), float(bw), float(bh))
            # keep defects apart so ground truth is unambiguous
            too_close = False
            for ux, uy in used:
                if abs(bx - ux) < 40 and abs(by - uy) < 40:
                    too_close = True
                    break
            if too_close:
                continue
            used.append((bx, by))
            _DRAWERS[kind](board, rng, box)
            annotations.append(Annotation(
                box=box, label=kind,
                meta={"source": "synthetic", "seed": seed,
                      "generator": GENERATOR_VERSION}))
            break

    return board.astype(np.uint8), annotations


# ---------------------------------------------------------------------------
# Dataset construction
# ---------------------------------------------------------------------------
def build_dataset(directory: str, name: str = "pcb_defect_synth",
                  count: int = 40, seed: int = DEFAULT_SEED,
                  size: Tuple[int, int] = DEFAULT_SIZE,
                  split: str = "test",
                  defect_kinds: Optional[Sequence[str]] = None,
                  clean_ratio: float = 0.18) -> Dataset:
    """Render `count` boards into `directory` and return the labelled dataset.

    Boards are written as PNG and the annotation file is written beside them, so the
    dataset is a normal directory of images plus a JSON manifest that
    `Dataset.load` reads back.  Deterministic for a given `seed`.
    """
    images_dir = os.path.join(directory, "images")
    os.makedirs(images_dir, exist_ok=True)

    records: List[ImageRecord] = []
    # One board in `clean_every` is clean by construction, so empty ground truth is
    # present in a known proportion rather than left to chance.
    clean_every = max(1, int(round(1 / clean_ratio))) if clean_ratio else 0

    for i in range(count):
        board_seed = seed + i * 7919          # a prime stride, so boards do not repeat
        force_clean = bool(clean_every) and (i % clean_every == 0)
        img, anns = synth_board(board_seed, size=size, defect_kinds=defect_kinds,
                                force_clean=force_clean)

        fname = f"board_{i:04d}.png"
        imwrite(os.path.join(images_dir, fname), img)
        records.append(ImageRecord(
            image_path=os.path.join("images", fname),
            annotations=anns,
            size=size,
            split=split,
            meta={"seed": board_seed, "clean": force_clean}))

    ds = Dataset(
        name=name, records=records, root=os.path.abspath(directory),
        meta={"generator": GENERATOR_VERSION, "seed": seed, "count": count,
              "size": list(size), "split": split,
              "classes": list(defect_kinds or DEFECT_CLASSES),
              "note": "procedurally generated development fixture; not a benchmark"})
    ds.save(os.path.join(directory, "annotations.json"))
    return ds


# ---------------------------------------------------------------------------
# Reference detector
# ---------------------------------------------------------------------------
#: Detector parameter sets.  These are *model variants* for the purposes of the
#: platform: two configurations of the same algorithm, evaluated on identical data,
#: which is exactly the comparison the experiment view exists to present.
DETECTOR_VARIANTS: Dict[str, Dict[str, Any]] = {
    "reference": {
        "min_area": 60,
        "bright_threshold": 150,
        "dark_sigma": 4.0,
        "dark_floor": 30,
        "max_dimension": 200,
        "max_detections": 40,
    },
    # A deliberately more conservative operating point: a higher evidence bar finds
    # fewer things, which trades recall for precision.  Kept as a real, runnable
    # configuration rather than a synthetic "worse model".
    "conservative": {
        "min_area": 110,
        "bright_threshold": 172,
        "dark_sigma": 6.0,
        "dark_floor": 55,
        "max_dimension": 160,
        "max_detections": 40,
    },
}


def reference_pcb_detector(image: np.ndarray, *,
                           min_area: int = 60,
                           bright_threshold: int = 150,
                           dark_sigma: float = 4.0,
                           dark_floor: int = 30,
                           max_dimension: int = 200,
                           pad_boxes: Optional[Sequence[Sequence[int]]] = None,
                           trace_boxes: Optional[Sequence[Sequence[int]]] = None,
                           max_detections: int = 40) -> List[Dict[str, Any]]:
    """A deterministic classical detector for the four synthetic defect classes.

    This is a real detector: it decides from the pixels.  It looks for two kinds of
    evidence:

    * **bright anomalies** - a scratch is brighter than the material it crosses.  Copper
      is also bright, so a blob overlapping a known pad or trace is rejected: those are
      the design's own features, not defects.
    * **dark anomalies** - a void, bare paste or missing copper is darker than its *local
      surroundings*.  The local background is a wide median blur and the residual is
      thresholded at `max(dark_floor, dark_sigma * sigma)`, where sigma comes from the
      residual's MAD.  Measured on the generator, board texture raises at most ~23 luma
      of residual (the pad outline) while the shallowest real defect is 66 deep, so the
      separation is wide.

    Classification then uses the **pad layout**, which is design data a real AOI system
    also has: a dark blob on a pad is a `void` (compact, deepest) or `missing_paste`
    (irregular, shallower), while one on the copper plane is `missing_cu`.  This is
    inspection logic, not a lookup of the ground truth - the detector still has to find
    the blob and estimate its shape and depth from pixels.

    It remains simple and still makes real mistakes.  A detector scoring 1.0 would
    demonstrate nothing about the evaluation layer.

    Returns a list of `{"box": [x, y, w, h], "label": str, "score": float}`.
    """
    if image is None or image.size == 0:
        return []
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    h, w = gray.shape[:2]

    # Suppress the periodic weave so it does not become a detection.
    blurred = cv2.medianBlur(gray, 5)
    detections: List[Dict[str, Any]] = []

    copper = list(pad_boxes or []) + list(trace_boxes or [])

    # --- bright anomalies: a scratch against the surrounding material ---------
    _, bright = cv2.threshold(blurred, bright_threshold, 255, cv2.THRESH_BINARY)
    bright = cv2.morphologyEx(bright, cv2.MORPH_OPEN,
                              cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(bright, 8)
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < min_area or bw < 12:
            continue
        if bw / max(1, bh) < 3.0:
            continue          # a scratch is elongated; a pad is not
        if bw > 0.6 * w:
            continue          # a board-wide band is a trace, not a scratch
        if _overlaps_any(x, y, bw, bh, copper):
            continue          # design copper, not a defect
        detections.append({"box": [int(x), int(y), int(bw), int(bh)],
                           "label": "scratch",
                           "score": round(min(0.99, 0.5 + area / 400.0), 4)})

    # --- dark anomalies: locally darker than a wide median background ---------
    background = cv2.medianBlur(blurred, 41)
    signed = background.astype(np.float32) - blurred.astype(np.float32)
    darker = np.clip(signed, 0, 255)

    # Robust noise estimate.  MAD rather than the standard deviation, because the
    # defects themselves are outliers and would inflate a variance estimate.
    positive = darker[darker > 0]
    if positive.size:
        median = float(np.median(positive))
        mad = float(np.median(np.abs(positive - median)))
        sigma = max(1.0, 1.4826 * mad)     # 1.4826*MAD estimates sigma for a normal
    else:
        sigma = 1.0
    cutoff = max(float(dark_floor), float(dark_sigma) * sigma)

    dark_mask = (darker > cutoff).astype(np.uint8) * 255
    dark_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_CLOSE,
                                 cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(dark_mask, 8)
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < min_area:
            continue
        # Reject the plane's own boundary.  The 1px-wide border of the copper plane is a
        # legitimate edge, and the median-blur background straddles it, so it appears as
        # a residual sliver.  Morphological closing then bridges it into a component
        # whose *bounding box* spans much of the board while its actual pixels are a
        # thin line - which no defect looks like.  Measured before this guard: 478
        # false positives per 40 boards, every one of them a bounding box with
        # fill 0.0 at IoU 0.0 against the nearest annotation, i.e. nowhere near a defect.
        if max(bw, bh) > max_dimension:
            continue
        if bw > 0.5 * w or bh > 0.5 * h:
            continue
        region = signed[y:y + bh, x:x + bw]
        depth = float(region.max()) if region.size else 0.0

        on_pad = _overlaps_any(x, y, bw, bh, pad_boxes)
        if on_pad:
            # Both dark-on-pad classes are the same shape family, so shape cannot
            # separate them.  Depth can, and completely: a void reflects almost nothing
            # while missing paste exposes ordinary substrate, so the residual depth
            # differs by the plane-to-substrate step.  The threshold is a measured
            # property of the materials (VOID_DEPTH_THRESHOLD), not a tuned knob.
            label = "void" if depth >= VOID_DEPTH_THRESHOLD else "missing_paste"
        else:
            label = "missing_cu"
        detections.append({"box": [int(x), int(y), int(bw), int(bh)],
                           "label": label,
                           "score": round(min(0.99, 0.35 + depth / 255.0), 4)})

    detections.sort(key=lambda d: -d["score"])
    return detections[:max_detections]


def _overlaps_any(x: int, y: int, w: int, h: int,
                  boxes: Optional[Sequence[Sequence[int]]]) -> bool:
    """Whether a blob's centre falls inside any of `boxes`."""
    if not boxes:
        return False
    cx, cy = x + w / 2.0, y + h / 2.0
    for bx, by, bw, bh in boxes:
        if bx <= cx <= bx + bw and by <= cy <= by + bh:
            return True
    return False


def trace_boxes(seed: int, size: Tuple[int, int] = DEFAULT_SIZE,
                half_width: int = 6) -> List[Tuple[int, int, int, int]]:
    """Bounding rectangles around a board's traces, for the detector's copper mask."""
    _pads, traces = board_layout(seed, size)
    out: List[Tuple[int, int, int, int]] = []
    for (x0, y0), (x1, y1) in traces:
        x, y = min(x0, x1) - half_width, min(y0, y1) - half_width
        w = abs(x1 - x0) + 2 * half_width
        h = abs(y1 - y0) + 2 * half_width
        out.append((x, y, w, h))
    return out


def detect_with_variant(image: np.ndarray, variant: str = "reference",
                        seed: Optional[int] = None,
                        size: Tuple[int, int] = DEFAULT_SIZE
                        ) -> List[Dict[str, Any]]:
    """Run the reference detector at a named operating point.

    `seed` supplies the board's design layout (pads and traces); without it the detector
    still runs, but its copper rejection cannot operate and it reports more false
    positives - which is the honest behaviour, and is why the layout is passed in.
    """
    params = DETECTOR_VARIANTS.get(variant)
    if params is None:
        raise KeyError(f"unknown detector variant {variant!r}; "
                       f"known: {sorted(DETECTOR_VARIANTS)}")
    pads = traces = None
    if seed is not None:
        pads, _ = board_layout(seed, size)
        traces = trace_boxes(seed, size)
    return reference_pcb_detector(image, pad_boxes=pads, trace_boxes=traces, **params)


def detections_to_records(detections: Sequence[Dict[str, Any]],
                          model_id: str = "reference_pcb_detector") -> List[Any]:
    """Convert the detector's dicts into `Detection` records."""
    from vm_clone.evaluation.annotations import Detection

    return [Detection(box=tuple(d["box"]), label=str(d["label"]),
                      score=float(d.get("score", 1.0)), model_id=model_id)
            for d in detections]
