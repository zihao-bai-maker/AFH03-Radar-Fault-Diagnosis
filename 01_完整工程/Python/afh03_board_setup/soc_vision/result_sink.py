"""结果输出：stdout(JSONL) / 文件 / 串口 / UDP。

一路结果统一成一个 dict：
    {"ts": 1710000000.123, "frame": 1234, "fps": 14.2,
     "led": {"led0": true, ...},
     "scope": {"freq_hz": 1000.0, "vpp_v": 3.3, ...},
     "ocr": {"text0": "北京欢迎你"}, "fpga": {...}, "err": ""}

用法：
    sink = ResultSink(cfg.sink)
    sink.emit(result_dict)
    sink.close()
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from typing import Any, Dict, List, Optional

from .config import SinkCfg

class ResultSink:
    def __init__(self, cfg: SinkCfg, log_prefix: str = "AFH03"):
        self.cfg = cfg
        self.log_prefix = log_prefix
        self._file = None
        self._serial = None
        self._sock: Optional[socket.socket] = None
        self._n = 0

        if cfg.file_path:
            d = os.path.dirname(os.path.abspath(cfg.file_path))
            if d and not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            self._file = open(cfg.file_path, "a", encoding="utf-8", buffering=1)

        if cfg.serial_dev:
            try:
                import serial                                     
                self._serial = serial.Serial(cfg.serial_dev, 115200, timeout=0.1)
            except Exception as e:
                sys.stderr.write("[%s] 串口 %s 打不开(%s)，已跳过串口输出\n"
                                 % (log_prefix, cfg.serial_dev, e))

        if cfg.udp_host:
            try:
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            except Exception as e:                                
                sys.stderr.write("[%s] UDP socket 创建失败: %s\n" % (log_prefix, e))

    def emit(self, result: Dict[str, Any]) -> None:
        self._n += 1
        line = json.dumps(result, ensure_ascii=False, separators=(",", ":"))

        if self.cfg.print_every_n > 0 and (self._n % self.cfg.print_every_n == 0):
            if self.cfg.stdout_json:
                print(line, flush=True)
            else:
                print("[%s] %s" % (self.log_prefix, self._human(result)), flush=True)

        if self._file is not None:
            self._file.write(line + "\n")

        if self._serial is not None:
            try:
                self._serial.write((line + "\n").encode("utf-8", "replace"))
            except Exception:
                pass

        if self._sock is not None:
            try:
                self._sock.sendto(line.encode("utf-8"),
                                  (self.cfg.udp_host, self.cfg.udp_port))
            except Exception:
                pass

    @staticmethod
    def _human(r: Dict[str, Any]) -> str:
        parts: List[str] = []
        led = r.get("led") or {}
        if led:
            parts.append("LED=" + "".join("1" if v else "0" for v in led.values()))
        sc = r.get("scope") or {}
        if sc and sc.get("ok"):
            seg = "f=%.4gHz Vpp=%.3fV" % (sc.get("freq_hz", 0.0), sc.get("vpp_v", 0.0))
            if sc.get("verdict"):
                seg += " %s(%+.2f%%)" % (sc["verdict"], sc.get("freq_dev_pct", 0.0))
            parts.append(seg)
        oc = r.get("ocr") or {}
        if oc:
            parts.append("OCR=" + ",".join("%s:%s" % (k, v) for k, v in oc.items()))
        if r.get("err"):
            parts.append("ERR=" + str(r["err"]))
        return " ".join(parts) if parts else "(no result)"

    def emit_heartbeat(self, frame: int, fps: float, extra: Dict[str, Any] = None) -> None:
        d = {"ts": round(time.time(), 3), "frame": frame, "fps": round(fps, 2),
             "heartbeat": True}
        if extra:
            d.update(extra)
        self.emit(d)

    def close(self) -> None:
        for obj in (self._file, self._serial):
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
