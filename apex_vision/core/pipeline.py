"""
Execution Engine & Multi-Flow Solution Manager for Apex Vision Studio.
Manages Multi-Flows, Connections, Execution Order, Global Variables, and Flow Run / Continuous Run.
Matches the reference product Multi-Flow (Manual p. 93-97) and Global Variables (Manual p. 108-112).
"""
import os
import math
import json
import time
import copy
from typing import Dict, List, Any, Optional, Callable, Set

# Root elements of the saved XML. Files written before the rename use the legacy names and are still read.
FLOW_TAG = "ApexFlow"
SOLUTION_TAG = "ApexSolution"
LEGACY_FLOW_TAG = "VisionMasterFlow"
LEGACY_SOLUTION_TAG = "VisionMasterSolution"
FLOW_TAGS = (FLOW_TAG, LEGACY_FLOW_TAG)
from apex_vision.core.base_tool import (
    VisionToolBase, ToolExecutionResult, ToolStatus, is_compatible_type
)


class FlowConnection:
    def __init__(self, from_node: str, from_port: str, to_node: str, to_port: str):
        self.from_node = from_node
        self.from_port = from_port
        self.to_node = to_node
        self.to_port = to_port

    def to_dict(self):
        return {
            "from_node": self.from_node,
            "from_port": self.from_port,
            "to_node": self.to_node,
            "to_port": self.to_port
        }

    @classmethod
    def from_dict(cls, d: dict):
        return cls(d["from_node"], d["from_port"], d["to_node"], d["to_port"])

    def __eq__(self, other):
        if not isinstance(other, FlowConnection):
            return False
        return (
            self.from_node == other.from_node and
            self.from_port == other.from_port and
            self.to_node == other.to_node and
            self.to_port == other.to_port
        )

    def __hash__(self):
        return hash((self.from_node, self.from_port, self.to_node, self.to_port))



#: characters that XML 1.0 forbids or that a parser rewrites (carriage return)
_XML_UNSAFE_TEXT = __import__("re").compile("[\x00-\x08\x0b-\x1f\ufffe\uffff\ud800-\udfff]|\r")


class VisionPipeline:
    """
    Represents a single execution flow graph in Apex Vision.
    Matches the reference product Flow Control & Multi-Flow (Manual p. 93-97).
    """
    def __init__(self, name: str = "Flow1"):
        self.name: str = name
        self.nodes: Dict[str, VisionToolBase] = {}  # instance_id -> Tool
        self.connections: List[FlowConnection] = []
        self.execution_order: List[str] = []
        self.last_results: Dict[str, ToolExecutionResult] = {}
        self.last_flow_time_ms: float = 0.0
        self.is_running: bool = False
        self.enabled: bool = True  # Flow control switch (Manual p. 97)
        self.run_interval_ms: float = 50.0  # Run Interval (Manual p. 93)
        self.stop_on_ng: bool = False  # Stop Flow Executed NG (Manual p. 93)
        self.flow_timeout_ms: float = 5000.0  # Flow Timeout (Manual p. 93)
        self.execution_count: int = 0  # Executed count telemetry (Manual p. 95)
        # Canvas placement (instance_id -> [x, y]); purely presentational but persisted so
        # a saved diagram reopens exactly as the operator arranged it.
        self.node_positions: Dict[str, List[float]] = {}

    def add_node(self, tool: VisionToolBase):
        self.nodes[tool.instance_id] = tool
        self._update_execution_order()

    def remove_node(self, instance_id: str):
        if instance_id in self.nodes:
            del self.nodes[instance_id]
            for other in self.nodes.values():
                if getattr(other, "group", "") == instance_id:        # the Group is gone: its modules are on their own again
                    other.group = ""
            self.connections = [
                c for c in self.connections
                if c.from_node != instance_id and c.to_node != instance_id
            ]
            self.node_positions.pop(instance_id, None)
            self._update_execution_order()

    def _has_path(self, start_node: str, target_node: str) -> bool:
        """DFS check to determine if target_node is reachable from start_node."""
        if start_node == target_node:
            return True
        visited = set()
        stack = [start_node]
        while stack:
            curr = stack.pop()
            if curr == target_node:
                return True
            if curr in visited:
                continue
            visited.add(curr)
            for c in self.connections:
                if c.from_node == curr and c.to_node not in visited and not self._internal_to_group(c):
                    stack.append(c.to_node)
        return False

    def _internal_to_group(self, c) -> bool:
        """True for a wire between a Group and one of its own modules: it is part of the loop, not a dependency, so it never makes a cycle."""
        return self.group_of(c.to_node) == c.from_node or self.group_of(c.from_node) == c.to_node

    def can_connect(self, from_node: str, from_port: str, to_node: str, to_port: str) -> tuple[bool, str]:
        """
        Validates connection feasibility: port existence, self-loop, type safety, and cycle prevention.
        Matches Hikrobot DAG connection rules.
        """
        if from_node == to_node:
            return False, "Cannot connect a module to itself."

        if from_node not in self.nodes:
            return False, f"Source module '{from_node}' does not exist."
        if to_node not in self.nodes:
            return False, f"Destination module '{to_node}' does not exist."

        src_tool = self.nodes[from_node]
        dst_tool = self.nodes[to_node]

        if from_port not in src_tool.outputs:
            return False, f"Output port '{from_port}' does not exist on '{src_tool.name}'."
        if to_port not in dst_tool.inputs:
            return False, f"Input port '{to_port}' does not exist on '{dst_tool.name}'."

        src_type = src_tool.outputs[from_port].data_type
        dst_type = dst_tool.inputs[to_port].data_type
        if not is_compatible_type(src_type, dst_type):
            return False, f"Type mismatch: cannot connect {src_type.value} to {dst_type.value}."

        # Circular dependency check: adding from_node -> to_node would create a cycle if a path to_node -> from_node exists
        if self._has_path(to_node, from_node):
            return False, f"Circular connection rejected: creates a loop between '{src_tool.name}' and '{dst_tool.name}'."

        return True, "Valid connection."

    def connect(self, from_node: str, from_port: str, to_node: str, to_port: str, force: bool = False) -> bool:
        """Connects two ports. Validates feasibility unless force=True."""
        if not force:
            can, msg = self.can_connect(from_node, from_port, to_node, to_port)
            if not can:
                return False

        # Remove any existing connection to the target input port (each input has single source)
        self.connections = [
            c for c in self.connections
            if not (c.to_node == to_node and c.to_port == to_port)
        ]
        self.connections.append(FlowConnection(from_node, from_port, to_node, to_port))
        self._update_execution_order()
        return True

    def disconnect(self, to_node: str, to_port: str):
        self.connections = [
            c for c in self.connections
            if not (c.to_node == to_node and c.to_port == to_port)
        ]
        self._update_execution_order()

    def group_of(self, node_id: str) -> str:
        """The id of the Group module a module belongs to, or '' (a Group is never a member of another)."""
        node = self.nodes.get(node_id)
        gid = getattr(node, "group", "") if node is not None else ""
        if gid and gid != node_id and gid in self.nodes and self.nodes[gid].tool_name == "Group" and node.tool_name != "Group":
            return gid
        return ""

    def set_group(self, node_id: str, group_id: str = "") -> bool:
        """Put a module inside a Group module (or take it out with an empty id). False when that is not allowed."""
        node = self.nodes.get(node_id)
        if node is None:
            return False
        if group_id:
            g = self.nodes.get(group_id)
            if g is None or g.tool_name != "Group" or node.tool_name == "Group" or group_id == node_id:
                return False
        node.group = group_id or ""
        self._update_execution_order()
        return True

    def group_members(self, group_id: str) -> List[str]:
        """The modules inside a Group, in running order."""
        return [n for n in self.execution_order if self.group_of(n) == group_id]

    @staticmethod
    def _kahn(ids: List[str], edges: List[tuple]) -> List[str]:
        adj: Dict[str, List[str]] = {n: [] for n in ids}
        indeg: Dict[str, int] = {n: 0 for n in ids}
        for a, b in edges:
            if a in adj and b in indeg and a != b:
                adj[a].append(b)
                indeg[b] += 1
        queue = [n for n in ids if indeg[n] == 0]
        order: List[str] = []
        while queue:
            cur = queue.pop(0)
            order.append(cur)
            for nxt in adj.get(cur, []):
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    queue.append(nxt)
        order += [n for n in ids if n not in order]
        return order

    def _update_execution_order(self):
        """Topological sort for node execution order, fallback to insertion order.

        A Group and the modules inside it are sorted as one unit (so everything the group's modules need has run before it, and everything
        that needs their results runs after it); inside the unit the modules are sorted among themselves and follow the Group module."""
        rep = {n: (self.group_of(n) or n) for n in self.nodes}
        units = [n for n in self.nodes if rep[n] == n]
        unit_order = self._kahn(units, [(rep.get(c.from_node, c.from_node), rep.get(c.to_node, c.to_node)) for c in self.connections])
        order: List[str] = []
        for u in unit_order:
            order.append(u)
            inside = [n for n in self.nodes if rep[n] == u and n != u]
            if inside:
                order += self._kahn(inside, [(c.from_node, c.to_node) for c in self.connections if rep.get(c.from_node) == u and rep.get(c.to_node) == u])
        self.execution_order = order

    def validate_flow(self) -> List[Dict[str, Any]]:
        """
        Comprehensive Flow Validation.
        Detects cycles, missing inputs, and isolated modules.
        """
        issues = []
        # 1. Cycle detection in overall graph (iterative 3-color DFS to avoid RecursionError)
        adj: Dict[str, List[str]] = {n: [] for n in self.nodes}
        for c in self.connections:
            if c.from_node in adj and not self._internal_to_group(c):
                adj[c.from_node].append(c.to_node)

        # 0 = unvisited, 1 = visiting (in stack), 2 = visited
        state: Dict[str, int] = {n: 0 for n in self.nodes}
        has_cycle = False

        for start_node in self.nodes:
            if state[start_node] != 0:
                continue
            stack = [(start_node, 0)]
            state[start_node] = 1
            while stack:
                curr, nbr_idx = stack[-1]
                nbrs = adj.get(curr, [])
                if nbr_idx < len(nbrs):
                    stack[-1] = (curr, nbr_idx + 1)
                    nbr = nbrs[nbr_idx]
                    nbr_state = state.get(nbr, 0)
                    if nbr_state == 1:
                        has_cycle = True
                        break
                    elif nbr_state == 0:
                        state[nbr] = 1
                        stack.append((nbr, 0))
                else:
                    state[curr] = 2
                    stack.pop()
            if has_cycle:
                break

        if has_cycle:
            issues.append({
                "severity": "error",
                "message": "Flow contains circular dependencies (cyclic loop detected)."
            })

        # 2. Check each node for unconnected input ports and bypass status
        for nid, tool in self.nodes.items():
            if not tool.enabled:
                issues.append({
                    "severity": "info",
                    "node_id": nid,
                    "message": f"Module '{tool.name}' is currently bypassed (disabled)."
                })

            connected_inputs = {c.to_port for c in self.connections if c.to_node == nid}
            for port_name, port in tool.inputs.items():
                if port_name not in connected_inputs:
                    issues.append({
                        "severity": "warning",
                        "node_id": nid,
                        "port": port_name,
                        "message": f"Module '{tool.name}' input '{port_name}' has no incoming connection."
                    })

        return issues

    def duplicate(self, new_name: Optional[str] = None) -> "VisionPipeline":
        """
        Creates an exact duplicate of this flow with all tools and connections.
        Matches the reference product 'Copy Flow' (Manual p. 93).
        """
        from apex_vision.core.registry import create_tool_instance
        copy_name = new_name or f"{self.name}_Copy"
        new_pipe = VisionPipeline(name=copy_name)
        new_pipe.enabled = self.enabled
        new_pipe.run_interval_ms = self.run_interval_ms
        new_pipe.stop_on_ng = self.stop_on_ng
        new_pipe.flow_timeout_ms = self.flow_timeout_ms

        id_map = {}
        from apex_vision.core.registry import new_instance_id
        for nid, tool in self.nodes.items():
            new_id = new_instance_id(f"{nid}_copy")
            id_map[nid] = new_id
            cloned_tool = create_tool_instance(tool.tool_name, new_id, f"{tool.name}_Copy")
            cloned_tool.load_dict(tool.to_dict())
            new_pipe.add_node(cloned_tool)
            if nid in self.node_positions:
                new_pipe.node_positions[new_id] = list(self.node_positions[nid])

        for conn in self.connections:
            if conn.from_node in id_map and conn.to_node in id_map:
                new_pipe.connect(
                    id_map[conn.from_node],
                    conn.from_port,
                    id_map[conn.to_node],
                    conn.to_port,
                    force=True
                )

        return new_pipe

    @staticmethod
    def _encode_xml_value(val: Any) -> tuple[str, str]:
        """Encode a parameter value into (type_str, encoded_str)."""
        if val is None:
            return "null", ""
        if isinstance(val, bool):
            return "bool", "true" if val else "false"
        elif isinstance(val, int):
            return "int", str(val)
        elif isinstance(val, float):
            return "float", str(val)
        elif isinstance(val, str):
            # XML 1.0 cannot carry most control characters and parsers normalise CR;
            # such strings travel as a JSON string literal so they round-trip exactly.
            if _XML_UNSAFE_TEXT.search(val):
                return "jsonstr", json.dumps(val, ensure_ascii=True)
            return "str", val
        elif isinstance(val, (list, tuple, dict)):
            return "json", json.dumps(val, ensure_ascii=False)
        else:
            return "str", str(val)

    @staticmethod
    def _decode_xml_value(type_str: Optional[str], text: Optional[str]) -> Any:
        """Decode a parameter value from (type_str, text)."""
        text = text if text is not None else ""
        t = (type_str or "").lower().strip()
        if t == "null":
            return None
        if t == "jsonstr":
            try:
                val = json.loads(text)
            except Exception as e:
                raise ValueError(f"Malformed XML string payload: {text!r}") from e
            if not isinstance(val, str):
                raise ValueError(f"Malformed XML string payload: {text!r}")
            return val
        if t == "bool":
            return text.strip().lower() in ("true", "1", "yes")
        elif t == "int":
            try:
                return int(text.strip())
            except ValueError as e:
                raise ValueError(f"Malformed XML integer value: {text!r}") from e
        elif t == "float":
            try:
                return float(text.strip())
            except ValueError as e:
                raise ValueError(f"Malformed XML float value: {text!r}") from e
        elif t in ("json", "list", "dict"):
            try:
                return json.loads(text)
            except Exception as e:
                raise ValueError(f"Malformed XML {t} JSON payload: {text!r}") from e
        elif t == "str":
            return text
        else:
            s = text.strip()
            if s.lower() == "true":
                return True
            if s.lower() == "false":
                return False
            try:
                return int(s)
            except ValueError:
                pass
            try:
                return float(s)
            except ValueError:
                pass
            if (s.startswith("[") and s.endswith("]")) or (s.startswith("{") and s.endswith("}")):
                try:
                    return json.loads(s)
                except Exception:
                    pass
            return text

    def to_xml(self) -> str:
        """Serialize flow pipeline into standard XML format (Manual p. 93 / §7.4)."""
        import xml.etree.ElementTree as ET

        root = ET.Element(FLOW_TAG, attrib={
            "version": "4.3",
            "name": self.name
        })

        props_el = ET.SubElement(root, "Properties")
        for prop_name, prop_val, ptype in (
            ("enabled", self.enabled, "bool"),
            ("run_interval_ms", self.run_interval_ms, "float"),
            ("stop_on_ng", self.stop_on_ng, "bool"),
            ("flow_timeout_ms", self.flow_timeout_ms, "float"),
            ("execution_count", self.execution_count, "int"),
        ):
            pel = ET.SubElement(props_el, "Property", attrib={"name": prop_name, "type": ptype})
            pel.text = "true" if prop_val is True else "false" if prop_val is False else str(prop_val)

        nodes_el = ET.SubElement(root, "Nodes")
        for node in self.nodes.values():
            node_el = ET.SubElement(nodes_el, "Node", attrib={
                "instance_id": str(node.instance_id),
                # a placeholder for a plugin module that is not installed keeps the real module's name and category,
                # so opening and re-saving such a project does not destroy it
                "tool_name": str(getattr(node, "missing_tool_name", None) or node.tool_name),
                "name": str(node.name),
                "category": str(getattr(node, "_saved_category", None) or getattr(node, "category", "")),
                "enabled": "true" if node.enabled else "false",
                **({"group": str(node.group)} if getattr(node, "group", "") else {}),
            })
            params_el = ET.SubElement(node_el, "Parameters")
            for p_key, p_val in node.parameters.items():
                p_type, p_encoded = self._encode_xml_value(p_val)
                param_el = ET.SubElement(params_el, "Parameter", attrib={"name": p_key, "type": p_type})
                param_el.text = p_encoded

            # The module's Display Setup, written only when it differs from the default, so
            # a project the user never touched keeps exactly the file it had.
            display = getattr(node, "display", None) or {}
            default = getattr(node, "DEFAULT_DISPLAY", None) or {}
            if default and display != default:
                ET.SubElement(node_el, "Display", attrib={
                    "roi": "true" if display.get("roi", True) else "false",
                    "labels": "true" if display.get("labels", True) else "false",
                    "boxes": "true" if display.get("boxes", True) else "false",
                    "colour": str(display.get("colour") or ""),
                })

        conns_el = ET.SubElement(root, "Connections")
        for conn in self.connections:
            ET.SubElement(conns_el, "Connection", attrib={
                "from_node": str(conn.from_node),
                "from_port": str(conn.from_port),
                "to_node": str(conn.to_node),
                "to_port": str(conn.to_port)
            })

        if self.node_positions:
            layout_el = ET.SubElement(root, "Layout")
            for nid, (x, y) in self.node_positions.items():
                if nid in self.nodes:
                    ET.SubElement(layout_el, "Position", attrib={
                        "node": str(nid), "x": repr(float(x)), "y": repr(float(y))})

        return self._flow_element_to_string(root)

    def to_xml_element(self):
        """The flow as an ElementTree element (used to embed flows in a solution file)."""
        import xml.etree.ElementTree as ET
        return ET.fromstring(self.to_xml().encode("utf-8"))

    @staticmethod
    def _flow_element_to_string(root) -> str:
        import xml.etree.ElementTree as ET
        ET.indent(root, space="  ")
        return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")

    @classmethod
    def from_xml(cls, xml_str: str) -> "VisionPipeline":
        """Deserialize flow pipeline from standard XML string."""
        from apex_vision.core.xml_safe import safe_fromstring
        return cls.from_xml_element(safe_fromstring(xml_str))

    @classmethod
    def from_xml_element(cls, root) -> "VisionPipeline":
        """Build a flow from a parsed ``<ApexFlow>`` (or legacy ``<VisionMasterFlow>``) element."""
        from apex_vision.core.registry import create_tool_instance

        if root.tag not in FLOW_TAGS:
            raise ValueError(f"Expected an <{FLOW_TAG}> element, found <{root.tag}>")
        name = root.attrib.get("name", "ImportedFlow")
        pipe = cls(name=name)

        props_el = root.find("Properties")
        if props_el is not None:
            for p_el in props_el.findall("Property"):
                p_name = p_el.attrib.get("name")
                p_type = p_el.attrib.get("type")
                val = cls._decode_xml_value(p_type, p_el.text)
                if p_name == "enabled":
                    pipe.enabled = bool(val)
                elif p_name == "run_interval_ms":
                    pipe.run_interval_ms = float(val)
                elif p_name == "stop_on_ng":
                    pipe.stop_on_ng = bool(val)
                elif p_name == "flow_timeout_ms":
                    pipe.flow_timeout_ms = float(val)
                elif p_name == "execution_count":
                    pipe.execution_count = int(val)

        nodes_el = root.find("Nodes")
        if nodes_el is not None:
            for n_el in nodes_el.findall("Node"):
                inst_id = n_el.attrib.get("instance_id", "")
                tool_name = n_el.attrib.get("tool_name", "")
                node_name = n_el.attrib.get("name", tool_name)
                enabled_str = n_el.attrib.get("enabled", "true")
                enabled = enabled_str.lower() in ("true", "1", "yes")

                tool = create_tool_instance(tool_name, inst_id, node_name, allow_placeholder=True)
                tool.enabled = enabled
                tool.group = n_el.attrib.get("group", "") or ""

                params_el = n_el.find("Parameters")
                if params_el is not None:
                    param_dict = {}
                    for param_el in params_el.findall("Parameter"):
                        k = param_el.attrib.get("name")
                        if not k:
                            continue
                        ptype = param_el.attrib.get("type")
                        param_dict[k] = cls._decode_xml_value(ptype, param_el.text)
                    tool.load_dict({"parameters": param_dict})
                display_el = n_el.find("Display")
                if display_el is not None:
                    tool.display = tool._coerce_display({
                        "roi": display_el.attrib.get("roi", "true").lower() in ("true", "1", "yes"),
                        "labels": display_el.attrib.get("labels", "true").lower() in ("true", "1", "yes"),
                        "boxes": display_el.attrib.get("boxes", "true").lower() in ("true", "1", "yes"),
                        "colour": display_el.attrib.get("colour", ""),
                    })
                if hasattr(tool, "_saved_category"):                 # a plugin module that is not installed
                    tool._saved_category = n_el.attrib.get("category") or None

                pipe.add_node(tool)

        conns_el = root.find("Connections")
        if conns_el is not None:
            for c_el in conns_el.findall("Connection"):
                fn = c_el.attrib.get("from_node")
                fp = c_el.attrib.get("from_port")
                tn = c_el.attrib.get("to_node")
                tp = c_el.attrib.get("to_port")
                if fn and fp and tn and tp:
                    pipe.connect(fn, fp, tn, tp, force=True)

        layout_el = root.find("Layout")
        if layout_el is not None:
            for pos_el in layout_el.findall("Position"):
                nid = pos_el.attrib.get("node")
                try:
                    x, y = float(pos_el.attrib["x"]), float(pos_el.attrib["y"])
                except (KeyError, ValueError):
                    continue
                if nid in pipe.nodes and math.isfinite(x) and math.isfinite(y):
                    pipe.node_positions[nid] = [x, y]

        return pipe

    def export_to_xml(self, filepath: str):
        """Export flow directly to XML file."""
        from apex_vision.core.fileio import atomic_write_text
        atomic_write_text(filepath, self.to_xml())

    @classmethod
    def import_from_xml(cls, filepath: str) -> "VisionPipeline":
        """Import flow from an XML file."""
        with open(filepath, "r", encoding="utf-8") as f:
            xml_content = f.read()
        return cls.from_xml(xml_content)

    def export_to_file(self, filepath: str):
        """Export flow in .xml / .prc / .json format (Manual p. 93)."""
        if filepath.lower().endswith((".xml", ".apex")):
            self.export_to_xml(filepath)
        else:
            from apex_vision.core.fileio import atomic_write_json
            atomic_write_json(filepath, self.to_dict())

    @classmethod
    def from_dict(cls, data: dict) -> "VisionPipeline":
        """Reconstruct VisionPipeline from dictionary representation."""
        from apex_vision.core.registry import create_tool_instance
        pipe = cls(name=data.get("name", "ImportedFlow"))
        pipe.enabled = data.get("enabled", True)
        pipe.run_interval_ms = float(data.get("run_interval_ms", 50.0))
        pipe.stop_on_ng = bool(data.get("stop_on_ng", False))
        pipe.flow_timeout_ms = float(data.get("flow_timeout_ms", 5000.0))
        pipe.execution_count = int(data.get("execution_count", 0))

        for n_data in data.get("nodes", []):
            tool = create_tool_instance(n_data["tool_name"], n_data["instance_id"], n_data.get("name"), allow_placeholder=True)
            tool.load_dict(n_data)
            pipe.add_node(tool)

        for c_data in data.get("connections", []):
            pipe.connect(c_data["from_node"], c_data["from_port"], c_data["to_node"], c_data["to_port"], force=True)

        raw_positions = data.get("positions")
        if isinstance(raw_positions, dict):
            for nid, xy in raw_positions.items():
                try:
                    x, y = float(xy[0]), float(xy[1])
                except (TypeError, ValueError, IndexError, KeyError):
                    continue
                if nid in pipe.nodes and math.isfinite(x) and math.isfinite(y):
                    pipe.node_positions[nid] = [x, y]

        return pipe

    @classmethod
    def import_from_file(cls, filepath: str) -> "VisionPipeline":
        """Import flow from .xml / .prc / .json format (Manual p. 93)."""
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        stripped = content.strip()
        if filepath.lower().endswith(".xml") or stripped.startswith("<?xml") or stripped.startswith("<"):
            return cls.from_xml(content)

        data = json.loads(content)
        return cls.from_dict(data)

    def execute_flow(
        self,
        global_vars: Optional[Dict[str, Any]] = None,
        on_step_callback: Optional[Callable[[str, ToolExecutionResult], None]] = None
    ) -> Dict[str, ToolExecutionResult]:
        """
        Execute all enabled tools in topological sequence.
        Transfers outputs along connections, shares global variables,
        and enforces flow timeouts and branch filtering.
        """
        if not self.enabled:
            return {}

        start_time = time.perf_counter()
        self.execution_count += 1
        results: Dict[str, ToolExecutionResult] = {}
        data_cache: Dict[str, Dict[str, Any]] = {}
        bypassed_branches = set()

        global_ctx = {
            "globals": global_vars if global_vars is not None else {},
            "flow_name": self.name,
            # what Time Consuming needs: when the flow began, what has run so far (live), in what order, and the modules' names
            "flow_started": start_time,
            "results": results,
            "order": list(self.execution_order),
            "node_names": {nid: n.name for nid, n in self.nodes.items()},
        }

        timed_out = False
        done: set = set()

        def run_one(node_id: str) -> Optional[ToolExecutionResult]:
            nonlocal timed_out
            node = self.nodes.get(node_id)
            if not node:
                return None

            # Timeout enforcement (Manual p. 93 Flow Timeout)
            elapsed_so_far = (time.perf_counter() - start_time) * 1000.0
            if elapsed_so_far > self.flow_timeout_ms or timed_out:
                timed_out = True
                res = ToolExecutionResult(
                    status=ToolStatus.TIMEOUT,
                    message=f"Flow timeout exceeded ({self.flow_timeout_ms:.1f} ms limit)",
                    elapsed_ms=0.0
                )
                results[node_id] = res
                if on_step_callback:
                    on_step_callback(node_id, res)
                return res

            # Bypass check (Manual toggle or conditional branch deactivation)
            if not node.enabled or node_id in bypassed_branches:
                reason = "Bypassed by Branch Logic" if node_id in bypassed_branches else "Bypassed (Disabled)"
                res = ToolExecutionResult(status=ToolStatus.BYPASS, message=reason)
                results[node_id] = res
                if on_step_callback:
                    on_step_callback(node_id, res)
                return res

            node_context: Dict[str, Any] = {"global": global_ctx}
            for c in self.connections:
                if c.to_node == node_id:
                    from_res = data_cache.get(c.from_node, {})
                    if c.from_port in from_res:
                        node_context[c.to_port] = from_res[c.from_port]

            t0 = time.perf_counter()
            try:
                res = node.execute(node_context)
                res.elapsed_ms = (time.perf_counter() - t0) * 1000.0
            except Exception as e:
                import logging
                logging.getLogger("apex_vision.pipeline").exception(f"Unhandled exception executing node '{node.name}' ({node_id}): {e}")
                res = ToolExecutionResult(
                    status=ToolStatus.ERROR,
                    message=f"Exception: {str(e)}",
                    elapsed_ms=(time.perf_counter() - t0) * 1000.0
                )

            # Conditional branch routing (Manual p. 551 Branch & Condition Branch)
            if "Inactive_Branches" in res.outputs and isinstance(res.outputs["Inactive_Branches"], list):
                for inactive_id in res.outputs["Inactive_Branches"]:
                    bypassed_branches.add(inactive_id)

            results[node_id] = res
            data_cache[node_id] = res.outputs

            if on_step_callback:
                on_step_callback(node_id, res)
            return res

        def run_group(gid: str) -> None:
            """Run a Group: its modules once, or round a loop, then report the group as a whole."""
            gnode = self.nodes[gid]
            members = self.group_members(gid)
            done.update(members)
            if not gnode.enabled or gid in bypassed_branches:
                reason = "Bypassed by Branch Logic" if gid in bypassed_branches else "Bypassed (Disabled)"
                for m in [gid] + members:
                    results[m] = ToolExecutionResult(status=ToolStatus.BYPASS, message=reason)
                    if on_step_callback:
                        on_step_callback(m, results[m])
                return
            loop = bool(gnode.get_param("loop_enable"))
            lo, hi = int(gnode.get_param("loop_start")), int(gnode.get_param("loop_end"))
            indices = list(range(lo, min(hi, lo + 100000))) if loop else [0]
            interval = max(0.0, float(gnode.get_param("interval_ms"))) / 1000.0 if loop else 0.0
            loops, broke, last = 0, False, lo
            t_group = time.perf_counter()
            for n, i in enumerate(indices):
                last = i
                data_cache[gid] = {"Cycle": i, "Loops": loops, "Broke": False}
                bypassed_branches.difference_update(members)             # every pass starts with all of its modules switched on
                for m in members:
                    run_one(m)
                loops += 1
                data_cache[gid] = {"Cycle": i, "Loops": loops, "Broke": False}
                if loop and bool(gnode.get_param("break_enable")) and self._group_should_break(gnode, gid, data_cache):
                    broke = True
                    break
                if timed_out:
                    break
                if interval > 0 and n < len(indices) - 1:
                    remaining = (self.flow_timeout_ms - (time.perf_counter() - start_time) * 1000.0) / 1000.0
                    time.sleep(max(0.0, min(interval, remaining)))
            inner = [results[m] for m in members if m in results and results[m].status != ToolStatus.BYPASS]
            statuses = {r.status for r in inner}
            worst = ToolStatus.ERROR if ToolStatus.ERROR in statuses else ToolStatus.TIMEOUT if ToolStatus.TIMEOUT in statuses else ToolStatus.NG if ToolStatus.NG in statuses else ToolStatus.OK
            res = ToolExecutionResult(
                status=worst,
                message=f"{loops} pass(es) over {len(members)} module(s)" + (" - stopped by the break condition" if broke else ""),
                outputs={"Cycle": last, "Loops": loops, "Broke": broke},
                elapsed_ms=(time.perf_counter() - t_group) * 1000.0)
            results[gid] = res
            data_cache[gid] = res.outputs
            if on_step_callback:
                on_step_callback(gid, res)

        for node_id in self.execution_order:
            if node_id in done:
                continue
            node = self.nodes.get(node_id)
            if node is not None and node.tool_name == "Group":
                run_group(node_id)
            else:
                run_one(node_id)

        total_elapsed = (time.perf_counter() - start_time) * 1000.0
        self.last_flow_time_ms = total_elapsed
        self.last_results = results
        return results

    def _group_should_break(self, gnode, gid: str, data_cache: Dict[str, Dict[str, Any]]) -> bool:
        """The Group's break test: compare its Base value with its Target value (each wired from a module, or typed)."""
        def value(port_name: str, typed_name: str):
            for c in self.connections:
                if c.to_node == gid and c.to_port == port_name:
                    out = data_cache.get(c.from_node, {})
                    if c.from_port in out:
                        return out[c.from_port]
            return gnode.get_param(typed_name)
        a, b = value("Base", "base_value"), value("Target", "target_value")
        kind = str(gnode.get_param("compare_type"))
        try:
            if kind == "String":
                a, b = str(a), str(b)
            elif kind == "Int":
                a, b = int(float(a)), int(float(b))
            else:
                a, b = float(a), float(b)
        except (TypeError, ValueError):
            return False
        op = str(gnode.get_param("break_when"))
        return {"==": a == b, "!=": a != b, ">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b}.get(op, False) if kind != "String" or op in ("==", "!=") else False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "run_interval_ms": self.run_interval_ms,
            "stop_on_ng": self.stop_on_ng,
            "flow_timeout_ms": self.flow_timeout_ms,
            "execution_count": self.execution_count,
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "connections": [c.to_dict() for c in self.connections],
            "positions": {nid: list(xy) for nid, xy in self.node_positions.items()
                          if nid in self.nodes},
        }


class _GlobalScriptContext:
    """Handle passed to the solution's global script."""

    def __init__(self, solution: "SolutionManager", results: Dict[str, str]):
        self._solution = solution
        self.results = results

    def get_global(self, name: str, default: Any = None) -> Any:
        return self._solution.get_global(name, default)

    def set_global(self, name: str, value: Any) -> None:
        self._solution.set_global(name, value)


class SolutionManager:
    """
    Manages complete Apex Vision solution containing multiple Flows and Global Variables.
    (Manual p. 93-97 Multi-Flow & p. 108-112 Global Variables)
    """
    def __init__(self, name: str = "Solution1"):
        self.name: str = name
        self.flows: Dict[str, VisionPipeline] = {}
        self.active_flow_name: str = "Flow1"
        # Name of the flow that receives the dependency wires in the Multi-Flow
        # overview (Manual p. 95 - the converging "trigger" flow card).
        self.trigger_flow_name: str = "Flow1"
        # Optional Python source defining process(context); run after every flow cycle.
        self.global_script: str = ""
        self.comm_devices: List[Dict[str, Any]] = []     # Communication Management: the network devices of this solution
        self.global_variables: Dict[str, Any] = {
            "g_CountOK": 0,
            "g_CountNG": 0,
            "g_LotNumber": "LOT-2026-A1",
            "g_TriggerEnable": True
        }
        #: Variables that hold *runtime* state rather than settings - a lot tally, a running
        #: count.  They live in the same shared namespace and are still saved, but a value the
        #: flow wrote during a run must not count as an unsaved edit by the operator.  See
        #: ProjectState.snapshot, which leaves them out of the comparison.
        self.runtime_globals: Set[str] = set()
        # Initialize default main flow
        self.add_flow("Flow1")

    def add_flow(self, flow_name: str) -> VisionPipeline:
        if flow_name not in self.flows:
            self.flows[flow_name] = VisionPipeline(name=flow_name)
        return self.flows[flow_name]

    def remove_flow(self, flow_name: str):
        if flow_name in self.flows and len(self.flows) > 1:
            del self.flows[flow_name]
            if self.active_flow_name == flow_name:
                self.active_flow_name = list(self.flows.keys())[0]
            if self.trigger_flow_name == flow_name:
                self.trigger_flow_name = list(self.flows.keys())[0]

    def get_trigger_flow_name(self) -> str:
        if self.trigger_flow_name not in self.flows:
            self.trigger_flow_name = list(self.flows.keys())[0]
        return self.trigger_flow_name

    def set_trigger_flow(self, flow_name: str):
        if flow_name in self.flows:
            self.trigger_flow_name = flow_name

    def duplicate_flow(self, flow_name: str, new_name: Optional[str] = None) -> VisionPipeline:
        """Duplicates an existing flow in the solution (Manual p. 93)."""
        if flow_name not in self.flows:
            raise KeyError(f"Flow '{flow_name}' not found.")
        orig = self.flows[flow_name]
        if new_name is not None:
            if new_name in self.flows:
                raise ValueError(f"Flow named '{new_name}' already exists in solution.")
            target_name = new_name
        else:
            base_name = f"{orig.name}_Copy"
            target_name = base_name
            counter = 1
            while target_name in self.flows:
                target_name = f"{base_name}_{counter}"
                counter += 1

        cloned = orig.duplicate(new_name=target_name)
        self.flows[target_name] = cloned
        return cloned

    def rename_flow(self, old_name: str, new_name: str) -> None:
        """Renames an existing flow, maintaining dictionary order and updating references."""
        if old_name not in self.flows:
            raise KeyError(f"Flow '{old_name}' not found.")
        if new_name == old_name:
            return
        if new_name in self.flows:
            raise ValueError(f"Flow named '{new_name}' already exists.")

        # Preserve key order by reconstructing dict
        new_flows: Dict[str, VisionPipeline] = {}
        for k, v in self.flows.items():
            if k == old_name:
                v.name = new_name
                new_flows[new_name] = v
            else:
                new_flows[k] = v
        self.flows = new_flows

        if self.active_flow_name == old_name:
            self.active_flow_name = new_name
        if self.trigger_flow_name == old_name:
            self.trigger_flow_name = new_name

    def export_flow(self, flow_name: str, filepath: str):
        """Exports a single flow to .xml / .prc / .json format (Manual p. 93)."""
        if flow_name in self.flows:
            self.flows[flow_name].export_to_file(filepath)

    def import_flow(self, filepath: str, flow_name: Optional[str] = None) -> VisionPipeline:
        """Imports a single flow from .xml / .prc / .json into the solution (Manual p. 93)."""
        cloned = VisionPipeline.import_from_file(filepath)
        target_name = flow_name or cloned.name
        # Ensure unique name
        base_name = target_name
        counter = 1
        while target_name in self.flows:
            target_name = f"{base_name}_{counter}"
            counter += 1
        cloned.name = target_name
        self.flows[target_name] = cloned
        return cloned

    def export_flow_xml(self, flow_name: str, filepath: str):
        """Exports a single flow directly to XML format."""
        if flow_name in self.flows:
            self.flows[flow_name].export_to_xml(filepath)

    def import_flow_xml(self, filepath: str, flow_name: Optional[str] = None) -> VisionPipeline:
        """Imports a single flow from XML format into the solution."""
        return self.import_flow(filepath, flow_name=flow_name)

    def get_active_flow(self) -> VisionPipeline:
        if self.active_flow_name not in self.flows:
            self.active_flow_name = list(self.flows.keys())[0]
        return self.flows[self.active_flow_name]

    def set_global(self, name: str, value: Any):
        self.global_variables[name] = value

    def run_global_script(self, results: Optional[Dict[str, ToolExecutionResult]] = None) -> Optional[str]:
        """Run the solution's global script once; returns an error text, or None on success.

        The script must define ``process(context)``; ``context`` offers ``get_global``,
        ``set_global`` and ``results`` (module name -> verdict of the cycle just executed).
        """
        code = (self.global_script or "").strip()
        if not code:
            return None
        results = results or {}
        flow = self.flows.get(self.active_flow_name)
        verdicts = {}
        for nid, res in results.items():
            node = flow.nodes.get(nid) if flow else None
            verdicts[node.name if node else nid] = res.status.value
        ctx = _GlobalScriptContext(self, verdicts)
        env: Dict[str, Any] = {"__name__": "global_script"}
        try:
            exec(code, env)
            process = env.get("process")
            if not callable(process):
                return "Global script must define process(context)"
            process(ctx)
        except Exception as exc:
            return f"Global script error: {type(exc).__name__}: {exc}"
        return None

    def get_global(self, name: str, default: Any = None) -> Any:
        return self.global_variables.get(name, default)

    def trigger_flow(self, flow_name: str) -> Dict[str, ToolExecutionResult]:
        """Triggers a specific flow by name (Manual p. 588 Trigger Module)."""
        if flow_name in self.flows and self.flows[flow_name].enabled:
            return self.flows[flow_name].execute_flow(global_vars=self.global_variables)
        return {}

    def execute_all_flows(self) -> Dict[str, Dict[str, ToolExecutionResult]]:
        """Executes all enabled flows in the solution."""
        all_results = {}
        for fname, flow in self.flows.items():
            if flow.enabled:
                all_results[fname] = flow.execute_flow(global_vars=self.global_variables)
        return all_results

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "active_flow": self.active_flow_name,
            "trigger_flow": self.trigger_flow_name,
            "global_variables": self.global_variables,
            # only when some are marked, so a file that never used the feature is unchanged
            **({"runtime_globals": sorted(self.runtime_globals)} if self.runtime_globals else {}),
            "global_script": self.global_script,
            **({"comm_devices": self.comm_devices} if self.comm_devices else {}),
            "flows": [flow.to_dict() for flow in self.flows.values()]
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SolutionManager":
        """Reconstruct SolutionManager from dictionary representation."""
        sol = cls(name=data.get("name", "Solution1"))
        sol.active_flow_name = data.get("active_flow", "Flow1")
        sol.trigger_flow_name = data.get("trigger_flow", sol.active_flow_name)
        if "global_variables" in data and isinstance(data["global_variables"], dict):
            sol.global_variables = copy.deepcopy(data["global_variables"])
        if isinstance(data.get("runtime_globals"), list):
            sol.runtime_globals = {str(n) for n in data["runtime_globals"]
                                   if str(n) in sol.global_variables}

        if isinstance(data.get("global_script"), str):
            sol.global_script = data["global_script"]
        if isinstance(data.get("comm_devices"), list):
            sol.comm_devices = [dict(d) for d in data["comm_devices"] if isinstance(d, dict)]

        flows_data = data.get("flows", [])
        if flows_data:
            sol.flows.clear()
            for f_dict in flows_data:
                flow = VisionPipeline.from_dict(f_dict)
                sol.flows[flow.name] = flow
        if sol.active_flow_name not in sol.flows and sol.flows:
            sol.active_flow_name = list(sol.flows.keys())[0]
        if sol.trigger_flow_name not in sol.flows and sol.flows:
            sol.trigger_flow_name = sol.active_flow_name
        return sol

    def to_xml(self) -> str:
        """The whole solution - flows, layout, global variables and script - as XML."""
        import xml.etree.ElementTree as ET
        root = ET.Element(SOLUTION_TAG, attrib={
            "version": "4.3", "name": self.name,
            "active_flow": self.active_flow_name, "trigger_flow": self.trigger_flow_name})
        vars_el = ET.SubElement(root, "GlobalVariables")
        for key, val in self.global_variables.items():
            vtype, enc = VisionPipeline._encode_xml_value(val)
            attrs = {"name": str(key), "type": vtype}
            if str(key) in self.runtime_globals:      # only when true, so old files stay identical
                attrs["runtime"] = "true"
            ET.SubElement(vars_el, "Variable", attrib=attrs).text = enc
        if self.comm_devices:
            devs_el = ET.SubElement(root, "CommDevices")
            for d in self.comm_devices:
                ET.SubElement(devs_el, "Device", attrib={k: ("true" if v is True else "false" if v is False else str(v)) for k, v in d.items()})
        if self.global_script:
            stype, senc = VisionPipeline._encode_xml_value(self.global_script)
            ET.SubElement(root, "GlobalScript", attrib={"type": stype}).text = senc
        flows_el = ET.SubElement(root, "Flows")
        for flow in self.flows.values():
            flows_el.append(flow.to_xml_element())
        return VisionPipeline._flow_element_to_string(root)

    @classmethod
    def from_xml(cls, xml_str: str) -> "SolutionManager":
        """Parse an ``<ApexSolution>`` (or a single ``<ApexFlow>``) document; the legacy ``VisionMaster*`` names also load."""
        from apex_vision.core.xml_safe import safe_fromstring
        return cls.from_xml_element(safe_fromstring(xml_str))

    @classmethod
    def from_xml_element(cls, root) -> "SolutionManager":
        if root.tag in FLOW_TAGS:
            pipe = VisionPipeline.from_xml_element(root)
            sol = cls(name=pipe.name)
            sol.flows = {pipe.name: pipe}
            sol.active_flow_name = pipe.name
            sol.set_trigger_flow(pipe.name)
            return sol
        if root.tag not in (SOLUTION_TAG, LEGACY_SOLUTION_TAG):
            raise ValueError(f"Not an Apex Vision document: root element is <{root.tag}>")
        sol = cls(name=root.attrib.get("name", "Solution1"))
        sol.active_flow_name = root.attrib.get("active_flow", "Flow1")
        sol.trigger_flow_name = root.attrib.get("trigger_flow", sol.active_flow_name)
        vars_el = root.find("GlobalVariables")
        if vars_el is not None:
            sol.global_variables = {}
            sol.runtime_globals = set()
            for v_el in vars_el.findall("Variable"):
                vname = v_el.attrib.get("name")
                if vname:
                    sol.global_variables[vname] = VisionPipeline._decode_xml_value(
                        v_el.attrib.get("type"), v_el.text)
                    if str(v_el.attrib.get("runtime", "")).lower() in ("true", "1", "yes"):
                        sol.runtime_globals.add(vname)
        devs_el = root.find("CommDevices")
        if devs_el is not None:
            for d_el in devs_el.findall("Device"):
                d = dict(d_el.attrib)
                d["auto_start"] = str(d.get("auto_start", "false")).lower() == "true"
                try:
                    d["port"] = int(d.get("port", 8000))
                except ValueError:
                    continue
                sol.comm_devices.append(d)
        script_el = root.find("GlobalScript")
        if script_el is not None:
            sol.global_script = str(VisionPipeline._decode_xml_value(
                script_el.attrib.get("type", "str"), script_el.text))
        flows_el = root.find("Flows")
        if flows_el is not None:
            sol.flows.clear()
            for f_el in (e for e in flows_el if e.tag in FLOW_TAGS):
                flow = VisionPipeline.from_xml_element(f_el)
                sol.flows[flow.name] = flow
        if sol.active_flow_name not in sol.flows and sol.flows:
            sol.active_flow_name = list(sol.flows.keys())[0]
        if sol.trigger_flow_name not in sol.flows and sol.flows:
            sol.trigger_flow_name = sol.active_flow_name
        return sol

    def save_to_file(self, filepath: str):
        """Save the solution: XML for ``.apex`` and ``.xml``, JSON for everything else (legacy .vmp / .sol / .json)."""
        if filepath.lower().endswith((".xml", ".apex")):
            from apex_vision.core.fileio import atomic_write_text
            atomic_write_text(filepath, self.to_xml())
            return
        from apex_vision.core.fileio import atomic_write_json
        atomic_write_json(filepath, self.to_dict())

    @classmethod
    def load_from_file(cls, filepath: str) -> "SolutionManager":
        """Load a solution or flow file from .apex, .xml, or the older .vmp, .sol, .json.

        Raises ``ValueError`` with a readable message for corrupt or unrelated files.
        """
        try:
            with open(filepath, "r", encoding="utf-8-sig") as f:
                content = f.read()
        except UnicodeDecodeError as exc:
            raise ValueError(f"'{os.path.basename(filepath)}' is not a text solution file ({exc.reason})") from exc

        stripped = content.strip()
        if filepath.lower().endswith(".xml") or stripped.startswith("<?xml") or stripped.startswith("<"):
            import xml.etree.ElementTree as ET
            try:
                return cls.from_xml(content)
            except ET.ParseError as exc:
                raise ValueError(
                    f"'{os.path.basename(filepath)}' is not valid XML ({exc})") from exc

        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"'{os.path.basename(filepath)}' is not a valid solution file "
                f"(corrupt or truncated JSON at line {exc.lineno}, column {exc.colno})") from exc
        if not isinstance(data, dict):
            raise ValueError(f"'{os.path.basename(filepath)}' is not a solution file "
                             f"(expected an object, found {type(data).__name__})")
        if "flows" in data and isinstance(data["flows"], list):
            return cls.from_dict(data)
        elif "nodes" in data:
            single_pipe = VisionPipeline.from_dict(data)
            sol = cls(name=data.get("name", "LoadedSolution"))
            sol.flows = {single_pipe.name: single_pipe}
            sol.active_flow_name = single_pipe.name
            sol.set_trigger_flow(single_pipe.name)
            return sol
        else:
            return cls.from_dict(data)


