"""Local HTTP API: run saved flows on images sent by another program.

Start it with ``python main.py serve --flows <folder>``.  Every flow file in the folder
(``.apex``, ``.xml``, ``.vmp``, ``.sol``, ``.json``) becomes callable by its file name::

    GET  /v1/health
    GET  /v1/flows                    which flows exist
    GET  /v1/flows/{name}             its modules and the parameters a caller may change
    POST /v1/flows/{name}/run         run it on an image, get PASS/FAIL and every module's outputs

The server runs the very same engine as the window (``VisionPipeline.execute_flow``), so a
result obtained over HTTP is the result the interface would show.  It uses only the Python
standard library.

Safety model
------------
* It listens on ``127.0.0.1`` unless told otherwise, and refuses to listen on any other address
  without an API key.
* Callers can only run flows that already sit in the flows folder.  They cannot upload a flow
  file, because a flow can contain a Script module, which runs Python.
* A caller may change a module's *numeric / on-off / choice* parameters for one request.  Text,
  file-path and code parameters can never be overridden, and every value is checked against the
  parameter's declared range before the flow runs.
* ``image_path`` (reading an image from the server's disk) works only inside ``--image-root``.
* Request size, image size and the time spent waiting for the engine are all limited.
"""
from __future__ import annotations

import base64
import binascii
import hmac
import json
import logging
import math
import os
import re
import threading
import time
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import cv2
import numpy as np

import apex_vision.tools  # noqa: F401  (registers the built-in modules)
from apex_vision.core import param_schema
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.imageio import imread
from apex_vision.core.overlays import render_overlays
from apex_vision.core.pipeline import SolutionManager
from apex_vision.version import DISPLAY as APP_VERSION

LOG = logging.getLogger("apex_vision.server")

API_PREFIX = "/v1"
FLOW_EXTENSIONS = (".apex", ".xml", ".vmp", ".sol", ".json")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")
LOOPBACK_HOSTS = ("127.0.0.1", "localhost")
#: parameter kinds a caller may change; text, path, directory, code, device and free JSON never.
OVERRIDABLE_KINDS = ("bool", "int", "float", "enum", "rect", "line", "point", "rgb", "points")
#: modules whose parameters a caller may never change, whatever their kind.
LOCKED_TOOLS = ("Script",)
FAILING_STATUSES = (ToolStatus.NG, ToolStatus.ERROR, ToolStatus.TIMEOUT)


class ApiError(Exception):
    """An error the client should see, with its HTTP status and a stable machine-readable code."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# JSON conversion
# ---------------------------------------------------------------------------
def to_jsonable(value: Any, depth: int = 0) -> Any:
    """Make a module output JSON-safe. Large arrays (images) become a short description."""
    if depth > 8:
        return str(value)
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, np.generic):
        return to_jsonable(value.item(), depth)
    if isinstance(value, np.ndarray):
        if value.ndim >= 2 and value.size > 64:
            return {"_type": "image", "shape": list(value.shape), "dtype": str(value.dtype)}
        return to_jsonable(value.tolist(), depth + 1)
    if isinstance(value, Enum):
        return to_jsonable(value.value, depth)
    if isinstance(value, dict):
        return {str(k): to_jsonable(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v, depth + 1) for v in list(value)[:10000]]
    if hasattr(value, "to_dict"):
        try:
            return to_jsonable(value.to_dict(), depth + 1)
        except Exception:                                     # noqa: BLE001 - fall through to text
            pass
    return str(value)


# ---------------------------------------------------------------------------
# Flow service: everything except HTTP
# ---------------------------------------------------------------------------
class FlowService:
    def __init__(self, flows_dir: str, image_root: Optional[str] = None,
                 max_image_bytes: int = 50 * 1024 * 1024, max_pixels: int = 100_000_000,
                 queue_timeout: float = 120.0):
        self.flows_dir = os.path.abspath(flows_dir)
        self.image_root = os.path.realpath(image_root) if image_root else None
        self.max_image_bytes = max_image_bytes
        self.max_pixels = max_pixels
        self.queue_timeout = queue_timeout
        self._lock = threading.Lock()          # the engine runs one flow at a time

    # -- discovery -----------------------------------------------------------------
    def _scan(self) -> Dict[str, str]:
        """name -> file. The name is the file name without its extension; ``.apex`` wins a tie."""
        found: Dict[str, str] = {}
        if not os.path.isdir(self.flows_dir):
            return found
        for ext in reversed(FLOW_EXTENSIONS):     # later (preferred) extensions overwrite earlier ones
            for entry in sorted(os.listdir(self.flows_dir)):
                stem, e = os.path.splitext(entry)
                full = os.path.join(self.flows_dir, entry)
                if e.lower() == ext and os.path.isfile(full):
                    found[stem] = full
        return found

    def _path(self, name: str) -> str:
        path = self._scan().get(name)
        if path is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "flow_not_found", f"no flow named '{name}'")
        return path

    def _load(self, name: str) -> SolutionManager:
        path = self._path(name)
        try:
            return SolutionManager.load_from_file(path)
        except Exception as exc:                              # noqa: BLE001 - reported to the caller
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "flow_unreadable",
                           f"'{name}' could not be loaded: {exc}") from exc

    def list_flows(self) -> List[Dict[str, Any]]:
        out = []
        for name, path in sorted(self._scan().items()):
            entry: Dict[str, Any] = {"name": name, "file": os.path.basename(path),
                                     "modified": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(path)))}
            try:
                sol = SolutionManager.load_from_file(path)
                entry["flows"] = list(sol.flows)
                entry["default_flow"] = sol.get_active_flow().name if sol.flows else None
            except Exception as exc:                          # noqa: BLE001 - one bad file must not hide the rest
                entry["error"] = str(exc)
            out.append(entry)
        return out

    # -- description -----------------------------------------------------------------
    @staticmethod
    def _overridable(node) -> Dict[str, Dict[str, Any]]:
        if node.tool_name in LOCKED_TOOLS:
            return {}
        specs: Dict[str, Dict[str, Any]] = {}
        for key, current in node.parameters.items():
            spec = param_schema.spec_for(node.tool_name, key, current)
            if spec["kind"] not in OVERRIDABLE_KINDS:
                continue
            item: Dict[str, Any] = {"kind": spec["kind"], "value": to_jsonable(current)}
            for field in ("min", "max", "choices", "unit"):
                if field in spec:
                    item[field] = spec[field]
            specs[key] = item
        return specs

    def describe(self, name: str) -> Dict[str, Any]:
        sol = self._load(name)
        flows = []
        for flow in sol.flows.values():
            modules = []
            for node in flow.nodes.values():
                modules.append({
                    "id": node.instance_id, "name": node.name, "tool": node.tool_name, "enabled": node.enabled,
                    "inputs": list(node.inputs), "outputs": list(node.outputs),
                    "parameters": self._overridable(node),
                })
            flows.append({"name": flow.name, "modules": modules,
                          "accepts_image": any(n.tool_name == "Image Source" for n in flow.nodes.values())})
        return {"name": name, "default_flow": sol.get_active_flow().name if sol.flows else None, "flows": flows}

    # -- inputs ------------------------------------------------------------------------
    def decode_image(self, data: bytes) -> np.ndarray:
        if len(data) > self.max_image_bytes:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "image_too_large",
                           f"image is larger than {self.max_image_bytes // (1024 * 1024)} MB")
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ApiError(HTTPStatus.BAD_REQUEST, "bad_image", "the data is not a readable PNG, JPEG, BMP or TIFF image")
        return self._check_pixels(img)

    def read_image_path(self, path: str) -> np.ndarray:
        if not self.image_root:
            raise ApiError(HTTPStatus.FORBIDDEN, "image_path_disabled",
                           "image_path is not enabled; start the server with --image-root <folder>")
        real = os.path.realpath(path if os.path.isabs(path) else os.path.join(self.image_root, path))
        try:
            inside = os.path.commonpath([real, self.image_root]) == self.image_root
        except ValueError:                                    # different drives
            inside = False
        if not inside:
            raise ApiError(HTTPStatus.FORBIDDEN, "image_path_outside_root", "image_path must be inside the image root folder")
        if not os.path.isfile(real) or not real.lower().endswith(IMAGE_EXTENSIONS):
            raise ApiError(HTTPStatus.NOT_FOUND, "image_not_found", "no such image file")
        img = imread(real)
        if img is None:
            raise ApiError(HTTPStatus.BAD_REQUEST, "bad_image", "the file is not a readable image")
        return self._check_pixels(img)

    def _check_pixels(self, img: np.ndarray) -> np.ndarray:
        if img.shape[0] * img.shape[1] > self.max_pixels:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "image_too_large",
                           f"image has more than {self.max_pixels // 1_000_000} megapixels")
        return img

    # -- overrides -----------------------------------------------------------------
    @staticmethod
    def _find_node(flow, ref: str):
        matches = [n for n in flow.nodes.values() if n.instance_id == ref]
        if not matches:
            matches = [n for n in flow.nodes.values() if n.name == ref]
        if not matches:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "unknown_module", f"the flow has no module '{ref}'")
        if len(matches) > 1:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "ambiguous_module",
                           f"more than one module is called '{ref}'; use its id: {[n.instance_id for n in matches]}")
        return matches[0]

    def apply_overrides(self, flow, params: Any) -> None:
        if params in (None, {}):
            return
        if not isinstance(params, dict) or not all(isinstance(v, dict) for v in params.values()):
            raise ApiError(HTTPStatus.BAD_REQUEST, "bad_params",
                           'params must look like {"<module name or id>": {"<parameter>": value}}')
        problems: List[str] = []
        planned: List[Tuple[Any, str, Any]] = []
        for ref, changes in params.items():
            node = self._find_node(flow, str(ref))
            allowed = self._overridable(node)
            for key, value in changes.items():
                if node.tool_name in LOCKED_TOOLS:
                    problems.append(f"{ref}.{key}: '{node.tool_name}' modules cannot be changed through the API")
                elif key not in node.parameters:
                    problems.append(f"{ref}.{key}: no such parameter")
                elif key not in allowed:
                    problems.append(f"{ref}.{key}: this parameter cannot be changed through the API")
                else:
                    why = param_schema.problem(node.tool_name, key, node.parameters[key], value)
                    if why:
                        problems.append(f"{ref}.{key}: {why}")
                    else:
                        planned.append((node, key, value))
        if problems:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "invalid_params", "; ".join(problems))
        for node, key, value in planned:
            node.set_param(key, value)

    # -- run ---------------------------------------------------------------------------
    def run(self, name: str, image: Optional[np.ndarray], params: Any = None,
            flow_name: Optional[str] = None, want_image: bool = False) -> Dict[str, Any]:
        sol = self._load(name)
        if flow_name:
            if flow_name not in sol.flows:
                raise ApiError(HTTPStatus.NOT_FOUND, "flow_not_found", f"'{name}' has no flow '{flow_name}'; it has {list(sol.flows)}")
            sol.active_flow_name = flow_name
        if not sol.flows:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "empty_solution", f"'{name}' contains no flow")
        flow = sol.get_active_flow()
        source = next((n for n in flow.nodes.values() if n.tool_name == "Image Source"), None)
        if image is not None:
            if source is None:
                raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "no_image_source",
                               f"flow '{flow.name}' has no Image Source module to receive an image")
            source._override_image = image
            source._override_name = "API image"
        self.apply_overrides(flow, params)

        if not self._lock.acquire(timeout=self.queue_timeout):
            raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "busy", "the server is busy running other jobs; try again shortly")
        try:
            t0 = time.perf_counter()
            try:
                results = flow.execute_flow(global_vars=sol.global_variables)
                script_error = sol.run_global_script(results)
            except Exception as exc:                          # noqa: BLE001 - an engine bug must not kill the server
                LOG.exception("flow '%s' crashed", name)
                raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "engine_error", f"{type(exc).__name__}: {exc}") from exc
            total_ms = (time.perf_counter() - t0) * 1000.0
        finally:
            self._lock.release()

        modules = []
        failing = []
        overlays: List[Dict[str, Any]] = []
        for node_id in flow.execution_order:
            res = results.get(node_id)
            node = flow.nodes.get(node_id)
            if res is None or node is None:
                continue
            modules.append({"id": node_id, "name": node.name, "tool": node.tool_name, "status": res.status.value,
                            "message": res.message, "elapsed_ms": round(res.elapsed_ms, 3),
                            "outputs": to_jsonable(res.outputs)})
            overlays.extend(res.overlays or [])
            if res.status in FAILING_STATUSES:
                failing.append(node.name)
        passed = not failing
        payload: Dict[str, Any] = {
            "flow": name, "flow_name": flow.name, "verdict": "PASS" if passed else "FAIL", "passed": passed,
            "failed_modules": failing, "elapsed_ms": round(total_ms, 3), "modules": modules,
        }
        if script_error:
            payload["script_error"] = script_error
        if want_image:
            base = None
            if source is not None and source.instance_id in results:
                base = results[source.instance_id].outputs.get("Image")
            if base is None:
                base = image
            if isinstance(base, np.ndarray):
                ok, buf = cv2.imencode(".png", render_overlays(base, overlays))
                if ok:
                    payload["image_base64"] = base64.b64encode(buf.tobytes()).decode("ascii")
        return payload


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------
_FLOW_RE = re.compile(r"^/v1/flows/([^/]+)$")
_RUN_RE = re.compile(r"^/v1/flows/([^/]+)/run$")


class ApexServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service: FlowService, api_key: Optional[str], cors_origins: Sequence[str]):
        super().__init__(address, _Handler)
        self.service = service
        self.api_key = api_key
        self.cors_origins = tuple(cors_origins)


class _Handler(BaseHTTPRequestHandler):
    server: ApexServer
    server_version = f"ApexVisionAPI/{APP_VERSION}"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:       # route access logs through logging
        LOG.info("%s %s", self.address_string(), fmt % args)

    # -- helpers -------------------------------------------------------------------
    def _cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        allowed = self.server.cors_origins
        if origin and ("*" in allowed or origin in allowed):
            self.send_header("Access-Control-Allow-Origin", origin if "*" not in allowed else "*")
            self.send_header("Vary", "Origin")

    def _send(self, status: int, payload: Optional[Dict[str, Any]], extra: Optional[Dict[str, str]] = None) -> None:
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors_headers()
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _fail(self, err: ApiError) -> None:
        extra = {"Retry-After": "5"} if err.status == HTTPStatus.SERVICE_UNAVAILABLE else None
        self._send(err.status, {"error": {"code": err.code, "message": err.message}}, extra)

    def _authorised(self) -> bool:
        key = self.server.api_key
        if not key:
            return True
        given = self.headers.get("X-API-Key", "")
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            given = auth[7:].strip()
        return hmac.compare_digest(given.encode("utf-8"), key.encode("utf-8"))

    def _read_body(self) -> bytes:
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            raise ApiError(HTTPStatus.LENGTH_REQUIRED, "length_required", "send a Content-Length header (chunked bodies are not supported)")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(HTTPStatus.BAD_REQUEST, "bad_length", "invalid Content-Length") from None
        limit = int(self.server.service.max_image_bytes * 4 / 3) + 65536     # room for base64 + JSON
        if length < 0 or length > limit:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request_too_large",
                           f"the request body is larger than {limit // (1024 * 1024)} MB")
        return self.rfile.read(length) if length else b""

    # -- verbs ---------------------------------------------------------------------
    def do_OPTIONS(self) -> None:                               # noqa: N802 - http.server API
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-API-Key")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:                                   # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:                                  # noqa: N802
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        try:
            url = urlparse(self.path)
            path = url.path.rstrip("/") or "/"
            query = parse_qs(url.query)
            if path == f"{API_PREFIX}/health" and method == "GET":
                return self._send(HTTPStatus.OK, {"status": "ok", "version": APP_VERSION})
            if not self._authorised():
                raise ApiError(HTTPStatus.UNAUTHORIZED, "unauthorized", "missing or wrong API key")
            service = self.server.service
            if path == f"{API_PREFIX}/flows" and method == "GET":
                return self._send(HTTPStatus.OK, {"flows": service.list_flows()})
            m = _FLOW_RE.match(path)
            if m and method == "GET":
                return self._send(HTTPStatus.OK, service.describe(unquote(m.group(1))))
            m = _RUN_RE.match(path)
            if m and method == "POST":
                return self._run(unquote(m.group(1)), query)
            if path.startswith(API_PREFIX):
                raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED if (m or _FLOW_RE.match(path) or path == f"{API_PREFIX}/flows") else HTTPStatus.NOT_FOUND,
                               "not_allowed" if (m or _FLOW_RE.match(path) or path == f"{API_PREFIX}/flows") else "not_found",
                               f"{method} {path} is not available")
            raise ApiError(HTTPStatus.NOT_FOUND, "not_found", "unknown address; the API lives under /v1")
        except ApiError as err:
            self._fail(err)
        except Exception as exc:                                # noqa: BLE001 - never leak a traceback to the client
            LOG.exception("unhandled error")
            self._fail(ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", f"{type(exc).__name__}"))

    def _run(self, name: str, query: Dict[str, List[str]]) -> None:
        service = self.server.service
        body = self._read_body()
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        image: Optional[np.ndarray] = None
        params: Any = None
        flow_name = (query.get("flow") or [None])[0]
        want_image = (query.get("return_image") or ["0"])[0].lower() in ("1", "true", "yes")
        if (query.get("params") or [None])[0]:
            try:
                params = json.loads(query["params"][0])
            except json.JSONDecodeError:
                raise ApiError(HTTPStatus.BAD_REQUEST, "bad_params", "the params query value is not valid JSON") from None

        if ctype == "application/json":
            try:
                data = json.loads(body.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise ApiError(HTTPStatus.BAD_REQUEST, "bad_json", "the request body is not valid JSON") from None
            if not isinstance(data, dict):
                raise ApiError(HTTPStatus.BAD_REQUEST, "bad_json", "the JSON body must be an object")
            params = data.get("params", params)
            flow_name = data.get("flow", flow_name)
            want_image = bool(data.get("return_image", want_image))
            if data.get("image_base64"):
                b64 = str(data["image_base64"])
                if b64.startswith("data:") and "," in b64:
                    b64 = b64.split(",", 1)[1]
                try:
                    raw = base64.b64decode(b64, validate=False)
                except (binascii.Error, ValueError):
                    raise ApiError(HTTPStatus.BAD_REQUEST, "bad_image", "image_base64 is not valid base64") from None
                image = service.decode_image(raw)
            elif data.get("image_path"):
                image = service.read_image_path(str(data["image_path"]))
        elif ctype.startswith("image/") or ctype == "application/octet-stream":
            image = service.decode_image(body)
        elif body:
            raise ApiError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "unsupported_media_type",
                           "send an image (image/png, image/jpeg ...) or JSON (application/json)")

        self._send(HTTPStatus.OK, service.run(name, image, params=params, flow_name=flow_name, want_image=want_image))


# ---------------------------------------------------------------------------
# Construction and entry point
# ---------------------------------------------------------------------------
def make_server(flows_dir: str, host: str = "127.0.0.1", port: int = 8800, api_key: Optional[str] = None,
                image_root: Optional[str] = None, max_image_mb: float = 50.0,
                cors_origins: Iterable[str] = (), queue_timeout: float = 120.0) -> ApexServer:
    """Create (but do not start) the server. Raises ``ValueError`` for an unsafe configuration."""
    if host not in LOOPBACK_HOSTS and not api_key:
        raise ValueError(f"refusing to listen on {host} without an API key; use --api-key (or APEX_API_KEY), "
                         "or keep the default 127.0.0.1 to accept only this computer")
    if not os.path.isdir(flows_dir):
        raise ValueError(f"flows folder not found: {flows_dir}")
    if image_root and not os.path.isdir(image_root):
        raise ValueError(f"image root folder not found: {image_root}")
    service = FlowService(flows_dir, image_root=image_root, max_image_bytes=int(max_image_mb * 1024 * 1024),
                          queue_timeout=queue_timeout)
    return ApexServer((host, port), service, api_key or None, tuple(cors_origins))
