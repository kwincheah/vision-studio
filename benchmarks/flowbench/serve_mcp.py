"""Start Apex Vision Studio's flow-generation MCP server over streamable HTTP.

HUD's MCP capability needs an http/ws URL (no stdio), so this wraps the existing
``apex_vision.flowgen.mcp_server.create_server`` without changing it.
Usage: python serve_mcp.py <port> [projects_dir]
"""
import os
import sys
import tempfile

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from apex_vision.flowgen.mcp_server import create_server  # noqa: E402


def exit_with_parent() -> None:
    """Exit when the process that started us exits: HUD's local runtime can end a rollout
    without running @env.shutdown, which would otherwise leave this server running."""
    import threading
    parent = os.getppid()
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, parent)  # SYNCHRONIZE
        if not handle:
            return

        def wait() -> None:
            ctypes.windll.kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
            os._exit(0)
    else:
        import time

        def wait() -> None:
            while os.getppid() == parent:
                time.sleep(1)
            os._exit(0)
    threading.Thread(target=wait, daemon=True).start()


exit_with_parent()

port = int(sys.argv[1])
projects = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="flowbench_")
server = create_server(projects_dir=projects)
server.settings.host = "127.0.0.1"
server.settings.port = port
server.settings.log_level = "WARNING"
server.run(transport="streamable-http")
