"""VisionMaster guide, Logic Tools and Communication chapters."""
import os

import numpy as np
import pytest

import apex_vision.tools  # noqa: F401
from apex_vision.core import dataqueue
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.pipeline import SolutionManager, VisionPipeline as Flow
from apex_vision.core.registry import create_tool_instance


def make(tool_name, /, **params):
    t = create_tool_instance(tool_name, "t")
    for k, v in params.items():
        t.set_param(k, v)
    return t


def run(tool_name, ctx=None, /, **params):
    return make(tool_name, **params).execute(ctx or {})


# ---- Condition Detection -----------------------------------------------------------------------------------------------------------------------------------
def test_condition_detection_all_and_any():
    both = run("Condition Detection", {"Value1": 5, "Value2": 50}, ranges="0,10; 40,60")
    assert both.status == ToolStatus.OK and both.outputs["Result"] == 1 and both.outputs["Results"] == [1, 1]
    one_bad = run("Condition Detection", {"Value1": 5, "Value2": 99}, ranges="0,10; 40,60")
    assert one_bad.status == ToolStatus.NG and one_bad.outputs["Results"] == [1, 0] and one_bad.outputs["Passed"] == 1
    any_ok = run("Condition Detection", {"Value1": 5, "Value2": 99}, ranges="0,10; 40,60", judge_method="Any")
    assert any_ok.status == ToolStatus.OK
    assert run("Condition Detection", {"Value1": 99, "Value2": 99}, ranges="0,10; 40,60", judge_method="Any").status == ToolStatus.NG
    shared = run("Condition Detection", {"Values": [1, 2, 3, 4]}, ranges="0,5")
    assert shared.outputs["Results"] == [1, 1, 1, 1], "the last range covers any value after it"
    edge = run("Condition Detection", {"Value1": 10.0}, ranges="0,10")
    assert edge.outputs["Result"] == 1, "the limits are inside the range"


def test_condition_detection_int_type_typed_values_and_problems():
    assert run("Condition Detection", {"Value1": 10.7}, ranges="0,10", condition_type="Int").status == ToolStatus.OK, "10.7 is taken as 10"
    assert run("Condition Detection", {"Value1": 10.7}, ranges="0,10", condition_type="Float").status == ToolStatus.NG
    typed = run("Condition Detection", {}, values="3, 4", ranges="0,5")
    assert typed.status == ToolStatus.OK and typed.outputs["Passed"] == 2
    mixed = run("Condition Detection", {"Value2": 7}, values="3", ranges="0,5; 0,10")
    assert mixed.outputs["Results"] == [1, 1]
    assert run("Condition Detection", {}).status == ToolStatus.ERROR
    assert run("Condition Detection", {"Value1": "x"}).status == ToolStatus.ERROR
    assert run("Condition Detection", {"Values": "abc"}).status == ToolStatus.ERROR
    assert run("Condition Detection", {"Value1": 1}, values="x").status == ToolStatus.ERROR
    assert run("Condition Detection", {"Value1": 1}, ranges="5,1").status == ToolStatus.ERROR
    assert run("Condition Detection", {"Value1": 1}, ranges="1").status == ToolStatus.ERROR
    assert run("Condition Detection", {"Value1": float("nan")}, ranges="0,1").status == ToolStatus.NG


# ---- Save Text ------------------------------------------------------------------------------------------------------------------------------------------------
def test_save_text_writes_lines_and_rolls_files(tmp_path):
    t = make("Save Text", save_dir=str(tmp_path), file_name="log", document_size_kb=1, file_count=3)
    for i in range(3):
        r = t.execute({"Text": f"line {i}"})
        assert r.status == ToolStatus.OK and r.outputs["Saved"] == 1
    files = sorted(os.listdir(tmp_path))
    assert files == ["log_0001.txt"] and (tmp_path / files[0]).read_bytes().decode() == "line 0\r\nline 1\r\nline 2\r\n"
    for _ in range(40):
        t.execute({"Text": "x" * 100})
    names = sorted(os.listdir(tmp_path))
    assert len(names) == 3 and names[-1] > "log_0003.txt", "only the newest 3 files are kept (the oldest were overwritten)"
    assert all((tmp_path / n).stat().st_size <= 1024 + 110 for n in names)


def test_save_text_stop_mode_trigger_csv_and_cache(tmp_path):
    stop = make("Save Text", save_dir=str(tmp_path / "s"), file_name="a", document_size_kb=1, file_count=1, save_mode="Stop Saving")
    status = [stop.execute({"Text": "y" * 200}).status for _ in range(8)]
    assert status[0] == ToolStatus.OK and status[-1] == ToolStatus.NG and len(os.listdir(tmp_path / "s")) == 1
    trig = make("Save Text", save_dir=str(tmp_path / "t"), file_name="t", trigger_value=1.0)
    assert trig.execute({"Text": "no", "Trigger": 0}).outputs["Saved"] == 0
    assert trig.execute({"Text": "yes", "Trigger": 1}).outputs["Saved"] == 1
    assert (tmp_path / "t" / "t_0001.txt").read_bytes().decode() == "yes\r\n"
    c = make("Save Text", save_dir=str(tmp_path / "c"), data_type="CSV", file_name="d", csv_header="a,b,c")
    c.execute({"Text": [1, "x,y", 3.5]})
    c.execute({"Text": [2, "z", 4]})
    assert (tmp_path / "c" / "d_0001.csv").read_bytes().decode() == 'a,b,c\r\n1,"x,y",3.5\r\n2,z,4\r\n'
    cache = make("Save Text", save_dir=str(tmp_path / "k"), file_name="k", real_time=False)
    waiting = cache.execute({"Text": "one"})
    assert waiting.outputs["Saved"] == 0 and waiting.outputs["Waiting"] == 1 and not (tmp_path / "k").exists()
    cache.execute({"Text": "two"})
    flushed = cache.execute({"Flush": True})
    assert flushed.outputs["Saved"] == 2 and (tmp_path / "k" / "k_0001.txt").read_bytes().decode() == "one\r\ntwo\r\n"


def test_save_text_names_dates_and_problems(tmp_path):
    r = run("Save Text", {"Text": "hi"}, save_dir=str(tmp_path), file_name='we/ird:name', timestamp=True, by_date=True)
    assert r.status == ToolStatus.OK
    day = [d for d in os.listdir(tmp_path)][0]
    name = os.listdir(tmp_path / day)[0]
    assert len(day) == 10 and name.endswith("we_ird_name_0001.txt") and name[8] == "_" and name[:8].isdigit()
    assert run("Save Text", {"Text": "hi"}).status == ToolStatus.ERROR
    assert run("Save Text", {}, save_dir=str(tmp_path)).status == ToolStatus.ERROR
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert run("Save Text", {"Text": "hi"}, save_dir=str(blocker / "sub")).status == ToolStatus.ERROR


# ---- Format Module -----------------------------------------------------------------------------------------------------------------------------------------------
def test_format_module_builds_the_message():
    r = run("Format Module", {"Data1": "OK", "Data2": 3.14159}, format="{Data1};{Data2:.2f}!")
    assert r.outputs["Text"] == "OK;3.14!\r\n" and r.outputs["Length"] == 10
    arr = run("Format Module", {"Data1": [1, 2, 3], "Data2": [[1, 2], [3, 4]]}, format="{Data1}|{Data2}", split_symbol=",", array_delimiter=";", end_char="")
    assert arr.outputs["Text"] == "1,2,3|1,2;3,4"
    dec = run("Format Module", {"Data1": 2.0, "Data2": [0.5, 1.25]}, format="{Data1} {Data2}", decimals=1, end_char="\\n")
    assert dec.outputs["Text"] == "2.0 0.5,1.2\n" or dec.outputs["Text"] == "2.0 0.5,1.3\n"
    ints = run("Format Module", {"Data1": 5.0, "Data2": True}, format="{Data1}{Data2}", end_char="")
    assert ints.outputs["Text"] == "51"
    plain = run("Format Module", {}, format="just words", end_char="")
    assert plain.outputs["Text"] == "just words"
    bad = run("Format Module", {"Data1": 1}, format="{Data1},{Data3}{Data2}", end_char="")
    assert bad.status == ToolStatus.ERROR and "Data2" in bad.message
    odd = run("Format Module", {"Data1": "abc"}, format="{Data1:.2f}", end_char="")
    assert odd.outputs["Text"] == "abc"
    safe = run("Format Module", {"Data1": 1}, format="{Data1.__class__} {0}", end_char="")
    assert safe.outputs["Text"] == "{Data1.__class__} {0}", "only {Data1}..{Data8} are filled in"


# ---- String Comparison ---------------------------------------------------------------------------------------------------------------------------------------------
def test_string_comparison_gives_the_index():
    r = run("String Comparison", {"Text": "NG"}, strings="OK;NG;WAIT")
    assert r.status == ToolStatus.OK and r.outputs["Index"] == 1 and r.outputs["Matched"] == 1
    assert run("String Comparison", {"Text": "nope"}, strings="OK;NG").status == ToolStatus.NG
    custom = run("String Comparison", {"Text": "B"}, strings="A\nB\nC", indices="10, 20, 30")
    assert custom.outputs["Index"] == 20
    short = run("String Comparison", {"Text": "C"}, strings="A;B;C", indices="7")
    assert short.outputs["Index"] == 2, "indices not given continue as 0, 1, 2..."
    assert run("String Comparison", {"Text": " ok\r\n"}, strings="OK", case_sensitive=False).status == ToolStatus.OK
    assert run("String Comparison", {"Text": " ok"}, strings="OK", case_sensitive=False, trim=False).status == ToolStatus.NG
    assert run("String Comparison", {"Text": "ok"}, strings="OK").status == ToolStatus.NG
    assert run("String Comparison", {"Text": 5}, strings="5").outputs["Index"] == 0
    assert run("String Comparison", {}, strings="OK").status == ToolStatus.ERROR
    assert run("String Comparison", {"Text": "a"}, strings="").status == ToolStatus.ERROR
    assert run("String Comparison", {"Text": "a"}, strings=";".join(str(i) for i in range(33))).status == ToolStatus.ERROR
    assert run("String Comparison", {"Text": "a"}, strings="a", indices="x").status == ToolStatus.ERROR


# ---- Point Set -------------------------------------------------------------------------------------------------------------------------------------------------------------
def test_point_set_gathers_points():
    r = run("Point Set", {"Points": [[1, 2], [3, 4]], "Point": (5, 6)})
    assert r.outputs["Points"] == [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]] and r.outputs["X"] == [1.0, 3.0, 5.0] and r.outputs["Y"] == [2.0, 4.0, 6.0] and r.outputs["Count"] == 3
    assert run("Point Set", {}, points=[[9, 9]]).outputs["Points"] == [[9.0, 9.0]]
    t = make("Point Set", loop=True)
    for i in range(20):
        r = t.execute({"Point": (i, i * 2)})
    assert r.outputs["Count"] == 16 and r.outputs["Points"][0] == [4.0, 8.0], "16 points at most; the oldest drop out"
    assert t.execute({"Point": (1, 1), "Clear": True}).outputs["Count"] == 1
    plain = make("Point Set")
    plain.execute({"Point": (1, 1)})
    assert plain.execute({"Point": (2, 2)}).outputs["Count"] == 1, "without the loop each run starts again"
    assert run("Point Set", {}).status == ToolStatus.NG
    assert run("Point Set", {"Points": "x"}).status == ToolStatus.ERROR
    assert run("Point Set", {"Point": ("a", 1)}).status == ToolStatus.ERROR


# ---- Time Consuming (inside a real flow) ----------------------------------------------------------------------------------------------------------------------
def test_time_consuming_in_a_flow():
    flow = Flow("f")
    a = create_tool_instance("Script", "slow", name="slow")
    a.set_param("code", "import time\ntime.sleep(0.05)\n")
    b = create_tool_instance("Script", "mid", name="mid")
    b.set_param("code", "import time\ntime.sleep(0.05)\n")
    tc = create_tool_instance("Time Consuming", "clock", name="clock")
    tc.set_param("measure", "Between Modules")
    tc.set_param("start_module", "slow")
    tc.set_param("end_module", "mid")
    tc2 = create_tool_instance("Time Consuming", "since", name="since")
    for n in (a, b, tc, tc2):
        flow.add_node(n)
    flow.execution_order = [a.instance_id, b.instance_id, tc.instance_id, tc2.instance_id]
    res = flow.execute_flow()
    assert res[tc.instance_id].status == ToolStatus.OK
    ms = res[tc.instance_id].outputs["Elapsed_Ms"]
    assert 90 <= ms < 400, ms
    assert res[tc2.instance_id].outputs["Elapsed_Ms"] >= ms
    tc.set_param("max_ms", 10.0)
    assert flow.execute_flow()[tc.instance_id].status == ToolStatus.NG
    tc.set_param("max_ms", 0.0)
    tc.set_param("start_module", "mid")
    tc.set_param("end_module", "slow")
    assert flow.execute_flow()[tc.instance_id].status == ToolStatus.ERROR, "the end comes before the start"
    tc.set_param("start_module", "nobody")
    assert flow.execute_flow()[tc.instance_id].status == ToolStatus.ERROR
    assert run("Time Consuming").status == ToolStatus.ERROR, "outside a flow there is no start time"


# ---- Data Set ----------------------------------------------------------------------------------------------------------------------------------------------------------------
def test_data_set_clear_signal_rules():
    t = make("Data Set", value_type="Int")
    for c, v in enumerate((3, 5, 8)):
        r = t.execute({"Value": v, "Cycle": c})
    assert r.outputs["Data"] == [3, 5, 8] and r.outputs["Count"] == 3 and r.outputs["Last"] == 8
    again = t.execute({"Value": 1, "Cycle": 0})
    assert again.outputs["Data"] == [1], "empty signal: the old cycle is cleared when a new one starts"
    keep = make("Data Set")
    for c, v in enumerate((1, 2)):
        keep.execute({"Value": v, "Cycle": c, "Clear": 0})
    assert keep.execute({"Value": 3, "Cycle": 0, "Clear": 0}).outputs["Data"] == [1.0, 2.0, 3.0], "signal 0: never cleared"
    last = make("Data Set")
    last.execute({"Value": 1, "Cycle": 0, "Clear": 1})
    assert last.execute({"Value": 2, "Cycle": 1, "Clear": 1}).outputs["Data"] == [2.0], "any other signal: only the last pass"
    s = run("Data Set", {"Value": 12.0}, value_type="String")
    assert s.outputs["Data"] == ["12"]
    assert run("Data Set", {}).status == ToolStatus.ERROR
    assert run("Data Set", {"Value": "abc"}, value_type="Float").status == ToolStatus.ERROR


# ---- Graphic Collection --------------------------------------------------------------------------------------------------------------------------------------------
def test_graphic_collection_draws_everything():
    pic = np.zeros((200, 300, 3), np.uint8)
    r = run("Graphic Collection", {"Image": pic, "Points": [[10, 10], [20, 20]], "Lines": [[0, 0, 50, 50]], "Rects": [[10, 10, 40, 30]],
                                   "Sectors": [{"cx": 100, "cy": 100, "r_in": 20, "r_out": 40, "start": 0, "end": 90}], "Text": "hello", "Status": 1})
    kinds = [o["type"] for o in r.overlays]
    assert r.status == ToolStatus.OK and r.outputs["Count"] == len(r.overlays)
    assert kinds.count("cross") == 2 and "line" in kinds and "rect" in kinds and "sector" in kinds and "text" in kinds
    assert all(o["color"] == (0, 220, 0) for o in r.overlays), "OK colour"
    bad = run("Graphic Collection", {"Image": pic, "Points": (5, 5), "Status": 0}, ng_color="Yellow")
    assert bad.status == ToolStatus.NG and bad.overlays[0]["color"] == (0, 255, 255)
    word = run("Graphic Collection", {"Image": pic, "Points": (5, 5), "Status": "NG"})
    assert word.status == ToolStatus.NG
    tint = run("Graphic Collection", {"Image": pic, "Rects": [[10, 10, 40, 30]]}, transparency=50)
    assert tint.overlays[0]["alpha"] == pytest.approx(0.5)
    turned = run("Graphic Collection", {"Image": pic, "Rects": [{"cx": 100, "cy": 100, "w": 60, "h": 20, "angle": 30}]})
    assert [o["type"] for o in turned.overlays].count("line") == 4
    from apex_vision.core.overlays import render_overlays
    drawn = render_overlays(pic, r.overlays)
    assert drawn.any(), "the sector and the rest really get painted"
    filled = render_overlays(pic, tint.overlays)
    assert filled[20, 20].sum() > 0 and filled[100, 250].sum() == 0
    assert run("Graphic Collection", {"Image": pic, "Lines": [[1, 2, 3]]}).status == ToolStatus.ERROR
    assert run("Graphic Collection", {"Image": pic, "Sectors": [{"cx": 1}]}).status == ToolStatus.ERROR
    assert run("Graphic Collection", {"Image": pic, "Points": "x"}).status == ToolStatus.ERROR
    assert run("Graphic Collection", {}).status == ToolStatus.OK, "nothing to draw is not an error"


# ---- Send Data / Receive Data -----------------------------------------------------------------------------------------------------------------------------------
def test_global_variables_and_queues_carry_data_between_modules():
    dataqueue.clear()
    gv = {}
    ctx = {"global": {"globals": gv}}
    s = run("Send Data", {**ctx, "Data": [1, 2, 3]}, name="shared")
    assert s.status == ToolStatus.OK and gv["shared"] == [1, 2, 3]
    r = run("Receive Data", ctx, name="shared")
    assert r.outputs["Data"] == [1, 2, 3] and r.outputs["Text"] == "1,2,3" and r.outputs["Has_Data"] == 1
    assert run("Receive Data", ctx, name="missing").status == ToolStatus.NG
    for v in ("a", "b", "c"):
        run("Send Data", {"Data": v}, target="Data Queue", name="q")
    assert dataqueue.size("q") == 3
    keep = run("Receive Data", {}, source="Data Queue", name="q", take="Keep")
    assert keep.outputs["Data"] == "a" and dataqueue.size("q") == 3
    got = [run("Receive Data", {}, source="Data Queue", name="q").outputs["Data"] for _ in range(3)]
    assert got == ["a", "b", "c"] and run("Receive Data", {}, source="Data Queue", name="q").status == ToolStatus.NG
    for i in range(5):
        run("Send Data", {"Data": i}, target="Data Queue", name="short", queue_length=3)
    assert dataqueue.size("short") == 3 and dataqueue.pop("short") == 2, "the oldest are dropped"
    off = run("Send Data", {**ctx, "Data": 1, "Trigger": 0}, name="gated")
    assert off.outputs["Sent"] == 0 and "gated" not in gv
    assert run("Send Data", {**ctx, "Data": 1, "Trigger": 1}, name="gated").outputs["Sent"] == 1
    assert run("Send Data", ctx, name="x").status == ToolStatus.ERROR
    assert run("Send Data", {"Data": 1}, name="").status == ToolStatus.ERROR
    assert run("Receive Data", {}, name="").status == ToolStatus.ERROR
    assert run("Receive Data", {}, source="Test Text", test_text="hello").outputs["Data"] == "hello"
    dataqueue.clear()


def test_two_flows_share_a_global_variable_through_the_solution():
    sol = SolutionManager()
    gv = sol.global_variables
    send = create_tool_instance("Send Data", "s")
    send.set_param("name", "answer")
    flow = Flow("one")
    flow.add_node(create_tool_instance("Script", "make"))
    flow.add_node(send)
    sc = [n for n in flow.nodes.values() if n.tool_name == "Script"][0]
    sc.set_param("code", "outputs['Result'] = 42\n")
    assert flow.connect(sc.instance_id, "Result", send.instance_id, "Data")
    flow.execution_order = [sc.instance_id, send.instance_id]
    flow.execute_flow(global_vars=gv)
    assert gv["answer"] == 42
    recv = create_tool_instance("Receive Data", "r")
    recv.set_param("name", "answer")
    other = Flow("two")
    other.add_node(recv)
    other.execution_order = [recv.instance_id]
    res = other.execute_flow(global_vars=gv)
    assert res[recv.instance_id].outputs["Data"] == 42


# ---- Protocol Parsing / Assembly ------------------------------------------------------------------------------------------------------------------------------
def test_text_parsing_and_assembly_round_trip():
    r = run("Protocol Parsing", {"Text": "1; 123;234"}, mode="Text", split_symbol=";")
    assert r.outputs["Values"] == [1, 123, 234] and r.outputs["Value2"] == 123 and r.outputs["Value4"] is None and r.outputs["Count"] == 3
    mix = run("Protocol Parsing", {"Text": "OK,3.5,-2"}, split_symbol=",")
    assert mix.outputs["Values"] == ["OK", 3.5, -2]
    crlf = run("Protocol Parsing", {"Text": "a|b\r\n"}, split_symbol="|")
    assert crlf.outputs["Values"] == ["a", "b"]
    esc = run("Protocol Parsing", {"Text": "a\tb"}, split_symbol="\\t")
    assert esc.outputs["Values"] == ["a", "b"]
    asm = run("Protocol Assembly", {"Values": [1, 2.5, "x"]}, mode="Text", split_symbol="|", end_char="\\r\\n")
    assert asm.outputs["Text"] == "1|2.5|x\r\n"
    back = run("Protocol Parsing", {"Text": asm.outputs["Text"]}, split_symbol="|")
    assert back.outputs["Values"] == [1, 2.5, "x"]
    ports = run("Protocol Assembly", {"Value1": 7, "Value2": "ab"}, split_symbol=",")
    assert ports.outputs["Text"] == "7,ab"
    assert run("Protocol Parsing", {}).status == ToolStatus.ERROR
    assert run("Protocol Parsing", {"Text": "a"}, split_symbol="").status == ToolStatus.ERROR
    assert run("Protocol Parsing", {"Text": ""}, split_symbol=";").status == ToolStatus.NG
    assert run("Protocol Assembly", {}).status == ToolStatus.ERROR
    assert run("Protocol Assembly", {"Value1": 1, "Value3": 3}).status == ToolStatus.ERROR, "a gap in the values"


def test_byte_parsing_and_assembly():
    r = run("Protocol Parsing", {"Text": "0000006400000005"}, mode="Byte", fields="i32,i32")
    assert r.outputs["Values"] == [100, 5]
    little = run("Protocol Parsing", {"Text": "64000000"}, mode="Byte", fields="speed:i32", byte_order="Little-endian")
    assert little.outputs["Values"] == [100]
    mixed = run("Protocol Parsing", {"Text": "FF 7F00 3F800000"}, mode="Byte", fields="i8,u16,float")
    assert mixed.outputs["Values"][0] == -1 and mixed.outputs["Values"][1] == 0x7F00 and mixed.outputs["Values"][2] == pytest.approx(1.0)
    ascii_ = run("Protocol Parsing", {"Text": "AB"}, mode="Byte", fields="u8,u8", input_format="ASCII")
    assert ascii_.outputs["Values"] == [65, 66]
    asm = run("Protocol Assembly", {"Values": [100, 5]}, mode="Byte", fields="i32,i32")
    assert asm.outputs["Text"] == "0000006400000005"
    f = run("Protocol Assembly", {"Values": [1.5, -2]}, mode="Byte", fields="float,i16", byte_order="Little-endian")
    assert run("Protocol Parsing", {"Text": f.outputs["Text"]}, mode="Byte", fields="float,i16", byte_order="Little-endian").outputs["Values"] == [1.5, -2]
    assert run("Protocol Parsing", {"Text": "00"}, mode="Byte", fields="i32").status == ToolStatus.NG, "too short for the fields"
    assert run("Protocol Parsing", {"Text": "zz"}, mode="Byte", fields="u8").status == ToolStatus.ERROR
    assert run("Protocol Parsing", {"Text": "00"}, mode="Byte", fields="bogus").status == ToolStatus.ERROR
    assert run("Protocol Assembly", {"Values": [1]}, mode="Byte", fields="i32,i32").status == ToolStatus.ERROR
    assert run("Protocol Assembly", {"Values": [300]}, mode="Byte", fields="u8").status == ToolStatus.ERROR, "does not fit one byte"
    assert run("Protocol Assembly", {"Values": ["x"]}, mode="Byte", fields="u8").status == ToolStatus.ERROR


def test_script_parsing_and_assembly_and_their_limits():
    r = run("Protocol Parsing", {"Text": "3;4"}, mode="Script")
    assert r.outputs["Values"] == [3.0, 4.0]
    d = run("Protocol Parsing", {"Text": "x"}, mode="Script", script="def parse(text):\n    return {'a': 1, 'b': 2}\n")
    assert d.outputs["Values"] == [1, 2]
    one = run("Protocol Parsing", {"Text": "x"}, mode="Script", script="def parse(text):\n    return 5\n")
    assert one.outputs["Values"] == [5]
    a = run("Protocol Assembly", {"Values": [1, 2]}, mode="Script")
    assert a.outputs["Text"] == "1;2"
    assert run("Protocol Parsing", {"Text": "x"}, mode="Script", script="x = 1").status == ToolStatus.ERROR
    assert run("Protocol Parsing", {"Text": "x"}, mode="Script", script="def parse(text):\n    return 1/0\n").status == ToolStatus.ERROR
    assert run("Protocol Parsing", {"Text": "x"}, mode="Script", script="def parse(:").status == ToolStatus.ERROR
    slow = run("Protocol Parsing", {"Text": "x"}, mode="Script", script="def parse(text):\n    while True:\n        pass\n")
    assert slow.status == ToolStatus.ERROR and "too long" in slow.message
    assert run("Protocol Assembly", {"Values": [1]}, mode="Script", script="def assemble(v):\n    raise ValueError('no')\n").status == ToolStatus.ERROR


@pytest.mark.parametrize("name", ["Condition Detection", "Save Text", "Format Module", "String Comparison", "Point Set", "Time Consuming", "Data Set", "Graphic Collection",
                                  "Send Data", "Receive Data", "Protocol Parsing", "Protocol Assembly"])
def test_every_module_survives_junk(name, tmp_path):
    for ctx in ({}, {"Text": 5, "Value": "x", "Data": object(), "Image": "x"}, {"Points": [[1]], "Rects": 5, "Values": [None], "Data1": object()},
                {"Text": None, "global": 5, "Trigger": "abc"}):
        t = create_tool_instance(name, "t")
        if name == "Save Text":
            t.set_param("save_dir", str(tmp_path))
        r = t.execute(ctx)
        assert r.status in (ToolStatus.OK, ToolStatus.NG, ToolStatus.ERROR) and r.message is not None
