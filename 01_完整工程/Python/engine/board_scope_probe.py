#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
board_scope_probe.py — 板端只读探针（RIGOL DS2102A）

用途：在**板子**上验证两条链路到底哪条能读到关键参数，并把实测值/失败模式打出来。
  1) LAN  ：end1(192.168.1.10/24) → 示波器 192.168.1.20:5555
  2) USBTMC：板子 USB 主机口 → USB-A-B → 示波器方口 → /dev/usbtmc0

这个脚本**故意不 import 仓库里的任何模块**（板子上可能只拷了这一个文件），
但协议安全策略与 engine/scope_lan.py 完全一致：
    * 单连接、串行、命令间 ≥300 ms
    * 每条命令 3 s 超时；超时/空返回 ⇒ 立刻断开，判"仪器无响应"
    * 整会话最多重建 2 次（间隔 2 s）
    * **只发查询**；绝不发 :WAVeform:DATA? / 深存储 / RAW

它**不**做任何破坏性动作：不 reboot、不重启服务、不写仪器设置（除非显式 --enable-measure）、
不碰相机、不碰 FLASH。

用法（板上）：
    sudo python3 board_scope_probe.py --env               # 只看环境（最安全）
    sudo python3 board_scope_probe.py --via usbtmc        # 只测 USB-TMC
    sudo python3 board_scope_probe.py --via lan           # 只测网口
    sudo python3 board_scope_probe.py --via both --json /tmp/probe.json

退出码：0=全通  2=环境问题  3=LAN 失败  4=USBTMC 失败  5=读到了 IDN 但参数读不到
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import select
import socket
import sys
import time

MIN_GAP_S = 0.30
TIMEOUT_S = 3.0
CONNECT_TIMEOUT_S = 3.0
RETRY_LIMIT = 2
RETRY_BACKOFF_S = 2.0
MAX_BYTES = 8192

DEFAULT_HOST = "192.168.1.20"
DEFAULT_PORT = 5555

PROBE_CMDS = [
    ("*IDN?", "idn"),
    (":MEASure:ITEM? FREQuency", "freq_hz"),
    (":MEASure:ITEM? VPP", "vpp_v"),
    (":CHANnel1:SCALe?", "ch1_scale_v_per_div"),
    (":TIMebase:SCALe?", "timebase_s_per_div"),
    (":TRIGger:STATus?", "trigger_status"),
]

FORBIDDEN = ("WAV", "DATA?", ":DATA", "STOR", "MASS", "DISK", "RECAL", "SAVE",
             "*RST", "PRES", ":RUN", ":STOP", ":SING", "AUTO", "FUNC", ";")

class ProbeError(Exception):
    RETRYABLE = ("E_CONNECT", "E_OPEN", "E_SEND")   

    def __init__(self, code, msg, advice="", retryable=None):
        Exception.__init__(self, msg)
        self.code = code
        self.msg = msg
        self.advice = advice
        self.retryable = (code in self.RETRYABLE) if retryable is None else bool(retryable)

def check_cmd(cmd):
    flat = cmd.replace(" ", "").upper()
    for tok in FORBIDDEN:
        if tok in flat:
            raise ProbeError("E_FORBIDDEN", "拒绝发送危险命令：%r" % cmd)
    if "?" not in cmd:
        raise ProbeError("E_FORBIDDEN", "只允许查询命令：%r" % cmd)

def parse_num(text):
    if text is None:
        return None, "empty"
    s = str(text).strip().strip('"')
    if not s:
        return None, "empty"
    if "*" in s:
        return None, "star"
    m = re.match(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?", s)
    if not m:
        return None, "unparsable"
    v = float(m.group(0))
    if abs(v) >= 9.0e36:
        return None, "sentinel"
    return v, "ok"

class LanIO:
    kind = "lan"

    def __init__(self, host, port, timeout=TIMEOUT_S):
        self.host, self.port, self.timeout = host, int(port), timeout
        self.s = None
        self.buf = b""

    def open(self):
        self.close()
        try:
            self.s = socket.create_connection((self.host, self.port),
                                              timeout=CONNECT_TIMEOUT_S)
            self.s.settimeout(self.timeout)
        except OSError as e:
            raise ProbeError("E_CONNECT", "TCP %s:%d 连接失败：%s" % (self.host, self.port, e),
                             "检查：板端 end1 是否 up、IP 是否 192.168.1.10/24、"
                             "ping 192.168.1.20、示波器是否上电")
        self.buf = b""

    def close(self):
        if self.s is not None:
            try:
                self.s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.s.close()
            except OSError:
                pass
            self.s = None
        self.buf = b""

    def send(self, cmd):
        try:
            self.s.sendall(cmd.encode("ascii") + b"\n")
        except OSError as e:
            self.close()
            raise ProbeError("E_SEND", "发送失败：%s" % e)

    def readline(self):
        deadline = time.monotonic() + self.timeout
        while b"\n" not in self.buf:
            remain = deadline - time.monotonic()
            if remain <= 0:
                self.close()
                raise ProbeError("E_TIMEOUT", "读超时 %.1fs（无 \\n）" % self.timeout,
                                 "仪器无响应 ⇒ 先断开、别再发；若持续如此需对示波器断电重启")
            self.s.settimeout(remain)
            try:
                chunk = self.s.recv(1024)
            except socket.timeout:
                self.close()
                raise ProbeError("E_TIMEOUT", "读超时 %.1fs" % self.timeout,
                                 "仪器无响应 ⇒ 需断电重启示波器")
            except OSError as e:
                self.close()
                raise ProbeError("E_RECV", "接收失败：%s" % e)
            if not chunk:
                self.close()
                raise ProbeError("E_CLOSED", "对端关闭连接（仪器可能已挂死）")
            self.buf += chunk
            if len(self.buf) > MAX_BYTES:
                self.close()
                raise ProbeError("E_OVERSIZE", "响应超过 %d 字节，已强制断链" % MAX_BYTES)
        line, _, self.buf = self.buf.partition(b"\n")
        return line.decode("ascii", "replace").strip()

class UsbIO:
    kind = "usbtmc"

    def __init__(self, path=None, timeout=TIMEOUT_S):
        self.path, self.timeout = path, timeout
        self.fd = None
        self.sel_ok = None
        self.buf = b""

    @staticmethod
    def find():
        return sorted(glob.glob("/dev/usbtmc*"))

    def open(self):
        self.close()
        path = self.path
        if not path:
            cands = self.find()
            if not cands:
                raise ProbeError(
                    "E_NO_DEVICE", "没有 /dev/usbtmc*",
                    "1) 示波器 UTILITY→IO Setting→USB 选 USBTMC；"
                    "2) USB-A-B 插在板子 SOC_USB2.0_1/2；3) lsmod | grep usbtmc；"
                    "4) 必要时 modprobe usbtmc（只加载驱动，不重启）")
            path = cands[0]
            self.path = path
        try:
            self.fd = os.open(path, os.O_RDWR | getattr(os, "O_NONBLOCK", 0))
        except PermissionError as e:
            raise ProbeError("E_PERM", "打开 %s 权限不足：%s" % (path, e),
                             "用 sudo 运行，或加 udev 规则给 usbtmc 读写权限")
        except OSError as e:
            raise ProbeError("E_OPEN", "打开 %s 失败：%s" % (path, e))
        try:
            os.set_blocking(self.fd, False)
        except (AttributeError, OSError):
            pass
        self.buf = b""
        self.sel_ok = None

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        self.buf = b""

    def send(self, cmd):
        data = cmd.encode("ascii") + b"\n"
        try:
            n = os.write(self.fd, data)
        except OSError as e:
            self.close()
            raise ProbeError("E_SEND", "USBTMC 写入失败：%s" % e)
        if n != len(data):
            self.close()
            raise ProbeError("E_SEND", "USBTMC 短写 %d/%d" % (n, len(data)))

    def readline(self):
        deadline = time.monotonic() + self.timeout
        while b"\n" not in self.buf:
            remain = deadline - time.monotonic()
            if remain <= 0:
                self.close()
                raise ProbeError("E_TIMEOUT", "USBTMC 读超时 %.1fs" % self.timeout,
                                 "仪器无响应 ⇒ 需断电重启示波器，或换 LAN 试试")
            if self.sel_ok is None:
                try:
                    select.select([self.fd], [], [], 0)
                    self.sel_ok = True
                except (OSError, ValueError):
                    self.sel_ok = False
            if self.sel_ok:
                ready, _, _ = select.select([self.fd], [], [], min(remain, 0.2))
                if not ready:
                    continue
            else:
                time.sleep(min(0.01, remain))
            try:
                chunk = os.read(self.fd, 256)
            except BlockingIOError:
                continue
            except OSError as e:
                self.close()
                raise ProbeError("E_RECV", "USBTMC 读取失败：%s" % e)
            if not chunk:
                time.sleep(0.01)
                continue
            self.buf += chunk
            if len(self.buf) > MAX_BYTES:
                self.close()
                raise ProbeError("E_OVERSIZE", "响应超过 %d 字节，已强制断链" % MAX_BYTES)
        line, _, self.buf = self.buf.partition(b"\n")
        return line.decode("ascii", "replace").strip()

def run_probe(io, enable_measure=False):
    """一个传输上跑完整探针；返回 (ok, result)。任何异常都转成失败模式。"""
    res = {"io": io.kind, "peer": getattr(io, "peer", None) or
           getattr(io, "path", None) or getattr(io, "host", None) or "(auto)",
           "ok": False, "idn": None, "readings": {}, "raw": {}, "error": None,
           "advice": "", "ms": None}
    t0 = time.monotonic()
    sess_attempts = 0
    try:
        last = None
        for attempt in range(RETRY_LIMIT + 1):
            if attempt:
                time.sleep(RETRY_BACKOFF_S)
                sess_attempts += 1
            try:
                io.open()
                last = None
                break
            except ProbeError as e:
                last = e
                if not e.retryable:
                    break                      
        if last is not None:
            raise last

        prev = 0.0
        if enable_measure:

            io.send(":MEASure:ITEM FREQuency")
            time.sleep(MIN_GAP_S)

        for cmd, key in PROBE_CMDS:
            check_cmd(cmd)
            gap = time.monotonic() - prev
            if gap < MIN_GAP_S:
                time.sleep(MIN_GAP_S - gap)
            io.send(cmd)
            raw = io.readline()
            prev = time.monotonic()
            res["raw"][key] = raw
            if raw == "" and key != "idn":
                raise ProbeError("E_EMPTY", "空返回：%s" % cmd,
                                 "检查是否选中了正确通道 / 测量项未开启（可试 --enable-measure）")
            if raw.startswith("-") and "," in raw and key != "idn":
                raise ProbeError("E_SCPI_ERROR", "仪器返回错误：%s" % raw,
                                 "该固件可能不支持此命令写法，改用 --dialect short 试 :MEAS:ITEM? FREQ")
            if key == "idn":
                res["idn"] = raw
                if not raw:
                    raise ProbeError("E_IDN", "*IDN? 空返回")
            elif key == "trigger_status":
                res["readings"][key] = raw          
            else:
                val, reason = parse_num(raw)
                res["readings"][key] = val
                if val is None:
                    res["readings"][key + "_reason"] = reason
        res["ok"] = True
    except ProbeError as e:
        res["error"] = e.code
        res["advice"] = e.advice
        res["raw"]["exception"] = e.msg
    except Exception as e:                                   
        res["error"] = "E_UNEXPECTED"
        res["raw"]["exception"] = "%s: %s" % (type(e).__name__, e)
    finally:
        io.close()
        res["ms"] = int((time.monotonic() - t0) * 1000)
        res["session_retries"] = sess_attempts
    return res["ok"], res

def env_report():
    rep = {"python": sys.version.split()[0], "kernel": None,
           "usbtmc_devices": UsbIO.find(), "end1": {}, "ip_route": None}
    try:
        rep["kernel"] = os.uname().release
    except AttributeError:
        rep["kernel"] = "(非 Linux，板子上才有 /dev/usbtmc*)"
    for key, path in (("operstate", "/sys/class/net/end1/operstate"),
                      ("mac", "/sys/class/net/end1/address"),
                      ("speed", "/sys/class/net/end1/speed")):
        try:
            rep["end1"][key] = open(path).read().strip()
        except OSError as e:
            rep["end1"][key] = "ERROR:%s" % e.__class__.__name__
    try:
        import subprocess
        rep["end1"]["addr"] = subprocess.run(
            ["ip", "-4", "-br", "addr", "show", "end1"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=5).stdout.decode("utf-8", "replace").strip()
    except Exception:
        rep["end1"]["addr"] = "(ip 命令不可用)"
    return rep

def main(argv=None):
    ap = argparse.ArgumentParser(description="板端示波器只读探针（LAN / USBTMC）")
    ap.add_argument("--via", choices=("lan", "usbtmc", "both"), default="both")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--usbtmc", default=None, help="指定 /dev/usbtmcN（默认自动）")
    ap.add_argument("--enable-measure", action="store_true",
                    help="[写] 发一次 :MEASure:ITEM FREQuency 打开测量项")
    ap.add_argument("--env", action="store_true", help="只打印环境，不连仪器")
    ap.add_argument("--json", default=None, help="把结果写成 JSON")
    args = ap.parse_args(argv)

    out = {"tool": "board_scope_probe.py", "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "via": args.via, "env": env_report(), "results": []}

    if args.env:
        print(json.dumps(out["env"], ensure_ascii=False, indent=2))
        if args.json:
            open(args.json, "w", encoding="utf-8").write(
                json.dumps(out, ensure_ascii=False, indent=2) + "\n")
        return 0

    targets = []
    if args.via in ("lan", "both"):
        targets.append("lan")
    if args.via in ("usbtmc", "both"):
        targets.append("usbtmc")

    worst = 0
    for kind in targets:
        if kind == "lan":
            io = LanIO(args.host, args.port)
        else:
            io = UsbIO(path=args.usbtmc)
        ok, res = run_probe(io, enable_measure=args.enable_measure)
        out["results"].append(res)

        print("=" * 72)
        print("[%s] peer=%s  %s  (%d ms)" % (kind, res["peer"],
                                             "OK" if ok else "FAIL " + str(res["error"]),
                                             res["ms"]))
        for k, v in res["raw"].items():
            if k == "exception":
                print("   ! %s" % v)
            else:
                print("   %-22s %r" % (k, v))
        if ok:
            r = res["readings"]
            print("   → IDN : %s" % res["idn"])
            print("   → FREQ: %s   VPP: %s   CH1: %s V/div   TB: %s s/div   TRIG: %s"
                  % (r.get("freq_hz"), r.get("vpp_v"), r.get("ch1_scale_v_per_div"),
                     r.get("timebase_s_per_div"), r.get("trigger_status")))
        else:
            print("   → 失败模式 %s：%s" % (res["error"], res["advice"]))
            if res["error"] == "E_TIMEOUT":
                worst = max(worst, 6)
            elif kind == "lan":
                worst = max(worst, 3)
            else:
                worst = max(worst, 4)

        if len(targets) > 1 and kind != targets[-1]:
            time.sleep(2.0)

    passed = [r for r in out["results"] if r["ok"]]
    print("=" * 72)
    print("PROBE_JSON " + json.dumps(
        {"ok": [r["io"] for r in passed],
         "failed": [{"io": r["io"], "err": r["error"]} for r in out["results"] if not r["ok"]],
         "readings": {r["io"]: {"idn": r["idn"], **{k: v for k, v in r["readings"].items()
                                                    if k in ("freq_hz", "vpp_v")}}
                      for r in out["results"]}},
        ensure_ascii=False))

    if args.json:
        open(args.json, "w", encoding="utf-8").write(
            json.dumps(out, ensure_ascii=False, indent=2) + "\n")
        print("[json] %s" % args.json)

    if any(r["ok"] and r["readings"].get("freq_hz") is None for r in out["results"]):
        worst = max(worst, 5)
    return worst

if __name__ == "__main__":
    sys.exit(main())
