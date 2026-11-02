#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""marker_id.py —— **读 4×4 标记 → 锁定模块身份**（复用 fpga-roi-accel 的 `markerdet.markerdet`）。

为什么用标记
------------
"这块板子对 LED 归属哪个部分不精准"的根治办法：**标记 = 模块身份（精确）**，标定 ROI = 灯位（精确），
两者合起来结论就能精确到"❌ 故障：`发射断` 红灯亮"。

归属优先级链（**绝不猜**）
--------------------------
1. **读到标记** → 模块身份 100% 确定 → 用该模块规则 + 该模块标定 ROI → 判每颗灯
2. 读不到标记 → 回退到**已标定 ROI**（`config/led_calib.json` 里有该部件）
3. 两者都没有 → **未判定**

`fpga-roi-accel` 踩出来的 3 个检测器参数坑（已按实际成像尺寸显式设置）
--------------------------------------------------------------------
* `min_side_px`：默认 14px 太松（A4 上中文字笔画会被当标记，实测误检 47 个）→ 默认取 **标记边长的一半**；
* `dark_win_frac`：默认 0.05 → 自适应窗口小于黑框厚度 → 填充率掉到下限以下、0 检出 → **小图用 0.25**；
* `max_side_px`：默认 `0.6×min(H,W)` → 紧贴裁剪的单张标记会被排除 → **显式传值**。

用法
----
    from soc_vision.marker_id import MarkerId
    mi = MarkerId()                       # 自动载入 markers_modules.json
    r = mi.detect(bgr)                    # -> {"label":"M6","marker_id":5,"score":0.93,"module":{...}}
"""

from __future__ import annotations

import itertools
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

try:
    import cv2
except Exception:                                                     
    cv2 = None

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "soc_vision", "_vendor"))

try:                                                                  
    from .module_route_alias import normalize_part_route as _normalize_part_route
except Exception:                                                     
    try:                                                              
        from module_route_alias import normalize_part_route as _normalize_part_route
    except Exception:                                                 
        def _normalize_part_route(part, route=""):                    
            """兜底（helper 缺失时原样返回，绝不猜）。"""
            return str(part or ""), str(route or "")

DEFAULT_JSON = os.path.join(HERE, "markers_modules.json")

RECT_MODULES = 8
RECT_PX = 320
RECT_CELL = RECT_PX // RECT_MODULES          
RECT_FRAME0 = RECT_CELL                      
RECT_FRAME1 = RECT_PX - RECT_CELL            

RULE_KEY_TO_PART = {
    "led_all_on:3": ["PS_KONG", "PS_WENYA"],                      
    "led_on:1": ["PS_GONGPIN", "ANT_START"],                      
    "led_exactly_one_of:2": ["ANT_DIR", "TX_CTRL"],               
    "led_green_all_on_red_all_off:3+2": ["TX_STATE"],             
    "screen_fields_ok:2": ["TEXT_SCREEN"],                        
    "seq_green_on+charge_red_on+voltage_in_tol": ["PD_BOARD"],    
}

RULE_TEXT_HINT = [
    ("三颗全亮", ["PS_KONG", "PS_WENYA"]),
    ("红灯亮=正常", ["PS_GONGPIN", "ANT_START"]),
    ("一亮一灭", ["ANT_DIR", "TX_CTRL"]),
    ("3 绿全亮", ["TX_STATE"]),
]

def _load_vendor():
    """载入 fpga-roi-accel 的 markerdet/marker（纯 numpy+cv2）。"""
    try:
        import markerdet  
        import marker     
        return markerdet, marker
    except Exception as e:                                            
        print("[marker] 载入 markerdet 失败: %s" % e, flush=True)
        return None, None

@dataclass
class MarkerHit:
    label: str = ""
    marker_id: int = -1
    score: float = 0.0
    cx: float = 0.0
    cy: float = 0.0
    side_px: float = 0.0
    theta: float = 0.0
    module: Dict[str, Any] = field(default_factory=dict)
    frames: int = 0
    breakdown: Dict[str, float] = field(default_factory=dict)
    rejected: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"label": self.label, "marker_id": self.marker_id, "score": round(self.score, 3),
                "rule_key": (self.module or {}).get("rule_key", ""),
                "instances": (self.module or {}).get("instances", []),
                "cx": round(self.cx, 1), "cy": round(self.cy, 1), "side_px": round(self.side_px, 1),
                "theta": round(self.theta, 1), "frames": self.frames,
                "name": (self.module or {}).get("name", "")}

class MarkerId:
    def __init__(self, json_path: str = "", min_side_px: int = 0, max_side_px: int = 0,
                 dark_win_frac: float = 0.25, max_hamming: int = 1, confirm_n: int = 3,
                 min_score: float = 0.80, max_side_frac: float = 0.50, verbose: bool = True,
                 min_total_px: float = 0.0, small_total_px: float = 0.0,
                 small_gain: float = 0.0):
        self.json_path = json_path or DEFAULT_JSON
        self.data: Dict[str, Any] = {}
        self.by_id: Dict[int, Dict[str, Any]] = {}
        self.marker: Any = None
        self.marker_names: Dict[int, str] = {}
        self.md, self.mk = _load_vendor()
        self._install_small_sampler()
        self.dark_win_frac = float(dark_win_frac)
        self.max_hamming = int(max_hamming)
        self.confirm_n = int(confirm_n)
        self.min_score = float(min_score)
        self.max_side_frac = float(max_side_frac)
        self.verbose = verbose

        

        

        
        self.min_total_px = float(min_total_px) if float(min_total_px or 0) > 0 else 18.0
        self.small_total_px = float(small_total_px) if float(small_total_px or 0) > 0 else 30.0
        self.small_gain = float(small_gain or 0.0)

        self.small_min_sep = 12.0
        self.small_min_quiet = 0.0
        self._user_min = int(min_side_px)
        self._user_max = int(max_side_px)
        self._streak: Dict[str, int] = {}
        self._prev: Optional[MarkerHit] = None
        self._hist: list = []            
        self._latch: Optional[MarkerHit] = None   
        self._latch_t = 0.0
        self.latch_sec = 5.0
        self.window_sec = 5.0
        self.progress = (0, 0)           
        self._last: Optional[MarkerHit] = None
        self._load()

    def _load(self) -> None:
        try:
            with open(self.json_path, encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception as e:                                        
            print("[marker][warn] 读不到 %s: %s" % (self.json_path, e), flush=True)
            return
        for label, m in (self.data.get("modules") or {}).items():
            mid = int(m.get("marker_id", -1))
            if mid >= 0:
                self.by_id[mid] = dict(m, label=label)
        if self.mk is not None:
            try:
                names = self.mk.build_dictionary(24, 4)               
                self.marker_names = {i: n for i, n in enumerate(names)} if isinstance(names[0], str) else {}
                self._codes = names
            except Exception as e:                                    
                print("[marker][warn] build_dictionary 失败: %s" % e, flush=True)
                self._codes = None
        else:
            self._codes = None
        if self.verbose:
            print("[marker] 载入 %d 个模块映射（%s）；码本=%s"
                  % (len(self.by_id), os.path.basename(self.json_path),
                     "有" if self._codes else "无"), flush=True)

    

    

    

    

    

    

    def _install_small_sampler(self) -> None:
        """★ 远距增强：小标记（s<4px/模块）的 4×4 读取改在**上采样 ROI** 上做。

        markerdet 的 readout 在 s≈2~3px 时一个数据格只有 2~3px，`sample_cell`
        取 1px 半径中值会把相邻格糊在一起 → 码字差 2 bit 就被 max_hamming=1 拒掉。
        2026-10-18 离屏实测（markers_v2 18 个）：18px 原生只认出 6/18，
        整帧 2× 上采样后 18/18；24px 原生 13/18、上采样 18/18。
        所以只替换"取样"这一步（检测/连通域/字典匹配一行不动），并且
        **s≥4px/模块（总边长≥32px）完全走原路径**，大标记行为零变化。
        """
        md = self.md
        if md is None or getattr(md, "_dsh_small_sampler", False):
            return
        orig = getattr(md, "sample_cell", None)
        if orig is None:
            return
        state = {"src": None, "key": None, "up": None, "gain": 1.0, "x0": 0, "y0": 0}

        def sample_small(gray, cx, cy, theta_deg, s, i, j, frac=0.30):
            if s >= 4.0:                                   
                return orig(gray, cx, cy, theta_deg, s, i, j, frac)
            key = (round(cx, 1), round(cy, 1), round(float(s), 2), round(float(theta_deg), 1))
            if state["src"] is not gray or state["key"] != key:
                gain = max(2.0, float(np.ceil(4.5 / max(float(s), 0.5))))
                gain = min(gain, 4.0)
                rad = 4.2 * float(s)
                H, W = gray.shape[:2]
                x0 = int(max(0, np.floor(cx - rad)))
                x1 = int(min(W, np.ceil(cx + rad) + 1))
                y0 = int(max(0, np.floor(cy - rad)))
                y1 = int(min(H, np.ceil(cy + rad) + 1))
                if (x1 - x0) < 4 or (y1 - y0) < 4:
                    return orig(gray, cx, cy, theta_deg, s, i, j, frac)
                up = MarkerId._resize_up(gray[y0:y1, x0:x1], gain)
                state.update(src=gray, key=key, up=up, gain=gain, x0=x0, y0=y0)
            g = state["gain"]
            x = (cx - state["x0"] + 0.5) * g - 0.5
            y = (cy - state["y0"] + 0.5) * g - 0.5
            return orig(state["up"], x, y, theta_deg, float(s) * g, i, j, frac)

        md.sample_cell = sample_small
        md._dsh_small_sampler = True

    @staticmethod
    def _rot_cw_rows(bits, n: int):
        """码字顺时针转 n×90°（与 ``_vendor/marker.py: rot90_bits`` 同约定）。

        ``rot90_bits(b, n) = np.rot90(b, -n%4)``，即顺时针 n 次；元素满足
        ``R[j][3-i] = b[i][j]``。检测器的 ``rot`` 就是这个 n：码字转 n 次后
        才与"沿 theta 采样出来的 4×4 格"对齐。
        """
        b = [[str(ch) for ch in str(row)] for row in (bits or [])]
        if len(b) != 4 or any(len(r) != 4 for r in b):
            return bits
        for _ in range(int(n) % 4):
            b = [[b[3 - v][u] for v in range(4)] for u in range(4)]
        return b

    @staticmethod
    def _apply_h(H: np.ndarray, xs: np.ndarray, ys: np.ndarray):
        """把单应 H 作用到坐标点（xs/ys 同形）。"""
        w = H[2, 0] * xs + H[2, 1] * ys + H[2, 2]
        w = np.where(np.abs(w) < 1e-9, 1e-9, w)
        return ((H[0, 0] * xs + H[0, 1] * ys + H[0, 2]) / w,
                (H[1, 0] * xs + H[1, 1] * ys + H[1, 2]) / w)

    @staticmethod
    def _bilinear(gray: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        """双线性插值采样（越界钳位）。"""
        h, w = gray.shape[:2]
        xs = np.clip(np.asarray(xs, np.float64), 0.0, max(0.0, w - 1.001))
        ys = np.clip(np.asarray(ys, np.float64), 0.0, max(0.0, h - 1.001))
        x0 = np.floor(xs).astype(np.int32)
        y0 = np.floor(ys).astype(np.int32)
        x1 = np.minimum(x0 + 1, w - 1)
        y1 = np.minimum(y0 + 1, h - 1)
        fx = xs - x0
        fy = ys - y0
        g = gray.astype(np.float64)
        top = g[y0, x0] * (1.0 - fx) + g[y0, x1] * fx
        bot = g[y1, x0] * (1.0 - fx) + g[y1, x1] * fx
        return top * (1.0 - fy) + bot * fy

    @staticmethod
    def _persp(src, dst) -> Optional[np.ndarray]:
        """4 点单应：src -> dst（优先 OpenCV，缺失时纯 numpy DLT）。"""
        src = np.asarray(src, np.float64).reshape(4, 2)
        dst = np.asarray(dst, np.float64).reshape(4, 2)
        if cv2 is not None:
            try:
                return cv2.getPerspectiveTransform(np.float32(src), np.float32(dst))
            except Exception:                                         
                pass
        A = []
        for (x, y), (u, v) in zip(src, dst):
            A.append([x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y, -u])
            A.append([0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y, -v])
        try:
            _, _, vt = np.linalg.svd(np.asarray(A, np.float64))
            H = vt[-1].reshape(3, 3)
            if abs(H[2, 2]) < 1e-12:
                return None
            return H / H[2, 2]
        except Exception:                                             
            return None

    @staticmethod
    def _warp(gray: np.ndarray, H: np.ndarray, size: int) -> np.ndarray:
        """按 H（src -> dst）输出 size×size 矫正图。"""
        if cv2 is not None:
            try:
                return cv2.warpPerspective(gray, H, (size, size), flags=cv2.INTER_LINEAR,
                                           borderMode=cv2.BORDER_REPLICATE)
            except Exception:                                         
                pass
        yy, xx = np.mgrid[0:size, 0:size]
        sx, sy = MarkerId._apply_h(H, xx.astype(np.float64), yy.astype(np.float64))
        return np.clip(MarkerId._bilinear(gray, sx, sy), 0, 255).astype(np.uint8)

    @staticmethod
    def _expected_quad(cx: float, cy: float, s: float, theta: float) -> np.ndarray:
        """按 (cx,cy,s,theta) 给出黑框外沿 4 角（TL,TR,BR,BL，与检测器 u/v 同向）。"""
        t = np.deg2rad(float(theta or 0.0))
        ct, st = np.cos(t), np.sin(t)
        out = []
        for (a, b) in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            u = a * 3.0 * s
            v = b * 3.0 * s
            out.append((cx + u * ct - v * st, cy + u * st + v * ct))
        return np.asarray(out, np.float64)

    @staticmethod
    def _rot_quad(quad: np.ndarray, deg: float) -> np.ndarray:
        """绕四边形质心旋转（小角度兜底用）。"""
        c = np.asarray(quad, np.float64).mean(axis=0)
        t = np.deg2rad(deg)
        ct, st = np.cos(t), np.sin(t)
        d = np.asarray(quad, np.float64) - c
        return np.stack([d[:, 0] * ct - d[:, 1] * st + c[0],
                         d[:, 0] * st + d[:, 1] * ct + c[1]], axis=1)

    def _find_quad(self, gray: np.ndarray, cx: float, cy: float, s: float, theta: float,
                   rad_scale: float = 4.6):
        """从候选附近提取黑框外沿的真实 4 角（透视四边形）。

        返回 ``(quad|None, conf, mode)``：
        * ``persp``：凸包 + approxPolyDP 得到 4 角（能表达透视）；
        * ``rot``  ：只能退化到 minAreaRect（旋转矩形，无透视）。

        ``rad_scale``：裁剪半径 = rad_scale×s。小标记（s 只有 2~3px）要用更大的
        7×s：否则灰面板只剩 0.3 模块宽，会被自适应阈值当成"暗环"包住整个 ROI
        （2026-10-18 实测 24px 标记 mode=no-contour，area/tgt=2.4 就是它）。
        """
        if cv2 is None or s < 2.5:
            return None, 0.0, "no-cv2"
        H, W = gray.shape[:2]
        rad = float(rad_scale) * s
        x0 = int(max(0, np.floor(cx - rad)))
        x1 = int(min(W, np.ceil(cx + rad) + 1))
        y0 = int(max(0, np.floor(cy - rad)))
        y1 = int(min(H, np.ceil(cy + rad) + 1))
        if (x1 - x0) < 3.0 * s or (y1 - y0) < 3.0 * s:
            return None, 0.0, "crop"
        roi = gray[y0:y1, x0:x1]
        rh, rw = roi.shape[:2]

        

        
        masks = []
        try:
            block = int(max(5, round(2.2 * s)))
            block += 1 if block % 2 == 0 else 0
            cut = float(max(5.0, 0.16 * s))
            masks.append(cv2.adaptiveThreshold(roi, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                               cv2.THRESH_BINARY_INV, block, cut))
        except Exception:                                             
            pass
        try:
            masks.append(cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1])
        except Exception:                                             
            pass
        if not masks:
            return None, 0.0, "cv2-err"
        tgt = (6.0 * s) ** 2
        k = int(round(s * 0.04))
        best = None
        for bw in masks:
            try:
                if k >= 2:
                    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))

                

                
                if s < 8.0 and rad_scale >= 7.0:   
                    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
                found = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                cnts = found[0] if len(found) == 2 else found[1]
            except Exception:                                         
                continue
            for c in (cnts or []):
                a = float(cv2.contourArea(c))
                if a < 0.20 * tgt or a > 2.6 * tgt:
                    continue
                bx, by, bw_, bh_ = cv2.boundingRect(c)

                

                if bx <= 0 or by <= 0 or (bx + bw_) >= (rw - 1) or (by + bh_) >= (rh - 1):
                    continue
                if bw_ > 9.5 * s or bh_ > 9.5 * s or bw_ < 3.0 * s or bh_ < 3.0 * s:
                    continue
                if not ((bx - 0.2 * s) <= (cx - x0) <= (bx + bw_ + 0.2 * s)
                        and (by - 0.2 * s) <= (cy - y0) <= (by + bh_ + 0.2 * s)):
                    continue
                sc = abs(a - tgt) / tgt
                if best is None or sc < best[0]:
                    best = (sc, c)
        if best is None:
            return None, 0.0, "no-contour"
        c = best[1]
        try:
            hull = cv2.convexHull(c)
            peri = float(cv2.arcLength(hull, True))
            pts, kind = None, "persp"
            for eps in (0.012, 0.02, 0.03, 0.045, 0.06):
                ap = cv2.approxPolyDP(hull, eps * peri, True)
                if len(ap) == 4:
                    pts = ap.reshape(4, 2).astype(np.float64)
                    break
            if pts is None:
                pts = cv2.boxPoints(cv2.minAreaRect(c)).astype(np.float64)
                kind = "rot"
        except Exception:                                             
            return None, 0.0, "cv2-geom-err"
        pts = pts + np.asarray([x0, y0], np.float64)
        exp = self._expected_quad(cx, cy, s, theta)

        bestp = None
        for perm in itertools.permutations(range(4)):
            d = sum(np.linalg.norm(pts[perm[k]] - exp[k]) for k in range(4))
            if bestp is None or d < bestp[0]:
                bestp = (d, perm)
        q = np.asarray([pts[bestp[1][k]] for k in range(4)], np.float64)

        disp = np.linalg.norm(q - exp, axis=1)
        if disp.max() > 1.35 * s:
            return None, 0.0, "shift"
        sides = np.asarray([np.linalg.norm(q[(k + 1) % 4] - q[k]) for k in range(4)])
        if sides.min() < 4.1 * s or sides.max() > 8.8 * s:
            return None, 0.0, "side"
        area = 0.5 * abs(float(np.dot(q[:, 0], np.roll(q[:, 1], -1))
                              - np.dot(q[:, 1], np.roll(q[:, 0], -1))))
        if not (0.52 * 36.0 * s * s <= area <= 1.95 * 36.0 * s * s):
            return None, 0.0, "area"
        for k in range(4):
            a = q[k - 1] - q[k]
            b = q[(k + 1) % 4] - q[k]
            na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
            if na < 1e-6 or nb < 1e-6:
                return None, 0.0, "degenerate"
            if abs(float(np.dot(a, b)) / (na * nb)) > 0.78:
                return None, 0.0, "angle"
        if float(np.linalg.norm(q.mean(axis=0) - np.asarray([cx, cy]))) > 0.55 * s:
            return None, 0.0, "center"
        conf = 1.0 if kind == "persp" else 0.72
        if float(disp.mean()) > 0.55 * s:
            conf = min(conf, 0.80)
        return q, conf, kind

    def _quiet_metrics(self, gray: np.ndarray, cx: float, cy: float, s: float):
        """静区干净度 / 更外圈参照 / 绝对对比（只在候选附近 ROI 里算，角度无关）。"""
        h, w = gray.shape[:2]
        r = 5.6 * s
        x0 = int(max(0, np.floor(cx - r)))
        x1 = int(min(w, np.ceil(cx + r) + 1))
        y0 = int(max(0, np.floor(cy - r)))
        y1 = int(min(h, np.ceil(cy + r) + 1))
        quiet, inkfrac, outfrac, rel = 0.0, 0.0, 0.0, 0.0
        contrast_abs = 0.0
        if x1 - x0 < 4 or y1 - y0 < 4:
            return quiet, inkfrac, outfrac, rel, contrast_abs
        sub = gray[y0:y1, x0:x1]
        yy, xx = np.mgrid[y0:y1, x0:x1]
        d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        ann = (d > 3.3 * s) & (d <= 3.9 * s)          
        outer = (d > 4.5 * s) & (d <= 5.5 * s)        
        inside = d <= 3.0 * s
        if inside.any():
            contrast_abs = float(np.clip((float(sub[inside].std()) - 12.0) / 45.0, 0.0, 1.0))
        if ann.any():

            gx = np.abs(np.diff(sub.astype(np.int16), axis=1, prepend=0))
            gy = np.abs(np.diff(sub.astype(np.int16), axis=0, prepend=0))
            ink = ((gx + gy) > 36)
            inkfrac = float(ink[ann].mean())
            quiet = float(np.clip(1.0 - inkfrac / 0.45, 0.0, 1.0))
        if outer.any():
            gx = np.abs(np.diff(sub.astype(np.int16), axis=1, prepend=0))
            gy = np.abs(np.diff(sub.astype(np.int16), axis=0, prepend=0))
            ink = ((gx + gy) > 36)
            outfrac = float(ink[outer].mean())
        if ann.any() and outer.any():
            rel = 1.0 if (inkfrac <= 0.80 * outfrac + 0.03) else 0.0
        return quiet, inkfrac, outfrac, rel, contrast_abs

    def _rect_metrics(self, gray: np.ndarray, quad: np.ndarray, m, mod,
                      mode: str, qconf: float, quiet_pack) -> Dict[str, Any]:
        """★ 在透视矫正后的坐标里采样 16 个数据格并重算全部分项。"""
        s = float(getattr(m, "s", 0) or 0)
        theta = float(getattr(m, "theta", 0) or 0)
        quiet, inkfrac, outfrac, rel, contrast_abs = quiet_pack
        f0, f1 = RECT_FRAME0, RECT_FRAME1
        dst = np.asarray([[f0, f0], [f1, f0], [f1, f1], [f0, f1]], np.float64)
        H_d2s = self._persp(dst, quad)          
        H_s2d = self._persp(quad, dst)          
        if H_d2s is None or H_s2d is None:
            return self._zero_breakdown(theta)

        off = np.asarray([-0.22, -0.11, 0.0, 0.11, 0.22], np.float64) * RECT_CELL
        obs, cells_std = [], []
        for i in range(4):
            for j in range(4):
                ccx = f0 + (1 + j + 0.5) * RECT_CELL
                ccy = f0 + (1 + i + 0.5) * RECT_CELL
                xs, ys = np.broadcast_arrays(ccx + off[None, :], ccy + off[:, None])
                sx, sy = self._apply_h(H_d2s, xs, ys)
                vals = self._bilinear(gray, sx, sy)
                med = float(np.median(vals))
                obs.append(med)
                cells_std.append(1.4826 * float(np.median(np.abs(vals - med))))

        rect = self._warp(gray, H_s2d, RECT_PX).astype(np.float32)
        yy, xx = np.mgrid[0:RECT_PX, 0:RECT_PX]
        frame_block = (xx >= f0) & (xx <= f1) & (yy >= f0) & (yy <= f1)
        inner4 = ((xx >= f0 + RECT_CELL - 4) & (xx <= f1 - RECT_CELL + 4)
                  & (yy >= f0 + RECT_CELL - 4) & (yy <= f1 - RECT_CELL + 4))
        frame_band = frame_block & (~inner4)
        data_zone = ((xx >= f0 + RECT_CELL + 4) & (xx <= f1 - RECT_CELL - 4)
                     & (yy >= f0 + RECT_CELL + 4) & (yy <= f1 - RECT_CELL - 4))
        q_h = (((xx >= 6) & (xx <= 34)) | ((xx >= RECT_PX - 34) & (xx <= RECT_PX - 6))) \
            & (yy >= 6) & (yy <= RECT_PX - 6)
        q_v = (((yy >= 6) & (yy <= 34)) | ((yy >= RECT_PX - 34) & (yy <= RECT_PX - 6))) \
            & (xx >= 6) & (xx <= RECT_PX - 6)
        quiet_band = q_h | q_v
        fb = float(np.median(rect[frame_band])) if frame_band.any() else 255.0
        qz = float(np.median(rect[quiet_band])) if quiet_band.any() else 0.0
        dz_mean = float(rect[data_zone].mean()) if data_zone.any() else 0.0
        dz_std = float(rect[data_zone].std()) if data_zone.any() else 0.0
        mid0 = 0.5 * (fb + qz)
        dark_frac = float((rect[frame_block] < mid0).mean()) if frame_block.any() else 1.0
        cell_lo = float(np.percentile(obs, 10))
        cell_hi = float(np.percentile(obs, 90))
        lo = min(fb, cell_lo)
        hi = max(cell_hi, float(np.percentile(rect[data_zone], 85)) if data_zone.any() else cell_hi)
        sep = float(hi - lo)
        noise = max(1.0, float(np.median(cells_std)))
        contrast = float(np.clip((sep / noise - 1.2) / 5.0, 0.0, 1.0))

        bits = None
        try:
            bits = (mod or {}).get("bits")
        except Exception:                                             
            bits = None
        n_match, pattern_ok, pattern_exact = 0, 0.0, 0
        if bits and sep >= 4.0:
            exp_rows = self._rot_cw_rows(bits, int(getattr(m, "rot", 0) or 0))

            exp = [1 if str(ch) == "1" else 0 for row in exp_rows for ch in row]
            mid = 0.5 * (lo + hi)
            got = [1 if v < mid else 0 for v in obs]
            if len(exp) == len(got) == 16:
                n_match = sum(1 for a2, b2 in zip(got, exp) if a2 == b2)
                pattern_ok = n_match / 16.0
                pattern_exact = 1 if n_match == 16 else 0

        

        

        frame_dark = (qz - fb) >= max(8.0, 0.12 * max(qz, 1.0))
        frame_vs_data = fb <= dz_mean - max(2.0, 0.05 * sep)
        ring_dark = dark_frac >= 0.42
        black_ok = 1.0 if (frame_dark and frame_vs_data and ring_dark) else 0.0
        std_d = dz_std
        data_ok = float(np.clip((std_d - 4.0) / 10.0, 0.0, 1.0))
        dt = abs(theta) % 90.0
        dt = min(dt, 90.0 - dt)
        if mode == "persp":
            theta_ok = 1.0 if qconf >= 0.55 else 0.0
        elif mode == "rot":
            theta_ok = 1.0 if dt <= 8.0 else 0.0
        else:
            theta_ok = 1.0 if (dt <= 8.0 or (pattern_exact and qconf >= 0.5)) else 0.0
        quad_ok = 1.0 if (mode == "persp" and qconf >= 0.6) else (0.55 if mode == "rot" else 0.6)
        score = (0.50 * pattern_ok + 0.20 * quad_ok + 0.12 * black_ok
                 + 0.10 * quiet + 0.08 * contrast)
        veto = ""
        if not black_ok:
            veto = "无黑框（暗带弱/厚度不符）"
        if bits and not pattern_exact:
            veto = (veto + ";" if veto else "") + "图案不吻合(%d/16<16/16)" % int(round(pattern_ok * 16))
        if sep < 10.0:
            veto = (veto + ";" if veto else "") + "对比度不足(sep=%.0f<10)" % sep
        if std_d < 4.0:
            veto = (veto + ";" if veto else "") + "数据区过于均匀(std=%.1f<4)" % std_d
        if inkfrac > 0.85:
            veto = (veto + ";" if veto else "") + "静区无墨率 %.2f>0.85" % inkfrac

        

        if mode == "rot" and dt > 8.0:
            veto = (veto + ";" if veto else "") + "角度偏离(θ=%.1f° 非90°整数倍，四角矫正不可用)" % theta
        return {"contrast": round(contrast, 3), "contrast_abs": round(contrast_abs, 3),
                "sep": round(sep, 1), "quiet": round(quiet, 3), "quiet_ink": round(inkfrac, 3),
                "outer_ink": round(outfrac, 3), "rel": rel, "black_ok": black_ok,
                "fb": round(fb, 1), "qz": round(qz, 1), "dz": round(dz_mean, 1),
                "dark_frac": round(dark_frac, 3),
                "pattern_ok": round(pattern_ok, 3), "pattern_exact": pattern_exact,
                "n_match": int(n_match), "data_ok": round(data_ok, 3),
                "theta": round(theta, 1), "theta_ok": theta_ok,
                "quad_ok": round(quad_ok, 2), "quad_conf": round(float(qconf), 2),
                "quad_mode": mode, "score": round(float(score), 3), "veto": veto}

    @staticmethod
    def _zero_breakdown(theta: float = 0.0) -> Dict[str, Any]:
        return {"contrast": 0.0, "contrast_abs": 0.0, "sep": 0.0, "quiet": 0.0,
                "quiet_ink": 0.0, "outer_ink": 0.0, "rel": 0.0, "black_ok": 0.0,
                "fb": 0.0, "qz": 0.0, "dz": 0.0, "dark_frac": 0.0,
                "pattern_ok": 0.0, "pattern_exact": 0, "n_match": 0, "data_ok": 0.0,
                "theta": round(float(theta), 1), "theta_ok": 0.0, "quad_ok": 0.0,
                "quad_conf": 0.0, "quad_mode": "none", "score": 0.0, "veto": "尺寸不足"}

    @staticmethod
    def _resize_up(gray: np.ndarray, f: float) -> np.ndarray:
        """放大 f 倍（cv2.INTER_CUBIC 优先；无 cv2 时用同一坐标映射的双线性）。"""
        if cv2 is not None:
            try:
                return cv2.resize(gray, None, fx=float(f), fy=float(f),
                                  interpolation=cv2.INTER_CUBIC)
            except Exception:                                         
                pass
        h, w = gray.shape[:2]
        nh, nw = int(round(h * f)), int(round(w * f))
        ys = (np.arange(nh, dtype=np.float64) + 0.5) / f - 0.5
        xs = (np.arange(nw, dtype=np.float64) + 0.5) / f - 0.5
        yy, xx = np.meshgrid(ys, xs, indexing="ij")
        return np.clip(MarkerId._bilinear(gray, xx, yy), 0, 255).astype(np.uint8)

    class _UpMarker:
        """上采样 ROI 里的候选代理（几何量按倍数缩放，`s` 仍是模块边长）。"""
        __slots__ = ("cx", "cy", "s", "theta", "rot", "mid", "side_px")

        def __init__(self, m, cx, cy, s):
            self.cx, self.cy, self.s = float(cx), float(cy), float(s)
            self.theta = float(getattr(m, "theta", 0) or 0)
            self.rot = int(getattr(m, "rot", 0) or 0)
            self.mid = int(getattr(m, "mid", getattr(m, "id", -1)))
            self.side_px = 0.0            

    def _small_roi(self, bgr: "np.ndarray", m):
        """小候选：裁 ROI → 上采样 → 返回 (gray_up, 代理, gain)；失败返回 None。

        放大不增加信息，但能让 **四角矫正 + 16 格 5×5 采样**落在真正的格心：
        18px 标记 s=2.25px，一个数据格只有 2.25px；2~3× 后每格 5~7px，
        双线性采样的 5 个点不再全落在同一像素上，16/16 才有意义。
        """
        s = float(getattr(m, "s", 0) or 0)
        if s <= 2.0:
            return None
        gain = float(self.small_gain or 0.0)
        if gain <= 0:
            gain = max(2.0, float(np.ceil(4.5 / s)))     
        gain = min(float(gain), 4.0)
        gray = np.asarray(bgr[:, :, 1] if bgr.ndim == 3 else bgr)
        h, w = gray.shape[:2]
        cx, cy = float(getattr(m, "cx", 0)), float(getattr(m, "cy", 0))
        rad = 6.8 * s                       
        x0 = int(max(0, np.floor(cx - rad)))
        x1 = int(min(w, np.ceil(cx + rad) + 1))
        y0 = int(max(0, np.floor(cy - rad)))
        y1 = int(min(h, np.ceil(cy + rad) + 1))
        if (x1 - x0) < 8 or (y1 - y0) < 8:
            return None
        roi = gray[y0:y1, x0:x1]
        up = self._resize_up(roi, gain)
        if up is None or up.shape[0] < 16 or up.shape[1] < 16:
            return None
        cx2 = (cx - x0 + 0.5) * gain - 0.5
        cy2 = (cy - y0 + 0.5) * gain - 0.5
        return up, self._UpMarker(m, cx2, cy2, s * gain), gain

    def _small_gate(self, br: Dict[str, Any], total: float, gain: float) -> Dict[str, Any]:
        """小候选额外护栏：**比大标记更严**（宁可漏判，绝不误判）。

        * 18~28px 时静区只剩 1~2px，"静区无墨率/quiet"这类指标**物理上不可测**
          （实测真标记 quiet=0.00~0.03），所以不拿它当门；改成
          **图案 16/16 + 黑框成立 + sep≥12** 三个硬门 + 连续 3 帧确认。
        * theta 兜底（rot）**允许**：20px 标记的透视畸变本来就 <1px，按
          min_area_rect 量到的 theta 摆正比乱试稳；真四角（persp）只有在能
          稳定拿到时才用。但"角度偏离"这条**大标记**的否决理由要摘掉，
          否则斜着拿的 18~24px 标记永远过不了。
        * 分数按**可达分项**重新归一（去掉 quiet 的 0.10 权重），否则真标记
          在远距永远差 0.05 分；raw 分仍记录在 score_raw。
        """
        br = dict(br)
        veto = str(br.get("veto", "") or "")
        if str(br.get("quad_mode", "")) == "rot" and int(br.get("pattern_exact", 0)) == 1:

            veto = ";".join(p for p in veto.split(";") if p and not p.startswith("角度偏离"))
        add = []
        if int(br.get("pattern_exact", 0)) != 1:
            add.append("小标记图案非16/16")
        if int(br.get("black_ok", 0)) != 1:
            add.append("小标记黑框不成立")
        if float(br.get("sep", 0.0)) < self.small_min_sep:
            add.append("小标记对比度不足(sep=%.0f<%.0f)"
                       % (float(br.get("sep", 0.0)), self.small_min_sep))
        if float(br.get("quiet", 0.0)) < self.small_min_quiet:
            add.append("小标记静区不干净(quiet=%.2f<%.2f)"
                       % (float(br.get("quiet", 0.0)), self.small_min_quiet))
        if add:
            veto = (veto + ";" if veto else "") + ";".join(add)

        raw = float(br.get("score", 0.0))
        s_small = (0.50 * float(br.get("pattern_ok", 0.0))
                   + 0.20 * float(br.get("quad_ok", 0.0))
                   + 0.12 * float(br.get("black_ok", 0.0))
                   + 0.08 * float(br.get("contrast", 0.0))) / 0.90
        br["score_raw"] = round(raw, 3)
        br["score"] = round(min(1.0, s_small), 3)
        br["veto"] = veto
        br["small_gain"] = round(float(gain), 2)
        br["total_px"] = round(float(total), 1)
        return br

    def verify(self, bgr: "np.ndarray", m, mod=None) -> Dict[str, float]:
        """★ 自算可解释置信分项：**先四角透视矫正，再在矫正图上采样**。

        2026-10-18 远距增强：总边长 < ``small_total_px``（默认 30px）时，先把候选
        ROI 上采样 2~3× 再走同一套"四角矫正 + 16 格采样"，并加严门（16/16、sep、
        静区、必须有真四角）。**放大的只是采样精度，不是判定门限**。
        """
        s0 = float(getattr(m, "s", 0) or 0)
        total = 8.0 * s0
        if s0 > 2.0 and 0 < total < self.small_total_px:
            got = self._small_roi(bgr, m)
            if got is not None:
                up, m2, gain = got
                br = self._verify_core(up, m2, mod, quad_rad=7.0)
                return self._small_gate(br, total, gain)
        return self._verify_core(bgr, m, mod)

    def _verify_core(self, bgr: "np.ndarray", m, mod=None, quad_rad: float = 4.6) -> Dict[str, float]:
        """（原 verify 主体）先四角透视矫正，再在矫正图上采样。"""
        h, w = bgr.shape[:2]
        cx, cy = float(getattr(m, "cx", 0)), float(getattr(m, "cy", 0))

        s = float(getattr(m, "side_px", 0) or getattr(m, "s", 0) or 0)
        theta = float(getattr(m, "theta", 0) or 0)
        if s <= 2:
            return self._zero_breakdown(theta)
        gray = np.asarray(bgr[:, :, 1] if bgr.ndim == 3 else bgr)
        quiet_pack = self._quiet_metrics(gray, cx, cy, s)
        quad, qconf, qmode = self._find_quad(gray, cx, cy, s, theta, rad_scale=quad_rad)
        best = None
        if quad is not None and qconf >= 0.55:

            best = self._rect_metrics(gray, quad, m, mod, "persp", qconf, quiet_pack)
            if not best.get("pattern_exact") and qconf >= 0.80:

                for dd in (-2.5, 2.5):
                    br2 = self._rect_metrics(gray, self._rot_quad(quad, dd), m, mod,
                                             "multi", 0.6, quiet_pack)
                    if br2.get("pattern_exact"):
                        best = br2
                        break
        if best is None or (not best.get("pattern_exact") and qmode == "rot"):

            q0 = self._expected_quad(cx, cy, s, theta)
            br0 = self._rect_metrics(gray, q0, m, mod, "rot", 0.55, quiet_pack)
            if best is None or int(br0.get("n_match", 0)) > int(best.get("n_match", 0)):
                best = br0
        self.last_quad = {"mode": best.get("quad_mode"), "conf": best.get("quad_conf"),
                          "quad": None if quad is None else np.round(quad, 1).tolist()}
        return best

    def detect_multi(self, bgr: "np.ndarray"):
        """★ variants 支持：同一 marker 可能有多个尺寸模板（如 G5 25mm/15mm）→ 各尺寸检一遍取最高分。"""
        variants = []
        for _mid, mod in (self.by_id or {}).items():
            for v in (mod.get("variants") or []):
                variants.append((_mid, v))
        if not variants:
            hit, hits = self.detect(bgr)
            return hit, hits
        best_hit, best_hits = None, []
        hh, ww = bgr.shape[:2]
        for _mid, v in variants:
            lo = int(v.get("min_recognizable_px") or 0)
            hi = int(0.25 * min(hh, ww))
            if lo:

                lo_s = max(1, int(lo / 8.0)); hi_s = max(2, int(hi / 8.0))
                try:
                    h2, hs2 = self.detect(bgr, min_side_px=lo_s, max_side_px=hi_s)
                except Exception:                                     
                    continue
                if h2 is not None and (best_hit is None or h2.score > best_hit.score):
                    best_hit, best_hits = h2, hs2
        return best_hit, best_hits

    def detect(self, bgr: "np.ndarray", min_side_px: int = 0, max_side_px: int = 0):
        """检测一帧；返回 (MarkerHit|None, 全部命中列表)。**已做连续帧确认（去抖）**。"""
        if self.md is None or self._codes is None or bgr is None:
            return None, []
        h, w = bgr.shape[:2]
        if bgr.ndim == 3:                                
            gray = (bgr[:, :, 0] * 0.114 + bgr[:, :, 1] * 0.587 + bgr[:, :, 2] * 0.299).astype(np.uint8)
        else:
            gray = bgr

        mn = min_side_px or self._user_min or max(3, int(24 / 8.0))   

        

        try:
            mn = min(int(mn), max(3, int(round(0.70 * self.min_total_px))))
        except Exception:                                             
            pass
        mx = max_side_px or self._user_max or int(0.9 * min(h, w))             
        try:
            res = self.md.detect_markers(gray, self._codes, min_side_px=mn, max_side_px=mx,
                                         max_hamming=self.max_hamming,
                                         dark_win_frac=self.dark_win_frac)
        except Exception as e:                                        
            print("[marker][warn] detect_markers 异常: %s" % e, flush=True)
            return None, []
        hits: List[MarkerHit] = []
        for m in (res or []):
            mid = int(getattr(m, "mid", getattr(m, "id", -1)))
            mod = self.by_id.get(mid)
            if mod is None:
                continue

            
            hh, ww = bgr.shape[:2]
            _s = float(getattr(m, "s", 0) or getattr(m, "side_px", 0) or 0)
            total = 8.0 * _s
            lo_px = max(float(self.min_total_px), 0.015 * min(hh, ww))  
            hi_px = self.max_side_frac * min(hh, ww)           
            if _s > 2 and (total > hi_px or total < lo_px):
                if self.verbose:
                    if total > hi_px:
                        why = ("尺寸过大(%.0fpx>%.0fpx) → 请把镜头拉远一点，或换小一号标记（G5/G6 用 15mm 版）"
                               % (total, hi_px))
                    else:
                        why = "尺寸不足(%.0fpx<%.0fpx) → 请把镜头靠近一些，或换大一号标记" % (total, lo_px)
                    print("[marker][reject] %s 总边长=%.0fpx 允许区间=[%.0f,%.0f]px（短边=%d）"
                          % (why, total, lo_px, hi_px, min(hh, ww)), flush=True)
                continue
            if self.verbose:
                print("[marker] %s side_px=%.1f 总边长=%.0fpx 区间=[%.0f,%.0f]（短边=%d）"
                      % (mod.get("label", "?"), _s, total, lo_px, hi_px, min(hh, ww)), flush=True)
            br = self.verify(bgr, m, mod)
            score = float(br.get("score", 0.0))
            veto = str(br.get("veto", "") or "")
            if score < self.min_score or veto:
                if self.verbose:
                    why = veto or ("分值 %.2f<%.2f" % (score, self.min_score))
                    print("[marker][reject] %s 原因=%s 分项=%s"
                          % (mod.get("label", "?"), why, br), flush=True)
                continue
            hits.append(MarkerHit(label=mod.get("label", "M?"), marker_id=mid, score=score,
                                  cx=float(getattr(m, "cx", 0)), cy=float(getattr(m, "cy", 0)),
                                  side_px=float(getattr(m, "side_px", 0) or getattr(m, "s", 0)),
                                  theta=float(getattr(m, "theta", 0)), module=mod, breakdown=br))
        hits.sort(key=lambda z: -z.score)

        best = hits[0] if hits else None
        import time as _t
        _now = _t.time()

        if best is not None:
            self._hist.append((_now, best.label))
        self._hist = [(t0, lb) for (t0, lb) in self._hist if _now - t0 <= self.window_sec]

        note = ""
        if best is not None and self._prev is not None:
            p = self._prev
            if p.label == best.label:
                dpos = abs(p.cx - best.cx) + abs(p.cy - best.cy)
                dsiz = abs(p.side_px - best.side_px) / max(1.0, p.side_px)
                if dpos > 1.0 * max(8.0, best.side_px * 8) or dsiz > 0.30:
                    note = "（位置漂移=%.0fpx 边长漂移=%.0f%%：仍计数）" % (dpos, 100 * dsiz)
        if best is not None:
            self._prev = best
            cnt = sum(1 for (_t0, lb) in self._hist if lb == best.label)
            high = (best.score >= 0.95 and not str(best.breakdown.get("veto", ""))
                    and float(best.breakdown.get("black_ok", 0)) >= 1.0
                    and float(best.breakdown.get("data_ok", 0)) >= 0.25
                    and float(best.breakdown.get("theta_ok", 0)) >= 1.0

                    
                    and 8.0 * float(best.side_px) >= self.small_total_px)

            _lbls = set(lb for (_t0, lb) in self._hist)
            if len(_lbls) > 1:
                need = int(self.confirm_n)
                high = False
            else:
                need = min(int(self.confirm_n), 2) if high else int(self.confirm_n)
            best.frames = cnt
            self.progress = (cnt, need)
            confirmed = cnt >= need
            if self.verbose:
                print("[marker] %s score=%.2f 窗口命中=%d/%d%s%s"
                      % (best.label, best.score, cnt, need, note,
                         "" if confirmed else "（未达确认）"), flush=True)

            if confirmed:
                if self._latch is None or self._latch.label != best.label or _now - self._latch_t > self.latch_sec:
                    self._latch, self._latch_t = best, _now
                    if self.verbose:
                        print("[marker] 身份锁定：%s（%.0fs）" % (best.label, self.latch_sec), flush=True)
                self._last = best
            return (best if confirmed else None), hits

        if self._latch is not None and (_now - self._latch_t) <= self.latch_sec:
            self._latch.frames = self.progress[0] if isinstance(self.progress, tuple) else 0
            return self._latch, hits
        if self._latch is not None and self.verbose:
            print("[marker] 身份锁定过期（%.0fs 内无命中）→ 回到未识别" % self.latch_sec, flush=True)
        self._latch = None
        self.progress = (0, 0)
        return None, []

    def resolve_part(self, hit: Optional[MarkerHit], calib_parts: Optional[List[str]] = None):
        """归属优先级链：标记 > 已标定 ROI > 未判定。返回 (part_key, reason, confidence)。"""
        if hit is not None and hit.module:
            mod = hit.module
            rk = str(mod.get("rule_key") or "")
            cands = RULE_KEY_TO_PART.get(rk)
            if not cands:
                for hint, ids in RULE_TEXT_HINT:
                    if hint in str(mod.get("rule_text", "")):
                        cands = ids
                        break
            if not cands:
                cands = [str(mod.get("part") or mod.get("label"))]
            inst = mod.get("instances") or []
            key = str(cands[0])
            extra = ""

            

            key_norm, _rt = _normalize_part_route(key, str(mod.get("route") or ""))
            if key_norm != key:
                extra += ("；旧模块 id %s 归一到母模块 %s（二路码，route=%s）"
                          % (key, key_norm, _rt or "II"))
                key = key_norm
            if len(cands) > 1:
                extra = ("；该标记覆盖 %d 个同类面板（实例：%s），按规则一致处理，实际取 %s"
                         % (len(cands), " / ".join(str(x)[:18] for x in inst[:2]) or "-", key))
            return key, ("标记 %s（%s）置信 %.2f，连续 %d 帧 → 身份确定%s"
                         % (hit.label, mod.get("name", ""), hit.score, hit.frames, extra)), hit.score
        parts = list(calib_parts or [])
        if len(parts) == 1:
            return parts[0], "无标记，但有唯一已标定部件 %s → 用其 ROI" % parts[0], 0.5
        if len(parts) > 1:
            return "", ("无标记且标定里有 %d 个部件（%s）→ 无法确定是哪一个 → 未判定"
                        % (len(parts), ",".join(parts))), 0.0
        return "", "无标记、也没有已标定 ROI → 未判定（绝不猜）", 0.0

def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="读 4×4 标记 → 锁定模块身份")
    ap.add_argument("-i", "--image", required=True)
    ap.add_argument("--json", default="")
    ap.add_argument("--min-side", type=int, default=0)
    ap.add_argument("--max-side", type=int, default=0)
    ap.add_argument("--dark-win-frac", type=float, default=0.25)
    ap.add_argument("--confirm-n", type=int, default=1)
    a = ap.parse_args(argv)
    bgr = cv2.imread(a.image, cv2.IMREAD_COLOR)
    if bgr is None:
        print("读不到 %s" % a.image)
        return 1
    mi = MarkerId(a.json, a.min_side, a.max_side, a.dark_win_frac, confirm_n=a.confirm_n)
    hit, hits = mi.detect(bgr)
    print("命中 %d 个候选：" % len(hits))
    for z in hits:
        print("  %-4s mid=%d score=%.2f side=%.1fpx theta=%.1f 模块=%s"
              % (z.label, z.marker_id, z.score, z.side_px, z.theta, z.module.get("name", "")))
    print("确认结果: %s" % (hit.to_dict() if hit else "无（未达确认帧数或未检出）"))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
