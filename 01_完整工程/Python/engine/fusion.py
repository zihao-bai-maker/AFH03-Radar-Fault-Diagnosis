#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多模态证据融合层（fusion layer）。

职责边界
--------
* 本模块 **只做“同一部位的多模态证据 → 部位级状态”**：
  ``abnormal`` / ``normal`` / ``undetermined``，并保留每条证据的模态来源。
* **不做** 故障定位。故障分级（机柜→分机→模块 + feature_id）在
  ``fault_grader.py``，二者通过 ``FusionResult`` 对接。

融合规则（一句话）
------------------
同一 ``(part, route)`` 下：异常证据按模态权重做 noisy-OR；任一高置信异常
（≥0.85）直接置该部位为异常候选；≥2 种模态一致则提置信；同一 field 出现
矛盾结论（异常 vs 正常，或两种异常值）则标 ``conflict`` 并降置信；正常结论
要求 ≥2 条正常证据且覆盖 ≥2 种模态；证据不足一律 ``undetermined``。

设计原则：宁可不判，绝不误判。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

SCHEMA_VERSION = "evidence/v1"
ENGINE_VERSION = "fusion/1.0.0"

ENGINE_DIR = Path(__file__).resolve().parent
CRITERIA_DIR = ENGINE_DIR.parent
DEFAULT_FAULT_CSV = CRITERIA_DIR / "判据库_故障.csv"

MODALITIES: Tuple[str, ...] = ("vision", "qa", "scope", "audio")
ROUTES: Tuple[str, ...] = ("I", "II", "")

ABNORMAL_VALUES: Set[str] = {
    "off", "no", "weak", "no_sound", "under_voltage", "no_move",
    "yellow_screen", "black_screen", "garbled", "abnormal", "no_noise", "not_done",
    "start_fail", "error", "angle_limit", "led_count_less_than_6_on",
}
NORMAL_VALUES: Set[str] = {
    "on", "normal", "ok", "good", "normal_sound", "waveform_normal",
    "correct", "pass", "yes", "done", "no_fault",
}
UNDETERMINED_VALUES: Set[str] = {"undetermined", "unknown", "uncertain", "skipped", ""}

COMPLEMENT: Dict[str, str] = {
    "off": "on", "on": "off",
    "no": "normal", "normal": "no",
    "weak": "normal",
    "no_sound": "normal_sound", "normal_sound": "no_sound",
    "under_voltage": "normal",
    "no_move": "normal",
    "yellow_screen": "normal", "black_screen": "normal",
    "abnormal": "normal",
    "no_noise": "normal",
    "not_done": "done", "done": "not_done",
    "start_fail": "normal", "error": "normal", "angle_limit": "normal",
    "led_count_less_than_6_on": "normal",
}

VALUE_ALIASES: Dict[str, str] = {
    "不亮": "off", "灭": "off", "无": "no", "无波形": "no", "无回波": "no",
    "亮": "on", "有": "on", "正常": "normal", "无吸合声": "no_sound",
    "欠压": "under_voltage", "不随动": "no_move", "黄屏": "yellow_screen",
    "黑屏": "black_screen", "判不了": "undetermined", "无法判断": "undetermined",
}

MODALITY_WEIGHTS: Dict[str, float] = {
    "vision": 1.00,
    "scope": 1.00,
    "qa": 0.92,
    "audio": 0.88,
}

HIGH_CONF = 0.85          
WEAK_CONF = 0.60          
MIN_ABNORMAL_SCORE = 0.50  
MIN_NORMAL_EVIDENCE = 2    
MIN_NORMAL_MODALITIES = 2  
CONFLICT_PENALTY = 0.15
AGREEMENT_BOOST = 0.04     

WARN_LIMIT = 60

class EvidenceError(ValueError):
    """单条证据不符合 evidence/v1 契约。"""

def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")

def _clip(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))

def _compact_value(v: Any, depth: int = 0) -> Any:
    """压缩 extras，防止视觉 metrics/大数组把证据 JSON 撑爆（日志节制）。"""
    if v is None or isinstance(v, (int, float, bool)):
        return v
    if isinstance(v, str):
        return v if len(v) <= 200 else v[:200] + "…"
    if depth >= 1:
        return f"<{type(v).__name__}>"
    if isinstance(v, (list, tuple)):
        out = [_compact_value(x, depth + 1) for x in list(v)[:8]]
        if len(v) > 8:
            out.append("…")
        return out
    if isinstance(v, dict):
        return {str(k): _compact_value(x, depth + 1) for k, x in list(v.items())[:8]}
    return f"<{type(v).__name__}>"

def normalize_text(text: Any) -> str:
    """NFKC + 小写 + 去空白/常见分隔符，用于现象匹配。"""
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = s.lower()
    s = re.sub(r"[\s\u3000]+", "", s)
    s = s.replace("->", "").replace("→", "")
    return s

_ALNUM_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_STOP_TOKENS = {"的", "了", "是", "为", "与", "和", "及"}

def tokenize_text(text: Any) -> Set[str]:
    """轻量中英混合 token：英文/型号串 + 中文 bigram。

    中文 bigram 足以让“无10M ↔ 10M相参基准波形无”“黑屏 ↔ 整屏黑”这类
    长短句互相命中，同时由 IDF 压制“指示灯/不亮”等高频词。
    """
    raw = unicodedata.normalize("NFKC", str(text or "")).lower()

    
    toks: Set[str] = set(_ALNUM_RE.findall(raw))
    t = re.sub(r"[\s\u3000]+", "", raw)
    for run in _CJK_RE.findall(t):
        if len(run) == 1:
            toks.add(run)
            continue
        for i in range(len(run) - 1):
            toks.add(run[i:i + 2])
        if len(run) <= 6:
            toks.add(run)

        toks.update(run)
    return {x for x in toks if x not in _STOP_TOKENS}

def normalize_part(part: Any) -> str:
    """Z11（收发分机） / Z11-1 / z11 → z11。"""
    s = str(part or "").strip().lower()
    if not s:
        raise EvidenceError("part 为空")
    m = re.match(r"^(?:z|机柜z?)\s*(\d+)", s)
    if m:
        return f"z{int(m.group(1))}"

    s = re.sub(r"[\s（）()]+", "", s)
    if not s:
        raise EvidenceError("part 归一后为空")
    return s

def normalize_route(route: Any) -> str:
    if route is None:
        return ""
    s = str(route).strip().upper()
    if s in ("", "-", "NONE", "NULL", "无"):
        return ""
    if s in ("1", "I", "Ⅰ", "一路", "I路"):
        return "I"
    if s in ("2", "II", "Ⅱ", "二路", "II路"):
        return "II"
    return s

def normalize_value(value: Any) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    low = s.lower()
    if low in VALUE_ALIASES:
        return VALUE_ALIASES[low]
    if s in VALUE_ALIASES:
        return VALUE_ALIASES[s]
    return low

def _infer_part(raw: Mapping[str, Any]) -> str:
    """part 缺失时的保守兜底：先看 check_item/evidence/field 里的 zNN。

    这是契约违规的降级路径（会打 warning），不是正常用法。
    """
    for key in ("check_item", "evidence", "reason", "display", "field"):
        text = str(raw.get(key, "") or "")
        m = re.search(r"[Zz]\s*(\d{1,2})", text)
        if m:
            return f"z{int(m.group(1))}"
    return "unknown"

@dataclass
class ValueSemantics:
    """把 (field, value) 映射到 abnormal/normal/undetermined。

    判据库是“反向语义”的唯一权威：例如
    ``(led_indicator)(operator_display)_z15_display_2A_fuse`` 的异常值是 ``on``。
    """

    field_abnormal: Dict[str, Set[str]] = dc_field(default_factory=dict)
    source: str = "default"
    warnings: List[str] = dc_field(default_factory=list)

    @classmethod
    def from_criteria(cls, csv_path: Optional[Path] = None) -> "ValueSemantics":
        path = Path(csv_path) if csv_path else DEFAULT_FAULT_CSV
        sem = cls()
        if not path.exists():
            sem.warnings.append(f"判据库未找到（{path}），仅使用默认值语义；2A保险丝 on/off 可能判反")
            return sem
        try:
            import csv as _csv
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                for row in _csv.DictReader(f):
                    fld = str(row.get("field", "") or "").strip()
                    val = normalize_value(row.get("abnormal_value", ""))
                    if fld and val:
                        sem.field_abnormal.setdefault(fld, set()).add(val)
            sem.source = str(path)
        except Exception as exc:  
            sem.warnings.append(f"读取判据库失败：{exc}；回退默认值语义")
        return sem

    def category(self, field: str, value: str) -> str:
        v = normalize_value(value)
        if v in UNDETERMINED_VALUES:
            return "undetermined"
        fld_abn = self.field_abnormal.get(field)
        if fld_abn:
            if v in fld_abn:
                return "abnormal"
            complements = {COMPLEMENT.get(x) for x in fld_abn}
            if v in complements:
                return "normal"
        if v in ABNORMAL_VALUES:
            return "abnormal"
        if v in NORMAL_VALUES:
            return "normal"
        return "undetermined"

@dataclass
class Evidence:
    part: str
    modality: str
    field: str
    value: str
    confidence: float
    evidence: str = ""
    ts: str = ""
    route: str = ""
    source: str = ""
    category: str = "undetermined"
    warnings: List[str] = dc_field(default_factory=list)
    ts_filled: bool = False
    extras: Dict[str, Any] = dc_field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], semantics: ValueSemantics,
                     allow_fill: bool = True) -> "Evidence":
        if not isinstance(raw, Mapping):
            raise EvidenceError(f"证据必须是 JSON 对象，收到 {type(raw).__name__}")
        warns: List[str] = []
        try:
            part = normalize_part(raw.get("part"))
        except EvidenceError:
            if not allow_fill:
                raise
            part = _infer_part(raw)
            warns.append(f"part 缺失/非法，已从证据文本推断为 {part}（契约违规，建议采集端补 part）")
        modality = str(raw.get("modality", "") or "").strip().lower()
        if modality not in MODALITIES:
            raise EvidenceError(f"未知 modality: {modality!r}（允许 {MODALITIES}）")
        field = str(raw.get("field", "") or "").strip()
        if not field:
            raise EvidenceError("field 为空")
        if "\n" in field or "\r" in field:
            raise EvidenceError(f"field 含换行：{field!r}")
        value = normalize_value(raw.get("value"))
        if not value:
            raise EvidenceError(f"value 为空（field={field}）")

        if "confidence" not in raw or str(raw.get("confidence", "")).strip() == "":
            raise EvidenceError(f"confidence 缺失（field={field}）")
        try:
            conf = float(raw.get("confidence"))
        except (TypeError, ValueError) as exc:
            raise EvidenceError(f"confidence 非数值：{raw.get('confidence')!r}") from exc

        if conf < 0 or conf > 1:
            warns.append(f"confidence={conf} 越界，已裁剪到 [0,1]")
            conf = _clip(conf)

        text = str(raw.get("evidence") or raw.get("reason") or raw.get("note")
                   or raw.get("description") or raw.get("evidence_text") or "").strip()
        if not text:
            if not allow_fill:
                raise EvidenceError(f"evidence 缺失（field={field}）")
            text = f"{field}={value}"
            warns.append("evidence 缺失，已用 field=value 兜底")

        ts = str(raw.get("ts") or raw.get("timestamp") or "").strip()
        ts_filled = False
        if not ts:
            if not allow_fill:
                raise EvidenceError(f"ts 缺失（field={field}）")
            ts = now_iso()
            ts_filled = True
            warns.append("ts 缺失，已由融合层补记（非采集时刻）")

        route = normalize_route(raw.get("route"))
        source = str(raw.get("source") or raw.get("module") or raw.get("producer")
                     or raw.get("item_id") or "").strip()

        category = semantics.category(field, value)
        if category == "undetermined" and value not in UNDETERMINED_VALUES:
            warns.append(f"value={value!r} 未在判据库/默认词表中，按 undetermined 处理")

        extras = {k: v for k, v in raw.items()
                  if k not in {"part", "route", "modality", "field", "value", "confidence",
                               "evidence", "reason", "note", "description", "evidence_text",
                               "ts", "timestamp", "source", "module", "producer"}}
        return cls(part=part, modality=modality, field=field, value=value,
                   confidence=round(conf, 4), evidence=text[:300], ts=ts, route=route,
                   source=source, category=category, warnings=warns,
                   ts_filled=ts_filled, extras=extras)

    def to_dict(self, include_extras: bool = True) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "part": self.part,
            "route": self.route,
            "modality": self.modality,
            "field": self.field,
            "value": self.value,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "ts": self.ts,
            "category": self.category,
        }
        if self.source:
            d["source"] = self.source
        if self.ts_filled:
            d["ts_filled"] = True
        if self.warnings:
            d["warnings"] = list(self.warnings)
        if include_extras and self.extras:
            d["extras"] = {k: _compact_value(v) for k, v in self.extras.items()}
        return d

@dataclass
class FusedPart:
    part: str
    route: str
    status: str                    
    confidence: float
    abnormal_score: float
    normal_score: float
    conflict: bool
    conflict_fields: List[str]
    value_conflicts: Dict[str, List[str]]
    high_conf_abnormal: bool
    modalities: Dict[str, List[Dict[str, Any]]]
    abnormal_evidence: List[Dict[str, Any]]
    normal_evidence: List[Dict[str, Any]]
    undetermined_evidence: List[Dict[str, Any]]
    reasons: List[str]
    evidence_trace: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "part": self.part,
            "route": self.route,
            "status": self.status,
            "confidence": round(self.confidence, 3),
            "abnormal_score": round(self.abnormal_score, 3),
            "normal_score": round(self.normal_score, 3),
            "conflict": self.conflict,
            "conflict_fields": self.conflict_fields,
            "value_conflicts": self.value_conflicts,
            "high_conf_abnormal": self.high_conf_abnormal,
            "agreement_modalities": sorted(self.modalities.keys()),
            "modalities": self.modalities,
            "abnormal_evidence": self.abnormal_evidence,
            "normal_evidence": self.normal_evidence,
            "undetermined_evidence": self.undetermined_evidence,
            "evidence_trace": self.evidence_trace,
            "reasons": self.reasons,
        }

@dataclass
class FusionResult:
    parts: List[FusedPart]
    evidence: List[Evidence]
    warnings: List[str]
    duplicates: int = 0
    generated_at: str = dc_field(default_factory=now_iso)

    def part(self, part: str, route: Optional[str] = None) -> Optional[FusedPart]:
        p = normalize_part(part)
        r = normalize_route(route) if route is not None else None
        for fp in self.parts:
            if fp.part == p and (r is None or fp.route == r):
                return fp
        return None

    def abnormal_parts(self) -> List[FusedPart]:
        return [p for p in self.parts if p.status == "abnormal"]

    def normal_parts(self) -> List[FusedPart]:
        return [p for p in self.parts if p.status == "normal"]

    def undetermined_parts(self) -> List[FusedPart]:
        return [p for p in self.parts if p.status == "undetermined"]

    def to_dict(self) -> Dict[str, Any]:
        modality_index: Dict[str, List[Dict[str, Any]]] = {m: [] for m in MODALITIES}
        for e in self.evidence:
            modality_index.setdefault(e.modality, []).append(e.to_dict(include_extras=False))
        return {
            "schema": SCHEMA_VERSION,
            "engine_version": ENGINE_VERSION,
            "generated_at": self.generated_at,
            "summary": {
                "evidence_count": len(self.evidence),
                "part_count": len(self.parts),
                "abnormal_parts": len(self.abnormal_parts()),
                "normal_parts": len(self.normal_parts()),
                "undetermined_parts": len(self.undetermined_parts()),
                "conflict_parts": sum(1 for p in self.parts if p.conflict),
                "duplicates": self.duplicates,
            },
            "parts": [p.to_dict() for p in self.parts],
            "modality_index": {k: v for k, v in modality_index.items() if v},
            "evidence": [e.to_dict() for e in self.evidence],
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FusionResult":
        """从序列化结果恢复（供 fault_grader 接收外部 fusion JSON）。"""
        mode = str(data.get("schema", ""))
        if mode and mode != SCHEMA_VERSION:
            raise ValueError(f"非 fusion 结果：schema={mode!r}")
        evs: List[Evidence] = []
        for d in data.get("evidence", []) or []:
            e = Evidence(
                part=normalize_part(d.get("part")), modality=str(d.get("modality", "")),
                field=str(d.get("field", "")), value=normalize_value(d.get("value")),
                confidence=float(d.get("confidence", 0.0)),
                evidence=str(d.get("evidence", "")), ts=str(d.get("ts", "")),
                route=normalize_route(d.get("route")), source=str(d.get("source", "")),
                category=str(d.get("category", "undetermined")),
            )
            evs.append(e)
        parts: List[FusedPart] = []
        for p in data.get("parts", []) or []:
            parts.append(FusedPart(
                part=str(p.get("part", "")), route=normalize_route(p.get("route")),
                status=str(p.get("status", "undetermined")),
                confidence=float(p.get("confidence", 0.0)),
                abnormal_score=float(p.get("abnormal_score", 0.0)),
                normal_score=float(p.get("normal_score", 0.0)),
                conflict=bool(p.get("conflict", False)),
                conflict_fields=list(p.get("conflict_fields", []) or []),
                value_conflicts=dict(p.get("value_conflicts", {}) or {}),
                high_conf_abnormal=bool(p.get("high_conf_abnormal", False)),
                modalities=dict(p.get("modalities", {}) or {}),
                abnormal_evidence=list(p.get("abnormal_evidence", []) or []),
                normal_evidence=list(p.get("normal_evidence", []) or []),
                undetermined_evidence=list(p.get("undetermined_evidence", []) or []),
                reasons=list(p.get("reasons", []) or []),
                evidence_trace=list(p.get("evidence_trace", []) or []),
            ))
        return cls(parts=parts, evidence=evs, warnings=list(data.get("warnings", []) or []),
                   duplicates=int((data.get("summary", {}) or {}).get("duplicates", 0)),
                   generated_at=str(data.get("generated_at", now_iso())))

class FusionEngine:
    """同一部位多模态证据融合。

    Parameters
    ----------
    semantics:
        值语义表；默认自动读取 ``判据库_故障.csv`` 的 field→abnormal_value。
    high_conf / weak_conf / min_abnormal_score:
        判定阈值，见模块 docstring。
    min_normal_evidence / min_normal_modalities:
        正常结论门槛（正常也必须多模态，防止“只拍了一张灯全亮”就报正常）。
    """

    def __init__(
        self,
        semantics: Optional[ValueSemantics] = None,
        high_conf: float = HIGH_CONF,
        weak_conf: float = WEAK_CONF,
        min_abnormal_score: float = MIN_ABNORMAL_SCORE,
        min_normal_evidence: int = MIN_NORMAL_EVIDENCE,
        min_normal_modalities: int = MIN_NORMAL_MODALITIES,
        allow_fill: bool = True,
    ) -> None:
        self.semantics = semantics or ValueSemantics.from_criteria()
        self.high_conf = float(high_conf)
        self.weak_conf = float(weak_conf)
        self.min_abnormal_score = float(min_abnormal_score)
        self.min_normal_evidence = int(min_normal_evidence)
        self.min_normal_modalities = int(min_normal_modalities)
        self.allow_fill = bool(allow_fill)

    @staticmethod
    def _unwrap(payload: Any) -> List[Any]:
        if isinstance(payload, FusionResult):
            return [e for e in payload.evidence]
        if isinstance(payload, Mapping):

            
            for key in ("evidence", "items", "records"):
                val = payload.get(key)
                if isinstance(val, (list, tuple)):
                    payload = val
                    break
            else:
                payload = [payload]
        if isinstance(payload, (str, bytes)) or not isinstance(payload, Iterable):
            raise EvidenceError("证据必须是数组或带 evidence 键的对象")
        return list(payload)

    def parse(self, payload: Any) -> Tuple[List[Evidence], List[str]]:
        raw_items = self._unwrap(payload)
        evs: List[Evidence] = []
        warnings: List[str] = []
        for idx, item in enumerate(raw_items):
            try:
                ev = (item if isinstance(item, Evidence)
                      else Evidence.from_mapping(item, self.semantics, allow_fill=self.allow_fill))
            except EvidenceError as exc:
                warnings.append(f"第{idx + 1}条证据被拒绝：{exc}")
                continue
            evs.append(ev)
            for w in ev.warnings:
                warnings.append(f"{ev.part}/{ev.route or '-'}/{ev.field}: {w}")
        return evs, warnings

    @staticmethod
    def dedupe(evs: Sequence[Evidence]) -> Tuple[List[Evidence], int]:
        """同模态同 field 同值重复上报 → 取最高置信，不同模态保留。"""
        best: Dict[Tuple[str, str, str, str, str], Evidence] = {}
        dups = 0
        for ev in evs:
            key = (ev.part, ev.route, ev.modality, ev.field, ev.value)
            old = best.get(key)
            if old is None:
                best[key] = ev
            else:
                dups += 1
                if ev.confidence > old.confidence:
                    merged = list(dict.fromkeys(old.warnings + ev.warnings))
                    ev.warnings = merged
                    best[key] = ev
        return list(best.values()), dups

    def fuse(self, payload: Any) -> FusionResult:
        evs, warnings = self.parse(payload)
        evs, dups = self.dedupe(evs)
        groups: Dict[Tuple[str, str], List[Evidence]] = {}
        for ev in evs:
            groups.setdefault((ev.part, ev.route), []).append(ev)
        parts = [self._fuse_group(part, route, items)
                 for (part, route), items in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1]))]
        if not parts:
            warnings.append("没有可融合的有效证据")
        return FusionResult(parts=parts, evidence=evs, warnings=warnings[:WARN_LIMIT], duplicates=dups)

    def _fuse_group(self, part: str, route: str, evs: Sequence[Evidence]) -> FusedPart:
        abn = [e for e in evs if e.category == "abnormal"]
        nor = [e for e in evs if e.category == "normal"]
        unk = [e for e in evs if e.category == "undetermined"]

        by_field: Dict[str, List[Evidence]] = {}
        for e in evs:
            by_field.setdefault(e.field, []).append(e)
        conflict_fields: List[str] = []
        value_conflicts: Dict[str, List[str]] = {}
        for fld, items in by_field.items():
            cats = {e.category for e in items if e.category != "undetermined"}
            vals = sorted({e.value for e in items if e.category == "abnormal"})
            if "abnormal" in cats and "normal" in cats:
                strong = [e for e in items if e.confidence >= 0.5]
                if len({e.category for e in strong}) >= 2:
                    conflict_fields.append(fld)
            if len(vals) >= 2:
                value_conflicts[fld] = vals
                if fld not in conflict_fields:
                    conflict_fields.append(fld)
        conflict = bool(conflict_fields)

        abnormal_score = 0.0
        for e in abn:
            w = MODALITY_WEIGHTS.get(e.modality, 0.9)
            abnormal_score = 1.0 - (1.0 - abnormal_score) * (1.0 - _clip(e.confidence) * w)
        abn_modalities = sorted({e.modality for e in abn})
        if len(abn_modalities) >= 2:
            abnormal_score = min(0.99, abnormal_score + AGREEMENT_BOOST * (len(abn_modalities) - 1))
        if conflict_fields:
            abnormal_score = max(0.0, abnormal_score - CONFLICT_PENALTY * len(conflict_fields))

        normal_score = 0.0
        for e in nor:
            w = MODALITY_WEIGHTS.get(e.modality, 0.9)
            normal_score = 1.0 - (1.0 - normal_score) * (1.0 - _clip(e.confidence) * w)
        nor_modalities = sorted({e.modality for e in nor})

        high_conf_abn = [e for e in abn if e.confidence >= self.high_conf]
        high_conf_abnormal = bool(high_conf_abn)

        status = "undetermined"
        confidence = 0.0
        reasons: List[str] = []

        if abn:
            if high_conf_abnormal and not (conflict and not any(e.confidence >= 0.9 for e in high_conf_abn)):
                status = "abnormal"
                confidence = max(abnormal_score, min(0.98, max(e.confidence for e in high_conf_abn) - 0.05))
            elif abnormal_score >= self.min_abnormal_score:
                status = "abnormal"
                confidence = abnormal_score
                if len(abn_modalities) == 1 and len(abn) == 1:
                    confidence = min(confidence, 0.82)  
            elif conflict:
                status = "undetermined"
                confidence = min(0.5, abnormal_score)
            else:
                status = "undetermined"
                confidence = abnormal_score

            if high_conf_abnormal:
                names = "、".join(f"{e.modality}:{e.field}={e.value}" for e in high_conf_abn[:3])
                reasons.append(f"存在高置信异常（≥{self.high_conf}）：{names}")
            if len(abn_modalities) >= 2:
                reasons.append(f"{'+'.join(abn_modalities)} 共{len(abn)}条异常证据一致，异常分{abnormal_score:.2f}")
            else:
                reasons.append(f"{abn_modalities[0] if abn_modalities else '未知'} 单模态{len(abn)}条异常证据，异常分{abnormal_score:.2f}")
            if conflict:
                reasons.append(f"检测到同 field 结论冲突：{', '.join(conflict_fields)}；已降置信")
            if status == "undetermined":
                if conflict:
                    reasons.append("冲突无法消解，按铁律不判故障")
                elif self.weak_conf > 0 and max((e.confidence for e in abn), default=0) < self.weak_conf:
                    reasons.append(f"全部异常证据置信<{self.weak_conf}，属弱证据，不判")
                else:
                    reasons.append(f"异常分{abnormal_score:.2f}<阈值{self.min_abnormal_score}")
        elif nor:
            if (len(nor) >= self.min_normal_evidence
                    and len(nor_modalities) >= self.min_normal_modalities
                    and normal_score >= self.min_abnormal_score):
                status = "normal"
                confidence = min(0.96, normal_score + 0.02 * (len(nor_modalities) - 1))
                reasons.append(f"{'+'.join(nor_modalities)} 共{len(nor)}条正常证据，正常分{normal_score:.2f}")
            else:
                status = "undetermined"
                confidence = min(0.5, normal_score)
                reasons.append(
                    f"正常证据不足：{len(nor)}条/{len(nor_modalities)}种模态"
                    f"（要求≥{self.min_normal_evidence}条且≥{self.min_normal_modalities}种），不报正常")
        else:
            reasons.append("无异常也无正常证据，无法判定")

        if unk:
            reasons.append(f"{len(unk)}条 undetermined 证据未参与判定")

        modalities: Dict[str, List[Dict[str, Any]]] = {}
        trace: List[Dict[str, Any]] = []
        for e in sorted(evs, key=lambda x: (x.modality, x.field, x.value)):
            w = MODALITY_WEIGHTS.get(e.modality, 0.9)
            view = {
                "modality": e.modality,
                "field": e.field,
                "value": e.value,
                "confidence": round(e.confidence, 3),
                "category": e.category,
                "evidence": e.evidence,
                "ts": e.ts,
                "source": e.source,
                "weight": round(w, 3),
            }
            if e.route:
                view["route"] = e.route
            if e.warnings:
                view["warnings"] = list(e.warnings)
            modalities.setdefault(e.modality, []).append(view)
            trace.append(dict(view))

        return FusedPart(
            part=part, route=route, status=status,
            confidence=round(_clip(confidence), 4),
            abnormal_score=round(_clip(abnormal_score), 4),
            normal_score=round(_clip(normal_score), 4),
            conflict=conflict,
            conflict_fields=conflict_fields,
            value_conflicts=value_conflicts,
            high_conf_abnormal=high_conf_abnormal,
            modalities=modalities,
            abnormal_evidence=[e.to_dict(include_extras=False) for e in abn],
            normal_evidence=[e.to_dict(include_extras=False) for e in nor],
            undetermined_evidence=[e.to_dict(include_extras=False) for e in unk],
            reasons=reasons,
            evidence_trace=trace,
        )

    def fuse_file(self, path: str | Path) -> FusionResult:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return self.fuse(data)

    def explain(self, result: FusionResult) -> str:
        lines = [f"# 融合结果（{result.generated_at}）", ""]
        lines.append(f"证据 {len(result.evidence)} 条，部位 {len(result.parts)} 个："
                     f"异常 {len(result.abnormal_parts())} / 正常 {len(result.normal_parts())} / "
                     f"未定 {len(result.undetermined_parts())}")
        for p in result.parts:
            lines.append("")
            lines.append(f"## {p.part} / route={p.route or '-'} → **{p.status}** "
                         f"(conf={p.confidence:.2f})")
            for r in p.reasons:
                lines.append(f"- {r}")
            for m, items in p.modalities.items():
                lines.append(f"- {m}（{len(items)}条）：")
                for it in items:
                    lines.append(f"  - `{it['field']}={it['value']}` conf={it['confidence']} — {it['evidence']}")
        return "\n".join(lines)

def _demo_payload() -> Dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "producer": "fusion.py --demo",
        "evidence": [
            {"part": "z11", "route": "I", "modality": "vision",
             "field": "(image)(operator_display)_display_screen", "value": "yellow_screen",
             "confidence": 0.9, "evidence": "操显画面整屏发黄，无扫描线",
             "ts": now_iso()},
            {"part": "z11", "route": "I", "modality": "vision",
             "field": "(led_indicator)_route_one_z11_work", "value": "off",
             "confidence": 0.9, "evidence": "Z11（收发）工作指示灯不亮",
             "ts": now_iso()},
            {"part": "z11", "route": "I", "modality": "scope",
             "field": "(scope)_route_one_10m_reference", "value": "no",
             "confidence": 0.88, "evidence": "10M 相参基准测试点无波形，幅度 0mV",
             "ts": now_iso()},
        ],
    }

def _print_json(obj: Any) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(json.dumps(obj, ensure_ascii=False, indent=2))

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="多模态证据融合（部位级）")
    ap.add_argument("--evidence", help="证据 JSON 路径（数组或 {evidence:[...]}）")
    ap.add_argument("--demo", action="store_true", help="运行内置黄屏示例")
    ap.add_argument("--markdown", action="store_true", help="输出可读报告而非 JSON")
    ap.add_argument("--no-semantics", action="store_true", help="不读判据库，仅用默认值语义")
    args = ap.parse_args(argv)

    try:
        sem = None if args.no_semantics else ValueSemantics.from_criteria()
        engine = FusionEngine(semantics=sem)
        if args.demo:
            result = engine.fuse(_demo_payload())
        elif args.evidence:
            result = engine.fuse_file(args.evidence)
        else:
            ap.error("需要 --evidence 或 --demo")
            return 2
    except (OSError, json.JSONDecodeError, EvidenceError) as exc:
        print(f"[fusion] 输入错误：{exc}", file=sys.stderr)
        return 1

    if args.markdown:
        print(engine.explain(result))
    else:
        _print_json(result.to_dict())
    if result.warnings:
        for w in result.warnings[:10]:
            print(f"[fusion][warn] {w}", file=sys.stderr)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
