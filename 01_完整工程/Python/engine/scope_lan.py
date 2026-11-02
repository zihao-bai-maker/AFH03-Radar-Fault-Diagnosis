#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scope_lan.py — 示波器关键参数采集（RIGOL DS2102A，SCPI over TCP :5555）

设计目标（用户新指示）：
  * 只取"关键参数"（:MEASure:ITEM? 频率/幅度），**绝不取整段波形**；
  * 绝不发深存储 / RAW（:WAVeform:DATA?）——该命令曾把 DS2102A 网口应用层挂死；
  * 单条 TCP 长连接、命令间 ≥300 ms、不并发、失败最多重建 2 次（间隔 2 s）；
  * 单条命令超时 3 s；超时或空返回 ⇒ 立刻断链并判定"仪器无响应"，不再继续发。

本文件同时提供：
  - `ScpiSession`  协议安全层（唯一入口，任何命令先过白名单校验）
  - `LanTransport`  TCP/SCPI 传输
  - `judge_*`      判据 → normal / abnormal / undetermined
  - `build_evidence` 统一多模态证据 JSON（与融合层对齐）
  - CLI：`python scope_lan.py --io lan --host 192.168.1.20`

USBTMC 走 `scope_usbtmc.py`（复用本文件的 `ScpiSession`）。

!! 本模块对仪器的写操作默认为 0 !!
  默认只发查询（以 '?' 结尾）。唯一可选的写命令是 `--enable-measure`
  显式开启后才发 `:MEASure:ITEM FREQuency`（让 DS2000A 打开该测量项）。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import socket
import sys
import time

MIN_CMD_GAP_S = 0.30        
CMD_TIMEOUT_S = 3.0         
CONNECT_TIMEOUT_S = 3.0     
RETRY_LIMIT = 2             
RETRY_BACKOFF_S = 2.0       
MAX_LINE_BYTES = 8192       
MAX_LOG_ENTRIES = 200       
NOISE_VPP_V = 0.05          
MIN_CONFIDENCE = 0.60       

DEFAULT_HOST = "192.168.1.20"
DEFAULT_PORT = 5555

FORBIDDEN_TOKENS = (
    "WAV",      
    "DATA?",
    ":DATA",
    "STOR",     
    "MASS",     
    "DISK",
    "RECAL",
    "SAVE",
    "*RST",
    "PRES",     
    ":RUN", ":STOP", ":SING", "AUTO",   
    "FUNC",     
    "\n", "\r",
)

ALLOWED_QUERY_PREFIXES = (
    "*IDN?", "*OPC?", "*ESR?", "*STB?", "*CLS",
    ":MEAS", ":MEASURE",
    ":CHAN", ":CHANNEL",
    ":TIM", ":TIMEBASE",
    ":TRIG", ":TRIGGER",
    ":SYST", ":SYSTEM",
)

PARAM_CMDS_LONG = {
    "FREQuency": ":MEASure:ITEM? FREQuency",
    "VPP":       ":MEASure:ITEM? VPP",
    "PERiod":    ":MEASure:ITEM? PERiod",
    "VAVerage":  ":MEASure:ITEM? VAVerage",
    "VRMS":      ":MEASure:ITEM? VRMS",
}
PARAM_CMDS_SHORT = {
    "FREQuency": ":MEAS:ITEM? FREQ",
    "VPP":       ":MEAS:ITEM? VPP",
    "PERiod":    ":MEAS:ITEM? PER",
    "VAVerage":  ":MEAS:ITEM? VAV",
    "VRMS":      ":MEAS:ITEM? VRMS",
}

CONTEXT_CMDS = (
    (":CHANnel1:SCALe?", "ch1_scale_v_per_div"),
    (":TIMebase:SCALe?", "timebase_s_per_div"),
    (":TRIGger:STATus?", "trigger_status"),
    (":MEASure:SOURce?", "measure_source"),
)

class ScopeError(Exception):
    """本模块所有异常的基类。"""

class InstrumentUnresponsive(ScopeError):
    """超时 / 空返回 / 连接被对端关闭 ⇒ 判定仪器无响应（不再继续发命令）。"""

class ProtocolViolation(ScopeError):
    """响应超长、二进制污染等协议异常 ⇒ 立刻断链。"""

class ForbiddenCommand(ScopeError):
    """命令被本地安全策略拒绝（未发送）。"""

class ProbeFailed(ScopeError):
    """探活失败（连不上 / *IDN? 不通）⇒ 直接报错退出，不尝试写。

    retryable=False 表示"重试也没用"（设备不存在、无权限、平台不支持），
    避免对着不存在的 /dev/usbtmc0 白等 4 秒。
    """

    def __init__(self, msg, retryable=True):
        super().__init__(msg)
        self.retryable = bool(retryable)

def assert_safe_command(cmd: str) -> str:
    """校验一条待发命令；不安全则抛 ForbiddenCommand（此时尚未发送任何字节）。"""
    if not isinstance(cmd, str) or not cmd.strip():
        raise ForbiddenCommand("空命令")
    if len(cmd) > 120:
        raise ForbiddenCommand("命令过长(%d)：%r" % (len(cmd), cmd[:40]))
    if "\n" in cmd or "\r" in cmd:
        raise ForbiddenCommand("命令含换行（注入风险）：%r" % cmd)
    try:
        cmd.encode("ascii")
    except UnicodeEncodeError:
        raise ForbiddenCommand("命令含非 ASCII 字符：%r" % cmd)

    flat = cmd.replace(" ", "").replace("\t", "").upper()
    for tok in FORBIDDEN_TOKENS:
        if tok.strip() and tok in flat:
            raise ForbiddenCommand(
                "命中禁用命令 (%s) ⇒ 该命令曾导致 DS2102A 网口挂死，已拒绝：%r" % (tok.strip(), cmd))

    
    if "?" not in cmd:
        raise ForbiddenCommand("只允许查询命令（须含 '?'）：%r" % cmd)
    if cmd.count("?") > 1:
        raise ForbiddenCommand("命令含多个 '?'（疑似拼接）：%r" % cmd)
    if ";" in cmd:
        raise ForbiddenCommand("命令含 ';'（多命令拼接风险）：%r" % cmd)

    if not any(flat.startswith(p.replace(" ", "").upper()) for p in ALLOWED_QUERY_PREFIXES):
        raise ForbiddenCommand("命令不在只读白名单前缀内：%r" % cmd)
    return cmd

_NUM_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?")

def parse_numeric(text):
    """把示波器响应解析成 float。

    返回 (value, reason)。value 为 None 时 reason 说明原因：
      'empty' | 'star' | 'sentinel' | 'unparsable'
    RIGOL 约定：
      '*****'  ⇒ 测量项未开启/无有效读数
      '9.9E+37'⇒ 溢出哨兵值
    """
    if text is None:
        return None, "empty"
    s = str(text).strip().strip('"').strip()
    if not s:
        return None, "empty"
    if "*" in s:
        return None, "star"
    m = _NUM_RE.match(s)
    if not m:
        return None, "unparsable"
    try:
        v = float(m.group(0))
    except ValueError:
        return None, "unparsable"
    if abs(v) >= 9.0e36:
        return None, "sentinel"
    return v, "ok"

def parse_idn(text: str) -> dict:
    """RIGOL TECHNOLOGIES,DS2102A,DS2A184800001,00.03.05 → dict"""
    raw = (text or "").strip()
    parts = [p.strip() for p in raw.split(",")]
    out = {"raw": raw, "vendor": None, "model": None, "serial": None, "firmware": None}
    if len(parts) >= 1:
        out["vendor"] = parts[0] or None
    if len(parts) >= 2:
        out["model"] = parts[1] or None
    if len(parts) >= 3:
        out["serial"] = parts[2] or None
    if len(parts) >= 4:
        out["firmware"] = parts[3] or None
    out["is_rigol"] = bool(out["vendor"] and "RIGOL" in out["vendor"].upper())
    out["is_ds2102a"] = bool(out["model"] and "DS2102A" in out["model"].upper())
    return out

class LanTransport:
    """SCPI over raw TCP（DS2102A 的 5555 端口）。"""

    kind = "lan"

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT,
                 timeout=CMD_TIMEOUT_S, connect_timeout=CONNECT_TIMEOUT_S):
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self.connect_timeout = float(connect_timeout)
        self._sock = None
        self._buf = b""
        self.peer = "%s:%d" % (self.host, self.port)

    def open(self):
        self.close()
        try:
            s = socket.create_connection((self.host, self.port), timeout=self.connect_timeout)
        except OSError as e:
            raise ProbeFailed("TCP 连接 %s 失败：%s" % (self.peer, e))
        try:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        s.settimeout(self.timeout)
        self._sock = s
        self._buf = b""
        return self

    def close(self):
        s, self._sock = self._sock, None
        self._buf = b""
        if s is not None:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass

    @property
    def is_open(self):
        return self._sock is not None

    def send(self, text: str):
        if self._sock is None:
            raise InstrumentUnresponsive("socket 未打开")
        try:
            self._sock.sendall(text.encode("ascii") + b"\n")
        except OSError as e:
            self.close()
            raise InstrumentUnresponsive("发送失败（对端可能已挂死/断开）：%s" % e)

    def read_line(self, timeout=None) -> str:
        """读一行（以 \\n 结尾）；超时/超长/对端关闭都抛异常。"""
        if self._sock is None:
            raise InstrumentUnresponsive("socket 未打开")
        deadline = time.monotonic() + (self.timeout if timeout is None else float(timeout))
        while b"\n" not in self._buf:
            remain = deadline - time.monotonic()
            if remain <= 0:
                self.close()
                raise InstrumentUnresponsive("读超时 %.1fs（无 \\n 结束）" % self.timeout)
            self._sock.settimeout(remain)
            try:
                chunk = self._sock.recv(1024)
            except socket.timeout:
                self.close()
                raise InstrumentUnresponsive("读超时 %.1fs" % self.timeout)
            except OSError as e:
                self.close()
                raise InstrumentUnresponsive("接收失败：%s" % e)
            if not chunk:
                self.close()
                raise InstrumentUnresponsive("对端关闭连接（仪器可能已挂死）")
            self._buf += chunk
            if len(self._buf) > MAX_LINE_BYTES:
                self.close()
                raise ProtocolViolation(
                    "响应超过 %d 字节，疑似误发深存储命令，已强制断链" % MAX_LINE_BYTES)
        line, _, self._buf = self._buf.partition(b"\n")
        return line.decode("ascii", "replace").strip()

class ScpiSession:
    """单会话、串行、限速的 SCPI 客户端。

    规则（全部可审计）：
      1. 一次只开一条连接；`open_and_ping()` 之后才能查询；
      2. 任意两条命令之间强制 ≥ `min_gap`（默认 300 ms）；
      3. 每条命令总超时 `timeout`（默认 3 s）；
      4. 超时 / 空返回 / 断链 ⇒ `_dead=True`，会话作废，调用方必须终止（不重试该命令）；
      5. 每会话最多重建 `RETRY_LIMIT` 次；只重建整会话，不逐条重试。
    """

    def __init__(self, transport, min_gap=MIN_CMD_GAP_S, timeout=CMD_TIMEOUT_S,
                 retry_limit=RETRY_LIMIT, retry_backoff=RETRY_BACKOFF_S,
                 log_limit=MAX_LOG_ENTRIES, logger=None):
        self.tr = transport
        self.min_gap = max(float(min_gap), MIN_CMD_GAP_S)   
        self.timeout = float(timeout)

        try:
            self.tr.timeout = self.timeout
        except Exception:
            pass
        self.retry_limit = int(retry_limit)
        self.retry_backoff = float(retry_backoff)
        self.log_limit = int(log_limit)
        self.logger = logger                    
        self.log = []                           
        self.idn = None
        self.idn_info = None
        self.dialect = "long"
        self._dead = False
        self._last_t = 0.0
        self.n_cmds = 0
        self.reattempts = 0

    def _note(self, level, **kw):
        rec = {"ts": _dt.datetime.now().strftime("%H:%M:%S.%f")[:-3], "lvl": level}
        rec.update(kw)
        self.log.append(rec)
        if len(self.log) > self.log_limit:
            del self.log[0:len(self.log) - self.log_limit]
        if self.logger:
            self.logger(level, rec)

    @property
    def is_dead(self):
        return self._dead

    def open_and_ping(self):
        """建链 + `*IDN?` 探活；失败可重建（最多 RETRY_LIMIT 次，间隔 retry_backoff）。"""
        last = None
        attempts = 0
        for attempt in range(self.retry_limit + 1):
            attempts = attempt + 1
            if attempt:
                self.reattempts += 1
                self._note("retry", attempt=attempt, backoff_s=self.retry_backoff)
                time.sleep(self.retry_backoff)
            try:
                self.tr.open()
                self._dead = False
                self._last_t = 0.0
                resp = self.query("*IDN?", allow_empty=False)
                info = parse_idn(resp)
                if not resp.strip():
                    raise InstrumentUnresponsive("*IDN? 空返回")
                self.idn = resp
                self.idn_info = info
                self._note("idn", model=info.get("model"), fw=info.get("firmware"))
                return info
            except (ProbeFailed, InstrumentUnresponsive, ProtocolViolation) as e:
                last = e
                self._note("probe_fail", attempt=attempt, err=str(e)[:120])
                try:
                    self.tr.close()
                except Exception:
                    pass
                if isinstance(e, ProbeFailed) and not e.retryable:
                    break
        raise ProbeFailed("探活失败（%d 次尝试）：%s" % (attempts, last))

    def close(self):
        try:
            self.tr.close()
        except Exception:
            pass

    def query(self, cmd: str, allow_empty=True) -> str:
        assert_safe_command(cmd)
        if self._dead:
            raise InstrumentUnresponsive("会话已作废，拒绝继续发送")
        if not self.tr.is_open:
            raise InstrumentUnresponsive("连接未打开")

        gap = time.monotonic() - self._last_t
        if gap < self.min_gap:
            time.sleep(self.min_gap - gap)

        t0 = time.monotonic()
        self.n_cmds += 1
        try:
            self.tr.send(cmd)
            resp = self.tr.read_line(self.timeout)
        except (InstrumentUnresponsive, ProtocolViolation) as e:
            self._dead = True
            dt = (time.monotonic() - t0) * 1000.0
            self._note("error", cmd=cmd[:60], ms=round(dt, 1), err=str(e)[:100])
            raise
        finally:
            self._last_t = time.monotonic()

        dt = (time.monotonic() - t0) * 1000.0
        if resp == "" and not allow_empty:
            self._dead = True
            self._note("error", cmd=cmd[:60], ms=round(dt, 1), err="empty response")
            raise InstrumentUnresponsive("空返回：%s" % cmd)

        self._note("ok", cmd=cmd[:60], ms=round(dt, 1), n=len(resp),
                   val=(resp[:40] if len(resp) <= 40 else resp[:40] + "…"))
        return resp

    def query_num(self, cmd: str):
        """返回 (value, reason, raw)。空返回按协议异常处理（会话作废）。"""
        raw = self.query(cmd, allow_empty=False)
        value, reason = parse_numeric(raw)
        return value, reason, raw

    def param_cmd(self, name: str) -> str:
        table = PARAM_CMDS_SHORT if self.dialect == "short" else PARAM_CMDS_LONG
        return table[name]

def _conf(ok, base):
    return round(base if ok else max(0.0, base - 0.15), 2)

def judge_freq(freq_hz, expect_hz, tol_pct, vpp=None):
    """频率判定。返回 (value, confidence, reason)。"""
    if expect_hz is None:
        return "undetermined", 0.30, "no_expect_freq"
    if freq_hz is None:

        if vpp is not None and vpp < NOISE_VPP_V:
            return "abnormal", 0.80, "no_signal"
        return "undetermined", 0.30, "freq_unreadable"
    dev = abs(freq_hz - expect_hz) / float(expect_hz) * 100.0
    if dev <= tol_pct:
        if vpp is not None and vpp < NOISE_VPP_V:
            return "undetermined", 0.40, "freq_ok_but_no_amplitude"
        base = 0.95 if vpp is not None else 0.85
        return "normal", base, "freq_within_tol(%.2f%%)" % dev

    return "abnormal", 0.90, "freq_out_of_tol(%.2f%%)" % dev

def judge_presence(vpp, freq_hz=None):
    """无频率判据的项：只能判"有没有信号"。有信号 ≠ 正常（形状无法量化）。"""
    if vpp is None:
        return "undetermined", 0.30, "vpp_unreadable"
    if vpp < NOISE_VPP_V:
        return "abnormal", 0.85, "no_signal(vpp=%.3fV)" % vpp
    return "undetermined", 0.50, "signal_present_but_unquantified(vpp=%.3fV)" % vpp

def decide(item, measured, raw_reasons):
    """统一裁决：返回 (value, confidence, reason)。undetermined 优先。"""
    freq = measured.get("freq_hz")
    vpp = measured.get("vpp")
    if item.get("judge_mode") == "freq":
        value, conf, reason = judge_freq(freq, item.get("expect_freq_hz"),
                                         item.get("tol_pct") or 3.0, vpp)
    else:
        value, conf, reason = judge_presence(vpp, freq)

    if value != "undetermined" and raw_reasons.get("vpp") in ("star", "unparsable") \
            and raw_reasons.get("freq") in ("star", "unparsable"):
        return "undetermined", 0.30, "all_params_invalid"
    if conf < MIN_CONFIDENCE and value != "abnormal":
        return "undetermined", conf, reason + "|low_conf"
    return value, conf, reason

def build_evidence(item, measured, value, confidence, io_kind, extra=None):
    """输出统一多模态证据 JSON（字段与融合层约定一致）。"""
    ev = {
        "part": item["part"],
        "route": item["route"],
        "modality": "scope",
        "field": item["field"],
        "value": value,
        "measured": {
            "freq_hz": measured.get("freq_hz"),
            "vpp": measured.get("vpp"),
            "period_s": measured.get("period_s"),
        },
        "expect_freq_hz": item.get("expect_freq_hz"),
        "tol_pct": item.get("tol_pct"),
        "confidence": round(float(confidence), 2),
        "io": io_kind,
    }
    if extra:
        ev.update(extra)
    return ev

class ScopeReader:
    """按 scope_items_lan.json 的条目采集关键参数。"""

    def __init__(self, session: ScpiSession, context=True):
        self.s = session
        self.context = bool(context)

    def read_context(self):
        ctx, missing = {}, []
        for cmd, key in CONTEXT_CMDS:
            try:
                raw = self.s.query(cmd, allow_empty=True)
            except (InstrumentUnresponsive, ProtocolViolation):
                raise
            if raw == "":
                ctx[key] = None
                missing.append(key)
                continue
            num, reason = parse_numeric(raw)
            ctx[key] = num if reason == "ok" else raw
        return ctx, missing

    def read_item(self, item):
        """采一个条目：上下文 + FREQ + VPP（+ 可选 PERiod）。"""
        ctx, ctx_missing = self.read_context() if self.context else ({}, [])

        measured, reasons, raw = {}, {}, {}
        try:
            val, reason, raw["freq"] = self.s.query_num(self.s.param_cmd("FREQuency"))
            measured["freq_hz"], reasons["freq"] = val, reason
        except InstrumentUnresponsive:
            raise

        try:
            val, reason, raw["vpp"] = self.s.query_num(self.s.param_cmd("VPP"))
            measured["vpp"], reasons["vpp"] = val, reason
        except InstrumentUnresponsive:
            raise

        if "PERiod" in (item.get("params") or []):
            val, reason, raw["period"] = self.s.query_num(self.s.param_cmd("PERiod"))
            measured["period_s"], reasons["period"] = val, reason
        elif measured.get("freq_hz"):
            measured["period_s"] = 1.0 / measured["freq_hz"]
            reasons["period"] = "derived"

        value, conf, reason = decide(item, measured, reasons)
        ev = build_evidence(item, measured, value, conf, self.s.tr.kind)
        diag = {
            "idx": item.get("idx"), "flow_no": item.get("flow_no"),
            "check_item": item.get("check_item"), "signal": item.get("signal"),
            "judge_mode": item.get("judge_mode"), "reason": reason,
            "raw": raw, "reasons": reasons, "context": ctx, "context_missing": ctx_missing,
        }
        return ev, diag

DEFAULT_ITEMS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "scope_items_lan.json")

def load_items(path=DEFAULT_ITEMS):
    doc = json.load(open(path, encoding="utf-8"))
    items = doc.get("items") or []
    if len(items) != 28:
        raise ScopeError("条目数异常：%d（应为 28）" % len(items))
    return doc, items

def select_items(items, only=None, parts=None, routes=None):
    out = items
    if only:
        want = {int(x) for x in only}
        out = [i for i in out if int(i["idx"]) in want]
    if parts:
        out = [i for i in out if i["part"] in set(parts)]
    if routes:
        out = [i for i in out if i["route"] in set(routes)]
    return out

def _make_transport(args):
    if args.io == "usbtmc":
        from scope_usbtmc import UsbTmcTransport          
        return UsbTmcTransport(path=args.usbtmc, timeout=args.timeout)
    return LanTransport(host=args.host, port=args.port, timeout=args.timeout,
                        connect_timeout=args.connect_timeout)

def icmp_ping(host, timeout_ms=1000):
    """辅助诊断（可选）：ICMP 只证明 IP 层活着，不证明 5555 应用层活着。"""
    import subprocess
    if os.name == "nt":
        cmd = ["ping", "-n", "1", "-w", str(timeout_ms), host]
    else:
        cmd = ["ping", "-c", "1", "-W", str(max(1, timeout_ms // 1000)), host]
    try:
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=timeout_ms / 1000.0 + 2)
        return r.returncode == 0
    except Exception:
        return False

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="示波器关键参数采集（只取 MEASURE 参数，不取波形）")
    ap.add_argument("--io", choices=("lan", "usbtmc"), default="lan")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--usbtmc", default=None, help="如 /dev/usbtmc0（默认自动探测）")
    ap.add_argument("--items", default=DEFAULT_ITEMS, help="条目表 JSON 路径")
    ap.add_argument("--only", nargs="*", type=int, help="只跑指定 idx（1..28）")
    ap.add_argument("--part", nargs="*", choices=("z11", "z14"), help="只跑指定部件")
    ap.add_argument("--route", nargs="*", choices=("I", "II"), help="只跑指定路")
    ap.add_argument("--dialect", choices=("long", "short"), default="long",
                    help="SCPI 写法：long=:MEASure:ITEM? FREQuency，short=:MEAS:ITEM? FREQ")
    ap.add_argument("--no-context", action="store_true", help="不读上下文（省 4 条命令/项）")
    ap.add_argument("--enable-measure", action="store_true",
                    help="[写操作] 先发 :MEASure:ITEM FREQuency 打开测量项（默认不发）")
    ap.add_argument("--raw-query", default=None, help="调试：单发一条只读查询")
    ap.add_argument("--icmp", action="store_true", help="诊断：先做一次 ICMP ping")
    ap.add_argument("--timeout", type=float, default=CMD_TIMEOUT_S)
    ap.add_argument("--connect-timeout", type=float, default=CONNECT_TIMEOUT_S)
    ap.add_argument("--gap", type=float, default=MIN_CMD_GAP_S, help="命令间隔（≥0.3s）")
    ap.add_argument("--retry", type=int, default=RETRY_LIMIT, help="整会话重建次数上限")
    ap.add_argument("--out", default=None, help="证据 JSON 输出路径")
    ap.add_argument("--report", default=None, help="运行报告（含耗时日志）输出路径")
    ap.add_argument("--dry-run", action="store_true", help="不碰仪器，只生成 undetermined 证据")
    ap.add_argument("--json-lines", action="store_true", help="每条证据单行输出到 stdout")
    args = ap.parse_args(argv)

    doc, items = load_items(args.items)
    todo = select_items(items, args.only, args.part, args.route)
    if not todo:
        print("没有匹配的条目", file=sys.stderr)
        return 2

    if args.dry_run:
        out = [build_evidence(i, {}, "undetermined", 0.0, args.io) for i in todo]
        _emit(out, args, doc, idn=None, aborted=False, note="dry-run：未连接仪器")
        return 0

    if args.icmp:
        ok = icmp_ping(args.host)
        print("[icmp] %s %s" % (args.host, "可达" if ok else "不可达(仅参考)"), file=sys.stderr)

    transport = _make_transport(args)
    session = ScpiSession(transport, min_gap=args.gap, timeout=args.timeout,
                          retry_limit=args.retry,
                          logger=lambda lv, r: print("[%s] %s" % (lv, json.dumps(r, ensure_ascii=False)),
                                                     file=sys.stderr))
    session.dialect = args.dialect

    evidence, diags, aborted, err = [], [], False, None
    t_start = time.monotonic()
    try:
        info = session.open_and_ping()
        print("[idn] %s" % (info["raw"] or "(空)"), file=sys.stderr)

        if args.enable_measure:

            session.tr.send(":MEASure:ITEM FREQuency")
            print("[write] 已发送 :MEASure:ITEM FREQuency（显式 --enable-measure）", file=sys.stderr)
            time.sleep(session.min_gap)

        if args.raw_query:
            assert_safe_command(args.raw_query)
            print("[raw] %s → %r" % (args.raw_query, session.query(args.raw_query)), file=sys.stderr)
            return 0

        reader = ScopeReader(session, context=not args.no_context)
        for item in todo:
            ev, diag = reader.read_item(item)
            evidence.append(ev)
            diags.append(diag)
            if args.json_lines:
                print(json.dumps(ev, ensure_ascii=False), flush=True)
            print("[%02d] %-22s %-10s %s" % (item["idx"], item["signal"][:22],
                                             ev["value"], diag["reason"]), file=sys.stderr)
    except (ProbeFailed, InstrumentUnresponsive, ProtocolViolation, ForbiddenCommand) as e:
        aborted = True
        err = "%s: %s" % (type(e).__name__, e)
        print("[abort] %s" % err, file=sys.stderr)

        done = {d["idx"] for d in diags}
        for item in todo:
            if item["idx"] in done:
                continue
            evidence.append(build_evidence(item, {}, "undetermined", 0.0, args.io))
            diags.append({"idx": item["idx"], "flow_no": item["flow_no"],
                          "check_item": item["check_item"], "signal": item["signal"],
                          "judge_mode": item["judge_mode"],
                          "reason": "aborted:%s" % type(e).__name__, "raw": {},
                          "reasons": {}, "context": {}, "context_missing": []})
    finally:
        session.close()

    elapsed = round(time.monotonic() - t_start, 2)
    _emit(evidence, args, doc, idn=(session.idn_info or {}), aborted=aborted,
          note=err, diags=diags, elapsed=elapsed, n_cmds=session.n_cmds,
          reattempts=session.reattempts, log=session.log)
    return 1 if aborted else 0

def _emit(evidence, args, doc, idn, aborted, note, diags=None, elapsed=None,
          n_cmds=None, reattempts=None, log=None):
    env = {
        "schema": "scope_evidence/v1",
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "tool": "scope_lan.py",
        "io": args.io,
        "dialect": args.dialect,
        "idn": idn,
        "counts": {
            "requested": len(evidence),
            "normal": sum(1 for e in evidence if e["value"] == "normal"),
            "abnormal": sum(1 for e in evidence if e["value"] == "abnormal"),
            "undetermined": sum(1 for e in evidence if e["value"] == "undetermined"),
        },
        "aborted": bool(aborted),
        "note": note,
        "elapsed_s": elapsed,
        "commands_sent": n_cmds,
        "session_reattempts": reattempts,
        "evidence": evidence,
    }
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(env, ensure_ascii=False, indent=2) + "\n")
        print("[out] %s（%d 条证据）" % (args.out, len(evidence)), file=sys.stderr)
    else:
        print(json.dumps(env, ensure_ascii=False, indent=2))

    if args.report:
        rep = {
            "schema": "scope_report/v1",
            "generated_at": env["generated_at"],
            "io": args.io, "host": getattr(args, "host", None), "port": getattr(args, "port", None),
            "idn": idn, "aborted": bool(aborted), "note": note,
            "elapsed_s": elapsed, "commands_sent": n_cmds,
            "session_reattempts": reattempts,
            "items_source": os.path.basename(args.items),
            "items_sha256": doc.get("source_files", [{}])[0].get("sha256"),
            "diag": diags or [],
            "command_log": log or [],
        }
        with open(args.report, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rep, ensure_ascii=False, indent=2) + "\n")
        print("[report] %s" % args.report, file=sys.stderr)

if __name__ == "__main__":
    sys.exit(main())
