"""示波器屏幕波形识别：从一帧图像里算频率(Hz)与振幅(Vpp)。

输入：一帧 BGR 图 + 标定（时基 s/div、垂直 V/div、探头衰减、屏幕格数）
输出：frequency_hz、vpp_v，外加自相关/过零两条独立估计做交叉验证

算法链路
--------
1. ROI 裁剪（只留波形显示区，去掉边框/菜单/右下角读数）
2. 波形像素分割
   a. HSV 颜色分割（示波器波形一般是亮黄/青/品红，网格是低饱和灰 -> 天然可分）
   b. 兜底："比背景亮"阈值（bg 中位数 + k*MAD）
   两者取 OR，再形态学闭运算 + 去小连通域
3. 逐列求波形上下沿 -> 中心线 y_mid(x)
   * 同一列可能有多个连续段（陡沿会形成长竖段），用"与上一列中点最近"的段做连续性跟踪
   * 无波形的列标记为 NaN，最后线性插值补上
4. 电压换算
   V = (gnd_y - y) * (V/div) / px_per_div * 探头衰减
   Vpp = (y_max - y_min) * 系数   （默认用 0.5/99.5 分位，抗单点噪点）
5. 周期估计（两条独立路径）
   * 自相关：去均值 -> FFT 自相关 -> 取"第一个足够强的局部极大"作为基波周期，
     抛物线插值到亚像素。这样可避免把 2 倍周期当成周期（谐波陷阱）
   * 过零：去均值 -> 上升沿线性插值求穿越点 -> 首尾跨度 / 间隔数（最稳的均值周期）
   两者相差 <15% 才认为是可信一致
6. 换算
   dt_per_px = (time/div) / px_per_div_x
   f = 1 / (period_px * dt_per_px)
   Nyquist = 1 / (2 * dt_per_px)，period_px < 5 时提示"可能混叠，请减小 time/div"

标定要点（现场必须提供/确认）
------------------------------
* time/div 与 V/div 直接读示波器面板，注意单位（ms/div、V/div）
* 探头衰减 ×1/×10/×100 必须乘回去
* 屏幕格数通常 10 x 8，但有些机型 12 x 8 或 14 x 8，要按实际数
* 若示波器有 "0V 基准" 标记，给出 gnd_y_px；否则只能得到相对值（Vpp 不受影响）
* 锁住示波器的触发（AUTO/NORMAL 都行），但不要开 "Roll" 模式
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

from .config import ScopeCfg

@dataclass
class ScopeResult:
    ok: bool = False
    freq_hz: float = 0.0
    vpp_v: float = 0.0
    vmax_v: float = 0.0
    vmin_v: float = 0.0
    vmean_v: float = 0.0
    period_px: float = 0.0
    cycles_on_screen: float = 0.0
    valid_col_ratio: float = 0.0
    dt_per_px_s: float = 0.0
    nyquist_hz: float = 0.0
    aliasing_suspect: bool = False
    ac_peak: float = 0.0
    zero_cross_n: int = 0
    freq_autocorr_hz: float = 0.0
    freq_zerocross_hz: float = 0.0
    freq_fft_hz: float = 0.0
    estimators_agree: bool = False
    confidence: float = 0.0
    mask_ratio: float = 0.0
    used_fallback: bool = False

    expect_hz: float = 0.0
    expect_hz_tol_pct: float = 0.0
    freq_dev_pct: float = 0.0        
    freq_ok: Optional[bool] = None   
    nominal_hz: float = 0.0          
    nearest_hz: float = 0.0          
    nearest_dev_pct: float = 0.0
    verdict: str = ""                
    label: str = ""                  
    message: str = ""
    debug: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {k: (round(v, 6) if isinstance(v, float) else v)
             for k, v in self.__dict__.items() if k != "debug"}
        return d

def _fmt_hz_short(v: float) -> str:
    """20e6 -> "20M"，1e3 -> "1k"（只用于消息里的白名单展示）。"""
    a = abs(v)
    if a >= 1e6:
        return "%gM" % (v / 1e6)
    if a >= 1e3:
        return "%gk" % (v / 1e3)
    return "%g" % v

def _largest_components(mask: np.ndarray, min_area: int, keep_top: int = 4) -> np.ndarray:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return mask
    order = np.argsort(-stats[1:, cv2.CC_STAT_AREA]) + 1
    out = np.zeros_like(mask)
    kept = 0
    for lbl in order:
        if stats[lbl, cv2.CC_STAT_AREA] < min_area:
            break
        out[labels == lbl] = 255
        kept += 1
        if kept >= keep_top:
            break
    return out if kept else mask

def waveform_mask(roi_bgr: np.ndarray, cfg: ScopeCfg) -> Tuple[np.ndarray, Dict[str, Any]]:
    """返回 (mask 0/255, info)。"""
    if cv2 is None:                                         
        raise RuntimeError("需要 cv2")
    h, w = roi_bgr.shape[:2]
    area = h * w
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    lo = np.array(cfg.wave_hsv_lo, dtype=np.uint8)
    hi = np.array(cfg.wave_hsv_hi, dtype=np.uint8)
    m_color = cv2.inRange(hsv, lo, hi)
    info: Dict[str, Any] = {"color_ratio": float(np.count_nonzero(m_color)) / max(1, area)}

    mask = m_color
    used_fallback = False

    if info["color_ratio"] < 0.0015 and cfg.bright_fallback:
        gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
        bg = float(np.median(gray))
        mad = float(np.median(np.abs(gray.astype(np.float32) - bg)))
        thr = bg + max(18.0, 5.0 * mad)
        m_bright = cv2.inRange(gray, int(min(255, int(thr))), 255)
        if cfg.invert_wave:
            m_bright = cv2.bitwise_not(m_bright)
        mask = cv2.bitwise_or(m_color, m_bright)
        used_fallback = True
        info["thr"] = thr
        info["bg"] = bg
        info["mad"] = mad

    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=1)
    mask = _largest_components(mask, min_area=max(20, int(0.0004 * area)))
    info["mask_ratio"] = float(np.count_nonzero(mask)) / max(1, area)
    info["used_fallback"] = used_fallback
    return mask, info

def trace_centerline(mask: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """返回 (y_mid, y_top, y_bot, valid)。NaN 表示该列没找到波形。"""
    h, w = mask.shape
    y_top = np.full(w, np.nan)
    y_bot = np.full(w, np.nan)
    y_mid = np.full(w, np.nan)
    prev_mid: Optional[float] = None
    for x in range(w):
        idx = np.flatnonzero(mask[:, x])
        if idx.size == 0:
            prev_mid = None
            continue
        splits = np.flatnonzero(np.diff(idx) > 1) + 1
        runs = np.split(idx, splits)
        if prev_mid is None:
            best = max(runs, key=lambda r: r.size)
        else:
            def cost(r: np.ndarray) -> float:
                mid = 0.5 * (r[0] + r[-1])
                return abs(mid - prev_mid) + (0.0 if r.size >= 2 else 3.0)
            best = min(runs, key=cost)
        y_top[x] = float(best[0])
        y_bot[x] = float(best[-1])
        y_mid[x] = 0.5 * (best[0] + best[-1])
        prev_mid = y_mid[x]
    valid = ~np.isnan(y_mid)
    return y_mid, y_top, y_bot, valid

def _interp_nan(y: np.ndarray) -> np.ndarray:
    valid = ~np.isnan(y)
    if valid.sum() == 0:
        return np.zeros_like(y)
    xi = np.arange(y.size, dtype=np.float64)
    return np.interp(xi, xi[valid], y[valid])

def _smooth(y: np.ndarray, k: int = 3) -> np.ndarray:
    if k <= 1 or y.size < k:
        return y
    ker = np.ones(k, dtype=np.float64) / k
    pad = k // 2
    yp = np.pad(y, pad, mode="edge")
    return np.convolve(yp, ker, mode="valid")[: y.size]

def estimate_grid_pitch(gray: np.ndarray, axis: int = 1) -> Optional[float]:
    """估计每格像素数：对投影做**自相关**取基波周期（比 FFT 取最强峰稳得多）。

    为什么不直接用 FFT 最强峰：网格线是"每格一根的脉冲串"，它的频谱是一排
    幅度相近的谐波，argmax 很容易落到高频谐波上（实测：700px/50px 的网格被判成
    无效）。自相关 + "深谷后第一个峰"的选法对这种脉冲串很稳。
    """
    prof = gray.mean(axis=0 if axis == 1 else 1).astype(np.float64)
    if prof.size < 32:
        return None
    p, peak, _ = period_autocorr(prof, min_lag=4, max_lag=prof.size // 3)
    if p is None or peak < 0.2 or p < 4:
        return None
    return float(p)

def detect_grid_lines(gray: np.ndarray, axis: int = 1,
                      min_prominence: float = 3.0) -> List[int]:
    """检测网格竖线/横线的像素位置（网格线比背景亮）。

    axis=1 -> 沿 x 方向找竖线；axis=0 -> 沿 y 方向找横线。
    注意：RIGOL 等机器每大格中间还有若干条**虚线**，如果虚线也被检出来，
    连续两线的间距就是"小格"，需要把 cfg.grid_subdiv 设成每大格的小格数
    （RIGOL 通常 5）。本项目用 expect_hz 做合格判定，一旦倍数搞错会立刻 FAIL 暴露出来。
    """
    prof = gray.mean(axis=0 if axis == 1 else 1).astype(np.float64)
    if prof.size < 16:
        return []
    prof = prof - float(np.median(prof))
    sm = _smooth(prof, 3)
    hi = float(np.percentile(sm, 99.0))
    thr = max(min_prominence, 0.25 * hi)
    out: List[int] = []
    for i in range(1, sm.size - 1):
        if sm[i] > sm[i - 1] and sm[i] >= sm[i + 1] and sm[i] > thr:
            out.append(i)

    if len(out) > 1:
        keep = [out[0]]
        for p in out[1:]:
            if p - keep[-1] < 3:
                if sm[p] > sm[keep[-1]]:
                    keep[-1] = p
            else:
                keep.append(p)
        out = keep
    return out

def resolve_px_per_div(gray: np.ndarray, axis: int, cfg: ScopeCfg,
                       size_px: int, default_div: float) -> Tuple[float, Dict[str, float], float]:
    """决定"每格多少像素"。返回 (px_per_div, 各候选值, 网格线跨度)。

    优先级（最鲁棒的在前）：
      1) cfg.px_per_div_x/y 人工标定值（调用方已处理，不走这里）
      2) `grid_pattern`：**投影的自相关基波周期**。示波器网格的亮度图案
         （亮主线 + 若干暗虚线）是"每个大格重复一次"的，所以它的基波周期
         就是每大格像素数 —— 这一条**不依赖任何关于格数的假设**，是最干净的方法。
      3) `line_pitch` = 相邻检出线间距中位数 × 每大格小格数（个别线被菜单遮挡也不怕，
         但要靠 cfg.grid_subdiv 或"检出线数"判别是否正确）
      4) `span/(n-1)`、`span/h_div`
      5) ROI 尺寸 / 默认格数（最差兜底）

    关于"每大格有几条小格线"（`grid_subdiv`）：RIGOL 一大格中间有若干虚线。
    如果虚线没被检出（对比度低），线距就等于大格间距，此时再乘 subdiv 会整体差 5 倍。
    这里用"检出线数"做自动判别：线数 ~= 大格数+1 说明检到的都是主线 -> 系数取 1；
    线数 ~= 大格数*subdiv+1 说明检到了虚线 -> 用配置的 subdiv。判别结果放在 debug 里。
    """
    subdiv = max(1, int(getattr(cfg, "grid_subdiv", 1) or 1))
    hint = getattr(cfg, "grid_h_div_hint", None) if axis == 1 else None
    cands: Dict[str, float] = {}
    pat_p = estimate_grid_pitch(gray, axis)
    if pat_p:
        cands["grid_pattern"] = float(pat_p)

    lines = detect_grid_lines(gray, axis)
    span = float(lines[-1] - lines[0]) if len(lines) >= 2 else 0.0
    nl = len(lines)
    subdiv_eff = subdiv
    if hint and nl >= 2:
        if abs(nl - (hint + 1)) <= 2:
            subdiv_eff = 1
        elif abs(nl - (hint * subdiv + 1)) <= max(3, int(0.15 * hint * subdiv)):
            subdiv_eff = subdiv
    if nl >= 2:
        diffs = np.diff(np.asarray(lines, dtype=np.float64))
        diffs = diffs[diffs >= 3.0]
        if diffs.size:
            cands["line_pitch"] = float(np.median(diffs)) * subdiv_eff
            cands["_median_line_gap_px"] = float(np.median(diffs))
            cands["_subdiv_eff"] = float(subdiv_eff)
            cands["_n_lines"] = float(nl)
        if nl >= 3:
            cands["span/(n-1)"] = span / float(nl - 1)
    if hint and span > 0:
        cands["span/h_div"] = span / float(hint)

    if "grid_pattern" in cands and "line_pitch" in cands:
        a, b = cands["grid_pattern"], cands["line_pitch"]
        cands["_pattern_vs_line_rel"] = abs(a - b) / max(a, b)

    for key in ("grid_pattern", "line_pitch", "span/(n-1)", "span/h_div"):
        if key in cands and cands[key] > 1.0:
            return cands[key], cands, span
    return max(1.0, size_px / max(1e-6, default_div)), cands, span

def period_autocorr(sig: np.ndarray, min_lag: int = 4,
                    max_lag: Optional[int] = None,
                    min_peak: float = 0.25) -> Tuple[Optional[float], float, np.ndarray]:
    """自相关求周期(像素)。返回 (period_px, 峰值强度, ac)。

    两个必须注意的点（都是实测踩出来的）：
    1. **必须用无偏自相关** ac_u(k) = ac(k)·N/(N-k)。有偏自相关随 lag 线性衰减，
       短 lag 的"斜坡"永远比真实周期的峰值高：T=250 的正弦在 k=10 处 ac≈0.96、
       在 k=250 处只有 0.88 —— 取全局最大会得到 10 而不是 250。
    2. 基波判定用"**深谷检验**"：候选局部极大 k 必须在 [k/2, k) 区间里出现过一个
       明显更低的谷（ac_u[k] - min(ac_u[k/2:k]) >= 0.4），然后在这些合格候选里取
       **最小的 k**。不要简单地取全局最大：低 lag 的噪声波纹峰在长周期信号上比真周期
       峰还高（T=137 含噪时 ac_u(5)=0.99 > ac_u(137)=0.81）；也不要取"深谷后的第一个峰"
       （深谷附近的噪声波纹会把 T=137 估成 66）；更不要按值取大于 0.95×峰值的峰
       （整数倍 2P/3P… 的无偏 ac_u 都≈1，会把 T=400 估成 800）。
    """
    x = sig.astype(np.float64) - float(np.mean(sig))
    n = x.size
    if max_lag is None:

        

        max_lag = max(min_lag + 2, int(n * 0.45))
    max_lag = int(min(max_lag, n - 1))
    if n < 16 or max_lag <= min_lag:
        return None, 0.0, np.zeros(1)
    nfft = 1
    while nfft < 2 * n:
        nfft <<= 1
    F = np.fft.rfft(x, nfft)
    ac = np.fft.irfft(F * np.conj(F), nfft)[: max_lag + 1]
    if ac[0] <= 1e-12:
        return None, 0.0, ac
    ac = ac / ac[0]
    ks = np.arange(ac.size, dtype=np.float64)
    bias = np.maximum(1.0 - ks / float(n), 1e-3)      

    
    ac_u = ac / bias
    peaks = [k for k in range(max(1, min_lag), max_lag)
             if ac_u[k] > ac_u[k - 1] and ac_u[k] >= ac_u[k + 1]]
    if not peaks:
        return None, 0.0, ac_u
    best_v = float(max(ac_u[k] for k in peaks))
    if best_v < min_peak:
        return None, best_v, ac_u

    

    

    

    

    
    valid: List[int] = []
    for k in peaks:
        if ac_u[k] < 0.90 * best_v:
            continue
        lo = int(max(1, min_lag, k // 2))
        dip = float(np.min(ac_u[lo:k])) if k > lo else float(ac_u[k])
        if ac_u[k] - dip >= 0.4:
            valid.append(k)
    if not valid:

        

        return None, best_v, ac_u
    p = min(valid)

    delta = 0.0
    if 0 < p < ac_u.size - 1:
        y0, y1, y2 = float(ac_u[p - 1]), float(ac_u[p]), float(ac_u[p + 1])
        den = y0 - 2.0 * y1 + y2
        if abs(den) > 1e-12:
            delta = float(np.clip(0.5 * (y0 - y2) / den, -0.5, 0.5))
    return p + delta, best_v, ac_u

def period_fft(sig: np.ndarray, min_cycles: float = 1.2
               ) -> Tuple[Optional[float], float]:
    """加窗 FFT + 对数幅度抛物线插值求周期(像素)。**准确度最高**，作为首选。

    返回 (period_px, snr_like)。做法：
      * Hann 窗抑制截断泄漏（示波器屏上通常不是整数个周期）；
      * 只在"周期 >= 4px"的频段找峰，挡住 DC 漂移；
      * 对数幅度上做抛物线插值（比线性幅度准得多）；
      * **次谐波护栏**：若 k/2 或 k/3 处的能量 >= 主峰的 0.5，说明真正基波在更低频
        （典型场景：二次谐波比基波还强），改取低频那个。
    """
    x = sig.astype(np.float64) - float(np.mean(sig))
    n = x.size
    if n < 16:
        return None, 0.0
    X = np.abs(np.fft.rfft(x * np.hanning(n)))
    kmax = max(2, int(n / 4))                       
    kmax = min(kmax, X.size - 2)
    if kmax < 3:
        return None, 0.0
    kmin = max(1, int(np.floor(min_cycles)))
    if kmin + 1 >= kmax:
        kmin = 1
    Xw = X.copy()
    Xw[:kmin] = 0.0
    Xw[kmax + 1:] = 0.0
    k = int(np.argmax(Xw))
    if k < 1 or X[k] <= 0:
        return None, 0.0
    eps = 1e-12
    if 1 <= k < X.size - 1:
        y0, y1, y2 = (float(np.log(X[k - 1] + eps)), float(np.log(X[k] + eps)),
                      float(np.log(X[k + 1] + eps)))
        den = y0 - 2.0 * y1 + y2
        d = float(np.clip(0.5 * (y0 - y2) / den, -0.5, 0.5)) if abs(den) > 1e-12 else 0.0
    else:
        d = 0.0
    kf = k + d

    for div in (2.0, 3.0):
        kk = int(round(kf / div))
        if kk >= 1 and X[kk] >= 0.5 * X[k]:
            kf = kf / div
            break
    period = n / kf
    band = X[kmin:kmax + 1]
    med = float(np.median(band)) if band.size else 0.0
    snr = float(X[k] / max(med, eps))
    return period, snr

def period_zerocross(sig: np.ndarray, hysteresis_ratio: float = 0.30,
                     smooth_len: int = 5) -> Tuple[Optional[float], int, float]:
    """施密特触发式过零求平均周期。返回 (period_px, 穿越点个数, 周期离散度cv)。

    cv = 相邻穿越间隔的标准差 / 均值，用来判断这次测量可不可信（建议 cv <= 0.04）。

    为什么不能直接用符号翻转：过零点附近信号在 0 附近抖动会产生大量假穿越
    （实测：T=137 的含噪正弦被估成 27.7 —— 5 倍错误）。这里做三件事：
      1. 先平滑（默认 5 点滑动平均），噪声降 ~2.2 倍，对 50px 级周期几乎不失真；
      2. 施密特门：信号必须先跌到 -h（h = ratio × 95 分位振幅），再升过 +h 才算一次上升；
      3. **回退到"正游程起点"**：从升过 +h 的位置往回走，遇到负样本就检查是不是浅坑
         （宽 <= 2 个样本且前后都是正）—— 是浅坑就跨过去继续回退，这样既能排除
         过零点抖动造成的假穿越，又不会把低占空比脉冲串的真实穿越排除掉。
    """
    s = _smooth(sig.astype(np.float64), max(1, int(smooth_len)))
    s = s - float(np.mean(s))
    n = s.size
    if n < 8:
        return None, 0, 0.0
    amp = float(np.percentile(np.abs(s), 95.0))
    if amp <= 1e-12:
        return None, 0, 0.0
    h = hysteresis_ratio * amp
    xs: List[float] = []
    armed = False
    for i in range(1, n):
        if s[i] <= -h:
            armed = True
            continue
        if not armed or s[i] < h:
            continue

        j = i
        while j > 1:
            if s[j - 1] >= 0.0:
                j -= 1
                continue
            k = j - 1
            while k > 1 and s[k - 1] < 0.0:
                k -= 1
            if (j - k) <= 2 and k > 1 and s[k - 1] >= 0.0:
                j = k
                continue
            break
        if j >= 1 and s[j - 1] < 0.0 <= s[j]:
            den = s[j] - s[j - 1]
            xs.append((j - 1) + (-s[j - 1]) / den if abs(den) > 1e-12 else float(j))
            armed = False
    if len(xs) < 2:
        return None, len(xs), 0.0
    d = np.diff(np.asarray(xs, dtype=np.float64))
    period = float((xs[-1] - xs[0]) / (len(xs) - 1))
    cv = float(np.std(d) / max(1e-9, np.mean(d))) if d.size else 0.0
    return period, len(xs), cv

def analyze_scope_frame(bgr: np.ndarray, cfg: ScopeCfg,
                        return_debug: bool = False) -> ScopeResult:
    """输入一帧 BGR（numpy uint8 HxWx3），输出 ScopeResult。"""
    r = ScopeResult()
    if cv2 is None:                                         
        r.message = "cv2 不可用"
        return r
    if bgr is None or bgr.size == 0:
        r.message = "空帧"
        return r

    x0, y0, w, h = cfg.roi
    H, W = bgr.shape[:2]
    x1, y1 = min(W, x0 + w), min(H, y0 + h)
    x0c, y0c = max(0, x0), max(0, y0)
    if x1 - x0c < 32 or y1 - y0c < 32:
        r.message = "ROI 太小或超出画面 (%s)" % (cfg.roi,)
        return r
    roi = bgr[y0c:y1, x0c:x1]
    rh, rw = roi.shape[:2]

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    ppd_x = cfg.px_per_div_x
    ppd_y = cfg.px_per_div_y
    if ppd_x is None:
        ppd_x, cands_x, span_x = resolve_px_per_div(gray, 1, cfg, rw, cfg.h_div)
        r.debug["grid_x"] = {"cands": cands_x, "span_px": span_x}
        if cfg.grid_h_div_hint and "span/h_div" not in cands_x:
            r.debug["grid_x_hint_ignored"] = "没检出足够网格线，退回其它候选"
    if ppd_y is None:
        ppd_y, cands_y, span_y = resolve_px_per_div(gray, 0, cfg, rh, cfg.v_div)
        r.debug["grid_y"] = {"cands": cands_y, "span_px": span_y}
    ppd_x = float(max(1.0, ppd_x))
    ppd_y = float(max(1.0, ppd_y))
    v_per_px = cfg.volt_per_div_v / ppd_y * cfg.probe_atten
    dt_per_px = cfg.time_per_div_s / ppd_x
    r.dt_per_px_s = dt_per_px
    r.nyquist_hz = 0.5 / dt_per_px if dt_per_px > 0 else 0.0

    mask, minfo = waveform_mask(roi, cfg)
    r.mask_ratio = minfo["mask_ratio"]
    r.used_fallback = bool(minfo["used_fallback"])
    y_mid, y_top, y_bot, valid = trace_centerline(mask)
    vratio = float(valid.sum()) / float(rw)
    r.valid_col_ratio = vratio
    if vratio < cfg.min_valid_col_ratio:
        r.message = ("波形像素太少: 有效列 %.1f%% < %.1f%%（检查 ROI/波形颜色/曝光，"
                     "或把 wave_hsv_lo/hi 调宽、打开 bright_fallback）"
                     % (vratio * 100, cfg.min_valid_col_ratio * 100))
        if return_debug:
            r.debug["mask"] = mask
        return r

    y_f = _interp_nan(y_mid)

    if cfg.gnd_y_px is not None:
        gnd = float(cfg.gnd_y_px) - y0c          
    else:
        gnd = float(np.median(y_f))
        r.debug["gnd_assumed"] = True
    if cfg.robust_percentile:
        lo_p = float(np.percentile(y_f, 0.5))
        hi_p = float(np.percentile(y_f, 99.5))
    else:
        lo_p = float(np.min(y_f))
        hi_p = float(np.max(y_f))
    vpp = (hi_p - lo_p) * v_per_px
    v_of = lambda yy: (gnd - yy) * v_per_px
    r.vpp_v = float(vpp)
    r.vmax_v = float(v_of(lo_p))
    r.vmin_v = float(v_of(hi_p))
    r.vmean_v = float(v_of(float(np.mean(y_f))))

    y_s = _smooth(y_f, 3)
    p_fft, fft_snr = period_fft(y_s)
    p_ac, ac_peak, ac = period_autocorr(y_s)
    p_zc, n_zc, zc_cv = period_zerocross(y_s)
    r.ac_peak = float(ac_peak)
    r.zero_cross_n = int(n_zc)
    r.debug["fft_snr"] = float(fft_snr)
    r.debug["period_fft_px"] = float(p_fft) if p_fft else None
    r.debug["period_ac_px"] = float(p_ac) if p_ac else None
    r.debug["period_zc_px"] = float(p_zc) if p_zc else None
    r.debug["zc_cv"] = float(zc_cv)
    if p_fft:
        r.freq_fft_hz = 1.0 / (p_fft * dt_per_px) if p_fft * dt_per_px > 0 else 0.0
    if p_ac:
        r.freq_autocorr_hz = 1.0 / (p_ac * dt_per_px) if p_ac * dt_per_px > 0 else 0.0
    if p_zc:
        r.freq_zerocross_hz = 1.0 / (p_zc * dt_per_px) if p_zc * dt_per_px > 0 else 0.0

    zc_ok = bool(p_zc and n_zc >= 3 and zc_cv <= 0.04)
    ests: List[Tuple[str, float]] = []
    if p_fft:
        ests.append(("fft", float(p_fft)))
    if p_ac:
        ests.append(("ac", float(p_ac)))
    if zc_ok:
        ests.append(("zc", float(p_zc)))

    period: Optional[float] = None
    msgs: List[str] = []
    only_zc = False
    primary = ""
    if len(ests) >= 2:
        best_pair, best_rel = None, 1e9
        for i in range(len(ests)):
            for j in range(i + 1, len(ests)):
                a, b = ests[i][1], ests[j][1]
                rel = abs(a - b) / max(a, b)
                if rel < best_rel:
                    best_rel, best_pair = rel, (ests[i], ests[j])
        if best_pair is not None and best_rel <= 0.05:
            period = 0.5 * (best_pair[0][1] + best_pair[1][1])
            primary = "%s+%s" % (best_pair[0][0], best_pair[1][0])
            r.estimators_agree = True
            rest = [e for e in ests if e not in best_pair]
            for e in rest:
                if abs(e[1] - period) / period > 0.05:
                    if e[0] == "ac" and p_fft and abs(round(e[1] / period) - e[1] / period) < 0.05 \
                            and round(e[1] / period) >= 2:
                        msgs.append("自相关给的是 %.0f 倍周期(%s)，按基波处理"
                                    % (round(e[1] / period), e[0]))
                    else:
                        msgs.append("第三个估计器(%s=%.1fpx)与共识不符，已忽略"
                                    % (e[0], e[1]))
    if period is None:

        if zc_ok:
            period, primary = float(p_zc), "zc"
            msgs.append("三个估计器互不一致(%s)，取过零(%.1fpx, cv=%.3f)"
                        % (", ".join("%s=%.1fpx" % e for e in ests), p_zc, zc_cv))
        elif p_fft:
            period, primary = float(p_fft), "fft"
            msgs.append("估计器不一致且过零质量不足(cv=%.3f)，取 FFT(%.1fpx)"
                        % (zc_cv, p_fft))
        elif p_ac:
            period, primary = float(p_ac), "ac"
    if period is None:
        r.message = "取不到周期：波形不是周期性信号，或 ROI / 阈值不对"
        return r
    if primary == "zc":
        only_zc = True
        if len(ests) <= 1:
            msgs.append("只有过零估计可用（自相关/FFT 无有效峰），可信度受限")

    r.period_px = float(period)
    r.freq_hz = 1.0 / (period * dt_per_px) if period * dt_per_px > 0 else 0.0
    r.cycles_on_screen = float(rw) / period
    n_agree = sum(1 for _, v in ests if abs(v - period) / max(period, 1e-9) <= 0.05)
    if period < 5.0:
        r.aliasing_suspect = True
        msgs.append("每周期只有 %.1f 像素，可能混叠（屏上采样率不足），请减小 time/div"
                    % period)
    if r.cycles_on_screen < 1.5:
        r.ok = False
        r.message = ("屏上只有 %.2f 个周期，频率估计不可信 —— 请把 time/div 调小"
                     "（目标：屏上 3~15 个周期。低频取 time/div ≈ 1/f；"
                     "高频要让一个周期占更多像素，取 time/div ≈ 0.3~0.5/f，"
                     "例如 20 MHz→20 ns/div、40 MHz→10 ns/div）" % r.cycles_on_screen)
        if return_debug:
            r.debug["period"] = period
        return r
    if r.cycles_on_screen > 40:
        msgs.append("屏上周期数过多（%.1f），自相关/FFT 可能锁到谐波，建议减小 time/div"
                    % r.cycles_on_screen)

    agree_f = {0: 0.40, 1: 0.55, 2: 0.85}.get(n_agree, 1.0)
    snr_f = float(np.clip((fft_snr - 1.5) / 6.0, 0.25, 1.0))
    r.confidence = float(np.clip(min(1.0, vratio / 0.85) * agree_f * snr_f, 0.0, 1.0))
    if only_zc:
        r.confidence = min(r.confidence, 0.45)
    r.ok = True

    

    
    names = cfg.nominal_list() if hasattr(cfg, "nominal_list") else (
        [float(cfg.expect_hz)] if (cfg.expect_hz and cfg.expect_hz > 0) else [])
    if names:
        r.expect_hz_tol_pct = float(cfg.expect_hz_tol_pct)
        best = min(names, key=lambda v: abs(v - r.freq_hz))
        dev = (r.freq_hz - best) / best * 100.0 if best else 0.0
        r.expect_hz = float(best)
        r.nominal_hz = float(best)
        r.freq_dev_pct = dev
        r.nearest_hz = float(best)
        r.nearest_dev_pct = dev
        r.freq_ok = abs(dev) <= r.expect_hz_tol_pct
        r.verdict = "PASS" if r.freq_ok else "FAIL"
        r.label = "NORMAL" if r.freq_ok else "ABNORMAL"
        if len(names) > 1:
            msgs.append("正常频点白名单 {%s} Hz；实测 %.6g Hz 最接近 %.6g Hz，偏差 %+.2f%%"
                        "（容差 ±%.2f%%）-> %s/%s"
                        % (", ".join(_fmt_hz_short(v) for v in names), r.freq_hz, best, dev,
                           r.expect_hz_tol_pct, r.verdict, r.label))
        else:
            msgs.append("标称 %.6g Hz，实测 %.6g Hz，偏差 %+.2f%% -> %s"
                        % (best, r.freq_hz, dev, r.verdict))
    if cfg.expect_hz_table:
        best2 = min(cfg.expect_hz_table, key=lambda v: abs(v - r.freq_hz))
        dev2 = (r.freq_hz - best2) / best2 * 100.0 if best2 else 0.0
        if not names:
            r.nearest_hz = float(best2)
            r.nearest_dev_pct = dev2
        msgs.append("候选频点表里最接近 %.6g Hz（偏差 %+.2f%%）" % (best2, dev2))

    r.message = "; ".join(msgs) if msgs else "OK"
    if return_debug:
        r.debug.update({"mask": mask, "y_mid": y_f, "ac": ac,
                        "ppd_x": ppd_x, "ppd_y": ppd_y, "gnd": gnd,
                        "mask_info": minfo})
    return r

def draw_result(bgr: np.ndarray, cfg: ScopeCfg, res: ScopeResult) -> np.ndarray:
    if cv2 is None:                                         
        return bgr
    out = bgr.copy()
    x, y, w, h = cfg.roi
    verdict_color = (0, 255, 0)
    if res.freq_ok is False:
        verdict_color = (0, 0, 255)
    cv2.rectangle(out, (x, y), (x + w, y + h), verdict_color, 2)
    txt = "f=%.4g Hz  Vpp=%.3f V  conf=%.2f" % (res.freq_hz, res.vpp_v, res.confidence)
    if res.verdict:
        txt += "  %s%s(%+.2f%%)" % (res.verdict, ("/" + res.label) if res.label else "",
                                    res.freq_dev_pct)
    if res.aliasing_suspect:
        txt += "  [ALIAS?]"
    cv2.putText(out, txt, (x, max(20, y - 10)), cv2.FONT_HERSHEY_SIMPLEX,
                0.7, verdict_color if res.ok else (0, 0, 255), 2)
    if not res.ok and res.message:
        cv2.putText(out, res.message[:70], (x, y + h + 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 1)
    return out

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="示波器波形 -> Hz / Vpp（单帧调参）")
    ap.add_argument("--config", required=True, help="JSON 配置（取 scope 段）")
    ap.add_argument("--image", required=True, help="一张示波器截图")
    ap.add_argument("--time-per-div", type=float, help="覆盖 time/div (s)")
    ap.add_argument("--volt-per-div", type=float, help="覆盖 V/div (V)")
    ap.add_argument("--probe", type=float, help="覆盖探头衰减")
    ap.add_argument("--expect-hz", type=float, help="该波形的标称频率（做 PASS/FAIL 判定）")
    ap.add_argument("--expect-hz-list", default="",
                    help="正常频点白名单，逗号分隔，如 20000000,40000000（命中任一即 PASS）")
    ap.add_argument("--tol-pct", type=float, help="允许偏差百分比，默认取配置里的值")
    ap.add_argument("--draw", help="把标注结果写到这个 png")
    a = ap.parse_args(argv)

    with open(a.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    sc = ScopeCfg.from_dict(cfg.get("scope", {}))
    if a.time_per_div is not None:
        sc.time_per_div_s = a.time_per_div
    if a.volt_per_div is not None:
        sc.volt_per_div_v = a.volt_per_div
    if a.probe is not None:
        sc.probe_atten = a.probe
    if a.expect_hz is not None:
        sc.expect_hz = a.expect_hz
    if a.expect_hz_list:
        vals = []
        for p in a.expect_hz_list.replace(";", ",").split(","):
            p = p.strip()
            if p:
                try:
                    vals.append(float(p))
                except ValueError:
                    print("忽略无法解析的白名单项: %s" % p)
        if vals:
            sc.expect_hz_list = vals
    if a.tol_pct is not None:
        sc.expect_hz_tol_pct = a.tol_pct

    img = cv2.imread(a.image, cv2.IMREAD_COLOR)
    if img is None:
        print("读不到图: %s" % a.image)
        return 1
    res = analyze_scope_frame(img, sc, return_debug=True)
    print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
    if res.verdict:
        print("\n判定: %s/%s   实测 %.6g Hz / 标称 %.6g Hz (%+.2f%%)"
              % (res.verdict, res.label or "-", res.freq_hz, res.nominal_hz, res.freq_dev_pct))
    if a.draw:
        cv2.imwrite(a.draw, draw_result(img, sc, res))
        print("标注图 -> %s" % a.draw)
    if not res.ok:
        return 2
    if res.freq_ok is False:
        return 3
    return 0

if __name__ == "__main__":                                  
    raise SystemExit(main())
