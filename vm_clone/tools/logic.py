"""
Logic and Control Tools: Condition Branch, Variable Calculation, Script.
Matches HikRobot Vision Master Logic Tools category.
"""
from typing import Dict, Any, List
from vm_clone.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, ToolPort, DataType
from vm_clone.core.registry import register_tool


@register_tool
class ConditionBranchTool(VisionToolBase):
    category = "Logic Tools"
    tool_name = "Condition Branch"
    description = "Evaluates comparison conditions (>, <, ==, !=) to trigger pass/fail or branch output."

    def _init_ports(self):
        self.inputs["Val_In"] = ToolPort("Val_In", DataType.VALUE, "Input value")
        self.outputs["Branch_Result"] = ToolPort("Branch_Result", DataType.BOOLEAN, "Evaluation boolean result")
        self.outputs["Status"] = ToolPort("Status", DataType.STRING, "OK or NG judgment")

    def _init_parameters(self):
        self.parameters = {
            "operator": ">=",  # ==, !=, >, >=, <, <=, Between
            "threshold_low": 50.0,
            "threshold_high": 150.0
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        val = context.get("Val_In")
        if val is None:
            val = 80.0
        else:
            try:
                val = float(val)
            except (ValueError, TypeError):
                val = 80.0

        op = self.get_param("operator", ">=")
        low = float(self.get_param("threshold_low", 50.0))
        high = float(self.get_param("threshold_high", 150.0))

        if op == "==":
            passed = abs(val - low) < 1e-4
        elif op == "!=":
            passed = abs(val - low) >= 1e-4
        elif op == ">":
            passed = val > low
        elif op == ">=":
            passed = val >= low
        elif op == "<":
            passed = val < low
        elif op == "<=":
            passed = val <= low
        elif op == "Between":
            passed = (low <= val <= high)
        else:
            passed = True

        status = ToolStatus.OK if passed else ToolStatus.NG
        msg = f"Val={val:.2f} {op} [{low}, {high}] -> {'PASS' if passed else 'FAIL'}"

        return ToolExecutionResult(
            status=status,
            message=msg,
            outputs={
                "Branch_Result": passed,
                "Status": "OK" if passed else "NG"
            },
            overlays=[
                {"type": "text", "text": f"Branch: {'PASS' if passed else 'FAIL'} ({val:.1f})", "pt": (15, 60), "color": (0, 255, 0) if passed else (0, 0, 255)}
            ]
        )


@register_tool
class VariableCalculationTool(VisionToolBase):
    category = "Logic Tools"
    tool_name = "Variable Calculation"
    description = "Performs mathematical arithmetic on input values (+, -, *, /, scale)."

    def _init_ports(self):
        self.inputs["Val_A"] = ToolPort("Val_A", DataType.VALUE, "Operand A")
        self.inputs["Val_B"] = ToolPort("Val_B", DataType.VALUE, "Operand B")
        self.outputs["Result"] = ToolPort("Result", DataType.VALUE, "Calculation result")

    def _init_parameters(self):
        self.parameters = {
            "operation": "+",  # +, -, *, /, Scale
            "scale_factor": 1.0,
            "default_a": 10.0,
            "default_b": 5.0
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        raw_a = context.get("Val_A", self.get_param("default_a", 10.0))
        raw_b = context.get("Val_B", self.get_param("default_b", 5.0))
        try:
            a = float(raw_a) if raw_a is not None else float(self.get_param("default_a", 10.0))
        except (ValueError, TypeError):
            a = float(self.get_param("default_a", 10.0))
        try:
            b = float(raw_b) if raw_b is not None else float(self.get_param("default_b", 5.0))
        except (ValueError, TypeError):
            b = float(self.get_param("default_b", 5.0))

        op = self.get_param("operation", "+")

        if op == "+":
            res = a + b
        elif op == "-":
            res = a - b
        elif op == "*":
            res = a * b
        elif op == "/":
            res = a / b if b != 0 else 0.0
        else:
            res = a * float(self.get_param("scale_factor", 1.0))

        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=f"Calc: {a} {op} {b} = {res:.4f}",
            outputs={"Result": res}
        )


@register_tool
class BranchTool(VisionToolBase):
    """
    Branch Module (Manual p. 551-552).
    Evaluates condition input by value or bitmask to dynamically select and execute branches.
    """
    category = "Logic Tools"
    tool_name = "Branch"
    description = "Branches execution using Index by Value or Index by Bit."

    def _init_ports(self):
        self.inputs["Condition_In"] = ToolPort("Condition_In", DataType.VALUE, "Branch selector value")
        self.outputs["Branch_Index"] = ToolPort("Branch_Index", DataType.VALUE, "Active branch index")
        self.outputs["Status"] = ToolPort("Status", DataType.STRING, "OK or NG judgment")

    def _init_parameters(self):
        self.parameters = {
            "mode": "Index by Value",  # "Index by Value" or "Index by Bit" (Manual p. 551-552)
            "target_value": 1,
            "bit_index": 0,
            "target_branches": ""  # comma-separated downstream module IDs governed by this branch
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        raw_cond = context.get("Condition_In")
        try:
            cond_val = int(raw_cond) if raw_cond is not None else int(self.get_param("target_value", 1))
        except (ValueError, TypeError):
            cond_val = int(self.get_param("target_value", 1))
        mode = self.get_param("mode", "Index by Value")

        if mode == "Index by Bit":
            bit = int(self.get_param("bit_index", 0))
            is_active = bool((cond_val >> bit) & 1)
        else:
            target = int(self.get_param("target_value", 1))
            is_active = (cond_val == target)

        raw_targets = str(self.get_param("target_branches", "")).strip()
        target_list = [t.strip() for t in raw_targets.split(",") if t.strip()]

        inactive_branches = []
        if not is_active and target_list:
            inactive_branches = target_list

        status = ToolStatus.OK if is_active else ToolStatus.NG
        msg = f"Branch ({mode}): Cond={cond_val} -> {'ACTIVE' if is_active else 'INACTIVE'}"

        return ToolExecutionResult(
            status=status,
            message=msg,
            outputs={
                "Branch_Index": cond_val if is_active else -1,
                "Status": "OK" if is_active else "NG",
                "Inactive_Branches": inactive_branches
            }
        )


@register_tool
class IfModuleTool(VisionToolBase):
    """
    If Module (Manual p. 549-550).
    Determines whether input values meet All/Any range condition.
    """
    category = "Logic Tools"
    tool_name = "If Module"
    description = "Condition detection with All/Any judge method against valid numeric range."

    def _init_ports(self):
        self.inputs["Val_In"] = ToolPort("Val_In", DataType.VALUE, "Input value")
        self.outputs["Result"] = ToolPort("Result", DataType.BOOLEAN, "Judge result boolean")
        self.outputs["Status"] = ToolPort("Status", DataType.STRING, "OK or NG judgment")

    def _init_parameters(self):
        self.parameters = {
            "judge_method": "All",  # "All" or "Any" (Manual p. 550)
            "min_val": 0.0,
            "max_val": 100.0,
            "condition_type": "Float"
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        val = context.get("Val_In", 50.0)
        try:
            fval = float(val)
        except (ValueError, TypeError):
            fval = 0.0

        min_v = float(self.get_param("min_val", 0.0))
        max_v = float(self.get_param("max_val", 100.0))
        passed = (min_v <= fval <= max_v)

        status = ToolStatus.OK if passed else ToolStatus.NG
        return ToolExecutionResult(
            status=status,
            message=f"If: {min_v:.2f} <= {fval:.2f} <= {max_v:.2f} -> {'PASS' if passed else 'FAIL'}",
            outputs={
                "Result": passed,
                "Status": "OK" if passed else "NG"
            }
        )


@register_tool
class BranchStringTool(VisionToolBase):
    """
    Branch String Module (Manual p. 553).
    Matches input text against pattern for string-based conditional branching.
    """
    category = "Logic Tools"
    tool_name = "Branch String"
    description = "Text pattern matching for string branch selection."

    def _init_ports(self):
        self.inputs["Input_Text"] = ToolPort("Input_Text", DataType.STRING, "Input text string")
        self.outputs["Branch_Result"] = ToolPort("Branch_Result", DataType.BOOLEAN, "Match result")
        self.outputs["Status"] = ToolPort("Status", DataType.STRING, "OK or NG judgment")

    def _init_parameters(self):
        self.parameters = {
            "target_text": "PASS",
            "match_mode": "Exact",  # "Exact", "Contains", "Prefix"
            "debug_mode": False  # (Manual p. 553: "If it is enabled, execution will be performed always")
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        debug = bool(self.get_param("debug_mode", False))
        if debug:
            return ToolExecutionResult(
                status=ToolStatus.OK,
                message="Debug Mode: Execution forced PASS",
                outputs={"Branch_Result": True, "Status": "OK"}
            )

        inp = str(context.get("Input_Text", "")).strip()
        target = str(self.get_param("target_text", "PASS")).strip()
        mode = self.get_param("match_mode", "Exact")

        if mode == "Contains":
            matched = target in inp
        elif mode == "Prefix":
            matched = inp.startswith(target)
        else:
            matched = (inp == target)

        status = ToolStatus.OK if matched else ToolStatus.NG
        return ToolExecutionResult(
            status=status,
            message=f"BranchString: '{inp}' {mode} '{target}' -> {'MATCH' if matched else 'MISMATCH'}",
            outputs={
                "Branch_Result": matched,
                "Status": "OK" if matched else "NG"
            }
        )


@register_tool
class TriggerTool(VisionToolBase):
    """
    Trigger Module (Manual p. 588).
    Triggers execution of another sub-flow in the multi-flow solution via Procedure ID/Name.
    """
    category = "Logic Tools"
    tool_name = "Trigger"
    description = "Triggers execution of another flow in the solution."

    def _init_ports(self):
        self.inputs["Trigger_Signal"] = ToolPort("Trigger_Signal", DataType.BOOLEAN, "Execution trigger signal")
        self.outputs["Status"] = ToolPort("Status", DataType.STRING, "OK or NG judgment")

    def _init_parameters(self):
        self.parameters = {
            "target_flow": "Flow2",
            "require_signal_true": True
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        sig = context.get("Trigger_Signal", True)
        require_true = bool(self.get_param("require_signal_true", True))
        target_flow = str(self.get_param("target_flow", "Flow2"))

        if require_true and not sig:
            return ToolExecutionResult(
                status=ToolStatus.OK,
                message=f"Trigger skipped: signal is False",
                outputs={"Status": "SKIPPED"}
            )

        # Trigger through global context if available
        g_ctx = context.get("global", {})
        sol = g_ctx.get("solution")
        if sol and hasattr(sol, "trigger_flow"):
            sol.trigger_flow(target_flow)
            msg = f"Triggered sub-flow '{target_flow}'"
        else:
            msg = f"Trigger signal active for sub-flow '{target_flow}'"

        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=msg,
            outputs={"Status": "OK"}
        )
