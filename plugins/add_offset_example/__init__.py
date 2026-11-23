"""Add Offset - the smallest useful plugin.

One module: a number arrives on the input port, the ``offset`` parameter is added to it, and
the sum leaves on the output port.  It shows the four things every plugin module needs:
a port, a parameter, the code that runs, and the result it returns.

Drop this folder in ``plugins/`` and restart, or use Settings > Plugins > Reload.  The module
then appears in the toolbox under "Calculation".
"""
from typing import Any, Dict, List, Type

from apex_vision.sdk import (
    DataType,
    IVisionPlugin,
    ParamDef,
    ParamType,
    PluginMetadata,
    PluginToolBase,
    ToolExecutionResult,
    ToolPort,
    ToolStatus,
)


class AddOffsetTool(PluginToolBase):
    """Output = input + offset."""

    plugin_id = "add_offset_example"          # must match plugin.json
    category = "Calculation"                  # the toolbox group it lands in
    tool_name = "Add Offset"                  # the name on the module card
    description = "Adds the offset parameter to the incoming number."

    # The config dialog builds its editors from this.  ParamType.INT gives a whole-number
    # field clamped to min/max, so the user cannot type something invalid.
    param_definitions = {
        "offset": ParamDef(
            name="offset",
            param_type=ParamType.INT,
            default_value=10,
            description="Value added to the input",
            min_value=-100000,
            max_value=100000,
            step=1,
        )
    }

    def _init_ports(self):
        """The wires this module accepts and offers."""
        self.inputs["Value"] = ToolPort("Value", DataType.VALUE, "Number to add to")
        self.outputs["Sum"] = ToolPort("Sum", DataType.VALUE, "Input + offset")

    def _init_parameters(self):
        """Starting values; must carry the same names as param_definitions."""
        self.parameters = {"offset": 10}

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        # Inputs arrive under their port name.  A port that was not wired is simply absent,
        # so treat it as zero rather than failing.
        raw = context.get("Value", 0)
        try:
            value = int(round(float(raw)))
        except (TypeError, ValueError):
            return ToolExecutionResult(
                status=ToolStatus.NG,
                message=f"Input is not a number: {raw!r}",
            )

        offset = int(self.get_param("offset", 10))
        total = value + offset

        return ToolExecutionResult(
            status=ToolStatus.OK,
            outputs={"Sum": total},
            message=f"{value} + {offset} = {total}",
        )


class AddOffsetPlugin(IVisionPlugin):
    """What the app discovers: metadata, and the list of modules to register."""

    @classmethod
    def get_metadata(cls) -> PluginMetadata:
        return PluginMetadata(
            plugin_id="add_offset_example",
            name="Add Offset (example)",
            version="1.0.0",
            author="Example",
            description="Smallest useful plugin: number in, offset added, sum out.",
            category="Calculation",
            min_sdk_version="1.0.0",
            tags=["example", "tutorial", "arithmetic"],
        )

    @classmethod
    def register_tools(cls) -> List[Type[PluginToolBase]]:
        return [AddOffsetTool]

    @classmethod
    def on_load(cls) -> bool:
        return True

    @classmethod
    def on_unload(cls):
        pass
