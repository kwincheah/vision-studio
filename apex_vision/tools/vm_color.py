"""VisionMaster guide, chapter "Color Processing": Color Recognition.

Teaches colour classes from labelled sample regions and then names the colour of a region by its nearest samples (K nearest neighbours).
Teach it by setting Mode to "Learn", the label, and running once per sample picture; switch Mode back to "Recognize" afterwards.
The samples are stored in the module's settings, so they are saved with the project.
"""
from typing import Any, Dict, List

import cv2
import numpy as np

from apex_vision.core.param_schema import enum, num
from apex_vision.tools._spec import as_bgr, define, err, get_image, img, ng, no_image, ok, port, val

CAT = "Color Processing"
BINS = {"Low Sensitivity": 8, "Medium Sensitivity": 16, "High Sensitivity": 32}


def features(region: np.ndarray, kind: str, bins: int, intensity: bool) -> np.ndarray:
    """A colour descriptor of a region, normalised to sum to 1.

    Feature Histogram: a joint hue-saturation (and brightness) histogram: sensitive to the colour mix.
    Feature Spectrum:  three separate histograms side by side (hue, saturation, brightness): steadier, always uses brightness.
    """
    hsv = cv2.cvtColor(as_bgr(region), cv2.COLOR_BGR2HSV)
    if kind == "Feature Spectrum":
        parts = [cv2.calcHist([hsv], [0], None, [bins], [0, 180]).ravel(), cv2.calcHist([hsv], [1], None, [bins], [0, 256]).ravel(),
                 cv2.calcHist([hsv], [2], None, [bins], [0, 256]).ravel()]
        f = np.concatenate(parts)
    elif intensity:
        f = cv2.calcHist([hsv], [0, 1, 2], None, [bins, max(4, bins // 2), max(4, bins // 2)], [0, 180, 0, 256, 0, 256]).ravel()
    else:
        f = cv2.calcHist([hsv], [0, 1], None, [bins, max(4, bins // 2)], [0, 180, 0, 256]).ravel()
    f = f.astype(np.float64)
    return f / max(1e-12, f.sum())


def distance(a: np.ndarray, b: np.ndarray, how: str) -> float:
    if how == "Manhattan Distance":
        return float(np.abs(a - b).sum())
    if how == "Intersection Distance":
        return float(1.0 - np.minimum(a, b).sum())                              # 0 = identical histograms
    return float(np.sqrt(((a - b) ** 2).sum()))


@define("Color Recognition", CAT,
        "Names the colour of a region by comparing it with samples you taught it (for example 'red', 'green', 'blue' caps). Learn samples "
        "with Mode = Learn, then recognise with Mode = Recognize. K nearest neighbours decide the class.",
        inputs=[img()],
        outputs=[port("Class", "str", "Best matching class"), val("Score", "How strongly the best class matches (0-1)"),
                 port("Scores", "any", "Score of every class"), port("Samples", "any", "How many samples each class has")],
        params={"mode": "Recognize", "learn_label": "", "roi": [0, 0, 0, 0], "sensitivity_mode": "Medium Sensitivity",
                "feature_type": "Feature Histogram", "use_intensity": True, "k_value": 3, "knn_distance": "Intersection Distance",
                "min_score": 0.0, "samples": {}},
        schema={"mode": enum("Recognize", "Learn", "Clear Samples"), "learn_label": {"kind": "text", "hint": "the class this sample belongs to"},
                "roi": {"kind": "rect"}, "sensitivity_mode": enum("Low Sensitivity", "Medium Sensitivity", "High Sensitivity"),
                "feature_type": enum("Feature Spectrum", "Feature Histogram"), "k_value": num(1, 50),
                "knn_distance": enum("Euclidean Distance", "Manhattan Distance", "Intersection Distance"), "min_score": num(0, 1, 0.05, decimals=2),
                "samples": {"kind": "json"}})
def color_recognition(t, ctx):
    a = get_image(ctx)
    if a is None:
        return no_image()
    x, y, w, h = [int(v) for v in t.get_param("roi")]
    if w > 0 and h > 0:
        x, y, w, h = t.get_roi("roi", [0, 0, 1, 1], img_shape=a.shape)
        region = a[y:y + h, x:x + w]
    else:
        region = a
    bins = BINS.get(str(t.get_param("sensitivity_mode")), 16)
    kind = str(t.get_param("feature_type"))
    intensity = bool(t.get_param("use_intensity")) or kind == "Feature Spectrum"
    samples: Dict[str, List[List[float]]] = t.parameters.setdefault("samples", {})
    if not isinstance(samples, dict):
        samples = t.parameters["samples"] = {}
    mode = str(t.get_param("mode"))
    counts = lambda: {k: len(v) for k, v in samples.items()}                                    # noqa: E731
    if mode == "Clear Samples":
        samples.clear()
        return ok("all samples removed", Class="", Score=0.0, Scores={}, Samples={})
    f = features(region, kind, bins, intensity)
    if mode == "Learn":
        label = str(t.get_param("learn_label")).strip()
        if not label:
            return err("Color Recognition: no class name chosen: type it in 'Learn label' first")
        samples.setdefault(label, []).append([round(float(v), 6) for v in f])
        return ok(f"learned a sample of '{label}' ({len(samples[label])} so far)", Class=label, Score=1.0, Scores={label: 1.0}, Samples=counts())
    flat = [(lab, np.asarray(vec, np.float64)) for lab, vecs in samples.items() for vec in vecs]
    if not flat:
        return ng("no samples learned yet: set Mode to Learn and run on a picture of each colour", Class="", Score=0.0, Scores={}, Samples={})
    flat = [(lab, v) for lab, v in flat if v.shape == f.shape]
    if not flat:
        return err("Color Recognition: the learned samples were made with other feature settings; clear them and learn again")
    how = str(t.get_param("knn_distance"))
    ranked = sorted(((distance(f, v, how), lab) for lab, v in flat), key=lambda p: p[0])
    k = min(int(t.get_param("k_value")), len(ranked))
    top = ranked[:k]
    votes: Dict[str, int] = {}
    for _d, lab in top:
        votes[lab] = votes.get(lab, 0) + 1
    scale = 1.0 if how != "Euclidean Distance" else float(np.sqrt(2.0))
    scores = {}
    for lab in samples:
        d = [dd for dd, ll in ranked if ll == lab]
        scores[lab] = round(max(0.0, 1.0 - (min(d) / scale if how != "Manhattan Distance" else min(d) / 2.0)), 4) if d else 0.0
    best = max(votes, key=lambda lab: (votes[lab], -min(dd for dd, ll in top if ll == lab)))
    best_score = scores.get(best, 0.0)
    if best_score < float(t.get_param("min_score")):
        return ng(f"best match '{best}' scores {best_score:.2f}, below the minimum", Class=best, Score=best_score, Scores=scores, Samples=counts())
    over = [{"type": "text", "text": f"{best} {best_score:.2f}", "pt": (x + 6, y + 22), "color": (0, 255, 255)}]
    if w > 0 and h > 0:
        over.append({"type": "rect", "box": [x, y, w, h], "color": (0, 255, 255)})
    return ok(f"{best} (score {best_score:.2f}, {votes[best]} of {k} neighbours)", over, Class=best, Score=best_score, Scores=scores, Samples=counts())
