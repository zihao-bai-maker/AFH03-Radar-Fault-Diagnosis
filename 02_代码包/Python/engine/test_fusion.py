#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多模态融合 + 故障分级 端到端测试。

* 全部场景使用**真实判据库**（``判据库_故障.csv``，268 行 / 69 个故障部位）；
* 证据是**构造的 evidence/v1**（模拟 4 个采集 agent 的输出），不是真实相机/示波器/
  麦克风采集——硬件链路未验证，见 README_fusion.md §10；
* 15 个场景 + 12 项单元检查，报告通过率；无第三方依赖。

运行：
    python test_fusion.py
    python -X utf8 test_fusion.py
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))

from fault_grader import FaultGrader, FaultLibrary, probe_integration  
from fusion import (  
    EvidenceError, FusionEngine, FusionResult, ValueSemantics, now_iso,
)

TS = "2026-10-18T09:00:00+08:00"

def E(part: str, modality: str, field: str, value: str, confidence: float,
      evidence: str, route: str = "I") -> Dict[str, Any]:
    """构造一条 evidence/v1（测试专用）。"""
    return {
        "part": part, "route": route, "modality": modality, "field": field,
        "value": value, "confidence": confidence, "evidence": evidence, "ts": TS,
    }

SCENARIOS: List[Dict[str, Any]] = [
    {
        "id": "S01",
        "name": "黄屏 + Z11工作灯不亮 + 无10M ⇒ Z11-1频综",
        "evidence": [
            E("z11", "vision", "(image)(operator_display)_display_screen", "yellow_screen", 0.90,
              "操显画面整屏发黄，无扫描线"),
            E("z11", "vision", "(led_indicator)_route_one_z11_work", "off", 0.90,
              "（I）路 Z11（收发）工作指示灯不亮"),
            E("z11", "scope", "(scope)_route_one_10m_reference", "no", 0.88,
              "10M 相参基准测试点无波形，幅度 0mV"),
        ],
        "expect": {
            "verdict": "fault",
            "module_contains": "Z11-1频综",
            "min_confidence": 0.80,
            "feature_id_nonempty": True,
            "part_status": {("z11", "I"): "abnormal"},
            "part_modalities": {("z11", "I"): {"vision", "scope"}},
            "part_count": 1,
        },
    },
    {
        "id": "S02",
        "name": "黑屏 + Z15电源灯不亮 + 2A保险丝灯亮 ⇒ 显示保险丝",
        "evidence": [
            E("z15", "vision", "(image)(operator_display)_display_screen", "black_screen", 0.93,
              "操显整屏黑，无字符无刻度"),
            E("z15", "vision", "(led_indicator)(operator_display)_z15_display_power", "off", 0.90,
              "Z15 显示电源指示灯不亮"),
            E("z15", "vision", "(led_indicator)(operator_display)_z15_display_2A_fuse", "on", 0.90,
              "2A 保险丝报警灯亮"),
        ],
        "expect": {
            "verdict": "fault",
            "module_contains": "显示保险丝",
            "min_confidence": 0.90,
            "feature_id_nonempty": True,
            "abnormal_value_in": ["black_screen", "off", "on"],
            "part_status": {("z15", "I"): "abnormal"},
        },
    },
    {
        "id": "S03",
        "name": "指示灯全亮 + 各波形正常 + 按键确认 ⇒ 正常",
        "evidence": [
            E("z11", "vision", "(led_indicator)_route_one_z11_work", "on", 0.95,
              "Z11 工作指示灯常亮"),
            E("z11", "scope", "(scope)_route_one_10m_reference", "normal", 0.92,
              "10M 相参基准 10.00MHz，波形正常"),
            E("z15", "vision", "(image)(operator_display)_display_screen", "normal", 0.93,
              "操显画面扫描正常，无黄屏/黑屏"),
            E("z15", "vision", "(led_indicator)(operator_display)_z15_display_power", "on", 0.92,
              "显示电源指示灯亮"),
            E("z15", "vision", "(led_indicator)(operator_display)_z15_display_2A_fuse", "off", 0.92,
              "2A 保险丝报警灯未亮（正常）"),
            E("z15", "qa", "(manual_action)_z15_display_power_on", "done", 0.90,
              "按下显示电源键，指示灯亮，问答确认"),
            E("z31", "vision", "(led_indicator)_z31_mains_power", "on", 0.92,
              "市电电源指示灯亮", route=""),
            E("z31", "audio", "(audio)_z31_power_box_contactor", "normal_sound", 0.90,
              "按下控制通后听到接触器吸合声", route=""),
        ],
        "expect": {
            "verdict": "normal",
            "candidate_max": 0,
            "part_count": 3,
            "part_status": {("z11", "I"): "normal", ("z15", "I"): "normal",
                            ("z31", ""): "normal"},
        },
    },
    {
        "id": "S04",
        "name": "只有单模态弱证据（10M 疑似无波形）⇒ undetermined",
        "evidence": [
            E("z11", "scope", "(scope)_route_one_10m_reference", "no", 0.35,
              "10M 疑似无波形，探头接触不良，读数不可靠"),
        ],
        "expect": {
            "verdict": "undetermined",
            "max_confidence": 0.35,
            "part_status": {("z11", "I"): "undetermined"},
        },
    },
    {
        "id": "S05",
        "name": "A/B/C 三相电压均欠压（问答）⇒ 供电欠压",
        "evidence": [
            E("z31", "qa", "(manual_action)_z18_phase_a_voltage", "under_voltage", 0.88,
              "万用表实测 A 相 186V，低于 198V", route=""),
            E("z31", "qa", "(manual_action)_z18_phase_b_voltage", "under_voltage", 0.88,
              "万用表实测 B 相 185V，低于 198V", route=""),
            E("z31", "qa", "(manual_action)_z18_phase_c_voltage", "under_voltage", 0.88,
              "万用表实测 C 相 187V，低于 198V", route=""),
        ],
        "expect": {
            "verdict": "fault",
            "module_contains": "供电欠压",
            "min_confidence": 0.85,
            "part_status": {("z31", ""): "abnormal"},
        },
    },
    {
        "id": "S06",
        "name": "Z31 空调/市电指示灯均不亮 ⇒ 无供电输入",
        "evidence": [
            E("z31", "vision", "(led_indicator)_z31_aircon_power", "off", 0.90,
              "Z31 空调电源指示灯不亮", route=""),
            E("z31", "vision", "(led_indicator)_z31_mains_power", "off", 0.90,
              "Z31 市电电源指示灯不亮", route=""),
        ],
        "expect": {
            "verdict": "fault",
            "module_contains": "无供电输入",
            "min_confidence": 0.80,
            "part_status": {("z31", ""): "abnormal"},
        },
    },
    {
        "id": "S07",
        "name": "Z31 控制灯不亮 + 接触器无吸合声（vision+audio）⇒ 继电器/接触器",
        "evidence": [
            E("z31", "vision", "(led_indicator)_z31_control", "off", 0.92,
              "Z31 控制指示灯不亮", route=""),
            E("z31", "audio", "(audio)_z31_power_box_contactor", "no_sound", 0.90,
              "按下控制通后 4s 内无吸合声，环境噪声 -52dB", route=""),
        ],
        "expect": {
            "verdict": "fault",
            "module_contains": "交流继电器",
            "min_confidence": 0.85,
            "part_modalities": {("z31", ""): {"vision", "audio"}},
        },
    },
    {
        "id": "S08",
        "name": "仅 2A 保险丝报警灯亮（单条高置信）⇒ 显示保险丝候选",
        "evidence": [
            E("z15", "vision", "(led_indicator)(operator_display)_z15_display_2A_fuse", "on", 0.95,
              "2A 保险丝报警灯亮，灯位清晰"),
        ],
        "expect": {
            "verdict": "fault",
            "module_contains": "显示保险丝",
            "min_confidence": 0.60,
            "candidate_min": 1,
            "feature_id_nonempty": True,
        },
    },
    {
        "id": "S09",
        "name": "同一 field 两模态结论冲突 ⇒ 融合 conflict，分级 undetermined",
        "evidence": [
            E("z11", "vision", "(led_indicator)_route_one_z11_work", "off", 0.90,
              "照片显示 Z11 工作灯不亮"),
            E("z11", "qa", "(led_indicator)_route_one_z11_work", "on", 0.60,
              "现场人员问答称工作灯亮（观察角度可能反光）"),
        ],
        "expect": {
            "verdict": "undetermined",
            "max_confidence": 0.50,
            "part_status": {("z11", "I"): "abnormal"},
            "part_conflict": {("z11", "I"): True},
        },
    },
    {
        "id": "S10",
        "name": "I/II 路同一 field 相反证据 ⇒ 分路融合，不互相污染",
        "evidence": [
            E("z11", "vision", "(led_indicator)_route_one_z11_work", "off", 0.90,
              "（I）路工作灯不亮", route="I"),
            E("z11", "vision", "(led_indicator)_route_one_z11_work", "on", 0.95,
              "（II）路工作灯亮", route="II"),
        ],
        "expect": {
            "verdict": "undetermined",
            "part_count": 2,
            "part_status": {("z11", "I"): "abnormal", ("z11", "II"): "undetermined"},
        },
    },
    {
        "id": "S11",
        "name": "黑屏 + 电源灯不亮 + Modem灯不亮（无 2A 灯）⇒ 显示保险丝",
        "evidence": [
            E("z15", "vision", "(image)(operator_display)_display_screen", "black_screen", 0.93,
              "操显整屏黑"),
            E("z15", "vision", "(led_indicator)(operator_display)_z15_display_power", "off", 0.90,
              "Z15 显示电源指示灯不亮"),
            E("z15", "vision", "(led_indicator)(operator_display)_z15_modem_power", "off", 0.90,
              "Z15 Modem 电源指示灯不亮"),
        ],
        "expect": {
            "verdict": "fault",
            "module_contains": "显示保险丝",
            "min_confidence": 0.90,
        },
    },
    {
        "id": "S12",
        "name": "航向/下滑均无回波 + Z11工作灯不亮 ⇒ 多候选、无法唯一确定",
        "evidence": [
            E("z11", "vision", "(image)(operator_display)_course_echo", "no", 0.90,
              "操显航向无回波"),
            E("z11", "vision", "(image)(operator_display)_glide_echo", "no", 0.90,
              "操显下滑无回波"),
            E("z11", "vision", "(led_indicator)_route_one_z11_work", "off", 0.90,
              "Z11（收发）工作指示灯不亮"),
        ],
        "expect": {
            "verdict": "undetermined",
            "candidate_min": 4,
            "module_any_contains": "Z11",
            "max_confidence": 0.90,
        },
    },
    {
        "id": "S13",
        "name": "黄屏 + 无10M（两条证据）⇒ Z11-1频综，置信低于 S01",
        "evidence": [
            E("z11", "vision", "(image)(operator_display)_display_screen", "yellow_screen", 0.90,
              "操显画面黄屏"),
            E("z11", "scope", "(scope)_route_one_10m_reference", "no", 0.88,
              "10M 相参基准无波形"),
        ],
        "expect": {
            "verdict": "fault",
            "module_contains": "Z11-1频综",
            "min_confidence": 0.70,
            "max_confidence": 0.90,
        },
    },
    {
        "id": "S14",
        "name": "外控下滑左/右均不随动 ⇒ 限位开关 vs 接口板继电器，候选并列",
        "evidence": [
            E("z4", "qa", "(manual_action)(operator_display)_external_control_glide_left",
              "no_move", 0.85, "外控下滑左，机构不随动"),
            E("z4", "qa", "(manual_action)(operator_display)_external_control_glide_right",
              "no_move", 0.85, "外控下滑右，机构不随动"),
        ],
        "expect": {
            "verdict": "undetermined",
            "candidate_min": 4,
            "max_confidence": 0.60,
        },
    },
    {
        "id": "S15",
        "name": "只有黄屏（单条高置信）⇒ 候选 5 个并列，undetermined",
        "evidence": [
            E("z11", "vision", "(image)(operator_display)_display_screen", "yellow_screen", 0.95,
              "操显整屏黄，无扫描线"),
        ],
        "expect": {
            "verdict": "undetermined",
            "candidate_min": 2,
            "max_confidence": 0.60,
        },
    },
]

def check_expect(expect: Mapping[str, Any], result: Mapping[str, Any],
                 fr: FusionResult) -> List[str]:
    fails: List[str] = []
    top = result.get("top_candidate") or {}
    candidates = result.get("candidates") or []

    if "verdict" in expect and result.get("verdict") != expect["verdict"]:
        fails.append(f"verdict={result.get('verdict')} 期望 {expect['verdict']}")
    if "module_contains" in expect:
        if not top or expect["module_contains"] not in str(top.get("module", "")):
            fails.append(f"top.module={top.get('module')!r} 不含 {expect['module_contains']!r}")
    if "module_any_contains" in expect:
        needle = expect["module_any_contains"]
        if not any(needle in str(c.get("module", "")) for c in candidates):
            fails.append(f"候选前{len(candidates)}名均不含 {needle!r}")
    if "min_confidence" in expect and float(result.get("confidence", 0)) < expect["min_confidence"]:
        fails.append(f"置信 {result.get('confidence')} < {expect['min_confidence']}")
    if "max_confidence" in expect and float(result.get("confidence", 0)) > expect["max_confidence"]:
        fails.append(f"置信 {result.get('confidence')} > {expect['max_confidence']}")
    if "candidate_min" in expect and len(candidates) < expect["candidate_min"]:
        fails.append(f"候选数 {len(candidates)} < {expect['candidate_min']}")
    if "candidate_max" in expect and len(candidates) > expect["candidate_max"]:
        fails.append(f"候选数 {len(candidates)} > {expect['candidate_max']}")
    if expect.get("feature_id_nonempty"):
        if not top.get("feature_id") or not str(top["feature_id"]).startswith("F_"):
            fails.append(f"top.feature_id={top.get('feature_id')!r} 不是判据库 feature_id")
    if "abnormal_value_in" in expect:
        if top.get("abnormal_value") not in expect["abnormal_value_in"]:
            fails.append(f"abnormal_value={top.get('abnormal_value')!r} 不在 {expect['abnormal_value_in']}")
    for (part, route), status in (expect.get("part_status") or {}).items():
        p = fr.part(part, route)
        if p is None:
            fails.append(f"缺少部位 {part}/{route}")
        elif p.status != status:
            fails.append(f"{part}/{route} status={p.status} 期望 {status}")
    for (part, route), mods in (expect.get("part_modalities") or {}).items():
        p = fr.part(part, route)
        got = set(p.modalities.keys()) if p else set()
        if not set(mods).issubset(got):
            fails.append(f"{part}/{route} 模态 {sorted(got)} 未覆盖 {sorted(mods)}")
    for (part, route), want in (expect.get("part_conflict") or {}).items():
        p = fr.part(part, route)
        if p is None or p.conflict != want:
            fails.append(f"{part}/{route} conflict={getattr(p, 'conflict', None)} 期望 {want}")
    if "part_count" in expect and len(fr.parts) != expect["part_count"]:
        fails.append(f"部位数 {len(fr.parts)} != {expect['part_count']}")
    return fails

def run_unit_checks(engine: FusionEngine, grader: FaultGrader,
                    scenario_results: Mapping[str, Mapping[str, Any]]) -> List[Tuple[str, bool, str]]:
    out: List[Tuple[str, bool, str]] = []

    def add(name: str, fn):
        try:
            detail = fn()
            out.append((name, detail is None or detail is True, "" if detail in (None, True) else str(detail)))
        except Exception as exc:  
            out.append((name, False, f"{type(exc).__name__}: {exc}"))

    def u01():
        from fusion import Evidence
        bad = {"part": "z11", "modality": "camera", "field": "x",
               "value": "off", "confidence": 0.9, "evidence": "x", "ts": TS}
        try:
            Evidence.from_mapping(bad, engine.semantics)
        except EvidenceError:
            pass
        else:
            return "Evidence.from_mapping 未拒绝非法 modality"
        fr = engine.fuse([bad])  
        if fr.evidence:
            return "批量入口未跳过非法证据"
        return True if any("被拒绝" in w for w in fr.warnings) else "缺少拒绝 warning"

    def u02():
        fr = engine.fuse([{"part": "z11", "route": "I", "modality": "vision",
                           "field": "(led_indicator)_route_one_z11_work", "value": "off",
                           "confidence": 0.9, "evidence": "工作灯不亮"}])
        e = fr.evidence[0]
        if not e.ts or not e.ts_filled:
            return "ts 未补记"
        if not any("ts 缺失" in w for w in fr.warnings):
            return "缺少 ts 缺失 warning"
        return True

    def u03():
        ev = {"part": "z31", "modality": "audio",
              "field": "(audio)_z31_power_box_contactor", "value": "no_sound",
              "confidence": 0.9, "reason": "无吸合声", "item_id": "audio_z31_power_box_contactor",
              "route": None}
        fr = engine.fuse([ev])
        e = fr.evidence[0]
        if e.route != "" or e.evidence != "无吸合声" or e.category != "abnormal":
            return f"route={e.route!r} evidence={e.evidence!r} cat={e.category}"
        p = fr.part("z31", "")
        return True if p and p.status == "abnormal" else "z31 未判异常"

    def u04():
        sem = ValueSemantics.from_criteria()
        fld = "(led_indicator)(operator_display)_z15_display_2A_fuse"
        checks = [sem.category(fld, "on") == "abnormal", sem.category(fld, "off") == "normal",
                  sem.category("(led_indicator)_route_one_z11_work", "off") == "abnormal",
                  sem.category("(led_indicator)_route_one_z11_work", "on") == "normal"]
        return True if all(checks) else f"2A/指示灯语义错误：{checks}"

    def u05():
        base = {"part": "z11", "route": "I", "modality": "vision",
                "field": "(image)(operator_display)_course_echo", "value": "no", "evidence": "无回波"}
        fr = engine.fuse([dict(base, confidence=0.6), dict(base, confidence=0.9)])
        if len(fr.evidence) != 1 or fr.duplicates != 1:
            return f"去重失败 evidence={len(fr.evidence)} dups={fr.duplicates}"
        return True if abs(fr.evidence[0].confidence - 0.9) < 1e-9 else "未保留最高置信"

    def u06():
        st = probe_integration()
        if st.get("total") != 4 or len(st.get("modules", {})) != 4:
            return "probe_integration 结构错误"
        if "convention_ok" not in st:
            return "缺少 convention_ok（qa 文件名不对齐时无法如实标记）"
        return True if all("present" in v for v in st["modules"].values()) else "缺少 present"

    def u07():
        fr = engine.fuse(SCENARIOS[0]["evidence"])
        r1 = grader.grade(fr)
        r2 = grader.grade(fr.to_dict())
        if r1["verdict"] != r2["verdict"] or r1["confidence"] != r2["confidence"]:
            return f"roundtrip 不一致 {r1['verdict']}/{r2['verdict']}"
        return True

    def u08():
        single = {"part": "z11", "route": "I", "modality": "scope",
                  "field": "(scope)_route_one_10m_reference", "value": "normal",
                  "confidence": 0.9, "evidence": "10M 波形正常", "ts": TS}
        fr = engine.fuse(single)  
        return True if len(fr.evidence) == 1 else "单条对象被误当封装"

    def u09():
        ev = {"modality": "vision", "field": "(image)(operator_display)_display_screen",
              "value": "black_screen", "confidence": 0.93, "evidence": "整屏黑",
              "check_item": "(操显)-显示画面", "route": "I", "ts": TS}
        fr = engine.fuse([ev])
        if not fr.evidence or fr.evidence[0].part != "unknown":
            return "空 part 未降级为 unknown"
        r = grader.grade(fr)
        if r["verdict"] != "fault" or "显示保险丝" not in str(r["top_candidate"]["module"]):
            return f"空 part 证据分级失败：{r['verdict']}"
        return True

    def u10():
        ev = {"part": "z14", "route": "I", "modality": "scope",
              "field": "(scope)_route_one_10m_reference", "value": "abnormal",
              "confidence": 0.8, "ts": TS,
              "evidence": "10M相参基准 实测10.4MHz 期望10.0MHz 偏差4.0% 超容差"}
        r = grader.grade(engine.fuse([ev]))

        return True if not r["candidates"] else f"误命中 {r['candidates'][0]['module']}"

    def u11():
        s01 = scenario_results["S01"]["confidence"]
        s13 = scenario_results["S13"]["confidence"]
        return True if s01 > s13 else f"S01 {s01} 未高于 S13 {s13}（多证据/多模态未提置信）"

    def u12():
        fr = engine.fuse([E("z11", "vision", "(led_indicator)_route_one_z11_work", "on", 0.95,
                            "只有一条正常证据")])
        p = fr.part("z11", "I")
        return True if p and p.status == "undetermined" else f"单条正常证据被判 {p.status if p else None}"

    def u13():

        ev = {"part": "z18", "route": "", "modality": "qa",
              "field": "(manual_action)_z18_phase_a_voltage", "value": "under_voltage",
              "confidence": 0.9, "note": "操作员确认：实测 A 相 186V"}
        fr = engine.fuse([ev])
        e = fr.evidence[0]
        if e.evidence != "操作员确认：实测 A 相 186V":
            return f"note 未作为 evidence：{e.evidence!r}"
        if not e.ts_filled:
            return "ts 未补记"
        return True if e.category == "abnormal" else f"category={e.category}"

    add("U01 非法 modality 被拒绝", u01)
    add("U02 缺 ts 自动补记并 warning", u02)
    add("U03 audio_rules 风格（reason/route=null/无ts）可接入", u03)
    add("U04 2A保险丝 on=异常 / off=正常 反向语义", u04)
    add("U05 同模态重复证据去重取最高置信", u05)
    add("U06 probe_integration 覆盖 4 模块", u06)
    add("U07 fusion 结果序列化后可继续分级", u07)
    add("U08 单条证据对象（含 evidence 字符串）可解析", u08)
    add("U09 part 缺失降级 unknown 仍可分级", u09)
    add("U10 示波器“频率超差”不得误命中“无10M”", u10)
    add("U11 多证据/多模态提置信（S01>S13）", u11)
    add("U12 单条正常证据不报 normal", u12)
    add("U13 qa_flow 风格（note/无ts/route空）可接入", u13)
    return out

def main() -> int:
    print("=" * 78)
    print("多模态融合 + 故障分级 端到端测试")
    print("=" * 78)
    try:
        library = FaultLibrary.load()
        engine = FusionEngine()
        grader = FaultGrader(library=library, fusion_engine=engine)
    except Exception as exc:  
        print(f"[FATAL] 初始化失败：{type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 2

    stats = library.stats
    print(f"判据库: {stats['rows']} 行 / {stats['distinct_faults']} 个故障部位 / "
          f"{stats['structured_rows']} 行结构化 / {stats['feature_ids']} 个 feature_id")
    print(f"现象: {stats['distinct_phenomena']} 条；step_name: "
          f"{stats.get('distinct_step_names', 0)} 条；field-step 疑似错位: "
          f"{stats.get('field_step_mismatch_rows', 0)} 行（判定不依赖单行配对）")
    st = probe_integration()
    ready = [k for k, v in st["modules"].items() if v.get("present")]
    print(f"模态模块就绪 {st['ready_count']}/4（约定名对齐 "
          f"{st.get('convention_ok', 0)}/4）：{', '.join(ready) if ready else '无'}")
    qa = st["modules"].get("qa_rules.py", {})
    if qa.get("present") and not qa.get("convention_ok"):
        print(f"  注意：约定名 qa_rules.py 未提供，检测到 {qa.get('filename')}（路径待对齐）")
    print("-" * 78)

    scenario_results: Dict[str, Dict[str, Any]] = {}
    scenario_pass = 0
    for sc in SCENARIOS:
        try:
            fr = engine.fuse(sc["evidence"])
            result = grader.grade(fr)
            fails = check_expect(sc["expect"], result, fr)
        except Exception as exc:  
            fails = [f"异常：{type(exc).__name__}: {exc}"]
            result = {"verdict": "ERROR", "confidence": 0.0, "candidates": []}
            traceback.print_exc()
        scenario_results[sc["id"]] = result
        ok = not fails
        scenario_pass += int(ok)
        top = result.get("top_candidate") or {}
        label = top.get("module") or result.get("verdict")
        print(f"[{'PASS' if ok else 'FAIL'}] {sc['id']} {sc['name']}")
        print(f"       → {result.get('verdict')} conf={result.get('confidence')} top={label}")
        for f in fails:
            print(f"       ✗ {f}")

    print("-" * 78)
    unit = run_unit_checks(engine, grader, scenario_results)
    unit_pass = sum(1 for _, ok, _ in unit if ok)
    for name, ok, detail in unit:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ✗ {detail}" if not ok else ""))

    total = len(SCENARIOS) + len(unit)
    passed = scenario_pass + unit_pass
    print("=" * 78)
    print(f"场景通过率: {scenario_pass}/{len(SCENARIOS)} = {scenario_pass / len(SCENARIOS) * 100:.1f}%")
    print(f"单元检查:   {unit_pass}/{len(unit)} = {unit_pass / len(unit) * 100:.1f}%")
    print(f"总计:       {passed}/{total} = {passed / total * 100:.1f}%")
    print("=" * 78)
    return 0 if passed == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
