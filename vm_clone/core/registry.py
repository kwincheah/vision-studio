"""
Tool Registry and Factory for Vision Master Clone.
Allows dynamic discovery, instancing, and registration of tools.
"""
from typing import Dict, Type, List
from vm_clone.core.base_tool import VisionToolBase

_TOOL_REGISTRY: Dict[str, Type[VisionToolBase]] = {}
_CATEGORIES: Dict[str, List[str]] = {}


def register_tool(cls: Type[VisionToolBase]):
    _TOOL_REGISTRY[cls.tool_name] = cls
    cat = getattr(cls, 'category', 'General')
    if cat not in _CATEGORIES:
        _CATEGORIES[cat] = []
    if cls.tool_name not in _CATEGORIES[cat]:
        _CATEGORIES[cat].append(cls.tool_name)
    return cls


def get_tool_class(tool_name: str) -> Type[VisionToolBase]:
    if tool_name not in _TOOL_REGISTRY:
        raise KeyError(f"Tool '{tool_name}' not registered in Vision Master registry.")
    return _TOOL_REGISTRY[tool_name]


def create_tool_instance(
    tool_name: str,
    instance_id: str,
    name: str = None,
    allow_placeholder: bool = False
) -> VisionToolBase:
    if tool_name not in _TOOL_REGISTRY:
        if allow_placeholder:
            from vm_clone.core.base_tool import MissingPluginPlaceholderTool
            return MissingPluginPlaceholderTool(instance_id=instance_id, name=name, missing_tool_name=tool_name)
        raise KeyError(f"Tool '{tool_name}' not registered in Vision Master registry.")
    cls = _TOOL_REGISTRY[tool_name]
    return cls(instance_id=instance_id, name=name)


def unregister_tool(tool_name: str) -> bool:
    """Deregister a tool by name from registry and category list."""
    if tool_name not in _TOOL_REGISTRY:
        return False
    cls = _TOOL_REGISTRY.pop(tool_name)
    cat = getattr(cls, 'category', 'General')
    if cat in _CATEGORIES and tool_name in _CATEGORIES[cat]:
        _CATEGORIES[cat].remove(tool_name)
        if not _CATEGORIES[cat]:
            del _CATEGORIES[cat]
    return True


def list_categories() -> Dict[str, List[str]]:
    return _CATEGORIES


def list_all_tools() -> List[str]:
    return list(_TOOL_REGISTRY.keys())
