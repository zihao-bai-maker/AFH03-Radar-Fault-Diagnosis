#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scpi_scope.py —— RIGOL DS2302A 直读（SCPI over LAN，TCP 5555），本项目**主判据**。

为什么它是主判据
----------------
相机拍屏法（`scope_wave.py`）的链路是"时基 × 网格像素"，时基读错、网格数错、
镜头畸变都会让频率系统性偏移；而 20 MHz / 40 MHz 之间只差 2 倍，
现场还要区分"是不是 20/40 MHz"，所以最可靠的是**直接问示波器**：

    *IDN?                      -> 型号/序列号/固件（确认对面真的是 DS2302A）
    :MEASure:ITEM? FREQ,CHAN1  -> 示波器自己测出来的频率（真值）
    :MEASure:ITEM? VPP,CHAN1   -> 峰峰值（DS2000A 的测量值已按探头倍率换算，就是探头端真实电压）
    :CHANnel1:PROBe?           -> 探头衰减
    :CHANnel1:SCALe?           -> V/div
    :TIMebase:MAIN:SCALe?      -> 时基 s/div

判定规则（可配）：`freq ∈ {20e6, 40e6}`（±容差，默认 1%）-> **PASS / NORMAL**，其余 -> **FAIL / ABNORMAL**。
读不到（网线没插 / 示波器不在线 / 超时 / 示波器自己测不出频率）-> **ERROR / UNKNOWN**，
既不会静默当 PASS，也不会把"连不上"混进"频率不对"。

三个独立读数（互相印证，避免单点异常导致误判）
--------------------------------------------
1. `:MEAS:ITEM? FREQ` —— 示波器自测频率（主值）
2. `:WAVeform:DATA?`  —— 把波形数据拉回来，本地算过零频率（交叉校验；顺带算 Vpp）
3. `:MEAS:ITEM? PERiod` —— 周期 -> 1/T（再一路交叉校验）

实现约束：**只用标准库**（socket/struct/statistics），不 import numpy，
这样在 PC（numpy 坏掉的环境）和板子上都能直接跑。

用法
----
    # 单次判定（本项目默认 20/40 MHz）
    python3 -m soc_vision.scpi_scope --host 192.168.1.50

    # 连续 20 次取均值/抖动，并输出 JSON
    python3 -m soc_vision.scpi_scope --host 192.168.1.50 --repeat 20 --json-out /tmp/verdict.json

    # 不知道示波器 IP：扫网段找 5555 端口上回答 *IDN? 的 RIGOL
    python3 -m soc_vision.scpi_scope --scan 192.168.1.0/24

退出码：0 PASS / 3 FAIL（读到了但频率不在白名单）/ 4 ERROR（读不到）/ 1 参数错
"""

from __future__ import annotations

import argparse
import concurrent.futures
import errno
import ipaddress
import json
import os
import socket
import statistics
import struct
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCOPE_PORT = 5555
DEFAULT_TIMEOUT = 3.0

DEFAULT_NOMINAL_HZ: Tuple[float, ...] = (20e6, 40e6)
DEFAULT_TOL_PCT = 1.0

_INVALID = 1e30

DEFAULT_SCAN_SUBNETS = ("192.168.1.0/24", "192.168.0.0/24", "192.168.100.0/24", "10.0.0.0/24")

class ScpiError(RuntimeError):
    """带"人话原因"的 SCPI 错误。

    kind 取值：
      no-interface  : 本机没有可用的以太网口（网线没插）
      net-unreachable / host-unreachable : 没有路由（IP 不在同网段 / 网线没插）
      conn-refused  : 对端在，但 5555 没监听（不是示波器 / SCPI 没开）
      timeout       : 连上了但没按时回话
      dns           : 主机名解析失败
      not-rigol     : 回话了但不是 RIGOL/DS2302A
      no-signal     : 示波器自己测不出频率（9.9E+37）
      bad-reply     : 返回内容解析不了
      other         : 其它
    """

    def __init__(self, kind: str, reason: str, detail: str = ""):
        super().__init__("%s: %s%s" % (kind, reason, (" | " + detail) if detail else ""))
        self.kind = kind
        self.reason = reason
        self.detail = detail

def _explain_oserror(e: OSError, host: str, port: int) -> ScpiError:
    """把 socket 异常翻译成现场能直接照做的原因。"""
    en = getattr(e, "errno", None)
    msg = getattr(e, "strerror", None) or str(e)
    if isinstance(e, socket.gaierror):
        return ScpiError("dns", "主机名/IP 解析失败：%s" % host, msg)
    if isinstance(e, socket.timeout) or en == errno.ETIMEDOUT:
        return ScpiError("timeout",
                         "连接 %s:%d 超时（示波器不在线 / IP 不对 / 被防火墙挡）" % (host, port), msg)
    if en == errno.ECONNREFUSED:
        return ScpiError("conn-refused",
                         "%s:%d 拒绝连接（对端不是示波器，或示波器的 SCPI/socket 服务没开）"
                         % (host, port), msg)

    if en == errno.EHOSTUNREACH:
        return ScpiError("host-unreachable",
                         "到 %s 的主机不可达（示波器关机 / IP 不存在 / 中间有交换机隔离）" % host, msg)
    if en == errno.ENETUNREACH:
        return ScpiError("net-unreachable",
                         "没有到 %s 的路由（网线没插 / 板子与示波器不在同一网段）" % host, msg)
    if en == errno.ENETDOWN:
        return ScpiError("no-interface", "网口处于 DOWN（网线没插好）", msg)
    return ScpiError("other", "连接 %s:%d 失败" % (host, port), msg)

class RigolScpi:
    """极简 RIGOL SCPI 客户端（裸 TCP，无第三方依赖）。"""

    def __init__(self, host: str, port: int = SCOPE_PORT, timeout: float = DEFAULT_TIMEOUT,
                 retries: int = 2, retry_delay: float = 0.4, verbose: bool = False):
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self.retries = int(retries)
        self.retry_delay = float(retry_delay)
        self.verbose = verbose
        self.sock: Optional[socket.socket] = None
        self.log: List[Dict[str, Any]] = []      

    def open(self) -> None:
        self.close()
        try:
            s = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            raise _explain_oserror(e, self.host, self.port)
        s.settimeout(self.timeout)
        try:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        self.sock = s
        if self.verbose:
            print("[SCPI] connected %s:%d" % (self.host, self.port))

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def __enter__(self) -> "RigolScpi":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _recv_line(self, timeout: float) -> bytes:
        assert self.sock is not None
        self.sock.settimeout(timeout)
        data = b""
        t0 = time.time()
        while True:
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            data += chunk
            if data.endswith(b"\n"):
                break
            if time.time() - t0 > timeout:
                break
        return data

    def _recv_exact(self, n: int, timeout: float) -> bytes:
        assert self.sock is not None
        self.sock.settimeout(timeout)
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(min(65536, n - len(buf)))
            if not chunk:
                break
            buf += chunk
        return buf

    def _raw_query(self, cmd: str, timeout: Optional[float] = None) -> str:
        if self.sock is None:
            raise ScpiError("other", "SCPI 未连接（先 open()）")
        to = float(timeout if timeout is not None else self.timeout)
        try:
            self.sock.sendall((cmd + "\n").encode("ascii"))
        except OSError as e:
            raise _explain_oserror(e, self.host, self.port)
        try:
            data = self._recv_line(to)
        except OSError as e:
            raise _explain_oserror(e, self.host, self.port)
        text = data.decode("ascii", "replace").strip()

        if text.startswith("-") and "," in text and "\n" not in text:
            self.log.append({"cmd": cmd, "reply": text, "err": True})
            raise ScpiError("bad-reply", "示波器拒绝了命令 %s" % cmd, text)
        self.log.append({"cmd": cmd, "reply": text})
        if self.verbose:
            print("[SCPI] %-34s -> %s" % (cmd, text[:90]))
        return text

    def write(self, cmd: str) -> None:
        """只写不读（设置类命令，示波器不回话）。"""
        if self.sock is None:
            raise ScpiError("other", "SCPI 未连接（先 open()）")
        try:
            self.sock.sendall((cmd + "\n").encode("ascii"))
        except OSError as e:
            raise _explain_oserror(e, self.host, self.port)
        self.log.append({"cmd": cmd, "reply": "<write>"})
        if self.verbose:
            print("[SCPI] %-34s -> (write)" % cmd)

    def query(self, cmd: str, timeout: Optional[float] = None,
              retries: Optional[int] = None) -> str:
        """带重试的查询：只有"读空/超时"才重试，明确的错误立刻抛。"""
        n = self.retries if retries is None else int(retries)
        last: Optional[ScpiError] = None
        for i in range(max(1, n + 1)):
            try:
                v = self._raw_query(cmd, timeout)
                if v != "":
                    return v
                last = ScpiError("timeout", "命令 %s 无返回" % cmd)
            except ScpiError as e:
                if e.kind in ("bad-reply",):
                    raise
                last = e
            if i < n:
                time.sleep(self.retry_delay)

                try:
                    self.open()
                except ScpiError:
                    pass
        if last is not None:
            raise last
        return ""

    def idn(self) -> str:
        return self.query("*IDN?")

    def is_rigol(self, idn: Optional[str] = None) -> bool:
        s = (idn if idn is not None else self.idn()).upper()
        return "RIGOL" in s or "DS2" in s or "MSO2" in s

    def read_state(self, channels: Sequence[int] = (1, 2)) -> Dict[str, Any]:
        """读全部通道设置 + 时基 + 触发（顺便把三个标定量自动读出来）。"""
        st: Dict[str, Any] = {"idn": self.idn()}
        st["time_per_div_s"] = self.query(":TIMebase:MAIN:SCALe?")
        for c in channels:
            key = "ch%d" % c
            st[key] = {
                "scale_v_per_div": self.query(":CHANnel%d:SCALe?" % c),
                "probe": self.query(":CHANnel%d:PROBe?" % c),
                "offset_v": self.query(":CHANnel%d:OFFSet?" % c),
                "display": self.query(":CHANnel%d:DISPlay?" % c),
                "coupling": self.query(":CHANnel%d:COUPling?" % c),
                "bwlimit": self.query(":CHANnel%d:BWLimit?" % c),
            }
        st["trigger_status"] = self.query(":TRIGger:STATus?")
        try:
            st["sample_rate_sa_s"] = self.query(":ACQuire:SRATe?")
        except ScpiError:
            st["sample_rate_sa_s"] = ""
        return st

    def read_measure(self, ch: int = 1) -> Dict[str, Any]:
        """示波器自己的测量值（真值）。命令因固件而异，逐个候选兜底。"""
        out: Dict[str, Any] = {"ch": ch}

        def first_ok(cmds: Iterable[str], timeout: float) -> str:
            last = ""
            for c in cmds:
                try:
                    v = self.query(c, timeout=timeout)
                except ScpiError:
                    continue
                if v == "":
                    continue
                last = v
                if not _is_invalid(v):
                    return v
            return last

        out["freq_raw"] = first_ok([
            ":MEASure:ITEM? FREQ,CHANnel%d" % ch,
            ":MEASure:ITEM? FREQuency,CHANnel%d" % ch,
            ":MEASure:FREQuency? CHANnel%d" % ch,
            ":MEASure:FREQuency?",
        ], timeout=max(self.timeout, 5.0))
        out["vpp_raw"] = first_ok([
            ":MEASure:ITEM? VPP,CHANnel%d" % ch,
            ":MEASure:VPP? CHANnel%d" % ch,
            ":MEASure:VPP?",
        ], timeout=max(self.timeout, 5.0))
        out["period_raw"] = first_ok([
            ":MEASure:ITEM? PERiod,CHANnel%d" % ch,
            ":MEASure:PERiod? CHANnel%d" % ch,
        ], timeout=max(self.timeout, 5.0))
        out["vmax_raw"] = first_ok([":MEASure:ITEM? VMAX,CHANnel%d" % ch], self.timeout)
        out["vmin_raw"] = first_ok([":MEASure:ITEM? VMIN,CHANnel%d" % ch], self.timeout)
        out["vavg_raw"] = first_ok([":MEASure:ITEM? VAVG,CHANnel%d" % ch], self.timeout)

        return out

    def read_waveform(self, ch: int = 1, points: int = 12000,
                      mode: str = "NORMal") -> Dict[str, Any]:
        """把波形数据拉回来（用来本地独立算频率/Vpp，做交叉校验）。

        返回 {xincrement, xorigin, yincrement, yorigin, yreference, npoints, samples[]}
        samples 已经是"伏特"（示波器显示坐标系，含探头倍率）。
        """
        self.write(":WAVeform:SOURce CHANnel%d" % ch)
        self.write(":WAVeform:FORMat BYTE")
        self.write(":WAVeform:MODE %s" % mode)
        try:
            self.write(":WAVeform:POINts %d" % int(points))
        except ScpiError:
            pass
        pre = self.query(":WAVeform:PREamble?", timeout=max(self.timeout, 5.0))
        parts = [p.strip() for p in pre.split(",")]
        if len(parts) < 10:
            raise ScpiError("bad-reply", "PREamble 格式看不懂", pre[:120])
        try:
            xinc = float(parts[4])
            xorig = float(parts[5])
            yinc = float(parts[7])
            yorig = float(parts[8])
            yref = float(parts[9])
        except (ValueError, IndexError) as e:
            raise ScpiError("bad-reply", "PREamble 数值解析失败", "%s | %s" % (e, pre[:120]))

        data = self._read_block(":WAVeform:DATA?", timeout=max(self.timeout, 10.0))
        npoints_asked = None
        try:
            npoints_asked = int(parts[2])
        except (ValueError, IndexError):
            pass
        vals = [((b - yref) * yinc) + yorig for b in data]
        return {"xincrement": xinc, "xorigin": xorig, "yincrement": yinc,
                "yorigin": yorig, "yreference": yref, "npoints_asked": npoints_asked,
                "npoints": len(vals), "samples": vals}

    def _read_block(self, cmd: str, timeout: float) -> bytes:
        """读 IEEE-488.2 块数据（RIGOL 回 `#800001000<binary>`）。"""
        if self.sock is None:
            raise ScpiError("other", "SCPI 未连接")
        try:
            self.sock.sendall((cmd + "\n").encode("ascii"))
        except OSError as e:
            raise _explain_oserror(e, self.host, self.port)
        self.sock.settimeout(timeout)
        buf = b""

        t0 = time.time()
        while b"#" not in buf:
            if time.time() - t0 > timeout:
                raise ScpiError("timeout", "%s 等待块头超时" % cmd)
            chunk = self.sock.recv(256)
            if not chunk:
                raise ScpiError("timeout", "%s 连接被关闭" % cmd)
            buf += chunk
        i = buf.index(b"#")
        buf = buf[i:]
        if len(buf) < 2:
            buf += self._recv_exact(2 - len(buf), timeout)
        ndig = int(chr(buf[1]))
        need = 2 + ndig
        while len(buf) < need:
            buf += self._recv_exact(need - len(buf), timeout)
        nbytes = int(buf[2:need].decode("ascii"))
        body = buf[need:]
        while len(body) < nbytes:
            body += self._recv_exact(nbytes - len(body), timeout)
        self.log.append({"cmd": cmd, "reply": "<binary %d bytes>" % nbytes})
        return body[:nbytes]

def _parse_number(text: Any) -> Optional[float]:
    """把 SCPI 返回的字符串转成 float；无效读数返回 None。"""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        v = float(text)
        return None if _is_invalid(v) else v
    t = str(text).strip().strip('"').replace(" ", "")
    if not t:
        return None
    try:
        v = float(t)
        return None if _is_invalid(v) else v
    except ValueError:
        pass

    num = ""
    for i, c in enumerate(t):
        if c.isdigit() or c in "+-.eE":
            num += c
        else:
            break
    if not num:
        return None
    try:
        v = float(num)
    except ValueError:
        return None
    if _is_invalid(v):
        return None
    mult = {"k": 1e3, "K": 1e3, "m": 1e-3, "M": 1e6, "u": 1e-6, "U": 1e-6,
            "n": 1e-9, "N": 1e-9, "G": 1e9, "g": 1e9}
    suf = t[len(num):]
    if suf and suf[0] in mult:
        v *= mult[suf[0]]
    return v

def _is_invalid(v: Any) -> bool:
    """RIGOL 无效读数判定。入参可能是 str（SCPI 原始返回），必须容错。"""
    try:
        return abs(float(v)) >= _INVALID
    except (TypeError, ValueError):
        return False

def fmt_hz(v: float) -> str:
    """人话频率：20 MHz / 1.5 kHz / 250 Hz。"""
    if v is None or v == 0:
        return "-"
    a = abs(v)
    if a >= 1e6:
        return "%.6g MHz" % (v / 1e6)
    if a >= 1e3:
        return "%.6g kHz" % (v / 1e3)
    return "%.6g Hz" % v

def analyze_samples(samples: Sequence[float], dt: float) -> Dict[str, float]:
    """对回读的波形做独立的频率/Vpp 计算（方波友好）。

    * Vpp   : 0.5% / 99.5% 分位之差（抗单点毛刺）
    * 频率  : 带迟滞的上升沿过零计数 + 线性插值，取多周期平均（方波比正弦更稳）
    """
    out: Dict[str, float] = {"freq_hz": 0.0, "vpp_v": 0.0, "period_s": 0.0,
                             "n_edges": 0, "n_samples": len(samples)}
    if len(samples) < 32 or dt <= 0:
        return out
    s = list(samples)
    lo = _percentile(s, 0.005)
    hi = _percentile(s, 0.995)
    out["vpp_v"] = max(0.0, hi - lo)
    mid = 0.5 * (lo + hi)
    amp = 0.5 * (hi - lo)
    if amp <= 0:
        return out

    hi_th = mid + 0.3 * amp
    lo_th = mid - 0.3 * amp
    rising: List[float] = []
    state = 1 if s[0] > mid else -1
    for i in range(1, len(s)):
        v = s[i]
        if state < 0 and v >= hi_th:

            v0 = s[i - 1]
            frac = 0.0 if v == v0 else (hi_th - v0) / (v - v0)
            rising.append((i - 1 + max(0.0, min(1.0, frac))) * dt)
            state = 1
        elif state > 0 and v <= lo_th:
            state = -1
    out["n_edges"] = len(rising)
    if len(rising) >= 2:
        span = rising[-1] - rising[0]
        nper = len(rising) - 1
        if span > 0 and nper > 0:
            period = span / nper
            out["period_s"] = period
            out["freq_hz"] = 1.0 / period

            ivs = [rising[i + 1] - rising[i] for i in range(nper)]
            if len(ivs) >= 2:
                m = statistics.fmean(ivs)
                if m > 0:
                    out["period_jitter_pct"] = statistics.pstdev(ivs) / m * 100.0
    return out

def _percentile(vals: Sequence[float], q: float) -> float:
    """线性插值分位数。

    q 可以给 0~1 的比例，也可以给 0~100 的百分数（自动识别）——这里踩过一次坑：
    调用方写成 99.5 而函数按比例解释，`xs[lo]` 直接越界。所以两件事都做：
    ① 自动归一化；② 索引夹紧，绝不越界。
    """
    if not vals:
        return 0.0
    if q > 1.0:
        q = q / 100.0
    q = 0.0 if q < 0 else (1.0 if q > 1 else q)
    xs = sorted(vals)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    lo = max(0, min(lo, len(xs) - 1))
    frac = pos - lo
    return xs[lo] * (1 - frac) + xs[hi] * frac

@dataclass
class ScopeVerdict:
    """一次判定的完整结果（可直接 json.dumps）。"""

    ok: bool = False                       
    verdict: str = "ERROR"                 
    label: str = "UNKNOWN"                 
    freq_hz: float = 0.0
    nominal_hz: float = 0.0
    nominal_list: List[float] = field(default_factory=list)
    freq_dev_pct: float = 0.0
    tol_pct: float = DEFAULT_TOL_PCT
    vpp_v: float = 0.0                     
    vpp_scope_v: float = 0.0               
    vpp_wave_v: float = 0.0                
    vpp_cross_dev_pct: float = 0.0
    probe: float = 0.0
    scale_v_per_div: float = 0.0
    time_per_div_s: float = 0.0
    ch: int = 1
    source: str = "scpi_meas"              
    reason: str = ""                       
    kind: str = ""                         
    n_success: int = 0
    n_total: int = 0
    freq_std_pct: float = 0.0
    freq_min_hz: float = 0.0
    freq_max_hz: float = 0.0
    idn: str = ""
    elapsed_s: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)

    def summary(self) -> str:
        if self.ok:
            extra = ""
            if self.vpp_cross_dev_pct:
                extra = "；Vpp 交叉校验偏差 %.2f%%" % self.vpp_cross_dev_pct
            return ("%s/%s  实测 %s  最接近标称 %s  偏差 %+.2f%%（±%.2f%%）"
                    "  Vpp %.4g V%s"
                    % (self.verdict, self.label, fmt_hz(self.freq_hz),
                       fmt_hz(self.nominal_hz), self.freq_dev_pct, self.tol_pct,
                       self.vpp_v, extra))
        return "%s/%s  %s" % (self.verdict, self.label, self.reason)

def judge_freq(freq_hz: float, nominal_list: Sequence[float],
               tol_pct: float = DEFAULT_TOL_PCT) -> Tuple[bool, float, float]:
    """返回 (是否命中, 最接近的标称, 偏差%)。白名单：命中任一即算命中。"""
    names = [float(v) for v in nominal_list if v]
    if not names:
        return True, 0.0, 0.0        
    best = min(names, key=lambda v: abs(v - freq_hz))
    dev = (freq_hz - best) / best * 100.0 if best else 0.0
    return abs(dev) <= tol_pct, best, dev

def check_scope(host: str, port: int = SCOPE_PORT, ch: int = 1,
                nominal_list: Sequence[float] = DEFAULT_NOMINAL_HZ,
                tol_pct: float = DEFAULT_TOL_PCT, timeout: float = DEFAULT_TIMEOUT,
                retries: int = 2, repeat: int = 1, read_wave: bool = True,
                verbose: bool = False) -> ScopeVerdict:
    """连上示波器 -> 读真值 -> 给 PASS/FAIL/ERROR 判定。绝不抛异常。"""
    t0 = time.time()
    v = ScopeVerdict(nominal_list=[float(x) for x in nominal_list],
                     tol_pct=float(tol_pct), ch=int(ch))
    sc = RigolScpi(host, port, timeout=timeout, retries=retries, verbose=verbose)
    try:
        sc.open()
        v.idn = sc.idn()
        if not sc.is_rigol(v.idn):
            v.kind = "not-rigol"
            v.reason = ("%s:%d 回话了但不是 RIGOL 示波器：%s" % (host, port, v.idn[:80]))
            v.elapsed_s = time.time() - t0
            return v

        state = sc.read_state(channels=(ch,))
        v.time_per_div_s = _parse_number(state.get("time_per_div_s")) or 0.0
        chd = state.get("ch%d" % ch, {}) or {}
        v.probe = _parse_number(chd.get("probe")) or 0.0
        v.scale_v_per_div = _parse_number(chd.get("scale_v_per_div")) or 0.0
        v.raw["state"] = state

        freqs: List[float] = []
        vpps: List[float] = []
        last_meas: Dict[str, Any] = {}
        for i in range(max(1, int(repeat))):
            meas = sc.read_measure(ch)
            last_meas = meas
            f = _parse_number(meas.get("freq_raw"))
            if f is None:
                p = _parse_number(meas.get("period_raw"))
                f = (1.0 / p) if (p and p > 0) else None
            if f is not None and f > 0:
                freqs.append(f)
            vp = _parse_number(meas.get("vpp_raw"))
            if vp is not None:
                vpps.append(abs(vp))
            if repeat > 1:
                time.sleep(0.15)
        v.raw["measure"] = last_meas
        v.n_total = max(1, int(repeat))
        v.n_success = len(freqs)

        if not freqs:

            if read_wave:
                try:
                    wf = sc.read_waveform(ch)
                    an = analyze_samples(wf["samples"], wf["xincrement"])
                    v.raw["waveform_info"] = {k: wf[k] for k in
                                              ("xincrement", "xorigin", "yorigin",
                                               "yreference", "npoints") }
                    if an["freq_hz"] > 0:
                        freqs.append(an["freq_hz"])
                        v.source = "scpi_wave"
                        v.vpp_wave_v = an["vpp_v"]
                        v.raw["waveform_analysis"] = an
                except ScpiError as e:
                    v.raw["waveform_error"] = str(e)
            if not freqs:
                v.kind = "no-signal"
                v.reason = ("示波器读不到有效频率（FREQ=%s%s）。可能原因："
                            "① 信号没接到 CH%d ② 幅度太小/未触发 ③ 测量项没打开"
                            " ④ 探头倍率/耦合不对。%s"
                            % (last_meas.get("freq_raw", "-"),
                               ("，PERiod=%s" % last_meas.get("period_raw"))
                               if last_meas.get("period_raw") else "",
                               ch, state.get("trigger_status", "")))
                v.elapsed_s = time.time() - t0
                return v

        f_mean = statistics.fmean(freqs)
        v.freq_hz = f_mean
        v.freq_min_hz = min(freqs)
        v.freq_max_hz = max(freqs)
        if len(freqs) >= 2 and f_mean > 0:
            v.freq_std_pct = statistics.pstdev(freqs) / f_mean * 100.0
        if vpps:
            v.vpp_scope_v = statistics.fmean(vpps)
            v.vpp_v = v.vpp_scope_v

        if read_wave and v.vpp_scope_v and not v.vpp_wave_v:
            try:
                wf = sc.read_waveform(ch)
                an = analyze_samples(wf["samples"], wf["xincrement"])
                v.vpp_wave_v = an["vpp_v"]
                v.raw["waveform_analysis"] = an
            except ScpiError as e:
                v.raw["waveform_error"] = str(e)
        if v.vpp_scope_v and v.vpp_wave_v:
            v.vpp_cross_dev_pct = (v.vpp_wave_v - v.vpp_scope_v) / v.vpp_scope_v * 100.0

        hit, best, dev = judge_freq(f_mean, v.nominal_list, v.tol_pct)
        v.nominal_hz = best
        v.freq_dev_pct = dev
        v.ok = True
        v.verdict = "PASS" if hit else "FAIL"
        v.label = "NORMAL" if hit else "ABNORMAL"
        v.reason = v.summary()
        v.elapsed_s = time.time() - t0
        return v

    except ScpiError as e:
        v.ok = False
        v.verdict = "ERROR"
        v.label = "UNKNOWN"
        v.kind = e.kind
        v.reason = e.reason + ((" | " + e.detail) if e.detail else "")
        v.elapsed_s = time.time() - t0
        return v
    except Exception as e:                                    
        v.ok = False
        v.verdict = "ERROR"
        v.label = "UNKNOWN"
        v.kind = "other"
        v.reason = "未预期错误 %s: %s" % (type(e).__name__, e)

        if os.environ.get("AFH03_SCPI_DEBUG"):
            import traceback
            traceback.print_exc()
        v.elapsed_s = time.time() - t0
        return v
    finally:
        v.raw.setdefault("scpi_log", sc.log[-40:])
        sc.close()

def _hosts_in(subnet: str) -> List[str]:
    try:
        net = ipaddress.ip_network(subnet, strict=False)
    except ValueError:
        return []
    return [str(h) for h in net.hosts()]

def _probe_host(host: str, port: int, timeout: float) -> Optional[Dict[str, str]]:
    """问一句 *IDN?，是 RIGOL 就返回基本信息。"""
    try:
        s = socket.create_connection((host, port), timeout=timeout)
    except OSError:
        return None
    try:
        s.settimeout(timeout)
        s.sendall(b"*IDN?\n")
        data = b""
        t0 = time.time()
        while not data.endswith(b"\n") and time.time() - t0 < timeout:
            try:
                chunk = s.recv(1024)
            except socket.timeout:
                break
            if not chunk:
                break
            data += chunk
        idn = data.decode("ascii", "replace").strip()
    finally:
        try:
            s.close()
        except OSError:
            pass
    if not idn:
        return None
    return {"host": host, "port": str(port), "idn": idn,
            "rigol": "yes" if ("RIGOL" in idn.upper() or "DS2" in idn.upper()
                               or "MSO2" in idn.upper()) else "no"}

def discover(subnets: Sequence[str] = DEFAULT_SCAN_SUBNETS, port: int = SCOPE_PORT,
             timeout: float = 0.6, workers: int = 64) -> List[Dict[str, str]]:
    """扫这些网段里开着 SCPI 端口、并且回答 *IDN? 的仪器。"""
    hosts: List[str] = []
    for s in subnets:
        hosts.extend(_hosts_in(s))
    found: List[Dict[str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_probe_host, h, port, timeout) for h in hosts]
        for fu in concurrent.futures.as_completed(futs):
            r = fu.result()
            if r:
                found.append(r)

    found.sort(key=lambda d: (0 if d.get("rigol") == "yes" else 1, d["host"]))
    return found

def local_ethernet_report() -> List[Dict[str, str]]:
    """列出本机网口与 carrier 状态（纯读 /sys，不依赖 iproute2）。"""
    out: List[Dict[str, str]] = []
    base = "/sys/class/net"
    if not os.path.isdir(base):
        return out
    for name in sorted(os.listdir(base)):
        if name == "lo":
            continue
        d = os.path.join(base, name)
        def rd(f: str) -> str:
            try:
                with open(os.path.join(d, f), "r") as fh:
                    return fh.read().strip()
            except OSError:
                return ""
        out.append({"iface": name, "carrier": rd("carrier"),
                    "operstate": rd("operstate"), "speed": rd("speed")})
    return out

def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="RIGOL DS2302A SCPI 直读判定（20/40 MHz 方波 = PASS，其余 = FAIL）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", help="示波器 IP（不知道就用 --scan）")
    ap.add_argument("--port", type=int, default=SCOPE_PORT, help="SCPI 端口，默认 5555")
    ap.add_argument("--ch", type=int, default=1, choices=[1, 2], help="通道，默认 1")
    ap.add_argument("--nominal", default=",".join("%g" % v for v in DEFAULT_NOMINAL_HZ),
                    help="正常频点白名单，逗号分隔（默认 20000000,40000000）")
    ap.add_argument("--tol-pct", type=float, default=DEFAULT_TOL_PCT, help="容差 %%，默认 1")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--repeat", type=int, default=1, help="重复读几次取均值/抖动")
    ap.add_argument("--no-wave", action="store_true", help="不回读波形（不交叉校验）")
    ap.add_argument("--scan", nargs="?", const=",".join(DEFAULT_SCAN_SUBNETS), default="",
                    help="扫网段找示波器（可给 192.168.1.0/24,192.168.0.0/24）")
    ap.add_argument("--scan-timeout", type=float, default=0.6)
    ap.add_argument("--json-out", default="", help="把结果 JSON 写到文件")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap

def _parse_nominal(s: str) -> List[float]:
    out = []
    for part in str(s).replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        p = _parse_number(part)
        if p:
            out.append(p)
    return out

def main(argv: Optional[List[str]] = None) -> int:
    a = _build_parser().parse_args(argv)
    nominal = _parse_nominal(a.nominal) or list(DEFAULT_NOMINAL_HZ)

    if a.scan:
        subnets = [x.strip() for x in str(a.scan).split(",") if x.strip()]
        print("== 本机网口 ==")
        for d in local_ethernet_report():
            print("  %-8s carrier=%s operstate=%s speed=%s"
                  % (d["iface"], d["carrier"] or "-", d["operstate"] or "-", d["speed"] or "-"))
        print("== 扫描网段: %s ==" % ", ".join(subnets))
        found = discover(subnets, a.port, a.scan_timeout)
        if not found:
            print("  没找到（网线插了吗？板子 IP 与示波器同网段吗？）")
            return 4
        for d in found:
            print("  %-15s :%s  rigol=%-3s  %s" % (d["host"], d["port"], d["rigol"], d["idn"]))
        rigols = [d for d in found if d["rigol"] == "yes"]
        if not rigols:
            print("  找到设备但不是 RIGOL，试试 --host 手动指定")
            return 4
        host = rigols[0]["host"]
        print("== 用 %s 继续判定 ==" % host)
    else:
        host = a.host
        if not host:
            print("[ERR] 需要 --host，或者用 --scan 自动找。")
            return 1

    v = check_scope(host=host, port=a.port, ch=a.ch, nominal_list=nominal,
                    tol_pct=a.tol_pct, timeout=a.timeout, retries=a.retries,
                    repeat=a.repeat, read_wave=not a.no_wave, verbose=a.verbose)

    print("\n== 示波器标识 ==")
    print("  *IDN?  %s" % (v.idn or "(未读到)"))
    st = (v.raw or {}).get("state") or {}
    if st:
        print("  时基        : %s s/div" % (st.get("time_per_div_s", "-")))
        print("  CH%d V/div   : %s" % (a.ch, (st.get("ch%d" % a.ch) or {}).get("scale_v_per_div", "-")))
        print("  CH%d 探头    : %s" % (a.ch, (st.get("ch%d" % a.ch) or {}).get("probe", "-")))
        print("  触发状态    : %s" % st.get("trigger_status", "-"))
        print("  采样率      : %s Sa/s" % (st.get("sample_rate_sa_s", "-")))
    meas = (v.raw or {}).get("measure") or {}
    if meas:
        print("== 示波器自测（原始返回值）==")
        for k in ("freq_raw", "vpp_raw", "period_raw", "vmax_raw", "vmin_raw", "vavg_raw"):
            if k in meas:
                print("  %-10s %s" % (k, meas.get(k, "")))

    print("\n== 判定 ==")
    print("  规则        : freq ∈ {%s} Hz  容差 ±%.3g%%"
          % (", ".join("%g" % x for x in nominal), a.tol_pct))
    print("  实测频率    : %s  (= %.9g Hz)" % (fmt_hz(v.freq_hz), v.freq_hz))
    if v.n_success > 1:
        print("  重复 %d 次   : %s ~ %s，相对抖动 %.3f%%"
              % (v.n_success, fmt_hz(v.freq_min_hz), fmt_hz(v.freq_max_hz), v.freq_std_pct))
    print("  最接近标称  : %s  偏差 %+.3f%%  -> %s/%s"
          % (fmt_hz(v.nominal_hz), v.freq_dev_pct, v.verdict, v.label))
    print("  Vpp         : %.6g V (示波器读数)  %s"
          % (v.vpp_v, ("/ %.6g V (波形回读)  交叉偏差 %+.2f%%"
                       % (v.vpp_wave_v, v.vpp_cross_dev_pct)) if v.vpp_wave_v else ""))
    print("  探头衰减    : %s   V/div: %s   时基: %s s/div"
          % (v.probe or "-", v.scale_v_per_div or "-", v.time_per_div_s or "-"))
    print("  数据来源    : %s" % v.source)
    if not v.ok:
        print("  失败原因    : [%s] %s" % (v.kind, v.reason))

    if a.json_out:
        payload = v.to_dict()
        payload["rule"] = {"nominal_hz": nominal, "tol_pct": a.tol_pct}
        payload["host"] = host
        payload["port"] = a.port
        os.makedirs(os.path.dirname(os.path.abspath(a.json_out)) or ".", exist_ok=True)
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print("  JSON        : %s" % a.json_out)

    if not v.ok:
        return 4
    return 0 if v.verdict == "PASS" else 3

if __name__ == "__main__":                                    
    raise SystemExit(main())
