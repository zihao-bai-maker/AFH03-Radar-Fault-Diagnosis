#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_steps.py —— 从判据库生成「SOP 步骤流」steps.json（只新建文件，不改任何既有模块）。

分组口径
--------
* 按 **(flow_no, sub_no)** 分组，一个分组 = 一个步骤（用户 2026-10-18 明确要求）。
* 源表里 sub_no 为空的 29 行（flow 21/23/24/25/26/27/28）按原表合并成 7 步；
  想"一行一步"就加 `--split-blank`（生成的 step_id 形如 `23-r1`）。

每一步包含
----------
    step_id / step_name / flow_no / flow_name / sub_no / part / route
    vision_items   method=摄像头拍摄        （61 项）
    qa_items       method=交互问答确认      （60 项，引用 qa_items.json 的 qa_id）
    scope_items    method=采集示波器输出数据（28 项，引用 scope_items_lan.json）
    audio_items    method=麦克风采集声音    （5 项，disabled=True：当前 UI 不启用）
    unclassified_items  method 为空的 12 行（不猜采集方式，如实标出）

part / route 取值优先级
-----------------------
    问答项 > 流程部位映射（scope_items.json 的 part_map：22/27→z14，23/28→z11）
    > 示波器项 > 声音项 > check_item/flow_name 里的 Z 编号
    > 「(操显)/(领显)」显示类 ⇒ z4
part_origin 记录来源；不同来源给出不同 part 时写进 part_conflict（不静默）。

用法
----
    python build_steps.py                 # 生成 steps.json（默认口径）
    python build_steps.py --split-blank   # 空白 sub_no 一行一步
    python build_steps.py --check         # 只校验已有 steps.json 与源表一致（不写文件）
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

CSV_PATH = os.path.join(ROOT, "判据库_SOP.csv")
QA_PATH = os.path.join(HERE, "qa_items.json")
SCOPE_PATH = os.path.join(HERE, "scope_items_lan.json")
SCOPE_OLD_PATH = os.path.join(HERE, "scope_items.json")   
AUDIO_PATH = os.path.join(HERE, "audio_items.json")
OUT_PATH = os.path.join(HERE, "steps.json")

METHOD_VISION = "摄像头拍摄"
METHOD_QA = "交互问答确认"
METHOD_SCOPE = "采集示波器输出数据"
METHOD_AUDIO = "麦克风采集声音"

MOD_LABEL = {"vision": "拍照", "qa": "问答", "scope": "波形", "audio": "声音",
             "none": "待定"}
PART_PRIORITY = ("qa", "flow_map", "scope", "audio", "text_z", "text_display")

def _read_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def _norm_sub(v) -> str:
    """sub_no 统一成去空白字符串（CSV 里是 '1'，json 里可能是 1）。"""
    if v is None:
        return ""
    return str(v).strip()

def _norm_flow(v) -> str:
    return str(v).strip()

def _norm_text(v) -> str:
    """比较 check_item 用：去掉所有空白（源表里有换行，qa_items 里没有）。"""
    return re.sub(r"\s+", "", str(v or ""))

def _norm_part(v) -> str:
    return str(v or "").strip().lower()

def _part_from_text(*texts: str) -> str:
    for t in texts:
        m = re.search(r"[Zz]\s*(\d{2})", t or "")
        if m:
            return "z" + m.group(1)
    return ""

def _part_from_display(*texts: str) -> str:
    """问答引擎的既有口径：操显/领显 的画面、内控/外控等 → z4（显示控制）。"""
    for t in texts:
        if re.search(r"[（(]\s*[操领]\s*显\s*[)）]", t or ""):
            return "z4"
    return ""

def _route_from_text(*texts: str) -> str:
    for t in texts:
        t = t or ""
        if re.search(r"[（(]\s*II\s*[)）]", t):
            return "II"
        if re.search(r"[（(]\s*I\s*[)）]", t):
            return "I"
    return ""

def _evidence_field_from_refs(refs) -> str:
    """fault_refs（'F_(led_indicator)_x|F_(image)...'）→ 证据 field（去 F_ 前缀）。"""
    if not refs:
        return ""
    first = str(refs).split("|")[0].strip()
    if first.startswith("F_"):
        first = first[2:]
    return first

def _compact_options(opts) -> list:
    out = []
    for o in opts or []:
        out.append({k: o.get(k) for k in
                    ("value", "label_plain", "label", "tone", "style",
                     "feature_id", "feature_source")
                    if o.get(k) is not None})
    return out

def _compact_skip(skip_if) -> dict:
    if not skip_if:
        return {}
    rules = []
    for r in skip_if.get("rules") or []:
        rules.append({k: r.get(k) for k in ("qa_id", "flow_no", "check_item", "values", "reason")
                      if r.get(k) is not None})
    return {"mode": skip_if.get("mode", "any"), "rules": rules,
            "reason": skip_if.get("reason", "")}

def _load_flow_part_map() -> dict:
    """scope_items.json 的 part_map：flow 22/27→z14（信处），23/28→z11（收发）。只读。"""
    out = {}
    try:
        doc = _read_json(SCOPE_OLD_PATH)
        for part, info in (doc.get("part_map") or {}).items():
            for fn in (info or {}).get("flows") or []:
                out[_norm_flow(fn)] = _norm_part(part)
    except Exception:                                                
        pass
    for fn, part in (("22", "z14"), ("27", "z14"), ("23", "z11"), ("28", "z11")):
        out.setdefault(fn, part)
    return out

def _majority(vals):
    vals = [v for v in vals if v]
    if not vals:
        return ""
    return collections.Counter(vals).most_common(1)[0][0]

def build(split_blank: bool = False) -> dict:
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    qa_doc = _read_json(QA_PATH)
    qa_items = qa_doc.get("items") or []
    scope_doc = _read_json(SCOPE_PATH)
    scope_items = scope_doc.get("items") or []
    audio_doc = _read_json(AUDIO_PATH)
    audio_items = audio_doc.get("items") or []
    flow_part_map = _load_flow_part_map()

    qa_idx = collections.defaultdict(list)
    for x in qa_items:
        qa_idx[(_norm_flow(x.get("flow_no")), _norm_sub(x.get("sub_no")))].append(x)
    scope_idx = collections.defaultdict(list)
    for x in scope_items:
        scope_idx[(_norm_flow(x.get("flow_no")), _norm_sub(x.get("sub_no")))].append(x)
    audio_idx = collections.defaultdict(list)
    for x in audio_items:
        audio_idx[(_norm_flow(x.get("flow_no")), _norm_sub(x.get("sub_no")))].append(x)

    groups = collections.OrderedDict()
    for r in rows:
        key = (_norm_flow(r.get("flow_no")), _norm_sub(r.get("sub_no")))
        groups.setdefault(key, []).append(r)

    if split_blank:
        expanded = collections.OrderedDict()
        for (fn, sn), sub in groups.items():
            if sn:
                expanded[(fn, sn)] = sub
            else:
                for i, r in enumerate(sub, 1):
                    expanded[(fn, "r%d" % i)] = [r]
        groups = expanded

    steps = []
    for (flow_no, sub_no), sub_rows in groups.items():
        first = sub_rows[0]
        flow_name = first.get("flow_name", "")
        step_id = "%s-%s" % (flow_no, sub_no) if sub_no else flow_no
        qa_list = qa_idx.get((flow_no, sub_no), [])
        sc_list = scope_idx.get((flow_no, sub_no), [])
        au_list = audio_idx.get((flow_no, sub_no), [])
        qa_texts = {_norm_text(q.get("check_item")) for q in qa_list}

        vision_items, unclassified = [], []
        for r in sub_rows:
            method = (r.get("method") or "").strip()
            refs = (r.get("fault_refs") or "").strip()
            base = {
                "check_item": (r.get("check_item") or "").strip(),
                "category": (r.get("category") or "").strip(),
                "subject": (r.get("subject") or "").strip(),
                "need_qa": (r.get("need_qa") or "").strip(),
                "fault_refs": [x for x in refs.split("|") if x.strip()] if refs else [],
                "method": method,
            }
            if method == METHOD_VISION:
                ef = _evidence_field_from_refs(refs)
                base["evidence_field"] = ef or ("(vision)_step_%s"
                                                % re.sub(r"[^0-9A-Za-z]+", "_", step_id))
                base["field_source"] = "fault_refs" if ef else "synthesized"
                vision_items.append(base)
            elif method == METHOD_QA:

                if not qa_list:
                    base["qa_missing"] = True
                    unclassified.append(base)
                elif _norm_text(base["check_item"]) not in qa_texts:
                    base["qa_text_mismatch"] = True   
            elif method in (METHOD_SCOPE, METHOD_AUDIO):
                pass  
            else:
                unclassified.append(base)

        by_origin = collections.defaultdict(list)
        for x in qa_list:
            by_origin["qa"].append((_norm_part(x.get("part")),
                                    (x.get("route") or "").strip()))
        fm = flow_part_map.get(flow_no, "")
        if fm:
            by_origin["flow_map"].append((fm, ""))
        for x in sc_list:
            by_origin["scope"].append((_norm_part(x.get("part")),
                                       (x.get("route") or "").strip()))
        for x in au_list:
            by_origin["audio"].append((_norm_part(x.get("part")),
                                       (x.get("route") or "").strip()))
        text_z = _part_from_text(first.get("check_item", ""), first.get("flow_name", ""),
                                 *(r.get("subject", "") for r in sub_rows))
        text_route = _route_from_text(first.get("check_item", ""), first.get("flow_name", ""))
        by_origin["text_z"].append((text_z, text_route))
        by_origin["text_display"].append((_part_from_display(
            *(r.get("check_item", "") for r in sub_rows)), text_route))

        part, route, part_origin = "", "", ""
        for origin in PART_PRIORITY:
            cand = by_origin.get(origin) or []
            ps = [p for p, _rt in cand]
            rts = [rt for _p, rt in cand]
            if not part and _majority(ps):
                part, part_origin = _majority(ps), origin
            if not route and _majority(rts):
                route = _majority(rts)
        all_parts = {p for vals in by_origin.values() for p, _rt in vals if p}
        conflict = sorted(all_parts - {part}) if part else sorted(all_parts)

        step_qa = []
        for q in qa_list:
            step_qa.append({
                "qa_id": q.get("qa_id"),
                "seq": q.get("seq"),
                "check_item": q.get("check_item"),
                "question": q.get("question"),
                "normal": q.get("normal"),
                "part": _norm_part(q.get("part")),
                "route": (q.get("route") or "").strip(),
                "evidence_field": q.get("evidence_field"),
                "options": _compact_options(q.get("options")),
                "skip_if": _compact_skip(q.get("skip_if")),
                "category": q.get("category"),
                "subject": q.get("subject"),
            })

        step_scope = []
        for x in sc_list:
            step_scope.append({
                "idx": x.get("idx"),
                "field": x.get("field"),
                "signal": x.get("signal"),
                "check_item": x.get("check_item"),
                "judge_mode": x.get("judge_mode"),
                "expect_freq_hz": x.get("expect_freq_hz"),
                "tol_pct": x.get("tol_pct"),
                "params": x.get("params"),
                "part": _norm_part(x.get("part")),
                "route": (x.get("route") or "").strip(),
                "note": x.get("note") or "",
            })

        step_audio = []
        for x in au_list:
            step_audio.append({
                "item_id": x.get("item_id"),
                "field": x.get("field"),
                "check_item": x.get("check_item"),
                "component": x.get("component"),
                "expect": x.get("expect"),
                "abnormal": x.get("abnormal"),
                "capture_window_s": x.get("capture_window_s"),
                "trigger_hint": x.get("trigger_hint"),
                "part": _norm_part(x.get("part")),
                "route": (x.get("route") or "").strip(),
                "disabled": True,
            })

        mods = []
        if vision_items:
            mods.append("vision")
        if step_qa:
            mods.append("qa")
        if step_scope:
            mods.append("scope")
        if step_audio:
            mods.append("audio")
        if not mods:
            mods = ["none"]

        if len(sub_rows) == 1:
            step_name = (sub_rows[0].get("check_item") or "").strip()
        elif sub_no and not sub_no.startswith("r"):
            step_name = (first.get("check_item") or "").strip()
        else:

            step_name = "%s（本步 %d 项）" % ((first.get("check_item") or "").strip(),
                                             len(sub_rows))

        steps.append({
            "seq": len(steps) + 1,
            "step_id": step_id,
            "flow_no": flow_no,
            "flow_name": flow_name,
            "sub_no": "" if sub_no.startswith("r") else sub_no,
            "step_name": step_name,
            "part": part,
            "route": route,
            "part_origin": part_origin,
            "part_conflict": conflict,
            "modalities": mods,
            "method_text": " + ".join(MOD_LABEL[m] for m in mods),
            "vision_items": vision_items,
            "qa_items": step_qa,
            "scope_items": step_scope,
            "audio_items": step_audio,
            "unclassified_items": unclassified,
        })

    by_type = collections.Counter()
    for s in steps:
        by_type["+".join(MOD_LABEL[m] for m in s["modalities"])] += 1
    by_method = collections.Counter((r.get("method") or "").strip() for r in rows)
    item_counts = {
        "vision": sum(len(s["vision_items"]) for s in steps),
        "qa": sum(len(s["qa_items"]) for s in steps),
        "scope": sum(len(s["scope_items"]) for s in steps),
        "audio": sum(len(s["audio_items"]) for s in steps),
        "unclassified": sum(len(s["unclassified_items"]) for s in steps),
    }

    doc = {
        "schema": "steps/v1",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "generated_by": "build_steps.py",
        "source": {
            "csv": os.path.basename(CSV_PATH),
            "qa": os.path.basename(QA_PATH),
            "scope": os.path.basename(SCOPE_PATH),
            "audio": os.path.basename(AUDIO_PATH),
            "flow_part_map": os.path.basename(SCOPE_OLD_PATH) + "#part_map",
        },
        "policy": {
            "group_by": ["flow_no", "sub_no"],
            "split_blank": bool(split_blank),
            "step_name_rule": "单行步=check_item；有 sub_no 的多行步=首行 check_item；空白 sub_no 合并步=首项（本步 N 项）",
            "part_rule": "问答项 > 流程部位映射(22/27→z14,23/28→z11) > 示波器项 > 声音项 > 文本 Z 编号 > (操显)/(领显)→z4",
            "route_rule": "示波器/问答/声音项优先，其次（I）/（II）文本",
            "qa_ref": "qa_items.json 的 qa_id",
            "audio_enabled": False,
        },
        "counts": {
            "steps_total": len(steps),
            "flows": len({s["flow_no"] for s in steps}),
            "csv_rows": len(rows),
            "by_type": dict(by_type),
            "by_method": {k or "(空)": v for k, v in by_method.items()},
            "item_counts": item_counts,
            "steps_with_qa": sum(1 for s in steps if s["qa_items"]),
            "steps_with_vision": sum(1 for s in steps if s["vision_items"]),
            "steps_with_scope": sum(1 for s in steps if s["scope_items"]),
            "steps_with_audio": sum(1 for s in steps if s["audio_items"]),
            "steps_with_unclassified": sum(1 for s in steps if s["unclassified_items"]),
            "steps_by_flow": dict(collections.Counter(s["flow_no"] for s in steps)),
        },
        "steps": steps,
    }
    return doc

def _stats_text(doc: dict) -> str:
    c = doc["counts"]
    lines = [
        "steps.json: %d 步 / %d 个 flow / 源表 %d 行" % (c["steps_total"], c["flows"], c["csv_rows"]),
        "  分类型：" + "；".join("%s=%d" % (k, v) for k, v in c["by_type"].items()),
        "  分采集：" + "；".join("%s=%d" % (k, v) for k, v in c["by_method"].items()),
        "  项数：拍照 %d / 问答 %d / 波形 %d / 声音 %d / 待定 %d"
        % (c["item_counts"]["vision"], c["item_counts"]["qa"], c["item_counts"]["scope"],
           c["item_counts"]["audio"], c["item_counts"]["unclassified"]),
        "  含问答的步 %d；含拍照的步 %d；含波形的步 %d；声音步 %d；待定步 %d"
        % (c["steps_with_qa"], c["steps_with_vision"], c["steps_with_scope"],
           c["steps_with_audio"], c["steps_with_unclassified"]),
    ]
    return "\n".join(lines)

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="判据库 -> SOP 步骤流 steps.json")
    ap.add_argument("--split-blank", action="store_true",
                    help="sub_no 为空的行各算一步（默认按原表合并）")
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    ap.add_argument("-o", "--out", default=OUT_PATH)
    a = ap.parse_args(argv)
    doc = build(split_blank=bool(a.split_blank))
    print(_stats_text(doc))
    if a.check:
        if not os.path.isfile(a.out):
            print("[check] 缺少 %s" % a.out)
            return 2
        old = _read_json(a.out)
        same = (json.dumps(old.get("steps"), ensure_ascii=False, sort_keys=True) ==
                json.dumps(doc["steps"], ensure_ascii=False, sort_keys=True))
        if not same:
            print("[check] steps 内容与源表不一致（重新生成即可）")
            return 3
        print("[check] OK：steps 与源表一致（%d 步）" % len(doc["steps"]))
        return 0
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, a.out)
    print("已写出 %s（%d 字节）" % (a.out, os.path.getsize(a.out)))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
