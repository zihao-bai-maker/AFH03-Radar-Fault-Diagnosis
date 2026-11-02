#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""part_recognizer.py —— **多模态部位识别**：这是哪个部位/模块？

背景
----
现场 119 张真图里，机柜门板上常印着 ``Z11 / 收发``、``Z14 / 信处``、
``Z15 / 显示电路``、``Z31 / 电源控制`` 等丝印；模块面板上也有
``频综 / 固态功放 / 接收前端 / 近程增益 / GL / CLK / IF / CPU`` 等字样。
因此**部位识别不能只依赖二维码标记**：标记（模态 A）是精确证据，但当前
现场还没贴标；OCR（模态 B）与外观（模态 C）必须能独立工作，上下文
（模态 D：flow/route、上一次结果）只做先验微调。

四个模态
--------
A. **标记 marker** —— 复用 :mod:`soc_vision.marker_id`（4x4 字典 / 8x8 布局）
   与 ``markers_v2.json``（18 个 id：4x4 码 6..23）。读到即映射到部位，
   置信 ~0.95。**没有标记也继续识别**，不会因为没标记就返回 unknown。
B. **面板文字 OCR** —— 优先用 RapidOCR（离线、可选依赖、CPU 约 1.4~2.3 s/帧），
   没有 RapidOCR 时退化为“渲染关键词模板 + 多尺度 NCC”的轻量匹配；模板命中块
   再用 ``ocr_cn.py`` 的 ``to_binary_char`` / ``_ncc`` 复核（只读复用，不改它）。
   关键词表覆盖 18 个部位的丝印名与模块名；对 ``714→Z14``、``231→Z31``
   这类 OCR 常见误读做**低分纠正**，不把纠正结果当高置信。
   **注意**：``ocr_cn.py`` 的 66 字模板库只覆盖 G5 状态屏，不能直接读任意面板
   丝印；因此主 OCR 不是它，见 README §4B。
C. **外观视觉特征** —— HSV 颜色直方图、4x4 空间色、3x3 梯度方向、
   边缘密度、指示灯/屏幕区域统计；用真图建立 ``part_features.json``
   参考库，余弦相似度匹配。外观分只有 0.5~0.8，永远低于明确 OCR/标记。
D. **上下文** —— ``flow_no``（1~27=I 路，28=切换点，29+=II 路）、
   ``route``、上一次识别结果（时间连续性）⇒ 先验分 ≤0.4，只做微调。

融合与“宁可不判”
----------------
加权融合（marker 1.00 > ocr 0.85 > appearance 0.55 > context 0.25）。
置信不足、前二名差距过小、OCR 与外观冲突、或检测到不在 18 个清单内的
部位（如 Z17 操显）⇒ ``need_confirm: true``，由 UI 问人确认。

输入/输出契约
-------------
``recognize()`` 输出::

    {"part": "z11", "name": "收发分机", "confidence": 0.86, "route": "I",
     "modality_breakdown": {
         "marker": null,
         "ocr": {"text": "Z11 收发", "score": 0.9, "backend": "rapidocr"},
         "appearance": {"best": "z11", "score": 0.72, "similarity": 0.81},
         "context": 0.4},
     "candidates": [{"part": "z11", "score": 0.86}, {"part": "z5", "score": 0.41}],
     "need_confirm": false, ...}

与 fusion/fault_grader 的衔接见 ``README_part_recognizer.md``：
部位确定后，``criteria_for(part)`` 取该部位的判据行，采集 agent 再用
``to_evidence()`` 生成 ``evidence/v1`` 证据交给 ``fusion.py`` /
``fault_grader.py``；本文件**不直接下故障结论**。

命令行
------
::

    python part_recognizer.py --image 某张.jpg
    python part_recognizer.py --image 某张.jpg --flow 3 --prior z11
    python part_recognizer.py --build-features labels.json --out part_features.json
    python part_recognizer.py --criteria z11
    python part_recognizer.py --self-test

硬约束：只读复用 ``marker_id.py`` / ``ocr_cn.py`` / ``cjk_text.py`` /
``markers_v2.json`` / 判据库；不修改它们，不碰板子。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

try:  
    import cv2
except Exception:  
    cv2 = None  

try:
    from PIL import Image, ImageDraw, ImageFont
    _HAVE_PIL = True
except Exception:  
    _HAVE_PIL = False

HERE = os.path.dirname(os.path.abspath(__file__))
RADAR_DIR = os.path.dirname(HERE)                       
WORKSPACE = os.path.dirname(RADAR_DIR)                  
BOARD_DIR = os.path.join(WORKSPACE, "afh03_board_setup")
SOC_VISION = os.path.join(BOARD_DIR, "soc_vision")
VENDOR_DIR = os.path.join(SOC_VISION, "_vendor")

MARKERS_V2_JSON = os.path.join(RADAR_DIR, "markers_v2", "markers_v2.json")
MARKERS_PLUS_G_JSON = os.path.join(RADAR_DIR, "markers_v2", "markers_v2_plus_G.json")
MARKERS_PNG_DIR = os.path.join(RADAR_DIR, "markers_v2", "png", "large")
FEATURES_JSON = os.path.join(HERE, "part_features.json")
SOP_CSV = os.path.join(RADAR_DIR, "判据库_SOP.csv")
FAULT_CSV = os.path.join(RADAR_DIR, "判据库_故障.csv")
PHOTO_DIR = os.path.join(WORKSPACE, "雷达照片_今天", "拍照UI照片")

_ALIAS_CACHE = None

def _alias_mod():
    """→ ``(normalize_part_route, normalize_route)``；helper 不可用时返回 ``(None, None)``。

    路径候选：engine 正常由 ``board_infer.bootstrap()`` 把板端 setup 目录塞进 sys.path；
    但**单文件直跑**（``python3 part_recognizer.py --image …``）时没有那层 bootstrap，
    这里显式把板端常见绝对路径也加进 sys.path，保证 CLI/单测同样归一。
    """
    global _ALIAS_CACHE
    if _ALIAS_CACHE is not None:
        return _ALIAS_CACHE
    fn = rn = None
    for p in (BOARD_DIR, SOC_VISION, HERE,
              "/home/rock/afh03_board_setup",
              "/home/rock/afh03_board_setup/soc_vision"):
        if p and p not in sys.path:
            sys.path.insert(0, p)
    try:
        from soc_vision.module_route_alias import (normalize_part_route as fn,
                                                  normalize_route as rn)
    except Exception:                                                 
        try:
            from module_route_alias import (normalize_part_route as fn,
                                            normalize_route as rn)
        except Exception:                                             
            fn = rn = None
    _ALIAS_CACHE = (fn, rn)
    return _ALIAS_CACHE

SCHEMA = "part_recognition/v1"
FEATURE_SCHEMA = "part_features/1.0"

PART_INFO: Dict[str, Dict[str, Any]] = {
    "z4": {"name": "天线控制单元", "short": "天线控制", "level": "cabinet"},
    "z5": {"name": "收发机柜", "short": "收发机柜", "level": "cabinet"},
    "z11": {"name": "收发分机", "short": "收发", "level": "cabinet"},
    "z12": {"name": "电源分机", "short": "电源", "level": "cabinet"},
    "z14": {"name": "信号处理分机", "short": "信处", "level": "cabinet"},
    "z15": {"name": "显示电路分机", "short": "显示电路", "level": "cabinet"},
    "z16": {"name": "指示分机", "short": "指示", "level": "cabinet"},
    "z18": {"name": "控制分机", "short": "控制", "level": "cabinet"},
    "z20": {"name": "控制台", "short": "控制台", "level": "cabinet"},
    "z31": {"name": "配电箱", "short": "配电箱", "level": "cabinet"},
    "z11-1": {"name": "频综", "short": "频综", "level": "module", "parent": "z11"},
    "z11-3": {"name": "固态功放", "short": "功放", "level": "module", "parent": "z11"},
    "z11-4": {"name": "接收前端", "short": "接收前端", "level": "module", "parent": "z11"},
    "z11-5": {"name": "近程增益", "short": "近程增益", "level": "module", "parent": "z11"},
    "z12-GL": {"name": "GL1/GL2/GL3 电源", "short": "GL电源", "level": "module", "parent": "z12"},
    "z14-CLK": {"name": "时钟板", "short": "时钟板", "level": "module", "parent": "z14"},
    "z15-IF": {"name": "接口板", "short": "接口板", "level": "module", "parent": "z15"},
    "z15-CPU": {"name": "CPU板", "short": "CPU板", "level": "module", "parent": "z15"},
}

CABINET_PARTS = [p for p, v in PART_INFO.items() if v.get("level") == "cabinet"]

UNSUPPORTED_HINTS = {
    "Z17": "Z17 操显（不在 18 个部位清单内）",
    "Z19": "Z19 转接分机（判据库有，但 markers_v2 清单未列）",
    "Z6": "Z6 机柜（清单未列）",
}

MODALITY_WEIGHTS = {"marker": 1.00, "ocr": 0.85, "appearance": 0.55, "context": 0.25}

FEATURE_BLOCKS: List[Tuple[str, int, float]] = [
    ("hsv_hist", 72, 1.00),
    ("grid_hsv", 64, 0.90),
    ("grad_hist", 72, 0.80),
    ("edge_grid", 12, 0.70),
    ("led", 22, 1.10),
    ("screen", 8, 0.90),
    ("stats", 10, 0.60),
]
FEATURE_DIM = sum(d for _, d, _ in FEATURE_BLOCKS)

OCR_NAME_RULES: List[Tuple[str, str, float]] = [
    ("收发机柜", "z5", 0.92),
    ("收发分机", "z11", 0.92),
    ("收发", "z11", 0.80),
    ("配电箱", "z31", 0.92),
    ("电源控制", "z31", 0.88),
    ("电源分机", "z12", 0.90),
    ("电源", "z12", 0.55),
    ("信号处理", "z14", 0.90),
    ("信处", "z14", 0.88),
    ("显示电路", "z15", 0.90),
    ("显示", "z15", 0.55),
    ("指示分机", "z16", 0.90),
    ("指示", "z16", 0.58),
    ("控制分机", "z18", 0.90),
    ("障碍灯控制", "z18", 0.86),
    ("控制台", "z20", 0.90),
    ("天线控制单元", "z4", 0.92),
    ("频综", "z11-1", 0.90),
    ("固态功放", "z11-3", 0.90),
    ("功放", "z11-3", 0.82),
    ("接收前端", "z11-4", 0.90),
    ("近程增益", "z11-5", 0.90),
    ("GL1", "z12-GL", 0.86),
    ("GL2", "z12-GL", 0.86),
    ("GL3", "z12-GL", 0.86),
    ("GL电源", "z12-GL", 0.86),
    ("时钟板", "z14-CLK", 0.90),
    ("CLK", "z14-CLK", 0.78),
    ("接口板", "z15-IF", 0.90),
    ("IF板", "z15-IF", 0.84),
    ("CPU板", "z15-CPU", 0.90),
    ("CPU", "z15-CPU", 0.80),
]
OCR_NAME_RULES.sort(key=lambda x: -len(x[0]))

TEMPLATE_KEYWORDS = [
    "Z4", "Z5", "Z11", "Z12", "Z14", "Z15", "Z16", "Z18", "Z20", "Z31",
    "收发", "信处", "显示电路", "电源控制", "控制台", "配电箱", "障碍灯控制",
    "频综", "功放", "接收前端", "近程增益", "时钟板", "接口板", "CPU",
]

NEAR_CODE_RE = re.compile(r"^[Z2T7]\s*[-]?\s*(\d{1,3})(?:\s*[-]?\s*([A-Z0-9]{1,3}))?$")
NEAR_CODE_MAP = {
    "4": "z4", "5": "z5", "11": "z11", "12": "z12", "14": "z14", "15": "z15",
    "16": "z16", "18": "z18", "20": "z20", "31": "z31",

    "714": "z14", "715": "z15", "711": "z11", "712": "z12", "718": "z18",
    "716": "z16", "720": "z20", "731": "z31", "131": "z31", "231": "z31",
}

ISO_TZ = timezone(timedelta(hours=8))

def now_iso() -> str:
    return datetime.now(ISO_TZ).isoformat(timespec="seconds")

def _clip(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return float(max(lo, min(hi, v)))

def _norm_part(part: Any) -> str:
    """Z11-1 / Z11（收发分机） / z11 都归一为 z11-1 / z11。"""
    s = str(part or "").strip().lower().replace("（", "-").replace("）", "")
    s = re.sub(r"[^a-z0-9\-]+", "", s)
    m = re.match(r"^z(\d{1,2})(?:[-_]?([a-z0-9]+))?$", s)
    if not m:
        return s
    base = "z" + str(int(m.group(1)))
    tail = (m.group(2) or "").upper()
    if not tail:
        return base
    if tail.isdigit():
        return base + "-" + tail
    return base + "-" + tail

def part_name(part: str) -> str:
    return (PART_INFO.get(part) or {}).get("name", "")

def part_display(part: str, route: str = "") -> str:
    """部位显示名。

    ★ 2026-10-29 二路码口径：旧 id（z11-1 / Z12-GL / z12-clk / Z14-CLK / Z15-IF）先归一成
      母模块 + II ⇒ 成对部位直接显示「Z11 二路」/「Z11 一路」；不传 route 时显示「Z11」
      （绝不猜路别）。独立模块/机柜部位保持「z11-3 固态功放」这种原名格式不变。
    """
    fn = _alias_mod()[0]
    if fn is not None:
        p, r = fn(part, route)
    else:
        p, r = str(part or "").strip(), str(route or "").strip().upper()
    if not p:
        return ""
    if p in ("z11", "z12", "z14", "z15"):
        cn = {"I": "一路", "II": "二路"}.get(str(r or "").upper())
        return ("%s %s" % (p.upper(), cn)) if cn else p.upper()
    info = PART_INFO.get(p) or {}
    return ("%s %s" % (p, info.get("name", ""))).strip()

def load_bgr(path_or_array: Any) -> Optional[np.ndarray]:
    """读图：兼容中文路径（cv2.imread 在 Windows 中文路径会失败）。"""
    if isinstance(path_or_array, np.ndarray):
        img = path_or_array
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if cv2 is not None else np.dstack([img] * 3)
        return img
    if cv2 is None or not path_or_array:
        return None
    path = str(path_or_array)
    if not os.path.isfile(path):
        return None
    try:
        data = np.fromfile(path, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        return img
    except Exception:
        return None

def _resize_max(img: np.ndarray, max_side: int = 1280) -> Tuple[np.ndarray, float]:
    h, w = img.shape[:2]
    m = max(h, w)
    if m <= max_side:
        return img, 1.0
    s = max_side / float(m)
    out = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
    return out, s

class MarkerBackend:
    """复用板端 ``soc_vision/marker_id.py``；不改它，只设置单帧模式。"""

    def __init__(self, json_path: str = "", verbose: bool = False):
        self.ok = False
        self.error = ""
        self.json_path = json_path or MARKERS_V2_JSON
        self.mi = None
        if cv2 is None:
            self.error = "no cv2"
            return
        if BOARD_DIR not in sys.path:
            sys.path.insert(0, BOARD_DIR)
        if VENDOR_DIR not in sys.path:
            sys.path.insert(0, VENDOR_DIR)
        try:
            from soc_vision.marker_id import MarkerId  
            self.mi = MarkerId(self.json_path, confirm_n=1, verbose=verbose)

            self.mi.latch_sec = 0.0
            self.mi.window_sec = 0.5
            self.ok = True
        except Exception as e:  
            self.error = "%s: %s" % (type(e).__name__, e)

    def detect(self, bgr: np.ndarray, rot_search: bool = False) -> Optional[Dict[str, Any]]:
        if not self.ok or self.mi is None or bgr is None:
            return None
        hit = self._detect_once(bgr)
        if hit is not None or not rot_search or cv2 is None:
            return hit

        
        h, w = bgr.shape[:2]
        center = (w / 2.0, h / 2.0)
        for ang in (4.0, -4.0, 7.0, -7.0):
            M = cv2.getRotationMatrix2D(center, ang, 1.0)
            rot = cv2.warpAffine(bgr, M, (w, h), borderValue=(210, 210, 210))
            hit = self._detect_once(rot)
            if hit is not None:
                hit["rotated_deg"] = ang
                hit["score"] = round(max(0.90, float(hit["score"]) - 0.02), 4)
                return hit
        return None

    def _detect_once(self, bgr: np.ndarray) -> Optional[Dict[str, Any]]:
        try:
            hit, _hits = self.mi.detect(bgr)
        except Exception as e:  
            self.error = "%s: %s" % (type(e).__name__, e)
            return None
        if hit is None:
            return None
        mod = hit.module or {}
        part = _norm_part(mod.get("part") or mod.get("label"))
        if part not in PART_INFO:
            return None
        score = _clip(0.90 + 0.06 * float(hit.score), 0.90, 0.97)
        return {
            "part": part,
            "label": hit.label,
            "marker_id": int(hit.marker_id),
            "score": round(score, 4),
            "hit_score": round(float(hit.score), 4),
            "name": mod.get("name", part_name(part)),
            "level": mod.get("level", (PART_INFO.get(part) or {}).get("level", "")),
            "box": [round(float(hit.cx), 1), round(float(hit.cy), 1), round(float(hit.side_px), 1)],
        }

def _font_path() -> str:
    cands = [
        os.path.join(BOARD_DIR, "fonts", "SourceHanSansJP-Normal.otf"),
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ]
    for p in cands:
        if p and os.path.isfile(p):
            return p
    return ""

class RapidOcrBackend:
    """可选依赖：``pip install rapidocr_onnxruntime``（离线 CPU 可跑）。"""

    name = "rapidocr"

    def __init__(self, max_side: int = 1280):
        self.max_side = max_side
        self._ocr = None
        self.error = ""
        try:
            from rapidocr_onnxruntime import RapidOCR  
            self._ocr = RapidOCR()
        except Exception as e:  
            self.error = "%s: %s" % (type(e).__name__, e)

    @property
    def ok(self) -> bool:
        return self._ocr is not None

    def read(self, bgr: np.ndarray) -> List[Dict[str, Any]]:
        if self._ocr is None or bgr is None:
            return []
        small, scale = _resize_max(bgr, self.max_side)
        try:
            raw, _elapse = self._ocr(small)
        except Exception as e:  
            self.error = "%s: %s" % (type(e).__name__, e)
            return []
        out: List[Dict[str, Any]] = []
        for item in raw or []:
            try:
                box, text, score = item[0], str(item[1]), float(item[2])
            except Exception:
                continue
            if not text.strip():
                continue
            pts = [[float(p[0]) / scale, float(p[1]) / scale] for p in box]
            out.append({"text": text.strip(), "score": _clip(score), "box": pts,
                        "backend": self.name})
        return out

class OcrCnBridge:
    """复用 ``ocr_cn.py`` 的二值化/NCC 做模板兜底复核（不改 ocr_cn）。

    ``ocr_cn.py`` 的固定模板库（``ref_cn/cn_bank_real2.npz``）只有 66 个
    G5 状态屏字符，**不能**直接读任意面板丝印；这里只复用它
    ``to_binary_char`` / ``_ncc`` 两个纯函数，对模板命中块做二次核对。
    """

    def __init__(self):
        self.ok = False
        self.error = ""
        try:
            if BOARD_DIR not in sys.path:
                sys.path.insert(0, BOARD_DIR)
            from soc_vision.ocr_cn import to_binary_char, _ncc  
            self._bin = to_binary_char
            self._ncc = _ncc
            self.ok = True
        except Exception as e:  
            self.error = "%s: %s" % (type(e).__name__, e)

    def verify(self, patch_bgr: np.ndarray, tmpl_bin: np.ndarray) -> float:
        if not self.ok or patch_bgr is None or patch_bgr.size == 0:
            return 0.0
        try:
            tb = self._bin(patch_bgr, (int(tmpl_bin.shape[1]), int(tmpl_bin.shape[0])))
            return float(self._ncc(tmpl_bin, tb))
        except Exception:
            return 0.0

class TemplateOcrBackend:
    """轻量兜底：把关键词渲染成模板，在暗字亮底图上做多尺度 NCC。

    它不是通用 OCR：只认 ``TEMPLATE_KEYWORDS``，且对旋转/透视/手写体弱。
    有 RapidOCR 时**不会**用它；实测精度见 README。命中块再用
    ``ocr_cn.OcrCnBridge`` 的 ``to_binary_char + _ncc`` 复核一次。
    """

    name = "template_ncc"

    def __init__(self):
        self.font_path = _font_path()
        self.error = "" if (self.font_path and _HAVE_PIL and cv2 is not None) else "no font/PIL/cv2"
        self._tmpls: Dict[str, List[np.ndarray]] = {}
        self.bridge = OcrCnBridge()
        if not self.error:
            self._build()

    def _render(self, text: str, px: int) -> np.ndarray:
        font = ImageFont.truetype(self.font_path, px)
        tmp = Image.new("L", (max(8, px * (len(text) + 2)), px * 3), 0)
        dr = ImageDraw.Draw(tmp)
        dr.text((2, 2), text, font=font, fill=255)
        bbox = tmp.getbbox()
        if bbox:
            tmp = tmp.crop(bbox)
        return np.asarray(tmp, dtype=np.uint8)

    def _build(self) -> None:
        for kw in TEMPLATE_KEYWORDS:
            arrs = []
            for px in (34, 44, 56, 70, 88):
                a = self._render(kw, px)
                if a.size:
                    arrs.append(a)
            self._tmpls[kw] = arrs

    @property
    def ok(self) -> bool:
        return not self.error and bool(self._tmpls)

    def read(self, bgr: np.ndarray) -> List[Dict[str, Any]]:
        if not self.ok or bgr is None:
            return []
        small, scale = _resize_max(bgr, 1280)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

        inv = cv2.GaussianBlur(255 - gray, (3, 3), 0)
        found: List[Dict[str, Any]] = []
        for kw, arrs in self._tmpls.items():
            best = None
            for t in arrs:
                if t.shape[0] >= inv.shape[0] or t.shape[1] >= inv.shape[1]:
                    continue
                try:
                    res = cv2.matchTemplate(inv, t, cv2.TM_CCOEFF_NORMED)
                except Exception:
                    continue
                _mn, mx, _ml, mloc = cv2.minMaxLoc(res)
                if mx >= 0.52 and (best is None or mx > best[1]):
                    best = (mloc, float(mx), t.shape, t)
            if best is not None:
                (x, y), sc, (th, tw), tmpl = best
                patch = small[max(0, y):y + th, max(0, x):x + tw]
                cn_ncc = self.bridge.verify(patch, tmpl) if self.bridge.ok else 0.0
                score = sc
                if cn_ncc > 0.25:
                    score = min(1.0, sc + 0.10 * cn_ncc)
                found.append({
                    "text": kw, "score": _clip(score),
                    "box": [[x / scale, y / scale], [(x + tw) / scale, (y + th) / scale]],
                    "backend": self.name, "cn_ncc": round(float(cn_ncc), 3),
                })
        found.sort(key=lambda z: -z["score"])

        out: List[Dict[str, Any]] = []
        for item in found:
            x0, y0 = item["box"][0]
            x1, y1 = item["box"][1]
            dup = False
            for prev in out:
                a0, b0 = prev["box"][0]
                a1, b1 = prev["box"][1]
                ix = max(0.0, min(x1, a1) - max(x0, a0))
                iy = max(0.0, min(y1, b1) - max(y0, b0))
                inter = ix * iy
                union = (x1 - x0) * (y1 - y0) + (a1 - a0) * (b1 - b0) - inter
                if union > 0 and inter / union > 0.35:
                    dup = True
                    break
            if not dup:
                out.append(item)
        return out

def normalize_ocr_text(s: str) -> str:
    s = (s or "").replace("（", "(").replace("）", ")")
    s = re.sub(r"\s+", "", s)
    return s.upper()

def _line_center_y(line: Mapping[str, Any]) -> float:
    box = line.get("box") or []
    ys = [p[1] for p in box if len(p) >= 2] or [0.0]
    return float(sum(ys) / len(ys))

def _line_height(line: Mapping[str, Any]) -> float:
    box = line.get("box") or []
    ys = [p[1] for p in box if len(p) >= 2] or [0.0]
    return max(1.0, float(max(ys) - min(ys)))

def match_ocr(lines: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """把 OCR 行匹配到部位候选。返回 ``{"scores": {...}, "matched": [...], ...}``。"""
    if not lines:
        return {"scores": {}, "matched": [], "text": "", "unsupported": [], "backend": ""}

    joined = normalize_ocr_text(" ".join(str(x.get("text", "")) for x in lines))
    scores: Dict[str, float] = {}
    matched: List[Dict[str, Any]] = []
    unsupported: List[str] = []
    used_lines: List[Mapping[str, Any]] = []

    code_re = re.compile(r"(?<![A-Z0-9])Z\s*[-]?\s*(\d{1,2})(?:\s*[-]?\s*(GL|CLK|IF|CPU|\d))?(?![0-9])")
    for m in code_re.finditer(joined):
        num = int(m.group(1))
        tail = (m.group(2) or "").upper()
        base = "z" + str(num)
        if base not in PART_INFO:
            hint = "Z%d" % num
            if hint in UNSUPPORTED_HINTS and hint not in unsupported:
                unsupported.append(hint)
            continue
        part = base
        if tail:
            if tail.isdigit() and (base + "-" + tail) in PART_INFO:
                part = base + "-" + tail
            elif tail in ("GL", "CLK", "IF", "CPU") and (base + "-" + tail) in PART_INFO:
                part = base + "-" + tail

        score = 0.88 + 0.08 * _line_conf_for_code(lines, joined, m.group(0))
        scores[part] = max(scores.get(part, 0.0), _clip(score, 0.0, 0.94))
        parent = (PART_INFO.get(part) or {}).get("parent")
        if parent:
            scores[parent] = max(scores.get(parent, 0.0), 0.74)
        matched.append({"part": part, "token": m.group(0), "kind": "code",
                        "score": round(_clip(score, 0.0, 0.94), 3)})

    for kw, part, base_score in OCR_NAME_RULES:
        if kw.upper() not in joined:
            continue

        score = base_score
        if len(kw) <= 2 and base_score < 0.7:
            score = min(score, 0.58)
        scores[part] = max(scores.get(part, 0.0), _clip(score, 0.0, 0.92))
        matched.append({"part": part, "token": kw, "kind": "name", "score": round(score, 3)})

    
    z20_cues = ("控制台", "电台", "天线控制", "发射机控制", "手摇", "航向", "俯仰", "收发转控")
    if any(c in joined for c in z20_cues) and "Z20" not in joined:
        if "Z31" not in joined and "配电箱" not in joined:
            if "z31" in scores:
                scores["z31"] = min(scores["z31"], 0.55)
        if "Z12" not in joined and "电源分机" not in joined:
            if "z12" in scores:
                scores["z12"] = min(scores["z12"], 0.45)
        scores["z20"] = max(scores.get("z20", 0.0), 0.62)

    if not any(x["kind"] == "code" for x in matched):
        for line in lines:
            tok = normalize_ocr_text(str(line.get("text", "")))
            m = NEAR_CODE_RE.match(tok)
            if not m:
                continue
            key = m.group(1)
            part = NEAR_CODE_MAP.get(key)
            if part and part in PART_INFO:
                conf = float(line.get("score", 0.5))
                score = 0.62 + 0.12 * conf
                scores[part] = max(scores.get(part, 0.0), _clip(score, 0.0, 0.78))
                matched.append({"part": part, "token": tok, "kind": "near_code",
                                "score": round(score, 3), "corrected_from": key})

    hit_tokens = {str(x["token"]) for x in matched}
    for line in lines:
        txt = normalize_ocr_text(str(line.get("text", "")))
        if not txt:
            continue
        if any(tok in txt or txt in tok for tok in hit_tokens if len(tok) >= 2):
            used_lines.append(line)
    if used_lines:
        used_lines.sort(key=_line_center_y)
        text = " ".join(str(x.get("text", "")) for x in used_lines)
    else:
        text = ""

    if matched and not any(re.search(r"[\u4e00-\u9fff]", str(x.get("text", ""))) for x in used_lines):
        for line in lines:
            txt = str(line.get("text", ""))
            if re.fullmatch(r"[\u4e00-\u9fff]{2,8}", txt.strip()):
                text = (text + " " + txt).strip()
                break
    if not text:
        text = " ".join(str(x.get("text", "")) for x in lines[:4])[:120]

    if not scores:
        return {"scores": {}, "matched": matched, "text": text,
                "unsupported": unsupported, "backend": str(lines[0].get("backend", ""))}

    top = sorted(scores.items(), key=lambda kv: -kv[1])[:4]
    return {"scores": dict(top), "matched": matched, "text": text[:160],
            "unsupported": unsupported, "backend": str(lines[0].get("backend", ""))}

def _line_conf_for_code(lines: Sequence[Mapping[str, Any]], joined: str, token: str) -> float:
    best = 0.6
    t = normalize_ocr_text(token)
    for line in lines:
        if t in normalize_ocr_text(str(line.get("text", ""))):
            best = max(best, float(line.get("score", 0.6)))
    return _clip(best)

def extract_appearance(bgr: np.ndarray) -> np.ndarray:
    """返回定长（FEATURE_DIM）外观特征；分块 L2 归一 + 块权重。"""
    if cv2 is None or bgr is None:
        return np.zeros(FEATURE_DIM, np.float32)
    img = cv2.resize(bgr, (320, 180), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0].astype(np.float32), hsv[:, :, 1].astype(np.float32), hsv[:, :, 2].astype(np.float32)

    blocks: List[np.ndarray] = []

    hist = cv2.calcHist([hsv], [0, 1, 2], None, [8, 3, 3], [0, 180, 0, 256, 0, 256]).astype(np.float32).ravel()
    blocks.append(_l2(hist))

    gh, gw = 4, 4
    cell_h, cell_w = img.shape[0] // gh, img.shape[1] // gw
    gv = []
    for gy in range(gh):
        for gx in range(gw):
            sl = (slice(gy * cell_h, (gy + 1) * cell_h), slice(gx * cell_w, (gx + 1) * cell_w))
            hh = np.deg2rad(h[sl] * 2.0)
            gv.extend([float(np.mean(np.cos(hh))), float(np.mean(np.sin(hh))),
                       float(np.mean(s[sl])) / 255.0, float(np.mean(v[sl])) / 255.0])
    blocks.append(_l2(np.asarray(gv, np.float32)))

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag, ang = cv2.cartToPolar(gx, gy, angleInDegrees=True)
    bins = ((ang / 45.0).astype(np.int32)) % 8
    ghist = []
    ch, cw = gray.shape[0] // 3, gray.shape[1] // 3
    for yy in range(3):
        for xx in range(3):
            sl = (slice(yy * ch, (yy + 1) * ch), slice(xx * cw, (xx + 1) * cw))
            ghist.extend(np.bincount(bins[sl].ravel(), weights=mag[sl].ravel(), minlength=8).tolist())
    blocks.append(_l2(np.asarray(ghist, np.float32)))

    edges = cv2.Canny(gray, 50, 120)
    e = []
    ch, cw = gray.shape[0] // 3, gray.shape[1] // 4
    for yy in range(3):
        for xx in range(4):
            sl = (slice(yy * ch, (yy + 1) * ch), slice(xx * cw, (xx + 1) * cw))
            e.append(float(np.mean(edges[sl] > 0)))
    blocks.append(_l2(np.asarray(e, np.float32)))

    led = _led_features(bgr)
    blocks.append(_l2(led))

    scr = _screen_features(hsv, v)
    blocks.append(_l2(scr))

    st = _stats_features(gray, hsv, edges)
    blocks.append(_l2(st))

    weighted = []
    for (name, dim, w), blk in zip(FEATURE_BLOCKS, blocks):
        if blk.size != dim:
            blk = np.resize(blk, dim)
        weighted.append(blk * math.sqrt(w))
    out = np.concatenate([_l2(x.astype(np.float32)) for x in weighted])
    return _l2(out).astype(np.float32)

def _l2(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, np.float32).ravel()
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        return v
    return v / n

def _led_features(bgr: np.ndarray) -> np.ndarray:
    small = cv2.resize(bgr, (480, 270), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    masks = {
        "red": (((h < 10) | (h > 170)) & (s > 90) & (v > 90)),
        "yellow": ((h >= 10) & (h < 35) & (s > 90) & (v > 90)),
        "green": ((h >= 35) & (h < 90) & (s > 80) & (v > 70)),
        "blue": ((h >= 90) & (h < 140) & (s > 80) & (v > 70)),
    }
    out: List[float] = []
    total = 0
    for _name, mask in masks.items():
        m = (mask.astype(np.uint8)) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n, _lbl, stats, cents = cv2.connectedComponentsWithStats(m, 8)
        areas, xs, ys = [], [], []
        for i in range(1, n):
            a = int(stats[i, cv2.CC_STAT_AREA])
            w, hh = int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT])
            if 8 <= a <= 2500 and w <= 90 and hh <= 90:
                areas.append(a)
                xs.append(float(cents[i][0]))
                ys.append(float(cents[i][1]))
        total += len(areas)
        cnt = min(len(areas), 10) / 10.0
        area = math.log1p(sum(areas)) / 10.0
        mx = float(np.mean(xs) / 480.0) if xs else 0.0
        my = float(np.mean(ys) / 270.0) if ys else 0.0
        spread = float(np.std(ys) / 270.0) if len(ys) >= 2 else 0.0
        out.extend([cnt, area, mx, my, spread])
    out.append(min(total, 16) / 16.0)

    bright = ((v > 200) & (s < 60)).astype(np.uint8) * 255
    n, _lbl, stats, _c = cv2.connectedComponentsWithStats(bright, 8)
    spots = sum(1 for i in range(1, n) if 6 <= int(stats[i, cv2.CC_STAT_AREA]) <= 800)
    out.append(min(spots, 20) / 20.0)
    return np.asarray(out[:22], np.float32)

def _screen_features(hsv: np.ndarray, v: np.ndarray) -> np.ndarray:
    h, s = hsv[:, :, 0], hsv[:, :, 1]
    out: List[float] = []
    masks = {
        "bright": ((v > 145) & (s < 70)),
        "green": ((h >= 35) & (h < 100) & (s > 55) & (v > 60)),
        "dark": (v < 75),
    }
    for _name, mask in masks.items():
        m = (mask.astype(np.uint8)) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        n, _lbl, stats, _c = cv2.connectedComponentsWithStats(m, 8)
        best = 0
        bw = bh = 0
        cx = cy = 0.0
        for i in range(1, n):
            a = int(stats[i, cv2.CC_STAT_AREA])
            if a > best:
                best = a
                bw, bh = int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT])
                cx, cy = float(stats[i, cv2.CC_STAT_LEFT] + bw / 2), float(stats[i, cv2.CC_STAT_TOP] + bh / 2)
        area_frac = best / float(v.size)
        aspect = (bw / float(bh)) if bh else 0.0
        out.extend([min(area_frac, 1.0), min(aspect, 5.0) / 5.0, cx / 320.0, cy / 180.0])

    out.append(float(np.mean(v > 200)))
    out.append(float(np.mean(v < 60)))
    return np.asarray(out[:8], np.float32)

def _stats_features(gray: np.ndarray, hsv: np.ndarray, edges: np.ndarray) -> np.ndarray:
    g = gray.astype(np.float32).ravel()
    p = np.percentile(g, [10, 50, 90])
    lap = cv2.Laplacian(gray, cv2.CV_32F)
    hist = np.histogram(gray, bins=32, range=(0, 256))[0].astype(np.float32)
    prob = hist / max(1.0, float(hist.sum()))
    ent = float(-(prob * np.log2(prob + 1e-9)).sum())

    col = float(np.std(hsv[:, :, 1].astype(np.float32) * hsv[:, :, 2].astype(np.float32) / 255.0))
    return np.asarray([
        float(np.mean(g)) / 255.0, float(np.std(g)) / 128.0,
        float(p[0]) / 255.0, float(p[1]) / 255.0, float(p[2]) / 255.0,
        math.log1p(float(np.var(lap))) / 12.0,
        ent / 5.0, float(np.mean(hsv[:, :, 1])) / 255.0,
        col / 128.0, float(np.mean(edges > 0)),
    ], np.float32)

class AppearanceBackend:
    """读 ``part_features.json``，余弦相似度匹配。"""

    def __init__(self, features_path: str = ""):
        self.path = features_path or FEATURES_JSON
        self.data: Dict[str, Any] = {}
        self.parts: Dict[str, List[np.ndarray]] = {}
        self.unknown: List[np.ndarray] = []
        self.error = ""
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
            if int(self.data.get("dim", -1)) != FEATURE_DIM:
                self.error = "feature dim 不匹配：json=%s code=%s" % (self.data.get("dim"), FEATURE_DIM)
                return
            for part, info in (self.data.get("parts") or {}).items():
                arrs = []
                for smp in info.get("samples") or []:
                    f = smp.get("feature") or []
                    if len(f) == FEATURE_DIM:
                        arrs.append(np.asarray(f, np.float32))
                if arrs:
                    self.parts[part] = arrs
            for smp in (self.data.get("unknown") or {}).get("samples") or []:
                f = smp.get("feature") or []
                if len(f) == FEATURE_DIM:
                    self.unknown.append(np.asarray(f, np.float32))
        except FileNotFoundError:
            self.error = "缺少 %s（先用 --build-features 生成）" % os.path.basename(self.path)
        except Exception as e:  
            self.error = "%s: %s" % (type(e).__name__, e)

    @property
    def ok(self) -> bool:
        return bool(self.parts)

    def match(self, bgr: np.ndarray, top_k: int = 5) -> Dict[str, Any]:
        if not self.ok or bgr is None:
            return {"scores": {}, "top": [], "best": "", "best_score": 0.0, "similarity": 0.0}
        q = extract_appearance(bgr)
        sims: Dict[str, float] = {}
        for part, arrs in self.parts.items():
            dots = [float(np.dot(q, a)) for a in arrs]

            sim = 0.72 * max(dots) + 0.28 * float(np.mean(dots))
            if len(arrs) == 1:
                sim -= 0.02
            sims[part] = sim
        order = sorted(sims.items(), key=lambda kv: -kv[1])
        unknown_sim = max([float(np.dot(q, a)) for a in self.unknown] or [-1.0])
        best_sim = order[0][1] if order else -1.0
        ood = bool(self.unknown) and (unknown_sim >= best_sim - 0.015)
        top: List[Dict[str, Any]] = []
        for p, sim in order[:top_k]:
            score = 0.50 + 0.30 * _clip((sim - 0.30) / 0.60, 0.0, 1.0)
            if p == order[0][0]:
                margin = float(order[0][1] - (order[1][1] if len(order) > 1 else 0.0))
                score += min(0.03, max(0.0, margin) * 0.20)
            top.append({"part": p, "score": round(_clip(score, 0.0, 0.80), 3),
                        "similarity": round(sim, 4)})
        if ood:
            for x in top:
                x["score"] = round(max(0.0, x["score"] - 0.06), 3)
        best = top[0] if top else {"part": "", "score": 0.0, "similarity": 0.0}
        return {"scores": {x["part"]: x["score"] for x in top}, "top": top,
                "best": best.get("part", ""), "best_score": best.get("score", 0.0),
                "similarity": best.get("similarity", 0.0),
                "unknown_similarity": round(unknown_sim, 4), "ood": ood}

def flow_no_index(flow_no: Any) -> Optional[int]:
    """SOP flow_no 容错解析：``'9(7-I)'`` / ``'16（10-II）'`` / ``9`` → 9/16/9；非法 → None。

    ★ 2026-10-21 修复（否定性报告 A2-10 / P1-2）：``steps.json`` 的 flow_no 带括号
      （``9(7-I)``），旧代码 ``int(flow_no)`` 直接抛
      ``ValueError: invalid literal for int() with base 10``，导致部位识别恒"未识别"。
      这里统一取前导数字（与 ``qa_flow._flow_index`` 同一口径），不再抛异常。
    """
    if flow_no is None or isinstance(flow_no, bool):
        return None
    try:
        return int(flow_no)
    except (TypeError, ValueError):
        pass
    m = re.match(r"\s*(\d+)", str(flow_no))
    return int(m.group(1)) if m else None

def route_from_flow(flow_no: Optional[int], route: str = "") -> str:
    if route:
        return str(route).strip().upper()[:4]
    if flow_no is None:
        return ""
    n = flow_no_index(flow_no)
    if n is None:
        return ""
    if 1 <= n <= 27:
        return "I"
    if n >= 29:
        return "II"
    return ""          

class ContextPrior:
    """flow→部位先验 + 上一次识别的时间连续性。"""

    def __init__(self, sop_csv: str = SOP_CSV):
        self.sop_csv = sop_csv
        self.flow_parts: Dict[int, Dict[str, float]] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.isfile(self.sop_csv):
            return
        try:
            with open(self.sop_csv, encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
        except Exception:
            return
        for r in rows:
            fn = flow_no_index(str(r.get("flow_no", "")).strip())
            if fn is None:
                continue
            text = "%s %s" % (r.get("flow_name", ""), r.get("check_item", ""))
            for m in re.finditer(r"Z\s*[-]?\s*(\d{1,2})(?:\s*[-]?\s*(GL|CLK|IF|CPU|\d))?", text.upper()):
                num = int(m.group(1))
                tail = (m.group(2) or "").upper()
                part = "z" + str(num)
                if tail:
                    cand = part + "-" + tail
                    if cand in PART_INFO:
                        part = cand
                if part in PART_INFO:
                    self.flow_parts.setdefault(fn, {})[part] = self.flow_parts.setdefault(fn, {}).get(part, 0.0) + 1.0

    def score(self, part: str, flow_no: Optional[int] = None, prior_part: str = "",
              prior_ts: Optional[float] = None, now: Optional[float] = None) -> Tuple[float, str]:
        s, src = 0.0, ""
        fn = flow_no_index(flow_no)
        if fn is not None and fn in self.flow_parts:
            cnt = self.flow_parts[fn]
            if cnt:
                total = sum(cnt.values())
                if part in cnt:
                    s = 0.40 * (cnt[part] / total) ** 0.4
                    src = "flow %s" % flow_no
        prior = _norm_part(prior_part)
        if prior and prior == part:
            t = now if now is not None else time.time()
            dt = max(0.0, t - float(prior_ts)) if prior_ts else 0.0
            decay = math.exp(-dt / 120.0) if prior_ts else 1.0
            sc = 0.40 * decay
            if sc > s:
                s, src = sc, "上一次识别 %s" % prior
        return _clip(s, 0.0, 0.4), src

def _fuse_candidates(marker: Optional[Mapping[str, Any]], ocr: Optional[Mapping[str, Any]],
                     app: Optional[Mapping[str, Any]], ctx_scores: Mapping[str, float],
                     top_k: int = 5) -> List[Dict[str, Any]]:
    all_parts: set = set()
    if marker and marker.get("part"):
        all_parts.add(str(marker["part"]))
    for block in (ocr, app, {"scores": ctx_scores}):
        if not block:
            continue
        all_parts.update((block.get("scores") or {}).keys())
    out: List[Dict[str, Any]] = []
    for part in all_parts:
        vals: List[Tuple[str, float]] = []
        if marker and marker.get("part") == part:
            vals.append(("marker", float(marker.get("score", 0.0))))
        if ocr and part in (ocr.get("scores") or {}):

            
            _ocr_max = max((ocr.get("scores") or {0.0: 0.0}).values() or [0.0])
            if _ocr_max >= 0.60:
                vals.append(("ocr", float(ocr["scores"][part])))
        if app and part in (app.get("scores") or {}):
            vals.append(("appearance", float(app["scores"][part])))
        if part in ctx_scores:
            vals.append(("context", float(ctx_scores[part])))
        if not vals:
            continue
        num = sum(MODALITY_WEIGHTS[m] * v for m, v in vals)
        den = sum(MODALITY_WEIGHTS[m] for m, _v in vals)
        score = num / den if den else 0.0
        strong = sum(1 for _m, v in vals if v >= 0.70)
        if strong >= 2:
            score += 0.03 * (strong - 1)

        if ocr and app and ocr.get("scores") and app.get("scores"):
            ocr_top = max(ocr["scores"].items(), key=lambda kv: kv[1])[0]
            app_top = max(app["scores"].items(), key=lambda kv: kv[1])[0]
            if part == ocr_top == app_top:
                score += 0.05
            elif part in (ocr_top, app_top) and ocr_top != app_top:
                score -= 0.04
        if marker:
            if part == marker.get("part"):
                score = max(score, 0.95)
            else:
                score *= 0.45
        score = _clip(score, 0.0, 0.98)
        out.append({"part": part, "score": round(score, 4),
                    "sources": [m for m, _v in vals]})
    out.sort(key=lambda z: (-z["score"], z["part"]))
    return out[:max(1, top_k)]

def _confidence_decision(cands: Sequence[Mapping[str, Any]], marker: Optional[Mapping[str, Any]],
                         ocr: Optional[Mapping[str, Any]], app: Optional[Mapping[str, Any]],
                         ctx_best: float, unsupported: Sequence[str]) -> Tuple[bool, List[str], str]:
    if not cands:
        return True, ["没有任何模态给出候选（无标记/无 OCR/无外观库）"], "未识别"
    top = cands[0]
    second = cands[1]["score"] if len(cands) > 1 else 0.0
    margin = float(top["score"]) - float(second)
    reasons: List[str] = []
    if top["score"] < 0.62:
        reasons.append("最高置信 %.2f < 0.62" % top["score"])
    if margin < 0.10:
        reasons.append("前二名差距 %.2f < 0.10" % margin)
    if not marker and not ocr:
        reasons.append("无标记、无 OCR（只剩外观/上下文）")
    if unsupported:
        reasons.append("检测到清单外部件：%s" % ",".join(unsupported))

    if ocr and app and ocr.get("scores") and app.get("scores"):
        ocr_top = max(ocr["scores"].items(), key=lambda kv: kv[1])[0]
        app_top = max(app["scores"].items(), key=lambda kv: kv[1])[0]
        if ocr_top != app_top and ocr["scores"][ocr_top] >= 0.80 and app["scores"][app_top] >= 0.62:
            reasons.append("OCR(%s) 与外观(%s) 冲突" % (ocr_top, app_top))
    if app and app.get("ood"):
        reasons.append("外观更像 unknown/清单外部件（unknown_sim=%.2f）" % float(app.get("unknown_similarity", 0.0)))
    if app and float(app.get("best_score", 0.0)) < 0.58 and not marker and not ocr:
        reasons.append("外观相似度不足")
    if top["score"] >= 0.90 and margin >= 0.08 and (marker or ocr):
        return False, [], "高置信（≥0.90）"
    if top["score"] >= 0.78 and margin >= 0.10 and not reasons:
        return False, [], "中高置信（≥0.78）"
    if top["score"] >= 0.68 and margin >= 0.14 and (marker or (ocr and app and ocr["scores"].get(top["part"], 0) >= 0.80)):
        return False, [], "多模态一致"
    if not reasons:
        reasons.append("置信不足（%.2f）或需要人工复核" % top["score"])
    return True, reasons, "待确认"

def _alias_candidates(cands: Sequence[Mapping[str, Any]], route: str = "") -> List[Dict[str, Any]]:
    """候选部位归一到母模块（2026-10-29 二路码口径），同名合并取最高分、保持原顺序。"""
    fn = _alias_mod()[0]
    out: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for c in cands or []:
        raw = str(c.get("part") or "")
        p, _r = (fn(raw, route) if fn is not None else (raw, route))
        if not p:
            continue
        score = float(c.get("score") or 0.0)
        if p not in out:
            out[p] = {"part": p, "name": part_name(p), "score": score,
                      "sources": list(c.get("sources") or [])}
            order.append(p)
            continue
        if score > out[p]["score"]:
            out[p]["score"] = score
        for s in (c.get("sources") or []):
            if s not in out[p]["sources"]:
                out[p]["sources"].append(s)
    return [out[p] for p in order]

class PartRecognizer:
    """多模态部位识别器。一次初始化，可反复调用 ``recognize()``。"""

    def __init__(self, features_path: str = "", markers_json: str = "",
                 ocr_backend: str = "auto", verbose: bool = False):
        self.verbose = verbose
        self.marker = MarkerBackend(markers_json or MARKERS_V2_JSON, verbose=verbose)
        self.appearance = AppearanceBackend(features_path or FEATURES_JSON)
        self.context = ContextPrior()
        self.ocr_backend_name = ocr_backend
        self._ocr: Any = None
        self._ocr_error = ""
        self._init_ocr(ocr_backend)

    def _init_ocr(self, mode: str) -> None:
        mode = (mode or "auto").lower()
        if mode in ("auto", "rapidocr"):
            backend = RapidOcrBackend()
            if backend.ok:
                self._ocr = backend
                self.ocr_backend_name = backend.name
                return
            self._ocr_error = getattr(backend, "error", "rapidocr 不可用")
            if mode == "rapidocr":
                self._ocr = None
                return
        if mode in ("auto", "template", "template_ncc"):
            backend = TemplateOcrBackend()
            if backend.ok:
                self._ocr = backend
                self.ocr_backend_name = backend.name
            else:
                self._ocr_error = backend.error
                self.ocr_backend_name = "none"

    def recognize(self, image: Any, flow_no: Optional[int] = None, route: str = "",
                  prior_part: str = "", prior_ts: Optional[float] = None,
                  use_marker: bool = True, use_ocr: bool = True,
                  use_appearance: bool = True, top_k: int = 5,
                  marker_rot_search: bool = False,
                  now: Optional[float] = None) -> Dict[str, Any]:
        t0 = time.time()
        bgr = load_bgr(image)
        now_ts = float(now) if now is not None else time.time()
        if bgr is None:
            return self._empty_result("读不到图像", route=route_from_flow(flow_no, route), top_k=top_k)

        marker = self.marker.detect(bgr, rot_search=marker_rot_search) if use_marker else None
        lines: List[Dict[str, Any]] = []
        ocr_pack: Optional[Dict[str, Any]] = None
        if use_ocr and self._ocr is not None:
            try:

                lines = self._ocr.read(bgr.copy())
            except Exception as e:  
                self._ocr_error = "%s: %s" % (type(e).__name__, e)
                lines = []
            ocr_pack = match_ocr(lines)
        app = self.appearance.match(bgr, top_k=top_k) if use_appearance else None

        candidate_parts = set()
        if marker:
            candidate_parts.add(marker["part"])
        if ocr_pack:
            candidate_parts.update((ocr_pack.get("scores") or {}).keys())
        if app:
            candidate_parts.update((app.get("scores") or {}).keys())

        _fn = flow_no_index(flow_no)
        if _fn is not None and _fn in self.context.flow_parts:
            candidate_parts.update(self.context.flow_parts[_fn].keys())
        ctx_scores: Dict[str, float] = {}
        ctx_src: Dict[str, str] = {}
        for p in candidate_parts:
            sc, src = self.context.score(p, flow_no, prior_part, prior_ts, now_ts)
            if sc > 0:
                ctx_scores[p] = sc
                ctx_src[p] = src

        cands = _fuse_candidates(marker, ocr_pack, app, ctx_scores, top_k=top_k)
        unsupported = list((ocr_pack or {}).get("unsupported") or [])
        need, reasons, decision = _confidence_decision(cands, marker, ocr_pack, app,
                                                       max(ctx_scores.values()) if ctx_scores else 0.0,
                                                       unsupported)
        top = cands[0] if cands else {"part": "", "score": 0.0}
        part_raw = str(top.get("part", ""))
        route_out = route_from_flow(flow_no, route)

        
        ocr_for_top = None
        if ocr_pack and (ocr_pack.get("scores") or {}):
            sc = float(ocr_pack["scores"].get(part_raw, 0.0))
            if sc > 0:
                ocr_for_top = {
                    "text": ocr_pack.get("text", ""),
                    "score": round(sc, 3),
                    "backend": ocr_pack.get("backend", self.ocr_backend_name),
                    "matched": [x for x in (ocr_pack.get("matched") or [])
                                if x.get("part") == part_raw],
                }
        app_for_top = None
        if app and app.get("scores"):
            sc = float(app["scores"].get(part_raw, 0.0))
            if sc > 0:
                app_for_top = {"best": app.get("best", ""), "score": round(sc, 3),
                               "similarity": round(float(app.get("similarity", 0.0)), 4)
                               if app.get("best") == part_raw else None,
                               "unknown_similarity": round(float(app.get("unknown_similarity", 0.0)), 4),
                               "ood": bool(app.get("ood")),
                               "top": app.get("top", [])}

        

        _norm = _alias_mod()[0]
        part, legacy_part, route_locked = part_raw, "", False
        if _norm is not None and part_raw:
            part, route_out = _norm(part_raw, route_out)
            if part != part_raw:
                legacy_part = part_raw
                route_locked = route_out in ("I", "II")
        name = part_name(part)

        question = ""
        if part:
            question = "请确认这是 %s 吗？" % part_display(part, route_out)
        else:
            question = "未能确定部位：请把镜头对准面板铭牌/二维码，或手动选择部位。"
        if unsupported and need:
            question = "画面里出现清单外部件（%s）。请确认当前要判定的 18 个部位之一。" % ",".join(unsupported)

        result = {
            "schema": SCHEMA,
            "part": part,
            "name": name,
            "part_display": part_display(part, route_out) if part else "",
            "level": (PART_INFO.get(part) or {}).get("level", ""),
            "confidence": round(float(top.get("score", 0.0)), 4),
            "route": route_out,

            
            "legacy_part": legacy_part,
            "route_locked": route_locked,
            "route_hint": "I→II" if flow_no_index(flow_no) == 28 else "",
            "modality_breakdown": {
                "marker": marker,
                "ocr": ocr_for_top,
                "appearance": app_for_top,
                "context": round(float(ctx_scores.get(part_raw, 0.0)), 3) if part_raw else 0.0,
            },
            "candidates": _alias_candidates(cands, route_out),
            "need_confirm": bool(need),
            "decision": decision,
            "reasons": reasons,
            "question": question,
            "unsupported_parts": unsupported,
            "context_detail": {"flow_no": flow_no, "route": route_out,
                               "prior_part": prior_part,
                               "ctx_source": ctx_src.get(part_raw, "") if part_raw else ""},
            "meta": {
                "ocr_backend": self.ocr_backend_name,
                "ocr_error": self._ocr_error,
                "marker_error": self.marker.error,
                "appearance_error": self.appearance.error,
                "appearance_library": os.path.basename(self.appearance.path),
                "elapsed_ms": int((time.time() - t0) * 1000),
                "ts": now_iso(),
            },
        }
        return result

    def _empty_result(self, why: str, route: str = "", top_k: int = 5) -> Dict[str, Any]:
        return {
            "schema": SCHEMA, "part": "", "name": "", "part_display": "", "level": "",
            "confidence": 0.0, "route": route, "route_hint": "",
            "modality_breakdown": {"marker": None, "ocr": None, "appearance": None, "context": 0.0},
            "candidates": [], "need_confirm": True,
            "decision": "未识别", "reasons": [why],
            "question": "未能读取图像：请重拍或检查相机。",
            "unsupported_parts": [],
            "context_detail": {}, "meta": {"ts": now_iso()},
        }

    def recognize_batch(self, images: Iterable[Any], **kw: Any) -> List[Dict[str, Any]]:
        out = []
        for i, im in enumerate(images):
            if i and "prior_part" not in kw and out and out[-1].get("part"):
                kw = dict(kw)
                kw["prior_part"] = out[-1]["part"]
                kw["prior_ts"] = time.time()
            out.append(self.recognize(im, **kw))
        return out

MODULE_MATCH_KEYS = {
    "z11-1": ["Z11-1", "频综"],
    "z11-3": ["Z11-3", "固态功放"],
    "z11-4": ["Z11-4", "接收前端"],
    "z11-5": ["Z11-5", "近程增益"],
    "z12-GL": ["GL1", "GL2", "GL3"],
    "z14-CLK": ["Z14-1", "时钟"],
    "z15-IF": ["Z15-IF", "接口板"],
    "z15-CPU": ["Z15-CPU", "CPU板"],
}

def criteria_for(part: str, route: str = "") -> List[Dict[str, Any]]:
    """取该部位在 ``判据库_故障.csv`` 里的判据行（只读，不做判定）。

    只看**故障归属字段**（cabinet / sub_unit / module），不看 ``step_name``：
    step_name 里出现 “Z20（控制台）-[发射机控制]” 的行，故障归属是 z11/z12/z18，
    不是 z20；把 step_name 算进来会让“部位↔判据”严重串味。

    ★ 2026-10-29 二路码口径：旧 id（z11-1/Z12-GL/z12-clk/Z14-CLK/Z15-IF）先归一成
      母模块（判据行按**母模块**归属取；用户口径：规则/问答都用母模块）。这里**只取
      part**、不引入 alias 的 route=II —— 否则会把知识库里只有 I 路标注的母模块行
      全部滤掉，导致"Z11-1 查不到判据行"。
    """
    p = _norm_part(part)
    _fn = _alias_mod()[0]
    if _fn is not None:
        p = _fn(p, "")[0]
    if p not in PART_INFO:
        return []
    info = PART_INFO[p]
    is_module = info.get("level") == "module"

    sub_keys = {
        "z4": [], "z5": [], "z31": ["配电箱"],
        "z16": ["指示分机", "Z16"], "z20": ["Z20"],
    }.get(p, [p.upper()])
    cab_keys = {"z4": ["Z4"], "z5": ["Z5"], "z31": ["Z31"]}.get(p, [])
    mod_keys = MODULE_MATCH_KEYS.get(p, [p.upper()]) if is_module else []

    rows: List[Dict[str, Any]] = []
    try:
        with open(FAULT_CSV, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                sub = str(r.get("sub_unit", "")).upper().replace(" ", "")
                cab = str(r.get("cabinet", "")).upper().replace(" ", "")
                mod = str(r.get("module", "")).upper().replace(" ", "")
                scope = ""
                if mod_keys and any(k.upper().replace(" ", "") in mod for k in mod_keys):
                    scope = "module"
                elif sub_keys and any(k.upper().replace(" ", "") in sub for k in sub_keys):
                    scope = "sub_unit"
                elif cab_keys and any(k.upper().replace(" ", "") in cab for k in cab_keys):
                    scope = "cabinet"
                if not scope:
                    continue
                rows.append({
                    "cabinet": r.get("cabinet", ""), "sub_unit": r.get("sub_unit", ""),
                    "module": r.get("module", ""), "step_name": r.get("step_name", ""),
                    "phenomenon": r.get("phenomenon", ""), "field": r.get("field", ""),
                    "abnormal_value": r.get("abnormal_value", ""),
                    "feature_id": r.get("feature_id", ""), "match_scope": scope,
                })
    except Exception:
        return []
    if route:
        rt = route.strip().upper()

        keep = []
        for r in rows:
            sub = r["sub_unit"].upper().replace("（", "(").replace("）", ")")
            marks = re.findall(r"\((I{1,2})[\u8def]?\)", sub)
            if not marks or rt in marks:
                keep.append(r)
        rows = keep
    return rows

def to_evidence(rec: Mapping[str, Any], field: str, value: str, evidence_text: str,
                confidence: Optional[float] = None, modality: str = "vision",
                ts: Optional[str] = None) -> Dict[str, Any]:
    """把一次部位识别结果变成 ``evidence/v1`` 的一条证据（供 fusion/fault_grader）。"""
    part = str(rec.get("part", ""))
    conf = float(rec.get("confidence", 0.0)) if confidence is None else float(confidence)
    return {
        "part": part,
        "route": str(rec.get("route", "") or ""),
        "modality": modality,
        "field": field,
        "value": value,
        "confidence": round(_clip(conf), 3),
        "evidence": evidence_text,
        "ts": ts or now_iso(),
        "source": "part_recognizer.to_evidence",
        "meta": {"recognition_confidence": rec.get("confidence"),
                 "need_confirm": rec.get("need_confirm"),
                 "modalities": [m for m in ("marker", "ocr", "appearance", "context")
                                if rec.get("modality_breakdown", {}).get(m)]},
    }

def apply_to_evidence(rec: Mapping[str, Any], evidence: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """给空 ``part``/``route`` 的证据补上本次识别结果（不覆盖已有值）。"""
    out: List[Dict[str, Any]] = []
    for ev in evidence:
        e = dict(ev)
        if not str(e.get("part", "")).strip() and rec.get("part"):
            e["part"] = rec["part"]
        if not str(e.get("route", "")).strip() and rec.get("route"):
            e["route"] = rec["route"]
        meta = dict(e.get("meta") or {})
        meta.setdefault("part_from", "part_recognizer")
        meta.setdefault("part_confidence", rec.get("confidence"))
        e["meta"] = meta
        out.append(e)
    return out

def build_feature_library(items: Sequence[Mapping[str, Any]], out_path: str = FEATURES_JSON,
                          source: str = "", holdout: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    """用人工打标的真图建 ``part_features.json``。

    ``items`` 每项：``{"image": 路径, "part": "z11", "label_source": "..."}``。
    ``part`` 为 ``unknown`` 的条目会被跳过（绝不瞎标）。
    """
    parts: Dict[str, Dict[str, Any]] = {}
    unknown_samples: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []
    for it in items:
        part = _norm_part(it.get("part"))
        path = str(it.get("image", ""))
        if part == "unknown":
            bgr = load_bgr(path)
            if bgr is None:
                skipped.append({"image": os.path.basename(path), "why": "读不到图"})
                continue
            unknown_samples.append({
                "image": os.path.basename(path),
                "label_source": str(it.get("label_source", "unknown")),
                "feature": [round(float(x), 6) for x in extract_appearance(bgr).astype(np.float32)],
            })
            continue
        if part not in PART_INFO:
            skipped.append({"image": os.path.basename(path), "why": "part=%s 不在 18 清单" % it.get("part")})
            continue
        bgr = load_bgr(path)
        if bgr is None:
            skipped.append({"image": os.path.basename(path), "why": "读不到图"})
            continue
        feat = extract_appearance(bgr).astype(np.float32)
        entry = {
            "image": os.path.basename(path),
            "label_source": str(it.get("label_source", "")),
            "feature": [round(float(x), 6) for x in feat],
        }
        parts.setdefault(part, {"name": part_name(part), "level": (PART_INFO.get(part) or {}).get("level", ""),
                                "samples": []})["samples"].append(entry)
    for part, info in parts.items():
        arrs = [np.asarray(s["feature"], np.float32) for s in info["samples"]]
        mean = np.mean(arrs, axis=0) if arrs else np.zeros(FEATURE_DIM, np.float32)
        info["n"] = len(arrs)
        info["mean"] = [round(float(x), 6) for x in _l2(mean)]
    data = {
        "schema": FEATURE_SCHEMA,
        "created": now_iso(),
        "source": source or "119 张现场真图（人工按可见丝印/标记打标；unknown 不入库）",
        "feature_version": "appearance/1.0",
        "dim": FEATURE_DIM,
        "blocks": [{"name": n, "dim": d, "weight": w} for n, d, w in FEATURE_BLOCKS],
        "labeling_policy": "只收能看清部位丝印/标记的照片；没把握标 unknown；unknown 不入库",
        "counts": {p: int(v["n"]) for p, v in parts.items()},
        "total_samples": sum(int(v["n"]) for v in parts.values()),
        "parts": parts,
        "unknown": {"n": len(unknown_samples), "samples": unknown_samples,
                    "note": "只用于 OOD/拒识校准，不会成为候选部位"},
        "skipped": skipped,
    }
    if holdout:
        data["holdout"] = [{"image": os.path.basename(str(h.get("image", ""))), "part": _norm_part(h.get("part"))}
                           for h in holdout]
        data["holdout_note"] = "这些真图**不参与建库**，仅用于 test_part_recognizer.py 的留出测试"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return {"out": out_path, "total": data["total_samples"], "counts": data["counts"],
            "skipped": skipped[:20]}

_DEFAULT: Optional[PartRecognizer] = None

def recognize(image: Any, **kw: Any) -> Dict[str, Any]:
    """模块级便捷入口：首次调用自动建 ``PartRecognizer``。"""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = PartRecognizer(features_path=kw.pop("features_path", ""),
                                  markers_json=kw.pop("markers_json", ""),
                                  ocr_backend=kw.pop("ocr_backend", "auto"))
    return _DEFAULT.recognize(image, **kw)

def _print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="多模态部位识别（标记/OCR/外观/上下文）")
    ap.add_argument("-i", "--image", default="", help="单张图片")
    ap.add_argument("--features", default="", help="part_features.json")
    ap.add_argument("--markers", default="", help="markers_v2.json")
    ap.add_argument("--flow", type=int, default=None, help="当前 SOP flow_no")
    ap.add_argument("--route", default="", help="I / II / 空")
    ap.add_argument("--prior", default="", help="上一次识别部位")
    ap.add_argument("--prior-age", type=float, default=0.0, help="上一次识别距今秒数")
    ap.add_argument("--ocr-backend", default="auto", choices=["auto", "rapidocr", "template", "none"])
    ap.add_argument("--marker-rot", action="store_true", help="无标记时做 ±4/±7° 旋转重试（单张照片用，较慢）")
    ap.add_argument("--no-marker", action="store_true")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--no-appearance", action="store_true")
    ap.add_argument("--json", default="", help="结果写到这个 JSON")
    ap.add_argument("--build-features", default="", help="labels.json（[{'image','part','label_source'}]）")
    ap.add_argument("--out", default=FEATURES_JSON)
    ap.add_argument("--criteria", default="", help="打印该部位的判据行")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)

    if a.build_features:
        with open(a.build_features, encoding="utf-8") as f:
            payload = json.load(f)
        items = payload.get("items") if isinstance(payload, dict) else payload
        holdout = payload.get("holdout") if isinstance(payload, dict) else None
        res = build_feature_library(items or [], a.out, source=(payload.get("source", "") if isinstance(payload, dict) else ""),
                                    holdout=holdout)
        _print_json(res)
        return 0

    if a.criteria:
        rows = criteria_for(a.criteria, a.route)
        print("部位 %s 的判据行：%d" % (part_display(_norm_part(a.criteria)), len(rows)))
        for r in rows[:40]:
            print("- %s | %s | %s | %s" % (r["sub_unit"], r["module"], r["field"], r["phenomenon"]))
        return 0 if rows else 2

    rec = PartRecognizer(features_path=a.features, markers_json=a.markers, ocr_backend=a.ocr_backend)
    if a.self_test:
        _print_json({"marker": {"ok": rec.marker.ok, "error": rec.marker.error},
                     "ocr": {"backend": rec.ocr_backend_name, "error": rec._ocr_error},
                     "appearance": {"ok": rec.appearance.ok, "error": rec.appearance.error,
                                    "parts": sorted(rec.appearance.parts.keys())},
                     "context_flows": len(rec.context.flow_parts)})
        return 0

    if not a.image:
        ap.print_help()
        return 2
    kw: Dict[str, Any] = {
        "flow_no": a.flow, "route": a.route, "prior_part": a.prior,
        "use_marker": not a.no_marker, "use_ocr": (not a.no_ocr) and a.ocr_backend != "none",
        "use_appearance": not a.no_appearance, "marker_rot_search": a.marker_rot,
    }
    if a.prior and a.prior_age:
        kw["prior_ts"] = time.time() - float(a.prior_age)
    res = rec.recognize(a.image, **kw)
    _print_json(res)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
    return 0 if not res.get("need_confirm") else 4

if __name__ == "__main__":
    raise SystemExit(main())
