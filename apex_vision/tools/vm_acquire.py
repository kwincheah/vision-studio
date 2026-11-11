"""VisionMaster guide, chapter "Acquisition": Multi-image Acquisition and Light Source."""
import os
import re
import socket
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from apex_vision.core.param_schema import enum, num
from apex_vision.tools._spec import define, err, ng, ok, port, val
from apex_vision.tools.communication_ext import decode_escapes

CAT = "Acquisition"
SIM = "Simulation (Log Only)"
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")


# ---------------------------------------------------------------------------------------------------------------------------
# light source controllers
# ---------------------------------------------------------------------------------------------------------------------------
def build_commands(template: str, channels: List[int], levels: List[int]) -> List[str]:
    """One command per channel from a template using {channel}, {brightness} and {brightness:04d}-style fields."""
    out = []
    for ch, lv in zip(channels, levels):
        def sub(m):
            name, spec = m.group(1), m.group(2)
            v = ch if name == "channel" else lv
            try:
                return format(int(v), spec or "")
            except ValueError:
                return str(v)
        out.append(re.sub(r"\{(channel|brightness)(?::([^{}]*))?\}", sub, decode_escapes(template)))
    return out


def send_commands(device: str, commands: List[str], port_name: str, baud: int, host: str, tcp_port: int, timeout_s: float = 1.0) -> Optional[str]:
    """Send the commands to the controller; returns an error text, or None when sent (or simulated)."""
    if device == SIM:
        return None
    try:
        if device == "Serial Port":
            try:
                import serial
            except ImportError:
                return "the serial port library (pyserial) is not installed"
            if not port_name.strip():
                return "no serial port chosen: type the port name, for example COM3"
            with serial.Serial(port_name.strip(), baud, timeout=timeout_s, write_timeout=timeout_s) as s:
                for c in commands:
                    s.write(c.encode("latin-1", "replace"))
                s.flush()
            return None
        if not host.strip():
            return "no controller address chosen: type its IP address"
        with socket.create_connection((host.strip(), int(tcp_port)), timeout=timeout_s) as sock:
            for c in commands:
                sock.sendall(c.encode("latin-1", "replace"))
        return None
    except OSError as e:
        return f"could not reach the light source controller: {e}"


LIGHT_PARAMS = {"device": SIM, "port_name": "COM1", "baud_rate": 9600, "host": "192.168.0.100", "tcp_port": 4001, "channels": "1,2", "brightness": "128,128",
                "command_template": "SA{channel}{brightness:04d}#", "trigger_time_ms": 0, "off_after_trigger": False, "off_command_template": "SA{channel}0000#"}
LIGHT_SCHEMA = {"device": enum(SIM, "Serial Port", "TCP Network"), "port_name": {"kind": "text", "hint": "for example COM3"}, "baud_rate": num(300, 4_000_000), "host": {"kind": "text", "hint": "the controller's IP address"}, "tcp_port": num(1, 65535),
                "channels": {"kind": "text", "hint": "channel numbers, separated by commas"}, "brightness": {"kind": "text", "hint": "brightness 0-255 for each channel, separated by commas"},
                "command_template": {"kind": "text", "hint": "{channel} and {brightness} (for example {brightness:04d})"}, "trigger_time_ms": num(0, 60000, unit="ms"),
                "off_after_trigger": {"kind": "bool"}, "off_command_template": {"kind": "text", "hint": "sent after the trigger time, to switch the channel off"}}


def _ints(text: str, n: Optional[int] = None) -> Optional[List[int]]:
    try:
        v = [int(float(p)) for p in re.split(r"[,;\s]+", str(text).strip()) if p]
    except ValueError:
        return None
    return v


@define("Light Source", CAT,
        "Sets the brightness of a light source controller's channels: it builds one command per channel from your command template and sends it "
        "(over a serial port or the network, or only logs it in simulation), optionally strobing for a trigger time and then switching the channels off.",
        inputs=[port("Brightness", "any", "Brightness for every channel (a number or a list), instead of the typed ones")],
        outputs=[val("Sent", "1 when sent or simulated"), port("Commands", "any", "The commands built"), port("Levels", "any", "Brightness of each channel")],
        params=dict(LIGHT_PARAMS), schema=dict(LIGHT_SCHEMA))
def light_source(t, ctx):
    chans = _ints(t.get_param("channels"))
    if not chans:
        return err("no channels chosen: type the channel numbers, for example 1,2")
    raw = ctx.get("Brightness")
    if raw is not None:
        try:
            levels = [int(float(v)) for v in np.atleast_1d(np.asarray(raw, float)).ravel()]
        except (TypeError, ValueError):
            return err("the brightness must be a number or a list of numbers")
    else:
        levels = _ints(t.get_param("brightness"))
    if not levels:
        return err("no brightness chosen: type a brightness 0-255 for each channel")
    if len(levels) == 1:
        levels = levels * len(chans)
    if len(levels) != len(chans):
        return err(f"{len(chans)} channel(s) but {len(levels)} brightness value(s): give one for each, or just one for all")
    if any(not 0 <= v <= 255 for v in levels):
        return err("brightness must be between 0 and 255")
    cmds = build_commands(str(t.get_param("command_template")), chans, levels)
    dev = str(t.get_param("device"))
    bad = send_commands(dev, cmds, str(t.get_param("port_name")), int(t.get_param("baud_rate")), str(t.get_param("host")), int(t.get_param("tcp_port")))
    if bad:
        return err(bad, Sent=0, Commands=cmds, Levels=levels)
    msg = f"{len(cmds)} command(s) {'logged' if dev == SIM else 'sent'}"
    hold = int(t.get_param("trigger_time_ms"))
    if hold > 0:
        time.sleep(min(hold, 5000) / 1000.0)
        if bool(t.get_param("off_after_trigger")):
            off = build_commands(str(t.get_param("off_command_template")), chans, [0] * len(chans))
            bad = send_commands(dev, off, str(t.get_param("port_name")), int(t.get_param("baud_rate")), str(t.get_param("host")), int(t.get_param("tcp_port")))
            if bad:
                return err(bad, Sent=1, Commands=cmds + off, Levels=levels)
            cmds = cmds + off
            msg += f", then off after {hold} ms"
    t._last_commands = cmds
    return ok(msg, Sent=1, Commands=cmds, Levels=levels)


# ---------------------------------------------------------------------------------------------------------------------------
# Multi-image Acquisition
# ---------------------------------------------------------------------------------------------------------------------------
def _read(path: str) -> Optional[np.ndarray]:
    try:
        im = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    except (OSError, ValueError):
        im = None
    return im if im is not None else cv2.imread(path)


def list_images(path: str) -> List[str]:
    """Image files in a folder (sorted by name), or the files named in a ';'-separated list."""
    parts = [p.strip().strip('"') for p in str(path).split(";") if p.strip()]
    files: List[str] = []
    for p in parts:
        if os.path.isdir(p):
            files += [os.path.join(p, n) for n in sorted(os.listdir(p), key=str.lower) if n.lower().endswith(IMAGE_EXT)]
        elif os.path.isfile(p) and p.lower().endswith(IMAGE_EXT):
            files.append(p)
    return files


def _series(text: str, n: int, cast) -> Optional[List[Any]]:
    """A list typed as 'a, b, c' stretched to n values: one value repeats, a short list repeats its last value."""
    try:
        v = [cast(float(p)) for p in re.split(r"[,;\s]+", str(text).strip()) if p]
    except ValueError:
        return None
    if not v:
        return None
    return (v + [v[-1]] * n)[:n]


MULTI_OUT = [port("Images", "any", "All the pictures taken, in order"), val("Count"), port("Light_Commands", "any", "What was sent to the light source"),
             val("Distribution_Angle"), val("Illumination_Angle")] + [port(f"Image{i}", "img") for i in range(1, 9)]


@define("Multi-image Acquisition", CAT,
        "Takes 3 to 8 pictures in one go - from a folder of local pictures (the next ones each time) or from a camera, changing the exposure, "
        "gain and light brightness for each - and passes them on one by one and as a list. Used for photometric stereo and multi-exposure work.",
        inputs=[port("Clear", "bool", "Start again from the first local picture")],
        outputs=MULTI_OUT,
        params={"image_source": "Local Images", "image_path": "", "fetch_quantity": 3, "fetch_interval_ms": 50, "camera_device": "mvs_gige_0", "exposures": "20000",
                "gains": "1", "light_enable": False, "light_device": SIM, "light_channel": 1, "light_levels": "255", "light_command_template": "SA{channel}{brightness:04d}#",
                "light_port": "COM1", "light_host": "192.168.0.100", "light_tcp_port": 4001, "trigger_time_ms": 0, "distribution_angle": 0.0, "illumination_angle": 0.0},
        schema={"image_source": enum("Local Images", "Camera"), "image_path": {"kind": "path", "filters": "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All files (*)"},
                "fetch_quantity": num(3, 8), "fetch_interval_ms": num(0, 60000, unit="ms"), "camera_device": {"kind": "text", "hint": "the camera's device name"},
                "exposures": {"kind": "text", "hint": "exposure in microseconds for each picture, separated by commas"}, "gains": {"kind": "text", "hint": "gain for each picture, separated by commas"},
                "light_enable": {"kind": "bool"}, "light_device": enum(SIM, "Serial Port", "TCP Network"), "light_channel": num(1, 64),
                "light_levels": {"kind": "text", "hint": "brightness 0-255 for each picture, separated by commas"}, "light_command_template": {"kind": "text", "hint": "{channel} and {brightness}"},
                "light_port": {"kind": "text", "hint": "for example COM3"}, "light_host": {"kind": "text", "hint": "the controller's IP address"}, "light_tcp_port": num(1, 65535),
                "trigger_time_ms": num(0, 60000, unit="ms"), "distribution_angle": num(0, 360, 1, "deg", 1), "illumination_angle": num(0, 360, 1, "deg", 1)})
def multi_image_acquisition(t, ctx):
    n = int(t.get_param("fetch_quantity"))
    src = str(t.get_param("image_source"))
    lights = _series(t.get_param("light_levels"), n, int)
    cmds: List[str] = []

    def set_light(i: int) -> Optional[str]:
        if not bool(t.get_param("light_enable")):
            return None
        if lights is None or any(not 0 <= v <= 255 for v in lights):
            return "the light brightness must be numbers between 0 and 255"
        c = build_commands(str(t.get_param("light_command_template")), [int(t.get_param("light_channel"))], [lights[i]])
        bad = send_commands(str(t.get_param("light_device")), c, str(t.get_param("light_port")), 9600, str(t.get_param("light_host")), int(t.get_param("light_tcp_port")))
        cmds.extend(c)
        if not bad and int(t.get_param("trigger_time_ms")) > 0:
            time.sleep(min(int(t.get_param("trigger_time_ms")), 2000) / 1000.0)
        return bad

    images: List[np.ndarray] = []
    if src == "Local Images":
        files = list_images(str(t.get_param("image_path")))
        if len(files) < n:
            return err(f"{len(files)} picture(s) found but {n} are needed: choose a folder with at least {n} pictures")
        if ctx.get("Clear"):
            t._cursor = 0
        start = int(getattr(t, "_cursor", 0)) % len(files)
        for i in range(n):
            bad = set_light(i)
            if bad:
                return err(bad)
            path = files[(start + i) % len(files)]
            im = _read(path)
            if im is None:
                return ng(f"could not read {os.path.basename(path)}")
            images.append(im)
        t._cursor = (start + n) % len(files)
    else:
        from apex_vision.core.camera_manager import CameraManager
        dev = str(t.get_param("camera_device")).strip()
        driver = CameraManager.get_instance().get_or_create_driver(dev) if dev else None
        if driver is None:
            return err(f"no camera chosen: '{dev}' is not a known camera (open Camera Management to add one)")
        exps, gains = _series(t.get_param("exposures"), n, float), _series(t.get_param("gains"), n, float)
        if exps is None or gains is None:
            return err("the exposures and gains must be numbers, one for each picture")
        for i in range(n):
            bad = set_light(i)
            if bad:
                return err(bad)
            driver.set_exposure(exps[i])
            driver.set_gain(gains[i])
            good, frame, msg = driver.capture_frame(timeout_ms=3000.0)
            if not good or frame is None:
                return ng(f"picture {i + 1} of {n} failed: {msg}")
            images.append(frame)
            if i < n - 1 and int(t.get_param("fetch_interval_ms")) > 0:
                time.sleep(min(int(t.get_param("fetch_interval_ms")), 5000) / 1000.0)
    outs: Dict[str, Any] = {"Images": images, "Count": len(images), "Light_Commands": cmds, "Distribution_Angle": float(t.get_param("distribution_angle")),
                            "Illumination_Angle": float(t.get_param("illumination_angle"))}
    for i in range(8):
        outs[f"Image{i + 1}"] = images[i] if i < len(images) else None
    h, w = images[0].shape[:2]
    return ok(f"{len(images)} picture(s) from {'local files' if src == 'Local Images' else 'the camera'}, first {w} x {h}", **outs)
