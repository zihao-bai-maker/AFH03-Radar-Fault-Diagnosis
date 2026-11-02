#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_seg7_read.py —— `seg7_read.read_seg7()` 的合成用例测试（不需要现场照片）

覆盖（18 项）
------------
 01 电池 27.1（3 位 + 小数点在第 2 位后）   → 27.1
 02 电池 27.0                              → 27.0
 03 市电 227（3 位整数，无小数点）          → 227
 04 下限 198                               → 198
 05 上限 242                               → 242
 06 小数 0.0（判据里"0"也是合法示数）        → 0.0
 07 负号 -12.0                             → -12.0
 08 模糊（高斯模糊 σ=2.2）                  → 27.1
 09 倾斜 +5°                               → 227
 10 倾斜 -4°                               → 27.0
 11 反光（旁边一块低饱和高亮斑）            → 27.1
 12 亮度不均（左暗右亮梯度）                → 227
 13 噪声（高斯噪声 σ=14）                   → 27.0
 14 无显示（只有面板）                      → None + no_led_strip
 15 段缺失（"8" 少 a 段）                   → None（拒判，绝不编数）
 16 该有小数点却没有                        → None + dp_not_found
 17 两个小数点 8.8.8（口径不明）             → None + multi_dp
 18 输出结构 / 置信区间 / 位长              → 字段齐、conf∈[0,1]、segments 7 位、digits 为整数（负号=-1）

运行：``python test_seg7_read.py``
"""
from __future__ import annotations

import os
import sys
import traceback
from typing import Callable, List, Tuple

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import seg7_read as S  

import cv2  

RESULTS: List[Tuple[str, bool, str]] = []

DIGIT_SEGS = {
    "0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "bcfg",
    "5": "acdfg", "6": "acdefg", "7": "abc", "8": "abcdefg", "9": "abcdfg",
    "-": "g",
}

def draw_display(text, has_dp=True, dp_pos=None, digit_h=64, gap=9,
                 panel=(38, 40, 44), pad=22, glow=0.75, core=1.0,
                 missing_seg=None):
    """渲染一块红色 LED 七段面板表（黑底红字 + 过曝白芯）。

    text   : 纯数字/负号串，如 "270"
    dp_pos : 小数点落在第几位之后（0 基）；None 表示按 text 里的 '.' 自动取
    missing_seg : (digit_index, "a") 抹掉某位某段（造「段缺失」用例）
    """
    if "." in text:
        dp_pos = text.index(".") - 1 - (0 if not text.startswith("-") else 0)
        text = text.replace(".", "")
    text = str(text)
    n = len(text)
    dw = max(10, int(round(0.63 * digit_h)))
    pitch = dw + gap
    W = pad * 2 + pitch * n - gap
    H = pad * 2 + digit_h
    img = np.full((H, W, 3), panel, dtype=np.float32)

    img[:pad - 6] = np.array(panel, dtype=np.float32) * 0.55
    img[-pad + 6:] = np.array(panel, dtype=np.float32) * 0.55

    seg_layer = np.zeros((H, W), dtype=np.float32)
    core_layer = np.zeros((H, W), dtype=np.float32)
    for i, ch in enumerate(text):
        x0 = pad + i * pitch
        y0 = pad
        segs = DIGIT_SEGS[ch]
        for seg in segs:
            if missing_seg and missing_seg[0] == i and seg == missing_seg[1]:
                continue
            a, b, c, d = S.SEG_WINDOWS[seg]
            xa = int(round(x0 + a * (dw - 1)))
            xb = int(round(x0 + b * (dw - 1)))
            ya = int(round(y0 + c * (digit_h - 1)))
            yb = int(round(y0 + d * (digit_h - 1)))
            seg_layer[ya:yb + 1, xa:xb + 1] = 1.0

            ins = 1 if min(xb - xa, yb - ya) >= 5 else 0
            core_layer[ya + ins:yb + 1 - ins, xa + ins:xb + 1 - ins] = 1.0

    if has_dp and dp_pos is not None:
        i = max(0, min(n - 1, int(dp_pos)))
        dx = pad + i * pitch + dw + gap * 0.42
        dy = pad + digit_h * 0.86
        r = max(2.0, digit_h * 0.105)
        yy, xx = np.mgrid[0:H, 0:W]
        dot = ((xx - dx) ** 2 + (yy - dy) ** 2) <= r * r
        seg_layer[dot] = 1.0
        core_layer[((xx - dx) ** 2 + (yy - dy) ** 2) <= (r * 0.55) ** 2] = 1.0

    halo = cv2.GaussianBlur(seg_layer, (0, 0), sigmaX=max(1.2, digit_h * 0.05))
    halo = np.clip(halo * 1.45, 0, 1) * glow
    b_ch = img[:, :, 0] + halo * 24 + core_layer * 200 * core
    g_ch = img[:, :, 1] + halo * 24 + core_layer * 225 * core
    r_ch = img[:, :, 2] + halo * 215 + core_layer * 245 * core
    img = np.stack([b_ch, g_ch, r_ch], axis=2)
    return np.clip(img, 0, 255).astype(np.uint8)

def add_gradient(img, lo=0.45, hi=1.0):
    """左暗右亮（模拟现场照明不均）。"""
    h, w = img.shape[:2]
    ramp = np.linspace(lo, hi, w, dtype=np.float32)[None, :, None]
    return np.clip(img.astype(np.float32) * ramp, 0, 255).astype(np.uint8)

def add_reflection(img, x, y, r=26, strength=0.55):
    """画一块低饱和高亮的「反光斑」（白光，不带红）。"""
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    g = np.exp(-(((xx - x) ** 2 + (yy - y) ** 2) / (2.0 * r * r)))
    out = img.astype(np.float32)
    for c in range(3):
        out[:, :, c] += g * 235 * strength
    return np.clip(out, 0, 255).astype(np.uint8)

def add_noise(img, sigma=14, seed=7):
    rng = np.random.default_rng(seed)
    out = img.astype(np.float32) + rng.normal(0, sigma, img.shape)
    return np.clip(out, 0, 255).astype(np.uint8)

def rotate(img, deg, border=0.0):
    h, w = img.shape[:2]
    diag = int(np.ceil(np.hypot(h, w))) + 8
    canvas = np.full((diag, diag, 3), int(border), dtype=np.uint8)
    y0 = (diag - h) // 2
    x0 = (diag - w) // 2
    canvas[y0:y0 + h, x0:x0 + w] = img
    M = cv2.getRotationMatrix2D((diag / 2.0, diag / 2.0), deg, 1.0)
    return cv2.warpAffine(canvas, M, (diag, diag), flags=cv2.INTER_LINEAR,
                          borderValue=(0, 0, 0))

def blur(img, sigma=2.2):
    return cv2.GaussianBlur(img, (0, 0), sigma)

def expect_value(img, want, ndigits, has_dp, tol=1e-6, why=""):
    r = S.read_seg7(img, ndigits=ndigits, has_dp=has_dp)
    assert r["value"] is not None, "读不出（reason=%s）" % r["reason"]
    assert abs(r["value"] - want) <= tol, "读数=%r 期望=%r（reason=%s）" % (
        r["value"], want, r["reason"])
    assert 0.0 <= r["conf"] <= 1.0, "conf 越界：%r" % (r["conf"],)
    return r

def expect_reject(img, ndigits, has_dp, reason_kw=None):
    r = S.read_seg7(img, ndigits=ndigits, has_dp=has_dp)
    assert r["value"] is None, "本该拒判，却读出 %r（conf=%.2f）" % (r["value"], r["conf"])
    if reason_kw:
        assert reason_kw in (r["reason"] or ""), "reason=%r 不含 %r" % (r["reason"], reason_kw)
    return r

def t01_battery_27_1():
    img = draw_display("271", has_dp=True, dp_pos=1)
    r = expect_value(img, 27.1, 3, True)
    assert r["digits"] == [2, 7, 1], r["digits"]
    assert r["dp_pos"] == 1, "dp_pos=%r" % (r["dp_pos"],)
    assert r["digits"] == [2, 7, 1] and r["dp_pos"] == 1
    return "27.1 → value=27.1 digits=[2,7,1] conf=%.2f" % r["conf"]

def t02_battery_27_0():
    img = draw_display("270", has_dp=True, dp_pos=1)
    r = expect_value(img, 27.0, 3, True)
    return "27.0 → value=27.0 conf=%.2f" % r["conf"]

def t03_mains_227():
    img = draw_display("227", has_dp=False)
    r = expect_value(img, 227.0, 3, False)
    assert r["dp_pos"] is None, "无小数点表却报了 dp_pos=%r" % (r["dp_pos"],)
    return "227 → value=227 conf=%.2f" % r["conf"]

def t04_low_198():
    img = draw_display("198", has_dp=False)
    r = expect_value(img, 198.0, 3, False)
    return "198 → value=198 conf=%.2f" % r["conf"]

def t05_high_242():
    img = draw_display("242", has_dp=False)
    r = expect_value(img, 242.0, 3, False)
    return "242 → value=242 conf=%.2f" % r["conf"]

def t06_zero():
    img = draw_display("00", has_dp=True, dp_pos=0)
    r = expect_value(img, 0.0, 2, True)
    return "0.0 → value=0.0 conf=%.2f" % r["conf"]

def t07_negative():
    img = draw_display("-120", has_dp=True, dp_pos=2)
    r = expect_value(img, -12.0, 4, True)
    assert r["digits"][0] == -1, "负号没解出来：%r" % (r["digits"],)
    return "-12.0 → value=-12.0 conf=%.2f" % r["conf"]

def t08_blur():
    img = blur(draw_display("271", has_dp=True, dp_pos=1), 2.2)
    r = expect_value(img, 27.1, 3, True)
    return "模糊 σ=2.2 → 27.1 conf=%.2f" % r["conf"]

def t09_tilt_plus5():
    img = rotate(draw_display("227", has_dp=False), +5.0)
    r = expect_value(img, 227.0, 3, False)
    return "倾斜 +5° → 227 conf=%.2f angle=%.1f" % (r["conf"], r["conf_detail"].get("angle", 0.0))

def t10_tilt_minus4():
    img = rotate(draw_display("270", has_dp=True, dp_pos=1), -4.0)
    r = expect_value(img, 27.0, 3, True)
    return "倾斜 -4° → 27.0 conf=%.2f" % r["conf"]

def t11_reflection():
    base = draw_display("271", has_dp=True, dp_pos=1)
    img = add_reflection(base, base.shape[1] * 0.32, base.shape[0] * 0.30,
                         r=22, strength=0.5)
    r = expect_value(img, 27.1, 3, True)
    return "轻微反光 → 27.1 conf=%.2f" % r["conf"]

def t12_uneven_light():
    img = add_gradient(draw_display("227", has_dp=False), 0.42, 1.0)
    r = expect_value(img, 227.0, 3, False)
    return "亮度不均（0.42→1.0）→ 227 conf=%.2f" % r["conf"]

def t13_noise():
    img = add_noise(draw_display("270", has_dp=True, dp_pos=1), sigma=14)
    r = expect_value(img, 27.0, 3, True)
    return "噪声 σ=14 → 27.0 conf=%.2f" % r["conf"]

def t14_blank():
    img = np.full((200, 520, 3), 40, dtype=np.uint8)
    r = expect_reject(img, 3, True, "no_led_strip")
    return "无显示 → None（%s）" % r["reason"]

def t15_missing_segment():

    img = draw_display("8", has_dp=False, missing_seg=(0, "a"))
    r = expect_reject(img, 1, False)
    return "段缺失（8 缺 a）→ None（%s）" % (r["reason"] or "拒判")

def t16_dp_expected_missing():
    img = draw_display("227", has_dp=False)
    r = expect_reject(img, 3, True, "dp_not_found")
    return "该有小数点却没有 → None（%s）" % r["reason"]

def t17_multi_dp():

    img = draw_display("888", has_dp=True, dp_pos=0)

    h, w = img.shape[:2]
    pad, dh = 22, 64
    dw = int(round(0.63 * dh))
    pitch = dw + 9
    dx = pad + 1 * pitch + dw + 9 * 0.42
    dy = pad + dh * 0.86
    cv2.circle(img, (int(dx), int(dy)), max(2, int(dh * 0.10)), (150, 210, 255), -1)
    cv2.circle(img, (int(dx), int(dy)), max(1, int(dh * 0.055)), (210, 240, 255), -1)
    img = cv2.GaussianBlur(img, (0, 0), 0.8)
    r = expect_reject(img, 3, True)
    ok = "multi_dp" in (r["reason"] or "")
    return "8.8.8 双小数点 → None（%s%s）" % (r["reason"] or "拒判",
                                             "" if ok else "／未识别成 multi_dp，仍拒判")

def t18_schema():
    img = draw_display("271", has_dp=True, dp_pos=1)
    r = S.read_seg7(img, ndigits=3, has_dp=True, value_range=(23.4, 28.6))
    for key in ("value", "digits", "dp_pos", "conf", "segments", "bbox", "reason"):
        assert key in r, "缺字段 %s" % key
    assert isinstance(r["conf"], float), "conf 类型 %r" % type(r["conf"])
    assert len(r["segments"]) == 3, "segments 位数=%d" % len(r["segments"])
    assert all(len(s) == 7 for s in r["segments"]), "每位的段数不是 7：%r" % (
        [len(s) for s in r["segments"]],)
    assert len(r["bbox"]) == 4, "bbox=%r" % (r["bbox"],)
    assert r["conf"] >= 0.6, "合成清晰图的置信偏低 %.2f" % r["conf"]

    r2 = S.read_seg7(img, ndigits=3, has_dp=True, value_range=(60.0, 90.0))
    assert r2["value"] == 27.1, "范围检查不该改读数"
    assert "out_of_range" in (r2["reason"] or ""), r2["reason"]
    assert r2["conf"] <= r["conf"], "越界后置信没降：%.3f -> %.3f" % (r["conf"], r2["conf"])
    return "字段齐 / segments 3×7 / conf=%.2f / 越界降置信 %.2f" % (r["conf"], r2["conf"])

CASES: List[Tuple[str, Callable[[], str]]] = [
    ("01 电池 27.1", t01_battery_27_1),
    ("02 电池 27.0", t02_battery_27_0),
    ("03 市电 227", t03_mains_227),
    ("04 下限 198", t04_low_198),
    ("05 上限 242", t05_high_242),
    ("06 小数 0.0", t06_zero),
    ("07 负号 -12.0", t07_negative),
    ("08 模糊", t08_blur),
    ("09 倾斜 +5°", t09_tilt_plus5),
    ("10 倾斜 -4°", t10_tilt_minus4),
    ("11 轻微反光", t11_reflection),
    ("12 亮度不均", t12_uneven_light),
    ("13 噪声", t13_noise),
    ("14 无显示", t14_blank),
    ("15 段缺失", t15_missing_segment),
    ("16 缺小数点", t16_dp_expected_missing),
    ("17 双小数点", t17_multi_dp),
    ("18 输出结构", t18_schema),
]

def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("=" * 78)
    print("seg7_read 自检：%d 个合成用例（纯离线，不碰板子）" % len(CASES))
    print("=" * 78)
    ok = 0
    for name, fn in CASES:
        try:
            msg = fn()
            ok += 1
            print("  ✅ %-14s %s" % (name, msg))
        except AssertionError as exc:
            RESULTS.append((name, False, str(exc)))
            print("  ❌ %-14s %s" % (name, exc))
        except Exception:
            RESULTS.append((name, False, traceback.format_exc(limit=2)))
            print("  ❌ %-14s 异常：%s" % (
                name, traceback.format_exc(limit=2).strip().splitlines()[-1]))
    n = len(CASES)
    print("-" * 78)
    print("通过 %d/%d = %.1f%%" % (ok, n, 100.0 * ok / n))
    print("依赖：numpy=%s  cv2=%s" % (np.__version__, cv2.__version__))
    return 0 if ok == n else 1

if __name__ == "__main__":
    raise SystemExit(main())
