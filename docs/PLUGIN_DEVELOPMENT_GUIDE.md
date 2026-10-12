# Apex Industrial Vision Studio - Plugin Developer Guide

The **Apex Vision Studio Plugin SDK** enables third-party machine vision engineers, researchers, and automated inspection teams to develop, package, distribute, and execute custom vision tools without modifying the core studio application.

---

## 1. SDK Architecture Overview

Every plugin is an isolated Python package that integrates into the studio lifecycle:
- **Discovered Dynamically:** Scanned automatically from `./plugins/` (local workspace) or `~/.apex_vision/plugins/` (user machine).
- **Strongly Typed Contracts:** Tools declare typed inputs (`Image`, `ROI`, `Number`, `String`), outputs, and configurable parameters.
- **Fail-Safe Containment:** Untrusted third-party code executes with exception isolation and timeout protection so buggy plugins never crash the main production inspection engine.
- **Visual Integration:** Automatically renders in the Tool Box category rail, the Flow Diagram canvas, and the Property Inspector.

---

## 2. Anatomy of a Plugin

A standard plugin directory structure:
```text
my_custom_filter_plugin/
├── plugin.json              # Plugin manifest & metadata
├── __init__.py              # Entrypoint module
└── filter_tool.py           # Vision tool implementation
```

### 2.1 Manifest: `plugin.json`
```json
{
  "plugin_id": "com.company.gaussian_filter",
  "name": "Adaptive Gaussian Filter",
  "version": "1.0.0",
  "min_sdk_version": "1.0.0",
  "author": "Vision Labs",
  "category": "Image Processing",
  "description": "High-speed adaptive Gaussian noise reduction with configurable kernel sizes.",
  "entrypoint": "__init__.py",
  "tools": [
    "AdaptiveGaussianFilterTool"
  ]
}
```

---

## 3. Creating a Vision Tool (Code Example)

Here is a complete, functioning custom vision tool:

```python
import cv2
import numpy as np
from typing import Dict, Any

from vm_clone.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus
from vm_clone.sdk import (
    IVisionPlugin,
    PluginMetadata,
    ParamDef,
    ParamType,
    CURRENT_SDK_VERSION,
)

class AdaptiveGaussianFilterTool(VisionToolBase):
    """Applies adaptive Gaussian smoothing to incoming inspection images."""
    tool_name = "Adaptive Gaussian Filter"
    category = "Image Processing"
    description = "Blurs image using Gaussian filter to remove high-frequency noise."

    def __init__(self, name: str = "GaussianFilter"):
        super().__init__(name)
        # 1. Declare Configurable Parameters
        self.params = {
            "kernel_size": 5,      # Must be an odd integer >= 3
            "sigma": 1.5,
        }

    @classmethod
    def get_parameter_definitions(cls) -> Dict[str, ParamDef]:
        """Provides schema for UI Property Inspector auto-generation."""
        return {
            "kernel_size": ParamDef(
                name="kernel_size",
                param_type=ParamType.INT,
                default_value=5,
                min_value=3,
                max_value=31,
                description="Odd kernel aperture size in pixels"
            ),
            "sigma": ParamDef(
                name="sigma",
                param_type=ParamType.FLOAT,
                default_value=1.5,
                min_value=0.1,
                max_value=10.0,
                description="Gaussian kernel standard deviation"
            ),
        }

    def execute(self, inputs: Dict[str, Any]) -> ToolExecutionResult:
        """Core execution method called by the workflow engine."""
        image = inputs.get("image")
        if image is None:
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                error_message="Missing required input: 'image'"
            )

        ksize = int(self.params.get("kernel_size", 5))
        if ksize % 2 == 0:
            ksize += 1  # Kernel must be odd
        sigma = float(self.params.get("sigma", 1.5))

        # Perform OpenCV image processing
        blurred = cv2.GaussianBlur(image, (ksize, ksize), sigmaX=sigma)

        return ToolExecutionResult(
            status=ToolStatus.SUCCESS,
            outputs={
                "image": blurred,
                "applied_kernel": ksize,
            },
            message=f"Gaussian blur applied ({ksize}x{ksize})"
        )


class GaussianPlugin(IVisionPlugin):
    """Plugin Lifecycle Entrypoint."""
    
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            plugin_id="com.company.gaussian_filter",
            name="Adaptive Gaussian Filter",
            version="1.0.0",
            min_sdk_version=CURRENT_SDK_VERSION,
            author="Vision Labs",
            category="Image Processing",
            description="Adaptive Gaussian noise filter",
        )

    def register_tools(self) -> list:
        return [AdaptiveGaussianFilterTool]

    def on_load(self, context) -> bool:
        context.logger.info("Adaptive Gaussian Filter plugin initialized.")
        return True

    def on_unload(self, context):
        context.logger.info("Adaptive Gaussian Filter plugin cleaned up.")
```

---

## 4. Testing Your Plugin Locally

You can test your tool with standard `pytest` without launching the entire GUI:

```python
import numpy as np
from my_custom_filter_plugin import AdaptiveGaussianFilterTool

def test_gaussian_tool():
    tool = AdaptiveGaussianFilterTool()
    tool.params["kernel_size"] = 5
    dummy_img = np.zeros((100, 100), dtype=np.uint8)
    
    result = tool.execute({"image": dummy_img})
    assert result.status.name == "SUCCESS"
    assert "image" in result.outputs
    assert result.outputs["image"].shape == (100, 100)
```

---

## 5. Publishing to the In-App Marketplace & GitHub

1. **GitHub Repository:** Host your plugin code on a public GitHub repo (e.g. `https://github.com/myorg/apex-plugin-gaussian`).
2. **Install from GitHub:** Operators can open **Tools -> Plugin Manager -> GitHub Installer**, enter your repository URL, and click **Install from GitHub**.
3. **Distribution Archive (`.vmpkg`):** Use the built-in **Plugin Creator / Packager** to generate a single validated zip bundle ready for offline factory environments.
