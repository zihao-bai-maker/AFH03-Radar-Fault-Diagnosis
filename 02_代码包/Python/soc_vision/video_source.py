"""视频源封装：V4L2 设备 / 视频文件 / 图片 / GStreamer 管道 / 合成测试图。

AFH03 上两条路都用同一个接口：
    FPGA 经 MIPI CSI3  -> /dev/video22  1920x1080 YUYV   (pixfmt="YUYV")
    imx415 -> rkisp    -> /dev/video51  1920x1080 NV12   (pixfmt="NV12")

重点：
* `read()` 返回 `Frame`，里面既有 BGR（给算法用），也有 `raw`（原始 YUYV 字节，
  给 fpga_status 解首行嵌入状态字用）。raw 只有在 `pixfmt='YUYV'` 且
  `raw_status=True` 时才有效。
* 设备节点打不开 / 取帧失败时不会抛异常炸掉主循环，而是返回 ok=False，
  由调用者决定重开（见 `reopen_after_fails`）。
"""

from __future__ import annotations

import glob
import os
import time
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

import numpy as np

try:
    import cv2
except Exception as _e:                                     
    cv2 = None                                             
    _CV2_ERR = _e
else:
    _CV2_ERR = None

from .config import VideoCfg

@dataclass
class Frame:
    bgr: np.ndarray                 
    raw: Optional[bytes] = None     
    index: int = 0                  
    ts: float = 0.0                 
    width: int = 0
    height: int = 0

def list_video_nodes() -> List[Tuple[str, str]]:
    """返回 [(节点, 驱动名字)]，用于自动找 FPGA / rkisp 节点。"""
    out: List[Tuple[str, str]] = []
    for namef in sorted(glob.glob("/sys/class/video4linux/video*/name")):
        dev = "/dev/" + os.path.basename(os.path.dirname(namef))
        try:
            with open(namef, "r") as f:
                nm = f.read().strip()
        except OSError:
            nm = ""
        out.append((dev, nm))
    return out

def guess_fpga_node() -> Optional[str]:
    """优先名字里带 milianke/fpga 的节点，其次 /dev/video22。"""
    for dev, nm in list_video_nodes():
        low = nm.lower()
        if "milianke" in low or "fpga" in low:
            return dev
    return "/dev/video22" if os.path.exists("/dev/video22") else None

class VideoSource:
    """统一取帧接口。"""

    def __init__(self, cfg: VideoCfg):
        if cv2 is None:                                     
            raise RuntimeError("cv2 不可用: %s（先跑 bash install_ai_env.sh）" % _CV2_ERR)
        self.cfg = cfg
        self.cap: Any = None
        self.index = 0
        self.fail_count = 0
        self.is_v4l2 = cfg.source.startswith("/dev/video")

    def open(self) -> bool:
        cfg = self.cfg
        if self.cap is not None:
            self.release()

        if cfg.source.startswith("gst:"):
            pipe = cfg.source[4:]
            self.cap = cv2.VideoCapture(pipe, cv2.CAP_GSTREAMER)
        elif cfg.source.startswith("img:"):
            img = cv2.imread(cfg.source[4:], cv2.IMREAD_COLOR)
            if img is None:
                return False
            self._image = img
            self.cap = None
            return True
        elif cfg.source.startswith("file:") or (
                not self.is_v4l2 and os.path.isfile(cfg.source)):
            path = cfg.source[5:] if cfg.source.startswith("file:") else cfg.source
            self.cap = cv2.VideoCapture(path)
        else:
            self.cap = cv2.VideoCapture(cfg.source, cv2.CAP_V4L2)

        if self.cap is None or not self.cap.isOpened():
            return False

        if self.is_v4l2:
            fourcc = {"YUYV": "YUYV", "NV12": "NV12", "BGR": "BGR3"}.get(cfg.pixfmt, "YUYV")
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.height)
            if cfg.fps > 0:
                self.cap.set(cv2.CAP_PROP_FPS, cfg.fps)
            try:
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, cfg.buffersize)
            except Exception:
                pass

            if cfg.pixfmt in ("YUYV", "NV12") and cfg.raw_status:
                try:
                    self.cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
                except Exception:
                    pass

        for _ in range(max(0, cfg.warmup_frames)):
            self.cap.read()
        return True

    def read(self) -> Tuple[bool, Optional[Frame]]:
        if self.cap is None:

            img = getattr(self, "_image", None)
            if img is None:
                return False, None
            self.index += 1
            return True, Frame(img.copy(), None, self.index, time.time(),
                               img.shape[1], img.shape[0])

        ok, data = self.cap.read()
        if not ok or data is None:
            self.fail_count += 1
            return False, None
        self.fail_count = 0
        self.index += 1

        raw: Optional[bytes] = None
        bgr: Optional[np.ndarray] = None

        if data.ndim == 3 and data.shape[2] == 3:

            bgr = data
        elif data.ndim == 2:
            h, w = data.shape[:2]
            if self.cfg.pixfmt == "NV12" or (w == self.cfg.width and h == self.cfg.height * 3 // 2):
                raw = data.tobytes()
                try:
                    bgr = cv2.cvtColor(data.reshape(self.cfg.height * 3 // 2, self.cfg.width),
                                       cv2.COLOR_YUV2BGR_NV12)
                except Exception:
                    bgr = None
            else:

                raw = data.tobytes()
                try:
                    yuyv = data.reshape(self.cfg.height, self.cfg.width, 2)
                    bgr = cv2.cvtColor(yuyv, cv2.COLOR_YUV2BGR_YUYV)
                except Exception:
                    bgr = None
        else:
            bgr = None

        if bgr is None:

            g = np.asarray(data)
            if g.ndim == 2 and g.shape[1] == self.cfg.width * 2:
                g = g[:, : self.cfg.width]
            bgr = cv2.cvtColor(g.astype(np.uint8), cv2.COLOR_GRAY2BGR)

        h, w = bgr.shape[:2]
        return True, Frame(bgr, raw, self.index, time.time(), w, h)

    def need_reopen(self) -> bool:
        return self.fail_count >= max(1, self.cfg.reopen_after_fails)

    def reopen(self) -> bool:
        self.release()
        time.sleep(0.5)
        return self.open()

    def release(self) -> None:
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
        self.cap = None

def make_test_scope_image(width: int = 1000, height: int = 700,
                          freq_div: float = 2.5, vpp_div: float = 3.0,
                          px_per_div_x: float = 100.0, px_per_div_y: float = 80.0,
                          gnd_y: float = 350.0, phase: float = 0.0) -> np.ndarray:
    """画一张"示波器屏幕"合成图：深底 + 网格 + 正弦波形。

    freq_div   : 整个屏幕宽度内的周期数（不是 Hz；Hz 由标定换算）
    vpp_div    : 峰峰值 = vpp_div 个格
    返回 BGR HxWx3（uint8）。用于 tools/selftest_offline.py 做算法冒烟测试。
    """
    if cv2 is None:                                        
        raise RuntimeError("需要 cv2")
    img = np.zeros((height, width, 3), np.uint8)
    img[:] = (30, 20, 15)

    for i in range(0, width, max(1, int(px_per_div_x))):
        cv2.line(img, (i, 0), (i, height), (70, 70, 70), 1)
    for j in range(0, height, max(1, int(px_per_div_y))):
        cv2.line(img, (0, j), (width, j), (70, 70, 70), 1)

    xs = np.arange(width, dtype=np.float64)

    y = gnd_y - (vpp_div / 2.0) * px_per_div_y * np.sin(
        2.0 * np.pi * freq_div * xs / float(width) + phase)
    pts = np.stack([xs, y], axis=1).astype(np.int32)
    cv2.polylines(img, [pts], False, (0, 230, 255), 3, cv2.LINE_AA)
    return img

def _default_rng(seed: int):
    """兼容新旧 numpy：1.17+ 用 default_rng，更老（如 1.15）退回 RandomState。"""
    if hasattr(np.random, "default_rng"):
        return np.random.default_rng(seed)
    return np.random.RandomState(seed)

def make_test_led_image(lit: Tuple[bool, ...] = (True, False, True),
                        rois: Optional[List[Tuple[int, int, int, int]]] = None,
                        width: int = 640, height: int = 240,
                        off_level: int = 25, on_level: int = 235,
                        noise: float = 3.0) -> np.ndarray:
    """画一张"LED 面板"合成图，用于 LED 判定算法的离线自测。"""
    if cv2 is None:                                        
        raise RuntimeError("需要 cv2")
    rng = _default_rng(7)
    img = (np.ones((height, width, 3), np.float32) * 40.0)
    if rois is None:
        rois = []
        for i in range(len(lit)):
            rois.append((60 + i * 180, 80, 90, 90))
    for on, (x, y, w, h) in zip(lit, rois):
        lv = on_level if on else off_level
        img[y:y + h, x:x + w] = lv
    img += rng.normal(0.0, noise, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)
