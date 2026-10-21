"""MCP server exposing the flow-generation tools to any MCP client (Claude Desktop, Claude Code, ...).

Start it with ``python main.py --mcp`` (or ``ApexVisionStudio.exe --mcp`` in a packaged build).  It speaks
MCP over stdio, calls no language model itself, and only reads the tool registry - except ``save_flow_xml``,
which writes inside the projects folder.  The client's model uses these tools the same way the in-app AI Gen
assistant does: look up, draft a spec, validate, repair, then build the XML.
"""
import os
import re
from typing import Any, Dict

from apex_vision.flowgen import api, docs
from apex_vision.flowgen.agent import SYSTEM_PROMPT


def projects_directory() -> str:
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "projects")


def safe_target(file_name: str, directory: str) -> str:
    """A path for ``file_name`` strictly inside ``directory`` (no separators, no traversal, .xml only)."""
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.basename(file_name.strip())).strip("._") or "flow"
    if not stem.lower().endswith(".xml"):
        stem += ".xml"
    path = os.path.abspath(os.path.join(directory, stem))
    if os.path.dirname(path) != os.path.abspath(directory):
        raise ValueError("The file must be inside the projects folder.")
    return path


def create_server(projects_dir: str = ""):
    from mcp.server.fastmcp import FastMCP
    directory = projects_dir or projects_directory()
    server = FastMCP("apex-flow-generator", instructions=SYSTEM_PROMPT)

    @server.tool()
    def search_tools(query: str, category: str = "") -> Dict[str, Any]:
        """Keyword search over the installed vision tools."""
        return api.search_tools(query, category)

    @server.tool()
    def get_tool_spec(tool: str) -> Dict[str, Any]:
        """Exact ports (with types) and parameters (defaults, allowed values) of one tool."""
        return api.get_tool_spec(tool)

    @server.tool()
    def search_docs(query: str) -> Dict[str, Any]:
        """Search the flow-building reference: concepts, port-type rules, worked recipes, per-tool pages."""
        return api.search_docs(query)

    @server.tool()
    def read_doc(section: str) -> Dict[str, Any]:
        """Read one reference section by id or title."""
        return api.read_doc(section)

    @server.tool()
    def validate_flow(spec: Dict[str, Any]) -> Dict[str, Any]:
        """Check a flow spec ({name, modules:[{id, tool, params}], links:[{from, from_port, to, to_port}]}); returns fixable issues."""
        return api.validate_flow(spec)

    @server.tool()
    def build_flow_xml(spec: Dict[str, Any], solution_name: str = "") -> Dict[str, Any]:
        """Turn a valid spec into the application's solution XML (opens in Apex Vision Studio)."""
        return api.build_xml(spec, solution_name)

    @server.tool()
    def dry_run(spec: Dict[str, Any]) -> Dict[str, Any]:
        """Run the flow once on synthetic input; modules with side effects are skipped."""
        return api.dry_run(spec)

    @server.tool()
    def save_flow_xml(spec: Dict[str, Any], file_name: str, solution_name: str = "") -> Dict[str, Any]:
        """Validate a spec and write its XML into the projects folder under ``file_name``."""
        built = api.build_xml(spec, solution_name)
        if not built["ok"]:
            return {"saved": False, "issues": built["issues"]}
        try:
            path = safe_target(file_name, directory)
        except ValueError as exc:
            return {"saved": False, "error": str(exc)}
        os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(built["xml"])
        return {"saved": True, "path": path, "issues": built["issues"]}

    @server.resource("apex://reference")
    def reference() -> str:
        """The complete flow-generation reference (concepts, recipes, tool catalogue)."""
        with open(docs.REFERENCE, encoding="utf-8") as f:
            return f.read()

    @server.prompt()
    def design_flow(task: str) -> str:
        """Plan and build a vision flow for a described inspection task."""
        return (f"Build a vision flow for this task: {task}\n\nFollow the workflow in the server instructions: look up "
                "recipes and tools, draft a spec, validate it until it is clean, then call build_flow_xml.")

    return server


def run() -> None:
    create_server().run()
