#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scope_quick.py —— RIGOL DS2102A 一次测量（**VXI-11**）：f / T / Vpp / duty + 真实波形 + 签名写入。

本版（2026-10-25）把传输层从「5555 裸 socket」整体换成 **VXI-11**：

    板端 end0 = 192.168.88.10/24  ──LAN──  示波器 DS2102A = 192.168.88.20
    资源串   = TCPIP0::192.168.88.20::INSTR        （pyvisa + pyvisa-py，@py 后端）
    打开方式 = pyvisa.ResourceManager("@py").open_resource(...)

为什么必须换
------------
* 5555 裸 socket 路径会**卡死** DS2102A 的 LAN 应用（之后连 ``*IDN?`` 都不回，
  只能断电）——本版**已删除**该路径；``--legacy-socket`` 只是一个墓碑参数，
  传了会明确报错并提示用 VXI-11，**不会真的去连 5555**。
* 禁用命令：``:MEASure:ITEM`` 全族 / 深存储 ``RAW`` / ``:WAVeform:POINts`` / ``*RST``
  （发送前硬拦截）。
* 真实波形只走**屏幕数据**：``:WAVeform:MODE NORMal`` + ``:WAVeform:FORMat BYTE``，
  最多 2000 点；**绝不** RAW / 深存储。``:WAVeform:DATA?`` 每会话最多读 1 次、失败不重试。
* 不用 5555；默认只走 VXI-11。

★ 实测配方（2026-10-25 板端 + 真机验证；SET 顺序逐字照抄）
-----------------------------------------------------------
::

    *CLS
    :TIMebase:DELay:ENABle OFF
    :CHANnel1:DISPlay ON
    :MEASure:AREA SCReen
    :MEASure:ADISplay OFF
    :MEASure:STATistic:DISPlay OFF
    :MEASure:SOURce CHANnel1
    :MEASure:CLEar ALL
    :MEASure:PERiod CHANnel1          # SET：开启周期测量
    :MEASure:VPP CHANnel1             # SET：开启峰峰值测量
    :MEASure:PDUTy CHANnel1           # SET：开启占空比测量
    :RUN
    → sleep 1.5 s
    :MEASure:PERiod? CHANnel1         # 测量查询 1/3 ⇒ 1.000000e-03
    :MEASure:VPP?    CHANnel1         # 测量查询 2/3 ⇒ 3.06
    :MEASure:PDUTy?  CHANnel1         # 测量查询 3/3 ⇒ 0.5
    :STOP
    :WAVeform:SOURce CHANnel1         # 以下 3 条 SET = 屏幕数据（NORMal，不碰深存储）
    :WAVeform:MODE NORMal
    :WAVeform:FORMat BYTE
    :WAVeform:PREamble?               # 波形元数据（xinc/yinc/点数；只读小包）
    :WAVeform:DATA?                   # ★ 唯一 1 次波形读（≤2000 点，BYTE）
    :SYSTem:ERRor:NEXT?               # 错误队列
    :RUN

查询预算分两段：**测量 3 条（``QUERY_BUDGET``）+ 波形段 3 条（``WAVE_QUERY_BUDGET``：
Preamble / DATA / 错误队列）**，每段都在发送前硬拦截；``DATA?`` 只读 1 次。
若某条查询在传输层失败，立即停止后续查询（不再对可能已卡住的仪器补刀），
所以整会话永远 ≤6 条，且波形段不会重试。

★ 实测（2026-10-25 真机，DS2102A）：``PREamble?`` =
``0,0,1400,1,2.000000e-06,-1.400000e-03,0,2.000000e-02,-74,127``，
``DATA?`` = 1400 bytes；``xinc=2e-06 s``、``yinc=0.02 V/LSB``。
**yorig/yref 的绝对换算有偏差**，因此页面只用**相对形状**：
``(b-127)*0.02`` 后去均值；Vpp 用 ``:MEASure:VPP?`` 的实测值，不用 y 绝对换算。

判定
----
* ``f = 1 / T``（``--measure`` 读 ``:MEASure:PERiod?`` 后自己算）
* 真实波形：``samples_v``（相对电压，已按 LSB 量化）= ``(b-127)*yinc``；
  ``sample_dt_s`` = Preamble 的 xinc；``points`` = DATA 实际字节数；页面逐点绘制
* ``--expect 1k`` / ``30M`` / ``1e3`` / ``10MHz`` 都可以；``dev_pct = (f - expect) / expect * 100``
* ``|dev_pct| <= 5`` ⇒ ``pass``；``> 5`` ⇒ ``fail``；没给 ``--expect`` ⇒ ``no_reference``；
  读数无效（``9.9E+37`` / 空 / 超时 / ``<=0``）⇒ ``no_signal``
* 退出码：``0`` pass/no_reference/--list/--probe-safe 正常；``1`` 连接或写入失败；
  ``3`` fail（偏差超限）；``4`` no_signal

写结果（必须签名）
------------------
页面（``ui_kiosk.load_scope_result``）只认 ``soc_vision.scope_collect`` 的
``begin()/finish()`` 写出的结果：``collector_session`` 必须在
``/userdata/.scope_sessions.json`` 台账里，``sig = HMAC-SHA256(key,
canonical_json(items) + str(ts))`` 必须匹配。本脚本**优先**走这套 API：

::

    from soc_vision.scope_collect import begin, finish
    sess = begin(script="scope_quick")
    finish(sess, payload, "/userdata/scope_result.json")

接口不可用（找不到模块 / 缺 key / finish 抛错）时，**如实报错**，并写一份带
``"signature": "UNSIGNED"`` 标记的结果文件；页面会把它判为
「数据来源未验证（缺少采集签名 sig / 采集会话 collector_session）」并**拒绝显示数字**。
—— 即：能签就签；签不了就明确标记未签名，绝不伪装成实测。

用法
----
::

    python3 scope_quick.py --measure                 # ★ f/T/Vpp/duty + 真实屏幕波形（写正式结果）
    python3 scope_quick.py --measure --expect 1k     # 人工期望 1kHz（|偏差|≤5% ⇒ pass；非判据库）
    python3 scope_quick.py --measure --expect 30M    # 实际 1kHz ⇒ fail（验证判定链路）
    python3 scope_quick.py --measure --no-wave       # 只测不采波形（页面会标注无真实采样）
    python3 scope_quick.py --measure --no-write      # 只测不写（联调）
    python3 scope_quick.py --probe-safe              # 只发 3 条只读查询（*IDN? / 错误队列 / 测量源）
    python3 scope_quick.py --list                    # 同 --probe-safe 的只读信息（不写结果）
    python3 scope_quick.py --enable                  # 跑完整配方 + 查询，但不写结果
    python3 scope_quick.py --ip 192.168.88.20 --ch 1 --expect 1k
    python3 scope_quick.py --dry-run                 # 只打印解析后的参数（PC 上可不装 pyvisa）
    python3 scope_quick.py --legacy-socket           # ✗ 墓碑：会明确报错（5555 会卡死，已移除）

板端位置：``/userdata/work2/scope_quick.py``
PC 副本：``D:\\xuexishengshou\\工作区2\\tools_wave\\scope_quick.py``
"""
from __future__ import annotations

import argparse
import hmac
import importlib
import importlib.util
import json
import math
import os
import re
import sys
import time
from datetime import datetime

DEFAULT_IP = "192.168.88.20"                       
DEFAULT_RESOURCE = "TCPIP0::%s::INSTR"             
BOARD_RESULT = "/userdata/scope_result.json"       
DEFAULT_RESULT = os.environ.get("AFH03_SCOPE_RESULT", BOARD_RESULT)
DEFAULT_TOL = 5.0                                  

DEFAULT_TIMEOUT = 8.0                              
PREP_WAIT = 1.5                                    
DEFAULT_GAP = 0.05                                 
MIN_GAP = 0.02
QUERY_BUDGET = 3                                   
WAVE_QUERY_BUDGET = 3                              
SESSION_QUERY_BUDGET = QUERY_BUDGET + WAVE_QUERY_BUDGET   
WAVE_MAX_POINTS = 2000                             
WAVE_DEFAULT_DT = 2e-6                             
WAVE_Y_INC = 0.02                                  
WAVE_CENTER_LSB = 127                              
WAVE_JSON_LIMIT = 60000                            
NO_SIGNAL_FLOOR = 1e30                             

EXIT_OK, EXIT_ERR, EXIT_FAIL, EXIT_NOSIGNAL = 0, 1, 3, 4

_FORBIDDEN = (
    ":MEAS:ITEM", ":MEASURE:ITEM",                 
    "RAW", "DEEP", "MEMORY", ":MEM:DATA",          
    ":WAVEFORM:POINTS", ":WAV:POIN",               
    "*RST", ":SYST:PRES", ":SYSTEM:PRESET",
)

_WAVE_ALLOW_PREFIX = (":WAVEFORM:SOURCE ",)
_WAVE_ALLOW_EXACT = (
    ":WAVEFORM:MODE NORMAL", ":WAVEFORM:FORMAT BYTE",
    ":WAVEFORM:PREAMBLE?", ":WAVEFORM:DATA?",
)

try:                       
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:          
    pass

class ScopeError(RuntimeError):
    """连接/协议/命令错误（退出码 1）。"""

class NoSignal(RuntimeError):
    """读数无效：9.9E+37 / 空响应 / <=0 / <TIMEOUT>（退出码 4）。"""

def now_iso():
    """ISO8601（带本地时区），页面 `_scope_ts` 可直接解析。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")

def say(msg=""):
    print(msg, flush=True)

def _vxi_resource(ip):
    return DEFAULT_RESOURCE % str(ip).strip()

def _expect_hz(text):
    """把 ``1k`` / ``30M`` / ``1e3`` / ``10MHz`` / ``1.5G`` / ``100k`` 解析成 Hz。"""
    s = str(text).strip().replace("_", "").replace(" ", "")
    m = re.fullmatch(r"([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?:[eE]([-+]?\d+))?([kKmMgG]?)(?:[hH][zZ])?",
                     s)
    if not m:
        raise argparse.ArgumentTypeError("频率写法不认识：%r（例：30M / 10MHz / 1.5G / 1e3）" % text)
    val = float(m.group(1))
    if m.group(2):
        val *= 10.0 ** int(m.group(2))
    mult = {"": 1.0, "k": 1e3, "m": 1e6, "g": 1e9}[m.group(3).lower()]
    hz = val * mult
    if not math.isfinite(hz) or hz <= 0:
        raise argparse.ArgumentTypeError("频率必须 > 0：%r" % text)
    return hz

def parse_period(raw):
    """解析 ``:MEASure:PERiod?`` 的返回；无效值抛 NoSignal。

    兼容：``1.000000e-03`` / ``3.333333E-08`` / ``+3.3E-8`` / 带引号 / 前后说明文字。
    ``9.9E+37``（无信号）和 ``<TIMEOUT>``（查询超时）都抛 NoSignal。
    """
    s = str(raw or "").strip().strip('"').strip("'").strip()
    if not s:
        raise NoSignal("空响应")
    if "TIMEOUT" in s.upper() or s.startswith("<"):
        raise NoSignal("查询超时无回包（%s）" % s)
    try:
        t = float(s)
    except ValueError:
        m = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", s)
        if not m:
            raise NoSignal("无法解析周期 %r" % raw)
        t = float(m.group(0))
    if not math.isfinite(t):
        raise NoSignal("非有限值 %r" % raw)
    if t <= 0:
        raise NoSignal("周期 <= 0（%r）" % raw)
    if t >= NO_SIGNAL_FLOOR:
        raise NoSignal("仪器报无效值 %r（9.9E+37 = 测量项未开启 / 无信号）" % raw)
    return t

def parse_level(raw, what="Vpp"):
    """解析 Vpp 等电平读数；``9.9E+37`` / 空 / ``<TIMEOUT>`` / 非有限 都抛 NoSignal。"""
    s = str(raw or "").strip().strip('"').strip("'").strip()
    if not s:
        raise NoSignal("空响应")
    if "TIMEOUT" in s.upper() or s.startswith("<"):
        raise NoSignal("查询超时无回包（%s）" % s)
    try:
        v = float(s)
    except ValueError:
        m = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", s)
        if not m:
            raise NoSignal("无法解析%s %r" % (what, raw))
        v = float(m.group(0))
    if not math.isfinite(v):
        raise NoSignal("非有限值 %r" % raw)
    if v < 0:
        raise NoSignal("%s 为负（%r）；示波器报错或查询错位" % (what, raw))
    if v >= NO_SIGNAL_FLOOR:
        raise NoSignal("仪器报无效值 %r（9.9E+37 = 测量项未开启 / 无信号）" % raw)
    return v

def parse_duty(raw):
    """解析 ``:MEASure:PDUTy?``：DS2102A 实测返回 0.5（比例）。

    兼容 50（百分数）；返回 0..1 的比例。无效值抛 NoSignal。
    """
    v = parse_level(raw, "Duty")
    if v > 1.0:
        if v <= 100.0:
            v /= 100.0
        else:
            raise NoSignal("占空比超出 0..100%%：%r" % raw)
    return v

def parse_preamble(raw):
    """解析 ``:WAVeform:PREamble?`` → dict（RIGOL 10 字段）。

    实测顺序：format,type,points,count,xincrement,xorigin,xreference,
    yincrement,yorigin,yreference。**不采用 yorigin 做绝对电压**（实测有偏差），
    只取 xinc / yinc / 点数；y 绝对换算交给页面做相对形状。
    """
    parts = [p.strip() for p in str(raw or "").split(",")]
    if len(parts) < 10:
        raise ScopeError("Preamble 字段不足 10 个：%r" % raw)
    try:
        vals = [float(p) for p in parts[:10]]
    except ValueError as e:
        raise ScopeError("Preamble 含非数字字段：%r（%s）" % (raw, e))
    xinc, yinc = vals[4], vals[7]
    if not math.isfinite(xinc) or xinc <= 0:
        raise ScopeError("Preamble xinc 非法：%r" % xinc)
    if not math.isfinite(yinc) or yinc <= 0:
        raise ScopeError("Preamble yinc 非法：%r" % yinc)
    return {"format": int(vals[0]), "type": int(vals[1]), "points_hdr": int(vals[2]),
            "count": int(vals[3]), "xinc": xinc, "xorig": vals[5], "xref": vals[6],
            "yinc": yinc, "yorig": vals[8], "yref": vals[9]}

def error_is_no_error(raw):
    """``0,"No error"`` / ``+0,"No error"`` ⇒ True；任何 ``-113`` 之类 ⇒ False。"""
    s = str(raw or "").strip()
    if not s:
        return False
    if "NO ERROR" in s.upper():
        return True
    return bool(re.match(r"^\+?0(?:\.0+)?(?:\s|,|$)", s))

def idn_model(idn):
    """从 *IDN? 取型号（第 2 段）；取不到就整串。"""
    parts = [p.strip() for p in str(idn or "").split(",")]
    if len(parts) >= 2 and parts[1]:
        return parts[1]
    return parts[0] if parts else str(idn or "")

def idn_is_rigol(idn):
    return str(idn or "").split(",")[0].strip().upper().startswith("RIGOL")

def judge(hz, expect, tol=DEFAULT_TOL):
    """返回 ``(state, dev_pct)``；state ∈ pass/fail/no_reference/no_signal。"""
    try:
        f = float(hz)
    except (TypeError, ValueError):
        return "no_signal", None
    if not math.isfinite(f) or f <= 0:
        return "no_signal", None
    if expect is None:
        return "no_reference", None
    dev = (f - float(expect)) / float(expect) * 100.0
    if not math.isfinite(dev):
        return "no_signal", None
    dev = round(dev, 6)
    if dev == 0:
        dev = 0.0
    return ("pass" if abs(dev) <= float(tol) else "fail"), dev

def fmt_hz(hz):
    """人类可读频率：``1000.000 Hz (1.0000 kHz)`` / ``30.000 MHz``。"""
    if hz is None:
        return "—"
    try:
        f = float(hz)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(f) or f <= 0:
        return "—"
    if f >= 1e9:
        return "%.4f GHz" % (f / 1e9)
    if f >= 1e6:
        return "%.3f MHz" % (f / 1e6)
    if f >= 1e3:
        return "%.3f Hz (%.4f kHz)" % (f, f / 1e3)
    return "%.4f Hz" % f

def fmt_sec(s):
    if s is None:
        return "—"
    try:
        v = float(s)
    except (TypeError, ValueError):
        return "—"
    if v >= 1.0:
        return "%.6f s" % v
    if v >= 1e-3:
        return "%.6f ms" % (v * 1e3)
    if v >= 1e-6:
        return "%.6f us" % (v * 1e6)
    return "%.6f ns" % (v * 1e9)

class VxiScope(object):
    """RIGOL DS2102A 的最小 VXI-11 客户端。

    * 一个实例 = 一条 VXI-11 会话；**用完必 close()**；
    * 查询数硬上限 ``max_queries``（默认 3 = 测量段）：第 N+1 条在**发送前**拒绝；
    * 所有发送前过 ``_guard``：禁 :MEASure:ITEM 族 / RAW 深存储 / *RST；
      波形只允许 NORMal + BYTE 的屏幕数据；
    * 文本查询 + **唯一 1 次** ``query_binary_values(:WAVeform:DATA?)``。
    """

    def __init__(self, ip=DEFAULT_IP, resource="", timeout=DEFAULT_TIMEOUT,
                 gap=DEFAULT_GAP, max_queries=QUERY_BUDGET):
        self.ip = str(ip).strip()
        self.resource = str(resource or _vxi_resource(self.ip)).strip()
        self.timeout = max(0.5, float(timeout))
        self.gap = max(MIN_GAP, float(gap))
        self.max_queries = int(max_queries or 0)      
        self.n_queries = 0
        self.commands = []
        self.inst = None
        self.rm = None
        self.via = "vxi11"
        self.endpoint = self.resource
        self._last = 0.0

    def open(self):
        try:
            import warnings
            warnings.filterwarnings("ignore")
            import pyvisa
        except ImportError as e:
            raise ScopeError(
                "缺少 pyvisa / pyvisa-py（VXI-11 必需）：%s\n"
                "  板端应已预装；PC 联调可 pip install pyvisa pyvisa-py" % e)
        t0 = time.monotonic()
        try:
            self.rm = pyvisa.ResourceManager("@py")
            self.inst = self.rm.open_resource(self.resource)
            self.inst.timeout = int(max(500, self.timeout * 1000))
            self.inst.read_termination = "\n"
            self.inst.write_termination = "\n"
        except Exception as e:                          
            self.close()
            raise ScopeError("VXI-11 打开 %s 失败：%s: %s"
                             % (self.resource, type(e).__name__, e))
        self._last = 0.0
        say("[OK] VXI-11 已连接 %s（pyvisa-py @py，timeout %.1fs，%.0f ms）"
            % (self.resource, self.timeout, (time.monotonic() - t0) * 1000))
        return self

    def _guard(self, cmd):
        up_raw = str(cmd).upper().strip()
        up = up_raw.replace(" ", "")
        for bad in _FORBIDDEN:
            if bad in up:
                raise ScopeError(
                    "拒绝发送危险命令 %r（安全红线：禁 :MEASure:ITEM 族 / RAW 深存储 / "
                    "点数设置 / *RST）" % cmd)
        if up.startswith(":WAV"):
            if not (up_raw in _WAVE_ALLOW_EXACT
                    or any(up_raw.startswith(x) for x in _WAVE_ALLOW_PREFIX)):
                raise ScopeError(
                    "拒绝发送未批准的波形命令 %r（只允许屏幕 NORMal/BYTE 的 "
                    "SOURce/MODE/FORMat/PREamble?/DATA?）" % cmd)

    def _wait_gap(self):
        if self._last:
            left = self.gap - (time.monotonic() - self._last)
            if left > 0:
                time.sleep(left)

    def _take_query_quota(self, cmd):
        """★ 查询硬上限：在发送前检查；超了直接 ScopeError，不占用 8s 超时。"""
        if self.max_queries and self.n_queries >= self.max_queries:
            raise ScopeError(
                "拒绝发送第 %d 条查询 %r：本会话查询上限 %d 条（VXI-11 查询预算）"
                % (self.n_queries + 1, cmd, self.max_queries))
        self.n_queries += 1

    def write(self, cmd):
        """短 SET：发完即返回；不产生回包、不占查询额度。"""
        self._guard(cmd)
        if self.inst is None:
            raise ScopeError("VXI-11 会话未打开")
        line = str(cmd).strip()
        self._wait_gap()
        try:
            self.inst.write(line)
        except Exception as e:                          
            raise ScopeError("VXI-11 发送 %r 失败：%s: %s" % (line, type(e).__name__, e))
        self._last = time.monotonic()
        self.commands.append(line)

    def query(self, cmd):
        """发一条查询并读回一行；失败抛 ScopeError（**本会话不自动重试**）。"""
        self._guard(cmd)
        if self.inst is None:
            raise ScopeError("VXI-11 会话未打开")
        self._take_query_quota(cmd)
        line = str(cmd).strip()
        self._wait_gap()
        try:
            raw = self.inst.query(line)
        except Exception as e:                          
            raise ScopeError("VXI-11 查询 %r 失败：%s: %s" % (line, type(e).__name__, e))
        self._last = time.monotonic()
        self.commands.append(line)
        text = str(raw or "").strip()
        if not text:
            raise ScopeError("VXI-11 查询 %r 返回空回包" % line)
        return text.splitlines()[0].strip()

    def query_binary_values(self, cmd, datatype="B", container=bytes, delay=0.2):
        """★ 唯一允许的二进制读：``:WAVeform:DATA?``（BYTE，屏幕 NORMal）。

        占 1 条查询额度；**本会话不重试**。返回值必须是 bytes（或可转 bytes 的序列）。
        ``delay`` 给仪器一点发块数据的准备时间（实测 0.2s 足够）。
        """
        self._guard(cmd)
        if self.inst is None:
            raise ScopeError("VXI-11 会话未打开")
        self._take_query_quota(cmd)
        line = str(cmd).strip()
        self._wait_gap()
        try:
            raw = self.inst.query_binary_values(line, datatype=datatype,
                                                container=container, delay=float(delay))
        except Exception as e:                          
            raise ScopeError("VXI-11 二进制查询 %r 失败：%s: %s"
                             % (line, type(e).__name__, e))
        self._last = time.monotonic()
        self.commands.append(line)
        if isinstance(raw, bytes):
            data = raw
        elif isinstance(raw, bytearray):
            data = bytes(raw)
        elif isinstance(raw, (list, tuple)):
            try:
                data = bytes(int(x) & 0xFF for x in raw)
            except (TypeError, ValueError) as e:
                raise ScopeError("波形二进制数据无法转 bytes：%s" % e)
        else:
            raise ScopeError("波形二进制返回类型异常：%s" % type(raw).__name__)
        if not data:
            raise ScopeError("VXI-11 二进制查询 %r 返回空数据" % line)
        return data

    def close(self):
        """关闭会话；**不发任何命令**（收尾不给仪器添负担）。"""
        if self.inst is not None:
            try:
                self.inst.close()
            except Exception:                           
                pass
            self.inst = None
        if self.rm is not None:
            try:
                self.rm.close()
            except Exception:                           
                pass
            self.rm = None

def measure_setup_steps(ch):
    chn = "CHANnel%d" % int(ch)
    return [
        ("*CLS", "清状态/错误队列"),
        (":TIMebase:DELay:ENABle OFF", "关延迟扫描"),
        (":%s:DISPlay ON" % chn, "开通道显示"),
        (":MEASure:AREA SCReen", "全屏测量区（防被设成光标区）"),
        (":MEASure:ADISplay OFF", "关测量显示（给仪器减负）"),
        (":MEASure:STATistic:DISPlay OFF", "关统计显示（关键：统计会让查询很慢）"),
        (":MEASure:SOURce %s" % chn, "测量源"),
        (":MEASure:CLEar ALL", "清历史统计"),
        (":MEASure:PERiod %s" % chn, "★ 开启周期测量（SET）"),
        (":MEASure:VPP %s" % chn, "★ 开启峰峰值测量（SET）"),
        (":MEASure:PDUTy %s" % chn, "★ 开启占空比测量（SET）"),
        (":RUN", "运行"),
    ]

def run_recipe(sc, ch, log=say):
    steps = measure_setup_steps(ch)
    log("[..] 整备：%d 条 SET（VXI-11，逐字照抄真机验证配方）" % len(steps))
    for i, (cmd, desc) in enumerate(steps, 1):
        sc.write(cmd)
        log("[SET %02d/%02d] %-40s # %s" % (i, len(steps), cmd, desc))
    log("[..] 等 %.1fs（:RUN 之后给采集/测量稳定时间）" % PREP_WAIT)
    time.sleep(PREP_WAIT)

def _safe_query(sc, cmd, log=say):
    """发 1 条查询并记录；返回 ``(raw, ok)``。失败不重试（查询预算有限）。"""
    log("[Q %d/%d] %s" % (sc.n_queries + 1, sc.max_queries or 0, cmd))
    try:
        raw = sc.query(cmd)
    except ScopeError as e:
        log("        -> ✗ %s" % e)
        return "", False
    log("        -> %s" % raw)
    return raw, True

def build_reason(ch, m, state, dev, tol, expect):
    name = "CH%d" % int(ch)
    hz, period, vpp = m.get("measured_hz"), m.get("period_s"), m.get("vpp_v")
    vtxt = "—" if vpp is None else "%.4g V" % vpp
    duty = m.get("duty")
    dtxt = "" if duty is None else "，占空比 %.2f%%" % (duty * 100.0)
    wave = m.get("wave") or {}
    wtxt = ("，真实屏幕波形 %d 点" % int(wave.get("points") or 0)) if wave else "，无真实波形"
    if state == "no_signal":
        if m.get("transport_error"):
            return ("%s 周期查询在传输层失败（VXI-11 无回包/会话中断）：不是无信号，"
                    "是通信没拿到读数；已停止后续查询，本会话只发了 %s 条"
                    % (name, m.get("queries")))
        return ("%s 无有效周期读数（原始 %r；周期测量未开启 / CH%d 无信号）"
                % (name, m.get("raw_period") or "", int(ch)))
    if state == "no_reference":
        return ("%s 实测 %s（T = %s），Vpp = %s%s%s；未给 --expect ⇒ 不判定，"
                "页面按判据库 28 项自动匹配" % (name, fmt_hz(hz), fmt_sec(period), vtxt, dtxt, wtxt))
    if state == "pass":
        return ("%s 实测 %s（T = %s），Vpp = %s%s%s，期望 %s，偏差 %+.3f%%（|偏差| ≤ %g%%）"
                % (name, fmt_hz(hz), fmt_sec(period), vtxt, dtxt, wtxt,
                   fmt_hz(expect), dev, tol))
    return ("%s 实测 %s（T = %s），Vpp = %s%s%s，期望 %s，偏差 %+.3f%%（超出 ±%g%%，判 fail）"
            % (name, fmt_hz(hz), fmt_sec(period), vtxt, dtxt, wtxt,
               fmt_hz(expect), dev, tol))

def build_wave(data, pre):
    """把屏幕 BYTE 采样转成**相对电压**（去均值居中），返回 JSON 字段。

    * ``samples_v``：``(b-127)*yinc`` 后减去均值，保留 3 位小数；**不是**合成曲线；
    * ``sample_dt_s``：Preamble 的 xinc；
    * Vpp 用示波器 ``:MEASure:VPP?`` 的读数，不用 y 绝对换算。
    """
    n = len(data)
    if n <= 10:
        raise ScopeError("波形点数过少（%d）" % n)
    if n > WAVE_MAX_POINTS:
        raise ScopeError("波形点数 %d 超过安全上限 %d（拒绝深存储数据）"
                         % (n, WAVE_MAX_POINTS))
    yinc = float(pre.get("yinc") or WAVE_Y_INC)
    vals = [(int(b) - WAVE_CENTER_LSB) * yinc for b in data]
    mean = sum(vals) / float(n)
    centered = [round(v - mean, 3) for v in vals]

    centered = [0.0 if v == 0 else v for v in centered]
    return {
        "samples_v": centered,
        "sample_dt_s": float(pre.get("xinc") or 0.0),
        "points": n,
        "wave_source": "scope_screen_NORMal_BYTE",
        "wave_mode": "NORMal",
        "wave_format": "BYTE",
        "wave_xinc_s": float(pre.get("xinc") or 0.0),
        "wave_yinc_v": yinc,
        "wave_center_lsb": WAVE_CENTER_LSB,
        "wave_mean_v": round(mean, 6),
        "wave_vpp_v": round(max(vals) - min(vals), 6),
        "wave_decimated": False,
    }

def _fit_json_size(payload, item, limit=WAVE_JSON_LIMIT):
    """结果 JSON 超过 ``limit`` 字节时，把波形等间隔降到 700 点（仍是真实采样）。

    ``sample_dt_s`` 同步乘以步长；``points`` 更新；并标记 ``wave_decimated=true``。
    HMAC 在写完 payload 后才算，所以这里改 items 不影响签名。
    """
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) <= limit:
        return payload, item
    samples = list(item.get("samples_v") or [])
    if not samples:
        return payload, item
    step = 2 if len(samples) > 700 else 1
    if step == 1:
        return payload, item
    dec = samples[::step]
    item["samples_v"] = dec
    item["points"] = len(dec)
    try:
        item["sample_dt_s"] = float(item.get("sample_dt_s") or 0.0) * step
        item["wave_xinc_s"] = float(item.get("wave_xinc_s") or 0.0) * step
    except (TypeError, ValueError):
        pass
    item["wave_decimated"] = True
    item["wave_decimate_step"] = step
    for k in ("points", "sample_dt_s", "wave_source", "wave_decimated"):
        if k in item:
            payload[k] = item[k]
    return payload, item

def build_item(args, m, state, dev, tol):
    ch = int(args.ch)
    wave = m.get("wave") or {}
    item = {
        "name": args.item or "CH%d 实测频率" % ch,
        "channel": "CH%d" % ch,
        "field": str(args.field or ""),
        "expect_hz": args.expect,
        "expect_source": ("manual_expect" if args.expect is not None else ""),
        "measured_hz": m.get("measured_hz"),
        "period_s": m.get("period_s"),
        "vpp_v": m.get("vpp_v"),
        "duty": m.get("duty"),
        "dev_pct": dev,
        "tol_pct": float(tol),
        "verdict": state,                 
        "shape": ("sampled" if wave else str(args.shape or "sine")),
        "signal": "no_signal" if state == "no_signal" else "ok",
        "freq_source": "1/T",
        "raw_period": m.get("raw_period") or "",
        "raw_vpp": m.get("raw_vpp") or "",
        "raw_duty": m.get("raw_duty") or "",
        "reason": m.get("reason") or "",
    }
    item.update(wave)
    return item

def build_payload(args, m, item, state, dev, tol, resource, ts):
    verdict_cn = {"pass": "正常", "fail": "不正常",
                  "no_reference": "未判定", "no_signal": "未判定"}[state]
    ch = int(args.ch)
    return {
        "source": "lan",                  
        "transport": "vxi11",             
        "ts": ts,                         
        "measured_at": ts,
        "instrument": "DS2102A",          
        "resource": resource,
        "channel": "CH%d" % ch,
        "items": [item],
        "verdict": verdict_cn,
        "reason": item.get("reason") or "",
        "mode": "vxi11_measure",
        "shape": str(args.shape or "sine"),
        "freq_source": "1/T",
        "tolerance_pct": float(tol),
        "expect_hz": args.expect,
        "measured_hz": m.get("measured_hz"),
        "period_s": m.get("period_s"),
        "vpp_v": m.get("vpp_v"),
        "duty": m.get("duty"),
        "sample_dt_s": item.get("sample_dt_s"),
        "points": item.get("points"),
        "wave_source": item.get("wave_source"),
        "wave_vpp_v": item.get("wave_vpp_v"),
        "dev_pct": dev,
        "query_count": int(m.get("queries") or 0),
        "query_budget": SESSION_QUERY_BUDGET,
        "measure_query_budget": QUERY_BUDGET,
        "wave_query_budget": WAVE_QUERY_BUDGET,
        "query_policy": ("测量 %d 条 + 波形段 %d 条（Preamble?/DATA?/ERRor?）；"
                         "DATA? 只读 1 次、失败不重试；第 7 条发送前拒绝"
                         % (QUERY_BUDGET, WAVE_QUERY_BUDGET)),
        "sys_error": m.get("sys_error") or "",
        "commands": list(m.get("commands") or []),
        "tool": "scope_quick.py",
        "tool_version": "vxi11-20261025",
    }

def _load_module_file(path):
    name = "scope_collect_%d" % (abs(hash(path)) % 100000)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def _has_api(mod):
    return all(callable(getattr(mod, n, None)) for n in ("begin", "finish", "abort"))

def load_collector(explicit=""):
    """找到 ``soc_vision.scope_collect``（板端/PC 都能用），返回 (module, 来源说明)。

    顺序：--collector → 环境变量 → 板端包目录 → 脚本目录 → cwd。
    找不到就**报错**（绝不悄悄退化成手写 JSON）。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    roots, files = [], []

    if explicit:
        p = os.path.abspath(os.path.expanduser(explicit))
        if os.path.isdir(p):
            roots.insert(0, p)
        elif os.path.isfile(p):
            files.insert(0, p)
        else:
            raise ScopeError("--collector 路径不存在：%s" % p)

    for env_name, bucket in (("AFH03_SOC_VISION", roots), ("AFH03_SCOPE_COLLECT", files)):
        v = os.environ.get(env_name, "")
        if v:
            bucket.insert(0, v)

    roots += ["/home/rock/afh03_board_setup", here, os.getcwd(),
              "/userdata/work2", "/userdata"]
    files += [os.path.join(here, "soc_vision", "scope_collect.py"),
              os.path.join(here, "scope_collect.py"),
              "/home/rock/afh03_board_setup/soc_vision/scope_collect.py",
              "/userdata/work2/soc_vision/scope_collect.py"]

    seen = set()
    for root in roots:
        if not root or root in seen:
            continue
        seen.add(root)
        pkg = os.path.join(root, "scope_collect.py") if root.endswith("soc_vision") \
            else os.path.join(root, "soc_vision", "scope_collect.py")
        if not os.path.isfile(pkg):
            continue
        if root not in sys.path:
            sys.path.insert(0, root)
        try:
            mod = importlib.import_module("soc_vision.scope_collect")
            if _has_api(mod):
                return mod, "import soc_vision.scope_collect（root=%s）" % root
        except Exception:                                          
            pass
        mod = _load_module_file(pkg)
        if mod is not None and _has_api(mod):
            return mod, pkg

    seen_f = set()
    for f in files:
        if not f or f in seen_f:
            continue
        seen_f.add(f)
        if not os.path.isfile(f):
            continue
        mod = _load_module_file(f)
        if mod is not None and _has_api(mod):
            return mod, f

    raise ScopeError(
        "找不到 soc_vision/scope_collect.py（页面只认它写的结果）。\n"
        "  板端应放在 /home/rock/afh03_board_setup/soc_vision/ 或 /userdata/work2/soc_vision/；\n"
        "  PC 联调可用 --collector <scope_collect.py 路径>，或设 AFH03_SOC_VISION=<包根目录>。")

def write_result_via_collector(mod, payload, result_path=""):
    """begin() → finish()（finish 内补 ts/session/sig 并原子写）。失败 abort()。"""
    sess = mod.begin(script="scope_quick_vxi11")
    try:
        return mod.finish(sess, payload, result_path or "")
    except BaseException:
        try:
            mod.abort(sess)
        except Exception:                                          
            pass
        raise

def _atomic_write_json(path, obj, mode=0o644):
    path = os.path.abspath(path)
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")
        f.flush()
        os.fsync(f.fileno())
    try:
        os.chmod(tmp, mode)
    except Exception:                                              
        pass
    os.replace(tmp, path)

def write_unsigned(payload, path, why):
    """签名接口不可用时的诚实降级：写 ``signature=UNSIGNED``，页面会拒绝显示。"""
    out = dict(payload)
    out["signature"] = "UNSIGNED"
    out["sig"] = ""
    out["collector_session"] = ""
    out["unsigned_reason"] = str(why or "")
    out["unsigned_at"] = now_iso()
    _atomic_write_json(path, out)
    return out

def open_scope(args, max_queries=QUERY_BUDGET):
    resource = args.resource or _vxi_resource(args.ip)
    sc = VxiScope(ip=args.ip, resource=resource, timeout=args.timeout,
                  gap=args.gap, max_queries=max_queries)
    sc.open()
    return sc

def open_scope(args, max_queries=QUERY_BUDGET):
    resource = args.resource or _vxi_resource(args.ip)
    sc = VxiScope(ip=args.ip, resource=resource, timeout=args.timeout,
                  gap=args.gap, max_queries=max_queries)
    sc.open()
    return sc

def _capture_wave(sc, chn, m, log=say):
    """★ 读**真实屏幕波形**：STOP → NORMal/BYTE → Preamble? → DATA?（仅 1 次）。

    严格限制：≤2000 点；绝不 RAW/深存储；DATA? 失败不重试。
    """
    log("[..] 波形：STOP 后取屏幕数据（MODE NORMal / FORMat BYTE，≤%d 点）"
        % WAVE_MAX_POINTS)
    sc.write(":STOP")
    m["stopped"] = True
    time.sleep(0.2)
    sc.write(":WAVeform:SOURce %s" % chn)
    sc.write(":WAVeform:MODE NORMal")
    sc.write(":WAVeform:FORMat BYTE")
    pre_raw, ok_pre = _safe_query(sc, ":WAVeform:PREamble?")
    if not ok_pre:
        raise ScopeError("VXI-11 Preamble 查询失败（波形段不重试）")
    m["queries_ok"] += 1
    pre = parse_preamble(pre_raw)
    log("         xinc=%.9g s  yinc=%.9g V/LSB  点数头=%d"
        % (pre["xinc"], pre["yinc"], pre["points_hdr"]))
    if pre["points_hdr"] <= 0 or pre["points_hdr"] > WAVE_MAX_POINTS:
        raise ScopeError("Preamble 点数 %d 超出安全范围 1..%d（拒绝深存储数据，不读 DATA）"
                         % (pre["points_hdr"], WAVE_MAX_POINTS))
    data = sc.query_binary_values(":WAVeform:DATA?", datatype="B",
                                  container=bytes, delay=0.2)
    m["queries_ok"] += 1

    if pre["points_hdr"] < len(data) <= pre["points_hdr"] + 2:
        data = data[:pre["points_hdr"]]
    log("         收到 %d bytes（= 数据点，BYTE）" % len(data))
    wave = build_wave(data, pre)
    log("         真实波形 %d 点 ｜ 相对 Vpp=%.3f V ｜ dt=%.3g s ｜ 已去均值"
        % (wave["points"], wave["wave_vpp_v"], wave["sample_dt_s"]))
    return wave

def do_measure(args):
    ch = int(args.ch)
    chn = "CHANnel%d" % ch
    tol = float(args.tol)
    shape = str(args.shape or "sine").strip().lower()
    if shape not in ("sine", "square"):
        raise ScopeError("--shape 只支持 sine / square（收到 %r）" % args.shape)
    resource = args.resource or _vxi_resource(args.ip)
    want_wave = not bool(getattr(args, "no_wave", False))

    say("")
    say("=== 一次测量（VXI-11）：%d 条 SET → 等 %.1fs → ≤%d 条查询（测量 %d + 波形段 %d）==="
        % (len(measure_setup_steps(ch)), PREP_WAIT, SESSION_QUERY_BUDGET,
           QUERY_BUDGET, WAVE_QUERY_BUDGET))
    say("    资源 : %s" % resource)
    say("    测量 : PERiod? / VPP? / PDUTy?")
    say("    波形 : NORMal + BYTE，Preamble? + DATA?（1 次，≤%d 点，绝不 RAW）"
        % WAVE_MAX_POINTS)

    m = {"period_s": None, "measured_hz": None, "vpp_v": None, "duty": None,
         "raw_period": "", "raw_vpp": "", "raw_duty": "", "sys_error": "",
         "period_ok": False, "vpp_ok": False, "duty_ok": False,
         "transport_error": False, "wave": {}, "wave_error": "", "stopped": False,
         "queries": 0, "queries_ok": 0, "commands": [], "resource": resource}
    sc = None
    try:
        sc = open_scope(args, max_queries=SESSION_QUERY_BUDGET)
        if args.no_enable:
            say("[..] --no-enable：跳过 %d 条 SET，直接等 %.1fs 后查询"
                % (len(measure_setup_steps(ch)), PREP_WAIT))
            time.sleep(PREP_WAIT)
        else:
            run_recipe(sc, ch)

        raw_p, ok_p = _safe_query(sc, ":MEASure:PERiod? %s" % chn)
        m["raw_period"] = raw_p
        if ok_p:
            m["queries_ok"] += 1
            try:
                m["period_s"] = parse_period(raw_p)
                hz = 1.0 / m["period_s"]
                if math.isfinite(hz) and hz > 0:
                    m["measured_hz"] = hz
                    m["period_ok"] = True
                else:
                    say("[WARN] 1/T 结果非法（T=%r）" % raw_p)
            except NoSignal as e:
                say("[WARN] 周期读数无效：%s" % e)
        else:
            m["transport_error"] = True
            say("[WARN] 周期查询失败 ⇒ 按规矩停止后续查询，不再对仪器补刀")

        if not m["transport_error"]:
            raw_v, ok_v = _safe_query(sc, ":MEASure:VPP? %s" % chn)
            m["raw_vpp"] = raw_v
            if ok_v:
                m["queries_ok"] += 1
                try:
                    m["vpp_v"] = parse_level(raw_v, "Vpp")
                    m["vpp_ok"] = True
                except NoSignal as e:
                    say("[WARN] Vpp 读数无效：%s" % e)
            else:
                m["transport_error"] = True
                say("[WARN] Vpp 查询失败 ⇒ 停止后续查询")

        if not m["transport_error"]:
            raw_d, ok_d = _safe_query(sc, ":MEASure:PDUTy? %s" % chn)
            m["raw_duty"] = raw_d
            if ok_d:
                m["queries_ok"] += 1
                try:
                    m["duty"] = parse_duty(raw_d)
                    m["duty_ok"] = True
                except NoSignal as e:
                    say("[WARN] 占空比读数无效：%s" % e)
            else:
                m["transport_error"] = True
                say("[WARN] 占空比查询失败 ⇒ 跳过波形段，不再补刀")

        if want_wave and not m["transport_error"] and (m["period_ok"] or m["vpp_ok"]):
            try:
                m["wave"] = _capture_wave(sc, chn, m)
            except ScopeError as e:
                m["wave_error"] = str(e)
                say("[WARN] 真实波形未采到：%s（不重试）" % e)
                if "VXI-11" in str(e) or "预算" in str(e):
                    m["transport_error"] = True
        elif not want_wave:
            say("[..] --no-wave：跳过真实波形采集")

        if not m["transport_error"]:
            raw_e, ok_e = _safe_query(sc, ":SYSTem:ERRor:NEXT?")
            if ok_e:
                m["queries_ok"] += 1
                m["sys_error"] = raw_e
                if error_is_no_error(raw_e):
                    say("[OK] 错误队列：%s" % raw_e)
                else:
                    say("[WARN] 错误队列非空：%s（可能某条 SET 未被接受）" % raw_e)
    except ScopeError as e:
        m["transport_error"] = True
        say("[FAIL] VXI-11 会话失败：%s" % e)
    finally:
        if sc is not None:
            if m.get("stopped"):
                try:
                    sc.write(":RUN")
                    say("[..] 已 :RUN 恢复示波器运行")
                except Exception as e:                             
                    say("[WARN] 恢复 :RUN 失败：%s" % e)
            m["queries"] = sc.n_queries
            m["commands"] = list(sc.commands)
            sc.close()
            say("[..] VXI-11 会话已关闭（本会话共发 %d 条查询，预算 %d）"
                % (m["queries"], SESSION_QUERY_BUDGET))

    if m["queries"] > SESSION_QUERY_BUDGET:                  
        raise ScopeError("内部错误：查询数 %d 超过预算 %d"
                         % (m["queries"], SESSION_QUERY_BUDGET))
    if m["queries_ok"] == 0:
        say("[FAIL] 本次没有拿到任何查询回包（VXI-11 连接/传输失败）")
        say("       ⇒ **不写结果**，保留上一次的有效文件；请先跑 --probe-safe 检查链路")
        return EXIT_ERR

    hz, period, vpp = m.get("measured_hz"), m.get("period_s"), m.get("vpp_v")
    state, dev = judge(hz, args.expect, tol)
    m["reason"] = build_reason(ch, m, state, dev, tol, args.expect)
    item = build_item(args, m, state, dev, tol)

    say("")
    say("=== 结果 ===")
    say("  仪器 : DS2102A @ %s（VXI-11）" % resource)
    say("  通道 : CH%d" % ch)
    say("  周期 T : %s   （原始 %s）" % (fmt_sec(period), m.get("raw_period") or "—"))
    say("  频率 f : %s   ← f = 1/T" % fmt_hz(hz))
    say("  幅度 Vpp: %s   （原始 %s）"
        % ("—" if vpp is None else "%.6g V" % vpp, m.get("raw_vpp") or "—"))
    say("  占空比 : %s   （原始 %s）"
        % ("—" if m.get("duty") is None else "%.3f%%" % (m["duty"] * 100.0),
           m.get("raw_duty") or "—"))
    if args.expect is None:
        say("  期望 : —（没给 --expect ⇒ 结果不判定；页面按判据库 28 项自动匹配）")
    else:
        say("  期望 : %s（人工指定，非判据库）" % fmt_hz(args.expect))
        say("  偏差 : %+.3f%%（容差 ±%g%%）" % (dev, tol))
    say("  判定 : %s" % {"pass": "pass ✔（正常）",
                         "fail": "fail ✘（异常，偏差超限）",
                         "no_reference": "no_reference（无参考，只读数）",
                         "no_signal": "no_signal（⚠ 无信号）"}[state])
    say("  查询 : %d 条（预算 %d = 测量 %d + 波形段 %d；PERiod?/VPP?/PDUTy?/Preamble?/DATA?/ERRor?）"
        % (m["queries"], SESSION_QUERY_BUDGET, QUERY_BUDGET, WAVE_QUERY_BUDGET))
    if m.get("sys_error") and not error_is_no_error(m["sys_error"]):
        say("  错误 : 错误队列 = %s" % m["sys_error"])
    if m.get("wave"):
        w = m["wave"]
        say("  波形 : 真实屏幕采样 %d 点（NORMal/BYTE）｜ dt=%.6g s ｜ 相对 Vpp=%.3f V"
            % (w["points"], w["sample_dt_s"], w["wave_vpp_v"]))
        say("         来源=%s（逐点绘制；不是重建/示意）" % w["wave_source"])
    else:
        say("  波形 : 未采到（%s）；页面不会假装有真实波形"
            % (m.get("wave_error") or "无有效读数"))

    ts = now_iso()
    payload = build_payload(args, m, item, state, dev, tol, resource, ts)
    payload, item = _fit_json_size(payload, item)

    if args.no_write:
        say("  写入 : 跳过（--no-write）")
        return _exit_for(state)

    target = os.path.abspath(args.result) if args.result else DEFAULT_RESULT
    say("  写入 : %s" % target)
    try:
        mod, where = load_collector(args.collector)
        out = write_result_via_collector(mod, payload, target)
        sig = str(out.get("sig") or "")

        sig_ok = False
        try:
            key = mod.read_key() if callable(getattr(mod, "read_key", None)) else ""
            if key and callable(getattr(mod, "sign", None)):
                sig_ok = hmac.compare_digest(
                    str(mod.sign(out.get("items"), out.get("ts"), key)), sig)
        except Exception:                                      
            sig_ok = False
        say("[OK] 已签名写入（scope_collect API：%s）" % where)
        say("     session=%s  sig=%s…  items=%d  ts=%s  sig自检=%s"
            % (out.get("collector_session", "?"), sig[:16],
               len(out.get("items") or []), out.get("ts"),
               "OK" if sig_ok else "未复算（不影响写入）"))
    except Exception as e:                                     
        why = "%s: %s" % (type(e).__name__, e)
        say("[WARN] 签名写入不可用：%s" % why)
        out = write_unsigned(payload, target, why)
        say("[WARN] 已写 UNSIGNED 标记：%s" % target)
        say("       页面会提示「数据来源未验证（缺少采集签名 sig / 采集会话 collector_session）」"
            "并拒绝显示数字；请修复 scope_collect 接口后重跑")
        say("  页面 : 该文件不会被当成实测显示（按失败处理，退出码 1）")
        return EXIT_ERR
    say("  页面 : 进【波形检测】看真实采样波形 + 判据库自动匹配")
    return _exit_for(state)

def do_list(args):
    """只读：3 条安全查询（*IDN? / 测量源 / 错误队列）；不写结果、不发 SET。"""
    resource = args.resource or _vxi_resource(args.ip)
    sc = None
    idn, src, err = "", "", ""
    try:
        sc = open_scope(args)
        say("")
        say("=== 仪器信息（VXI-11 只读）===")
        say("  资源 : %s" % resource)
        idn, _ = _safe_query(sc, "*IDN?")
        src, _ = _safe_query(sc, ":MEASure:SOURce?")
        err, _ = _safe_query(sc, ":SYSTem:ERRor:NEXT?")
    except ScopeError as e:
        say("[FAIL] %s" % e)
        return EXIT_ERR
    finally:
        if sc is not None:
            sc.close()
    say("  型号 : %s" % (idn_model(idn) or "—"))
    say("  测量源 : %s" % (src or "—"))
    say("  错误队列 : %s" % (err or "—"))
    say("  （只读：3 条查询；未发 SET；未写结果）")
    if idn and not idn_is_rigol(idn):
        say("[WARN] 厂商段不是 RIGOL：%r" % str(idn).split(",")[0])
        return EXIT_ERR
    return EXIT_OK if idn else EXIT_ERR

def do_probe_safe(args):
    """保守探活：**只发 3 条只读查询**，不发任何 SET、不启动测量、不写结果。

    这比旧版（发 11 条 SET）更保守；用于确认 VXI-11 链路/仪器 LAN 应用还活着。
    """
    resource = args.resource or _vxi_resource(args.ip)
    sc = None
    idn, src, err = "", "", ""
    try:
        sc = open_scope(args)
        say("")
        say("=== 保守探针（VXI-11）：3 条只读查询，0 条 SET ===")
        say("  资源 : %s" % resource)
        idn, ok_idn = _safe_query(sc, "*IDN?")
        src, ok_src = _safe_query(sc, ":MEASure:SOURce?")
        err, ok_err = _safe_query(sc, ":SYSTem:ERRor:NEXT?")
    except ScopeError as e:
        say("")
        say("=== 探针结论 ===")
        say("  结果 : 失败（VXI-11 连接/查询异常）")
        say("  原因 : %s" % e)
        say("  处置 : 检查网线/192.168.88.20 是否可达；不要反复重连、不要退回 5555")
        return EXIT_ERR
    finally:
        if sc is not None:
            sc.close()

    rigol = idn_is_rigol(idn)
    err_ok = error_is_no_error(err)
    say("")
    say("=== 探针结论 ===")
    say("  *IDN?      : %s" % (idn or "（无回包）"))
    say("  型号       : %s" % (idn_model(idn) or "—"))
    say("  测量源     : %s" % (src or "—"))
    say("  错误队列   : %s" % (err or "—"))
    say("  查询数     : %d 条（预算 %d）" % (sc.n_queries if sc else 0, QUERY_BUDGET))
    say("  SET 数     : 0（本动作不发任何 SET，不改仪器状态）")
    if not ok_idn or not rigol:
        say("  结论 : FAIL（VXI-11 有/无回包，但 *IDN? 缺失或厂商不是 RIGOL）")
        return EXIT_ERR
    if not err_ok:
        say("  结论 : FAIL（活着、有回包，但错误队列非空：%s）" % err)
        return EXIT_ERR
    say("  结论 : OK（VXI-11 链路活、*IDN? 正常、错误队列无错误）")
    say("  下一步 : 可跑 --measure --expect 1k（或按实际信号换期望值）")
    return EXIT_OK

def _exit_for(state):
    if state in ("pass", "no_reference"):
        return EXIT_OK
    if state == "fail":
        return EXIT_FAIL
    return EXIT_NOSIGNAL

def build_parser():
    ap = argparse.ArgumentParser(
        description="一次测量（RIGOL DS2102A，VXI-11）：f / T / Vpp / duty + 真实屏幕波形 + 签名写入",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("退出码：0 通过/只记录，1 连接或写入失败，3 偏差超限，4 无信号\n"
                "波形：屏幕 NORMal + BYTE，≤2000 点，DATA? 仅 1 次；绝不 RAW/深存储。\n"
                "传输：TCPIP0::<ip>::INSTR（pyvisa-py）；5555 裸 socket 已移除（会卡死仪器）。"))
    ap.add_argument("--ip", "--host", dest="ip", default=DEFAULT_IP,
                    help="示波器 LAN 地址（默认 %s；VXI-11 资源 = TCPIP0::<ip>::INSTR）" % DEFAULT_IP)
    ap.add_argument("--resource", default="",
                    help="直接指定 VISA 资源串（默认 TCPIP0::<ip>::INSTR；一般不用）")
    ap.add_argument("--ch", type=int, default=1, choices=(1, 2, 3, 4), help="通道（默认 1）")
    ap.add_argument("--expect", type=_expect_hz, default=None,
                    help="期望频率，如 1k / 30M / 1e3 / 10MHz（不填=no_reference 不判定）")
    ap.add_argument("--tol", type=float, default=DEFAULT_TOL, help="偏差容差 %%（默认 5）")
    ap.add_argument("--item", default="", help="参数表里的名称（默认 CHn 实测频率）")
    ap.add_argument("--field", default="",
                    help="对应 scope_items_lan.json 的 field（如 (scope)z11_30m_if）")
    ap.add_argument("--shape", default="sine", choices=("sine", "square"),
                    help="**仅在无真实采样时**页面兜底示意用的形状（默认 sine）")
    ap.add_argument("--measure", action="store_true",
                    help="★ 一次测量（默认动作）：SET + 1.5s + 测量 3 条 + 真实波形 1 次，写签名结果")
    ap.add_argument("--wave", action="store_true",
                    help="同 --measure（真实波形默认已包含；保留此开关便于显式调用）")
    ap.add_argument("--no-wave", action="store_true",
                    help="调试用：跳过波形段（页面会标注无真实采样，不冒充）")
    ap.add_argument("--list", action="store_true",
                    help="只读：*IDN? / 测量源 / 错误队列 3 条查询（不写结果）")
    ap.add_argument("--enable", action="store_true",
                    help="跑完整配方 + 查询，但不写结果（等价 --measure --no-write）")
    ap.add_argument("--probe-safe", action="store_true",
                    help="保守探活：只发 3 条只读查询，0 条 SET（不写结果）")
    ap.add_argument("--no-enable", action="store_true",
                    help="跳过 11 条 SET，直接查询（调试用；假设面板已配好）")
    ap.add_argument("--result", default="", help="结果路径（默认 %s）" % DEFAULT_RESULT)
    ap.add_argument("--collector", default="",
                    help="scope_collect.py 路径/包根目录（PC 联调用；板端自动找）")
    ap.add_argument("--no-write", action="store_true", help="只测不写结果")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                    help="单条查询超时秒（默认 8）")
    ap.add_argument("--gap", type=float, default=DEFAULT_GAP,
                    help="命令间隔秒（默认 0.05，不得小于 %.2f）" % MIN_GAP)
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印解析后的参数并退出（不导入 pyvisa、不连仪器）")
    ap.add_argument("--legacy-socket", action="store_true",
                    help="✗ 已移除的 5555 裸 socket 路径（默认禁用；传了会明确报错——该路径会卡死仪器）")
    return ap

def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.gap < MIN_GAP:
        ap.error("--gap 不能小于 %.2fs（VXI-11 最小间隔）" % MIN_GAP)
    if args.tol <= 0:
        ap.error("--tol 必须 > 0")
    if args.timeout <= 0:
        ap.error("--timeout 必须 > 0")

    if args.legacy_socket:
        say("[FAIL] 5555 裸 socket 路径已移除：该路径会卡死 DS2102A 的 LAN 应用"
            "（之后连 *IDN? 都不回）。请用默认的 VXI-11：")
        say("       python3 scope_quick.py --probe-safe")
        return EXIT_ERR

    resource = args.resource or _vxi_resource(args.ip)
    if args.dry_run:
        say("=== dry-run（不连仪器）===")
        say("  ip       : %s" % args.ip)
        say("  resource : %s" % resource)
        say("  channel  : CH%d" % args.ch)
        say("  expect   : %s" % ("—" if args.expect is None else "%g Hz" % args.expect))
        say("  tol      : %g%%" % args.tol)
        say("  result   : %s" % (args.result or DEFAULT_RESULT))
        say("  query    : 测量 %d + 波形段 %d = <= %d 条/会话（DATA? 仅 1 次）"
            % (QUERY_BUDGET, WAVE_QUERY_BUDGET, SESSION_QUERY_BUDGET))
        say("  wave     : %s（NORMal/BYTE，≤%d 点，绝无 RAW）"
            % ("OFF (--no-wave)" if args.no_wave else "ON", WAVE_MAX_POINTS))
        say("  set      : %d 条（配方）" % len(measure_setup_steps(args.ch)))
        return EXIT_OK

    say("=== scope_quick.py · VXI-11 一次测量（f / T / Vpp / duty + 真实波形，"
        "判定 pass·fail·no_reference·no_signal）===")
    say("时间 %s ｜ 资源 %s ｜ 通道 CH%d" % (now_iso(), resource, args.ch))

    try:
        if args.list:
            return do_list(args)
        if args.probe_safe:
            return do_probe_safe(args)
        if args.enable:
            args.no_write = True
            say("[..] --enable：跑完整配方但**不写结果**")
            return do_measure(args)

        return do_measure(args)
    except ScopeError as e:
        say("")
        say("[FAIL] %s" % e)
        return EXIT_ERR
    except KeyboardInterrupt:
        say("\n[中断] 用户取消")
        return EXIT_ERR
    except Exception as e:                                     
        say("")
        say("[FAIL] 未预期异常：%s: %s" % (type(e).__name__, e))
        return EXIT_ERR

if __name__ == "__main__":
    sys.exit(main())
