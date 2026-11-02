#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_lamp_blob.py —— `lamp_blob.detect_lamps()` 的合成用例测试（不需要现场照片）

覆盖（15 项，≥10 项的要求）
--------------------------
 01 红灯亮        → red / on
 02 绿灯亮        → green / on
 03 白灯亮        → white / on
 04 琥珀灯亮      → amber / on
 05 暗灯（灭）    → 仍输出、on=False、delta_v<0
 06 亮背景        → 不报灯（大面积白墙被面积/半径门挡掉）
 07 长条干扰      → 不报灯（extent/长宽比/圆度）
 08 方形按钮      → 不报灯（绿/红方按钮面不是灯）
 09 多灯排序      → 按 y 再 x 升序
 10 无灯          → 空列表
 11 ROI           → 只报框内的灯，坐标仍是原图坐标
 12 输出结构      → 字段/类型/取值范围
 13 dv_thresh     → 对比度不够的"灰区"斑块不判亮
 14 灯组聚类      → Z31 竖排 3 颗聚成一组、按 y 排序
 15 真实照片回归  → 201923（Z31）自动找到 2 红 + 1 绿（有照片才跑）
 16 机位平移      → 面板整体平移后仍能找到灯（固定坐标会失效）——有照片才跑

运行：``python test_lamp_blob.py``
"""
from __future__ import annotations

import math
import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Tuple

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lamp_blob as LB  

W, H = 900, 700
RESULTS: List[Tuple[str, bool, str]] = []
PHOTO = r"D:\xuexishengshou\雷达照片_今天\拍照UI照片\IMGP_20260427_201923.jpg"

def canvas(mean: int = 140, noise: int = 3, seed: int = 0) -> np.ndarray:
    """灰面板（带轻微噪声，模拟真实照片）。"""
    rng = np.random.default_rng(seed)
    base = np.full((H, W, 3), mean, dtype=np.float32)
    base += rng.normal(0, noise, base.shape)
    return np.clip(base, 0, 255).astype(np.uint8)

def draw_lamp(img: np.ndarray, x: int, y: int, r: int, bgr: Tuple[int, int, int],
              on: bool = True, glow: float = 0.50) -> None:
    """画一颗灯。

    on=True  → 亮盘 + 同心光晕（中心远亮于环带 ⇒ 自发光）
    on=False → 暗灯罩（颜色饱和度还在，但比面板暗 ⇒ on=False）
    """
    yy, xx = np.mgrid[0:img.shape[0], 0:img.shape[1]]
    rr = np.sqrt((xx - x) ** 2 + (yy - y) ** 2)
    if on:
        g = np.exp(-(rr / (r * 2.2)) ** 2) * float(glow)
        for c in range(3):
            img[:, :, c] = np.clip(img[:, :, c].astype(np.float32) + g * bgr[c], 0, 255).astype(np.uint8)
        img[rr <= max(2.0, 0.8 * r)] = np.array(bgr, dtype=np.uint8)
    else:
        dark = tuple(max(0, int(v * 0.35)) for v in bgr)
        img[rr <= r] = np.array(dark, dtype=np.uint8)

def fill_rect(img: np.ndarray, x0: int, y0: int, x1: int, y1: int,
              bgr: Tuple[int, int, int]) -> None:
    img[y0:y1, x0:x1] = np.array(bgr, dtype=np.uint8)

def t01_red_on():
    img = canvas(seed=1)
    draw_lamp(img, 300, 350, 11, (0, 0, 255))
    bs = LB.detect_lamps(img)
    assert len(bs) == 1, "应检出 1 颗红亮灯，实得 %d：%s" % (len(bs), bs)
    b = bs[0]
    assert b["color"] == "red", "颜色=%s" % b["color"]
    assert b["on"] is True, "没判成亮：delta_v=%.3f" % b["delta_v"]
    assert abs(b["xy"][0] - 300) <= 2 and abs(b["xy"][1] - 350) <= 2, "坐标偏了：%s" % (b["xy"],)
    assert b["conf"] >= 0.55, "置信 %.2f 过低" % b["conf"]
    return "红亮灯 → red/on @%s d=%+.2f" % (b["xy"], b["delta_v"])

def t02_green_on():
    img = canvas(seed=2)
    draw_lamp(img, 450, 300, 11, (60, 245, 60))
    bs = LB.detect_lamps(img)
    assert len(bs) == 1 and bs[0]["color"] == "green", "绿亮灯没检出：%s" % bs
    assert bs[0]["on"] is True, "绿灯没判亮"
    return "绿亮灯 → green/on @%s d=%+.2f" % (bs[0]["xy"], bs[0]["delta_v"])

def t03_white_on():
    img = canvas(seed=3)
    draw_lamp(img, 350, 250, 10, (255, 255, 255))
    bs = LB.detect_lamps(img)
    assert len(bs) == 1 and bs[0]["color"] == "white", "白亮灯没检出：%s" % bs
    assert bs[0]["on"] is True, "白灯没判亮"
    return "白亮灯 → white/on @%s d=%+.2f" % (bs[0]["xy"], bs[0]["delta_v"])

def t04_amber_on():
    img = canvas(seed=4)
    draw_lamp(img, 550, 400, 11, (0, 165, 255))
    bs = LB.detect_lamps(img)
    assert len(bs) == 1 and bs[0]["color"] == "amber", "琥珀亮灯没检出：%s" % bs
    assert bs[0]["on"] is True, "琥珀灯没判亮"
    return "琥珀亮灯 → amber/on @%s d=%+.2f" % (bs[0]["xy"], bs[0]["delta_v"])

def t05_dark_lamp():
    """灭灯也要输出（只是没亮），否则判定层没法"数灯"。"""
    img = canvas(seed=5)
    draw_lamp(img, 400, 350, 9, (0, 0, 255), on=False)
    bs = LB.detect_lamps(img)
    assert len(bs) == 1, "暗灯没输出：%s" % bs
    b = bs[0]
    assert b["color"] == "red", "暗灯颜色=%s" % b["color"]
    assert b["on"] is False, "暗灯被判成亮（delta_v=%+.3f）" % b["delta_v"]
    assert b["delta_v"] < 0, "暗灯中心应比环带暗：%+.3f" % b["delta_v"]
    return "暗红灯 → red/off d=%+.2f（照样输出）" % b["delta_v"]

def t06_bright_background():
    """大面积亮背景（白墙/纸）不得被当成灯。"""
    img = canvas(seed=6)
    fill_rect(img, 80, 60, 800, 620, (250, 250, 250))
    bs = LB.detect_lamps(img)
    assert bs == [], "亮背景被当成灯：%s" % bs
    return "大面积白背景 → 0 灯"

def t07_long_strip():
    """长条亮带（灯管/反光条）不得被当成灯。"""
    img = canvas(seed=7)
    fill_rect(img, 150, 340, 700, 352, (0, 0, 255))
    bs = LB.detect_lamps(img)
    assert bs == [], "长条亮带被当成灯：%s" % bs
    return "300×12 红长条 → 0 灯"

def t08_square_button():
    """方形色块按钮不得被当成灯（Z31 的〔通〕〔断〕就是方按钮）。"""
    img = canvas(seed=8)
    fill_rect(img, 300, 300, 360, 360, (60, 245, 60))
    bs = LB.detect_lamps(img)
    assert bs == [], "方形按钮被当成灯：%s" % bs
    return "60×60 绿方按钮 → 0 灯"

def t09_sort_order():
    img = canvas(seed=9)
    draw_lamp(img, 100, 300, 9, (0, 0, 255))
    draw_lamp(img, 300, 100, 9, (0, 0, 255))
    draw_lamp(img, 500, 200, 9, (0, 0, 255))
    bs = LB.detect_lamps(img)
    assert len(bs) == 3, "应检出 3 颗，实得 %d" % len(bs)
    ys = [b["xy"][1] for b in bs]
    assert ys == sorted(ys), "没按 y 升序：%s" % [b["xy"] for b in bs]
    assert bs[0]["xy"][0] == 300 and bs[1]["xy"][0] == 500, "同 y 时没按 x 升序：%s" % [b["xy"] for b in bs]
    return "3 灯 → 按 (y,x) 排序 %s" % [b["xy"] for b in bs]

def t10_empty():
    img = canvas(seed=10)
    bs = LB.detect_lamps(img)
    assert bs == [], "空白面板检出了灯：%s" % bs
    return "空白面板 → []"

def t11_roi():
    img = canvas(seed=11)
    draw_lamp(img, 250, 250, 10, (0, 0, 255))
    draw_lamp(img, 700, 550, 10, (0, 0, 255))
    bs = LB.detect_lamps(img, roi=(150, 150, 200, 200))
    assert len(bs) == 1, "ROI 内应只检出 1 颗，实得 %d：%s" % (len(bs), bs)
    assert abs(bs[0]["xy"][0] - 250) <= 2 and abs(bs[0]["xy"][1] - 250) <= 2, \
        "ROI 坐标没还原到原图：%s" % (bs[0]["xy"],)
    return "ROI(150,150,200,200) → 只报框内 1 颗 @%s（原图坐标）" % (bs[0]["xy"],)

def t12_schema():
    img = canvas(seed=12)
    draw_lamp(img, 400, 300, 10, (0, 0, 255))
    bs = LB.detect_lamps(img)
    assert bs, "没检出灯"
    need = {"xy", "r", "color", "hsv", "center_v", "ring_v", "delta_v", "on", "conf"}
    b = bs[0]
    miss = need - set(b)
    assert not miss, "输出缺字段 %s" % miss
    assert isinstance(b["xy"], tuple) and len(b["xy"]) == 2 and all(isinstance(v, int) for v in b["xy"]), "xy 不是 (int,int)"
    assert b["color"] in ("red", "green", "white", "amber"), "color 越界 %s" % b["color"]
    assert isinstance(b["on"], bool), "on 不是 bool"
    assert 0.0 <= b["center_v"] <= 1.0 and 0.0 <= b["ring_v"] <= 1.0, "center_v/ring_v 越界"
    assert -1.0 <= b["delta_v"] <= 1.0, "delta_v 越界"
    assert 0.0 <= b["conf"] <= 1.0, "conf 越界"
    assert len(b["hsv"]) == 3, "hsv 不是三元组"
    return "输出字段齐全（%d 个键）+ 取值域合法" % len(b)

def t13_dv_thresh():
    """对比度落在阈值以下的色斑：仍输出，但 on=False。"""
    img = canvas(mean=120, seed=13)

    yy, xx = np.mgrid[0:img.shape[0], 0:img.shape[1]]
    rr = np.sqrt((xx - 400) ** 2 + (yy - 350) ** 2)
    img[rr <= 10] = (0, 0, 140)
    bs = LB.detect_lamps(img)
    assert len(bs) == 1, "红斑没输出：%s" % bs
    b = bs[0]
    assert b["on"] is False, "灰区红斑被判亮：delta_v=%+.3f" % b["delta_v"]
    assert b["delta_v"] < 0.10, "delta_v 居然≥0.10：%+.3f" % b["delta_v"]
    return "灰区红斑 → red/off d=%+.3f（不判亮）" % b["delta_v"]

def t14_groups():
    """Z31 的三颗灯是竖排：应聚成一组，且组内按 y 排序。"""
    blobs = [
        {"xy": (800, 360), "r": 3.0, "color": "green", "on": False, "conf": 0.8},
        {"xy": (799, 192), "r": 8.0, "color": "red", "on": True, "conf": 0.9},
        {"xy": (799, 254), "r": 8.0, "color": "red", "on": True, "conf": 0.9},
        {"xy": (1256, 348), "r": 13.0, "color": "red", "on": False, "conf": 0.7},
    ]
    gs = LB.group_lamps(blobs, long_side=1600)
    g3 = [g for g in gs if len(g) == 3]
    assert g3, "竖排 3 颗没聚成一组：%s" % [[b["xy"] for b in g] for g in gs]
    g = g3[0]
    assert [b["color"] for b in g] == ["red", "red", "green"], "组内颜色顺序不对：%s" % [b["color"] for b in g]
    assert [b["xy"][1] for b in g] == [192, 254, 360], "组内没按 y 排序：%s" % [b["xy"] for b in g]
    return "竖排 3 颗 → 1 组 %s；右侧孤立红块单独成组" % ([b["xy"] for b in g],)

def _load_photo(path: str, work: int = 1600):
    """按引擎口径读图（EXIF 转正 + 长边缩到 1600；中文路径用 imdecode/fromfile）。"""
    if not os.path.isfile(path):
        return None
    try:
        import cv2
        from PIL import Image, ImageOps
        im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        w, h = im.size
        if max(w, h) > work:
            k = work / max(w, h)
            im = im.resize((int(round(w * k)), int(round(h * k))), Image.BILINEAR)
        return np.asarray(im)[:, :, ::-1].copy()
    except Exception:
        return None

def t15_real_201923():
    """真实照片回归：Z31 应自动找到 2 红 + 1 绿，且红亮、绿灭。"""
    img = _load_photo(PHOTO)
    if img is None:
        return "跳过：本机没有 %s" % PHOTO
    bs = LB.detect_lamps(img)
    cols = [b["color"] for b in bs]
    assert cols == ["red", "red", "green"], "201923 检出颜色序列=%s（应为 red,red,green）" % cols
    assert bs[0]["on"] and bs[1]["on"], "两颗红灯应判亮"
    assert not bs[2]["on"], "控制绿灯应判灭"
    return "201923 → %s（红亮/红亮/绿灭）" % [(b["color"], b["xy"], b["on"]) for b in bs]

def t16_shifted_camera():
    """机位平移：把面板整体右移 180 / 下移 80，仍应找到同样的 3 颗灯（固定坐标会失效）。"""
    img = _load_photo(PHOTO)
    if img is None:
        return "跳过：本机没有 %s" % PHOTO
    h, w = img.shape[:2]
    moved = np.full_like(img, 90)
    moved[80:, 180:] = img[:h - 80, :w - 180]
    bs = LB.detect_lamps(moved)
    cols = [b["color"] for b in bs]
    assert cols == ["red", "red", "green"], "平移后检出=%s（应为 red,red,green）" % cols
    dx = bs[0]["xy"][0] - 799
    dy = bs[0]["xy"][1] - 192
    assert abs(dx - 180) <= 3 and abs(dy - 80) <= 3, "灯位没跟着平移：dx=%d dy=%d" % (dx, dy)
    return "面板右移180/下移80 → 仍检出 3 颗（灯位跟着移动 dx=%d dy=%d）" % (dx, dy)

CASES: List[Tuple[str, Callable[[], str]]] = [
    ("01 红灯亮", t01_red_on),
    ("02 绿灯亮", t02_green_on),
    ("03 白灯亮", t03_white_on),
    ("04 琥珀灯亮", t04_amber_on),
    ("05 暗灯照常输出", t05_dark_lamp),
    ("06 亮背景不误报", t06_bright_background),
    ("07 长条干扰", t07_long_strip),
    ("08 方形按钮", t08_square_button),
    ("09 多灯排序", t09_sort_order),
    ("10 无灯空列表", t10_empty),
    ("11 ROI", t11_roi),
    ("12 输出结构", t12_schema),
    ("13 灰区不判亮", t13_dv_thresh),
    ("14 灯组聚类", t14_groups),
    ("15 真图 201923", t15_real_201923),
    ("16 机位平移", t16_shifted_camera),
]

def main(argv=None) -> int:
    print("=" * 78)
    print("lamp_blob 自检：%d 个用例（%s）" % (len(CASES), "含真图回归" if os.path.isfile(PHOTO) else "纯合成"))
    print("=" * 78)
    ok = 0
    for name, fn in CASES:
        try:
            msg = fn()
            ok += 1
            print("  ✅ %-18s %s" % (name, msg))
        except AssertionError as exc:
            RESULTS.append((name, False, str(exc)))
            print("  ❌ %-18s %s" % (name, exc))
        except Exception:
            RESULTS.append((name, False, traceback.format_exc(limit=2)))
            print("  ❌ %-18s 异常：%s" % (name, traceback.format_exc(limit=2).strip().splitlines()[-1]))
    n = len(CASES)
    print("-" * 78)
    print("通过 %d/%d = %.1f%%" % (ok, n, 100.0 * ok / n))
    print("依赖：numpy=%s  cv2=%s" % (np.__version__, "有" if LB.cv2 is not None else "无（numpy 兜底）"))
    return 0 if ok == n else 1

if __name__ == "__main__":
    raise SystemExit(main())
