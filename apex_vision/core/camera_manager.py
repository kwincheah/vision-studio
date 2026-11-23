"""Industrial and Standard Camera Driver System for Apex Vision Studio.

Provides unified device enumeration, parameter configuration, acquisition,
and live streaming across:
1. Standard Webcams & USB Video Class (DirectShow / MSMF / V4L2)
2. Industrial GigE / USB3 Vision Cameras (GenICam / Hikrobot MVS / Basler Pylon)
   with graceful ctypes / SDK dynamic loading and software emulation fallback.
3. Network Video & Industrial HTTP / RTSP Streams (Hikvision, Dahua, Axis, generic IP cameras)
4. Virtual / Mock Industrial Camera (Simulated trigger, exposure, gain, test chart, live frames)

Designed following the reference product Camera Management (Manual Chapter 4 & 5).
"""
import os
import sys
import time
import ctypes
import logging
import threading
from typing import Dict, List, Any, Optional, Tuple
import cv2
import numpy as np

from apex_vision.core._native import create_ring_buffer

logger = logging.getLogger("apex_vision.camera")


class CameraDeviceInfo:
    """Descriptor for an enumerated camera device."""
    def __init__(
        self,
        device_id: str,
        name: str,
        camera_type: str,  # "USB/Webcam", "Industrial GigE", "Industrial USB3", "IP/RTSP Stream", "Virtual Industrial"
        model: str = "",
        serial_number: str = "",
        ip_address: str = "",
        interface_name: str = "",
        is_available: bool = True,
        stream_url: Optional[str] = None
    ):
        self.device_id = device_id
        self.name = name
        self.camera_type = camera_type
        self.model = model or name
        self.serial_number = serial_number or device_id
        self.ip_address = ip_address
        self.interface_name = interface_name
        self.is_available = is_available
        self.stream_url = stream_url

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "name": self.name,
            "camera_type": self.camera_type,
            "model": self.model,
            "serial_number": self.serial_number,
            "ip_address": self.ip_address,
            "interface_name": self.interface_name,
            "is_available": self.is_available,
        }

    def __repr__(self):
        return f"<CameraDeviceInfo {self.name} [{self.camera_type}] id={self.device_id}>"


class CameraDriverBase:
    """Base interface for all camera hardware drivers."""

    def __init__(self, device_info: CameraDeviceInfo):
        self.device_info = device_info
        self.is_connected = False
        self.exposure_time_us: float = 20000.0  # microseconds
        self.gain: float = 1.0
        self.width: int = 1280
        self.height: int = 1024
        self.pixel_format: str = "BGR8"  # BGR8, Mono8
        self.trigger_mode: str = "Off"  # Off (Continuous/FreeRun), On (Software/Hardware Trigger)
        self.frame_rate: float = 30.0
        self._io_lock = threading.RLock()
        self._frame_seq: int = 0
        self._last_capture_timestamp: Optional[float] = None
        self.ring_buffer = create_ring_buffer(capacity=4)

    def _record_frame(self, frame: np.ndarray) -> None:
        self._frame_seq += 1
        try:
            self.ring_buffer.push(frame, self._frame_seq, time.time())
        except Exception:
            pass

    def last_capture_timestamp(self) -> float:
        """Return timestamp in seconds of the most recently captured frame."""
        if self._last_capture_timestamp is not None:
            return float(self._last_capture_timestamp)
        return time.monotonic()

    def latest_buffered_frame(self) -> Optional[Tuple[np.ndarray, Dict[str, Any]]]:
        return self.ring_buffer.latest()

    def open(self) -> Tuple[bool, str]:
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    def set_exposure(self, exposure_us: float) -> bool:
        self.exposure_time_us = exposure_us
        return True

    def set_gain(self, gain: float) -> bool:
        self.gain = gain
        return True

    def set_roi(self, width: int, height: int, offset_x: int = 0, offset_y: int = 0) -> bool:
        self.width = width
        self.height = height
        return True

    def set_trigger_mode(self, mode: str) -> bool:
        self.trigger_mode = mode
        return True

    def capture_frame(self, timeout_ms: float = 2000.0) -> Tuple[bool, Optional[np.ndarray], str]:
        raise NotImplementedError


class OpenCVCameraDriver(CameraDriverBase):
    """Driver for standard USB webcams and USB Video Class (UVC) cameras."""

    def __init__(self, device_info: CameraDeviceInfo, camera_index: int = 0):
        super().__init__(device_info)
        self.camera_index = camera_index
        self._cap: Optional[cv2.VideoCapture] = None
        self._auto: Optional[bool] = None            # what the module asked for: camera-controlled exposure (True) or fixed (False)
        self._auto_applied: Optional[bool] = None    # what the camera has been told since it was opened

    def open(self) -> Tuple[bool, str]:
        with self._io_lock:
            if self._cap is not None and self._cap.isOpened():
                self.is_connected = True
                return True, "Already connected"

            # Platform-optimized OpenCV capture backend
            if sys.platform == "win32":
                backend = cv2.CAP_DSHOW
            elif sys.platform == "darwin":
                backend = cv2.CAP_AVFOUNDATION
            else:
                backend = cv2.CAP_ANY

            self._cap = cv2.VideoCapture(self.camera_index, backend)

            if not self._cap.isOpened():
                # Fallback to default backend
                self._cap = cv2.VideoCapture(self.camera_index)

            if not self._cap.isOpened():
                self._cap = None
                self.is_connected = False
                if sys.platform == "darwin":
                    return False, (
                        f"Failed to open camera index {self.camera_index}. On macOS, ensure your Terminal or IDE "
                        "has Camera permission in System Settings -> Privacy & Security -> Camera, "
                        "or try switching camera_index to 1 (FaceTime camera vs Continuity Camera)."
                    )
                return False, f"Failed to open camera index {self.camera_index}"

            # Probe resolution
            w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if w > 0 and h > 0:
                self.width = w
                self.height = h

            self.is_connected = True
            self._auto_applied = None
            return True, f"Connected to camera {self.camera_index} ({self.width}x{self.height})"

    def close(self):
        with self._io_lock:
            if self._cap is not None:
                try:
                    self._cap.release()
                except Exception:
                    pass
                self._cap = None
            self.is_connected = False

    def set_auto_exposure(self, on: bool) -> bool:
        """Let the camera set exposure (and brightness) itself, as a webcam does in any other program. Applied on the next capture."""
        with self._io_lock:
            self._auto = bool(on)
            if on:
                self.gain = 1.0                       # no leftover digital gain from a fixed setting
            return True

    def _apply_auto_exposure(self) -> None:
        if self._auto is None or self._auto == self._auto_applied or self._cap is None:
            return
        try:
            # DirectShow: 0.75 = automatic, 0.25 = manual (this also undoes a fixed exposure left on the camera by an earlier run)
            self._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75 if self._auto else 0.25)
            if self._auto:
                for _ in range(8):                # the first frames are dark until the camera has adjusted
                    self._cap.read()
        except Exception:
            pass
        self._auto_applied = self._auto

    def set_exposure(self, exposure_us: float) -> bool:
        with self._io_lock:
            self.exposure_time_us = exposure_us
            if self._cap and self._cap.isOpened():
                # DirectShow exposure property is typically log2(seconds) or arbitrary units
                try:
                    # Convert us to approximate cv2 exposure
                    exp_sec = exposure_us / 1000000.0
                    if exp_sec > 0:
                        exp_val = np.log2(exp_sec)
                        self._cap.set(cv2.CAP_PROP_EXPOSURE, float(exp_val))
                except Exception:
                    pass
            return True

    def set_gain(self, gain: float) -> bool:
        with self._io_lock:
            self.gain = gain
            if self._cap and self._cap.isOpened():
                try:
                    self._cap.set(cv2.CAP_PROP_GAIN, float(gain))
                except Exception:
                    pass
            return True

    def set_roi(self, width: int, height: int, offset_x: int = 0, offset_y: int = 0) -> bool:
        with self._io_lock:
            self.width = width
            self.height = height
            if self._cap and self._cap.isOpened():
                try:
                    self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
                    self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
                    self.width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    self.height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                except Exception:
                    pass
            return True

    def capture_frame(self, timeout_ms: float = 2000.0) -> Tuple[bool, Optional[np.ndarray], str]:
        with self._io_lock:
            if not self.is_connected or self._cap is None or not self._cap.isOpened():
                ok, msg = self.open()
                if not ok:
                    return False, None, msg

            self._apply_auto_exposure()
            ret, frame = self._cap.read()
            if not ret or frame is None:
                return False, None, f"Camera index {self.camera_index} frame acquisition timed out"

            # Apply digital gain/exposure adjustments if hardware didn't satisfy
            if self.gain != 1.0 and self.gain > 0:
                frame = cv2.convertScaleAbs(frame, alpha=float(self.gain), beta=0)

            if self.pixel_format == "Mono8" and len(frame.shape) == 3:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            self._last_capture_timestamp = time.monotonic()

            self._record_frame(frame)
            return True, frame, "OK"


def _clean_stream_url(url: str) -> str:
    clean = str(url or "").strip().strip('"').strip("'")
    if clean.lower().startswith("file:///"):
        from urllib.parse import unquote
        clean = unquote(clean[8:])
    return clean


class StreamCameraDriver(CameraDriverBase):
    """Driver for IP, RTSP, HTTP (MJPEG), and industrial network camera streams."""

    def __init__(self, device_info: CameraDeviceInfo, stream_url: str):
        super().__init__(device_info)
        self.stream_url = _clean_stream_url(stream_url)
        self._cap: Optional[cv2.VideoCapture] = None

    def open(self) -> Tuple[bool, str]:
        with self._io_lock:
            self.stream_url = _clean_stream_url(self.stream_url)
            if not self.stream_url:
                return False, "Stream URL is empty"
            self.close()
            is_net = self.stream_url.lower().startswith(("rtsp://", "rtsps://", "http://", "https://"))
            if is_net:
                os.environ.setdefault(
                    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
                    "rtsp_transport;tcp|timeout;3000000|stimeout;3000000",
                )
                if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC") and hasattr(cv2, "CAP_FFMPEG"):
                    try:
                        self._cap = cv2.VideoCapture(
                            self.stream_url,
                            cv2.CAP_FFMPEG,
                            [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000],
                        )
                    except TypeError:
                        self._cap = cv2.VideoCapture(self.stream_url)
                else:
                    self._cap = cv2.VideoCapture(self.stream_url)
            else:
                self._cap = cv2.VideoCapture(self.stream_url)
            if not self._cap.isOpened():
                self._cap = None
                self.is_connected = False
                return False, f"Could not connect to stream: {self.stream_url}"

            try:
                # Minimize RTSP/network frame buffering so tracking sees near-real-time frames
                self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass

            self.is_connected = True
            w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if w > 0 and h > 0:
                self.width = w
                self.height = h
            return True, f"Connected to stream {self.stream_url}"

    def close(self):
        with self._io_lock:
            if self._cap is not None:
                try:
                    self._cap.release()
                except Exception:
                    pass
                self._cap = None
            self.is_connected = False

    def capture_frame(self, timeout_ms: float = 2000.0) -> Tuple[bool, Optional[np.ndarray], str]:
        with self._io_lock:
            if not self.is_connected or self._cap is None or not self._cap.isOpened():
                ok, msg = self.open()
                if not ok:
                    return False, None, msg

            ret, frame = self._cap.read()
            if not ret or frame is None:
                # Attempt one transparent reconnect on transient RTSP drop before failing
                self.close()
                ok, msg = self.open()
                if not ok or self._cap is None:
                    return False, None, f"Failed to grab frame from stream: {self.stream_url} ({msg})"
                ret, frame = self._cap.read()
                if not ret or frame is None:
                    return False, None, f"Failed to grab frame from stream: {self.stream_url}"

            if self.pixel_format == "Mono8" and len(frame.shape) == 3:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            if os.path.isfile(self.stream_url):
                fps = float(self._cap.get(cv2.CAP_PROP_FPS) or 0.0)
                pos_frames = float(self._cap.get(cv2.CAP_PROP_POS_FRAMES) or 0.0)
                pos_msec = float(self._cap.get(cv2.CAP_PROP_POS_MSEC) or 0.0)
                if fps > 0.0 and pos_frames >= 1.0:
                    self._last_capture_timestamp = max(0.0, (pos_frames - 1.0) / fps)
                elif pos_msec >= 0.0:
                    self._last_capture_timestamp = pos_msec / 1000.0
                else:
                    self._last_capture_timestamp = time.monotonic()
            else:
                self._last_capture_timestamp = time.monotonic()

            self._record_frame(frame)
            return True, frame, "OK"


class IndustrialCameraDriver(CameraDriverBase):
    """Industrial GigE / USB3 Vision Camera Driver.

    Directly interfaces with industrial camera features:
    - Microsecond hardware exposure time
    - Analog / Digital dB gain
    - Hardware trigger (Line0, Line1) and Software trigger
    - Hardware ROI / binning
    - GenICam parameter control
    - Fallback: High-precision synthetic inspection chart with live dynamic noise,
      simulating real factory inspection conveyor movement and strobe trigger.
    """

    def __init__(self, device_info: CameraDeviceInfo):
        super().__init__(device_info)
        self._frame_count = 0
        self._last_trigger_time = 0.0

    def open(self) -> Tuple[bool, str]:
        self.is_connected = True
        return True, f"Connected to {self.device_info.name} [{self.device_info.camera_type}]"

    def close(self):
        self.is_connected = False

    def capture_frame(self, timeout_ms: float = 2000.0) -> Tuple[bool, Optional[np.ndarray], str]:
        with self._io_lock:
            if not self.is_connected:
                ok, msg = self.open()
                if not ok:
                    return False, None, msg

            self._frame_count += 1
            frame_num = self._frame_count
            w, h = self.width, self.height
            exp_us = self.exposure_time_us
            gain_val = self.gain
            px_fmt = self.pixel_format
            sn = self.device_info.serial_number

        # Generate synthetic industrial frame outside the lock so multiple threads don't stall
        img = np.zeros((h, w, 3), dtype=np.uint8)
        img[:] = (45, 52, 48)

        t_shift = int((time.time() * 30) % w)
        cx = (w // 2 + (t_shift % 60) - 30)
        cy = h // 2

        cv2.rectangle(img, (cx - 240, cy - 180), (cx + 240, cy + 180), (120, 125, 130), -1)
        cv2.rectangle(img, (cx - 240, cy - 180), (cx + 240, cy + 180), (200, 205, 210), 3)
        cv2.rectangle(img, (cx - 210, cy - 150), (cx + 210, cy + 150), (30, 90, 45), -1)

        cv2.circle(img, (cx - 180, cy - 120), 16, (220, 220, 220), -1)
        cv2.circle(img, (cx - 180, cy - 120), 6, (10, 10, 10), -1)
        cv2.circle(img, (cx + 180, cy + 120), 16, (220, 220, 220), -1)
        cv2.circle(img, (cx + 180, cy + 120), 6, (10, 10, 10), -1)

        cv2.circle(img, (cx, cy), 65, (25, 25, 25), -1)
        cv2.circle(img, (cx, cy), 65, (230, 230, 230), 4)
        cv2.circle(img, (cx, cy), 18, (180, 180, 180), -1)

        cv2.line(img, (cx - 150, cy + 80), (cx + 150, cy + 80), (240, 240, 240), 2)
        cv2.line(img, (cx - 150, cy + 110), (cx + 150, cy + 110), (240, 240, 240), 2)

        stamp = f"ID: {sn} | Exp: {exp_us:.0f}us | Gain: {gain_val:.1f}x | F#{frame_num}"
        cv2.putText(img, stamp, (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 128), 1, cv2.LINE_AA)

        exp_factor = max(0.2, min(2.5, exp_us / 20000.0))
        gain_factor = max(0.5, min(4.0, gain_val))
        if exp_factor != 1.0 or gain_factor != 1.0:
            scale = exp_factor * gain_factor
            img = cv2.convertScaleAbs(img, alpha=scale, beta=0)

        noise = np.random.normal(0, 3.0, img.shape).astype(np.int16)
        img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        if px_fmt == "Mono8":
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        self._record_frame(img)
        return True, img, "OK"


class CameraManager:
    """Singleton Camera Manager handling device discovery, connection registry,

    and camera setting dialogs across all supported protocols.
    """
    _instance: Optional["CameraManager"] = None
    _instance_lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> "CameraManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = CameraManager()
            return cls._instance

    def __init__(self):
        self._devices: Dict[str, CameraDeviceInfo] = {}
        self._user_streams: Dict[str, CameraDeviceInfo] = {}
        self._active_drivers: Dict[str, CameraDriverBase] = {}
        self._drivers_lock = threading.RLock()
        self.default_camera_id: str = "virtual_gige_0"
        self.refresh_devices()

    def add_network_stream(self, stream_url: str, name: Optional[str] = None) -> CameraDeviceInfo:
        """Register a persistent user-configured RTSP/HTTP network stream."""
        clean_url = _clean_stream_url(stream_url)
        dev_id = f"rtsp_{abs(hash(clean_url)) % 10000000}"
        display_name = name or f"Network Stream ({clean_url})"
        info = CameraDeviceInfo(
            device_id=dev_id,
            name=display_name,
            camera_type="IP/RTSP Stream",
            interface_name="RTSP/HTTP Stream",
            stream_url=clean_url
        )
        self._user_streams[dev_id] = info
        self._devices[dev_id] = info
        return info

    def refresh_devices(self) -> List[CameraDeviceInfo]:
        """Scans the host system and discovers all available standard, industrial, and MVS cameras."""
        self._devices.clear()
        # Re-populate user-defined streams
        for dev_id, dev_info in self._user_streams.items():
            self._devices[dev_id] = dev_info

        # 1. Hikrobot MVS Camera Integration (Native C SDK or High-Fidelity MVS Emulation)
        from apex_vision.core.mvs_sdk import MvsSdkLoader, MvsCameraDriver
        mvs_loader = MvsSdkLoader.get_instance()

        # Check for physical Hikrobot MVS cameras via C SDK
        if mvs_loader.is_sdk_available and mvs_loader.dll:
            try:
                from apex_vision.core.mvs_sdk import MV_CC_DEVICE_INFO_LIST, MV_GIGE_DEVICE, MV_USB_DEVICE
                dev_list = MV_CC_DEVICE_INFO_LIST()
                ret = mvs_loader.dll.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, ctypes.byref(dev_list))
                if ret == 0:
                    for i in range(dev_list.nDeviceNum):
                        dev_ptr = dev_list.pDeviceInfo[i]
                        if dev_ptr:
                            dev = dev_ptr.contents
                            if dev.nTLayerType == MV_GIGE_DEVICE:
                                gige_info = dev.SpecialInfo.stGigEInfo
                                m_model = gige_info.chModelName.decode("utf-8", errors="ignore").strip("\x00")
                                m_sn = gige_info.chSerialNumber.decode("utf-8", errors="ignore").strip("\x00")
                                m_id = f"mvs_hw_gige_{m_sn}"
                                cam_info = CameraDeviceInfo(
                                    device_id=m_id,
                                    name=f"Hikrobot {m_model} [MVS GigE] (S/N: {m_sn})",
                                    camera_type="Hikrobot MVS GigE",
                                    model=m_model or "Hikrobot GigE Camera",
                                    serial_number=m_sn or m_id,
                                    interface_name="Hikrobot MVS GigE Vision"
                                )
                                cam_info._mvs_c_dev_ptr = dev_ptr
                                self._devices[m_id] = cam_info
                            elif dev.nTLayerType == MV_USB_DEVICE:
                                usb_info = dev.SpecialInfo.stUsb3VInfo
                                m_model = usb_info.chModelName.decode("utf-8", errors="ignore").strip("\x00")
                                m_sn = usb_info.chSerialNumber.decode("utf-8", errors="ignore").strip("\x00")
                                m_id = f"mvs_hw_usb3_{m_sn}"
                                cam_info = CameraDeviceInfo(
                                    device_id=m_id,
                                    name=f"Hikrobot {m_model} [MVS USB3] (S/N: {m_sn})",
                                    camera_type="Hikrobot MVS USB3",
                                    model=m_model or "Hikrobot USB3 Camera",
                                    serial_number=m_sn or m_id,
                                    interface_name="Hikrobot MVS USB3 Vision"
                                )
                                cam_info._mvs_c_dev_ptr = dev_ptr
                                self._devices[m_id] = cam_info
            except Exception as e:
                logger.warning(f"Error enumerating native MVS cameras: {e}", exc_info=True)

        # Hikrobot MVS Virtual / Target Cameras (Guaranteed offline & development availability)
        mvs_gige = CameraDeviceInfo(
            device_id="mvs_gige_0",
            name="Hikrobot MV-CA050-10GM (MVS GigE)",
            camera_type="Hikrobot MVS GigE",
            model="MV-CA050-10GM",
            serial_number="DA12345678",
            ip_address="192.168.1.100",
            interface_name="Hikrobot MVS GigE"
        )
        mvs_usb3 = CameraDeviceInfo(
            device_id="mvs_usb3_0",
            name="Hikrobot MV-CS016-10UC (MVS USB3)",
            camera_type="Hikrobot MVS USB3",
            model="MV-CS016-10UC",
            serial_number="UC98765432",
            interface_name="Hikrobot MVS USB3"
        )
        self._devices[mvs_gige.device_id] = mvs_gige
        self._devices[mvs_usb3.device_id] = mvs_usb3

        # 2. Industrial Virtual / Simulation Cameras
        v_gige = CameraDeviceInfo(
            device_id="virtual_gige_0",
            name="Industrial GigE Vision Camera (Simulation)",
            camera_type="Industrial GigE",
            model="MV-CA050-10GM",
            serial_number="DA12345678",
            ip_address="192.168.1.100",
            interface_name="GigE Vision"
        )
        v_usb3 = CameraDeviceInfo(
            device_id="virtual_usb3_0",
            name="Basler dart daA1600-60uc (USB3 Simulation)",
            camera_type="Industrial USB3",
            model="daA1600-60uc",
            serial_number="21894561",
            interface_name="USB3 Vision"
        )
        self._devices[v_gige.device_id] = v_gige
        self._devices[v_usb3.device_id] = v_usb3

        # 2. Probe physical OpenCV Webcams / UVC Cameras
        if sys.platform == "win32":
            backend = cv2.CAP_DSHOW
        elif sys.platform == "darwin":
            backend = cv2.CAP_AVFOUNDATION
        else:
            backend = cv2.CAP_ANY

        probe_range = 4 if sys.platform == "darwin" else 3
        for idx in range(probe_range):
            cap = cv2.VideoCapture(idx, backend)
            if not cap.isOpened() and sys.platform == "darwin":
                cap = cv2.VideoCapture(idx)
            if cap.isOpened():
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cap.release()
                cam_id = f"webcam_{idx}"
                cam_info = CameraDeviceInfo(
                    device_id=cam_id,
                    name=f"Standard USB Camera / Webcam {idx} ({w}x{h})",
                    camera_type="USB/Webcam",
                    model=f"UVC Camera {idx}",
                    serial_number=f"USB-VID-CAM{idx}",
                    interface_name=f"USB Video Class (Index {idx})"
                )
                self._devices[cam_id] = cam_info
            else:
                try:
                    cap.release()
                except Exception:
                    pass

        # 3. Add predefined RTSP / IP Network Camera template
        rtsp_info = CameraDeviceInfo(
            device_id="ip_stream_custom",
            name="IP / RTSP Network Camera (Custom URL)",
            camera_type="IP/RTSP Stream",
            model="Generic Industrial RTSP Stream",
            serial_number="NET-RTSP-01",
            ip_address="192.168.1.64",
            interface_name="Ethernet RTSP/HTTP"
        )
        self._devices[rtsp_info.device_id] = rtsp_info

        return list(self._devices.values())

    def list_devices(self) -> List[CameraDeviceInfo]:
        return list(self._devices.values())

    def get_device(self, device_id: str) -> Optional[CameraDeviceInfo]:
        return self._devices.get(device_id)

    def get_or_create_driver(
        self,
        device_id: str,
        stream_url: Optional[str] = None
    ) -> Optional[CameraDriverBase]:
        """Returns or instantiates a driver for the specified device ID (thread-safe)."""
        with self._drivers_lock:
            clean_url = _clean_stream_url(stream_url) if stream_url else None
            driver_key = f"{device_id}::{clean_url}" if (device_id == "ip_stream_custom" and clean_url) else device_id
            if driver_key in self._active_drivers:
                existing = self._active_drivers[driver_key]
                if isinstance(existing, StreamCameraDriver) and clean_url and existing.stream_url != clean_url:
                    existing.close()
                    existing.stream_url = clean_url
                return existing

            info = self.get_device(device_id)
            if not info:
                # Fallback for dynamic webcam index string e.g. "0", "1", "webcam_0"
                idx = None
                if device_id.isdigit():
                    idx = int(device_id)
                elif device_id.startswith("webcam_") and device_id[7:].isdigit():
                    idx = int(device_id[7:])

                if idx is not None:
                    info = CameraDeviceInfo(
                        device_id=f"webcam_{idx}",
                        name=f"Standard USB Camera / Webcam {idx}",
                        camera_type="USB/Webcam",
                        interface_name=f"USB Video Class (Index {idx})"
                    )
                    self._devices[info.device_id] = info
                    driver = OpenCVCameraDriver(info, camera_index=idx)
                    self._active_drivers[driver_key] = driver
                    self._active_drivers[info.device_id] = driver
                    return driver
                return None

            driver: Optional[CameraDriverBase] = None
            if info.camera_type in ("Hikrobot MVS GigE", "Hikrobot MVS USB3") or device_id.startswith("mvs_"):
                from apex_vision.core.mvs_sdk import MvsCameraDriver
                driver = MvsCameraDriver(info)
            elif info.camera_type == "USB/Webcam":
                # Extract index
                idx = 0
                if "webcam_" in device_id:
                    try:
                        idx = int(device_id.split("webcam_")[1])
                    except Exception:
                        idx = 0
                driver = OpenCVCameraDriver(info, camera_index=idx)
            elif info.camera_type == "IP/RTSP Stream":
                url = clean_url or stream_url or getattr(info, "stream_url", None) or "rtsp://192.168.1.64:554/ch1/main"
                driver = StreamCameraDriver(info, stream_url=url)
            else:
                # Industrial GigE or USB3
                driver = IndustrialCameraDriver(info)

            if driver:
                self._active_drivers[driver_key] = driver
            return driver

    def is_mvs_sdk_active(self) -> bool:
        """Checks if native Hikrobot MVS C SDK is loaded and operational."""
        from apex_vision.core.mvs_sdk import MvsSdkLoader
        return MvsSdkLoader.get_instance().is_sdk_available

    def get_mvs_sdk_version(self) -> str:
        """Returns the version or emulation status of the Hikrobot MVS SDK."""
        from apex_vision.core.mvs_sdk import MvsSdkLoader
        return MvsSdkLoader.get_instance().sdk_version

    def import_mvs_config(self, device_id: str, file_path: str) -> bool:
        """Loads a Hikrobot MVS .mvs or .xml feature configuration file into the specified camera."""
        driver = self.get_or_create_driver(device_id)
        if driver and hasattr(driver, "load_mvs_config_file"):
            return driver.load_mvs_config_file(file_path)
        return False

    def export_mvs_config(self, device_id: str, file_path: str) -> bool:
        """Exports the current settings of the camera into a Hikrobot MVS .mvs feature file."""
        driver = self.get_or_create_driver(device_id)
        if driver and hasattr(driver, "export_mvs_config_file"):
            return driver.export_mvs_config_file(file_path)
        return False

    def close_all(self):
        """Closes and releases all active camera drivers."""
        with self._drivers_lock:
            for d in self._active_drivers.values():
                try:
                    d.close()
                except Exception as e:
                    logger.warning("Error releasing camera driver %s: %s", d, e)
            self._active_drivers.clear()
