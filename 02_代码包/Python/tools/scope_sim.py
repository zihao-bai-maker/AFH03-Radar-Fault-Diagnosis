#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scope_sim.py —— RIGOL DS2302A 示波器模拟器（纯标准库，TCP 5555 裸 socket SCPI 服务器）。

为什么需要它
------------
现场验收要证明「20 MHz / 40 MHz 方波 = PASS，其余 = FAIL」，但示波器不是随时在身边。
这个模拟器在**本机**起一个和真机行为一致的 SCPI 服务器，于是：

  * 判定逻辑（白名单 / 容差 / 边界）可以用**真实 TCP 栈**端到端验证，不用等真机；
  * 异常路径（不响应、延迟、断连、端口没监听）也能**可复现地**测出来，
    证明"连不上时给明确原因、不挂死、不静默"；
  * 真机到货后，把 `--host` 从 127.0.0.1 换成示波器 IP，**同一套脚本不用改**。

模拟范围
--------
读（query）：
    *IDN?  *OPC?  *RST
    :MEASure:ITEM? FREQ|PERIod|VPP|VMAX|VMIN|VAVG|VAMP|VRMS,CHANnel<n>
    :MEASure:FREQuency?|PERiod?|VPP?|VMAX?|VMIN?|VAVG? [CHANnel<n>]
    :CHANnel<n>:SCALe?|PROBe?|OFFSet?|DISPlay?|COUPling?|BWLimit?
    :TIMebase:MAIN:SCALe?|OFFSet?   :TRIGger:STATus?|MODE?
    :ACQuire:SRATe?|TYPE?           :WAVeform:PREamble?|DATA?|POINts?
写（set）：*RST、:CHANnel<n>:SCALe/PROBe/OFFSet/DISPlay/COUPling/BWLimit、:TIMebase:MAIN:SCALe、
    :TRIGger:MODE、:ACQuire:TYPE、:WAVeform:SOURce/FORMat/MODE/POINts、:RUN、:STOP、:AUTOSet
SCPI 短写按标准前缀规则展开（`CHAN1` == `CHANNEL1`，`TIM:MAIN:SCAL` == `TIMEBASE:MAIN:SCALE`），
和真机一样大小写不敏感。

异常注入（专门用来测客户端容错）
    --delay MS        每次回话前延迟 ms（模拟慢）
    --drop-after N    服务过 N 条命令后不再回话（连接保持）-> 客户端应当"超时"
    --close-after N   服务过 N 条命令后直接断开连接 -> 客户端应当"重连/报错"
    --drop-conn-after N 同上（别名）

用法
----
    # 起模拟器：20 MHz 方波，V pp=3.3 V，×10 探头，20 ns/div
    python3 tools/scope_sim.py --freq 20e6 --vpp 3.3 --probe 10 --scal 0.5 --timebase 20ns

    # 无信号（示波器测不出频率 -> 客户端应报 ERROR/no-signal）
    python3 tools/scope_sim.py --freq none

    # 注入故障
    python3 tools/scope_sim.py --delay 200
    python3 tools/scope_sim.py --drop-after 3
"""

from __future__ import annotations

import argparse
import math
import re
import socket
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_IDN = "RIGOL TECHNOLOGIES,DS2302A,DS2A000000001,00.02.01"

_WORDS = [
    "MEASURE", "ITEM", "CHANNEL", "TIMEBASE", "MAIN", "SCALE", "OFFSET", "PROBE",
    "DISPLAY", "COUPLING", "BWLIMIT", "TRIGGER", "STATUS", "MODE", "ACQUIRE", "SRATE",
    "TYPE", "WAVEFORM", "SOURCE", "FORMAT", "POINTS", "PREAMBLE", "DATA",
    "FREQUENCY", "PERIOD", "VPP", "VMAX", "VMIN", "VAVG", "VAMP", "VRMS",
    "RUN", "STOP", "AUTOSET", "RST", "CLS", "OPC", "IDN", "CHANNEL",
]

INVALID = 9.9e37

def parse_num(text: str) -> Optional[float]:
    """'20ns' / '1ms' / '3.3' / '2e-8' / '10' -> float（秒/伏/倍率都用得上）。"""
    if text is None:
        return None
    t = str(text).strip().strip('"')
    if not t or t.upper() in ("NONE", "OFF", "NAN"):
        return None
    m = re.match(r"^([-+]?[0-9.]+(?:[eE][-+]?[0-9]+)?)\s*([a-zA-Z%]*)$", t)
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    suf = m.group(2)
    mult = 1.0
    if suf and suf[0] in "kKmMuUnNpPgG":
        mult = {"k": 1e3, "K": 1e3, "m": 1e-3, "M": 1e6, "u": 1e-6, "U": 1e-6,
                "n": 1e-9, "N": 1e-9, "p": 1e-12, "G": 1e9, "g": 1e9}.get(suf[0], 1.0)
    return v * mult

def _expand_seg(seg: str) -> str:
    m = re.match(r"^([A-Za-z]+)(\d*)$", seg)
    if not m:
        return seg.upper()
    word, num = m.group(1).upper(), m.group(2)
    for w in _WORDS:
        if w.startswith(word):
            return w + num
    return word + num

def canon(cmd: str) -> Tuple[str, str]:
    """把命令规范化成 (KEY, param)。规则与 SCPI 一致：大小写不敏感 + 前缀展开。"""
    c = cmd.strip()
    is_q = c.endswith("?")
    if is_q:
        c = c[:-1]
    if c.startswith("*"):
        return c.upper() + ("?" if is_q else ""), ""
    parts = c.split(None, 1)
    head = parts[0]
    param = parts[1].strip() if len(parts) > 1 else ""
    segs = [s for s in head.split(":") if s != ""]
    key = ":" + ":".join(_expand_seg(s) for s in segs)
    if is_q:
        key += "?"
    return key, param

def fmt_sci(v: float) -> str:
    return "%.6E" % v

class FakeRigolScope:
    """可嵌入线程的 DS2302A 模拟器。

    典型用法（测试里）::

        sim = FakeRigolScope(freq_hz=20e6, vpp_v=3.3, probe=10.0, port=0)
        sim.start()                     # port=0 -> 自动选空闲端口
        print(sim.port)                 # 实际端口
        ... 用 scpi_scope.check_scope("127.0.0.1", sim.port, ...)
        sim.stop()
    """

    def __init__(self, freq_hz: Optional[float] = 20e6, vpp_v: float = 3.3,
                 probe: float = 10.0, scale_v_per_div: float = 0.5,
                 time_per_div_s: float = 20e-9, idn: str = DEFAULT_IDN,
                 bind: str = "127.0.0.1", port: int = 5555,
                 sample_rate: float = 2.0e9, wave_points: int = 12000,
                 delay_ms: float = 0.0, drop_after: int = -1,
                 close_after: int = -1, trigger_status: str = "TD",
                 offset_v: float = 0.0, coupling: str = "DC",
                 verbose: bool = False):
        self.freq_hz = freq_hz
        self.vpp_v = float(vpp_v)
        self.probe = float(probe)
        self.scale_v_per_div = float(scale_v_per_div)
        self.time_per_div_s = float(time_per_div_s)
        self.idn = idn
        self.bind = bind
        self.port = int(port)
        self.sample_rate = float(sample_rate)
        self.wave_points = int(wave_points)
        self.delay_ms = float(delay_ms)
        self.drop_after = int(drop_after)
        self.close_after = int(close_after)
        self.trigger_status = trigger_status
        self.offset_v = float(offset_v)
        self.coupling = coupling
        self.verbose = verbose

        self.commands: List[str] = []       
        self.n_served = 0
        self.running = False
        self._srv: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._conns: List[threading.Thread] = []

    def start(self) -> "FakeRigolScope":
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((self.bind, self.port))
        self._srv.listen(8)
        self.port = self._srv.getsockname()[1]
        self._srv.settimeout(0.3)
        self.running = True
        self._thread = threading.Thread(target=self._accept_loop, name="scope-sim", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self.running = False
        if self._srv is not None:
            try:
                self._srv.close()
            except OSError:
                pass
            self._srv = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        for t in list(self._conns):
            t.join(timeout=1.0)
        self._conns.clear()

    def __enter__(self) -> "FakeRigolScope":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    def _accept_loop(self) -> None:
        while self.running and self._srv is not None:
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            t = threading.Thread(target=self._serve, args=(conn,), daemon=True)
            t.start()
            self._conns.append(t)

    def _serve(self, conn: socket.socket) -> None:
        conn.settimeout(30.0)
        buf = b""
        try:
            while self.running:
                try:
                    chunk = conn.recv(1024)
                except socket.timeout:
                    break
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    cmd = line.decode("ascii", "replace").strip()
                    if not cmd:
                        continue
                    self.n_served += 1
                    self.commands.append(cmd)
                    if self.verbose:
                        print("[sim] <- %s" % cmd)

                    if self.drop_after >= 0 and self.n_served > self.drop_after:
                        continue
                    if self.close_after >= 0 and self.n_served > self.close_after:
                        return
                    payload = self.handle(cmd)
                    if payload is None:
                        continue
                    if self.delay_ms > 0:
                        time.sleep(self.delay_ms / 1000.0)
                    try:
                        conn.sendall(payload)
                    except OSError:
                        return
                    if self.verbose:
                        print("[sim] -> %s" % payload[:80])
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def handle(self, cmd: str):
        """返回要发回去的 bytes；None 表示不回话（设置类命令）。"""
        key, param = canon(cmd)
        r = self._dispatch(key, param)
        if r is None:
            return None
        if isinstance(r, bytes):
            return r
        return (r + "\n").encode("ascii")

    def _dispatch(self, key: str, param: str):
        """返回 str（自动补 \n）/ bytes（块数据）/ None（不回话）。"""

        if key == "*IDN?":
            return self.idn
        if key == "*OPC?":
            return "1"
        if key in ("*RST", "*CLS"):
            self.probe, self.scale_v_per_div = 1.0, 1.0
            self.time_per_div_s, self.offset_v, self.coupling = 1e-3, 0.0, "DC"
            self.trigger_status = "TD"
            return None
        if key in (":RUN", ":STOP", ":AUTOSET"):
            if key == ":STOP":
                self.trigger_status = "STOP"
            return None

        m = re.match(r"^:CHANNEL(\d):(\w+)(\?)?$", key)
        if m:
            ch, item = int(m.group(1)), m.group(2)
            q = bool(m.group(3))
            return self._channel(ch, item, q, param)

        if key.startswith(":TIMEBASE:MAIN:SCALE"):
            if key.endswith("?"):
                return fmt_sci(self.time_per_div_s)
            v = parse_num(param)
            if v:
                self.time_per_div_s = v
            return None
        if key.startswith(":TIMEBASE:MAIN:OFFSET"):
            return fmt_sci(0.0) if key.endswith("?") else None

        if key.startswith(":TRIGGER:STATUS"):
            return self.trigger_status
        if key.startswith(":TRIGGER:MODE"):
            return "EDGE" if key.endswith("?") else None

        if key.startswith(":ACQUIRE:SRATE"):
            return fmt_sci(self.sample_rate)
        if key.startswith(":ACQUIRE:TYPE"):
            return "NORMAL" if key.endswith("?") else None

        if key.startswith(":MEASURE:ITEM"):
            item, ch = self._split_item_param(param)
            return self._meas(item, ch)
        m = re.match(r"^:MEASURE:(\w+)(\?)?$", key)
        if m:
            item, q = m.group(1), bool(m.group(2))
            ch = 1
            if param:
                p2 = param.strip().rstrip("?").strip()
                if p2:
                    mm = re.search(r"(\d)\s*$", p2)
                    if mm:
                        ch = int(mm.group(1))
            if not q and key.endswith("?"):
                q = True
            return self._meas(item, ch) if q else None

        if key.startswith(":WAVEFORM:SOURCE"):
            return "CHAN1" if key.endswith("?") else None
        if key.startswith(":WAVEFORM:FORMAT"):
            return "BYTE" if key.endswith("?") else None
        if key.startswith(":WAVEFORM:MODE"):
            return "NORMAL" if key.endswith("?") else None
        if key.startswith(":WAVEFORM:POINTS"):
            if key.endswith("?"):
                return str(self._eff_points())
            v = parse_num(param)
            if v:
                self.wave_points = int(max(16, min(200000, v)))
            return None
        if key.startswith(":WAVEFORM:PREAMBLE"):
            return self._preamble()
        if key.startswith(":WAVEFORM:DATA"):
            return self._waveform_block()

        return '-113,"Undefined header"'

    def _channel(self, ch: int, item: str, q: bool, param: str) -> Optional[str]:
        if item == "SCALE":
            if q:
                return fmt_sci(self.scale_v_per_div)
            v = parse_num(param)
            if v:
                self.scale_v_per_div = v
            return None
        if item == "PROBE":
            if q:
                return fmt_sci(self.probe)
            v = parse_num(param)
            if v:
                self.probe = v
            return None
        if item == "OFFSET":
            if q:
                return fmt_sci(self.offset_v)
            v = parse_num(param)
            if v is not None:
                self.offset_v = v
            return None
        if item == "DISPLAY":
            return "1" if q else None
        if item == "COUPLING":
            if q:
                return self.coupling
            if param:
                self.coupling = param.strip().upper()
            return None
        if item == "BWLIMIT":
            return "OFF" if q else None
        return '-113,"Undefined header"'

    def _split_item_param(self, param: str) -> Tuple[str, int]:
        ch = 1
        item = ""
        p = param.strip().rstrip("?").strip()
        if not p:
            return "", ch
        bits = [b.strip() for b in p.split(",") if b.strip()]
        for b in bits:
            up = b.upper()
            if up.startswith("CHAN") or up.startswith("CHANNEL"):
                mm = re.search(r"(\d)\s*$", up)
                if mm:
                    ch = int(mm.group(1))
            else:
                item = up
        if not item and bits:
            item = bits[0].upper()

        for w in ("FREQUENCY", "PERIOD", "VPP", "VMAX", "VMIN", "VAVG", "VAMP", "VRMS"):
            if w.startswith(item) and item:
                return w, ch
        return item, ch

    def _meas(self, item: str, ch: int) -> str:
        item = (item or "").upper()
        no_signal = (self.freq_hz is None) or (self.freq_hz <= 0)
        if item in ("FREQUENCY", "FREQ"):
            if no_signal:
                return fmt_sci(INVALID)          

            jitter = 1.0 + 2e-6 * math.sin(time.time() * 7.0)
            return fmt_sci(self.freq_hz * jitter)
        if item == "PERIOD":
            if no_signal:
                return fmt_sci(INVALID)
            return fmt_sci(1.0 / self.freq_hz)
        if item == "VPP":
            if no_signal:
                return fmt_sci(INVALID)
            return fmt_sci(self.vpp_v)
        if item == "VMAX":
            if no_signal:
                return fmt_sci(INVALID)
            return fmt_sci(self.vpp_v / 2.0)
        if item == "VMIN":
            if no_signal:
                return fmt_sci(INVALID)
            return fmt_sci(-self.vpp_v / 2.0)
        if item == "VAVG":
            if no_signal:
                return fmt_sci(INVALID)
            return fmt_sci(0.0)
        if item in ("VAMP", "VRMS"):
            if no_signal:
                return fmt_sci(INVALID)
            return fmt_sci(self.vpp_v / 2.0)
        return fmt_sci(INVALID)

    def _eff_points(self) -> int:
        return self.wave_points

    def _preamble(self) -> str:

        dt = 1.0 / self.sample_rate
        yinc = 10.0 / 255.0            
        return ",".join(["0", "0", str(self._eff_points()), "1",
                         fmt_sci(dt), fmt_sci(0.0), fmt_sci(0.0),
                         fmt_sci(yinc), fmt_sci(0.0), fmt_sci(128.0)])

    def _waveform_block(self) -> bytes:
        n = self._eff_points()
        dt = 1.0 / self.sample_rate
        yinc = 10.0 / 255.0
        yref, yorig = 128.0, 0.0
        no_signal = (self.freq_hz is None) or (self.freq_hz <= 0)
        data = bytearray(n)
        for i in range(n):
            if no_signal:
                v = 0.0
            else:
                ph = (i * dt * self.freq_hz) % 1.0
                v = (self.vpp_v / 2.0) if ph < 0.5 else (-self.vpp_v / 2.0)
            b = int(round((v - yorig) / yinc + yref))
            data[i] = 0 if b < 0 else (255 if b > 255 else b)
        header = ("#8%08d" % n).encode("ascii")
        return header + bytes(data) + b"\n"

def _parse_timebase(s: str) -> float:
    v = parse_num(s)
    if v is None or v <= 0:
        raise argparse.ArgumentTypeError("timebase 例：20ns / 1ms / 2e-8")
    return v

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="RIGOL DS2302A 模拟器（TCP 裸 socket SCPI，纯标准库）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--freq", default="20e6",
                    help="信号频率，如 20e6/40e6/13.5e6；none 表示无信号（测不出来）")
    ap.add_argument("--vpp", type=float, default=3.3, help="峰峰值 V（探头端真实值）")
    ap.add_argument("--probe", type=float, default=10.0, help="探头衰减 1/10/100")
    ap.add_argument("--scal", type=float, default=0.5, help="V/div")
    ap.add_argument("--timebase", type=_parse_timebase, default=20e-9, help="时基 s/div，如 20ns")
    ap.add_argument("--idn", default=DEFAULT_IDN)
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=5555)
    ap.add_argument("--sample-rate", type=float, default=2.0e9)
    ap.add_argument("--points", type=int, default=12000)
    ap.add_argument("--delay", type=float, default=0.0, help="每次回话前延迟 ms")
    ap.add_argument("--drop-after", type=int, default=-1, help="服务 N 条后不再回话（测超时）")
    ap.add_argument("--close-after", type=int, default=-1, help="服务 N 条后断开连接（测重连）")
    ap.add_argument("--trigger-status", default="TD")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap

def main(argv: Optional[List[str]] = None) -> int:
    a = build_parser().parse_args(argv)
    f = parse_num(a.freq)
    sim = FakeRigolScope(freq_hz=f, vpp_v=a.vpp, probe=a.probe,
                         scale_v_per_div=a.scal, time_per_div_s=a.timebase,
                         idn=a.idn, bind=a.bind, port=a.port,
                         sample_rate=a.sample_rate, wave_points=a.points,
                         delay_ms=a.delay, drop_after=a.drop_after,
                         close_after=a.close_after,
                         trigger_status=a.trigger_status, verbose=a.verbose)
    try:
        sim.start()
    except OSError as e:

        print("[ERR] 绑定 %s:%d 失败: %s" % (a.bind, a.port, e))
        if a.port == 5555:
            print("      端口 5555 被占用时换一个即可（连真示波器的 5555 不受影响，"
                  "因为那是出向连接）：--port 15555")
        return 2

    
    try:
        sys.stdout.reconfigure(line_buffering=True)      
    except Exception:                                     
        pass
    banner = [
        "== DS2302A 模拟器已启动 ==",
        "  监听        : %s:%d   (TCP, SCPI)" % (a.bind, sim.port),
        "  *IDN?       : %s" % a.idn,
        "  频率        : %s" % ("无信号(9.9E+37)" if f is None else "%.9g Hz" % f),
        "  Vpp         : %.4g V   V/div=%.4g   探头=×%g   时基=%.4g s/div"
        % (a.vpp, a.scal, a.probe, a.timebase),
    ]
    if a.delay or a.drop_after >= 0 or a.close_after >= 0:
        banner.append("  故障注入    : delay=%gms drop_after=%d close_after=%d"
                      % (a.delay, a.drop_after, a.close_after))
    banner += [
        "  客户端连    : python3 -m soc_vision.scpi_scope --host 127.0.0.1 --port %d" % sim.port,
        "  Ctrl+C 退出",
    ]
    for line in banner:
        print(line, flush=True)
    try:
        while True:
            time.sleep(0.3)
    except KeyboardInterrupt:
        print("\n[sim] 退出，共服务 %d 条命令" % sim.n_served, flush=True)
    finally:
        sim.stop()
    return 0

if __name__ == "__main__":                                     
    raise SystemExit(main())
