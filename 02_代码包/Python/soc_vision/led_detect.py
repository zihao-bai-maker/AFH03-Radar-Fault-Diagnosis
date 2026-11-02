"""LED 亮/灭判定（SoC 侧兜底实现 + 与 FPGA 判决融合）。

两种数据来源
------------
1. **FPGA 侧判亮（首选）**：`项目_FPGA侧设计.md` 里 `cam_stat_regs.v` 对 8 个 ROI 做
   颜色累加 + 阈值 + 时间去抖，结果塞进 CSI-2 首行（`fpga_status.py` 解出）。
   本模块的 `fuse()` 会用 FPGA 的判决作为最终值，同时保留软件计算值用于交叉验证。
2. **SoC 侧兜底**：本文件的 `LedDetector`，HSV/亮度阈值 + 迟滞 + 时间去抖。

现场标定的关键（不做这两件事，亮度阈值一定飘）
----------------------------------------------
* **锁曝光/增益**：`v4l2-ctl -d /dev/video22 --set-ctrl=exposure_auto=1 --set-ctrl=exposure_absolute=N`
  （rkisp 的 imx415 路径同理；板上没有的可控项就只能靠 FPGA 固定 AE）。
  否则 LED 点亮会让全画面变亮，单点阈值必然误判。
* **采"全灭"基线**：让所有目标 LED 熄灭，跑 `--calibrate` 采 N 帧，得到每个 ROI 的
  平均亮度与标准差；判定用"相对基线的抬升"，而不是绝对亮度。
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    import cv2
except Exception:                                           
    cv2 = None                                              

from .config import LedCfg, LedItemCfg, ROI
from .fpga_status import FpgaStatus

@dataclass
class LedState:
    name: str
    on: bool
    score: float                 
    dv: float = 0.0              
    color_ratio: float = 0.0
    source: str = "sw"           
    changed: bool = False        
    raw_metric: float = 0.0
    valid: bool = True           
    reason: str = ""             

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "on": bool(self.on),
                "score": round(float(self.score), 1),
                "dv": round(float(self.dv), 1),
                "color_ratio": round(float(self.color_ratio), 3),
                "source": self.source, "changed": bool(self.changed),
                "valid": bool(self.valid), "reason": self.reason}

@dataclass
class LedGate:
    """**防误检门**：ROI/标记不全就**拒绝出判定**，绝不为凑数而凭空给结果。

    与"SoC 侧标记门"同一思路：需要的输入不齐 -> 不出结论，并给出具体原因。
    """
    ok: bool = False
    reason: str = ""
    n_items: int = 0
    n_valid: int = 0
    invalid: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": bool(self.ok), "reason": self.reason, "n_items": self.n_items,
                "n_valid": self.n_valid, "invalid": list(self.invalid)}

@dataclass
class LedBaseline:
    """每个 LED 的"全灭"基线。"""
    v_mean: Dict[str, float] = field(default_factory=dict)
    v_std: Dict[str, float] = field(default_factory=dict)

    def to_json(self) -> Dict[str, Any]:
        return {"v_mean": self.v_mean, "v_std": self.v_std}

    @staticmethod
    def from_json(d: Dict[str, Any]) -> "LedBaseline":
        return LedBaseline(v_mean=dict(d.get("v_mean", {})),
                           v_std=dict(d.get("v_std", {})))

def _crop(img: np.ndarray, roi: ROI) -> np.ndarray:
    x, y, w, h = roi
    H, W = img.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return img[0:1, 0:1]
    return img[y0:y1, x0:x1]

def _robust_bg_v(hsv_v: np.ndarray, q: float = 25.0) -> float:
    """用分位数估计"背景亮度"，比均值更抗 LED 自身高亮像素的影响。"""
    return float(np.percentile(hsv_v, q))

class LedDetector:
    def __init__(self, cfg: LedCfg, baseline: Optional[LedBaseline] = None):
        self.cfg = cfg
        if cv2 is None:                                     
            raise RuntimeError("需要 cv2：bash install_ai_env.sh")
        self.baseline = baseline or LedBaseline()

        self.on_thr: Dict[str, float] = {}
        self.off_thr: Dict[str, float] = {}
        for it in cfg.items:
            self._set_thresholds(it)

        self._cnt: Dict[str, int] = {it.name: 0 for it in cfg.items}
        self._state: Dict[str, bool] = {it.name: False for it in cfg.items}
        self.last_gate: Optional["LedGate"] = None

    def _set_thresholds(self, it: LedItemCfg) -> None:
        std = self.baseline.v_std.get(it.name, 0.0)

        auto = 3.0 * std
        self.on_thr[it.name] = max(it.on_thr, min(auto, it.on_thr * 3.0))
        self.off_thr[it.name] = max(it.off_thr, min(0.6 * auto, it.off_thr * 3.0))
        if self.off_thr[it.name] >= self.on_thr[it.name]:
            self.off_thr[it.name] = 0.7 * self.on_thr[it.name]

    def gate(self, shape) -> LedGate:
        """检查"这一路 LED 判定该不该出结果"。返回 LedGate（ok=False 时必须拒绝采信）。

        判据（任一不满足即拒绝）：
          * `led.enabled` 为真、`led.items` 非空；
          * 每个 ROI 宽高合法、面积 ≥16 px、≤ `max_roi_area_frac` 倍画面面积、且**完全在画面内**；
          * 有效 ROI 数 ≥ 需要数（`require_all_rois=True` 时要求**全部**有效）。
        """
        items = self.cfg.items
        g = LedGate(n_items=len(items))
        if not self.cfg.enabled:
            g.reason = "配置里 led.enabled=false（未启用 LED 判定）"
            return g
        if not items:
            g.reason = "配置里 led.items 为空（**没有标定任何 LED ROI**）→ 拒绝出判定"
            return g
        H, W = int(shape[0]), int(shape[1])
        max_area = float(self.cfg.max_roi_area_frac) * H * W
        for it in items:
            try:
                x, y, w, h = [int(v) for v in it.roi]
            except Exception:                                     
                g.invalid.append("%s(ROI 非法)" % it.name)
                continue
            bad = ""
            if w <= 0 or h <= 0:
                bad = "宽高非法 %dx%d" % (w, h)
            elif w * h < 16:
                bad = "面积过小 %d px" % (w * h)
            elif w * h > max_area:
                bad = "面积过大 %.1f%% 画面(>%.0f%%)" % (w * h * 100.0 / max(1, H * W),
                                                        self.cfg.max_roi_area_frac * 100)
            elif x < 0 or y < 0 or x + w > W or y + h > H:
                bad = "越界 x=%d,y=%d,%dx%d > %dx%d" % (x, y, w, h, W, H)
            if bad:
                g.invalid.append("%s(%s)" % (it.name, bad))
            else:
                g.n_valid += 1
        need = len(items) if self.cfg.require_all_rois else max(1, int(self.cfg.min_valid_rois))
        if g.n_valid < need:
            g.reason = ("有效 ROI %d < 需要 %d：%s → **拒绝出判定**（不凭空给结果）"
                        % (g.n_valid, need, "; ".join(g.invalid) or "-"))
            return g
        g.ok = True
        g.reason = "ROI 校验通过（有效 %d/%d）" % (g.n_valid, len(items))
        return g

    def set_baseline(self, baseline: LedBaseline) -> None:
        self.baseline = baseline
        for it in self.cfg.items:
            self._set_thresholds(it)

    def calibrate(self, frames: Sequence[np.ndarray]) -> LedBaseline:
        """用若干帧"LED 全灭"的画面估基线。"""
        acc: Dict[str, List[float]] = {it.name: [] for it in self.cfg.items}
        for f in frames:
            hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
            v = hsv[:, :, 2]
            for it in self.cfg.items:
                patch = _crop(v, it.roi)
                acc[it.name].append(_robust_bg_v(patch))
        bl = LedBaseline()
        for name, vals in acc.items():
            if vals:
                bl.v_mean[name] = float(np.mean(vals))
                bl.v_std[name] = float(np.std(vals))
        self.set_baseline(bl)
        return bl

    def _metric(self, it: LedItemCfg, bgr: np.ndarray) -> Tuple[float, float, float]:
        """返回 (metric, dv, color_ratio)。"""
        patch = _crop(bgr, it.roi)
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        v = hsv[:, :, 2]
        base = self.baseline.v_mean.get(it.name)
        if base is None:

            gv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[:, :, 2]
            base = _robust_bg_v(gv)
        dv = float(np.mean(v)) - float(base)

        lo = np.array(it.hsv_lo, dtype=np.uint8)
        hi = np.array(it.hsv_hi, dtype=np.uint8)
        mask = cv2.inRange(hsv, lo, hi)
        color_ratio = float(np.count_nonzero(mask)) / max(1, mask.size)

        mode = it.mode
        if mode == "bright":
            metric = dv
        elif mode == "color":
            metric = color_ratio * 255.0
        else:  
            metric = dv if color_ratio >= it.min_color_ratio else min(dv, 0.5 * self.off_thr[it.name])
        return metric, dv, color_ratio

    def detect(self, bgr: np.ndarray,
               fpga: Optional[FpgaStatus] = None,
               return_gate: bool = False):
        """判 LED 亮灭。

        **先过防误检门**：门不过时返回的每个 LedState 都带 `valid=False` + `reason`，
        且 `on` 一律为 False —— 调用方**必须**据此显示"未标定/拒绝出判定"，不得当作 OFF。
        """
        gate = self.gate(bgr.shape)
        self.last_gate = gate
        if not gate.ok:
            states = [LedState(name=it.name, on=False, score=0.0, source="sw",
                               valid=False, reason=gate.reason) for it in self.cfg.items]
            return (states, gate) if return_gate else states
        states: List[LedState] = []
        for it in self.cfg.items:
            metric, dv, ratio = self._metric(it, bgr)
            on_raw = metric >= self.on_thr[it.name]
            off_raw = metric <= self.off_thr[it.name]
            prev = self._state[it.name]
            if on_raw and not prev:
                self._cnt[it.name] += 1
            elif off_raw and prev:
                self._cnt[it.name] -= 1
            else:

                self._cnt[it.name] = 0
            new = prev
            if self._cnt[it.name] >= self.cfg.debounce_n:
                new, self._cnt[it.name] = True, 0
            elif self._cnt[it.name] <= -self.cfg.debounce_n:
                new, self._cnt[it.name] = False, 0
            changed = (new != prev)
            self._state[it.name] = new
            states.append(LedState(name=it.name, on=new, score=metric, dv=dv,
                                   color_ratio=ratio, source="sw",
                                   changed=changed, raw_metric=metric))
        if fpga is not None and fpga.present and self.cfg.use_fpga_status:
            states = fuse(states, fpga, self.cfg.items)
        return (states, gate) if return_gate else states

    def check_expect(self, states: List[LedState]) -> List[str]:
        bad = []
        by = {s.name: s for s in states}
        for it in self.cfg.items:
            if it.expect is None or it.name not in by:
                continue
            if bool(by[it.name].on) != bool(it.expect):
                bad.append("%s 期望 %s 实际 %s (score=%.1f)"
                           % (it.name, "ON" if it.expect else "OFF",
                              "ON" if by[it.name].on else "OFF", by[it.name].score))
        return bad

def fuse(states: List[LedState], fpga: FpgaStatus,
         items: Sequence[LedItemCfg]) -> List[LedState]:
    """FPGA 判决优先，软件结果保留在 score/dv 里做交叉验证。

    约定：ROI 编号 n 对应配置里第 n 个 LED（顺序必须一致，见 config 注释）。
    """
    bits = fpga.lit_bits(max(len(items), 8))
    for i, st in enumerate(states):
        if i < len(bits):
            st.source = "fpga"
            st.on = bool(bits[i])
    return states

def _load_frames(path: str, n: int) -> List[np.ndarray]:
    if os.path.isdir(path):
        fs = sorted(os.path.join(path, f) for f in os.listdir(path)
                    if f.lower().endswith((".png", ".jpg", ".bmp")))
        return [cv2.imread(f) for f in fs[:n] if cv2.imread(f) is not None]
    img = cv2.imread(path)
    return [img] if img is not None else []

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="LED 亮灭判定（离线图片 / 单帧调参）")
    ap.add_argument("--config", required=True, help="JSON 配置")
    ap.add_argument("--dark", help="LED 全灭的图或目录（做基线）")
    ap.add_argument("--test", help="待判定的图或目录")
    ap.add_argument("--out-baseline", default="", help="把基线写成 JSON")
    a = ap.parse_args(argv)

    from .config import AppCfg
    with open(a.config, "r", encoding="utf-8") as f:
        cfg = AppCfg.from_dict(json.load(f))

    det = LedDetector(cfg.led)
    if a.dark:
        frames = _load_frames(a.dark, cfg.led.baseline_frames)
        if not frames:
            print("读不到 --dark 的图"); return 1
        bl = det.calibrate(frames)
        print("基线: " + json.dumps(bl.to_json(), ensure_ascii=False))
        for it in cfg.led.items:
            print("  %-10s thr on=%.1f off=%.1f" %
                  (it.name, det.on_thr[it.name], det.off_thr[it.name]))
        if a.out_baseline:
            with open(a.out_baseline, "w", encoding="utf-8") as f:
                json.dump(bl.to_json(), f, ensure_ascii=False, indent=2)
            print("基线已写 %s" % a.out_baseline)
    if a.test:
        frames = _load_frames(a.test, 32)
        if not frames:
            print("读不到 --test 的图"); return 1

        for f in frames * max(1, cfg.led.debounce_n):
            st = det.detect(f)
        for s in st:
            print("  %-10s %s  score=%7.1f dv=%7.1f ratio=%.3f"
                  % (s.name, "ON " if s.on else "OFF", s.score, s.dv, s.color_ratio))
        bad = det.check_expect(st)
        if bad:
            print("期望不符:"); [print("   " + b) for b in bad]
            return 2
    return 0

if __name__ == "__main__":                                  
    raise SystemExit(main())
