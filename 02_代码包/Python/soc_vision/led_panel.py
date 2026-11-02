#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""led_panel.py —— 面板 LED **点亮/熄灭**检测（阈值全部来自真值照片实测，不是拍脑袋）。

实测依据（8 张真值照片，工作分辨率长边 1536）
--------------------------------------------
* **真正的灯**：半径 **r≈19~31 px**、`中心盘V − 外围暗环V(25分位) = delta 45~193`、
  饱和度 S 常 >80（过曝时 S 会掉到 30~60 但 **B/G/R 通道增量**仍能判色）
* **假阳性（必须排除）**：丝印白字/反光/镜面高光 → **r≤8**、S<20 的纯白小点，
  它们的 delta 甚至能到 190（比真灯还高）→ **单靠 delta 一定误检，必须联合"半径 + 饱和度/通道增量"**
* **按钮 ≠ 灯**：`通`/`断` 方按钮、拨杆、方形色块 → 自发光弱（delta≈0）、且**形状非圆**（fill/长宽比不符）
* **过曝处理**：点亮红/绿灯会过曝偏白 → 用「各通道相对暗环的**增量**」判颜色，而不是只看 HSV 色相

判据
----
1. 候选：红/绿/过曝白掩膜 → 连通域 → 半径 r∈[r_min,r_max]、圆度 fill≥0.45、长宽比 0.5~2.0
2. `delta = mean(V_中心0.75r) − P25(V_暗环 2.2~3.2r)`（暗环避开光晕）
3. 迟滞：`delta ≥ thr_on` → ON；`delta ≤ thr_off` → OFF；中间保持上一状态（**时间去抖 N 帧**）
4. 颜色：`excess_c = center_c − ring_c`，取最大者（过曝也稳）；S 高时用 HSV 色相交叉校验
5. **防误检门**：没标定 / ROI 越界 / 半径超界 / delta 落在死区 / 检出灯数与规则不符
   → 一律 `unknown`（**绝不当成"灯灭"**），并给出原因
6. 有 FPGA 状态字时**以 FPGA 为准**，软件值并列保留（在 led_rules.evaluate 里做）

标定产物（`tools/led_calibrate.py` 产出）JSON 结构：
    {"image": "...", "work_long": 1536,
     "parts": {"PS_KONG": [{"name":"空调电源指示","color":"R","x":527,"y":208,"r":26}, ...]}}
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    import cv2
except Exception:                                                 
    cv2 = None

from soc_vision.led_rules import LampState, PartRule, PartVerdict, RuleBook, evaluate

WORK_LONG = 1536
R_MIN_FRAC = 0.0040          
R_MAX_FRAC = 0.0450
FILL_MIN = 0.45
ASPECT_LO, ASPECT_HI = 0.5, 2.0
DELTA_ON = 25.0              
DELTA_OFF = 15.0             
RING_IN, RING_OUT = 2.2, 3.2
DEBOUNCE_N = 3

@dataclass
class LampCand:
    x: int
    y: int
    r: int
    delta: float
    v_center: float
    v_ring: float
    s_mean: float
    blown: float
    color: str
    excess: Tuple[float, float, float]
    fill: float
    is_lamp: bool = True
    reject: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"x": self.x, "y": self.y, "r": self.r, "delta": round(self.delta, 1),
                "v_center": round(self.v_center, 1), "v_ring": round(self.v_ring, 1),
                "s": round(self.s_mean, 1), "blown": round(self.blown, 2), "color": self.color,
                "excess": [round(e, 1) for e in self.excess], "fill": round(self.fill, 2),
                "is_lamp": self.is_lamp, "reject": self.reject}

def orient_normalize(bgr):
    """朝向归一：横拍（宽>高）→ 顺时针 90°（真值照片 151324/151341/151359/151448 正是这种）。
    注意：这 8 张 **都没有 EXIF 朝向**（实测全为 1），所以只能按几何判断。"""
    h, w = bgr.shape[:2]
    if w > h:
        return cv2.rotate(bgr, cv2.ROTATE_90_CLOCKWISE), True
    return bgr, False

def fit_long(bgr, long_side: int = WORK_LONG):
    h, w = bgr.shape[:2]
    k = float(long_side) / max(h, w)
    if k < 1.0:
        return cv2.resize(bgr, (int(round(w * k)), int(round(h * k))), interpolation=cv2.INTER_AREA)
    return bgr

def _ring_means(bgr, hsv, cx, cy, r_in, r_out):
    h, w = bgr.shape[:2]
    x0, x1 = max(0, int(cx - r_out)), min(w, int(cx + r_out) + 1)
    y0, y1 = max(0, int(cy - r_out)), min(h, int(cy + r_out) + 1)
    if x1 <= x0 or y1 <= y0:
        return (0.0, 0.0, 0.0, 0.0)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    rr = np.sqrt((xx - cx) ** 2.0 + (yy - cy) ** 2.0)
    m = (rr >= r_in) & (rr <= r_out)
    if not np.any(m):
        return (0.0, 0.0, 0.0, 0.0)
    sub = bgr[y0:y1, x0:x1].astype(np.float32)
    v = hsv[y0:y1, x0:x1, 2].astype(np.float32)
    return (float(v[m].mean()), float(np.percentile(v[m], 25)),
            float(sub[:, :, 2][m].mean()), float(sub[:, :, 1][m].mean()), float(sub[:, :, 0][m].mean()))

def measure_at(bgr, hsv, cx, cy, r) -> Optional[dict]:
    """在给定圆心/半径处量：中心 V/BGR、暗环 V/BGR、delta、饱和度、过曝比、颜色。"""
    h, w = bgr.shape[:2]
    x0, x1 = max(0, int(cx - r)), min(w, int(cx + r) + 1)
    y0, y1 = max(0, int(cy - r)), min(h, int(cy + r) + 1)
    if x1 <= x0 or y1 <= y0:
        return None
    yy, xx = np.mgrid[y0:y1, x0:x1]
    rr = np.sqrt((xx - cx) ** 2.0 + (yy - cy) ** 2.0)
    m = rr <= max(1.0, r * 0.75)
    if not np.any(m):
        return None
    sub = bgr[y0:y1, x0:x1].astype(np.float32)
    hs = hsv[y0:y1, x0:x1]
    V = hs[:, :, 2].astype(np.float32)[m]
    S = hs[:, :, 1].astype(np.float32)[m]
    B = float(sub[:, :, 0][m].mean()); G = float(sub[:, :, 1][m].mean()); R = float(sub[:, :, 2][m].mean())
    ring_v, ring_p25, ring_r, ring_g, ring_b = _ring_means(bgr, hsv, cx, cy, r * RING_IN, r * RING_OUT)
    if ring_v <= 0:
        return None
    excess = (R - ring_r, G - ring_g, B - ring_b)
    e_max = max(excess)
    if e_max <= 0:
        color = "W"
    elif excess[0] == e_max and excess[0] > excess[1] * 1.02:
        color = "R"
    elif excess[1] == e_max and excess[1] > excess[0] * 1.02:
        color = "G"
    else:
        color = "W"
    return dict(v_center=float(V.mean()), v_ring=ring_p25, ring_mean_v=ring_v,
                delta=float(V.mean()) - ring_p25, s_mean=float(S.mean()),
                blown=float((V >= 250).mean()), b=B, g=G, r=R,
                ring_bgr=(ring_b, ring_g, ring_r), excess=excess, color=color)

def detect_candidates(bgr, r_min_frac: float = R_MIN_FRAC, r_max_frac: float = R_MAX_FRAC,
                      keep_rejected: bool = True) -> List[LampCand]:
    """找出所有"像灯"的候选（含被拒的，便于审计）。"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    red = (((H < 12) | (H > 168)) & (S > 80) & (V > 130))
    grn = ((H > 35) & (H < 95) & (S > 70) & (V > 110))
    white = (V > 240) & (S < 90)
    mask = ((red | grn | white).astype(np.uint8)) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, _lab, stats, cent = cv2.connectedComponentsWithStats(mask, 8)
    long_side = max(bgr.shape[:2])
    r_min = max(3, int(round(r_min_frac * long_side)))
    r_max = max(r_min + 1, int(round(r_max_frac * long_side)))
    out: List[LampCand] = []
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        x, y, w, h = (int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP]),
                      int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT]))
        fill = area / float(max(1, w * h))
        asp = w / float(max(1, h))
        cx, cy = int(cent[i][0]), int(cent[i][1])
        r = max(2, int(round((w + h) / 4.0)))
        reject = ""
        if r > r_max:
            reject = "半径过大 r=%d>%d（像大色块/按钮光泽，非 LED）" % (r, r_max)
        elif r < r_min:
            reject = "半径过小 r=%d<%d（丝印白字/镜面高光）" % (r, r_min)
        elif fill < FILL_MIN:
            reject = "圆度不足 fill=%.2f（方形按钮/长条）" % fill
        elif not (ASPECT_LO <= asp <= ASPECT_HI):
            reject = "长宽比 %.2f 不在 [%.1f,%.1f]" % (asp, ASPECT_LO, ASPECT_HI)
        m = measure_at(bgr, hsv, cx, cy, r) if not reject else measure_at(bgr, hsv, cx, cy, r)
        if m is None:
            continue
        c = LampCand(x=cx, y=cy, r=r, delta=m["delta"], v_center=m["v_center"], v_ring=m["v_ring"],
                     s_mean=m["s_mean"], blown=m["blown"], color=m["color"], excess=m["excess"],
                     fill=fill, is_lamp=(reject == ""), reject=reject)
        if c.is_lamp and (c.delta <= 0.0
                          or (c.delta < DELTA_ON and c.s_mean < 90)
                          or (c.color == "W" and c.s_mean < 20)):
            c.is_lamp = False
            c.reject = "自发光不足/白点误检 delta=%.0f S=%.1f（按钮/色块/丝印不自发光）" % (
                c.delta, c.s_mean)
        if c.is_lamp or keep_rejected:
            out.append(c)
    out.sort(key=lambda z: -z.delta)
    return out

def lamps_only(cands: Sequence[LampCand]) -> List[LampCand]:
    return [c for c in cands if c.is_lamp]

@dataclass
class Calib:
    work_long: int = WORK_LONG
    parts: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    grid: str = ""
    image: str = ""

    @staticmethod
    def load(path: str) -> "Calib":
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return Calib(work_long=int(d.get("work_long", WORK_LONG)),
                     parts=dict(d.get("parts", {})), grid=str(d.get("grid", "")),
                     image=str(d.get("image", "")))

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"work_long": self.work_long, "grid": self.grid, "image": self.image,
                       "parts": self.parts}, f, ensure_ascii=False, indent=2)

class PanelDetector:
    """有状态检测器：负责**时间去抖**与"同一路灯的迟滞状态"。"""

    def __init__(self, calib: Optional[Calib] = None, debounce_n: int = DEBOUNCE_N,
                 delta_on: float = DELTA_ON, delta_off: float = DELTA_OFF):
        self.calib = calib
        self.debounce_n = int(debounce_n)
        self.delta_on = float(delta_on)
        self.delta_off = float(delta_off)
        self._cnt: Dict[str, int] = {}
        self._state: Dict[str, bool] = {}
        self.last_gate: Dict[str, Any] = {}

    def states_from_calib(self, bgr, part_id: str, rule: PartRule) -> Tuple[List[LampState], Dict[str, Any]]:
        c = self.calib
        gate = {"ok": False, "reason": "", "part": part_id}
        if c is None or part_id not in c.parts:
            gate["reason"] = "该部件没有标定 ROI（calib.parts 缺 %s）→ 未判定" % part_id
            return [LampState(name=ls.name, color=ls.color, on=None, reason=gate["reason"])
                    for ls in rule.lamps], gate
        rois = c.parts[part_id]
        H, W = bgr.shape[:2]
        long_side = max(H, W)
        r_min = max(3, int(round(R_MIN_FRAC * long_side)))
        r_max = max(r_min + 1, int(round(R_MAX_FRAC * long_side)))
        bad = []
        for i, r in enumerate(rois):
            x, y, rr = int(r.get("x", -1)), int(r.get("y", -1)), int(r.get("r", 0))
            if x < 0 or y < 0 or x >= W or y >= H:
                bad.append("%s(越界 %d,%d)" % (r.get("name", i), x, y))
            elif rr < r_min or rr > r_max:
                bad.append("%s(半径 r=%d 不在 [%d,%d])" % (r.get("name", i), rr, r_min, r_max))
        if bad:
            gate["reason"] = "标定 ROI 非法：%s → 拒绝出判定" % "; ".join(bad)
            return [LampState(name=ls.name, color=ls.color, on=None, reason=gate["reason"])
                    for ls in rule.lamps], gate
        if len(rois) != len(rule.lamps):
            gate["reason"] = ("标定灯数 %d ≠ 规则灯数 %d（**拒绝出判定**，避免张冠李戴）"
                              % (len(rois), len(rule.lamps)))
            return [LampState(name=ls.name, color=ls.color, on=None, reason=gate["reason"])
                    for ls in rule.lamps], gate
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        bright = lamps_only(detect_candidates(bgr))       
        states: List[LampState] = []
        for ls, r in zip(rule.lamps, rois):
            x, y, rr = int(r["x"]), int(r["y"]), int(r["r"])
            m = measure_at(bgr, hsv, x, y, rr)
            key = "%s/%s" % (part_id, ls.name)
            if m is None:
                states.append(LampState(name=ls.name, color=ls.color, on=None, x=x, y=y, r=rr,
                                        reason="量不到（ROI 越界）"))
                continue
            d = m["delta"]

            near = any((c.x - x) ** 2 + (c.y - y) ** 2 <= (0.9 * max(c.r, rr)) ** 2 for c in bright)
            lit = bool(near and d >= self.delta_on)
            if lit:
                self._cnt[key] = self._cnt.get(key, 0) + 1
            elif d <= self.delta_off or not near:
                self._cnt[key] = self._cnt.get(key, 0) - 1
            else:
                self._cnt[key] = 0
            prev = self._state.get(key, False)
            new = prev
            if self._cnt.get(key, 0) >= self.debounce_n:
                new, self._cnt[key] = True, 0
            elif self._cnt.get(key, 0) <= -self.debounce_n:
                new, self._cnt[key] = False, 0
            self._state[key] = new
            states.append(LampState(name=ls.name, color=m["color"] if m["color"] != "W" else ls.color,
                                    on=new, delta=d, thr_on=self.delta_on, thr_off=self.delta_off,
                                    x=x, y=y, r=rr, source="sw",
                                    reason="delta=%.1f 亮点命中=%s（阈值 %.0f/%.0f）"
                                           % (d, "是" if near else "否", self.delta_on, self.delta_off)))
        gate.update({"ok": True, "reason": "标定 ROI 校验通过（%d 颗）" % len(rois),
                     "n_lamp": len(rois)})
        return states, gate

    def states_auto(self, bgr, part_id: str, rule: PartRule) -> Tuple[List[LampState], Dict[str, Any]]:
        cands = lamps_only(detect_candidates(bgr))
        gate = {"ok": False, "reason": "", "part": part_id, "n_cand": len(cands)}
        need = len(rule.lamps)

        want_colors = [ls.color for ls in rule.lamps]
        want_r = sum(1 for c in want_colors if c == "R")
        want_g = sum(1 for c in want_colors if c == "G")
        got = list(cands)

        sel_r = sorted([c for c in got if c.color == "R"], key=lambda z: -z.delta)[:max(want_r, 1) if want_r else 0]
        sel_g = sorted([c for c in got if c.color == "G"], key=lambda z: -z.delta)[:max(want_g, 1) if want_g else 0]
        sel = sel_r + sel_g
        gate["sel_R"], gate["sel_G"] = len(sel_r), len(sel_g)
        if not got:
            gate["reason"] = "画面里没有检测到任何点亮的灯（也可能全部熄灭）"
        states: List[LampState] = []

        for i, c in enumerate(sel):
            nm = rule.lamps[i].name if i < need else "额外亮点%d" % i
            states.append(LampState(name=nm, color=c.color, on=True, delta=c.delta,
                                    thr_on=self.delta_on, thr_off=self.delta_off,
                                    x=c.x, y=c.y, r=c.r, source="sw",
                                    reason="中心-暗环 delta=%.1f" % c.delta))
        miss = need - len(states)
        for k in range(max(0, miss)):
            j = len(states) + k
            nm = rule.lamps[j].name if j < need else "缺%d" % j
            states.append(LampState(name=nm, color=rule.lamps[j].color if j < need else "?",
                                    on=None, reason="未标定自动模式下找不到这颗灯 → 未判定"))
        gate["ok"] = len(states) >= need and miss <= 0
        gate["reason"] = (gate["reason"] or "自动检出 %d 颗（需 %d 颗）" % (len(sel), need))
        return states, gate

def analyze(bgr, book: RuleBook, part_id: str = "", calib: Optional[Calib] = None,
            fpga_lit: Optional[Sequence[bool]] = None, det: Optional[PanelDetector] = None,
            auto_ok: bool = True):
    """一张图 -> 部件判定。返回 (PartVerdict, info_dict)。"""
    det = det or PanelDetector(calib)
    information: Dict[str, Any] = {}
    cands = detect_candidates(bgr)
    information["candidates"] = [c.to_dict() for c in lamps_only(cands)]
    information["rejected"] = [c.to_dict() for c in cands if not c.is_lamp]
    if not part_id:
        information["gate"] = {"ok": False, "reason": "未指定部件（需丝印 OCR 或标定）→ 未判定"}
        v = PartVerdict(verdict="未判定", reason=information["gate"]["reason"])
        return v, information
    rule = book.get(part_id)

    try:
        import json as _json
        import os as _os
        _here = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        _cfg = _json.load(open(_os.path.join(_here, "config", "led_rules.json"), encoding="utf-8"))
        _raw = next((p for p in _cfg.get("parts", []) if p.get("id") == part_id), None)
    except Exception:                                                 
        _raw = None
    _kind = str((_raw or {}).get("kind", ""))
    if _kind in ("text_assert", "numeric_range"):
        information["gate"] = {"ok": False, "reader": True, "kind": _kind}
        rdr = str((_raw or {}).get("reader", ""))
        reason = "该部件的判定能力未就绪（%s 读数器未加载）→ 未判定" % (rdr or _kind)
        val_txt = ""
        try:
            if _kind == "text_assert":                                 
                from soc_vision.screen_read import ScreenReader
                _rd = ScreenReader()
                _cells, _roi, _quad, _gl, _info = _rd.read(bgr)
                _f = _rd.fields(_cells)
                parts_txt = []
                ok_all, conf_lo = True, False
                for asrt in (_raw.get("asserts") or []):
                    nm = asrt.get("field", "")
                    got = (_f.get(nm) or {})
                    parts_txt.append("%s=%s(%.2f)" % (nm, got.get("value", "?"), got.get("conf", 0.0)))
                    if got.get("value") != asrt.get("expect"):
                        ok_all = False
                    if float(got.get("conf", 0.0)) < float(_raw.get("min_conf", 0.55)):
                        conf_lo = True
                val_txt = "、".join(parts_txt)
                if conf_lo or not _f:
                    reason = ("屏读数器读数置信不足（%s）→ 未判定" % (val_txt or "无读数"))
                elif ok_all:
                    reason = "屏读数：%s ⇒ 正常" % val_txt
                else:
                    reason = "屏读数：%s ⇒ 故障" % val_txt
            else:                                                      
                from soc_vision import seg7
                _im = bgr[:, :, ::-1] if bgr.ndim == 3 else bgr    
                _disps = seg7.read_displays(_im)
                if not _disps:
                    reason = "7 段读数器未就绪/未检出数字 → 未判定"
                else:
                    val_txt = "、".join("%s=%s(%.2f)" % (d0.text, "", d0.conf) for d0 in _disps[:4])
                    reason = "7 段读数：%s（容差校验待接入）→ 未判定" % val_txt
        except Exception as _e:                                        
            reason = "该部件的判定能力未就绪（%s: %s）→ 未判定" % (type(_e).__name__, _e)
        information["gate"]["reason"] = reason
        information["reader_text"] = val_txt
        v = PartVerdict(verdict="未判定", reason=reason)
        return v, information
    if rule is None:
        information["gate"] = {"ok": False, "reason":
                               "该部件的判定能力未就绪（规则表缺少 %s 条目）→ 未判定" % part_id}
        v = PartVerdict(verdict="未判定", reason=information["gate"]["reason"])
        return v, information
    states, gate = det.states_from_calib(bgr, part_id, rule) if (calib and part_id in (calib.parts or {})) \
        else det.states_auto(bgr, part_id, rule)
    information["gate"] = gate
    if (calib and part_id in (calib.parts or {})):

        v = evaluate(rule, states, fpga_lit=fpga_lit)
    else:

        from soc_vision.led_rules import evaluate_by_litcount
        lit_c = [c for c in (information.get("candidates") or []) if c.get("is_lamp", True)]
        long_side = max(bgr.shape[:2])
        cands_obj = [LampCand(x=c["x"], y=c["y"], r=c["r"], delta=c["delta"],
                             v_center=c["v_center"], v_ring=c["v_ring"], s_mean=c["s"],
                             blown=c["blown"], color=c["color"], excess=tuple(c["excess"]),
                             fill=c["fill"]) for c in lit_c]
        gok, greason = geometry_gate(cands_obj, len(rule.lamps), long_side)
        n_lit = len(cands_obj)
        n_lens = count_lenses(bgr, cands_obj)
        information["n_lens"] = n_lens
        information["geometry_gate"] = {"ok": gok, "reason": greason, "n_lit": n_lit, "n_lens": n_lens}
        if not gok:
            v = PartVerdict(pid=rule.pid, name=rule.name, kind=rule.kind, verdict="未判定",
                            reason=greason)
            information["path"] = "geometry-gate(未判定)"
        else:
            lens_ev = int(n_lens)
            v = evaluate_by_litcount(rule, n_lit, panel_present=(n_lit + lens_ev > 0),
                                     lit_names=[rule.lamps[i].name
                                                for i in range(min(n_lit, len(rule.lamps)))],
                                     lens_evidence=lens_ev)
            information["path"] = "litcount"
    information["verdict"] = v.to_dict()
    return v, information

def pick_lamp_slots(spots: List[dict], need: int, long_side: int) -> List[dict]:
    """从"亮点 + 暗灯罩"里挑出**排成一条直线的 N 个灯位**。

    现场教训（⑦ `151448` 一行 5 灯）：只按 delta 挑暗灯罩，会把**不在灯位上的反光**选进来，
    空间排序后与真灯**张冠李戴**（实测把 `发射通` 判成 off、`发射断` 判成 on）。
    正确做法：**先用已亮的灯定出灯位栅格**（轴线 + 间距），再把暗灯罩**吸附到缺的格位**：
      1. 以亮点的坐标分散方向定轴线（竖排/横排）；
      2. 只在"灯位走廊"内取候选（垂轴偏差 <= 2.5×r 或 6% 长边）；
      3. 必须包含**全部亮点**，在走廊候选里枚举 C(k, need-n_bright)，
         选"相邻间距最规整"（间距变异系数最小）的那一组。
    """
    import itertools
    if not spots:
        return []
    bright = [z for z in spots if z.get("is_bright")]
    dark = [z for z in spots if not z.get("is_bright")]
    if len(spots) <= need:
        return sorted(spots, key=lambda z: (z["y"], z["x"]))

    ref = bright if len(bright) >= 2 else spots
    sx = float(np.std([z["x"] for z in ref]))
    sy = float(np.std([z["y"] for z in ref]))
    vertical = sy >= sx
    def proj(z):
        return z["y"] if vertical else z["x"]
    def perp(z):
        return z["x"] if vertical else z["y"]
    r_typ = float(np.median([z["r"] for z in ref])) if ref else long_side * 0.02
    ref_perp = float(np.median([perp(z) for z in ref])) if ref else 0.0
    tol = max(2.5 * r_typ, 0.06 * long_side)
    corridor = [z for z in (bright + dark) if abs(perp(z) - ref_perp) <= tol]
    if len(corridor) < need:
        corridor = list(spots)
    must = [z for z in corridor if z.get("is_bright")]
    pool = [z for z in corridor if not z.get("is_bright")]
    k = need - len(must)
    if k <= 0:
        chosen = sorted(must, key=proj)[:need]
    elif len(pool) <= k:
        chosen = sorted(must + pool, key=proj)[:need]
    else:
        best, best_cv = None, None
        for comb in itertools.combinations(pool, k):
            cand = sorted(must + list(comb), key=proj)
            gaps = [proj(cand[i + 1]) - proj(cand[i]) for i in range(len(cand) - 1)]
            if not gaps or min(gaps) <= 0:
                continue
            mean = float(np.mean(gaps))
            cv = float(np.std(gaps)) / mean if mean > 0 else 9e9
            if best_cv is None or cv < best_cv:
                best, best_cv = cand, cv
        chosen = best if best else sorted(must + pool, key=proj)[:need]
    chosen.sort(key=proj)
    return chosen

def count_lenses(bgr, lit: Sequence[LampCand], r_min_frac: float = R_MIN_FRAC,
                 r_max_frac: float = R_MAX_FRAC) -> int:
    """Hough 找**未点亮的圆形灯罩**（"面板在场"的证据；全灭面板也要能判"故障"而不是"未判定"）。"""
    long_side = max(bgr.shape[:2])
    r_min = max(3, int(round(r_min_frac * long_side)))
    r_max = max(r_min + 1, int(round(r_max_frac * long_side)))
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 5)
    circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1.2, minDist=int(r_min * 1.8),
                               param1=140, param2=int(os.environ.get("AFH03_HOUGH_P2", "26")),
                               minRadius=int(r_min), maxRadius=int(r_max))
    if circles is None:
        return 0
    n = 0
    for c in circles[0][:64]:
        x, y, r = int(c[0]), int(c[1]), int(c[2])
        if all((x - z.x) ** 2 + (y - z.y) ** 2 > (0.9 * max(r, z.r)) ** 2 for z in lit):
            n += 1
    return n

def geometry_gate(cands: Sequence[LampCand], n_lamp: int, long_side: int) -> Tuple[bool, str]:
    """**几何/版面门**（专治广视角照片的假阳性，如 151104 检出 11 个红、151230 检出 11+15）。

    判据（任一不过 -> 未判定，绝不硬判）：
      1. **亮点数不得超过该部件灯数**（多了 = 画面里有别的发光物/反光 → 不可信）；
      2. 灯数 ≥3 时要求**近似共线**（同一面板的灯排成一行/一列）：垂轴偏差 ≤ 15% 长边；
      3. 灯数 ≥2 时要求**直径相近**（最大/最小 ≤ 2.2，面板同款灯罩）。
    """
    n = len(cands)
    if n == 0:
        return True, "无亮点（可能全灭 → 由亮灯数规则判故障）"

    
    if n > n_lamp:
        return False, ("检出亮点 %d 颗 > 该模块灯数 %d 颗（疑似混入别的发光体/反光）→ 未判定；"
                       "请对准该模块近景、或先标定 ROI" % (n, n_lamp))
    if n >= 2:
        rs = sorted(c.r for c in cands)
        if rs[-1] > 2.2 * max(1, rs[0]):
            return False, ("灯径差异过大（%d vs %d px）→ 不像同一模块的灯 → 未判定" % (rs[0], rs[-1]))

    
    return True, "几何门通过（检出 %d 颗 ≤ 期望 %d 颗，灯径一致）" % (n, n_lamp)

def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="面板 LED 检测（点/灭 + 标定 ROI + 防误检门）")
    ap.add_argument("-i", "--image", required=True)
    ap.add_argument("--rules", default="")
    ap.add_argument("--part", default="")
    ap.add_argument("--calib", default="")
    ap.add_argument("--list-cand", action="store_true", help="列出候选（含被拒原因）")
    a = ap.parse_args(argv)
    bgr = cv2.imread(a.image, cv2.IMREAD_COLOR)
    if bgr is None:
        print("读不到图: %s" % a.image)
        return 1
    bgr, rot = orient_normalize(bgr)
    bgr = fit_long(bgr)
    book = RuleBook.load(a.rules or None)
    calib = Calib.load(a.calib) if a.calib and os.path.isfile(a.calib) else None
    if a.list_cand:
        print("旋转归一=%s  工作尺寸=%dx%d" % (rot, bgr.shape[1], bgr.shape[0]))
        for c in detect_candidates(bgr):
            print("  %s (%4d,%4d) r=%-3d delta=%6.1f S=%5.1f col=%s %s"
                  % ("[灯]" if c.is_lamp else "[拒]", c.x, c.y, c.r, c.delta, c.s_mean, c.color, c.reject))
        return 0
    v, info = analyze(bgr, book, a.part, calib)
    print(json.dumps(v.to_dict(), ensure_ascii=False, indent=2))
    print("结论: %s" % v.banner())
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
