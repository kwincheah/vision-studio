"""Marketplace and GitHub Extension Platform for Vision Master Clone.

Provides services for:
1. Browsing and searching a curated community plugin catalog.
2. Installing / downloading plugins directly from GitHub repositories (URL or branch ZIP).
3. Scaffolding new plugin projects ready to be pushed to GitHub.
4. Packaging and validating plugins into distributable bundles (.vmpkg / .zip).
5. Checking installed plugin status, updates, and uninstallation.
"""
import os
import re
import sys
import json
import zipfile
import logging
import urllib.request
import urllib.error
import tempfile
import shutil
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

from apex_vision.sdk import CURRENT_SDK_VERSION, PluginMetadata, parse_semver, is_version_compatible
from apex_vision.sdk.manager import PluginManager, PluginRecord, PluginState

logger = logging.getLogger("apex_vision.marketplace")


@dataclass
class MarketplacePluginItem:
    """Represents a plugin available in the online / community marketplace."""
    id: str
    name: str
    version: str
    author: str
    description: str
    category: str
    github_url: str
    download_url: str = ""
    stars: int = 0
    downloads: int = 0
    min_sdk_version: str = "1.0.0"
    tags: List[str] = field(default_factory=list)
    license: str = "MIT"
    installed_version: Optional[str] = None

    @property
    def is_installed(self) -> bool:
        return self.installed_version is not None

    @property
    def has_update(self) -> bool:
        if not self.installed_version:
            return False
        try:
            return parse_semver(self.version) > parse_semver(self.installed_version)
        except Exception:
            return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "category": self.category,
            "github_url": self.github_url,
            "download_url": self.download_url,
            "stars": self.stars,
            "downloads": self.downloads,
            "min_sdk_version": self.min_sdk_version,
            "tags": self.tags,
            "license": self.license,
            "installed_version": self.installed_version,
            "is_installed": self.is_installed,
            "has_update": self.has_update
        }


# Curated catalog of community plugins available in the marketplace
DEFAULT_CATALOG_DATA: List[Dict[str, Any]] = [
    {
        "id": "sample_sobel_edge_plugin",
        "name": "Sobel Edge Detector",
        "version": "1.0.0",
        "author": "ThirdParty Vision Lab",
        "description": "High-performance edge detection using directional Sobel operators.",
        "category": "Custom Filters",
        "github_url": "https://github.com/visionmaster-community/sobel-edge-detector",
        "stars": 128,
        "downloads": 1420,
        "min_sdk_version": "1.0.0",
        "tags": ["edge", "filter", "gradient", "opencv"],
        "license": "Apache-2.0"
    },
    {
        "id": "clahe_contrast_enhancer",
        "name": "CLAHE Contrast Enhancer",
        "version": "1.1.0",
        "author": "Industrial Vision Hub",
        "description": "Contrast Limited Adaptive Histogram Equalization for challenging low-contrast industrial illumination.",
        "category": "Image Processing",
        "github_url": "https://github.com/visionmaster-community/clahe-contrast-enhancer",
        "stars": 94,
        "downloads": 860,
        "min_sdk_version": "1.0.0",
        "tags": ["enhancement", "clahe", "contrast", "histogram"],
        "license": "MIT"
    },
    {
        "id": "hough_circle_detector",
        "name": "Hough Circle Metrology",
        "version": "1.0.2",
        "author": "Apex Metrology Group",
        "description": "Fast Hough transform circular feature detector with sub-pixel center localization and radius measurement.",
        "category": "Measurement",
        "github_url": "https://github.com/visionmaster-community/hough-circle-detector",
        "stars": 156,
        "downloads": 2130,
        "min_sdk_version": "1.0.0",
        "tags": ["circle", "hough", "measurement", "metrology"],
        "license": "MIT"
    },
    {
        "id": "datamatrix_pro_decoder",
        "name": "DataMatrix & QR Decoder Pro",
        "version": "2.0.0",
        "author": "AutoID Solutions",
        "description": "Robust ECC200 DataMatrix, QR Code, and MicroQR reader with DPM (Direct Part Marking) preprocessing.",
        "category": "Recognition",
        "github_url": "https://github.com/visionmaster-community/datamatrix-pro",
        "stars": 230,
        "downloads": 3450,
        "min_sdk_version": "1.0.0",
        "tags": ["barcode", "datamatrix", "qr", "dpm", "id"],
        "license": "BSD-3-Clause"
    },
    {
        "id": "color_segmentation_tool",
        "name": "HSV Color Space Segmenter",
        "version": "1.0.0",
        "author": "VisionCraft AI",
        "description": "Multi-range HSV color mask generator with interactive hue range selection and noise suppression.",
        "category": "Color Processing",
        "github_url": "https://github.com/visionmaster-community/color-segmentation",
        "stars": 72,
        "downloads": 610,
        "min_sdk_version": "1.0.0",
        "tags": ["color", "hsv", "segmentation", "mask"],
        "license": "MIT"
    }
]


class MarketplaceService:
    """Service handling plugin marketplace catalogue, GitHub downloading, and scaffolding."""
    _instance: Optional["MarketplaceService"] = None

    @classmethod
    def get_instance(cls) -> "MarketplaceService":
        if cls._instance is None:
            cls._instance = MarketplaceService()
        return cls._instance

    def __init__(self, workspace_root: Optional[str] = None):
        if workspace_root:
            self.workspace_root = workspace_root
            self.plugins_dir = os.path.join(self.workspace_root, "plugins")
            self.catalog_cache_file = os.path.join(self.workspace_root, ".vm_config", "marketplace_catalog.json")
        else:
            local_plugins = os.path.abspath("plugins")
            is_frozen = getattr(sys, "frozen", False)
            if os.path.exists(local_plugins) and os.access(local_plugins, os.W_OK) and not is_frozen:
                self.workspace_root = os.path.abspath(".")
                self.plugins_dir = local_plugins
                self.catalog_cache_file = os.path.join(self.workspace_root, ".vm_config", "marketplace_catalog.json")
            else:
                user_root = os.path.join(os.path.expanduser("~"), ".apex_vision")
                self.workspace_root = user_root
                self.plugins_dir = os.path.join(user_root, "plugins")
                self.catalog_cache_file = os.path.join(user_root, "marketplace_catalog.json")

        os.makedirs(self.plugins_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self.catalog_cache_file), exist_ok=True)
        self._cached_catalog: Optional[List[MarketplacePluginItem]] = None

    # =========================================================================
    # Catalog Browsing & Searching
    # =========================================================================

    def get_catalog(self, refresh: bool = False) -> List[MarketplacePluginItem]:
        """Returns the list of marketplace plugins merged with local installation status."""
        if self._cached_catalog is None or refresh:
            self._cached_catalog = self._load_catalog_data()

        # Update local installation status
        pm = PluginManager.get_instance()
        if not getattr(pm, "_discovered", False):
            pm.discover_and_load_all()
        installed_plugins = {p.metadata.plugin_id: p.metadata.version for p in pm.list_plugins()}

        for item in self._cached_catalog:
            item.installed_version = installed_plugins.get(item.id)

        return self._cached_catalog

    def _load_catalog_data(self) -> List[MarketplacePluginItem]:
        """Loads catalog from local cache file or falls back to curated default list."""
        data_list = []
        if os.path.exists(self.catalog_cache_file):
            try:
                with open(self.catalog_cache_file, "r", encoding="utf-8") as f:
                    data_list = json.load(f)
            except Exception as e:
                logger.warning(f"Could not read marketplace cache: {e}")
                data_list = DEFAULT_CATALOG_DATA
        else:
            data_list = DEFAULT_CATALOG_DATA

        items = []
        for d in data_list:
            items.append(MarketplacePluginItem(
                id=d["id"],
                name=d["name"],
                version=d.get("version", "1.0.0"),
                author=d.get("author", "Community"),
                description=d.get("description", ""),
                category=d.get("category", "Custom Plugins"),
                github_url=d.get("github_url", ""),
                download_url=d.get("download_url", ""),
                stars=d.get("stars", 0),
                downloads=d.get("downloads", 0),
                min_sdk_version=d.get("min_sdk_version", "1.0.0"),
                tags=d.get("tags", []),
                license=d.get("license", "MIT")
            ))
        return items

    def search(
        self,
        query: str = "",
        category: Optional[str] = None
    ) -> List[MarketplacePluginItem]:
        """Filter marketplace items by search query and category."""
        catalog = self.get_catalog()
        q = query.strip().lower()

        results = []
        for item in catalog:
            if category and category != "All" and item.category != category:
                continue
            if q:
                match = (
                    q in item.name.lower() or
                    q in item.description.lower() or
                    q in item.author.lower() or
                    q in item.id.lower() or
                    any(q in tag.lower() for tag in item.tags)
                )
                if not match:
                    continue
            results.append(item)
        return results

    # =========================================================================
    # GitHub URL Parsing & Repository Installation
    # =========================================================================

    @staticmethod
    def parse_github_url(url: str) -> Optional[Tuple[str, str, str]]:
        """Parses a GitHub repo URL into (owner, repo, branch).

        Supports:
        - https://github.com/owner/repo
        - https://github.com/owner/repo.git
        - https://github.com/owner/repo/tree/branch_name
        - owner/repo
        """
        clean = url.strip()
        if not clean:
            return None

        # Clean git suffix
        if clean.endswith(".git"):
            clean = clean[:-4]

        # owner/repo format
        if re.match(r"^[a-zA-Z0-9_\.-]+/[a-zA-Z0-9_\.-]+$", clean):
            parts = clean.split("/")
            return parts[0], parts[1], "main"

        # Full URL
        m = re.match(r"^https?://github\.com/([a-zA-Z0-9_\.-]+)/([a-zA-Z0-9_\.-]+)(?:/tree/([a-zA-Z0-9_\.-]+))?", clean)
        if m:
            owner = m.group(1)
            repo = m.group(2)
            branch = m.group(3) or "main"
            return owner, repo, branch

        return None

    def install_from_github(
        self,
        repo_url: str,
        branch: str = "main",
        target_dir: Optional[str] = None
    ) -> Tuple[bool, str, Optional[PluginRecord]]:
        """Downloads, validates, and installs a plugin directly from a GitHub repository."""
        parsed = self.parse_github_url(repo_url)
        if not parsed:
            return False, f"Invalid GitHub URL: '{repo_url}'. Expected format: https://github.com/owner/repo", None

        owner, repo, specified_branch = parsed
        effective_branch = branch if branch != "main" else specified_branch

        # Construct GitHub archive download URL
        zip_url = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{effective_branch}"

        dest_base = target_dir or self.plugins_dir
        os.makedirs(dest_base, exist_ok=True)

        temp_dir = tempfile.mkdtemp(prefix="vm_github_download_")
        zip_path = os.path.join(temp_dir, f"{repo}.zip")

        try:
            # 1. Download repository zip archive
            logger.info(f"Downloading plugin from GitHub: {zip_url}...")
            req = urllib.request.Request(
                zip_url,
                headers={"User-Agent": "VisionMaster-Studio-PluginManager/1.0"}
            )
            with urllib.request.urlopen(req, timeout=20.0) as resp, open(zip_path, "wb") as out_f:
                shutil.copyfileobj(resp, out_f)

            # 2. Extract archive
            extract_dir = os.path.join(temp_dir, "extracted")
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

            # GitHub zips typically extract to a root folder like repo-branch/
            subitems = os.listdir(extract_dir)
            if not subitems:
                return False, "Downloaded GitHub archive is empty.", None

            repo_root = os.path.join(extract_dir, subitems[0]) if len(subitems) == 1 and os.path.isdir(os.path.join(extract_dir, subitems[0])) else extract_dir

            # 3. Validate Plugin Structure
            is_valid, validation_errors = self.validate_plugin_directory(repo_root)
            if not is_valid:
                return False, f"GitHub repository does not meet plugin standards: {'; '.join(validation_errors)}", None

            # Read plugin_id from manifest
            manifest_path = os.path.join(repo_root, "plugin.json")
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            plugin_id = manifest_data.get("id", repo)
            if (
                not isinstance(plugin_id, str)
                or plugin_id in (".", "..")
                or not re.fullmatch(r"[a-zA-Z0-9_.-]+", plugin_id)
            ):
                return False, f"Invalid plugin id {plugin_id!r}: only letters, digits, '_', '.', '-' are allowed.", None

            # 4. Copy to target destination in plugins/
            final_plugin_dir = os.path.join(dest_base, plugin_id)
            real_base = os.path.realpath(dest_base)
            if os.path.dirname(os.path.realpath(final_plugin_dir)) != real_base:
                return False, f"Plugin id {plugin_id!r} resolves outside the plugins directory.", None

            if os.path.exists(final_plugin_dir):
                # Unload first if previously active
                pm = PluginManager.get_instance()
                pm.unload_plugin(plugin_id)
                shutil.rmtree(final_plugin_dir, ignore_errors=True)

            shutil.copytree(repo_root, final_plugin_dir)

            # 5. Load and Register in PluginManager
            pm = PluginManager.get_instance()
            record = pm.load_plugin_from_directory(final_plugin_dir, reload=True)

            if record and record.state == PluginState.LOADED:
                return True, f"Successfully installed and loaded '{record.metadata.name}' v{record.metadata.version} from GitHub.", record
            elif record:
                return False, f"Installed but loaded with warning ({record.state}): {record.error_message}", record
            else:
                return False, "Failed to load installed plugin into runtime.", None

        except urllib.error.HTTPError as e:
            return False, f"GitHub HTTP error {e.code}: {e.reason} for {zip_url}", None
        except urllib.error.URLError as e:
            return False, f"Network connection error accessing GitHub: {e.reason}", None
        except Exception as e:
            logger.exception(f"Unexpected error installing from GitHub: {e}")
            return False, f"Installation error: {str(e)}", None
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # =========================================================================
    # Plugin Scaffolding & Creator (Developer Tools)
    # =========================================================================

    def scaffold_plugin(
        self,
        dest_parent_dir: str,
        plugin_id: str,
        name: str,
        author: str,
        category: str = "Custom Filters",
        tool_name: str = "Custom Vision Tool",
        description: str = "",
        min_sdk_version: str = "1.0.0"
    ) -> Tuple[bool, str, str]:
        """Creates a complete, GitHub-ready plugin repository directory structure."""
        clean_id = re.sub(r"[^a-zA-Z0-9_\.-]", "_", plugin_id.strip())
        if not clean_id:
            return False, "Invalid plugin ID", ""

        plugin_dir = os.path.join(dest_parent_dir, clean_id)
        if os.path.exists(plugin_dir):
            return False, f"Directory already exists: {plugin_dir}", ""

        try:
            os.makedirs(plugin_dir, exist_ok=True)
            tests_dir = os.path.join(plugin_dir, "tests")
            os.makedirs(tests_dir, exist_ok=True)

            # 1. plugin.json manifest
            manifest = {
                "id": clean_id,
                "name": name.strip() or clean_id,
                "version": "1.0.0",
                "author": author.strip() or "Third-Party Developer",
                "description": description.strip() or f"{name} extension for Vision Master Studio.",
                "category": category.strip() or "Custom Plugins",
                "min_sdk_version": min_sdk_version,
                "entrypoint": "__init__.py",
                "license": "MIT",
                "tags": [category.lower().replace(" ", "-"), "vision-master", "plugin"],
                "website": f"https://github.com/{author.lower().replace(' ', '')}/{clean_id}"
            }
            with open(os.path.join(plugin_dir, "plugin.json"), "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)

            # 2. __init__.py tool implementation
            clean_class_name = re.sub(r"[^a-zA-Z0-9_]", "", tool_name.title().replace(" ", "")) + "Tool"
            clean_plugin_cls = re.sub(r"[^a-zA-Z0-9_]", "", name.title().replace(" ", "")) + "Plugin"

            code = f'''"""Vision Master Plugin: {name}
Author: {author}
License: MIT
"""
import cv2
import numpy as np
from typing import Dict, Any, List, Type

from apex_vision.sdk import (
    IVisionPlugin,
    PluginMetadata,
    PluginToolBase,
    ParamDef,
    ParamType,
    DataType,
    ToolPort,
    ToolExecutionResult,
    ToolStatus,
)


class {clean_class_name}(PluginToolBase):
    """Custom Vision Tool implementation."""
    plugin_id = "{clean_id}"
    category = "{category}"
    tool_name = "{tool_name}"
    description = "{description or f'Custom processing algorithm for {tool_name}'}"

    param_definitions = {{
        "threshold": ParamDef(
            name="threshold",
            param_type=ParamType.INT,
            default_value=128,
            description="Binarization/filtering threshold value (0-255)",
            min_value=0,
            max_value=255,
            step=1
        ),
        "invert_output": ParamDef(
            name="invert_output",
            param_type=ParamType.BOOLEAN,
            default_value=False,
            description="Invert processed binary or grayscale output"
        )
    }}

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image to process")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Processed output image")
        self.outputs["Metric_Value"] = ToolPort("Metric_Value", DataType.VALUE, "Computed feature scalar metric")

    def _init_parameters(self):
        self.parameters = {{
            "threshold": 128,
            "invert_output": False
        }}

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        img = self.get_input_image(context)
        if img is None:
            return ToolExecutionResult(status=ToolStatus.NG, message="No valid input image provided")

        try:
            gray = self.to_grayscale(img)
            thresh_val = int(self.get_param("threshold", 128))
            invert = bool(self.get_param("invert_output", False))

            mode = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
            _, binary = cv2.threshold(gray, thresh_val, 255, mode)
            dst_bgr = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)

            mean_val = float(np.mean(binary))

            return ToolExecutionResult(
                status=ToolStatus.OK,
                outputs={{
                    "Image": dst_bgr,
                    "Metric_Value": mean_val
                }},
                message=f"{tool_name} executed successfully"
            )
        except Exception as e:
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"Processing error in {tool_name}: {{str(e)}}"
            )


class {clean_plugin_cls}(IVisionPlugin):
    """Entry point plugin descriptor for Vision Master Studio."""

    @classmethod
    def get_metadata(cls) -> PluginMetadata:
        return PluginMetadata(
            plugin_id="{clean_id}",
            name="{name}",
            version="1.0.0",
            author="{author}",
            description="{description}",
            category="{category}",
            min_sdk_version="{min_sdk_version}"
        )

    @classmethod
    def register_tools(cls) -> List[Type[PluginToolBase]]:
        return [{clean_class_name}]

    @classmethod
    def on_load(cls) -> bool:
        return True

    @classmethod
    def on_unload(cls):
        pass
'''
            with open(os.path.join(plugin_dir, "__init__.py"), "w", encoding="utf-8") as f:
                f.write(code)

            # 3. README.md with GitHub instructions
            readme = f"""# {name}

A custom vision extension tool for **Vision Master Studio**.

## Features
- **Tool:** `{tool_name}`
- **Category:** `{category}`
- **SDK Compatibility:** Requires Vision Master Studio SDK >= `{min_sdk_version}`

## Installation via Vision Master Studio
1. Open Vision Master Studio.
2. Go to **Tools -> Plugin Manager...** -> **Install from GitHub**.
3. Enter repository URL: `https://github.com/{author.lower().replace(' ', '')}/{clean_id}`
4. Click **Install & Verify**.

## Author
Developed by {author}.
"""
            with open(os.path.join(plugin_dir, "README.md"), "w", encoding="utf-8") as f:
                f.write(readme)

            # 4. .gitignore
            gitignore = "__pycache__/\n*.pyc\n.pytest_cache/\n*.vmpkg\n*.zip\n"
            with open(os.path.join(plugin_dir, ".gitignore"), "w", encoding="utf-8") as f:
                f.write(gitignore)

            return True, f"Successfully scaffolded plugin '{name}' at {plugin_dir}", plugin_dir

        except Exception as e:
            shutil.rmtree(plugin_dir, ignore_errors=True)
            return False, f"Failed to scaffold plugin: {str(e)}", ""

    # =========================================================================
    # Validation & Packaging
    # =========================================================================

    def validate_plugin_directory(self, plugin_dir: str) -> Tuple[bool, List[str]]:
        """Validates that a local or cloned directory meets all plugin requirements."""
        errors = []
        if not os.path.exists(plugin_dir):
            return False, [f"Directory not found: {plugin_dir}"]

        manifest_path = os.path.join(plugin_dir, "plugin.json")
        init_path = os.path.join(plugin_dir, "__init__.py")

        if not os.path.exists(manifest_path):
            errors.append("Missing 'plugin.json' manifest file.")
        else:
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest_data = json.load(f)
                if not manifest_data.get("id"):
                    errors.append("'plugin.json' must specify an 'id'.")
                if not manifest_data.get("name"):
                    errors.append("'plugin.json' must specify a 'name'.")
                if not manifest_data.get("version"):
                    errors.append("'plugin.json' must specify a 'version'.")
                else:
                    try:
                        parse_semver(manifest_data["version"])
                    except Exception as e:
                        errors.append(f"Invalid 'version' SemVer in plugin.json: {e}")
            except Exception as e:
                errors.append(f"Failed to parse 'plugin.json': {str(e)}")

        if not os.path.exists(init_path):
            errors.append("Missing entrypoint '__init__.py'.")

        return len(errors) == 0, errors

    def package_plugin(self, plugin_dir: str, output_path: Optional[str] = None) -> Tuple[bool, str, str]:
        """Packages a plugin into a distributable .zip or .vmpkg archive ready for GitHub Releases."""
        is_valid, errors = self.validate_plugin_directory(plugin_dir)
        if not is_valid:
            return False, f"Cannot package invalid plugin: {'; '.join(errors)}", ""

        plugin_id = os.path.basename(os.path.normpath(plugin_dir))
        out_file = output_path or os.path.join(os.path.dirname(plugin_dir), f"{plugin_id}.vmpkg")

        try:
            with zipfile.ZipFile(out_file, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(plugin_dir):
                    # Exclude pycache and git
                    dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", ".pytest_cache")]
                    for file in files:
                        if file.endswith((".pyc", ".pyo")):
                            continue
                        abs_file = os.path.join(root, file)
                        rel_path = os.path.relpath(abs_file, plugin_dir)
                        zf.write(abs_file, rel_path)

            return True, f"Successfully packaged plugin into {out_file}", out_file
        except Exception as e:
            return False, f"Failed to package plugin: {str(e)}", ""
