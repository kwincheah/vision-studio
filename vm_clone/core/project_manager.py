"""
Project and Solution Manager for Vision Master Clone.
Provides persistent storage, recent projects history, project creation,
template scaffolding, loading, saving, and physical file deletion.
"""
import os
import sys
import json
import time
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from PyQt6.QtCore import QSettings

from vm_clone.core.pipeline import VisionPipeline, SolutionManager
from vm_clone.samples.pcb_solution import (
    create_pcb_inspection_solution,
    create_precision_measurement_solution,
    create_calibration_robot_solution,
    create_object_detection_solution
)


class ProjectManager:
    """Manages project files, recent solutions list, and application startup preferences."""

    SETTINGS_KEY = "recent_projects"
    STARTUP_KEY = "general/show_start_page_on_startup"

    def __init__(self, workspace_root: Optional[str] = None):
        if workspace_root:
            self.workspace_root = workspace_root
            self.default_projects_dir = os.path.join(self.workspace_root, "projects")
            self.cache_dir = os.path.join(self.workspace_root, ".vm_config")
            if os.path.abspath(workspace_root) != os.path.abspath("."):
                h = abs(hash(os.path.abspath(workspace_root))) % 1000000
                self.settings = QSettings("ApexVision", f"VisionMasterStudio_Test_{h}")
            else:
                self.settings = QSettings("ApexVision", "VisionMasterStudio")
        else:
            local_proj = os.path.abspath("projects")
            is_frozen = getattr(sys, "frozen", False)
            if os.path.exists(local_proj) and os.access(local_proj, os.W_OK) and not is_frozen:
                self.workspace_root = os.path.abspath(".")
                self.default_projects_dir = local_proj
                self.cache_dir = os.path.join(self.workspace_root, ".vm_config")
            else:
                user_root = os.path.join(os.path.expanduser("~"), ".apex_vision")
                self.workspace_root = user_root
                self.default_projects_dir = os.path.join(os.path.expanduser("~"), "Documents", "ApexVision", "Projects")
                self.cache_dir = os.path.join(user_root, "config")
            self.settings = QSettings("ApexVision", "VisionMasterStudio")

        os.makedirs(self.default_projects_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        self.cache_file = os.path.join(self.cache_dir, "recent_projects.json")

    # =========================================================================
    # Recent Projects Operations
    # =========================================================================

    def get_recent_projects(self) -> List[Dict[str, Any]]:
        """Retrieve recent projects list with live file existence and metadata checks."""
        raw_list = []

        # 1. Try workspace local cache file first
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    raw_list = json.load(f)
            except Exception:
                raw_list = []

        # 2. Fallback to QSettings
        if not raw_list:
            val = self.settings.value(self.SETTINGS_KEY, None)
            if val is not None:
                if isinstance(val, str):
                    try:
                        raw_list = json.loads(val)
                    except Exception:
                        raw_list = []
                elif isinstance(val, list):
                    raw_list = val

        # 3. Verify file status and refresh metadata
        projects = []
        for item in raw_list:
            if not isinstance(item, dict) or "path" not in item:
                continue
            path = os.path.normpath(item["path"])
            exists = os.path.exists(path)
            size_bytes = os.path.getsize(path) if exists else 0
            mtime = ""
            if exists:
                try:
                    dt = datetime.fromtimestamp(os.path.getmtime(path))
                    mtime = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    pass

            entry = {
                "name": item.get("name") or os.path.splitext(os.path.basename(path))[0],
                "path": path,
                "last_opened": item.get("last_opened") or mtime or datetime.now().strftime("%Y-%m-%d %H:%M"),
                "file_exists": exists,
                "size_bytes": size_bytes,
                "template": item.get("template", "Custom"),
                "flow_count": item.get("flow_count", 1)
            }
            projects.append(entry)

        return projects

    def _save_recent_projects(self, projects: List[Dict[str, Any]]):
        """Persist recent projects to both QSettings and local cache file."""
        # Cap at 30 items
        trimmed = projects[:30]
        json_str = json.dumps(trimmed, indent=2)

        try:
            self.settings.setValue(self.SETTINGS_KEY, json_str)
        except Exception:
            pass

        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                f.write(json_str)
        except Exception:
            pass

    def add_recent_project(self, path: str, name: Optional[str] = None, template: str = "Custom", flow_count: int = 1):
        """Add or bump a project to the top of the recent list."""
        norm_path = os.path.normpath(os.path.abspath(path))
        proj_name = name or os.path.splitext(os.path.basename(norm_path))[0]
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        existing = self.get_recent_projects()
        filtered = [p for p in existing if os.path.normpath(p["path"]) != norm_path]

        exists = os.path.exists(norm_path)
        size_bytes = os.path.getsize(norm_path) if exists else 0

        new_entry = {
            "name": proj_name,
            "path": norm_path,
            "last_opened": now_str,
            "file_exists": exists,
            "size_bytes": size_bytes,
            "template": template,
            "flow_count": flow_count
        }

        filtered.insert(0, new_entry)
        self._save_recent_projects(filtered)

    def remove_recent_project(self, path: str):
        """Remove project from recent list without deleting from disk."""
        norm_path = os.path.normpath(os.path.abspath(path))
        existing = self.get_recent_projects()
        filtered = [p for p in existing if os.path.normpath(p["path"]) != norm_path]
        self._save_recent_projects(filtered)

    def delete_project_file(self, path: str, delete_file_from_disk: bool = True) -> Tuple[bool, str]:
        """
        Delete project entry from recent list, optionally deleting physical file from disk.
        Returns (success, message).
        """
        norm_path = os.path.normpath(os.path.abspath(path))
        msg = f"Project '{os.path.basename(norm_path)}' removed from recent list."

        if delete_file_from_disk and os.path.exists(norm_path):
            try:
                os.remove(norm_path)
                msg = f"Project file '{os.path.basename(norm_path)}' permanently deleted from disk."
            except Exception as e:
                # Still remove from recent list
                self.remove_recent_project(norm_path)
                return False, f"Failed to delete file from disk: {str(e)}"

        self.remove_recent_project(norm_path)
        return True, msg

    def clear_recent_projects(self):
        """Clear all entries in recent projects list."""
        self._save_recent_projects([])

    # =========================================================================
    # Project Scaffolding, Loading & Saving
    # =========================================================================

    def create_project(
        self,
        name: str,
        directory: Optional[str] = None,
        template: str = "blank"
    ) -> Tuple[SolutionManager, str]:
        """
        Create a new solution project from template, write file to disk,
        register in recent list, and return (solution, file_path).
        """
        clean_name = re.sub(r'[^\w\-_.]', '_', name.strip()) or "NewSolution"
        target_dir = os.path.abspath(directory or self.default_projects_dir)
        os.makedirs(target_dir, exist_ok=True)

        filepath = os.path.join(target_dir, f"{clean_name}.vmp")

        # Resolve template
        sol = SolutionManager(name=clean_name)
        template_label = "Blank"

        t_key = template.lower().strip()
        if t_key in ("pcb", "pcb_inspection", "pcb inspection"):
            pipe = create_pcb_inspection_solution()
            sol.flows = {pipe.name: pipe}
            sol.active_flow_name = pipe.name
            sol.set_trigger_flow(pipe.name)
            template_label = "PCB Inspection"
        elif t_key in ("measurement", "precision measurement"):
            pipe = create_precision_measurement_solution()
            sol.flows = {pipe.name: pipe}
            sol.active_flow_name = pipe.name
            sol.set_trigger_flow(pipe.name)
            template_label = "Precision Measurement"
        elif t_key in ("calibration", "robot calibration"):
            pipe = create_calibration_robot_solution()
            sol.flows = {pipe.name: pipe}
            sol.active_flow_name = pipe.name
            sol.set_trigger_flow(pipe.name)
            template_label = "Robot Calibration"
        elif t_key in ("yolo", "object_detection", "object detection"):
            pipe = create_object_detection_solution()
            sol.flows = {pipe.name: pipe}
            sol.active_flow_name = pipe.name
            sol.set_trigger_flow(pipe.name)
            template_label = "Object Detection"
        else:
            # Default Blank solution
            sol.flows.clear()
            pipe = VisionPipeline(name="Flow1")
            from vm_clone.core.registry import create_tool_instance
            src = create_tool_instance("Image Source", "node_source", "01_Acquisition")
            pipe.add_node(src)
            sol.flows["Flow1"] = pipe
            sol.active_flow_name = "Flow1"
            sol.set_trigger_flow("Flow1")

        sol.name = clean_name
        sol.save_to_file(filepath)

        self.add_recent_project(
            filepath,
            name=clean_name,
            template=template_label,
            flow_count=len(sol.flows)
        )
        return sol, filepath

    def load_project(self, filepath: str) -> SolutionManager:
        """Load solution file, update recent projects, and return SolutionManager."""
        sol = SolutionManager.load_from_file(filepath)
        self.add_recent_project(
            filepath,
            name=sol.name,
            template="Custom",
            flow_count=len(sol.flows)
        )
        return sol

    def save_project(self, solution: SolutionManager, filepath: str) -> str:
        """Save solution to file and update recent projects."""
        solution.save_to_file(filepath)
        self.add_recent_project(
            filepath,
            name=solution.name,
            template="Custom",
            flow_count=len(solution.flows)
        )
        return filepath

    # =========================================================================
    # Startup Configuration
    # =========================================================================

    def get_show_on_startup(self) -> bool:
        """Whether the start page should be shown on application launch."""
        val = self.settings.value(self.STARTUP_KEY, True)
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes")
        return bool(val)

    def set_show_on_startup(self, enabled: bool):
        """Set whether start page should be shown on application launch."""
        self.settings.setValue(self.STARTUP_KEY, bool(enabled))

    def seed_default_samples_if_empty(self):
        """Seed sample demo projects into default projects directory if recent list is empty."""
        recent = self.get_recent_projects()
        if recent:
            return

        # Create demo projects
        sample_configs = [
            ("PCB_Inspection_Demo", "pcb", "PCB Optical Inspection & Defects"),
            ("Precision_Measurement_Demo", "measurement", "Dimensional Edge & Hole Measurement"),
            ("YOLO_ObjectDetection_Demo", "yolo", "YOLOv11 Deep Learning Object Detection")
        ]
        for name, template_key, _ in sample_configs:
            fpath = os.path.join(self.default_projects_dir, f"{name}.vmp")
            if not os.path.exists(fpath):
                self.create_project(name, self.default_projects_dir, template=template_key)
            else:
                self.add_recent_project(fpath, name=name, template=template_key)
