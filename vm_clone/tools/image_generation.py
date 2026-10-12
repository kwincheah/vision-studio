"""
Image Generation & Geometry Tools.
Matches HikRobot Vision Master Image Generation category:
- Geometry Fit (Circle Fit, Ellipse Fit, Line Fit on the basis of 3+ feature points)
- Geometry Generation (Auxiliary fixture graphics: synthetic datum lines, center points, reference circles)
"""
import cv2
import numpy as np
from typing import Dict, Any, List
from vm_clone.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, ToolPort, DataType
from vm_clone.core.registry import register_tool


@register_tool
class GeometryFitTool(VisionToolBase):
    category = "Image Generation"
    tool_name = "Circle/Line Fit"
    description = "Fits circle or line on the basis of 3 or more coordinate feature points."

    def _init_ports(self):
        self.inputs["Point_Set"] = ToolPort("Point_Set", DataType.ANY, "List of (x, y) coordinates")
        self.outputs["Center_X"] = ToolPort("Center_X", DataType.VALUE, "Fitted Center X")
        self.outputs["Center_Y"] = ToolPort("Center_Y", DataType.VALUE, "Fitted Center Y")
        self.outputs["Radius"] = ToolPort("Radius", DataType.VALUE, "Fitted Radius")
        self.outputs["Angle_Deg"] = ToolPort("Angle_Deg", DataType.VALUE, "Fitted Line Angle")

    def _init_parameters(self):
        self.parameters = {
            "fit_type": "Circle Fit",  # Circle Fit, Line Fit
            "default_points": [[100, 200], [200, 100], [300, 200], [200, 300]]
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        pts_in = context.get("Point_Set") or self.get_param("default_points")
        fit_t = self.get_param("fit_type", "Circle Fit")

        if not pts_in or len(pts_in) < 3:
            return ToolExecutionResult(status=ToolStatus.NG, message="At least 3 points required for geometry fitting")

        pts = np.array(pts_in, dtype=np.float32)

        if fit_t == "Circle Fit":
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

            A = np.array([[Suu, Suv], [Suv, Svv]], dtype=np.float32)
            B = 0.5 * np.array([Suuu + Suvv, Svvv + Svuu], dtype=np.float32)

            try:
                c_uv = np.linalg.solve(A, B)
                cx = float(mx + c_uv[0])
                cy = float(my + c_uv[1])
                r = float(np.mean(np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)))

                overlays = [
                    {"type": "circle", "center": (int(cx), int(cy)), "radius": int(r), "color": (0, 240, 255), "label": f"Fit R={r:.1f}"},
                    {"type": "cross", "pt": (int(cx), int(cy)), "size": 8, "color": (255, 180, 0)}
                ]

                return ToolExecutionResult(
                    status=ToolStatus.OK,
                    message=f"Fitted Circle: Center=({cx:.1f}, {cy:.1f}), R={r:.2f} ({len(pts)} pts)",
                    outputs={"Center_X": cx, "Center_Y": cy, "Radius": r, "Angle_Deg": 0.0},
                    overlays=overlays
                )
            except np.linalg.LinAlgError:
                return ToolExecutionResult(status=ToolStatus.NG, message="Singular matrix in circle fit")

        else:  # Line Fit
            vx, vy, x0, y0 = cv2.fitLine(pts, cv2.DIST_L2, 0, 0.01, 0.01).flatten()
            angle = float(np.degrees(np.arctan2(vy, vx)))
            t_min = np.min((pts[:, 0] - x0) * vx + (pts[:, 1] - y0) * vy)
            t_max = np.max((pts[:, 0] - x0) * vx + (pts[:, 1] - y0) * vy)
            p1 = (int(x0 + t_min * vx), int(y0 + t_min * vy))
            p2 = (int(x0 + t_max * vx), int(y0 + t_max * vy))

            overlays = [
                {"type": "line", "pt1": p1, "pt2": p2, "color": (0, 240, 255), "thickness": 2},
                {"type": "text", "text": f"Fit Line {angle:.1f}°", "pt": (p1[0], p1[1] - 8), "color": (0, 240, 255)}
            ]

            return ToolExecutionResult(
                status=ToolStatus.OK,
                message=f"Fitted Line: Angle={angle:.2f}° ({len(pts)} pts)",
                outputs={"Center_X": float(x0), "Center_Y": float(y0), "Radius": 0.0, "Angle_Deg": angle},
                overlays=overlays
            )


@register_tool
class GeometryGenerationTool(VisionToolBase):
    category = "Image Generation"
    tool_name = "Geometry Generation"
    description = "Generates synthetic auxiliary geometric fixtures (Datum lines, Crosshairs, Circles)."

    def _init_ports(self):
        self.outputs["Line"] = ToolPort("Line", DataType.LINE, "Generated line segment")
        self.outputs["Circle"] = ToolPort("Circle", DataType.CIRCLE, "Generated reference circle")
        self.outputs["Point"] = ToolPort("Point", DataType.POINT, "Generated reference point")

    def _init_parameters(self):
        self.parameters = {
            "geom_type": "Datum Cross",  # Datum Cross, Reference Line, Pitch Circle
            "center_x": 400.0,
            "center_y": 300.0,
            "radius": 50.0,
            "line_p1": [100.0, 300.0],
            "line_p2": [700.0, 300.0]
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        gtype = self.get_param("geom_type", "Datum Cross")
        cx = float(self.get_param("center_x", 400.0))
        cy = float(self.get_param("center_y", 300.0))
        r = float(self.get_param("radius", 50.0))
        p1 = self.get_param("line_p1", [100.0, 300.0])
        p2 = self.get_param("line_p2", [700.0, 300.0])

        overlays = []
        if gtype == "Datum Cross":
            overlays.append({"type": "cross", "pt": (int(cx), int(cy)), "size": 25, "color": (255, 179, 0)})
            overlays.append({"type": "text", "text": f"Datum ({cx:.0f}, {cy:.0f})", "pt": (int(cx) + 10, int(cy) - 10), "color": (255, 179, 0)})
        elif gtype == "Pitch Circle":
            overlays.append({"type": "circle", "center": (int(cx), int(cy)), "radius": int(r), "color": (255, 179, 0), "label": f"Pitch R={r:.0f}"})
        else:
            overlays.append({"type": "line", "pt1": (int(p1[0]), int(p1[1])), "pt2": (int(p2[0]), int(p2[1])), "color": (255, 179, 0), "thickness": 1})

        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=f"Generated {gtype} at ({cx:.1f}, {cy:.1f})",
            outputs={
                "Point": (cx, cy),
                "Circle": {"cx": cx, "cy": cy, "r": r},
                "Line": {"x1": p1[0], "y1": p1[1], "x2": p2[0], "y2": p2[1]}
            },
            overlays=overlays
        )
