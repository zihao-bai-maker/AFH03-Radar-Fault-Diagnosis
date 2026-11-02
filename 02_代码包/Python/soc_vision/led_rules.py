#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""led_rules.py —— **按部件类型的 LED 判定规则引擎**（数据驱动，规则表在 config/led_rules.json）。

为什么必须"按部件套规则"
------------------------
用户逐条确认的规则**不能用一个全局假设**：

| 部件类型 | `kind` | 正常 | 异常 |
|---|---|---|---|
| 电源指示类（3 灯：2 红 + 1 绿） | `power3` | **三颗全亮** | 任意一颗不亮 |
| 状态指示类（2 灯，互斥状态） | `status2` | **恰好一亮一灭** | 两颗都灭（都亮不可能发生） |
| 发射机状态类（5 灯：3 绿 + 2 红） | `tx5` | **3 颗绿全亮**（不需要红灯） | **任一红灯亮 = 故障**；绿缺 = 故障 |
| 单红灯类（红灯亮=正常） | `single_red` | 红灯亮 | 红灯灭 |

★ 反例证明"按部件"是必需的：**同为红灯**，`天线启动` 亮 = **正常**；`发射机状态·故障` 灯亮 = **故障**。

输入/输出
---------
输入：部件 id（或由丝印 OCR 认出的部件名）+ 每颗灯的 `on/off/unknown`
输出：`PartVerdict`：`verdict ∈ {正常, 故障, 未判定}` + `哪颗灯不正常` + `依据` + `置信度`

**未判定绝不当成"灯灭"**：任何 `unknown`（没标定/ROI 越界/信号不足）都会把结论降级为"未判定"并给出原因。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

VERDICT_OK = "正常"
VERDICT_BAD = "故障"
VERDICT_UNK = "未判定"

KIND_ALIAS = {
    "led": "generic", "led_all_on": "power3", "led_mutex_pair": "status2",
    "led_single_on": "single_red", "led_tx5": "tx5",
}

def check_catalog_coverage(rules_path: str = "", markers_path: str = "") -> list:
    """★ 完整性自检：`markers_modules.json` 的每个模块都必须能在 `led_rules.json` 找到规则。

    现场教训：**认出来却判不了 = 规则表缺口**（G5 认到 TEXT_SCREEN，规则表却没有该条目 →
    用户看到"规则表里没有这个部件"）。上线前必须自检，缺一条就报错。
    返回缺失清单（空 = 通过）。
    """
    import json as _json
    import os as _os
    here = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    rp = rules_path or _os.path.join(here, "config", "led_rules.json")
    mp = markers_path or _os.path.join(here, "markers_modules.json")
    try:
        rules = _json.load(open(rp, encoding="utf-8"))
        marks = _json.load(open(mp, encoding="utf-8"))
    except Exception as e:                                            
        return ["读取配置失败: %s" % e]
    have = {p.get("id") for p in rules.get("parts", [])}
    from soc_vision.marker_id import RULE_KEY_TO_PART as _MAP
    missing = []
    for label, m in (marks.get("modules") or {}).items():
        cands = _MAP.get(str(m.get("rule_key", ""))) or []
        if not cands:
            missing.append("%s(rule_key=%s 无映射)" % (label, m.get("rule_key")))
            continue
        if not any(c in have for c in cands):
            missing.append("%s(rule_key=%s → 候选 %s 都不在规则表)" % (label, m.get("rule_key"), cands))
    return missing

def canon_kind(kind: str) -> str:
    k = (kind or "").strip()
    return KIND_ALIAS.get(k, k)

TRISTATE = ("on", "off", "unknown")

@dataclass
class LampSpec:
    name: str
    color: str = "R"                 
    silk: str = ""                   
    expect: str = "any"              
    fault_if_on: bool = False        
    critical: bool = True            

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "LampSpec":
        return LampSpec(name=str(d.get("name", "?")), color=str(d.get("color", "R")).upper()[:1],
                        silk=str(d.get("silk", "")), expect=str(d.get("expect", "any")).lower(),
                        fault_if_on=bool(d.get("fault_if_on", False)),
                        critical=bool(d.get("critical", True)))

@dataclass
class NumericSpec:
    """**数字示数容差类判据**（真值⑨ 配电盘）：如"电池电压 26 V ±10%"、"市电电压 220 V ±10%"。

    与"LED 亮灭类"并列，配置里用 `type: "numeric_range"` 区分；
    示数值来自 7 段数码管读数（`soc_vision.seg7`）或人工标定值。
    """
    name: str
    nominal: float
    tol_pct: float = 10.0
    unit: str = "V"
    decimals: int = 1
    roi: str = ""                       
    type: str = "numeric_range"

    @property
    def lo(self) -> float:
        return self.nominal * (1.0 - self.tol_pct / 100.0)

    @property
    def hi(self) -> float:
        return self.nominal * (1.0 + self.tol_pct / 100.0)

    def range_text(self) -> str:
        return "%.*f~%.*f %s" % (self.decimals, self.lo, self.decimals, self.hi, self.unit)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "NumericSpec":
        return NumericSpec(name=str(d.get("name", "?")), nominal=float(d.get("nominal", 0.0)),
                           tol_pct=float(d.get("tol_pct", 10.0)), unit=str(d.get("unit", "")),
                           decimals=int(d.get("decimals", 1)), roi=str(d.get("roi", "")),
                           type=str(d.get("type", "numeric_range")))

def check_numeric(spec: NumericSpec, value: Optional[float]) -> Tuple[str, str]:
    """返回 (tri, reason)，tri ∈ {'ok','bad','unknown'}。"""
    if value is None:
        return "unknown", "%s：未读到示数（数码管识别失败/未标定）→ 未判定" % spec.name
    if spec.lo <= value <= spec.hi:
        return "ok", "%s %.1f%s 在 %s 内 → 正常" % (spec.name, value, spec.unit, spec.range_text())
    return ("bad", "%s %.1f%s 超出 %s → 故障"
            % (spec.name, value, spec.unit, spec.range_text()))

def evaluate_part(rule: "PartRule", led_verdict: "PartVerdict",
                  numeric: Optional[Dict[str, Optional[float]]] = None) -> "PartVerdict":
    """把 **LED 类**结论与 **数字示数类**判据合成**一句结论**：
    `正常` / `故障：<哪一项不满足，实际值 vs 允许范围>` / `未判定：<原因>`。"""
    numeric = numeric or {}
    bad: List[str] = list(led_verdict.bad_lamps or [])
    reasons: List[str] = []
    if led_verdict.verdict in (VERDICT_BAD, VERDICT_UNK):
        reasons.append(led_verdict.reason)
    any_unknown = (led_verdict.verdict == VERDICT_UNK)
    for spec in (rule.numeric or []):
        tri, why = check_numeric(spec, numeric.get(spec.name))
        if tri == "bad":
            bad.append(spec.name)
            reasons.append(why)
        elif tri == "unknown":
            any_unknown = True
            reasons.append(why)
        else:
            reasons.append(why)
    v = PartVerdict(pid=rule.pid, name=rule.name, kind=rule.kind, lamps=led_verdict.lamps,
                    confidence=led_verdict.confidence)
    if bad:
        v.verdict, v.ok, v.bad_lamps = VERDICT_BAD, False, bad
    elif any_unknown:
        v.verdict = VERDICT_UNK
    else:
        v.verdict, v.ok = VERDICT_OK, True
    v.reason = "；".join(reasons) if reasons else "全部判据满足 → 正常"
    return v

@dataclass
class PartRule:
    pid: str
    name: str
    kind: str                        
    lamps: List[LampSpec] = field(default_factory=list)
    silk: List[str] = field(default_factory=list)
    note: str = ""
    numeric: List["NumericSpec"] = field(default_factory=list)   
    min_lit: int = 0                 
    aliases: List[str] = field(default_factory=list)   

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "PartRule":
        return PartRule(pid=str(d.get("id", "?")), name=str(d.get("name", d.get("id", "?"))),
                        kind=str(d.get("kind", "generic")),
                        lamps=[LampSpec.from_dict(x) for x in (d.get("lamps") or [])],
                        silk=[str(s) for s in (d.get("silk") or [])], note=str(d.get("note", "")),
                        numeric=[NumericSpec.from_dict(x) for x in (d.get("numeric") or [])],
                        min_lit=int(d.get("min_lit") or 0),
                        aliases=[str(a) for a in (d.get("aliases") or [])])

@dataclass
class LampState:
    name: str
    on: Optional[bool] = None        
    color: str = "?"
    delta: float = 0.0               
    thr_on: float = 0.0
    thr_off: float = 0.0
    source: str = "sw"               
    reason: str = ""
    x: int = -1
    y: int = -1
    r: int = 0

    @property
    def tri(self) -> str:
        return "unknown" if self.on is None else ("on" if self.on else "off")

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "on": self.on, "tri": self.tri, "color": self.color,
                "delta": round(float(self.delta), 2), "thr_on": round(float(self.thr_on), 2),
                "thr_off": round(float(self.thr_off), 2), "source": self.source,
                "reason": self.reason, "x": self.x, "y": self.y, "r": self.r}

@dataclass
class PartVerdict:
    pid: str = ""
    name: str = ""
    kind: str = ""
    verdict: str = VERDICT_UNK
    ok: Optional[bool] = None
    bad_lamps: List[str] = field(default_factory=list)
    reason: str = ""
    confidence: float = 0.0
    lamps: List[LampState] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.pid, "name": self.name, "kind": self.kind, "verdict": self.verdict,
                "ok": self.ok, "bad_lamps": list(self.bad_lamps), "reason": self.reason,
                "confidence": round(float(self.confidence), 3),
                "lamps": [x.to_dict() for x in self.lamps]}

    def banner(self) -> str:
        if self.verdict == VERDICT_OK:
            return "✅ 正常" + ("" if not self.name else "  %s" % self.name)
        if self.verdict == VERDICT_BAD:
            who = ("：%s" % "、".join(self.bad_lamps)) if self.bad_lamps else ""
            return "❌ 故障%s" % who
        return "⚠ 未判定" + (("：%s" % self.reason) if self.reason else "")

DEFAULT_RULES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  "config", "led_rules.json")

class RuleBook:
    def __init__(self, parts: Sequence[PartRule]):
        self.parts: List[PartRule] = list(parts)

    @staticmethod
    def load(path: Optional[str] = None) -> "RuleBook":
        p = path or DEFAULT_RULES_PATH
        if not os.path.isfile(p):
            return RuleBook(DEFAULT_PARTS)
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        parts = [PartRule.from_dict(x) for x in (d.get("parts") or [])]
        return RuleBook(parts or DEFAULT_PARTS)

    def get(self, pid_or_name: str) -> Optional[PartRule]:
        s = (pid_or_name or "").strip()
        for p in self.parts:
            if p.pid == s or p.name == s:
                return p

        sl = s.lower()
        for p in self.parts:
            if any(sl == str(a).strip().lower() for a in (p.aliases or [])):
                return p

        for p in self.parts:
            if s and (s in p.name or p.name in s):
                return p
            for si in p.silk:
                if si and (si in s or s in si):
                    return p
        return None

    def match_by_silk(self, text: str) -> Optional[PartRule]:
        """用 OCR 出来的整串丝印文字去认部件（命中丝印词最多的那个）。"""
        t = text or ""
        best, score = None, 0
        for p in self.parts:
            sc = sum(1 for si in p.silk if si and si in t)
            if sc > score:
                best, score = p, sc
        return best if score > 0 else None

def _tri(st: LampState) -> str:
    return st.tri

def evaluate(rule: PartRule, states: Sequence[LampState],
             fpga_lit: Optional[Sequence[bool]] = None) -> PartVerdict:
    """按部件类型判定。`states` 顺序必须与 `rule.lamps` 一致。"""
    v = PartVerdict(pid=rule.pid, name=rule.name, kind=rule.kind, lamps=list(states))

    if fpga_lit:
        for i, st in enumerate(v.lamps):
            if i < len(fpga_lit):
                st.source = "fpga"
                st.on = bool(fpga_lit[i])
    n_lamp = len(rule.lamps)
    if n_lamp == 0:
        v.reason = "该部件未定义灯（规则表缺 lamps）"
        return v
    if len(states) != n_lamp:
        v.reason = "灯数不匹配：规则期望 %d 颗，实际给了 %d 颗" % (n_lamp, len(states))
        return v

    unknown = [st.name for st in v.lamps if _tri(st) == "unknown"]
    n_on = sum(1 for st in v.lamps if _tri(st) == "on")
    v.confidence = n_on / float(n_lamp)

    if canon_kind(rule.kind) == "power3":

        if unknown:
            v.verdict = VERDICT_UNK
            v.reason = "有灯未判定（%s）→ 不给出正常/故障结论" % "、".join(unknown)
            return v
        off = [st.name for st in v.lamps if _tri(st) == "off"]
        if not off:
            v.verdict, v.ok = VERDICT_OK, True
            v.reason = "该部件 %d 颗灯全亮 → 供电正常" % n_lamp
        else:
            v.verdict, v.ok, v.bad_lamps = VERDICT_BAD, False, off
            v.reason = "该部件应有 %d 颗全亮，但 %s 不亮 → 供电差错" % (n_lamp, "、".join(off))
        return v

    if canon_kind(rule.kind) == "status2":

        if unknown:
            v.verdict = VERDICT_UNK
            v.reason = "有灯未判定（%s）→ 不给出结论" % "、".join(unknown)
            return v
        n_on = sum(1 for st in v.lamps if _tri(st) == "on")
        if n_on == 1:
            v.verdict, v.ok = VERDICT_OK, True
            on_name = [st.name for st in v.lamps if _tri(st) == "on"][0]
            v.reason = "互斥状态灯恰好一亮一灭（%s 亮）→ 正常" % on_name
        elif n_on == 0:
            v.verdict, v.ok, v.bad_lamps = VERDICT_BAD, False, [st.name for st in v.lamps]
            v.reason = "互斥状态灯两颗都灭 → 故障（用户规则）"
        else:
            v.verdict, v.ok, v.bad_lamps = VERDICT_BAD, False, [st.name for st in v.lamps]
            v.reason = "互斥状态灯两颗都亮（理论上不该发生）→ 判为异常"
        return v

    if canon_kind(rule.kind) == "tx5":

        if unknown:
            v.verdict = VERDICT_UNK
            v.reason = "有灯未判定（%s）→ 不给出结论" % "、".join(unknown)
            return v
        green_specs = [ls for ls in rule.lamps if ls.color == "G"]
        red_on = [st.name for ls, st in zip(rule.lamps, v.lamps)
                  if ls.color == "R" and _tri(st) == "on"]
        green_off = [st.name for ls, st in zip(rule.lamps, v.lamps)
                     if ls.color == "G" and _tri(st) == "off"]
        if red_on:
            v.verdict, v.ok, v.bad_lamps = VERDICT_BAD, False, red_on
            v.reason = "红色故障灯亮（%s）→ 故障（用户规则：红灯不能亮）" % "、".join(red_on)
        elif green_off:
            v.verdict, v.ok, v.bad_lamps = VERDICT_BAD, False, green_off
            v.reason = "绿色工作灯未全亮（%s 灭）→ 故障" % "、".join(green_off)
        else:
            v.verdict, v.ok = VERDICT_OK, True
            v.reason = "%d 颗绿全亮、红灯全灭 → 正常" % len(green_specs)
        return v

    if canon_kind(rule.kind) == "single_red":
        st = v.lamps[0]
        s = _tri(st)
        if s == "unknown":
            v.verdict = VERDICT_UNK
            v.reason = "该灯未判定（%s）→ 不给出结论" % st.reason
        elif s == "on":
            v.verdict, v.ok = VERDICT_OK, True
            v.reason = "%s 红灯亮 → 正常" % st.name
        else:
            v.verdict, v.ok, v.bad_lamps = VERDICT_BAD, False, [st.name]
            v.reason = "%s 红灯灭 → 故障" % st.name
        return v

    bad: List[str] = []
    unk: List[str] = []
    for ls, st in zip(rule.lamps, v.lamps):
        t = _tri(st)
        if t == "unknown":
            unk.append(st.name)
            continue
        if ls.fault_if_on and t == "on":
            bad.append(st.name)
        elif ls.expect == "on" and t != "on":
            bad.append(st.name)
        elif ls.expect == "off" and t == "on":
            bad.append(st.name)
    if unk:
        v.verdict = VERDICT_UNK
        v.reason = "有灯未判定（%s）" % "、".join(unk)
    elif bad:
        v.verdict, v.ok, v.bad_lamps = VERDICT_BAD, False, bad
        v.reason = "不满足期望的灯：%s" % "、".join(bad)
    else:
        v.verdict, v.ok = VERDICT_OK, True
        v.reason = "各灯状态均符合该部件期望"
    return v

def evaluate_by_litcount(rule: PartRule, n_lit: int, panel_present: bool = True,
                         lit_names: Optional[List[str]] = None,
                         lens_evidence: int = 0) -> PartVerdict:
    """**只用"亮灯数 + 面板在场证据"**按用户规则判定（灯位没法全部定位时的主路径）。

    为什么这样也对：**"亮"是自发光事件，一定被亮点掩膜抓到**（8 张真值实测：真亮的灯 100% 命中、
    0 误检）；而"灭"的灯是暗灯罩、位置难定位。用户规则的语义本身大多只用**亮灯数**：
      * `power3`：全亮才正常（`n_lit == n_lamp`）；少了就是供电差错 —— 不需要知道缺的是哪颗
      * `status2`：恰好一颗亮才正常（`n_lit == 1`）；0 颗 = 故障；2 颗 = 不可能
      * `tx5`：3 颗绿全亮且红灯全灭 → 判"绿亮 3 且红亮 0"
      * `single_red`：红亮 = 正常（`n_lit >= 1`）；0 颗 = 故障
    `panel_present=False`（画面里既没亮点也没暗灯罩）→ 一律 **未判定**，绝不误报"故障"。
    """
    n_lamp = len(rule.lamps)
    need_lit = int(rule.min_lit or n_lamp)      
    v = PartVerdict(pid=rule.pid, name=rule.name, kind=rule.kind)
    v.lamps = [LampState(name=ls.name, color=ls.color, on=None, reason="灯位未逐一标定（按亮灯数判定）")
               for ls in rule.lamps]
    for i, nm in enumerate(lit_names or []):
        if i < len(v.lamps):
            v.lamps[i].on = True
            v.lamps[i].source = "sw"
            v.lamps[i].reason = "亮点掩膜命中（自发光）"
    if not panel_present:
        v.verdict = VERDICT_UNK
        v.reason = "画面里没有检测到任何灯（亮点 0、灯罩 %d）→ 未判定" % lens_evidence
        return v
    n_green_norm = sum(1 for ls in rule.lamps if ls.color == "G")
    v.confidence = min(1.0, n_lit / float(max(1, n_lamp)))
    if canon_kind(rule.kind) == "power3":
        if n_lit >= need_lit:
            v.verdict, v.ok = VERDICT_OK, True
            if need_lit < n_lamp:
                v.reason = ("该部件至少 %d/%d 颗亮（实测 %d 颗，控制灯期望待确认）→ 供电正常"
                            % (need_lit, n_lamp, n_lit))
            else:
                v.reason = "该部件 %d 颗灯全亮 → 供电正常" % n_lamp
        elif n_lit == 0 and lens_evidence == 0:
            v.verdict = VERDICT_UNK
            v.reason = "0 颗亮且没有灯罩证据 → 无法确认面板在画面内 → 未判定"
        else:
            v.verdict, v.ok = VERDICT_BAD, False
            v.reason = ("该部件至少需 %d 颗亮，实测只亮 %d 颗 → 供电差错"
                        "（控制灯期望待确认；用户规则：红电源灯不能缺）" % (need_lit, n_lit))
            v.bad_lamps = [ls.name for ls in rule.lamps[n_lit:]]
        return v
    if canon_kind(rule.kind) == "status2":
        if n_lit == 1:
            v.verdict, v.ok = VERDICT_OK, True
            v.reason = "互斥状态灯恰好一颗亮（实测亮 %d 颗）→ 正常" % n_lit
        elif n_lit == 0:
            v.verdict, v.ok = VERDICT_BAD, False
            v.bad_lamps = [ls.name for ls in rule.lamps]
            v.reason = "互斥状态灯 0 颗亮（两颗都灭）→ 故障（用户规则）"
        else:
            v.verdict, v.ok = VERDICT_BAD, False
            v.reason = "互斥状态灯亮 %d 颗（只允许 1 颗）→ 异常" % n_lit
        return v
    if canon_kind(rule.kind) == "tx5":

        if n_lit >= n_green_norm and n_lit <= n_green_norm:
            v.verdict, v.ok = VERDICT_OK, True
            v.reason = "%d 颗绿全亮、红灯全灭 → 正常" % n_green_norm
        elif n_lit > n_green_norm:
            v.verdict, v.ok = VERDICT_BAD, False
            v.bad_lamps = [ls.name for ls in rule.lamps if ls.color == "R"]
            v.reason = "亮灯数 %d > 绿灯数 %d → 有红灯亮 → 故障（用户规则：红灯不能亮）" % (n_lit, n_green_norm)
        elif n_lit == 0 and lens_evidence == 0:
            v.verdict = VERDICT_UNK
            v.reason = "0 颗亮且无灯罩证据 → 未判定"
        else:
            v.verdict, v.ok = VERDICT_BAD, False
            v.bad_lamps = [ls.name for ls in rule.lamps if ls.color == "G"][n_lit:]
            v.reason = "绿色工作灯只亮 %d/%d 颗 → 故障" % (n_lit, n_green_norm)
        return v
    if canon_kind(rule.kind) == "single_red":
        if n_lit >= 1:
            v.verdict, v.ok = VERDICT_OK, True
            v.reason = "%s 红灯亮 → 正常" % rule.lamps[0].name
        else:
            v.verdict, v.ok = VERDICT_BAD, False
            v.bad_lamps = [rule.lamps[0].name]
            v.reason = "%s 红灯灭 → 故障" % rule.lamps[0].name
        return v

    v.verdict = VERDICT_UNK
    v.reason = "generic 部件需要逐灯灯位，无法只按亮灯数判定 → 未判定"
    return v

DEFAULT_PARTS: List[PartRule] = [
    PartRule("PS_KONG", "电源指示（空调/市电/控制）", "power3",
             [LampSpec("空调电源指示", "R", "空调电源指示", "on"),
              LampSpec("市电电源", "R", "市电电源", "on"),
              LampSpec("控制", "G", "控制", "on")],
             ["空调电源指示", "市电电源", "控制"], min_lit=2),
    PartRule("PS_WENYA", "电源指示（稳压工频/发电机/控制）", "power3",
             [LampSpec("稳压工频电源指示", "R", "稳压工频电源指示", "on"),
              LampSpec("发电机电源", "R", "发电机电源", "on"),
              LampSpec("控制", "G", "控制", "on")],
             ["稳压工频电源指示", "发电机电源", "控制"], min_lit=2),
    PartRule("ANT_DIR", "天线换向控制（位置指示）", "status2",
             [LampSpec("右向", "R", "右向", "any"), LampSpec("左向", "R", "左向", "any")],
             ["位置指示", "右向", "左向"]),
    PartRule("TX_CTRL", "发射机控制（发射机工作 I/II）", "status2",
             [LampSpec("发射机工作 I", "R", "I", "any"), LampSpec("发射机工作 II", "R", "II", "any")],
             ["发射机工作", "两路转换"]),
    PartRule("TX_STATE", "发射机状态（工作/本路/发射通/发射断/故障）", "tx5",
             [LampSpec("工作", "G", "工作", "on"),
              LampSpec("本路", "G", "本路", "on"),
              LampSpec("发射通", "G", "发射通", "on"),
              LampSpec("发射断", "R", "发射断", "off", fault_if_on=True),
              LampSpec("故障", "R", "故障", "off", fault_if_on=True)],
             ["工作", "本路", "发射通", "发射断", "故障"]),
    PartRule("ANT_START", "天线控制（天线启动）", "single_red",
             [LampSpec("天线启动", "R", "天线启动", "on")],
             ["天线控制", "天线启动"]),
    PartRule("PS_GONGPIN", "电源控制（工频电源指示）", "single_red",
             [LampSpec("工频电源", "R", "工频电源", "on")],
             ["电源控制", "工频电源", "电合选择", "电池电合电源", "市电"]),
]

def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="LED 规则引擎（按部件类型判定）")
    ap.add_argument("--rules", default="", help="规则表 JSON 路径")
    ap.add_argument("--list", action="store_true", help="列出规则表")
    ap.add_argument("--part", default="", help="部件 id/名称")
    ap.add_argument("--states", default="", help="各灯状态，逗号分隔：on,off,unknown")
    a = ap.parse_args(argv)
    book = RuleBook.load(a.rules or None)
    if a.list or not a.part:
        print("规则表：%d 个部件" % len(book.parts))
        for p in book.parts:
            print("  %-10s %-8s %d 灯  %s" % (p.pid, p.kind, len(p.lamps),
                                              "/".join("%s(%s,%s)" % (l.name, l.color, l.expect) for l in p.lamps)))
        return 0
    rule = book.get(a.part)
    if rule is None:
        print("规则表里没有部件：%s" % a.part)
        return 2
    toks = [t.strip() for t in a.states.split(",") if t.strip()]
    states = []
    for i, ls in enumerate(rule.lamps):
        t = toks[i] if i < len(toks) else "unknown"
        states.append(LampState(name=ls.name, color=ls.color,
                                on=None if t == "unknown" else (t == "on"),
                                source="cli"))
    v = evaluate(rule, states)
    print(json.dumps(v.to_dict(), ensure_ascii=False, indent=2))
    print("结论: %s" % v.banner())
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
