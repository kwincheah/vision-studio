"""Audit persistence and file handling: projects, image loads, export/import.

These are the paths where a user's *data* is at risk, so each is tested with real
files and with the failure modes that actually happen: a missing file, a corrupt
file, a truncated XML document, a read-only target directory, and a wrong-extension
file.  A handler that raises, or that reports success while writing nothing, is worse
than one that refuses.

Run:  python scripts/audit_persistence.py
"""
import json
import os
import shutil
import sys
import tempfile
import traceback
from typing import Any, Dict, List

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from vm_clone.core.base_tool import ToolStatus  # noqa: E402
from vm_clone.core.registry import create_tool_instance  # noqa: E402
import vm_clone.tools  # noqa: E402,F401


def case(label: str, fn) -> Dict[str, Any]:
    rec = {"case": label, "outcome": "ok", "detail": ""}
    try:
        fn()
    except Exception as exc:
        rec["outcome"] = "RAISED"
        rec["detail"] = f"{type(exc).__name__}: {exc}"
        rec["trace"] = traceback.format_exc()[-400:]
    return rec


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="vm_audit_")
    results: List[Dict[str, Any]] = []
    problems: List[str] = []

    try:
        # ---------------------------------------------------------------
        # 1. Image acquisition: every failure mode must be reported, not raised
        # ---------------------------------------------------------------
        def missing_file():
            tool = create_tool_instance("Image Source", "src")
            tool.set_param("source_type", "File")
            tool.set_param("file_path", os.path.join(tmp, "does_not_exist.png"))
            res = tool.execute({})
            assert res is not None
            if res.status == ToolStatus.OK:
                raise AssertionError("missing file reported OK")

        results.append(case("Image Source: missing file -> error", missing_file))

        def empty_file():
            p = os.path.join(tmp, "empty.png")
            open(p, "wb").close()
            tool = create_tool_instance("Image Source", "src")
            tool.set_param("source_type", "File")
            tool.set_param("file_path", p)
            res = tool.execute({})
            if res.status == ToolStatus.OK:
                raise AssertionError("empty file reported OK")

        results.append(case("Image Source: empty file -> error", empty_file))

        def garbage_file():
            p = os.path.join(tmp, "garbage.png")
            with open(p, "wb") as fh:
                fh.write(b"this is not a png at all" * 40)
            tool = create_tool_instance("Image Source", "src")
            tool.set_param("source_type", "File")
            tool.set_param("file_path", p)
            res = tool.execute({})
            if res.status == ToolStatus.OK:
                raise AssertionError("garbage file reported OK")

        results.append(case("Image Source: corrupt file -> error", garbage_file))

        def directory_as_file():
            tool = create_tool_instance("Image Source", "src")
            tool.set_param("source_type", "File")
            tool.set_param("file_path", tmp)
            res = tool.execute({})
            if res.status == ToolStatus.OK:
                raise AssertionError("directory as image reported OK")

        results.append(case("Image Source: directory path -> error", directory_as_file))

        def valid_file():
            import cv2
            p = os.path.join(tmp, "ok.png")
            cv2.imwrite(p, np.full((60, 80, 3), 200, dtype=np.uint8))
            tool = create_tool_instance("Image Source", "src")
            tool.set_param("source_type", "File")
            tool.set_param("file_path", p)
            res = tool.execute({})
            if res.status != ToolStatus.OK:
                raise AssertionError(f"valid file reported {res.status.value}: {res.message}")
            img = res.outputs.get("Image")
            if not isinstance(img, np.ndarray) or img.shape[:2] != (60, 80):
                raise AssertionError(f"wrong image returned: {getattr(img, 'shape', img)}")

        results.append(case("Image Source: valid file -> 60x80 image", valid_file))

        # ---------------------------------------------------------------
        # 2. Project save / load round trip, then corrupt, truncate and
        #    permission-denied cases.  `load_project` is documented to raise;
        #    every caller in the UI wraps it, so what is checked here is that
        #    (a) it raises a *catchable* exception rather than corrupting state,
        #    (b) the round trip is faithful, and (c) a failed load leaves the
        #    recent-projects store usable.
        # ---------------------------------------------------------------
        from vm_clone.core.project_manager import ProjectManager
        from vm_clone.samples.pcb_solution import create_pcb_inspection_solution

        def roundtrip():
            from vm_clone.core.pipeline import SolutionManager

            pm = ProjectManager(workspace_root=tmp)
            pipe = create_pcb_inspection_solution()
            solution = SolutionManager(name="audit_proj")
            solution.flows = {pipe.name: pipe}
            solution.active_flow_name = pipe.name
            solution.set_trigger_flow(pipe.name)

            path = os.path.join(tmp, "audit_proj.vmp")
            pm.save_project(solution, path)
            if not os.path.exists(path):
                raise AssertionError("save_project reported success but wrote no file")

            loaded = pm.load_project(path)
            if loaded is None:
                raise AssertionError("load_project returned None for its own file")
            if not loaded.flows:
                raise AssertionError("loaded solution has no flows")
            first = next(iter(loaded.flows.values()))
            if len(first.nodes) != len(pipe.nodes):
                raise AssertionError(
                    f"node count changed: {len(pipe.nodes)} -> {len(first.nodes)}")
            if len(first.connections) != len(pipe.connections):
                raise AssertionError("connection count changed after round trip")
            # parameter values must survive too, not just the topology
            for nid, node in pipe.nodes.items():
                if nid not in first.nodes:
                    raise AssertionError(f"node {nid} missing after load")
                if first.nodes[nid].parameters != node.parameters:
                    raise AssertionError(f"parameters changed for {node.name}")

        results.append(case("Project: save -> load round trip is faithful", roundtrip))

        def corrupt_json():
            pm = ProjectManager(workspace_root=tmp)
            p = os.path.join(tmp, "corrupt.vmp")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write('{"name": "x", "flows": [ this is not json')
            try:
                pm.load_project(p)
            except Exception as exc:
                # must be an ordinary, catchable exception - not a crash or a
                # partially-populated object
                if not isinstance(exc, Exception):
                    raise AssertionError(f"raised non-Exception {type(exc)}")
                return
            raise AssertionError("corrupt project loaded without any error")

        results.append(case("Project: corrupt file -> catchable error", corrupt_json))

        def missing_project():
            pm = ProjectManager(workspace_root=tmp)
            try:
                pm.load_project(os.path.join(tmp, "nope.vmp"))
            except (OSError, ValueError, KeyError, Exception) as exc:
                if not isinstance(exc, Exception):
                    raise AssertionError(f"raised non-Exception {type(exc)}")
                return
            raise AssertionError("missing project loaded without any error")

        results.append(case("Project: missing file -> catchable error", missing_project))

        def truncated_xml():
            pm = ProjectManager(workspace_root=tmp)
            from vm_clone.core.pipeline import SolutionManager
            pipe = create_pcb_inspection_solution()
            solution = SolutionManager(name="audit_xml")
            solution.flows = {pipe.name: pipe}
            solution.active_flow_name = pipe.name
            solution.set_trigger_flow(pipe.name)
            path = os.path.join(tmp, "audit_xml.vmp")
            pm.save_project(solution, path)
            with open(path, "rb") as fh:
                data = fh.read()
            trunc = os.path.join(tmp, "truncated.vmp")
            with open(trunc, "wb") as fh:
                fh.write(data[: max(1, len(data) // 3)])
            try:
                pm.load_project(trunc)
            except Exception as exc:
                if not isinstance(exc, Exception):
                    raise AssertionError(f"raised non-Exception {type(exc)}")
                return
            raise AssertionError("truncated project loaded without any error")

        results.append(case("Project: truncated file -> catchable error", truncated_xml))

        def recent_list_survives_a_bad_project():
            """A project that fails to load must not poison the recent list."""
            pm = ProjectManager(workspace_root=tmp)
            bad = os.path.join(tmp, "bad.vmp")
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write("not a project")
            pm.add_recent_project(bad, name="Bad")
            before = len(pm.get_recent_projects())
            try:
                pm.load_project(bad)
            except Exception:
                pass
            after = pm.get_recent_projects()
            if len(after) != before:
                raise AssertionError(f"recent list changed {before} -> {len(after)}")
            if not all("path" in e and "name" in e for e in after):
                raise AssertionError("recent entries lost their required keys")

        results.append(case("Project: failed load leaves the recent list intact",
                           recent_list_survives_a_bad_project))

        # ---------------------------------------------------------------
        # 3. Flow XML export / import round trip and rejection of junk
        # ---------------------------------------------------------------
        def xml_roundtrip():
            pipe = create_pcb_inspection_solution()
            xml = pipe.to_xml()
            if not xml or "<" not in xml:
                raise AssertionError("to_xml produced nothing usable")
            restored = type(pipe).from_xml(xml)
            if len(restored.nodes) != len(pipe.nodes):
                raise AssertionError("XML round trip lost nodes")

        results.append(case("Flow XML: export -> import preserves nodes", xml_roundtrip))

        def xml_junk():
            """Junk must give a diagnosable error, never a crash or an empty graph."""
            pipe = create_pcb_inspection_solution()
            for junk in ("", "   ", "not xml", '{"json": 1}', "\x00\x01binary", None):
                try:
                    result = type(pipe).from_xml(junk)
                except (ValueError, TypeError) as exc:
                    if not str(exc).strip():
                        raise AssertionError(f"from_xml({junk!r}) raised an empty message")
                    continue
                except Exception as exc:
                    raise AssertionError(
                        f"from_xml({junk!r}) raised unhelpful "
                        f"{type(exc).__name__}: {exc}")
                if result is None:
                    raise AssertionError(f"from_xml({junk!r}) returned None")
                if not getattr(result, "nodes", None):
                    raise AssertionError(
                        f"from_xml({junk!r}) silently produced an empty flow")

        results.append(case("Flow XML: junk input -> diagnosable error", xml_junk))

        def export_missing_dir():
            pipe = create_pcb_inspection_solution()
            target = os.path.join(tmp, "no_such_dir", "flow.xml")
            try:
                pipe.export_to_xml(target)
            except FileNotFoundError:
                return          # refusing is correct
            except Exception as exc:
                raise AssertionError(f"raised {type(exc).__name__}: {exc}")

        results.append(case("Flow XML: export into a missing directory", export_missing_dir))

        # ---------------------------------------------------------------
        # 4. Image Output module writes a real file
        # ---------------------------------------------------------------
        def image_output_writes():
            tool = create_tool_instance("Image Output", "out")
            out_dir = os.path.join(tmp, "out")
            os.makedirs(out_dir, exist_ok=True)
            tool.set_param("save_directory", out_dir)
            # The generated filename has millisecond resolution, so two saves inside
            # one second can collide; the directory mtime is the reliable evidence.
            before = (len(os.listdir(out_dir)), os.path.getmtime(out_dir))
            res = tool.execute({"Image": np.full((40, 50, 3), 128, dtype=np.uint8)})
            after = (len(os.listdir(out_dir)), os.path.getmtime(out_dir))
            if res.status == ToolStatus.OK and after == before:
                raise AssertionError("reported OK but wrote no file")

        results.append(case("Image Output: OK implies a file was written", image_output_writes))

        def image_output_unsupported_format():
            tool = create_tool_instance("Image Output", "out")
            out_dir = os.path.join(tmp, "out2")
            os.makedirs(out_dir, exist_ok=True)
            tool.set_param("save_directory", out_dir)
            tool.set_param("file_format", "xyz")
            res = tool.execute({"Image": np.full((40, 50, 3), 128, dtype=np.uint8)})
            # cv2.imwrite raises for an unknown extension; it must be reported
            if res.status == ToolStatus.OK:
                raise AssertionError("unsupported format reported OK")

        results.append(case("Image Output: unsupported format -> error",
                            image_output_unsupported_format))

        def image_output_unwritable_dir():
            tool = create_tool_instance("Image Output", "out")
            blocker = os.path.join(tmp, "blocker")
            with open(blocker, "w", encoding="utf-8") as fh:
                fh.write("x")
            tool.set_param("save_directory", os.path.join(blocker, "sub"))
            res = tool.execute({"Image": np.full((40, 50, 3), 128, dtype=np.uint8)})
            if res.status == ToolStatus.OK:
                raise AssertionError("unwritable directory reported OK")

        results.append(case("Image Output: unwritable directory -> error",
                            image_output_unwritable_dir))

        def image_output_save_policy():
            """`save_mode` and the Trigger port must actually gate the write."""
            img = np.full((40, 50, 3), 128, dtype=np.uint8)
            scenarios = [
                ("Only on NG with an OK verdict", "Only on NG", {"Result": True}, False),
                ("Only on NG with an NG verdict", "Only on NG", {"Result": False}, True),
                ("Only on OK with an NG verdict", "Only on OK", {"Result": False}, False),
                ("inactive trigger", "Always Save", {"Trigger": False}, False),
            ]
            for i, (label, mode, extra, expect_write) in enumerate(scenarios):
                d = os.path.join(tmp, f"policy{i}")
                os.makedirs(d, exist_ok=True)
                tool = create_tool_instance("Image Output", f"out{i}")
                tool.set_param("save_directory", d)
                tool.set_param("save_mode", mode)
                res = tool.execute({"Image": img, **extra})
                wrote = bool(os.listdir(d))
                if wrote != expect_write:
                    raise AssertionError(
                        f"{label}: wrote={wrote} expected={expect_write} ({res.message})")

        results.append(case("Image Output: save_mode and Trigger gate the write",
                            image_output_save_policy))

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    for r in results:
        flag = "ok  " if r["outcome"] == "ok" else "FAIL"
        print(f"{flag} {r['case']}")
        if r["outcome"] != "ok":
            problems.append(f"{r['case']}: {r['detail']}")
            print(f"       {r['detail']}")

    out = os.path.join(ROOT, "docs", "audit", "persistence_matrix.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1, default=str)

    print(f"\n{len(results)} persistence case(s), {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
