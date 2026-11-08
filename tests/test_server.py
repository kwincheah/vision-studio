"""The local HTTP API: other programs run saved flows on images they send."""
import base64
import json
import os
import shutil
import threading
import urllib.error
import urllib.request

import pytest

from apex_vision.server import make_server

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEMO = "Precision_Measurement_Demo"
SAMPLE = os.path.join(ROOT, "apex_vision", "samples", "pcb_sample.png")


@pytest.fixture()
def flows(tmp_path):
    folder = tmp_path / "flows"
    folder.mkdir()
    shutil.copy(os.path.join(ROOT, "projects", f"{DEMO}.apex"), folder)
    shutil.copy(os.path.join(ROOT, "projects", "PCB_Inspection_Demo.apex"), folder)
    return str(folder)


def start(flows, **kw):
    server = make_server(flows, port=0, **kw)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1"


@pytest.fixture()
def api(flows):
    server, base = start(flows)
    yield base
    server.shutdown()
    server.server_close()


def call(url, method="GET", body=None, ctype=None, headers=None):
    req = urllib.request.Request(url, data=body, method=method, headers=dict(headers or {}))
    if ctype:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), dict(e.headers)


def post_json(url, payload, headers=None):
    return call(url, "POST", json.dumps(payload).encode(), "application/json", headers)


def test_health_and_flow_listing(api):
    status, body, _ = call(f"{api}/health")
    assert status == 200 and body["status"] == "ok" and body["version"]
    status, body, _ = call(f"{api}/flows")
    names = {f["name"] for f in body["flows"]}
    assert status == 200 and {DEMO, "PCB_Inspection_Demo"} <= names


def test_describe_lists_only_parameters_a_caller_may_change(api):
    status, body, _ = call(f"{api}/flows/{DEMO}")
    assert status == 200 and body["flows"][0]["accepts_image"] is True
    modules = {m["name"]: m for m in body["flows"][0]["modules"]}
    light = modules["04_IlluminationCheck"]["parameters"]
    assert light["min_mean"]["kind"] in ("int", "float") and "min" in light["min_mean"]
    source = modules["01_Acquisition"]["parameters"]
    assert "file_path" not in source, "path parameters are never exposed"


def test_run_without_an_image_uses_the_flows_own_source(api):
    status, body, _ = call(f"{api}/flows/{DEMO}/run", "POST")
    assert status == 200 and body["verdict"] in ("PASS", "FAIL")
    assert body["passed"] == (body["verdict"] == "PASS")
    assert [m["name"] for m in body["modules"]] and all("status" in m for m in body["modules"])
    json.dumps(body)                                     # fully JSON-serialisable


def test_run_with_an_uploaded_png_and_an_overlay_image(api):
    data = open(SAMPLE, "rb").read()
    status, body, _ = call(f"{api}/flows/{DEMO}/run?return_image=1", "POST", data, "image/png")
    assert status == 200
    png = base64.b64decode(body["image_base64"])
    assert png.startswith(b"\x89PNG")
    assert body["modules"][0]["message"].endswith("from API image"), "the uploaded image, not the flow's own source, was used"


def test_run_with_base64_json_and_a_data_uri(api):
    b64 = base64.b64encode(open(SAMPLE, "rb").read()).decode()
    for value in (b64, "data:image/png;base64," + b64):
        status, body, _ = post_json(f"{api}/flows/{DEMO}/run", {"image_base64": value})
        assert status == 200 and "verdict" in body


def test_parameter_overrides_change_the_verdict_and_are_validated(api):
    brightness = {"04_IlluminationCheck": {"min_mean": 250, "max_mean": 255}}
    status, body, _ = post_json(f"{api}/flows/{DEMO}/run", {"params": brightness})
    assert status == 200 and body["verdict"] == "FAIL" and "04_IlluminationCheck" in body["failed_modules"]
    ok = {"04_IlluminationCheck": {"min_mean": 0, "max_mean": 255}}
    assert post_json(f"{api}/flows/{DEMO}/run", {"params": ok})[1]["verdict"] == "PASS"


@pytest.mark.parametrize("params, fragment", [
    ({"04_IlluminationCheck": {"min_mean": -5}}, "at least"),                      # out of range
    ({"04_IlluminationCheck": {"min_mean": "high"}}, "number"),                    # wrong type
    ({"04_IlluminationCheck": {"nonsense": 1}}, "no such parameter"),
    ({"01_Acquisition": {"file_path": "C:/Windows/win.ini"}}, "cannot be changed"),  # path parameters are locked
    ({"missing_module": {"a": 1}}, "no module"),
    ([1, 2], "params must look like"),
])
def test_bad_overrides_are_rejected_before_anything_runs(api, params, fragment):
    status, body, _ = post_json(f"{api}/flows/{DEMO}/run", {"params": params})
    assert status in (400, 422) and fragment in body["error"]["message"]


def test_script_modules_cannot_be_changed_through_the_api(flows):
    from apex_vision.core.pipeline import SolutionManager
    from apex_vision.core.registry import create_tool_instance
    sol = SolutionManager.load_from_file(os.path.join(flows, f"{DEMO}.apex"))
    flow = sol.get_active_flow()
    flow.add_node(create_tool_instance("Script", "node_script", "Script"))
    sol.save_to_file(os.path.join(flows, "WithScript.apex"))
    server, base = start(flows)
    try:
        status, body, _ = post_json(f"{base}/flows/WithScript/run", {"params": {"Script": {"code": "import os"}}})
        assert status == 422 and "cannot be changed" in body["error"]["message"]
        described = call(f"{base}/flows/WithScript")[1]
        script = next(m for m in described["flows"][0]["modules"] if m["tool"] == "Script")
        assert script["parameters"] == {}
    finally:
        server.shutdown()
        server.server_close()


def test_error_responses(api):
    assert call(f"{api}/flows/nope/run", "POST")[0] == 404
    assert call(f"{api}/flows/..%2F..%2Fsecret/run", "POST")[0] == 404
    assert call(f"{api}/flows/{DEMO}/run", "POST", b"not an image", "image/png")[0] == 400
    assert call(f"{api}/flows/{DEMO}/run", "POST", b"{bad", "application/json")[0] == 400
    assert call(f"{api}/flows/{DEMO}/run", "POST", b"x", "text/plain")[0] == 415
    assert call(f"{api}/elsewhere")[0] == 404
    assert call(f"{api}/flows/{DEMO}/run")[0] == 405          # GET on a POST address
    status, body, _ = call(f"{api}/flows/{DEMO}/run?params=not-json", "POST")
    assert status == 400 and body["error"]["code"] == "bad_params"


def test_flow_without_an_image_source_rejects_an_image(flows):
    from apex_vision.core.pipeline import SolutionManager
    sol = SolutionManager.load_from_file(os.path.join(flows, f"{DEMO}.apex"))
    flow = sol.get_active_flow()
    for cid in [c for c in flow.connections if c.from_node == "node_source"]:
        flow.connections.remove(cid)
    flow.remove_node("node_source")
    sol.save_to_file(os.path.join(flows, "NoSource.apex"))
    server, base = start(flows)
    try:
        status, body, _ = call(f"{base}/flows/NoSource/run", "POST", open(SAMPLE, "rb").read(), "image/png")
        assert status == 422 and body["error"]["code"] == "no_image_source"
    finally:
        server.shutdown()
        server.server_close()


def test_oversized_uploads_are_refused(flows):
    server, base = start(flows, max_image_mb=0.001)           # about 1 KB
    try:
        status, body, _ = call(f"{base}/flows/{DEMO}/run", "POST", open(SAMPLE, "rb").read(), "image/png")
        assert status == 413
    finally:
        server.shutdown()
        server.server_close()


def test_api_key_is_enforced_but_health_stays_open(flows):
    server, base = start(flows, api_key="s3cret")
    try:
        assert call(f"{base}/health")[0] == 200
        assert call(f"{base}/flows")[0] == 401
        assert call(f"{base}/flows", headers={"Authorization": "Bearer wrong"})[0] == 401
        assert call(f"{base}/flows", headers={"Authorization": "Bearer s3cret"})[0] == 200
        assert call(f"{base}/flows", headers={"X-API-Key": "s3cret"})[0] == 200
        assert call(f"{base}/flows/{DEMO}/run", "POST")[0] == 401
    finally:
        server.shutdown()
        server.server_close()


def test_refuses_to_listen_beyond_this_computer_without_a_key(flows):
    with pytest.raises(ValueError, match="API key"):
        make_server(flows, host="0.0.0.0", port=0)
    make_server(flows, host="0.0.0.0", port=0, api_key="k").server_close()
    with pytest.raises(ValueError, match="not found"):
        make_server(os.path.join(flows, "missing"), port=0)


def test_image_path_is_off_unless_an_image_root_is_given_and_stays_inside_it(flows, tmp_path):
    server, base = start(flows)
    try:
        status, body, _ = post_json(f"{base}/flows/{DEMO}/run", {"image_path": SAMPLE})
        assert status == 403 and body["error"]["code"] == "image_path_disabled"
    finally:
        server.shutdown()
        server.server_close()
    root = tmp_path / "images"
    root.mkdir()
    shutil.copy(SAMPLE, root / "board.png")
    outside = tmp_path / "outside.png"
    shutil.copy(SAMPLE, outside)
    server, base = start(flows, image_root=str(root))
    try:
        assert post_json(f"{base}/flows/{DEMO}/run", {"image_path": "board.png"})[0] == 200
        assert post_json(f"{base}/flows/{DEMO}/run", {"image_path": str(root / "board.png")})[0] == 200
        assert post_json(f"{base}/flows/{DEMO}/run", {"image_path": str(outside)})[0] == 403
        assert post_json(f"{base}/flows/{DEMO}/run", {"image_path": "../outside.png"})[0] == 403
        assert post_json(f"{base}/flows/{DEMO}/run", {"image_path": "missing.png"})[0] == 404
        assert post_json(f"{base}/flows/{DEMO}/run", {"image_path": str(root / "board.png") + ".txt"})[0] == 404
    finally:
        server.shutdown()
        server.server_close()


def test_cors_is_off_by_default_and_opt_in(flows):
    server, base = start(flows)
    try:
        _, _, headers = call(f"{base}/health", headers={"Origin": "http://app.example"})
        assert "Access-Control-Allow-Origin" not in headers
    finally:
        server.shutdown()
        server.server_close()
    server, base = start(flows, cors_origins=["http://localhost:3000"])
    try:
        _, _, headers = call(f"{base}/health", headers={"Origin": "http://localhost:3000"})
        assert headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"
        _, _, headers = call(f"{base}/health", headers={"Origin": "http://evil.example"})
        assert "Access-Control-Allow-Origin" not in headers
        status, _, headers = call(f"{base}/flows", "OPTIONS", headers={"Origin": "http://localhost:3000"})
        assert status == 204 and "Authorization" in headers.get("Access-Control-Allow-Headers", "")
    finally:
        server.shutdown()
        server.server_close()


def test_concurrent_requests_are_all_served(api):
    results = []

    def one():
        results.append(call(f"{api}/flows/{DEMO}/run", "POST")[0])

    threads = [threading.Thread(target=one) for _ in range(6)]
    [t.start() for t in threads]
    [t.join(60) for t in threads]
    assert results == [200] * 6


def test_the_samples_on_disk_are_not_modified_by_running_them(api, flows):
    path = os.path.join(flows, f"{DEMO}.apex")
    before = open(path, "rb").read()
    call(f"{api}/flows/{DEMO}/run", "POST")
    assert open(path, "rb").read() == before


def test_command_line_entry_point_serves_and_validates(monkeypatch, flows):
    from apex_vision import cli
    assert cli.main(["serve", "--flows", flows, "--host", "0.0.0.0", "--port", "0"]) == 2   # no key: refused
    assert cli.main(["serve", "--flows", os.path.join(flows, "missing"), "--port", "0"]) == 2
