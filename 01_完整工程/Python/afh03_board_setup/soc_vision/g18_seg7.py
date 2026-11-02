# -*- coding: utf-8 -*-
"""g18_seg7.py — G18 三块红色 LED 七段表读数 + Z18 相电压多模态判定（读数→判定→问答预填）。

定位（2026-10-29 现场）
=======================
G18 配电盘三块 XIELI 红色 LED 七段面板表。两张不同机位/光照的现场照片实测：

    照片                                 左表        中表          右表
    /userdata/afh03_shots/20261029_201402 270         00336.3       228
    /userdata/afh03_shots/20261025_105447 270         00333.0       228

⇒ 中表在 4.4 天里 00333.0→00336.3 递增（计数器/计时器量纲，非相电压）；
  左表 270、右表 228 稳定；只有右表 228 落在 Z18 相电压判据 198~242V 内。
⇒ 默认把「Z18 相电压」指向右表（`phase_voltage_display="right"`），
  中表判为计数器（role=counter）、左表判为其它电压表（role=other_voltage）。
  **该表-相位映射尚未现场核实**（表头丝印不可读），`mapping_confirmed=false`；
  接线/选相开关确认后改 `config/g18_displays.json` 即可，不改代码。

本模块提供（Lead 要的「先读数、再判定、后问答」三件套）
========================================================
  1. `read_g18(img)` -> 三块表 {value,text,conf,bbox,reason,valid}
  2. `classify_voltage(v)` -> done / under_voltage / over_voltage / not_done（198~242V）
  3. `z18_phase_pack(img, phase)` -> 一次给出：
       - readings     三块表原始读数（结果页可先显示数字）
       - rows         board_infer 结果页逐条结构（kind/pos/name/state/state_text/match/...）
       - evidence_items  evidence/v1 契约（字段 `(manual_action)_z18_phase_a_voltage` 等）
       - prefill      QA 预填（qa_id + measured + suggested_answer + confidence）
       - conclusion   ✅正常/❌异常/⚠未判定
  4. `build_z18_phase_evidence(phase, reading)` 单条证据（与 qa_flow 同契约）
  5. 命令行：`python3 -m soc_vision.g18_seg7 -i IMG [--phase A] [--json out] [--annotate out.png]`

★ 读数器：底层复用 `/userdata/work2/engine/seg7_read.py`（2026-10-29 增补
  box_mode="runs" / bin_mode="soft" / dp_index_hint 多小数点裁定，默认行为不变）。
★ 契约：读不出 ⇒ value=None + reason，绝不编造；conf 只在有读数时有意义。
★ 不改 ui_kiosk.py：集成 patch/说明见 `_work_20261029_ui_bug/z18_vision_integration_patch.md`。

作者：AFH03 视觉子链（2026-10-29 G18 现场）
"""

from __future__ import annotations

import json
import os
import sys

import cv2
import numpy as np

__all__ = [
    "read_g18",
    "read_display",
    "classify_voltage",
    "build_z18_phase_evidence",
    "z18_phase_pack",
    "read_z18_phase_voltage",
    "load_config",
    "DEFAULT_DISPLAYS",
    "PHASE_FIELDS",
    "PHASE_QA_IDS",
    "VOLTAGE_RANGE",
]

VERSION = "2026-10-29.2"

_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(os.path.dirname(_HERE), "config", "g18_displays.json")

REF_W, REF_H = 1920, 1080

VOLTAGE_RANGE = (198.0, 242.0)

PHASE_FIELDS = {
    "A": "(manual_action)_z18_phase_a_voltage",
    "B": "(manual_action)_z18_phase_b_voltage",
    "C": "(manual_action)_z18_phase_c_voltage",
}

_PHASE_QA_IDS = {"A": "QA002", "B": "QA003", "C": "QA004"}
PHASE_QA_IDS = dict(_PHASE_QA_IDS)

DEFAULT_DISPLAYS = (
    dict(key="left", label="左表", role="other_voltage",
         role_note="两张现场照片均 270（稳定）；不在 198~242V，疑 DC 母线/其它电压表，待现场确认",
         ndigits=3, has_dp=False, dp_index_hint=None,
         roi_tight=(370, 440, 170, 100), roi_band=(320, 375, 330, 215),
         evidence_field="(vision)_g18_display_left"),
    dict(key="middle", label="中表", role="counter",
         role_note="00333.0(10-25)→00336.3(10-29) 跨天递增 ⇒ 计数器/计时器，非相电压",
         ndigits=6, has_dp=True, dp_index_hint=4,
         roi_tight=(845, 440, 300, 100), roi_band=(720, 375, 470, 215),
         evidence_field="(vision)_g18_display_middle"),
    dict(key="right", label="右表", role="phase_voltage",
         role_note="两张照片均 228 且落在 198~242V ⇒ 默认当相电压表（相序/电压选择开关切相）",
         ndigits=3, has_dp=False, dp_index_hint=None,
         roi_tight=(1490, 450, 180, 100), roi_band=(1185, 375, 580, 220),
         evidence_field="(manual_action)_z18_phase_a_voltage"),
)

_DEFAULT_CONFIG = {
    "note": "G18 三块七段表读数 + Z18 相电压多模态判定配置（2026-10-29 子 agent 生成）",
    "version": VERSION,
    "reference_size": [REF_W, REF_H],
    "displays": [dict(d) for d in DEFAULT_DISPLAYS],
    "phase_voltage_display": "right",
    "phase_voltage_range": list(VOLTAGE_RANGE),
    "phase_qa_ids": dict(_PHASE_QA_IDS),
    "mapping_confirmed": False,
    "mapping_note": (
        "三块表的表头丝印在现有照片上不可读；中表已由两次实拍证明是计数器（00333.0→00336.3），"
        "左表 270 不在相电压判据内，仅右表 228 符合 198~242V，故默认相电压=右表。"
        "现场确认相序/电压选择开关与表位对应关系后，把 mapping_confirmed 改 true；"
        "若相电压表是别的表，改 phase_voltage_display。"
    ),
}

MIN_CONF = 0.55
VALUE_RANGE = (0.0, 9999.0)

_ENGINE_CACHE = {}

def _engine():
    """返回已打补丁的 seg7_read 模块（导入失败明确报错，不静默降级）。"""
    if "m" in _ENGINE_CACHE:
        return _ENGINE_CACHE["m"]
    try:
        import seg7_read as SR                          
    except Exception:
        for d in ("/userdata/work2/engine", os.path.expanduser("~/afh03_board_setup/engine")):
            if os.path.isdir(d) and d not in sys.path:
                sys.path.insert(0, d)
        import seg7_read as SR                          
    if not hasattr(SR, "read_seg7"):
        raise ImportError("seg7_read 缺少 read_seg7：%r" % (SR,))
    _ENGINE_CACHE["m"] = SR
    return SR

def load_config(path=None):
    """读 config/g18_displays.json；不存在则用内置默认。"""
    cfg = json.loads(json.dumps(_DEFAULT_CONFIG))
    p = path or CONFIG_PATH
    if p and os.path.isfile(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                user = json.load(f)
        except Exception as exc:                        
            cfg["config_error"] = "读取 %s 失败: %s" % (p, exc)
            return cfg
        for k, v in user.items():
            if k == "displays" and isinstance(v, list) and v:
                cfg["displays"] = v
            else:
                cfg[k] = v
        cfg["_config_path"] = p
    else:
        cfg["_config_path"] = None
    return cfg

def _displays(cfg):
    out = []
    defaults = {d["key"]: d for d in DEFAULT_DISPLAYS}
    for d in cfg.get("displays") or DEFAULT_DISPLAYS:
        dd = dict(defaults.get(d.get("key"), {}))
        dd.update(d)
        dd.setdefault("key", "d%d" % len(out))
        dd.setdefault("label", dd["key"])
        dd.setdefault("role", "unknown")
        dd.setdefault("role_note", "")
        dd.setdefault("ndigits", 3)
        dd.setdefault("has_dp", False)
        dd.setdefault("dp_index_hint", None)
        dd.setdefault("roi_tight", None)
        dd.setdefault("roi_band", None)
        dd.setdefault("evidence_field", "(vision)_g18_display_%s" % dd["key"])
        out.append(dd)
    return out

def _scale_roi(roi, shape):
    if not roi:
        return None
    H, W = shape[:2]
    sx, sy = W / float(REF_W), H / float(REF_H)
    x, y, w, h = [int(round(float(v) * s)) for v, s in zip(roi, (sx, sy, sx, sy))]
    x = max(0, min(x, W - 2))
    y = max(0, min(y, H - 2))
    w = max(8, min(w, W - x))
    h = max(8, min(h, H - y))
    return [x, y, w, h]

def _valid_reading(r, spec):
    if not r or r.get("value") is None:
        return False
    n = int(spec["ndigits"])
    txt = r.get("raw_text")
    if txt is None:
        txt = r.get("text") or ""
    if len(str(txt)) != n:
        return False
    if spec["has_dp"]:
        if r.get("dp_pos") != spec["dp_index_hint"]:
            return False
    elif r.get("dp_pos") is not None:
        return False
    if float(r.get("conf") or 0.0) < MIN_CONF:
        return False
    lo, hi = VALUE_RANGE
    return lo <= float(r["value"]) <= hi

def _with_dp(raw_text, dp_pos):
    """引擎 text 是纯数字（如 "003363"）；按 dp_pos 插入小数点给人看（"00336.3"）。"""
    t = str(raw_text or "")
    if dp_pos is None or not t:
        return t
    k = int(dp_pos) + 1
    if 0 < k < len(t):
        return t[:k] + "." + t[k:]
    return t

def _read_one(img, spec, roi):
    SR = _engine()
    try:
        r = SR.read_seg7(
            img, roi=roi, ndigits=int(spec["ndigits"]), has_dp=bool(spec["has_dp"]),
            dp_index_hint=spec["dp_index_hint"], value_range=(0, 10000),
            box_mode="runs", bin_mode="soft",
        )
    except Exception as exc:                            
        r = dict(value=None, text="", conf=0.0, bbox=list(roi or []),
                 reason="read_error:%s" % exc, dp_pos=None)
    out = dict(
        key=spec["key"], label=spec["label"], role=spec.get("role"),
        role_note=spec.get("role_note") or "",
        evidence_field=spec.get("evidence_field"),
        value=r.get("value"), text=_with_dp(r.get("text"), r.get("dp_pos")),
        raw_text=r.get("text") or "",
        conf=round(float(r.get("conf") or 0.0), 4),
        bbox=r.get("bbox"), dp_pos=r.get("dp_pos"),
        reason=r.get("reason") or "",
        spec=dict(ndigits=spec["ndigits"], has_dp=spec["has_dp"],
                  dp_index_hint=spec["dp_index_hint"]),
    )
    out["valid"] = _valid_reading(r, spec)
    return out

def _enumerate_candidates(img, roi):
    """引擎内部候选枚举：ROI 内可能的显示条绝对框（私有 API 缺失时返回 []）。"""
    try:
        SR = _engine()
        for fn in ("_feature_maps", "_red_geometry", "_ink_candidates", "_strip_hypotheses"):
            if not hasattr(SR, fn):
                return []
        x, y, w, h = roi
        work = img[y:y + h, x:x + w]
        if work.size == 0:
            return []
        feat = SR._feature_maps(work)
        red = SR._red_geometry(feat)
        boxes = []
        for _mode, mask in SR._ink_candidates(feat, red):
            for b in SR._strip_hypotheses(mask):
                boxes.append([b[0] + x, b[1] + y, b[2], b[3]])
        uniq = []
        for b in sorted(boxes, key=lambda z: -z[2] * z[3]):
            if all(_iou(b, u) < 0.70 for u in uniq):
                uniq.append(b)
        return uniq
    except Exception:                                   
        return []

def _iou(a, b):
    ax0, ay0, ax1, ay1 = a[0], a[1], a[0] + a[2], a[1] + a[3]
    bx0, by0, bx1, by1 = b[0], b[1], b[0] + b[2], b[1] + b[3]
    ix = max(0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    ua = a[2] * a[3] + b[2] * b[3] - inter
    return inter / float(ua) if ua > 0 else 0.0

def read_display(img, spec, roi=None):
    """读一块表：紧 ROI / 宽搜索带 / ROI 内候选枚举 三级尝试 + 跨 ROI 一致性校验。

    ★ 一致性校验（2026-10-29 加入）：同一块表用「紧 ROI」和「宽搜索带」各读一次，
      两个口径都读出时必须数值一致才采信；不一致说明有一个口径只框到局部数字
      （换机位后紧 ROI 可能只盖住表的角落）⇒ 改用候选枚举重读，仍冲突就如实失败
      （value=None, reason="roi_value_conflict"，不把局部读数当成功）。
    """
    if isinstance(img, str):
        img = _engine().imread_u(img)
    empty = dict(key=spec["key"], label=spec["label"], role=spec.get("role"),
                 role_note=spec.get("role_note") or "",
                 evidence_field=spec.get("evidence_field"),
                 value=None, text="", raw_text="", conf=0.0, bbox=None, dp_pos=None,
                 reason="no_image", valid=False,
                 spec=dict(ndigits=spec["ndigits"], has_dp=spec["has_dp"],
                           dp_index_hint=spec["dp_index_hint"]))
    if img is None:
        return empty
    attempts = []
    for cand in (roi, spec.get("roi_tight"), spec.get("roi_band")):
        if not cand:
            continue
        sc = _scale_roi(cand, img.shape)
        if sc and sc not in attempts:
            attempts.append(sc)
    results = []
    for a in attempts:
        r = _read_one(img, spec, a)
        r["roi_used"] = a
        results.append(r)
    valids = [r for r in results if r["valid"]]
    if valids:
        vals = {round(float(r["value"]), 3) for r in valids}
        if len(vals) == 1:
            best = max(valids, key=lambda z: z["conf"])
            best["cross_check"] = ("agreed:%d" % len(valids)) if len(valids) > 1 else "single_roi"
            return best

        band = _scale_roi(spec.get("roi_band"), img.shape)
        cand = _read_from_candidates(img, spec, band or attempts[-1])
        if cand is not None:
            cand["cross_check"] = "candidate_resolve"
            return cand
        best = max(valids, key=lambda z: z["conf"])
        best["valid"] = False
        best["reason"] = "roi_value_conflict%s" % sorted(vals)
        return best
    cand = _read_from_candidates(img, spec, attempts[-1]) if attempts else None
    if cand is not None:
        cand["cross_check"] = "candidate_only"
        return cand
    out = results[0] if results else empty
    out["valid"] = False
    if not out.get("reason"):
        out["reason"] = "unreadable"
    return out

def _read_from_candidates(img, spec, roi):
    """在 ROI 内枚举候选显示条逐个试，返回第一个合法读数（无则 None）。"""
    if not roi:
        return None
    for box in _enumerate_candidates(img, roi):
        pad_x, pad_y = int(0.15 * box[2]), int(0.15 * box[3])
        roi2 = [max(0, box[0] - pad_x), max(0, box[1] - pad_y),
                box[2] + 2 * pad_x, box[3] + 2 * pad_y]
        r = _read_one(img, spec, roi2)
        if r["valid"]:
            r["roi_used"] = roi2
            return r
    return None

def read_g18(img_or_path, config=None, mode="auto"):
    """G18 三块表读数。

    返回 {"ok","image_size","displays":{key:...},"readings":{key:value},
          "failed":[key...],"notes":[...],"version","config_path"}
    """
    SR = _engine()
    cfg = config or load_config()
    if isinstance(img_or_path, str):
        img = SR.imread_u(img_or_path)
        path = img_or_path
    else:
        img = img_or_path
        path = None
    if img is None:
        return dict(ok=False, image_size=None, displays={}, readings={},
                    failed=["all"], notes=["no_image:%s" % path], version=VERSION)
    out, notes = {}, []
    for spec in _displays(cfg):
        if spec.get("enabled") is False:
            continue
        if mode == "static":
            r = _read_one(img, spec, _scale_roi(spec.get("roi_tight") or spec.get("roi_band"),
                                               img.shape))
            r["valid"] = _valid_reading(r, spec)
        else:
            r = read_display(img, spec)
        out[spec["key"]] = r
        if not r["valid"]:
            notes.append("%s 读不出：%s" % (spec["label"], r.get("reason") or "?"))
    failed = [k for k, v in out.items() if not v.get("valid")]
    return dict(ok=(len(failed) == 0),
                image_size=[int(img.shape[1]), int(img.shape[0])],
                displays=out, readings={k: v.get("value") for k, v in out.items()},
                failed=failed, notes=notes, version=VERSION,
                config_path=cfg.get("_config_path"))

def classify_voltage(value, normal_range=None):
    """数值 -> done / under_voltage / over_voltage / not_done（qa_items 同词表）。"""
    lo, hi = normal_range or VOLTAGE_RANGE
    if value is None:
        return "not_done"
    v = float(value)
    if v < float(lo):
        return "under_voltage"
    if v > float(hi):
        return "over_voltage"
    return "done"

_STATUS_TEXT = {
    "done": "正常（{v:g} V 在 {lo:g}~{hi:g} V 内）",
    "under_voltage": "欠压（{v:g} V < {lo:g} V）",
    "over_voltage": "过压（{v:g} V > {hi:g} V）",
    "not_done": "未读数（七段码读不出，保持 QA 人工测量）",
}
_STATUS_CN = {"done": "正常", "under_voltage": "欠压",
              "over_voltage": "过压", "not_done": "未读数"}

def _now_iso():
    import datetime
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")

def build_z18_phase_evidence(phase, reading, *, confidence=None, display_key=None,
                             schema_values=False, source="z18_multimodal", note="",
                             ts=None):
    """生成与 qa_flow.QAFlow.answer() 同契约的 Z18 相电压 evidence。

    reading: 数值(V) 或 read_g18() 的某块表 dict（有 value/conf/text）
    schema_values: True ⇒ done→normal、over_voltage→abnormal，原词放 qa_value
                   （与 qa_flow schema_values 行为一致）
    """
    ph = str(phase).strip().upper()
    if ph not in PHASE_FIELDS:
        raise ValueError("phase 必须是 A/B/C：%r" % (phase,))
    if isinstance(reading, dict):
        value = reading.get("value")
        conf = reading.get("conf")
        display_key = display_key or reading.get("key")
        measured = reading.get("text") or (None if value is None else "%.1f" % float(value))
    else:
        value, conf = reading, None
        measured = None if value is None else "%.1f" % float(value)
    lo, hi = VOLTAGE_RANGE
    status = classify_voltage(value, VOLTAGE_RANGE)
    if confidence is None:
        confidence = 0.9 if conf in (None, 0) else float(conf)
    confidence = round(max(0.0, min(1.0, float(confidence))), 3)
    if value is None:
        confidence = 0.0
    text = _STATUS_TEXT[status].format(v=float(value) if value is not None else 0.0,
                                       lo=lo, hi=hi)
    ev_note = "视觉读数：" + text
    if display_key:
        ev_note += "（来源表 %s）" % display_key
    if note:
        ev_note += "；" + note
    ev_text = "Z18 %s相电压：%s" % (ph, text)
    if display_key:
        ev_text += "（七段表 %s）" % display_key
    if note:
        ev_text += "；" + note
    emitted = status
    if schema_values:
        emitted = {"done": "normal", "over_voltage": "abnormal"}.get(status, status)
    ev = {
        "part": "z18", "route": "", "modality": "vision",
        "field": PHASE_FIELDS[ph], "value": emitted, "confidence": confidence,
        "note": ev_note, "evidence": ev_text, "ts": ts or _now_iso(),
        "source": source,
    }
    if schema_values and emitted != status:
        ev["qa_value"] = status
    if measured is not None:
        ev["measured"] = measured
    if value is not None:
        ev["measured_value"] = float(value)
        ev["unit"] = "V"
    if display_key:
        ev["display"] = display_key
    ev["normal_range"] = [lo, hi]
    return ev

def _phase_reading(g, cfg, phase, config_key=None):
    """挑出「相电压表」那块读数。返回 (display_key, display_dict|None)。"""
    key = config_key or cfg.get("phase_voltage_display") or ""
    return key, (g.get("displays") or {}).get(key)

def z18_rows(g18, phase="", config=None):
    """把三块表读数整理成 board_infer/结果页可直接用的 rows + 证据 + 预填。

    返回 dict:
      rows            [3 条] 结果页逐条（kind="seg7"）
      evidence_items  evidence/v1 证据（相电压 1 条；未给 phase 时为空）
      prefill         QA 预填 {qa_id, measured, suggested_answer, confidence, note}
      conclusion      {"state": "ok"|"bad"|"unknown", "text", "why", ...}
      mapping_confirmed / warnings
    """
    cfg = config or load_config()
    lo, hi = cfg.get("phase_voltage_range") or list(VOLTAGE_RANGE)
    confirmed = bool(cfg.get("mapping_confirmed"))
    key, disp = _phase_reading(g18, cfg, phase)
    warnings = []
    if not confirmed:
        warnings.append(cfg.get("mapping_note") or "表-相位映射未现场确认")

    rows = []
    for k, d in (g18.get("displays") or {}).items():
        role = d.get("role") or "unknown"
        role_note = d.get("role_note") or ""
        if d.get("enabled") is False or role in ("counter", "ignore"):
            continue
        is_phase = (bool(key) and k == key)
        if is_phase:
            name = "%s（相电压表?）" % d.get("label")
        elif role in ("battery_voltage", "battery", "work_voltage", "work"):
            name = d.get("label") or "电池电压"
        elif role in ("mains_voltage", "mains", "phase_voltage"):
            name = d.get("label") or "市电电压"
        elif role == "other_voltage":
            name = "%s（其它电压表）" % d.get("label")
        else:
            name = d.get("label")
        if d.get("valid"):
            val = float(d["value"])
            text = d.get("text") or ("%g" % val)
            state = "read"
            state_text = "读数 %s" % text
            why = "七段码读数=%s，conf=%.2f，bbox=%s" % (text, d.get("conf") or 0.0, d.get("bbox"))
            conf = d.get("conf") or 0.0
            match = None
            measured = text
        else:
            val = None
            text = ""
            state = "undetermined"
            state_text = "未读数"
            why = "读不出：%s" % (d.get("reason") or "?")
            conf = 0.0
            match = None
            measured = ""
        if is_phase and phase:
            status = classify_voltage(val, (lo, hi))
            state = status
            state_text = _STATUS_CN[status]
            match = (status == "done")
            expect_text = "%g~%gV" % (lo, hi)
            why = "%s；判据 %g~%gV → %s" % (why, lo, hi, _STATUS_CN[status])
            field = PHASE_FIELDS[str(phase).strip().upper()]
            check_item = "Z18（控制）-(下柜）-[电压测量]-%s相电压正常（%gV～%gV）" % (
                str(phase).strip().upper(), lo, hi)
        else:
            expect_text = ""
            field = d.get("evidence_field") or "(vision)_g18_display_%s" % k
            check_item = "G18 七段表 %s 读数" % d.get("label")
        if role == "counter" and is_phase is False:
            pass  
        rows.append({
            "kind": "seg7", "pos": d.get("label") or k, "name": name,
            "state": state, "state_text": state_text, "expect_text": expect_text,
            "match": match, "value": val, "text": text, "conf": round(float(conf), 3),
            "meaning": check_item, "why": why, "role": role, "role_note": role_note,
            "field": field, "route": "", "part": "z18" if is_phase else "",
            "rule": "seg7:g18#%s" % k,
        })

    evidence_items = []
    prefill = None
    if phase and key and disp is not None:
        ph = str(phase).strip().upper()
        status = classify_voltage((disp or {}).get("value"), (lo, hi))
        note_bits = []
        if not confirmed:
            note_bits.append("表-相位映射未现场确认")
        others = []
        for k, d in (g18.get("displays") or {}).items():
            if k == key:
                continue
            others.append("%s=%s" % (d.get("label"), d.get("text") or "未读数"))
        if others:
            note_bits.append("同帧其它表：" + "，".join(others))
        ev = build_z18_phase_evidence(
            ph, (disp or {"value": None}), display_key=key,
            note=("；".join(note_bits)), schema_values=False)
        evidence_items.append(ev)
        qa_id = (cfg.get("phase_qa_ids") or PHASE_QA_IDS).get(ph, "")
        prefill = {
            "qa_id": qa_id,
            "phase": ph,
            "measured": (disp or {}).get("value"),
            "measured_text": (disp or {}).get("text"),
            "suggested_answer": status,
            "confidence": round(float((disp or {}).get("conf") or 0.0), 3),
            "display": key,
            "normal_range": [lo, hi],
            "mapping_confirmed": confirmed,
            "note": ev["note"],
            "evidence": ev,
        }

        if not (disp or {}).get("valid"):
            conclusion = {"state": "unknown", "text": "未判定（相电压表未读数）",
                          "why": (disp or {}).get("reason") or "",
                          "n_bad": 0, "n_ok": 0}
        elif status == "done":
            conclusion = {"state": "ok",
                          "text": "正常（%s相 %sV 在 %g~%gV）" % (ph, (disp or {}).get("text"), lo, hi),
                          "why": ev["note"], "n_bad": 0, "n_ok": 1}
        else:
            conclusion = {"state": "bad",
                          "text": "异常：%s相%s（%sV）" % (ph, _STATUS_CN[status], (disp or {}).get("text")),
                          "why": ev["note"], "n_bad": 1, "n_ok": 0}
    else:
        ok = bool(g18.get("ok"))
        conclusion = {"state": "ok" if ok else "unknown",
                      "text": "工作电压/市电电压读数完成" if ok else "有表读不出",
                      "why": "；".join(g18.get("notes") or []) or "工作电压/市电电压均读出（计时器不读）",
                      "n_bad": 0, "n_ok": sum(1 for d in (g18.get("displays") or {}).values()
                                              if d.get("valid"))}
    return dict(rows=rows, evidence_items=evidence_items, prefill=prefill,
                conclusion=conclusion, mapping_confirmed=confirmed,
                warnings=warnings, readings=g18.get("readings") or {},
                displays=g18.get("displays") or {})

def z18_phase_pack(img_or_path, phase, config=None, mode="auto"):
    """Lead 要的一步式入口：读图 → 三块读数 → 相电压判定 → rows/evidence/prefill/结论。"""
    cfg = config or load_config()
    g = read_g18(img_or_path, config=cfg, mode=mode)
    _phase = phase if cfg.get("phase_voltage_display") else ""
    pack = z18_rows(g, phase=_phase, config=cfg)
    pack["g18"] = g
    pack["phase"] = str(_phase).strip().upper()
    return pack

def read_z18_phase_voltage(img_or_path, phase, config=None, display_key=None,
                           require_mapping_confirmed=False):
    """兼容入口：返回单相判定 + evidence（不返回 rows）。"""
    cfg = config or load_config()
    g = read_g18(img_or_path, config=cfg)
    key = display_key or cfg.get("phase_voltage_display") or "right"
    disp = (g.get("displays") or {}).get(key)
    confirmed = bool(cfg.get("mapping_confirmed"))
    warnings = []
    if not confirmed:
        warnings.append(cfg.get("mapping_note") or "相电压表映射未确认")
    if disp is None:
        status = "not_done"
        ev = build_z18_phase_evidence(phase, None, display_key=key,
                                      note="所选七段表不存在（配置错误）")
    else:
        status = classify_voltage(disp.get("value"), cfg.get("phase_voltage_range"))
        if require_mapping_confirmed and not confirmed:
            status = "not_done"
            note = "映射未确认，拒绝自动判定 → 保持 QA"
        else:
            note = "" if confirmed else "表-相位映射未现场确认"
        ev = build_z18_phase_evidence(phase, disp, display_key=key, note=note)
    return dict(phase=phase, display=key, reading=(disp or {}).get("value"),
                display_text=(disp or {}).get("text"), display_conf=(disp or {}).get("conf"),
                status=status, evidence=ev, mapping_confirmed=confirmed,
                warnings=warnings, g18=g)

def selftest():
    """无图自检：判定边界 + 三字段证据契约 + rows/prefill 契约 + JSON 序列化。"""
    errs = []
    for v, want in ((197.9, "under_voltage"), (198.0, "done"), (242.0, "done"),
                    (242.1, "over_voltage"), (None, "not_done"), (0.0, "under_voltage")):
        got = classify_voltage(v)
        if got != want:
            errs.append("classify(%r)=%r 应为 %r" % (v, got, want))
    for ph in ("A", "B", "C"):
        ev = build_z18_phase_evidence(ph, 228.0, confidence=0.84, display_key="right")
        if ev["field"] != PHASE_FIELDS[ph]:
            errs.append("%s 字段错: %s" % (ph, ev["field"]))
        if ev["value"] != "done":
            errs.append("%s 228V 应为 done: %r" % (ph, ev["value"]))
        try:
            json.dumps(ev, ensure_ascii=False)
        except Exception as exc:                        
            errs.append("%s 证据不可 JSON 序列化: %s" % (ph, exc))
    ev = build_z18_phase_evidence("A", 270.0, confidence=0.7, display_key="left")
    if ev["value"] != "over_voltage":
        errs.append("270V 应为 over_voltage: %r" % ev["value"])
    ev = build_z18_phase_evidence("B", None, display_key="middle")
    if ev["value"] != "not_done" or ev["confidence"] != 0.0:
        errs.append("未读数证据应 value=not_done/conf=0: %r" % (ev,))

    fake = dict(ok=True, image_size=[1920, 1080], notes=[], version=VERSION,
                displays={
                    "left": dict(key="left", label="左表", role="other_voltage",
                                 role_note="", evidence_field="(vision)_g18_display_left",
                                 value=270.0, text="270", conf=0.907, bbox=[1, 2, 3, 4],
                                 valid=True, reason=""),
                    "middle": dict(key="middle", label="中表", role="counter",
                                   role_note="", evidence_field="(vision)_g18_display_middle",
                                   value=336.3, text="00336.3", conf=0.842, bbox=[1, 2, 3, 4],
                                   valid=True, reason=""),
                    "right": dict(key="right", label="右表", role="phase_voltage",
                                  role_note="", evidence_field="(manual_action)_z18_phase_a_voltage",
                                  value=228.0, text="228", conf=0.840, bbox=[1, 2, 3, 4],
                                  valid=True, reason=""),
                }, readings={"left": 270.0, "middle": 336.3, "right": 228.0})
    pk = z18_rows(fake, phase="A", config=load_config("/nonexistent.json"))
    if len(pk["rows"]) != 3:
        errs.append("rows 应 3 条: %d" % len(pk["rows"]))
    if pk["prefill"]["qa_id"] != "QA002":
        errs.append("A 相应预填 QA002: %r" % (pk["prefill"]["qa_id"],))
    if pk["prefill"]["suggested_answer"] != "done":
        errs.append("228V 预填应为 done")
    if pk["evidence_items"][0]["field"] != PHASE_FIELDS["A"]:
        errs.append("rows 证据字段应为 A 相字段")
    if not pk["mapping_confirmed"]:
        pass  
    if not pk["warnings"]:
        errs.append("映射未确认时应有 warnings")
    try:
        json.dumps(pk, ensure_ascii=False)
    except Exception as exc:                            
        errs.append("pack 不可 JSON 序列化: %s" % exc)
    return dict(ok=not errs, errors=errs,
                checks="classify+evidence+rows+prefill+json")

def _annotate(img, g):
    SR = _engine()
    items = []
    for _k, d in (g.get("displays") or {}).items():
        if d.get("bbox"):
            items.append(dict(value=d.get("value"), conf=d.get("conf"),
                              bbox=d.get("bbox"), text=d.get("text"),
                              reason=d.get("reason")))
    return SR.annotate(img, items)

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="G18 三块七段表读数 + Z18 相电压多模态判定")
    ap.add_argument("-i", "--image", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--annotate", default="")
    ap.add_argument("--phase", default="", help="相别 A/B/C：输出该相判定/rows/prefill")
    ap.add_argument("--display", default="", help="相电压取哪块表（默认按配置）")
    ap.add_argument("--schema-values", action="store_true", help="证据 value 用 evidence/v1 枚举")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--mode", default="auto", choices=("auto", "static"))
    a = ap.parse_args(argv)

    if a.selftest or not a.image:
        st = selftest()
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0 if st["ok"] else 1

    SR = _engine()
    img = SR.imread_u(a.image)
    if img is None:
        print("读图失败: %s" % a.image)
        return 2
    cfg = load_config()
    if a.display:
        cfg["phase_voltage_display"] = a.display
    g = read_g18(img, config=cfg, mode=a.mode)
    print("图 %s  %dx%d  version=%s  config=%s" % (
        os.path.basename(a.image), g["image_size"][0], g["image_size"][1],
        g["version"], g.get("config_path")))
    for k, d in (g.get("displays") or {}).items():
        print("  [%s] %-4s role=%-13s value=%-8s text=%-8r conf=%.3f bbox=%s reason=%r" % (
            k, d.get("label"), d.get("role"), d.get("value"), d.get("text"),
            d.get("conf") or 0.0, d.get("bbox"), d.get("reason")))
    print("  ok=%s failed=%s notes=%s" % (g["ok"], g["failed"], g["notes"]))
    payload = {"g18": g}
    if a.phase:
        pack = z18_rows(g, phase=a.phase, config=cfg)
        print("  Z18 %s相: %s  mapping_confirmed=%s" % (
            a.phase, pack["conclusion"]["text"], pack["mapping_confirmed"]))
        for w in pack["warnings"]:
            print("    警告: %s" % w)
        print("    prefill: %s" % json.dumps(pack["prefill"], ensure_ascii=False))
        print("    evidence: %s" % json.dumps(pack["evidence_items"], ensure_ascii=False))
        payload["z18"] = pack
    if a.annotate:
        ok = SR.imwrite_u(a.annotate, _annotate(img, g))
        print("  标注图 -> %s (%s)" % (a.annotate, "ok" if ok else "fail"))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print("  JSON -> %s" % a.json)
    return 0 if g["ok"] else 3

if __name__ == "__main__":
    raise SystemExit(main())
