# Local HTTP API

Run your saved flows from another program. The other program sends an image over HTTP; Apex Vision runs the
flow on your computer and sends back **PASS / FAIL** and every module's results as JSON. It uses the same engine as
the window, so a result over HTTP is the result you would see on screen.

```text
your app  ──HTTP──▶  python main.py serve  ──▶  flow engine  ──▶  JSON result (+ annotated image)
```

## Start it

```bash
python main.py serve --flows path/to/folder
```

Every flow file in that folder (`.apex`, `.xml`, and older `.vmp`, `.sol`, `.json`) can be called by its file name.
Without `--flows` it uses `./projects`, or `Documents/ApexVision/Projects`. Anything you save from the app into that
folder is available straight away; no restart needed.

| Option | Meaning |
|---|---|
| `--port 8800` | port (default 8800) |
| `--host 127.0.0.1` | address to listen on. The default accepts **this computer only** |
| `--api-key KEY` | require this key. **Mandatory** if `--host` is anything other than `127.0.0.1`. Also read from `APEX_API_KEY` |
| `--image-root DIR` | let callers pass `image_path` for files inside this folder (off by default) |
| `--max-image-mb 50` | largest accepted image |
| `--cors-origin URL` | allow a browser app at this address to call the API (repeatable) |

The server prints its address and the flows it found when it starts. Stop it with <kbd>Ctrl</kbd>+<kbd>C</kbd>.

> The server is started from source (`python main.py serve`). The packaged Windows app is a windowed program and has
> no console, so it does not offer `serve` yet.

## Endpoints

| | |
|---|---|
| `GET /v1/health` | `{"status": "ok", "version": ...}` (never needs the key) |
| `GET /v1/flows` | the flows in the folder |
| `GET /v1/flows/{name}` | its modules, ports, and the parameters a caller may change (with limits) |
| `POST /v1/flows/{name}/run` | run it on an image |

### Running a flow

Send the image as the request body, or as JSON.

**Raw image** (`Content-Type: image/png`, `image/jpeg`, ...). Options go in the query string:
`?return_image=1` returns the annotated image, `?flow=<name>` picks a flow inside a multi-flow solution,
`?params=<json>` sets parameters.

**JSON** (`Content-Type: application/json`):

```json
{
  "image_base64": "<base64 of a PNG/JPEG, or a data: URI>",
  "image_path": "board_001.png",
  "params": { "04_IlluminationCheck": { "min_mean": 40, "max_mean": 200 } },
  "flow": "Precision_Measurement_Solution",
  "return_image": true
}
```

Use `image_base64` **or** `image_path` (only inside `--image-root`). With no image at all, the flow runs on its own
Image Source (a camera, a file, or the synthetic test image). Sending an image to a flow with no Image Source is an error.

**Response**

```json
{
  "flow": "Precision_Measurement_Demo",
  "flow_name": "Precision_Measurement_Solution",
  "verdict": "PASS",
  "passed": true,
  "failed_modules": [],
  "elapsed_ms": 70.0,
  "modules": [
    { "id": "node_p2p", "name": "03_HoleDistance", "tool": "P2P Measure", "status": "OK",
      "message": "P2P Dist: 200.00", "elapsed_ms": 0.4, "outputs": { "Distance": 200.0 } }
  ],
  "image_base64": "<annotated PNG, only if return_image was requested>"
}
```

`verdict` is `FAIL` when any module reports NG, Error or Timeout. Images inside `outputs` are not copied; they appear
as `{"_type": "image", "shape": [600, 800, 3], "dtype": "uint8"}`. Use `return_image` to get the annotated picture.

### Changing parameters for one request

`params` maps a **module name or id** to the settings to change, for this call only. The saved flow is never modified.
`GET /v1/flows/{name}` lists, for each module, exactly which parameters can be changed and their limits.

You can change numbers, on/off switches, drop-down choices, regions, lines, points and colours. Values are checked
against the allowed range first; if any is wrong, nothing runs and you get a `422` that names every problem.
Text, file-path, folder and code parameters, and every parameter of the Script module, can **not** be changed through
the API.

### Errors

Errors always look like `{"error": {"code": "...", "message": "..."}}`.

| Status | `code` | Meaning |
|---|---|---|
| 400 | `bad_image`, `bad_json`, `bad_params` | the request could not be understood |
| 401 | `unauthorized` | missing or wrong API key |
| 403 | `image_path_disabled`, `image_path_outside_root` | `image_path` not allowed |
| 404 | `flow_not_found`, `image_not_found` | no such flow or file |
| 405 / 415 | `not_allowed`, `unsupported_media_type` | wrong method or content type |
| 413 | `image_too_large`, `request_too_large` | over the size limits |
| 422 | `invalid_params`, `unknown_module`, `no_image_source`, `flow_unreadable` | understood but not valid |
| 500 | `engine_error` | the flow crashed (details in the server log) |
| 503 | `busy` | other jobs are still running; retry |

## Examples

### Python

```python
import requests

API = "http://127.0.0.1:8800/v1"

with open("tile_0042.png", "rb") as f:
    r = requests.post(f"{API}/flows/width_check/run", data=f.read(),
                      headers={"Content-Type": "image/png"},
                      params={"return_image": 1})
r.raise_for_status()
result = r.json()
print(result["verdict"], result["failed_modules"])
for m in result["modules"]:
    print(m["name"], m["status"], m["outputs"])
```

Change a threshold for one call:

```python
requests.post(f"{API}/flows/width_check/run", json={
    "image_base64": b64_png,
    "params": {"Condition Branch": {"threshold_low": 100, "threshold_high": 300}},
})
```

### JavaScript

```js
const form = await fetch("http://127.0.0.1:8800/v1/flows/width_check/run", {
  method: "POST",
  headers: { "Content-Type": "image/png" },
  body: pngBlob,                       // a File or Blob
});
const result = await form.json();
console.log(result.verdict);
```

A web page calling the API straight from the browser needs `--cors-origin http://your-site`.

### curl

```bash
curl -X POST -H "Content-Type: image/png" --data-binary @tile.png \
     "http://127.0.0.1:8800/v1/flows/width_check/run?return_image=1"
```

## Safety

- Listens on `127.0.0.1` by default. To accept other computers, set `--host 0.0.0.0` **and** an API key; the server
  refuses to start without one. Use HTTPS in front of it (a reverse proxy) if the traffic leaves a trusted network.
- Callers can only run flows already in the folder. They cannot upload a flow file, because a flow can contain a Script
  module that runs Python code.
- The flow's own global script and Script modules run as you saved them. Only put flows you trust in the folder.
- Jobs run one at a time. Other requests wait (up to two minutes) and then get `503`.
