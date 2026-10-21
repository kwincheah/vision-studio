"""The flow-generation MCP server: tools are callable in-process and over a real stdio session."""
import asyncio
import json
import os
import sys

import pytest

pytest.importorskip("mcp")
from apex_vision.flowgen import mcp_server

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SPEC = {"name": "M", "modules": [{"id": "src", "tool": "Image Source"}, {"id": "f", "tool": "Image Filter"}],
        "links": [{"from": "src", "from_port": "Image", "to": "f", "to_port": "Image"}]}


def test_safe_target_stays_inside_the_projects_folder(tmp_path):
    d = str(tmp_path)
    assert mcp_server.safe_target("my flow", d) == os.path.join(d, "my_flow.xml")
    for evil in ("../../etc/passwd", r"..\..\x", r"C:\Windows\x.xml", "/abs/path.xml", "a/../../b"):
        assert os.path.dirname(mcp_server.safe_target(evil, d)) == os.path.abspath(d)


def call(server, name, args):
    async def go():
        return await server.call_tool(name, args)
    out = asyncio.run(go())
    content = out[0] if isinstance(out, tuple) else out
    blocks = content if isinstance(content, list) else [content]
    return json.loads(blocks[0].text)


def test_tools_are_registered_and_work_in_process(tmp_path):
    server = mcp_server.create_server(str(tmp_path))
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"search_tools", "get_tool_spec", "search_docs", "validate_flow", "build_flow_xml", "dry_run", "save_flow_xml"} <= names
    assert call(server, "validate_flow", {"spec": SPEC})["ok"] is True
    bad = call(server, "validate_flow", {"spec": {"modules": [{"id": "a", "tool": "Nope"}]}})
    assert bad["ok"] is False and bad["issues"][0]["code"] == "unknown_tool"
    xml = call(server, "build_flow_xml", {"spec": SPEC})
    assert xml["ok"] and xml["xml"].startswith("<?xml")
    saved = call(server, "save_flow_xml", {"spec": SPEC, "file_name": "../escape"})
    assert saved["saved"] and os.path.dirname(saved["path"]) == str(tmp_path)
    assert not call(server, "save_flow_xml", {"spec": {"modules": []}, "file_name": "x"})["saved"]


def test_the_server_works_over_real_stdio():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def go():
        params = StdioServerParameters(command=sys.executable, args=[os.path.join(ROOT, "main.py"), "--mcp"], cwd=ROOT)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = {t.name for t in (await session.list_tools()).tools}
                res = await session.call_tool("search_tools", {"query": "caliper"})
                prompts = [p.name for p in (await session.list_prompts()).prompts]
                return tools, json.loads(res.content[0].text), prompts

    tools, found, prompts = asyncio.run(asyncio.wait_for(go(), 60))
    assert "build_flow_xml" in tools and found["tools"][0]["tool"] == "Caliper" and "design_flow" in prompts
