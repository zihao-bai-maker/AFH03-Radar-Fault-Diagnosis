#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scope_rules.py —— 示波器波形项判据库（28 项）+ 判定引擎 + 拍屏读数

设计约束（用户确认，硬约束）
--------------------------
* **绝不发任何 SCPI 命令**：`:MEAS:*` / `:WAV:*` 会把 RIGOL DS2102A 网口挂死，
  只能"相机拍屏"。本文件里没有 socket / VISA / USBTMC，搜 `SCPI` 也只有注释。
* **不修改** `afh03_board_setup/soc_vision/ui_kiosk.py`：可用时 import 它的
  `wave_from_frame()`，但**只取 `freq_mhz`**；它内部"20/40 MHz 正常"的
  `verdict` 是错的，一律丢弃（见 README_scope.md「与旧 20/40 逻辑的差异」）。
* 判据来源：`雷达判据/判据库_SOP.csv` 中 `method=采集示波器输出数据` 的 **28 项**
  （flow 22/23/27/28）+ `SOP_field_id_V1.5.md`（原文核对）。
* **宁可不判，绝不误判**：置信度不足 / 无时基 / 平线 / 读不到频率 ⇒ `undetermined`。

与统一证据格式 `schema_evidence.md`（evidence/v1）的关系
--------------------------------------------------------
* `part` 用**小写 z token**（`z14`/`z11`）、`route`=`I`/`II`、`field` 用 `(scope)_route_...`，
  与 schema §3/§4 一致；
* `judge()` 的 `value` 按本任务要求只用 `normal|abnormal|undetermined`；
  需要 schema 更细的值域时用 `as_evidence_v1(ev)`（`no_signal` → `value="no"`）；
* 输出已带 schema 必填的 `confidence` / `evidence` / `ts`（ISO-8601 带时区）。

公共 API
--------
    judge(signal_name, measured_freq_hz=None, measured_vpp=None, confidence=1.0, ...)
        -> {"part", "modality":"scope", "field", "value", "feature_id", ...}

    read_scope_screen(frame, ns_per_div=None, ocr_fn=None, backend="builtin")
        -> 拍屏读数（屏幕框 / 曲线 / 周期 / 频率 / Vpp / 置信度）

    measure_item(frame, signal_name=None, route=None, ns_per_div=None, ...)
        -> 读数 + 判定 合成的一条证据（可直接进多模态证据池）

    library(path=None) -> ScopeLibrary      # 28 项判据库（scope_items.json）

CLI
---
    python scope_rules.py --list
    python scope_rules.py --judge 10M相参基准 --freq 10.02e6 --route I --vpp 3.3
    python scope_rules.py --judge 40M时钟 --freq 43e6 --route II
    python scope_rules.py --frame shot.jpg --signal 10M相参基准 --route I --ns-per-div 100
    python scope_rules.py --frame shot.jpg --signal 10M相参基准 --ocr-text "Freq = 10.00MHz"
    python scope_rules.py --selftest
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import unicodedata
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ITEMS = os.path.join(HERE, "scope_items.json")

VALUE_NORMAL = "normal"
VALUE_ABNORMAL = "abnormal"
VALUE_UNDETERMINED = "undetermined"
VERDICT_CN = {VALUE_NORMAL: "正常", VALUE_ABNORMAL: "故障", VALUE_UNDETERMINED: "未判定"}
MODALITY = "scope"

try:                                                        
    from soc_vision.ui_kiosk import wave_from_frame as _uk_wave_from_frame  
except Exception:                                           
    _uk_wave_from_frame = None

def _norm(s: Any) -> str:
    """名称归一化：全角→半角、小写、去空白/连字符、去『波形/测量』等虚词。"""
    t = unicodedata.normalize("NFKC", str(s or "")).lower()
    t = t.replace("波形正常", "").replace("波形", "").replace("测量", "")
    t = re.sub(r"[\s\-_—–·/\\]+", "", t)
    return t

def route_from_text(s: Any) -> Optional[str]:
    """从项目/流程名里取 I/II 路。"""
    t = unicodedata.normalize("NFKC", str(s or "")).lower()
    t = re.sub(r"\s+", "", t)
    if re.search(r"\(ii\)|ii路|二路|2路", t):
        return "II"
    if re.search(r"\(i\)|i路|一路|1路", t):
        return "I"
    return None

_FREQ_NAME_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(k|m|g)?(?:hz|赫)?(?![a-z])", re.I)

def parse_freq_text(text: Any) -> Optional[float]:
    """从名字里解析频率：'10M相参' -> 10e6；'30M中频' -> 30e6；'40M时钟' -> 40e6。
    无单位时只接受 >=1000 的数（避免把序号/编号当频率）。"""
    t = str(text or "")
    for m in _FREQ_NAME_RE.finditer(t):
        val = float(m.group(1))
        unit = (m.group(2) or "").lower()
        if unit in ("k", "m", "g"):
            return val * {"k": 1e3, "m": 1e6, "g": 1e9}[unit]
        if val >= 1000:
            return val
    return None

def fmt_hz(hz: Optional[float]) -> str:
    if hz is None or not isinstance(hz, (int, float)) or not math.isfinite(float(hz)):
        return "—"
    a = abs(float(hz))
    if a >= 1e6:
        return "%.3f MHz" % (float(hz) / 1e6)
    if a >= 1e3:
        return "%.3f kHz" % (float(hz) / 1e3)
    return "%.1f Hz" % float(hz)

class ScopeLibrary:
    """scope_items.json 的只读封装：28 项判据 + 14 个信号定义。"""

    def __init__(self, data: Dict[str, Any], path: str = ""):
        self.data = data or {}
        self.path = path
        self.policy: Dict[str, Any] = self.data.get("policy") or {}
        self.signals: List[Dict[str, Any]] = list(self.data.get("signals") or [])
        self.items: List[Dict[str, Any]] = list(self.data.get("items") or [])
        self._by_field = {it["field"]: it for it in self.items if it.get("field")}
        self._by_id = {str(it.get("item_id") or it.get("id")): it for it in self.items
                       if it.get("item_id") or it.get("id")}
        self._names: Dict[str, Dict[str, Any]] = {}
        for s in self.signals:
            for nm in [s.get("signal"), s.get("key")] + list(s.get("aliases") or []):
                if nm:
                    self._names[_norm(nm)] = s

    @classmethod
    def load(cls, path: Optional[str] = None) -> "ScopeLibrary":
        p = path or DEFAULT_ITEMS
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(data, p)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScopeLibrary":
        return cls(data, "<dict>")

    def signal(self, name: Any) -> Optional[Dict[str, Any]]:
        return self._names.get(_norm(name))

    def get_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        return self._by_id.get(item_id)

    def items_for(self, signal: str, route: Optional[str] = None) -> List[Dict[str, Any]]:
        its = [it for it in self.items if it.get("signal") == signal]
        if route:
            its = [it for it in its if it.get("route") == route]
        return its

    def _match_signal(self, text: Any) -> Tuple[Optional[Dict[str, Any]], str]:
        n = _norm(text)
        if not n:
            return None, ""
        if n in self._names:
            return self._names[n], "signal_exact"
        best: Optional[Tuple[int, Dict[str, Any]]] = None
        for s in self.signals:
            for a in [s.get("signal"), s.get("key")] + list(s.get("aliases") or []):
                an = _norm(a)
                if an and an in n and (best is None or len(an) > best[0]):
                    best = (len(an), s)
        if best:
            return best[1], "alias"
        f = parse_freq_text(text)
        if f:
            cands = [s for s in self.signals
                     if s.get("expect_freq_hz") and abs(float(s["expect_freq_hz"]) - f) / f <= 0.01]
            if len(cands) == 1:
                return cands[0], "name_freq"
        return None, ""

    def resolve(self, name: Any = None, route: Optional[str] = None,
                flow_no: Optional[int] = None, sub_no: Optional[int] = None,
                check_item: Optional[str] = None
                ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """把『信号名 / 项目原文 / flow+sub』解析成 28 项里的一条。

        返回 (item|None, meta)；meta 记录匹配方式、路别是否被假定、名称里的频率。
        """
        text = str(check_item or name or "")
        meta: Dict[str, Any] = {
            "library_match": False, "match_kind": "", "route": route,
            "route_assumed": False, "expected_from_name_hz": parse_freq_text(text),
            "signal": None, "error": "",
        }
        item: Optional[Dict[str, Any]] = None

        if flow_no is not None:
            cands = [it for it in self.items
                     if int(it.get("flow_no") or -1) == int(flow_no)]
            if sub_no is not None:
                c2 = [it for it in cands if it.get("sub_no") == int(sub_no)]
                if c2:
                    cands = c2
            if check_item:
                c2 = [it for it in cands if _norm(it.get("check_item")) == _norm(check_item)]
                if not c2:
                    c2 = [it for it in cands
                          if _norm(check_item) in _norm(it.get("check_item"))
                          or _norm(it.get("check_item")) in _norm(check_item)]
                if c2:
                    cands = c2
            if route:
                c2 = [it for it in cands if it.get("route") == route]
                if c2:
                    cands = c2
            if len(cands) == 1:
                item = cands[0]
            elif len(cands) > 1:
                meta["error"] = ("flow_no=%s%s 命中 %d 项，请补 sub_no / check_item / signal"
                                 % (flow_no, "" if sub_no is None else " sub_no=%s" % sub_no,
                                    len(cands)))

        if item is None:
            sig, kind = self._match_signal(text)
            if sig:
                its = [it for it in self.items if it.get("signal") == sig.get("signal")]
                r = route or route_from_text(text)
                if r:
                    its = [it for it in its if it.get("route") == r]
                elif len({it.get("route") for it in its}) > 1:

                    meta["route_assumed"] = True
                    its = [it for it in its if it.get("route") == "I"]
                if len(its) == 1:
                    item = its[0]
                    meta["match_kind"] = kind
                    meta["route"] = item.get("route")
                    meta["signal"] = item.get("signal")
                elif len(its) > 1:
                    meta["error"] = "信号 %s 在 I/II 两路都有，请指定 route" % sig.get("signal")
            elif not meta["expected_from_name_hz"]:
                meta["error"] = meta["error"] or ("信号『%s』不在 28 项判据库内，"
                                                  "名称里也没有可解析的频率" % (name or check_item or ""))

        if item is not None:
            meta.update(library_match=True, signal=item.get("signal"),
                        route=item.get("route"))
        return item, meta

    def summary(self) -> Dict[str, Any]:
        by_flow: Dict[str, int] = {}
        for it in self.items:
            by_flow[str(it.get("flow_no"))] = by_flow.get(str(it.get("flow_no")), 0) + 1
        return {
            "items": len(self.items),
            "signals": len(self.signals),
            "by_flow": by_flow,
            "freq_items": sum(1 for it in self.items if it.get("expect_freq_hz")),
            "presence_items": sum(1 for it in self.items if not it.get("expect_freq_hz")),
            "policy": self.policy,
        }

_LIB_CACHE: Dict[str, ScopeLibrary] = {}

def library(path: Optional[str] = None) -> ScopeLibrary:
    p = os.path.abspath(path or DEFAULT_ITEMS)
    if p not in _LIB_CACHE:
        _LIB_CACHE[p] = ScopeLibrary.load(p)
    return _LIB_CACHE[p]

def items(path: Optional[str] = None) -> List[Dict[str, Any]]:
    return library(path).items

def signals(path: Optional[str] = None) -> List[Dict[str, Any]]:
    return library(path).signals

def _feature_for(item: Optional[Dict[str, Any]], abnormal_value: str) -> str:
    if not item:
        return ""
    fids = item.get("feature_ids") or {}
    if fids:
        return str(fids.get(abnormal_value) or "")
    fid = str(item.get("feature_id") or "")
    if fid and (not item.get("abnormal_value") or item.get("abnormal_value") == abnormal_value):
        return fid
    return ""

def _iso_ts(ts: Any = None) -> str:
    """ISO-8601 带时区（schema_evidence.md 要求）。"""
    if ts is None:
        return datetime.now().astimezone().isoformat(timespec="seconds")
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(float(ts)).astimezone().isoformat(timespec="seconds")
    return str(ts)

def _base_evidence(item: Optional[Dict[str, Any]], meta: Dict[str, Any],
                   value: str, feature_id: str) -> Dict[str, Any]:
    """证据 JSON：前 5 个键是用户要求的最小集（part/modality/field/value/feature_id）。"""
    return {
        "part": str(item.get("part") or "") if item else "",
        "modality": MODALITY,
        "field": str(item.get("field") or "") if item else "",
        "value": value,
        "feature_id": feature_id,

        "verdict_cn": VERDICT_CN[value],
        "ok": value == VALUE_NORMAL,
        "signal": str(item.get("signal") or "") if item else str(meta.get("signal") or ""),
        "route": ((item.get("route") if item else meta.get("route")) or ""),
        "part_name": str(item.get("part_name") or "") if item else "",
        "check_item": str(item.get("check_item") or "") if item else "",
        "flow_no": item.get("flow_no") if item else None,
        "sub_no": item.get("sub_no") if item else None,
        "item_id": (item.get("item_id") or item.get("id")) if item else None,
    }

def judge(signal_name: Any = None, measured_freq_hz: Optional[float] = None,
          measured_vpp: Optional[float] = None, confidence: Optional[float] = 1.0,
          *, route: Optional[str] = None, flow_no: Optional[int] = None,
          sub_no: Optional[int] = None, check_item: Optional[str] = None,
          item_id: Optional[str] = None,
          tol_pct: Optional[float] = None, wave_present: Optional[bool] = None,
          expected_freq_hz: Optional[float] = None,
          min_confidence: Optional[float] = None,
          no_signal_verdict: Optional[str] = None,
          source: Optional[str] = None, lib: Optional[ScopeLibrary] = None,
          ts: Optional[float] = None) -> Dict[str, Any]:
    """判定一条示波器波形项证据。

    参数
    ----
    signal_name      : 信号名 / 项目原文 / 流程项目（'10M相参基准'、'（I）路-测量10M相参基准波形正常'）
    measured_freq_hz : 实测频率（Hz）。屏幕 Freq 直读或 周期÷时基 换算。
    measured_vpp     : 实测峰峰值（V），仅记录，不作判据（判据库未给幅度门限）。
    confidence       : 读数置信度 0..1；< min_confidence（默认 0.35）⇒ undetermined。
    route            : 'I' / 'II'；不从名字里猜错，未给时若名字里没有路别则按 I 取字段并标记。
    flow_no/sub_no   : 直接按判据库流程定位（flow 23/28 的 sub_no 在库中为空）。
    check_item       : 判据库项目原文（用于 flow_no + 原文 唯一定位）。
    item_id          : 直接按判据库 id 定位（`f22_01` …），便于和流程表/fusion 对齐。
    tol_pct          : 覆盖容差（默认取该项目的 tol_pct，库中为 4.0，即 3~5% 区间中值）。
    wave_present     : True=确认有波形；False=确认无波形（平线/Freq=*****）；None=未知。
    expected_freq_hz : 覆盖期望频率（用于库外信号的临时核对）。
    no_signal_verdict: 'undetermined'（默认，宁可不判）或 'abnormal'（流程保证探针已接好时）。

    返回
    ----
    dict，前 5 键固定为 part / modality / field / value / feature_id，
    value ∈ {'normal','abnormal','undetermined'}，feature_id 仅在 abnormal 时非空；
    另带 confidence / evidence / ts（evidence/v1 必填）与 expected/measured/tol/reason 等。
    """
    lb = lib or library()
    pol = lb.policy or {}
    if item_id:
        item = lb.get_item(str(item_id))
        meta: Dict[str, Any] = {
            "library_match": bool(item), "match_kind": "item_id",
            "route": item.get("route") if item else route, "route_assumed": False,
            "expected_from_name_hz": None, "signal": item.get("signal") if item else None,
            "error": "" if item else "未知 item_id: %s" % item_id,
        }
    else:
        item, meta = lb.resolve(name=signal_name, route=route, flow_no=flow_no,
                                sub_no=sub_no, check_item=check_item)

    min_conf = float(pol.get("min_confidence", 0.35) if min_confidence is None else min_confidence)
    ns_pol = str(no_signal_verdict or pol.get("no_signal_verdict") or VALUE_UNDETERMINED).lower()
    if ns_pol not in (VALUE_UNDETERMINED, VALUE_ABNORMAL):
        ns_pol = VALUE_UNDETERMINED

    exp = expected_freq_hz
    if exp is None and item:
        exp = item.get("expect_freq_hz")
    if exp is None:
        exp = meta.get("expected_from_name_hz")
    if tol_pct is not None:
        tol: Optional[float] = float(tol_pct)
    elif item is not None and item.get("tol_pct") is not None:
        tol = float(item["tol_pct"])
    elif exp is not None:
        tol = float(pol.get("default_tol_pct", 4.0))
    else:
        tol = None
    conf = 1.0 if confidence is None else max(0.0, min(1.0, float(confidence)))

    meas = None
    if measured_freq_hz is not None:
        try:
            meas = float(measured_freq_hz)
        except (TypeError, ValueError):
            meas = None
        if meas is not None and (not math.isfinite(meas) or meas <= 0):
            meas = None

    value = VALUE_UNDETERMINED
    feature_id = ""
    reason = ""
    dev: Optional[float] = None
    abnormal_value = ""

    if item is None and exp is None:

        reason = meta.get("error") or ("信号『%s』不在 28 项判据库内，也没有期望频率"
                                       % (signal_name or check_item or ""))
    elif conf < min_conf:
        reason = ("读数置信度 %.2f < %.2f ⇒ 未判定（宁可不判，绝不误判）"
                  % (conf, min_conf))
    elif wave_present is False:
        abnormal_value = "no_signal"
        if ns_pol == VALUE_ABNORMAL:
            value = VALUE_ABNORMAL
            feature_id = _feature_for(item, abnormal_value)
            reason = "确认无有效波形（平线 / Freq=*****）⇒ 异常（no_signal）"
        else:
            reason = ("确认无有效波形（平线 / Freq=*****），但无法排除探针未接/通道错 ⇒ 未判定"
                      "（如流程保证探针已接好，可传 no_signal_verdict='abnormal'）")
    elif exp is not None:
        if meas is None:
            reason = "缺少频率读数（未直读 Freq、也没有可用的时基换算）⇒ 未判定"
        else:
            dev = abs(meas - float(exp)) / float(exp) * 100.0
            if dev <= float(tol) + 1e-9:
                value = VALUE_NORMAL
                reason = ("实测 %s，与期望 %s 偏差 %.2f%% ≤ ±%.1f%% ⇒ 正常"
                          % (fmt_hz(meas), fmt_hz(exp), dev, float(tol)))
            else:
                value = VALUE_ABNORMAL
                abnormal_value = "freq_out_of_tol"
                feature_id = _feature_for(item, abnormal_value)
                reason = ("实测 %s，与期望 %s 偏差 %.2f%% > ±%.1f%% ⇒ 异常（freq_out_of_tol）"
                          % (fmt_hz(meas), fmt_hz(exp), dev, float(tol)))
    else:

        if wave_present is True or meas is not None:
            value = VALUE_NORMAL
            reason = ("确认有波形；判据库仅要求『波形正常』、未给频率/幅度门限 ⇒ "
                      "按存在性判据判正常（频率/形状需人工复核）")
        else:
            reason = ("判据库未给该信号的频率/幅度门限，且未提供 waveform_present ⇒ 未判定"
                      "（不臆造频率）")

    conf_out = min(conf, 0.50) if value == VALUE_UNDETERMINED else conf
    ev = _base_evidence(item, meta, value, feature_id)
    ev.update({
        "criterion": (item.get("judge_mode") if item else
                      ("freq_name_fallback" if exp is not None else "")),
        "expected_freq_hz": (float(exp) if exp is not None else None),
        "tol_pct": (round(float(tol), 4) if tol is not None else None),
        "measured_freq_hz": meas,
        "measured_vpp_v": (float(measured_vpp) if measured_vpp is not None else None),
        "dev_pct": (round(dev, 3) if dev is not None else None),
        "confidence": round(conf_out, 3),
        "confidence_raw": round(conf, 3),
        "library_match": bool(item),
        "route_assumed": bool(meta.get("route_assumed")),
        "abnormal_value": abnormal_value,
        "reason": reason,

        "evidence": (reason or "")[:200].replace("\n", " "),
        "ts": _iso_ts(ts),
        "source": source or "scope_rules.judge",
    })
    return ev

def as_evidence_v1(ev: Dict[str, Any]) -> Dict[str, Any]:
    """转成 `schema_evidence.md` 的 evidence/v1（值域更细）。

    * `abnormal` + `abnormal_value=no_signal` → `value="no"`（无波形）
    * 其余 normal/abnormal/undetermined 原样保留（`abnormal` 属 schema §5.2 扩展枚举）
    必填：part/route/modality/field/value/confidence/evidence/ts —— 本函数补齐。
    """
    out = dict(ev or {})
    if out.get("value") == VALUE_ABNORMAL and out.get("abnormal_value") == "no_signal":
        out["value"] = "no"
    out["route"] = out.get("route") or ""
    out.setdefault("evidence", str(out.get("reason") or "")[:200].replace("\n", " "))
    out.setdefault("ts", _iso_ts())
    out.setdefault("confidence", 0.0)
    return out

def evidence_batch(evs: Sequence[Dict[str, Any]],
                   producer: str = "scope_rules.py") -> Dict[str, Any]:
    """schema_evidence.md §2 的批量上报格式。"""
    return {"schema": "evidence/v1", "producer": producer,
            "evidence": [as_evidence_v1(e) for e in evs]}

def judge_batch(rows: Sequence[Dict[str, Any]],
                lib: Optional[ScopeLibrary] = None) -> List[Dict[str, Any]]:
    """批量判定：rows 里每行是 judge() 的关键字参数（键名同 judge）。"""
    out = []
    for r in rows:
        kw = dict(r or {})
        if "freq_hz" in kw and "measured_freq_hz" not in kw:
            kw["measured_freq_hz"] = kw.pop("freq_hz")
        if "vpp_v" in kw and "measured_vpp" not in kw:
            kw["measured_vpp"] = kw.pop("vpp_v")
        if "signal" in kw and "signal_name" not in kw:
            kw["signal_name"] = kw.pop("signal")
        out.append(judge(lib=lib, **kw))
    return out

def _imread(path: str):
    try:                                                    
        import cv2                                          
        b = cv2.imread(path, cv2.IMREAD_COLOR)
        if b is not None:
            return b[:, :, ::-1]
    except Exception:                                       
        pass
    try:
        from PIL import Image
        return np.asarray(Image.open(path).convert("RGB"))
    except Exception:                                       
        return None

def _as_array(frame: Any):
    if frame is None:
        return None
    if isinstance(frame, np.ndarray):
        a = frame
    elif isinstance(frame, (str, bytes, os.PathLike)):
        a = _imread(os.fspath(frame))
    else:
        a = np.asarray(frame)
    if a is None:
        return None
    if a.ndim == 2:
        a = np.repeat(a[:, :, None], 3, axis=2)
    if a.shape[2] == 4:
        a = a[:, :, :3]
    return a.astype(np.float32)

def _guess_channel_order(a: np.ndarray, roi: Optional[Sequence[int]] = None) -> str:
    """猜 RGB / BGR：示波器亮线多为黄色（R≈G≫B）。只看屏幕框内，避免蓝线缆干扰。"""
    try:
        if roi is not None:
            x0, y0, x1, y1 = [int(v) for v in roi]
            sub = a[max(0, y0):y1 + 1, max(0, x0):x1 + 1]
        else:
            step_y = max(1, a.shape[0] // 64)
            step_x = max(1, a.shape[1] // 64)
            sub = a[::step_y, ::step_x]
        pos = float(((sub[:, :, 0] - sub[:, :, 2]) > 40).sum())   
        neg = float(((sub[:, :, 2] - sub[:, :, 0]) > 40).sum())   
        if pos < 20 and neg < 20:
            return "rgb"
        return "bgr" if neg > pos * 1.5 else "rgb"
    except Exception:                                       
        return "rgb"

def _apply_order(a: np.ndarray, channel_order: str,
                 roi: Optional[Sequence[int]] = None) -> np.ndarray:
    order = str(channel_order or "auto").lower()
    if order == "auto":
        order = _guess_channel_order(a, roi)
    if order == "bgr":
        return a[:, :, ::-1]
    return a

def _runs(mask: np.ndarray, min_len: int = 40, max_gap: int = 3) -> List[Tuple[int, int]]:
    """掩膜里连续为 True 的区间（允许 max_gap 个断点），按长度降序。"""
    idx = np.where(mask)[0]
    if len(idx) == 0:
        return []
    out: List[Tuple[int, int]] = []
    start = prev = int(idx[0])
    for i in idx[1:]:
        i = int(i)
        if i - prev > max_gap:
            if prev - start + 1 >= min_len:
                out.append((start, prev))
            start = i
        prev = i
    if prev - start + 1 >= min_len:
        out.append((start, prev))
    out.sort(key=lambda se: se[1] - se[0], reverse=True)
    return out

def locate_screen(frame: Any) -> Dict[str, Any]:
    """定位示波器屏幕（暗色大矩形）。

    为什么不用 ui_kiosk 的原版投影：手持整幅照片里**暗色线缆会被并进屏幕**
    （实测 box=(100,17,1389,1043)，随后在噪点上误检出 11 px 周期、相关峰 0.475）。
    这里改成"行连续带 × 带内列连续带 × 填充率/长宽比打分"，取最像屏幕的那块。
    """
    a = _as_array(frame)
    if a is None:
        return {"ok": False, "box": [0, 0, 0, 0], "fill": 0.0, "reason": "无画面"}
    H, W = a.shape[:2]
    g = a.mean(axis=2)
    thr = max(40.0, float(np.percentile(g, 25)))
    dark = g < thr

    row_runs = _runs(dark.sum(axis=1) / float(W) > 0.25, 40, max_gap=10)[:4]
    best = None
    for (y0, y1) in row_runs:
        band = dark[y0:y1 + 1, :]
        cf = band.sum(axis=0) / float(max(1, y1 - y0 + 1))
        for (x0, x1) in _runs(cf > 0.55, 40, max_gap=6)[:3]:
            w, h = x1 - x0 + 1, y1 - y0 + 1
            if w < 80 or h < 60:
                continue
            aspect = w / float(h)
            area = w * h / float(W * H)
            fill = float(dark[y0:y1 + 1, x0:x1 + 1].mean())
            if not (0.6 <= aspect <= 4.0) or area < 0.02 or fill < 0.45:
                continue
            score = area * fill
            if best is None or score > best[0]:
                best = (score, (x0, y0, x1, y1), fill, aspect)
    if best is None:
        return {"ok": False, "box": [0, 0, W - 1, H - 1], "fill": 0.0,
                "reason": "未定位到暗色屏幕矩形（按整幅分析，置信度降低）"}
    _, box, fill, aspect = best
    return {"ok": True, "box": [int(box[0]), int(box[1]), int(box[2]), int(box[3])],
            "fill": round(fill, 3), "aspect": round(aspect, 2), "reason": "暗色屏幕矩形"}

def _centers(ink: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    ys, xs = [], []
    for x in range(ink.shape[1]):
        c = np.where(ink[:, x])[0]
        if len(c) >= 2:
            ys.append(float(c.mean()))
            xs.append(float(x))
    return np.asarray(xs, float), np.asarray(ys, float)

def _ink_warm(lum: np.ndarray, warm: np.ndarray) -> np.ndarray:
    """自适应取"暖色亮线"：白字/灰栅格 warm≈0 天然被排除。"""
    m = warm > 15.0
    if int(m.sum()) < 60:
        return np.zeros_like(m)
    t_lum = max(80.0, float(np.percentile(lum[m], 25)))
    return (lum >= t_lum) & m

def _ink_legacy(lum: np.ndarray, warm: np.ndarray) -> np.ndarray:
    """ui_kiosk.wave_from_frame 原版阈值（兜底）。"""
    t_lum = max(80.0, float(np.percentile(lum, 97)))
    t_warm = max(20.0, float(np.percentile(warm, 95)))
    return (lum >= t_lum) & (warm >= t_warm)

def _first_period(ac: np.ndarray, lo: int, hi: int) -> Tuple[Optional[float], float]:
    """取第一个显著自相关峰（避免把 2×/3× 周期当基频），并做抛物线亚像素细化。"""
    if hi - lo < 6:
        return None, 0.0
    seg = ac[lo:hi + 1]
    peak = float(seg.max()) if seg.size else 0.0
    if peak < 0.30:
        return None, peak
    thr = 0.85 * peak
    idx = None
    for i in range(1, len(seg) - 1):
        if seg[i] >= thr and seg[i] >= seg[i - 1] and seg[i] >= seg[i + 1]:
            idx = i
            break
    if idx is None:
        idx = int(np.argmax(seg))

    frac = 0.0
    if 0 < idx < len(seg) - 1:
        den = float(seg[idx - 1]) - 2.0 * float(seg[idx]) + float(seg[idx + 1])
        if abs(den) > 1e-12:
            frac = max(-0.5, min(0.5, 0.5 * (float(seg[idx - 1]) - float(seg[idx + 1])) / den))
    return float(lo + idx) + frac, peak

def extract_trace(frame: Any, box: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    """在屏幕框内提波形曲线 + 周期（自相关）。

    注意：直接调用时 `frame` 需为 **RGB**；OpenCV 的 BGR 帧请走
    `read_scope_screen(..., channel_order="bgr")`（会自动转序）。
    """
    a = _as_array(frame)
    if a is None:
        return {"ok": False, "reason": "无画面", "cols": 0}
    H, W = a.shape[:2]
    if box is None:
        box = locate_screen(a)["box"]
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W - 1, x1), min(H - 1, y1)
    if x1 - x0 < 60 or y1 - y0 < 50:
        return {"ok": False, "reason": "屏幕框太小（%dx%d）" % (x1 - x0, y1 - y0), "cols": 0}
    crop = a[y0:y1 + 1, x0:x1 + 1]
    r, g, b = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    lum = (r + g + b) / 3.0
    warm = (r + g) / 2.0 - b
    sw, sh = crop.shape[1], crop.shape[0]

    ink = _ink_warm(lum, warm)
    xs, ys = _centers(ink)
    method = "warm"
    if len(xs) < max(20, int(0.10 * sw)):
        ink = _ink_legacy(lum, warm)
        xs, ys = _centers(ink)
        method = "legacy"
    min_cols = max(20, int(0.10 * sw))
    if len(xs) < min_cols:
        return {"ok": False, "cols": int(len(xs)), "method": method,
                "reason": "屏幕内未找到波形亮线（列数 %d < %d）" % (len(xs), min_cols)}

    v = ys - np.polyval(np.polyfit(xs, ys, 1), xs)
    v = v - float(v.mean())
    yspan = float(np.percentile(ys, 95) - np.percentile(ys, 5))
    absmax = float(np.abs(v).max())
    out: Dict[str, Any] = {"ok": True, "curve": (xs, ys), "cols": int(len(xs)),
                           "yspan": round(yspan, 2), "absmax": round(absmax, 2),
                           "method": method, "box": [x0, y0, x1, y1]}
    if absmax < 2.0 or yspan < 3.0:
        out.update(flat=True, reason="波形是平线（无有效信号：示波器 Freq 应为 *****）")
        return out
    out["flat"] = False
    ac = np.correlate(v, v, mode="full")[len(v) - 1:]
    ac = ac / (ac[0] + 1e-9)
    k, peak = _first_period(ac, 4, max(6, len(v) // 2))
    out.update(period_px=k, peak=round(float(peak), 3))
    if not k:
        out.update(ok=False, reason="波形不规则/噪声（相关峰 %.2f < 0.30）" % peak)
    return out

def freq_from_period(period_px: float, screen_w: float,
                     ns_per_div: float, h_div: float = 10.0) -> Optional[float]:
    """频率 = 1 /（周期像素 ÷ 每格像素 × 时基）。ns_per_div 单位 ns（RIGOL 风格）。"""
    if not period_px or period_px <= 0 or not screen_w or screen_w <= 0:
        return None
    if ns_per_div is None or ns_per_div <= 0:
        return None
    px_per_div = float(screen_w) / float(h_div)
    t = (float(period_px) / px_per_div) * float(ns_per_div) * 1e-9
    if t <= 0:
        return None
    return 1.0 / t

def _curve_conf(peak: float, cols: int, screen_w: float) -> float:
    c_peak = max(0.0, min(1.0, (float(peak) - 0.30) / 0.45))
    c_cov = max(0.0, min(1.0, float(cols) / max(1.0, 0.60 * float(screen_w))))
    return round(min(0.95, 0.35 + 0.60 * c_peak * c_cov), 3)

_TB_RE1 = re.compile(r"(?:s\s*/\s*div|时基)\s*[=:：]?\s*(\d+(?:\.\d+)?)\s*([nµuμm]?)s", re.I)
_TB_RE2 = re.compile(r"(?:^|\s)[Hh]\s*(\d+(?:\.\d+)?)\s*([nµuμm]?)s(?:\s|$)", re.I)
_FREQ_RE = re.compile(r"(?:freq(?:uency)?|频率)\s*[=:：]?\s*(\*+|\d+(?:\.\d+)?)\s*([kKmMgG]?)\s*(?:hz|赫)?", re.I)
_VPP_RE = re.compile(r"(?:vpp|v\s*p\s*p|峰峰值|峰-峰值|幅度)\s*[=:：]?\s*(\d+(?:\.\d+)?)\s*([munµμ]?)\s*v", re.I)

def _unit_mul(u: str, table: Dict[str, float]) -> float:
    u = (u or "").lower()
    return table.get(u, 0.0)

def parse_measurement_text(text: Any) -> Dict[str, Any]:
    """解析示波器屏幕文字（RIGOL 风格）：

        Freq = 10.00MHz   Vpp = 3.30V
        频率 = *****      峰峰值 = 80.00mV
        H 100ns          s/div = 50ns
    """
    t = str(text or "")
    out: Dict[str, Any] = {"freq_hz": None, "vpp_v": None, "ns_per_div": None, "raw": t}
    m = _FREQ_RE.search(t)
    if m and not m.group(1).startswith("*"):
        mul = _unit_mul(m.group(2), {"": 1.0, "k": 1e3, "m": 1e6, "g": 1e9})
        if mul:
            out["freq_hz"] = float(m.group(1)) * mul
    m = _VPP_RE.search(t)
    if m:
        mul = _unit_mul(m.group(2), {"": 1.0, "m": 1e-3, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "n": 1e-9})
        if mul:
            out["vpp_v"] = float(m.group(1)) * mul
    for rx in (_TB_RE1, _TB_RE2):
        m = rx.search(t)
        if m:
            mul = _unit_mul(m.group(2), {"": 1.0, "n": 1e-9, "u": 1e-6, "µ": 1e-6,
                                        "μ": 1e-6, "m": 1e-3})
            if mul:
                out["ns_per_div"] = float(m.group(1)) * mul * 1e9
                break
    return out

def read_scope_screen(frame: Any, ns_per_div: Optional[float] = None,
                      ocr_fn: Optional[Callable[[np.ndarray], str]] = None,
                      h_div: float = 10.0, backend: str = "builtin",
                      channel_order: str = "auto") -> Dict[str, Any]:
    """相机拍屏 → 读数（优先屏幕 Freq/Vpp 数字；其次 曲线周期 ÷ 时基）。

    ns_per_div : 时基（ns/格）。**必须尽量给真实值**；不给时只允许从屏幕文字里读，
                 两者都没有 ⇒ 拒绝换算频率（时基错会让 10M 读成 20M，属误判）。
    ocr_fn     : 可选文字识别回调，输入屏幕裁剪图（RGB ndarray），返回文字。
                 本机无 OCR 后端，真图路径未验证；可用 parse_measurement_text 先验。
    backend    : 'builtin'（本文件算法，默认）| 'ui_kiosk'（复用 wave_from_frame，
                 只取 freq_mhz）| 'auto'。
    channel_order : 'auto'（默认，按黄色亮线猜）/ 'rgb' / 'bgr'（OpenCV 相机帧传 bgr）。
    """
    out: Dict[str, Any] = {
        "ok": False, "freq_hz": None, "vpp_v": None, "ns_per_div": ns_per_div,
        "source": "none", "confidence": 0.0, "wave_present": None,
        "screen_box": None, "screen_ok": False, "period_px": None, "peak": None,
        "cols": 0, "text": "", "backend": backend, "reason": "",
    }
    a = _as_array(frame)
    if a is None:
        out["reason"] = "无画面"
        return out
    scr = locate_screen(a)               
    a = _apply_order(a, channel_order, scr["box"])
    out.update(screen_box=scr["box"], screen_ok=bool(scr["ok"]))
    conf_base = 0.85 if scr["ok"] else 0.30

    text = ""
    if ocr_fn is not None:
        try:
            x0, y0, x1, y1 = scr["box"]
            text = str(ocr_fn(a[y0:y1 + 1, x0:x1 + 1].astype(np.uint8)))
        except Exception as e:                              
            text = ""
            out["reason"] = "OCR 回调失败：%s" % e
    out["text"] = text
    parsed = parse_measurement_text(text) if text else {}
    if out.get("ns_per_div") is None and parsed.get("ns_per_div"):
        out["ns_per_div"] = parsed["ns_per_div"]
    if parsed.get("freq_hz"):
        out.update(ok=True, freq_hz=float(parsed["freq_hz"]), vpp_v=parsed.get("vpp_v"),
                   source="screen_text", wave_present=True,
                   confidence=round(min(0.98, conf_base + 0.10), 3),
                   reason="屏幕 Freq 数字直读：%s" % fmt_hz(parsed["freq_hz"]))
        return out

    tr = extract_trace(a, scr["box"])
    out.update(cols=int(tr.get("cols") or 0), period_px=tr.get("period_px"),
               peak=tr.get("peak"))
    if tr.get("flat"):
        out.update(wave_present=False, confidence=(0.80 if scr["ok"] else 0.30),
                   reason="屏幕内波形为平线（Freq=*****）：无有效信号")
        return out
    if not tr.get("ok"):
        out.update(confidence=min(conf_base, tr.get("confidence", 0.30)),
                   reason=str(tr.get("reason") or "未提取到有效波形"))
        return out

    if backend in ("ui_kiosk", "auto") and _uk_wave_from_frame is not None and out.get("ns_per_div"):
        try:
            r = _uk_wave_from_frame(a.astype(np.uint8), float(out["ns_per_div"]))
            if r.get("freq_mhz"):
                out.update(ok=True, freq_hz=float(r["freq_mhz"]) * 1e6, source="ui_kiosk.wave_from_frame",
                           wave_present=True, period_px=r.get("period_px"), peak=r.get("peak"),
                           backend="ui_kiosk",
                           confidence=round(min(0.95, 0.55 + 0.35 * float(r.get("peak") or 0.0)), 3),
                           reason="UI 复用后端：wave_from_frame 仅取 freq_mhz（verdict 不用）")
                return out
        except Exception as e:                              
            out["reason"] = "ui_kiosk 后端失败(%s)，回退内置算法" % e

    if out.get("ns_per_div") is None:
        out.update(wave_present=True, confidence=round(min(conf_base, 0.45), 3),
                   reason="有波形但没有 s/div 时基读数 ⇒ 拒绝按默认时基换算频率（防 2× 误判）")
        return out

    f = freq_from_period(tr["period_px"], tr["box"][2] - tr["box"][0] + 1,
                         float(out["ns_per_div"]), h_div)
    out.update(ok=True, freq_hz=f, source="period_timebase", wave_present=True,
               backend="builtin",
               confidence=_curve_conf(float(tr.get("peak") or 0.0), int(tr.get("cols") or 0),
                                      tr["box"][2] - tr["box"][0] + 1),
               reason="曲线周期 %s px ÷ 时基 %s ns/格 ⇒ %s"
                      % (tr.get("period_px"), out["ns_per_div"], fmt_hz(f)))
    return out

def measure_item(frame: Any, signal_name: Any = None, route: Optional[str] = None,
                 ns_per_div: Optional[float] = None,
                 ocr_fn: Optional[Callable[[np.ndarray], str]] = None,
                 backend: str = "builtin", channel_order: str = "auto",
                 lib: Optional[ScopeLibrary] = None,
                 **judge_kw: Any) -> Dict[str, Any]:
    """一条"拍屏 → 读数 → 判定"的完整证据（多模态证据池直接收）。

    **多信号**：每个项目对应各自的屏幕显示（时基/通道不同）⇒ 每个项目单独调一次，
    传该项目的 signal/route 与**当时屏幕的** ns_per_div。
    """
    rd = read_scope_screen(frame, ns_per_div=ns_per_div, ocr_fn=ocr_fn,
                           backend=backend, channel_order=channel_order)
    ev = judge(signal_name, rd.get("freq_hz"), rd.get("vpp_v"), rd.get("confidence"),
               route=route, wave_present=rd.get("wave_present"),
               source="scope_screen:%s" % rd.get("source"), lib=lib, **judge_kw)
    ev.update({
        "screen_box": rd.get("screen_box"),
        "screen_ok": rd.get("screen_ok"),
        "reading_confidence": rd.get("confidence"),
        "freq_source": rd.get("source"),
        "ns_per_div": rd.get("ns_per_div"),
        "period_px": rd.get("period_px"),
        "peak": rd.get("peak"),
        "reading_reason": rd.get("reason"),
    })
    return ev

def annotate(frame: Any, out_path: str, screen: Optional[Dict[str, Any]] = None,
             trace: Optional[Dict[str, Any]] = None) -> str:
    """画屏幕框 + 提取到的曲线（给现场留证）。"""
    from PIL import Image, ImageDraw
    a = _as_array(frame)
    if a is None:
        raise ValueError("无画面")
    a = _apply_order(a, "auto")
    im = Image.fromarray(a.astype(np.uint8))
    d = ImageDraw.Draw(im)
    box = (screen or locate_screen(a))["box"]
    d.rectangle([box[0], box[1], box[2], box[3]], outline=(255, 0, 0), width=3)
    tr = trace if trace is not None else extract_trace(a, box)
    if tr.get("curve") is not None:
        xs, ys = tr["curve"]
        pts = [(box[0] + int(x), box[1] + int(y)) for x, y in zip(xs, ys)]
        if len(pts) > 1:
            d.line(pts, fill=(0, 255, 0), width=2)
    im.save(out_path)
    return out_path

def _selftest(lib: ScopeLibrary) -> int:
    s = lib.summary()
    print(json.dumps(s, ensure_ascii=False, indent=2))
    bad = 0
    if s["items"] != 28:
        print("!! 项数 %d != 28" % s["items"]); bad += 1
    if len({it.get("field") for it in lib.items}) != s["items"]:
        print("!! field 不唯一"); bad += 1
    for it in lib.items:
        if not it.get("判据来源"):
            print("!! 缺判据来源:", it.get("item_id")); bad += 1
        if not it.get("signal") or not it.get("part"):
            print("!! 缺 signal/part:", it.get("item_id")); bad += 1
    print("自检：%s" % ("通过" if bad == 0 else "%d 处问题" % bad))
    return 0 if bad == 0 else 1

def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                       
        pass
    ap = argparse.ArgumentParser(description="示波器波形项判据引擎（28 项）")
    ap.add_argument("--items", default="", help="scope_items.json 路径")
    ap.add_argument("--list", action="store_true", help="列出 28 项")
    ap.add_argument("--selftest", action="store_true", help="判据库自检")
    ap.add_argument("--signal", "--judge", dest="signal", default="",
                    metavar="SIGNAL", help="信号名 / 项目原文")
    ap.add_argument("--route", default="", choices=["", "I", "II"])
    ap.add_argument("--flow", type=int, default=None)
    ap.add_argument("--sub", type=int, default=None)
    ap.add_argument("--check-item", default="")
    ap.add_argument("--freq", type=float, default=None, help="实测频率 Hz")
    ap.add_argument("--vpp", type=float, default=None, help="实测 Vpp (V)")
    ap.add_argument("--conf", type=float, default=None, help="读数置信度 0..1")
    ap.add_argument("--tol", type=float, default=None, help="容差 %%（默认该项目 4.0）")
    ap.add_argument("--wave", type=int, default=None, choices=[0, 1],
                    help="1=有波形 0=无波形")
    ap.add_argument("--no-signal-verdict", default="", choices=["", "undetermined", "abnormal"])
    ap.add_argument("--frame", default="", help="拍屏图片")
    ap.add_argument("--ns-per-div", type=float, default=None)
    ap.add_argument("--ocr-text", default="", help="模拟 OCR 文本（无 OCR 后端时验证解析）")
    ap.add_argument("--backend", default="builtin", choices=["builtin", "ui_kiosk", "auto"])
    ap.add_argument("--annot", default="", help="标注图输出路径")
    args = ap.parse_args(argv)

    lib = library(args.items or None)
    if args.list:
        for it in lib.items:
            print("%2d flow%-2s %-28s part=%-4s route=%-2s %-12s tol=%s"
                  % (it["item_no"], it["flow_no"], it["signal"], it["part"], it["route"],
                     fmt_hz(it.get("expect_freq_hz")), it.get("tol_pct")))
        return 0
    if args.selftest or not (args.frame or args.signal or args.flow is not None):
        return _selftest(lib)

    kw: Dict[str, Any] = {}
    if args.route:
        kw["route"] = args.route
    if args.flow is not None:
        kw["flow_no"] = args.flow
    if args.sub is not None:
        kw["sub_no"] = args.sub
    if args.check_item:
        kw["check_item"] = args.check_item
    if args.tol is not None:
        kw["tol_pct"] = args.tol
    if args.wave is not None:
        kw["wave_present"] = bool(args.wave)
    if args.no_signal_verdict:
        kw["no_signal_verdict"] = args.no_signal_verdict

    if args.frame:
        ocr_fn = (lambda _crop: args.ocr_text) if args.ocr_text else None
        rd = read_scope_screen(args.frame, ns_per_div=args.ns_per_div, ocr_fn=ocr_fn,
                               backend=args.backend)
        if args.annot:
            print("标注图: %s" % annotate(args.frame, args.annot))
        ev = judge(args.signal or args.check_item, rd.get("freq_hz"), rd.get("vpp_v"),
                   rd.get("confidence"), wave_present=rd.get("wave_present"),
                   source="scope_screen:%s" % rd.get("source"), lib=lib, **kw)
        ev["reading"] = {k: rd.get(k) for k in
                         ("ok", "source", "confidence", "wave_present", "screen_box",
                          "ns_per_div", "period_px", "peak", "cols", "reason", "backend")}
    else:
        ev = judge(args.signal or args.check_item, args.freq, args.vpp,
                   (1.0 if args.conf is None else args.conf), lib=lib, **kw)
    print(json.dumps(ev, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
