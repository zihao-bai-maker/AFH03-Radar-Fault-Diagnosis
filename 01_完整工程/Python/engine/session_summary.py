#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""session_summary.py —— **本轮（一次 session）多模块拍照证据 → 故障候选收敛**。

用户要求（2026-10-20 原话）
--------------------------
> 「拍照拍了很多个模块…要有一个**总结按钮**，生成这一轮里所有拍照结果中**错误的一个集合**，
>  导向哪一个错误；如果能**缩小范围确定到最后几个错误**里最好不过。
>  这个程序慢慢做。在保证不输错的情况下完成。」

⇒ 本文件就是那颗【总结】按钮背后的**离线原型**：吃一轮里所有 ``evidence/v1``，
吐「异常清单 + 交集优先的故障候选 Top1~3 + 无法收敛的现象 + 结论」。

铁律（写进算法的硬约束）
------------------------
1. **宁可不判，绝不误判**：候选收敛不了就如实写 ``verdict="undetermined"``，绝不硬凑；
2. **每一步可追溯**：每条异常都有 ``ev_id``（``E01``…），每个候选都有 ``kb_rows``
   （判据库第几行）+ ``support``（支撑它的 ev_id）+ ``score_detail``（置信怎么算的）；
3. **不许编原因**：知识库没有的现象只报现象（``kb_external``），绝不给候选。

六步汇总算法（对应 ``summarize()`` 的实现顺序）
-----------------------------------------------
1. **收集**：接受裸数组或 ``{"evidence": [...]}`` 包装；逐条校验（缺 field/value → ``invalid``，
   缺 part/confidence → 降级 + warning）；按 **fusion.py 同口径**去重
   ``(part, route, modality, field, value)`` 取最高置信（§11）。
2. **分类**：每条证据 → ``abnormal`` / ``normal`` / ``undetermined`` / ``scope`` / ``invalid``。
   语义优先级（先命中先算，全部可复核）：
   ① ``value`` 属未判定枚举 → undetermined；
   ② 判据库 **field 级反向语义**（如 2A 保险丝 ``on`` 才是异常）→ abnormal/normal；
   ③ 采集层自带规则期望（``match``/``expect``，如「3.15A 保险丝 应为灭」）→ normal/abnormal；
   ④ 全局异常/正常枚举 → abnormal/normal；
   ⑤ ``cause_explainer`` 的屏幕选项清单（``no_echo`` / ``no_scan`` / ``garbled`` …）；
   ⑥ 知识库未收录的现象（``yellow_line`` / ``no_guidance_line``）→ undetermined
   （``kb_external=True``，只报现象、绝不给原因）。
   ``modality="part"``（部位识别）归 ``scope``，不当现象参与收敛。
   **问答优先**：同一 ``(part, route, field)`` 上 qa 与 vision 结论相反时**以问答为准**
   （复用 ``screen_qa.py`` 的口径：视觉提示与人工确认不一致 → 以人工确认为准），
   视觉那条降级为 ``superseded`` 并记进 ``conflicts``；qa 自己「跳过」不算冲突。
3. **分组求候选**：按 ``(part, route)`` 分组，每组把**该组全部异常值**一次性喂给
   ``cause_explainer.explain(part, values, route, fields=…, evidence=…)``
   ⇒ 每组得到一份候选（机柜/分机/模块 + 原因 + 置信 + 判据行号）。
4. **交集优先**（核心）：
   * 候选身份 = ``(cabinet, sub_unit, module)``（与 explain() 的分组粒度一致）；
   * ``phenomena_explained`` = 这个候选能解释本轮几个不同现象（现象 = 组 × 值）；
   * ``groups_hit`` = 它能在几个 ``(part, route)`` 组里被解释出来（跨部位印证数）；
   * **能解释全部现象的候选（交集）排在只解释部分现象的候选前面**，同一档再按置信；
     交集为空 ⇒ **不做故障收敛**（``verdict="undetermined"``），只按并集列出候选并注明
     「无法收敛」，绝不挑一个第一名冒充结论。
5. **收敛输出**：Top1~3 + 每个候选的 ``support``（支撑证据 ev_id + 判据行号）
   + ``unexplained``（Top1~3 都解释不了的现象）+ 完整候选清单（不隐藏）。
6. **置信与结论**（公式全部写进 ``score_detail``，可手算复核）::

       conf = base × support_factor × cross_factor × evidence_factor   （上限 0.95）
       base           = 该候选在各组 explain() 里的最高置信
       support_factor = 0.78 + 0.22 × (被解释现象数 / 现象总数)
       cross_factor   = 1 + 0.08 × (groups_hit − 1)      # 跨部位交叉印证加分，上限 1.16
       evidence_factor= 0.85 + 0.15 × 支撑证据的最低置信  # 最弱环节，不让弱照片撑起强结论

   ``verdict`` / ``conclusion`` 矩阵（**conclusion 才是能拿去做决定的那个**）：

   ==============  ==============  ==================================================
   verdict         conclusion      条件
   ==============  ==============  ==================================================
   converged       fault           交集非空 + 交集内 ≤3 个 + 交集内第一名 ≥0.60 且领先 ≥0.10
                                   + 本轮没有解释不了的异常现象
   converged       normal          无异常 + 正常证据 ≥2 条且覆盖 ≥2 种模态（schema §7）
   partial         undetermined    有候选但没收敛（交集候选 >3 / 交集内前两名接近 /
                                   置信 <0.60 / 存在知识库未收录的异常现象）
   undetermined    undetermined    交集为空 / 一个候选都没有 / 证据不足 / 输入损坏
   ==============  ==============  ==================================================

命令行
------
::

    python session_summary.py --evidence flow_evidence_20261018_154422.json
    python session_summary.py --evidence ev.json --out summary.json
    python session_summary.py --evidence ev.json --session-dir sessions/S20261020_211500
    python session_summary.py --evidence ev.json --json      # 完整 JSON（含 score_detail）

依赖：**只用 ``cause_explainer`` + 标准库**（不联网、不装包、不改任何现有文件）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

ENGINE_DIR = Path(__file__).resolve().parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

import cause_explainer as ce  

SCHEMA = "session_summary/1.0"

ENGINE_VERSION = "session_summary/1.0.1"
ISO_TZ = timezone(timedelta(hours=8))

MIN_FAULT_CONF = 0.60        
MIN_MARGIN = 0.10            
MAX_TOP = 3                  
MAX_LIST = 10                
CONF_CAP = 0.95              
WEAK_EV_CONF = 0.50          
MIN_NORMAL_EVIDENCE = 2      
MIN_NORMAL_MODALITIES = 2    

SUPPORT_BASE = 0.78          
SUPPORT_SPAN = 0.22
CROSS_BOOST = 0.08           
CROSS_BOOST_MAX = 1.16
EV_FACTOR_BASE = 0.85        
EV_FACTOR_SPAN = 0.15

MODALITIES = ("vision", "qa", "scope", "audio")

ALLOWED_MODALITIES = MODALITIES + ("part",)

ABNORMAL_VALUES = {
    "off", "no", "weak", "no_sound", "under_voltage", "no_move",
    "yellow_screen", "black_screen", "garbled", "abnormal", "no_noise", "not_done",
    "start_fail", "error", "angle_limit", "led_count_less_than_6_on",
}
NORMAL_VALUES = {
    "on", "normal", "ok", "good", "normal_sound", "waveform_normal",
    "correct", "pass", "yes", "done", "no_fault",
}
UNDETERMINED_VALUES = {"undetermined", "unknown", "uncertain", "skipped", "skip", ""}
COMPLEMENT = {
    "off": "on", "on": "off",
    "no": "normal", "normal": "no",
    "weak": "normal",
    "no_sound": "normal_sound", "normal_sound": "no_sound",
    "under_voltage": "normal", "no_move": "normal",
    "yellow_screen": "normal", "black_screen": "normal",
    "abnormal": "normal", "no_noise": "normal",
    "not_done": "done", "done": "not_done",
    "start_fail": "normal", "error": "normal", "angle_limit": "normal",
    "led_count_less_than_6_on": "normal",
}

VALUE_ALIASES = {
    "不亮": "off", "灭": "off", "灯灭": "off",
    "亮": "on", "灯亮": "on", "有": "on",
    "无": "no", "无波形": "no", "无回波": "no_echo",
    "正常": "normal", "无吸合声": "no_sound", "欠压": "under_voltage",
    "不随动": "no_move", "黄屏": "yellow_screen", "黑屏": "black_screen",
    "判不了": "undetermined", "无法判断": "undetermined", "看不清": "undetermined",
    "跳过": "undetermined", "未验证": "undetermined",
}

EXPECT_ALIASES = {
    "灭": "off", "不亮": "off", "应灭": "off", "应为灭": "off",
    "亮": "on", "应亮": "on", "应为亮": "on", "常亮": "on",
    "正常": "normal", "应正常": "normal", "应为正常": "normal",
}

VALUE_FAMILY = {
    "no": {"no", "no_echo", "no_scan"},
    "abnormal": {"abnormal", "meter_zero", "no_guidance_line", "meter_dark"},
    "no_echo": {"no", "no_echo"},
    "no_scan": {"no", "no_scan"},
    "meter_zero": {"abnormal", "meter_zero"},
}

_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"

def now_iso() -> str:
    return datetime.now(ISO_TZ).isoformat(timespec="seconds")

def _clean(text: Any) -> str:
    """压成单行（判据库 check_item 里有换行，UI 不能直接画）。"""
    s = str(text if text is not None else "").replace("\u3000", " ")
    return re.sub(r"\s+", " ", s).strip()

def _key(text: Any) -> str:
    return re.sub(r"\s+", "", _clean(text))

def _clip(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))

def _canon_value(value: Any) -> str:
    """原始值 → 收敛用的规范值（不改变可判性，只统一写法）。"""
    s = _clean(value)
    if s.lower() in VALUE_ALIASES:
        return VALUE_ALIASES[s.lower()]
    if s in VALUE_ALIASES:
        return VALUE_ALIASES[s]
    return s.lower() if s.isascii() else s

def _canon_expect(expect: Any) -> str:
    """采集层的期望值（「应灭」/「应亮」/「off」）→ 规范值；解析不了返回 ""。"""
    s = _clean(expect)
    if not s:
        return ""
    if s in EXPECT_ALIASES:
        return EXPECT_ALIASES[s]
    if s.lower() in NORMAL_VALUES or s.lower() in ABNORMAL_VALUES:
        return s.lower()
    for k, v in EXPECT_ALIASES.items():
        if k and k in s:
            return v
    return ""

def _same_phenomenon(a: Any, b: Any) -> bool:
    """两个现象值是不是同一件事（容忍 no / no_echo / no_scan 这类族内写法）。"""
    ca, cb = _canon_value(a), _canon_value(b)
    if ca == cb:
        return True
    return cb in VALUE_FAMILY.get(ca, {ca}) or ca in VALUE_FAMILY.get(cb, {cb})

def _pretty_module(name: str) -> str:
    """``Z19-FU1-2A保险丝`` → ``Z19-FU1-2A 保险丝``（与 cause_explainer 显示口径一致）。"""
    return re.sub(r"^([A-Za-z0-9\-\+\.]+)(?=[\u4e00-\u9fff])", r"\1 ", _clean(name)).strip()

def _value_label(value: Any) -> str:
    """值 → 人看的中文短标签（优先屏幕选项清单，其次判据库含义）。"""
    opt = ce.resolve_option(value)
    if opt:
        return _clean(opt.get("label_plain") or opt.get("id"))
    meaning = _clean(ce.ABNORMAL_VALUE_MEANING.get(_canon_value(value), ""))
    return meaning.split(" / ")[0] if meaning else _clean(value)

def _gkey_str(gkey: Sequence[str]) -> str:
    part, route = (list(gkey) + ["", ""])[:2]
    return f"{part}/{route or '-'}"

def _sorted_gkeys(gkeys: Sequence[Tuple[str, str]]) -> List[Tuple[str, str]]:
    return sorted(gkeys, key=lambda k: (k[0], k[1]))

_SEM: Dict[str, Any] = {"loaded": False, "field_abnormal": {}, "pairs": set(),
                        "fields": set(), "values": set(), "source": "", "warnings": []}

def _semantics() -> Dict[str, Any]:
    """只读 ``cause_explainer.load_fault_rows()``，建 field → 异常值 的覆盖表。"""
    if _SEM["loaded"]:
        return _SEM
    _SEM["loaded"] = True
    try:
        rows = ce.load_fault_rows()
    except Exception as exc:                                    
        _SEM["warnings"].append(f"判据库读取失败：{exc}（只能用全局值语义）")
        return _SEM
    if not rows:
        _SEM["warnings"].append("判据库为空/不可用（只能用全局值语义，结论会偏保守）")
        return _SEM
    field_abnormal: Dict[str, set] = {}
    pairs = set()
    for r in rows:
        fld = _clean(r.get("field"))
        val = _canon_value(r.get("abnormal_value"))
        if fld and val:
            field_abnormal.setdefault(fld, set()).add(val)
            pairs.add((fld, val))
    _SEM["field_abnormal"] = field_abnormal
    _SEM["pairs"] = pairs
    _SEM["fields"] = set(field_abnormal)
    _SEM["values"] = {v for vals in field_abnormal.values() for v in vals}
    _SEM["source"] = str(getattr(ce, "FAULT_CSV", ""))
    return _SEM

FIELD_ALIASES: Dict[str, str] = {

    "(led_indicator)_z31_aircon": "(led_indicator)_z31_aircon_power",
    "(led_indicator)_z31_mains": "(led_indicator)_z31_mains_power",
    "(led_indicator)_z31_power_control": "(led_indicator)_z31_control",

    "(led_indicator)_z11_work": "(led_indicator)_route_one_z11_work",
    "(led_indicator)_z11_work_route_one": "(led_indicator)_route_one_z11_work",
    "(led_indicator)_route_two_z11_work": "(led_indicator)_route_one_z11_work",
    "(led_indicator)_z20_transmitter_work": "(led_indicator)_z20_transmitter_work_route_one",
}

_ROUTE_PREFIX_PAIRS = (("route_two", "route_one"), ("route_one", "route_two"))

def _strip_field_suffix(field: str) -> Tuple[str, str]:
    """``..._off`` → (``...``, ``off``)；尾缀 token 必须在判据库 abnormal_value 词表内。

    长 token 优先（``led_count_less_than_6_on`` 先于 ``on``），避免把 ``..._on`` 误切。
    """
    f = _clean(field)
    if not f:
        return "", ""
    for v in sorted((_semantics().get("values") or ()), key=lambda x: (-len(x), x)):
        suf = "_" + v
        if len(f) > len(suf) and f.endswith(suf):
            return f[:-len(suf)], v
    return f, ""

def _normalize_field(field: str) -> Tuple[str, str]:
    """采集层 field → 判据库 field；返回 ``(归一 field, 规则说明)``。

    ``规则说明`` 为空 = 原样/未命中；非空 = ``suffix:off`` / ``alias`` / ``route:...``，
    写进证据 JSON 供追溯（**不猜**：任何一步不精确命中就返回原 field）。
    """
    f = _clean(field)
    if not f:
        return "", ""
    fields = _semantics().get("fields") or set()
    if f in fields:
        return f, ""

    base, token = _strip_field_suffix(f)
    if token:
        if base in fields:
            return base, "suffix:%s" % token
        alias = FIELD_ALIASES.get(base)
        if alias and alias in fields:
            return alias, "suffix:%s+alias" % token

    alias = FIELD_ALIASES.get(f)
    if alias and alias in fields:
        return alias, "alias"

    for a, b in _ROUTE_PREFIX_PAIRS:
        if a in f:
            cand = f.replace(a, b)
            if cand in fields:
                return cand, "route:%s->%s" % (a, b)
            alias = FIELD_ALIASES.get(cand)
            if alias and alias in fields:
                return alias, "route:%s->%s+alias" % (a, b)
    return f, ""

def _implied_value(field_raw: str, canon: str, raw: Mapping[str, Any]) -> Tuple[str, str]:
    """通用 ``abnormal`` + field 尾缀给出具体异常态时，把值细化为尾缀 token。

    仅当：① 原值就是通用 ``abnormal``；② 该条不是采集层规则判定（``rule``/``match`` 会给出
    具体实测值，不能被字段名覆盖）；③ (归一 field, 尾缀 token) 在判据库里真实存在。
    例：``(led_indicator)_z31_aircon_power_off`` + ``abnormal`` → value=``off``（rec#7）。
    """
    if canon != "abnormal":
        return canon, ""
    if raw.get("match") is not None or raw.get("rule"):
        return canon, ""
    _, token = _strip_field_suffix(field_raw)
    if not token:
        return canon, ""
    norm, rule = _normalize_field(field_raw)
    if not norm or not rule.startswith("suffix:"):
        return canon, ""
    if (norm, token) not in (_semantics().get("pairs") or set()):
        return canon, ""
    return token, "suffix-value:%s" % token

def _kb_row_for(field: str, value: str) -> Tuple[int, str]:
    """(field, value) 直接命中的第一条判据行 → (行号, feature_id)；没有则 (0, "")。

    口径：``行号`` = 数据行序号（1 基、不含表头）= CSV rec# - 1；页面显示时再加 1。
    field/value 会先做与 ``_prepare`` 相同的归一（去尾缀/别名/route 镜像），保证
    ``abnormals[].kb_row`` 与 ``pairs``/``explain()`` 用同一口径。
    """
    fld, val = _clean(field), _canon_value(value)
    if not fld or not val:
        return 0, ""
    fld, _rule = _normalize_field(fld)
    for r in ce.load_fault_rows():
        if _clean(r.get("field")) == fld and _canon_value(r.get("abnormal_value")) == val:
            return int(r.get("row") or 0), _clean(r.get("feature_id"))
    return 0, ""

def _rule_expectation(raw: Mapping[str, Any]) -> Tuple[str, str]:
    """采集层自带规则期望 → (category, why)；没有/解析不了返回 ("", "")。

    只对**规则驱动**的观测（带 ``rule`` / ``kind``）生效，避免把任意 ``expect`` 当判据。
    例：``{"value":"off","expect":"应灭","match":true}`` ⇒ 这颗灯灭是**正常态**。
    """
    if not (raw.get("rule") or raw.get("kind")):
        return "", ""
    match = raw.get("match")
    if isinstance(match, bool):
        if match:
            return "normal", "采集层规则判定 match=true（实测与「%s」一致）" % (
                _clean(raw.get("expect")) or "期望态")
        return "abnormal", "采集层规则判定 match=false（实测「%s」≠ 期望「%s」）" % (
            _clean(raw.get("value")), _clean(raw.get("expect")))
    want = _canon_expect(raw.get("expect"))
    if want:
        got = _canon_value(raw.get("value"))
        if want == got:
            return "normal", "实测「%s」符合规则期望「%s」" % (got, want)
        return "abnormal", "实测「%s」不符合规则期望「%s」" % (got, want)
    return "", ""

def _as_evidence_list(payload: Any) -> Tuple[List[Any], Dict[str, Any]]:
    """裸数组 / 带 ``evidence`` 键的包装对象 → (证据数组, 包装对象)。"""
    if payload is None:
        return [], {}
    if isinstance(payload, Mapping):
        for key in ("evidence", "evidences", "items", "evidence_list"):
            val = payload.get(key)
            if isinstance(val, list):
                return list(val), dict(payload)
        if payload.get("field") and payload.get("value"):
            return [dict(payload)], {}
        return [], dict(payload)
    if isinstance(payload, (list, tuple)):
        return list(payload), {}
    if isinstance(payload, (str, bytes)):
        data = json.loads(payload)          
        return _as_evidence_list(data)
    raise TypeError(f"证据必须是数组或带 evidence 键的对象，收到 {type(payload).__name__}")

def _classify(raw: Mapping[str, Any], sem: Mapping[str, Any]) -> Dict[str, Any]:
    """单条证据 → {category, why, semantics}（**不判故障**，只判「这条是正常/异常/未定」）。"""
    value_raw = _clean(raw.get("value"))
    canon = _canon_value(value_raw)
    field = _clean(raw.get("field"))

    if canon in UNDETERMINED_VALUES or value_raw in UNDETERMINED_VALUES:
        return {"category": "undetermined", "subcategory": "skipped", "canon": canon,
                "why": "观测值就是未判定/跳过（%s）：不产生正常/异常结论" % (value_raw or "空"),
                "semantics": "undetermined_value"}

    field_abn = sem["field_abnormal"].get(field)
    if field_abn:
        if canon in field_abn:
            return {"category": "abnormal", "subcategory": "", "canon": canon,
                    "why": "判据库 field 级语义：该 field 的异常值就是「%s」" % canon,
                    "semantics": "kb_field_override"}
        comps = {COMPLEMENT.get(x) for x in field_abn}
        if canon in comps:
            return {"category": "normal", "subcategory": "", "canon": canon,
                    "why": "判据库 field 级语义：该 field 的异常值是「%s」，实测「%s」是正常态"
                           % ("/".join(sorted(field_abn)), canon),
                    "semantics": "kb_field_override"}

    rule_cat, rule_why = _rule_expectation(raw)
    if rule_cat:
        return {"category": rule_cat, "subcategory": "", "canon": canon,
                "why": rule_why, "semantics": "evidence_rule_expect"}

    if canon in ABNORMAL_VALUES:
        return {"category": "abnormal", "subcategory": "", "canon": canon,
                "why": "异常值枚举「%s」" % canon, "semantics": "global_enum"}
    if canon in NORMAL_VALUES:
        return {"category": "normal", "subcategory": "", "canon": canon,
                "why": "正常值枚举「%s」" % canon, "semantics": "global_enum"}

    opt = ce.resolve_option(value_raw)
    if opt is not None:
        oid = _clean(opt.get("id"))
        if oid in getattr(ce, "NORMAL_OPTION_IDS", set()):
            return {"category": "normal", "subcategory": "", "canon": canon,
                    "why": "屏幕选项「%s」是正常态" % oid, "semantics": "screen_option"}
        kb_vals = set((opt.get("kb_match") or {}).get("abnormal_values") or [])
        if kb_vals & ABNORMAL_VALUES:
            return {"category": "abnormal", "subcategory": "", "canon": canon,
                    "why": "屏幕选项「%s」对应判据库异常值 %s"
                           % (oid, "/".join(sorted(kb_vals & ABNORMAL_VALUES))),
                    "semantics": "screen_option"}
        if opt.get("in_kb"):
            return {"category": "abnormal", "subcategory": "", "canon": canon,
                    "why": "屏幕选项「%s」是判据库里记录在案的现象" % oid,
                    "semantics": "screen_option"}
        return {"category": "undetermined", "subcategory": "kb_external", "canon": canon,
                "why": "现象「%s」知识库未收录：只报现象，不给原因（%s）"
                       % (_clean(opt.get("label_plain")) or oid, _clean(opt.get("note"))[:60]),
                "semantics": "screen_option_external", "label": _clean(opt.get("label_plain"))}

    return {"category": "undetermined", "subcategory": "unknown_value", "canon": canon,
            "why": "值「%s」不在异常/正常枚举，也不是屏幕选项清单里的现象" % (value_raw or "空"),
            "semantics": "unknown"}

def _prepare(payload: Any) -> Dict[str, Any]:
    """收集 + 校验 + 去重 + 分类。永不抛异常（坏输入进 ``invalid``）。"""
    sem = _semantics()
    raw_list, wrapper = _as_evidence_list(payload)
    items: List[Dict[str, Any]] = []
    invalid: List[Dict[str, Any]] = []
    warnings: List[str] = []

    for i, raw in enumerate(raw_list, 1):
        if not isinstance(raw, Mapping):
            invalid.append({"idx": i, "why": f"不是 JSON 对象（{type(raw).__name__}）",
                            "raw": _clean(raw)[:80]})
            continue
        field_raw = _clean(raw.get("field"))
        value = _clean(raw.get("value"))
        modality = _clean(raw.get("modality")).lower()
        if not field_raw or not value:
            invalid.append({"idx": i, "why": "field 或 value 为空（无法判读，按契约拒收）",
                            "part": _clean(raw.get("part")), "raw": f"{field_raw}={value}"})
            continue
        if modality and modality not in ALLOWED_MODALITIES:
            invalid.append({"idx": i, "why": f"modality={modality!r} 不在 {ALLOWED_MODALITIES}",
                            "part": _clean(raw.get("part")), "field": field_raw})
            continue
        part = ce.normalize_part(raw.get("part"))
        route = _clean(raw.get("route")).upper()
        if route not in ("I", "II"):
            route = ""
        conf_raw = raw.get("confidence")
        try:
            conf = _clip(float(conf_raw)) if conf_raw not in (None, "") else 0.5
            conf_missing = conf_raw in (None, "")
        except (TypeError, ValueError):
            conf, conf_missing = 0.5, True

        
        field_norm, field_rule = _normalize_field(field_raw)
        canon_raw = _canon_value(value)
        canon_eff, value_rule = _implied_value(field_raw, canon_raw, raw)
        _classify_raw = dict(raw)
        _classify_raw["field"] = field_norm or field_raw
        if value_rule:
            _classify_raw["value"] = canon_eff
        cls = _classify(_classify_raw, sem)
        it = {
            "ev_id": "E%02d" % (len(items) + 1),
            "idx": i,
            "part": part,
            "part_raw": _clean(raw.get("part")),
            "route": route,
            "modality": modality or "vision",
            "field": field_norm or field_raw,
            "field_raw": field_raw,
            "field_norm": field_rule,
            "value": value,
            "value_raw": value,
            "value_norm": value_rule,
            "canon_raw": canon_raw,
            "canon": cls["canon"],
            "confidence": round(conf, 3),
            "category": "scope" if modality == "part" else cls["category"],
            "subcategory": cls["subcategory"],
            "why": cls["why"],
            "semantics": cls["semantics"],
            "evidence": _clean(raw.get("evidence") or raw.get("note") or raw.get("reason")),
            "ts": _clean(raw.get("ts")),
            "check_item": _clean(raw.get("check_item")),
            "step_name": _clean(raw.get("step_name")),
            "step_id": _clean(raw.get("step_id")),
            "flow_no": _clean(raw.get("flow_no")),
            "item_id": _clean(raw.get("item_id")),
            "feature_id": _clean(raw.get("feature_id")),
            "rule": _clean(raw.get("rule")),
            "expect": _clean(raw.get("expect")),
            "match": raw.get("match"),
            "raw": dict(raw),
            "warnings": list(warnings),
        }
        if conf_missing:
            it["warnings"].append("confidence 缺失 → 按 0.5 处理（契约违规）")
        if not part:
            it["warnings"].append("part 为空 → 只能按现象枚举，部位先验不生效（契约违规）")
        if it["category"] == "scope":
            it["why"] = "部位识别证据（modality=part）：只作范围线索，不参与异常收敛"
            it["subcategory"] = ""
        items.append(it)

    best: Dict[Tuple[str, str, str, str, str], Dict[str, Any]] = {}
    for it in items:
        key = (it["part"], it["route"], it["modality"], it["field"], it["canon"])
        cur = best.get(key)
        if cur is None or it["confidence"] > cur["confidence"]:
            if cur is not None:
                it.setdefault("merged_idx", []).extend([cur["idx"]] + cur.get("merged_idx", []))
            best[key] = it
        else:
            cur.setdefault("merged_idx", []).append(it["idx"])
    deduped = [it for it in items if best.get(
        (it["part"], it["route"], it["modality"], it["field"], it["canon"])) is it]
    duplicate_count = len(items) - len(deduped)
    for n, it in enumerate(deduped, 1):
        it["ev_id"] = "E%02d" % n

    for it in deduped:
        if it["category"] == "abnormal" and it["confidence"] < WEAK_EV_CONF:
            it["category"] = "undetermined"
            it["subcategory"] = "weak_evidence"
            it["category_hint"] = "abnormal"
            it["why"] = ("看起来异常（%s），但观测置信 %.2f < %.2f ⇒ 只记录、不参与故障收敛"
                         % (it["canon"], it["confidence"], WEAK_EV_CONF))

    return {"items": deduped, "invalid": invalid, "wrapper": wrapper,
            "duplicates": duplicate_count, "warnings": warnings,
            "raw_total": len(raw_list)}

def _part_display(part: str) -> str:
    """部位显示名；18 部位表里没有的（如 z19 转接分机在 cause_explainer 的兜底表里缺）
    退化为大写代号，绝不写成「该部位（Z19）」这种半截话。"""
    p = _clean(part).lower()
    if not p:
        return "该部位"
    if ce.part_name(p):
        return ce.part_display(p)
    return p.upper()

def _merge_unspecified_routes(items: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """route 未标注（""）且该部位只有一个已知路别 ⇒ 并入该路别。

    真实 flow_evidence 里视觉证据的 route 常是 ""、问答证据是 "I"（见
    ``_shots/flow_evidence_20261018_154422.json``）。不归一会被当成两组现象，
    凭空多一次「交叉印证」，所以这里按「该部位唯一已知路别」对齐（多路别时不猜）。
    """
    routes: Dict[str, set] = {}
    for it in items:
        if it["category"] == "scope":
            continue
        routes.setdefault(it["part"], set()).add(it["route"])
    filled = 0
    for part, rs in routes.items():
        if "" not in rs or len(rs) < 2:
            continue
        known = sorted(r for r in rs if r)
        if len(known) != 1:
            continue
        for it in items:
            if it["part"] == part and it["route"] == "":
                it["route"] = known[0]
                it["route_filled"] = known[0]
                filled += 1
    return items, filled

def _resolve_conflicts(items: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """同 field 上问答与视觉结论相反 ⇒ 以问答为准（视觉标 superseded）。

    复用 ``screen_qa.py`` 的口径：**视觉提示与人工确认不一致时以人工确认为准**；
    问答自己选「跳过/看不清」不算冲突（那一题没有形成结论）。
    """
    by_key: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    for it in items:
        if it["category"] == "scope":
            continue
        by_key.setdefault((it["part"], it["route"], it["field"]), []).append(it)

    conflicts: List[Dict[str, Any]] = []
    for (part, route, field), group in by_key.items():
        qas = [x for x in group if x["modality"] == "qa" and x["subcategory"] != "skipped"]
        visions = [x for x in group if x["modality"] in ("vision", "scope")]
        if not qas or not visions:
            continue
        for qa in qas:
            for vis in visions:
                if qa["category"] == vis["category"]:
                    vis["agrees_with"] = qa["ev_id"]
                    continue
                if qa["category"] == "undetermined" or vis["category"] == "undetermined":
                    continue        
                prev_cat = vis["category"]
                vis["superseded_by"] = qa["ev_id"]
                vis["category"] = "undetermined"
                vis["subcategory"] = "superseded_by_qa"
                vis["why"] = ("与问答结论相反（qa=%s / vision=%s）⇒ 以问答为准，"
                              "视觉这条降级（screen_qa.py 口径）"
                              % (qa["canon"], vis["canon"]))
                vis["superseded_from"] = prev_cat
                conflicts.append({
                    "part": part, "route": route, "field": field,
                    "winner_ev": qa["ev_id"], "winner_modality": "qa", "winner_value": qa["canon"],
                    "loser_ev": vis["ev_id"], "loser_modality": vis["modality"],
                    "loser_value": vis["canon"],
                    "rule": "视觉提示与人工确认不一致 → 以人工确认为准（复用 screen_qa.py）",
                })
    return items, conflicts

def _group_abnormal(items: Sequence[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for it in items:
        if it["category"] != "abnormal":
            continue
        gkey = (it["part"], it["route"])
        g = groups.setdefault(gkey, {"values": [], "fields": [], "items": [], "flow_no": set()})
        if not any(_same_phenomenon(v, it["canon"]) for v in g["values"]):
            g["values"].append(it["canon"])
        if it["field"] and it["field"] not in g["fields"]:
            g["fields"].append(it["field"])
        if it["flow_no"]:
            g["flow_no"].add(it["flow_no"])
        g["items"].append(it)
    for g in groups.values():
        g["values"].sort()
        g["fields"].sort()
        g["flow_no"] = sorted(g["flow_no"])[0] if len(g["flow_no"]) == 1 else ""
    return groups

def _explain_groups(groups: Mapping[Tuple[str, str], Mapping[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """每个 (part, route) 一组，一次性把所有异常现象喂给 explain()（只读调用）。"""
    sem = _semantics()
    pairs = sem["pairs"]
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for gkey in _sorted_gkeys(list(groups)):
        g = groups[gkey]
        part, route = gkey
        ev_payload = []
        for it in g["items"]:
            if (it["field"], it["canon"]) in pairs:
                ev_payload.append({"field": it["field"], "value": it["canon"],
                                   "confidence": it["confidence"]})
        ctx = {"flow_no": g["flow_no"]} if g["flow_no"] else None
        try:
            res = ce.explain(part=part, values=list(g["values"]), route=route,
                             fields=list(g["fields"]), evidence=ev_payload, ctx=ctx)
        except Exception as exc:                                
            res = {"causes": [], "is_fault": None,
                   "uncertain_reason": f"explain() 调用失败：{exc}"}
        out[gkey] = res
    return out

def _candidate_confidence(agg: Mapping[str, Any], n_groups: int, n_phenomena: int) -> Dict[str, Any]:
    """候选汇总置信（公式与 score_detail 一一对应，可手算复核）。"""
    per_group = agg["groups"]
    groups_hit = len(per_group)
    base_group = max(per_group, key=lambda k: per_group[k]["confidence"])
    base = float(per_group[base_group]["confidence"])

    explained = set()
    for gkey, g in per_group.items():
        for ex in g["explains"]:
            explained.add((gkey, _canon_value(ex.get("value"))))
    p_explained = len(explained)
    gcov = groups_hit / max(1, n_groups)
    pcov = min(1.0, p_explained / max(1, n_phenomena))
    support_factor = SUPPORT_BASE + SUPPORT_SPAN * pcov
    cross_factor = min(CROSS_BOOST_MAX, 1.0 + CROSS_BOOST * max(0, groups_hit - 1))
    ev_confs = [float(s.get("confidence") or 0.5) for s in agg.get("support", [])]
    ev_min = min(ev_confs) if ev_confs else 1.0
    ev_factor = EV_FACTOR_BASE + EV_FACTOR_SPAN * ev_min
    conf = _clip(base * support_factor * cross_factor * ev_factor, 0.0, CONF_CAP)
    return {
        "confidence": round(conf, 3),
        "phenomena_explained": p_explained,
        "score_detail": {
            "base": round(base, 3), "base_group": _gkey_str(base_group),
            "groups_hit": groups_hit, "groups_total": n_groups,
            "group_coverage": round(gcov, 3),
            "phenomena_explained": p_explained, "phenomena_total": n_phenomena,
            "phenomenon_coverage": round(pcov, 3),
            "support_factor": round(support_factor, 3),
            "cross_factor": round(cross_factor, 3),
            "evidence_factor": round(ev_factor, 3),
            "min_support_confidence": round(ev_min, 3),
            "formula": "base × support_factor × cross_factor × evidence_factor（上限 0.95）；"
                       "support_factor=0.78+0.22×现象覆盖；"
                       "cross_factor=1+0.08×(命中组数-1) 上限 1.16；"
                       "evidence_factor=0.85+0.15×支撑证据最低置信",
        },
    }

def _collect_candidates(explains: Mapping[Tuple[str, str], Mapping[str, Any]],
                        groups: Mapping[Tuple[str, str], Mapping[str, Any]],
                        items_by_id: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """把所有组的候选按 (cabinet, sub_unit, module) 合并 + 挂支撑证据。"""

    val_ids: Dict[Tuple[str, str], Dict[str, List[str]]] = {}
    for gkey, g in groups.items():
        idx: Dict[str, List[str]] = {}
        for it in g["items"]:
            idx.setdefault(it["canon"], []).append(it["ev_id"])
        val_ids[gkey] = idx

    merged: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for gkey in _sorted_gkeys(list(explains)):
        res = explains[gkey]
        for c in res.get("causes") or []:
            key = (_clean(c.get("cabinet")), _clean(c.get("sub_unit")), _clean(c.get("module")))
            agg = merged.setdefault(key, {
                "key": key, "cabinet": key[0], "cabinet_code": _clean(c.get("cabinet_code")),
                "sub_unit": key[1], "sub_unit_code": _clean(c.get("sub_unit_code")),
                "module": key[2], "feature_ids": set(), "groups": {}, "support": [],
            })
            feat = _clean(c.get("feature_id"))
            if feat:
                agg["feature_ids"].add(feat)
            agg["groups"][gkey] = {
                "confidence": float(c.get("confidence") or 0.0),
                "reason": _clean(c.get("reason")),
                "reason_source": _clean(c.get("reason_source")),
                "in_part_scope": bool(c.get("in_part_scope")),
                "in_symptom_scope": bool(c.get("in_symptom_scope")),
                "route_mismatch": bool(c.get("route_mismatch")),
                "kb_rows": list(c.get("kb_rows") or []),
                "explains": list(c.get("explains") or []),
                "coverage": dict(c.get("coverage") or {}),
                "score_detail": dict(c.get("score_detail") or {}),
                "phenomenon": _clean(c.get("phenomenon")),
                "step_name": _clean(c.get("step_name")),
            }

            for ex in c.get("explains") or []:
                ex_val = _canon_value(ex.get("value"))
                for raw_val, ids in val_ids.get(gkey, {}).items():
                    if not _same_phenomenon(raw_val, ex_val):
                        continue
                    for ev_id in ids:
                        it = items_by_id.get(ev_id) or {}
                        rec = {
                            "ev_id": ev_id, "group": _gkey_str(gkey),
                            "part": it.get("part", ""), "field": it.get("field", ""),
                            "value": raw_val, "confidence": it.get("confidence", 0.0),
                            "strength": ex.get("strength"), "by": ex.get("by"),
                            "kb_row": ex.get("row"), "kb_feature_id": _clean(ex.get("feature_id")),
                            "kb_field": _clean(ex.get("field")),
                            "modality": it.get("modality", ""),
                            "text": _item_text(it),
                        }
                        if all(s["ev_id"] != ev_id or s["group"] != rec["group"]
                               for s in agg["support"]):
                            agg["support"].append(rec)

    out = []
    for key, agg in merged.items():
        agg["feature_ids"] = sorted(agg["feature_ids"])
        best_g = max(agg["groups"], key=lambda k: agg["groups"][k]["confidence"])
        best = agg["groups"][best_g]
        agg["reason"] = best["reason"]
        agg["reason_source"] = best["reason_source"]
        agg["best_group"] = best_g
        agg["reasons"] = [
            {"group": _gkey_str(gk), "reason": g["reason"], "confidence": round(g["confidence"], 3),
             "kb_rows": g["kb_rows"]}
            for gk, g in sorted(agg["groups"].items())
        ]
        agg["kb_rows"] = sorted({r for g in agg["groups"].values() for r in g["kb_rows"]})
        agg["support_phenomena"] = len({(s["group"], s["value"]) for s in agg["support"]})
        agg["min_support_confidence"] = min(
            [float(s.get("confidence") or 0.0) for s in agg["support"]] or [1.0])
        agg["in_part_scope"] = any(g["in_part_scope"] for g in agg["groups"].values())
        agg["route_mismatch"] = all(g["route_mismatch"] for g in agg["groups"].values())
        agg["feature_id"] = agg["feature_ids"][0] if agg["feature_ids"] else ""
        out.append(agg)
    return out

def _item_text(it: Mapping[str, Any]) -> str:
    """一条证据的人话短句（UI 的「异常项」用）。"""
    part_disp = _part_display(it.get("part"))

    def _join(txt: str) -> str:

        sep = " " if re.search(r"[A-Za-z0-9]$", part_disp) else ""
        return f"{part_disp}{sep}{txt}"

    txt = _clean(it.get("check_item") or it.get("step_name"))
    if txt:
        txt = re.sub(r"^[（(][^）)]{1,8}[）)]\s*[-—]?\s*", "", txt)
        if re.search(r"[Zz]\s*\d", txt):
            return txt
        return _join(txt)
    return _join(_value_label(it.get("value")))

def _blank_result() -> Dict[str, Any]:
    return {
        "schema": SCHEMA,
        "engine": ENGINE_VERSION,
        "generated_at": now_iso(),
        "session": {},
        "counts": {},
        "abnormals": [],
        "normals": [],
        "undetermined": [],
        "scope": [],
        "invalid": [],
        "duplicates": [],
        "conflicts": [],
        "top_faults": [],
        "all_candidates": [],
        "candidates_total": 0,
        "unexplained": [],
        "field_match": {},
        "converge": {},
        "verdict": "undetermined",
        "conclusion": "undetermined",
        "verdict_reason": "",
        "notes": [],
        "warnings": [],
        "page": {},
        "text": "",
    }

def _degraded(reason: str, session: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """输入不可用时的**优雅降级**结果（结构仍然完整，UI 不用分支）。"""
    res = _blank_result()
    res["session"] = dict(session or {})
    res["counts"] = {
        "modules": 0, "module_status": {"normal": 0, "abnormal": 0, "undetermined": 0},
        "items": {"total": 0, "abnormal": 0, "normal": 0, "undetermined": 0,
                  "scope": 0, "invalid": 0},
        "parts": {"total": 0, "normal": 0, "abnormal": 0, "undetermined": 0},
        "phenomena": {"total": 0, "groups": 0, "explained": 0, "unexplained": 0},
        "duplicates": 0, "superseded": 0,
    }
    res["verdict"] = "undetermined"
    res["conclusion"] = "undetermined"
    res["verdict_reason"] = reason
    res["notes"].append(reason)
    res["text"] = "⚠️ 本轮无法总结：%s\n【返回】【再拍一轮】" % reason
    res["page"] = {"state": "summary", "lines": res["text"].split("\n"),
                   "buttons": _page_buttons()}
    return res

def _page_buttons() -> List[Dict[str, str]]:
    return [{"id": "back", "label": "返回", "action": "summary:back"},
            {"id": "again", "label": "再拍一轮", "action": "summary:again"}]

def summarize(evidence: Any, *, session: Optional[Mapping[str, Any]] = None,
              generated_at: Optional[str] = None) -> Dict[str, Any]:
    """**本轮总结**：一轮的所有 evidence → 异常清单 + 收敛后的故障候选 + 未解释现象。

    参数
    ----
    evidence : 裸数组 / ``{"evidence": [...]}`` 包装 / JSON 文本 / None
    session  : 可选的会话元信息（``id`` / ``started_at`` / ``saved_at`` / ``session_dir``）
    generated_at : 固定生成时间（测试确定性用）

    返回
    ----
    dict（``schema=session_summary/1.0``）：``session`` / ``counts`` / ``abnormals`` /
    ``top_faults`` / ``unexplained`` / ``verdict`` / ``conclusion`` / ``text`` 等。
    """
    try:
        prep = _prepare(evidence)
    except Exception as exc:                                    
        return _degraded("证据无法解析：%s" % exc, session)

    items = prep["items"]
    items, route_filled = _merge_unspecified_routes(items)
    if route_filled:
        prep["warnings"].append("%d 条证据 route 未标注，已并入该部位唯一已知路别（不猜多路别）"
                                % route_filled)
    items, conflicts = _resolve_conflicts(items)
    items_by_id = {it["ev_id"]: it for it in items}
    wrapper = prep["wrapper"]

    sess: Dict[str, Any] = {
        "id": _clean((session or {}).get("id")) or "",
        "started_at": _clean((session or {}).get("started_at"))
                      or _clean(wrapper.get("started_at")),
        "saved_at": _clean((session or {}).get("saved_at"))
                    or _clean(wrapper.get("saved_at")),
        "session_dir": _clean((session or {}).get("session_dir")) or "",
        "source_file": _clean((session or {}).get("source_file")),
        "schema": _clean(wrapper.get("schema")) or "evidence/v1",
        "producer": _clean(wrapper.get("producer")),
        "steps_total": wrapper.get("steps_total"),
        "current_step": wrapper.get("current_step"),
        "evidence_total": prep["raw_total"],
        "evidence_used": len(items),
        "duplicates": prep["duplicates"],
        "invalid": len(prep["invalid"]),
    }

    units: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for it in items:
        if it["category"] == "scope":
            continue
        unit = it["step_id"] or it["check_item"] or it["flow_no"] or it["field"]
        units.setdefault((it["part"], _clean(unit) or it["field"]), []).append(it)

    def _status(group: Sequence[Mapping[str, Any]]) -> str:
        if any(x["category"] == "abnormal" for x in group):
            return "abnormal"
        if any(x["category"] == "normal" for x in group):
            return "normal"
        return "undetermined"

    module_status = {"normal": 0, "abnormal": 0, "undetermined": 0}
    for _, g in units.items():
        module_status[_status(g)] += 1

    parts: Dict[str, List[Dict[str, Any]]] = {}
    for it in items:
        if it["category"] == "scope":
            continue
        parts.setdefault(it["part"], []).append(it)
    part_status = {"normal": 0, "abnormal": 0, "undetermined": 0}
    for _, g in parts.items():
        part_status[_status(g)] += 1

    abnormals = [it for it in items if it["category"] == "abnormal"]
    normals = [it for it in items if it["category"] == "normal"]
    undet = [it for it in items if it["category"] == "undetermined"]
    scopes = [it for it in items if it["category"] == "scope"]

    groups = _group_abnormal(items)
    explains = _explain_groups(groups)
    n_phenomena = sum(len(g["values"]) for g in groups.values())

    cands = _collect_candidates(explains, groups, items_by_id)
    n_groups = len(groups)
    for c in cands:
        agg = _candidate_confidence(c, n_groups, n_phenomena)
        c["confidence"] = agg["confidence"]
        c["score_detail"] = agg["score_detail"]
        c["phenomena_explained"] = agg["phenomena_explained"]

    cands.sort(key=lambda c: (-c["phenomena_explained"], -c["confidence"],
                              c["kb_rows"][:1] or [0]))
    for c in cands:
        c["groups_hit"] = len(c["groups"])
        c["covers_all"] = bool(n_phenomena) and c["phenomena_explained"] >= n_phenomena
    covering = [c for c in cands if c["covers_all"]]

    top = cands[:MAX_TOP]
    for i, c in enumerate(cands, 1):
        c["rank"] = i

    explained_ids = {s["ev_id"] for c in top for s in c["support"]}
    unexplained: List[Dict[str, Any]] = []
    for it in abnormals:
        if it["ev_id"] in explained_ids:
            continue
        own = [c for c in cands if any(s["ev_id"] == it["ev_id"] for s in c["support"])]
        unexplained.append({
            "ev_id": it["ev_id"], "part": it["part"], "part_display": _part_display(it["part"]),
            "field": it["field"], "value": it["canon"], "confidence": it["confidence"],
            "text": _item_text(it),
            "why": ("候选存在但没有进入 Top%d（%s）" % (MAX_TOP, "、".join(
                _pretty_module(c["module"]) for c in own[:3])) if own
                else "所有候选都解释不了这个现象"),
            "any_candidate": bool(own),
            "candidates": [_pretty_module(c["module"]) for c in own[:5]],
        })
    for it in undet:
        if it.get("subcategory") != "kb_external":
            continue
        unexplained.append({
            "ev_id": it["ev_id"], "part": it["part"], "part_display": _part_display(it["part"]),
            "field": it["field"], "value": it["canon"], "confidence": it["confidence"],
            "text": _item_text(it),
            "why": "知识库未收录该现象 ⇒ 只报现象，不给原因（不硬凑）",
            "any_candidate": False, "candidates": [],
        })

    converge: Dict[str, Any] = {
        "groups": n_groups,
        "group_keys": [_gkey_str(k) for k in _sorted_gkeys(list(groups))],
        "groups_hit_top": top[0]["groups_hit"] if top else 0,
        "phenomena_total": n_phenomena,
        "phenomena_explained_top": top[0]["phenomena_explained"] if top else 0,
        "intersection_size": len(covering),
        "intersection": [{"module": _pretty_module(c["module"]),
                          "cabinet": c["cabinet_code"], "sub_unit": c["sub_unit_code"],
                          "confidence": c["confidence"]} for c in covering[:MAX_LIST]],
        "intersection_empty": bool(n_phenomena) and not covering,
        "top_confidence": top[0]["confidence"] if top else 0.0,
        "margin_covering": 0.0,
        "single_candidate_explains_all": bool(covering),
        "all_phenomena_explained": False,
        "complete": False,
    }
    if covering:
        first_c = covering[0]["confidence"]
        second_c = covering[1]["confidence"] if len(covering) > 1 else 0.0
        converge["margin_covering"] = round(first_c - second_c, 3)
    converge["all_phenomena_explained"] = not unexplained

    conclusion = "undetermined"
    verdict = "undetermined"
    reason = ""

    if not items:
        reason = "本轮没有任何可用证据（没有拍照/问答记录）⇒ 不能总结（宁可不判）"
    elif not abnormals and not normals:
        reason = ("本轮 %d 条证据全部是未判定/范围线索 ⇒ 无法给出结论：%s"
                  % (len(items), "；".join(sorted({u["why"] for u in undet}))[:160]))
    elif not abnormals:
        modalities = sorted({it["modality"] for it in normals})
        if len(normals) >= MIN_NORMAL_EVIDENCE and len(modalities) >= MIN_NORMAL_MODALITIES:
            verdict, conclusion = "converged", "normal"
            reason = ("本轮 %d 项正常观测（模态：%s）覆盖 ≥%d 条 / ≥%d 种 ⇒ 未发现异常"
                      % (len(normals), "、".join(modalities),
                         MIN_NORMAL_EVIDENCE, MIN_NORMAL_MODALITIES))
        else:
            reason = ("只有 %d 条正常证据、%d 种模态：不足以支持「正常」结论"
                      "（schema_evidence.md §7 要求 ≥%d 条且 ≥%d 种模态）⇒ 未判定"
                      % (len(normals), len(modalities),
                         MIN_NORMAL_EVIDENCE, MIN_NORMAL_MODALITIES))
    elif not cands:
        reason = ("%d 个异常现象，但判据库没有任何一行能对应 ⇒ 给不出候选故障（不编原因）"
                  % len(abnormals))
    elif converge["intersection_empty"]:
        reason = ("%d 个现象（%d 组）没有公共候选（交集为空）⇒ 不做故障收敛，"
                  "只按并集列出候选（不硬凑）" % (n_phenomena, n_groups))
    elif top[0]["confidence"] < MIN_FAULT_CONF:
        verdict = "partial"
        reason = ("最高候选置信 %.2f < %.2f ⇒ 证据太弱，只列候选、不下结论"
                  % (top[0]["confidence"], MIN_FAULT_CONF))
    elif len(covering) > MAX_TOP:
        verdict = "partial"
        reason = ("交集内还有 %d 个候选能解释全部现象（超过 %d 个）⇒ 需要再拍/再问才能缩小"
                  % (len(covering), MAX_TOP))
    elif converge["margin_covering"] < MIN_MARGIN:
        verdict = "partial"
        reason = ("交集内前两名置信接近（%.2f / %.2f，差 %.2f < %.2f）⇒ 分不清哪一个"
                  % (covering[0]["confidence"], covering[1]["confidence"],
                     converge["margin_covering"], MIN_MARGIN))
    elif unexplained:
        verdict = "partial"
        reason = ("已收敛到 %d 个候选，但还有 %d 个异常现象没被解释 ⇒ 结论不完整"
                  % (len(covering), len(unexplained)))
    else:
        verdict, conclusion = "converged", "fault"
        if len(covering) == 1:
            reason = ("%d 个现象收敛到唯一能同时解释全部现象的候选：%s（%.2f）"
                      % (n_phenomena, _pretty_module(covering[0]["module"]),
                         covering[0]["confidence"]))
        else:
            reason = ("%d 个现象收敛到 %d 个候选，第一名 %.2f（领先第二名 %.2f ≥ %.2f）"
                      % (n_phenomena, len(covering), top[0]["confidence"],
                         converge["margin_covering"], MIN_MARGIN))

    res = _blank_result()
    res["generated_at"] = generated_at or now_iso()
    res["session"] = sess
    abnormal_ids = {it["ev_id"] for it in abnormals}
    res["counts"] = {
        "modules": len(units),
        "module_status": module_status,
        "items": {"total": len(items), "abnormal": len(abnormals), "normal": len(normals),
                  "undetermined": len(undet), "scope": len(scopes),
                  "invalid": len(prep["invalid"])},
        "parts": {"total": len(parts), **part_status},
        "phenomena": {"total": n_phenomena, "groups": n_groups,
                      "explained_evidences": len(explained_ids & abnormal_ids),
                      "unexplained": len(unexplained)},
        "duplicates": prep["duplicates"],
        "superseded": sum(1 for it in items if it.get("superseded_by")),
    }
    _abn_public = [_public(it, extra=_abnormal_extra(it)) for it in abnormals]
    res["abnormals"] = _abn_public

    

    res["field_match"] = _field_match_stats(_abn_public)
    res["normals"] = [_public(it) for it in normals]
    res["undetermined"] = [_public(it) for it in undet]
    res["scope"] = [_public(it) for it in scopes]
    res["invalid"] = list(prep["invalid"])
    res["duplicates"] = [{"ev_id": it["ev_id"], "merged_idx": it.get("merged_idx", []),
                          "part": it["part"], "field": it["field"], "value": it["canon"]}
                         for it in items if it.get("merged_idx")]
    res["conflicts"] = conflicts
    res["top_faults"] = [_public_candidate(c) for c in top]
    res["all_candidates"] = [_public_candidate(c, short=True) for c in cands[:MAX_LIST]]
    res["candidates_total"] = len(cands)
    res["unexplained"] = unexplained
    converge["complete"] = (verdict == "converged" and conclusion in ("fault", "normal"))
    res["converge"] = converge
    res["verdict"] = verdict
    res["conclusion"] = conclusion
    res["verdict_reason"] = reason
    res["warnings"] = list(prep["warnings"])
    res["notes"] = _notes(items, abnormals, undet, top, covering, groups, conflicts, unexplained,
                          res["counts"], cands, field_match=res["field_match"])
    res["text"] = format_text(res)
    res["page"] = {"state": "summary", "title": "本轮总结",
                   "lines": res["text"].split("\n"), "buttons": _page_buttons()}
    return res

def _abnormal_extra(it: Mapping[str, Any]) -> Dict[str, Any]:
    row, feat = _kb_row_for(it.get("field", ""), it.get("canon", ""))
    return {"kb_row": row, "feature_id": feat}

def _field_match_stats(abnormals: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """本轮异常现象的 field 命中统计（B 页文本门的唯一依据）。

    ``kb_row > 0`` = (归一 field, 值) 在 268 条判据库里真实存在；否则是
    「同值匹配/库中无此项」，B 页**只报数量，不点名具体候选**。
    """
    unmatched = []
    for a in abnormals or []:
        try:
            row = int(a.get("kb_row") or 0)
        except (TypeError, ValueError):
            row = 0
        if row <= 0:
            unmatched.append(a)
    total = len(list(abnormals or []))
    return {
        "abnormal_total": total,
        "matched": total - len(unmatched),
        "unmatched": len(unmatched),
        "all_matched": bool(total) and not unmatched,
        "unmatched_ev_ids": [str(a.get("ev_id") or "") for a in unmatched],
        "unmatched_fields": [str(a.get("field") or "") for a in unmatched],
    }

def _public(it: Mapping[str, Any], extra: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """对外的证据条目（不含 raw，避免 JSON 膨胀）。

    ``field`` 是**归一到判据库口径后**的 field（用于 pairs/explain/展示门）；
    ``field_raw`` 保留采集层原值，``field_norm`` 记录归一规则（空=未改/未命中），可追溯。
    """
    rec = {
        "ev_id": it["ev_id"], "part": it["part"], "part_display":
            _part_display(it["part"]),
        "route": it["route"], "modality": it["modality"], "field": it["field"],
        "field_raw": it.get("field_raw", it["field"]),
        "field_norm": it.get("field_norm", ""),
        "value": it["value"], "value_raw": it.get("value_raw", it["value"]),
        "value_norm": it.get("value_norm", ""),
        "canon": it["canon"], "canon_raw": it.get("canon_raw", it["canon"]),
        "confidence": it["confidence"],
        "category": it["category"], "subcategory": it["subcategory"], "why": it["why"],
        "semantics": it["semantics"], "evidence": it["evidence"], "ts": it["ts"],
        "check_item": it["check_item"], "step_id": it["step_id"], "flow_no": it["flow_no"],
        "text": _item_text(it),
        "superseded_by": it.get("superseded_by", ""),
        "agrees_with": it.get("agrees_with", ""),
        "warnings": list(it.get("warnings") or []),
    }
    if extra:
        rec.update(dict(extra))
    return rec

def _public_candidate(c: Mapping[str, Any], short: bool = False) -> Dict[str, Any]:
    rec = {
        "rank": c.get("rank", 0),
        "cabinet": c["cabinet"], "cabinet_code": c["cabinet_code"],
        "sub_unit": c["sub_unit"], "sub_unit_code": c["sub_unit_code"],
        "module": c["module"], "module_display": _pretty_module(c["module"]),
        "reason": c["reason"], "reason_source": c["reason_source"],
        "feature_id": c["feature_id"], "feature_ids": c["feature_ids"],
        "confidence": c["confidence"],
        "groups_hit": c["groups_hit"], "groups_total": c["score_detail"].get("groups_total", 0),
        "phenomena_explained": c["phenomena_explained"],
        "phenomena_total": c["score_detail"].get("phenomena_total", 0),
        "covers_all": c["covers_all"],
        "kb_rows": c["kb_rows"],
        "in_part_scope": c["in_part_scope"], "route_mismatch": c["route_mismatch"],
        "reasons": c["reasons"],
        "score_detail": c["score_detail"],
    }
    if not short:
        rec["support"] = c["support"]
        rec["support_count"] = len(c["support"])
        rec["support_phenomena"] = c.get("support_phenomena", len(c["support"]))
        rec["support_ids"] = sorted({s["ev_id"] for s in c["support"]})
    return rec

def _notes(items: Sequence[Mapping[str, Any]], abnormals: Sequence[Mapping[str, Any]],
           undet: Sequence[Mapping[str, Any]], top: Sequence[Mapping[str, Any]],
           covering: Sequence[Mapping[str, Any]],
           groups: Mapping[Tuple[str, str], Any],
           conflicts: Sequence[Mapping[str, Any]],
           unexplained: Sequence[Mapping[str, Any]],
           counts: Mapping[str, Any],
           cands: Sequence[Mapping[str, Any]] = (),
           field_match: Optional[Mapping[str, Any]] = None) -> List[str]:
    notes: List[str] = []

    try:
        _n_unm = int((field_match or {}).get("unmatched") or 0)
    except (TypeError, ValueError):
        _n_unm = 0
    n_phen = counts.get("phenomena", {}).get("total", 0)
    if n_phen <= 1 and abnormals:
        notes.append("本轮只有 %d 个现象：没有交叉印证，候选只能按单现象可能性排序" % n_phen)
    elif len(groups) <= 1 and abnormals:
        notes.append("本轮 %d 个现象都来自同一部位（%s）：交叉印证只是组内多现象，"
                     "不是跨部位印证" % (n_phen, _gkey_str(list(groups)[0])))
    if conflicts:
        notes.append("%d 个 field 上问答与视觉结论相反，已按「问答优先」处理（视觉那条降级）"
                     % len(conflicts))
    weak = [u for u in undet if u.get("subcategory") == "weak_evidence"]
    if weak:
        notes.append("%d 条观测置信 <%.2f（弱证据），只记录、未参与收敛"
                     % (len(weak), WEAK_EV_CONF))
    external = [u for u in undet if u.get("subcategory") == "kb_external"]
    if external:
        notes.append("%d 个现象知识库未收录（%s）：只报现象，不给原因"
                     % (len(external), "、".join(_value_label(u["value"]) for u in external[:3])))
    if counts["duplicates"]:
        notes.append("%d 条重复证据已合并（同 part/route/modality/field/value 取最高置信）"
                     % counts["duplicates"])
    if top and len(covering) > 1:
        if _n_unm:
            notes.append("交集内还有 %d 个候选分不开（field 未命中，不列具体故障名）"
                         % len(covering))
        else:
            notes.append("交集内还有 %d 个候选分不开：%s"
                         % (len(covering),
                            "、".join(_pretty_module(c["module"]) for c in covering[:3])))
    if top and any(c["route_mismatch"] for c in top):
        notes.append("候选命中判据库只有 I 路记录的行：route=II 时已降权，需人工确认知识库缺口")
    if covering and cands:
        best_conf = max(cands, key=lambda c: c["confidence"])
        if best_conf["confidence"] > top[0]["confidence"]:
            if _n_unm:
                notes.append("有候选置信更高（%.2f）但只解释 %d/%d 个现象 ⇒ 按「覆盖优先」"
                             "排在后面（field 未命中，不列具体候选名）"
                             % (best_conf["confidence"],
                                best_conf["phenomena_explained"], n_phen))
            else:
                notes.append("有候选置信更高（%s %.2f）但只解释 %d/%d 个现象 ⇒ 按「覆盖优先」排在后面"
                             % (_pretty_module(best_conf["module"]), best_conf["confidence"],
                                best_conf["phenomena_explained"], n_phen))
    elif cands and top:
        best_conf = max(cands, key=lambda c: c["confidence"])
        if best_conf["confidence"] > top[0]["confidence"]:
            if _n_unm:
                notes.append("置信最高的候选（%.2f）只能解释 %d/%d 个现象 ⇒ 按「覆盖优先」"
                             "排在候选清单第 %d 位（field 未命中，不列具体候选名）"
                             % (best_conf["confidence"], best_conf["phenomena_explained"],
                                n_phen, best_conf["rank"]))
            else:
                notes.append("置信最高的候选是 %s（%.2f），但它只能解释 %d/%d 个现象 ⇒ 按「覆盖优先」"
                             "排在候选清单第 %d 位（不是结论）"
                             % (_pretty_module(best_conf["module"]), best_conf["confidence"],
                                best_conf["phenomena_explained"], n_phen, best_conf["rank"]))
    missing = [c for c in (covering or list(top)[:1]) if not c["in_part_scope"]]
    if missing:
        if _n_unm:
            notes.append("存在跨部位候选（field 未命中，不列具体故障名，按知识库归属之外处理）")
        else:
            notes.append("主因不在拍照部位自身：%s（跨部位候选，按知识库归属列出）"
                         % "、".join("%s/%s %s" % (c["cabinet_code"], c["sub_unit_code"],
                                                   _pretty_module(c["module"])) for c in missing[:2]))
    if unexplained and any(u.get("any_candidate") for u in unexplained):
        notes.append("有现象只能用「未进 Top%d」的候选解释，结论可能不完整" % MAX_TOP)
    return notes

def _candidate_name_set(res: Mapping[str, Any]) -> set:
    """本轮所有候选的显示名（只用于「field 未命中时把文本里的具体名抹掉」）。"""
    names = set()
    for c in list(res.get("top_faults") or []) + list(res.get("all_candidates") or []):
        for k in ("module_display", "module"):
            v = _clean(c.get(k))
            if v:
                names.add(v)
    return names

def _hide_candidate_names(text: Any, res: Mapping[str, Any]) -> str:
    """把文本里出现的具体候选名替换成占位（B 页 field 未命中门的兜底）。"""
    s = _clean(text)
    for nm in sorted(_candidate_name_set(res), key=len, reverse=True):
        if nm and nm in s:
            s = s.replace(nm, "（候选名已隐藏）")
    return s

def format_text(res: Mapping[str, Any]) -> str:
    """UI/CLI 共用的人话格式（与 README §3 的页面设计一一对应）。

    ★ 2026-10-27 收尾（B 页反幻觉门）：只要本轮有异常现象的 field 未在判据库命中，
    **不把具体候选名写成「最可能的故障」**——只报同值候选数量；
    ``top_faults``/``all_candidates`` 数据仍保留（A 页自己做 field 级门控）。
    """
    counts = res.get("counts") or {}
    ms = counts.get("module_status") or {}
    items = counts.get("items") or {}
    lines: List[str] = []
    lines.append("本轮共拍 %d 个模块（%d 正常 / %d 异常 / %d 未判定）"
                 % (counts.get("modules", 0), ms.get("normal", 0),
                    ms.get("abnormal", 0), ms.get("undetermined", 0)))
    if items.get("undetermined"):
        lines.append("· 另有 %d 项观测未判定（已如实记录，未参与结论）" % items["undetermined"])

    abnormals = res.get("abnormals") or []
    if abnormals:
        texts = [_clean(a.get("text")) for a in abnormals[:4]]
        more = "" if len(abnormals) <= 4 else " …等 %d 项" % len(abnormals)
        lines.append("❌ 异常项：" + " / ".join(t for t in texts if t) + more)

    try:
        _n_unm = int((res.get("field_match") or {}).get("unmatched") or 0)
    except (TypeError, ValueError):
        _n_unm = 0
    top = res.get("top_faults") or []
    total_phen = (res.get("converge") or {}).get("phenomena_total", 0)
    if top:
        if _n_unm:
            try:
                _n_cands = int(res.get("candidates_total") or 0)
            except (TypeError, ValueError):
                _n_cands = 0
            if _n_cands <= 0:
                _n_cands = len(top)
            lines.append("🎯 同值候选 %d 个（field 未命中，不作故障范围/不作结论）" % _n_cands)
            lines.append("   （以上只是候选：field 未命中 ⇒ 不列具体故障名，不作结论）")
        else:
            lines.append("🎯 最可能的故障（按可能性）：")
            for c in top:
                num = _CIRCLED[c.get("rank", 1) - 1] if 1 <= c.get("rank", 1) <= len(_CIRCLED) \
                    else "(%d)" % c.get("rank", 1)
                reason = (" —— " + c["reason"]) if c.get("reason") else ""
                alt = ""
                if total_phen and c.get("phenomena_explained", 0) < total_phen:
                    alt = "（只解释 %d/%d 个现象）" % (c["phenomena_explained"], total_phen)
                lines.append("   %s %s%s（%.2f）｜支撑 %d 个现象｜%s/%s%s"
                             % (num, c["module_display"], reason, c["confidence"],
                                c.get("support_phenomena") or c["groups_hit"],
                                c["cabinet_code"], c["sub_unit_code"], alt))
            if res.get("verdict") == "partial":
                lines.append("   （以上只是候选：%s）" % res.get("verdict_reason", ""))
    elif _n_unm:
        lines.append("🎯 无可信候选（%d 个异常现象 field 未命中，不作故障范围/不作结论）"
                     % _n_unm)
    elif res.get("conclusion") == "normal":
        lines.append("✅ 本轮未发现异常（%d 项正常观测）" % items.get("normal", 0))

    if res.get("verdict") == "undetermined":
        _why = _hide_candidate_names(res.get("verdict_reason", "无法判定"), res) if _n_unm \
            else res.get("verdict_reason", "无法判定")
        lines.append("⚠️ %s" % _why)

    unexplained = res.get("unexplained") or []
    if unexplained:
        bits = []
        for u in unexplained[:3]:
            _w = _clean(u.get("why"))
            if _n_unm and "候选" in _w:
                _w = "field 未命中/候选未确认 ⇒ 不列具体故障名（不作结论）"
            elif _n_unm:
                _w = _hide_candidate_names(_w, res)
            bits.append("%s（%s）" % (_clean(u.get("text")), _w))
        lines.append("⚠️ 无法收敛的现象：" + "；".join(bits) +
                     ("" if len(unexplained) <= 3 else " …等 %d 项" % len(unexplained)))

    for n in (res.get("notes") or [])[:3]:
        lines.append("· " + (_hide_candidate_names(n, res) if _n_unm else _clean(n)))
    lines.append("【返回】【再拍一轮】")
    return "\n".join(lines)

def summarize_file(path: str | Path, *, out_path: Optional[str | Path] = None,
                   session: Optional[Mapping[str, Any]] = None,
                   generated_at: Optional[str] = None) -> Dict[str, Any]:
    """读 evidence 文件 → summarize()。**坏 JSON 不抛异常**，返回降级结果并留 error。"""
    p = Path(path)
    sess = dict(session or {})
    sess.setdefault("source_file", str(p.resolve()))
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _degraded("证据文件不存在：%s" % p, sess)
    except UnicodeDecodeError:
        try:
            payload = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception as exc:                                
            return _degraded("证据文件编码/JSON 损坏（%s）：%s" % (p, exc), sess)
    except Exception as exc:                                    
        return _degraded("证据文件 JSON 损坏（%s）：%s" % (p, exc), sess)
    res = summarize(payload, session=sess, generated_at=generated_at)
    if out_path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        res["written_to"] = str(out)
    return res

def _ts_id() -> str:
    return "S" + datetime.now(ISO_TZ).strftime("%Y%m%d_%H%M%S")

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="本轮总结：多模块拍照证据 → 故障候选收敛（离线原型）")
    ap.add_argument("--evidence", required=True, help="证据 JSON（裸数组或 {evidence:[...]}）")
    ap.add_argument("--out", default="", help="summary.json 输出路径（默认与证据同目录）")
    ap.add_argument("--session-dir", default="",
                    help="会话目录（板端约定 sessions/<id>/）；给了就写 <dir>/summary.json")
    ap.add_argument("--session-id", default="", help="会话 id（默认 S<时间戳>）")
    ap.add_argument("--json", action="store_true", help="打印完整 JSON（含 score_detail）")
    ap.add_argument("--quiet", action="store_true", help="只写文件，不打印正文")
    args = ap.parse_args(argv)

    src = Path(args.evidence)
    sid = args.session_id or _ts_id()
    sess = {"id": sid, "source_file": str(src.resolve())}
    if args.session_dir:
        sess["session_dir"] = str(Path(args.session_dir).resolve())
        out_path = args.out or str(Path(args.session_dir) / "summary.json")
    else:
        out_path = args.out or str(src.with_name("summary.json"))

    res = summarize_file(src, out_path=out_path, session=sess)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    elif not args.quiet:
        print(res.get("text", ""))
    print("\n[summary] verdict=%s conclusion=%s → %s"
          % (res.get("verdict"), res.get("conclusion"), res.get("written_to") or "(未写文件)"))
    return 0 if res.get("verdict") != "undetermined" or res.get("session", {}).get("evidence_used") else 2

def _force_utf8_stdout() -> None:
    """Windows 控制台默认 GBK，直接 print「❌」会崩；能改就改成 UTF-8，改不了也不致命。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")     
        except Exception:                                              
            pass

if __name__ == "__main__":
    _force_utf8_stdout()
    raise SystemExit(main())
