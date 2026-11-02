#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""touch_input.py —— 板载触摸输入（**多点触控协议 B / ABS_MT_***），带可见反馈与逐事件日志。

现场教训（2026-10-04，用户点【拍照】没反应）
--------------------------------------------
本板触摸是 **`goodix-ts` @ `/dev/input/event3`**，实测：
* `EVIOCGABS(ABS_X=0)` / `(ABS_Y=1)` → **无此能力**（`/proc/bus/input/devices` 里 `PROP=2`、`ABS=265000000000000`）
* `KEY` 位图里**没有 `BTN_TOUCH(330)`** → 只报 `BTN_TOUCH` 的旧写法**永远不会触发**
* 它用 **MT 协议 B**：`ABS_MT_SLOT(0x2f)` / `ABS_MT_TRACKING_ID(0x39)`（**-1 = 抬手**） /
  `ABS_MT_POSITION_X(0x35)` / `ABS_MT_POSITION_Y(0x36)`

所以正确做法：**跟踪 TRACKING_ID 判断按下/抬起**，坐标取 `ABS_MT_POSITION_X/Y`（并兼容 `ABS_X/Y` 与
`ABS_PRESSURE`），按下/抬起各触发一次但**去抖成一次 tap**；坐标按设备实际范围缩放到窗口。

诊断
----
    python3 -m soc_vision.touch_input --dump --seconds 8     # 打印该设备的能力/范围 + 逐条事件
"""

from __future__ import annotations

import fcntl
import os
import struct
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

EV_SYN, EV_KEY, EV_ABS, EV_MSC = 0, 1, 3, 4
ABS_X, ABS_Y, ABS_PRESSURE = 0x00, 0x01, 0x18
ABS_MT_SLOT, ABS_MT_POSITION_X, ABS_MT_POSITION_Y, ABS_MT_TRACKING_ID = 0x2F, 0x35, 0x36, 0x39
BTN_TOUCH = 0x14A
STRUCT = "llHHi"                       
_EVIOCGABS = 0x80184540                
_EVIOCGNAME = 0x80FF4506

def _absinfo(fd: int, axis: int):
    try:
        b = bytearray(24)
        fcntl.ioctl(fd, _EVIOCGABS + axis, b)
        v, mn, mx, fz, fl, res = struct.unpack("iiiiii", bytes(b))
        return {"value": v, "min": mn, "max": mx, "fuzz": fz, "flat": fl, "res": res}
    except Exception:                                              
        return None

def _devname(fd: int) -> str:
    try:
        b = bytearray(256)
        fcntl.ioctl(fd, _EVIOCGNAME, b)
        return bytes(b).split(b"\x00")[0].decode("utf-8", "replace")
    except Exception:                                              
        return "?"

@dataclass
class TouchTrace:
    """现场诊断用：最近若干条事件 + 统计。"""
    events: List[str] = field(default_factory=list)
    n_abs: int = 0
    n_key: int = 0
    n_syn: int = 0
    n_tap: int = 0

    def add(self, line: str, keep: int = 40) -> None:
        self.events.append(line)
        if len(self.events) > keep:
            del self.events[: len(self.events) - keep]

class TouchScreen:
    """MT 协议 B 触摸（自动探测设备与坐标范围）。`poll()` 返回"(x,y,tap)" 或 None。"""

    def __init__(self, dev: str = "/dev/input/event3", win_w: int = 1024, win_h: int = 600,
                 max_x: int = 0, max_y: int = 0, verbose: bool = True):
        self.dev = dev
        self.win_w, self.win_h = int(win_w), int(win_h)
        self.fd = -1
        self.name = ""
        self.verbose = verbose
        self.trace = TouchTrace()

        self.x = self.y = -1
        self.raw_x = self.raw_y = -1
        self.pressure = 0
        self.down = False
        self.taps = 0
        self.last_hit = ""
        self.last_tap_xy: Optional[Tuple[int, int]] = None
        self.max_x = int(max_x) or 0
        self.max_y = int(max_y) or 0
        self.open()

    def open(self) -> bool:
        try:
            self.fd = os.open(self.dev, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as e:
            self.warn = "触摸打不开 %s: %s" % (self.dev, e)
            print("[touch] %s" % self.warn, flush=True)
            self.fd = -1
            return False
        self.name = _devname(self.fd)
        ax = _absinfo(self.fd, ABS_MT_POSITION_X)
        ay = _absinfo(self.fd, ABS_MT_POSITION_Y)
        if not self.max_x:
            self.max_x = (ax or {}).get("max") or (_absinfo(self.fd, ABS_X) or {}).get("max") or self.win_w
        if not self.max_y:
            self.max_y = (ay or {}).get("max") or (_absinfo(self.fd, ABS_Y) or {}).get("max") or self.win_h
        self.has_btn_touch = bool(_absinfo(self.fd, ABS_PRESSURE)) or False
        self.warn = ""
        print("[touch] 打开 %s name=%r MT_X范围=%s MT_Y范围=%s -> 缩放 %dx%d"
              % (self.dev, self.name, (ax or {}).get("max"), (ay or {}).get("max"),
                 self.max_x, self.max_y), flush=True)
        return True

    def poll(self):
        """读一轮事件；返回 (x, y) 表示**一次点击**（已按窗口缩放），否则 None。"""
        if self.fd < 0:
            return None
        try:
            data = os.read(self.fd, 24 * 256)
        except (BlockingIOError, OSError):
            return None
        if not data:
            return None
        tap = None
        slot_x, slot_y = {}, {}
        cur = 0
        for i in range(len(data) // 24):
            _s, _us, typ, code, val = struct.unpack(STRUCT, data[i * 24:(i + 1) * 24])
            if typ == EV_SYN:
                self.trace.n_syn += 1
                continue
            if typ == EV_ABS:
                self.trace.n_abs += 1
                if code == ABS_MT_SLOT:
                    cur = int(val)
                elif code == ABS_MT_POSITION_X:
                    self.raw_x = int(val); slot_x[cur] = int(val)
                elif code == ABS_MT_POSITION_Y:
                    self.raw_y = int(val); slot_y[cur] = int(val)
                elif code == ABS_X:
                    self.raw_x = int(val)
                elif code == ABS_Y:
                    self.raw_y = int(val)
                elif code == ABS_PRESSURE:
                    self.pressure = int(val)
                    if not self.down:
                        self.down = True                       
                elif code == ABS_MT_TRACKING_ID:
                    if int(val) >= 0:
                        if not self.down:
                            self.down = True
                    else:                                      
                        self.down = False
                        tap = self._emit("lift")
                if self.verbose and self.trace.n_abs <= 6:
                    self.trace.add("ABS code=%d val=%d raw=(%d,%d)" % (code, val, self.raw_x, self.raw_y))
            elif typ == EV_KEY:
                self.trace.n_key += 1
                if code == BTN_TOUCH:
                    self.down = bool(val)
                    if val:
                        pass
                    else:
                        tap = self._emit("btn-up")
                if self.verbose:
                    self.trace.add("KEY code=%d val=%d" % (code, val))

        if tap is None and self.down and self.pressure == 0 and self.trace.n_key == 0:
            pass
        if tap is None and self.raw_x >= 0 and not self.down and self.trace.n_tap == self.taps:

            pass
        return tap

    def _map(self):
        mx = self.raw_x if self.raw_x >= 0 else 0
        my = self.raw_y if self.raw_y >= 0 else 0
        x = int(round(mx * self.win_w / max(1, self.max_x)))
        y = int(round(my * self.win_h / max(1, self.max_y)))
        return max(0, min(self.win_w - 1, x)), max(0, min(self.win_h - 1, y))

    def _emit(self, why: str):
        if self.raw_x < 0 or self.raw_y < 0:
            self.trace.add("tap(%s) 但无坐标 -> 丢弃" % why)
            return None
        x, y = self._map()
        self.taps += 1
        self.last_tap_xy = (x, y)
        self.trace.n_tap = self.taps
        line = "TAP#%d(%s) raw=(%d,%d) 屏幕=(%d,%d)" % (self.taps, why, self.raw_x, self.raw_y, x, y)
        self.trace.add(line)
        if self.verbose:
            print("[touch] %s" % line, flush=True)
        return (x, y)

    def close(self):
        if self.fd >= 0:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = -1

def dump(dev: str = "/dev/input/event3", seconds: float = 8.0) -> int:
    """诊断：打印设备能力/范围 + N 秒内的逐条原始事件（请在这段时间点屏幕）。"""
    try:
        fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
    except OSError as e:
        print("打不开 %s: %s" % (dev, e))
        return 2
    print("== %s name=%r ==" % (dev, _devname(fd)))
    for ax, label in ((ABS_X, "ABS_X"), (ABS_Y, "ABS_Y"), (ABS_PRESSURE, "ABS_PRESSURE"),
                      (ABS_MT_SLOT, "ABS_MT_SLOT"), (ABS_MT_POSITION_X, "ABS_MT_POSITION_X"),
                      (ABS_MT_POSITION_Y, "ABS_MT_POSITION_Y"), (ABS_MT_TRACKING_ID, "ABS_MT_TRACKING_ID")):
        info = _absinfo(fd, ax)
        print("   %-20s %s" % (label, ("min=%d max=%d res=%d" % (info["min"], info["max"], info["res"]))
                               if info else "（该设备没有这个轴）"))
    print("== 开始收事件 %.0f 秒（请点屏幕）==" % seconds)
    kinds = {EV_SYN: "EV_SYN", EV_KEY: "EV_KEY", EV_ABS: "EV_ABS", EV_MSC: "EV_MSC"}
    t0, n = time.time(), 0
    while time.time() - t0 < seconds:
        try:
            data = os.read(fd, 24 * 256)
        except (BlockingIOError, OSError):
            time.sleep(0.03)
            continue
        for i in range(len(data) // 24):
            _s, _us, typ, code, val = struct.unpack(STRUCT, data[i * 24:(i + 1) * 24])
            n += 1
            if typ == EV_SYN:
                continue
            print("   t=%.2f %-7s code=%-4d value=%d" % (time.time() - t0, kinds.get(typ, typ), code, val))
    print("== 共 %d 条非 SYN 事件；0 条 = 没收到触摸（设备不对或未点）==" % n)
    os.close(fd)
    return 0

def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="触摸输入（MT 协议 B）+ 诊断")
    ap.add_argument("--dump", action="store_true", help="打印能力/范围 + 逐条事件")
    ap.add_argument("--dev", default="/dev/input/event3")
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--live", action="store_true", help="实时打印 tap（映射后坐标）")
    a = ap.parse_args(argv)
    if a.dump:
        return dump(a.dev, a.seconds)
    if a.live:
        ts = TouchScreen(a.dev, 1024, 600)
        t0 = time.time()
        while time.time() - t0 < a.seconds:
            r = ts.poll()
            if r:
                print("tap -> %s" % (r,), flush=True)
            time.sleep(0.02)
        ts.close()
        return 0
    ap.print_help()
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
