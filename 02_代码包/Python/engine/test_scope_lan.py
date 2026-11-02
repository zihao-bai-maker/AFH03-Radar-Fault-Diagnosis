#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_scope_lan.py — 离线单测：假 SCPI 服务器 + 真实协议格式回放

不碰真仪器。覆盖：
  * *IDN? / 频率 / Vpp 响应解析（含 ***** / 9.9E+37 / 科学计数 / 带单位）
  * 判据裁决（normal / abnormal / undetermined、容差边界、无信号、只报有信号）
  * 防挂死机制：单条超时 3 s、空返回、超长响应、对端断开、会话作废后不再发命令
  * 节奏：命令间 ≥300 ms（服务器侧打时间戳核对）
  * 重试策略：整会话最多重建 2 次、间隔 2 s（常量与行为都测）
  * 禁用命令本地拦截（:WAV:DATA? 一个字节都不发）
  * USBTMC 分帧（\\n 结尾）+ 无设备时的失败模式
  * scope_items_lan.json 与判据库 CSV 逐条一致性（28 项）

运行：
    python test_scope_lan.py            # 跑全部，打印通过率
    python test_scope_lan.py -v         # 额外打印每条用例
"""

from __future__ import annotations

import csv
import json
import os
import socket
import sys
import tempfile
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import scope_lan as S            
import scope_usbtmc as U         

CSV_PATH = os.path.join(HERE, "..", "判据库_SOP.csv")
ITEMS_PATH = os.path.join(HERE, "scope_items_lan.json")

IDN = "RIGOL TECHNOLOGIES,DS2102A,DS2A184800001,00.03.05"

DEFAULTS = {
    "*IDN?": IDN,
    ":CHANnel1:SCALe?": "5.000000E-01",
    ":TIMebase:SCALe?": "1.000000E-07",
    ":TRIGger:STATus?": "TD",
    ":MEASure:SOURce?": "CHAN1",
    ":MEASure:ITEM? FREQuency": "1.000000E+07",
    ":MEASure:ITEM? VPP": "1.200000E+00",
    ":MEASure:ITEM? PERiod": "1.000000E-07",
    ":MEAS:ITEM? FREQ": "1.000000E+07",
    ":MEAS:ITEM? VPP": "1.200000E+00",
}

class FakeScope:
    """本地 TCP 假示波器：按 RIGOL 格式回放，可注入挂起/空/超长/断链。"""

    def __init__(self, resp=None, hang=(), empty=(), huge=(), close_on=()):
        self.resp = dict(DEFAULTS)
        if resp:
            self.resp.update(resp)
        self.hang = set(hang)
        self.empty = set(empty)
        self.huge = set(huge)
        self.close_on = set(close_on)
        self.cmds = []                 
        self._stop = threading.Event()
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(8)
        self._srv.settimeout(0.2)
        self.port = self._srv.getsockname()[1]
        self.conns = 0
        self._threads = []
        self._t = threading.Thread(target=self._serve, daemon=True)
        self._t.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self.conns += 1
            th = threading.Thread(target=self._handle, args=(conn,), daemon=True)
            th.start()
            self._threads.append(th)

    def _handle(self, conn):
        buf = b""
        try:
            conn.settimeout(5.0)
            while not self._stop.is_set():
                try:
                    data = conn.recv(4096)
                except socket.timeout:
                    break
                except OSError:
                    break
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, _, buf = buf.partition(b"\n")
                    cmd = line.decode("ascii", "replace").strip()
                    if not cmd:
                        continue
                    self.cmds.append((time.monotonic(), cmd))
                    if cmd in self.hang:
                        continue                      
                    if cmd in self.close_on:
                        conn.close()
                        return
                    if cmd in self.huge:
                        conn.sendall(b"1.000000E+00" + b" " * 20000 + b"\n")
                        continue
                    if cmd in self.empty:
                        conn.sendall(b"\n")
                        continue
                    body = self.resp.get(cmd, "-113,Undefined header")
                    conn.sendall(body.encode("ascii") + b"\n")
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def stop(self):
        self._stop.set()
        try:
            self._srv.close()
        except OSError:
            pass

    def count(self, cmd):
        return sum(1 for _, c in self.cmds if c == cmd)

    def gaps(self):
        ts = [t for t, _ in self.cmds]
        return [round(b - a, 3) for a, b in zip(ts, ts[1:])]

CASES, SKIPS = [], []

def case(fn):
    CASES.append(fn)
    return fn

def eq(a, b, what=""):
    if a != b:
        raise AssertionError("%s: %r != %r" % (what or "值不相等", a, b))

def truth(v, what=""):
    if not v:
        raise AssertionError("断言失败: %s" % (what or "应为真"))

def session_for(port, **kw):
    to = kw.pop("timeout", 1.0)
    tr = S.LanTransport(host="127.0.0.1", port=port, timeout=to)
    kw.setdefault("retry_backoff", 0.02)
    return S.ScpiSession(tr, timeout=to, **kw)

def item(idx):
    doc = json.load(open(ITEMS_PATH, encoding="utf-8"))
    return next(i for i in doc["items"] if i["idx"] == idx)

@case
def t_parse_idn():
    info = S.parse_idn(IDN)
    eq(info["vendor"], "RIGOL TECHNOLOGIES", "vendor")
    eq(info["model"], "DS2102A", "model")
    eq(info["firmware"], "00.03.05", "firmware")
    truth(info["is_ds2102a"] and info["is_rigol"], "型号识别")

@case
def t_parse_numeric():
    eq(S.parse_numeric("1.000000E+07")[0], 1e7, "科学计数")
    eq(S.parse_numeric(" 1.2E+00\n")[0], 1.2, "空白")
    eq(S.parse_numeric("1.200000E+00V")[0], 1.2, "带单位")
    eq(S.parse_numeric("-2.5E-03")[0], -0.0025, "负数")
    eq(S.parse_numeric("*****"), (None, "star"), "星号=无读数")
    eq(S.parse_numeric("9.9E+37"), (None, "sentinel"), "溢出哨兵")
    eq(S.parse_numeric(""), (None, "empty"), "空")
    eq(S.parse_numeric("abc"), (None, "unparsable"), "不可解析")

@case
def t_forbidden_commands_not_sent():
    fs = FakeScope()
    try:
        s = session_for(fs.port, min_gap=0.3, timeout=1.0)
        s.open_and_ping()
        banned = [":WAVeform:DATA? CHANnel1", ":WAV:DATA?", ":WAVeform:POINts?",
                  ":STORage:LOAD?", ":SYSTem:PRESet", ":RUN", ":AUToscale"]
        for cmd in banned:
            try:
                s.query(cmd)
                raise AssertionError("未拦截禁用命令：%s" % cmd)
            except S.ForbiddenCommand:
                pass
        eq(int(s.tr.peer.split(":")[1]), fs.port, "会话仍在同端口")
        got = [c for _, c in fs.cmds]
        truth(got == ["*IDN?"], "服务器只应收到 *IDN?，实收 %r" % (got,))
    finally:
        fs.stop()

@case
def t_query_only_policy():
    for bad in (":MEASure:ITEM FREQuency", ":SYSTem:PRESet\n*IDN?", "é"):
        try:
            S.assert_safe_command(bad)
            raise AssertionError("应拒绝：%r" % bad)
        except S.ForbiddenCommand:
            pass

@case
def t_happy_item_normal():
    fs = FakeScope()
    try:
        s = session_for(fs.port, min_gap=0.3, timeout=1.0)
        s.open_and_ping()
        rd = S.ScopeReader(s, context=False)
        ev, diag = rd.read_item(item(1))
        eq(ev["value"], "normal", "10M 应判正常")
        eq(ev["io"], "lan", "io")
        eq(ev["modality"], "scope", "modality")
        eq(ev["part"], "z11", "part")
        eq(ev["field"], "(scope)z11_10m_reference", "field")
        eq(ev["expect_freq_hz"], 10000000, "expect")
        eq(ev["measured"]["freq_hz"], 1e7, "freq")
        eq(ev["measured"]["vpp"], 1.2, "vpp")
        truth(abs(ev["measured"]["period_s"] - 1e-7) < 1e-15, "period 由频率换算")
        truth(ev["confidence"] >= 0.9, "置信度")
        eq(sorted(ev.keys()),
           sorted(["part", "route", "modality", "field", "value", "measured",
                   "expect_freq_hz", "tol_pct", "confidence", "io"]), "证据键集合")
        truth(not any("WAV" in c.upper() for _, c in fs.cmds), "绝不应出现 WAV 命令")
    finally:
        fs.stop()

@case
def t_freq_abnormal():
    fs = FakeScope(resp={":MEASure:ITEM? FREQuency": "1.200000E+07"})   
    try:
        s = session_for(fs.port, timeout=1.0)
        s.open_and_ping()
        ev, diag = S.ScopeReader(s, context=False).read_item(item(1))
        eq(ev["value"], "abnormal", "20% 偏差应异常")
        truth(ev["confidence"] >= 0.8, "异常置信度")
        truth("out_of_tol" in diag["reason"], diag["reason"])
    finally:
        fs.stop()

@case
def t_tolerance_boundary():
    tol = item(1)["tol_pct"]
    inside = 1e7 * (1 + (tol - 0.01) / 100.0)
    outside = 1e7 * (1 + (tol + 0.01) / 100.0)
    eq(S.judge_freq(inside, 1e7, tol, 1.2)[0], "normal", "边界内")
    eq(S.judge_freq(outside, 1e7, tol, 1.2)[0], "abnormal", "边界外")

@case
def t_context_read():
    fs = FakeScope()
    try:
        s = session_for(fs.port, timeout=1.0)
        s.open_and_ping()
        ctx, missing = S.ScopeReader(s, context=True).read_context()
        eq(ctx["ch1_scale_v_per_div"], 0.5, "CH1 档位")
        eq(ctx["timebase_s_per_div"], 1e-7, "时基")
        eq(ctx["trigger_status"], "TD", "触发状态")
        eq(ctx["measure_source"], "CHAN1", "测量源")
        eq(missing, [], "无缺失")
    finally:
        fs.stop()

@case
def t_timeout_kills_session():
    fs = FakeScope(hang={":MEASure:ITEM? FREQuency"})
    try:
        s = session_for(fs.port, timeout=0.4)
        s.open_and_ping()
        t0 = time.monotonic()
        try:
            s.query(":MEASure:ITEM? FREQuency")
            raise AssertionError("应超时")
        except S.InstrumentUnresponsive:
            pass
        dt = time.monotonic() - t0
        truth(0.3 <= dt <= 2.0, "超时时长 %.2fs" % dt)
        truth(s.is_dead, "会话应作废")
        truth(not s.tr.is_open, "socket 应已关闭")
        n = len(fs.cmds)
        try:
            s.query(":MEASure:ITEM? VPP")
            raise AssertionError("作废后不应再发")
        except S.InstrumentUnresponsive:
            pass
        eq(len(fs.cmds), n, "作废后不得再发命令（不重试轰炸）")
        eq(fs.count(":MEASure:ITEM? FREQuency"), 1, "超时命令只发一次")
    finally:
        fs.stop()

@case
def t_empty_response_unresponsive():
    fs = FakeScope(empty={":MEASure:ITEM? VPP"})
    try:
        s = session_for(fs.port, timeout=1.0)
        s.open_and_ping()
        try:
            s.query(":MEASure:ITEM? VPP", allow_empty=False)
            raise AssertionError("空返回应判无响应")
        except S.InstrumentUnresponsive:
            pass
        truth(s.is_dead, "空返回后会话作废")
    finally:
        fs.stop()

@case
def t_oversized_response_aborts():
    fs = FakeScope(huge={":CHANnel1:SCALe?"})
    try:
        s = session_for(fs.port, timeout=1.0)
        s.open_and_ping()
        try:
            s.query(":CHANnel1:SCALe?")
            raise AssertionError("超长响应应被拒")
        except S.ProtocolViolation:
            pass
        truth(s.is_dead, "超长响应后会话作废")
    finally:
        fs.stop()

@case
def t_peer_close_unresponsive():
    fs = FakeScope(close_on={":MEASure:ITEM? FREQuency"})
    try:
        s = session_for(fs.port, timeout=1.0)
        s.open_and_ping()
        try:
            s.query(":MEASure:ITEM? FREQuency")
            raise AssertionError("对端断开应报无响应")
        except S.InstrumentUnresponsive:
            pass
        eq(fs.conns, 1, "不应重连")
    finally:
        fs.stop()

@case
def t_probe_fail_no_retry_storm():
    class DeadTransport:
        kind = "lan"
        is_open = False
        peer = "dead"
        def open(self):
            raise S.ProbeFailed("connection refused")
        def close(self):
            pass
    s = S.ScpiSession(DeadTransport(), retry_limit=2, retry_backoff=0.02)
    try:
        s.open_and_ping()
        raise AssertionError("应探活失败")
    except S.ProbeFailed as e:
        truth("3 次" in str(e), "错误信息应含尝试次数：%s" % e)
    eq(s.reattempts, 2, "整会话最多重建 2 次")

@case
def t_retry_backoff_is_2s():
    sleeps = []

    class DeadTransport:
        kind = "lan"
        is_open = False
        peer = "dead"
        def open(self):
            raise S.ProbeFailed("dead")
        def close(self):
            pass

    real = time.sleep
    time.sleep = lambda sec: sleeps.append(round(sec, 3))
    try:
        s = S.ScpiSession(DeadTransport(), retry_limit=S.RETRY_LIMIT,
                          retry_backoff=S.RETRY_BACKOFF_S)
        try:
            s.open_and_ping()
            raise AssertionError("应失败")
        except S.ProbeFailed:
            pass
    finally:
        time.sleep = real
    eq(sleeps, [2.0, 2.0], "重建前应各等 2 s（共 2 次）")

    tmp = socket.socket()
    tmp.bind(("127.0.0.1", 0))
    dead_port = tmp.getsockname()[1]
    tmp.close()
    s2 = session_for(dead_port, timeout=0.5, retry_limit=2, retry_backoff=0.02)
    try:
        s2.open_and_ping()
        raise AssertionError("应探活失败")
    except S.ProbeFailed:
        pass
    eq(s2.reattempts, 2, "真实连接失败也只重建 2 次")

@case
def t_probe_reconnect_succeeds():
    fs = FakeScope()
    try:
        s = session_for(fs.port, timeout=1.0)
        s.open_and_ping()
        s.close()

        info = s.open_and_ping()
        eq(info["model"], "DS2102A", "重连后 IDN")
        eq(fs.conns, 2, "两次连接")
    finally:
        fs.stop()

@case
def t_min_gap_enforced():
    fs = FakeScope()
    try:
        s = session_for(fs.port, min_gap=0.3, timeout=1.0)
        s.open_and_ping()
        for _ in range(3):
            s.query(":CHANnel1:SCALe?")
        gaps = [g for g in fs.gaps()]
        truth(len(gaps) >= 3, "命令数不足：%r" % (gaps,))
        truth(min(gaps) >= 0.29, "最小间隔 %.3fs < 0.3s（%r）" % (min(gaps), gaps))
    finally:
        fs.stop()

@case
def t_gap_floor_and_constants():
    s = session_for(1, min_gap=0.01)
    eq(s.min_gap, S.MIN_CMD_GAP_S, "间隔不允许低于硬下限")
    eq(S.MIN_CMD_GAP_S, 0.30, "硬下限 300ms")
    eq(S.CMD_TIMEOUT_S, 3.0, "单条超时 3s")
    eq(S.RETRY_LIMIT, 2, "整会话重建上限 2")
    eq(S.RETRY_BACKOFF_S, 2.0, "重建间隔 2s")

@case
def t_presence_no_signal_abnormal():

    fs = FakeScope(resp={":MEASure:ITEM? FREQuency": "*****",
                         ":MEASure:ITEM? VPP": "2.000000E-02"})
    try:
        s = session_for(fs.port, timeout=1.0)
        s.open_and_ping()
        ev, diag = S.ScopeReader(s, context=False).read_item(item(5))     
        eq(ev["value"], "abnormal", "无信号应异常")
        truth("no_signal" in diag["reason"], diag["reason"])
        eq(ev["judge_mode"] if "judge_mode" in ev else None, None, "证据不带内部字段")
    finally:
        fs.stop()

@case
def t_presence_signal_present_undetermined():
    fs = FakeScope(resp={":MEASure:ITEM? FREQuency": "*****",
                         ":MEASure:ITEM? VPP": "8.000000E-01"})
    try:
        s = session_for(fs.port, timeout=1.0)
        s.open_and_ping()
        ev, _ = S.ScopeReader(s, context=False).read_item(item(5))
        eq(ev["value"], "undetermined", "有信号但无判据 ⇒ undetermined")
        truth(ev["confidence"] < 0.6, "置信度应低")
    finally:
        fs.stop()

@case
def t_freq_star_but_vpp_ok_undetermined():
    fs = FakeScope(resp={":MEASure:ITEM? FREQuency": "*****",
                         ":MEASure:ITEM? VPP": "1.000000E+00"})
    try:
        s = session_for(fs.port, timeout=1.0)
        s.open_and_ping()
        ev, diag = S.ScopeReader(s, context=False).read_item(item(1))
        eq(ev["value"], "undetermined", "频率读不到且幅度正常 ⇒ undetermined")
        truth(diag["reason"].startswith("freq_unreadable"), "原因：%s" % diag["reason"])
    finally:
        fs.stop()

@case
def t_abort_marks_remaining_undetermined():

    fs = FakeScope(hang={":MEASure:ITEM? FREQuency"})
    try:
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "ev.json")
            rep = os.path.join(td, "rep.json")
            rc = S.main(["--host", "127.0.0.1", "--port", str(fs.port),
                         "--only", "1", "2", "3", "--no-context",
                         "--timeout", "0.4", "--retry", "0",
                         "--out", out, "--report", rep])
            eq(rc, 1, "异常退出码")
            env = json.load(open(out, encoding="utf-8"))
            eq(len(env["evidence"]), 3, "3 条证据都要有")
            truth(all(e["value"] == "undetermined" for e in env["evidence"]), "全部 undetermined")
            truth(env["aborted"], "标记 aborted")
            truth(all(e["confidence"] == 0.0 for e in env["evidence"]), "置信度 0")
            eq(fs.count(":MEASure:ITEM? FREQuency"), 1, "只发过一次频率命令")
    finally:
        fs.stop()

@case
def t_usbtmc_framing_via_fd():
    tr = U.UsbTmcTransport()
    if os.name == "nt":
        SKIPS.append("t_usbtmc_framing_via_fd: Windows 无 /dev/usbtmc（已在 Linux 侧实现，这里跳过）")
        return
    rfd, wfd = os.pipe()
    try:
        os.write(wfd, b"1.234000E+01\n")
        tr._fd = rfd
        tr.peer = "pipe"
        eq(tr.read_line(1.0), "1.234000E+01", "读到一行")
        os.write(wfd, b"CHAN1\n2.000000E+00\n")
        eq(tr.read_line(1.0), "CHAN1", "第一行")
        eq(tr.read_line(1.0), "2.000000E+00", "第二行（缓冲/分帧）")
    finally:
        os.close(rfd)
        os.close(wfd)
        tr._fd = None

@case
def t_usbtmc_missing_device():
    tr = U.UsbTmcTransport()
    try:
        tr.open()
        raise AssertionError("无设备时应 ProbeFailed")
    except S.ProbeFailed as e:
        msg = str(e)
        truth(("Windows" in msg) or ("usbtmc" in msg) or ("USBTMC" in msg),
              "失败信息应可操作：%s" % msg)

@case
def t_usbtmc_write_guard():

    tr = U.UsbTmcTransport()
    s = S.ScpiSession(tr, timeout=1.0, retry_backoff=0.01)
    try:
        s.query(":WAVeform:DATA? CHANnel1")
        raise AssertionError("应拦截")
    except S.ForbiddenCommand:
        pass
    eq(tr._fd, None, "未打开任何设备")

@case
def t_items_28_and_csv_consistent():
    doc = json.load(open(ITEMS_PATH, encoding="utf-8"))
    items = doc["items"]
    eq(len(items), 28, "条目数")
    rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8-sig")))
    expect = [r["check_item"].strip() for r in rows
              if r["method"].strip() == "采集示波器输出数据"]
    eq(len(expect), 28, "CSV 中示波器项数")
    eq([i["check_item"] for i in items], expect, "check_item 必须与判据库逐条一致")
    eq([i["flow_no"] for i in items], [int(r["flow_no"]) for r in rows
                                       if r["method"].strip() == "采集示波器输出数据"], "flow_no")

    keys = {(i["field"], i["route"]) for i in items}
    eq(len(keys), 28, "field+route 唯一")
    eq({i["part"] for i in items}, {"z11", "z14"}, "部件集合")
    eq(sorted({i["expect_freq_hz"] for i in items if i["expect_freq_hz"]}),
       [10000000, 30000000, 40000000], "预期频率集合（无 20M）")
    eq(sum(1 for i in items if i["judge_mode"] == "freq"), 6, "可判频率的项（3 信号×2 路）")
    eq({i["route"] for i in items}, {"I", "II"}, "路集合")

    f1 = {i["field"] for i in items if i["route"] == "I"}
    f2 = {i["field"] for i in items if i["route"] == "II"}
    eq(f1, f2, "I/II 路 field 集合应相同（同 z 同元件）")

@case
def t_items_route_from_check_item():
    doc = json.load(open(ITEMS_PATH, encoding="utf-8"))
    for i in doc["items"]:
        if "（II）" in i["check_item"]:
            eq(i["route"], "II", i["check_item"])
        if "（I）路" in i["check_item"]:
            eq(i["route"], "I", i["check_item"])

@case
def t_dry_run_evidence_schema():
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "ev.json")
        rc = S.main(["--dry-run", "--out", out])
        eq(rc, 0, "dry-run 退出码")
        env = json.load(open(out, encoding="utf-8"))
        eq(len(env["evidence"]), 28, "dry-run 28 条")
        for e in env["evidence"]:
            eq(sorted(e.keys()), sorted(["part", "route", "modality", "field", "value",
                                         "measured", "expect_freq_hz", "tol_pct",
                                         "confidence", "io"]), "证据键")
            truth(e["value"] in ("normal", "abnormal", "undetermined"), "value 枚举")
            eq(e["io"], "lan", "io")
            truth(isinstance(e["measured"], dict), "measured 结构")
            eq(sorted(e["measured"].keys()), ["freq_hz", "period_s", "vpp"], "measured 键")
        eq(env["counts"]["undetermined"], 28, "dry-run 全 undetermined")

@case
def t_select_items():
    _, items = S.load_items(ITEMS_PATH)
    eq(len(S.select_items(items, only=[1, 15])), 2, "only")
    eq({i["route"] for i in S.select_items(items, routes=["II"])}, {"II"}, "route")
    eq({i["part"] for i in S.select_items(items, parts=["z14"])}, {"z14"}, "part")

@case
def t_cli_end_to_end():
    fs = FakeScope()
    try:
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "ev.json")
            rep = os.path.join(td, "rep.json")
            rc = S.main(["--host", "127.0.0.1", "--port", str(fs.port),
                         "--only", "1", "15", "--no-context",
                         "--out", out, "--report", rep])
            eq(rc, 0, "退出码")
            env = json.load(open(out, encoding="utf-8"))
            eq(env["counts"]["normal"], 2, "两项都应 normal")
            eq(env["idn"]["model"], "DS2102A", "IDN 落盘")
            eq({e["route"] for e in env["evidence"]}, {"I", "II"}, "两路")
            eq(len({e["field"] for e in env["evidence"]}), 1, "同 z 同 field")
            r = json.load(open(rep, encoding="utf-8"))
            truth(r["commands_sent"] >= 5, "命令计数")
            truth(all("ms" in x for x in r["command_log"] if x.get("lvl") == "ok"),
                  "每条命令都记录耗时")
            truth(len(r["command_log"]) <= S.MAX_LOG_ENTRIES, "日志条数受限")
            truth(not any("WAV" in c.upper() for _, c in fs.cmds), "无 WAV")
    finally:
        fs.stop()

@case
def t_dialect_short():
    fs = FakeScope(resp={":MEAS:ITEM? FREQ": "3.000000E+07"})
    try:
        s = session_for(fs.port, timeout=1.0)
        s.dialect = "short"
        s.open_and_ping()
        ev, _ = S.ScopeReader(s, context=False).read_item(item(2))   
        eq(ev["value"], "normal", "short 写法应可判")
        truth(fs.count(":MEAS:ITEM? FREQ") == 1, "短写法只发一次")
        eq(fs.count(":MEASure:ITEM? FREQuency"), 0, "不应同时发长写法")
    finally:
        fs.stop()

def main():
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    passed, failed = 0, []
    t_all = time.monotonic()
    for fn in CASES:
        name = fn.__name__
        t0 = time.monotonic()
        try:
            fn()
            passed += 1
            print("PASS  %-42s %6.2fs" % (name, time.monotonic() - t0))
        except Exception as e:
            failed.append((name, e))
            print("FAIL  %-42s %6.2fs  %s: %s" % (name, time.monotonic() - t0,
                                                  type(e).__name__, e))
            if verbose:
                traceback.print_exc()
    total = len(CASES)
    dt = time.monotonic() - t_all
    print("-" * 74)
    if SKIPS:
        for s in SKIPS:
            print("SKIP  %s" % s)
    rate = passed / total * 100.0 if total else 0.0
    print("通过率: %d/%d = %.1f%%   用时 %.2fs" % (passed, total, rate, dt))
    if failed:
        print("失败用例：")
        for n, e in failed:
            print("  - %s: %s: %s" % (n, type(e).__name__, e))
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
