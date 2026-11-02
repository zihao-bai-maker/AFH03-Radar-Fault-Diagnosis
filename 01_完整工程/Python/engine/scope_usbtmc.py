#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scope_usbtmc.py — 同一套"关键参数采集"走 USB-A-B（USBTMC，板端 /dev/usbtmc0）

硬件链路（用户已确认可用）：
    板子 USB 主机口 SOC_USB2.0_1/2  ──USB-A-B──  示波器方口
    示波器 UTILITY → IO Setting → USB → 选 **USBTMC**
    板端出现 /dev/usbtmc0（内核 usbtmc 模块 + usbtmc 权限）

协议安全与 scope_lan.py 完全一致（复用同一个 `ScpiSession`）：
    单会话 / 命令间隔 ≥300 ms / 单条超时 3 s / 空返回或超时立刻断链 /
    整会话最多重建 2 次（间隔 2 s）/ 只发查询，绝不发 :WAVeform:DATA?。

用法（在板子上）：
    python3 scope_usbtmc.py --list                  # 看有没有 /dev/usbtmc*
    python3 scope_usbtmc.py --selfcheck             # 只发 *IDN? 自检
    python3 scope_usbtmc.py --only 1 15             # 只测 10M 相承基准（I/II 路）
    python3 scope_usbtmc.py --out /tmp/scope_ev.json --report /tmp/scope_rep.json
"""

from __future__ import annotations

import glob
import os
import select
import sys
import time

from scope_lan import (  
    CMD_TIMEOUT_S,
    MAX_LINE_BYTES,
    InstrumentUnresponsive,
    ProbeFailed,
    ProtocolViolation,
    ScpiSession,
    parse_idn,
)

CANDIDATE_GLOBS = ("/dev/usbtmc*",)

def find_usbtmc_devices():
    found = []
    for pat in CANDIDATE_GLOBS:
        found.extend(sorted(glob.glob(pat)))

    seen, out = set(), []
    for p in found:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out

class UsbTmcTransport:
    """基于 /dev/usbtmcN 的最简 USBTMC 传输：写 "命令\\n"，读到 '\\n' 为止。"""

    kind = "usbtmc"

    def __init__(self, path=None, timeout=CMD_TIMEOUT_S):
        self.path = path
        self.timeout = float(timeout)
        self._fd = None
        self._sel_ok = None
        self.peer = path or "(auto)"

    def open(self):
        self.close()
        self._sel_ok = None
        if os.name == "nt":
            raise ProbeFailed("Windows 上没有 /dev/usbtmc*；USBTMC 只能在板子(Linux)上跑",
                              retryable=False)

        path = self.path
        if not path:
            cands = find_usbtmc_devices()
            if not cands:
                raise ProbeFailed(
                    "未发现 /dev/usbtmc*：请确认 1) 示波器 UTILITY→IO Setting→USB 已选 USBTMC；"
                    "2) USB-A-B 线插在板子 SOC_USB2.0 主机口；3) 板端有 usbtmc 内核模块",
                    retryable=False)
            path = cands[0]
            self.path = path
        try:
            fd = os.open(path, os.O_RDWR | getattr(os, "O_NONBLOCK", 0))
        except OSError as e:
            raise ProbeFailed("打开 %s 失败：%s（检查权限：usbtmc 通常需要 root 或 udev 规则）"
                              % (path, e), retryable=False)
        try:
            os.set_blocking(fd, False)
        except (AttributeError, OSError):
            pass
        self._fd = fd
        self.peer = path
        return self

    def close(self):
        fd, self._fd = self._fd, None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    @property
    def is_open(self):
        return self._fd is not None

    def send(self, text: str):
        if self._fd is None:
            raise InstrumentUnresponsive("usbtmc 未打开")
        data = text.encode("ascii") + b"\n"
        try:
            n = os.write(self._fd, data)
        except OSError as e:
            self.close()
            raise InstrumentUnresponsive("写入 %s 失败：%s" % (self.peer, e))
        if n != len(data):
            self.close()
            raise ProtocolViolation("USBTMC 短写 %d/%d 字节" % (n, len(data)))

    def _wait_readable(self, remain):
        """等 fd 可读。Linux 字符设备走 select；无 select 支持的 fd 退化为忙轮询。"""
        if self._sel_ok is None:
            try:
                select.select([self._fd], [], [], 0)
                self._sel_ok = True
            except (OSError, ValueError):
                self._sel_ok = False
        if self._sel_ok:
            ready, _, _ = select.select([self._fd], [], [], min(remain, 0.2))
            return bool(ready)
        time.sleep(min(0.01, max(0.0, remain)))
        return True

    def read_line(self, timeout=None) -> str:
        if self._fd is None:
            raise InstrumentUnresponsive("usbtmc 未打开")
        deadline = time.monotonic() + (self.timeout if timeout is None else float(timeout))
        buf = b""
        while True:
            remain = deadline - time.monotonic()
            if remain <= 0:
                self.close()
                raise InstrumentUnresponsive("USBTMC 读超时 %.1fs" % self.timeout)
            try:
                if not self._wait_readable(remain):
                    continue
            except OSError as e:
                self.close()
                raise InstrumentUnresponsive("select 失败：%s" % e)
            try:
                chunk = os.read(self._fd, 256)
            except BlockingIOError:
                continue
            except OSError as e:
                self.close()
                raise InstrumentUnresponsive("读取失败：%s" % e)
            if not chunk:

                time.sleep(0.01)
                continue
            buf += chunk
            if b"\n" in buf:
                line = buf.split(b"\n", 1)[0]
                return line.decode("ascii", "replace").strip()
            if len(buf) > MAX_LINE_BYTES:
                self.close()
                raise ProtocolViolation(
                    "响应超过 %d 字节，疑似误发深存储命令，已强制断链" % MAX_LINE_BYTES)

def probe_idn(path=None, timeout=CMD_TIMEOUT_S):
    """只做 *IDN? 自检，返回 dict。失败抛异常。"""
    tr = UsbTmcTransport(path=path, timeout=timeout)
    s = ScpiSession(tr, timeout=timeout)
    try:
        info = s.open_and_ping()
        return {"ok": True, "idn": info, "path": tr.peer, "cmds": s.n_cmds}
    finally:
        s.close()

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    if "--list" in argv:
        devs = find_usbtmc_devices()
        print("found=%d" % len(devs))
        for d in devs:
            try:
                st = os.stat(d)
                print("  %s  mode=%o  rdev=%s" % (d, st.st_mode, st.st_rdev))
            except OSError as e:
                print("  %s  (stat 失败: %s)" % (d, e))
        return 0 if devs else 3

    if "--selfcheck" in argv:
        t0 = time.monotonic()
        try:
            r = probe_idn(timeout=CMD_TIMEOUT_S)
        except Exception as e:
            print("SELFCHECK FAIL  %s: %s" % (type(e).__name__, e))
            return 4
        dt = (time.monotonic() - t0) * 1000.0
        print("SELFCHECK OK  path=%s  cmds=%d  %.0fms" % (r["path"], r["cmds"], dt))
        print("*IDN? → %s" % r["idn"]["raw"])
        print("        vendor=%s model=%s fw=%s is_ds2102a=%s"
              % (r["idn"]["vendor"], r["idn"]["model"],
                 r["idn"]["firmware"], r["idn"]["is_ds2102a"]))
        return 0

    from scope_lan import main as lan_main
    if "--io" in argv:
        i = argv.index("--io")
        argv[i + 1] = "usbtmc"
    else:
        argv = ["--io", "usbtmc"] + argv
    return lan_main(argv)

if __name__ == "__main__":
    sys.exit(main())
