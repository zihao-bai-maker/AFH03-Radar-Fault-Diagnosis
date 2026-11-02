#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_session_summary.py —— ``session_summary.py`` 的场景测试（19 个场景，覆盖用户点名的每一条）。

覆盖
----
1. 单现象 ⇒ 候选列全（不隐藏候选）
2. 多现象交叉印证（不扫描 + 无底噪）⇒ 交集优先、收敛到 1 个
3. 交集内 2 个候选接近 ⇒ partial（分不清就不硬认）
4. 无交集（黑屏 + 无底噪）⇒ verdict=undetermined，只列并集，不硬凑
5. 全正常（≥2 条 / ≥2 模态）⇒ 正常
6. 只有 1 条正常 ⇒ 不足以判正常（schema §7）
7. 全 undetermined ⇒ 未判定 + 原因
8. 空 evidence ⇒ 优雅降级
9. 损坏 JSON ⇒ 优雅降级（不抛异常）
10. 弱灯问答 + 视觉冲突 ⇒ 问答优先（复用 screen_qa 口径）
11. 低置信异常（0.3）⇒ 不参与收敛（宁可不判）
12. 知识库未收录现象（有黄线）⇒ 只报现象、不给原因
13. 判据库 field 级反向语义（2A 保险丝 on=异常）
14. 采集层规则期望（match/expect）⇒ 该灭的灯灭=正常
15. 去重 + 部位识别证据（modality=part 归 scope）
16. 真实板端 flow_evidence 样例（只读）
17. 契约字段 / 确定性 / JSON 可序列化
18. CLI（in-process 调用 main）写 summary.json
19. 置信公式可用 score_detail 手算复核

运行
----
::

    python test_session_summary.py            # 打印通过率
    python test_session_summary.py -v         # 失败时也不额外刷屏（保留接口）
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

ENGINE_DIR = Path(__file__).resolve().parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

import session_summary as ss  

TS = "2026-10-20T21:00:00+08:00"
REQUIRED_KEYS = ("session", "counts", "abnormals", "top_faults", "unexplained", "verdict")

class Check:
    def __init__(self, name: str, verbose: bool = False):
        self.name = name
        self.verbose = verbose
        self.fails: List[str] = []
        self.checks = 0

    def ok(self, cond: Any, msg: str) -> None:
        self.checks += 1
        if not cond:
            self.fails.append(msg)

    def eq(self, got: Any, want: Any, msg: str) -> None:
        self.ok(got == want, f"{msg}: 期望 {want!r}，实际 {got!r}")

    def contains(self, hay: Any, needle: Any, msg: str) -> None:
        self.ok(needle in hay, f"{msg}: {needle!r} 不在 {hay!r}")

    def between(self, got: float, lo: float, hi: float, msg: str) -> None:
        self.ok(lo <= got <= hi, f"{msg}: 期望 [{lo}, {hi}]，实际 {got!r}")

def ev(part: str, field: str, value: str, conf: float = 0.9, modality: str = "vision",
       route: str = "", **kw: Any) -> Dict[str, Any]:
    d = {"part": part, "route": route, "modality": modality, "field": field,
         "value": value, "confidence": conf, "evidence": "场景构造的证据",
         "ts": TS}
    d.update(kw)
    return d

def run(payload: Any) -> Dict[str, Any]:
    return ss.summarize(payload, generated_at=TS)

def t01_single_phenomenon(c: Check) -> None:
    """单现象：候选必须**列全**，不是只给第一名。"""
    r = run([ev("z15", "(image)(operator_display)_display_screen", "black_screen", 0.93,
                step_id="s1", check_item="(操显)-Z15-显示画面")])
    c.eq(r["verdict"], "converged", "黑屏单现象结论")
    c.eq(r["conclusion"], "fault", "黑屏单现象 conclusion")
    c.eq(r["candidates_total"], 3, "黑屏应有 3 个候选（显示保险丝/电源模块/指示分机）")
    c.eq(len(r["top_faults"]), 3, "候选 ≤3 时应全部列出")
    c.eq(len(r["all_candidates"]), 3, "all_candidates 也要列全")
    c.contains(r["top_faults"][0]["module"], "显示保险丝", "黑屏第一名")
    c.eq(r["top_faults"][0]["covers_all"], True, "单现象时第一名覆盖全部现象")
    c.ok(0.80 <= r["top_faults"][0]["confidence"] <= 0.95,
         f"置信应在 [0.80,0.95]，实际 {r['top_faults'][0]['confidence']}")
    c.eq(r["top_faults"][0]["support_ids"], ["E01"], "支撑证据 id")
    c.ok(r["top_faults"][0]["kb_rows"], "候选必须带判据库行号")
    c.contains(r["text"], "🎯 最可能的故障", "页面文案")
    c.contains(r["text"], "①", "页面文案用 ①②③ 编号")
    c.contains(r["text"], "【返回】【再拍一轮】", "页面按钮文案")
    c.ok(any("没有交叉印证" in n for n in r["notes"]), "单现象必须注明没有交叉印证")

def t02_intersection_converges(c: Check) -> None:
    """多现象交叉印证：不扫描 + 无底噪 ⇒ 交集只有 Z19-FU1，且排在「单现象更强」的候选前面。"""
    r = run([
        ev("z15", "(image)(operator_display)_course_scan", "no_scan", 0.9,
           step_id="s1", check_item="(操显)-Z15-航向扫描"),
        ev("z15", "(image)(operator_display)_course_noise", "no_noise", 0.9,
           step_id="s2", check_item="(操显)-Z15-航向噪声"),
    ])
    c.eq(r["verdict"], "converged", "交叉印证应收敛")
    c.eq(r["conclusion"], "fault", "交叉印证 conclusion=fault")
    c.eq(r["converge"]["phenomena_total"], 2, "两个现象")
    c.eq(r["converge"]["intersection_size"], 1, "交集应只有 1 个候选")
    top = r["top_faults"][0]
    c.contains(top["module"], "保险丝", "交集候选应是 Z19-FU1-2A保险丝")
    c.eq(top["covers_all"], True, "第一名覆盖全部现象")
    c.eq(top["phenomena_explained"], 2, "第一名解释 2 个现象")
    c.eq(top["support_phenomena"], 2, "支撑 2 个现象")
    c.eq(sorted(top["support_ids"]), ["E01", "E02"], "支撑证据应是两条")
    c.ok(all(s["kb_row"] for s in top["support"]), "每条支撑都要有判据行号")
    c.ok(all(not x["covers_all"] for x in r["top_faults"][1:]),
         "只解释部分现象的候选不能标 covers_all")

    c.ok(all(x["phenomena_explained"] < 2 for x in r["top_faults"][1:]),
         "排在交集候选后面的只能解释 1 个现象")
    c.contains(r["verdict_reason"], "唯一", "收敛理由应说明唯一候选")
    c.ok(top["confidence"] >= 0.60, f"收敛候选置信应 ≥0.60（实际 {top['confidence']}）")

def t03_intersection_two_close(c: Check) -> None:
    """交集内 2 个候选（Z19-FU1 / GL2），置信差 <0.10 ⇒ 只能 partial（不硬认第一名）。"""
    r = run([
        ev("z15", "(image)(operator_display)_display_screen", "yellow_screen", 0.9,
           step_id="s1", check_item="(操显)-Z15-显示画面"),
        ev("z15", "(image)(operator_display)_course_noise", "no_noise", 0.9,
           step_id="s2", check_item="(操显)-Z15-航向噪声"),
    ])
    c.eq(r["verdict"], "partial", "前两名接近时 verdict=partial")
    c.eq(r["conclusion"], "undetermined", "前两名接近时 conclusion=undetermined")
    c.eq(r["converge"]["intersection_size"], 2, "黄屏+无底噪 的交集应是 2 个候选")
    mods = [x["module"] for x in r["top_faults"][:2]]
    c.ok(any("保险丝" in m for m in mods), "交集含 Z19-FU1")
    c.ok(any("GL2" in m for m in mods), "交集含 GL2 电源模块")
    c.ok(all(x["covers_all"] for x in r["top_faults"][:2]), "交集内两个都覆盖全部现象")
    c.ok(r["converge"]["margin_covering"] < ss.MIN_MARGIN,
         f"交集内差距应 <{ss.MIN_MARGIN}，实际 {r['converge']['margin_covering']}")
    c.contains(r["verdict_reason"], "接近", "理由说明分不清")
    c.contains(r["text"], "以上只是候选", "页面对未收敛结论必须标注")

def t04_no_intersection(c: Check) -> None:
    """无交集（黑屏 + 无底噪）⇒ 不硬凑：verdict=undetermined，只列并集。"""
    r = run([
        ev("z15", "(image)(operator_display)_display_screen", "black_screen", 0.93,
           step_id="s1", check_item="(操显)-Z15-显示画面"),
        ev("z15", "(image)(operator_display)_glide_noise", "no_noise", 0.9,
           step_id="s2", check_item="(操显)-Z15-下滑噪声"),
    ])
    c.eq(r["verdict"], "undetermined", "交集为空 ⇒ undetermined")
    c.eq(r["conclusion"], "undetermined", "交集为空 ⇒ conclusion=undetermined")
    c.eq(r["converge"]["intersection_empty"], True, "应标记 intersection_empty")
    c.eq(r["converge"]["intersection_size"], 0, "交集应为 0")
    c.ok(r["candidates_total"] > 0, "并集候选必须列出来（不能什么都不给）")
    c.eq(len(r["top_faults"]), 3, "并集按可能性列 Top3")
    c.ok(not any(x["covers_all"] for x in r["all_candidates"]), "没有任何候选能覆盖全部现象")
    c.contains(r["verdict_reason"], "交集为空", "理由必须写清交集为空")
    c.contains(r["verdict_reason"], "不硬凑", "理由必须写清不硬凑")
    c.contains(r["text"], "⚠️", "页面要提示无法收敛")

def t05_all_normal(c: Check) -> None:
    """全正常（≥2 条正常证据 + ≥2 种模态）⇒ 正常。"""
    r = run([
        ev("z14", "(led_indicator)_z14_power", "on", 0.95, step_id="s1",
           check_item="(操显)-Z14-电源灯"),
        ev("z14", "(led_indicator)_z14_reset", "on", 1.0, modality="qa", route="I",
           step_id="s1", check_item="(操显)-Z14-复位灯"),
    ])
    c.eq(r["verdict"], "converged", "全正常 verdict=converged")
    c.eq(r["conclusion"], "normal", "全正常 conclusion=normal")
    c.eq(r["counts"]["items"]["normal"], 2, "正常证据 2 条")
    c.eq(r["counts"]["items"]["abnormal"], 0, "无异常")
    c.eq(r["top_faults"], [], "正常时不能给故障候选")
    c.contains(r["text"], "未发现异常", "页面文案")
    c.ok(not r["unexplained"], "正常时没有未解释现象")

def t06_single_normal_not_enough(c: Check) -> None:
    """只有 1 条正常证据 ⇒ 不足以判「正常」（schema_evidence.md §7：宁可不判）。"""
    r = run([ev("z14", "(led_indicator)_z14_power", "on", 0.95, step_id="s1")])
    c.eq(r["conclusion"], "undetermined", "单条正常证据不能判正常")
    c.eq(r["verdict"], "undetermined", "单条正常证据 verdict=undetermined")
    c.contains(r["verdict_reason"], "§7", "理由要引用证据契约 §7")
    c.eq(r["counts"]["items"]["normal"], 1, "正常证据计数仍为 1")

def t07_all_undetermined(c: Check) -> None:
    """全 undetermined ⇒ 未判定 + 原因。"""
    r = run([
        ev("z14", "(led_indicator)_z14_reset", "undetermined", 0.3, modality="qa",
           step_id="s1"),
        ev("z14", "(vision)_step_9_7_I_3", "undetermined", 0.5, step_id="s1"),
    ])
    c.eq(r["verdict"], "undetermined", "全未判定 ⇒ verdict=undetermined")
    c.eq(r["conclusion"], "undetermined", "全未判定 ⇒ conclusion=undetermined")
    c.eq(r["counts"]["items"]["undetermined"], 2, "未判定计数")
    c.eq(r["top_faults"], [], "不能凭未判定给候选")
    c.ok(r["verdict_reason"], "必须给原因")
    c.contains(r["verdict_reason"], "未判定", "原因里要出现未判定")
    c.contains(r["text"], "⚠️", "页面要提示")

def t08_empty(c: Check) -> None:
    """空 evidence ⇒ 优雅降级，结构完整。"""
    for payload in ([], None, {"schema": "evidence/v1", "evidence": []}):
        r = run(payload)
        c.eq(r["verdict"], "undetermined", f"空输入 verdict（{type(payload).__name__}）")
        for k in REQUIRED_KEYS:
            c.ok(k in r, f"空输入也必须输出 {k}")
        c.eq(r["counts"]["modules"], 0, "空输入没有模块")
        c.ok(r["text"], "空输入也要有页面文案")

def t09_corrupt_json(c: Check) -> None:
    """损坏 JSON / 不支持的类型 ⇒ 优雅降级（不抛异常）。"""
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "bad.json"
        bad.write_text('{"evidence": [ {"part": "z11", ', encoding="utf-8")
        r = ss.summarize_file(str(bad), generated_at=TS)
        c.eq(r["verdict"], "undetermined", "坏 JSON verdict")
        c.contains(r["verdict_reason"], "损坏", "坏 JSON 原因")
        c.ok(not (Path(td) / "summary.json").exists(), "坏 JSON 不应写 summary.json")
        c.ok(r["text"], "坏 JSON 也要有文案")

        missing = ss.summarize_file(str(Path(td) / "nope.json"), generated_at=TS)
        c.eq(missing["verdict"], "undetermined", "文件不存在 verdict")
        c.contains(missing["verdict_reason"], "不存在", "文件不存在原因")

    r2 = ss.summarize("这不是 JSON", generated_at=TS)
    c.eq(r2["verdict"], "undetermined", "非法 JSON 文本 verdict")
    c.contains(r2["verdict_reason"], "无法解析", "非法 JSON 文本原因")
    r3 = ss.summarize(12345, generated_at=TS)
    c.eq(r3["verdict"], "undetermined", "非法类型 verdict")

def t10_qa_priority(c: Check) -> None:
    """弱灯问答 + 视觉冲突 ⇒ 问答优先（视觉那条降级，不作为异常）。"""
    r = run([
        ev("z14", "(led_indicator)_z14_power", "off", 0.55, step_id="s1",
           note="画面偏暗，疑似灯灭"),
        ev("z14", "(led_indicator)_z14_power", "on", 1.0, modality="qa", route="I",
           step_id="s1", note="操作员确认灯亮"),
        ev("z14", "(led_indicator)_z14_reset", "on", 0.9, step_id="s1"),
    ])
    c.eq(len(r["conflicts"]), 1, "应识别 1 处冲突")
    c.eq(r["conflicts"][0]["winner_modality"], "qa", "冲突以问答为准")
    c.eq(r["counts"]["items"]["abnormal"], 0, "视觉那条被降级后不能算异常")
    c.eq(r["counts"]["items"]["normal"], 2, "剩下的正常证据 2 条")
    c.eq(r["counts"]["superseded"], 1, "应记录被降级的证据数")
    c.eq(r["conclusion"], "normal", "问答优先后本轮正常")
    vis = [x for x in r["undetermined"] if x["subcategory"] == "superseded_by_qa"]
    c.eq(len(vis), 1, "被降级的视觉证据进 undetermined 且带原因")
    c.contains(vis[0]["why"], "问答为准", "降级原因")
    c.ok(any("问答优先" in n for n in r["notes"]), "notes 要说明问答优先")

def t11_weak_evidence(c: Check) -> None:
    """低置信异常（0.3）⇒ 只记录、不参与收敛。"""
    r = run([
        ev("z31", "(led_indicator)_z31_control", "off", 0.3, step_id="s1"),
        ev("z31", "(led_indicator)_z31_mains_power", "off", 0.9, step_id="s1"),
    ])
    c.eq(r["counts"]["items"]["abnormal"], 1, "只有 0.9 那条算异常")
    c.eq(r["counts"]["items"]["undetermined"], 1, "0.3 那条降级为未判定")
    weak = [x for x in r["undetermined"] if x["subcategory"] == "weak_evidence"]
    c.eq(len(weak), 1, "弱证据要有 subcategory")
    c.eq(weak[0]["value"], "off", "弱证据仍要保留原始观测")
    c.ok(any("弱证据" in n for n in r["notes"]), "notes 要提弱证据")
    c.ok(all(0.60 <= x["confidence"] <= 0.95 for x in r["top_faults"]),
         "候选置信不应被 0.3 的弱证据抬高")

def t12_kb_external(c: Check) -> None:
    """知识库未收录现象（有黄线）⇒ 只报现象、绝不给原因。"""
    r = run([
        ev("z15", "(image)(operator_display)_display_screen", "yellow_line", 0.8,
           step_id="s1", check_item="(操显)-Z15-画面有黄线"),
        ev("z15", "(image)(operator_display)_course_noise", "no_noise", 0.9, step_id="s2"),
    ])
    c.eq(r["counts"]["items"]["abnormal"], 1, "有黄线不算异常（知识库无依据）")
    ext = [x for x in r["undetermined"] if x["subcategory"] == "kb_external"]
    c.eq(len(ext), 1, "有黄线应落 kb_external")
    c.contains(ext[0]["why"], "知识库未收录", "原因")
    c.ok(any(u["ev_id"] == ext[0]["ev_id"] for u in r["unexplained"]),
         "知识库外现象必须进 unexplained")
    c.eq(r["verdict"], "partial", "还有未解释现象 ⇒ 最多 partial")
    c.eq(r["conclusion"], "undetermined", "有未解释现象 ⇒ 不下结论")
    c.ok(all("黄线" not in x["module"] for x in r["all_candidates"]),
         "绝不能给「黄线」编候选原因")
    c.ok(any("知识库未收录" in n for n in r["notes"]), "notes 要说明")

def t13_reverse_semantics(c: Check) -> None:
    """判据库 field 级反向语义：2A 保险丝报警灯「亮」才是异常。"""
    r = run([ev("z15", "(led_indicator)(operator_display)_z15_display_2A_fuse", "on", 0.95,
                step_id="s1", check_item="(操显)-Z15-[2A]-保险丝报警灯亮")])
    c.eq(r["counts"]["items"]["abnormal"], 1, "2A 保险丝 on 应判异常")
    c.eq(r["abnormals"][0]["semantics"], "kb_field_override", "语义来源应是判据库覆盖")
    c.eq(r["verdict"], "converged", "2A 保险丝应能收敛")
    c.contains(r["top_faults"][0]["module"], "保险丝", "候选应是显示保险丝")
    c.eq(r["top_faults"][0]["feature_id"].startswith("F_"), True,
         "应带判据库 feature_id")

    r2 = run([ev("z15", "(led_indicator)(operator_display)_z15_display_2A_fuse", "off", 0.95,
                 step_id="s1")])
    c.eq(r2["counts"]["items"]["abnormal"], 0, "同一 field 报 off 是正常态")
    c.eq(r2["abnormals"], [], "off 不能产生异常")

def t14_rule_expectation(c: Check) -> None:
    """采集层规则期望：该灭的灯灭了 = 正常（避免把「正常态 off」误报成故障）。"""
    r = run([ev("z14", "(led_indicator)_z14_fuse", "off", 0.95, step_id="s1",
                rule="led:Z14_PANEL#3", kind="led", expect="应灭", match=True,
                check_item="(操显)-Z14-[保险丝]-3.15A-指示灯")])
    c.eq(r["counts"]["items"]["normal"], 1, "match=true 应判正常")
    c.eq(r["counts"]["items"]["abnormal"], 0, "match=true 不能误报异常")
    c.eq(r["normals"][0]["semantics"], "evidence_rule_expect", "语义来源")

    r2 = run([ev("z14", "(led_indicator)_z14_fuse", "off", 0.95, step_id="s1",
                 rule="led:Z14_PANEL#3", kind="led", expect="应亮", match=False)])
    c.eq(r2["counts"]["items"]["abnormal"], 1, "match=false 应判异常")

    r3 = run([ev("z14", "(led_indicator)_z14_fuse", "off", 0.95, step_id="s1")])
    c.eq(r3["counts"]["items"]["abnormal"], 1, "无规则字段时 off 按全局枚举算异常")

def t15_dedupe_and_scope(c: Check) -> None:
    """去重（同 part/route/modality/field/value）+ modality=part 归 scope。"""
    r = run([
        ev("z14", "(led_indicator)_z14_fuse", "off", 0.9, step_id="s1"),
        ev("z14", "(led_indicator)_z14_fuse", "off", 0.7, step_id="s1"),
        ev("z14", "(part)_step_9_7_I_3", "z14", 0.85, modality="part", step_id="s1"),
    ])
    c.eq(r["counts"]["duplicates"], 1, "重复证据应合并")
    c.eq(len(r["duplicates"]), 1, "duplicates 明细")
    c.eq(r["counts"]["items"]["scope"], 1, "部位识别证据归 scope")
    c.eq(r["counts"]["modules"], 1, "scope 不算模块")
    c.eq(r["counts"]["items"]["total"], 2, "有效证据 = 去重后 1 条 + scope 1 条")
    c.ok(all(x["category"] != "scope" for x in r["abnormals"]), "scope 不能算异常")

def t16_real_board_file(c: Check) -> None:
    """真实板端 flow_evidence 样例：只读、能跑通、结论正常（3 正常 / 2 未判定）。"""
    p = ENGINE_DIR.parent / "_shots" / "flow_evidence_20261018_154422.json"
    if not p.exists():
        c.ok(True, f"样例不存在，跳过：{p}")
        return
    before = p.read_bytes()
    r = ss.summarize_file(str(p), generated_at=TS)
    c.eq(p.read_bytes(), before, "绝不能改动板端证据文件（只读）")
    c.eq(r["session"]["schema"], "flow_evidence/v1", "会话包装 schema")
    c.eq(r["session"]["producer"], "ui_kiosk.flow", "producer")
    c.eq(r["session"]["evidence_total"], 6, "原始证据 6 条")
    c.eq(r["session"]["duplicates"], 1, "同 field 同值应合并 1 条")
    c.eq(r["counts"]["items"]["total"], 5, "去重后 5 条")
    c.eq(r["counts"]["items"]["normal"], 3, "正常 3 条（含规则期望的保险丝灯灭）")
    c.eq(r["counts"]["items"]["undetermined"], 2, "未判定 2 条")
    c.eq(r["counts"]["items"]["abnormal"], 0, "这条真实记录没有异常")
    c.eq(r["conclusion"], "normal", "真实样例结论：未发现异常")
    c.eq(r["verdict"], "converged", "真实样例 verdict")
    c.ok(r["session"]["started_at"].startswith("2026-10-18"), "会话时间")
    c.ok(r["session"]["steps_total"] == 127, "steps_total 原样带回")

def t17_contract_and_determinism(c: Check) -> None:
    """契约字段齐全、JSON 可序列化、两次调用结果一致（除 generated_at）。"""
    payload = [
        ev("z15", "(image)(operator_display)_course_scan", "no_scan", 0.9, step_id="s1"),
        ev("z15", "(image)(operator_display)_course_noise", "no_noise", 0.9, step_id="s2"),
        ev("z16", "(led_indicator)_z16_power", "on", 0.9, modality="qa", step_id="s3"),
    ]
    r1 = run(payload)
    r2 = run(payload)
    for k in REQUIRED_KEYS + ("conclusion", "verdict_reason", "page", "text", "converge",
                              "all_candidates", "candidates_total", "conflicts"):
        c.ok(k in r1, f"缺字段 {k}")
    a, b = dict(r1), dict(r2)
    a.pop("generated_at")
    b.pop("generated_at")
    c.eq(json.dumps(a, ensure_ascii=False, sort_keys=True),
         json.dumps(b, ensure_ascii=False, sort_keys=True), "两次汇总必须一致（确定性）")
    json.dumps(r1, ensure_ascii=False)                          
    c.eq(r1["page"]["state"], "summary", "页面 state")
    c.eq([b["action"] for b in r1["page"]["buttons"]], ["summary:back", "summary:again"],
         "页面按钮")
    ids = [x["ev_id"] for x in r1["abnormals"] + r1["normals"] + r1["undetermined"]
           + r1["scope"]]
    c.eq(len(ids), len(set(ids)), "ev_id 不能重复")
    c.ok(all(i.startswith("E") for i in ids), "ev_id 形如 E01")

    for a_ in r1["abnormals"]:
        c.ok(a_["text"], "异常项要有人话")
        c.ok(a_["why"], "异常项要有判定依据")

def t18_cli(c: Check) -> None:
    """CLI（in-process）：打印文案 + 写 summary.json（结构完整）。"""
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "ev.json"
        src.write_text(json.dumps({
            "schema": "evidence/v1", "producer": "test",
            "evidence": [
                ev("z15", "(image)(operator_display)_course_scan", "no_scan", 0.9, step_id="s1"),
                ev("z15", "(image)(operator_display)_course_noise", "no_noise", 0.9,
                   step_id="s2"),
            ]}, ensure_ascii=False), encoding="utf-8")
        out = Path(td) / "summary.json"
        with contextlib.redirect_stdout(io.StringIO()):        
            code = ss.main(["--evidence", str(src), "--out", str(out)])
        c.eq(code, 0, "CLI 退出码")
        c.ok(out.exists(), "CLI 必须写 summary.json")
        data = json.loads(out.read_text(encoding="utf-8"))
        c.eq(data["schema"], ss.SCHEMA, "summary.json schema")
        c.eq(data["verdict"], "converged", "CLI 结果 verdict")
        c.contains(data["text"], "本轮共拍", "summary.json 里的文案")

        sdir = Path(td) / "sessions" / "S_TEST"
        with contextlib.redirect_stdout(io.StringIO()):
            code2 = ss.main(["--evidence", str(src), "--session-dir", str(sdir),
                             "--session-id", "S_TEST", "--quiet"])
        c.eq(code2, 0, "CLI --session-dir 退出码")
        c.ok((sdir / "summary.json").exists(), "session-dir 下应写 summary.json")
        d2 = json.loads((sdir / "summary.json").read_text(encoding="utf-8"))
        c.eq(d2["session"]["id"], "S_TEST", "session id")

def t19_formula_recompute(c: Check) -> None:
    """置信公式可复核：用 score_detail 手算必须与 confidence 一致（误差 <0.002）。"""
    r = run([
        ev("z15", "(image)(operator_display)_display_screen", "yellow_screen", 0.9,
           step_id="s1"),
        ev("z19", "(image)(operator_display)_course_noise", "no_noise", 0.9, step_id="s2"),
        ev("z19", "(image)(operator_display)_course_scan", "no_scan", 0.9, step_id="s3"),
    ])
    top = r["top_faults"][0]
    sd = top["score_detail"]
    for k in ("base", "support_factor", "cross_factor", "evidence_factor",
              "phenomena_explained", "phenomena_total", "formula"):
        c.ok(k in sd, f"score_detail 缺 {k}")
    recomputed = (sd["base"] * sd["support_factor"] * sd["cross_factor"]
                  * sd["evidence_factor"])
    recomputed = min(ss.CONF_CAP, recomputed)
    c.ok(abs(recomputed - top["confidence"]) < 0.002,
         f"公式不可复核：手算 {recomputed:.3f} vs 输出 {top['confidence']}")
    c.eq(sd["phenomena_explained"], top["phenomena_explained"], "现象数一致")
    c.ok(0.0 <= top["confidence"] <= ss.CONF_CAP, "置信在 [0, 0.95]")

    factors = [x["score_detail"]["support_factor"] for x in r["all_candidates"]]
    c.eq(factors, sorted(factors, reverse=True),
         "support_factor 应随现象覆盖度单调不增（候选按覆盖排序）")

SCENARIOS: List[Tuple[str, Callable[[Check], None]]] = [
    ("01 单现象列全候选", t01_single_phenomenon),
    ("02 交叉印证收敛到 1 个", t02_intersection_converges),
    ("03 交集内 2 个分不清 ⇒ partial", t03_intersection_two_close),
    ("04 无交集 ⇒ 不硬凑", t04_no_intersection),
    ("05 全正常", t05_all_normal),
    ("06 单条正常证据不够", t06_single_normal_not_enough),
    ("07 全未判定", t07_all_undetermined),
    ("08 空证据优雅降级", t08_empty),
    ("09 损坏 JSON 优雅降级", t09_corrupt_json),
    ("10 问答优先（视觉冲突）", t10_qa_priority),
    ("11 弱证据不参与收敛", t11_weak_evidence),
    ("12 知识库外现象不给原因", t12_kb_external),
    ("13 2A 保险丝反向语义", t13_reverse_semantics),
    ("14 规则期望（该灭的灯灭）", t14_rule_expectation),
    ("15 去重 + 部位证据归 scope", t15_dedupe_and_scope),
    ("16 真实板端 flow_evidence", t16_real_board_file),
    ("17 契约/确定性/可序列化", t17_contract_and_determinism),
    ("18 CLI 写 summary.json", t18_cli),
    ("19 置信公式可复核", t19_formula_recompute),
]

def main(argv: List[str]) -> int:
    verbose = "-v" in argv or "--verbose" in argv
    print("=" * 78)
    print(f"session_summary 场景测试：{len(SCENARIOS)} 个场景（离线，只读 判据库_故障.csv）")
    print("=" * 78)
    passed = 0
    failed: List[Tuple[str, List[str]]] = []
    total_asserts = 0
    for name, fn in SCENARIOS:
        c = Check(name, verbose)
        try:
            fn(c)
        except Exception:
            c.fails.append("抛异常：\n" + traceback.format_exc(limit=4))
        total_asserts += c.checks
        if c.fails:
            failed.append((name, c.fails))
            print(f"FAIL  {name}  （{len(c.fails)}/{c.checks} 条断言失败）")
            for f in c.fails[:6]:
                print(f"      - {f}")
        else:
            passed += 1
            print(f"PASS  {name}  （{c.checks} 条断言）")
    rate = passed / len(SCENARIOS) * 100
    print("-" * 78)
    print(f"通过率：{passed}/{len(SCENARIOS)} = {rate:.1f}%（断言总数 {total_asserts}）")
    if failed:
        print("失败场景：" + "、".join(n for n, _ in failed))
        return 1
    print("全部通过 ✔（收敛不了的一律 verdict=undetermined，未编造任何原因）")
    return 0

def _force_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")      
        except Exception:                                               
            pass

if __name__ == "__main__":
    _force_utf8_stdout()
    raise SystemExit(main(sys.argv[1:]))
