"""Multi-person-safe, occlusion-aware, localized shelf-state delta tracker."""
from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

PixelRect = Tuple[int, int, int, int]


def _clamp_rect(x1: int, y1: int, x2: int, y2: int, w: int, h: int) -> Optional[Tuple[int, int, int, int]]:
    cx1 = max(0, min(w - 1, int(x1)))
    cy1 = max(0, min(h - 1, int(y1)))
    cx2 = max(cx1, min(w, int(x2)))
    cy2 = max(cy1, min(h, int(y2)))
    if cx2 <= cx1 or cy2 <= cy1:
        return None
    return (cx1, cy1, cx2, cy2)


def _rect_intersects(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


class LocalizedShelfDeltaTracker:
    """Tracks per-shelf selective backgrounds and per-track localized touch patches.

    Designed for multi-shopper aisles:
    - Occluded pixels (any person bbox or wrist inside a shelf ROI) are masked out of background
      updates so another shopper standing elsewhere on the same shelf never corrupts the baseline.
    - Each reaching track snapshots the clean shelf baseline from ~0.6s prior to reach onset and
      isolates changes strictly inside its own localized contact patch (`<= 150x150`).
    - Same-spot multi-person wrist overlap marks episodes `contested_multi_person`.
    - Post-reach measurement waits until >= 75% of the contact patch is unoccluded for consecutive
      settle frames, preventing passing bystanders' clothing from triggering false deltas.
    """

    MAX_PATCH_PX = 150
    SETTLE_FRAMES = 2
    MIN_UNOCCLUDED_RATIO = 0.75
    MIN_VALID_BASELINE_RATIO = 0.45
    POST_TOUCH_DELAY_SEC = 0.20
    WRIST_HISTORY_SEC = 1.2
    LAG_REF_SEC = 0.65

    def __init__(self) -> None:
        self._shelves: Dict[int, Dict[str, Any]] = {}
        self._episodes: Dict[int, Dict[str, Any]] = {}
        self._wrist_history: Dict[int, Deque[Tuple[float, List[Tuple[int, int]]]]] = {}
        self._coexisting_pairs: set[Tuple[int, int]] = set()

    def reset(self) -> None:
        self._shelves.clear()
        self._episodes.clear()
        self._wrist_history.clear()
        self._coexisting_pairs.clear()

    def clear_track(self, tid: int) -> None:
        self._episodes.pop(tid, None)
        self._wrist_history.pop(tid, None)
        self._coexisting_pairs = {p for p in self._coexisting_pairs if tid not in p}

    def _tracks_coexisted(self, tid_a: int, tid_b: int) -> bool:
        if tid_a == tid_b:
            return False
        pair = (tid_a, tid_b) if tid_a < tid_b else (tid_b, tid_a)
        return pair in self._coexisting_pairs

    def clear_episode(self, tid: int) -> None:
        self._episodes.pop(tid, None)

    def _ensure_shelf(self, s_idx: int, rect: PixelRect) -> Dict[str, Any]:
        sx, sy, sw, sh = rect
        st = self._shelves.get(s_idx)
        if st is None or st["rect"] != rect or st["bg_gray"].shape != (sh, sw):
            st = {
                "rect": rect,
                "bg_gray": np.zeros((sh, sw), dtype=np.float32),
                "valid_mask": np.zeros((sh, sw), dtype=np.uint8),
                "lag_ring": deque(maxlen=16),
            }
            self._shelves[s_idx] = st
        return st

    def _build_occupancy_mask(
        self,
        shelf_rect: PixelRect,
        person_boxes: Sequence[PixelRect],
        all_wrists: Sequence[Tuple[int, Tuple[int, int]]],
    ) -> np.ndarray:
        sx, sy, sw, sh = shelf_rect
        mask = np.zeros((sh, sw), dtype=np.uint8)
        for bx, by, bw, bh in person_boxes:
            clipped = _clamp_rect(bx - 10 - sx, by - 10 - sy, bx + bw + 10 - sx, by + bh + 10 - sy, sw, sh)
            if clipped is not None:
                x1, y1, x2, y2 = clipped
                mask[y1:y2, x1:x2] = 1
        for _, (wx, wy) in all_wrists:
            clipped = _clamp_rect(int(round(wx)) - 24 - sx, int(round(wy)) - 24 - sy, int(round(wx)) + 25 - sx, int(round(wy)) + 25 - sy, sw, sh)
            if clipped is not None:
                x1, y1, x2, y2 = clipped
                mask[y1:y2, x1:x2] = 1
        return mask

    def _update_shelf_bg(self, s_state: Dict[str, Any], cur_gray: np.ndarray, occ_mask: np.ndarray, now: float) -> None:
        bg = s_state["bg_gray"]
        valid = s_state["valid_mask"]
        clean = occ_mask == 0
        if np.any(clean):
            first = clean & (valid == 0)
            if np.any(first):
                bg[first] = cur_gray[first]
                valid[first] = 1
            upd = clean & (valid > 0)
            if np.any(upd):
                bg[upd] = (0.95 * bg[upd]) + (0.05 * cur_gray[upd])

        ring: Deque[Tuple[float, np.ndarray, np.ndarray]] = s_state["lag_ring"]
        if not ring or (now - ring[-1][0]) >= 0.25:
            if np.any(valid > 0):
                ring.append((now, bg.copy(), valid.copy()))

    def _get_pre_snapshot(self, s_state: Dict[str, Any], now: float) -> Tuple[np.ndarray, np.ndarray]:
        ring: Deque[Tuple[float, np.ndarray, np.ndarray]] = s_state["lag_ring"]
        target = now - self.LAG_REF_SEC
        chosen: Optional[Tuple[float, np.ndarray, np.ndarray]] = None
        for entry in ring:
            if entry[0] <= target:
                chosen = entry
        if chosen is not None:
            pre_bg, pre_val = chosen[1].copy(), chosen[2].copy()
        elif ring:
            pre_bg, pre_val = ring[0][1].copy(), ring[0][2].copy()
        else:
            return s_state["bg_gray"].copy(), s_state["valid_mask"].copy()

        # Backfill any pixels that became unoccluded only recently (after target timestamp)
        missing = pre_val == 0
        if np.any(missing):
            for _, r_bg, r_val in reversed(ring):
                fill = missing & (r_val > 0)
                if np.any(fill):
                    pre_bg[fill] = r_bg[fill]
                    pre_val[fill] = 1
                    missing = pre_val == 0
                    if not np.any(missing):
                        break
            if np.any(missing):
                cur_val = s_state["valid_mask"]
                fill = missing & (cur_val > 0)
                if np.any(fill):
                    pre_bg[fill] = s_state["bg_gray"][fill]
                    pre_val[fill] = 1
        return pre_bg, pre_val

    def _reseed_shelf_patch(
        self,
        s_idx: int,
        patch_rect: Tuple[int, int, int, int],
        cur_gray: np.ndarray,
        occ_mask: np.ndarray,
        exclude_tid: int,
    ) -> None:
        s_state = self._shelves.get(s_idx)
        if s_state is None:
            return
        tx1, ty1, tx2, ty2 = patch_rect
        for other_tid, ep in self._episodes.items():
            if other_tid == exclude_tid or ep.get("shelf_idx") != s_idx:
                continue
            other_rect = ep.get("touch_rect")
            if other_rect is not None and _rect_intersects(patch_rect, other_rect):
                return
        clean = occ_mask[ty1:ty2, tx1:tx2] == 0
        if np.any(clean):
            bg_sub = s_state["bg_gray"][ty1:ty2, tx1:tx2]
            val_sub = s_state["valid_mask"][ty1:ty2, tx1:tx2]
            cur_sub = cur_gray[ty1:ty2, tx1:tx2]
            bg_sub[clean] = cur_sub[clean]
            val_sub[clean] = 1

    @staticmethod
    def _measure_patch_delta(
        pre_patch: np.ndarray,
        post_patch: np.ndarray,
        eval_mask: np.ndarray,
    ) -> Tuple[float, float, float, bool]:
        valid_px = int(np.count_nonzero(eval_mask))
        if valid_px < 36:
            return 0.0, 0.0, 0.0, False

        pre_vals = pre_patch[eval_mask]
        post_vals = post_patch[eval_mask]
        pre_mean = float(pre_vals.mean())
        post_mean = float(post_vals.mean())
        pre_std = float(pre_vals.std())
        post_std = float(post_vals.std())

        pre_c = pre_patch - pre_mean
        post_c = post_patch - post_mean
        changed_int = float(np.mean(np.abs(post_c - pre_c)[eval_mask] > 16.0))

        gx1 = cv2.Sobel(pre_patch, cv2.CV_32F, 1, 0, ksize=3)
        gy1 = cv2.Sobel(pre_patch, cv2.CV_32F, 0, 1, ksize=3)
        g1 = cv2.magnitude(gx1, gy1)
        gx2 = cv2.Sobel(post_patch, cv2.CV_32F, 1, 0, ksize=3)
        gy2 = cv2.Sobel(post_patch, cv2.CV_32F, 0, 1, ksize=3)
        g2 = cv2.magnitude(gx2, gy2)
        changed_edge = float(np.mean(np.abs(g2 - g1)[eval_mask] > 20.0))

        # Reject uniform multiplicative/additive illumination shifts when spatial structure matches tightly
        if pre_std >= 6.0 and post_std >= 6.0:
            corr = float(np.mean(((pre_c[eval_mask]) / pre_std) * ((post_c[eval_mask]) / post_std)))
            std_ratio = abs(post_std - pre_std) / max(12.0, pre_std)
            if corr >= 0.92 and std_ratio < 0.45:
                return 0.0, changed_int, changed_edge, False

        score = round(0.60 * changed_int + 0.40 * changed_edge, 4)
        confirmed = score >= 0.12 and (changed_int >= 0.08 or changed_edge >= 0.05)
        return score, round(changed_int, 4), round(changed_edge, 4), confirmed

    def step(
        self,
        frame_bgr: np.ndarray,
        now: float,
        shelf_rects: Sequence[PixelRect],
        track_inputs: Sequence[Dict[str, Any]],
    ) -> Dict[int, Dict[str, Any]]:
        """Update shelf backgrounds and evaluate localized per-track reach deltas.

        Each item in `track_inputs` expects:
        - `tid`: int track ID
        - `bbox`: (x, y, w, h)
        - `wrists`: list of (wx, wy)
        - `reach_active`: bool (whether track currently touches a shelf)
        - `touched_shelf_idx`: Optional[int]
        """
        results: Dict[int, Dict[str, Any]] = {}
        if frame_bgr is None or frame_bgr.size == 0 or not shelf_rects:
            for item in track_inputs:
                tid = int(item["tid"])
                results[tid] = {"status": "no_shelf", "score": 0.0, "confirmed": False, "shelf_idx": None, "touch_rect": None}
            return results

        if frame_bgr.ndim == 2:
            gray_full = frame_bgr.astype(np.float32)
        else:
            gray_full = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        gray_full = cv2.GaussianBlur(gray_full, (5, 5), 0)

        person_boxes: List[PixelRect] = [tuple(int(v) for v in it["bbox"][:4]) for it in track_inputs]
        all_wrists: List[Tuple[int, Tuple[int, int]]] = []
        active_tids = set()
        for it in track_inputs:
            tid = int(it["tid"])
            active_tids.add(tid)
            w_pts = [(int(round(p[0])), int(round(p[1]))) for p in (it.get("wrists") or [])]
            for wp in w_pts:
                all_wrists.append((tid, wp))
            hist = self._wrist_history.setdefault(tid, deque(maxlen=24))
            hist.append((now, w_pts))
            while hist and (now - hist[0][0]) > self.WRIST_HISTORY_SEC:
                hist.popleft()

        active_list = sorted(active_tids)
        for i in range(len(active_list)):
            a = active_list[i]
            for j in range(i + 1, len(active_list)):
                self._coexisting_pairs.add((a, active_list[j]))

        for stale_tid in [k for k in self._wrist_history if k not in active_tids]:
            hist = self._wrist_history[stale_tid]
            if not hist or (now - hist[-1][0]) > self.WRIST_HISTORY_SEC:
                self._wrist_history.pop(stale_tid, None)
                if stale_tid not in self._episodes:
                    self._coexisting_pairs = {p for p in self._coexisting_pairs if stale_tid not in p}

        shelf_cur_grays: Dict[int, np.ndarray] = {}
        shelf_occ_masks: Dict[int, np.ndarray] = {}
        for s_idx, s_rect in enumerate(shelf_rects):
            sx, sy, sw, sh = s_rect
            cur_patch = gray_full[sy:sy + sh, sx:sx + sw]
            if cur_patch.size == 0:
                continue
            s_state = self._ensure_shelf(s_idx, s_rect)
            occ = self._build_occupancy_mask(s_rect, person_boxes, all_wrists)
            self._update_shelf_bg(s_state, cur_patch, occ, now)
            shelf_cur_grays[s_idx] = cur_patch
            shelf_occ_masks[s_idx] = occ

        for stale_idx in [k for k in self._shelves if k >= len(shelf_rects)]:
            self._shelves.pop(stale_idx, None)

        # Track episode creation, contention tracking, and occlusion-aware evaluation
        for it in track_inputs:
            tid = int(it["tid"])
            bx, by, bw, bh = [int(v) for v in it["bbox"][:4]]
            w_pts = [(int(round(p[0])), int(round(p[1]))) for p in (it.get("wrists") or [])]
            reach_active = bool(it.get("reach_active"))
            t_idx = it.get("touched_shelf_idx")
            ep = self._episodes.get(tid)

            # Open/extend localized episode while reaching into a valid shelf
            if reach_active and t_idx is not None and 0 <= int(t_idx) < len(shelf_rects):
                s_idx = int(t_idx)
                s_rect = shelf_rects[s_idx]
                sx, sy, sw, sh = s_rect
                in_wrists = [(wx, wy) for wx, wy in w_pts if sx <= wx < sx + sw and sy <= wy < sy + sh]
                if len(in_wrists) > 1:
                    in_wrists.sort(key=lambda p: min(p[0] - sx, sx + sw - p[0], p[1] - sy, sy + sh - p[1]), reverse=True)
                    anchor = in_wrists[0]
                    in_wrists = [p for p in in_wrists if abs(p[0] - anchor[0]) <= 80 and abs(p[1] - anchor[1]) <= 80]
                if not in_wrists and w_pts:
                    in_wrists = [min(w_pts, key=lambda p: abs(p[0] - (sx + sw * 0.5)) + abs(p[1] - (sy + sh * 0.5)))]

                if in_wrists and (ep is None or ep.get("shelf_idx") != s_idx or ep.get("status") != "confirmed"):
                    r = max(22, min(64, int(bw * 0.30)))
                    s_state = self._shelves.get(s_idx)
                    if ep is None or ep.get("shelf_idx") != s_idx:
                        if s_state is None:
                            continue
                        pre_bg, pre_valid = self._get_pre_snapshot(s_state, now)
                        ep = {
                            "shelf_idx": s_idx,
                            "touch_rect": None,
                            "pre_bg": pre_bg,
                            "pre_valid": pre_valid,
                            "reach_start_ts": now,
                            "last_touch_ts": now,
                            "contested": False,
                            "settle_streak": 0,
                            "status": "pending",
                            "score": 0.0,
                            "confirmed": False,
                        }
                        self._episodes[tid] = ep

                    ep["last_touch_ts"] = now
                    ep["settle_streak"] = 0

                    for wx0, wy0 in in_wrists:
                        lx, ly = wx0 - sx, wy0 - sy
                        new_box = _clamp_rect(lx - r, ly - r, lx + r + 1, ly + r + 1, sw, sh)
                        if new_box is None:
                            continue
                        cur_tr = ep.get("touch_rect")
                        if cur_tr is None:
                            tr = new_box
                        else:
                            ux1 = min(cur_tr[0], new_box[0])
                            uy1 = min(cur_tr[1], new_box[1])
                            ux2 = max(cur_tr[2], new_box[2])
                            uy2 = max(cur_tr[3], new_box[3])
                            if (ux2 - ux1) > self.MAX_PATCH_PX:
                                cx = max(0, min(sw, lx))
                                ux1 = max(0, cx - self.MAX_PATCH_PX // 2)
                                ux2 = min(sw, ux1 + self.MAX_PATCH_PX)
                            if (uy2 - uy1) > self.MAX_PATCH_PX:
                                cy = max(0, min(sh, ly))
                                uy1 = max(0, cy - self.MAX_PATCH_PX // 2)
                                uy2 = min(sh, uy1 + self.MAX_PATCH_PX)
                            tr = _clamp_rect(ux1, uy1, ux2, uy2, sw, sh) or cur_tr
                        ep["touch_rect"] = tr

                        # Retrospectively check if another person's wrist touched this exact spot right before us
                        ex1, ey1, ex2, ey2 = sx + tr[0] - 16, sy + tr[1] - 16, sx + tr[2] + 16, sy + tr[3] + 16
                        for other_tid, o_hist in self._wrist_history.items():
                            if not self._tracks_coexisted(tid, other_tid):
                                continue
                            for ots, o_pts in o_hist:
                                if (now - ots) > self.WRIST_HISTORY_SEC:
                                    continue
                                if any(ex1 <= owx <= ex2 and ey1 <= owy <= ey2 for owx, owy in o_pts):
                                    ep["contested"] = True
                                    ep["status"] = "contested_multi_person"
                                    ep["confirmed"] = False
                                    break

            ep = self._episodes.get(tid)
            if ep is None or ep.get("touch_rect") is None:
                results[tid] = {"status": "none", "score": 0.0, "confirmed": False, "shelf_idx": None, "touch_rect": None}
                continue

            s_idx = int(ep["shelf_idx"])
            s_rect = shelf_rects[s_idx]
            sx, sy, sw, sh = s_rect
            tx1, ty1, tx2, ty2 = ep["touch_rect"]

            # Live contention monitor: another track's wrist inside our localized touch_rect
            ex1, ey1, ex2, ey2 = sx + tx1 - 16, sy + ty1 - 16, sx + tx2 + 16, sy + ty2 + 16
            for other_tid, owp in all_wrists:
                if self._tracks_coexisted(tid, other_tid) and ex1 <= owp[0] <= ex2 and ey1 <= owp[1] <= ey2:
                    ep["contested"] = True
                    ep["status"] = "contested_multi_person"
                    ep["confirmed"] = False
                    break

            cur_gray = shelf_cur_grays.get(s_idx)
            occ = shelf_occ_masks.get(s_idx)
            if not reach_active and ep.get("status") != "confirmed" and not ep["contested"] and cur_gray is not None and occ is not None:
                if (now - ep["last_touch_ts"]) >= self.POST_TOUCH_DELAY_SEC:
                    occ_patch = occ[ty1:ty2, tx1:tx2]
                    pre_val_patch = ep["pre_valid"][ty1:ty2, tx1:tx2]
                    unocc_mask = occ_patch == 0
                    unocc_ratio = float(np.mean(unocc_mask)) if occ_patch.size > 0 else 0.0
                    eval_mask = unocc_mask & (pre_val_patch > 0)
                    valid_ratio = float(np.mean(eval_mask)) if occ_patch.size > 0 else 0.0

                    if unocc_ratio >= self.MIN_UNOCCLUDED_RATIO and valid_ratio >= self.MIN_VALID_BASELINE_RATIO:
                        ep["settle_streak"] += 1
                        if ep["settle_streak"] >= self.SETTLE_FRAMES:
                            pre_p = ep["pre_bg"][ty1:ty2, tx1:tx2]
                            post_p = cur_gray[ty1:ty2, tx1:tx2]
                            score, _, _, confirmed = self._measure_patch_delta(pre_p, post_p, eval_mask)
                            ep["score"] = score
                            ep["confirmed"] = confirmed
                            ep["status"] = "confirmed" if confirmed else "unchanged"
                            if confirmed:
                                self._reseed_shelf_patch(s_idx, (tx1, ty1, tx2, ty2), cur_gray, occ, tid)
                    else:
                        ep["settle_streak"] = 0
                        if ep["status"] in ("pending", "unchanged", "occluded_unverified"):
                            ep["status"] = "occluded_unverified"
                            ep["confirmed"] = False

            results[tid] = {
                "status": ep["status"],
                "score": float(ep["score"]),
                "confirmed": bool(ep["confirmed"]),
                "shelf_idx": s_idx,
                "touch_rect": (sx + tx1, sy + ty1, tx2 - tx1, ty2 - ty1),
            }

        return results
