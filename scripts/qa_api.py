"""Exercise the documented HTTP API against a live server."""
import base64
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "apex_vision", "samples", "pcb_sample.png")
results = []


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    print("  %s %s%s" % ("ok  " if ok else "FAIL", name, (": " + detail) if detail else ""))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def call(url, method="GET", body=None, headers=None, timeout=60):
    req = urllib.request.Request(url, data=body, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def start(extra=()):
    port = free_port()
    cmd = [sys.executable, os.path.join(ROOT, "main.py"), "serve",
           "--flows", os.path.join(ROOT, "projects"), "--port", str(port), *extra]
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    base = "http://127.0.0.1:%d" % port
    for _ in range(120):
        if proc.poll() is not None:
            return proc, base, False
        try:
            code, _h, _b = call(base + "/v1/health", timeout=2)
            if code == 200:
                return proc, base, True
        except Exception:
            pass
        time.sleep(0.25)
    return proc, base, False


def stop(proc):
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        proc.kill()


def jbody(raw):
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def err_code(doc):
    return ((doc or {}).get("error") or {}).get("code")


png = open(SAMPLE, "rb").read()
print("sample image: %d bytes" % len(png))

proc, base, up = start()
if not up:
    print("FATAL: server did not start")
    print((proc.stdout.read() or "")[:800] if proc.stdout else "")
    sys.exit(2)
print("server up at", base, "\n")

try:
    # ---------------------------------------------------------------- health
    print("health and discovery")
    c, h, b = call(base + "/v1/health")
    doc = jbody(b)
    record("GET /v1/health returns 200", c == 200, str(c))
    record("health reports status ok", doc.get("status") == "ok", str(doc)[:60])
    record("health reports a version", bool(doc.get("version")), str(doc.get("version")))

    c, h, b = call(base + "/v1/flows")
    doc = jbody(b)
    names = [f.get("name") if isinstance(f, dict) else f for f in (doc if isinstance(doc, list) else doc.get("flows", []))]
    record("GET /v1/flows lists the folder", c == 200 and len(names) >= 1, str(names)[:90])
    record("the demo flow is listed", any("PCB_Inspection" in str(n) for n in names), str(names)[:90])

    flow = next(n for n in names if "PCB_Inspection" in str(n))
    c, h, b = call(base + "/v1/flows/" + urllib.parse.quote(str(flow)))
    doc = jbody(b)
    sub = (doc.get("flows") or [{}])[0]
    mods = sub.get("modules") or []
    record("GET /v1/flows/{name} returns modules", c == 200 and len(mods) >= 1,
           "%d module(s) in flow %r" % (len(mods), sub.get("name")))
    with_params = [m for m in mods if m.get("parameters")]
    record("modules expose changeable parameters with limits",
           bool(with_params), "%d of %d modules" % (len(with_params), len(mods)))
    limits = [k for m in with_params for k, sp in m["parameters"].items()
              if isinstance(sp, dict) and sp.get("min") is not None]
    record("numeric parameters carry their limits", bool(limits),
           "%d parameter(s) with min/max, e.g. %s" % (len(limits), limits[:3]))

    # ---------------------------------------------------------------- run
    print("\nrunning a flow")
    c, h, b = call(base + "/v1/flows/%s/run" % urllib.parse.quote(str(flow)),
                   method="POST", body=png, headers={"Content-Type": "image/png"})
    doc = jbody(b)
    record("POST run with a raw PNG returns 200", c == 200, "%d %s" % (c, err_code(doc)))
    record("a verdict comes back", doc.get("verdict") in ("PASS", "FAIL"), str(doc.get("verdict")))
    record("modules are reported", isinstance(doc.get("modules"), list) and doc["modules"],
           "%d module(s)" % len(doc.get("modules") or []))
    record("elapsed_ms is a number", isinstance(doc.get("elapsed_ms"), (int, float)),
           str(doc.get("elapsed_ms")))
    record("failed_modules agrees with the verdict",
           (doc.get("verdict") == "PASS") == (not doc.get("failed_modules")),
           "%s / %s" % (doc.get("verdict"), doc.get("failed_modules")))

    # annotated image
    c, h, b = call(base + "/v1/flows/%s/run?return_image=1" % urllib.parse.quote(str(flow)),
                   method="POST", body=png, headers={"Content-Type": "image/png"})
    doc = jbody(b)
    if c == 200 and doc.get("image_base64"):
        raw = base64.b64decode(doc["image_base64"])
        record("return_image=1 returns a PNG", raw[:8] == b"\x89PNG\r\n\x1a\n",
               "%d bytes" % len(raw))
    else:
        record("return_image=1 returns an annotated image", False,
               "%d %s" % (c, str(doc)[:80]))

    # JSON body with base64 and data URI
    payload = json.dumps({"image_base64": base64.b64encode(png).decode()}).encode()
    c, h, b = call(base + "/v1/flows/%s/run" % urllib.parse.quote(str(flow)),
                   method="POST", body=payload, headers={"Content-Type": "application/json"})
    record("JSON body with image_base64 works", c == 200 and jbody(b).get("verdict") in ("PASS", "FAIL"),
           "%d" % c)
    payload = json.dumps({"image_base64": "data:image/png;base64," + base64.b64encode(png).decode()}).encode()
    c, h, b = call(base + "/v1/flows/%s/run" % urllib.parse.quote(str(flow)),
                   method="POST", body=payload, headers={"Content-Type": "application/json"})
    record("a data: URI is accepted", c == 200, "%d %s" % (c, err_code(jbody(b))))

    # no image at all: the flow's own source
    c, h, b = call(base + "/v1/flows/%s/run" % urllib.parse.quote(str(flow)),
                   method="POST", body=b"", headers={"Content-Type": "image/png"})
    record("no image runs on the flow's own source", c == 200, "%d %s" % (c, err_code(jbody(b))))

    # ---------------------------------------------------------------- params
    print("\nparameter overrides")
    flow_file = os.path.join(ROOT, "projects", str(flow))
    if not flow_file.endswith(".apex"):
        flow_file += ".apex"
    before = hashlib.sha256(open(flow_file, "rb").read()).hexdigest()

    target = None
    for m in with_params:
        for k, sp in (m.get("parameters") or {}).items():
            if isinstance(sp, dict) and sp.get("kind") in ("int", "float") \
                    and sp.get("min") is not None and sp.get("max") is not None:
                target = (m, dict(sp, key=k))
                break
        if target:
            break
    if target:
        m, p = target
        val = p.get("max") if p.get("max") is not None else 1
        key = "%s.%s" % ((m.get("name") or m.get("id")), p.get("key"))
        params = {str(m.get("name") or m.get("id")): {p["key"]: val}}
        url = base + "/v1/flows/%s/run?params=%s" % (
            urllib.parse.quote(str(flow)), urllib.parse.quote(json.dumps(params)))
        c, h, b = call(url, method="POST", body=png, headers={"Content-Type": "image/png"})
        record("a legal parameter override runs", c == 200, "%s <- %s" % (key, val))

        bad = {str(m.get("name") or m.get("id")): {p["key"]: (p.get("max") or 0) + 10 ** 6}}
        url = base + "/v1/flows/%s/run?params=%s" % (
            urllib.parse.quote(str(flow)), urllib.parse.quote(json.dumps(bad)))
        c, h, b = call(url, method="POST", body=png, headers={"Content-Type": "image/png"})
        doc = jbody(b)
        record("an out-of-range value is 422 invalid_params",
               c == 422 and err_code(doc) == "invalid_params", "%d %s" % (c, err_code(doc)))
        record("the 422 names the offending parameter",
               p["key"] in json.dumps(doc), str(doc)[:100])

    c, h, b = call(base + "/v1/flows/%s/run?params=%s" % (
        urllib.parse.quote(str(flow)), urllib.parse.quote(json.dumps({"NoSuchModule": {"x": 1}}))),
        method="POST", body=png, headers={"Content-Type": "image/png"})
    record("an unknown module is 422 unknown_module",
           c == 422 and err_code(jbody(b)) == "unknown_module", "%d %s" % (c, err_code(jbody(b))))

    after = hashlib.sha256(open(flow_file, "rb").read()).hexdigest()
    record("the saved flow is not modified by an override", before == after,
           "hash unchanged" if before == after else "FILE CHANGED")

    # ---------------------------------------------------------------- errors
    print("\nerror handling")
    c, h, b = call(base + "/v1/flows/NoSuchFlow/run", method="POST", body=png,
                   headers={"Content-Type": "image/png"})
    record("unknown flow is 404 flow_not_found",
           c == 404 and err_code(jbody(b)) == "flow_not_found", "%d %s" % (c, err_code(jbody(b))))

    c, h, b = call(base + "/v1/flows/%s/run" % urllib.parse.quote(str(flow)),
                   method="POST", body=b"not an image", headers={"Content-Type": "image/png"})
    record("garbage bytes are 400 bad_image",
           c == 400 and err_code(jbody(b)) == "bad_image", "%d %s" % (c, err_code(jbody(b))))

    c, h, b = call(base + "/v1/flows/%s/run" % urllib.parse.quote(str(flow)),
                   method="POST", body=json.dumps({"image_base64": "!!!not base64!!!"}).encode(),
                   headers={"Content-Type": "application/json"})
    record("bad base64 is 400 bad_image or bad_json",
           c == 400 and err_code(jbody(b)) in ("bad_image", "bad_json"),
           "%d %s" % (c, err_code(jbody(b))))

    c, h, b = call(base + "/v1/flows/%s/run" % urllib.parse.quote(str(flow)),
                   method="POST", body=png, headers={"Content-Type": "text/plain"})
    record("an unsupported content type is 415",
           c == 415 and err_code(jbody(b)) == "unsupported_media_type",
           "%d %s" % (c, err_code(jbody(b))))

    c, h, b = call(base + "/v1/flows/%s/run" % urllib.parse.quote(str(flow)), method="GET")
    record("GET on run is 405 not_allowed",
           c == 405 and err_code(jbody(b)) == "not_allowed", "%d %s" % (c, err_code(jbody(b))))

    c, h, b = call(base + "/v1/flows/%s/run" % urllib.parse.quote(str(flow)),
                   method="POST", body=json.dumps({"image_path": "x.png"}).encode(),
                   headers={"Content-Type": "application/json"})
    record("image_path without --image-root is 403 image_path_disabled",
           c == 403 and err_code(jbody(b)) == "image_path_disabled",
           "%d %s" % (c, err_code(jbody(b))))

    c, h, b = call(base + "/v1/nope")
    record("an unknown path is 404", c == 404, str(c))
finally:
    stop(proc)

# -------------------------------------------------------------------- api key
print("\nAPI key mode")
proc, base, up = start(["--api-key", "sekret"])
if not up:
    record("server starts with --api-key", False, "did not start")
else:
    try:
        c, _h, _b = call(base + "/v1/health")
        record("health never needs the key", c == 200, str(c))
        c, _h, b = call(base + "/v1/flows")
        record("flows without a key is 401", c == 401 and err_code(jbody(b)) == "unauthorized",
               "%d %s" % (c, err_code(jbody(b))))
        c, _h, _b = call(base + "/v1/flows", headers={"X-API-Key": "wrong"})
        record("a wrong key is 401", c == 401, str(c))
        c, _h, _b = call(base + "/v1/flows", headers={"X-API-Key": "sekret"})
        record("X-API-Key is accepted", c == 200, str(c))
        c, _h, _b = call(base + "/v1/flows", headers={"Authorization": "Bearer sekret"})
        record("Authorization: Bearer is accepted", c == 200, str(c))
    finally:
        stop(proc)

# -------------------------------------------------------------------- guards
print("\nstart-up guards")
env = dict(os.environ)
env.pop("APEX_API_KEY", None)
r = subprocess.run([sys.executable, os.path.join(ROOT, "main.py"), "serve",
                    "--host", "0.0.0.0", "--port", str(free_port())],
                   cwd=ROOT, capture_output=True, text=True, timeout=60, env=env)
out = (r.stdout or "") + (r.stderr or "")
record("listening beyond loopback without a key is refused",
       r.returncode != 0 and ("key" in out.lower()),
       "exit %d" % r.returncode)

print()
passed = sum(1 for _n, ok, _d in results if ok)
print("=" * 64)
print("%d/%d passed" % (passed, len(results)))
for n, ok, d in results:
    if not ok:
        print("  FAILED: %s (%s)" % (n, d))
sys.exit(0 if passed == len(results) else 1)
