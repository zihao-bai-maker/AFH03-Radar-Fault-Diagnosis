#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scpi_sim_selftest.py —— 示波器 SCPI 判定链路的**一键模拟验收**。

用途
----
用户身边暂时没有示波器，所以先用 `tools/scope_sim.py`（DS2302A 模拟器）把整条链路
**端到端**验完；真机到货后，把 `--host` 换成示波器 IP，同一套断言不用改。

验什么（每条都留原始输出）
--------------------------
A. 正常链路（走真实 TCP 栈）
   * 回环 127.0.0.1
   * 本机 LAN IP（如果存在）——证明不是"只在 loopback 上能跑"
   * `*IDN?` / 频率 / Vpp / 探头 / 时基 全部打印
B. 白名单判定（本项目：20 MHz / 40 MHz 方波 = 正常）
   * 20e6 -> PASS/NORMAL      40e6 -> PASS/NORMAL
   * 13.5e6 -> FAIL/ABNORMAL  1e3 -> FAIL
   * 容差边界：20e6 的 +0.9% 内 -> PASS、+1.2% 外 -> FAIL；
               40e6 的 +0.75% 内 -> PASS、-1.25% 外 -> FAIL
C. 异常与容错（必须给明确原因、不挂死、不崩、不静默）
   * 端口没监听        -> ERROR / conn-refused
   * 不回话（超时）     -> ERROR / timeout，且耗时可控
   * 变慢（delay 300ms）-> 加大 timeout 后仍能 PASS（证明超时可调）
   * 不可达网段        -> ERROR，不抛异常
   * 示波器测不出频率（freq=none）-> ERROR / no-signal
D. 设置类命令回读：`:CHAN1:PROB 100` -> `:CHAN1:PROB?` == 100；`*RST` 复位

退出码：0 全过 / 1 有 FAIL
用法：
    python3 tools/scpi_sim_selftest.py --log afh03_work/soc/log_scpi_sim.txt
"""

from __future__ import annotations

import argparse
import contextlib
import inspect
import io
import json
import os
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from soc_vision.scpi_scope import (DEFAULT_NOMINAL_HZ, RigolScpi, ScpiError,  
                                   check_scope, fmt_hz)

try:
    import scope_sim                                                          
except Exception:                                                             
    import importlib.util
    _p = os.path.join(HERE, "scope_sim.py")
    _spec = importlib.util.spec_from_file_location("scope_sim", _p)
    scope_sim = importlib.util.module_from_spec(_spec)                          
    _spec.loader.exec_module(scope_sim)                                         

FakeRigolScope = scope_sim.FakeRigolScope

PASS = 0
FAIL = 0
NOTES = []

def check(name: str, cond: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %-52s %s" % (name, detail))
    else:
        FAIL += 1
        print("  [FAIL] %-52s %s" % (name, detail))
    return bool(cond)

def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p

def pick_port(preferred: int = 5555) -> int:
    """优先用 5555（和现场一致），被占用就自动换一个空闲端口。"""
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", preferred))
        s.close()
        return preferred
    except OSError:
        s.close()
        return free_port()

def local_lan_ip() -> str:
    """找一个非 loopback 的本机 IPv4（走真实网卡），没有就返回空。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))          
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass

    try:
        out = os.popen("hostname -I 2>/dev/null").read().split()
        for ip in out:
            if ":" not in ip and not ip.startswith("127."):
                return ip
    except Exception:                                                         
        pass
    return ""

def run_cli(argv) -> str:
    """在进程内跑 scpi_scope CLI，抓它的原始输出（不用子进程，避免管道问题）。"""
    from soc_vision import scpi_scope
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = scpi_scope.main(argv)
    return "exit=%d\n%s" % (rc, buf.getvalue())

def section_a_normal_tcp(port: int) -> None:
    print("\n== A. 正常链路（真实 TCP 栈）==")
    sim = FakeRigolScope(freq_hz=20e6, vpp_v=3.3, probe=10.0, scale_v_per_div=0.5,
                         time_per_div_s=20e-9, bind="0.0.0.0", port=port,
                         wave_points=4000)
    sim.start()
    try:

        v = check_scope("127.0.0.1", port, ch=1, nominal_list=DEFAULT_NOMINAL_HZ,
                        tol_pct=1.0, timeout=2.0, retries=1, read_wave=True)
        print("  --- 回环 127.0.0.1 原始输出 ---")
        for line in run_cli(["--host", "127.0.0.1", "--port", str(port), "--no-wave"]).splitlines():
            print("      %s" % line)
        check("A1 *IDN? 读到 DS2302A", "DS2302A" in (v.idn or ""), v.idn[:60])
        check("A1 频率 20 MHz", abs(v.freq_hz - 20e6) / 20e6 < 1e-4, fmt_hz(v.freq_hz))
        check("A1 Vpp 3.3 V（示波器读数）", abs(v.vpp_v - 3.3) < 0.05, "%.4f V" % v.vpp_v)
        check("A1 Vpp 波形回读交叉校验 <2%",
              v.vpp_wave_v > 0 and abs(v.vpp_cross_dev_pct) < 2.0,
              "wave=%.4f V dev=%+.2f%%" % (v.vpp_wave_v, v.vpp_cross_dev_pct))
        check("A1 探头 ×10", abs(v.probe - 10.0) < 1e-6, "%g" % v.probe)
        check("A1 时基 20 ns/div", abs(v.time_per_div_s - 20e-9) < 1e-15, "%.4g s/div" % v.time_per_div_s)
        check("A1 V/div 0.5", abs(v.scale_v_per_div - 0.5) < 1e-9, "%g" % v.scale_v_per_div)
        check("A1 判定 PASS/NORMAL", v.ok and v.verdict == "PASS" and v.label == "NORMAL", v.summary())

        lan = local_lan_ip()
        if lan:
            v2 = check_scope(lan, port, ch=1, nominal_list=DEFAULT_NOMINAL_HZ,
                             tol_pct=1.0, timeout=2.0, retries=1, read_wave=False)
            check("A2 走 LAN IP(%s) 也 PASS" % lan,
                  v2.ok and v2.verdict == "PASS",
                  "%s f=%s" % (v2.verdict, fmt_hz(v2.freq_hz)))
        else:
            NOTES.append("本机没有非 loopback IPv4，A2（LAN IP）跳过（板子无网口时属正常）")
            print("  [SKIP] %s" % NOTES[-1])

        v3 = check_scope("127.0.0.1", port, ch=2, nominal_list=DEFAULT_NOMINAL_HZ,
                         tol_pct=1.0, timeout=2.0, retries=1, read_wave=False)
        check("A3 CH2 也能读并判定", v3.ok and v3.verdict == "PASS", v3.summary())

        sc = RigolScpi("127.0.0.1", port, timeout=2.0, retries=1)
        sc.open()
        sc.write(":CHANnel1:PROBe 100")
        got = sc.query(":CHANnel1:PROBe?")
        check("A4 :CHAN1:PROB 100 后回读 =100", abs((float(got) if got else -1) - 100.0) < 1e-6, got)
        sc.write(":TIMebase:MAIN:SCALe 1ms")
        got2 = sc.query(":TIMebase:MAIN:SCALe?")
        check("A4 :TIM:MAIN:SCAL 1ms 后回读 ≈1e-3",
              got2 != "" and abs(float(got2) - 1e-3) / 1e-3 < 1e-6, got2)
        sc.write("*RST")
        got3 = sc.query(":CHANnel1:PROBe?")
        check("A4 *RST 复位探头到 1", abs((float(got3) if got3 else -1) - 1.0) < 1e-6, got3)
        sc.close()
        check("A4 客户端确实发出了这些命令", len(sim.commands) >= 5,
              "共 %d 条: %s" % (len(sim.commands), sim.commands[:6]))
    finally:
        sim.stop()

def section_b_whitelist(port: int) -> None:
    print("\n== B. 白名单判定（20 MHz / 40 MHz = 正常，其余不正常）==")
    cases = [

        (20e6, "PASS", "20 MHz 标准"),
        (40e6, "PASS", "40 MHz 标准"),
        (20e6 * 1.009, "PASS", "20 MHz +0.9% 容差内"),
        (20e6 * 1.012, "FAIL", "20 MHz +1.2% 容差外"),
        (40e6 * 1.0075, "PASS", "40 MHz +0.75% 容差内"),
        (40e6 * 0.9875, "FAIL", "40 MHz -1.25% 容差外"),
        (13.5e6, "FAIL", "13.5 MHz 不在白名单"),
        (1e3, "FAIL", "1 kHz 不在白名单"),
    ]
    for f, want, note in cases:
        sim = FakeRigolScope(freq_hz=f, vpp_v=2.0, probe=10.0, bind="127.0.0.1",
                             port=port, wave_points=800)
        sim.start()
        try:
            v = check_scope("127.0.0.1", port, nominal_list=DEFAULT_NOMINAL_HZ,
                            tol_pct=1.0, timeout=2.0, retries=0, read_wave=False)
        finally:
            sim.stop()
        detail = "实测 %s 偏差 %+.3f%% 标称 %s -> %s/%s" % (
            fmt_hz(v.freq_hz), v.freq_dev_pct, fmt_hz(v.nominal_hz), v.verdict, v.label)
        check("B %-22s -> %s" % (note, want), v.ok and v.verdict == want, detail)
        if want == "PASS":
            check("B %-22s label=NORMAL" % note, v.label == "NORMAL", v.label)
        else:
            check("B %-22s label=ABNORMAL" % note, v.label == "ABNORMAL", v.label)

def section_c_faults(port: int) -> None:
    print("\n== C. 异常与容错（明确原因 / 不挂死 / 不崩 / 不静默）==")

    dead = free_port()
    t0 = time.time()
    v = check_scope("127.0.0.1", dead, nominal_list=DEFAULT_NOMINAL_HZ, tol_pct=1.0,
                    timeout=1.0, retries=0, read_wave=False)
    dt = time.time() - t0
    check("C1 端口没监听 -> ERROR", (not v.ok) and v.verdict == "ERROR",
          "%s | %s" % (v.kind, v.reason[:70]))
    if v.kind == "conn-refused":
        check("C1 原因 = conn-refused", True, v.kind)
    else:

        
        NOTES.append("C1 本平台关闭端口返回 %s（Windows 可能静默丢弃而非 RST）；"
                     "errno->原因 的映射由 C1b 单独确定性验证" % v.kind)
        check("C1 原因属于网络类(conn-refused/timeout)",
              v.kind in ("conn-refused", "timeout"), v.kind)
    check("C1 原因可读（含排查提示）",
          ("示波器不在线" in v.reason) or ("拒绝连接" in v.reason), v.reason[:70])
    check("C1 快速返回（<3s）", dt < 3.0, "%.2fs" % dt)

    from soc_vision.scpi_scope import _explain_oserror
    import errno as _errno
    mapping = [
        (ConnectionRefusedError(_errno.ECONNREFUSED, "refused"), ("conn-refused",)),
        (OSError(_errno.ETIMEDOUT, "timed out"), ("timeout",)),
        (OSError(_errno.ENETUNREACH, "net unreachable"), ("net-unreachable", "host-unreachable")),
        (OSError(_errno.EHOSTUNREACH, "host unreachable"), ("net-unreachable", "host-unreachable")),
        (OSError(_errno.ENETDOWN, "net down"), ("no-interface",)),
    ]
    ok_map = True
    detail = []
    for exc, want in mapping:
        got = _explain_oserror(exc, "1.2.3.4", 5555).kind
        detail.append("%s->%s" % (want[0], got))
        if got not in want:
            ok_map = False
    check("C1b errno -> 明确原因 映射", ok_map, " ".join(detail))

    sim = FakeRigolScope(freq_hz=20e6, bind="127.0.0.1", port=free_port(), drop_after=0)
    sim.start()
    try:
        t0 = time.time()
        v = check_scope("127.0.0.1", sim.port, nominal_list=DEFAULT_NOMINAL_HZ,
                        tol_pct=1.0, timeout=0.8, retries=0, read_wave=False)
        dt = time.time() - t0
    finally:
        sim.stop()
    check("C2 不回话 -> ERROR/timeout", (not v.ok) and v.kind == "timeout",
          "%s | %s" % (v.kind, v.reason[:70]))
    check("C2 超时可控（<4s）", dt < 4.0, "%.2fs（timeout=0.8s）" % dt)
    check("C2 没有被误判成 FAIL", v.verdict != "FAIL", v.verdict)

    sim = FakeRigolScope(freq_hz=40e6, vpp_v=3.3, bind="127.0.0.1",
                         port=free_port(), delay_ms=300.0, wave_points=200)
    sim.start()
    try:
        v = check_scope("127.0.0.1", sim.port, nominal_list=DEFAULT_NOMINAL_HZ,
                        tol_pct=1.0, timeout=3.0, retries=0, read_wave=False)
    finally:
        sim.stop()
    check("C3 每次延迟 300ms + timeout 3s -> 仍 PASS", v.ok and v.verdict == "PASS", v.summary())

    sim = FakeRigolScope(freq_hz=40e6, bind="127.0.0.1", port=free_port(),
                         delay_ms=1500.0, wave_points=200)
    sim.start()
    try:
        v = check_scope("127.0.0.1", sim.port, nominal_list=DEFAULT_NOMINAL_HZ,
                        tol_pct=1.0, timeout=0.5, retries=0, read_wave=False)
    finally:
        sim.stop()
    check("C3b 延迟 1.5s + timeout 0.5s -> ERROR/timeout",
          (not v.ok) and v.kind == "timeout", "%s | %s" % (v.kind, v.reason[:60]))

    t0 = time.time()
    v = check_scope("192.0.2.1", nominal_list=DEFAULT_NOMINAL_HZ, tol_pct=1.0,
                    timeout=1.0, retries=0, read_wave=False)
    dt = time.time() - t0
    check("C4 不可达 IP -> ERROR（不抛异常）",
          (not v.ok) and v.verdict == "ERROR", "%s | %s" % (v.kind, v.reason[:60]))
    check("C4 原因属于网络类", v.kind in ("timeout", "net-unreachable",
                                          "host-unreachable", "no-interface"), v.kind)
    check("C4 耗时可控（<6s）", dt < 6.0, "%.2fs" % dt)

    sim = FakeRigolScope(freq_hz=None, bind="127.0.0.1", port=free_port(), wave_points=200)
    sim.start()
    try:
        v = check_scope("127.0.0.1", sim.port, nominal_list=DEFAULT_NOMINAL_HZ,
                        tol_pct=1.0, timeout=2.0, retries=0, read_wave=True)
    finally:
        sim.stop()
    check("C5 示波器测不出频率 -> ERROR/no-signal",
          (not v.ok) and v.kind == "no-signal", "%s | %s" % (v.kind, v.reason[:70]))
    check("C5 不静默当 PASS/FAIL", v.verdict == "ERROR" and v.label == "UNKNOWN", v.verdict)

    sim = FakeRigolScope(freq_hz=20e6, bind="127.0.0.1", port=free_port(),
                         idn="AGILENT TECHNOLOGIES,DSOX1102G,CN00000001,1.0")
    sim.start()
    try:
        v = check_scope("127.0.0.1", sim.port, nominal_list=DEFAULT_NOMINAL_HZ,
                        tol_pct=1.0, timeout=2.0, retries=0, read_wave=False)
    finally:
        sim.stop()
    check("C6 不是 RIGOL -> ERROR/not-rigol", (not v.ok) and v.kind == "not-rigol",
          "%s | %s" % (v.kind, v.reason[:60]))

def section_d_raw_evidence(port: int, json_out: str) -> None:
    print("\n== D. 完整 CLI 原始输出（取证）==")
    sim = FakeRigolScope(freq_hz=20e6, vpp_v=3.3, probe=10.0, scale_v_per_div=0.5,
                         time_per_div_s=20e-9, bind="127.0.0.1", port=port,
                         wave_points=4000)
    sim.start()
    try:
        out = run_cli(["--host", "127.0.0.1", "--port", str(port),
                       "--nominal", "20000000,40000000", "--tol-pct", "1",
                       "--repeat", "3", "--json-out", json_out])
    finally:
        sim.stop()
    for line in out.splitlines():
        print("      %s" % line)
    check("D CLI 退出码 = 0（PASS 路径）", out.startswith("exit=0"), out.splitlines()[0])
    check("D JSON 已写出", os.path.isfile(json_out), json_out)
    if os.path.isfile(json_out):
        with open(json_out, "r", encoding="utf-8") as f:
            j = json.load(f)
        check("D JSON verdict=PASS / label=NORMAL",
              j.get("verdict") == "PASS" and j.get("label") == "NORMAL",
              "verdict=%s label=%s freq=%.9g" % (j.get("verdict"), j.get("label"), j.get("freq_hz", 0)))
        check("D JSON 里有 Vpp 与标称表",
              j.get("vpp_v", 0) > 0 and j.get("nominal_list") == [20000000.0, 40000000.0],
              "vpp=%.4g nominal_list=%s" % (j.get("vpp_v", 0), j.get("nominal_list")))

def section_e_repeat_stability(port: int) -> None:
    print("\n== E. 重复读稳定性（真机会有读数抖动）==")
    sim = FakeRigolScope(freq_hz=40e6, vpp_v=3.3, bind="127.0.0.1", port=port,
                         wave_points=800)
    sim.start()
    try:
        v = check_scope("127.0.0.1", port, nominal_list=DEFAULT_NOMINAL_HZ, tol_pct=1.0,
                        timeout=2.0, retries=1, repeat=8, read_wave=False)
    finally:
        sim.stop()
    check("E 读 8 次全部成功", v.n_success == 8, "%d/%d" % (v.n_success, v.n_total))
    check("E 40 MHz 判定 PASS", v.verdict == "PASS", v.summary())
    check("E 重复抖动 <0.5%", v.freq_std_pct < 0.5,
          "min=%s max=%s std=%.4f%%" % (fmt_hz(v.freq_min_hz), fmt_hz(v.freq_max_hz), v.freq_std_pct))

def main() -> int:
    ap = argparse.ArgumentParser(description="示波器 SCPI 判定链路 一键模拟验收")
    ap.add_argument("--port", type=int, default=0, help="模拟器端口（0=自动选，默认优先 5555）")
    ap.add_argument("--log", default="", help="把输出同时写到这个文件")
    ap.add_argument("--json-out", default="", help="D 段的判定 JSON 路径")
    a = ap.parse_args()

    port = a.port or pick_port(5555)
    json_out = a.json_out or os.path.join("/tmp" if os.name != "nt" else os.environ.get("TEMP", "."),
                                          "afh03_scpi_verdict.json")

    print("=" * 68)
    print(" AFH03 示波器 SCPI 判定链路 模拟验收")
    print(" 时间        : %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    print(" Python      : %s" % sys.version.split()[0])
    print(" 模拟器      : tools/scope_sim.py (DS2302A, TCP %d)" % port)
    print(" 判定规则    : freq ∈ {20 MHz, 40 MHz} ±1%% -> PASS，其余 FAIL")
    print(" 本机 LAN IP : %s" % (local_lan_ip() or "(无)"))
    print("=" * 68)

    sig = inspect.signature(check_scope)
    print("被测接口 check_scope%s" % str(sig))

    try:
        section_a_normal_tcp(port)
        section_b_whitelist(port)
        section_c_faults(port)
        section_d_raw_evidence(port, json_out)
        section_e_repeat_stability(port)
    except Exception as e:                                                     
        import traceback
        traceback.print_exc()
        check("验收脚本自身不抛异常", False, "%s: %s" % (type(e).__name__, e))

    print("\n" + "=" * 68)
    print("模拟验收结果：PASS=%d  FAIL=%d" % (PASS, FAIL))
    for n in NOTES:
        print("备注：%s" % n)
    print("真机待验：网线插板子网口 -> 板子配同网段静态 IP -> "
          "python3 -m soc_vision.scpi_scope --host <示波器IP>（同一套断言可复用）")
    print("=" * 68)
    return 0 if FAIL == 0 else 1

if __name__ == "__main__":                                                     

    _argv = sys.argv[1:]
    _log = ""
    for i, x in enumerate(_argv):
        if x == "--log" and i + 1 < len(_argv):
            _log = _argv[i + 1]
    if _log:
        os.makedirs(os.path.dirname(os.path.abspath(_log)) or ".", exist_ok=True)
        class _Tee:
            def __init__(self, *streams):
                self.streams = streams
            def write(self, s):
                for st in self.streams:
                    st.write(s)
                    try:
                        st.flush()
                    except Exception:                                          
                        pass
            def flush(self):
                for st in self.streams:
                    try:
                        st.flush()
                    except Exception:                                          
                        pass
        _f = open(_log, "w", encoding="utf-8")
        sys.stdout = _Tee(sys.stdout, _f)
    raise SystemExit(main())
