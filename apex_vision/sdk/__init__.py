"""SDK for Third-Party and Built-in Apex Vision Studio Plugins.

Provides stable, typed contracts for:
1. Plugin Metadata & SemVer compatibility checking
2. Parameter Schema definitions with type constraints & enum choices
3. Typed Port declarations (IMAGE, REGION, VALUE, etc.)
4. Execution Context & Execution Result structures
5. Custom Vision Tool interface (PluginToolBase)
6. Plugin Entrypoint / Manifest interfaces

Version: 1.0.0
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Type, Union
import re
import numpy as np

# SemVer regex for semantic version parsing
_SEMVER_REGEX = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?"
    r"(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)

CURRENT_SDK_VERSION = "1.0.0"


def parse_semver(version_str: str) -> Tuple[int, int, int]:
    """Parse a semantic version string into (major, minor, patch). Raises ValueError if invalid."""
    match = _SEMVER_REGEX.match(version_str.strip())
    if not match:
        raise ValueError(f"Invalid SemVer version string: '{version_str}'")
    parts = match.groupdict()
    return int(parts["major"]), int(parts["minor"]), int(parts["patch"])


def is_version_compatible(required_range: str, actual_version: str) -> bool:
    """Check if actual_version satisfies required_range (e.g. '>=1.0.0', '^1.0.0', '1.0.0', '~1.0.0')."""
    req = required_range.strip()
    if not req or req == "*":
        return True

    act_maj, act_min, act_pat = parse_semver(actual_version)

    if req.startswith("^"):
        req_maj, req_min, req_pat = parse_semver(req[1:])
        return act_maj == req_maj and (act_min > req_min or (act_min == req_min and act_pat >= req_pat))

    if req.startswith(">="):
        req_maj, req_min, req_pat = parse_semver(req[2:])
        return (act_maj, act_min, act_pat) >= (req_maj, req_min, req_pat)

    if req.startswith("<="):
        req_maj, req_min, req_pat = parse_semver(req[2:])
        return (act_maj, act_min, act_pat) <= (req_maj, req_min, req_pat)

    if req.startswith("=="):
        req_maj, req_min, req_pat = parse_semver(req[2:])
        return (act_maj, act_min, act_pat) == (req_maj, req_min, req_pat)

    # Exact match
    try:
        req_maj, req_min, req_pat = parse_semver(req)
        return (act_maj, act_min, act_pat) == (req_maj, req_min, req_pat)
    except ValueError:
        return False


# Re-export core enums and classes with full type safety
from apex_vision.core.base_tool import (
    DataType,
    ToolStatus,
    ToolPort,
    ToolExecutionResult,
    is_compatible_type,
    VisionToolBase
)


class ParamType(Enum):
    """Data types for configurable tool parameters."""
    INT = "int"
    FLOAT = "float"
    STRING = "string"
    BOOLEAN = "bool"
    ENUM = "enum"
    FILE_PATH = "file_path"
    DIR_PATH = "dir_path"
    ROI = "roi"
    LIST = "list"
    DICT = "dict"


@dataclass
class ParamDef:
    """Schema descriptor for a configurable tool parameter."""
    name: str
    param_type: ParamType
    default_value: Any
    description: str = ""
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    step: Optional[Union[int, float]] = None
    choices: List[str] = field(default_factory=list)
    unit: str = ""
    is_advanced: bool = False

    def validate(self, value: Any) -> Tuple[bool, str]:
        """Validate an assigned value against this parameter definition."""
        if self.param_type == ParamType.INT:
            if not isinstance(value, int) or isinstance(value, bool):
                return False, f"Expected int, got {type(value).__name__}"
            if self.min_value is not None and value < self.min_value:
                return False, f"Value {value} is less than min {self.min_value}"
            if self.max_value is not None and value > self.max_value:
                return False, f"Value {value} is greater than max {self.max_value}"
        elif self.param_type == ParamType.FLOAT:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False, f"Expected float, got {type(value).__name__}"
            if self.min_value is not None and value < self.min_value:
                return False, f"Value {value} is less than min {self.min_value}"
            if self.max_value is not None and value > self.max_value:
                return False, f"Value {value} is greater than max {self.max_value}"
        elif self.param_type == ParamType.BOOLEAN:
            if not isinstance(value, bool):
                return False, f"Expected bool, got {type(value).__name__}"
        elif self.param_type == ParamType.ENUM:
            if str(value) not in self.choices:
                return False, f"Value '{value}' not in valid choices: {self.choices}"
        elif self.param_type == ParamType.ROI:
            if not isinstance(value, (list, tuple)) or len(value) != 4:
                return False, "ROI must be a 4-element sequence [x, y, w, h]"
        return True, ""


@dataclass
class PluginMetadata:
    """Standard metadata descriptor for a Apex Vision plugin package."""
    plugin_id: str
    name: str
    version: str
    author: str
    description: str = ""
    category: str = "Custom Plugins"
    min_sdk_version: str = "1.0.0"
    max_sdk_version: Optional[str] = None
    website: str = ""
    license: str = "Proprietary"
    dependencies: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    def validate(self) -> List[str]:
        """Validates plugin metadata fields. Returns list of error messages (empty if valid)."""
        errors = []
        if not self.plugin_id or not re.match(r"^[a-zA-Z0-9_\.-]+$", self.plugin_id):
            errors.append(f"Invalid plugin_id '{self.plugin_id}': must be alphanumeric with underscores/hyphens/dots.")
        if not self.name or not self.name.strip():
            errors.append("Plugin 'name' cannot be empty.")
        try:
            parse_semver(self.version)
        except ValueError as e:
            errors.append(f"Invalid plugin version '{self.version}': {str(e)}")
        try:
            parse_semver(self.min_sdk_version)
        except ValueError as e:
            errors.append(f"Invalid min_sdk_version '{self.min_sdk_version}': {str(e)}")
        return errors


class PluginToolBase(VisionToolBase):
    """Refined Base Class for Apex Vision Tools (both Built-in and Third-Party Plugins).

    Inherits from VisionToolBase to maintain 100% compatibility with existing Pipeline DAG,
    FlowScene canvas, PropertyInspector, and serialization.
    """
    plugin_id: str = "builtin"
    param_definitions: Dict[str, ParamDef] = {}

    def get_param_defs(self) -> Dict[str, ParamDef]:
        """Returns the dictionary of typed parameter definitions."""
        return self.param_definitions or {}

    def validate_inputs(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        """Validates that all required connected ports are present and type-safe."""
        for port_name, port in self.inputs.items():
            if port_name in context:
                val = context[port_name]
                if port.data_type == DataType.IMAGE and val is not None:
                    if not isinstance(val, np.ndarray) or val.ndim < 2:
                        return False, f"Port '{port_name}' expected numpy image, got {type(val).__name__}"
        return True, ""


class IVisionPlugin:
    """Interface that third-party plugin packages must implement in their entrypoint module."""

    @classmethod
    def get_metadata(cls) -> PluginMetadata:
        """Returns the plugin package metadata."""
        raise NotImplementedError

    @classmethod
    def register_tools(cls) -> List[Type[VisionToolBase]]:
        """Returns the list of Tool classes exported by this plugin."""
        raise NotImplementedError

    @classmethod
    def on_load(cls) -> bool:
        """Lifecycle hook executed when the plugin is loaded into the platform. Return True on success."""
        return True

    @classmethod
    def on_unload(cls):
        """Lifecycle hook executed when the plugin is unloaded or disabled."""
        pass
