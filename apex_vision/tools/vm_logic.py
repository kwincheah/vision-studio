"""VisionMaster guide, chapters "Logic Tools" and "Communication": Condition Detection, Save Text, Format Module, String Comparison,
Point Set, Time Consuming, Data Set, Graphic Collection, Send Data, Receive Data, Protocol Parsing and Protocol Assembly.
"""
import csv
import io
import math
import os
import re
import struct
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from apex_vision.core import dataqueue
from apex_vision.core.param_schema import enum, num
from apex_vision.tools import vm_geom as g
from apex_vision.tools._spec import define, err, get_image, img, ng, ok, port, val
from apex_vision.tools.communication_ext import decode_escapes, stringify
from apex_vision.tools.script_tool import ScriptTimeout, run_with_deadline

LOGIC = "Logic Tools"
COMM = "Communication"


def _globals(ctx) -> Dict[str, Any]:
    gc = ctx.get("global")
    gv = gc.get("globals") if isinstance(gc, dict) else None
    return gv if isinstance(gv, dict) else {}


def _xy(v: Any) -> Optional[Tuple[float, float]]:
    """An (x, y) pair of real numbers (a sequence or a dict with x and y), else None."""
    if isinstance(v, dict) and "x" in v and "y" in v:
        v = (v["x"], v["y"])
    if not isinstance(v, (list, tuple, np.ndarray)) or len(v) < 2:
        return None
    a, b = v[0], v[1]
    if any(isinstance(q, (bool, str)) or not isinstance(q, (int, float, np.integer, np.floating)) for q in (a, b)):
        return None
    return (float(a), float(b)) if math.isfinite(a) and math.isfinite(b) else None


def _floats(v: Any) -> Optional[List[float]]:
    """A number or a list of numbers as a list of floats, or None."""
    if v is None:
        return None
    try:
        a = np.atleast_1d(np.asarray(v, dtype=float)).ravel()
    except (TypeError, ValueError):
        return None
    return [float(x) for x in a]


def _split_list(text: str) -> List[str]:
    return [p.strip() for p in re.split(r"[;\n]", str(text or "")) if p.strip()]


# ---------------------------------------------------------------------------------------------------------------------------
# Condition Detection
# ---------------------------------------------------------------------------------------------------------------------------
@define("Condition Detection", LOGIC,
        "Checks whether values are inside their allowed ranges. Judge All means every value must pass, Any means one is enough. Each value "
        "comes from a connected module or is typed; the result is OK or NG and the verdict of every value is listed.",
        inputs=[port("Value1", "val"), port("Value2", "val"), port("Value3", "val"), port("Value4", "val"), port("Values", "any", "A list of values")],
        outputs=[val("Result", "1 when the condition is met, else 0"), port("Results", "any", "1 or 0 for each value"), val("Passed", "How many values passed")],
        params={"judge_method": "All", "condition_type": "Float", "values": "", "ranges": "0,100"},
        schema={"judge_method": enum("All", "Any"), "condition_type": enum("Int", "Float"),
                "values": {"kind": "text", "hint": "typed values separated by commas (used where nothing is connected)"},
                "ranges": {"kind": "text", "hint": "min,max for each value, as 'min,max; min,max'"}})
def condition_detection(t, ctx):
    vals: List[Optional[float]] = []
    seen_any = False
    if ctx.get("Values") is not None:
        lst = _floats(ctx.get("Values"))
        if lst is None:
            return err("the values must be numbers or a list of numbers")
        vals, seen_any = list(lst), True
    else:
        for i in range(1, 5):
            v = ctx.get(f"Value{i}")
            if v is None:
                vals.append(None)
                continue
            f = _floats(v)
            if f is None or not f:
                return err(f"Value{i} must be a number")
            vals.append(f[0])
            seen_any = True
    typed = [p for p in re.split(r"[,;\s]+", str(t.get_param("values") or "")) if p]
    for i, p in enumerate(typed):
        try:
            f = float(p)
        except ValueError:
            return err(f"the typed value {p!r} is not a number")
        if i < len(vals):
            vals[i] = f if vals[i] is None else vals[i]
        else:
            vals.append(f)
        seen_any = True
    while vals and vals[-1] is None:
        vals.pop()
    if not seen_any or not vals:
        return err("no values to check: connect them, or type them")
    ranges: List[Tuple[float, float]] = []
    for part in _split_list(str(t.get_param("ranges")).replace("|", ";")) or ["0,100"]:
        nums = [x for x in re.split(r"[,\s]+", part) if x]
        try:
            lo, hi = float(nums[0]), float(nums[1])
        except (IndexError, ValueError):
            return err(f"a range must be 'min,max', not {part!r}")
        if lo > hi:
            return err(f"the range {part!r} has its minimum above its maximum")
        ranges.append((lo, hi))
    ints = str(t.get_param("condition_type")) == "Int"
    results: List[int] = []
    for i, v in enumerate(vals):
        lo, hi = ranges[min(i, len(ranges) - 1)]
        if v is None or not math.isfinite(v):
            results.append(0)
            continue
        x = float(int(v)) if ints else v
        results.append(1 if lo <= x <= hi else 0)
    passed = sum(results)
    good = passed == len(results) if str(t.get_param("judge_method")) == "All" else passed > 0
    fn = ok if good else ng
    return fn(f"{passed} of {len(results)} value(s) in range: {'OK' if good else 'NG'}", Result=1 if good else 0, Results=results, Passed=passed)


# ---------------------------------------------------------------------------------------------------------------------------
# Save Text
# ---------------------------------------------------------------------------------------------------------------------------
@define("Save Text", LOGIC,
        "Saves text or values to TXT or CSV files, one line each time. Choose the folder and file name, how large a file may grow, how many "
        "files to keep, and whether to stop or overwrite the oldest when that is reached. A trigger can decide when to save.",
        inputs=[port("Text", "any", "Text, or a list of values (one CSV row)"), port("Trigger", "val", "Saves only when this equals the trigger value"),
                port("Flush", "bool", "Write what is waiting in the cache now")],
        outputs=[val("Saved", "Lines written this time"), port("Path", "str", "The file written to"), val("Waiting", "Lines still in the cache")],
        params={"data_type": "TXT", "save_dir": "", "file_name": "result", "trigger_value": 1.0, "file_count": 10, "document_size_kb": 1024, "save_mode": "Overwrite Oldest",
                "timestamp": False, "by_date": False, "real_time": True, "csv_header": ""},
        schema={"data_type": enum("TXT", "CSV"), "save_dir": {"kind": "dir"}, "file_name": {"kind": "text", "hint": "base name of the files"},
                "trigger_value": num(-1e9, 1e9, 1, decimals=3), "file_count": num(1, 10000), "document_size_kb": num(1, 10_000_000, unit="KB"),
                "save_mode": enum("Stop Saving", "Overwrite Oldest"), "timestamp": {"kind": "bool"}, "by_date": {"kind": "bool"}, "real_time": {"kind": "bool"},
                "csv_header": {"kind": "text", "hint": "column names for a new CSV file, separated by commas"}})
def save_text(t, ctx):
    ext = "csv" if str(t.get_param("data_type")) == "CSV" else "txt"
    folder = str(t.get_param("save_dir") or "").strip()
    if not folder:
        return err("no folder chosen: choose where to save the files")
    base = re.sub(r'[\\/:*?"<>|]+', "_", str(t.get_param("file_name") or "result").strip()) or "result"
    buf: List[str] = getattr(t, "_buf", None) or []
    t._buf = buf
    trig = ctx.get("Trigger")
    flush = bool(ctx.get("Flush"))
    fire = True
    if trig is not None:
        f = _floats(trig)
        fire = bool(f) and abs(f[0] - float(t.get_param("trigger_value"))) < 1e-9
    text = ctx.get("Text")
    if fire and text is not None:
        if ext == "csv":
            row = text if isinstance(text, (list, tuple, np.ndarray)) else [text]
            sio = io.StringIO()
            csv.writer(sio, lineterminator="").writerow([stringify(v) for v in row])
            buf.append(sio.getvalue())
        else:
            buf.append(stringify(text))
    elif fire and text is None and trig is None and not flush:
        return err("no text to save: connect some")
    if not buf or not (bool(t.get_param("real_time")) or flush or sum(len(b) + 1 for b in buf) >= 4096):
        return ok(f"{len(buf)} line(s) waiting in the cache" if buf else "nothing to save", Saved=0, Path="", Waiting=len(buf))
    now = datetime.now()
    out_dir = os.path.join(folder, now.strftime("%Y-%m-%d")) if bool(t.get_param("by_date")) else folder
    try:
        os.makedirs(out_dir, exist_ok=True)
        pat = re.compile(r"^(?:\d{8}_\d{6}_)?" + re.escape(base) + r"_(\d{4})\." + ext + "$")
        files = sorted(((int(m.group(1)), n) for n in os.listdir(out_dir) if (m := pat.match(n))))
        limit = int(t.get_param("document_size_kb")) * 1024
        cur = None
        if files:
            path = os.path.join(out_dir, files[-1][1])
            if os.path.getsize(path) < limit:
                cur = path
        if cur is None:
            if len(files) >= int(t.get_param("file_count")):
                if str(t.get_param("save_mode")) == "Stop Saving":
                    return ng(f"the limit of {int(t.get_param('file_count'))} files is reached and saving is set to stop", Saved=0, Path="", Waiting=len(buf))
                for _, n in files[:len(files) - int(t.get_param("file_count")) + 1]:
                    os.remove(os.path.join(out_dir, n))
            idx = files[-1][0] + 1 if files else 1
            stamp = now.strftime("%Y%m%d_%H%M%S_") if bool(t.get_param("timestamp")) else ""
            cur = os.path.join(out_dir, f"{stamp}{base}_{idx:04d}.{ext}")
            header = str(t.get_param("csv_header") or "").strip()
            if ext == "csv" and header:
                with open(cur, "w", encoding="utf-8", newline="") as f:
                    f.write(header + "\r\n")
        with open(cur, "a", encoding="utf-8", newline="") as f:
            for line in buf:
                f.write(line + "\r\n")
    except OSError as e:
        return err(f"could not save: {e}")
    n = len(buf)
    t._buf = []
    return ok(f"saved {n} line(s) to {os.path.basename(cur)}", Saved=n, Path=cur, Waiting=0)


# ---------------------------------------------------------------------------------------------------------------------------
# Format Module
# ---------------------------------------------------------------------------------------------------------------------------
_FIELD = re.compile(r"\{(Data[1-8])(?::([^{}]*))?\}")


@define("Format Module", LOGIC,
        "Builds one line of text from your own wording and the results of other modules, ready to send to a PLC or robot. Write the text and "
        "put {Data1} to {Data8} where the values go ({Data1:.2f} sets the decimals); lists are joined with the split symbol.",
        inputs=[port(f"Data{i}", "any") for i in range(1, 9)],
        outputs=[port("Text", "str", "The finished text"), val("Length")],
        params={"format": "{Data1},{Data2}", "split_symbol": ",", "array_delimiter": ";", "end_char": "\\r\\n", "decimals": -1},
        schema={"format": {"kind": "text", "hint": "wording with {Data1}..{Data8}"}, "split_symbol": {"kind": "text", "hint": "between the elements of a list"},
                "array_delimiter": {"kind": "text", "hint": "between lists inside a list of lists"}, "end_char": {"kind": "text", "hint": "\\r, \\n or \\r\\n at the end"},
                "decimals": num(-1, 12)})
def format_module(t, ctx):
    template = str(t.get_param("format") or "")
    split, adelim = decode_escapes(str(t.get_param("split_symbol"))), decode_escapes(str(t.get_param("array_delimiter")))
    dec = int(t.get_param("decimals"))
    missing: List[str] = []

    def one(v: Any) -> str:
        if isinstance(v, (float, np.floating)) and dec >= 0:
            return f"{float(v):.{dec}f}"
        return stringify(v)

    def render(v: Any) -> str:
        if isinstance(v, (list, tuple, np.ndarray)):
            items = list(v)
            if items and all(isinstance(x, (list, tuple, np.ndarray)) for x in items):
                return adelim.join(split.join(one(y) for y in x) for x in items)
            return split.join(one(x) for x in items)
        return one(v)

    def sub(m):
        name, spec = m.group(1), m.group(2)
        v = ctx.get(name)
        if v is None:
            missing.append(name)
            return ""
        if spec:
            try:
                return format(float(v), spec)
            except (TypeError, ValueError):
                return render(v)
        return render(v)

    text = _FIELD.sub(sub, decode_escapes(template))
    if missing:
        return err("nothing connected to " + ", ".join(sorted(set(missing))) + ": connect it, or take it out of the wording")
    text += decode_escapes(str(t.get_param("end_char") or ""))
    return ok(f"{len(text)} character(s)", Text=text, Length=len(text))


# ---------------------------------------------------------------------------------------------------------------------------
# String Comparison
# ---------------------------------------------------------------------------------------------------------------------------
@define("String Comparison", LOGIC,
        "Compares a text with up to 32 texts you list and gives the index of the one it matches, for use with Branch. Nothing matching gives NG "
        "and no index.",
        inputs=[port("Text", "str", "Text to look up")],
        outputs=[val("Index", "Index of the matching text"), val("Matched", "1 when one matched"), port("Text", "str", "The text compared")],
        params={"strings": "OK;NG", "indices": "", "case_sensitive": True, "trim": True},
        schema={"strings": {"kind": "text", "hint": "texts separated by semicolons or new lines"}, "indices": {"kind": "text", "hint": "an index for each, separated by commas (default 0, 1, 2...)"},
                "case_sensitive": {"kind": "bool"}, "trim": {"kind": "bool"}})
def string_comparison(t, ctx):
    text = ctx.get("Text")
    if text is None:
        return err("no text to compare: connect one")
    targets = _split_list(str(t.get_param("strings")))
    if not targets:
        return err("no texts to compare with: type some")
    if len(targets) > 32:
        return err("at most 32 texts can be compared")
    idx_txt = [p for p in re.split(r"[,;\s]+", str(t.get_param("indices") or "")) if p]
    try:
        indices = [int(float(p)) for p in idx_txt] if idx_txt else list(range(len(targets)))
    except ValueError:
        return err("the indices must be whole numbers")
    if len(indices) < len(targets):
        indices += list(range(len(indices), len(targets)))
    s = str(text)
    if bool(t.get_param("trim")):
        s = s.strip()
    for i, c in enumerate(targets):
        a, b = (s, c) if bool(t.get_param("case_sensitive")) else (s.lower(), c.lower())
        if a == b:
            return ok(f"{s!r} is text number {indices[i]}", Index=indices[i], Matched=1, Text=s)
    return ng(f"{s!r} matches none of the {len(targets)} text(s)", Matched=0, Text=s)


# ---------------------------------------------------------------------------------------------------------------------------
# Point Set
# ---------------------------------------------------------------------------------------------------------------------------
@define("Point Set", LOGIC,
        "Gathers up to 16 points into one set for later modules. Points come from a list, from the typed ones, or - with the loop on - one more "
        "each time it runs (inside a Group's loop), until you clear it.",
        inputs=[port("Point", "pt", "A point to add"), port("Points", "any", "A list of points to add"), port("Clear", "bool", "Start the set again")],
        outputs=[port("Points", "any", "[[x, y], ...]"), port("X", "any", "All the X values"), port("Y", "any", "All the Y values"), val("Count")],
        params={"loop": False, "points": []}, schema={"loop": {"kind": "bool"}, "points": {"kind": "points"}})
def point_set(t, ctx):
    from apex_vision.tools.vm_calib import as_points
    acc: List[List[float]] = getattr(t, "_set", None) or []
    if ctx.get("Clear"):
        acc = []
    new: List[List[float]] = []
    if ctx.get("Points") is not None:
        pts = as_points(ctx.get("Points"))
        if pts is None:
            return err("the list of points is not a list of (x, y) pairs")
        new += pts.tolist()
    if ctx.get("Point") is not None:
        p = _xy(ctx.get("Point"))
        if p is None:
            return err("the point is not an (x, y) pair")
        new.append([p[0], p[1]])
    typed = as_points(t.get_param("points")) if t.get_param("points") else None
    if bool(t.get_param("loop")):
        acc = (acc + new)[-16:]
        t._set = acc
        out = acc
    else:
        t._set = []
        out = ((typed.tolist() if typed is not None else []) + new)[:16]
    if not out:
        return ng("the set is empty: connect points or type some", Points=[], X=[], Y=[], Count=0)
    over = [g.cross_overlay(x, y, (0, 255, 255), 5) for x, y in out]
    return ok(f"{len(out)} point(s) in the set", over, Points=out, X=[p[0] for p in out], Y=[p[1] for p in out], Count=len(out))


# ---------------------------------------------------------------------------------------------------------------------------
# Time Consuming
# ---------------------------------------------------------------------------------------------------------------------------
@define("Time Consuming", LOGIC,
        "Measures how long the flow has taken: since it began, or from the start of one module to the end of another (the end must come after the "
        "start). A limit turns a slow run into NG.",
        inputs=[port("Trigger", "any", "Connect to run after the module you want timed")],
        outputs=[val("Elapsed_Ms", "Time taken, milliseconds")],
        params={"measure": "Since Flow Start", "start_module": "", "end_module": "", "max_ms": 0.0},
        schema={"measure": enum("Since Flow Start", "Between Modules"), "start_module": {"kind": "text", "hint": "name of the first module"},
                "end_module": {"kind": "text", "hint": "name of the last module"}, "max_ms": num(0, 3_600_000, 10, "ms", 1)})
def time_consuming(t, ctx):
    gc = ctx.get("global") if isinstance(ctx.get("global"), dict) else {}
    limit = float(t.get_param("max_ms"))
    if str(t.get_param("measure")) == "Since Flow Start":
        started = gc.get("flow_started")
        if started is None:
            return err("the flow's start time is not known here: connect this module into a flow and run the flow")
        ms = (time.perf_counter() - float(started)) * 1000.0
    else:
        names = gc.get("node_names") or {}
        order = list(gc.get("order") or [])
        res = gc.get("results") or {}
        by_name = {n: i for i, n in names.items()}
        a, b = str(t.get_param("start_module")).strip(), str(t.get_param("end_module")).strip()
        if a not in by_name or b not in by_name:
            return err("both module names must be chosen from the flow's modules")
        ia, ib = order.index(by_name[a]) if by_name[a] in order else -1, order.index(by_name[b]) if by_name[b] in order else -1
        if ia < 0 or ib < 0:
            return err("a chosen module is not in this flow's running order")
        if ib < ia:
            return err("the end module must come after the start module")
        if any(order[k] not in res for k in range(ia, ib + 1)):
            return err("the end module has not run yet: place this module after it")
        ms = float(sum(res[order[k]].elapsed_ms for k in range(ia, ib + 1)))
    over_limit = limit > 0 and ms > limit
    fn = ng if over_limit else ok
    return fn(f"{ms:.2f} ms" + (f" - over the {limit:g} ms limit" if over_limit else ""), Elapsed_Ms=ms)


# ---------------------------------------------------------------------------------------------------------------------------
# Data Set
# ---------------------------------------------------------------------------------------------------------------------------
@define("Data Set", LOGIC,
        "Collects the value made on each pass of a loop into one list. The clear signal decides what comes out: empty or none - the whole "
        "cycle, cleared when the next cycle starts; 0 - the whole cycle, never cleared; any other value - only the last pass.",
        inputs=[port("Value", "any", "The value from this pass"), port("Clear", "any", "Clear signal"), port("Cycle", "val", "Pass number (0, 1, 2...), from a Group's loop")],
        outputs=[port("Data", "any", "The collected values"), val("Count"), port("Last", "any", "The value from the latest pass")],
        params={"name": "data", "value_type": "Float"},
        schema={"name": {"kind": "text", "hint": "a name for this data"}, "value_type": enum("Int", "Float", "String")})
def data_set(t, ctx):
    v = ctx.get("Value")
    if v is None:
        return err("no value to collect: connect one")
    kind = str(t.get_param("value_type"))
    try:
        v = int(float(v)) if kind == "Int" else float(v) if kind == "Float" else stringify(v)
    except (TypeError, ValueError):
        return err(f"the value cannot be taken as {kind.lower()}")
    st = getattr(t, "_ds", None)
    if st is None:
        st = t._ds = {"data": [], "cycle": None}
    clear = ctx.get("Clear")
    cyc = ctx.get("Cycle")
    try:
        cyc = int(float(cyc)) if cyc is not None else None
    except (TypeError, ValueError):
        cyc = None
    empty = clear is None or (isinstance(clear, str) and not clear.strip())
    zero = (not empty) and _floats(clear) == [0.0]
    if cyc is not None and st["cycle"] is not None and cyc <= st["cycle"] and empty:       # a new cycle begins: the old one is cleared
        st["data"] = []
    st["cycle"] = cyc if cyc is not None else st["cycle"]
    st["data"].append(v)
    out = list(st["data"]) if (empty or zero) else [v]
    return ok(f"{len(out)} value(s) in {t.get_param('name')}", Data=out, Count=len(out), Last=v)


# ---------------------------------------------------------------------------------------------------------------------------
# Graphic Collection
# ---------------------------------------------------------------------------------------------------------------------------
COLOURS = {"Green": (0, 220, 0), "Red": (0, 0, 255), "Yellow": (0, 255, 255), "Blue": (255, 120, 0), "White": (255, 255, 255), "Cyan": (255, 255, 0),
           "Magenta": (255, 0, 255), "Orange": (0, 140, 255)}


@define("Graphic Collection", LOGIC,
        "Draws results from several modules on one picture: points, lines, rectangles, ring sectors and text. Drawn in the OK colour when the "
        "status is OK and the NG colour otherwise; the transparency fills rectangles with a see-through tint.",
        inputs=[img(), port("Points", "any", "Point or [[x, y], ...]"), port("Lines", "any", "Line or a list of lines"), port("Rects", "any", "Boxes: [x, y, w, h] or {cx, cy, w, h, angle}"),
                port("Sectors", "any", "[{cx, cy, r_in, r_out, start, end}, ...]"), port("Text", "str", "Text to write"), port("Status", "any", "1 / OK for the OK colour")],
        outputs=[img(), val("Count", "Graphics drawn")],
        params={"ok_color": "Green", "ng_color": "Red", "transparency": 0, "text_x": 10, "text_y": 30},
        schema={"ok_color": enum(*COLOURS), "ng_color": enum(*COLOURS), "transparency": num(0, 100, 5, "%", 0), "text_x": num(0, 100000), "text_y": num(0, 100000)})
def graphic_collection(t, ctx):
    from apex_vision.tools.vm_boxes import box_points, to_boxes
    from apex_vision.tools.vm_calib import as_points
    a = get_image(ctx)
    st = ctx.get("Status")
    good = True if st is None else (str(st).strip().upper() in ("OK", "1", "TRUE") or (_floats(st) not in (None, [0.0]) and str(st).strip().upper() not in ("NG", "FALSE")))
    col = COLOURS[str(t.get_param("ok_color") if good else t.get_param("ng_color"))]
    alpha = 1.0 - float(t.get_param("transparency")) / 100.0
    over: List[Dict[str, Any]] = []
    if ctx.get("Points") is not None:
        p1 = ctx.get("Points")
        pts = as_points(p1) if not (isinstance(p1, (tuple, list)) and len(p1) == 2 and not isinstance(p1[0], (list, tuple))) else as_points([p1])
        if pts is None:
            return err("the points are not (x, y) pairs")
        over += [g.cross_overlay(x, y, col, 6) for x, y in pts]
    if ctx.get("Lines") is not None:
        raw = ctx.get("Lines")
        lines = [raw] if isinstance(raw, dict) or (isinstance(raw, (list, tuple)) and raw and not isinstance(raw[0], (dict, list, tuple))) else raw
        for l in lines or []:
            ll = t.as_line(l)
            if ll is None:
                return err("a line is not [x1, y1, x2, y2] or a line result")
            over.append(g.line_overlay(g.line_to_dict(*ll), col))
    if ctx.get("Rects") is not None:
        for b in to_boxes(ctx.get("Rects")):
            pts = box_points(b)
            xs, ys = pts[:, 0], pts[:, 1]
            item = {"type": "rect", "box": [int(xs.min()), int(ys.min()), int(xs.max() - xs.min()), int(ys.max() - ys.min())], "color": col}
            if alpha < 1.0:
                item["alpha"] = 1.0 - alpha if alpha > 0 else 0.0
            over.append(item)
            if abs(b.get("angle", 0.0)) > 1e-6:                                              # a turned box: draw its true outline too
                over += [{"type": "line", "pt1": (int(pts[i][0]), int(pts[i][1])), "pt2": (int(pts[(i + 1) % 4][0]), int(pts[(i + 1) % 4][1])), "color": col, "thickness": 2} for i in range(4)]
    if ctx.get("Sectors") is not None:
        raw = ctx.get("Sectors")
        for s in ([raw] if isinstance(raw, dict) else raw) or []:
            try:
                over.append({"type": "sector", "center": (int(s["cx"]), int(s["cy"])), "r_in": int(s.get("r_in", 0)), "r_out": int(s["r_out"]), "start": float(s.get("start", 0)),
                             "end": float(s.get("end", 360)), "color": col})
            except (KeyError, TypeError, ValueError):
                return err("a sector needs cx, cy and r_out")
    if ctx.get("Text") is not None:
        over.append({"type": "text", "text": stringify(ctx.get("Text")), "pt": (int(t.get_param("text_x")), int(t.get_param("text_y"))), "color": col})
    fn = ok if good else ng
    return fn(f"{len(over)} graphic(s)", over, Image=a, Count=len(over))


# ---------------------------------------------------------------------------------------------------------------------------
# Send Data / Receive Data
# ---------------------------------------------------------------------------------------------------------------------------
@define("Send Data", COMM,
        "Puts a result where other flows or modules can pick it up: into a named global variable, or onto a named queue (first in, first out). "
        "To send to a PLC, robot or computer use TCP Send, UDP Send, Serial Send or Modbus TCP Write.",
        inputs=[port("Data", "any", "What to send"), port("Trigger", "any", "Sends only when this is not 0 (optional)")],
        outputs=[val("Sent", "1 when sent"), val("Queue_Length", "Items on the queue afterwards")],
        params={"target": "Global Variable", "name": "result", "queue_length": 1000},
        schema={"target": enum("Global Variable", "Data Queue", "Communication Device"), "name": {"kind": "text", "hint": "name of the variable or queue"}, "queue_length": num(1, 1_000_000)})
def send_data(t, ctx):
    name = str(t.get_param("name") or "").strip()
    if not name:
        return err("no name chosen: type the name of the variable or queue")
    trig = ctx.get("Trigger")
    if trig is not None and _floats(trig) in (None, [0.0]) and str(trig).strip().lower() in ("", "0", "false", "none"):
        return ok("not sent: the trigger is off", Sent=0, Queue_Length=dataqueue.size(name))
    if ctx.get("Data") is None:
        return err("nothing to send: connect the data")
    if str(t.get_param("target")) == "Global Variable":
        _globals(ctx)[name] = ctx.get("Data")
        return ok(f"global variable {name} set", Sent=1, Queue_Length=0)
    if str(t.get_param("target")) == "Communication Device":
        from apex_vision.core import comm_manager
        bad = comm_manager.get_manager().send(name, stringify(ctx.get("Data")))
        return err(bad, Sent=0, Queue_Length=0) if bad else ok(f"sent to device {name}", Sent=1, Queue_Length=0)
    n = dataqueue.push(name, ctx.get("Data"), int(t.get_param("queue_length")))
    return ok(f"queue {name} now holds {n}", Sent=1, Queue_Length=n)


@define("Receive Data", COMM,
        "Takes data from a named global variable or queue (the oldest item, or just a look at it), or from a fixed text for testing.",
        inputs=[port("Trigger", "any", "Connect to take data after another module ran")],
        outputs=[port("Data", "any", "What was received"), port("Text", "str", "The data as text"), val("Has_Data", "1 when something was there"), val("Queue_Length")],
        params={"source": "Global Variable", "name": "result", "take": "Remove", "test_text": ""},
        schema={"source": enum("Global Variable", "Data Queue", "Communication Device", "Test Text"), "name": {"kind": "text", "hint": "name of the variable or queue"}, "take": enum("Remove", "Keep"),
                "test_text": {"kind": "text", "hint": "text to receive when the source is Test Text"}})
def receive_data(t, ctx):
    src = str(t.get_param("source"))
    if src == "Test Text":
        txt = str(t.get_param("test_text") or "")
        return ok(f"{len(txt)} character(s)", Data=txt, Text=txt, Has_Data=1 if txt else 0, Queue_Length=0)
    name = str(t.get_param("name") or "").strip()
    if not name:
        return err("no name chosen: type the name of the variable or queue")
    if src == "Global Variable":
        gv = _globals(ctx)
        if name not in gv:
            return ng(f"no global variable called {name}", Has_Data=0, Queue_Length=0)
        d = gv[name]
        return ok(f"read global variable {name}", Data=d, Text=stringify(d), Has_Data=1, Queue_Length=0)
    if src == "Communication Device":
        from apex_vision.core import comm_manager
        name = comm_manager.queue_name(name)
    d = dataqueue.pop(name) if str(t.get_param("take")) == "Remove" else dataqueue.peek(name)
    if d is None:
        return ng(f"queue {name} is empty", Has_Data=0, Queue_Length=dataqueue.size(name))
    return ok(f"received from queue {name}", Data=d, Text=stringify(d), Has_Data=1, Queue_Length=dataqueue.size(name))


# ---------------------------------------------------------------------------------------------------------------------------
# Protocol Parsing / Assembly
# ---------------------------------------------------------------------------------------------------------------------------
BYTE_TYPES = {"i8": "b", "u8": "B", "i16": "h", "u16": "H", "i32": "i", "u32": "I", "i64": "q", "u64": "Q", "float": "f", "double": "d"}
PARSE_SCRIPT = "def parse(text):\n    # return the values as a list, e.g. split the text and convert\n    return [float(p) for p in text.split(';')]\n"
ASSEMBLE_SCRIPT = "def assemble(values):\n    # return the text to send\n    return ';'.join(str(v) for v in values)\n"


def _fields(spec: str) -> Optional[List[Tuple[str, str]]]:
    out = []
    for part in [p.strip() for p in str(spec or "").split(",") if p.strip()]:
        name, _, typ = part.partition(":")
        typ = (typ or name).strip().lower()
        if typ not in BYTE_TYPES:
            return None
        out.append((name.strip() if ":" in part else f"v{len(out) + 1}", typ))
    return out or None


def _run_script(code: str, fn: str, arg: Any) -> Any:
    env: Dict[str, Any] = {}
    run_with_deadline(compile(code, "<protocol>", "exec"), env, 2.0)
    if fn not in env or not callable(env[fn]):
        raise ValueError(f"the script must define {fn}(...)")
    box: Dict[str, Any] = {}

    def call():
        box["r"] = env[fn](arg)
    run_with_deadline(compile("call()", "<protocol>", "exec"), {"call": call}, 2.0)
    return box["r"]


def _typed(p: str):
    try:
        f = float(p)
        return int(f) if f.is_integer() and re.fullmatch(r"\s*[-+]?\d+\s*", p) else f
    except ValueError:
        return p.strip()


@define("Protocol Parsing", COMM,
        "Turns a received message into separate values. Text parsing splits at a symbol (1;123;234 becomes 1, 123 and 234); byte parsing reads "
        "numbers of a given size out of hex text (0000006400000005 with i32,i32 becomes 100 and 5); script parsing runs your parse(text) function.",
        inputs=[port("Text", "str", "The received message")],
        outputs=[port("Values", "any", "All the values"), val("Count")] + [port(f"Value{i}", "any") for i in range(1, 9)],
        params={"mode": "Text", "split_symbol": ";", "trim": True, "fields": "i32,i32", "byte_order": "Big-endian", "input_format": "Hex", "script": PARSE_SCRIPT},
        schema={"mode": enum("Text", "Byte", "Script"), "split_symbol": {"kind": "text", "hint": "what separates the values"}, "trim": {"kind": "bool"},
                "fields": {"kind": "text", "hint": "types in order: i8 u8 i16 u16 i32 u32 i64 u64 float double, as 'name:type' or 'type', separated by commas"},
                "byte_order": enum("Big-endian", "Little-endian"), "input_format": enum("Hex", "ASCII"), "script": {"kind": "code"}})
def protocol_parsing(t, ctx):
    raw = ctx.get("Text")
    if raw is None:
        return err("no message to parse: connect the text")
    text = raw.decode("latin-1") if isinstance(raw, (bytes, bytearray)) else str(raw)
    mode = str(t.get_param("mode"))
    if mode == "Text":
        sym = decode_escapes(str(t.get_param("split_symbol")))
        if not sym:
            return err("no split symbol chosen: type what separates the values")
        parts = text.split(sym)
        if bool(t.get_param("trim")):
            parts = [p.strip() for p in parts]
        parts = [p for p in parts if p != ""] if bool(t.get_param("trim")) else parts
        values = [_typed(p) for p in parts]
    elif mode == "Byte":
        fields = _fields(str(t.get_param("fields")))
        if fields is None:
            return err("the fields must be types like i32, u16 or float, separated by commas")
        if str(t.get_param("input_format")) == "Hex":
            clean = re.sub(r"[\s,]|0x", "", text)
            try:
                data = bytes.fromhex(clean)
            except ValueError:
                return err("the message is not hexadecimal text")
        else:
            data = text.encode("latin-1", "replace")
        order = ">" if str(t.get_param("byte_order")).startswith("Big") else "<"
        fmt = order + "".join(BYTE_TYPES[tp] for _, tp in fields)
        if struct.calcsize(fmt) > len(data):
            return ng(f"the message has {len(data)} byte(s) but the fields need {struct.calcsize(fmt)}")
        values = list(struct.unpack(fmt, data[:struct.calcsize(fmt)]))
    else:
        try:
            values = _run_script(str(t.get_param("script")), "parse", text)
        except ScriptTimeout:
            return err("the parsing script ran too long and was stopped")
        except Exception as e:  # noqa: BLE001 - the user's script can fail in any way; report it
            return err(f"the parsing script failed: {e}")
        values = list(values.values()) if isinstance(values, dict) else list(values) if isinstance(values, (list, tuple)) else [values]
    outs = {f"Value{i + 1}": (values[i] if i < len(values) else None) for i in range(8)}
    if not values:
        return ng("nothing could be read from the message", Values=[], Count=0, **outs)
    return ok(f"{len(values)} value(s): " + ", ".join(stringify(v) for v in values[:6]), Values=values, Count=len(values), **outs)


@define("Protocol Assembly", COMM,
        "Builds a message from values - the reverse of Protocol Parsing. Text assembly joins them with a symbol; byte assembly packs numbers of a "
        "given size into hex text; script assembly runs your assemble(values) function.",
        inputs=[port("Values", "any", "A list of values")] + [port(f"Value{i}", "any") for i in range(1, 9)],
        outputs=[port("Text", "str", "The message"), val("Length")],
        params={"mode": "Text", "split_symbol": ";", "end_char": "", "fields": "i32,i32", "byte_order": "Big-endian", "script": ASSEMBLE_SCRIPT},
        schema={"mode": enum("Text", "Byte", "Script"), "split_symbol": {"kind": "text", "hint": "put between the values"}, "end_char": {"kind": "text", "hint": "\\r, \\n or \\r\\n at the end"},
                "fields": {"kind": "text", "hint": "types in order: i8 u8 i16 u16 i32 u32 i64 u64 float double, separated by commas"},
                "byte_order": enum("Big-endian", "Little-endian"), "script": {"kind": "code"}})
def protocol_assembly(t, ctx):
    vals: List[Any]
    if ctx.get("Values") is not None:
        v = ctx.get("Values")
        vals = list(v) if isinstance(v, (list, tuple, np.ndarray)) else [v]
    else:
        vals = [ctx.get(f"Value{i}") for i in range(1, 9)]
        while vals and vals[-1] is None:
            vals.pop()
    if not vals or any(v is None for v in vals):
        return err("no values to assemble: connect them, in order and without gaps")
    mode = str(t.get_param("mode"))
    if mode == "Text":
        text = decode_escapes(str(t.get_param("split_symbol"))).join(stringify(v) for v in vals)
    elif mode == "Byte":
        fields = _fields(str(t.get_param("fields")))
        if fields is None:
            return err("the fields must be types like i32, u16 or float, separated by commas")
        if len(vals) < len(fields):
            return err(f"{len(fields)} values are needed but {len(vals)} were given")
        order = ">" if str(t.get_param("byte_order")).startswith("Big") else "<"
        try:
            data = struct.pack(order + "".join(BYTE_TYPES[tp] for _, tp in fields), *[(float(v) if tp in ("float", "double") else int(float(v))) for v, (_, tp) in zip(vals, fields)])
        except (struct.error, TypeError, ValueError, OverflowError) as e:
            return err(f"a value does not fit its field: {e}")
        text = data.hex().upper()
    else:
        try:
            text = _run_script(str(t.get_param("script")), "assemble", vals)
        except ScriptTimeout:
            return err("the assembly script ran too long and was stopped")
        except Exception as e:  # noqa: BLE001
            return err(f"the assembly script failed: {e}")
        text = stringify(text)
    text += decode_escapes(str(t.get_param("end_char") or ""))
    return ok(f"{len(text)} character(s)", Text=text, Length=len(text))
