"""
Location and Geometric Search Tools.
Implements the reference product Location modules:
- Template Match (NCC with multi-angle rotation search, sub-pixel peak, match score, angle, bounding box)
- Circle Search (Caliper radial rays + sub-pixel edge points extraction + algebraic/Kasa circle fitting)
- Line Search (Perpendicular caliper rakes + sub-pixel edge transition detection + M-estimator line fitting)
- Caliper (1D sub-pixel edge transition and distance caliper with polarity, contrast, and edge pair modes)
- BLOB Analysis (Connected component labeling, area, centroid, bounding box, filter)
- Edge Search (1D ray transition with first/last/strongest edge detection)
- Position Correction (Establishes reference vs running point/angle deviation to modify downstream tool ROIs)
"""
import cv2
import numpy as np
from typing import Dict, Any, Tuple, Optional
from apex_vision.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, ToolPort, DataType
from apex_vision.core.registry import register_tool


def _subpixel_peak_1d(profile: np.ndarray, peak_idx: int) -> float:
    """Quadratic / parabolic interpolation for 1D sub-pixel peak estimation."""
    if peak_idx <= 0 or peak_idx >= len(profile) - 1:
        return float(peak_idx)
    y0 = float(profile[peak_idx - 1])
    y1 = float(profile[peak_idx])
    y2 = float(profile[peak_idx + 1])
    denom = 2.0 * (2.0 * y1 - y0 - y2)
    if abs(denom) < 1e-6:
        return float(peak_idx)
    delta = (y0 - y2) / denom
    return float(peak_idx) + np.clip(delta, -1.0, 1.0)


def _find_edge_points_along_ray(
    gray: np.ndarray,
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    polarity: str = "Any",  # Dark to light, Light to dark, Any
    edge_type: str = "Strongest Edge",  # Strongest Edge, First Edge, Last Edge
    threshold: float = 20.0
) -> Optional[Tuple[float, float, float]]:
    """
    Samples pixels along segment (p1->p2), computes 1D gradient, and finds the sub-pixel edge.
    Returns: (edge_x, edge_y, strength) or None
    """
    x1, y1 = p1
    x2, y2 = p2
    length = int(np.hypot(x2 - x1, y2 - y1))
    if length < 4:
        return None

    h, w = gray.shape[:2]
    xs = np.linspace(x1, x2, length)
    ys = np.linspace(y1, y2, length)

    valid = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
    if np.count_nonzero(valid) < 4:
        return None

    xs_v = xs[valid]
    ys_v = ys[valid]

    # Bilinear or nearest sample
    profile = gray[ys_v.astype(int), xs_v.astype(int)].astype(np.float32)
    if profile.size < 2:
        return None
    grad = np.gradient(profile)

    # Filter polarity
    if polarity == "Dark to light":
        grad_filt = np.where(grad > 0, grad, 0.0)
    elif polarity == "Light to dark":
        grad_filt = np.where(grad < 0, -grad, 0.0)
    else:  # Any
        grad_filt = np.abs(grad)

    candidates = np.where(grad_filt >= threshold)[0]
    if len(candidates) == 0:
        return None

    if edge_type == "First Edge":
        sel_idx = candidates[0]
    elif edge_type == "Last Edge":
        sel_idx = candidates[-1]
    else:  # Strongest
        sel_idx = candidates[np.argmax(grad_filt[candidates])]

    sub_idx = _subpixel_peak_1d(grad_filt, sel_idx)
    sub_idx = np.clip(sub_idx, 0, len(xs_v) - 1)
    
    # Linear interpolation of (x, y)
    edge_x = float(np.interp(sub_idx, np.arange(len(xs_v)), xs_v))
    edge_y = float(np.interp(sub_idx, np.arange(len(ys_v)), ys_v))
    strength = float(grad_filt[int(round(sub_idx))])

    return (edge_x, edge_y, strength)


@register_tool
class TemplateMatchTool(VisionToolBase):
    category = "Location"
    tool_name = "Template Match"
    description = "Searches for a template pattern with confidence score, subpixel translation, and rotation angle."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Pass-through image")
        self.outputs["Score"] = ToolPort("Score", DataType.VALUE, "Match score (0.0 - 1.0)")
        self.outputs["Center_X"] = ToolPort("Center_X", DataType.VALUE, "Matched center X")
        self.outputs["Center_Y"] = ToolPort("Center_Y", DataType.VALUE, "Matched center Y")
        self.outputs["Angle"] = ToolPort("Angle", DataType.VALUE, "Rotation angle in degrees")
        self.outputs["Box"] = ToolPort("Box", DataType.REGION, "Matched bounding box [x, y, w, h]")

    def _init_parameters(self):
        self.parameters = {
            "min_score": 0.65,
            "template_roi": [260, 240, 180, 120],  # Default bounding box for template
            "start_angle": -15.0,
            "end_angle": 15.0,
            "angle_step": 2.0,
            "max_matches": 1
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided")

        gray = self.to_grayscale(img)
        h, w = gray.shape[:2]

        tx, ty, tw, th = self.get_param("template_roi", [260, 240, 180, 120])
        tx = max(0, min(tx, w - 10))
        ty = max(0, min(ty, h - 10))
        tw = max(10, min(tw, w - tx))
        th = max(10, min(th, h - ty))

        template = gray[ty:ty+th, tx:tx+tw]
        if template.size == 0 or template.shape[0] < 5 or template.shape[1] < 5:
            return ToolExecutionResult(status=ToolStatus.NG, message="Invalid template dimensions")

        min_score = float(self.get_param("min_score", 0.65))
        start_ang = float(self.get_param("start_angle", -15.0))
        end_ang = float(self.get_param("end_angle", 15.0))
        step_ang = max(0.5, float(self.get_param("angle_step", 2.0)))

        # Multi-angle search
        best_score = -1.0
        best_loc = (0, 0)
        best_angle = 0.0

        tpl_h, tpl_w = template.shape[:2]
        tpl_center = (tpl_w / 2.0, tpl_h / 2.0)

        # Optimization: if angle range is 0, test single 0° orientation
        angles = [0.0] if abs(start_ang) < 1e-4 and abs(end_ang) < 1e-4 else np.arange(start_ang, end_ang + 0.1, step_ang)

        for ang in angles:
            if abs(ang) < 1e-3:
                rot_tpl = template
            else:
                rot_mat = cv2.getRotationMatrix2D(tpl_center, ang, 1.0)
                rot_tpl = cv2.warpAffine(template, rot_mat, (tpl_w, tpl_h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

            if rot_tpl.shape[0] > gray.shape[0] or rot_tpl.shape[1] > gray.shape[1]:
                continue

            res = cv2.matchTemplate(gray, rot_tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)

            if max_val > best_score:
                best_score = float(max_val)
                best_loc = max_loc
                best_angle = float(ang)

        matched_box = [int(best_loc[0]), int(best_loc[1]), int(tw), int(th)]
        center_x = float(best_loc[0] + tw / 2.0)
        center_y = float(best_loc[1] + th / 2.0)

        status = ToolStatus.OK if best_score >= min_score else ToolStatus.NG
        msg = f"Match score: {best_score:.3f} (Min: {min_score}) at ({center_x:.1f}, {center_y:.1f}), Angle: {best_angle:.1f}°"

        overlays = [
            {
                "type": "rect",
                "box": matched_box,
                "color": (0, 255, 0) if status == ToolStatus.OK else (0, 0, 255),
                "label": f"Match: {best_score:.2f} ({best_angle:.1f}°)"
            },
            {
                "type": "cross",
                "pt": (int(center_x), int(center_y)),
                "size": 12,
                "color": (0, 255, 255)
            }
        ]

        return ToolExecutionResult(
            status=status,
            message=msg,
            outputs={
                "Image": img,
                "Score": best_score,
                "Center_X": center_x,
                "Center_Y": center_y,
                "Angle": best_angle,
                "Box": matched_box
            },
            overlays=overlays
        )


@register_tool
class PositionCorrectionTool(VisionToolBase):
    category = "Location"
    tool_name = "Position Correction"
    description = "Establishes reference match point & angle to calculate position deviation for subsequent tool ROIs."

    def _init_ports(self):
        self.inputs["Running_X"] = ToolPort("Running_X", DataType.VALUE, "Matched running X coordinate")
        self.inputs["Running_Y"] = ToolPort("Running_Y", DataType.VALUE, "Matched running Y coordinate")
        self.inputs["Running_Angle"] = ToolPort("Running_Angle", DataType.VALUE, "Matched running Angle (deg)")
        self.outputs["Delta_X"] = ToolPort("Delta_X", DataType.VALUE, "X shift deviation (pixels)")
        self.outputs["Delta_Y"] = ToolPort("Delta_Y", DataType.VALUE, "Y shift deviation (pixels)")
        self.outputs["Delta_Angle"] = ToolPort("Delta_Angle", DataType.VALUE, "Angle deviation (degrees)")
        self.outputs["Affine_Matrix"] = ToolPort("Affine_Matrix", DataType.ANY, "2x3 Affine transformation matrix")

    def _init_parameters(self):
        self.parameters = {
            "fiducial_x": 350.0,
            "fiducial_y": 300.0,
            "fiducial_angle": 0.0,
            "set_current_as_fiducial": False
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        # The three running pose values arrive from a match/correction chain, so any
        # of them can be absent, `None`, a string, or non-finite.  `float()` raised on
        # all of those, and a non-finite value then propagated NaN through the affine
        # matrix into every downstream module.  `as_float` substitutes the fiducial
        # default and the run continues with a corrected pose.
        fallback_x = self.as_float(self.get_param("fiducial_x", 350.0), 350.0)
        fallback_y = self.as_float(self.get_param("fiducial_y", 300.0), 300.0)
        run_x = self.as_float(context.get("Running_X"), fallback_x)
        run_y = self.as_float(context.get("Running_Y"), fallback_y)
        run_ang = self.as_float(context.get("Running_Angle"), 0.0)

        if self.get_param("set_current_as_fiducial", False):
            self.set_param("fiducial_x", run_x)
            self.set_param("fiducial_y", run_y)
            self.set_param("fiducial_angle", run_ang)
            self.set_param("set_current_as_fiducial", False)

        f_x = self.as_float(self.get_param("fiducial_x", 350.0), 350.0)
        f_y = self.as_float(self.get_param("fiducial_y", 300.0), 300.0)
        f_ang = self.as_float(self.get_param("fiducial_angle", 0.0), 0.0)

        dx = run_x - f_x
        dy = run_y - f_y
        d_ang = run_ang - f_ang

        # Compute 2x3 Affine transform: translate(-f) -> rotate(d_ang) -> translate(f + [dx, dy])
        rad = np.radians(d_ang)
        cos_a = np.cos(rad)
        sin_a = np.sin(rad)
        tx = run_x - (cos_a * f_x - sin_a * f_y)
        ty = run_y - (sin_a * f_x + cos_a * f_y)
        affine_mat = np.array([[cos_a, -sin_a, tx], [sin_a, cos_a, ty]], dtype=np.float32)

        overlays = [
            {"type": "cross", "pt": (int(f_x), int(f_y)), "size": 10, "color": (150, 150, 150)},
            {"type": "cross", "pt": (int(run_x), int(run_y)), "size": 10, "color": (0, 255, 255)},
            {"type": "text", "text": f"Delta: ({dx:+.1f}, {dy:+.1f}, {d_ang:+.1f}°)", "pt": (int(run_x) + 10, int(run_y) - 10), "color": (0, 255, 255)}
        ]

        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=f"Position deviation: dX={dx:+.2f}, dY={dy:+.2f}, dAngle={d_ang:+.2f}°",
            outputs={
                "Delta_X": dx,
                "Delta_Y": dy,
                "Delta_Angle": d_ang,
                "Affine_Matrix": affine_mat
            },
            overlays=overlays
        )


@register_tool
class CircleSearchTool(VisionToolBase):
    category = "Location"
    tool_name = "Circle Search"
    description = "Searches circular holes and features using multi-ray calipers and circle fitting."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Pass-through image")
        self.outputs["Center_X"] = ToolPort("Center_X", DataType.VALUE, "Circle center X")
        self.outputs["Center_Y"] = ToolPort("Center_Y", DataType.VALUE, "Circle center Y")
        self.outputs["Radius"] = ToolPort("Radius", DataType.VALUE, "Circle radius")
        self.outputs["Circle"] = ToolPort("Circle", DataType.CIRCLE, "Circle dict (cx, cy, r)")

    def _init_parameters(self):
        self.parameters = {
            "center_x": 680,
            "center_y": 480,
            "min_radius": 20,
            "max_radius": 75,
            "caliper_rays": 32,
            "edge_polarity": "Any",      # Dark to light, Light to dark, Any
            "edge_type": "Strongest Edge",# Strongest Edge, First Edge, Last Edge
            "edge_threshold": 25.0
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided")

        gray = self.to_grayscale(img)

        cx_init = float(self.get_param("center_x", 680))
        cy_init = float(self.get_param("center_y", 480))
        min_r = float(self.get_param("min_radius", 20))
        max_r = float(self.get_param("max_radius", 75))
        num_rays = max(8, int(self.get_param("caliper_rays", 32)))
        polarity = self.get_param("edge_polarity", "Any")
        edge_t = self.get_param("edge_type", "Strongest Edge")
        thresh = float(self.get_param("edge_threshold", 25.0))

        # Industrial multi-ray caliper scan
        angles = np.linspace(0, 2 * np.pi, num_rays, endpoint=False)
        edge_points = []
        overlays = []

        for ang in angles:
            p1 = (cx_init + min_r * np.cos(ang), cy_init + min_r * np.sin(ang))
            p2 = (cx_init + max_r * np.cos(ang), cy_init + max_r * np.sin(ang))
            res_pt = _find_edge_points_along_ray(gray, p1, p2, polarity=polarity, edge_type=edge_t, threshold=thresh)
            if res_pt:
                ex, ey, _ = res_pt
                edge_points.append([ex, ey])
                overlays.append({"type": "cross", "pt": (int(ex), int(ey)), "size": 3, "color": (0, 255, 255)})

        # Fit circle from edge points (Kasa / Pratt algebraic fit)
        if len(edge_points) >= 6:
            pts = np.array(edge_points, dtype=np.float32)
            # Center of mass
            mx = np.mean(pts[:, 0])
            my = np.mean(pts[:, 1])
            u = pts[:, 0] - mx
            v = pts[:, 1] - my

            Suu = np.sum(u * u)
            Suv = np.sum(u * v)
            Svv = np.sum(v * v)
            Suuu = np.sum(u * u * u)
            Suvv = np.sum(u * v * v)
            Svvv = np.sum(v * v * v)
            Svuu = np.sum(v * u * u)

            # Solve linear system for (uc, vc)
            A = np.array([[Suu, Suv], [Suv, Svv]], dtype=np.float32)
            B = 0.5 * np.array([Suuu + Suvv, Svvv + Svuu], dtype=np.float32)

            try:
                c_uv = np.linalg.solve(A, B)
                cx = float(mx + c_uv[0])
                cy = float(my + c_uv[1])
                r = float(np.mean(np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)))

                overlays.append({"type": "circle", "center": (int(cx), int(cy)), "radius": int(r), "color": (0, 255, 0), "label": f"R={r:.1f}px"})
                overlays.append({"type": "cross", "pt": (int(cx), int(cy)), "size": 8, "color": (255, 0, 0)})

                return ToolExecutionResult(
                    status=ToolStatus.OK,
                    message=f"Circle found at ({cx:.1f}, {cy:.1f}), radius={r:.2f}px ({len(edge_points)} caliper points)",
                    outputs={
                        "Image": img,
                        "Center_X": cx,
                        "Center_Y": cy,
                        "Radius": r,
                        "Circle": {"cx": cx, "cy": cy, "r": r}
                    },
                    overlays=overlays
                )
            except np.linalg.LinAlgError:
                pass

        # Fallback to Hough Circle if caliper ray points were insufficient
        gray_b = cv2.GaussianBlur(gray, (5, 5), 1.5)
        circles = cv2.HoughCircles(gray_b, cv2.HOUGH_GRADIENT, dp=1, minDist=40, param1=60, param2=30, minRadius=int(min_r), maxRadius=int(max_r))
        if circles is not None and len(circles) > 0:
            c = circles[0][0]
            cx, cy, r = float(c[0]), float(c[1]), float(c[2])
            overlays.append({"type": "circle", "center": (int(cx), int(cy)), "radius": int(r), "color": (0, 255, 0), "label": f"R={r:.1f}px"})
            return ToolExecutionResult(
                status=ToolStatus.OK,
                message=f"Circle found (Hough fallback) at ({cx:.1f}, {cy:.1f}), radius={r:.1f}",
                outputs={"Image": img, "Center_X": cx, "Center_Y": cy, "Radius": r, "Circle": {"cx": cx, "cy": cy, "r": r}},
                overlays=overlays
            )

        return ToolExecutionResult(
            status=ToolStatus.NG,
            message="No circle detected within specified parameters",
            outputs={"Image": img, "Center_X": 0.0, "Center_Y": 0.0, "Radius": 0.0}
        )


@register_tool
class LineSearchTool(VisionToolBase):
    category = "Location"
    tool_name = "Line Search"
    description = "Searches straight edges using perpendicular caliper rakes and M-estimator line fitting."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Pass-through image")
        self.outputs["Angle_Deg"] = ToolPort("Angle_Deg", DataType.VALUE, "Line orientation angle in degrees")
        self.outputs["Line"] = ToolPort("Line", DataType.LINE, "Line coordinates (x1, y1, x2, y2)")

    def _init_parameters(self):
        self.parameters = {
            "start_pt": [50, 150],
            "end_pt": [450, 150],
            "caliper_rake_width": 40,
            "caliper_count": 25,
            "edge_polarity": "Any",
            "edge_type": "Strongest Edge",
            "edge_threshold": 25.0
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided")

        gray = self.to_grayscale(img)

        p_start = self.get_param("start_pt", [50, 150])
        p_end = self.get_param("end_pt", [450, 150])
        x1, y1 = float(p_start[0]), float(p_start[1])
        x2, y2 = float(p_end[0]), float(p_end[1])

        rake_w = float(self.get_param("caliper_rake_width", 40))
        num_calipers = max(5, int(self.get_param("caliper_count", 25)))
        polarity = self.get_param("edge_polarity", "Any")
        edge_t = self.get_param("edge_type", "Strongest Edge")
        thresh = float(self.get_param("edge_threshold", 25.0))

        # Base line normal vector
        line_dx = x2 - x1
        line_dy = y2 - y1
        line_len = np.hypot(line_dx, line_dy)
        if line_len < 10:
            return ToolExecutionResult(status=ToolStatus.NG, message="Line ROI length too short")

        norm_x = -line_dy / line_len
        norm_y = line_dx / line_len

        # Sample edge points along perpendicular rakes
        edge_points = []
        overlays = []

        fractions = np.linspace(0.05, 0.95, num_calipers)
        for f in fractions:
            mx = x1 + f * line_dx
            my = y1 + f * line_dy
            rp1 = (mx - norm_x * (rake_w / 2.0), my - norm_y * (rake_w / 2.0))
            rp2 = (mx + norm_x * (rake_w / 2.0), my + norm_y * (rake_w / 2.0))

            res_pt = _find_edge_points_along_ray(gray, rp1, rp2, polarity=polarity, edge_type=edge_t, threshold=thresh)
            if res_pt:
                ex, ey, _ = res_pt
                edge_points.append([ex, ey])
                overlays.append({"type": "cross", "pt": (int(ex), int(ey)), "size": 3, "color": (255, 180, 0)})

        if len(edge_points) >= 4:
            pts = np.array(edge_points, dtype=np.float32)
            # M-estimator robust line fit via cv2.fitLine
            vx, vy, x0, y0 = cv2.fitLine(pts, cv2.DIST_L2, 0, 0.01, 0.01).flatten()

            # Project endpoints
            t_min = np.min((pts[:, 0] - x0) * vx + (pts[:, 1] - y0) * vy)
            t_max = np.max((pts[:, 0] - x0) * vx + (pts[:, 1] - y0) * vy)
            fx1, fy1 = float(x0 + t_min * vx), float(y0 + t_min * vy)
            fx2, fy2 = float(x0 + t_max * vx), float(y0 + t_max * vy)

            angle = float(np.degrees(np.arctan2(vy, vx)))

            overlays.append({"type": "line", "pt1": (int(fx1), int(fy1)), "pt2": (int(fx2), int(fy2)), "color": (0, 255, 255), "thickness": 2})
            overlays.append({"type": "text", "text": f"Line {angle:.1f}° ({len(edge_points)} pts)", "pt": (int(fx1), int(fy1) - 10), "color": (0, 255, 255)})

            return ToolExecutionResult(
                status=ToolStatus.OK,
                message=f"Line found: Angle={angle:.2f}°, ({len(edge_points)} caliper points)",
                outputs={
                    "Image": img,
                    "Angle_Deg": angle,
                    "Line": {"x1": fx1, "y1": fy1, "x2": fx2, "y2": fy2, "length": float(np.hypot(fx2 - fx1, fy2 - fy1))}
                },
                overlays=overlays
            )

        # Fallback to Canny + Hough
        edges = cv2.Canny(gray, 50, 150)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=40, minLineLength=50, maxLineGap=15)
        if lines is not None and len(lines) > 0:
            l = np.asarray(lines).reshape(-1, 4)[0]
            angle = float(np.degrees(np.arctan2(l[3] - l[1], l[2] - l[0])))
            return ToolExecutionResult(
                status=ToolStatus.OK,
                message=f"Line found (Hough fallback): Angle={angle:.2f}°",
                outputs={"Image": img, "Angle_Deg": angle, "Line": {"x1": float(l[0]), "y1": float(l[1]), "x2": float(l[2]), "y2": float(l[3]), "length": float(np.hypot(l[2]-l[0], l[3]-l[1]))}},
                overlays=[{"type": "line", "pt1": (l[0], l[1]), "pt2": (l[2], l[3]), "color": (0, 255, 255), "thickness": 2}]
            )

        return ToolExecutionResult(
            status=ToolStatus.NG,
            message="No line detected",
            outputs={"Image": img, "Angle_Deg": 0.0, "Line": None}
        )


@register_tool
class CaliperTool(VisionToolBase):
    category = "Location"
    tool_name = "Caliper"
    description = "1D subpixel edge profile caliper for single edge or edge pair distance & width measurement."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Distance"] = ToolPort("Distance", DataType.VALUE, "Distance between caliper edges")
        self.outputs["Edge1"] = ToolPort("Edge1", DataType.POINT, "First edge point")
        self.outputs["Edge2"] = ToolPort("Edge2", DataType.POINT, "Second edge point")

    def _init_parameters(self):
        self.parameters = {
            "line_p1": [100, 300],  # Caliper projection line start
            "line_p2": [500, 300],  # Caliper projection line end
            "edge_threshold": 25.0,
            "polarity": "Any",       # Dark to Light, Light to Dark, Any
            "caliper_mode": "Edge Pair"  # Single Edge, Edge Pair
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided")

        gray = self.to_grayscale(img)

        p1 = self.get_param("line_p1", [100, 300])
        p2 = self.get_param("line_p2", [500, 300])
        x1, y1 = float(p1[0]), float(p1[1])
        x2, y2 = float(p2[0]), float(p2[1])

        length = int(np.hypot(x2 - x1, y2 - y1))
        if length < 5:
            return ToolExecutionResult(status=ToolStatus.NG, message="Caliper line length too short")

        h, w = gray.shape[:2]
        xs = np.linspace(x1, x2, length)
        ys = np.linspace(y1, y2, length)

        valid = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
        xs_v = xs[valid]
        ys_v = ys[valid]
        if len(xs_v) < 2:
            return ToolExecutionResult(status=ToolStatus.NG, message="Caliper line ROI outside image bounds")

        profile = gray[ys_v.astype(int), xs_v.astype(int)].astype(np.float32)
        grad = np.gradient(profile)

        pol = str(self.get_param("polarity", "Any")).strip().lower()      # "Dark to light" in the editor, older files say "Dark to Light"
        if pol == "dark to light":
            grad_filt = np.where(grad > 0, grad, 0.0)
        elif pol == "light to dark":
            grad_filt = np.where(grad < 0, -grad, 0.0)
        else:
            grad_filt = np.abs(grad)

        thresh = float(self.get_param("edge_threshold", 25.0))
        peaks = np.where(grad_filt >= thresh)[0]

        if len(peaks) >= 2:
            p_first = peaks[0]
            p_last = peaks[-1]
            sub1 = _subpixel_peak_1d(grad_filt, p_first)
            sub2 = _subpixel_peak_1d(grad_filt, p_last)

            e1_x = float(np.interp(sub1, np.arange(len(xs_v)), xs_v))
            e1_y = float(np.interp(sub1, np.arange(len(ys_v)), ys_v))
            e2_x = float(np.interp(sub2, np.arange(len(xs_v)), xs_v))
            e2_y = float(np.interp(sub2, np.arange(len(ys_v)), ys_v))

            dist = float(np.hypot(e2_x - e1_x, e2_y - e1_y))

            overlays = [
                {"type": "line", "pt1": (int(x1), int(y1)), "pt2": (int(x2), int(y2)), "color": (120, 120, 255), "thickness": 1},
                {"type": "cross", "pt": (int(e1_x), int(e1_y)), "size": 8, "color": (0, 240, 255)},
                {"type": "cross", "pt": (int(e2_x), int(e2_y)), "size": 8, "color": (0, 240, 255)},
                {"type": "text", "text": f"Caliper: {dist:.2f}px", "pt": (int((e1_x+e2_x)/2), int((e1_y+e2_y)/2) - 10), "color": (0, 240, 255)}
            ]

            return ToolExecutionResult(
                status=ToolStatus.OK,
                message=f"Caliper width: {dist:.2f}px",
                outputs={
                    "Distance": dist,
                    "Edge1": (e1_x, e1_y),
                    "Edge2": (e2_x, e2_y)
                },
                overlays=overlays
            )

        return ToolExecutionResult(
            status=ToolStatus.NG,
            message="Could not find edge pair along caliper line",
            outputs={"Distance": 0.0, "Edge1": None, "Edge2": None}
        )


@register_tool
class EdgeSearchTool(VisionToolBase):
    category = "Location"
    tool_name = "Edge Search"
    description = "Searches feature edge transition along projection ray (First, Last, Strongest Edge)."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Edge_X"] = ToolPort("Edge_X", DataType.VALUE, "Detected edge subpixel X")
        self.outputs["Edge_Y"] = ToolPort("Edge_Y", DataType.VALUE, "Detected edge subpixel Y")
        self.outputs["Strength"] = ToolPort("Strength", DataType.VALUE, "Edge gradient strength")

    def _init_parameters(self):
        self.parameters = {
            "start_pt": [100, 250],
            "end_pt": [500, 250],
            "edge_type": "Strongest Edge",  # Strongest Edge, First Edge, Last Edge
            "polarity": "Any",              # Dark to light, Light to dark, Any
            "edge_threshold": 25.0
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided")

        gray = self.to_grayscale(img)

        p1 = self.get_param("start_pt", [100, 250])
        p2 = self.get_param("end_pt", [500, 250])
        e_type = self.get_param("edge_type", "Strongest Edge")
        pol = self.get_param("polarity", "Any")
        thresh = float(self.get_param("edge_threshold", 25.0))

        res_pt = _find_edge_points_along_ray(gray, (p1[0], p1[1]), (p2[0], p2[1]), polarity=pol, edge_type=e_type, threshold=thresh)
        if res_pt:
            ex, ey, s = res_pt
            overlays = [
                {"type": "line", "pt1": (int(p1[0]), int(p1[1])), "pt2": (int(p2[0]), int(p2[1])), "color": (100, 100, 160), "thickness": 1},
                {"type": "cross", "pt": (int(ex), int(ey)), "size": 10, "color": (0, 255, 0)},
                {"type": "text", "text": f"Edge ({ex:.1f}, {ey:.1f}) S:{s:.0f}", "pt": (int(ex) + 8, int(ey) - 8), "color": (0, 255, 0)}
            ]
            return ToolExecutionResult(
                status=ToolStatus.OK,
                message=f"Edge found at ({ex:.2f}, {ey:.2f}), Strength={s:.1f}",
                outputs={"Edge_X": ex, "Edge_Y": ey, "Strength": s},
                overlays=overlays
            )

        return ToolExecutionResult(status=ToolStatus.NG, message="No edge transition found along ray", outputs={"Edge_X": 0.0, "Edge_Y": 0.0, "Strength": 0.0})


@register_tool
class BlobAnalysisTool(VisionToolBase):
    category = "Location"
    tool_name = "BLOB Analysis"
    description = "Extracts connected binary regions, filters by area/circularity, and finds centroids."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Pass-through image")
        self.outputs["Count"] = ToolPort("Count", DataType.VALUE, "Number of blobs found")
        self.outputs["Blobs"] = ToolPort("Blobs", DataType.ANY, "List of detected blob dictionaries")

    def _init_parameters(self):
        self.parameters = {
            "threshold": 128,
            "invert": False,
            "min_area": 50,
            "max_area": 50000,
            "min_circularity": 0.0
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided")

        gray = self.to_grayscale(img)
        thresh_val = int(self.get_param("threshold", 128))
        invert = bool(self.get_param("invert", False))

        ttype = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
        _, binary = cv2.threshold(gray, thresh_val, 255, ttype)

        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)

        min_area = float(self.get_param("min_area", 50))
        max_area = float(self.get_param("max_area", 50000))
        min_circ = float(self.get_param("min_circularity", 0.0))

        blobs = []
        overlays = []

        for i in range(1, num_labels):
            area = stats[i, cv2.CC_STAT_AREA]
            if area < min_area or area > max_area:
                continue

            bx = stats[i, cv2.CC_STAT_LEFT]
            by = stats[i, cv2.CC_STAT_TOP]
            bw = stats[i, cv2.CC_STAT_WIDTH]
            bh = stats[i, cv2.CC_STAT_HEIGHT]
            cx, cy = centroids[i]

            perimeter = 2 * (bw + bh)
            circ = (4 * np.pi * area) / (perimeter * perimeter + 1e-5)
            if circ < min_circ:
                continue

            blob_info = {
                "id": i,
                "cx": float(cx),
                "cy": float(cy),
                "area": float(area),
                "box": [int(bx), int(by), int(bw), int(bh)],
                "circularity": float(circ)
            }
            blobs.append(blob_info)

            overlays.append({
                "type": "rect",
                "box": [int(bx), int(by), int(bw), int(bh)],
                "color": (255, 120, 0),
                "label": f"#{len(blobs)} Area:{area}"
            })
            overlays.append({
                "type": "cross",
                "pt": (int(cx), int(cy)),
                "size": 6,
                "color": (0, 255, 0)
            })

        status = ToolStatus.OK if len(blobs) > 0 else ToolStatus.NG
        return ToolExecutionResult(
            status=status,
            message=f"Detected {len(blobs)} blob(s)",
            outputs={
                "Image": img,
                "Count": len(blobs),
                "Blobs": blobs
            },
            overlays=overlays
        )
