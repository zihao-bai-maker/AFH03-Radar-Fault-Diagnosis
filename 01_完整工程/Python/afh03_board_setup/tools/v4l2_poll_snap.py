#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v4l2_poll_snap.py —— **自己 poll 的取帧工具：超时自己 STREAMOFF + close，永不依赖外部 kill**。

为什么必须要有它（现场教训）
----------------------------
`v4l2-ctl --stream-mmap` **没有任何内部超时**；一旦设备没在出帧就永久阻塞。
现场做法是外面套 `timeout`——**但 `timeout` 到点会把正在取流的 v4l2-ctl SIGTERM 掉**，
而"在无帧时被 kill 的取流进程"会让 CSI streamoff 走不干净，实测多次把 SoC 拖到卡死/复位
（lead 踩过两次、我也踩过两次）。也就是说 **"套 timeout" 与 "绝不中途 kill" 在无帧场景下本质冲突**，
`rc=124 就中止` 只是事后止损。

本工具的解法是**根治**：
  1. 用 `VIDIOC_REQBUFS(mm, 4)` + `mmap` + `QBUF` + `STREAMON` 自己起流；
  2. 用 `select.poll()` **带超时**等帧 —— 超时就**自己** `STREAMOFF` + `munmap` + `close` 干净退出；
  3. 全程**不被任何外部信号打断**，因此不存在"被 kill 到一半"的状态。

关键细节
--------
* rkcif 是 **multiplanar** 设备 → 必须用 `V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE`(=10)、
  `struct v4l2_pix_format_mplane`、`struct v4l2_buffer.m.planes` + `struct v4l2_plane` 数组。
* `struct v4l2_format` 的 `fmt` 在 **偏移 8**（union 里有指针，8 字节对齐）→ sizeof=**208**，
  不是 204。结构体用 ctypes 声明（对齐规则与 C 一致），`--selfcheck` 会把这些数字打印并断言。
* 只依赖标准库（ctypes/fcntl/mmap/select/struct）。`--png` 才需要 cv2。

用法
----
    # ① 先自检结构体布局（不碰设备，PC 上也能跑）
    python3 tools/v4l2_poll_snap.py --selfcheck

    # ② 空跑：设格式 + 起流 + 立刻停流（不开读，验证 ioctl 链路是否通）
    python3 tools/v4l2_poll_snap.py -d /dev/video22 --dry-run

    # ③ 真正取一帧（默认超时 3000ms；超时自己干净退出，绝不被 kill）
    python3 tools/v4l2_poll_snap.py -d /dev/video22 --out /tmp/f.raw --png /tmp/f.png

    # ④ 顺便做现场判据：0xFF 占比 / 灰阶数 / FPGA 魔数 0xA5C35A00
    python3 tools/v4l2_poll_snap.py -d /dev/video22 --out /tmp/f.raw --report

退出码：0 成功 / 1 参数或自检失败 / 2 打不开设备或格式/缓冲区失败 / 3 **poll 超时（干净退出）** / 4 其它
"""

from __future__ import annotations

import argparse
import ctypes as C
import errno
import mmap
import os
import select
import struct
import sys
import time

try:
    import fcntl
except ImportError:                                               
    fcntl = None                                                  

V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE = 10
V4L2_MEMORY_MMAP = 1
VIDEO_MAX_PLANES = 8
POLLIN = 0x0001

_IOC_NRBITS, _IOC_TYPEBITS, _IOC_SIZEBITS = 8, 8, 14
_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS
_IOC_NONE, _IOC_WRITE, _IOC_READ = 0, 1, 2

def _IOC(direction: int, type_: str, nr: int, size: int) -> int:
    return ((direction << _IOC_DIRSHIFT) | (ord(type_) << _IOC_TYPESHIFT)
            | (nr << _IOC_NRSHIFT) | (size << _IOC_SIZESHIFT))

def _IOWR(type_: str, nr: int, size: int) -> int:
    return _IOC(_IOC_READ | _IOC_WRITE, type_, nr, size)

def _IOW(type_: str, nr: int, size: int) -> int:
    return _IOC(_IOC_WRITE, type_, nr, size)

class v4l2_plane_pix_format(C.Structure):
    _pack_ = 1
    _fields_ = [("sizeimage", C.c_uint32),
                ("bytesperline", C.c_uint32),
                ("reserved", C.c_uint16 * 6)]

class v4l2_pix_format_mplane(C.Structure):
    _pack_ = 1
    _fields_ = [("width", C.c_uint32),
                ("height", C.c_uint32),
                ("pixelformat", C.c_uint32),
                ("field", C.c_uint32),
                ("plane_fmt", v4l2_plane_pix_format * VIDEO_MAX_PLANES),
                ("num_planes", C.c_uint8),
                ("flags", C.c_uint8),
                ("ycbcr_enc", C.c_uint8),
                ("quantization", C.c_uint8),
                ("xfer_func", C.c_uint8),
                ("reserved", C.c_uint8 * 7)]

class _FmtUnion(C.Union):

    
    _fields_ = [("pix_mp", v4l2_pix_format_mplane),
                ("_ptr", C.c_void_p),
                ("raw", C.c_uint8 * 200)]

class v4l2_format(C.Structure):
    _fields_ = [("type", C.c_uint32), ("fmt", _FmtUnion)]

class v4l2_requestbuffers(C.Structure):
    _fields_ = [("count", C.c_uint32),
                ("type", C.c_uint32),
                ("memory", C.c_uint32),
                ("capabilities", C.c_uint32),
                ("reserved", C.c_uint32 * 1)]

class _Timeval(C.Structure):

    _fields_ = [("tv_sec", C.c_int64), ("tv_usec", C.c_int64)]

class v4l2_timecode(C.Structure):
    _fields_ = [("type", C.c_uint32), ("flags", C.c_uint32),
                ("frames", C.c_uint8), ("seconds", C.c_uint8),
                ("minutes", C.c_uint8), ("hours", C.c_uint8),
                ("userbits", C.c_uint8 * 4)]

class v4l2_plane(C.Structure):
    _fields_ = [("bytesused", C.c_uint32),
                ("length", C.c_uint32),
                ("m", C.c_uint64),          
                ("data_offset", C.c_uint32),
                ("reserved", C.c_uint32 * 11)]

class _BufM(C.Union):
    _fields_ = [("offset", C.c_uint32),
                ("userptr", C.c_void_p),
                ("planes", C.POINTER(v4l2_plane)),
                ("fd", C.c_int32)]

class v4l2_buffer(C.Structure):
    _fields_ = [("index", C.c_uint32),
                ("type", C.c_uint32),
                ("bytesused", C.c_uint32),
                ("flags", C.c_uint32),
                ("field", C.c_uint32),
                ("timestamp", _Timeval),
                ("timecode", v4l2_timecode),
                ("sequence", C.c_uint32),
                ("memory", C.c_uint32),
                ("m", _BufM),
                ("length", C.c_uint32),
                ("reserved2", C.c_uint32),
                ("request_fd", C.c_int32)]

VIDIOC_S_FMT = _IOWR("V", 5, C.sizeof(v4l2_format))
VIDIOC_REQBUFS = _IOWR("V", 8, C.sizeof(v4l2_requestbuffers))
VIDIOC_QUERYBUF = _IOWR("V", 9, C.sizeof(v4l2_buffer))
VIDIOC_QBUF = _IOWR("V", 15, C.sizeof(v4l2_buffer))
VIDIOC_DQBUF = _IOWR("V", 17, C.sizeof(v4l2_buffer))
VIDIOC_STREAMON = _IOW("V", 18, C.sizeof(C.c_int))
VIDIOC_STREAMOFF = _IOW("V", 19, C.sizeof(C.c_int))

_MAGIC = 0xA5C35A00

def fourcc(s: str) -> int:
    """'YUYV' -> 小端整数（V4L2 用的是字符顺序）。"""
    b = s.encode("ascii")
    if len(b) != 4:
        raise ValueError("fourcc 必须是 4 个字符: %r" % s)
    return struct.unpack("<I", b)[0]

def fourcc_str(v: int) -> str:
    return struct.pack("<I", v & 0xFFFFFFFF).decode("latin-1")

def selfcheck() -> int:
    exp = {
        "v4l2_plane_pix_format": (C.sizeof(v4l2_plane_pix_format), 20),
        "v4l2_pix_format_mplane": (C.sizeof(v4l2_pix_format_mplane), 188),
        "v4l2_format": (C.sizeof(v4l2_format), 208),
        "v4l2_requestbuffers": (C.sizeof(v4l2_requestbuffers), 20),
        "v4l2_plane": (C.sizeof(v4l2_plane), 64),
        "v4l2_buffer": (C.sizeof(v4l2_buffer), 88),
    }
    print("=== V4L2 结构体布局自检（期望值 = Linux 64 位 ABI）===")
    ok = True
    for name, (got, want) in exp.items():
        flag = "OK " if got == want else "错 "
        if got != want:
            ok = False
        print("  [%s] %-24s size=%-4d 期望=%d" % (flag, name, got, want))

    f = v4l2_format()
    off_fmt = v4l2_format.fmt.offset
    off_pmpp = _FmtUnion.pix_mp.offset
    b = v4l2_buffer()
    offs = {
        "v4l2_format.fmt": (off_fmt, 8),
        "v4l2_format.fmt.pix_mp": (off_pmpp, 0),
        "v4l2_buffer.timestamp": (v4l2_buffer.timestamp.offset, 24),
        "v4l2_buffer.m": (v4l2_buffer.m.offset, 64),
        "v4l2_buffer.length": (v4l2_buffer.length.offset, 72),
    }
    for name, (got, want) in offs.items():
        flag = "OK " if got == want else "错 "
        if got != want:
            ok = False
        print("  [%s] %-32s off=%-4d 期望=%d" % (flag, name, got, want))
    print("  ioctl 号: S_FMT=0x%08X REQBUFS=0x%08X QUERYBUF=0x%08X QBUF=0x%08X DQBUF=0x%08X "
          "STREAMON=0x%08X STREAMOFF=0x%08X"
          % (VIDIOC_S_FMT, VIDIOC_REQBUFS, VIDIOC_QUERYBUF, VIDIOC_QBUF, VIDIOC_DQBUF,
             VIDIOC_STREAMON, VIDIOC_STREAMOFF))
    print("  fourcc('YUYV') = 0x%08X (%s)" % (fourcc("YUYV"), fourcc_str(fourcc("YUYV"))))
    print("结论: %s" % ("结构体布局自检通过" if ok else "结构体布局与期望不符，别上板！"))
    return 0 if ok else 1

class Snapper:
    def __init__(self, dev: str, w: int, h: int, pixfmt: str, buffers: int = 4,
                 verbose: bool = False):
        self.dev = dev
        self.w, self.h, self.pixfmt = w, h, pixfmt
        self.nbuf = buffers
        self.verbose = verbose
        self.fd = -1
        self.maps = []              
        self.streaming = False

    def open(self) -> None:
        if fcntl is None:
            raise RuntimeError("fcntl 不可用：本工具真正取帧只能在 Linux 上跑"
                               "（--selfcheck 可在任意平台跑）")
        try:
            self.fd = os.open(self.dev, os.O_RDWR)
        except OSError as e:
            raise RuntimeError("打不开 %s: %s" % (self.dev, e))
        if self.verbose:
            print("  [v4l2] open %s fd=%d" % (self.dev, self.fd))

    def close(self) -> None:

        try:
            if self.streaming:
                self.streamoff()
        except Exception as e:                                    
            print("  [warn] streamoff 时出错: %s" % e)
        for mp, _ln in self.maps:
            try:
                mp.close()
            except Exception:                                     
                pass
        self.maps.clear()
        if self.fd >= 0:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = -1

    def set_fmt(self) -> dict:
        f = v4l2_format()
        C.memset(C.byref(f), 0, C.sizeof(f))
        f.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
        f.fmt.pix_mp.width = self.w
        f.fmt.pix_mp.height = self.h
        f.fmt.pix_mp.pixelformat = fourcc(self.pixfmt)
        f.fmt.pix_mp.field = 1                   
        try:
            fcntl.ioctl(self.fd, VIDIOC_S_FMT, f)
        except OSError as e:
            raise RuntimeError("VIDIOC_S_FMT 失败(%s): %s —— 该节点可能不支持 %s %dx%d 或不是 multiplanar"
                               % (errno.errorcode.get(e.errno, e.errno), e, self.pixfmt, self.w, self.h))
        pm = f.fmt.pix_mp
        info = {"width": pm.width, "height": pm.height,
                "pixelformat": fourcc_str(pm.pixelformat), "num_planes": pm.num_planes,
                "sizeimage": pm.plane_fmt[0].sizeimage,
                "bytesperline": pm.plane_fmt[0].bytesperline}
        if self.verbose or True:
            print("  [v4l2] 协商格式: %dx%d %s planes=%d sizeimage=%d bpl=%d"
                  % (info["width"], info["height"], info["pixelformat"],
                     info["num_planes"], info["sizeimage"], info["bytesperline"]))
        return info

    def reqbufs(self) -> None:
        rb = v4l2_requestbuffers()
        C.memset(C.byref(rb), 0, C.sizeof(rb))
        rb.count = self.nbuf
        rb.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
        rb.memory = V4L2_MEMORY_MMAP
        try:
            fcntl.ioctl(self.fd, VIDIOC_REQBUFS, rb)
        except OSError as e:
            raise RuntimeError("VIDIOC_REQBUFS 失败: %s" % e)
        if rb.count < 1:
            raise RuntimeError("REQBUFS 返回 count=0（驱动没给缓冲）")
        self.nbuf = rb.count
        if self.verbose:
            print("  [v4l2] REQBUFS ok count=%d" % rb.count)

    def _buf(self, index: int):
        """构造一个带 planes 数组的 v4l2_buffer。"""
        planes = (v4l2_plane * VIDEO_MAX_PLANES)()
        C.memset(C.byref(planes), 0, C.sizeof(planes))
        b = v4l2_buffer()
        C.memset(C.byref(b), 0, C.sizeof(b))
        b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
        b.memory = V4L2_MEMORY_MMAP
        b.index = index
        b.length = VIDEO_MAX_PLANES
        b.m.planes = C.cast(planes, C.POINTER(v4l2_plane))
        return b, planes

    def map_all(self) -> None:
        self.planes_structs = []
        for i in range(self.nbuf):
            b, planes = self._buf(i)
            try:
                fcntl.ioctl(self.fd, VIDIOC_QUERYBUF, b)
            except OSError as e:
                raise RuntimeError("VIDIOC_QUERYBUF(index=%d) 失败: %s" % (i, e))

            ln = planes[0].length
            off = planes[0].m
            if ln <= 0:
                raise RuntimeError("plane0 length=%d 异常" % ln)
            try:
                mp = mmap.mmap(self.fd, ln, prot=mmap.PROT_READ | mmap.PROT_WRITE,
                               flags=mmap.MAP_SHARED, offset=off)
            except OSError as e:
                raise RuntimeError("mmap(index=%d, len=%d, off=%d) 失败: %s" % (i, ln, off, e))
            self.maps.append((mp, ln))
            self.planes_structs.append(planes)
            if self.verbose:
                print("  [v4l2] buf[%d] len=%d off=%d mmap OK" % (i, ln, off))

    def streamon(self) -> None:
        for i in range(self.nbuf):
            b, _p = self._buf(i)
            try:
                fcntl.ioctl(self.fd, VIDIOC_QBUF, b)
            except OSError as e:
                raise RuntimeError("VIDIOC_QBUF(%d) 失败: %s" % (i, e))
        t = C.c_int(V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE)
        try:
            fcntl.ioctl(self.fd, VIDIOC_STREAMON, t)
        except OSError as e:
            raise RuntimeError("VIDIOC_STREAMON 失败: %s" % e)
        self.streaming = True
        if self.verbose:
            print("  [v4l2] STREAMON ok，已排入 %d 个缓冲" % self.nbuf)

    def streamoff(self) -> None:
        t = C.c_int(V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE)
        try:
            fcntl.ioctl(self.fd, VIDIOC_STREAMOFF, t)
            if self.verbose:
                print("  [v4l2] STREAMOFF ok")
        finally:
            self.streaming = False

    def grab(self, timeout_ms: int = 3000):
        po = select.poll()
        po.register(self.fd, POLLIN)
        t0 = time.time()
        evs = po.poll(timeout_ms)
        if not evs:
            print("  [TIMEOUT] poll %d ms 内没有帧 —— **自己干净退出**（STREAMOFF + close），"
                  "没有任何进程被 kill" % timeout_ms)
            return None, None, time.time() - t0
        b, planes = self._buf(0)
        try:
            fcntl.ioctl(self.fd, VIDIOC_DQBUF, b)
        except OSError as e:
            raise RuntimeError("VIDIOC_DQBUF 失败: %s" % e)
        idx = b.index
        ln = planes[0].bytesused or planes[0].length
        data = bytes(self.maps[idx][0][:ln])

        b2, _p2 = self._buf(idx)
        try:
            fcntl.ioctl(self.fd, VIDIOC_QBUF, b2)
        except OSError:
            pass
        return b, data, time.time() - t0

def report_payload(data: bytes) -> None:
    n = len(data) or 1
    ff = data.count(0xff)
    uniq = len(set(data))
    print("  [判据] 原始字节 %d B（期望 1920*1080*2=%d）；0xFF 占比 = %.2f%%；不同字节值 = %d"
          % (len(data), 1920 * 1080 * 2, ff * 100.0 / n, uniq))
    print("         -> %s" % ("[DUMMY] 几乎全 0xFF：FPGA 未配置（rkcif dummy buffer）"
                              if ff * 100.0 / n > 95 else "[REAL] 有分布，像真实图像"))
    le = _MAGIC.to_bytes(4, "little")
    be = _MAGIC.to_bytes(4, "big")
    c_le, c_be = data.count(le), data.count(be)
    print("  [判据] FPGA 魔数 0x%08X：小端=%d 大端=%d -> %s"
          % (_MAGIC, c_le, c_be,
             "**ROI 版 bit（带状态字）**" if (c_le or c_be) else "厂家版 bit（无状态字）"))
    if c_le or c_be:
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from soc_vision.fpga_status import scan_raw_yuyv
            st = scan_raw_yuyv(data)
            print("         scan_raw_yuyv: present=%s layout=%s frame_cnt=%s n_lit=%s lit=%s"
                  % (st.present, st.layout, st.frame_cnt, st.n_lit, st.lit_bits()))
        except Exception as e:                                    
            print("         （scan_raw_yuyv 失败: %s）" % e)

def write_png(raw: bytes, path: str, w: int, h: int, pixfmt: str) -> bool:
    try:
        import cv2
        import numpy as np
    except Exception as e:                                        
        print("  [skip] 没装 cv2/numpy，不出 PNG: %s" % e)
        return False
    try:
        if pixfmt.upper() == "YUYV":
            arr = np.frombuffer(raw[:w * h * 2], np.uint8).reshape(h, w, 2)
            bgr = cv2.cvtColor(arr, cv2.COLOR_YUV2BGR_YUYV)
        elif pixfmt.upper() in ("NV12",):
            arr = np.frombuffer(raw[:w * h * 3 // 2], np.uint8).reshape(h * 3 // 2, w)
            bgr = cv2.cvtColor(arr, cv2.COLOR_YUV2BGR_NV12)
        else:
            print("  [skip] 不认识的 pixelformat，不出 PNG")
            return False
        cv2.imwrite(path, bgr)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        print("  [PNG] %s  灰度 min=%d max=%d mean=%.1f std=%.1f 灰阶=%d 纯白=%.2f%%"
              % (path, gray.min(), gray.max(), gray.mean(), gray.std(),
                 len(np.unique(gray)), (gray >= 250).mean() * 100))
        return True
    except Exception as e:                                        
        print("  [warn] 出 PNG 失败: %s" % e)
        return False

def main() -> int:
    ap = argparse.ArgumentParser(
        description="自 poll 的 V4L2 取帧（超时自己 STREAMOFF+close，永不依赖外部 kill）")
    ap.add_argument("-d", "--dev", default="/dev/video22")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--pixfmt", default="YUYV")
    ap.add_argument("--buffers", type=int, default=4)
    ap.add_argument("--timeout-ms", type=int, default=3000, help="poll 超时（毫秒）")
    ap.add_argument("--out", default="", help="把原始帧写到这个文件")
    ap.add_argument("--png", default="", help="顺便出 PNG（需要 cv2）")
    ap.add_argument("--report", action="store_true", help="打印 0xFF/灰阶/魔数 判据")
    ap.add_argument("--dry-run", action="store_true",
                    help="只做 S_FMT/REQBUFS/mmap/QBUF/STREAMON/STREAMOFF，不读帧（安全验证 ioctl 链路）")
    ap.add_argument("--selfcheck", action="store_true", help="只自检结构体布局，不碰设备")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    if a.selfcheck:
        return selfcheck()

    print("== v4l2_poll_snap: %s  %dx%d %s  timeout=%dms%s =="
          % (a.dev, a.width, a.height, a.pixfmt, a.timeout_ms,
             "  [dry-run]" if a.dry_run else ""))
    snap = Snapper(a.dev, a.width, a.height, a.pixfmt, a.buffers, a.verbose)

    
    CAND = [("YUYV", 1920, 1080), ("NV12", 1920, 1080), ("YUYV", 1280, 720),
            ("NV12", 1280, 720), ("YV12", 640, 480), ("YU12", 640, 480), ("UYVY", 640, 480)]
    try:
        snap.open()
        info = None
        last_err = None
        for (fmt, w, h) in CAND:
            snap.w, snap.h, snap.pixfmt = w, h, fmt
            try:
                info = snap.set_fmt()
                break
            except RuntimeError as e:
                last_err = e
                print("  [try] %s %dx%d 不支持，换下一个" % (fmt, w, h))
        if info is None:
            print("  [ERR] 所有候选格式都被拒: %s" % last_err)
            return 2
        print("  [OK] 协商成功: %dx%d %s" % (info["width"], info["height"], info["pixelformat"]))
        snap.reqbufs()
        snap.map_all()
        snap.streamon()
        if a.dry_run:
            time.sleep(0.2)
            snap.streamoff()
            print("  [dry-run] ioctl 链路全部成功，已干净停流（没有读帧，也没有 kill 任何东西）")
            return 0
        b, data, dt = snap.grab(a.timeout_ms)
        if data is None:
            return 3
        print("  [OK] 取到 1 帧：index=%d 长度=%d B 耗时=%.3fs  sequence=%d"
              % (b.index, len(data), dt, b.sequence))
        fmt = snap.pixfmt.upper()
        exp = {"YUYV": snap.w * snap.h * 2, "UYVY": snap.w * snap.h * 2, "NV12": snap.w * snap.h * 3 // 2,
               "YV12": snap.w * snap.h * 3 // 2, "YU12": snap.w * snap.h * 3 // 2}.get(fmt, snap.w * snap.h * 2)
        if len(data) < exp:
            print("  [warn] 帧长度 %d < 期望 %d（可能只拿到部分平面/行）" % (len(data), exp))
        if a.out:
            with open(a.out, "wb") as f:
                f.write(data)
            print("  [写] %s (%d B)" % (a.out, len(data)))
        if a.report or a.out:
            report_payload(data)
        if a.png:
            write_png(data, a.png, snap.w, snap.h, fmt)
        return 0
    except RuntimeError as e:
        print("  [ERR] %s" % e)
        return 2
    except KeyboardInterrupt:
        print("\n  [INT] 收到 Ctrl+C，走正常收尾（STREAMOFF + close）")
        return 4
    finally:
        snap.close()
        print("  [clean] 已 STREAMOFF + munmap + close（无外部 kill）")

if __name__ == "__main__":
    raise SystemExit(main())
