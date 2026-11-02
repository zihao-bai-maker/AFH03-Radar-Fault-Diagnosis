#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_cause_explainer.py —— ``cause_explainer.py`` 的场景测试（≥8 场景）。

覆盖
----
1. 黄屏（知识库 5 行 abnormal_value + 5 行纯现象）
2. 黑屏（唯一带 feature_id 的显示保险丝）
3. 花屏（知识库只有现象文本，没有 garbled 值）
4. 无回波（abnormal_value=no）
5. 不扫描（知识库连异常值都没有）
6. 无底噪（no_noise，跨部位）
7. **有黄线**（知识库外 ⇒ 必须给「无知识库依据」，不许编原因）
8. 多现象组合（黄屏 + 无底噪；三现象收敛）
9. 正常 / 空输入 / 未知现象 / 未知部位
10. route II（知识库只有 I 路子单元 ⇒ 降权但不丢，且必须提示缺口）
11. z20 控制台（criteria_overrides 的**症状白名单**，不是故障归属）
12. z5 收发机柜（只到柜级 ⇒ need_narrow，不许假装定位）
13. 自检 30 / 弱回波 / 表头 0.00 / 天线方向（其他知识库内现象）
14. 额外证据（evidence/v1）交叉印证加分
15. ``screen_options.json`` 与判据库同步（防过期）+ 穷举清单自洽
16. abnormal_value 全集覆盖（屏幕相关的 8 个值全覆盖）
17. ``to_evidence()`` 产物符合 evidence/v1 契约
18. 显示格式（文案契约）与确定性（两次调用结果一致）

运行
----
::

    python test_cause_explainer.py            # 打印通过率
    python test_cause_explainer.py -v         # 每条断言的细节
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

ENGINE_DIR = Path(__file__).resolve().parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

import cause_explainer as ce  

SCREEN_RELEVANT_AV = {"yellow_screen", "black_screen", "no", "weak", "no_noise",
                      "abnormal", "error", "angle_limit"}
NON_SCREEN_AV = {"off", "on", "no_move", "not_done", "no_sound", "under_voltage",
                 "start_fail", "led_count_less_than_6_on"}

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

def t01_yellow_screen(c: Check) -> None:
    r = ce.explain("z15", ["yellow_screen"], route="I")
    c.eq(r["is_fault"], True, "黄屏应判故障")
    c.ok(len(r["causes"]) >= 5, f"黄屏候选应 ≥5 个（实际 {len(r['causes'])}）")
    for cause in r["causes"]:
        for k in ("cabinet", "sub_unit", "module", "reason", "confidence", "feature_id",
                  "kb_rows", "explains"):
            c.ok(k in cause, f"候选缺字段 {k}")
        c.ok(0.0 <= cause["confidence"] <= 0.97, f"置信越界 {cause['confidence']}")
    c.ok(all(x["cabinet_code"].startswith("Z") for x in r["causes"]), "机柜代号应形如 Z5/Z6")
    c.contains(r["text"], "可能原因（按可能性排序）：", "显示格式")
    c.contains(r["text"], "注：以上为知识库中的候选", "免责注记")

    ev = [e for e in r["evidence_used"] if e["option_id"] == "yellow_screen"][0]
    c.eq(ev["count"], 10, "黄屏应命中 10 行判据")
    c.eq(ev["kb_value"], "yellow_screen", "黄屏的判据库异常值")

def t02_black_screen(c: Check) -> None:
    r = ce.explain("z15", ["black_screen"], route="I")
    c.eq(r["is_fault"], True, "黑屏应判故障")
    top = r["primary"]
    c.ok(top is not None, "黑屏应有 primary")
    if top:
        c.contains(top["module"], "显示保险丝", "黑屏首选应是 Z15 显示保险丝")
        c.eq(top["feature_id"], "F_(image)(operator_display)_display_screen_black_screen",
             "黑屏 feature_id")
        c.ok(top["in_part_scope"], "显示保险丝应属于 z15 自己的判据")
        c.ok(top["confidence"] >= 0.80, f"显示保险丝置信应 ≥0.80（实际 {top['confidence']}）")
    c.ok(any("电源模块" in x["module"] for x in r["causes"]), "应同时列出 Z15 电源模块 220V 候选")

def t03_garbled(c: Check) -> None:
    r = ce.explain("z15", ["garbled"], route="I")
    c.eq(r["is_fault"], True, "花屏应判故障")
    c.ok(len(r["causes"]) >= 2, "花屏应 ≥2 个候选（CPU板 / 图形图像板）")
    mods = " ".join(x["module"] for x in r["causes"])
    c.contains(mods, "CPU板", "花屏候选应含 CPU板（存储卡）")
    c.contains(mods, "图形图像板", "花屏候选应含图形图像板")
    c.ok(all(x["in_part_scope"] for x in r["causes"]), "花屏候选都应在 Z15 自己的判据里")

    inv = {d["value"] for d in ce.abnormal_value_inventory()}
    c.ok("garbled" not in inv, "判据库不应有 garbled 这个 abnormal_value（只能靠现象文本）")

def t04_no_echo(c: Check) -> None:
    r = ce.explain("z11", ["no_echo"], route="I")
    c.eq(r["is_fault"], True, "无回波应判故障")
    c.ok(len(r["causes"]) >= 8, f"无回波候选应 ≥8（实际 {len(r['causes'])}）")
    mods = " ".join(x["module"] for x in r["causes"])
    for want in ("接收前端", "固态功放", "频综"):
        c.contains(mods, want, "无回波候选应覆盖 Z11 模块")
    c.ok(all(x["route_mismatch"] is False for x in r["causes"]), "route=I 时不应有路别不匹配")

def t05_no_scan(c: Check) -> None:
    r = ce.explain("z15", ["no_scan"], route="I")
    c.eq(r["is_fault"], True, "不扫描应判故障")
    mods = " ".join(x["module"] for x in r["causes"])
    for want in ("角码变换板-U1", "角码变换板-U2", "扫描变换板"):
        c.contains(mods, want, "不扫描候选应含 Z15 扫描相关板")
    c.ok(len([x for x in r["causes"] if x["in_part_scope"]]) == 3, "应有 3 个 Z15 自家候选")

def t06_no_noise(c: Check) -> None:
    r = ce.explain("z14", ["no_noise"], route="I")
    c.eq(r["is_fault"], True, "无底噪应判故障")
    c.ok(r["primary"] is not None and r["primary"]["sub_unit_code"] == "Z14",
         "part=z14 时首选应在 Z14")
    c.ok(r["primary"] is not None and r["primary"]["in_part_scope"], "首选应属于本部位判据")
    c.ok(len(r["causes"]) >= 3, "无底噪候选应 ≥3（Z14-10 / Z14-3 / Z19）")
    c.ok(any("Z19" in x["sub_unit"] or "Z19" in x["module"] for x in r["causes"]),
         "应列出 Z19 转接分机（跨部位）")

def t07_yellow_line_kb_external(c: Check) -> None:
    """★ 用户点名的「有黄线」：知识库没有 ⇒ 必须报「无知识库依据」，绝不编原因。"""
    r = ce.explain("z15", ["yellow_line"], route="I")
    c.eq(r["is_fault"], None, "知识库外现象不能判故障")
    c.eq(r["causes"], [], "知识库外现象不能给候选原因")
    c.eq(r["primary"], None, "知识库外现象不能给 primary")
    c.ok(len(r["unknown"]) == 1, "应把有黄线放进 unknown")
    c.contains(r["uncertain_reason"], "知识库", "原因应说明知识库无记录")
    c.contains(r["text"], "知识库无此现象", "显示格式应标注知识库无此现象")

    r2 = ce.explain("z15", ["有黄线"], route="I")
    c.eq(r2["is_fault"], None, "中文「有黄线」同样不判")
    c.ok(any(o["option_id"] == "yellow_line" for o in r["options_used"]) or
         any(u.get("option_id") == "yellow_line" for u in r["unknown"]),
         "输入应被解析成 yellow_line 选项")

def t08_multi_value(c: Check) -> None:
    r = ce.explain("z11", ["yellow_screen", "no_noise"], route="I")
    c.eq(r["is_fault"], True, "黄屏+无底噪应判故障")
    c.ok(r["primary"] is not None and r["primary"]["in_part_scope"], "首选应在本部位（Z11）")
    c.eq(r["primary"]["sub_unit_code"], "Z11", "part=z11 时首选分机应是 Z11")
    covered = [x for x in r["causes"] if x["coverage"]["matched"] == 2]
    c.ok(len(covered) >= 1, "应存在能同时解释 2 个现象的候选（先枚举再精确）")
    c.ok(any(len(x["explains"]) == 2 for x in r["causes"]), "候选的 explains 应能含 2 个现象")
    c.ok("交叉印证" in "".join(r["notes"]), "应提示交叉印证（有候选解释更多现象）")

    r3 = ce.explain("z14", ["yellow_screen", "no_noise", "no_echo"], route="I")
    c.eq(r3["is_fault"], True, "三现象应判故障")
    c.ok(r3["primary"] is not None and r3["primary"]["coverage"]["matched"] >= 2,
         "三现象时首选应至少能解释 2 个现象")
    c.ok(r3["primary"]["confidence"] >= r["primary"]["confidence"],
         "现象越多、解释越全 ⇒ 首选置信不应下降")

def t09_normal_and_edge_cases(c: Check) -> None:
    r = ce.explain("z15", ["normal"], route="I")
    c.eq(r["is_fault"], False, "只给正常 ⇒ 不判故障")
    c.eq(r["causes"], [], "正常不应有候选原因")
    c.contains(r["text"], "未发现", "正常显示格式")

    r = ce.explain("z15", [], route="I")
    c.eq(r["is_fault"], None, "空输入 ⇒ 宁可不判")
    c.contains(r["uncertain_reason"], "现象", "空输入原因")

    r = ce.explain("z15", ["完全不认识的现象xyz"], route="I")
    c.eq(r["is_fault"], None, "未知现象 ⇒ 宁可不判")
    c.ok(len(r["unknown"]) == 1, "未知现象应进 unknown")

    r = ce.explain("z99", ["no_noise"], route="I")
    c.eq(r["is_fault"], True, "部位不认识但现象在知识库里 ⇒ 仍可判现象是故障")
    c.ok(any("不在 18 部位清单" in n for n in r["notes"]), "未知部位应有提示")
    c.ok(r["primary"] is not None and not r["primary"]["in_part_scope"],
         "未知部位没有自家判据 ⇒ 首选只能是跨部位")

    r = ce.explain("z15", ["normal", "black_screen"], route="I")
    c.eq(r["is_fault"], True, "有异常现象就判故障")
    c.contains(r["uncertain_reason"], "矛盾", "矛盾输入应提示复核")

def t10_route_two(c: Check) -> None:
    r = ce.explain("z11", ["yellow_screen"], route="II")
    c.eq(r["is_fault"], True, "route=II 仍应判故障（降权不丢）")
    marked = [x for x in r["causes"] if ce._route_of(x["sub_unit"])]
    c.ok(len(marked) >= 1, "route=II 时仍应保留 I 路子单元候选（不能静默丢弃）")
    c.ok(all(x["route_mismatch"] for x in marked), "I 路子单元在 route=II 时应标 route_mismatch")
    c.ok(all(x["score_detail"]["route_factor"] < 1.0 for x in marked), "路别不匹配应降权")
    c.ok(any("路别提示" in n for n in r["notes"]), "应提示知识库只有 I 路")
    r_i = ce.explain("z11", ["yellow_screen"], route="I")
    c.ok(r_i["primary"]["confidence"] > r["primary"]["confidence"],
         "同一现象 route=I 的置信应高于 route=II（降权生效）")

def t11_z20_symptom_scope(c: Check) -> None:
    r = ce.explain("z20", ["off"], route="")
    c.ok(r["is_fault"] is True, "z20 + 灯灭应能判")
    c.ok(all(x["cabinet_code"] != "Z20" for x in r["causes"]), "z20 的候选绝不能写成 Z20 自身故障")
    c.ok(any(x.get("in_symptom_scope") for x in r["causes"]), "应标出症状白名单命中的候选")
    c.ok(all(not x["in_part_scope"] for x in r["causes"]),
         "owner_policy=do_not_treat_as_owner ⇒ 不算 z20 自己的判据")
    c.contains(r["text"], "症状行", "显示格式应说明这是症状行")
    pol = r["part_scope"]["override"]
    c.ok(bool(pol), "z20 应读取 criteria_overrides.json")

def t12_z5_need_narrow(c: Check) -> None:
    r = ce.explain("z5", ["yellow_screen"], route="I")
    c.eq(r["is_fault"], True, "只到 Z5 柜也要按现象给候选")
    c.ok(r["part_scope"]["need_narrow"], "z5 未定位到分机/模块 ⇒ need_narrow 必须为 True")
    c.ok(any("不能假装已定位" in n or "没有分机/模块" in n for n in r["notes"]),
         "应提示不能假装已定位")
    c.ok(any(x["in_part_scope"] for x in r["causes"]), "Z5 柜内候选应算 in_part_scope")
    c.eq(r["part_scope"]["criteria_rows"], 63, "Z5 的判据行应为 63 行（allow_rows 白名单）")

    r2 = ce.explain("z11-1", ["yellow_screen"], route="I")
    c.eq(r2["part_scope"]["criteria_rows"], 18, "z11-1 应被 module_z11_1 收窄到 18 行")
    c.ok(r2["primary"] is not None and r2["primary"]["in_part_scope"], "z11-1 首选应在本部位")

def t13_other_kb_phenomena(c: Check) -> None:
    r = ce.explain("z15", ["自检30"], route="I")
    c.eq(r["is_fault"], True, "自检30 应判故障")
    c.eq(len(r["causes"]), 1, "自检30 只有 1 行判据")
    c.contains(r["causes"][0]["module"], "扫描变换板", "自检30 → 扫描变换板")

    r = ce.explain("z15", ["自检40"], route="I")
    c.contains(r["causes"][0]["module"], "检测获取板", "自检40 → 检测获取板")

    r = ce.explain("z11", ["weak"], route="I")
    c.eq(r["is_fault"], True, "弱回波应判故障")
    c.contains(r["causes"][0]["module"], "近程增益", "weak → Z11-5 近程增益")

    r = ce.explain("z12", ["表头异常"], route="I")
    c.eq(len(r["causes"]), 3, "表头 0.00 应有 3 个 Z12 电源模块候选")
    c.ok(all(x["sub_unit_code"] == "Z12" for x in r["causes"]), "表头候选应全在 Z12")

    r = ce.explain("z18", ["天线方向"], route="I")
    c.eq(r["is_fault"], True, "天线方向错误应判故障")
    c.ok(all(x["sub_unit_code"] == "Z18" for x in r["causes"]), "天线方向候选应全在 Z18")

def t14_evidence_bonus(c: Check) -> None:
    base = ce.explain("z15", ["black_screen"], route="I")
    ev = [{"field": "(image)(operator_display)_display_screen", "value": "black_screen",
           "confidence": 0.93, "modality": "vision"}]
    boosted = ce.explain("z15", ["black_screen"], route="I", evidence=ev)
    c.eq(len(boosted["extra_evidence"]), 1, "证据应被记录")
    c.eq(boosted["extra_evidence"][0]["matched_rows"], [89], "证据应命中判据库第 89 行")
    c.ok(boosted["primary"]["confidence"] >= base["primary"]["confidence"],
         "交叉证据不应降低置信")
    c.ok(boosted["primary"]["score_detail"]["evidence_bonus"] > 0, "应体现证据加分")

    bad = ce.explain("z15", ["black_screen"], route="I",
                     evidence=[{"field": "(led_indicator)_not_exist", "value": "off"}])
    c.ok(bad["primary"]["score_detail"]["evidence_bonus"] == 0, "假证据不能加分")
    c.contains(bad["extra_evidence"][0]["note"], "不存在", "假证据应注明不存在")

def t15_options_sync(c: Check) -> None:
    p = ce.OPTIONS_JSON
    c.ok(p.exists(), f"{p.name} 应存在（可用 --write-options 生成）")
    if not p.exists():
        return
    res = ce.check_screen_options()
    c.ok(res["ok"], f"screen_options.json 应与判据库同步（{res.get('reason')}）")
    data = json.loads(p.read_text(encoding="utf-8"))
    c.eq(data["schema"], ce.OPTIONS_SCHEMA, "schema")
    opts = data["options"]
    c.eq(len(opts), 31, "屏幕现象清单应为 31 项")
    c.eq(sum(1 for o in opts if o["in_kb"]), 17, "in_kb=true 应为 17 项")
    c.eq(sum(1 for o in opts if not o["in_kb"]), 14, "知识库外应为 14 项")
    c.eq(sum(1 for o in opts if o["user_dictated"]), 13, "用户口述应为 13 项")
    c.eq(sum(1 for o in opts if not o["in_kb"] and o["in_sop"]), 1, "仅 SOP 应为 1 项")
    ids = [o["id"] for o in opts]
    c.eq(len(ids), len(set(ids)), "选项 id 不能重复")
    c.ok(len({o["value"] for o in opts}) == len(opts), "选项 value 不能重复")

    for must in ("normal", "black_screen", "yellow_screen", "garbled", "no_echo", "no_scan",
                 "no_noise", "weak_echo", "yellow_line", "flicker", "too_bright", "too_dim",
                 "missing_rows", "snow_excess", "char_garbled", "screen_freeze", "echo_partial",
                 "selftest_30", "selftest_40", "meter_zero", "meter_direction", "guidance_stuck"):
        c.contains(ids, must, "清单应包含")

    for o in opts:
        if not o["in_kb"]:
            c.eq(o["possible_causes"], [], f"{o['id']} 是知识库外选项，不能编候选原因")
            c.ok(bool(o["nearest_kb_hint"]), f"{o['id']} 应给出「为什么没有原因」的说明")
        else:
            c.ok(o["kb_basis"] in ("abnormal_value", "phenomenon", "sop_check_item"),
                 f"{o['id']} kb_basis 非法")

    for o in opts:
        if o["in_kb"] and o["id"] not in ("normal", "noise_present"):
            c.ok(o["kb_row_count"] > 0, f"{o['id']} 标注 in_kb 但 0 行命中（in_kb 可能写错）")

    yl = [o for o in opts if o["id"] == "yellow_line"][0]
    c.eq(yl["in_kb"], False, "有黄线必须标 in_kb=false")
    c.eq(yl["user_dictated"], True, "有黄线应标用户口述")

    for o in opts:
        c.ok(isinstance(o["vision_hintable"], bool) and isinstance(o["vision_supported"], bool),
             f"{o['id']} 视觉标注应为 bool")
        if o["vision_supported"]:
            c.ok(o["vision_state"], f"{o['id']} 声称视觉可判就必须给 vision_state")

def t16_abnormal_value_inventory(c: Check) -> None:
    inv = ce.abnormal_value_inventory()
    c.eq(len(inv), 16, "判据库 abnormal_value 应为 16 个非空值")
    values = {d["value"] for d in inv}
    c.eq(sum(d["rows"] for d in inv), 99, "有异常值的行应为 99 行（268 - 169 纯现象行）")
    c.ok(SCREEN_RELEVANT_AV <= values, f"屏幕相关的值缺：{SCREEN_RELEVANT_AV - values}")
    data = json.loads(ce.OPTIONS_JSON.read_text(encoding="utf-8"))
    uncovered = {d["value"] for d in data["abnormal_value_uncovered"]}
    c.ok(uncovered <= NON_SCREEN_AV,
         f"未覆盖的值应全是非屏幕类，实际还漏了：{uncovered - NON_SCREEN_AV}")
    for d in data["abnormal_value_inventory"]:
        c.ok(d["rows"] == len(d["row_numbers"]), f"{d['value']} 行数应等于行号列表长度")

def t17_to_evidence(c: Check) -> None:
    r = ce.explain("z15", ["black_screen"], route="I")
    evs = ce.to_evidence(r)
    c.ok(len(evs) >= 1, "应能转成 evidence/v1")
    need = ("part", "route", "modality", "field", "value", "confidence", "evidence", "ts")
    for e in evs:
        for k in need:
            c.ok(k in e, f"evidence 缺字段 {k}")
        c.ok(e["modality"] in ("vision", "qa", "scope", "audio"), "modality 非法")
        c.eq(e["route"], "I", "route 应原样带过去")
        c.ok(e["field"] and "\n" not in e["field"], "field 不能为空/含换行")
        c.ok(0.0 <= e["confidence"] <= 1.0, "confidence 越界")

    c.ok(any(e["meta"]["kb_row"] == 89 for e in evs), "应带出判据库行号")

def t18_text_and_determinism(c: Check) -> None:
    r1 = ce.explain("z11", ["yellow_screen", "no_noise"], route="I")
    r2 = ce.explain("z11", ["yellow_screen", "no_noise"], route="I")
    c.eq([(x["module"], x["confidence"]) for x in r1["causes"]],
         [(x["module"], x["confidence"]) for x in r2["causes"]], "两次调用结果应一致")
    c.eq(r1["text"], r2["text"], "显示文本应一致")
    t = r1["text"]
    c.contains(t, "存在故障", "故障头")
    c.contains(t, "可能原因（按可能性排序）：", "候选标题")
    c.contains(t, "置信 0.", "置信显示")
    c.contains(t, "注：以上为知识库中的候选，需结合其它现象进一步确认", "免责注记")
    c.ok("①" in t, "应使用 ①②③ 编号")

    confs = [x["confidence"] for x in r1["causes"]]
    c.eq(confs, sorted(confs, reverse=True), "候选必须按置信降序")
    c.eq([x["rank"] for x in r1["causes"]], list(range(1, len(r1["causes"]) + 1)), "rank 应连续")

    c.eq(r1["causes_total"], len(r1["causes"]), "causes_total 应等于列表长度")

    if len(r1["causes"]) > 10:
        c.contains(t, "其余见 JSON", "超过 10 条应提示见 JSON")

def t19_confidence_breakdown(c: Check) -> None:
    r = ce.explain("z15", ["black_screen"], route="I")
    top = r["primary"]
    sd = top["score_detail"]
    for k in ("base", "coverage_factor", "specificity", "part_factor", "route_factor",
              "field_bonus", "evidence_bonus", "formula"):
        c.ok(k in sd, f"score_detail 缺 {k}")
    recomputed = (sd["base"] * sd["coverage_factor"] * sd["specificity"] * sd["part_factor"]
                  * sd["route_factor"] + sd["field_bonus"] + sd["evidence_bonus"])
    c.ok(abs(min(0.97, recomputed) - top["confidence"]) < 0.002,
         f"置信公式不可复核：{recomputed:.3f} vs {top['confidence']}")
    c.eq(sd["part_factor"], 1.0, "本部位候选 part_factor 应为 1.0")
    c.ok(sd["specificity"] <= 1.0 and sd["specificity"] >= 0.75, "特异性因子应在 [0.75, 1.0]")

def t20_crosswalk_and_disambiguation(c: Check) -> None:
    """与另一 agent 的 ``qa_items_screen.json`` 对齐：只读、不写、歧义值用 field 消歧。"""
    qa = ENGINE_DIR / "qa_items_screen.json"
    if not qa.exists():
        c.ok(True, "qa_items_screen.json 不存在 —— 跳过（本文件不新建）")
        return
    before = qa.read_bytes()
    cw = ce.crosswalk_qa_items_screen()
    c.ok(cw["ok"], f"对方选项应全部有对照（unmapped={cw['unmapped_theirs']}）")
    c.eq(cw["items"], 15, "qa_items_screen 应有 15 题")
    for their in ("normal", "black_screen", "yellow_screen", "garbled", "no", "weak",
                  "no_noise", "abnormal", "skipped"):
        c.contains(cw["their_option_ids"], their, "对方选项")
        c.contains(list(cw["mapping"]), their, "对照表应覆盖对方选项")

    r = ce.explain("z15", ["no"], field="(image)(operator_display)_course_scan")
    c.contains(" ".join(x["module"] for x in r["causes"]), "扫描变换板", "扫描题的 no 应走 no_scan")
    c.ok(all("no_scan" in [e["option_id"] for e in x["explains"]] for x in r["causes"]),
         "扫描题的候选都应来自 no_scan 匹配")

    r = ce.explain("z11", ["no"], field="(image)(operator_display)_course_echo")
    mods = " ".join(x["module"] for x in r["causes"])
    c.contains(mods, "频综", "回波题的 no 应走 no_echo")
    c.ok("扫描变换板" not in mods, "回波题不能串到扫描板")

    r = ce.explain("z15", ["abnormal"], field="(image)(operator_display)_course_line")
    c.eq(r["is_fault"], None, "理想线 abnormal 在知识库无对应行")
    c.eq(r["causes"], [], "理想线 abnormal 不能给候选")
    c.ok(any(u.get("option_id") == "no_guidance_line" for u in r["unknown"]),
         "应落到 no_guidance_line（仅 SOP）")

    r = ce.explain("z12", ["abnormal"])
    c.eq(len(r["causes"]), 3, "不带 field 时 abnormal 走判据库 abnormal（3 行 Z12）")
    c.ok(any("歧义" in n for n in r["notes"]), "不带 field 应提示 no/abnormal 有歧义")

    r = ce.explain("z15", ["skipped"])
    c.eq(r["is_fault"], None, "skipped 不能判故障")
    c.eq(r["skipped_values"], ["skipped"], "应记录 skipped_values")
    c.contains(r["uncertain_reason"], "跳过", "skipped 原因")

    c.eq(qa.read_bytes(), before, "绝不能改写别人的 qa_items_screen.json")

SCENARIOS: List[Tuple[str, Callable[[Check], None]]] = [
    ("01 黄屏（知识库 10 行）", t01_yellow_screen),
    ("02 黑屏（显示保险丝）", t02_black_screen),
    ("03 花屏（只有现象文本）", t03_garbled),
    ("04 无回波（abnormal_value=no）", t04_no_echo),
    ("05 不扫描（无异常值）", t05_no_scan),
    ("06 无底噪（跨部位）", t06_no_noise),
    ("07 有黄线（知识库外，不许编）", t07_yellow_line_kb_external),
    ("08 多现象组合（先枚举再精确）", t08_multi_value),
    ("09 正常 / 空输入 / 未知 / 矛盾", t09_normal_and_edge_cases),
    ("10 route II（降权不丢）", t10_route_two),
    ("11 z20 症状白名单", t11_z20_symptom_scope),
    ("12 z5 柜级 need_narrow", t12_z5_need_narrow),
    ("13 自检30/40、弱回波、表头、方向", t13_other_kb_phenomena),
    ("14 额外证据交叉印证", t14_evidence_bonus),
    ("15 screen_options.json 同步与自洽", t15_options_sync),
    ("16 abnormal_value 全集覆盖", t16_abnormal_value_inventory),
    ("17 to_evidence 符合 evidence/v1", t17_to_evidence),
    ("18 显示格式与确定性", t18_text_and_determinism),
    ("19 置信公式可复核", t19_confidence_breakdown),
    ("20 与 qa_items_screen.json 对齐（只读）", t20_crosswalk_and_disambiguation),
]

def main(argv: List[str]) -> int:
    verbose = "-v" in argv or "--verbose" in argv
    print("=" * 78)
    print(f"cause_explainer 场景测试：{len(SCENARIOS)} 个场景（离线，只读 判据库_故障.csv）")
    print("=" * 78)
    passed = 0
    failed: List[Tuple[str, List[str]]] = []
    total_asserts = 0
    for name, fn in SCENARIOS:
        c = Check(name, verbose)
        try:
            fn(c)
        except Exception:
            c.fails.append("抛异常：\n" + traceback.format_exc(limit=3))
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
    print("全部通过 ✔（知识库外现象一律标「无依据」，未编造任何原因）")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
