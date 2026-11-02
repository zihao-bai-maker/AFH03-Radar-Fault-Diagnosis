# -*- coding: utf-8 -*-
"""
rules.py —— 28 项三态判据引擎（严格按交接文档 §5.4，修 §8 第 4/5 条缺陷）

背景（文档 §8）：
  * 原 `scope_lan.judge_presence()` 对"有信号"一律返回 undetermined -> 22 项永远不可能"正常"
  * 原实现没有"幅度 < 正常基准 50%"（`baseline_vpp` 字段都不存在）
  * tol_pct 三套口径（3.0 / 4.0 / ±5%）

本模块只做**判定**，不碰仪器、不联网，可离线单测。
三态：normal(正常) / abnormal(不正常) / undetermined(未判定)。undetermined 不能被汇总成正常。
"""
from __future__ import annotations

NOISE_VPP_V = 0.05          
TOL_PCT_DEFAULT = 5.0       
AMP_LOW_PCT = 50.0          
CONF_MIN = 0.60             
SENTINELS = ("*****", "9.9E+37", "9.9e+37", "9.900000E+37", "inf", "nan",
             "", "NAN", "-inf")

NORMAL, ABNORMAL, UNDET = "normal", "abnormal", "undetermined"
CN = {NORMAL: "正常", ABNORMAL: "不正常", UNDET: "未判定"}

def _num(v):
    """把 SCPI 回包转 float；哨兵/非法 -> None"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        if f != f or abs(f) >= 9.9e36:      
            return None
        return f
    s = str(v).strip()
    if s in SENTINELS or s.lower() in SENTINELS:
        return None
    if s.startswith("*"):
        return None
    s = s.replace(",", "")
    try:
        f = float(s)
    except ValueError:
        return None
    if f != f or abs(f) >= 9.9e36:
        return None
    return f

def _res(verdict, code, reason, **kw):
    d = {"verdict": verdict, "verdict_cn": CN[verdict], "code": code, "reason": reason}
    d.update(kw)
    return d

def judge_freq(measured_hz, expect_hz, tol_pct=TOL_PCT_DEFAULT,
               vpp_v=None, probe_ok=True, confidence=1.0):
    """偏差 ≤ tol_pct ⇒ 正常；> tol_pct ⇒ 异常；读不到 ⇒ 按有无信号分流，绝不猜"""
    exp = _num(expect_hz)
    m = _num(measured_hz)
    vpp = _num(vpp_v)
    dev = None
    if exp is not None and exp > 0 and m is not None:
        dev = abs(m - exp) / exp * 100.0
    if dev is not None:
        out = _res(NORMAL, "freq_in_tol", "频率偏差 %.2f%% ≤ ±%.1f%%" % (dev, tol_pct),
                   dev_pct=round(dev, 3), measured_hz=m, expect_hz=exp, criterion="freq")
        if dev > tol_pct:
            out = _res(ABNORMAL, "freq_out_of_tol",
                       "频率偏差 %.2f%% > ±%.1f%%" % (dev, tol_pct),
                       dev_pct=round(dev, 3), measured_hz=m, expect_hz=exp, criterion="freq")
        return out

    if vpp is not None and vpp < NOISE_VPP_V:
        if probe_ok:
            return _res(ABNORMAL, "no_signal", "无信号（Vpp %.3f V < %.2f V）" % (vpp, NOISE_VPP_V),
                        measured_hz=None, expect_hz=exp, criterion="freq")
        return _res(UNDET, "probe_unclear", "无信号但无法确认探头已接好", criterion="freq")
    if vpp is not None and confidence < CONF_MIN:
        return _res(UNDET, "low_confidence", "置信度 %.2f < %.2f" % (confidence, CONF_MIN),
                    criterion="freq")
    return _res(UNDET, "no_freq_reading", "未读到频率且不能判无信号", criterion="freq")

def judge_presence(vpp_v, noise_vpp_v=NOISE_VPP_V, baseline_vpp=None,
                   amp_low_pct=AMP_LOW_PCT, probe_ok=True, confidence=1.0):
    """有信号 ⇒ 正常（仅存在性；有基准再判幅度）；无信号 ⇒ 异常（前提探头已接好）"""
    vpp = _num(vpp_v)
    base = _num(baseline_vpp)
    if vpp is None:
        return _res(UNDET, "no_reading", "无 Vpp 读数", criterion="presence")
    if vpp < noise_vpp_v:
        if probe_ok:
            return _res(ABNORMAL, "no_signal",
                        "无信号（Vpp %.3f V < %.2f V）" % (vpp, noise_vpp_v),
                        criterion="presence", vpp_v=round(vpp, 4))
        return _res(UNDET, "probe_unclear", "无信号但无法确认探头已接好", criterion="presence")

    if confidence < CONF_MIN:
        return _res(UNDET, "low_confidence", "置信度 %.2f < %.2f" % (confidence, CONF_MIN),
                    criterion="presence", vpp_v=round(vpp, 4))
    if base is not None and base > 0:
        pct = vpp / base * 100.0
        if pct < amp_low_pct:
            return _res(ABNORMAL, "amplitude_low",
                        "幅度为基准的 %.0f%% < %.0f%%（基准 %.3f V）" % (pct, amp_low_pct, base),
                        criterion="presence", vpp_v=round(vpp, 4),
                        baseline_vpp=round(base, 4), amplitude_pct=round(pct, 1))
        return _res(NORMAL, "presence_and_amp_ok",
                    "有信号且幅度为基准的 %.0f%%" % pct,
                    criterion="presence", vpp_v=round(vpp, 4),
                    baseline_vpp=round(base, 4), amplitude_pct=round(pct, 1))

    return _res(NORMAL, "presence_only",
                "有信号（Vpp %.3f V）；幅度基准未标定，未判幅度" % vpp,
                criterion="presence", vpp_v=round(vpp, 4), baseline_vpp=None,
                amplitude_pct=None)

def judge_item(item, meas):
    """item: items_lan.json 的一项；meas: {'freq_hz','vpp_v','confidence','probe_ok'}"""
    meas = meas or {}
    mode = item.get("judge_mode")
    conf = meas.get("confidence", 1.0)
    probe_ok = meas.get("probe_ok", True)
    if mode == "freq":
        r = judge_freq(meas.get("freq_hz"), item.get("expect_freq_hz"),
                       item.get("tol_pct") or TOL_PCT_DEFAULT, meas.get("vpp_v"),
                       probe_ok, conf)
    else:
        r = judge_presence(meas.get("vpp_v"), item.get("noise_vpp_v", NOISE_VPP_V),
                           item.get("baseline_vpp"), item.get("amp_low_pct", AMP_LOW_PCT),
                           probe_ok, conf)
    r["idx"] = item["idx"]
    r["name"] = item["signal"]
    r["route"] = item["route"]
    r["part"] = item["part"]
    r["field"] = item.get("field")
    r["check_item"] = item.get("check_item")
    r["measured"] = (meas.get("freq_hz") is not None or meas.get("vpp_v") is not None)
    r["expect_hz"] = item.get("expect_freq_hz")
    r["measured_hz"] = _num(meas.get("freq_hz"))
    r["vpp_v"] = _num(meas.get("vpp_v"))
    r["confidence"] = round(float(conf), 2)
    return r

def summarize(results):
    """页面级汇总：任一异常 ⇒ 不正常；全部正常 ⇒ 正常；否则 未判定（undetermined 绝不算正常）"""
    n_ok = sum(1 for r in results if r["verdict"] == NORMAL)
    n_bad = sum(1 for r in results if r["verdict"] == ABNORMAL)
    n_unk = sum(1 for r in results if r["verdict"] == UNDET)
    total = len(results)
    if total == 0:
        return UNDET, "无条目"
    if n_bad:
        verdict = ABNORMAL
        bad = [r["name"] for r in results if r["verdict"] == ABNORMAL][:3]
        reason = "%d 项：正常 %d / 异常 %d / 未判定 %d；异常项：%s" % (
            total, n_ok, n_bad, n_unk, "、".join(bad))
    elif n_ok == total:
        verdict = NORMAL
        reason = "%d 项全部正常" % total
    else:
        verdict = UNDET
        reason = "%d 项：正常 %d / 异常 %d / 未判定 %d（未判定项不足以下结论）" % (
            total, n_ok, n_bad, n_unk)
    return verdict, reason
