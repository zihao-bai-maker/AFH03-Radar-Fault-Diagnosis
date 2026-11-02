#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""故障分级判定（机柜 cabinet → 分机 sub_unit → 模块 module + feature_id）。

输入
----
* ``evidence/v1`` 证据列表（或 ``fusion.py`` 的融合结果 JSON）；
* 判据库 ``判据库_故障.csv``（268 行真值，69 个“机柜/分机/模块”，
  其中 99 行带 ``field/abnormal_value/feature_id``，169 行为纯现象行）。

输出
----
按置信排序的**候选故障列表**；每条候选给出：
``cabinet / sub_unit / module / module_family / abnormal_value / feature_id``
``confidence / feature_ids / modalities / matched_by / evidence_chain / reason``。

判定方式
--------
1. **field 精确映射**：证据 ``field`` + ``value`` 命中判据库 ``field`` +
   ``abnormal_value`` → 该行所属故障，权重最高；
2. **field 模糊映射**：``field`` 命中但值不在库中 → 低权重（0.35）；
3. **现象文本映射**：未知 field（示波器/新增项）→ 证据原句与 114 条现象做
   IDF 加权的 token 覆盖度匹配（≥0.55）；
4. 同一条证据命中的多个候选按**特异性** ``ln(1+N/该现象候选数)`` 加权，
   多模态一致、多条证据交叉命中、feature_id 对齐 → 提置信；
5. 最高候选置信 <0.60 或与次优差距 <0.08 → **undetermined**（宁可不判）。

铁律：**宁可不判，绝不误判。**
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

try:  
    from fusion import (
        Evidence, FusionEngine, FusionResult, MODALITY_WEIGHTS, MODALITIES,
        normalize_part, normalize_route, normalize_text, normalize_value,
        now_iso, tokenize_text,
    )
except ImportError:  
    from .fusion import (  
        Evidence, FusionEngine, FusionResult, MODALITY_WEIGHTS, MODALITIES,
        normalize_part, normalize_route, normalize_text, normalize_value,
        now_iso, tokenize_text,
    )

ENGINE_VERSION = "fault_grader/1.0.0"
SCHEMA_VERSION = "fault_grade/v1"

ENGINE_DIR = Path(__file__).resolve().parent
CRITERIA_DIR = ENGINE_DIR.parent
DEFAULT_FAULT_CSV = CRITERIA_DIR / "判据库_故障.csv"
DEFAULT_SOP_CSV = CRITERIA_DIR / "判据库_SOP.csv"
DEFAULT_JSON = CRITERIA_DIR / "判据库.json"

MIN_FAULT_CONF = 0.60     
MIN_MARGIN = 0.08         
MIN_CANDIDATE_CONF = 0.10  
MAX_CANDIDATES = 6
SCORE_SCALE = 3.6         

MATCH_FIELD_VALUE = 1.00
MATCH_FIELD_ONLY = 0.35
MATCH_PHENOMENON = 0.95
PHENOMENON_MIN_COVERAGE = 0.55

MODALITY_FACTOR: Dict[str, float] = {
    "vision": 1.00,
    "scope": 1.00,
    "qa": 0.92,
    "audio": 0.88,
}

def _clean(text: Any) -> str:
    """CSV 单元格清洗：换行/全角空格压成单空格。"""
    s = str(text or "").replace("\u3000", " ")
    return re.sub(r"\s+", " ", s).strip()

def module_family(module: str) -> str:
    """把同一物理模块的不同失效模式归并成家族名（仅用于展示/聚合）。

    * ``（Z11-1频综）（无供电）`` / ``（Z11-1频综）（10M相参基准）`` → ``（Z11-1频综）``
    * ``（面板）保险丝FU10（5A）`` → ``（面板）保险丝FU10``
    * 其余保持原样（避免把 ``交流继电器（KA1）`` 误砍成 ``交流继电器``）。
    """
    s = _clean(module)
    s = re.split(r"分别拆|注意", s)[0].strip(" ，,")
    m = re.match(r"^(（Z11-\d[^）]*）)\s*[（(][^）)]*[）)]$", s)
    if m:
        return m.group(1)
    s = re.sub(r"[（(](?:\d+(?:\.\d+)?A)[）)]$", "", s).strip()
    return s or module

@dataclass(frozen=True)
class FaultRef:
    """判据库的一行（故障真值行）。"""

    cabinet: str
    sub_unit: str
    module: str
    remark: str = ""
    step_name: str = ""
    phenomenon: str = ""
    field: str = ""
    abnormal_value: str = ""
    feature_id: str = ""

    @property
    def key(self) -> Tuple[str, str, str]:
        return (self.cabinet, self.sub_unit, self.module)

    @property
    def path(self) -> str:
        return f"{self.cabinet} > {self.sub_unit} > {self.module}"

@dataclass
class EvidenceMatch:
    key: Tuple[str, str, str]
    kind: str                 
    score: float              
    specificity: float        
    rows: List[FaultRef]
    phenomenon: str = ""

    @property
    def support_weight(self) -> float:
        return self.score * self.specificity

class FaultLibrary:
    """判据库索引：field/现象 → 故障候选。"""

    def __init__(self, rows: Sequence[FaultRef], fault_csv: Path,
                 sop_meta: Optional[Dict[str, Any]] = None) -> None:
        self.rows: List[FaultRef] = list(rows)
        self.fault_csv = Path(fault_csv)
        self.sop_meta = sop_meta or {}
        self.keys: List[Tuple[str, str, str]] = []
        self.key_rows: Dict[Tuple[str, str, str], List[FaultRef]] = {}
        self.field_value: Dict[Tuple[str, str], Set[Tuple[str, str, str]]] = {}
        self.field_any: Dict[str, Set[Tuple[str, str, str]]] = {}
        self.phenomenon_keys: Dict[str, Set[Tuple[str, str, str]]] = {}
        self.phenomenon_rows: Dict[str, List[FaultRef]] = {}
        self.phenomenon_tokens: Dict[str, Set[str]] = {}
        self.step_keys: Dict[str, Set[Tuple[str, str, str]]] = {}
        self.step_rows: Dict[str, List[FaultRef]] = {}
        self.step_tokens: Dict[str, Set[str]] = {}
        self.token_idf: Dict[str, float] = {}
        self.step_token_idf: Dict[str, float] = {}
        self.warnings: List[str] = []

        for row in self.rows:
            if row.key not in self.key_rows:
                self.keys.append(row.key)
                self.key_rows[row.key] = []
            self.key_rows[row.key].append(row)
            if row.field:
                self.field_value.setdefault((row.field, normalize_value(row.abnormal_value)),
                                            set()).add(row.key)
                self.field_any.setdefault(row.field, set()).add(row.key)
            if row.phenomenon:
                p = normalize_text(row.phenomenon)
                if len(p) < 2:
                    continue
                self.phenomenon_keys.setdefault(p, set()).add(row.key)
                self.phenomenon_rows.setdefault(p, []).append(row)
            if row.step_name:
                s = normalize_text(row.step_name)
                if len(s) >= 2:
                    self.step_keys.setdefault(s, set()).add(row.key)
                    self.step_rows.setdefault(s, []).append(row)

        for p in self.phenomenon_keys:
            self.phenomenon_tokens[p] = tokenize_text(p)
        n_phen = max(1, len(self.phenomenon_keys))
        df: Dict[str, int] = {}
        for toks in self.phenomenon_tokens.values():
            for t in toks:
                df[t] = df.get(t, 0) + 1
        self.token_idf = {
            t: math.log((n_phen + 1.0) / (d + 0.5)) for t, d in df.items()
        }

        for s in self.step_keys:
            self.step_tokens[s] = tokenize_text(s)
        n_step = max(1, len(self.step_keys))
        sdf: Dict[str, int] = {}
        for toks in self.step_tokens.values():
            for t in toks:
                sdf[t] = sdf.get(t, 0) + 1
        self.step_token_idf = {
            t: math.log((n_step + 1.0) / (d + 0.5)) for t, d in sdf.items()
        }

        self.stats = self._stats()
        self._data_quality()

    @classmethod
    def load(cls, fault_csv: Optional[Path] = None,
             sop_csv: Optional[Path] = None) -> "FaultLibrary":
        path = Path(fault_csv) if fault_csv else DEFAULT_FAULT_CSV
        if not path.exists():
            raise FileNotFoundError(f"判据库不存在：{path}")
        rows: List[FaultRef] = []
        skipped = 0
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            for raw in csv.DictReader(f):
                row = FaultRef(
                    cabinet=_clean(raw.get("cabinet")),
                    sub_unit=_clean(raw.get("sub_unit")),
                    module=_clean(raw.get("module")),
                    remark=_clean(raw.get("remark")),
                    step_name=_clean(raw.get("step_name")),
                    phenomenon=_clean(raw.get("phenomenon")),
                    field=_clean(raw.get("field")),
                    abnormal_value=normalize_value(raw.get("abnormal_value")),
                    feature_id=_clean(raw.get("feature_id")),
                )
                if not (row.cabinet and row.sub_unit and row.module):
                    skipped += 1
                    continue
                rows.append(row)

        sop_meta: Dict[str, Any] = {}
        sop_path = Path(sop_csv) if sop_csv else DEFAULT_SOP_CSV
        if sop_path.exists():
            try:
                with sop_path.open("r", encoding="utf-8-sig", newline="") as f:
                    sop_rows = list(csv.DictReader(f))
                methods: Dict[str, int] = {}
                for r in sop_rows:
                    m = _clean(r.get("method")) or "(空)"
                    methods[m] = methods.get(m, 0) + 1
                sop_meta = {"path": str(sop_path), "rows": len(sop_rows),
                            "methods": methods}
            except Exception as exc:
                sop_meta = {"path": str(sop_path), "error": str(exc)}
        lib = cls(rows, path, sop_meta)
        if skipped:
            lib.warnings.append(f"判据库 {skipped} 行缺少 cabinet/sub_unit/module，已跳过")
        return lib

    def _stats(self) -> Dict[str, Any]:
        structured = [r for r in self.rows if r.field]
        feature_ids = {r.feature_id for r in self.rows if r.feature_id}
        return {
            "fault_csv": str(self.fault_csv),
            "rows": len(self.rows),
            "structured_rows": len(structured),
            "phenomenon_only_rows": len(self.rows) - len(structured),
            "distinct_faults": len(self.keys),
            "distinct_modules": len({k[2] for k in self.keys}),
            "distinct_fields": len(self.field_any),
            "field_value_combos": len(self.field_value),
            "distinct_phenomena": len(self.phenomenon_keys),
            "distinct_step_names": len(self.step_keys),
            "feature_ids": len(feature_ids),
            "sop": self.sop_meta,
        }

    def _data_quality(self) -> None:
        """诚实记录 CSV 已知列错位（field 与 step_name 不匹配）。"""
        bad = 0
        examples: List[str] = []
        for r in self.rows:
            if not (r.field and r.step_name):
                continue
            f, s = r.field, r.step_name
            mismatch = (
                ("course_echo" in f and "回波" not in s)
                or ("glide_echo" in f and "回波" not in s)
                or ("display_screen" in f and "显示画面" not in s)
                or ("z11_work" in f and "工作" not in s)
                or ("transmitter_work" in f and "发射机工作" not in s)
            )
            if mismatch:
                bad += 1
                if len(examples) < 3:
                    examples.append(f"{r.module}: step={s[:24]!r} field={f[:40]!r}")
        self.stats["field_step_mismatch_rows"] = bad
        if bad:
            self.warnings.append(
                f"判据库存在 {bad} 行 field 与 step_name 疑似列错位（如 {examples[0]}）；"
                "判定以 field+value 与多证据交叉为主，不依赖单行 step/phenomenon 配对")

    def _specificity(self, n_keys: int) -> float:
        return math.log(1.0 + len(self.keys) / max(1, n_keys))

    def _coverage(self, text: str, pattern: str,
                  tokens_map: Dict[str, Set[str]],
                  idf: Dict[str, float]) -> float:
        """pattern 的 token 有多少被证据文本覆盖（0..1）。"""
        p_tokens = tokens_map.get(pattern)
        if not p_tokens:
            return 0.0
        n_text = normalize_text(text)
        n_phen = normalize_text(pattern)
        if n_phen and n_phen in n_text:
            return 1.0
        t_tokens = tokenize_text(text)
        matched = p_tokens & t_tokens

        
        if len(p_tokens) >= 2 and len(matched) < 2:
            return 0.0

        
        if matched and max(idf.get(t, 0.0) for t in matched) < 2.0:
            return 0.0
        num = sum(idf.get(t, 0.0) for t in matched)
        den = sum(idf.get(t, 0.0) for t in p_tokens)
        return num / den if den > 0 else 0.0

    def _phenomenon_coverage(self, text: str, phenomenon: str) -> float:
        return self._coverage(text, phenomenon, self.phenomenon_tokens, self.token_idf)

    def _step_coverage(self, text: str, step_name: str) -> float:
        return self._coverage(text, step_name, self.step_tokens, self.step_token_idf)

    def match_evidence(self, ev: Evidence) -> List[EvidenceMatch]:
        """一条异常证据 → 若干候选（带匹配方式/匹配度/特异性）。"""
        field = ev.field
        value = normalize_value(ev.value)

        if field in self.field_any:
            exact = self.field_value.get((field, value))
            if exact:
                return [
                    EvidenceMatch(
                        key=key, kind="field_value", score=MATCH_FIELD_VALUE,
                        specificity=self._specificity(len(exact)),
                        rows=[r for r in self.key_rows[key]
                              if r.field == field and normalize_value(r.abnormal_value) == value],
                    )
                    for key in sorted(exact)
                ]
            keys = self.field_any[field]
            return [
                EvidenceMatch(
                    key=key, kind="field", score=MATCH_FIELD_ONLY,
                    specificity=self._specificity(len(keys)),
                    rows=[r for r in self.key_rows[key] if r.field == field],
                )
                for key in sorted(keys)
            ]

        parts = [ev.evidence or "", str(ev.extras.get("phenomenon", "") or ""),
                 field.replace("_", " ")]
        text = " ".join(p for p in parts if p)
        matches: List[EvidenceMatch] = []
        for phen, keys in self.phenomenon_keys.items():
            cov = self._phenomenon_coverage(text, phen)
            if cov < PHENOMENON_MIN_COVERAGE:
                continue
            phen_rows = self.phenomenon_rows.get(phen, [])
            for key in sorted(keys):
                matches.append(EvidenceMatch(
                    key=key, kind="phenomenon",
                    score=cov * MATCH_PHENOMENON,
                    specificity=self._specificity(len(keys)),
                    rows=[r for r in phen_rows if r.key == key],
                    phenomenon=phen,
                ))

        best: Dict[Tuple[str, str, str], EvidenceMatch] = {}
        for m in matches:
            old = best.get(m.key)
            if old is None or m.score * m.specificity > old.score * old.specificity:
                best[m.key] = m

        if not best:
            for step, keys in self.step_keys.items():
                cov = self._step_coverage(text, step)
                if cov < PHENOMENON_MIN_COVERAGE:
                    continue
                step_rows = self.step_rows.get(step, [])
                for key in sorted(keys):
                    m = EvidenceMatch(
                        key=key, kind="phenomenon",
                        score=cov * MATCH_PHENOMENON,
                        specificity=self._specificity(len(keys)),
                        rows=[r for r in step_rows if r.key == key],
                        phenomenon=step,
                    )
                    old = best.get(key)
                    if old is None or m.score * m.specificity > old.score * old.specificity:
                        best[key] = m
        ranked = sorted(best.values(), key=lambda m: -(m.score * m.specificity))
        return ranked[:12]

@dataclass
class Candidate:
    key: Tuple[str, str, str]
    raw_score: float = 0.0
    confidence: float = 0.0
    modalities: Set[str] = dc_field(default_factory=set)
    matched_by: Set[str] = dc_field(default_factory=set)
    chain: List[Dict[str, Any]] = dc_field(default_factory=list)
    feature_ids: Set[str] = dc_field(default_factory=set)
    evidence_values: Set[str] = dc_field(default_factory=set)
    penalized: List[str] = dc_field(default_factory=list)

    @property
    def cabinet(self) -> str:
        return self.key[0]

    @property
    def sub_unit(self) -> str:
        return self.key[1]

    @property
    def module(self) -> str:
        return self.key[2]

    def primary_chain_item(self) -> Optional[Dict[str, Any]]:
        """优先选带判据库 feature_id 的最高支持证据，保证异常值与 feature 对齐。"""
        with_fid = [c for c in self.chain if c.get("feature_id")]
        pool = with_fid or self.chain
        if not pool:
            return None
        return max(pool, key=lambda c: (c.get("support", 0.0), c.get("confidence", 0.0)))

class FaultGrader:
    def __init__(self, library: Optional[FaultLibrary] = None,
                 fusion_engine: Optional[FusionEngine] = None,
                 min_fault_conf: float = MIN_FAULT_CONF,
                 min_margin: float = MIN_MARGIN,
                 min_candidate_conf: float = MIN_CANDIDATE_CONF,
                 max_candidates: int = MAX_CANDIDATES) -> None:
        self.library = library or FaultLibrary.load()
        self.fusion = fusion_engine or FusionEngine()
        self.min_fault_conf = float(min_fault_conf)
        self.min_margin = float(min_margin)
        self.min_candidate_conf = float(min_candidate_conf)
        self.max_candidates = int(max_candidates)

    def _prepare(self, payload: Any) -> FusionResult:
        if isinstance(payload, FusionResult):
            return payload
        if isinstance(payload, Mapping) and "parts" in payload:
            parts = payload.get("parts") or []
            first = parts[0] if parts and isinstance(parts[0], Mapping) else {}
            if str(payload.get("engine_version", "")).startswith("fusion/") or "abnormal_score" in first:
                return FusionResult.from_dict(payload)
        return self.fusion.fuse(payload)

    def grade(self, payload: Any, fusion: Optional[FusionResult] = None) -> Dict[str, Any]:
        fr = fusion or self._prepare(payload)
        warnings: List[str] = list(fr.warnings)
        abnormal_evs = [e for e in fr.evidence if e.category == "abnormal"]
        part_map = {(p.part, p.route): p for p in fr.parts}

        if not abnormal_evs:
            if fr.parts and all(p.status == "normal" for p in fr.parts):
                conf = min((p.confidence for p in fr.parts), default=0.0)
                return self._result(
                    verdict="normal", confidence=conf,
                    summary=f"全部 {len(fr.parts)} 个部位证据均为正常，未见异常信号",
                    candidates=[], fr=fr, warnings=warnings,
                )
            reason = ("无异常证据，但正常证据不足（需同一部位≥2条且≥2种模态）"
                      if fr.parts else "未收到有效证据")
            return self._result(
                verdict="undetermined", confidence=0.0,
                summary="无法确定：没有异常证据，也不满足正常判定条件",
                undetermined_reason=reason, candidates=[], fr=fr, warnings=warnings,
            )

        cands: Dict[Tuple[str, str, str], Candidate] = {}
        unmatched = 0
        for ev in abnormal_evs:
            matches = self.library.match_evidence(ev)
            if not matches:
                unmatched += 1
                warnings.append(f"证据未命中判据库：{ev.part}/{ev.field}={ev.value}")
                continue
            mf = MODALITY_FACTOR.get(ev.modality, 0.9)
            part = part_map.get((ev.part, ev.route))
            for m in matches:
                support = ev.confidence * mf * m.support_weight
                c = cands.setdefault(m.key, Candidate(key=m.key))
                row_fids = sorted({r.feature_id for r in m.rows if r.feature_id})
                db_vals = sorted({r.abnormal_value for r in m.rows if r.abnormal_value})
                c.raw_score += support
                c.modalities.add(ev.modality)
                c.matched_by.add(m.kind)
                c.evidence_values.add(ev.value)
                c.feature_ids.update(row_fids)
                c.chain.append({
                    "modality": ev.modality,
                    "part": ev.part,
                    "route": ev.route,
                    "field": ev.field,
                    "value": ev.value,
                    "confidence": round(ev.confidence, 3),
                    "evidence": ev.evidence,
                    "ts": ev.ts,
                    "match": m.kind,
                    "match_score": round(m.score, 3),
                    "specificity": round(m.specificity, 3),
                    "support": round(support, 3),
                    "feature_id": row_fids[0] if row_fids else "",
                    "feature_ids": row_fids,
                    "db_abnormal_values": db_vals,
                    "matched_phenomenon": m.phenomenon,
                    "part_status": part.status if part else "unknown",
                    "part_conflict": bool(part.conflict) if part else False,
                })

        if unmatched:
            warnings.append(f"{unmatched}/{len(abnormal_evs)} 条异常证据未命中判据库")

        for c in cands.values():
            raw = c.raw_score
            n_ev = len(c.chain)
            n_mod = len(c.modalities)
            if n_mod >= 2:
                raw *= 1.0 + 0.10 * (n_mod - 1)
            if n_ev >= 2:
                raw *= 1.0 + 0.04 * (n_ev - 1)
            if c.matched_by == {"phenomenon"}:
                raw *= 0.88  

            statuses = {ch.get("part_status") for ch in c.chain}
            if statuses == {"undetermined"}:
                raw *= 0.75
                c.penalized.append("证据所在部位融合状态为 undetermined")
            if any(ch.get("part_conflict") for ch in c.chain):
                raw *= 0.85
                c.penalized.append("证据所在部位存在模态冲突")

            conf = 1.0 - math.exp(-raw / SCORE_SCALE)
            if n_mod >= 2:
                conf += 0.02 * (n_mod - 1)
            if c.matched_by == {"phenomenon"}:
                conf = min(conf, 0.72)
            c.confidence = round(max(0.0, min(0.97, conf)), 4)

        ranked = sorted(cands.values(), key=lambda c: (-c.confidence, -c.raw_score, c.key))
        ranked = [c for c in ranked if c.confidence >= self.min_candidate_conf][: self.max_candidates]
        candidates = [self._candidate_dict(c, i + 1) for i, c in enumerate(ranked)]

        if not candidates:
            return self._result(
                verdict="undetermined", confidence=0.0,
                summary="异常信号存在，但无法映射到判据库故障",
                undetermined_reason="所有候选置信均低于 %.2f" % self.min_candidate_conf,
                candidates=[], fr=fr, warnings=warnings,
            )

        top = candidates[0]
        second_conf = candidates[1]["confidence"] if len(candidates) > 1 else 0.0
        margin = top["confidence"] - second_conf
        if top["confidence"] >= self.min_fault_conf and margin >= self.min_margin:
            verdict = "fault"
            summary = (f"判为故障：{top['fault_path']}（置信{top['confidence']:.2f}，"
                       f"{top['matched_evidence_count']}条证据/{len(top['modalities'])}种模态）")
            reason = ""
        else:
            verdict = "undetermined"
            bits = []
            if top["confidence"] < self.min_fault_conf:
                bits.append(f"最高候选置信{top['confidence']:.2f}<{self.min_fault_conf:.2f}")
            if margin < self.min_margin:
                bits.append(f"与次优差距{margin:.2f}<{self.min_margin:.2f}（候选难分）")
            summary = "无法确定：" + "；".join(bits)
            reason = "；".join(bits) + "，按铁律不判，仅列候选供人工复核"

        return self._result(
            verdict=verdict, confidence=top["confidence"], summary=summary,
            undetermined_reason=reason, candidates=candidates, fr=fr,
            warnings=warnings, hierarchy=self._hierarchy(candidates),
        )

    def _candidate_dict(self, c: Candidate, rank: int) -> Dict[str, Any]:
        primary = c.primary_chain_item() or {}
        fids = sorted(c.feature_ids)
        primary_fid = primary.get("feature_id", "") or (fids[0] if fids else "")
        modalities = sorted(c.modalities)
        return {
            "rank": rank,
            "cabinet": c.cabinet,
            "sub_unit": c.sub_unit,
            "module": c.module,
            "module_family": module_family(c.module),
            "fault_path": f"{c.cabinet} > {c.sub_unit} > {c.module}",
            "confidence": round(c.confidence, 3),
            "abnormal_value": primary.get("value", ""),
            "abnormal_values": sorted(c.evidence_values),
            "feature_id": primary_fid,
            "feature_ids": fids,
            "matched_evidence_count": len(c.chain),
            "modalities": modalities,
            "parts": sorted({str(ch.get("part", "")) for ch in c.chain if ch.get("part")}),
            "matched_by": sorted(c.matched_by),
            "evidence_chain": c.chain,
            "penalized": c.penalized,
            "reason": self._candidate_reason(c, modalities),
        }

    @staticmethod
    def _candidate_reason(c: Candidate, modalities: Sequence[str]) -> str:
        parts = [f"{len(c.chain)}条证据（{'+'.join(modalities)}）命中"]
        for ch in c.chain[:4]:
            tag = {"field_value": "精确", "field": "同字段", "phenomenon": "现象"}.get(ch["match"], ch["match"])
            parts.append(f"{ch['modality']}:{ch['field']}={ch['value']}[{tag}]")
        if len(c.chain) > 4:
            parts.append(f"…另{len(c.chain) - 4}条")
        if c.penalized:
            parts.append("降权：" + "；".join(c.penalized))
        return "；".join(parts)

    def _hierarchy(self, candidates: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        tree: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
        for c in candidates:
            tree.setdefault((str(c["cabinet"]), str(c["sub_unit"])), []).append(c)
        out: List[Dict[str, Any]] = []
        for (cabinet, sub_unit), items in sorted(
                tree.items(), key=lambda kv: (-max(x["confidence"] for x in kv[1]), kv[0])):
            best = items[0]
            out.append({
                "cabinet": cabinet,
                "sub_unit": sub_unit,
                "best_module": best["module"],
                "confidence": best["confidence"],
                "modules": [
                    {"module": x["module"], "confidence": x["confidence"],
                     "feature_ids": x["feature_ids"]}
                    for x in items
                ],
            })
        return out

    def _result(self, verdict: str, confidence: float, summary: str,
                candidates: Sequence[Mapping[str, Any]], fr: FusionResult,
                warnings: Sequence[str], undetermined_reason: str = "",
                hierarchy: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "engine_version": ENGINE_VERSION,
            "generated_at": now_iso(),
            "verdict": verdict,
            "verdict_cn": {"fault": "故障", "normal": "正常", "undetermined": "无法确定"}[verdict],
            "confidence": round(float(confidence), 3),
            "summary": summary,
            "undetermined_reason": undetermined_reason,
            "top_candidate": candidates[0] if candidates else None,
            "candidates": list(candidates),
            "hierarchy": list(hierarchy or []),
            "parts": [
                {"part": p.part, "route": p.route, "status": p.status,
                 "confidence": round(p.confidence, 3), "conflict": p.conflict,
                 "agreement_modalities": sorted(p.modalities.keys()),
                 "reasons": p.reasons}
                for p in fr.parts
            ],
            "evidence_trace": [
                {"part": p.part, "route": p.route, "status": p.status,
                 "modalities": {m: [{"field": v["field"], "value": v["value"],
                                     "confidence": v["confidence"]} for v in items]
                                for m, items in p.modalities.items()}}
                for p in fr.parts
            ],
            "library": dict(self.library.stats, warnings=list(self.library.warnings)),
            "warnings": list(dict.fromkeys(list(warnings)))[:40],
        }

    def explain(self, result: Mapping[str, Any]) -> str:
        lines = [
            f"# 故障分级结果：{result['verdict_cn']}（置信 {result['confidence']:.2f}）",
            "",
            result["summary"],
        ]
        if result.get("undetermined_reason"):
            lines += ["", f"> {result['undetermined_reason']}"]
        cands = result.get("candidates") or []
        if cands:
            lines += ["", "## 候选故障（按置信排序）", "",
                      "| # | 机柜 | 分机 | 模块 | 异常值 | feature_id | 置信 | 模态 |",
                      "|---|---|---|---|---|---|---|---|"]
            for c in cands:
                lines.append(
                    f"| {c['rank']} | {c['cabinet']} | {c['sub_unit']} | {c['module']} | "
                    f"`{c['abnormal_value']}` | `{c['feature_id'] or '—'}` | "
                    f"{c['confidence']:.2f} | {'+'.join(c['modalities'])} |")
            top = cands[0]
            lines += ["", "## 首选候选依据", ""]
            for ch in top["evidence_chain"]:
                tag = {"field_value": "判据库精确命中", "field": "同字段（值不在库）",
                       "phenomenon": "现象文本匹配"}.get(ch["match"], ch["match"])
                lines.append(
                    f"- **{ch['modality']}** `{ch['field']}={ch['value']}` "
                    f"conf={ch['confidence']}，{tag}，支持度 {ch['support']}：{ch['evidence']}")
        lines += ["", "## 部位融合状态", ""]
        for p in result.get("parts", []):
            mods = "+".join(p["agreement_modalities"]) or "—"
            flag = "，存在冲突" if p.get("conflict") else ""
            lines.append(f"- `{p['part']}/{p['route'] or '-'}` → **{p['status']}** "
                         f"({p['confidence']:.2f}，模态：{mods}{flag})")
        if result.get("warnings"):
            lines += ["", "## 警告", ""] + [f"- {w}" for w in result["warnings"]]
        return "\n".join(lines)

def probe_integration(engine_dir: Optional[Path] = None) -> Dict[str, Any]:
    """检查 4 个模态模块是否就绪。只读文件元数据，不执行、不修改。

    qa 的约定文件名是 ``qa_rules.py``，但实际交付可能是 ``qa_flow.py``；
    这里按别名探测并在 ``convention_ok`` 中如实标记，不替对方改名。
    """
    d = Path(engine_dir) if engine_dir else ENGINE_DIR
    specs = {
        "vision_rules.py": ("vision_rules.py",),
        "qa_rules.py": ("qa_rules.py", "qa_flow.py"),
        "scope_rules.py": ("scope_rules.py",),
        "audio_rules.py": ("audio_rules.py",),
    }
    modules: Dict[str, Dict[str, Any]] = {}
    for expected, aliases in specs.items():
        found = next((d / name for name in aliases if (d / name).exists()), None)
        if found is not None:
            st = found.stat()
            modules[expected] = {
                "present": True,
                "filename": found.name,
                "convention_ok": found.name == expected,
                "size": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime).astimezone().isoformat(timespec="seconds"),
                "contract": "未按 evidence/v1 验收（仅探测存在性，未 import）",
            }
            if found.name != expected:
                modules[expected]["note"] = f"约定名 {expected} 不存在，检测到 {found.name}（路径未对齐）"
        else:
            modules[expected] = {"present": False, "filename": "",
                                 "convention_ok": False, "status": "未就绪/待集成"}
    ready = sum(1 for m in modules.values() if m.get("present"))
    convention_ok = sum(1 for m in modules.values() if m.get("convention_ok"))
    return {"engine_dir": str(d), "ready_count": ready, "convention_ok": convention_ok,
            "total": 4, "modules": modules}

def _demo_evidence() -> List[Dict[str, Any]]:
    ts = now_iso()
    return [
        {"part": "z15", "route": "I", "modality": "vision",
         "field": "(image)(operator_display)_display_screen", "value": "black_screen",
         "confidence": 0.93, "evidence": "操显整屏黑，无字符无刻度", "ts": ts},
        {"part": "z15", "route": "I", "modality": "vision",
         "field": "(led_indicator)(operator_display)_z15_display_power", "value": "off",
         "confidence": 0.9, "evidence": "Z15 显示电源指示灯不亮", "ts": ts},
        {"part": "z15", "route": "I", "modality": "vision",
         "field": "(led_indicator)(operator_display)_z15_display_2A_fuse", "value": "on",
         "confidence": 0.9, "evidence": "2A 保险丝报警灯亮", "ts": ts},
    ]

def _print_json(obj: Any) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(json.dumps(obj, ensure_ascii=False, indent=2))

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="故障分级（机柜→分机→模块 + feature_id）")
    ap.add_argument("--evidence", help="evidence/v1 JSON 或 fusion 结果 JSON")
    ap.add_argument("--demo", action="store_true", help="运行内置黑屏保险丝示例")
    ap.add_argument("--markdown", action="store_true", help="输出可读报告")
    ap.add_argument("--status", action="store_true", help="只检查 4 个模态模块就绪情况")
    args = ap.parse_args(argv)

    if args.status:
        _print_json(probe_integration())
        return 0

    try:
        grader = FaultGrader()
        if args.demo:
            payload: Any = _demo_evidence()
        elif args.evidence:
            payload = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
        else:
            ap.error("需要 --evidence、--demo 或 --status")
            return 2
        result = grader.grade(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[fault_grader] 输入/判据库错误：{exc}", file=sys.stderr)
        return 1

    if args.markdown:
        print(grader.explain(result))
    else:
        _print_json(result)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
