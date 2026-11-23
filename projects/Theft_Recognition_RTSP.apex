<?xml version='1.0' encoding='utf-8'?>
<ApexSolution version="4.3" name="Theft_Recognition_RTSP" active_flow="RTSP_Theft_Cam1" trigger_flow="RTSP_Theft_Cam1">
  <GlobalVariables>
    <Variable name="g_CountOK" type="int">0</Variable>
    <Variable name="g_CountNG" type="int">0</Variable>
    <Variable name="g_LotNumber" type="str">LOT-2026-A1</Variable>
    <Variable name="g_TriggerEnable" type="bool">true</Variable>
  </GlobalVariables>
  <Flows>
    <ApexFlow version="4.3" name="RTSP_Theft_Cam1">
      <Properties>
        <Property name="enabled" type="bool">true</Property>
        <Property name="run_interval_ms" type="float">125.0</Property>
        <Property name="stop_on_ng" type="bool">false</Property>
        <Property name="flow_timeout_ms" type="float">5000.0</Property>
        <Property name="execution_count" type="int">0</Property>
      </Properties>
      <Nodes>
        <Node instance_id="node_rtsp_cam1" tool_name="Image Source" name="01_RTSP_Camera" category="Acquisition" enabled="true">
          <Parameters>
            <Parameter name="source_type" type="str">IP Stream</Parameter>
            <Parameter name="file_path" type="str">C:\Users\winch\Downloads\VMClone\apex_vision\samples\pcb_sample.png</Parameter>
            <Parameter name="pattern_type" type="str">Part with Defects</Parameter>
            <Parameter name="color_mode" type="str">BGR</Parameter>
            <Parameter name="camera_device" type="str">mvs_gige_0</Parameter>
            <Parameter name="camera_index" type="int">0</Parameter>
            <Parameter name="auto_exposure" type="bool">true</Parameter>
            <Parameter name="exposure_time_us" type="float">20000.0</Parameter>
            <Parameter name="gain" type="float">1.0</Parameter>
            <Parameter name="trigger_mode" type="str">Continuous</Parameter>
            <Parameter name="mvs_config_file" type="str" />
            <Parameter name="mvs_trigger_source" type="str">Software</Parameter>
            <Parameter name="stream_url" type="str">rtsp://192.168.1.64:554/ch1/main</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_roi_zones" tool_name="ROI Zone Manager" name="01b_ROI_Zones" category="ROI &amp; Zones" enabled="true">
          <Parameters>
            <Parameter name="zones" type="json">[{"name": "shelf", "rect": [1866, 11, 978, 1491]}, {"name": "aisle", "rect": [1511, 550, 435, 969]}]</Parameter>
            <Parameter name="draw_overlays" type="bool">true</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_bag_detector" tool_name="Object Detection" name="02_Bag_Detector" category="Deep Learning" enabled="true">
          <Parameters>
            <Parameter name="model_path" type="str">yolo11n.onnx</Parameter>
            <Parameter name="confidence" type="float">0.25</Parameter>
            <Parameter name="iou" type="float">0.45</Parameter>
            <Parameter name="classes" type="str">backpack,handbag,suitcase,cell phone,bottle</Parameter>
            <Parameter name="device" type="str">auto</Parameter>
            <Parameter name="max_detections" type="int">100</Parameter>
            <Parameter name="roi" type="json">[0, 0, 0, 0]</Parameter>
            <Parameter name="labels" type="str" />
            <Parameter name="save_in_solution" type="bool">false</Parameter>
            <Parameter name="model_data" type="json">{}</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_yolo_pose" tool_name="YOLO Pose" name="03_YOLO_Pose" category="Theft Recognition" enabled="true">
          <Parameters>
            <Parameter name="model_path" type="str">yolo11n-pose.pt</Parameter>
            <Parameter name="confidence" type="float">0.35</Parameter>
            <Parameter name="iou" type="float">0.5</Parameter>
            <Parameter name="device" type="str">auto</Parameter>
            <Parameter name="draw_skeleton" type="bool">true</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_botsort" tool_name="BoT-SORT Tracker" name="04_BoTSORT_Tracker" category="Theft Recognition" enabled="true">
          <Parameters>
            <Parameter name="tracker_type" type="str">botsort.yaml</Parameter>
            <Parameter name="frame_rate" type="int">8</Parameter>
            <Parameter name="device" type="str">auto</Parameter>
            <Parameter name="enable_reid" type="bool">true</Parameter>
            <Parameter name="draw_trails" type="bool">true</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_behavior_script" tool_name="Script" name="05_Behavior_Gate_Grid" category="Logic Tools" enabled="true">
          <Parameters>
            <Parameter name="code" type="str"># Script 1: Dual-Trigger Behavioral Gate + Localized Shelf Delta + Shared Cross-Cam Pickup Sheet
# Inputs : Image, Val1=Timestamp (sec), Data1=Tracks (BoT-SORT), Data2=Context Detections, Data3=Named_ROIs or shelf ROI, Data4=aisle ROI
# Outputs: Image (2x3 grid on dispatch), Sequence_Frames (up to 12 JPEGs; Image #1 = ref sheet on shelf_free_tuck), Data/Result, Trigger (bool)

img = context.get("Image")
tracks = context.get("Data1") or []
bags_raw = context.get("Data2") or []
raw_d3 = context.get("Data3")
raw_d4 = context.get("Data4")
raw_ts = context.get("Val1")

outputs["Image"] = img
outputs["Sequence_Frames"] = []
outputs["Trigger"] = False
outputs["Status"] = "OK"
outputs["Data"] = {}
outputs["Result"] = {}

DWELL_SEC = 1.2
BUFFER_SEC = 10.0
SAMPLE_SEC = 0.35
TUCK_WIN_SEC = 7.0
MERCH_TTL_SEC = 60.0
PICKUP_POOL_TTL = 120.0
BASKET_LATCH_FRAMES = 3
BAG_STUFF_HOLD_SEC = 0.50
GARMENT_HOLD_SEC = 0.70
CROUCH_HOLD_SEC = 0.60
BLADE_DROP = 0.40
CROUCH_DROP = 0.28
RELEASE_WAIT_SEC = 3.5
ID_LOSS_GRACE_SEC = 0.8
COOLDOWN_SEC = 12.0
MIN_FRAMES = 4
TILE_PX = 384

_BENIGN_VESSELS = {"shopping basket", "shopping cart", "basket", "cart"}
_PHONE_CLASSES = {"cell phone", "smartphone", "phone"}

def _parse_roi(val, w, h):
    if isinstance(val, dict):
        val = val.get("rect") or val.get("box")
    if not isinstance(val, (list, tuple)) or len(val) &lt; 4:
        return None
    x, y, rw, rh = [int(round(float(v))) for v in val[:4]]
    if rw &lt;= 0 or rh &lt;= 0:
        return None
    x1 = max(0, min(w - 1, x))
    y1 = max(0, min(h - 1, y))
    x2 = max(x1 + 1, min(w, x + rw))
    y2 = max(y1 + 1, min(h, y + rh))
    return (x1, y1, x2 - x1, y2 - y1)

def _clamp_rect(x1, y1, x2, y2, w, h):
    cx1 = max(0, min(w - 1, int(x1)))
    cy1 = max(0, min(h - 1, int(y1)))
    cx2 = max(cx1, min(w, int(x2)))
    cy2 = max(cy1, min(h, int(y2)))
    return (cx1, cy1, cx2, cy2) if cx2 &gt; cx1 and cy2 &gt; cy1 else None

def _derive_hr(aisle_rois, shelf_rois, w, h):
    if aisle_rois:
        return aisle_rois
    out = []
    for sx, sy, sw, sh in shelf_rois:
        px, py = max(80, int(sw * 0.85)), max(60, int(sh * 0.45))
        x1, y1 = max(0, sx - px), max(0, sy - py // 2)
        x2, y2 = min(w, sx + sw + px), min(h, sy + sh + py)
        out.append((x1, y1, max(1, x2 - x1), max(1, y2 - y1)))
    return out

def _pt_in_any(px, py, rois, pad=0):
    for rx, ry, rw, rh in rois:
        if (rx - pad) &lt;= px &lt;= (rx + rw + pad) and (ry - pad) &lt;= py &lt;= (ry + rh + pad):
            return True
    return False

def _in_hr(bbox, rois):
    if not rois:
        return True
    x, y, bw, bh = bbox
    cx = x + bw * 0.5
    return _pt_in_any(cx, y + bh * 0.55, rois) or _pt_in_any(cx, y + bh * 0.92, rois)

def _boxes_close(b1, b2, m=36):
    x1, y1, w1, h1 = b1
    x2, y2, w2, h2 = b2
    return not (x1 + w1 + m &lt; x2 or x2 + w2 + m &lt; x1 or y1 + h1 + m &lt; y2 or y2 + h2 + m &lt; y1)

def _enc_jpg(arr, max_dim=640, q=85):
    ah, aw = arr.shape[:2]
    if max(ah, aw) &gt; max_dim:
        s = max_dim / float(max(ah, aw))
        arr = cv2.resize(arr, (max(1, int(aw * s)), max(1, int(ah * s))))
    ok, buf = cv2.imencode(".jpg", arr, [int(cv2.IMWRITE_JPEG_QUALITY), q])
    return buf.tobytes() if ok else b""

def _dec_jpg(raw):
    return cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR) if raw else None

def _crop_person(arr, x, y, bw, bh, w, h):
    if arr is None or bw &lt;= 0 or bh &lt;= 0:
        return None
    px, py = max(16, int(round(bw * 0.14))), max(12, int(round(bh * 0.08)))
    x1, y1 = max(0, x - px), max(0, y - py)
    x2, y2 = min(w, x + bw + px), min(h, y + bh + py)
    return arr[y1:y2, x1:x2].copy() if x2 &gt; x1 and y2 &gt; y1 else None

def _upper_hist(crop_bgr):
    if crop_bgr is None or not isinstance(crop_bgr, np.ndarray) or crop_bgr.ndim &lt; 3 or crop_bgr.shape[2] &lt; 3:
        return None
    h, w = crop_bgr.shape[:2]
    if h &lt; 12 or w &lt; 12:
        return None
    y1, y2 = max(0, int(round(h * 0.12))), min(h, max(4, int(round(h * 0.55))))
    x1, x2 = max(0, int(round(w * 0.15))), min(w, max(4, int(round(w * 0.85))))
    torso = crop_bgr[y1:y2, x1:x2]
    if torso.size == 0:
        return None
    hsv = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [12, 8], [0, 180, 0, 256]).astype(np.float32).flatten()
    norm = float(np.linalg.norm(hist))
    return (hist / norm) if norm &gt; 1e-6 else None

def _hist_sim(a, b):
    if a is None or b is None:
        return 0.0
    try:
        if len(a) != len(b):
            return 0.0
        return max(0.0, min(1.0, float(np.dot(a, b))))
    except Exception:
        return 0.0

def _pool_get():
    try:
        items = get_global("g_RecentPickups")
        return list(items) if isinstance(items, list) else []
    except Exception:
        return []

def _pool_set(items):
    try:
        set_global("g_RecentPickups", items)
    except Exception:
        pass

def _record_global_pickup(cam_id, tid, now_ts, crop_bgr, shelf_zone, d_score, hist):
    jpg = _enc_jpg(crop_bgr, max_dim=288, q=80)
    if not jpg:
        return
    pool = [e for e in _pool_get() if isinstance(e, dict) and (0.0 &lt;= (now_ts - float(e.get("ts", -1e9))) &lt;= PICKUP_POOL_TTL or abs(now_ts - float(e.get("ts", -1e9))) &lt;= 2.0)]
    entry = {
        "camera_id": str(cam_id),
        "track_id": int(tid),
        "ts": float(now_ts),
        "crop_jpeg": jpg,
        "shelf_zone": str(shelf_zone or "shelf"),
        "delta_score": float(d_score),
        "upper_color_hist": hist.tolist() if isinstance(hist, np.ndarray) else hist,
        "resolution": "pending",
    }
    replaced = False
    for idx, ex in enumerate(pool):
        if ex.get("camera_id") == entry["camera_id"] and int(ex.get("track_id", -1)) == entry["track_id"] and abs(now_ts - float(ex.get("ts", -1e9))) &lt;= 6.0:
            if ex.get("resolution") == "carried_openly":
                entry["resolution"] = "carried_openly"
            pool[idx] = entry
            replaced = True
            break
    if not replaced:
        pool.append(entry)
    pool.sort(key=lambda e: float(e.get("ts", 0.0)), reverse=True)
    _pool_set(pool[:24])

def _build_global_ref_sheet(now_ts, query_hist=None, max_tiles=6, tile_px=240):
    pool = [
        e for e in _pool_get()
        if isinstance(e, dict)
        and e.get("resolution") != "returned"
        and e.get("crop_jpeg")
        and (0.0 &lt;= (now_ts - float(e.get("ts", -1e9))) &lt;= PICKUP_POOL_TTL or abs(now_ts - float(e.get("ts", -1e9))) &lt;= 2.0)
    ]
    if not pool:
        return None, []
    q_arr = np.asarray(query_hist, dtype=np.float32) if query_hist is not None else None
    scored = []
    if len(pool) &lt;= max_tiles:
        for e in pool:
            eh = np.asarray(e["upper_color_hist"], dtype=np.float32) if e.get("upper_color_hist") is not None else None
            scored.append((float(e["ts"]), e, _hist_sim(q_arr, eh)))
        scored.sort(key=lambda it: it[0], reverse=True)
    else:
        for e in pool:
            age = max(0.0, now_ts - float(e["ts"]))
            rec = max(0.0, 1.0 - (age / PICKUP_POOL_TTL))
            eh = np.asarray(e["upper_color_hist"], dtype=np.float32) if e.get("upper_color_hist") is not None else None
            sim = _hist_sim(q_arr, eh)
            scored.append((0.60 * rec + 0.40 * sim, e, sim))
        scored.sort(key=lambda it: (it[0], float(it[1]["ts"])), reverse=True)

    sel = scored[:max_tiles]
    n = len(sel)
    cols = 2 if n &lt;= 4 else 3
    rows = 1 if n &lt;= 2 else 2
    banner_h, label_h = 28, 22
    canvas = np.full((banner_h + rows * tile_px, cols * tile_px, 3), (20, 24, 32), dtype=np.uint8)
    cv2.rectangle(canvas, (0, 0), (cols * tile_px, banner_h), (29, 36, 48), -1)
    cv2.putText(canvas, f"RECENT STORE PICKUPS (LAST {int(PICKUP_POOL_TTL)}s) - REF SHEET", (10, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (240, 244, 248), 1, cv2.LINE_AA)
    meta = []
    for idx, (_, e, sim) in enumerate(sel):
        r, c = idx // cols, idx % cols
        x0, y0 = c * tile_px, banner_h + r * tile_px
        im = _dec_jpg(e["crop_jpeg"])
        ih_max, iw_max = tile_px - label_h - 4, tile_px - 4
        if im is not None and im.size &gt; 0:
            ih, iw = im.shape[:2]
            sc = min(float(iw_max) / float(max(1, iw)), float(ih_max) / float(max(1, ih)))
            nw, nh = max(1, int(round(iw * sc))), max(1, int(round(ih * sc)))
            rsz = cv2.resize(im, (nw, nh))
            px, py = x0 + 2 + (iw_max - nw) // 2, y0 + label_h + 2 + (ih_max - nh) // 2
            canvas[py:py + nh, px:px + nw] = rsz
        is_open = e.get("resolution") == "carried_openly"
        cv2.rectangle(canvas, (x0, y0), (x0 + tile_px - 1, y0 + label_h), (22, 85, 58) if is_open else (34, 42, 56), -1)
        age_s = max(0, int(round(now_ts - float(e["ts"]))))
        lbl = f"#{idx + 1} {e.get('camera_id', 'cam')} | {age_s}s ago | {str(e.get('shelf_zone', 'shelf'))[:12]}{' OPEN' if is_open else ''}"
        cv2.putText(canvas, lbl[:40], (x0 + 6, y0 + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (245, 248, 252), 1, cv2.LINE_AA)
        cv2.rectangle(canvas, (x0, y0), (x0 + tile_px - 1, y0 + tile_px - 1), (56, 68, 88), 1)
        meta.append({"tile": idx + 1, "camera_id": e.get("camera_id", "cam"), "track_id": int(e.get("track_id", 0)), "age_sec": round(max(0.0, now_ts - float(e["ts"])), 2), "shelf_zone": e.get("shelf_zone", "shelf"), "color_sim": round(sim, 3)})
    ok, buf = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    return (buf.tobytes(), meta) if ok else (None, [])

def _fit_tile(arr, sz, title, color):
    canvas = np.zeros((sz, sz, 3), dtype=np.uint8)
    ah, aw = arr.shape[:2]
    top = 24
    s = min(sz / float(max(1, aw)), (sz - top) / float(max(1, ah)))
    nw, nh = max(1, int(aw * s)), max(1, int(ah * s))
    rsz = cv2.resize(arr, (nw, nh))
    x0 = (sz - nw) // 2
    y0 = top + ((sz - top) - nh) // 2
    canvas[y0:y0 + nh, x0:x0 + nw] = rsz
    cv2.putText(canvas, title, (8, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    return canvas

def _pose_cues(kps, p_bbox, shelf_rois, bag_boxes, basket_boxes, phone_boxes):
    out = {
        "reach_side": "", "touched_shelf_idx": None, "wrist_pts": [],
        "tucked": False, "occluded": False, "in_core_or_bag": False,
        "in_core": False, "in_personal_bag": False, "wrist_open": False, "two_hands_torso": False,
        "in_benign_basket": False, "holding_phone": False, "norm_sh": None,
    }
    if not isinstance(kps, list) or len(kps) &lt; 13:
        return out
    def pt(idx):
        p = kps[idx]
        if not isinstance(p, (list, tuple)) or len(p) &lt; 2:
            return None
        conf = float(p[2]) if len(p) &gt; 2 else 0.9
        x, y = float(p[0]), float(p[1])
        if conf &lt; 0.30 or (x &lt;= 0 and y &lt;= 0):
            return None
        return (x, y)
    ls, rs = pt(5), pt(6)
    le, re = pt(7), pt(8)
    lw, rw = pt(9), pt(10)
    lh, rh = pt(11), pt(12)
    nose = pt(0)
    px, py, pw, ph = p_bbox
    torso_h = max(24.0, ph * 0.42)
    if (ls or rs) and (lh or rh):
        sy = float(np.mean([p[1] for p in (ls, rs) if p is not None]))
        hy = float(np.mean([p[1] for p in (lh, rh) if p is not None]))
        torso_h = max(20.0, abs(hy - sy))
    if ls and rs:
        out["norm_sh"] = abs(ls[0] - rs[0]) / torso_h
    sh_cx = float(np.mean([p[0] for p in (ls, rs) if p is not None])) if (ls or rs) else (px + pw * 0.5)
    sh_cy = float(np.mean([p[1] for p in (ls, rs) if p is not None])) if (ls or rs) else (py + ph * 0.28)
    waist_y = float(np.mean([p[1] for p in (lh, rh) if p is not None])) if (lh or rh) else (py + ph * 0.55)
    reach_sides = []
    for side, wp in (("left", lw), ("right", rw)):
        if wp is None:
            continue
        out["wrist_pts"].append((int(round(wp[0])), int(round(wp[1]))))
        stretch = ((wp[0] - sh_cx) ** 2 + (wp[1] - sh_cy) ** 2) ** 0.5
        if shelf_rois:
            for s_idx, (rx, ry, rws, rhs) in enumerate(shelf_rois):
                if rx &lt;= wp[0] &lt;= rx + rws and ry &lt;= wp[1] &lt;= ry + rhs:
                    reach_sides.append(side)
                    if out["touched_shelf_idx"] is None:
                        out["touched_shelf_idx"] = s_idx
                    break
        elif (
            not _pt_in_any(wp[0], wp[1], bag_boxes)
            and not _pt_in_any(wp[0], wp[1], basket_boxes)
            and wp[1] &lt;= sh_cy + 0.55 * torso_h
            and stretch &gt; max(0.90 * torso_h, 0.50 * pw)
            and abs(wp[0] - sh_cx) &gt; max(0.85 * pw, 0.90 * torso_h)
        ):
            reach_sides.append(side)
    if reach_sides:
        out["reach_side"] = "+".join(reach_sides)
    torso_arms = 0
    for side, wp in (("left", lw), ("right", rw)):
        if wp is None:
            continue
        in_basket = _pt_in_any(wp[0], wp[1], basket_boxes, pad=10)
        on_phone = _pt_in_any(wp[0], wp[1], phone_boxes, pad=14)
        in_bag = _pt_in_any(wp[0], wp[1], bag_boxes)
        in_core = abs(wp[0] - sh_cx) &lt;= max(28.0, 0.36 * pw) and (sh_cy - 10.0) &lt;= wp[1] &lt;= (waist_y + 0.25 * torso_h)
        if in_core or in_bag:
            torso_arms += 1
        elif not in_basket and not on_phone:
            out["wrist_open"] = True
        if side in reach_sides:
            out["wrist_open"] = True
            continue
        if in_basket and not in_bag:
            out["in_benign_basket"] = True
            continue
        if on_phone and not in_bag:
            out["holding_phone"] = True
        if in_bag:
            out["in_personal_bag"] = True
        if in_core and not on_phone:
            out["in_core"] = True
        if in_core or in_bag:
            out["in_core_or_bag"] = True
            out["tucked"] = True
    if torso_arms &gt;= 2 or (torso_arms &gt;= 1 and len(out["wrist_pts"]) &lt; 2):
        out["two_hands_torso"] = True
    if shelf_rois or nose is not None:
        for ep, wp in ((le, lw), (re, rw)):
            if ep is not None and wp is None:
                if _pt_in_any(ep[0], ep[1], basket_boxes, pad=14) and not _pt_in_any(ep[0], ep[1], bag_boxes):
                    out["in_benign_basket"] = True
                    continue
                if abs(ep[0] - sh_cx) &lt;= max(35.0, 0.45 * pw) and (sh_cy - 10.0) &lt;= ep[1] &lt;= (waist_y + 0.35 * torso_h):
                    out["occluded"] = True
                    break
    return out

def _measure_patch_delta(pre_p, post_p, eval_mask):
    if int(np.count_nonzero(eval_mask)) &lt; 36:
        return 0.0, False
    pre_vals = pre_p[eval_mask]
    post_vals = post_p[eval_mask]
    pre_std = float(pre_vals.std())
    post_std = float(post_vals.std())
    pre_c = pre_p - float(pre_vals.mean())
    post_c = post_p - float(post_vals.mean())
    changed_int = float(np.mean(np.abs(post_c - pre_c)[eval_mask] &gt; 16.0))
    gx1 = cv2.Sobel(pre_p, cv2.CV_32F, 1, 0, ksize=3)
    gy1 = cv2.Sobel(pre_p, cv2.CV_32F, 0, 1, ksize=3)
    gx2 = cv2.Sobel(post_p, cv2.CV_32F, 1, 0, ksize=3)
    gy2 = cv2.Sobel(post_p, cv2.CV_32F, 0, 1, ksize=3)
    changed_edge = float(np.mean(np.abs(cv2.magnitude(gx2, gy2) - cv2.magnitude(gx1, gy1))[eval_mask] &gt; 20.0))
    if pre_std &gt;= 6.0 and post_std &gt;= 6.0:
        corr = float(np.mean((pre_c[eval_mask] / pre_std) * (post_c[eval_mask] / post_std)))
        std_ratio = abs(post_std - pre_std) / max(12.0, pre_std)
        if corr &gt;= 0.92 and std_ratio &lt; 0.45:
            return 0.0, False
    score = round(0.60 * changed_int + 0.40 * changed_edge, 4)
    confirmed = score &gt;= 0.12 and (changed_int &gt;= 0.08 or changed_edge &gt;= 0.05)
    return score, confirmed

def _shelf_delta_step(frame_bgr, now, shelf_rois, delta_inputs):
    out = {}
    if not shelf_rois:
        for it in delta_inputs:
            out[it["tid"]] = {"status": "no_shelf", "score": 0.0, "confirmed": False}
        return out
    sd = state.setdefault("sd", {"shelves": {}, "episodes": {}, "whist": {}})
    gray = frame_bgr.astype(np.float32) if frame_bgr.ndim == 2 else cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    p_boxes = [it["bbox"] for it in delta_inputs]
    all_wrists = []
    for it in delta_inputs:
        tid = it["tid"]
        wpts = it["wrists"]
        for wp in wpts:
            all_wrists.append((tid, wp))
        wh = sd["whist"].setdefault(tid, deque(maxlen=24))
        wh.append((now, wpts))
        while wh and (now - wh[0][0]) &gt; 1.2:
            wh.popleft()

    cur_grays, occ_masks = {}, {}
    for s_idx, (sx, sy, sw, sh) in enumerate(shelf_rois):
        cur_p = gray[sy:sy + sh, sx:sx + sw]
        if cur_p.size == 0:
            continue
        sst = sd["shelves"].get(s_idx)
        if sst is None or sst["rect"] != (sx, sy, sw, sh) or sst["bg"].shape != (sh, sw):
            sst = {"rect": (sx, sy, sw, sh), "bg": np.zeros((sh, sw), dtype=np.float32), "val": np.zeros((sh, sw), dtype=np.uint8), "ring": deque(maxlen=16)}
            sd["shelves"][s_idx] = sst
        occ = np.zeros((sh, sw), dtype=np.uint8)
        for bx, by, bw, bh in p_boxes:
            cl = _clamp_rect(bx - 10 - sx, by - 10 - sy, bx + bw + 10 - sx, by + bh + 10 - sy, sw, sh)
            if cl is not None:
                occ[cl[1]:cl[3], cl[0]:cl[2]] = 1
        for _, (wx, wy) in all_wrists:
            cl = _clamp_rect(wx - 24 - sx, wy - 24 - sy, wx + 25 - sx, wy + 25 - sy, sw, sh)
            if cl is not None:
                occ[cl[1]:cl[3], cl[0]:cl[2]] = 1
        clean = occ == 0
        if np.any(clean):
            first = clean &amp; (sst["val"] == 0)
            if np.any(first):
                sst["bg"][first] = cur_p[first]
                sst["val"][first] = 1
            upd = clean &amp; (sst["val"] &gt; 0)
            if np.any(upd):
                sst["bg"][upd] = 0.95 * sst["bg"][upd] + 0.05 * cur_p[upd]
        if (not sst["ring"] or (now - sst["ring"][-1][0]) &gt;= 0.25) and np.any(sst["val"] &gt; 0):
            sst["ring"].append((now, sst["bg"].copy(), sst["val"].copy()))
        cur_grays[s_idx] = cur_p
        occ_masks[s_idx] = occ

    for it in delta_inputs:
        tid = it["tid"]
        bw = it["bbox"][2]
        wpts = it["wrists"]
        reach_active = it["reach_active"]
        t_idx = it["touched_shelf_idx"]
        ep = sd["episodes"].get(tid)
        if reach_active and t_idx is not None and 0 &lt;= t_idx &lt; len(shelf_rois):
            s_idx = int(t_idx)
            sx, sy, sw, sh = shelf_rois[s_idx]
            in_w = [(wx, wy) for wx, wy in wpts if sx &lt;= wx &lt; sx + sw and sy &lt;= wy &lt; sy + sh]
            if len(in_w) &gt; 1:
                in_w.sort(key=lambda p: min(p[0] - sx, sx + sw - p[0], p[1] - sy, sy + sh - p[1]), reverse=True)
                anc = in_w[0]
                in_w = [p for p in in_w if abs(p[0] - anc[0]) &lt;= 80 and abs(p[1] - anc[1]) &lt;= 80]
            if in_w and (ep is None or ep["s_idx"] != s_idx or ep["status"] != "confirmed"):
                r = max(22, min(64, int(bw * 0.30)))
                sst = sd["shelves"].get(s_idx)
                if ep is None or ep["s_idx"] != s_idx:
                    if sst is None:
                        continue
                    ring = sst["ring"]
                    chosen = None
                    for entry in ring:
                        if entry[0] &lt;= now - 0.65:
                            chosen = entry
                    if chosen is not None:
                        p_bg, p_val = chosen[1].copy(), chosen[2].copy()
                    elif ring:
                        p_bg, p_val = ring[0][1].copy(), ring[0][2].copy()
                    else:
                        p_bg, p_val = sst["bg"].copy(), sst["val"].copy()
                    missing = p_val == 0
                    if np.any(missing):
                        for _, r_bg, r_val in reversed(ring):
                            fill = missing &amp; (r_val &gt; 0)
                            if np.any(fill):
                                p_bg[fill] = r_bg[fill]
                                p_val[fill] = 1
                                missing = p_val == 0
                                if not np.any(missing):
                                    break
                    ep = {"s_idx": s_idx, "rect": None, "pre_bg": p_bg, "pre_val": p_val, "last_ts": now, "contested": False, "streak": 0, "status": "pending", "score": 0.0, "confirmed": False}
                    sd["episodes"][tid] = ep
                ep["last_ts"] = now
                ep["streak"] = 0
                for wx0, wy0 in in_w:
                    lx, ly = wx0 - sx, wy0 - sy
                    nb = _clamp_rect(lx - r, ly - r, lx + r + 1, ly + r + 1, sw, sh)
                    if nb is None:
                        continue
                    cur_tr = ep["rect"]
                    if cur_tr is None:
                        tr = nb
                    else:
                        ux1, uy1, ux2, uy2 = min(cur_tr[0], nb[0]), min(cur_tr[1], nb[1]), max(cur_tr[2], nb[2]), max(cur_tr[3], nb[3])
                        if (ux2 - ux1) &gt; 150:
                            cx = max(0, min(sw, lx))
                            ux1 = max(0, cx - 75)
                            ux2 = min(sw, ux1 + 150)
                        if (uy2 - uy1) &gt; 150:
                            cy = max(0, min(sh, ly))
                            uy1 = max(0, cy - 75)
                            uy2 = min(sh, uy1 + 150)
                        tr = _clamp_rect(ux1, uy1, ux2, uy2, sw, sh) or cur_tr
                    ep["rect"] = tr
                    ex1, ey1, ex2, ey2 = sx + tr[0] - 16, sy + tr[1] - 16, sx + tr[2] + 16, sy + tr[3] + 16
                    for otid, oh in sd["whist"].items():
                        if otid == tid:
                            continue
                        for ots, opts in oh:
                            if (now - ots) &lt;= 1.2 and any(ex1 &lt;= owx &lt;= ex2 and ey1 &lt;= owy &lt;= ey2 for owx, owy in opts):
                                ep["contested"] = True
                                ep["status"] = "contested_multi_person"
                                ep["confirmed"] = False
                                break
        ep = sd["episodes"].get(tid)
        if ep is None or ep.get("rect") is None:
            out[tid] = {"status": "none", "score": 0.0, "confirmed": False}
            continue
        s_idx = ep["s_idx"]
        sx, sy, sw, sh = shelf_rois[s_idx]
        tx1, ty1, tx2, ty2 = ep["rect"]
        ex1, ey1, ex2, ey2 = sx + tx1 - 16, sy + ty1 - 16, sx + tx2 + 16, sy + ty2 + 16
        for otid, owp in all_wrists:
            if otid != tid and ex1 &lt;= owp[0] &lt;= ex2 and ey1 &lt;= owp[1] &lt;= ey2:
                ep["contested"] = True
                ep["status"] = "contested_multi_person"
                ep["confirmed"] = False
                break
        cg, occ = cur_grays.get(s_idx), occ_masks.get(s_idx)
        if not reach_active and ep["status"] != "confirmed" and not ep["contested"] and cg is not None and occ is not None:
            if (now - ep["last_ts"]) &gt;= 0.20:
                unocc = occ[ty1:ty2, tx1:tx2] == 0
                em = unocc &amp; (ep["pre_val"][ty1:ty2, tx1:tx2] &gt; 0)
                if unocc.size &gt; 0 and float(np.mean(unocc)) &gt;= 0.75 and float(np.mean(em)) &gt;= 0.45:
                    ep["streak"] += 1
                    if ep["streak"] &gt;= 2:
                        sc, ok_d = _measure_patch_delta(ep["pre_bg"][ty1:ty2, tx1:tx2], cg[ty1:ty2, tx1:tx2], em)
                        ep["score"] = sc
                        ep["confirmed"] = ok_d
                        ep["status"] = "confirmed" if ok_d else "unchanged"
                        if ok_d:
                            tr_p = (tx1, ty1, tx2, ty2)
                            blocked = any(
                                otid != tid and oep.get("s_idx") == s_idx and oep.get("rect") is not None
                                and not (tr_p[2] &lt;= oep["rect"][0] or oep["rect"][2] &lt;= tr_p[0] or tr_p[3] &lt;= oep["rect"][1] or oep["rect"][3] &lt;= tr_p[1])
                                for otid, oep in sd["episodes"].items()
                            )
                            if not blocked and np.any(unocc):
                                sst_cur = sd["shelves"].get(s_idx)
                                if sst_cur is not None:
                                    bgs = sst_cur["bg"][ty1:ty2, tx1:tx2]
                                    vals = sst_cur["val"][ty1:ty2, tx1:tx2]
                                    cgs = cg[ty1:ty2, tx1:tx2]
                                    bgs[unocc] = cgs[unocc]
                                    vals[unocc] = 1
                else:
                    ep["streak"] = 0
                    if ep["status"] in ("pending", "unchanged", "occluded_unverified"):
                        ep["status"] = "occluded_unverified"
        out[tid] = {"status": ep["status"], "score": float(ep["score"]), "confirmed": bool(ep["confirmed"])}
    return out

def _extract_seq_frames(st, max_frames=12):
    samps = list(st["samples"])
    if not samps:
        return []
    if len(samps) &lt;= max_frames:
        return [j for _, j, _ in samps if j]
    chosen = {0, len(samps) - 1}
    mid_ts = st["tuck_ts"] or st["bladed_ts"] or st["crouch_ts"] or st["armed_ts"]
    reach_ts = st["reach_peak_ts"] or st["reach_ts"]
    for idx, (ts, _, ph) in enumerate(samps):
        if ph in ("REACH", "TUCK", "BLADED", "CROUCH", "RELEASE") and len(chosen) &lt; max_frames - 2:
            if mid_ts is None or reach_ts is None or abs(ts - mid_ts) &lt;= 2.5 or abs(ts - reach_ts) &lt;= 2.0:
                chosen.add(idx)
    for idx in np.linspace(0, len(samps) - 1, max_frames, dtype=int).tolist():
        if len(chosen) &gt;= max_frames:
            break
        chosen.add(int(idx))
    return [samps[i][1] for i in sorted(chosen)[:max_frames] if samps[i][1]]

def _build_grid(st, fallback_ov):
    samps = list(st["samples"])
    if not samps:
        return fallback_ov
    def nearest(target, lo, hi, phases=()):
        cands = [i for i in range(lo, hi + 1) if samps[i][2] in phases] if phases else []
        if cands:
            return cands[0] if target is None else min(cands, key=lambda i: abs(samps[i][0] - target))
        return (lo + hi) // 2 if target is None else min(range(lo, hi + 1), key=lambda i: abs(samps[i][0] - target))
    n = len(samps)
    mid_ts = st["tuck_ts"] or st["bladed_ts"] or st["crouch_ts"] or st["armed_ts"]
    i_mid = nearest(mid_ts, 0, n - 1, ("TUCK", "BLADED", "CROUCH"))
    i_reach = nearest(st["reach_peak_ts"] or st["reach_ts"], 0, i_mid, ("REACH",))
    i_pre = nearest(samps[i_reach][0] - 1.8, 0, i_reach, ("PRE", "BROWSE"))
    post_ts = samps[i_mid][0] + 1.5 if i_mid &lt; n - 1 else None
    i_post = nearest(post_ts, min(n - 1, i_mid), n - 1, ("POST",))
    idxs = sorted({i_pre, i_reach, i_mid, i_post, n - 1})
    for idx in np.linspace(0, n - 1, 5, dtype=int).tolist():
        if len(idxs) &gt;= 5:
            break
        if idx not in idxs:
            idxs.append(idx)
    idxs.sort()
    while len(idxs) &lt; 5:
        idxs.append(idxs[-1])
    ov = _dec_jpg(st["peak_ov"])
    if ov is None:
        ov = fallback_ov
    tiles = [_fit_tile(ov, TILE_PX, f"1. AISLE OVERVIEW | ID:{st['id']}", (0, 220, 255))]
    t0 = samps[idxs[0]][0]
    for k, si in enumerate(idxs[:5], start=2):
        ts, jpg, ph = samps[si]
        crop = _dec_jpg(jpg)
        if crop is None:
            crop = ov
        col = (0, 140, 255) if ph in ("REACH", "TUCK", "BLADED", "CROUCH") else (120, 235, 160)
        tiles.append(_fit_tile(crop, TILE_PX, f"{k}. t+{max(0.0, ts - t0):.1f}s [{ph}]", col))
    return np.vstack([np.hstack(tiles[:3]), np.hstack(tiles[3:6])])

def _build_cand(st, img, cause, zone_names, now_ts=None):
    if st["samples"]:
        ts_l, jpg_l, _ = st["samples"][-1]
        st["samples"][-1] = (ts_l, jpg_l, "RELEASE")
    grid_i = _build_grid(st, img)
    seq_i = _extract_seq_frames(st, 6)
    tid = int(st["id"])
    ds = str(st.get("sd_status") or "none")
    dsc = float(st.get("sd_score") or 0.0)
    tmode = str(st.get("trigger_mode") or "shelf_reach_and_delta")
    has_ref = False
    ref_meta = []
    if tmode == "shelf_free_tuck":
        ref_ts = float(now_ts if now_ts is not None else st.get("last_seen") or 0.0)
        sheet_jpg, ref_meta = _build_global_ref_sheet(ref_ts, query_hist=st.get("upper_color_hist"), max_tiles=6)
        if sheet_jpg:
            seq_i = [sheet_jpg] + seq_i[:6]
            has_ref = True
    cand_i = {
        "track_id": tid,
        "bbox": list(st["bbox"]),
        "dwell_sec": round(st["dwell"], 2),
        "reach_side": st["reach_side"],
        "behaviors": list(st["reasons"]),
        "nearby_bags": sorted(st["bags"]),
        "context_vessels": sorted(st["vessels"]),
        "has_store_vessel": bool(st.get("has_store_vessel")),
        "trigger_mode": tmode,
        "has_reference_sheet": has_ref,
        "reference_pickups": ref_meta,
        "zone_names": zone_names or ["full_frame"],
        "dispatch_cause": cause,
        "shelf_delta_status": ds,
        "shelf_delta_score": dsc,
        "shelf_delta_confirmed": bool(st.get("sd_conf")),
        "reason_hint": f"mode={tmode} dwell={st['dwell']:.1f}s shelf_delta={ds}({dsc:.2f}) vessels={','.join(sorted(st['vessels'])) or 'none'}",
    }
    return (grid_i, cand_i, seq_i)

def _reset_armed(st):
    st["armed_ts"] = st["reach_ts"] = st["reach_peak_ts"] = st["tuck_ts"] = st["bladed_ts"] = st["crouch_ts"] = None
    st["bag_stuff_since"] = st["garment_hide_since"] = st["crouch_hide_since"] = None
    st["trigger_mode"] = "shelf_reach_and_delta"
    st["pickup_delta_logged"] = False
    st["reasons"].clear()
    st["sd_status"] = "none"
    st["sd_score"] = 0.0
    st["sd_conf"] = False

def _step():
    if img is None or not isinstance(img, np.ndarray) or img.size == 0:
        outputs["Result"] = {"gate_state": "NO_IMAGE"}
        return
    h_img, w_img = img.shape[:2]
    shelf_rois, shelf_znames, aisle_rois, zone_names = [], [], [], []
    if isinstance(raw_d3, dict) and ("rect" not in raw_d3 and "box" not in raw_d3):
        for k, v in raw_d3.items():
            r = _parse_roi(v, w_img, h_img)
            if r is None:
                continue
            zone_names.append(str(k))
            if "shelf" in str(k).lower():
                shelf_rois.append(r)
                shelf_znames.append(str(k))
            else:
                aisle_rois.append(r)
    else:
        r3 = _parse_roi(raw_d3, w_img, h_img)
        if r3 is not None:
            shelf_rois.append(r3)
            shelf_znames.append("shelf")
            zone_names.append("shelf")
    if not aisle_rois and raw_d4 is not None:
        r4 = _parse_roi(raw_d4, w_img, h_img)
        if r4 is not None:
            aisle_rois.append(r4)
            zone_names.append("aisle")
    hr_rois = _derive_hr(aisle_rois, shelf_rois, w_img, h_img)

    bags = [b for b in bags_raw if isinstance(b, dict) and isinstance(b.get("Box") or b.get("bbox"), (list, tuple))]
    bag_boxes = [tuple(int(round(float(v))) for v in (b.get("Box") or b.get("bbox"))[:4]) for b in bags]
    bag_labels = [str(b.get("Class", b.get("label", "bag"))).strip().lower() for b in bags]

    tstore = state.setdefault("tracks", {})
    dqueue = state.setdefault("dispatch_queue", deque(maxlen=16))
    if raw_ts is not None:
        cur_ts = float(raw_ts)
        prev_raw = state.get("_prev_raw_ts")
        ts_offset = float(state.get("_ts_offset", 0.0) or 0.0)
        if prev_raw is not None and cur_ts + 0.05 &lt; prev_raw:
            ts_offset += prev_raw + (1.0 / 24.0)
        state["_prev_raw_ts"] = cur_ts
        state["_ts_offset"] = ts_offset
        now = ts_offset + cur_ts
    else:
        now = time.monotonic()

    cam_id_str = str(context.get("camera_id") or state.get("camera_id") or "cam_apex")
    seen = set()
    prepared, delta_in = [], []
    for tr in tracks:
        if not isinstance(tr, dict):
            continue
        tid = int(tr.get("track_id", -1))
        bb = tr.get("bbox") or [0, 0, 0, 0]
        if tid &lt; 0 or len(bb) &lt; 4:
            continue
        x, y, bw, bh = [int(v) for v in bb[:4]]
        seen.add(tid)
        st = tstore.setdefault(tid, {
            "id": tid, "last_seen": now, "fc": 0, "in_zone": False, "enter_ts": None, "exit_ts": None,
            "dwell": 0.0, "samples": deque(maxlen=40), "last_samp": -1e9, "sh": deque(maxlen=40),
            "zone_sh": deque(maxlen=40), "heights": deque(maxlen=40), "last_y2": None,
            "reach_ts": None, "reach_peak_ts": None, "reach_side": "", "tuck_ts": None,
            "bladed_ts": None, "crouch_ts": None, "armed_ts": None, "reasons": [], "peak_ov": b"",
            "cooldown": 0.0, "bags": set(), "vessels": set(), "bbox": [x, y, bw, bh],
            "last_shelf_idx": None, "sd_status": "none", "sd_score": 0.0, "sd_conf": False,
            "basket_hits": 0, "basket_miss": 0, "has_store_vessel": False,
            "wrist_was_open": False, "bag_stuff_since": None, "garment_hide_since": None, "crouch_hide_since": None,
            "last_center": None, "norm_speed": 0.0,
            "has_merchandise_until": None, "last_pickup_recorded_ts": -1e9, "pickup_delta_logged": False,
            "trigger_mode": "shelf_reach_and_delta", "upper_color_hist": None,
        })
        cx_t, cy_t = x + bw * 0.5, y + bh * 0.5
        prev_c = st.get("last_center")
        if prev_c is not None and (now - prev_c[0]) &gt; 1e-4:
            dt_c = now - prev_c[0]
            dist_c = ((cx_t - prev_c[1]) ** 2 + (cy_t - prev_c[2]) ** 2) ** 0.5
            st["norm_speed"] = (dist_c / dt_c) / max(40.0, float(bh))
        else:
            st["norm_speed"] = 0.0
        st["last_center"] = (now, cx_t, cy_t)
        st["last_seen"] = now
        st["fc"] += 1
        st["bbox"] = [x, y, bw, bh]
        near_bags, near_baskets, near_phones, near_all = [], [], [], []
        margin = max(30, int(bw * 0.25))
        for ib, bb_i in enumerate(bag_boxes):
            if not _boxes_close((x, y, bw, bh), bb_i, margin):
                continue
            lbl = bag_labels[ib]
            st["vessels"].add(lbl)
            near_all.append(bb_i)
            if lbl in _BENIGN_VESSELS:
                near_baskets.append(bb_i)
            elif lbl in _PHONE_CLASSES:
                near_phones.append(bb_i)
            else:
                near_bags.append(bb_i)
                st["bags"].add(lbl)
        if near_baskets:
            st["basket_hits"] = min(12, int(st["basket_hits"]) + 1)
            st["basket_miss"] = 0
            if st["basket_hits"] &gt;= BASKET_LATCH_FRAMES:
                st["has_store_vessel"] = True
        else:
            st["basket_miss"] = int(st["basket_miss"]) + 1
            if st["basket_miss"] &gt;= 15:
                st["has_store_vessel"] = False
                st["basket_hits"] = 0
        in_hr = _in_hr((x, y, bw, bh), hr_rois)
        cues = _pose_cues(tr.get("keypoints") or [], (x, y, bw, bh), shelf_rois, near_bags, near_baskets, near_phones)
        if cues["wrist_open"]:
            st["wrist_was_open"] = True
        if cues["touched_shelf_idx"] is not None:
            st["last_shelf_idx"] = cues["touched_shelf_idx"]
        prepared.append((tid, st, (x, y, bw, bh), cues, near_all, in_hr))
        delta_in.append({"tid": tid, "bbox": (x, y, bw, bh), "wrists": cues["wrist_pts"], "reach_active": bool(cues["reach_side"]), "touched_shelf_idx": cues["touched_shelf_idx"]})

    delta_map = _shelf_delta_step(img, now, shelf_rois, delta_in)

    for tid, st, (x, y, bw, bh), cues, near_all, in_hr in prepared:
        dr = delta_map.get(tid) or {}
        if dr.get("confirmed"):
            st["sd_status"] = "confirmed"
            st["sd_score"] = max(float(st.get("sd_score") or 0.0), float(dr.get("score") or 0.0))
            st["sd_conf"] = True
        elif not st.get("sd_conf") and dr.get("status") not in (None, "none"):
            st["sd_status"] = str(dr["status"])
            st["sd_score"] = float(dr.get("score") or 0.0)

        if in_hr:
            st["in_zone"] = True
            st["exit_ts"] = None
            if st["enter_ts"] is None:
                st["enter_ts"] = now
            st["dwell"] = now - st["enter_ts"]
        else:
            if st["exit_ts"] is None:
                st["exit_ts"] = now
            if now - st["exit_ts"] &gt; 0.5:
                if st["armed_ts"] is not None and now &gt;= st["cooldown"]:
                    dqueue.append(_build_cand(st, img, "zone_exit", zone_names))
                    st["cooldown"] = now + COOLDOWN_SEC
                st["in_zone"] = False
                st["enter_ts"] = None
                st["dwell"] = 0.0
                st["zone_sh"].clear()
                _reset_armed(st)
                if "sd" in state:
                    state["sd"]["episodes"].pop(tid, None)

        mature = st["in_zone"] and st["dwell"] &gt;= DWELL_SEC and st["fc"] &gt;= MIN_FRAMES
        fast_delta = st["in_zone"] and st["dwell"] &gt;= min(DWELL_SEC, 0.5) and st["fc"] &gt;= 3 and bool(st["sd_conf"]) and not cues["in_benign_basket"]
        reach_now = bool(cues["reach_side"])
        d_conf_now = bool(dr.get("confirmed"))
        if reach_now or d_conf_now:
            st["has_merchandise_until"] = max(float(st.get("has_merchandise_until") or 0.0), now + MERCH_TTL_SEC)
            need_log = (now - float(st["last_pickup_recorded_ts"])) &gt;= 4.0 or (d_conf_now and not st.get("pickup_delta_logged"))
            if need_log:
                p_crop = _crop_person(img, x, y, bw, bh, w_img, h_img)
                if p_crop is not None:
                    lsi = st.get("last_shelf_idx")
                    z_lbl = shelf_znames[int(lsi)] if (lsi is not None and 0 &lt;= int(lsi) &lt; len(shelf_znames)) else (shelf_znames[0] if shelf_znames else (zone_names[0] if zone_names else "aisle"))
                    _record_global_pickup(cam_id_str, tid, now, p_crop, z_lbl, float(st.get("sd_score") or 0.0), _upper_hist(p_crop))
                    st["last_pickup_recorded_ts"] = now
                    if d_conf_now:
                        st["pickup_delta_logged"] = True

        phone_sup = cues["holding_phone"] and not st["sd_conf"]
        eff_tuck = (cues["tucked"] or cues["occluded"]) and not cues["in_benign_basket"] and not phone_sup
        conc = bool(eff_tuck or len(cues["wrist_pts"]) &lt; 2)
        pool = st["zone_sh"] if len(st["zone_sh"]) &gt;= 4 else st["sh"]
        bladed_frame = (
            (not reach_now or conc) and conc and not cues["in_benign_basket"]
            and cues["norm_sh"] is not None and len(pool) &gt;= 3
            and cues["norm_sh"] &lt;= float(np.percentile(list(pool), 85)) * (1.0 - BLADE_DROP)
        )
        crouch_frame = False
        if (not reach_now or conc) and not cues["in_benign_basket"] and len(st["heights"]) &gt;= 3:
            bh_base = float(np.percentile(list(st["heights"]), 90))
            y2 = y + bh
            steady = st["last_y2"] is None or abs(y2 - st["last_y2"]) &lt;= max(28.0, bh_base * 0.12)
            crouch_frame = bh_base &gt; 30.0 and bh &lt;= bh_base * (1.0 - CROUCH_DROP) and steady

        tuck_now = bladed_now = crouch_now = False
        bag_stuff_hit = garment_hit = crouch_hide_hit = False
        has_merch = st["has_merchandise_until"] is not None and now &lt;= float(st["has_merchandise_until"])
        cd_ok = now &gt;= st["cooldown"]

        if (mature or fast_delta) and st["armed_ts"] is None:
            if reach_now:
                if st["reach_ts"] is None:
                    st["reach_ts"] = now
                st["reach_peak_ts"] = now
                st["reach_side"] = cues["reach_side"]
            dt_r = (now - st["reach_ts"]) if st["reach_ts"] is not None else -1.0
            rec_r = st["reach_ts"] is not None and 0.15 &lt;= dt_r &lt;= TUCK_WIN_SEC
            if rec_r and eff_tuck:
                tuck_now = True
                st["tuck_ts"] = now
            if rec_r and bladed_frame:
                bladed_now = True
                st["bladed_ts"] = now
            if rec_r and crouch_frame:
                crouch_now = True
                st["crouch_ts"] = now
            if has_merch and not rec_r and not reach_now and (eff_tuck or bladed_frame or crouch_frame):
                if eff_tuck:
                    tuck_now = True
                    st["tuck_ts"] = now
                if bladed_frame:
                    bladed_now = True
                    st["bladed_ts"] = now
                if crouch_frame:
                    crouch_now = True
                    st["crouch_ts"] = now
                st["trigger_mode"] = "carry_delayed"

        if not bladed_frame and not bladed_now and cues["norm_sh"] is not None:
            st["sh"].append(float(cues["norm_sh"]))
            if in_hr and not reach_now:
                st["zone_sh"].append(float(cues["norm_sh"]))
        if not crouch_frame and not crouch_now:
            st["heights"].append(float(bh))
        st["last_y2"] = float(y + bh)

        mature_b = st["in_zone"] and st["dwell"] &gt;= min(DWELL_SEC, 0.8) and st["fc"] &gt;= MIN_FRAMES
        vessel_sup = st["has_store_vessel"] and not cues["in_personal_bag"]
        if (
            mature_b and cd_ok and st["armed_ts"] is None and st["reach_ts"] is None
            and not reach_now and not st["sd_conf"] and not has_merch
            and st["wrist_was_open"] and not cues["in_benign_basket"] and not vessel_sup and not phone_sup
        ):
            bag_cond = cues["in_personal_bag"] and not cues["holding_phone"]
            slowed = float(st.get("norm_speed") or 0.0) &lt;= 0.85
            garment_cond = (cues["in_core"] or (cues["occluded"] and bladed_frame)) and slowed and (cues["two_hands_torso"] or bladed_frame) and not cues["holding_phone"]
            crouch_cond = crouch_frame and (cues["in_core"] or cues["in_personal_bag"] or cues["occluded"]) and not cues["holding_phone"]
            if bag_cond:
                if st["bag_stuff_since"] is None:
                    st["bag_stuff_since"] = now
                elif (now - st["bag_stuff_since"]) &gt;= BAG_STUFF_HOLD_SEC:
                    bag_stuff_hit = True
            else:
                st["bag_stuff_since"] = None
            if garment_cond:
                if st["garment_hide_since"] is None:
                    st["garment_hide_since"] = now
                elif (now - st["garment_hide_since"]) &gt;= GARMENT_HOLD_SEC:
                    garment_hit = True
            else:
                st["garment_hide_since"] = None
            if crouch_cond:
                if st["crouch_hide_since"] is None:
                    st["crouch_hide_since"] = now
                elif (now - st["crouch_hide_since"]) &gt;= CROUCH_HOLD_SEC:
                    crouch_hide_hit = True
            else:
                st["crouch_hide_since"] = None
        else:
            st["bag_stuff_since"] = st["garment_hide_since"] = st["crouch_hide_since"] = None

        path_b_hit = bag_stuff_hit or garment_hit or crouch_hide_hit
        ph = "TUCK" if (tuck_now or bag_stuff_hit or garment_hit) else ("BLADED" if bladed_now else ("CROUCH" if (crouch_now or crouch_hide_hit) else ("PRE" if not (mature or fast_delta or mature_b) else ("REACH" if reach_now else ("POST" if st["armed_ts"] else "BROWSE")))))
        if st["in_zone"] and (ph in ("REACH", "TUCK", "BLADED", "CROUCH") or (now - st["last_samp"]) &gt;= SAMPLE_SEC or not st["samples"]):
            ux1, uy1, ux2, uy2 = x, y, x + bw, y + bh
            for bx, by, bbw, bbh in near_all:
                ux1, uy1, ux2, uy2 = min(ux1, bx), min(uy1, by), max(ux2, bx + bbw), max(uy2, by + bbh)
            t_shelf = shelf_rois[st["last_shelf_idx"]] if (st["last_shelf_idx"] is not None and 0 &lt;= st["last_shelf_idx"] &lt; len(shelf_rois)) else (min(shelf_rois, key=lambda r: abs((r[0] + r[2] * 0.5) - (x + bw * 0.5))) if shelf_rois else None)
            if t_shelf is not None:
                sx_t, _, sw_t, _ = t_shelf
                ux1 = min(ux1, sx_t + sw_t // 3)
                ux2 = max(ux2, sx_t + (2 * sw_t) // 3)
            pad_x, pad_y = max(35, int((ux2 - ux1) * 0.25)), max(25, int((uy2 - uy1) * 0.12))
            cx1, cy1 = max(0, ux1 - pad_x), max(0, uy1 - pad_y)
            cx2, cy2 = min(w_img, ux2 + pad_x), min(h_img, uy2 + pad_y)
            jpg = _enc_jpg(img[cy1:cy2, cx1:cx2])
            if jpg:
                st["samples"].append((now, jpg, ph))
                st["last_samp"] = now
        while st["samples"] and (now - st["samples"][0][0]) &gt; BUFFER_SEC:
            st["samples"].popleft()

        fast_hit = fast_delta and (tuck_now or bladed_now or crouch_now or cues["in_core_or_bag"] or not reach_now)
        path_a_hit = cd_ok and ((mature and (tuck_now or bladed_now or crouch_now)) or fast_hit) and not cues["in_benign_basket"]
        hit = path_a_hit or (path_b_hit and not cues["in_benign_basket"])
        if path_b_hit and not path_a_hit and st["armed_ts"] is None:
            st["trigger_mode"] = "shelf_free_tuck"
        elif path_a_hit and st["armed_ts"] is None and st.get("trigger_mode") != "carry_delayed":
            st["trigger_mode"] = "shelf_reach_and_delta"
        if cd_ok and (hit or st["armed_ts"] is not None):
            for flag, lbl in (
                (tuck_now, "reach_and_tuck"),
                (bladed_now, "blading"),
                (crouch_now, "crouch"),
                (fast_hit, "shelf_item_removed"),
                (st.get("trigger_mode") == "carry_delayed" and (tuck_now or bladed_now or crouch_now), "carry_delayed"),
                (bag_stuff_hit, "bag_stuff"),
                (garment_hit, "garment_hide"),
                (crouch_hide_hit, "crouch_hide"),
            ):
                if flag and lbl not in st["reasons"]:
                    st["reasons"].append(lbl)
        if hit and st["armed_ts"] is None:
            st["armed_ts"] = now
            st["upper_color_hist"] = _upper_hist(_crop_person(img, x, y, bw, bh, w_img, h_img))
            ov = img.copy()
            cv2.rectangle(ov, (x, y), (x + bw, y + bh), (0, 60, 255), 3)
            st["peak_ov"] = _enc_jpg(ov, max_dim=768)

        if st["armed_ts"] is not None and (now - st["armed_ts"]) &gt;= RELEASE_WAIT_SEC:
            dqueue.append(_build_cand(st, img, "natural_release", zone_names, now))
            _reset_armed(st)
            if "sd" in state:
                state["sd"]["episodes"].pop(tid, None)
            st["cooldown"] = now + COOLDOWN_SEC
        if st["armed_ts"] is None and st["reach_ts"] is not None and (now - st["reach_ts"]) &gt; TUCK_WIN_SEC:
            st["reach_ts"] = None

    for tid, st in list(tstore.items()):
        if tid in seen:
            continue
        miss = now - st["last_seen"]
        if st["armed_ts"] is not None and miss &gt;= ID_LOSS_GRACE_SEC and now &gt;= st["cooldown"]:
            dqueue.append(_build_cand(st, img, "id_disappearance", zone_names))
            tstore.pop(tid, None)
            if "sd" in state:
                state["sd"]["episodes"].pop(tid, None)
        elif miss &gt; 15.0:
            tstore.pop(tid, None)
            if "sd" in state:
                state["sd"]["episodes"].pop(tid, None)
                state["sd"]["whist"].pop(tid, None)

    if dqueue:
        grid_out, cand_out, seq_out = dqueue.popleft()
        outputs["Image"] = grid_out
        outputs["Sequence_Frames"] = seq_out
        outputs["Trigger"] = True
        outputs["Data"] = cand_out
        outputs["Result"] = cand_out
    else:
        outputs["Result"] = {"tracks": len(seen), "queued": 0, "gate_state": "ARMED" if any(s["armed_ts"] for s in tstore.values()) else "MONITORING"}

_step()
</Parameter>
            <Parameter name="timeout_ms" type="int">5000</Parameter>
            <Parameter name="custom_inputs" type="json">[]</Parameter>
            <Parameter name="custom_outputs" type="json">[{"name": "Sequence_Frames", "type": "ANY"}]</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_prompt_script" tool_name="Script" name="06_Prompt_Builder" category="Logic Tools" enabled="true">
          <Parameters>
            <Parameter name="code" type="str"># Script 2: Neutral 4-Fact Visual Audit Prompt Builder + Cross-Cam Reference Sheet Context
# Inputs : Image (2x3 grid), Data1=Candidate Telemetry, Data2=Named_ROIs, Trigger (bool)
# Outputs: Image, Text (User Prompt), System_Prompt, Trigger (bool)

trig = bool(context.get("Trigger"))
cand = context.get("Data1") or {}
rois = context.get("Data2") or {}

outputs["Image"] = context.get("Image")
outputs["Trigger"] = trig
outputs["Status"] = "OK"

outputs["System_Prompt"] = """### Role
You are a skeptical retail loss-prevention auditor reviewing chronological CCTV frames of a single shopper near a store shelf. Do NOT assume theft from posture alone; verify physical evidence across consecutive frames.

### Critical Differential Checks (Examine Chronological Frame Order)
1. Motion Direction &amp; Item Conservation:
   - Did an actual store item visibly leave the shelf, or did the shopper merely look, return it, or keep hands empty?
   - Was the object entering a pocket/bag a personal smartphone, wallet, or key (NOT merchandise)?
2. Visible Destination of Store Merchandise:
   - "returned_to_shelf": item placed back onto any shelf/display.
   - "store_basket_or_cart": item placed inside a store shopping basket or rolling cart.
   - "personal_bag_or_clothing": store merchandise visibly placed inside a personal backpack, purse, tote, waistband, or jacket pocket.
   - "carried_openly": customer holds item openly toward checkout/aisle.
   - "unclear": hand/item blocked or too blurry to confirm concealment.
3. Normal Shopping / Staff Exceptions:
   - Store staff restocking/facing -&gt; behavior_category="staff_stocking".
   - Phone/wallet/keys -&gt; likely_personal_object=true, behavior_category="regular_browsing", low confidence (&lt; 0.35).
   - Store basket/cart or returned to shelf -&gt; behavior_category="regular_browsing", low confidence (&lt; 0.25).
4. Cross-Camera Pickup Reference Sheet (When Attached as Image #1):
   - If Image #1 is labeled "RECENT STORE PICKUPS", compare clothing, bags, and carried items across Image #1 tiles vs. the action frames.
   - If trigger_mode="shelf_free_tuck" and NO matching pickup tile/item shows store merchandise (or object is personal/unclear), classify "regular_browsing".

### Output Specification
Respond ONLY with strict JSON:
{
  "person_detected": true,
  "item_removed_from_shelf": "yes | no | unclear",
  "visible_destination": "returned_to_shelf | store_basket_or_cart | personal_bag_or_clothing | carried_openly | unclear",
  "likely_personal_object": false,
  "staff_or_byob_indicator": false,
  "behavior_category": "high_risk_concealment_attempt | regular_browsing | staff_stocking",
  "confidence_score": 0.00,
  "justification": "Brief 1-2 sentence explanation citing specific frame transitions."
}"""

if trig and isinstance(cand, dict) and cand:
    zone_names = ", ".join(k for k, v in rois.items() if isinstance(v, list) and len(v) == 4 and v[2] &gt; 0) or ", ".join(cand.get("zone_names") or []) or "full_frame"
    ds = cand.get("shelf_delta_status", "none")
    dsc = float(cand.get("shelf_delta_score", 0.0) or 0.0)
    tmode = str(cand.get("trigger_mode") or "shelf_reach_and_delta")
    vessels = ", ".join(cand.get("context_vessels") or cand.get("nearby_bags") or []) or "none"
    dwell = float(cand.get("dwell_sec", 0.0) or 0.0)
    has_ref = bool(cand.get("has_reference_sheet"))
    ref_pickups = cand.get("reference_pickups") or []
    ref_line = ""
    frame_note = "Attached frames show the chronological interaction progression."
    if has_ref:
        tile_desc = ", ".join(f"#{int(p.get('tile', i + 1))} {p.get('camera_id', 'cam')}({float(p.get('age_sec', 0.0)):.0f}s,{p.get('shelf_zone', 'shelf')})" for i, p in enumerate(ref_pickups[:6]))
        ref_line = f"- Reference Sheet Tiles: {tile_desc}\n"
        frame_note = f"Image #1 is the cross-camera RECENT STORE PICKUPS reference sheet ({len(ref_pickups)} tile(s)); subsequent frames show chronological progression."
    outputs["Text"] = (
        f"### Objective Scene Context\n"
        f"- Active Monitored ROIs: {zone_names}\n"
        f"- Trigger Path: {tmode}\n"
        f"- Subject Dwell in Aisle: {dwell:.1f}s\n"
        f"- Localized Shelf Delta: {ds} (score={dsc:.2f})\n"
        f"- Nearby Detected Objects: {vessels}\n"
        f"{ref_line}"
        f"{frame_note} Evaluate objectively and return ONLY the JSON object."
    )
    outputs["Result"] = cand
else:
    outputs["Text"] = ""
    outputs["Result"] = {"waiting": True}
</Parameter>
            <Parameter name="timeout_ms" type="int">5000</Parameter>
            <Parameter name="custom_inputs" type="json">[]</Parameter>
            <Parameter name="custom_outputs" type="json">[]</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_vlm" tool_name="VLM" name="07_VLM" category="Theft Recognition" enabled="true">
          <Parameters>
            <Parameter name="mode" type="str">Cloud / OpenAI-Compatible API</Parameter>
            <Parameter name="provider" type="str">openai</Parameter>
            <Parameter name="base_url" type="str" />
            <Parameter name="model_name" type="str">gpt-4o-mini</Parameter>
            <Parameter name="api_key" type="str" />
            <Parameter name="temperature" type="float">0.1</Parameter>
            <Parameter name="max_tokens" type="int">2048</Parameter>
            <Parameter name="timeout_sec" type="float">25.0</Parameter>
            <Parameter name="async_non_blocking" type="bool">true</Parameter>
            <Parameter name="parse_json" type="bool">true</Parameter>
            <Parameter name="max_concurrent" type="int">3</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_verdict_script" tool_name="Script" name="08_Parse_Verdict" category="Logic Tools" enabled="true">
          <Parameters>
            <Parameter name="code" type="str"># Script 3: 4-Fact Verdict Consistency Gate + 6s Hold + Red Alert / Silent Watch Routing
# Inputs : Image (evaluated grid), Data1=Response_JSON, Data2=Response_Text, Data3=Error, Data4=VLM Status, Trigger=Has_Response
# Outputs: Image, Value (0..100 for Condition Branch: &gt;=65 =&gt; PASS, &lt;65 =&gt; NG), Trigger (1-cycle Red Alert), Watch_Trigger (1-cycle Silent Watch), Result (log dict)

raw_json = context.get("Data1")
raw_text = str(context.get("Data2") or "")
vlm_err = str(context.get("Data3") or "").strip()
vlm_status = str(context.get("Data4") or "").strip()
fresh = bool(context.get("Trigger"))
now = time.monotonic()

outputs["Image"] = context.get("Image")
outputs["Status"] = "OK"
outputs["Trigger"] = False
outputs["Watch_Trigger"] = False

if vlm_err:
    err_payload = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "behavior_category": "ERROR",
        "vlm_status": vlm_status or "ERROR",
        "confidence_score": 0.0,
        "error": vlm_err,
    }
    state["last_error_payload"] = err_payload
    outputs["Status"] = "ERROR"
    outputs["Value"] = 0.0
    outputs["Result"] = err_payload
    outputs["Data"] = err_payload
else:
    if fresh and isinstance(raw_json, dict) and raw_json:
        state.pop("last_error_payload", None)
        cat = str(raw_json.get("behavior_category", "regular_browsing")).strip().lower()
        conf = float(raw_json.get("confidence_score", 0.0) or 0.0)
        dest = str(raw_json.get("visible_destination", "")).strip().lower()
        removed = str(raw_json.get("item_removed_from_shelf", "")).strip().lower()
        personal_obj = raw_json.get("likely_personal_object") is True
        staff_or_byob = raw_json.get("staff_or_byob_indicator") is True

        benign_fact = dest in ("returned_to_shelf", "store_basket_or_cart", "carried_openly") or removed == "no" or personal_obj
        watch_only = (dest == "unclear" or staff_or_byob) and not benign_fact
        red_ok = (cat == "high_risk_concealment_attempt") and not benign_fact and not watch_only
        raw_pct = round(conf * 100.0, 2)
        score_pct = raw_pct if red_ok else 0.0
        payload = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "behavior_category": cat,
            "vlm_status": vlm_status or "OK",
            "confidence_score": round(conf, 4),
            "item_removed_from_shelf": removed or "unknown",
            "visible_destination": dest or "unknown",
            "likely_personal_object": personal_obj,
            "staff_or_byob_indicator": staff_or_byob,
            "watch_only": watch_only,
            "justification": str(raw_json.get("justification", "")),
            "sequence_verification": raw_json.get("sequence_verification", {}),
        }
        state["last_payload"] = payload
        state["last_score"] = score_pct
        if score_pct &gt;= 65.0:
            state["hold_until"] = now + 6.0
            outputs["Trigger"] = True
        else:
            state["hold_until"] = 0.0
            if watch_only and raw_pct &gt;= 50.0:
                outputs["Watch_Trigger"] = True

    hold_until = float(state.get("hold_until", 0.0) or 0.0)
    if now &lt;= hold_until:
        outputs["Value"] = float(state.get("last_score", 0.0) or 0.0)
    else:
        outputs["Value"] = 0.0

    if vlm_status == "NO_API_KEY" and not state.get("last_payload"):
        res_payload = {"behavior_category": "NO_API_KEY", "vlm_status": "NO_API_KEY", "confidence_score": 0.0}
    else:
        res_payload = state.get("last_payload") or {"behavior_category": vlm_status or "IDLE", "vlm_status": vlm_status or "IDLE", "confidence_score": 0.0}
    outputs["Result"] = res_payload
    outputs["Data"] = res_payload
</Parameter>
            <Parameter name="timeout_ms" type="int">5000</Parameter>
            <Parameter name="custom_inputs" type="json">[]</Parameter>
            <Parameter name="custom_outputs" type="json">[{"name": "Watch_Trigger", "type": "BOOLEAN"}]</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_theft_branch" tool_name="Condition Branch" name="09_Theft_Verdict" category="Logic Tools" enabled="true">
          <Parameters>
            <Parameter name="operator" type="str">&gt;=</Parameter>
            <Parameter name="threshold_low" type="float">65.0</Parameter>
            <Parameter name="threshold_high" type="float">150.0</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_theft_log" tool_name="Data Log" name="10_Theft_Event_Log" category="Communication" enabled="true">
          <Parameters>
            <Parameter name="file_path" type="str">./results/theft_events.csv</Parameter>
            <Parameter name="add_timestamp" type="bool">true</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_evidence_saver" tool_name="Image Output" name="11_Evidence_Saver" category="Acquisition" enabled="true">
          <Parameters>
            <Parameter name="save_directory" type="str">./results/evidence</Parameter>
            <Parameter name="file_format" type="str">PNG</Parameter>
            <Parameter name="save_mode" type="str">Always Save</Parameter>
            <Parameter name="image_quality" type="int">95</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_alert_dispatch" tool_name="TCP Send" name="12_Alert_Dispatch" category="Communication" enabled="false">
          <Parameters>
            <Parameter name="mode" type="str">Simulation (Loopback Log)</Parameter>
            <Parameter name="server_ip" type="str">127.0.0.1</Parameter>
            <Parameter name="server_port" type="int">8080</Parameter>
            <Parameter name="prefix" type="str">APEX_RES,</Parameter>
            <Parameter name="suffix" type="str">\r\n</Parameter>
            <Parameter name="format" type="str">CSV</Parameter>
            <Parameter name="connect_timeout_ms" type="int">500</Parameter>
          </Parameters>
        </Node>
      </Nodes>
      <Connections>
        <Connection from_node="node_rtsp_cam1" from_port="Image" to_node="node_roi_zones" to_port="Image" />
        <Connection from_node="node_rtsp_cam1" from_port="Image" to_node="node_bag_detector" to_port="Image" />
        <Connection from_node="node_rtsp_cam1" from_port="Image" to_node="node_yolo_pose" to_port="Image" />
        <Connection from_node="node_roi_zones" from_port="Union_ROI" to_node="node_yolo_pose" to_port="ROI" />
        <Connection from_node="node_rtsp_cam1" from_port="Image" to_node="node_botsort" to_port="Image" />
        <Connection from_node="node_yolo_pose" from_port="Detections" to_node="node_botsort" to_port="Detections" />
        <Connection from_node="node_yolo_pose" from_port="Keypoints" to_node="node_botsort" to_port="Keypoints" />
        <Connection from_node="node_rtsp_cam1" from_port="Image" to_node="node_behavior_script" to_port="Image" />
        <Connection from_node="node_rtsp_cam1" from_port="Timestamp" to_node="node_behavior_script" to_port="Val1" />
        <Connection from_node="node_botsort" from_port="Tracks" to_node="node_behavior_script" to_port="Data1" />
        <Connection from_node="node_bag_detector" from_port="Detections" to_node="node_behavior_script" to_port="Data2" />
        <Connection from_node="node_roi_zones" from_port="Named_ROIs" to_node="node_behavior_script" to_port="Data3" />
        <Connection from_node="node_roi_zones" from_port="aisle" to_node="node_behavior_script" to_port="Data4" />
        <Connection from_node="node_behavior_script" from_port="Image" to_node="node_prompt_script" to_port="Image" />
        <Connection from_node="node_behavior_script" from_port="Data" to_node="node_prompt_script" to_port="Data1" />
        <Connection from_node="node_roi_zones" from_port="Named_ROIs" to_node="node_prompt_script" to_port="Data2" />
        <Connection from_node="node_behavior_script" from_port="Trigger" to_node="node_prompt_script" to_port="Trigger" />
        <Connection from_node="node_prompt_script" from_port="Image" to_node="node_vlm" to_port="Image" />
        <Connection from_node="node_prompt_script" from_port="Text" to_node="node_vlm" to_port="Prompt" />
        <Connection from_node="node_prompt_script" from_port="System_Prompt" to_node="node_vlm" to_port="System_Prompt" />
        <Connection from_node="node_prompt_script" from_port="Trigger" to_node="node_vlm" to_port="Trigger" />
        <Connection from_node="node_vlm" from_port="Image" to_node="node_verdict_script" to_port="Image" />
        <Connection from_node="node_vlm" from_port="Response_JSON" to_node="node_verdict_script" to_port="Data1" />
        <Connection from_node="node_vlm" from_port="Response_Text" to_node="node_verdict_script" to_port="Data2" />
        <Connection from_node="node_vlm" from_port="Error" to_node="node_verdict_script" to_port="Data3" />
        <Connection from_node="node_vlm" from_port="Status" to_node="node_verdict_script" to_port="Data4" />
        <Connection from_node="node_vlm" from_port="Has_Response" to_node="node_verdict_script" to_port="Trigger" />
        <Connection from_node="node_verdict_script" from_port="Value" to_node="node_theft_branch" to_port="Val_In" />
        <Connection from_node="node_verdict_script" from_port="Result" to_node="node_theft_log" to_port="Data" />
        <Connection from_node="node_verdict_script" from_port="Trigger" to_node="node_theft_log" to_port="Trigger" />
        <Connection from_node="node_verdict_script" from_port="Image" to_node="node_evidence_saver" to_port="Image" />
        <Connection from_node="node_verdict_script" from_port="Trigger" to_node="node_evidence_saver" to_port="Trigger" />
        <Connection from_node="node_verdict_script" from_port="Result" to_node="node_alert_dispatch" to_port="Data" />
        <Connection from_node="node_theft_branch" from_port="Branch_Result" to_node="node_alert_dispatch" to_port="Trigger" />
        <Connection from_node="node_roi_zones" from_port="Union_ROI" to_node="node_bag_detector" to_port="ROI" />
        <Connection from_node="node_behavior_script" from_port="Sequence_Frames" to_node="node_vlm" to_port="Frames" />
      </Connections>
      <Layout>
        <Position node="node_rtsp_cam1" x="40.0" y="180.0" />
        <Position node="node_roi_zones" x="280.0" y="40.0" />
        <Position node="node_bag_detector" x="280.0" y="210.0" />
        <Position node="node_yolo_pose" x="280.0" y="360.0" />
        <Position node="node_botsort" x="540.0" y="320.0" />
        <Position node="node_behavior_script" x="800.0" y="180.0" />
        <Position node="node_prompt_script" x="1060.0" y="180.0" />
        <Position node="node_vlm" x="1320.0" y="180.0" />
        <Position node="node_verdict_script" x="1580.0" y="180.0" />
        <Position node="node_theft_branch" x="1840.0" y="60.0" />
        <Position node="node_theft_log" x="1840.0" y="190.0" />
        <Position node="node_evidence_saver" x="1840.0" y="320.0" />
        <Position node="node_alert_dispatch" x="1840.0" y="450.0" />
      </Layout>
    </ApexFlow>
  </Flows>
</ApexSolution>