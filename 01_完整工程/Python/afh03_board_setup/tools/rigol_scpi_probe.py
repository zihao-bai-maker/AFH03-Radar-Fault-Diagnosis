#!/usr/bin/env python3
"""RIGOL DS2302A 真值探针（SCPI over LAN，裸 socket，不需要 pyvisa）。

为什么需要它
------------
图像识别波形的频率，链路是"时基 x 网格像素"，标定一旦有偏差就会系统性错。
本机（DS2302A）支持 SCPI，可以直接问它：
    :MEASure:ITEM? FREQ,CHAN1   -> 示波器自己测出来的频率（真值）
    :TIMebase:MAIN:SCALe?       -> 当前时基 s/div（不用人眼读面板，也不怕读错）
    :CHANnel1:SCALe?            -> 当前 V/div
    :CHANnel1:PROBe?            -> 当前探头衰减
于是：
  * 标定可以**自动填**（时基/V/div/探头都是问出来的）；
  * 图像算出来的频率可以和 SCPI 真值逐帧对比，直接给我们算法的偏差。

前提
----
1) 示波器已配好 LAN（Utility -> IO -> LAN），记下 IP；
   DS2302A 的 SCPI 端口是 **5555**（Ultra Sigma / 裸 socket），也常支持 5025(VXI-11 需要 pyvisa)。
2) 板上能 ping 通示波器：`ping <scope-ip>`
3) 纯标准库实现，不需要额外 pip 包。

用法
----
    # 只读状态
    python3 tools/rigol_scpi_probe.py --host 192.168.1.50

    # 读状态 + 跑一次图像识别做对比，并生成标定 JSON 片段
    python3 tools/rigol_scpi_probe.py --host 192.168.1.50 --image /tmp/scope.png \
            --roi 40,60,700,360 --write-config config/scope_calib.json

    # 连续比较 20 次（看算法偏差的稳定性）
    python3 tools/rigol_scpi_probe.py --host 192.168.1.50 --grab-dev /dev/video22 --repeat 20
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCOPE_PORT = 5555

class RigolScope:
    """极简 SCPI 客户端（裸 TCP）。"""

    def __init__(self, host: str, port: int = SCOPE_PORT, timeout: float = 3.0):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock: socket.socket | None = None

    def open(self) -> None:
        s = socket.create_connection((self.host, self.port), timeout=self.timeout)
        s.settimeout(self.timeout)
        self.sock = s

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def query(self, cmd: str) -> str:
        assert self.sock is not None
        self.sock.sendall((cmd + "\n").encode("ascii"))
        time.sleep(0.05)
        data = b""
        try:
            while True:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                if data.endswith(b"\n"):
                    break
        except socket.timeout:
            pass
        return data.decode("ascii", "replace").strip()

    def try_query(self, cmd: str) -> str:
        try:
            return self.query(cmd)
        except Exception as e:
            return "ERR:%s" % e

    def info(self) -> dict:
        out = {"idn": self.try_query("*IDN?")}
        for ch in (1, 2):
            out["ch%d_scale_v_per_div" % ch] = self.try_query(":CHANnel%d:SCALe?" % ch)
            out["ch%d_probe" % ch] = self.try_query(":CHANnel%d:PROBe?" % ch)
            out["ch%d_offset" % ch] = self.try_query(":CHANnel%d:OFFSet?" % ch)
            out["ch%d_display" % ch] = self.try_query(":CHANnel%d:DISPlay?" % ch)
        out["time_per_div_s"] = self.try_query(":TIMebase:MAIN:SCALe?")
        out["time_offset_s"] = self.try_query(":TIMebase:MAIN:OFFSet?")
        out["trig_status"] = self.try_query(":TRIGger:STATus?")
        return out

    def measure(self, ch: int = 1) -> dict:
        out = {}
        out["freq_hz"] = self._first_ok([
            ":MEASure:ITEM? FREQ,CHANnel%d" % ch,
            ":MEASure:FREQuency? CHANnel%d" % ch,
        ])
        out["vpp_v"] = self._first_ok([
            ":MEASure:ITEM? VPP,CHANnel%d" % ch,
            ":MEASure:VPP? CHANnel%d" % ch,
        ])
        out["vmax_v"] = self._first_ok([":MEASure:ITEM? VMAX,CHANnel%d" % ch])
        out["vmin_v"] = self._first_ok([":MEASure:ITEM? VMIN,CHANnel%d" % ch])
        out["period_s"] = self._first_ok([
            ":MEASure:ITEM? PERiod,CHANnel%d" % ch,
            ":MEASure:PERiod? CHANnel%d" % ch,
        ])
        return out

    def _first_ok(self, cmds) -> str:
        for c in cmds:
            v = self.try_query(c)
            if v and not v.startswith("ERR:") and "not" not in v.lower():
                return v
        return ""

def _num(s: str):
    try:
        return float(s)
    except Exception:
        return None

def main() -> int:
    ap = argparse.ArgumentParser(description="RIGOL DS2302A SCPI 真值探针")
    ap.add_argument("--host", required=True, help="示波器 IP")
    ap.add_argument("--port", type=int, default=SCOPE_PORT)
    ap.add_argument("--ch", type=int, default=1, choices=[1, 2])
    ap.add_argument("--image", help="同时跑图像识别对比（一张截图）")
    ap.add_argument("--grab-dev", help="同时抓一帧做图像识别（V4L2 设备）")
    ap.add_argument("--roi", default="", help="波形显示区 x,y,w,h")
    ap.add_argument("--repeat", type=int, default=1, help="重复比较次数")
    ap.add_argument("--write-config", help="把 SCPI 读到的时基/V/div/探头写成标定 JSON")
    a = ap.parse_args()

    sc = RigolScope(a.host, a.port)
    try:
        sc.open()
    except Exception as e:
        print("连不上 %s:%d -> %s" % (a.host, a.port, e))
        print("排查：① 示波器 LAN 配好了吗 ② 板上能 ping 通吗 ③ 端口 5555 是否开放")
        print("      RIGOL 需要先按 Utility->IO->LAN 设好 IP；USB 方式需要 pyvisa + USBTMC。")
        return 1

    print("== 基本信息 ==")
    info = sc.info()
    for k, v in info.items():
        print("  %-22s %s" % (k, v))
    meas = sc.measure(a.ch)
    print("\n== SCPI 自测值（真值）==")
    for k, v in meas.items():
        print("  %-22s %s" % (k, v))

    tdiv = _num(info.get("time_per_div_s", ""))
    vdiv = _num(info.get("ch%d_scale_v_per_div" % a.ch, ""))
    probe = _num(info.get("ch%d_probe" % a.ch, ""))
    print("\n== 可直接用的标定 ==")
    print("  time_per_div_s = %s" % tdiv)
    print("  volt_per_div_v = %s" % vdiv)
    print("  probe_atten    = %s" % probe)

    frame = None
    if a.image:
        import cv2
        frame = cv2.imread(a.image, cv2.IMREAD_COLOR)
        if frame is None:
            print("读不到图 %s" % a.image)
    elif a.grab_dev:

        

        

        if os.environ.get("AFH03_I_KNOW_IT_MAY_HANG") != "1":
            print("[拒绝] --grab-dev 会用 OpenCV 阻塞式取流（cap.read() 可能永久阻塞）。")
            print("       请先抓成图再传 --image：")
            print("         python3 tools/v4l2_poll_snap.py -d %s --out /tmp/f.raw --png /tmp/f.png --report"
                  % a.grab_dev)
            print("         python3 tools/rigol_scpi_probe.py --host <IP> --image /tmp/f.png")
            print("       确实要用阻塞式抓帧，请设 AFH03_I_KNOW_IT_MAY_HANG=1（自行承担卡死风险）。")
            return 3
        import cv2
        cap = cv2.VideoCapture(a.grab_dev, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUYV"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        cap.set(cv2.CAP_PROP_CONVERT_RGB, 1)
        for _ in range(10):
            ret, f = cap.read()
            if ret:
                frame = f
        cap.release()

    if frame is not None:
        from soc_vision.config import ScopeCfg
        from soc_vision.scope_wave import analyze_scope_frame
        if a.roi:
            x, y, w, h = (int(v) for v in a.roi.split(","))
        else:
            x, y, w, h = 0, 0, frame.shape[1], frame.shape[0]
            print("警告：没给 --roi，按整图处理（会把菜单栏也算进去）")
        roi = frame[y:y + h, x:x + w]
        if tdiv is None or vdiv is None:
            print("时基/V/div 没读到，无法换算；先确认 SCPI 通了")
        else:
            print("\n== 图像 vs SCPI 对比（%d 次）==" % a.repeat)
            print("  %-6s %-14s %-14s %-9s" % ("次数", "图像 f(Hz)", "SCPI f(Hz)", "偏差%"))
            devs = []
            for i in range(a.repeat):
                cfg = ScopeCfg(roi=(0, 0, w, h), time_per_div_s=tdiv,
                               volt_per_div_v=vdiv, probe_atten=probe or 1.0,
                               h_div=14.0, v_div=8.0, grid_subdiv=5,
                               expect_hz=(_num(meas.get("freq_hz", "")) or None))
                r = analyze_scope_frame(roi, cfg)
                truth = _num(sc.measure(a.ch).get("freq_hz", ""))
                if r.ok and truth:
                    dev = (r.freq_hz - truth) / truth * 100.0
                    devs.append(dev)
                    print("  %-6d %-14.6g %-14.6g %+.2f" % (i + 1, r.freq_hz, truth, dev))
                else:
                    print("  %-6d %-14s %-14s %s" % (i + 1, r.freq_hz if r.ok else "fail",
                                                     truth, r.message[:40]))
                if a.grab_dev:
                    time.sleep(0.3)
                else:
                    break
            if devs:
                import statistics
                print("  偏差均值 %+.2f%%，最大 |偏差| %.2f%%"
                      % (statistics.mean(devs), max(abs(d) for d in devs)))

    if a.write_config:
        block = {"model": "RIGOL DS2302A (SCPI 自动标定)",
                 "time_per_div_s": tdiv, "volt_per_div_v": vdiv, "probe_atten": probe}
        if a.roi:
            block["roi"] = [int(v) for v in a.roi.split(",")]
        old = {}
        if os.path.isfile(a.write_config):
            try:
                old = json.load(open(a.write_config, encoding="utf-8"))
            except Exception:
                old = {}
        cfg = old.get("scope", {}) if isinstance(old.get("scope"), dict) else {}
        cfg.update({k: v for k, v in block.items() if v is not None})
        old["scope"] = cfg
        os.makedirs(os.path.dirname(os.path.abspath(a.write_config)) or ".", exist_ok=True)
        with open(a.write_config, "w", encoding="utf-8") as f:
            json.dump(old, f, ensure_ascii=False, indent=2)
        print("\n已写入 %s" % a.write_config)

    sc.close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
