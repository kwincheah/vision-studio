"""The API surface the first suite did not cover: CORS, image-root, limits, sub-flows, concurrency."""
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SAMPLE = os.path.join(ROOT, "apex_vision", "samples", "pcb_sample.png")
results = []


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    print("  %s %s%s" % ("ok  " if ok else "FAIL", name, (": " + detail) if detail else ""))


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def call(url, method="GET", body=None, headers=None, timeout=120):
    req = urllib.request.Request(url, data=body, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def jbody(raw):
    try: return json.loads(raw.decode("utf-8"))
    except Exception: return {}


def err_code(doc):
    return ((doc or {}).get("error") or {}).get("code")


def start(flows_dir, extra=()):
    port = free_port()
    cmd = [sys.executable, os.path.join(ROOT, "main.py"), "serve", "--flows", flows_dir,
           "--port", str(port), *extra]
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, text=True)
    base = "http://127.0.0.1:%d" % port
    for _ in range(160):
        if proc.poll() is not None:
            return proc, base, False
        try:
            if call(base + "/v1/health", timeout=2)[0] == 200:
                return proc, base, True
        except Exception:
            pass
        time.sleep(0.25)
    return proc, base, False


def stop(proc):
    try:
        proc.terminate(); proc.wait(timeout=10)
    except Exception:
        proc.kill()


png = open(SAMPLE, "rb").read()
flows_dir = os.path.join(ROOT, "projects")

# ------------------------------------------------------------------ CORS
print("CORS")
proc, base, up = start(flows_dir, ["--cors-origin", "http://localhost:3000"])
if not up:
    record("server starts with --cors-origin", False)
else:
    try:
        c, h, _b = call(base + "/v1/health", headers={"Origin": "http://localhost:3000"})
        allow = {k.lower(): v for k, v in h.items()}.get("access-control-allow-origin")
        record("an allowed origin gets Access-Control-Allow-Origin", allow == "http://localhost:3000",
               str(allow))
        c, h, _b = call(base + "/v1/flows/PCB_Inspection_Demo/run", method="OPTIONS",
                        headers={"Origin": "http://localhost:3000",
                                 "Access-Control-Request-Method": "POST"})
        record("preflight OPTIONS is answered", c in (200, 204), str(c))
        c, h, _b = call(base + "/v1/health", headers={"Origin": "http://evil.example"})
        allow = {k.lower(): v for k, v in h.items()}.get("access-control-allow-origin")
        record("an unlisted origin is not granted access", allow in (None, ""), str(allow))
    finally:
        stop(proc)

# ------------------------------------------------------------------ image root
print("\n--image-root")
img_dir = tempfile.mkdtemp(prefix="apex_imgroot_")
shutil.copy(SAMPLE, os.path.join(img_dir, "board.png"))
secret_dir = tempfile.mkdtemp(prefix="apex_secret_")
shutil.copy(SAMPLE, os.path.join(secret_dir, "secret.png"))
proc, base, up = start(flows_dir, ["--image-root", img_dir])
if not up:
    record("server starts with --image-root", False)
else:
    try:
        payload = json.dumps({"image_path": "board.png"}).encode()
        c, _h, b = call(base + "/v1/flows/PCB_Inspection_Demo/run", method="POST", body=payload,
                        headers={"Content-Type": "application/json"})
        record("image_path inside the root runs", c == 200, "%d %s" % (c, err_code(jbody(b))))
        payload = json.dumps({"image_path": "missing.png"}).encode()
        c, _h, b = call(base + "/v1/flows/PCB_Inspection_Demo/run", method="POST", body=payload,
                        headers={"Content-Type": "application/json"})
        record("a missing image_path is 404 image_not_found",
               c == 404 and err_code(jbody(b)) == "image_not_found", "%d %s" % (c, err_code(jbody(b))))
        escape = os.path.join(secret_dir, "secret.png")
        payload = json.dumps({"image_path": escape}).encode()
        c, _h, b = call(base + "/v1/flows/PCB_Inspection_Demo/run", method="POST", body=payload,
                        headers={"Content-Type": "application/json"})
        record("a path outside the root is 403 image_path_outside_root",
               c == 403 and err_code(jbody(b)) == "image_path_outside_root",
               "%d %s" % (c, err_code(jbody(b))))
        payload = json.dumps({"image_path": "../" * 6 + "Windows/win.ini"}).encode()
        c, _h, b = call(base + "/v1/flows/PCB_Inspection_Demo/run", method="POST", body=payload,
                        headers={"Content-Type": "application/json"})
        record("a traversal attempt is refused", c == 403, "%d %s" % (c, err_code(jbody(b))))
    finally:
        stop(proc)
    shutil.rmtree(img_dir, ignore_errors=True); shutil.rmtree(secret_dir, ignore_errors=True)

# ------------------------------------------------------------------ size limit
print("\nsize limits")
proc, base, up = start(flows_dir, ["--max-image-mb", "1"])
if not up:
    record("server starts with --max-image-mb", False)
else:
    try:
        import numpy as np, cv2
        rng = np.random.default_rng(7)
        # a realistic overshoot: over the 1 MB image cap, under the request cap
        mid = cv2.imencode(".png", rng.integers(0, 256, (620, 620, 3), dtype=np.uint8))[1].tobytes()
        record("(test image is over the 1 MB cap)", len(mid) > 1024 * 1024, "%d bytes" % len(mid))
        c, _h, b = call(base + "/v1/flows/PCB_Inspection_Demo/run", method="POST", body=mid,
                        headers={"Content-Type": "image/png"})
        record("an oversized image is 413 image_too_large",
               c == 413 and err_code(jbody(b)) == "image_too_large",
               "%d %s" % (c, err_code(jbody(b))))

        # far beyond the limit: the server refuses on Content-Length before reading, so a
        # client still writing the body may see the connection close.  curl reports the
        # status that was actually sent.
        big = cv2.imencode(".png", rng.integers(0, 256, (1400, 1400, 3), dtype=np.uint8))[1].tobytes()
        tmp = os.path.join(tempfile.gettempdir(), "apex_big.png")
        open(tmp, "wb").write(big)
        try:
            out = subprocess.run(["curl.exe", "-s", "-o", os.devnull, "-w", "%{http_code}",
                                  "--max-time", "90", "-X", "POST",
                                  "-H", "Content-Type: image/png", "--data-binary", "@" + tmp,
                                  base + "/v1/flows/PCB_Inspection_Demo/run"],
                                 capture_output=True, text=True, timeout=120).stdout.strip()
        finally:
            os.remove(tmp)
        record("a body far over the cap is 413 request_too_large", out == "413", "HTTP %s" % out)
    finally:
        stop(proc)

# ------------------------------------------------------------------ sub-flows
print("\nsub-flow selection")
multi_dir = tempfile.mkdtemp(prefix="apex_multi_")
try:
    from apex_vision.core.project_manager import ProjectManager
    demo = os.path.join(flows_dir, "PCB_Inspection_Demo.apex")
    sol = ProjectManager().load_project(demo)
    flow2 = sol.add_flow("Second_Flow")
    # an empty flow has no Image Source, so an image would be refused with 422 - give it one
    from apex_vision.core.registry import create_tool_instance
    flow2.add_node(create_tool_instance("Image Source", "src_second", "01_Acquisition"))
    target = os.path.join(multi_dir, "Multi_Demo.apex")
    ProjectManager().save_project(sol, target)
    proc, base, up = start(multi_dir)
    if not up:
        record("server starts on a multi-flow solution", False)
    else:
        try:
            c, _h, b = call(base + "/v1/flows/Multi_Demo")
            doc = jbody(b)
            names = [f["name"] for f in doc.get("flows") or []]
            record("both flows are listed", len(names) >= 2, str(names))
            c, _h, b = call(base + "/v1/flows/Multi_Demo/run?flow=Second_Flow", method="POST",
                            body=png, headers={"Content-Type": "image/png"})
            doc = jbody(b)
            record("?flow= selects the named flow",
                   c == 200 and doc.get("flow_name") == "Second_Flow",
                   "%d flow_name=%s" % (c, doc.get("flow_name")))
            c, _h, b = call(base + "/v1/flows/Multi_Demo/run?flow=NoSuchFlow", method="POST",
                            body=png, headers={"Content-Type": "image/png"})
            record("an unknown sub-flow is 404 flow_not_found",
                   c == 404 and err_code(jbody(b)) == "flow_not_found",
                   "%d %s" % (c, err_code(jbody(b))))
            c, _h, b = call(base + "/v1/flows/Multi_Demo/run", method="POST", body=png,
                            headers={"Content-Type": "image/png"})
            record("no ?flow= uses the default flow", c == 200 and bool(jbody(b).get("flow_name")),
                   str(jbody(b).get("flow_name")))
        finally:
            stop(proc)
finally:
    shutil.rmtree(multi_dir, ignore_errors=True)

# ------------------------------------------------------------------ unreadable flow
print("\nunreadable flow")
bad_dir = tempfile.mkdtemp(prefix="apex_bad_")
try:
    open(os.path.join(bad_dir, "Broken.apex"), "w", encoding="utf-8").write("<not-a-flow")
    proc, base, up = start(bad_dir)
    if not up:
        record("server starts on a folder with a broken flow", False)
    else:
        try:
            c, _h, b = call(base + "/v1/flows/Broken/run", method="POST", body=png,
                            headers={"Content-Type": "image/png"})
            record("a corrupt flow is 422 flow_unreadable",
                   c == 422 and err_code(jbody(b)) == "flow_unreadable",
                   "%d %s" % (c, err_code(jbody(b))))
        finally:
            stop(proc)
finally:
    shutil.rmtree(bad_dir, ignore_errors=True)

# ------------------------------------------------------------------ concurrency
print("\nconcurrency")
proc, base, up = start(flows_dir)
if not up:
    record("server starts for the concurrency test", False)
else:
    try:
        outcomes = []
        def hit(i):
            c, _h, b = call(base + "/v1/flows/PCB_Inspection_Demo/run", method="POST", body=png,
                            headers={"Content-Type": "image/png"})
            outcomes.append((i, c, err_code(jbody(b))))
        threads = [threading.Thread(target=hit, args=(i,)) for i in range(4)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=180)
        codes = sorted(c for _i, c, _e in outcomes)
        record("four concurrent runs all answer", len(outcomes) == 4, str(codes))
        record("none of them crashes the server (no 500)",
               all(c != 500 for _i, c, _e in outcomes),
               str([(c, e) for _i, c, e in outcomes]))
        record("the server is still healthy afterwards",
               call(base + "/v1/health")[0] == 200, "")
    finally:
        stop(proc)

print()
passed = sum(1 for _n, ok, _d in results if ok)
print("=" * 64)
print("%d/%d passed" % (passed, len(results)))
for n, ok, d in results:
    if not ok:
        print("  FAILED: %s (%s)" % (n, d))
sys.exit(0 if passed == len(results) else 1)
