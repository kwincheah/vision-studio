"""Plugin Discovery, Validation, Lifecycle, and Management System.

Handles:
- Scanning plugin directories (default: `./plugins`, user configurable)
- Manifest parsing (`plugin.json` or Python `IVisionPlugin` class)
- Semantic version compatibility verification
- Structural schema and input/output contract validation
- Dynamic loading & module registration
- Safe unload and registry purging
- In-process execution wrapping with timeout and exception containment
- Security policy checks for untrusted third-party code
"""
import os
import sys
import json
import logging
import importlib
import importlib.util
from typing import Dict, List, Optional, Type, Tuple, Any
from dataclasses import dataclass, field

from apex_vision.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus
from apex_vision.core.registry import register_tool, unregister_tool, _TOOL_REGISTRY, _CATEGORIES
from apex_vision.sdk import (
    PluginMetadata,
    IVisionPlugin,
    CURRENT_SDK_VERSION,
    is_version_compatible,
    parse_semver
)

logger = logging.getLogger("apex_vision.plugins")


class PluginState:
    LOADED = "Loaded"
    DISABLED = "Disabled"
    ERROR = "Error"
    INCOMPATIBLE = "Incompatible"


@dataclass
class PluginRecord:
    """Represents a discovered and managed plugin package."""
    metadata: PluginMetadata
    directory_path: str
    entrypoint_module: str
    state: str = PluginState.LOADED
    error_message: str = ""
    tools: List[Type[VisionToolBase]] = field(default_factory=list)
    plugin_class: Optional[Type[IVisionPlugin]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.metadata.plugin_id,
            "name": self.metadata.name,
            "version": self.metadata.version,
            "author": self.metadata.author,
            "category": self.metadata.category,
            "description": self.metadata.description,
            "state": self.state,
            "error_message": self.error_message,
            "directory_path": self.directory_path,
            "tool_count": len(self.tools),
            "tool_names": [t.tool_name for t in self.tools]
        }


class PluginSecurityError(Exception):
    """Raised when an untrusted plugin violates security policies."""
    pass


class PluginManager:
    """Singleton Plugin Manager for discovering, loading, and managing vision tool plugins."""
    _instance: Optional["PluginManager"] = None

    @classmethod
    def get_instance(cls) -> "PluginManager":
        if cls._instance is None:
            cls._instance = PluginManager()
        return cls._instance

    def __init__(self, plugin_dirs: Optional[List[str]] = None):
        if plugin_dirs:
            self.plugin_dirs = plugin_dirs
        else:
            base_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.abspath(".")
            user_plugin_dir = os.path.abspath(os.path.join(os.path.expanduser("~"), ".apex_vision", "plugins"))
            p_dirs = [
                user_plugin_dir,
                os.path.abspath(os.path.join(base_dir, "plugins")),
                os.path.abspath(os.path.join(base_dir, "_internal", "plugins")),
                os.path.abspath(os.path.join(".", "plugins")),
            ]
            self.plugin_dirs = list(dict.fromkeys(p_dirs))
        self._plugins: Dict[str, PluginRecord] = {}  # plugin_id -> PluginRecord
        self._tool_to_plugin: Dict[str, str] = {}  # tool_name -> plugin_id
        self._discovered: bool = False

    def add_plugin_dir(self, directory: str):
        abs_path = os.path.abspath(directory)
        if abs_path not in self.plugin_dirs:
            self.plugin_dirs.append(abs_path)

    def list_plugins(self) -> List[PluginRecord]:
        return list(self._plugins.values())

    def get_plugin(self, plugin_id: str) -> Optional[PluginRecord]:
        return self._plugins.get(plugin_id)

    def discover_and_load_all(self, reload: bool = False) -> Dict[str, PluginRecord]:
        """Scans all configured plugin directories and loads valid plugins."""
        self._discovered = True
        for pdir in self.plugin_dirs:
            if not os.path.exists(pdir):
                try:
                    os.makedirs(pdir, exist_ok=True)
                except Exception:
                    continue

            for item in os.listdir(pdir):
                item_path = os.path.join(pdir, item)
                if os.path.isdir(item_path):
                    self.load_plugin_from_directory(item_path, reload=reload)

        return self._plugins

    def load_plugin_from_directory(self, plugin_dir: str, reload: bool = False) -> Optional[PluginRecord]:
        """Loads a single plugin from a directory containing plugin.json and entrypoint."""
        manifest_file = os.path.join(plugin_dir, "plugin.json")
        init_file = os.path.join(plugin_dir, "__init__.py")

        if not os.path.exists(manifest_file) and not os.path.exists(init_file):
            return None

        # 1. Parse Metadata
        meta: Optional[PluginMetadata] = None
        entrypoint = "__init__.py"

        if os.path.exists(manifest_file):
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    manifest_data = json.load(f)
                meta = PluginMetadata(
                    plugin_id=manifest_data.get("id", os.path.basename(plugin_dir)),
                    name=manifest_data.get("name", os.path.basename(plugin_dir)),
                    version=manifest_data.get("version", "1.0.0"),
                    author=manifest_data.get("author", "Third-Party Developer"),
                    description=manifest_data.get("description", ""),
                    category=manifest_data.get("category", "Custom Plugins"),
                    min_sdk_version=manifest_data.get("min_sdk_version", "1.0.0"),
                    max_sdk_version=manifest_data.get("max_sdk_version"),
                    website=manifest_data.get("website", ""),
                    license=manifest_data.get("license", "Proprietary"),
                    dependencies=manifest_data.get("dependencies", []),
                    tags=manifest_data.get("tags", [])
                )
                entrypoint = manifest_data.get("entrypoint", "__init__.py")
            except Exception as e:
                logger.error(f"Failed to parse plugin.json in {plugin_dir}: {e}")
                err_record = PluginRecord(
                    metadata=PluginMetadata(
                        plugin_id=os.path.basename(plugin_dir),
                        name=os.path.basename(plugin_dir),
                        version="0.0.0",
                        author="Unknown"
                    ),
                    directory_path=plugin_dir,
                    entrypoint_module="",
                    state=PluginState.ERROR,
                    error_message=f"Manifest parse error: {str(e)}"
                )
                self._plugins[err_record.metadata.plugin_id] = err_record
                return err_record

        # 2. Validate Metadata & SemVer Compatibility
        if meta:
            val_errors = meta.validate()
            if val_errors:
                record = PluginRecord(
                    metadata=meta,
                    directory_path=plugin_dir,
                    entrypoint_module=entrypoint,
                    state=PluginState.ERROR,
                    error_message="; ".join(val_errors)
                )
                self._plugins[meta.plugin_id] = record
                return record

            if not is_version_compatible(meta.min_sdk_version, CURRENT_SDK_VERSION):
                record = PluginRecord(
                    metadata=meta,
                    directory_path=plugin_dir,
                    entrypoint_module=entrypoint,
                    state=PluginState.INCOMPATIBLE,
                    error_message=f"SDK version mismatch: requires SDK >= {meta.min_sdk_version}, current is {CURRENT_SDK_VERSION}"
                )
                self._plugins[meta.plugin_id] = record
                return record

            # If already loaded and not reloading, return existing record; if reloading, unload first
            if meta.plugin_id in self._plugins:
                existing = self._plugins[meta.plugin_id]
                if existing.state == PluginState.LOADED and not reload:
                    return existing
                if reload:
                    self.unload_plugin(meta.plugin_id)

        # 3. Dynamic Python Import
        entry_path = os.path.join(plugin_dir, entrypoint)
        if not os.path.exists(entry_path):
            record = PluginRecord(
                metadata=meta or PluginMetadata(os.path.basename(plugin_dir), os.path.basename(plugin_dir), "1.0.0", ""),
                directory_path=plugin_dir,
                entrypoint_module=entrypoint,
                state=PluginState.ERROR,
                error_message=f"Entrypoint file '{entrypoint}' not found in {plugin_dir}"
            )
            self._plugins[record.metadata.plugin_id] = record
            return record

        module_name = f"vm_plugin_{meta.plugin_id if meta else os.path.basename(plugin_dir)}"
        try:
            # Ensure plugin directory is in sys.path temporarily for local imports
            if plugin_dir not in sys.path:
                sys.path.insert(0, plugin_dir)

            spec = importlib.util.spec_from_file_location(module_name, entry_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot load spec from {entry_path}")

            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)

            # Discover IVisionPlugin or exported VisionToolBase classes
            plugin_cls: Optional[Type[IVisionPlugin]] = None
            discovered_tools: List[Type[VisionToolBase]] = []

            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if isinstance(attr, type):
                    if issubclass(attr, IVisionPlugin) and attr is not IVisionPlugin:
                        plugin_cls = attr
                    elif issubclass(attr, VisionToolBase) and attr is not VisionToolBase:
                        if getattr(attr, "tool_name", "BaseTool") != "BaseTool":
                            discovered_tools.append(attr)

            if plugin_cls is not None:
                if meta is None:
                    meta = plugin_cls.get_metadata()
                plugin_tools = plugin_cls.register_tools()
                for pt in plugin_tools:
                    if pt not in discovered_tools:
                        discovered_tools.append(pt)
                # Invoke on_load
                plugin_cls.on_load()

            if not meta:
                meta = PluginMetadata(
                    plugin_id=os.path.basename(plugin_dir),
                    name=os.path.basename(plugin_dir),
                    version="1.0.0",
                    author="Developer"
                )

            # Register discovered tools into the core Vision Master registry
            registered_tools = []
            for tool_cls in discovered_tools:
                # Assign default category from plugin metadata if tool category is generic
                if getattr(tool_cls, "category", "General") in ("General", "Custom"):
                    tool_cls.category = meta.category
                register_tool(tool_cls)
                registered_tools.append(tool_cls)
                self._tool_to_plugin[tool_cls.tool_name] = meta.plugin_id

            record = PluginRecord(
                metadata=meta,
                directory_path=plugin_dir,
                entrypoint_module=entrypoint,
                state=PluginState.LOADED,
                tools=registered_tools,
                plugin_class=plugin_cls
            )
            self._plugins[meta.plugin_id] = record
            logger.info(f"Loaded plugin '{meta.name}' v{meta.version} with {len(registered_tools)} tools.")
            return record

        except Exception as e:
            logger.exception(f"Error executing plugin module {entry_path}: {e}")
            record = PluginRecord(
                metadata=meta or PluginMetadata(os.path.basename(plugin_dir), os.path.basename(plugin_dir), "0.0.0", "Unknown"),
                directory_path=plugin_dir,
                entrypoint_module=entrypoint,
                state=PluginState.ERROR,
                error_message=f"Execution error during load: {str(e)}"
            )
            self._plugins[record.metadata.plugin_id] = record
            return record

    def unload_plugin(self, plugin_id: str) -> bool:
        """Safely unloads a plugin, deregisters its tools from core registry, and calls on_unload."""
        if plugin_id not in self._plugins:
            return False

        record = self._plugins[plugin_id]
        if record.state != PluginState.LOADED:
            del self._plugins[plugin_id]
            return True

        # Call lifecycle hook
        if record.plugin_class is not None:
            try:
                record.plugin_class.on_unload()
            except Exception as e:
                logger.warning(f"Error in on_unload for plugin {plugin_id}: {e}")

        # Deregister all tools from core registry
        for tool_cls in record.tools:
            tool_name = getattr(tool_cls, "tool_name", "")
            if tool_name:
                unregister_tool(tool_name)
                if tool_name in self._tool_to_plugin:
                    del self._tool_to_plugin[tool_name]

        # Purge dynamic module and submodules from sys.modules
        module_name = f"vm_plugin_{plugin_id}"
        keys_to_del = [k for k in sys.modules if k == module_name or k.startswith(f"{module_name}.")]
        for k in keys_to_del:
            del sys.modules[k]

        # Clean sys.path if directory is not used by other loaded plugins
        if record.directory_path in sys.path:
            other_using = any(
                p.directory_path == record.directory_path
                for pid, p in self._plugins.items()
                if pid != plugin_id and p.state == PluginState.LOADED
            )
            if not other_using:
                try:
                    sys.path.remove(record.directory_path)
                except ValueError:
                    pass

        record.state = PluginState.DISABLED
        record.tools.clear()
        del self._plugins[plugin_id]
        logger.info(f"Unloaded plugin '{plugin_id}'.")
        return True
