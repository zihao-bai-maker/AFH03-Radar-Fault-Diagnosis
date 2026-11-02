#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归用例：**检测帧必须全分辨率**（本次回归的根因防线）。

读 afh03-ui 的 journal，取最近的 `[marker] frame=WxH` 行，断言短边 >= 1080。
用法：python3 tools/check_detect_frame.py    （通过 exit 0，失败 exit 1）
"""
import re
import subprocess
import sys

try:
    out = subprocess.run(["journalctl", "-u", "afh03-ui", "-n", "300", "--no-pager"],
                         capture_output=True, text=True, timeout=30).stdout
except Exception as e:                                                
    print("取 journal 失败: %s" % e)
    sys.exit(2)
sizes = re.findall(r"\[marker\] frame=(\d+)x(\d+)", out)
if not sizes:
    print("[check] 未找到 `[marker] frame=WxH` 行 —— 无法判定（可能 UI 未运行/未启动标记线程）")
    sys.exit(2)
w, h = int(sizes[-1][0]), int(sizes[-1][1])
short = min(w, h)
print("[check] 最近检测帧 = %dx%d（短边 %d）" % (w, h, short))
if short < 1080:
    print("[check][FAIL] 检测帧短边 < 1080：标记检测会失效（只允许降预览，不允许降检测帧）")
    sys.exit(1)
print("[check][PASS] 检测帧全分辨率 OK（预览可独立降采样）")
sys.exit(0)
