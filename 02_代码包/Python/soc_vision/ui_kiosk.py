#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ui_kiosk.py —— 用户草图版 UI（**两页**，版式由 `config/ui_layout.json` 驱动）。

流程（用户确认）
----------------
```
页面1「故障检测」 = 相机**实时画面** + 底部【拍照】【波形检测】
        │ 按【拍照】
        ▼
页面2「故障或者正常」 = 刚拍的**静止照片** + **醒目结论**（绿=正常 / 红=故障 / 灰=未判定）
                     + **依据**（哪颗灯不亮 / 哪项不满足 / 实际值 vs 允许范围）+ 【返回】
```
* 版式/文案/颜色/按钮全部来自 `config/ui_layout.json` → **以后加功能按钮不用改代码**
* 中文一律走 `soc_vision.cjk_text`（**绝不乱码**）
* **出帧**：优先 OpenCV `VideoCapture`（实测独占设备时 0.08 s 就出帧）；连续失败会自动重开设备，
  仍失败则**明确提示"取流失败"**并给出自 poll 命令（不静默）
* 拍照 → 存 `/userdata/afh03_shots/<时间戳>/{full.jpg, annot.jpg, verdict.json}`

用法
----
    python3 -m soc_vision.ui_kiosk --part PS_KONG --calib config/led_calib.json      # 板端实时
    python3 -m soc_vision.ui_kiosk --part PS_KONG --auto                             # 无标定演示
    python3 -m soc_vision.ui_kiosk --render page1 --frame f.jpg --out out/ui_page1.png
    python3 -m soc_vision.ui_kiosk --render page2 --frame f.jpg --part PS_KONG --auto --out out/ui_page2.png

2026-10-22（本轮总结接板）
-------------------------
* 流程页顶栏右上新增【总结】按钮（`flow:summary`，键盘 `t`）→ `state="summary"`；
* `draw_summary()` 只渲染 `session_summary.summarize()` 的 `page.lines`（+ `top_faults` 着色），
  页面文案与 PC 验收**同一来源**；`summary:back` 回流程、`summary:again` 清空本轮证据回第 1 步；
* 落盘 `/userdata/afh03_shots/sessions/<id>/{session,evidence,summary}.json + summary.txt`（原子写）；
* `import session_summary` 失败 / `summarize()` 抛异常 ⇒ 页面显示「⚠ 总结模块不可用」，**UI 不崩**。

2026-10-27（双总结功能）
------------------------
* 主页底排按钮上方新增【总结】（`summary_all`，键盘 `s`）→ `state="summary_all"`：
  「拍照 + 波形」四块（盘点 / 问题 / 故障范围 / 未解释），数据来自 `flow["evidence"]`
  + 本轮落盘的 `flow_evidence_*.json` + `/userdata/scope_result.json`；
* 推理**只调** `session_summary.summarize()`：候选的 `kb_rows` / `support` 原样显示，
  库里没有的现象写「库中无此项」，绝不编原因；空数据 / 异常都只降级，UI 不崩；
* 流程页原【总结】保留，标题改为「流程检测总结」以区分两个总结页。
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                                    
import cv2                                                            

try:
    from PIL import Image as _PILImage, ImageDraw as _PILImageDraw, ImageFont as _PILImageFont
    for _fp in ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
        if os.path.isfile(_fp):
            _PILImageDraw.Draw(_PILImage.new("L", (48, 24), 0)).text(
                (2, 2), "Z12", font=_PILImageFont.truetype(_fp, 12), fill=255)
            break
except Exception:                                                      
    pass

from soc_vision.cjk_text import (draw_text, text_size, backend as cjk_backend,  
                                 install_cv2_puttext_patch)
from soc_vision.led_rules import RuleBook, VERDICT_OK, VERDICT_BAD, VERDICT_UNK                
from soc_vision.ui_app import judge, save_shot, scpi_verdict, build_parser as _ui_parser
from soc_vision.touch_input import TouchScreen
try:
    from soc_vision import board_infer as BI        
except Exception as _bi:                            
    BI = None
    print("[infer] 适配层不可用: %s" % _bi, flush=True)
try:
    from soc_vision.marker_id import MarkerId       
except Exception as _me:                            
    MarkerId = None
    print("[marker] 不可用: %s" % _me, flush=True)  

_ENGINE_DIRS = [os.environ.get("AFH03_ENGINE", ""), "/userdata/work2/engine",
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine")]
for _ed in _ENGINE_DIRS:
    try:
        if _ed and os.path.isdir(_ed) and _ed not in sys.path:
            sys.path.insert(0, _ed)
    except Exception:                                                  
        pass
try:
    import session_summary as SS
    print("[summary] 模块已加载: %s (%s)"
          % (getattr(SS, "__file__", "?"), getattr(SS, "ENGINE_VERSION", "?")), flush=True)
except Exception as _se:                                               
    SS = None
    print("[summary] 模块不可用（总结页将降级显示）: %s" % _se, flush=True)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYOUT_DEFAULT = os.path.join(HERE, "config", "ui_layout.json")

_RULE_CTX = {"loaded": False, "meta": {}, "alias": {}, "marker_pid": {}, "markers": {}}
_RULE_WARNED: set = set()

def _load_rule_ctx():
    """懒加载 led_rules.json + markers_modules.json，建立 label→规则 id 映射。"""
    if _RULE_CTX["loaded"]:
        return _RULE_CTX
    _RULE_CTX["loaded"] = True
    try:
        with open(os.path.join(HERE, "config", "led_rules.json"), encoding="utf-8") as f:
            doc = json.load(f)
        for p in (doc.get("parts") or []):
            pid = str(p.get("id") or "")
            if not pid:
                continue
            _RULE_CTX["meta"][pid] = p
            _RULE_CTX["alias"][pid.upper()] = pid
            for a in (p.get("aliases") or []):
                _RULE_CTX["alias"][str(a).strip().upper()] = pid
    except Exception as e:                                         
        print("[ui_kiosk][warn] 规则表读取失败（全部按无规则降级）: %s" % e, flush=True)
    try:
        with open(os.path.join(HERE, "markers_modules.json"), encoding="utf-8") as f:
            _RULE_CTX["markers"] = (json.load(f).get("modules") or {})
    except Exception as e:                                         
        print("[ui_kiosk][warn] 标记映射读取失败: %s" % e, flush=True)
    try:
        from soc_vision.marker_id import RULE_KEY_TO_PART as _RK
    except Exception:                                              
        _RK = {}
    for label, m in _RULE_CTX["markers"].items():
        pid = ""
        cands = _RK.get(str((m or {}).get("rule_key") or "")) or []
        if cands:
            pid = next((c for c in cands if c in _RULE_CTX["meta"]), cands[0])
        if not pid:
            pid = _resolve_rule_pid(label)
        _RULE_CTX["marker_pid"][str(label).strip().upper()] = pid
    return _RULE_CTX

def _resolve_rule_pid(name) -> str:
    """标记 label / 识别部位 id（大小写不敏感）→ 规则部件 id；找不到返回 ""。

    ★ 2026-10-29：旧"模块 id"（Z11-1/Z12-GL/Z14-CLK/Z15-IF…）先归一成母模块
      （它们是母模块的二路二维码，不是独立部位）→ 规则/问答也落到母模块。
    """
    ctx = _load_rule_ctx()
    s = str(name or "").strip()
    if not s:
        return ""
    _alias = _MODULE_ALIAS_II.get(s.lower())
    if _alias:
        s = _alias[0]
    up = s.upper()
    if up in ctx["marker_pid"]:
        return ctx["marker_pid"][up]
    if up in ctx["alias"]:
        return ctx["alias"][up]
    for pid in ctx["meta"]:
        if pid.upper() == up:
            return pid
    return ""

def _rule_state(pid) -> str:
    m = _load_rule_ctx()["meta"].get(pid) or {}
    if not m:
        return "missing"
    if not (m.get("lamps") or []):

        
        if (str(m.get("kind") or "") in ("text_assert", "numeric_range")
                and m.get("reader")):
            return "ready"
        return "registered"
    if "待确认" in str(m.get("status") or ""):
        return "draft"
    return "ready"

def _rule_state_for_label(label) -> str:
    return _rule_state(_resolve_rule_pid(label))

def _coverage_report() -> list:
    """启动自检（**只 WARN，不 FATAL**）：返回"暂无可用判定规则"的部位清单。"""
    ctx = _load_rule_ctx()
    if not ctx["markers"]:
        print("[ui_kiosk][warn] 没有 markers_modules.json → 跳过规则覆盖自检", flush=True)
        return []
    groups = {"ready": [], "draft": [], "registered": [], "missing": []}
    for label in ctx["markers"]:
        st = _rule_state(ctx["marker_pid"].get(str(label).strip().upper()) or "")
        groups.setdefault(st, []).append(str(label))
    pend = groups["draft"] + groups["registered"] + groups["missing"]
    print("[ui_kiosk] 规则覆盖自检：%d 个标记模块 → 有判定规则 %d、草案待确认 %d、仅登记 %d、未登记 %d"
          % (len(ctx["markers"]), len(groups["ready"]), len(groups["draft"]),
             len(groups["registered"]), len(groups["missing"])), flush=True)
    if pend:
        print("[ui_kiosk][WARN] 以下 %d 个部位暂无可用判定规则（**不 FATAL**；识别到 → "
              "界面提示「该部位已识别，判定规则待标定」，结论=未判定）：%s"
              % (len(pend), "、".join(pend)), flush=True)
    return pend

def _degrade_result(r: dict, label: str = "") -> dict:
    """★ 结果页优雅降级：部位没有可用规则 ⇒ 结论=「未判定（判定规则待标定）」。

    只在后台判定本来就给不出结论（state=unknown）时接管；engine 给出 ok/bad 时不动它。
    """
    if not isinstance(r, dict):
        return r
    part = r.get("part") or {}
    lbl = str(label or part.get("part") or part.get("part_used") or "").strip()
    pid = _resolve_rule_pid(lbl)
    st = _rule_state(pid)
    r["rule"] = {"part": pid, "state": st, "label": lbl}
    if not lbl:
        return r
    up = lbl.upper()
    disp = str(part.get("display") or part.get("part") or "")
    if up.startswith("Z") and up not in disp.upper():
        part["display"] = ("%s（%s）" % (disp, up)) if disp else up
        r["part"] = part
    concl = dict(r.get("conclusion") or {})
    if st == "ready" or str(concl.get("state") or "unknown") != "unknown":
        return r
    detail = {"missing": "规则表无此部位",
              "draft": "规则已登记但灯序/期望待确认（草案）",
              "registered": "仅登记部位，尚无灯序规则"}.get(st, "规则未就绪")
    short = {"missing": "无规则", "draft": "草案", "registered": "仅登记"}.get(st, "未就绪")
    note = "该部位已识别（%s），判定规则待标定" % up
    concl["state"] = "unknown"
    concl["text"] = "未判定（判定规则待标定）"
    concl["why"] = "%s（%s）" % (note, short)
    r["conclusion"] = concl
    r["rule_note"] = note
    und = dict(r.get("undetermined") or {})
    und["n"] = max(int(und.get("n") or 0), 1)
    und["reasons"] = [note] + [x for x in (und.get("reasons") or []) if x != note]
    r["undetermined"] = und
    if up not in _RULE_WARNED:
        _RULE_WARNED.add(up)
        print("[result][WARN] %s → 结论=未判定（%s）" % (note, detail), flush=True)
    return r

def _apply_screen_qa(r: dict) -> dict:
    """★ Fix2（2026-10-25 现场 Bug1）：屏幕类**只做粗判提示，问答为准** —— 结果页收口。

    背景：用户现场报「屏幕项被视觉直接判正常 ⇒ 问答不出现」。vision_rules 侧已改成
    屏幕项**禁止输出 normal**（value=undetermined + ``decided_by="qa_required"`` + ``hint``）；
    这里负责结果页口径：

    1. 每个"需人工确认"的屏幕项显示成一行「⚠ 需人工确认（视觉提示：…，参考）」；
    2. 这些行**不计入正常项数**（`match=None`，`qa_required=True`）；
    3. 只要存在屏幕项且没有明确异常 ⇒ 结论改成「⚠ 需人工确认」，
       主循环据此 3 秒自动跳到问答（见 RESULT_AUTO_QA_SEC）。
    """
    if not isinstance(r, dict):
        return r
    ev = [e for e in (r.get("vision_evidence") or [])
          if isinstance(e, dict) and str(e.get("decided_by") or "") == "qa_required"]
    if not ev:
        return r
    rows = list(r.get("rows") or [])
    seen = set()
    qa_rows = []
    for e in ev:
        hint = str(e.get("hint") or "视觉提示（参考）")
        disp = {"operator_display": "操显", "leader_display": "领显"}.get(
            str(e.get("display") or ""), "")
        key = (disp, hint)
        if key in seen:                 
            continue
        seen.add(key)
        qa_rows.append({
            "kind": "screen_qa", "qa_required": True, "record_only": False,
            "pos": ("屏幕·%s" % disp) if disp else "屏幕",
            "name": "视觉提示：%s" % hint,
            "state_text": "⚠ 需人工确认", "expect_text": "问答为准", "match": None,
            "why": str(e.get("evidence") or ""), "conf": e.get("confidence"),
            "item_no": e.get("item_no") or "", "field": e.get("field") or "",
            "rule": e.get("rule") or "", "category": e.get("category") or "",
        })
    if not qa_rows:
        return r
    r["qa_required"] = {"n": len(ev), "rows": len(qa_rows),
                        "hints": [q["name"] for q in qa_rows]}
    r["rows"] = rows + qa_rows
    bad = [x for x in rows if x.get("match") is False]
    n_ok = len([x for x in rows if x.get("match") is True])      
    if not bad:
        concl = dict(r.get("conclusion") or {})
        concl["state"] = "qa"
        concl["text"] = "⚠ 需人工确认"
        concl["why"] = ("屏幕类 %d 项以问答为准（视觉仅提示，不计入正常项）；其余 %d 项符合"
                        % (len(ev), n_ok))
        concl["n_ok"] = n_ok
        concl["n_bad"] = 0
        r["conclusion"] = concl
        print("[result] 屏幕类 %d 项 → 结论=⚠ 需人工确认（视觉仅提示；正常项 %d，不含屏幕）"
              % (len(ev), n_ok), flush=True)
    else:
        print("[result] 屏幕类 %d 项需人工确认，但已有明确异常 %d 项 ⇒ 结论仍为异常"
              % (len(ev), len(bad)), flush=True)
    return r

def _apply_partqa(r: dict, pq: dict) -> dict:
    """★ 2026-10-29（现场 G18 20:14）：按部位问答的答案合并回结果页并重算结论。

    背景：partqa 作答只写 res_meta["part_qa"]["answers"]，结果页 resv 从不重算 ⇒
    用户连答 QA002/QA003/QA004=done（屏幕类 21 项 qa_required），结果页仍显示
    「⚠ 需人工确认｜屏幕类 21 项以问答为准」，点几次"正常"也不变。

    这里：
      1. 已答 QA → 一行「问答 QAxxx：答案」（正常/异常/跳过），替换旧的视觉提示行；
      2. 未答 QA → 仍一行「⚠ 待人工确认（本题未作答）」；
      3. 重算 conclusion：有明确异常答案 → 异常；未答完 → 仍需人工确认（剩 M 题）；
         全部答完且无异常 → 正常（问答确认 N 题），不再显示"需人工确认"。
    """
    if not isinstance(r, dict) or not isinstance(pq, dict):
        return r
    items = list(pq.get("items") or [])
    if not items:
        return r
    answers = pq.get("answers") or {}
    rows = [x for x in (r.get("rows") or []) if not x.get("qa_required")]
    _BAD = ("no", "bad", "abnormal", "false", "异常", "否", "不正常", "没有")
    n_ans = n_bad = 0
    bad_labels = []
    for it in items:
        qid = str(it.get("qa_id") or "")
        a = answers.get(qid)
        _subj = _flow_clean(it.get("subject") or it.get("check_item")
                            or it.get("question") or "")[:34]
        if not a:
            rows.append({"kind": "screen_qa", "qa_required": True, "record_only": False,
                         "pos": "问答 %s" % (qid or "-"), "name": _subj or "待答问题",
                         "state_text": "⚠ 待人工确认", "expect_text": "问答为准",
                         "match": None, "why": "本题尚未作答", "qa_id": qid,
                         "field": it.get("evidence_field") or ""})
            continue
        val = str(a.get("value") or "")
        lab = str(a.get("label") or a.get("label_plain") or val)
        skipped = bool(a.get("skipped")) or val in ("skipped", "undetermined")
        _low = (val + " " + lab).lower()
        bad = (not skipped) and any(b in _low for b in _BAD)
        n_ans += 1
        if bad:
            n_bad += 1
            bad_labels.append(_subj or qid)
        rows.append({"kind": "qa_answered", "qa_required": False, "record_only": skipped,
                     "pos": "问答 %s" % (qid or "-"), "name": _subj or "问答题",
                     "state_text": ("跳过（未验证）" if skipped else lab),
                     "expect_text": "问答为准",
                     "match": (None if skipped else (not bad)),
                     "why": "操作员作答：%s" % lab, "qa_id": qid,
                     "field": it.get("evidence_field") or ""})
    r["rows"] = rows
    r["partqa"] = {"n": len(items), "answered": n_ans, "bad": n_bad}
    concl = dict(r.get("conclusion") or {})
    left = len(items) - n_ans
    if n_bad:
        concl.update(state="bad", text="异常：问答确认 %d 项异常" % n_bad,
                     why="；".join(bad_labels[:3]), n_bad=n_bad, n_ok=0)
    elif left:
        concl.update(state="qa", text="⚠ 需人工确认（还剩 %d 题）" % left,
                     why="按部位问答还有 %d 题未作答" % left,
                     n_bad=0, n_ok=len([x for x in rows if x.get("match") is True]))
    else:
        _ok = len([x for x in rows if x.get("match") is True])
        concl.update(state="ok", text="正常（问答确认 %d 题）" % n_ans,
                     why="；".join("问答 %s=%s" % (str(x.get("qa_id") or "-"),
                                                  x.get("state_text")) for x in rows
                                  if x.get("kind") == "qa_answered")[:160],
                     n_bad=0, n_ok=_ok)
    r["conclusion"] = concl
    print("[partqa] 答案合并回结果页：已答 %d/%d、异常 %d → 结论=%s"
          % (n_ans, len(items), n_bad, concl.get("text")), flush=True)
    return r

def _effective_part(part, mi, marker_hit, calib, explicit_part=False):
    """归属优先级：显式 --part > 标记 > 环境变量/默认 part > 未判定。

    ★ `AFH03_PART` 环境变量只是**默认值**（systemd 里设的 PS_KONG），
      现场贴了 v2 标记时应以标记为准；只有命令行真的写了 `--part` 才禁止标记改判。
    """
    if explicit_part and part:
        return part, "命令行显式 --part=%s（标记不参与改判）" % part, 1.0
    if mi is not None and marker_hit is not None:
        try:
            p, why, conf = mi.resolve_part(marker_hit,
                                           list((calib.parts if calib else {}).keys()))
            if p:
                return p, why, conf
        except Exception as e:                                         
            print("[marker] resolve 异常: %s" % e, flush=True)
    if part:
        return part, "无标记 → 用默认部件 %s（环境变量/步骤）" % part, 0.5
    return "", "无标记、也无默认部件 → 未判定", 0.0

ROUTE_PAIRED = ("z11", "z12", "z14", "z15")      

_MODULE_ALIAS_II = {
    "z11-1": ("z11", "II"), "z11ii": ("z11", "II"), "z11-ii": ("z11", "II"),
    "z12-gl": ("z12", "II"), "z12-clk": ("z12", "II"), "z12clk": ("z12", "II"),
    "z12-gl2": ("z12", "II"),
    "z14-clk": ("z14", "II"), "z14clk": ("z14", "II"), "z14-ii": ("z14", "II"),
    "z15-if": ("z15", "II"), "z15if": ("z15", "II"), "z15-ii": ("z15", "II"),
}
ROUTE_CN = {"I": "一路", "II": "二路"}
_ROUTE_ALIAS = {"I": "I", "1": "I", "1路": "I", "一": "I", "一路": "I",
                "L1": "I", "ONE": "I", "A": "I",
                "II": "II", "2": "II", "2路": "II", "二": "II", "二路": "II",
                "L2": "II", "TWO": "II", "B": "II"}

def _route_norm(x) -> str:
    """任意写法 → ``"I"`` / ``"II"`` / ``""``（大小写/中文/数字都收；认不出就返回空，绝不猜）。"""
    if x is None:
        return ""
    s = str(x).strip().replace(" ", "").replace("　", "").upper()
    if not s:
        return ""
    for k in (s, (s[:-1] if s.endswith("路") and len(s) > 1 else s)):
        v = _ROUTE_ALIAS.get(k)
        if v:
            return v
    return ""

def _route_cn(route) -> str:
    """I/II → 「一路」/「二路」；未知返回 ""。"""
    return ROUTE_CN.get(_route_norm(route), "")

def _part_key(part) -> str:
    """部位 key 归一：旧"模块 id"（z11-1/Z12-GL/Z14-CLK/Z15-IF…）→ 母模块 key。

    ★ 2026-10-29 用户明确口径：z11-1 / z12-clk(或 Z12-GL) / z14-clk / z15-if 都**不是独立
      模块**，而是各自母模块的**二路二维码**（route=II）。板端 markers_modules.json 的
      part/route 已正确（z11/z12/z14/z15 + II），但识别/旧缓存里仍会出现旧 id，
      这里统一归一，避免显示 z11-1、也避免按"独立部位"去找规则/题库。
    """
    p = str(part or "").strip().lower()
    return _MODULE_ALIAS_II.get(p, (p, ""))[0]

def _part_route_hint(part) -> str:
    """旧模块 id 自带的路别（z11-1 → II）；非旧 id 返回 ""。"""
    p = str(part or "").strip().lower()
    return _MODULE_ALIAS_II.get(p, ("", ""))[1]

def _part_disp(part, route="", base="") -> str:
    """模块显示名（用户口径）。

    * 成对部位（z11/z12/z14/z15）+ 已知路别 → ``"Z11 二路"`` / ``"Z11 一路"``；
      路别未知 → ``"Z11"``（绝不猜一路/二路）；
    * 旧模块 id（z11-1/Z14-CLK…）→ 母模块 + 二路（route=II 由 _part_route_hint 给出）；
    * 其它部位 → **原名不变**（给了 ``base`` 就原样用，否则用大写 part）。
    """
    p0 = str(part or "").strip()
    route = _route_norm(route) or _part_route_hint(p0)
    p = _part_key(p0)
    if not p:
        return str(base or "")
    if p in ROUTE_PAIRED:
        cn = _route_cn(route)
        return ("%s %s" % (p.upper(), cn)) if cn else p.upper()
    return str(base or p.upper())

def _marker_route(hit) -> str:
    """MarkerHit → 路别（只读 markers_modules.json 的 ``route`` 字段，不猜）。"""
    mod = getattr(hit, "module", None) or {}
    return _route_norm(mod.get("route"))

def _marker_code(hit) -> str:
    """MarkerHit → 码名（Z11-1/Z14-CLK…，**仅内部/日志用**，不做模块名）。"""
    mod = getattr(hit, "module", None) or {}
    return str(mod.get("label") or getattr(hit, "label", "") or "")

def _route_from_label(label) -> str:
    """码名（Z11-1 / Z14-CLK / Z15-IF / Z12-GL）→ 路别；字典里查不到返回 ""。"""
    s = str(label or "").strip().upper()
    if not s:
        return ""
    for k, m in (_load_rule_ctx().get("markers") or {}).items():
        if str(k).strip().upper() == s:
            return _route_norm((m or {}).get("route"))
    return ""

def _step_route(step) -> str:
    """步骤路别：``step.route`` 优先；为空则用该步 qa_items 的**唯一** route（全一致才用）。

    现场数据里 9(7-I)-3 / 10(7-II)-3 / 11(8-I)-3 … 这些步骤 route 字段是空的，
    但它们的 LQ 题自带 route（I/II 各一份副本）⇒ 用它把路别补回来（不猜：仅当唯一）。
    """
    r = _route_norm((step or {}).get("route"))
    if r:
        return r
    rs = {_route_norm(q.get("route")) for q in ((step or {}).get("qa_items") or [])
          if isinstance(q, dict)}
    rs.discard("")
    return rs.pop() if len(rs) == 1 else ""

def _result_route(r, meta=None) -> str:
    """结果 dict → 路别。优先级（先现场、后推断）：

    ① ``meta["marker_route"]``  现场标记（最权威：码就是面板身份）
    ② ``meta["route"]``         步骤路别（流程页）
    ③ ``part["route"]`` / ``part["raw"]["route"]``  part_recognizer 输出
    ④ 码名反查字典（Z11-1 → II）
    ⑤ 证据 route 众数（最弱，仅当前面全空）
    """
    meta = meta or {}
    r = r or {}
    part = r.get("part") or {}
    raw = part.get("raw") or {}
    for v in (meta.get("marker_route"), meta.get("route"), part.get("route"),
              raw.get("route"), _route_from_label(meta.get("marker_label"))):
        rv = _route_norm(v)
        if rv:
            return rv
    cnt: Dict[str, int] = {}
    for e in (r.get("vision_evidence") or []):
        if isinstance(e, dict):
            rv = _route_norm(e.get("route"))
            if rv:
                cnt[rv] = cnt.get(rv, 0) + 1
    if cnt:
        return max(cnt, key=lambda k: cnt[k])
    return ""

def _apply_route(r: dict, meta=None) -> dict:
    """把路别灌进结果 dict（**幂等，只补空不覆盖**）：

    * ``part.route`` / ``part.route_text``（一路/二路）/ ``part.display``（Z11 二路）；
    * ``r["route"]``（结果级，给按部位问答用）；
    * 逐条证据若 route 为空 → 补本次路别（证据 route 贯穿）；
    * 标记路别与步骤路别冲突时**以标记为准**，只记日志 + ``r["route_conflict"]``。
    """
    if not isinstance(r, dict):
        return r
    meta = dict(meta or {})
    part = dict(r.get("part") or {})

    

    _locked_r = _route_norm(part.get("route")) if part.get("route_locked") else ""
    if _locked_r:
        meta["marker_route"] = _locked_r
        meta["route"] = _locked_r
        part["route"] = _locked_r
        print("[route] 二路码归一：%s → %s %s（route=%s 已锁定，忽略旧标记/步骤路别）"
              % (part.get("legacy_part") or "?", str(part.get("part") or "").upper(),
                 _route_cn(_locked_r), _locked_r), flush=True)

    

    _p0 = str(part.get("part") or part.get("part_used") or "").strip().lower()
    _legacy_ii = _MODULE_ALIAS_II.get(_p0)
    if _legacy_ii:
        part["legacy_module_id"] = _p0
        part["part"] = _legacy_ii[0]
        if part.get("part_used"):
            part["part_used"] = _legacy_ii[0]
        meta["marker_route"] = _legacy_ii[1]
        meta["route"] = _legacy_ii[1]
        print("[route] 旧模块 id %s → %s 二路（route=II，覆盖旧路别/旧标记锁）"
              % (_p0, _legacy_ii[0].upper()), flush=True)
        r["part"] = part
    route = _result_route(r, meta)
    p = _part_key(part.get("part") or part.get("part_used"))
    if route and not _route_norm(part.get("route")):
        part["route"] = route
    if p in ROUTE_PAIRED:
        raw = part.get("raw") or {}
        base = (part.get("display_base") or raw.get("part_display") or raw.get("name")
                or part.get("display") or "")
        if base and not part.get("display_base"):
            part["display_base"] = str(base)       
        part["display"] = _part_disp(p, route)     
        part["route_text"] = _route_cn(route)
    part["route"] = _route_norm(part.get("route"))
    r["part"] = part
    r["route"] = part["route"] or _route_norm(route)
    for _k in ("evidence_items", "vision_evidence"):
        for e in (r.get(_k) or []):
            if isinstance(e, dict) and route and not str(e.get("route") or "").strip():
                e["route"] = route
    _mr, _sr = _route_norm(meta.get("marker_route")), _route_norm(meta.get("route"))
    if _mr and _sr and _mr != _sr:
        r["route_conflict"] = {"marker": _mr, "step": _sr}
        print("[route] 标记路别 %s 与步骤路别 %s 不一致 → 以**标记**为准（显示 %s）"
              % (_mr, _sr, part.get("display") or "-"), flush=True)
    if route or p in ROUTE_PAIRED:
        print("[route] 部位 %s：route=%s 显示=%s（标记码=%s）"
              % (p or "-", route or "-", part.get("display") or "-",
                 str(meta.get("marker_label") or "") or "-"), flush=True)
    return r

def load_layout(path: str = "") -> dict:
    p = path or LAYOUT_DEFAULT
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def page(layout: dict, pid: str) -> dict:
    for pg in layout.get("pages", []):
        if pg.get("id") == pid:
            return pg
    return (layout.get("pages") or [{}])[0]

def _card(img, rect, color, alpha=1.0):
    x0, y0, x1, y1 = [int(v) for v in rect]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(img.shape[1], x1), min(img.shape[0], y1)
    if x1 <= x0 or y1 <= y0:
        return
    if alpha >= 1.0:
        img[y0:y1, x0:x1] = color
        return
    roi = img[y0:y1, x0:x1].astype(np.float32)
    img[y0:y1, x0:x1] = (roi * (1 - alpha) + np.array(color, np.float32) * alpha).astype(np.uint8)

_MASK_CACHE: dict = {}

def _rrect_mask(w, h, r):
    """圆角矩形软蒙版（0..1 float，h×w）。按尺寸缓存 —— 每帧不重复算。"""
    key = (int(w), int(h), int(r))
    got = _MASK_CACHE.get(key)
    if got is not None:
        return got
    w, h = max(1, int(w)), max(1, int(h))
    r = int(max(0, min(int(r), min(w, h) // 2)))
    m = np.zeros((h, w), np.uint8)
    if r <= 1:
        m[:] = 255
    else:
        m[r:h - r, :] = 255                                    
        m[:, r:w - r] = 255                                    
        for cx, cy in ((r, r), (w - r - 1, r), (r, h - r - 1), (w - r - 1, h - r - 1)):
            cv2.circle(m, (cx, cy), r, 255, -1, lineType=cv2.LINE_AA)
    f = m.astype(np.float32) / 255.0
    _MASK_CACHE[key] = f
    return f

def _rrect_fill(img, rect, color, r=12):
    """不透明圆角实心块（cv2 图元，快；角上是抗锯齿）。"""
    x0, y0, x1, y1 = [int(round(v)) for v in rect]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(img.shape[1], x1), min(img.shape[0], y1)
    if x1 <= x0 or y1 <= y0:
        return
    r = int(max(0, min(int(r), (x1 - x0) // 2, (y1 - y0) // 2)))
    if r <= 1:
        img[y0:y1, x0:x1] = color
        return
    cv2.rectangle(img, (x0 + r, y0), (x1 - r - 1, y1 - 1), color, -1)
    cv2.rectangle(img, (x0, y0 + r), (x1 - 1, y1 - r - 1), color, -1)
    for cx, cy in ((x0 + r, y0 + r), (x1 - r - 1, y0 + r),
                   (x0 + r, y1 - r - 1), (x1 - r - 1, y1 - r - 1)):
        cv2.circle(img, (cx, cy), r, color, -1, lineType=cv2.LINE_AA)

def _rrect_panel(img, rect, fill, edge=None, r=12, shadow=0, shadow_color=(12, 9, 7)):
    """圆角面板 = 可选下投影 + 1px 描边 + 实心填充（全部不透明，零混合开销）。"""
    x0, y0, x1, y1 = [int(v) for v in rect]
    if shadow:
        _rrect_fill(img, (x0, y0 + shadow, x1, y1 + shadow), shadow_color, r)
    if edge is not None:
        _rrect_fill(img, (x0 - 1, y0 - 1, x1 + 1, y1 + 1), edge, r + 1)
    _rrect_fill(img, (x0, y0, x1, y1), fill, r)

def _grad_v(img, rect, c_top, c_bot):
    """竖向渐变填充（只在底板渲染时用一次）。"""
    x0, y0, x1, y1 = [int(v) for v in rect]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(img.shape[1], x1), min(img.shape[0], y1)
    h = y1 - y0
    if h <= 0 or x1 <= x0:
        return
    t = (np.arange(h, dtype=np.float32) / float(max(1, h - 1))).reshape(h, 1, 1)
    a = np.array(c_top, np.float32).reshape(1, 1, 3)
    b = np.array(c_bot, np.float32).reshape(1, 1, 3)
    img[y0:y1, x0:x1] = np.clip(a * (1.0 - t) + b * t, 0, 255).astype(np.uint8)

def _dot(img, cx, cy, r, color):
    cv2.circle(img, (int(cx), int(cy)), int(r), color, -1, lineType=cv2.LINE_AA)

def _text_center(img, text, rect, scale, color, th=1):
    """在 rect 里**横竖都居中**画一行（比原来按 0.62 系数估基线更准）。"""
    x0, y0, x1, y1 = [int(v) for v in rect]
    try:
        w, h = text_size(text, scale)
    except Exception:                                                  
        w, h = int(len(str(text)) * scale * 15), int(scale * 30)
    draw_text(img, text, (int(x0 + ((x1 - x0) - w) / 2), int(y0 + ((y1 - y0) + h) / 2)),
              scale=scale, color=color, th=th)

def _fit_text(text, maxw, scale, ellip="…"):
    """按最大像素宽截断显示串（**只影响显示**，不动任何数据/逻辑）。"""
    s = str(text or "")
    try:
        w, _h = text_size(s, scale)
    except Exception:                                                  
        return s
    if int(maxw) <= 0 or w <= maxw:
        return s
    while len(s) > 1:
        s = s[:-1]
        try:
            w2, _h2 = text_size(s + ellip, scale)
        except Exception:                                              
            break
        if w2 <= maxw:
            return s + ellip
    return s

def _wrap_cjk(text, maxw, scale):
    """按**像素宽**折行（Pango 的 size 是 pt，别用"字数"估宽度）。"""
    s = str(text or "")
    out, cur = [], ""
    for ch in s:
        try:
            w, _h = text_size(cur + ch, scale)
        except Exception:                                              
            w = 0
        if cur and w > maxw:
            out.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out or [""]

def _corner_marks(img, rect, color, inset=12, ln=22, t=2):
    """预览四角装饰线（摄像机取景框感，轻量）。"""
    x0, y0, x1, y1 = [int(v) for v in rect]
    for px, py, dx, dy in ((x0 + inset, y0 + inset, 1, 1), (x1 - inset, y0 + inset, -1, 1),
                           (x0 + inset, y1 - inset, 1, -1), (x1 - inset, y1 - inset, -1, -1)):
        cv2.line(img, (px, py), (px + dx * ln, py), color, t, lineType=cv2.LINE_AA)
        cv2.line(img, (px, py), (px, py + dy * ln), color, t, lineType=cv2.LINE_AA)

def _round_corners(img, rect, r, color):
    """每帧只碰 4 个 r×r 小方块，把预览的方角"盖"成圆角（外色=边框色）。"""
    if color is None:
        return
    x0, y0, x1, y1 = [int(v) for v in rect]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(img.shape[1], x1), min(img.shape[0], y1)
    w, h = x1 - x0, y1 - y0
    r = int(max(0, min(int(r), w // 2, h // 2)))
    if r < 2:
        return
    m = _rrect_mask(w, h, r)
    col = np.array(color, np.float32).reshape(1, 1, 3)
    for sx, sy, mx, my in ((x0, y0, 0, 0), (x1 - r, y0, w - r, 0),
                           (x0, y1 - r, 0, h - r), (x1 - r, y1 - r, w - r, h - r)):
        sub = m[my:my + r, mx:mx + r][:, :, None]
        roi = img[sy:sy + r, sx:sx + r].astype(np.float32)
        img[sy:sy + r, sx:sx + r] = np.clip(col * (1.0 - sub) + roi * sub, 0, 255).astype(np.uint8)

def _center_text(img, text, cx, baseline, scale, color, th=1):
    try:
        from soc_vision.cjk_text import text_size
        w, _h = text_size(text, scale)
    except Exception:                                                  
        w = int(len(text) * scale * 14)
    draw_text(img, text, (int(cx - w / 2), int(baseline)), scale=scale, color=color, th=th)

def _fit(img, frame, rect, label="", bg=None):
    x0, y0, x1, y1 = [int(v) for v in rect]
    _card(img, rect, (14, 15, 18) if bg is None else bg, 1.0)
    if frame is None:
        _center_text(img, label or "（无画面）", (x0 + x1) / 2, (y0 + y1) / 2, 0.8, (200, 200, 200))
        return
    fh, fw = frame.shape[:2]
    k = min((x1 - x0) / max(1, fw), (y1 - y0) / max(1, fh))
    if k < 0.5:                      
        small = cv2.resize(frame, (max(1, int(fw * 0.5)), max(1, int(fh * 0.5))),
                           interpolation=cv2.INTER_AREA)
        frame = small
        fh, fw = frame.shape[:2]
        k = min((x1 - x0) / max(1, fw), (y1 - y0) / max(1, fh))
    d = cv2.resize(frame, (max(1, int(fw * k)), max(1, int(fh * k))), interpolation=cv2.INTER_AREA)
    ox = x0 + ((x1 - x0) - d.shape[1]) // 2
    oy = y0 + ((y1 - y0) - d.shape[0]) // 2
    img[oy:oy + d.shape[0], ox:ox + d.shape[1]] = d

def annotate_frame(frame, rows, vobj, extra=""):
    """在照片上画：顶部结论横幅 + 圈灯 + ON/OFF（**本地实现**，不依赖 tools/，避免 import 崩溃）。"""
    img = frame.copy()
    v = (vobj or {}).get("verdict", VERDICT_UNK)
    col = (80, 200, 90) if v == VERDICT_OK else ((60, 60, 230) if v == VERDICT_BAD else (170, 170, 170))
    icon = "OK" if v == VERDICT_OK else ("FAULT" if v == VERDICT_BAD else "UNKNOWN")
    W = img.shape[1]
    cv2.rectangle(img, (0, 0), (W, 78), (24, 24, 28), -1)
    draw_text(img, "%s %s" % (icon, v), (14, 60), scale=2.2, color=col, th=2)
    draw_text(img, str((vobj or {}).get("reason") or "")[:44], (14, 108), scale=0.72,
              color=(240, 240, 240))
    if extra:
        draw_text(img, str(extra)[:60], (14, 136), scale=0.5, color=(190, 190, 190))
    for r in (rows or []):
        if r.get("x", -1) < 0:
            continue
        cc = (80, 200, 90) if r.get("on") else ((60, 60, 230) if r.get("on") is False else (170, 170, 170))
        cv2.circle(img, (int(r["x"]), int(r["y"])), int(max(6, r.get("r", 10))), cc, 3)
        draw_text(img, "%s %s" % (str(r.get("name"))[:8],
                                  "ON" if r.get("on") else ("?" if r.get("on") is None else "OFF")),
                  (int(r["x"]) - int(r.get("r", 10)), int(r["y"]) - int(r.get("r", 10)) - 6),
                  scale=0.5, color=cc)
    return img

def _reader_kind(part_id):
    """该部件是否为"读数器型"（不靠 ROI，故必须绕过"未标定"门槛）。"""
    try:
        import json as _json
        _p = os.path.join(HERE, "config", "led_rules.json")
        _d = _json.load(open(_p, encoding="utf-8"))
        _raw = next((x for x in _d.get("parts", []) if x.get("id") == part_id), None)
        if _raw and str(_raw.get("kind", "")) in ("text_assert", "numeric_range"):
            return _raw
    except Exception:                                                 
        pass
    return None

def reader_verdict(frame, part_id):
    """★ 读数器型部件直接出结论/明确原因（**不经过"未标定 ⇒ 未判定"那道门**）。"""
    raw = _reader_kind(part_id)
    if raw is None:
        return None
    kind = str(raw.get("kind"))
    why = "该部件的判定能力未就绪（%s 读数器未加载）" % (raw.get("reader") or kind)
    if kind == "text_assert":                                          
        try:
            from soc_vision.screen_read_v2 import ScreenReaderV2 as ScreenReader
            rd = ScreenReader(os.path.join(HERE, "ref_cn"), verbose=False)   
            _res = rd.read(frame)                     
            f = rd.fields(_res)
            minc = float(raw.get("min_conf", 0.55))
            txt, ok_all, lo = [], True, False
            for asrt in (raw.get("asserts") or []):
                nm = asrt.get("field", "")
                got = f.get(nm) or {}
                txt.append("%s=%s(%.2f)" % (nm, got.get("value", "?"), float(got.get("conf", 0.0))))
                if got.get("value") != asrt.get("expect"):
                    ok_all = False
                if float(got.get("conf", 0.0)) < minc:
                    lo = True
            line = "、".join(txt) or "无读数"
            print("[reader] 屏读数：%s（v2 口径）" % line, flush=True)
            if lo or not f:
                why = "屏读数器读数置信不足（%s）" % line
            elif ok_all:
                return "正常", "屏读数：%s ⇒ 正常" % line
            else:
                return "故障", "屏读数：%s ⇒ 与期望不符" % line
        except Exception as e:                                         
            why = "屏读数器未就绪（%s: %s）" % (type(e).__name__, e)
    else:                                                              
        try:
            from soc_vision import seg7
            rgb = frame[:, :, ::-1] if frame.ndim == 3 else frame
            disps = seg7.read_displays(rgb)
            if not disps:
                why = "7 段读数器未就绪/未检出数字"
            else:
                line = "、".join("%s(%.2f)" % (d0.text, d0.conf) for d0 in disps[:4] if d0.text.strip())
                print("[reader] 7 段读数：%s" % line, flush=True)
                why = "7 段读数：%s（容差校验待接入）" % (line or "空")
        except Exception as e:                                         
            why = "7 段读数器未就绪（%s: %s）" % (type(e).__name__, e)

    return None, "该部件的判定能力未就绪（%s）→ 未判定" % why

def run_capture(frame, part, book, calib, det, allow_auto, shots_dir, scope):
    """**受保护的 capture 全链**：判定 -> 标注 -> 存盘。**绝不抛异常**。

    返回 dict：{ok, verdict, reason, shot_dir, error, rows, vobj}
    每个阶段都打点日志（`[capture] stage=...`），异常时打完整 traceback。
    """
    import traceback
    out = {"ok": False, "verdict": VERDICT_UNK, "reason": "", "shot_dir": "", "error": "",
           "rows": [], "vobj": None}
    stage = "start"
    try:
        stage = "reader"
        rv = reader_verdict(frame, part)          
        if rv is not None:
            verdict, reason = rv if isinstance(rv, tuple) else ("未判定", rv)
            v = {"verdict": verdict or "未判定", "reason": reason}
            info = {"rows": [], "path": "reader"}
            print("[capture] stage=reader verdict=%s reason=%s" % (v["verdict"], v["reason"]), flush=True)
        else:
            stage = "judge"
            v, info = judge(frame, part, book, calib, det, allow_auto=allow_auto)
        rows = info.get("rows", []) or []
        out["vobj"], out["rows"] = v, rows
        out["verdict"] = v.get("verdict", VERDICT_UNK)
        out["reason"] = v.get("reason", "")
        print("[capture] stage=judge ok verdict=%s reason=%s" % (out["verdict"], out["reason"]),
              flush=True)
        stage = "annotate"
        annot = annotate_frame(frame, rows, v, extra="部件=%s 路径=%s" % (part or "-", info.get("path")))
        print("[capture] stage=annotate ok %s" % (annot.shape,), flush=True)
        stage = "save"
        d = save_shot(shots_dir, frame, annot, v, info, scope)
        out["shot_dir"] = d
        out["ok"] = True
        print("[capture] stage=save ok -> %s" % d, flush=True)
    except Exception as e:                                             
        out["error"] = "%s: %s" % (type(e).__name__, e)
        print("[capture] stage=%s 失败: %s" % (stage, out["error"]), flush=True)
        traceback.print_exc()

        try:
            fb = "/tmp/afh03_shots_fallback"
            os.makedirs(fb, exist_ok=True)
            p = os.path.join(fb, time.strftime("fail_%Y%m%d_%H%M%S.jpg"))
            cv2.imwrite(p, frame)
            out["shot_dir"] = fb
            print("[capture] 兜底已把原图存到 %s" % p, flush=True)
        except Exception:                                              
            pass
    return out

def _draw_dbg(img, layout, dbg):
    """★ 可见的点击反馈：taps 计数 + 最近一次 tap 的屏幕坐标 + 命中按钮 + 触摸设备名。"""
    if not dbg:
        return
    W, H = layout["canvas"]["w"], layout["canvas"]["h"]
    xy = dbg.get("xy")
    txt = "taps=%d %s 命中=%s  %s" % (dbg.get("taps", 0),
                                      ("(%d,%d)" % xy) if xy else "(未点过)",
                                      dbg.get("hit") or "-", dbg.get("dev") or "")
    x0 = int(W * 0.30)
    _card(img, [x0, H - 24, W - 8, H - 4], (18, 20, 24), 1.0)
    draw_text(img, txt[:64], (x0 + 6, H - 8), scale=0.45, color=(120, 220, 140))
    if xy:
        cx, cy = int(xy[0]), int(xy[1])
        cv2.circle(img, (cx, cy), 18, (0, 255, 255), 2)
        cv2.line(img, (cx - 26, cy), (cx + 26, cy), (0, 255, 255), 1)
        cv2.line(img, (cx, cy - 26), (cx, cy + 26), (0, 255, 255), 1)

FLOW_BUTTON = {"id": "flow", "label": "流程检测", "action": "flow", "style": "alt"}

SA_BTN = [800, 478, 1000, 528]
SA_SPEC = {"id": "summary_all", "label": "总   结", "rect": list(SA_BTN),
           "action": "summary_all", "style": "alt", "font_scale": 0.62}

def _page1_specs(layout):
    """page1 按钮表：capture/wave/flow 等宽三列 + 右上方【总结】；其余按钮（退出）原样保留。"""
    pg = page(layout, "page1")
    specs = list(pg.get("buttons", []))
    by_id = {b.get("id"): b for b in specs}
    if "flow" in by_id or "capture" not in by_id or "wave" not in by_id:
        return specs + [dict(SA_SPEC)]
    cap, wav = by_id["capture"], by_id["wave"]
    x0 = min(int(cap["rect"][0]), int(wav["rect"][0]))
    x1 = max(int(cap["rect"][2]), int(wav["rect"][2]))
    y0 = min(int(cap["rect"][1]), int(wav["rect"][1]))
    y1 = max(int(cap["rect"][3]), int(wav["rect"][3]))
    gap = 23
    w = (x1 - x0 - 2 * gap) // 3
    out = []
    for i, b in enumerate((cap, wav, FLOW_BUTTON)):
        nb = dict(b)
        nb["rect"] = [x0 + i * (w + gap), y0, x0 + i * (w + gap) + w, y1]
        out.append(nb)
    out.extend(b for b in specs if b.get("id") not in ("capture", "wave"))
    out.append(dict(SA_SPEC))
    return out

def _buttons(img, layout, pg, active_id=""):
    """★ 画按钮：**几何仍严格取自 layout 的 rect**（返回值给触摸命中用，两边同一 rect）。

    美化只改"怎么涂"：圆角 + 1px 描边 + 轻投影 + 主/次按钮明显区分 + 文字真正居中。
    """
    C = layout["colors"]
    fs = layout.get("font_scale", {})
    R = layout.get("radius", {})
    rb = int(R.get("button", 12))
    drawn = []
    _specs = _page1_specs(layout) if pg.get("id") == "page1" else pg.get("buttons", [])
    for b in _specs:
        rect = b["rect"]
        x0, y0, x1, y1 = [int(v) for v in rect]
        primary = b.get("style") == "primary"
        bg = C["button"] if primary else C["button_alt"]
        fg = C["button_text"] if primary else C["button_alt_text"]
        edge = C.get("button_edge_primary" if primary else "button_edge")
        if b["id"] == active_id:
            bg = tuple(min(255, int(c * 1.18)) for c in bg)
        if C.get("shadow") is not None:
            _rrect_fill(img, (x0, y0 + 4, x1, y1 + 4), C["shadow"], rb)
        if edge is not None:
            _rrect_fill(img, (x0 - 1, y0 - 1, x1 + 1, y1 + 1), edge, rb + 1)
        _rrect_fill(img, (x0, y0, x1, y1), bg, rb)
        sc = float(b.get("font_scale", fs.get("button", 1.0)))
        _text_center(img, b.get("label", b["id"]), rect, sc, fg, th=2)
        drawn.append((b, rect))
    return drawn

def draw_page1(layout, frame, toast="", warn="", dbg=None, err="", marker_txt=""):
    """页面1「故障检测」= 深色卡片仪表风。

    ★ 本函数**只负责画**：入参全沿用调用方给的现有数据（frame/marker_txt/toast/err），
      不做任何检测、不改任何状态、不加任何新数据源（时间只是 strftime 读系统钟）。
    """
    C = layout["colors"]; fs = layout.get("font_scale", {})
    pg = page(layout, "page1")
    W, H = layout["canvas"]["w"], layout["canvas"]["h"]
    R = layout.get("radius", {})
    tb = layout.get("topbar") or {}
    bar_h = int(tb.get("h", 92))
    img = np.full((H, W, 3), C["bg"], np.uint8)
    _grad_v(img, (0, 0, W, H), C["bg"], C.get("bg_bottom", C["bg"]))

    _grad_v(img, (0, 0, W, bar_h), C["title_bar"], C.get("title_bar2", C["title_bar"]))
    cv2.line(img, (0, bar_h), (W - 1, bar_h), C.get("accent", C["dim"]), 2, lineType=cv2.LINE_AA)
    _rrect_fill(img, (24, 32, 31, 84), C.get("accent", C["title_text"]), 3)
    draw_text(img, pg.get("title", ""), (40, 78),
              scale=fs.get("title_p1", fs.get("title", 1.9)), color=C["title_text"], th=2)

    chip = (272, 30, 700, 82)
    has_m = bool(marker_txt)
    _rrect_fill(img, chip, C.get("chip_bg", C["card"]), int(R.get("pill", 26)))
    _dot(img, chip[0] + 24, (chip[1] + chip[3]) // 2, 7, C["ok"] if has_m else C.get("unk", C["dim"]))
    draw_text(img, _fit_text("标记  " + (marker_txt or "未识别（把标记牌对准摄像头）"),
                             chip[2] - chip[0] - 52, fs.get("chip", 0.44)),
              (chip[0] + 42, chip[1] + 34), scale=fs.get("chip", 0.44),
              color=C["text"] if has_m else C.get("unk", C["dim"]), th=1)

    mode = (716, 32, 812, 80)
    _rrect_fill(img, mode, C.get("chip_bg", C["card"]), int(R.get("pill", 24)))
    _dot(img, mode[0] + 22, (mode[1] + mode[3]) // 2, 6, C["ok"])
    draw_text(img, "实时", (mode[0] + 38, mode[1] + 31), scale=fs.get("chip", 0.44),
              color=C["ok"], th=1)
    clock = time.strftime("%H:%M")
    try:
        cw, _ch = text_size(clock, fs.get("clock", 0.62))
    except Exception:                                                  
        cw = 60
    draw_text(img, clock, (908 - int(cw), 74), scale=fs.get("clock", 0.62),
              color=C["title_text"], th=1)

    pv = [int(v) for v in pg["preview"]]
    rpv = int(R.get("preview", 10))
    _rrect_panel(img, pv, C.get("preview_bg", (14, 15, 18)), C.get("preview_frame", C["dim"]), rpv)
    _fit(img, frame, pv, label=("正在取流…" if frame is None else ""), bg=C.get("preview_bg"))
    _round_corners(img, pv, rpv, C.get("preview_frame", C["dim"]))
    _corner_marks(img, pv, C.get("accent", C["dim"]), inset=12, ln=22, t=2)

    sb = pg.get("sidebar") or {}
    if sb.get("rect"):
        srect = [int(v) for v in sb["rect"]]
        _rrect_panel(img, srect, C.get("card", (39, 30, 24)),
                     C.get("card_edge", C["dim"]), int(R.get("card", 14)))
        sx = srect[0] + 24
        sy = srect[1] + 56
        draw_text(img, sb.get("title", ""), (sx, sy), scale=fs.get("side", 0.5),
                  color=C["text"], th=1)
        cv2.line(img, (sx, sy + 14), (sx + 62, sy + 14), C.get("accent", C["dim"]), 2,
                 lineType=cv2.LINE_AA)
        sy += 52
        for lab, ck in (sb.get("legend") or []):
            _dot(img, sx + 7, sy - 7, 7, C.get(ck, C["dim"]))
            draw_text(img, lab, (sx + 26, sy), scale=fs.get("side", 0.5), color=C["text"], th=1)
            sy += 44
        sy += 4
        cv2.line(img, (sx - 12, sy), (srect[2] - 26, sy), C.get("card_edge", C["dim"]), 1)
        sy += 34
        draw_text(img, sb.get("hint_title", "操作提示"), (sx, sy),
                  scale=fs.get("small", 0.42), color=C["dim"], th=1)
        sy += 30

        lines = sb.get("hint_lines") or _wrap_cjk(pg.get("hint", ""), srect[2] - sx - 20,
                                                  fs.get("side", 0.5))
        for ln in lines:
            draw_text(img, ln, (sx, sy), scale=fs.get("side", 0.5), color=C["text"], th=1)
            sy += 30
        if sb.get("note"):
            draw_text(img, sb["note"], (sx, srect[3] - 26), scale=fs.get("small", 0.42),
                      color=C["dim"], th=1)

    _buttons(img, layout, pg)

    msg, mcol = "", None
    if err:
        msg, mcol = "！" + str(err), C["bad"]
    elif toast:
        msg, mcol = str(toast), C.get("unk", C["dim"])
    elif warn:
        msg, mcol = str(warn), C.get("unk", C["dim"])
    if msg:
        _text_center(img, _fit_text(msg, 940, 0.52), (24, 496, 1000, 526), 0.52, mcol, th=1)
    return img

def draw_page2(layout, still, vobj, toast="", dbg=None, err="", marker_txt=""):
    C = layout["colors"]; fs = layout.get("font_scale", {})
    pg = page(layout, "page2")
    W, H = layout["canvas"]["w"], layout["canvas"]["h"]
    img = np.full((H, W, 3), C["bg"], np.uint8)
    _card(img, [0, 0, W, 76], C["title_bar"], 1.0)
    _center_text(img, pg.get("title", ""), W / 2, 58, fs.get("title", 1.9), C["title_text"], th=2)
    if marker_txt:
        draw_text(img, marker_txt[:38], (12, 34), scale=0.52, color=(120, 220, 140))
    _fit(img, still, pg["preview"], label="（没有静止图）")
    v = (vobj or {}).get("verdict", VERDICT_UNK)
    bg = C["ok"] if v == VERDICT_OK else (C["bad"] if v == VERDICT_BAD else C["unk"])
    _card(img, pg["verdict"], bg, 1.0)
    x0, y0, x1, y1 = [int(t) for t in pg["verdict"]]

    _center_text(img, v, (x0 + x1) / 2, y0 + int((y1 - y0) * 0.66),
                 fs.get("verdict", 2.1), C["verdict_text"], th=3)

    _card(img, pg["reason"], C["card"] if "card" in C else (40, 43, 48), 1.0)
    rx0, ry0, rx1, ry1 = [int(t) for t in pg["reason"]]
    reason = (vobj or {}).get("reason") or "（无依据）"
    rscale = float(fs.get("reason", 0.72))
    rmaxw = max(80, (rx1 - 12) - (rx0 + 12))        
    ty = ry0 + 36
    if v == VERDICT_UNK:

        draw_text(img, "未判定原因", (rx0 + 12, ry0 + 24), scale=0.58, color=C["unk"], th=1)
        ty = ry0 + 48
    lines = _wrap_cjk(reason, rmaxw, rscale)        
    if len(lines) > 4:
        lines = lines[:4]
        lines[-1] = _fit_text(lines[-1] + "…", rmaxw, rscale)
    step = 30 if v != VERDICT_UNK else 27
    for i, ln in enumerate(lines):
        draw_text(img, ln, (rx0 + 12, ty + i * step), scale=rscale, color=C["text"], th=1)
    if pg.get("hint"):

        _center_text(img, _fit_text(pg["hint"], W - 80, fs.get("body", 0.5)),
                     W / 2, pg["preview"][1] - 22, fs.get("body", 0.5), C["dim"])
    _buttons(img, layout, pg)
    if toast:
        _center_text(img, toast[:60], W / 2, H - 92, 0.55, C["text"])
    _draw_dbg(img, layout, dbg)
    if err:
        _card(img, [8, H - 56, W - 8, H - 30], C["bad"], 1.0)
        draw_text(img, ("⚠ " + err)[:70], (14, H - 34), scale=0.55, color=(255, 255, 255), th=1)
    return img

def draw_qa(layout, cur, toast=""):
    """cur = QAFlow.current()；返回 (img, btns)，btns 可直接给 _hit()。"""
    C = layout["colors"]
    W, H = layout["canvas"]["w"], layout["canvas"]["h"]
    img = np.full((H, W, 3), C["bg"], np.uint8)
    _grad_v(img, (0, 0, W, H), C["bg"], C.get("bg_bottom", C["bg"]))
    _grad_v(img, (0, 0, W, 92), C["title_bar"], C.get("title_bar2", C["title_bar"]))
    cv2.line(img, (0, 92), (W - 1, 92), C.get("accent", C["dim"]), 2, lineType=cv2.LINE_AA)

    draw_text(img, "问答确认", (150, 68), scale=0.90, color=C["title_text"], th=2)
    draw_text(img, "进度 %s" % cur["ui"]["progress"], (306, 66), scale=0.52,
              color=C["dim"], th=1)
    chip = (430, 32, 600, 80)
    _rrect_fill(img, chip, C.get("chip_bg", C["card"]), 24)
    _center_text(img, ("%s %s" % (cur["ui"]["part_chip"], cur["ui"]["route_chip"])).strip(),
                 (chip[0] + chip[2]) / 2, 66, 0.55, C["accent"], th=1)
    cat = (616, 32, 840, 80)
    _rrect_fill(img, cat, C.get("chip_bg", C["card"]), 24)
    _center_text(img, cur["ui"].get("category_chip", ""), (cat[0] + cat[2]) / 2, 66,
                 0.44, C["dim"], th=1)

    qr = [24, 104, 1000, 318]
    _rrect_panel(img, qr, C.get("card", (39, 31, 24)), C.get("card_edge", C["dim"]), 14)
    draw_text(img, _fit_text(cur["ui"]["flow"], 940, 0.46),
              (qr[0] + 24, qr[1] + 34), scale=0.46, color=C["dim"], th=1)
    lines = _wrap_cjk(cur["ui"]["question"], qr[2] - qr[0] - 48, 0.90)
    if len(lines) > 3:
        lines = lines[:3]
        lines[-1] = _fit_text(lines[-1] + "…", qr[2] - qr[0] - 48, 0.90)
    ty = qr[1] + 90
    for ln in lines:
        draw_text(img, ln, (qr[0] + 24, ty), scale=0.90, color=C["text"], th=2)
        ty += 44

    nr = [24, 330, 1000, 432]
    _rrect_fill(img, nr, C.get("chip_bg", C["card"]), 12)
    nlines = _wrap_cjk(cur["ui"]["normal"], nr[2] - nr[0] - 40, 0.55)
    for i, ln in enumerate(nlines[:2]):
        draw_text(img, ln, (nr[0] + 20, nr[1] + 34 + i * 30), scale=0.55,
                  color=C["ok"], th=1)

    _vis = cur.get("vision") or {}
    if _vis.get("displays"):
        _parts = []
        for _d in _vis["displays"]:
            _parts.append("%s%s" % (_d.get("label") or _d.get("key"),
                                    _d.get("text") or ("未读数" if not _d.get("valid") else "?")))
        _sug = _vis.get("suggested_label") or ""
        _line = "七段码实测：" + " ｜ ".join(_parts)
        if _vis.get("phase") or _sug:
            _line += " → %s相电压 %s" % (_vis.get("phase") or "?", _sug or "未判定")
        _col = (C["ok"] if _vis.get("suggested_answer") == "done"
                else (C["bad"] if _sug else C["dim"]))
        draw_text(img, _fit_text(_line, nr[2] - nr[0] - 40, 0.46),
                  (nr[0] + 20, nr[1] + 82), scale=0.46, color=_col, th=1)
        if not _vis.get("mapping_confirmed"):
            draw_text(img, _fit_text("（表-相位映射待现场确认，以操作员确认为准）",
                                     nr[2] - nr[0] - 40, 0.40),
                      (nr[0] + 20, nr[1] + 100), scale=0.40, color=C["dim"], th=1)

    if cur.get("skip_suggested"):
        _rrect_fill(img, [24, 442, 1000, 478], C.get("chip_bg", C["card"]), 10)
        draw_text(img, _fit_text("建议跳过：" + cur["skip_reason"], 940, 0.46),
                  (36, 468), scale=0.46, color=C["unk"], th=1)

    btns = []
    for b in cur["ui"]["buttons"]:
        rect = [int(v) for v in b["rect"]]
        bg = C["ok"] if b["tone"] == "ok" else (
            C["bad"] if b["tone"] == "bad" else C["button_alt"])
        fg = C["verdict_text"] if b["tone"] in ("ok", "bad") else C["button_alt_text"]
        _rrect_fill(img, rect, bg, 14)

        _sug = str((cur.get("vision") or {}).get("suggested_answer") or "")
        _bval = str(b.get("value") or b.get("action") or "").rsplit(":", 1)[-1]
        if _sug and _bval == _sug:
            cv2.rectangle(img, (rect[0] - 3, rect[1] - 3), (rect[2] + 3, rect[3] + 3),
                          C.get("accent", C["ok"]), 3, lineType=cv2.LINE_AA)
        _text_center(img, b.get("label_plain", b["label"]), rect, 0.95, fg, th=2)
        btns.append(({"id": b["id"], "label": b["label_plain"], "rect": rect,
                      "action": b["action"]}, rect))

    for b in (cur["ui"]["skip_button"], cur["ui"]["back_button"]):
        if not b:                     
            continue
        rect = [int(v) for v in b["rect"]]
        _rrect_fill(img, rect, C.get("button_alt", C["card"]), 12)
        _text_center(img, b["label_plain"], rect, 0.55, C["button_alt_text"], th=1)
        btns.append(({"id": b["id"], "label": b["label_plain"], "rect": rect,
                      "action": b["action"]}, rect))
    if toast:
        _center_text(img, toast[:60], W / 2, 100, 0.44, C["text"])
    return img, btns

FLOW_EVIDENCE_DIR = "/userdata/afh03_shots/flow"
FLOW_PREVIEW = [624, 192, 996, 360]

SESSION_DIR = os.environ.get("AFH03_SESSION_DIR", "/userdata/afh03_shots/sessions")
SUMMARY_ENABLED = os.environ.get("AFH03_SUMMARY", "1") not in ("0", "false", "False")
SUMMARY_MODULE_ERR = "⚠ 总结模块不可用"

def load_flow_steps(cli_path=""):
    """读 steps.json；返回 (doc, path)。找不到就抛异常（调用方 toast 提示）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [cli_path, os.environ.get("AFH03_STEPS", ""),
             os.path.join(HERE, "engine", "steps.json"),
             os.path.join(here, "qa", "steps.json"),
             os.path.join(HERE, "soc_vision", "qa", "steps.json"),
             os.path.join(HERE, "..", "雷达判据", "engine", "steps.json")]
    for p in cands:
        if p and os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                doc = json.load(f)
            steps = doc.get("steps") or []
            if not steps:
                raise RuntimeError("steps.json 里没有 steps：%s" % p)
            return doc, os.path.abspath(p)
    raise RuntimeError("找不到 steps.json（试过：%s）" % "；".join(x for x in cands if x))

def _flow_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")

def _flow_clean(s):
    """判据库 check_item 里有换行（flow 5/6）；画之前压成单行，避免多行位图盖住上一行。"""
    return re.sub(r"\s+", " ", str(s or "")).strip()

def _flow_panel_label(st):
    """从步骤名取面板标签：'（操显）…' / '(领显)…' / '（Z31…）' 等；无则空。"""
    import re as _re
    name = str((st or {}).get("step_name") or "")
    m = _re.match(r"^\s*[（(]([^）)]{1,12})[）)]", name)
    return (m.group(1).strip() if m else "")

def _flow_module_key(st):
    """模块/面板分组键：部位 + 路别 + 面板标签；空部位不合并。"""
    part = str((st or {}).get("part") or "").strip().lower()
    if not part:
        return ""
    route = str((st or {}).get("route") or "").strip().lower()
    label = _flow_panel_label(st)
    return "%s|%s|%s" % (part, route, label)

def _flow_merge_items(dst, src, key):
    seen = {key(x) for x in dst if key(x)}
    for x in src or []:
        k = key(x)
        if k and k in seen:
            continue
        if k:
            seen.add(k)
        dst.append(dict(x))

def _group_flow_modules(steps):
    """把同模块步骤合并为 module step；保留非影像步骤的顺序与相对位置。"""
    if os.environ.get("AFH03_FLOW_GROUP", "1").strip() == "0":
        return list(steps)
    groups, order = {}, []
    for i, st in enumerate(steps):
        k = _flow_module_key(st)
        if not k:
            continue
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append((i, st))
    if not groups:
        return list(steps)

    merged = {}
    used_ids = set()
    for k in order:
        arr = groups[k]
        if len(arr) <= 1:
            continue
        first = dict(arr[0][1])
        first_id = str(first.get("step_id") or "")
        vis, qa, scope, audio, unc = [], [], [], [], []
        modalities = set()
        original_ids = []
        for _, st in arr:
            original_ids.append(str(st.get("step_id") or ""))
            _flow_merge_items(vis, st.get("vision_items"),
                              lambda x: x.get("evidence_field") or x.get("check_item"))
            _flow_merge_items(qa, st.get("qa_items"),
                              lambda x: "%s|%s" % (x.get("qa_id"), x.get("route") or ""))
            _flow_merge_items(scope, st.get("scope_items"),
                              lambda x: x.get("field") or x.get("item_id") or x.get("check_item"))
            _flow_merge_items(audio, st.get("audio_items"),
                              lambda x: x.get("field") or x.get("item_id") or x.get("check_item"))
            _flow_merge_items(unc, st.get("unclassified_items"),
                              lambda x: x.get("check_item") or x.get("item"))
            modalities.update(st.get("modalities") or [])
        part = str(first.get("part") or "").strip().lower()
        label = _flow_panel_label(first)
        name_prefix = ("%s %s" % (part.upper(), label)).strip()
        _base_id = "MOD-" + re.sub(r"[^0-9a-zA-Z]+", "-", k).strip("-")
        _sid = _base_id
        _n = 2
        while _sid in used_ids:
            _sid = "%s-%d" % (_base_id, _n)
            _n += 1
        used_ids.add(_sid)
        first.update({
            "step_id": _sid,
            "seq": min(int(x.get("seq") or 0) for _, x in arr) or first.get("seq"),
            "step_name": "%s 模块整体判定（%d 项影像 / %d 项问答）"
                         % (name_prefix, len(vis), len(qa)),
            "flow_name": "%s 模块" % name_prefix,
            "method_text": "拍照（模块整体）" if vis else first.get("method_text"),
            "modalities": sorted(modalities),
            "vision_items": vis, "qa_items": qa,
            "scope_items": scope, "audio_items": audio,
            "unclassified_items": unc,
            "_module_photo": bool(vis),
            "_module_steps": original_ids,
        })
        merged[k] = first

    out, placed = [], set()
    for st in steps:
        k = _flow_module_key(st)
        if k in merged:
            if k in placed:
                continue
            out.append(merged[k])
            placed.add(k)
            continue
        if k in groups and len(groups[k]) > 1:

            continue
        out.append(st)
    return out

def _new_flow(doc, steps_path):
    ts = time.strftime("%Y%m%d_%H%M%S")
    sid = "S" + ts
    return {"doc": doc, "steps": _group_flow_modules(doc["steps"]), "steps_path": steps_path, "idx": 0,
            "answers": {}, "shots": {}, "evidence": [], "started_at": _flow_iso(),
            "path": os.path.join(FLOW_EVIDENCE_DIR, "flow_evidence_%s.json" % ts),
            "session_id": sid,                                  
            "session_dir": os.path.join(SESSION_DIR, sid),      
            "still": None, "freeze_until": 0.0, "saved": 0}

def _flow_step(flow):
    return flow["steps"][flow["idx"]]

def _flow_answers(flow, step):
    return flow["answers"].setdefault(step["step_id"], {})

def _flow_cur_qa(flow, step):
    ans = _flow_answers(flow, step)
    for q in step.get("qa_items") or []:
        if q.get("qa_id") not in ans:
            return q
    return None

QA_SCREEN_JSON = "qa_items_screen.json"
_PART_QA_CACHE: Dict[str, Any] = {}

def _qa_screen_path() -> str:
    if "path" in _PART_QA_CACHE:
        return _PART_QA_CACHE["path"]
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.environ.get("AFH03_QA_SCREEN", ""),
             os.path.join(here, "qa", QA_SCREEN_JSON),
             os.path.join(HERE, "soc_vision", "qa", QA_SCREEN_JSON),
             os.path.join(here, "..", "soc_vision", "qa", QA_SCREEN_JSON),
             "/home/rock/afh03_board_setup/soc_vision/qa/" + QA_SCREEN_JSON]
    path = next((os.path.abspath(p) for p in cands if p and os.path.isfile(p)), "")
    _PART_QA_CACHE["path"] = path
    return path

def _part_qa_index() -> Dict[str, List[Dict[str, Any]]]:
    """屏幕题库：部位 → 题列表（按 seq 升序）。读不到就空。"""
    if "screen" in _PART_QA_CACHE:
        return _PART_QA_CACHE["screen"]
    idx: Dict[str, List[Dict[str, Any]]] = {}
    p = _qa_screen_path()
    if p:
        try:
            with open(p, encoding="utf-8") as f:
                doc = json.load(f)
            for it in doc.get("items") or []:
                part = str(it.get("part") or "").strip().lower()
                if not part:
                    continue
                idx.setdefault(part, []).append(dict(it, _src="qa_items_screen"))
            for v in idx.values():
                v.sort(key=lambda q: int(q.get("seq") or 0))
            print("[partqa] 屏幕题库 %s：%d 题 / %d 个部位（%s）"
                  % (os.path.basename(p), sum(len(v) for v in idx.values()), len(idx),
                     "、".join("%s=%d" % (k, len(v)) for k, v in sorted(idx.items()))),
                  flush=True)
        except Exception as e:                                     
            print("[partqa] 读 %s 失败：%s" % (p, e), flush=True)
    else:
        print("[partqa][warn] 找不到 %s ⇒ 主页拍照只能靠 steps.json 兜底找题" % QA_SCREEN_JSON,
              flush=True)
    _PART_QA_CACHE["screen"] = idx
    return idx

def _part_qa_steps() -> Dict[str, List[Dict[str, Any]]]:
    """steps.json 兜底：部位 → 该部位各步的 qa_items。

    ★ 2026-10-27（二路）：去重键从 ``qa_id`` 改成 ``(qa_id, route)``。
      现场数据里 LQ001–LQ005 的**一路/二路是两条独立副本**（同 qa_id、不同 route，
      分属 9(7-I)-3 与 10(7-II)-3 这类步骤）。旧键只按 qa_id 去重 ⇒ **二路副本被丢**，
      于是"识别到 Z14 二路"却只能问到一路的 LQ。改键后两路各自成题（route 仍照原样）。
    """
    if "steps" in _PART_QA_CACHE:
        return _PART_QA_CACHE["steps"]
    out: Dict[str, List[Dict[str, Any]]] = {}
    try:
        doc, _p = load_flow_steps("")
        for st in doc.get("steps") or []:
            part = str(st.get("part") or "").strip().lower()
            if not part:
                continue
            lst = out.setdefault(part, [])
            have = {(str(x.get("qa_id")), _route_norm(x.get("route"))) for x in lst}
            for q in st.get("qa_items") or []:
                qid = str(q.get("qa_id") or "")
                if not qid:
                    continue
                _k = (qid, _route_norm(q.get("route")))
                if _k in have:
                    continue
                have.add(_k)
                lst.append(dict(q, _src="steps.json", step_id=st.get("step_id")))
    except Exception as e:                                         
        print("[partqa] steps.json 兜底不可用：%s" % e, flush=True)
    _PART_QA_CACHE["steps"] = out
    return out

def _qa_owner_map() -> Dict[str, str]:
    """qa_id → 屏幕题库里的**归属部位**（P0-5 屏幕改绑后：SQ001–SQ009/SQ012–SQ015→z16）。"""
    if "owners" in _PART_QA_CACHE:
        return _PART_QA_CACHE["owners"]
    owners: Dict[str, str] = {}
    for _part, items in (_part_qa_index() or {}).items():
        for q in items:
            qid = str(q.get("qa_id") or "")
            if qid and qid not in owners:
                owners[qid] = _part
    _PART_QA_CACHE["owners"] = owners
    return owners

def _part_qa_items(part: str) -> List[Dict[str, Any]]:
    """该部位的题。

    * 成对路别部位（z11/z12/z14/z15）：**合并**屏幕题库 + steps.json 兜底（按
      ``(qa_id, route)`` 去重；屏幕题以 ``qa_items_screen.json`` 的 part 为准 ⇒
      steps 里跨部位重复的 SQ 副本不再挂到 z11。旧实现"屏幕库有该部位就不看
      steps.json"会让 z14 **只剩 SQ010/SQ011**，QA011/QA012/LQ001/LQ002 全丢）。
    * 其它部位：保持原优先级（屏幕库有该部位 → 只用屏幕库；否则 steps 兜底）——
      不扩大改动面（例如 z16 的屏幕题口径不受影响）。
    """
    part = str(part or "").strip().lower()
    if not part:
        return []
    if part not in ROUTE_PAIRED:
        got = _part_qa_index().get(part)
        if got:
            return got
        return _part_qa_steps().get(part) or []
    owners = _qa_owner_map()
    out: List[Dict[str, Any]] = []
    have = set()
    for q in (_part_qa_index().get(part) or []):
        qid = str(q.get("qa_id") or "")
        if qid and (qid, _route_norm(q.get("route"))) in have:
            continue
        if qid:
            have.add((qid, _route_norm(q.get("route"))))
        out.append(q)
    _skip = 0
    for q in (_part_qa_steps().get(part) or []):
        qid = str(q.get("qa_id") or "")
        _own = owners.get(qid) or ""
        if _own and _own != part:          
            _skip += 1
            continue
        if qid and (qid, _route_norm(q.get("route"))) in have:
            continue
        if qid:
            have.add((qid, _route_norm(q.get("route"))))
        out.append(q)
    if _skip:
        print("[partqa] 部位 %s：跳过 %d 题屏幕题（qa_items_screen 归属别的部位，不重复问）"
              % (part, _skip), flush=True)
    return out

def _part_qa_route_filter(items, route) -> List[Dict[str, Any]]:
    """按路别筛题：保留**同路**题 + **空路别**题；无同路题时**退回全部**（绝不丢题）。"""
    r = _route_norm(route)
    items = list(items or [])
    if not r:
        return items
    same = [q for q in items if _route_norm(q.get("route")) == r]
    neut = [q for q in items if not _route_norm(q.get("route"))]
    if not same:
        print("[partqa] 路别 %s 没有专属题 → 保留全部 %d 题（不丢题）" % (r, len(items)),
              flush=True)
        return items
    return same + neut

def _part_qa_pick(r: dict) -> Tuple[str, List[Dict[str, Any]]]:
    """按"识别出的部位 + 路别"选题：需要人工确认的屏幕项对应的题排在最前，其余按题号。

    ★ 2026-10-27（二路）：识别到路别（I/II）时**只留同路题 + 空路别题**；
      没有同路题则退回全部（旧行为，绝不因路别而丢题）。
      ⇒ z11 I → QA045/QA048–QA052（6 题）；z11 II → QA056–QA060（5 题）；
        z14 II → QA012 + LQ001/LQ002 的**二路副本**；z15 II → QA014 + LQ003–LQ005 二路副本。
    """
    r = r or {}
    _p = r.get("part") or {}
    part = str(_p.get("part") or _p.get("part_used") or "").strip().lower()
    route = _result_route(r)
    items = _part_qa_items(part)

    

    if part in ROUTE_PAIRED:
        items = _part_qa_route_filter(items, route)
    if not items:
        return "", []
    need = set()
    for e in (r.get("vision_evidence") or []):
        if not isinstance(e, dict):
            continue
        if str(e.get("decided_by") or "") != "qa_required":
            continue
        for k in ("item_no", "field", "screen_key"):
            if e.get(k):
                need.add(str(e[k]))

    def _rank(q):
        hit = (str(q.get("screen_key") or "") in need
               or str(q.get("evidence_field") or "") in need
               or str(q.get("item_no") or "") in need
               or str(q.get("qa_id") or "") in need)
        return (0 if hit else 1, int(q.get("seq") or 999))

    return part, sorted(items, key=_rank)

def _flow_done(flow, step):
    if step.get("qa_items"):
        return len(_flow_answers(flow, step)) >= len(step["qa_items"])
    if step.get("vision_items"):
        return bool(flow["shots"].get(step["step_id"]))
    return False

def _flow_pending_vision(flow, step):
    shots = flow["shots"].get(step["step_id"]) or []
    i = len(shots)
    if step.get("_module_photo"):

        if not shots:
            return 0, (step.get("vision_items") or [{}])[0]
        return None, None
    if i < len(step.get("vision_items") or []):
        return i, step["vision_items"][i]
    return None, None

def _flow_value(v):
    """问答值 -> fusion 口径（done→normal；skipped 原样）。"""
    return {"done": "normal"}.get(v, v)

def _atomic_text(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)

def _atomic_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)

def _flow_session_docs(flow, summary_res=None):
    """本轮 session 元信息 + evidence/v1 包装（板端 sessions/<id>/ 数据契约）。"""
    sid = flow.get("session_id") or ("S" + time.strftime("%Y%m%d_%H%M%S"))
    sess = dict(summary_res.get("session") or {}) if summary_res else {}
    done = [s["step_id"] for s in (flow.get("steps") or []) if _flow_done(flow, s)]
    sess_doc = {
        "schema": "session/1.0", "producer": "ui_kiosk.flow",
        "id": sid,
        "started_at": sess.get("started_at") or flow.get("started_at") or _flow_iso(),
        "saved_at": _flow_iso(),
        "source_file": flow.get("path") or "",
        "steps_total": len(flow.get("steps") or []),
        "steps_answered": len(done),
        "evidence_total": len(flow.get("evidence") or []),
        "session_dir": flow.get("session_dir") or "",
    }
    if summary_res is not None:
        sess_doc["evidence_used"] = (summary_res.get("session") or {}).get("evidence_used")
        sess_doc["summary"] = {"schema": summary_res.get("schema"),
                               "verdict": summary_res.get("verdict"),
                               "conclusion": summary_res.get("conclusion"),
                               "generated_at": summary_res.get("generated_at"),
                               "counts": summary_res.get("counts") or {}}
    ev_doc = {"schema": "evidence/v1", "producer": "ui_kiosk.flow",
              "session_id": sid,
              "started_at": sess_doc["started_at"], "saved_at": sess_doc["saved_at"],
              "source_file": flow.get("path") or "",
              "evidence": list(flow.get("evidence") or [])}
    return sid, sess_doc, ev_doc

def _write_session_snapshot(flow):
    """每次证据落盘时**顺带**刷新 sessions/<id>/{session,evidence}.json（失败只打印，不抛）。"""
    try:
        sid, sess_doc, ev_doc = _flow_session_docs(flow)
        sdir = flow.get("session_dir") or os.path.join(SESSION_DIR, sid)
        flow["session_dir"] = sdir
        os.makedirs(sdir, exist_ok=True)
        _atomic_json(os.path.join(sdir, "session.json"), sess_doc)
        _atomic_json(os.path.join(sdir, "evidence.json"), ev_doc)
        return True
    except Exception as e:                                            
        print("[summary] session 快照失败: %s" % e, flush=True)
        return False

def _write_summary_files(flow, res):
    """summary.json / summary.txt / session.json / evidence.json 全部原子写。"""
    try:
        sid, sess_doc, ev_doc = _flow_session_docs(flow, res)
        sdir = flow.get("session_dir") or os.path.join(SESSION_DIR, sid)
        flow["session_dir"] = sdir
        os.makedirs(sdir, exist_ok=True)
        _atomic_json(os.path.join(sdir, "evidence.json"), ev_doc)
        _atomic_json(os.path.join(sdir, "summary.json"), res)
        _atomic_text(os.path.join(sdir, "summary.txt"), res.get("text") or "")
        _atomic_json(os.path.join(sdir, "session.json"), sess_doc)   
        print("[summary] 落盘 %s/（verdict=%s evidence=%d）"
              % (sdir, res.get("verdict"), len(flow.get("evidence") or [])), flush=True)
        return True
    except Exception as e:                                            
        print("[summary] summary 落盘失败: %s" % e, flush=True)
        return False

def _flow_save(flow):
    """把已收集证据整包落盘（原子写）。失败只打日志，不抛。"""
    try:
        d = os.path.dirname(flow["path"])
        os.makedirs(d, exist_ok=True)
        done = [s["step_id"] for s in flow["steps"] if _flow_done(flow, s)]
        doc = {
            "schema": "flow_evidence/v1",
            "producer": "ui_kiosk.flow",
            "started_at": flow["started_at"],
            "saved_at": _flow_iso(),
            "source": {"steps": os.path.basename(flow["steps_path"]),
                       "qa": "qa_items.json"},
            "steps_total": len(flow["steps"]),
            "current_step": flow["idx"] + 1,
            "current_step_id": _flow_step(flow)["step_id"],
            "counts": {
                "evidence": len(flow["evidence"]),
                "qa": sum(1 for e in flow["evidence"] if e.get("modality") == "qa"),
                "vision": sum(1 for e in flow["evidence"] if e.get("modality") == "vision"),
                "steps_answered": len(done),
            },
            "answered_steps": done,
            "evidence": flow["evidence"],
        }
        tmp = flow["path"] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        os.replace(tmp, flow["path"])
        flow["saved"] = int(flow.get("saved", 0)) + 1
        _write_session_snapshot(flow)      
        return True
    except Exception as e:                                            
        print("[flow] 证据落盘失败: %s" % e, flush=True)
        return False

def _flow_ev_key(ev):
    """证据幂等键：qa → (step_id, qa_id)；part → (step_id)；vision → (step_id, field, item_id)。

    ★ 2026-10-21（P2-3）：跨步同 field（LQ001 操显/领显、16 组 evidence_field）**不能**合并，
      因为它们是不同部位的不同证据；同一步里重复写同一颗灯/同一题才需要去重。
    """
    ev = ev or {}
    step = str(ev.get("step_id") or "")
    mod = str(ev.get("modality") or "")
    if mod == "qa":
        return ("qa", step, str(ev.get("qa_id") or ev.get("item_id") or ev.get("field") or ""))
    if mod == "part":
        return ("part", step)
    return ("vision", step, str(ev.get("field") or ""), str(ev.get("item_id") or ""))

def _flow_add_evidence(flow, ev):
    """写一条本步证据：按幂等键**替换**旧记录，绝不重复追加（同颗灯不再写 2 条）。"""
    key = _flow_ev_key(ev)
    kept = [e for e in flow["evidence"] if _flow_ev_key(e) != key]
    n_rep = len(flow["evidence"]) - len(kept)
    kept.append(ev)
    flow["evidence"] = kept
    if n_rep:
        print("[flow] 证据去重 step=%s：同键(qa_id/field+item_id)替换 %d 条旧记录（幂等）"
              % (ev.get("step_id"), n_rep), flush=True)
    return _flow_save(flow)

MAX_INFER_EV = 24          

_Z15_FIELD_CANON = {
    "(led_indicator)_z15_fuse": "(led_indicator)(operator_display)_z15_display_2A_fuse",
    "(led_indicator)_z15_power": "(led_indicator)(operator_display)_z15_display_power",
    "(led_indicator)_z15_modem_power": "(led_indicator)(operator_display)_z15_modem_power",
    "(led_indicator)_z15_reset": "(led_indicator)(operator_display)_z15_display_reset",
}

def _canon_z15_field(field):
    """把 Z15 旧合成字段名映射到判据库命名；其它字段原样返回。"""
    f = str(field or "")
    return _Z15_FIELD_CANON.get(f, f)

def _infer_verdict(concl) -> str:
    """board_infer 结论 → 页面三档；**结果页与流程页共用这一处映射**（用词与结果页一致）。"""
    st = str((concl or {}).get("state") or "unknown")
    return {"ok": "正常", "bad": "异常"}.get(st, "未判定")

def _flow_latest_infer_verdict(flow, step_id):
    """流程页「判定：X」的唯一来源 = 结果页 board_infer 写下的 (vision_infer) 证据。

    返回 (verdict, ev)；还没判定完返回 ("", None) ⇒ 页面显示「判定中…」。
    ★ 2026-10-21（P2-2）：不再显示 run_capture 的即时判定——两条链对同一张照片曾给出
      相反结论（流程页"故障" / 结果页"正常"，4/4 步全矛盾，见否定性报告 A2-11）。
    """
    for ev in reversed(flow.get("evidence") or []):
        if str(ev.get("step_id") or "") != str(step_id):
            continue
        if not str(ev.get("field") or "").startswith("(vision_infer)"):
            continue
        v = {"normal": "正常", "abnormal": "异常"}.get(str(ev.get("value") or ""), "未判定")
        return v, ev
    return "", None

def _flow_sync_verdict(flow, step_id, r):
    """结果页判定完成 → 把本步「即时判定」证据统一到同一结论（单一判定源）。"""
    v = _infer_verdict((r or {}).get("conclusion"))
    val = {"正常": "normal", "异常": "abnormal", "故障": "abnormal"}.get(v)
    if not val:
        return 0
    _part = (r or {}).get("part") or {}
    _part_used = str(_part.get("part_used") or _part.get("part") or "").strip().lower()
    n = 0
    for s in (flow.get("shots") or {}).get(step_id) or []:
        if s.get("verdict") != v:
            s["verdict_before_unify"] = s.get("verdict")
            s["verdict"] = v
            s["verdict_source"] = "board_infer"
            n += 1
    for ev in flow.get("evidence") or []:
        if (str(ev.get("step_id") or "") == str(step_id)
                and ev.get("modality") == "vision"
                and str(ev.get("item_id") or "") == "camera:%s" % step_id
                and not str(ev.get("field") or "").startswith("(vision_infer)")):

            

            

            if str(ev.get("value") or "") in ("undetermined", "unknown", ""):
                continue
            if _part_used and str(ev.get("part") or "").strip().lower() != _part_used:
                continue
            if ev.get("value") != val:
                ev["value_before_unify"] = ev.get("value")
                ev["value"] = val
                ev["note"] = (ev.get("note") or "") + "（已统一为结果页 board_infer 结论）"
                n += 1
    if n:
        print("[flow] 统一判定源 step=%s：流程页即时判定 → %s"
              "（与结果页同一份 board_infer 结论，改 %d 条）" % (step_id, v, n), flush=True)
    return n

def _flow_merge_infer(flow, st, r, meta):
    """把 board_infer 的结果合并进**本步证据**，一次落盘。

    写入三类证据（全部带 ``part`` / ``route`` / ``step_id``）：

    1. ``modality="part"``   —— 部位识别（部位 + 置信 + 候选）
    2. ``modality="vision"`` —— 本步判定结论（field=``(vision_infer)_step_N``）
    3. ``modality="vision"`` —— **逐个灯/屏** N 条（每条一个灯位/画面，带 rule/位次/应为）
    """
    r = r or {}
    part = r.get("part") or {}
    concl = r.get("conclusion") or {}
    part_used = part.get("part_used") or part.get("part") or st.get("part") or ""
    ts = _flow_iso()
    base = {"ts": ts, "source": "ui_kiosk.flow", "part": part_used,

            
            "route": _route_norm(part.get("route")) or _step_route(st),
            "flow_no": st.get("flow_no"), "flow_name": st.get("flow_name"),
            "step_id": st["step_id"], "step_name": st.get("step_name"),
            "shot_dir": meta.get("shot_dir") or ""}
    new = []

    if part.get("part"):
        ev = dict(base)
        ev.update({
            "modality": "part",
            "field": "(part)_step_%s" % st["step_id"],
            "item_id": "camera:part:%s" % part.get("part"),
            "value": part.get("part"),
            "confidence": round(float(part.get("confidence") or 0.0), 3),
            "note": "部位识别：%s（%s，置信 %.0f%%）"
                    % (part.get("display") or part.get("part"),
                       part.get("decision") or "-",
                       float(part.get("confidence") or 0.0) * 100),
            "evidence": "part_recognizer：%s；候选 %s"
                        % (part.get("decision") or "-",
                           "、".join("%s %.2f" % (c.get("part"), c.get("score") or 0)
                                    for c in (part.get("candidates") or [])[:3])),
            "need_confirm": bool(part.get("need_confirm")),
            "part_source": part.get("part_source") or "",
        })
        new.append(ev)

    val = {"ok": "normal", "bad": "abnormal"}.get(concl.get("state") or "", "undetermined")
    conf_map = {"ok": 0.85, "bad": 0.85}
    ev = dict(base)
    ev.update({
        "modality": "vision",
        "field": "(vision_infer)_step_%s" % st["step_id"],
        "item_id": "camera:infer:%s" % st["step_id"],
        "value": val,
        "confidence": conf_map.get(concl.get("state") or "", 0.0),
        "note": "拍照判定（%s）：%s" % (part_used or "-", concl.get("text") or "未判定"),
        "evidence": "%s；%s" % (concl.get("text") or "未判定", concl.get("why") or ""),
        "n_ok": concl.get("n_ok"), "n_bad": concl.get("n_bad"),
        "undetermined": (r.get("undetermined") or {}).get("n"),
    })
    new.append(ev)

    items = (r.get("evidence_items") or [])[:MAX_INFER_EV]
    _z15_fix_n = 0
    for it in items:
        ev = dict(base)
        _raw_field = it.get("field") or "(vision)_lamp"
        _field = _canon_z15_field(_raw_field)
        if _field != _raw_field:
            _z15_fix_n += 1
        ev.update({
            "modality": "vision",
            "field": _field,
            "item_id": it.get("item_id") or "camera:lamp",
            "value": it.get("value"),
            "confidence": round(float(it.get("confidence") or 0.0), 3),
            "note": it.get("note") or "",
            "evidence": it.get("evidence") or "",
            "check_item": it.get("check_item") or "",
            "rule": it.get("rule") or "",
            "position": it.get("position") or "",
            "expect": it.get("expect") or "",
            "match": it.get("match"),
            "kind": it.get("kind") or "",
        })
        new.append(ev)

    if _z15_fix_n:
        print("[flow] Z15 field 归一 %d 条 → 判据库命名（vision_rules 生成侧未改，"
              "本次禁改；落证据前统一）" % _z15_fix_n, flush=True)
    if not new:
        return 0

    _uniq, _seen = [], set()
    for _ev in new:
        _k = _flow_ev_key(_ev)
        if _k in _seen:
            continue
        _seen.add(_k)
        _uniq.append(_ev)
    _dup = len(new) - len(_uniq)
    _old_n = len(flow["evidence"])
    flow["evidence"] = [e for e in flow["evidence"] if _flow_ev_key(e) not in _seen]
    _rep = _old_n - len(flow["evidence"])
    flow["evidence"].extend(_uniq)
    ok = _flow_save(flow)
    print("[flow] 合并判定证据 step=%s：部位 %d + 结论 1 + 逐条 %d = %d 条"
          "（丢弃重复 %d，替换旧记录 %d，落盘=%s）"
          % (st["step_id"], 1 if part.get("part") else 0, len(items), len(_uniq),
             _dup, _rep, ok), flush=True)
    return len(_uniq)

def _attach_multimodal_result(r: dict, meta=None) -> dict:
    """★ 2026-10-29：结果页多模态——视觉证据行与 QA 行并存，QA 仍是主判据。

    当前先接 Z18（7 段码）：rows 增加左/中/右三块表的读数行和相电压判定行；
    QA 答完后 _apply_partqa 只追加问答行，不删除这些视觉行；结论由 QA 决定。
    """
    if not isinstance(r, dict):
        return r
    try:
        part = str((r.get("part") or {}).get("part") or "").strip().lower()
        if part not in ("z18", "g18"):
            return r
        meta = meta or {}
        path = ""
        sd = str(meta.get("shot_dir") or "")
        if sd:
            path = os.path.join(sd, "full.jpg")
        if not path or not os.path.exists(path):
            p0 = str(r.get("photo") or "")
            path = p0 if (p0 and os.path.exists(p0)) else ""
        if not path:
            return r
        from soc_vision import g18_seg7 as _G18
        sid = str(meta.get("step_id") or "")
        phase = {"3-1": "A", "3-2": "B", "3-3": "C"}.get(sid, "A")
        try:
            if str(meta.get("qa_id") or "").upper() in ("QA002", "QA003", "QA004"):
                phase = {"QA002": "A", "QA003": "B", "QA004": "C"}[
                    str(meta.get("qa_id")).upper()]
        except Exception:
            pass
        pack = _G18.z18_phase_pack(path, phase)
        if not pack:
            return r
        old = [x for x in (r.get("rows") or []) if not (x.get("kind") == "seg7")]
        r["rows"] = list(pack.get("rows") or []) + old
        ve = list(r.get("vision_evidence") or [])
        ve.extend(pack.get("evidence_items") or [])
        r["vision_evidence"] = ve
        r["multimodal"] = {
            "z18": {"phase": (pack.get("phase") or ""),
                    "mapping_confirmed": bool(pack.get("mapping_confirmed")),
                    "warnings": pack.get("warnings") or [],
                    "visual_conclusion": (pack.get("conclusion") or {}).get("text") or ""},
        }
        print("[multimodal] Z18 结果页：七段码 rows=%d 视觉证据=%d（QA 仍为主判据）"
              % (len(pack.get("rows") or []), len(pack.get("evidence_items") or [])), flush=True)
    except Exception as e:                                       
        print("[multimodal] Z18 视觉行挂接失败: %s" % e, flush=True)
    return r

def _result_ready(job, meta, flow=None):
    """后台判定线程完成：取结果；若来自流程页则合并证据（只做一次）。"""
    meta["merged"] = True
    r = _degrade_result(getattr(job, "result", None) or {},
                        meta.get("marker_label") or "")
    r = _apply_screen_qa(r)          
    r = _attach_multimodal_result(r, meta)   
    r = _apply_partqa(r, (meta.get("part_qa") or {}))   
    r = _apply_route(r, meta)        
    if meta.get("mode") == "flow" and flow is not None:
        try:

            _sid = str(meta.get("step_id") or "")
            _st = next((s for s in (flow.get("steps") or [])
                        if str(s.get("step_id") or "") == _sid), None) or _flow_step(flow)
            _flow_merge_infer(flow, _st, r, meta)
            if _flow_sync_verdict(flow, _st["step_id"], r):
                _flow_save(flow)
        except Exception as e:                                         
            print("[flow] 合并判定证据失败: %s" % e, flush=True)
            import traceback as _tb
            _tb.print_exc()
    elif meta.get("mode") == "page1":

        
        try:
            _sa_add_page1_photo(r, meta)
        except Exception as e:                                         
            print("[summary_all] 主页拍照证据并入失败（不影响结果页）: %s" % e, flush=True)
    return r

def _flow_button(img, C, btns, bid, rect, label, action, primary=False, tone="", scale=0.72):
    x0, y0, x1, y1 = [int(v) for v in rect]
    bg = C["button"] if primary else C["button_alt"]
    fg = C["button_text"] if primary else C["button_alt_text"]
    if tone == "ok":
        bg, fg = C["ok"], (255, 255, 255)
    elif tone == "bad":
        bg, fg = C["bad"], (255, 255, 255)
    elif tone == "unk":
        bg, fg = C["unk"], (255, 255, 255)
    _rrect_fill(img, (x0, y0, x1, y1), bg, 10)
    _text_center(img, label, (x0, y0, x1, y1), scale, fg, th=2)
    btns.append(({"id": bid, "label": label, "rect": [x0, y0, x1, y1],
                  "action": action}, [x0, y0, x1, y1]))

def _flow_vcolor(C, verdict):
    v = str(verdict or "")
    return C["ok"] if v == "正常" else (C["bad"] if ("故障" in v or "异常" in v) else C["unk"])

def draw_flow(layout, flow, frame=None, toast="", err=""):
    """流程页（1024×600）：顶栏进度 + 步骤卡 + 拍照/本步问答 + 实时预览 + 上一步/下一步。

    纯渲染：不改任何状态（按钮 rect 与触摸命中共用同一批）。
    """
    C = layout["colors"]
    W, H = layout["canvas"]["w"], layout["canvas"]["h"]
    img = np.full((H, W, 3), C["bg"], np.uint8)
    _grad_v(img, (0, 0, W, H), C["bg"], C.get("bg_bottom", C["bg"]))
    btns = []
    st = _flow_step(flow)
    total, idx = len(flow["steps"]), flow["idx"]
    ans = _flow_answers(flow, st)
    done = _flow_done(flow, st)
    shots = flow["shots"].get(st["step_id"]) or []
    freeze = flow.get("still") is not None and time.time() < flow.get("freeze_until", 0.0)

    _grad_v(img, (0, 0, W, 72), C["title_bar"], C.get("title_bar2", C["title_bar"]))
    cv2.line(img, (0, 72), (W - 1, 72), C.get("accent", C["dim"]), 2, lineType=cv2.LINE_AA)
    _flow_button(img, C, btns, "back", [16, 14, 132, 58], "返回", "flow:back", scale=0.55)
    draw_text(img, "流程检测", (146, 52), scale=0.82, color=C["title_text"], th=2)
    _rrect_fill(img, (282, 16, 468, 64), C.get("chip_bg", C["card"]), 22)
    _center_text(img, "第 %d / %d 步" % (idx + 1, total), 375, 50, 0.5, C["accent"], th=1)
    _rrect_fill(img, (476, 16, 620, 64), C.get("chip_bg", C["card"]), 22)
    _n_done = sum(1 for s in flow["steps"] if _flow_done(flow, s))
    _center_text(img, "已答 %d 步" % _n_done, 548, 50, 0.44,
                 C["ok"] if _n_done else C["dim"], th=1)
    _rrect_fill(img, (624, 16, 880, 64), C.get("chip_bg", C["card"]), 22)

    draw_text(img, _fit_text("部位 %s" % (_part_disp(st.get("part"),
                                                     _step_route(st)) or "-"), 232, 0.38),
              (636, 42), scale=0.38, color=C["text"], th=1)
    draw_text(img, _fit_text(st.get("method_text") or "-", 232, 0.34),
              (636, 59), scale=0.34, color=C["dim"], th=1)

    _flow_button(img, C, btns, "summary", SUMMARY_BTN, "总结", "flow:summary",
                 primary=bool(SUMMARY_ENABLED), scale=0.52)

    _rrect_panel(img, (16, 76, 1008, 176), C.get("card", (39, 31, 24)),
                 C.get("card_edge", C["dim"]), 14)
    draw_text(img, _fit_text("%s｜%s" % (st.get("flow_no", ""),
                                          _flow_clean(st.get("flow_name"))),
                             640, 0.42), (32, 104), scale=0.42, color=C["dim"], th=1)
    if toast:
        draw_text(img, _fit_text(_flow_clean(toast), 230, 0.42), (700, 104), scale=0.42,
                  color=C.get("accent", C["text"]), th=1)
    if done:
        draw_text(img, "已答", (944, 104), scale=0.42, color=C["ok"], th=1)
    lines = _wrap_cjk(_flow_clean(st.get("step_name")), 940, 0.62)
    if len(lines) > 2:
        lines = lines[:2]
        lines[-1] = _fit_text(lines[-1] + "…", 940, 0.62)
    lines = lines or [""]
    y0 = 148 if len(lines) == 1 else 138
    for i, ln in enumerate(lines):
        draw_text(img, ln, (32, y0 + i * 26), scale=0.62, color=C["text"], th=2)

    _rrect_panel(img, (16, 180, 600, 472), C.get("card", (39, 31, 24)),
                 C.get("card_edge", C["dim"]), 14)
    _pend_i, _pend_it = _flow_pending_vision(flow, st)
    can_shot = bool(st.get("vision_items")) and (_pend_i is not None)
    if st.get("_module_photo"):
        cap_lab = ("拍照（整模块）" if can_shot else
                   ("已拍（整模块）" if st.get("vision_items") else "本步无拍照项"))
    else:
        cap_lab = ("拍  照" if can_shot else
                   ("本步已拍完" if st.get("vision_items") else "本步无拍照项"))
    _flow_button(img, C, btns, "capture", [28, 192, 588, 250], cap_lab, "flow:capture",
                 primary=can_shot, scale=0.95)
    _rrect_fill(img, (28, 258, 588, 304), C.get("chip_bg", C["card"]), 10)
    if shots:
        last = shots[-1]

        _iv, _iev = _flow_latest_infer_verdict(flow, st["step_id"])
        _vtext = ("判定：%s" % _iv) if _iv else "判定中…（约 20~30 秒）"
        col = _flow_vcolor(C, _iv) if _iv else C["unk"]
        _dot(img, 46, 281, 7, col)
        draw_text(img, _fit_text(_vtext, 380, 0.55),
                  (62, 290), scale=0.55, color=col, th=2)
        draw_text(img, ("整模块已拍" if (st.get("_module_photo") and shots)
                        else ("拍摄 %d/%d" % (len(shots), len(st["vision_items"])))),
                  (470, 289), scale=0.44, color=C["dim"], th=1)
    else:
        draw_text(img, "判定：尚未拍照" if st.get("vision_items") else "判定：本步无拍摄项",
                  (40, 289), scale=0.5, color=C["dim"], th=1)
        if st.get("scope_items"):
            draw_text(img, "波形 %d 项" % len(st["scope_items"]), (470, 289),
                      scale=0.44, color=C["dim"], th=1)

    qa = _flow_cur_qa(flow, st)
    q_total = len(st.get("qa_items") or [])
    if qa is not None:
        q_pos = len(ans) + 1
        draw_text(img, "本步问题 %d/%d" % (q_pos, q_total), (40, 326), scale=0.44,
                  color=C["dim"], th=1)
        qlines = _wrap_cjk(_flow_clean(qa.get("question") or qa.get("check_item")), 548, 0.56)
        if len(qlines) > 2:
            qlines = qlines[:2]
            qlines[-1] = _fit_text(qlines[-1] + "…", 548, 0.56)
        for i, ln in enumerate(qlines):
            draw_text(img, ln, (40, 354 + i * 26), scale=0.56, color=C["text"], th=2)
        draw_text(img, _fit_text("正常：" + (_flow_clean(qa.get("normal")) or "-"), 548, 0.42),
                  (40, 402), scale=0.42, color=C["ok"], th=1)
        opts = list(qa.get("options") or [])

        _has_skip_opt = any(str(o.get("value")) in ("skipped", "undetermined") for o in opts)
        nbtn = len(opts) + (0 if _has_skip_opt else 1)
        gap, x0, x1, by0, by1 = 8, 28, 588, 410, 460
        w = (x1 - x0 - gap * (nbtn - 1)) // nbtn
        _bs = 0.62 if nbtn <= 4 else 0.52
        for i, o in enumerate(opts):
            tone = o.get("tone") if o.get("tone") in ("ok", "bad") else ""
            _flow_button(img, C, btns, "ans%d" % i,
                         [x0 + i * (w + gap), by0, x0 + i * (w + gap) + w, by1],
                         o.get("label_plain") or o.get("label") or o.get("value", ""),
                         "flow:answer:%s" % o.get("value", ""), tone=tone, scale=_bs)
        if not _has_skip_opt:
            _flow_button(img, C, btns, "skip",
                         [x0 + len(opts) * (w + gap), by0,
                          x0 + len(opts) * (w + gap) + w, by1],
                         "跳过", "flow:skip", scale=0.58)
    elif q_total:
        draw_text(img, "本步问答已完成（%d/%d）" % (len(ans), q_total), (40, 352),
                  scale=0.58, color=C["ok"], th=2)
        k = 0
        for q in st["qa_items"]:
            rec = ans.get(q.get("qa_id")) or {}
            draw_text(img, _fit_text("%s → %s" % (_flow_clean(
                (q.get("subject") or q.get("check_item") or ""))[:18],
                                      rec.get("label") or rec.get("value") or "?"),
                                     548, 0.44), (40, 382 + k * 24), scale=0.44,
                      color=C["text"], th=1)
            k += 1
            if k >= 3:
                break
    else:
        draw_text(img, "本步无问答项", (40, 352), scale=0.52, color=C["dim"], th=1)
        info = []
        if st.get("vision_items"):
            info.append("拍照：对准后点上方【拍照】，判定结果在本页显示")
        if st.get("scope_items"):
            info.append("波形：%d 项（走主页【波形检测】页采集）" % len(st["scope_items"]))
        if st.get("audio_items"):
            info.append("声音：%d 项（当前未启用）" % len(st["audio_items"]))
        if st.get("unclassified_items"):
            info.append("待定：%d 项（判据库未写采集方式）" % len(st["unclassified_items"]))
        for i, ln in enumerate(info[:3]):
            draw_text(img, _fit_text(ln, 548, 0.44), (40, 384 + i * 26), scale=0.44,
                      color=C["text"], th=1)

    _rrect_panel(img, (612, 180, 1008, 472), C.get("card", (39, 31, 24)),
                 C.get("card_edge", C["dim"]), 14)
    _rrect_panel(img, FLOW_PREVIEW, C.get("preview_bg", (20, 14, 10)),
                 C.get("preview_frame", C["dim"]), 10)
    draw_text(img, ("刚拍的照片（3 秒后回实时）" if freeze else "实时画面") +
              ("  ·  整模块 1 张" if st.get("_module_photo") else
               ("  ·  拍摄 %d/%d" % (len(shots), len(st["vision_items"])) if st.get("vision_items") else "")),
              (624, 382), scale=0.42, color=C["dim"], th=1)
    _rrect_fill(img, (624, 388, 996, 464), C.get("chip_bg", C["card"]), 10)
    if shots:
        last = shots[-1]

        _iv, _iev = _flow_latest_infer_verdict(flow, st["step_id"])
        if _iv:
            _center_text(img, _iv, 810, 426, 0.95, _flow_vcolor(C, _iv), th=2)
            _why = ((_iev or {}).get("evidence") or (_iev or {}).get("note") or "-")
            draw_text(img, _fit_text("依据：" + _flow_clean(_why), 350, 0.4),
                      (636, 452), scale=0.4, color=C["text"], th=1)
        else:
            _center_text(img, "判定中…", 810, 420, 0.8, C["unk"], th=2)
            draw_text(img, "约 20~30 秒，完成后与结果页同一结论", (640, 452),
                      scale=0.38, color=C["dim"], th=1)
    else:
        _center_text(img, "尚未拍照", 810, 424, 0.7, C["dim"])
        draw_text(img, "拍照后在这里显示判定结果", (660, 452), scale=0.4, color=C["dim"], th=1)

    _flow_button(img, C, btns, "prev", [16, 486, 300, 580], "上一步", "flow:prev", scale=0.8)
    _flow_button(img, C, btns, "next", [308, 486, 592, 580], "下一步", "flow:next",
                 primary=True, scale=0.8)
    _flow_button(img, C, btns, "save", [600, 486, 800, 580], "保存", "flow:save", scale=0.7)
    draw_text(img, "证据 %d 条" % len(flow["evidence"]), (812, 512), scale=0.42,
              color=C["text"], th=1)
    draw_text(img, _fit_text("已存 %s" % os.path.basename(flow["path"]), 192, 0.34),
              (812, 536), scale=0.34, color=C["dim"], th=1)
    if err:
        draw_text(img, _fit_text("！" + str(err), 192, 0.38), (812, 560), scale=0.38,
                  color=C["bad"], th=1)
    return img, btns

SUMMARY_BTN = [888, 14, 1008, 58]           
SUMMARY_BACK = [16, 508, 492, 588]          
SUMMARY_AGAIN = [508, 508, 1008, 588]       

def _summary_px(scale):
    return max(9, int(round(float(scale) * 26)))

def _summary_line_h(scale):
    return int(round(_summary_px(scale) * 1.5)) + 2

def _summary_error(reason=SUMMARY_MODULE_ERR, detail=""):
    """模块缺失/调用崩溃的降级页数据（绝不抛异常）。"""
    return {"schema": "session_summary/error", "verdict": "undetermined",
            "conclusion": "undetermined", "counts": {}, "top_faults": [],
            "session": {}, "page": {"state": "summary", "lines": []},
            "_ui_error": str(reason or SUMMARY_MODULE_ERR),
            "_ui_detail": str(detail or "")}

def _sum_pack(prefix, items, scale, maxw=944):
    """把多条异常项按「项」整条换行（不在括号/词中间断行）。"""
    lines, cur = [], prefix
    for it in items:
        it = str(it or "").strip()
        if not it:
            continue
        joiner = "" if cur == prefix else " / "
        cand = cur + joiner + it
        try:
            too_wide = text_size(cand, scale)[0] > maxw
        except Exception:                                              
            too_wide = False
        if cur != prefix and too_wide:
            lines.append(cur)
            cur = "    " + it
        else:
            cur = cand
    if cur.strip():
        lines.append(cur)
    return "\n".join(lines) or prefix

def _summary_blocks(summary, C):
    """summary → [(text, scale, color, max_lines)]：只按行前缀选**样式**，文案不改写。

    ★ 板端中文字体（wqy/Pango）没有 ❌🎯✅ 字形（实测 unknown_glyphs=1）⇒ 显示层
      等价替换为 ×/◆/√；summary.txt 里仍是原文（不改落盘内容）。
    """
    lines = list(((summary or {}).get("page") or {}).get("lines") or [])
    abnormals = (summary or {}).get("abnormals") or []
    top = (summary or {}).get("top_faults") or []
    blocks = []
    for raw in lines:
        s = str(raw or "")
        if not s.strip():
            continue
        if "【返回】" in s and "【再拍一轮】" in s:      
            continue
        for _k, _v in (("❌", "×"), ("🎯", "◆"), ("✅", "√")):
            if s.startswith(_k):
                s = _v + s[len(_k):]
                break
        s = s.replace("⚠️", "⚠")
        if s.startswith("×"):

            if abnormals:
                _items = [_flow_clean(a.get("text")) for a in abnormals[:8]]
                if len(abnormals) > 8:
                    _items.append("…等 %d 项" % len(abnormals))
                s = _sum_pack("× 异常项：", _items, 0.46)
            blocks.append((s, 0.46, C["bad"], 3))
            continue
        scale, color, maxl = 0.46, C["text"], 2
        if s.startswith("本轮共拍"):
            scale, color, maxl = 0.58, C["title_text"], 1
        elif s.startswith("◆"):
            scale, color, maxl = 0.5, C["accent"], 1
        elif s.lstrip().startswith(tuple("①②③")):
            scale, color, maxl = 0.46, C["text"], 3
            _i = "①②③".find(s.lstrip()[0])          
            _c = float((top[_i].get("confidence") if 0 <= _i < len(top) else 0) or 0)
            color = C["ok"] if _c >= 0.60 else C["unk"]

            try:
                if text_size(s, scale)[0] > 944:
                    _head, _sep, _tail = s.partition("｜支撑")
                    if _sep:
                        s = _head + "\n     " + _sep + _tail
            except Exception:                                          
                pass
        elif s.startswith("√"):
            scale, color, maxl = 0.62, C["ok"], 2
        elif s.startswith("⚠"):
            scale, color, maxl = 0.44, C["unk"], 2
        elif s.lstrip().startswith("（以上只是候选"):
            scale, color, maxl = 0.4, C["dim"], 2
        elif s.startswith("·"):
            scale, color, maxl = 0.42, C["dim"], 2
        blocks.append((s, scale, color, maxl))
    _ml = (summary or {}).get("model_locate") or {}
    if _ml.get("ok"):
        _mlb = [("模型推测（仅参考，不替代规则）", 0.44, C["accent"], 1),
                (str(_ml.get("line") or ""), 0.42, C["text"], 2)]
        _pos = 1 if blocks else 0
        blocks[_pos:_pos] = _mlb
    return blocks

def draw_summary(layout, summary, toast="", err=""):
    """「本轮总结」页（1024×600）：只渲染 summarize() 结果，不取流、不改状态。"""
    C = layout["colors"]
    W, H = layout["canvas"]["w"], layout["canvas"]["h"]
    img = np.full((H, W, 3), C["bg"], np.uint8)
    _grad_v(img, (0, 0, W, H), C["bg"], C.get("bg_bottom", C["bg"]))
    btns = []
    summary = summary or {}
    sess = summary.get("session") or {}
    counts = summary.get("counts") or {}
    items = counts.get("items") or {}
    verdict = str(summary.get("verdict") or "undetermined")

    _grad_v(img, (0, 0, W, 72), C["title_bar"], C.get("title_bar2", C["title_bar"]))
    cv2.line(img, (0, 72), (W - 1, 72), C.get("accent", C["dim"]), 2, lineType=cv2.LINE_AA)
    _flow_button(img, C, btns, "back", [16, 14, 132, 58], "返回", "summary:back", scale=0.55)
    draw_text(img, "流程检测总结", (146, 52), scale=0.76, color=C["title_text"], th=2)
    _rrect_fill(img, (352, 16, 704, 64), C.get("chip_bg", C["card"]), 22)
    _sess_txt = "会话 %s ｜ 证据 %s 条" % (
        sess.get("id") or "-",
        sess.get("evidence_total", items.get("total", 0)) or 0)
    draw_text(img, _fit_text(_sess_txt, 336, 0.4), (366, 48), scale=0.4,
              color=C["accent"], th=1)
    _badge = {"converged": ("√ 已收敛", C["ok"]),
              "partial": ("◐ 部分收敛", C["unk"])}.get(verdict, ("⚠ 未判定", C["unk"]))

    
    if int((summary.get("field_match") or {}).get("unmatched") or 0):
        _badge = ("⚠ 未判定（field 未命中）", C["unk"])
    _rrect_fill(img, (712, 16, 1008, 64), _badge[1], 22)
    _center_text(img, _badge[0], 860, 50, 0.46, (255, 255, 255), th=1)

    _rrect_panel(img, (16, 80, 1008, 500), C.get("card", (39, 31, 24)),
                 C.get("card_edge", C["dim"]), 14)
    _err = str(summary.get("_ui_error") or "")
    _empty = str(summary.get("_ui_empty") or "")
    if _err:
        draw_text(img, SUMMARY_MODULE_ERR, (40, 176), scale=0.95, color=C["bad"], th=2)
        _det = str(summary.get("_ui_detail") or "") or "（无更多信息）"
        for _i, _ln in enumerate(_wrap_cjk(_det, 920, 0.44)[:3]):
            draw_text(img, _ln, (40, 226 + _i * 24), scale=0.44, color=C["text"], th=1)
        draw_text(img, "原因：session_summary.py 未部署 / 导入失败 / summarize() 抛异常",
                  (40, 322), scale=0.44, color=C["dim"], th=1)
        draw_text(img, "本轮证据仍保存在 flow_evidence 里（拍照/问答/保存不受影响），修复后可再点【总结】。",
                  (40, 354), scale=0.42, color=C["dim"], th=1)
        draw_text(img, "本页只降级，不影响其它页面；可【返回（继续拍）】或【再拍一轮（清空本轮）】。",
                  (40, 384), scale=0.42, color=C["dim"], th=1)
    elif _empty or (sess.get("evidence_total") or 0) == 0:
        _center_text(img, "本轮还没有拍照记录", 512, 190, 1.0, C["accent"], th=2)
        _center_text(img, "先拍 2~3 个模块，再点【总结】，结论才有依据", 512, 252, 0.5,
                     C["text"], th=1)
        _center_text(img, "⚠ 本轮没有任何可用证据（没有拍照/问答记录）⇒ 不能总结（宁可不判）",
                     512, 302, 0.4, C["unk"], th=1)
        _center_text(img, "（本轮的 evidence 仍是空的：没有可总结的东西，不硬凑结论）",
                     512, 336, 0.38, C["dim"], th=1)
    else:
        _y = 96
        _budget = 456 if (toast or err) else 486
        _normal = str(summary.get("conclusion") or "") == "normal"
        for _text, _scale, _color, _maxl in _summary_blocks(summary, C):
            _lh, _px = _summary_line_h(_scale), _summary_px(_scale)
            _ls = []
            for _seg in str(_text).split("\n"):
                _ls.extend(_wrap_cjk(_seg, 944, _scale))
            if _maxl and len(_ls) > _maxl:
                _ls = _ls[:_maxl]
                _ls[-1] = _fit_text(_ls[-1] + "…", 944, _scale)
            if _normal and _text.startswith("√") and _y + 110 <= _budget:

                _center_text(img, _text, W // 2, _y + 64, 0.95, C["ok"], th=2)
                _center_text(img, "（本轮已拍 %s 个模块 / %s 项正常观测；只代表已拍项目正常，不等于整机全检）"
                              % ((counts.get("modules") or 0), (items.get("normal") or 0)),
                              W // 2, _y + 116, 0.4, C["dim"], th=1)
                _y += 140
                continue
            if _y + len(_ls) * _lh > _budget:
                if _y + _lh <= _budget:
                    draw_text(img, "…（本页放不下，完整内容见 sessions/<id>/summary.txt）",
                              (32, _y + _summary_px(0.38)), scale=0.38, color=C["dim"], th=1)
                break
            for _ln in _ls:
                draw_text(img, _ln, (32, _y + _px), scale=_scale, color=_color,
                          th=2 if _scale >= 0.55 else 1)
                _y += _lh
            _y += 5

    if toast or err:
        _rrect_fill(img, (24, 462, 1000, 498), C.get("chip_bg", C["card"]), 10)
        _msg = ("！" + _flow_clean(err)) if err else _flow_clean(toast)
        draw_text(img, _fit_text(_msg, 940, 0.42), (36, 488), scale=0.42,
                  color=C["bad"] if err else C["accent"], th=1)

    _flow_button(img, C, btns, "back2", SUMMARY_BACK, "返回（继续拍）", "summary:back",
                 scale=0.66)
    _flow_button(img, C, btns, "again", SUMMARY_AGAIN, "再拍一轮（清空本轮）",
                 "summary:again", primary=True, scale=0.66)
    return img, btns

SA_SCOPE_FIELD = "(scope)_freq_hz"
SA_SCOPE_PART = "PD_BOARD"
SA_BACK = [16, 508, 492, 588]        
SA_AGAIN = [508, 508, 1008, 588]     
_APP_START_TS = time.time()          
_SA_SESSION = {"id": "", "dir": ""}

SA_EXTRA = []
SA_EXTRA_MAX = 240
_SA_EXTRA_SEQ = [0]
_SA_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"

def _sa_short(text, n=46):
    s = _flow_clean(text)
    return s if len(s) <= n else s[:max(1, n - 1)] + "…"

def _sa_rows_kb(rows):
    """引擎 kb_rows（判据库**数据行**号，1 基、不含表头）→ 页面显示 **rec#（含表头）**。

    口径（已实读源码复核）：cause_explainer.load_fault_rows() 用
    ``enumerate(csv.DictReader(f), 1)``，所以 kb#N = 数据行 N = CSV rec#(N+1)
    （表头 = rec#1）。页面统一显示 rec#，与项目其它文档的 rec# 对齐，避免差 1 错位。
    """
    out = []
    for r in rows or []:
        try:
            r = int(r or 0)
        except (TypeError, ValueError):
            r = 0
        if r > 0 and r not in out:
            out.append(r)
    return "、".join("rec#%d" % (r + 1) for r in out)

def _sa_rows_for_ev(summary, ev_id):
    """这条现象被哪些判据行解释（从 top_faults[].support 反查，绝不自己编行号）。

    ★ 2026-10-27 复核后：**只保留给候选块/兼容用**，不再用于「发现的问题」行。
    support[].kb_row 是「候选的原因行」，不是「现象本身的判据行」；把两者混在一起，
    会把 4NIC 电源行贴到 Z31 空调电源指示上（field 根本不一致）。
    """
    rows = []
    for c in (summary.get("top_faults") or []):
        for s in (c.get("support") or []):
            if str(s.get("ev_id") or "") != str(ev_id or ""):
                continue
            try:
                r = int(s.get("kb_row") or 0)
            except (TypeError, ValueError):
                r = 0
            if r > 0:
                rows.append(r)
    return sorted(set(rows))

def _sa_ev_maps(summary):
    """ev_id → (field, step_id)，只取引擎公开字段，不自己编。"""
    ef, es = {}, {}
    for grp in ("abnormals", "undetermined", "scope"):
        for a in (summary.get(grp) or []):
            eid = str(a.get("ev_id") or "")
            if not eid:
                continue
            ef[eid] = str(a.get("field") or "")
            es[eid] = str(a.get("step_id") or "")
    return ef, es

def _sa_field_grounded(summary, cand, ev_field):
    """候选的支撑行里是否**至少一条 field 与现象 evidence.field 完全相同**。

    页面层反幻觉门：只有 field 级对应的候选才允许进入「故障范围」；
    仅 abnormal_value 同值匹配（例如所有 off / abnormal）不算——否则会把
    Z99 不存在的假灯匹配到 4NIC 电源行，页面出现具体故障名（实测注入失败）。
    """
    for s in (cand.get("support") or []):
        eid = str(s.get("ev_id") or "")
        ef = ev_field.get(eid, "")
        if ef and str(s.get("kb_field") or "") == ef:
            return True
    return False

def _sa_latest_flow_doc():
    """本次 UI 进程启动后落盘的**最近一份** flow 证据 JSON → (evidence, path)。"""
    best = None
    try:
        for fn in os.listdir(FLOW_EVIDENCE_DIR):
            if not (fn.startswith("flow_evidence_") and fn.endswith(".json")):
                continue
            p = os.path.join(FLOW_EVIDENCE_DIR, fn)
            try:
                mt = os.path.getmtime(p)
            except OSError:
                continue
            if mt < _APP_START_TS - 2.0:          
                continue
            if mt > time.time() + 5.0:             
                continue
            if best is None or mt > best[0]:
                best = (mt, p)
    except Exception as e:                                        
        print("[summary_all] 扫描 %s 失败: %s" % (FLOW_EVIDENCE_DIR, e), flush=True)
        return [], ""
    if best is None:
        return [], ""
    try:
        with open(best[1], encoding="utf-8") as f:
            doc = json.load(f)
        ev = doc.get("evidence") if isinstance(doc, dict) else doc
        return (list(ev) if isinstance(ev, list) else []), best[1]
    except Exception as e:                                        
        print("[summary_all] 读 %s 失败: %s" % (best[1], e), flush=True)
        return [], ""

def _sa_photo_evidences(flow):
    """拍照证据：主页 SA_EXTRA + 内存 flow["evidence"] + 本轮 flow_evidence_*.json。

    2026-10-27 收尾（G-3）：主页【拍照】判定完成后由 ``_sa_add_page1_photo()`` 写进
    ``SA_EXTRA``；这里按 ``_flow_ev_key`` 统一去重（SA_EXTRA 优先，其次内存，最后落盘）。
    """
    extra = [e for e in SA_EXTRA if isinstance(e, dict)]
    mem, disk = [], []
    if isinstance(flow, dict):
        mem = [e for e in (flow.get("evidence") or []) if isinstance(e, dict)]
        p = str(flow.get("path") or "")
        if p and os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                disk.extend((d.get("evidence") if isinstance(d, dict) else d) or [])
            except Exception:                                     
                pass
    _fev, _fpath = _sa_latest_flow_doc()
    disk.extend(_fev)
    seen, out = set(), []
    for src in (extra, mem, disk):
        for e in src:
            if not isinstance(e, dict):
                continue

            

            
            _before = str(e.get("value_before_unify") or "")
            if _before in ("undetermined", "unknown"):
                e = dict(e)
                e["value"] = _before
                e["note"] = (e.get("note") or "") + "（汇总页：原为未判定，不按统一后的异常计入）"
            if str(e.get("modality") or "") not in ("vision", "part", "qa"):
                continue                      
            k = _flow_ev_key(e)
            if k in seen:
                continue
            seen.add(k)
            out.append(e)
    return out

def _sa_add_page1_photo(r, meta=None):
    """主页【拍照】判定完成 → ``resv["evidence_items"]`` 转 A 页 evidence/v1。

    - 每条：part/route/field/value/confidence/note/evidence/check_item/rule/…，
      并补 ``ts/source/step_id/step_name/shot_dir/item_id``（A 页去重/追溯用）。
    - 若这张照片**没有逐条证据**（没识别出灯/屏），再加一条 ``(vision_infer)_page1_*``
      结论证据：A 页仍能盘点「拍了 1 张」并显示判定；有逐条证据时不加，避免整图
      abnormal 把逐灯证据的候选收敛带偏。
    - 存进程级 ``SA_EXTRA``；重启清空。返回写入条数。
    """
    r = r or {}
    meta = dict(meta or {})
    part = r.get("part") or {}
    part_used = str(meta.get("part_use") or part.get("part_used") or part.get("part") or "")
    route = str(meta.get("marker_route") or meta.get("route") or r.get("route") or "")
    shot_dir = str(meta.get("shot_dir") or "")
    _SA_EXTRA_SEQ[0] += 1
    token = "%s_%03d" % (time.strftime("%Y%m%d_%H%M%S"), _SA_EXTRA_SEQ[0])
    step_id = "page1_%s" % token
    ts = _flow_iso()
    added = []
    for i, it in enumerate([x for x in (r.get("evidence_items") or []) if isinstance(x, dict)]):
        try:
            conf = float(it.get("confidence") if it.get("confidence") is not None
                         else (it.get("conf") or 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        added.append({
            "part": str(it.get("part") or part_used or ""),
            "route": str(it.get("route") or route or ""),
            "modality": "vision",
            "field": str(it.get("field") or "(vision)_lamp"),
            "value": it.get("value") if it.get("value") is not None else "undetermined",
            "confidence": round(conf, 3),
            "note": str(it.get("note") or ""),
            "evidence": str(it.get("evidence") or ""),
            "ts": ts, "source": "ui_kiosk.page1",
            "step_id": step_id, "step_name": "主页拍照",
            "item_id": str(it.get("item_id") or ("camera:page1:%s:%d" % (token, i))),
            "check_item": str(it.get("check_item") or ""),
            "rule": str(it.get("rule") or ""),
            "position": str(it.get("position") or ""),
            "expect": str(it.get("expect") or ""),
            "match": it.get("match"),
            "kind": str(it.get("kind") or ""),
            "shot_dir": shot_dir,
        })
    concl = r.get("conclusion") or {}
    _st = str(concl.get("state") or "")
    _val = {"ok": "normal", "bad": "abnormal"}.get(_st, "undetermined")

    
    if (concl or part_used) and not added:
        added.append({
            "part": part_used,
            "route": route,
            "modality": "vision",
            "field": "(vision_infer)_page1_%s" % token,
            "value": _val,
            "confidence": 0.85 if _val != "undetermined" else 0.5,
            "note": "主页拍照判定（%s）：%s" % (part_used or "-", concl.get("text") or "未判定"),
            "evidence": "主页拍照判定：%s；%s" % (concl.get("text") or "未判定",
                                                  concl.get("why") or ""),
            "ts": ts, "source": "ui_kiosk.page1",
            "step_id": step_id, "step_name": "主页拍照",
            "item_id": "camera:infer:page1:%s" % token,
            "shot_dir": shot_dir,
        })
    if not added:
        return 0
    keys = {_flow_ev_key(e) for e in added}
    SA_EXTRA[:] = [e for e in SA_EXTRA if _flow_ev_key(e) not in keys]
    SA_EXTRA.extend(added)
    if len(SA_EXTRA) > SA_EXTRA_MAX:
        del SA_EXTRA[:len(SA_EXTRA) - SA_EXTRA_MAX]
    print("[summary_all] 主页拍照证据并入 A 页：%d 条（进程级 SA_EXTRA，重启清空）"
          % len(added), flush=True)
    return len(added)

def _sa_scope_problem(scope, full=False):
    """波形问题的一句话（只用已有判定词，不解释原因）。"""
    st = str((scope or {}).get("state") or "")
    hz = _fmt_hz(scope.get("hz")) if scope.get("hz") is not None else "—"
    vpp = _fmt_vpp(scope.get("vpp")) if scope.get("vpp") is not None else "—"
    exp = scope.get("expect")
    dev = scope.get("dev")
    if st == "pass":
        s = "频率 %s / 期望 %s / 偏差 %s / Vpp %s ⇒ pass" % (
            hz, _fmt_hz(exp) if exp is not None else "—",
            _fmt_dev(dev) if dev is not None else "—", vpp)
    elif st == "fail":
        s = "频率 %s 超出期望 %s（偏差 %s）⇒ fail" % (
            hz, _fmt_hz(exp) if exp is not None else "—",
            _fmt_dev(dev) if dev is not None else "—")
    elif st == "no_reference":
        s = "频率 %s 不在 28 项期望内 ⇒ 无参考值（库中无此项）" % hz
    elif st == "no_signal":
        s = "无有效频率读数 ⇒ 无信号（no_signal）"
    else:
        s = "波形判定未知"
    if full and st in ("pass", "fail"):
        s += "（Vpp %s，%s）" % (vpp, _sa_short(scope.get("why") or "", 26))
    return s

def _sa_scope_view():
    """波形 → 盘点/问题/evidence 三用视图。只读现有字段（实测/期望/判定）。"""
    res = load_scope_result()
    v = {"ok": False, "state": "", "hz": None, "vpp": None, "expect": None,
         "dev": None, "why": "", "at": "", "name": "", "judge": {},
         "evidence": None, "res": res}
    if not res.get("valid") or not res.get("items"):
        v["why"] = str(res.get("invalid_reason") or res.get("reason")
                       or "本次没有有效波形记录")
        return v
    it = res["items"][0]
    table, _src, _stat = _scope_expect_table()
    j = _scope_judge(it, table)
    st = str(j.get("state") or "")
    v.update(ok=True, state=st, hz=it.get("measured_hz"), vpp=it.get("vpp_v"),
             expect=j.get("expect_hz"), dev=j.get("dev_pct"),
             why=str(j.get("why") or ""), at=str(res.get("measured_at") or res.get("ts") or ""),
             name=str(it.get("name") or it.get("channel") or "CH1"), judge=j)

    
    val = st if st in ("pass", "fail", "no_reference", "no_signal") else "no_signal"
    ev = {
        "part": SA_SCOPE_PART, "route": "", "modality": "scope",
        "field": SA_SCOPE_FIELD, "value": val,
        "confidence": 0.9 if st in ("pass", "fail") else 0.5,
        "note": _sa_scope_problem(v, full=True),
        "evidence": _sa_scope_problem(v, full=True),
        "ts": _flow_iso(), "source": "ui_kiosk.summary_all",
        "item_id": "scope:%s" % v["name"], "check_item": v["name"],
        "step_id": "scope", "step_name": "波形检测",
    }
    if st == "fail":
        ev.update(kind="scope", match=False, expect="pass")
    v["evidence"] = ev
    return v

def _model_judge_scope(scope):
    """模型判断（波形参数判别）：只读、失败降级；规则仍权威。"""
    try:
        _d = os.path.dirname(os.path.abspath(__file__))
        if _d not in sys.path:
            sys.path.insert(0, _d)
        try:
            from . import model_judge as MV
        except Exception:                                     
            import model_judge as MV
    except Exception:                                         
        return None
    try:
        return MV.judge_scope(scope)
    except Exception:                                         
        return None

def _model_judge_locate(evidences):
    """模型故障部位候选排序（推测）：只读、失败降级；规则仍权威。"""
    try:
        _d = os.path.dirname(os.path.abspath(__file__))
        if _d not in sys.path:
            sys.path.insert(0, _d)
        try:
            from . import model_judge as MV
        except Exception:                                     
            import model_judge as MV
    except Exception:                                         
        return None
    try:
        return MV.locate_flow(evidences)
    except Exception:                                         
        return None

def _sa_error(reason, detail=""):
    return {"updated": time.strftime("%H:%M:%S"), "empty": False,
            "_error": str(reason or SUMMARY_MODULE_ERR), "_detail": str(detail or ""),
            "photo": {"n": 0, "parts": 0, "abn": 0, "undet": 0},
            "scope": {"ok": False, "why": ""}, "summary": {}, "counts": {},
            "problems": [], "ranges": [], "unexplained": [], "notice": "",
            "ranges_note": "", "mode": ""}

def _sa_persist(sa, sid, evs):
    """把本轮汇总用的证据与结果原子落盘（供 PC 交叉核对）。"""
    if not sid:
        return ""
    try:
        d = os.path.join(SESSION_DIR, sid)
        os.makedirs(d, exist_ok=True)
        _atomic_json(os.path.join(d, "summary_all_evidence.json"),
                     {"schema": "evidence/v1", "producer": "ui_kiosk.summary_all",
                      "session": {"id": sid}, "evidence": evs})
        if sa.get("summary"):
            _atomic_json(os.path.join(d, "summary_all.json"), sa["summary"])
        return d
    except Exception as e:                                        
        print("[summary_all] 落盘失败: %s" % e, flush=True)
        return ""

def _sa_build(evidences=None, flow=None, persist=True):
    """构建汇总页数据。evidences 给定时（离屏验收）只信这份，不读相机/波形文件。"""
    updated = time.strftime("%H:%M:%S")
    if evidences is None:
        scope = _sa_scope_view()
        photo = _sa_photo_evidences(flow)
        all_ev = list(photo)
        if scope.get("evidence"):
            all_ev.append(scope["evidence"])
    else:
        _raw = [e for e in (evidences or []) if isinstance(e, dict)]

        
        _fixed = []
        for e in _raw:
            _before = str(e.get("value_before_unify") or "")
            if _before in ("undetermined", "unknown"):
                e = dict(e)
                e["value"] = _before
                e["note"] = (e.get("note") or "") + "（汇总页：原为未判定，不按统一后的异常计入）"
            _fixed.append(e)

        all_ev = [e for e in _fixed
                  if str(e.get("modality") or "") in ("vision", "part", "scope")]
        photo = [e for e in all_ev if str(e.get("modality") or "") in ("vision", "part")]
        scope = {"ok": False, "state": "", "why": "", "evidence": None}
    if not _SA_SESSION["id"]:
        _SA_SESSION["id"] = "SA" + time.strftime("%Y%m%d_%H%M%S")
        _SA_SESSION["dir"] = os.path.join(SESSION_DIR, _SA_SESSION["id"])
    sid = _SA_SESSION["id"]

    shot_dirs, parts = set(), set()
    for e in photo:
        if str(e.get("modality") or "") == "vision":
            sd = str(e.get("shot_dir") or "")
            if sd:
                shot_dirs.add(sd)
        p = str(e.get("part") or "").strip()
        if p:
            parts.add(p)
    n_shots = len(shot_dirs)
    if not n_shots:
        n_shots = len({str(e.get("step_id") or "") for e in photo
                       if str(e.get("modality") or "") == "vision" and e.get("step_id")})

    if not all_ev:
        print("[summary_all] 空态：本次没有拍照/波形记录（不总结、不硬凑）", flush=True)
        return {"updated": updated, "empty": True, "sid": sid,
                "photo": {"n": 0, "parts": 0, "abn": 0, "undet": 0},
                "scope": scope, "summary": {}, "counts": {}, "problems": [],
                "ranges": [], "unexplained": [], "notice": "", "ranges_note": "",
                "mode": ""}
    if SS is None:
        return _sa_error(SUMMARY_MODULE_ERR,
                         "session_summary.py 未部署或导入失败（见启动日志）")
    try:
        res = SS.summarize(all_ev, session={"id": sid, "started_at": _flow_iso(),
                                            "session_dir": _SA_SESSION["dir"],
                                            "source_file": "summary_all"})
    except Exception as e:                                        
        print("[summary_all] summarize 异常（已降级，UI 不崩）: %s" % e, flush=True)
        return _sa_error(SUMMARY_MODULE_ERR, "summarize() 抛异常：%s" % e)

    counts = res.get("counts") or {}
    it_counts = counts.get("items") or {}
    abn = [a for a in (res.get("abnormals") or [])
           if str(a.get("field") or "") != SA_SCOPE_FIELD]
    und = [a for a in (res.get("undetermined") or [])
           if str(a.get("field") or "") != SA_SCOPE_FIELD]

    _ev_field, _ev_step = _sa_ev_maps(res)

    _lamp_steps = set()
    for _a in abn + und:
        if (str(_a.get("modality") or "") == "vision"
                and not str(_a.get("field") or "").startswith("(vision_infer)")):
            _lamp_steps.add(str(_a.get("step_id") or ""))
    problems = []
    for a in abn:
        _f = str(a.get("field") or "")
        if _f.startswith("(vision_infer)") and str(a.get("step_id") or "") in _lamp_steps:
            continue
        try:
            _r0 = int(a.get("kb_row") or 0)
        except (TypeError, ValueError):
            _r0 = 0

        

        
        kbtxt = (_sa_rows_kb([_r0]) if _r0 > 0
                 else "库中无此项（field 未命中）")
        problems.append({"src": "拍照", "text": str(a.get("text") or a.get("field") or ""),
                         "kb": kbtxt, "tone": "bad"})
    for a in und:
        if str(a.get("modality") or "") not in ("vision", "part"):
            continue
        if (str(a.get("field") or "").startswith("(vision_infer)")
                and str(a.get("step_id") or "") in _lamp_steps):
            continue
        sub = str(a.get("subcategory") or "")
        tag = ("库中无此项（未判定）" if sub in ("kb_external", "unknown_value", "weak_evidence")
               else "未判定")
        problems.append({"src": "拍照", "text": str(a.get("text") or a.get("field") or ""),
                         "kb": tag, "tone": "unk"})
    if scope.get("ok") and scope.get("state") and scope["state"] != "pass":
        problems.append({"src": "波形", "text": _sa_scope_problem(scope),
                         "kb": "库中无此项", "tone": "bad" if scope["state"] == "fail" else "unk"})
    _extra_n = max(0, len(problems) - 4)
    _p_abn = sum(1 for p in problems if p.get("tone") == "bad" and p.get("src") == "拍照")
    _p_und = sum(1 for p in problems if p.get("tone") == "unk" and p.get("src") == "拍照")
    if _extra_n:
        problems = problems[:4] + [{"src": "", "text": "…还有 %d 条未显示（完整见 summary_all.json）"
                                    % _extra_n, "kb": "", "tone": "dim"}]

    top = res.get("top_faults") or []
    covering = [c for c in top if c.get("covers_all")]

    

    
    _grounded_covering = [c for c in covering if _sa_field_grounded(res, c, _ev_field)]
    _grounded_top = [c for c in top if _sa_field_grounded(res, c, _ev_field)]

    
    try:
        _inter = int((res.get("converge") or {}).get("intersection_size") or 0)
    except (TypeError, ValueError):
        _inter = 0
    _inter = max(_inter, len(covering))
    try:
        _n_cands = int(res.get("candidates_total") or 0)
    except (TypeError, ValueError):
        _n_cands = 0
    if not _n_cands:
        _n_cands = len(res.get("all_candidates") or top) or len(top)

    
    try:
        _n_unm = int((res.get("field_match") or {}).get("unmatched") or 0)
    except (TypeError, ValueError):
        _n_unm = 0

    def _cname(c):
        return "%s%s %s" % (c.get("module_display") or c.get("module") or "?",
                            "（跨部位）" if not c.get("in_part_scope") else "",
                            _sa_rows_kb(c.get("kb_rows")) or "rec#—")

    ranges, notice, ranges_note, mode = [], "", "", ""
    if _grounded_covering:
        mode = "converged" if (str(res.get("verdict")) == "converged"
                               and len(_grounded_covering) == len(covering)) else "partial"
        for c in _grounded_covering[:3]:
            ranges.append({
                "module": str(c.get("module_display") or c.get("module") or "?"),
                "reason": str(c.get("reason") or ""),
                "conf": float(c.get("confidence") or 0.0),
                "kb": _sa_rows_kb(c.get("kb_rows")),
                "support": int(c.get("support_count") or 0),
                "cross": not bool(c.get("in_part_scope")),
                "feature": str(c.get("feature_id") or "")})
        _dropped = max(0, _inter - len(_grounded_covering))
        if _dropped or _n_cands > len(_grounded_covering):
            ranges_note = ("交集内共 %d 个候选；页面只列 field 级对应的 %d 个"
                           "（%d 个同值候选未列；候选总数 %d）"
                           % (_inter, len(_grounded_covering), _dropped, _n_cands))
    elif covering:
        mode = "no_field_match"
        notice = "⚠ 候选只有同值匹配（现象 field 未在判据库命中）⇒ 不作故障范围"
        ranges_note = "同值候选 %d 个（不列具体故障名，避免误导）" % _n_cands
    elif _grounded_top:
        mode = "no_intersection"
        notice = "⚠ 无法收敛到具体故障（无公共候选）"
        _u = [_cname(c) for c in _grounded_top[:2]]
        ranges_note = ("field 级对应候选 %d 个（%s 等），均不能解释全部现象 ⇒ 不作故障范围"
                       % (_n_cands, "；".join(_u)))
    elif top:
        mode = "no_field_match"
        notice = "⚠ 候选只有同值匹配（现象 field 未在判据库命中）⇒ 不作故障范围"
        ranges_note = "同值候选 %d 个（不列具体故障名，避免误导）" % _n_cands
    else:
        mode = "none"
        notice = "本轮没有可参与推理的异常现象 ⇒ 无需收敛"

    unexpl = []
    for u in (res.get("unexplained") or []):
        _uf = str(u.get("field") or "")
        _ue = str(u.get("ev_id") or "")

        

        if (_uf.startswith("(vision_infer)")
                and _ev_step.get(_ue, "") in _lamp_steps):
            continue
        if _uf == SA_SCOPE_FIELD:
            txt = _sa_scope_problem(scope) if scope.get("ok") else "波形现象"
            why = "库中无对应候选（不编原因）"
        else:
            txt = str(u.get("text") or "")
            w = str(u.get("why") or "")
            if _n_unm and "候选" in w:
                why = "库中无此项/候选未确认（field 未命中，不编原因）"
            else:
                why = ("库中无此项（不编原因）" if "未收录" in w else
                       ("库中无对应候选（不编原因）" if "所有候选都解释不了" in w else
                        _sa_short(w, 30)))
        unexpl.append({"text": txt, "why": why})
    if len(unexpl) > 3:
        unexpl = unexpl[:3]

    sa = {"updated": updated, "empty": False, "sid": sid,
          "photo": {"n": n_shots, "parts": len(parts),
                    "abn": _p_abn, "undet": _p_und},
          "scope": scope, "summary": res, "counts": it_counts,
          "problems": problems, "ranges": ranges, "unexplained": unexpl,
          "notice": notice, "ranges_note": ranges_note, "mode": mode}
    if persist:
        _sa_persist(sa, sid, all_ev)
    print("[summary_all] verdict=%s 候选=%d 收敛=%d 问题=%d 未解释=%d 证据=%d 照片=%d 部位=%d"
          % (res.get("verdict"), len(top), len(ranges), len(problems), len(unexpl),
             len(all_ev), n_shots, len(parts)), flush=True)
    return sa

def draw_summary_all(layout, sa, toast="", err=""):
    """「拍照 + 波形总结」页（1024×600）：四块 = 盘点 / 问题 / 故障范围 / 未解释。"""
    C = layout["colors"]
    W, H = layout["canvas"]["w"], layout["canvas"]["h"]
    img = np.full((H, W, 3), C["bg"], np.uint8)
    _grad_v(img, (0, 0, W, H), C["bg"], C.get("bg_bottom", C["bg"]))
    btns = []
    sa = sa or {}
    summary = sa.get("summary") or {}
    photo = sa.get("photo") or {}
    scope = sa.get("scope") or {}
    counts = sa.get("counts") or {}
    verdict = str(summary.get("verdict") or "")
    concl = str(summary.get("conclusion") or "")

    _grad_v(img, (0, 0, W, 72), C["title_bar"], C.get("title_bar2", C["title_bar"]))
    cv2.line(img, (0, 72), (W - 1, 72), C.get("accent", C["dim"]), 2, lineType=cv2.LINE_AA)
    _flow_button(img, C, btns, "back", [16, 14, 132, 58], "返回", "summary_all:back",
                 scale=0.55)
    draw_text(img, "拍照 + 波形总结", (146, 52), scale=0.82, color=C["title_text"], th=2)
    _rrect_fill(img, (352, 16, 704, 64), C.get("chip_bg", C["card"]), 22)
    _evn = ((summary.get("session") or {}).get("evidence_total")) or 0
    draw_text(img, _fit_text("更新于 %s ｜ 证据 %s 条" % (sa.get("updated") or "-", _evn),
                             336, 0.4), (366, 48), scale=0.4, color=C["accent"], th=1)
    _badge, _bcol = ("已收敛到故障", C["bad"]) if (verdict == "converged" and concl == "fault") \
        else (("未发现异常", C["ok"]) if (verdict == "converged" and concl == "normal")
              else (("部分收敛", C["unk"]) if verdict == "partial" else ("未判定", C["unk"])))
    if sa.get("empty"):
        _badge, _bcol = "空（无证据）", C["dim"]
    elif sa.get("_error"):
        _badge, _bcol = "不可用", C["bad"]
    elif str(sa.get("mode") or "") == "no_field_match":

        _badge, _bcol = "未判定（field 未命中）", C["unk"]
    _rrect_fill(img, (712, 16, 1008, 64), _bcol, 22)
    _center_text(img, _badge, 860, 50, 0.46, (255, 255, 255), th=1)

    _rrect_panel(img, (16, 80, 1008, 500), C.get("card", (39, 31, 24)),
                 C.get("card_edge", C["dim"]), 14)
    _err = str(sa.get("_error") or "")
    if _err:
        draw_text(img, _err, (40, 176), scale=0.95, color=C["bad"], th=2)
        _det = str(sa.get("_detail") or "") or "（无更多信息）"
        for _i, _ln in enumerate(_wrap_cjk(_det, 920, 0.44)[:3]):
            draw_text(img, _ln, (40, 226 + _i * 24), scale=0.44, color=C["text"], th=1)
        draw_text(img, "原因：session_summary.py 未部署 / 导入失败 / summarize() 抛异常",
                  (40, 322), scale=0.44, color=C["dim"], th=1)
        draw_text(img, "拍照/波形功能不受影响；修复后可再点【总结】。本页只降级，UI 不崩。",
                  (40, 354), scale=0.42, color=C["dim"], th=1)
    elif sa.get("empty"):
        _center_text(img, "本次还没有拍照/波形记录", 512, 206, 1.0, C["accent"], th=2)
        _center_text(img, "先在主页或流程页【拍照】，或点【波形检测】测一次，再点【总结】",
                     512, 266, 0.44, C["text"], th=1)
        _center_text(img, "（主页【拍照】判定完成后自动并入本页；波形取最近一次有效测量）",
                     512, 298, 0.36, C["dim"], th=1)
        _center_text(img, "拍照 0 张 ｜ 波形 0 次 ｜ 证据 0 条",
                     512, 332, 0.42, C["dim"], th=1)
        _center_text(img, "⚠ 没有证据 ⇒ 不给结论（宁可不判，绝不编原因）",
                     512, 370, 0.42, C["unk"], th=1)
        draw_text(img, "本次进程启动后没有新证据：旧轮次（上次开机前）的 flow 文件不计入本轮。",
                  (40, 420), scale=0.36, color=C["dim"], th=1)
    else:
        y = 100

        def _head(txt):
            nonlocal y
            y += 10                      
            if y + 22 > 494:
                return False
            draw_text(img, txt, (32, y + 13), scale=0.5, color=C["accent"], th=2)
            y += 24
            return True

        def _line(txt, color=None, scale=0.42, indent=42, pre=""):
            nonlocal y
            if y + 18 > 494:
                return False
            draw_text(img, _fit_text(pre + str(txt), 944, scale), (indent, y + 12),
                      scale=scale, color=color or C["text"], th=1)
            y += 19
            return True

        _head("─ 盘点 ─")
        _line("拍照：本次 %d 张 / 识别部位 %d 个 / 异常 %d 条 / 未判定 %d 条"
              % (photo.get("n", 0), photo.get("parts", 0),
                 photo.get("abn", 0), photo.get("undet", 0)))
        if scope.get("ok"):
            _hz_t = _fmt_hz(scope.get("hz")) if scope.get("hz") is not None else "—"
            _vpp_t = _fmt_vpp(scope.get("vpp")) if scope.get("vpp") is not None else "—"
            _line("波形：本次 1 次测量 / 频率 %s / Vpp %s / 判定 %s"
                  % (_hz_t, _vpp_t, scope.get("state") or "—"))
            _mj = _model_judge_scope(scope)
            if _mj and _mj.get("ok"):
                _mj_col = C["ok"] if _mj.get("agree") else (
                    C["bad"] if _mj.get("verdict") == "不正常" else C["unk"])
                _line("模型判断：" + str(_mj.get("line") or ""), color=_mj_col)
        else:
            _line("波形：本次 0 次有效测量（%s）"
                  % _sa_short(scope.get("why") or "未测量", 34), color=C["dim"])

        _head("─ 发现的问题（逐条，带来源）─")
        problems = sa.get("problems") or []
        if not problems:
            _line("（本轮未发现异常现象）", color=C["dim"])
        for i, p in enumerate(problems):
            pre = (_SA_CIRCLED[i] if i < len(_SA_CIRCLED) else "·") + " "
            txt = ("[%s] %s" % (p.get("src"), p.get("text"))) if p.get("src") else str(p.get("text"))
            if p.get("kb"):
                txt += " ｜ " + str(p.get("kb"))
            col = C["bad"] if p.get("tone") == "bad" else (
                C["dim"] if p.get("tone") == "dim" else C["unk"])
            if not _line(txt, color=col, pre=pre):
                break

        _head("◆ 故障范围（按库推理）")
        ranges = sa.get("ranges") or []
        if ranges:
            for i, r in enumerate(ranges):
                pre = (_SA_CIRCLED[i] if i < len(_SA_CIRCLED) else "·") + " "
                _line("%s%s —— %s（置信 %.2f）｜库行 %s｜支撑 %d 条证据"
                      % (r["module"], "（跨部位）" if r.get("cross") else "",
                         _sa_short(r["reason"], 28), r["conf"],
                         r["kb"] or "rec#—", r["support"]), pre=pre)
            if sa.get("mode") == "partial":
                _line("（仅部分收敛：%s）" % _sa_short(summary.get("verdict_reason"), 42),
                      color=C["unk"], scale=0.36)
            if sa.get("ranges_note"):
                _line(sa["ranges_note"], color=C["dim"], scale=0.36)
        elif sa.get("notice"):
            _line(sa["notice"], color=C["unk"], scale=0.42)
            if sa.get("ranges_note"):
                _line(sa["ranges_note"], color=C["dim"], scale=0.36)

        _head("─ 未解释现象 ─")
        unexpl = sa.get("unexplained") or []
        if not unexpl:
            _line("（无）", color=C["dim"])
        for i, u in enumerate(unexpl):
            pre = (_SA_CIRCLED[i] if i < len(_SA_CIRCLED) else "·") + " "
            if not _line("%s ⇒ %s" % (u.get("text"), u.get("why")),
                         color=C["text"], scale=0.4, pre=pre):
                break
        if not (toast or err) and y <= 470:
            draw_text(img, "行号口径：rec#N=判据库含表头记录号（数据行 N-1）；field 未命中不编原因",
                      (32, 492), scale=0.3, color=C["dim"], th=1)

    if toast or err:
        _rrect_fill(img, (24, 464, 1000, 498), C.get("chip_bg", C["card"]), 10)
        _msg = ("！" + _flow_clean(err)) if err else _flow_clean(toast)
        draw_text(img, _fit_text(_msg, 940, 0.42), (36, 488), scale=0.42,
                  color=C["bad"] if err else C["accent"], th=1)

    _flow_button(img, C, btns, "back2", SA_BACK, "返回", "summary_all:back", scale=0.66)
    _flow_button(img, C, btns, "again", SA_AGAIN, "重新汇总", "summary_all:again",
                 primary=True, scale=0.66)
    return img, btns

RESULT_CONFIRM = [16, 76, 1008, 130]
RESULT_CONCL = [16, 134, 1008, 186]
RESULT_LEFT = [16, 190, 300, 468]
RESULT_RIGHT = [308, 190, 1008, 468]
RESULT_ROWS_MAX = 8

RESULT_AUTO_QA_SEC = 10.0

def _res_tone(C, st):

    return {"ok": C["ok"], "bad": C["bad"], "qa": C["unk"]}.get(st, C["unk"])

def draw_result(layout, r, elapsed=0.0, pending=False, toast="", err="",
                has_qa=False, qa_left=0, countdown=None, qa_done=0):
    """结果页（1024×600）：部位+置信 / 低置信确认（可点选）/ 逐条灯与屏 /
    本步结论（✔正常 · ✗异常 · 未判定）/ 【重拍】【去问答 ▶】【返回】。

    ``pending=True`` 时只画"判定中"骨架（板端单张 15~25s，绝不能冻住 UI）。
    ``countdown``：本步有 QA 且判定完成后的自动跳转剩余秒数（3/2/1）；None=不跳。
    """
    C = layout["colors"]
    W, H = layout["canvas"]["w"], layout["canvas"]["h"]
    img = np.full((H, W, 3), C["bg"], np.uint8)
    _grad_v(img, (0, 0, W, H), C["bg"], C.get("bg_bottom", C["bg"]))
    btns = []
    r = r or {}
    part = r.get("part") or {}
    concl = r.get("conclusion") or {}
    rows = r.get("rows") or []

    

    rows = [dict(x, expect_text="任意（不判）", match=None, record_only=True)
            if (x.get("expect_text") == "任亮灭" or x.get("record_only")) else x
            for x in rows]
    und = r.get("undetermined") or {}
    rule_note = r.get("rule_note") or ""
    cf = float(part.get("confidence") or 0.0)

    _grad_v(img, (0, 0, W, 72), C["title_bar"], C.get("title_bar2", C["title_bar"]))
    cv2.line(img, (0, 72), (W - 1, 72), C.get("accent", C["dim"]), 2, lineType=cv2.LINE_AA)
    _flow_button(img, C, btns, "back", [16, 14, 132, 58], "返回", "result:back", scale=0.55)
    draw_text(img, "拍照判定", (146, 52), scale=0.82, color=C["title_text"], th=2)
    _rrect_fill(img, (276, 16, 600, 64), C.get("chip_bg", C["card"]), 22)
    _pdisp = (part.get("display") or part.get("part")
              or ((part.get("part_used") or "") + "（步骤指定）" if part.get("part_used")
                  else "未识别"))
    draw_text(img, _fit_text("部位 %s" % _pdisp, 304, 0.5),
              (290, 50), scale=0.5,
              color=(C["ok"] if part.get("part") else C["unk"]), th=2)
    _rrect_fill(img, (612, 16, 806, 64), C.get("chip_bg", C["card"]), 22)
    _center_text(img, ("置信 %.0f%%" % (cf * 100)) if part.get("part") else "置信 —",
                 709, 50, 0.52, (C["ok"] if cf >= 0.60 else C["unk"]), th=1)
    _rrect_fill(img, (818, 16, 1008, 64), C.get("chip_bg", C["card"]), 22)
    if countdown is not None:

        _cd = max(0, int(countdown))
        _center_text(img, "自动问答 %ds" % _cd, 913, 50, 0.52,
                     (C["ok"] if _cd % 2 == 0 else C["accent"]), th=2)
    else:
        _center_text(img, ("判定中 %.1fs" % elapsed) if pending else
                     ("%.1fs ｜ 证据 %d 条" % ((r.get("elapsed_ms") or 0) / 1000.0,
                                              len(r.get("evidence_items") or []))),
                     913, 50, 0.42, (C["accent"] if pending else C["dim"]), th=1)

    need = bool(part.get("need_confirm")) and not pending
    conflict = part.get("hint_conflict") or ""
    _rrect_fill(img, RESULT_CONFIRM, C.get("chip_bg", C["card"]), 12)
    if pending:
        draw_text(img, "判定中…（部位识别 + 逐条判灯/判屏，约需 20~30 秒）",
                  (30, 110), scale=0.46, color=C["accent"], th=1)
    elif need or conflict:
        _q = part.get("question") or ("请确认：是不是 %s？" % (part.get("part") or "该部位"))
        draw_text(img, _fit_text("! " + _flow_clean(_q), 520, 0.5), (30, 106),
                  scale=0.5, color=C["unk"], th=2)
        if conflict:
            draw_text(img, _fit_text(conflict, 520, 0.4), (30, 126), scale=0.4,
                      color=C["bad"], th=1)
        cands = (part.get("candidates") or [])[:3]
        if cands:
            x0, y0, y1, gap = 566, 84, 122, 8
            n = len(cands)
            w = (1004 - x0 - gap * (n - 1)) // n
            for i, c in enumerate(cands):
                lab = "%s %s" % (c.get("part") or "?",
                                 ("%.0f%%" % ((c.get("score") or 0) * 100)))
                _flow_button(img, C, btns, "pick%d" % i,
                             [x0 + i * (w + gap), y0, x0 + i * (w + gap) + w, y1],
                             lab, "result:pick:%d" % i, scale=0.5)
    else:
        draw_text(img, "部位识别：%s（%s）" % (part.get("display") or part.get("part") or "-",
                                            part.get("decision") or "-"),
                  (30, 106 if rule_note else 114), scale=0.5, color=C["text"], th=1)
        draw_text(img, _fit_text("来源：%s" % (part.get("part_source") or "-"), 300, 0.42),
                  (700, 114), scale=0.42, color=C["dim"], th=1)

    
    if rule_note and not pending and not conflict:
        _w = 520 if need else 940      
        draw_text(img, _fit_text("！" + _flow_clean(rule_note), _w, 0.4), (30, 127),
                  scale=0.4, color=C["unk"], th=2)

    _rrect_fill(img, RESULT_CONCL, C.get("card", (39, 31, 24)), 12)
    st = concl.get("state") or "unknown"
    tone = _res_tone(C, st)

    mark = {"ok": "√ 正常", "bad": "× 异常", "qa": "⚠ 需问答"}.get(st, "? 未判定")
    _rrect_fill(img, (24, 140, 196, 180), tone, 10)
    _center_text(img, mark, 110, 168, 0.6, (255, 255, 255), th=2)
    draw_text(img, _fit_text(_flow_clean(concl.get("text") or "未判定"), 390, 0.6),
              (212, 167), scale=0.6, color=tone, th=2)
    why = _flow_clean(concl.get("why") or "")
    if why:
        draw_text(img, _fit_text(why, 368, 0.4), (628, 166), scale=0.4,
                  color=C["text"], th=1)

    _rrect_panel(img, RESULT_LEFT, C.get("card", (39, 31, 24)),
                 C.get("card_edge", C["dim"]), 14)
    draw_text(img, "部位识别", (32, 214), scale=0.44, color=C["dim"], th=1)
    draw_text(img, _fit_text(part.get("display") or part.get("part") or "未识别", 250, 0.8),
              (32, 250), scale=0.8,
              color=(C["ok"] if part.get("part") else C["dim"]), th=2)
    draw_text(img, ("置信 %.0f%%" % (cf * 100))
              + ("（待确认）" if part.get("need_confirm") else ""),
              (32, 280), scale=0.46,
              color=(C["unk"] if part.get("need_confirm") else C["ok"]), th=1)
    draw_text(img, _fit_text("决断：%s" % (part.get("decision") or "-"), 250, 0.4),
              (32, 306), scale=0.4, color=C["text"], th=1)
    draw_text(img, _fit_text("来源：%s" % (part.get("part_source") or "-"), 250, 0.4),
              (32, 328), scale=0.4, color=C["dim"], th=1)
    draw_text(img, "识别依据", (32, 356), scale=0.4, color=C["dim"], th=1)
    for i, ln in enumerate((part.get("reasons") or [])[:2]):
        draw_text(img, _fit_text("· " + _flow_clean(ln), 246, 0.36), (36, 376 + i * 19),
                  scale=0.36, color=C["text"], th=1)
    draw_text(img, "候选故障", (32, 420), scale=0.4, color=C["dim"], th=1)
    _cd = r.get("candidates") or []
    if _cd:
        for i, c in enumerate(_cd[:2]):
            draw_text(img, _fit_text("· " + str(c), 246, 0.34), (36, 440 + i * 17),
                      scale=0.34, color=C["bad"], th=1)
    else:
        draw_text(img, "—（无）", (36, 440), scale=0.38, color=C["dim"], th=1)

    _rrect_panel(img, RESULT_RIGHT, C.get("card", (39, 31, 24)),
                 C.get("card_edge", C["dim"]), 14)
    draw_text(img, "逐条判定（灯 / 屏幕）", (324, 214), scale=0.44, color=C["dim"], th=1)

    _n_qa = len([x for x in rows if x.get("qa_required")])
    _n_det = len(rows) - _n_qa
    if _n_qa:
        draw_text(img, "确定 %d 项 ｜ 需问答 %d 项 ｜ 未判定 %d 项"
                  % (_n_det, _n_qa, und.get("n") or 0), (614, 214), scale=0.36,
                  color=C["dim"], th=1)
    else:
        draw_text(img, "确定 %d 项 ｜ 未判定 %d 项" % (_n_det, und.get("n") or 0),
                  (690, 214), scale=0.42, color=C["dim"], th=1)
    for _x, _t in ((324, "位次"), (426, "亮灭/状态"), (556, "含义（灯名 / 画面）"),
                   (834, "应为"), (950, "符合")):
        draw_text(img, _t, (_x, 240), scale=0.38, color=C["dim"], th=1)
    cv2.line(img, (324, 247), (996, 247), C.get("card_edge", C["dim"]), 1,
             lineType=cv2.LINE_AA)
    if pending:
        _center_text(img, "判定中…", 658, 336, 0.9, C["accent"], th=2)
        draw_text(img, "部位识别（模板 NCC 兜底）→ 逐条判定（vision_rules），通常 20~30 秒",
                  (344, 372), scale=0.4, color=C["dim"], th=1)
        draw_text(img, "完成后本页自动刷新；有问答的步 → 再等 3 秒自动进问答",
                  (344, 396), scale=0.4, color=C["dim"], th=1)
    elif rows:
        _y = 272
        for row in rows[:RESULT_ROWS_MAX]:
            m = row.get("match")
            _rec = bool(row.get("record_only"))

            _qa = bool(row.get("qa_required"))
            _c = (C["unk"] if _qa else
                  (C["dim"] if _rec else (C["ok"] if m else (C["bad"] if m is False else C["unk"]))))
            _dot(img, 332, _y - 5, 5, _c)
            draw_text(img, _fit_text(row.get("pos") or "-", 92, 0.4), (344, _y),
                      scale=0.4, color=C["text"], th=1)
            draw_text(img, _fit_text(row.get("state_text") or "-", 124, 0.44), (426, _y),
                      scale=0.44, color=(C["text"] if _rec else _c), th=2)
            draw_text(img, _fit_text(row.get("name") or "-", 258, 0.42), (556, _y),
                      scale=0.42, color=C["text"], th=1)
            draw_text(img, _fit_text(row.get("expect_text") or "-", 96, 0.38), (834, _y),
                      scale=0.38, color=C["dim"], th=1)
            draw_text(img, ("⚠" if _qa else
                            ("—" if _rec else ("√" if m else ("×" if m is False else "?")))),
                      (952, _y), scale=0.55, color=_c, th=2)
            _y += 24
        if len(rows) > RESULT_ROWS_MAX:
            draw_text(img, "+%d 项（已全部写入证据）" % (len(rows) - RESULT_ROWS_MAX),
                      (344, _y), scale=0.38, color=C["dim"], th=1)
    else:
        _center_text(img, "无逐条结论", 658, 318, 0.8, C["unk"], th=2)
        draw_text(img, _fit_text("原因：" + _flow_clean((und.get("reasons") or ["—"])[0]),
                                 630, 0.38), (344, 350), scale=0.38,
                  color=C["text"], th=1)
        draw_text(img, "（画面里没有成排指示灯 / 显示屏，或本部位无对应判据）",
                  (344, 374), scale=0.36, color=C["dim"], th=1)
    if not pending and (und.get("reasons") or []) and len(rows) <= 6:

        draw_text(img, _fit_text("未判定原因：%s" % _flow_clean(und["reasons"][0]),
                                 660, 0.36), (324, 456), scale=0.36,
                  color=C["dim"], th=1)

    _flow_button(img, C, btns, "retake", [16, 476, 300, 570], "重  拍",
                 "result:retake", scale=0.8)
    if has_qa:
        _qa_lab = ("去问答 ▶（剩 %d 题）" % qa_left) if qa_left else "去问答 ▶"
        if countdown is not None:

            _qa_lab = "去问答 > %d 秒后自动" % max(0, int(countdown))
        _flow_button(img, C, btns, "qa", [308, 476, 600, 570], _qa_lab,
                     "result:qa", primary=True,
                     scale=(0.62 if countdown is not None else 0.68),
                     tone=("ok" if (countdown is not None and int(countdown) % 2 == 0) else ""))
        if countdown is not None:

            cv2.rectangle(img, (303, 471), (605, 575),
                          C["ok"] if int(countdown) % 2 == 0 else C["accent"], 3,
                          lineType=cv2.LINE_AA)
    else:
        _rrect_fill(img, (308, 476, 600, 570), C.get("button_alt", C["card"]), 10)

        _text_center(img, ("问答已完成（%d 题）" % qa_done) if qa_done else "本步无问答项",
                     (308, 476, 600, 570), 0.56 if qa_done else 0.6,
                     C["ok"] if qa_done else C["dim"])
    _flow_button(img, C, btns, "back2", [608, 476, 872, 570], "返  回",
                 "result:back", scale=0.8)
    draw_text(img, "证据 %d 条" % len(r.get("evidence_items") or []), (884, 508),
              scale=0.42, color=C["text"], th=1)
    if err:
        draw_text(img, _fit_text("！" + str(err), 116, 0.34), (884, 532), scale=0.34,
                  color=C["bad"], th=1)
    if toast:
        _center_text(img, _fit_text(toast, 900, 0.4), W / 2, 594, 0.4, C["text"])
    return img, btns

_PHASE_FIELDS = {
    "A": "(manual_action)_z18_phase_a_voltage",
    "B": "(manual_action)_z18_phase_b_voltage",
    "C": "(manual_action)_z18_phase_c_voltage",
}

def _z18_phase_of(q):
    """从 qa_item 认出相别 A/B/C（证据字段优先，其次题干「A相电压」）。无则空。"""
    f = str((q or {}).get("evidence_field") or "")
    for ph, fld in _PHASE_FIELDS.items():
        if f == fld:
            return ph
    txt = "%s %s" % ((q or {}).get("question") or "", (q or {}).get("check_item") or "")
    for ph in ("A", "B", "C"):
        if ("%s相电压" % ph) in txt or ("%s相" % ph) in txt:
            return ph
    return ""

def _z18_pack_for(flow, step, qa, frame):
    """取（并缓存）本步本题的 g18 多模态 pack；非 Z18 电压题/模块不可用 ⇒ None。"""
    ph = _z18_phase_of(qa)
    if not ph:
        return None
    part = str((step or {}).get("part") or "").strip().lower()
    if part not in ("z18", "g18"):
        return None
    key = (str((step or {}).get("step_id") or ""), str((qa or {}).get("qa_id") or ""))
    cache = flow.setdefault("_z18_packs", {})
    if key in cache:
        return cache[key]
    try:
        from soc_vision import g18_seg7 as _G18
        pack = _G18.z18_phase_pack(frame, ph)
    except Exception as e:                                       
        print("[z18] 多模态读数失败（step=%s qa=%s）: %s" % (key[0], key[1], e), flush=True)
        return None
    pack["_phase"] = ph if (pack.get("prefill") or pack.get("evidence_items")) else ""
    cache[key] = pack
    try:
        _pf = pack.get("prefill") or {}
        _rd = pack.get("readings") or {}
        print("[z18] %s相 实测=%s suggested=%s conf=%.2f -> %s"
              % (ph, _pf.get("measured"), _pf.get("suggested_answer"),
                 float(_pf.get("confidence") or 0.0),
                 (pack.get("conclusion") or {}).get("text")), flush=True)
    except Exception:                                            
        pass
    return pack

def _z18_attach_vision(flow, step, qa, frame, view):
    """把 z18 pack 摘要挂到 _flow_qa_view 的返回上，供 draw_qa 画读数条/高亮按钮。"""
    if view is None:
        return
    pack = _z18_pack_for(flow, step, qa, frame)
    if not pack:
        return
    disps = []
    for k, d in (pack.get("displays") or {}).items():
        disps.append({"key": k, "label": d.get("label"), "value": d.get("value"),
                      "text": d.get("text") or "", "valid": bool(d.get("valid"))})
    pre = pack.get("prefill") or {}
    view["vision"] = {
        "displays": disps,
        "readings": pack.get("readings") or {},
        "phase": pack.get("_phase") or "",
        "suggested_answer": pre.get("suggested_answer") or "",
        "suggested_label": {"done": "正常", "under_voltage": "欠压",
                            "over_voltage": "过压", "not_done": "未读数"}.get(
                                pre.get("suggested_answer") or "", ""),
        "confidence": pre.get("confidence") or 0.0,
        "conclusion": (pack.get("conclusion") or {}).get("text") or "",
        "mapping_confirmed": bool(pack.get("mapping_confirmed")),
        "warnings": pack.get("warnings") or [],
    }

def _z18_enrich_qa_evidence(flow, step, qa, ev):
    """问答落证据后，把视觉读数/建议并入同一条 evidence（不新增重复字段证据）。"""
    try:
        key = (str((step or {}).get("step_id") or ""), str((qa or {}).get("qa_id") or ""))
        pack = (flow.get("_z18_packs") or {}).get(key)
        if not pack or not isinstance(ev, dict):
            return
        pre = pack.get("prefill") or {}
        ph = _z18_phase_of(qa) or pack.get("_phase") or ""
        if ph:
            ev["field"] = _PHASE_FIELDS.get(ph, ev.get("field") or "")
        ev["vision"] = {
            "display": pre.get("display"),
            "phase": ph,
            "readings": pack.get("readings") or {},
            "measured": pre.get("measured"),
            "measured_text": pre.get("measured_text"),
            "suggested_answer": pre.get("suggested_answer"),
            "confidence": pre.get("confidence"),
            "mapping_confirmed": bool(pack.get("mapping_confirmed")),
            "normal_range": pre.get("normal_range"),
        }
        note = str(pre.get("note") or "")
        if note:
            ev["note"] = ((ev.get("note") or "") + "；" + note).strip("；")
        chosen = str(ev.get("qa_value") or ev.get("value") or "")
        sug = str(pre.get("suggested_answer") or "")
        if sug and chosen and chosen != sug:
            ev["vision_conflict"] = True
            ev["note"] = (ev.get("note") or "") + "（视觉=%s 与人工=%s 不一致）" % (sug, chosen)
    except Exception as e:                                       
        print("[z18] 证据合并失败: %s" % e, flush=True)

def _flow_qa_view(flow, step, q):
    """把 steps.json 的 qa_item 包成 draw_qa() 要的形状。

    ★ 复用**已有**的问答页渲染（draw_qa），页面上只显示**本步**这一题；
    作答/跳过/返回的动作名换成 ``flowqa:*``，由流程那一套证据逻辑处理。
    """
    ans = _flow_answers(flow, step)
    total = len(step.get("qa_items") or [])
    pos = len(ans) + 1
    opts = list(q.get("options") or [])

    
    _has_skip_opt = any(str(o.get("value")) in ("skipped", "undetermined") for o in opts)
    n = max(1, len(opts) + (0 if _has_skip_opt else 1))
    gap, x0, x1, y0, y1 = 14, 24, 1000, 452, 560
    w = (x1 - x0 - gap * (n - 1)) // n
    btns = []
    for i, o in enumerate(opts):
        tone = o.get("tone") if o.get("tone") in ("ok", "bad") else ""
        btns.append({
            "id": "ans%d" % i,
            "label": o.get("label") or o.get("value") or "",
            "label_plain": o.get("label_plain") or o.get("label") or o.get("value", ""),
            "rect": [x0 + i * (w + gap), y0, x0 + i * (w + gap) + w, y1],
            "tone": tone,
            "action": "flow:answer:%s" % o.get("value", ""),
        })
    k = len(opts)
    skip = None if _has_skip_opt else {
        "id": "skip", "label": "跳过", "label_plain": "跳过",
        "rect": [x0 + k * (w + gap), y0, x0 + k * (w + gap) + w, y1],
        "tone": "", "action": "flow:skip"}
    back = {"id": "flowqa_back", "label": "返回流程", "label_plain": "返回流程",
            "rect": [852, 28, 1000, 78], "tone": "", "action": "flowqa:back"}
    return {
        "qa_id": q.get("qa_id"),
        "skip_suggested": False,
        "skip_reason": "",
        "ui": {
            "progress": "本步第 %d/%d 题" % (pos, total),

            
            "part_chip": _part_disp(step.get("part"), _step_route(step)) or "-",
            "route_chip": "",
            "category_chip": q.get("category") or "",
            "flow": "%s｜%s" % (step.get("flow_no") or "",
                                _flow_clean(step.get("flow_name"))),
            "question": _flow_clean(q.get("question") or q.get("check_item")),
            "normal": _flow_clean(q.get("normal") or ""),
            "buttons": btns, "skip_button": skip, "back_button": back,
        },
    }

def _part_qa_view(pq):
    """把"按部位找出来的题"包成 draw_qa() 要的形状（主页拍照用；与流程问答同一套渲染）。

    动作名换成 ``partqa:*``：主页没有 step 上下文，证据只记在本次结果的 part_qa 里。
    """
    items = pq.get("items") or []
    i = max(0, min(int(pq.get("idx") or 0), len(items) - 1))
    q = items[i]
    total = len(items)
    opts = list(q.get("options") or [])
    _has_skip_opt = any(str(o.get("value")) in ("skipped", "undetermined") for o in opts)
    n = max(1, len(opts) + (0 if _has_skip_opt else 1))
    gap, x0, x1, y0, y1 = 14, 24, 1000, 452, 560
    w = (x1 - x0 - gap * (n - 1)) // n
    btns = []
    for k, o in enumerate(opts):
        tone = o.get("tone") if o.get("tone") in ("ok", "bad") else ""
        btns.append({
            "id": "ans%d" % k,
            "label": o.get("label") or o.get("value") or "",
            "label_plain": o.get("label_plain") or o.get("label") or o.get("value", ""),
            "rect": [x0 + k * (w + gap), y0, x0 + k * (w + gap) + w, y1],
            "tone": tone,
            "action": "partqa:answer:%s" % o.get("value", ""),
        })
    k = len(opts)
    skip = None if _has_skip_opt else {
        "id": "skip", "label": "跳过", "label_plain": "跳过",
        "rect": [x0 + k * (w + gap), y0, x0 + k * (w + gap) + w, y1],
        "tone": "", "action": "partqa:skip"}
    back = {"id": "partqa_back", "label": "返回", "label_plain": "返回",
            "rect": [852, 28, 1000, 78], "tone": "", "action": "partqa:back"}
    return {
        "qa_id": q.get("qa_id"),
        "skip_suggested": False,
        "skip_reason": "",
        "ui": {
            "progress": "%d/%d" % (i + 1, total),

            "part_chip": _part_disp(pq.get("part"),
                                    pq.get("route") or q.get("route")) or "-",
            "route_chip": "",
            "category_chip": str(q.get("category") or ""),
            "flow": _flow_clean("拍照部位：%s ｜ 题目来源：%s"
                                % (_part_disp(pq.get("part"),
                                              pq.get("route") or q.get("route")) or "-",
                                   q.get("_src") or "-")),
            "question": _flow_clean(q.get("question") or q.get("check_item")),
            "normal": _flow_clean(q.get("normal") or ""),
            "buttons": btns, "skip_button": skip, "back_button": back,
        },
    }

def wave_from_frame(frame, ns_per_div=100.0):
    """从相机帧里识别示波器屏幕与波形，返回判定字典（纯 numpy，不依赖 SCPI/外部程序）
    规则（用户要求）：20 MHz ±3% 正常；40 MHz ±3% 正常；其余不正常；不确定一律"未判定"。
    ns_per_div：示波器时基（ns/格，默认 100），可在 ui_layout.json 的 wave.ns_per_div 改。
    """
    out = {"verdict": "未判定", "message": "未识别到示波器屏幕", "freq_mhz": None,
           "box": None, "period_px": None, "peak": 0.0, "src": "曲线计算"}
    if frame is None:
        out["message"] = "无画面"
        return out
    a = frame.astype(np.float32)
    g = a.mean(axis=2)

    thr = 0.5 * (float(g.min()) + float(np.percentile(g, 60)))
    dark = g < thr
    rows = np.where(dark.sum(axis=1) > a.shape[1] * 0.15)[0]
    cols = np.where(dark.sum(axis=0) > a.shape[0] * 0.15)[0]
    if len(rows) < 20 or len(cols) < 20:

        rows = np.array([0, a.shape[0] - 1]); cols = np.array([0, a.shape[1] - 1])
        out["message"] = "未定位到屏幕（按整幅分析）"
    y0, y1, x0, x1 = int(rows[0]), int(rows[-1]), int(cols[0]), int(cols[-1])
    scr = a[y0:y1, x0:x1]
    r = scr[:, :, 0].astype(np.float32); gg = scr[:, :, 1].astype(np.float32); b = scr[:, :, 2].astype(np.float32)
    lum = (r + gg + b) / 3.0
    warm = (r + gg) / 2.0 - b                      

    t_lum = max(80.0, float(np.percentile(lum, 97)))
    t_warm = max(20.0, float(np.percentile(warm, 95)))
    yellow = (lum >= t_lum) & (warm >= t_warm)
    out["box"] = [x0, y0, x1, y1]
    ys, xs = [], []
    for x in range(scr.shape[1]):
        c = np.where(yellow[:, x])[0]
        if len(c) >= 2:
            ys.append(float(c.mean())); xs.append(x)
    if len(xs) < 30:
        out["message"] = "屏幕内未找到波形曲线（黄线像素不足）"
        return out
    xs = np.array(xs, float); ys = np.array(ys, float)
    out["curve"] = (xs, ys)                               
    v = ys - np.polyval(np.polyfit(xs, ys, 1), xs)
    v = v - v.mean()
    if float(np.abs(v).max()) < 2.0:                      
        out["message"] = "波形是平线（无有效信号：示波器 Freq 应为 *****）"
        return out
    ac = np.correlate(v, v, mode="full")[len(v) - 1:]
    ac = ac / (ac[0] + 1e-9)
    lo, hi = 4, max(6, len(v) // 2)
    k = int(np.argmax(ac[lo:hi])) + lo
    peak = float(ac[k])
    out["period_px"], out["peak"] = k, peak

    if peak < 0.30:
        out["message"] = "波形不规则/噪声（相关峰 %.2f < 0.30）" % peak
        return out
    px_per_div = (x1 - x0) / 10.0                         
    f_hz = 1.0 / (k / px_per_div * (ns_per_div * 1e-9))
    out["freq_mhz"] = f_hz / 1e6
    for tgt in (20e6, 40e6):
        if abs(f_hz - tgt) / tgt <= 0.03:
            out.update(verdict="正常", message="%.0f MHz 正常（实测 %.2f MHz，误差 %.1f%%）"
                       % (tgt / 1e6, f_hz / 1e6, abs(f_hz - tgt) / tgt * 100))
            return out
    out.update(verdict="不正常", message="不正常：实测 %.2f MHz（正常只有 20 / 40 MHz）" % (f_hz / 1e6))
    return out

SCOPE_RESULT_DEFAULT = os.environ.get("AFH03_SCOPE_RESULT", "/userdata/scope_result.json")

SCOPE_KEY_FILE = os.environ.get("AFH03_SCOPE_KEY", "/userdata/.scope_key")
SCOPE_LOCK_FILE = os.environ.get("AFH03_SCOPE_LOCK", "/tmp/scope_collecting.lock")
SCOPE_SESSIONS_FILE = os.environ.get("AFH03_SCOPE_SESSIONS",
                                     "/userdata/.scope_sessions.json")

SCOPE_FRESH_MIN_DEFAULT = 10.0
SCOPE_FRESH_ENV = "AFH03_SCOPE_FRESH_MIN"          
SCOPE_RELOAD_SEC = 20.0                            
SCOPE_SOURCES = ("lan", "usbtmc")
_SCOPE_TEST_RE = re.compile(r"(test|fake|dummy|mock|simulat|模拟|测试|假)", re.I)

SCOPE_TOL_PCT = 5.0                       
SCOPE_ITEMS_LAN_PATHS = (
    "/home/rock/afh03_board_setup/soc_vision/scope_items_lan.json",
    "/home/rock/afh03_board_setup/scope_items_lan.json",
    "/userdata/scope_items_lan.json",
)

SCOPE_EXPECT_BUILTIN = (
    ("(scope)z11_10m_reference", 10e6),
    ("(scope)z11_30m_if", 30e6),
    ("(scope)z14_40m_clock", 40e6),
)

SCOPE_QUICK_PATH = os.environ.get("AFH03_SCOPE_QUICK", "/userdata/work2/scope_quick.py")
SCOPE_MEASURE_TIMEOUT_S = 45.0
SCOPE_MEASURE_HINT = "测量中…（约 6 秒）"
SCOPE_TEMP_RESULT = os.environ.get("AFH03_SCOPE_TEMP", "/userdata/scope_measure_last.json")
SCOPE_ADDR_HINT = "TCPIP0::192.168.88.20::INSTR"
SCOPE_SAMPLES_MAX = 2000                  

def _scope_fresh_min() -> float:
    """新鲜度阈值（分钟）：AFH03_SCOPE_FRESH_MIN，默认 10；非法值回退默认。"""
    raw = os.environ.get(SCOPE_FRESH_ENV, "")
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return SCOPE_FRESH_MIN_DEFAULT
    if not np.isfinite(v) or v <= 0:
        return SCOPE_FRESH_MIN_DEFAULT
    return v

def _scope_source_kind(src) -> str:
    """source 归一：只接受 lan / usbtmc（大小写不敏感）；其它一律返回 ""。"""
    s = str(src or "").strip().lower()
    return s if s in SCOPE_SOURCES else ""

def _scope_is_test(d, src_raw) -> bool:
    """是否测试/模拟数据：test/fake/simulated 字段，或 source 含 test/fake/模拟。"""
    if _SCOPE_TEST_RE.search(str(src_raw or "")):
        return True
    for key in ("test", "selftest", "fake", "simulated", "simulation"):
        if key not in d:
            continue
        v = d.get(key)
        if v is True:
            return True
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v:
            return True
        if isinstance(v, str) and v.strip().lower() in ("1", "true", "yes", "on", "y", "是"):
            return True
    return False

def _scope_canon(items) -> str:
    """签名用的规范 JSON：排序键 + 紧凑分隔符（采集端/页面必须完全一致）。"""
    return json.dumps(items if items is not None else [], ensure_ascii=False,
                      sort_keys=True, separators=(",", ":"))

def _scope_sign(items, ts, key: str) -> str:
    """HMAC-SHA256(key, canonical_json(items) + str(ts))，与采集端同一算法。"""
    msg = (_scope_canon(items) + str(ts)).encode("utf-8")
    return hmac.new(str(key).encode("utf-8"), msg, hashlib.sha256).hexdigest()

def _scope_read_key() -> str:
    """读板端采集密钥；不存在/不可读 ⇒ 返回 ""（页面会判"数据来源未验证"）。"""
    try:
        with open(SCOPE_KEY_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:                                                  
        return ""

def _scope_sessions() -> dict:
    """采集会话台账（只由采集脚本登记；页面只读）。"""
    try:
        with open(SCOPE_SESSIONS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        s = d.get("sessions") if isinstance(d, dict) else None
        return s if isinstance(s, dict) else {}
    except Exception:                                                  
        return {}

def _scope_session_state(session: str) -> str:
    """会话状态：collecting（lock 里就是它）/ known（台账登记过）/ ""（不认识）。"""
    session = str(session or "").strip()
    if not session:
        return ""
    try:
        with open(SCOPE_LOCK_FILE, encoding="utf-8") as f:
            lock = json.load(f) or {}
    except Exception:                                                  
        lock = {}
    if isinstance(lock, dict) and str(lock.get("session") or "") == session:
        return "collecting"
    return "known" if session in _scope_sessions() else ""

def _scope_verify(d, src_raw=""):
    """A+B 校验：采集会话必须已登记 + HMAC 数据指纹必须匹配。

    返回 (ok, 原因, extra)；extra 带 session/collecting/sig 供页面与 journal 使用。
    """
    extra = {"session": "", "collecting": False, "sig": ""}
    session = str(d.get("collector_session") or "").strip()
    sig = str(d.get("sig") or "").strip()
    extra["session"], extra["sig"] = session, sig
    if (not session) or (not sig):
        return False, "数据来源未验证（缺少采集签名 sig / 采集会话 collector_session；手写 JSON 不属于实测）", extra
    state = _scope_session_state(session)
    extra["collecting"] = (state == "collecting")
    if not state:
        return False, "数据来源未验证（采集会话未登记：只接受采集脚本写入的数据）", extra
    key = _scope_read_key()
    if not key:
        return False, "数据来源未验证（板端缺少采集密钥 %s）" % SCOPE_KEY_FILE, extra
    raw_items = d.get("items")
    ts = d.get("ts")
    if ts is None:
        ts = d.get("measured_at")
    try:
        expect = _scope_sign(raw_items, ts, key)
    except Exception as e:                                             
        return False, "数据签名校验失败（%s）" % e, extra
    if not hmac.compare_digest(expect, sig):
        return False, "数据签名不匹配（手写/篡改数据，拒绝显示）", extra
    return True, "", extra

def _scope_ts(raw):
    """解析 ts/measured_at → (epoch 秒, 显示串, 错误)。支持 epoch / ISO / 只有 HH:MM:SS。"""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, "", "数据缺少测量时间（ts/measured_at）"
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        t = float(raw)
        if t > 1e12:                                   
            t /= 1000.0
        if t <= 0:
            return None, "", "测量时间非法"
        return t, time.strftime("%H:%M:%S", time.localtime(t)), ""
    s = str(raw).strip()
    if re.fullmatch(r"\d{9,14}(\.\d+)?", s):            
        t = float(s)
        if t > 1e12:
            t /= 1000.0
        return t, time.strftime("%H:%M:%S", time.localtime(t)), ""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", s)   
    if m:
        hh, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        if hh > 23 or mm > 59 or ss > 59:
            return None, "", "测量时间非法"
        now = time.time()
        lt = time.localtime(now)
        t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hh, mm, ss, 0, 0, -1))
        if t > now + 120:                              
            t -= 86400.0
        return t, "%02d:%02d:%02d" % (hh, mm, ss), ""

    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        dt = None
    if dt is None:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s.replace("/", "-"), fmt)
                break
            except ValueError:
                continue
    if dt is None or dt.year < 1970:
        return None, "", "测量时间格式无法识别"
    t = dt.timestamp() if dt.tzinfo is not None else time.mktime(dt.timetuple())
    return t, time.strftime("%H:%M:%S", time.localtime(t)), ""

def _scope_check(d, src_raw, items, fresh_min):
    """真实性/时效校验；返回 (是否有效, 原因, 附加字段)。"""
    extra = {"measured_at": "", "age_min": None, "bucket": "src",
             "session": "", "collecting": False, "sig": ""}

    if _scope_is_test(d, src_raw):
        extra["bucket"] = "test"
        return False, "数据来源无效：测试/模拟数据（禁止当作实测显示）", extra

    
    _ok_sig, _why_sig, _ex_sig = _scope_verify(d, src_raw)
    extra.update(_ex_sig)
    if not _ok_sig:
        extra["bucket"] = "nosig"
        return False, _why_sig, extra

    if not _scope_source_kind(src_raw):
        extra["bucket"] = "src"
        if str(src_raw or "").strip():
            return False, "数据来源无效（source 必须是 lan / usbtmc）", extra
        return False, "数据来源无效（缺少 source）", extra

    raw_ts = d.get("ts") or d.get("measured_at") or d.get("time") or d.get("timestamp")
    t, tdisp, terr = _scope_ts(raw_ts)
    if terr:
        extra["bucket"] = "ts"
        return False, terr, extra
    age = time.time() - t
    extra.update(measured_at=tdisp, age_min=age / 60.0, bucket="time")
    if age < -120:
        extra["bucket"] = "future"
        return False, "数据时间异常（测量时间在未来，检查板端时钟）", extra
    if age > fresh_min * 60.0 + 0.5:
        extra["bucket"] = "old"
        if age >= 120 * 60.0:
            return False, "数据已过期 %.1f 小时（阈值 %g 分钟）" % (age / 3600.0, fresh_min), extra
        return False, "数据已过期 %.0f 分钟（阈值 %g 分钟）" % (age / 60.0, fresh_min), extra

    if not items:
        extra["bucket"] = "empty"
        return False, "无实测数据（结果文件里没有测量值）", extra
    return True, "", extra

def _vnorm(v):
    """判定词归一成三档：正常 / 不正常 / 未判定（兼容 level=ok/bad、中文长句）。"""
    s = str(v or "").strip()
    if not s:
        return "未判定"
    low = s.lower()
    if ("不正常" in s) or ("异常" in s) or ("故障" in s) or (low in ("bad", "fail", "failed", "ng")):
        return "不正常"
    if ("正常" in s) or (low in ("ok", "pass", "passed", "good")):
        return "正常"
    return "未判定"

def _vcolor(C, v):
    v = _vnorm(v)
    if v == "正常":
        return C["ok"]
    if v == "不正常":
        return C["bad"]
    return C["unk"]

def _hz(v):
    """转 Hz；空/非法/<=0 一律视为"无数据"。"""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(f) or f <= 0:
        return None
    return f

def _fmt_hz(v):
    f = _hz(v)
    if f is None:
        return "—"
    if f >= 1e9:
        return "%.3f GHz" % (f / 1e9)
    if f >= 1e6:
        return "%.2f MHz" % (f / 1e6)
    if f >= 1e3:
        return "%.2f kHz" % (f / 1e3)
    return "%.1f Hz" % f

def _fmt_dev(v):
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(f):
        return "—"
    return "%+.2f" % f

def _posnum(v, allow_zero=False):
    """转成有限浮点；非法 ⇒ None。``allow_zero`` 时 0 也算有效（Vpp 可以是 0）。"""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(f):
        return None
    return f if (f >= 0.0 if allow_zero else f > 0.0) else None

def _fmt_hz_full(v):
    """示数区用的完整频率串：``1000.00 Hz (1.000 kHz)`` / ``30.000 MHz``。"""
    f = _hz(v)
    if f is None:
        return "—"
    if f >= 1e9:
        return "%.4f GHz" % (f / 1e9)
    if f >= 1e6:
        return "%.3f MHz" % (f / 1e6)
    if f >= 1e3:
        return "%.2f Hz (%.3f kHz)" % (f, f / 1e3)
    return "%.3f Hz" % f

def _fmt_period(v):
    """周期串：``1.000 ms`` / ``33.33 ns``。"""
    s = _posnum(v)
    if s is None:
        return "—"
    if s >= 1.0:
        return "%.4f s" % s
    if s >= 1e-3:
        return "%.3f ms" % (s * 1e3)
    if s >= 1e-6:
        return "%.3f us" % (s * 1e6)
    return "%.3f ns" % (s * 1e9)

def _fmt_vpp(v):
    """幅度串：``3.08 V`` / ``120 mV``。"""
    x = _posnum(v, allow_zero=True)
    if x is None:
        return "—"
    if x >= 1.0:
        return "%.3g V" % x
    if x >= 1e-3:
        return "%.3g mV" % (x * 1e3)
    return "%.3g uV" % (x * 1e6)

def _fmt_duty(v):
    """占空比：采集端存 0..1 比例；兼容 0..100 的百分数。"""
    if v is None or isinstance(v, bool):
        return "—"
    try:
        d = float(v)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(d) or d < 0:
        return "—"
    if d > 1.0:
        d /= 100.0
    if d > 1.0:
        return "—"
    return "%.2f%%" % (d * 100.0)

def _fmt_volt(v):
    """坐标刻度用（带符号、短）：``+1.54V`` / ``0`` / ``-1.54V``。"""
    if v is None:
        return "—"
    if abs(v) < 1e-12:
        return "0"
    if abs(v) >= 1.0:
        return "%+.3gV" % v
    return "%+.3gmV" % (v * 1e3)

def _scope_expect_table():
    """28 项期望频率表：``({field: expect_hz_or_None}, 来源路径, 统计)``。

    优先读 ``scope_items_lan.json``（有就用全部 28 项，null 表示"只有有无判据"）；
    读不到就用内置的 6 条（10M / 30M / 40M）。
    统计 = ``{"rows": 28 项条数, "freq": 带期望频率的项数, "path": 实际读到的文件}``。
    """
    table = {}
    for p in SCOPE_ITEMS_LAN_PATHS:
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:                                              
            continue
        rows = d.get("items") if isinstance(d, dict) else None
        if not isinstance(rows, list):
            continue
        n_freq = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            fld = str(row.get("field") or "").strip()
            if not fld:
                continue
            exp = _hz(row.get("expect_freq_hz"))
            table[fld] = exp
            if exp is not None:
                n_freq += 1
        if table:
            return (table, p,
                    {"rows": len(rows), "freq": n_freq, "path": p})
    return ({fld: exp for fld, exp in SCOPE_EXPECT_BUILTIN},
            "<内置 6 项（未找到 28 项 json）>",
            {"rows": 0, "freq": len(SCOPE_EXPECT_BUILTIN), "path": ""})

def _scope_freq_matches(table, meas, tol):
    """在 28 项期望频率里找**唯一的 ±5% 匹配**（同名 I/II 路去重）。

    ``table`` 是 ``{field: expect_hz|None}``；返回 ``(exp, field, dev_pct)`` 或 ``None``。
    只按频率数值匹配，不看名称猜测——没有匹配就是没有参考值。
    """
    best = None
    seen = set()
    for fld, exp in table.items():
        if exp is None:
            continue
        key = round(float(exp), 6)
        if key in seen:
            continue
        seen.add(key)
        dev = (meas - exp) / exp * 100.0
        if abs(dev) <= tol and (best is None or abs(dev) < abs(best[2])):
            best = (float(exp), str(fld), dev)
    return best

def _scope_judge(item, table):
    """页面自己从读数 + 判据库**重算**判定（不盲信文件里的 verdict）。

    判定优先级（2026-10-25 用户口径）：
      ① 结果里有 ``expect_hz``（``--expect`` 人工指定，``expect_source=manual_expect``）
         ⇒ 按它算 pass/fail，来源标注「人工指定期望值（非判据库）」；
      ② ``field`` 命中判据库 ⇒ 按该 field 的期望值算 pass/fail；
      ③ 否则用实测 f 在 28 项期望频率里自动找 ±5% 匹配 ⇒ 找到才 pass；
         找不到 ⇒ ``no_reference``，文案「判据库中无匹配项（无参考值）」，绝不判正常。

    返回 dict：state ∈ {pass, fail, no_signal, no_reference} / expect_hz / dev_pct /
    tol_pct / src / why / manual。
    """
    meas = _hz(item.get("measured_hz"))
    tol = _posnum(item.get("tol_pct")) or SCOPE_TOL_PCT
    exp = _hz(item.get("expect_hz"))
    src_manual = str(item.get("expect_source") or "") == "manual_expect"
    fld = str(item.get("field") or "").strip()
    if meas is None:

        _why = str(item.get("reason") or "").strip()
        return {"state": "no_signal", "expect_hz": exp, "dev_pct": None, "tol_pct": tol,
                "src": "", "manual": src_manual,
                "why": _why or "无有效频率读数（9.9E+37 / <TIMEOUT> / 查询失败）"}

    if exp is None and fld and fld in table and table.get(fld) is not None:
        exp = float(table[fld])
        src = "scope_items_lan.json：%s" % fld
        manual = False
    elif exp is not None:
        src = ("人工指定期望值（--expect，非判据库）" if src_manual else
               "结果 JSON 的人工/外部期望值（非判据库自动匹配）")
        manual = True
    else:

        hit = _scope_freq_matches(table, meas, tol)
        if hit is None:
            return {"state": "no_reference", "expect_hz": None, "dev_pct": None,
                    "tol_pct": tol, "src": "", "manual": False,
                    "why": "判据库中无匹配项（无参考值）"}
        exp, _fld, _dev = hit
        src = "判据库自动匹配 ±%g%%（28 项）" % tol
        manual = False
    dev = (meas - exp) / exp * 100.0
    state = "pass" if abs(dev) <= tol else "fail"
    if state == "pass":
        why = "实测与期望相差 %+.3f%%，在 ±%g%% 以内" % (dev, tol)
    else:
        why = "实测与期望相差 %+.3f%%，超出 ±%g%%" % (dev, tol)
    if manual:
        why = "人工指定期望值（非判据库）；" + why
    return {"state": state, "expect_hz": exp, "dev_pct": dev, "tol_pct": tol,
            "src": src, "manual": manual, "why": why}

def load_scope_result(path: str = "") -> dict:
    """读结果 JSON 并**校验真实性/时效**（只读文件，绝不做网络/仪器查询）。

    只有同时满足下面 4 条，页面才允许显示数字（否则一律「⚠ 无实测数据」）：

    1. `source` ∈ {`lan`, `usbtmc`}（大小写不敏感，其它值/缺失 ⇒ 无效）；
    2. `ts` / `measured_at` 可解析，且在 `AFH03_SCOPE_FRESH_MIN` 分钟（默认 10）内；
    3. 不带 `test:true` / `fake` / `simulated`，且 `source` 不含 test/fake/模拟；
    4. 至少有一条带数值的 `items`。

    约定格式（采集端写）::

        {"items": [{"name","expect_hz","measured_hz","dev_pct","verdict"}],
         "verdict": "正常|不正常|未判定", "reason": "...", "instrument": "DS2102A",
         "source": "lan" | "usbtmc", "ts": "2026-10-18 15:20:31"}

    兼容旧格式：`level` / `freq_median_hz` / `freq_hz` / `idn` / `detail` / `time`
    （**旧格式没有 source/ts 时同样判无效**，不能再被当成实测显示）。
    返回字典额外带 `valid/invalid_reason/measured_at/source_kind/age_min/fresh_min`；
    `stamp` 参与页面缓存键，文件或有效性一变就重画。
    """
    p = path or SCOPE_RESULT_DEFAULT
    out = {"ok": False, "valid": False, "path": p, "items": [], "verdict": "无实测数据",
           "reason": "", "invalid_reason": "", "instrument": "", "source": "",
           "source_kind": "", "transport": "", "signed": False, "sig_prefix": "",
           "ts": "", "measured_at": "", "age_min": None,
           "fresh_min": _scope_fresh_min(), "error": "", "stamp": "",
           "read_at": time.strftime("%H:%M:%S"), "n_items": 0, "raw_n_items": 0,
           "collector_session": "", "collecting": False,
           "file_mtime_ns": 0, "file_size": 0}
    try:
        st = os.stat(p)
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            raise ValueError("JSON 顶层不是对象")

        out["file_mtime_ns"] = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
        out["file_size"] = int(st.st_size)
    except Exception as e:                                             
        out["error"] = "%s: %s" % (type(e).__name__, e)
        out["invalid_reason"] = "未连接示波器（还没有采集结果或文件不可读）"
        out["reason"] = out["invalid_reason"]
        out["stamp"] = "missing"
        return out

    def _item(raw):
        if not isinstance(raw, dict):
            return None
        exp = _hz(raw.get("expect_hz", raw.get("expected_hz")))
        meas = _hz(raw.get("measured_hz", raw.get("freq_hz", raw.get("measured"))))
        dev = raw.get("dev_pct", raw.get("deviation_pct"))
        if dev is not None and str(dev).strip() in ("", "—", "-"):
            dev = None
        try:
            dev = None if dev is None else float(dev)
        except (TypeError, ValueError):
            dev = None
        if dev is None and exp and meas is not None:
            dev = (meas - exp) / exp * 100.0
        raw_v = raw.get("verdict", raw.get("level"))
        rv = str(raw_v or "").strip()
        if rv in ("无数据", "N/A", "NA", "na", "none", "None", "—", "-"):
            vd = "无数据"
        elif rv:
            vd = _vnorm(rv)
        else:
            vd = "未判定" if meas is not None else "无数据"

        tol = _posnum(raw.get("tol_pct"))

        samples = []
        raw_samples = raw.get("samples_v")
        if isinstance(raw_samples, list) and len(raw_samples) <= SCOPE_SAMPLES_MAX:
            try:
                for v in raw_samples:
                    fv = float(v)
                    if not np.isfinite(fv):
                        samples = []
                        break
                    samples.append(fv)
            except (TypeError, ValueError):
                samples = []
        sample_dt = _posnum(raw.get("sample_dt_s"), allow_zero=False)
        if samples and sample_dt is None:
            sample_dt = None                     
        return {"name": str(raw.get("name") or "—"), "expect_hz": exp, "measured_hz": meas,
                "dev_pct": dev, "verdict": vd, "source": raw.get("source", ""),
                "ts": raw.get("ts", ""),
                "verdict_raw": rv,                      
                "period_s": _posnum(raw.get("period_s", raw.get("period"))),
                "vpp_v": _posnum(raw.get("vpp_v", raw.get("vpp")), allow_zero=True),
                "duty": _posnum(raw.get("duty", raw.get("duty_pct")), allow_zero=True),
                "field": str(raw.get("field") or ""),
                "expect_source": str(raw.get("expect_source") or ""),
                "samples_v": samples,
                "sample_dt_s": sample_dt,
                "points": len(samples),
                "wave_source": str(raw.get("wave_source") or ""),
                "wave_vpp_v": _posnum(raw.get("wave_vpp_v"), allow_zero=True),
                "tol_pct": tol,
                "reason": str(raw.get("reason") or ""),
                "channel": str(raw.get("channel") or "")}

    raw_items = d.get("items")
    items = []
    if isinstance(raw_items, list):
        for raw in raw_items:
            it = _item(raw)
            if it is not None:
                items.append(it)

    if not items:
        f = _hz(d.get("freq_median_hz")) or _hz(d.get("freq_hz"))
        if f is not None:
            items.append({"name": "CH1 频率", "expect_hz": None, "measured_hz": f,
                          "dev_pct": None, "verdict": _vnorm(d.get("level") or d.get("verdict")),
                          "source": "", "ts": ""})

    raw_overall = d.get("verdict") or d.get("level")
    if raw_overall:
        verdict = _vnorm(raw_overall)
    else:
        vs = [it["verdict"] for it in items]
        if vs and all(x == "正常" for x in vs):
            verdict = "正常"
        elif any(x == "不正常" for x in vs):
            verdict = "不正常"
        else:
            verdict = "未判定"

    reason = str(d.get("reason") or d.get("detail") or "")
    if not reason:
        if verdict == "正常":
            reason = "全部 %d 项参数在允许范围内" % len(items)
        elif verdict == "不正常":
            bad = next((it for it in items if it["verdict"] == "不正常"), None)
            if bad is not None:
                reason = "%s：实测 %s" % (bad["name"], _fmt_hz(bad["measured_hz"]))
                if bad["dev_pct"] is not None:
                    reason += "，偏差 %s%%" % _fmt_dev(bad["dev_pct"])
            else:
                reason = "存在不合格参数"
        else:
            miss = [it["name"] for it in items if it["verdict"] in ("无数据", "未判定")]
            reason = ("缺少 %d 项数据，暂不能判定" % len(miss)) if miss else "暂无判定结论"

    inst = d.get("instrument")
    if not inst and isinstance(d.get("idn"), str):
        ps = [x.strip() for x in d["idn"].split(",")]
        inst = ps[1] if len(ps) > 1 else ps[0]
    src = d.get("source") or d.get("transport") or ""
    if isinstance(src, (dict, list)):
        src = json.dumps(src, ensure_ascii=False)
    src = str(src or "").strip()
    ts = d.get("ts") or d.get("measured_at") or d.get("time") or ""

    
    transport = str(d.get("transport") or "").strip().lower()

    base = "%d_%d" % (int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
                      int(st.st_size))
    fresh = out["fresh_min"]
    okv, why, extra = _scope_check(d, src, items, fresh)
    out.update(instrument=str(inst or ""), source=src, source_kind=_scope_source_kind(src),
               transport=transport, sig_prefix=str(extra.get("sig") or "")[:12],
               raw_n_items=len(items), error="")
    if not okv:

        out.update(ok=False, valid=False, signed=False, items=[], n_items=0,
                   verdict="无实测数据",
                   reason=why, invalid_reason=why,
                   measured_at=extra.get("measured_at", ""), ts=str(ts or ""),
                   age_min=extra.get("age_min"),
                   collector_session=extra.get("session", ""),
                   collecting=bool(extra.get("collecting")),
                   stamp="%s_bad_%s" % (base, extra.get("bucket", "")))
        return out

    out.update(ok=True, valid=True, signed=True, items=items, verdict=verdict, reason=reason,
               n_items=len(items), measured_at=extra.get("measured_at", ""),
               age_min=extra.get("age_min"), ts=str(ts or ""),
               collector_session=extra.get("session", ""),
               collecting=bool(extra.get("collecting")),
               stamp="%s_ok" % base)
    return out

def _scope_transport_label(res) -> str:
    """顶栏"来源"文案：transport=vxi11 ⇒ VXI-11；否则用 source（LAN / USBTMC）。"""
    t = str((res or {}).get("transport") or "").strip().lower()
    if t == "vxi11":
        return "VXI-11"
    if t:
        return t.upper()
    return (str((res or {}).get("source_kind") or (res or {}).get("source") or "—")).upper()

def load_local_measure_result(path: str = "") -> dict:
    """★ 降级路径：读**本机刚测完、但签名失败**的未签名结果（``signed:false``）。

    只在 ``ScopeMeasurer`` 明确报告 ``signed=false`` 时调用；页面必须写清
    「未签名(仅本地测量)」，**绝不冒充签名数据**。防伪边界不放宽：
      * 必须是本工具写的文件（``origin == "ui_vxi11_measure"`` 且 ``signed is False``）；
      * source 必须是 lan、transport 必须是 vxi11；
      * ts 必须在新鲜度阈值内；
      * 必须至少有 measured_hz 或 vpp 之一。
    任何一条不满足 ⇒ 返回 ``{}``（页面回到"无实测数据"）。
    """
    p = path or SCOPE_TEMP_RESULT
    try:
        st = os.stat(p)
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:                                                  
        return {}
    if not isinstance(d, dict):
        return {}
    if str(d.get("origin") or "") != "ui_vxi11_measure" or d.get("signed") is not False:
        return {}
    if _scope_source_kind(d.get("source")) != "lan" or \
            str(d.get("transport") or "").lower() != "vxi11":
        return {}
    t, tdisp, terr = _scope_ts(d.get("ts") or d.get("measured_at"))
    if terr or t is None:
        return {}
    fresh = _scope_fresh_min()
    age = time.time() - t
    if age < -120 or age > fresh * 60.0 + 0.5:
        return {}
    raw_items = d.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return {}
    it = raw_items[0] if isinstance(raw_items[0], dict) else {}
    meas = _hz(it.get("measured_hz"))
    period = _posnum(it.get("period_s", it.get("period")))
    vpp = _posnum(it.get("vpp_v", it.get("vpp")), allow_zero=True)
    if meas is None and period is None and vpp is None:
        return {}
    if meas is None and period:
        meas = 1.0 / period
    if period is None and meas:
        period = 1.0 / meas
    item = {"name": str(it.get("name") or "实测频率"), "expect_hz": _hz(it.get("expect_hz")),
            "measured_hz": meas, "dev_pct": None, "verdict": "未判定", "source": "lan",
            "ts": d.get("ts", ""), "verdict_raw": str(it.get("verdict") or "measured"),
            "period_s": period, "vpp_v": vpp, "duty": _posnum(it.get("duty"), allow_zero=True),
            "field": str(it.get("field") or ""),
            "expect_source": str(it.get("expect_source") or ""),
            "samples_v": [], "sample_dt_s": None, "points": 0,
            "wave_source": "", "wave_vpp_v": None, "tol_pct": SCOPE_TOL_PCT,
            "reason": str(it.get("reason") or ""), "channel": "CH1"}
    out = {"ok": True, "valid": True, "signed": False, "unsigned": True,
           "path": p, "items": [item], "n_items": 1, "raw_n_items": 1,
           "verdict": "未判定", "reason": "未签名(仅本地测量)：签名 API 失败，读数只在本机显示",
           "invalid_reason": "",
           "unsigned_reason": str((d.get("sign_error") or d.get("temp_reason")
                                   or "签名 API 未成功")),
           "instrument": str(d.get("instrument") or "DS2102A"),
           "source": "lan", "source_kind": "lan",
           "transport": str(d.get("transport") or "vxi11").lower(),
           "sig_prefix": "", "ts": str(d.get("ts") or ""),
           "measured_at": tdisp, "age_min": age / 60.0, "fresh_min": fresh,
           "error": "", "read_at": time.strftime("%H:%M:%S"),
           "collector_session": "", "collecting": False,
           "stamp": "unsigned_%d_%d" % (int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
                                        int(st.st_size))}
    return out

def _wave_page(layout, measuring=False):
    """波形页按钮（**绘制与触摸命中共用这一份 rect**）。

    【重新测量】= 再跑一次 VXI-11 测量（后台线程；测量中再点只会提示，不会叠加）。
    """
    return {"buttons": [
        {"id": "retest", "label": ("测量中…" if measuring else "重新测量"),
         "rect": [16, 530, 504, 588],
         "action": "retest", "style": "primary", "font_scale": 0.95},
        {"id": "back", "label": "返   回", "rect": [520, 530, 1008, 588],
         "action": "back", "style": "alt", "font_scale": 1.0},
    ]}

class ScopeMeasurer:
    """★ 后台测量控制器：点【波形检测】/【重新测量】→ 起线程跑子进程，UI 绝不阻塞。

    * 子进程：``python3 /userdata/work2/scope_quick.py --measure --result …``
      （pyvisa + VXI-11；测量 3 条 + 波形段 Preamble?/DATA?/ERRor?；写签名结果）；
    * **不传 --expect**：页面判定走判据库自动匹配，避免人工期望值冒充数据库；
    * 主线程每帧只读 ``snapshot()``（不 join、不 wait）；
    * 同一时刻只允许一个测量；重复点只会得到 ``False``。
    """

    def __init__(self, result_path: str = "", temp_path: str = ""):
        self.result_path = result_path or SCOPE_RESULT_DEFAULT
        self.temp_path = temp_path or SCOPE_TEMP_RESULT
        self.lock = threading.Lock()
        self.status = "idle"          
        self.seq = 0                  
        self.t0 = 0.0
        self.t1 = 0.0
        self.summary = {}
        self.error = ""
        self.signed = False
        self.local_only = False
        self.result_mtime_ns = 0      
        self.result_size = 0
        self.stdout_tail = ""
        self.stderr_tail = ""
        self.thread = None

    def start(self, force: bool = False) -> bool:
        with self.lock:
            if self.status == "running":
                return False
            if not force and os.environ.get("AFH03_SCOPE_AUTO_MEASURE", "1") == "0":
                return False
            self.status = "running"
            self.t0 = time.time()
            self.t1 = 0.0
            self.seq += 1
            self.summary = {}
            self.error = ""
            self.signed = False
            self.local_only = False
            self.result_mtime_ns = 0
            self.result_size = 0
            self.thread = threading.Thread(target=self._run, name="scope_measure",
                                           daemon=True)
            th = self.thread
        print("[scope] 自动测量开始：%s（scope_quick/VXI-11，测量 3 条 + 波形段，DATA? 1 次）"
              % self.result_path, flush=True)
        th.start()
        return True

    def running(self) -> bool:
        return self.status == "running"

    def snapshot(self) -> dict:
        """给渲染用的一份快照（st_time 由调用方按需格式化）。"""
        with self.lock:
            now = time.time()
            elapsed = (self.t1 or now) - self.t0 if self.t0 else 0.0
            return {"status": self.status, "seq": self.seq,
                    "running": (self.status == "running"),
                    "t0": self.t0, "t1": self.t1, "elapsed": max(0.0, elapsed),
                    "started_at": (time.strftime("%H:%M:%S", time.localtime(self.t0))
                                   if self.t0 else ""),
                    "finished_at": (time.strftime("%H:%M:%S", time.localtime(self.t1))
                                    if self.t1 else ""),
                    "summary": dict(self.summary), "error": self.error,
                    "signed": self.signed, "local_only": self.local_only,
                    "result_mtime_ns": self.result_mtime_ns,
                    "result_size": self.result_size,
                    "elapsed_s": (round(self.t1 - self.t0, 2) if self.t1 and self.t0 else None),
                    "result_path": self.result_path, "temp_path": self.temp_path}

    def _run(self):
        out_text = err_text = ""
        summary = {}
        error = ""
        result_stat = None
        try:
            env = dict(os.environ)
            env["PYTHONPATH"] = HERE + os.pathsep + env.get("PYTHONPATH", "")
            cmd = [sys.executable, "-u", SCOPE_QUICK_PATH, "--measure",
                   "--result", self.result_path]
            _scope_ip = (os.environ.get("AFH03_SCOPE_IP") or
                         os.environ.get("AFH03_SCOPE_HOST") or "").strip()
            if _scope_ip:
                cmd += ["--ip", _scope_ip]
            cp = subprocess.run(cmd, cwd=HERE, env=env, timeout=SCOPE_MEASURE_TIMEOUT_S,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace")
            out_text, err_text = cp.stdout or "", cp.stderr or ""

            
            if cp.returncode not in (0, 3):
                tail = [x.strip() for x in out_text.splitlines() if x.strip()]
                summary = {"ok": False, "signed": False, "rc": cp.returncode,
                           "error": (tail[-1] if tail else
                                     "scope_quick 退出码 %s（无有效结果）" % cp.returncode)}
            else:
                try:
                    with open(self.result_path, encoding="utf-8") as f:
                        d = json.load(f)
                    result_stat = os.stat(self.result_path)   
                    it = (d.get("items") or [{}])[0] if isinstance(d.get("items"), list) else {}
                    summary = {"ok": bool(d.get("sig")), "signed": bool(d.get("sig")),
                               "measured_hz": it.get("measured_hz"),
                               "vpp_v": it.get("vpp_v"), "duty": it.get("duty"),
                               "points": it.get("points"), "samples_v": it.get("samples_v") or [],
                               "wave_source": it.get("wave_source"),
                               "rc": cp.returncode}
                except Exception as e:                                 
                    summary = {"ok": False, "signed": False, "rc": cp.returncode,
                               "error": "未读到结果文件：%s: %s" % (type(e).__name__, e)}
        except subprocess.TimeoutExpired:
            error = "测量超时（> %g 秒）" % SCOPE_MEASURE_TIMEOUT_S
        except Exception as e:                                         
            error = "测量子进程启动失败：%s: %s" % (type(e).__name__, e)
        signed = bool(summary.get("signed"))
        ok = bool(summary.get("ok"))
        if not error and not ok:
            error = str(summary.get("error") or "测量失败（无有效读数）")
        with self.lock:
            self.summary = summary
            self.signed = signed
            self.local_only = bool(ok and not signed)
            if result_stat is not None:
                self.result_mtime_ns = int(getattr(result_stat, "st_mtime_ns",
                                                   int(result_stat.st_mtime * 1e9)))
                self.result_size = int(result_stat.st_size)
            self.error = error if not (ok or signed) else ""
            self.stdout_tail = out_text[-800:]
            self.stderr_tail = err_text[-800:]
            self.t1 = time.time()
            self.seq += 1
            self.status = "done" if (ok or signed) else "error"
            st, seq = self.status, self.seq
            el = self.t1 - self.t0
        print("[scope] 测量结束 status=%s signed=%s ok=%s f=%s vpp=%s 用时=%.2fs%s"
              % (st, signed, ok, summary.get("measured_hz"), summary.get("vpp_v"), el,
                 ("  错误=%s" % error) if error else ""), flush=True)
        if self.stderr_tail.strip():
            print("[scope][stderr] %s" % self.stderr_tail.strip()[-300:], flush=True)

def _draw_sampled_wave(img, box, samples, dt_s, f_hz, C):
    """★ 逐点绘制**示波器屏幕真实采样**（NORMal/BYTE），不拟合、不重建。

    横轴：``x = i * sample_dt_s``（Preamble 的 xinc）；没有 dt 时退回采样点序号。
    纵轴：采样值（scope_quick 已按 LSB 换算并去均值），按实际范围缩放，绝不裁掉峰。
    """
    x0, y0, x1, y1 = [int(v) for v in box]
    w, h = x1 - x0, y1 - y0
    n = len(samples or [])
    if w < 60 or h < 30 or n < 2:
        return False
    grid = C.get("card_edge", C["dim"])
    axis = C.get("preview_frame", C["dim"])
    for i in range(1, 8):
        cv2.line(img, (x0 + int(round(w * i / 8.0)), y0),
                 (x0 + int(round(w * i / 8.0)), y1), grid, 1, lineType=cv2.LINE_AA)
    for j in range(1, 4):
        cv2.line(img, (x0, y0 + int(round(h * j / 4.0))),
                 (x1, y0 + int(round(h * j / 4.0))), grid, 1, lineType=cv2.LINE_AA)
    cv2.rectangle(img, (x0, y0), (x1, y1), axis, 1, lineType=cv2.LINE_AA)
    ys = np.asarray(samples, dtype=np.float32)
    ys = ys - float(np.mean(ys, dtype=np.float64))
    ymax_abs = float(np.max(np.abs(ys))) if ys.size else 0.0
    if not np.isfinite(ymax_abs) or ymax_abs <= 1e-9:
        ymax_abs = 1.0
    amp = h * 0.44
    ymid = y0 + h / 2.0
    xmax = (n - 1) * float(dt_s or 0.0)
    pts = np.empty((n, 1, 2), np.int32)
    for i in range(n):
        px = x0 + int(round(w * i / float(n - 1)))
        py = int(round(ymid - (float(ys[i]) / ymax_abs) * amp))
        pts[i, 0, 0] = px
        pts[i, 0, 1] = max(y0, min(y1, py))
    cv2.polylines(img, [pts], False, C["accent"], 2, lineType=cv2.LINE_AA)
    cv2.line(img, (x0, int(round(ymid))), (x1, int(round(ymid))), C["dim"], 1,
             lineType=cv2.LINE_AA)

    for val, yy in ((ymax_abs, y0 + 4), (0.0, int(round(ymid)) - 4),
                    (-ymax_abs, y1 - 12)):
        t = _fmt_volt(val)
        try:
            tw, _th = text_size(t, 0.36)
        except Exception:                                              
            tw = len(t) * 6
        draw_text(img, t, (x0 - 8 - int(tw), int(yy) + 12), scale=0.36,
                  color=C["dim"], th=1)

    labels = []
    period = (1.0 / f_hz) if (f_hz and f_hz > 0) else None
    if period and xmax > 0 and 2.0 * period <= xmax * 1.10:
        labels = [(0.0, "0"), (0.5 * period, "T/2"), (period, "T"),
                  (1.5 * period, "3T/2"), (2.0 * period, "2T")]
    elif xmax > 0:
        labels = [(0.0, "0"), (xmax / 2.0, _fmt_period(xmax / 2.0)),
                  (xmax, _fmt_period(xmax))]
    else:
        labels = [(0.0, "0"), (0.5, "点序"), (1.0, "%d" % n)]
    for frac, lb in labels:
        if xmax > 0 and frac > xmax * 1.02:
            continue
        px = x0 + (w * frac / xmax if xmax > 0 else w * frac)
        _center_text(img, lb, px, y1 + 22, 0.36, C["dim"], th=1)

    try:
        tw, _th = text_size("真实采样", 0.34)
    except Exception:                                                  
        tw = 52
    draw_text(img, "真实采样", (x1 - int(tw), y0 + 8), scale=0.34,
              color=C.get("accent", C["text"]), th=1)
    return True

def _wave_elapsed_text(res, meas) -> str:
    """只显示**本轮测量**的用时；拿不到本轮值就 ``—``（不再回放上一轮的 4.09s）。

    判定「本轮」用文件身份，而不是只看 ``meas.elapsed_s``：
      * 测量完成状态必须 ``done``；
      * 本次子进程写出的结果文件 mtime_ns/size 必须与页面当前读到的文件**完全一致**
        （失败的一轮不会匹配旧文件，因此不会把上一轮耗时搬到旧数据上）；
      * 未签名降级结果只认本次 ``local_only``。
    """
    if not isinstance(meas, dict) or meas.get("status") != "done":
        return "—"
    try:
        el = meas.get("elapsed_s")
        if el is None:
            return "—"
        res = res if isinstance(res, dict) else {}
        if res.get("unsigned"):
            same = bool(meas.get("local_only"))
        else:
            m_mtime = int(meas.get("result_mtime_ns") or 0)
            m_size = int(meas.get("result_size") or 0)
            same = (m_mtime > 0 and m_mtime == int(res.get("file_mtime_ns") or 0)
                    and m_size == int(res.get("file_size") or 0))
        return ("%.2fs" % float(el)) if same else "—"
    except (TypeError, ValueError):
        return "—"

def draw_wave(layout, scope=None, back_page=True):
    """波形检测页：**示数 + 故障判定 + 真实屏幕采样逐点波形**（绝不画摄像头帧）。

    真实性规则见 `load_scope_result`（source=lan/usbtmc、HMAC 签名、ts 在 10 分钟内、非测试数据）。
    波形规则（2026-10-25 用户要求，**绝不幻觉**）：
      ① 只有 items[0].samples_v（scope_quick 的 NORMal/BYTE 屏幕数据）⇒ **真实波形**，
         标题写「实测波形（示波器屏幕数据 NORMal/BYTE，N 点）」；
      ② **没有任何真实采样 ⇒ 一条波形线都不画**，只显示提示「⚠ 无采样数据（本次未读到示波器波形）」。
         旧的「按 f/Vpp 重建正弦/方波示意」分支已整体删除，不允许再复活。
    **无效时**：三块卡片都写「无实测数据」+ 原因，参数表与波形区**一个数字都不画**。

    版式（1024x600）::

        顶栏  26..102  : 波 形 检 测 + 实测于 hh:mm:ss ｜ 来源 ｜ 仪器 ｜ 签名 HMAC ✓
        示数卡 [16,106,430,340]   : 频率 f / 周期 T / Vpp / duty / 判定
        波形卡 [442,106,1008,340] : 仅真实采样曲线（x=i*dt；无采样则空白+提示）
        参数卡 [16,348,1008,522]  : 名称 | 期望 | 实测 | 偏差% | 结果（4 行）
        按钮   [16,530,504,588]【重测】  [520,530,1008,588]【返回】
    """
    C = layout["colors"]; R = layout.get("radius", {})
    W, H = layout["canvas"]["w"], layout["canvas"]["h"]
    res = scope if isinstance(scope, dict) else {}
    valid = bool(res.get("valid"))

    items = list(res.get("items") or []) if valid else []
    it0 = items[0] if items else {}
    samples = list(it0.get("samples_v") or []) if items else []
    has_real_wave = bool(samples and len(samples) >= 2)
    fresh_txt = "%g" % float(res.get("fresh_min") or SCOPE_FRESH_MIN_DEFAULT)

    meas = res.get("_meas") if isinstance(res.get("_meas"), dict) else {}
    m_status = str(meas.get("status") or "idle")
    m_running = (m_status == "running")
    m_elapsed = float(meas.get("elapsed") or 0.0)
    signed_ok = bool(valid and res.get("signed"))
    unsigned = bool(valid and res.get("unsigned"))
    sig_txt = ("签名 HMAC ✓" if signed_ok else
               ("未签名(仅本地测量)" if unsigned else "签名 HMAC —"))
    src_txt = "VXI-11" if (m_running and not valid) else _scope_transport_label(res)
    elapsed_txt = _wave_elapsed_text(res, meas)
    img = np.full((H, W, 3), C["bg"], np.uint8)
    _grad_v(img, (0, 0, W, H), C["bg"], C.get("bg_bottom", C["bg"]))
    rc = int(R.get("card", 14))

    bar_y1 = 102
    _grad_v(img, (0, 26, W, bar_y1), C["title_bar"], C.get("title_bar2", C["title_bar"]))
    cv2.line(img, (0, bar_y1), (W - 1, bar_y1), C.get("accent", C["dim"]), 2, lineType=cv2.LINE_AA)
    draw_text(img, "波 形 检 测", (40, 74), scale=1.0, color=C["title_text"], th=2)
    note = ("示数 + 判定 + 真实屏幕采样 · 无摄像头画面" if has_real_wave else
            "示数 + 判定 · 无摄像头画面（无采样不画波形）")
    try:
        nw, _nh = text_size(note, 0.46)
    except Exception:                                                  
        nw = len(note) * 7
    draw_text(img, note, (W - 24 - int(nw), 74), scale=0.46, color=C["dim"], th=1)
    if m_running:
        sub = "%s 已 %.1fs  ｜  来源 %s  ｜  仪器 DS2102A  ｜  后台线程测量，UI 不阻塞" % (
            SCOPE_MEASURE_HINT, m_elapsed, src_txt)
        sub_col = C["unk"]
    elif valid:
        if unsigned:
            sub = ("实测于 %s  ｜  来源 %s  ｜  仪器 %s  ｜  未签名(仅本地测量)  ｜  用时 %s"
                   % (res.get("measured_at") or res.get("ts") or "—", src_txt,
                      res.get("instrument") or "—", elapsed_txt))
        else:
            sub = "实测于 %s  ｜  来源 %s  ｜  仪器 %s  ｜  %s  ｜  用时 %s  ｜  会话 %s" % (
                res.get("measured_at") or res.get("ts") or "—", src_txt,
                res.get("instrument") or "—", sig_txt, elapsed_txt,
                (res.get("collector_session") or "—")[:8])
        sub_col = C["unk"] if unsigned else C["dim"]
    elif m_status == "error":
        sub = "测量失败：%s  ｜  点【重新测量】重试" % (meas.get("error") or "未知错误")
        sub_col = C["bad"]
    else:
        sub = "无实测数据  ｜  点【重新测量】立即测（scope_quick/VXI-11，约 6 秒，%s 分钟内有效）" % fresh_txt
        sub_col = C["unk"]
    draw_text(img, _fit_text(sub, W - 60, 0.42), (40, 100), scale=0.42, color=sub_col, th=1)

    table, tsrc, tmeta = _scope_expect_table()
    judge = {"state": "no_signal", "expect_hz": None, "dev_pct": None,
             "tol_pct": SCOPE_TOL_PCT, "src": "", "why": ""}
    if valid and items:
        judge = _scope_judge(items[0], table)
    st = judge["state"] if valid else ""
    vcol = {"pass": C["ok"], "fail": C["bad"]}.get(st, C["unk"])

    vtxt = {"pass": "✔ 正常", "fail": "✘ 异常",
            "no_signal": "⚠ 无信号", "no_reference": "⚠ 判据库无匹配"}.get(st, "—")

    SX0, SY0, SX1, SY1 = 16, 106, 430, 340
    _rrect_panel(img, [SX0, SY0, SX1, SY1], C["card"], C.get("card_edge", C["dim"]), rc)
    _rrect_fill(img, [SX0, SY0, SX0 + 8, SY1], vcol if valid else C["unk"], 4)
    draw_text(img, "实 测 示 数", (32, 130), scale=0.46, color=C["text"], th=1)
    cv2.line(img, (32, 142), (128, 142), C.get("accent", C["dim"]), 2, lineType=cv2.LINE_AA)
    if m_running and not valid:
        draw_text(img, SCOPE_MEASURE_HINT, (32, 196), scale=0.82, color=C["unk"], th=2)
        draw_text(img, _fit_text("VXI-11  " + SCOPE_ADDR_HINT, SX1 - 48, 0.36),
                  (32, 232), scale=0.36, color=C["text"], th=1)
        draw_text(img, _fit_text("CH1 周期/Vpp/duty + 真实屏幕采样 ｜ 已用 %.1fs" % m_elapsed,
                                 SX1 - 48, 0.36), (32, 262), scale=0.36, color=C["text"], th=1)
        draw_text(img, "后台线程测量：页面不冻结，测完自动刷新", (32, 330), scale=0.36,
                  color=C["dim"], th=1)
    elif valid and items:
        it0 = items[0]
        f_hz = _hz(it0.get("measured_hz"))
        if unsigned:
            _ut = "未签名(仅本地测量)"
            try:
                _uw, _uh = text_size(_ut, 0.34)
            except Exception:                                          
                _uw = len(_ut) * 7
            draw_text(img, _ut, (SX1 - 16 - int(_uw), 130), scale=0.34,
                      color=C["unk"], th=1)
        rows = (("频率 f", _fmt_hz_full(f_hz)),
                ("周期 T", _fmt_period(it0.get("period_s"))),
                ("幅度 Vpp", _fmt_vpp(it0.get("vpp_v"))),
                ("占空比", _fmt_duty(it0.get("duty"))))
        for k, (lab, val) in enumerate(rows):
            y = 168 + k * 30
            draw_text(img, lab, (32, y), scale=0.46, color=C["dim"], th=1)
            draw_text(img, _fit_text(val, SX1 - 126, 0.52), (118, y), scale=0.52,
                      color=C["title_text"], th=1)
        draw_text(img, "判 定", (32, 300), scale=0.50, color=C["dim"], th=1)
        draw_text(img, vtxt, (118, 300), scale=0.66, color=vcol, th=2)

        why = judge.get("why") or ""
        if judge.get("manual"):
            pass                          
        elif judge.get("src"):
            why = "%s（口径：%s）" % (why, judge["src"])
        draw_text(img, _fit_text(why, SX1 - 48, 0.34), (32, 330), scale=0.34,
                  color=C["text"], th=1)
    elif m_status == "error":
        draw_text(img, "✘ 测量失败", (32, 196), scale=0.78, color=C["bad"], th=2)
        draw_text(img, _fit_text(res.get("invalid_reason") or meas.get("error") or "",
                                 SX1 - 48, 0.36), (32, 232), scale=0.36, color=C["text"], th=1)
        draw_text(img, "点【重新测量】重试；示波器/网络恢复后再测", (32, 330), scale=0.36,
                  color=C["dim"], th=1)
    else:
        draw_text(img, "⚠ 无实测数据", (32, 196), scale=0.86, color=C["unk"], th=2)
        draw_text(img, _fit_text(res.get("invalid_reason") or res.get("reason") or "",
                                 SX1 - 48, 0.36), (32, 232), scale=0.36, color=C["text"], th=1)
        draw_text(img, "点【重新测量】立即测（scope_quick/VXI-11，约 6 秒）", (32, 330),
                  scale=0.36, color=C["dim"], th=1)

    WX0, WY0, WX1, WY1 = 442, 106, 1008, 340
    _rrect_panel(img, [WX0, WY0, WX1, WY1], C["card"], C.get("card_edge", C["dim"]), rc)
    f_hz = _hz(it0.get("measured_hz"))
    if has_real_wave:
        ttl = "实测波形（示波器屏幕数据 NORMal/BYTE，%d 点）" % len(samples)
        draw_text(img, _fit_text(ttl, 540, 0.38), (458, 130), scale=0.38,
                  color=C["title_text"], th=1)
        _draw_sampled_wave(img, (504, 148, 992, 278), samples,
                           it0.get("sample_dt_s") or 0.0, f_hz, C)
        _center_text(img, "示波器屏幕逐点采样 · 真实波形（非拟合/非生成）",
                     (WX0 + WX1) / 2, WY1 - 10, 0.38, C["ok"], th=1)
    else:

        
        draw_text(img, "波 形 采 集", (458, 130), scale=0.46, color=C["text"], th=1)
        if m_running and not valid:
            _center_text(img, "⏳ 等待真实采样…（后台测量中）", (WX0 + WX1) / 2, 205,
                         0.56, C["unk"], th=1)
            _center_text(img, "本次还没有 samples_v ⇒ 不画任何波形",
                         (WX0 + WX1) / 2, 246, 0.38, C["dim"], th=1)
        elif valid and items:
            _center_text(img, "⚠ 无采样数据（本次未读到示波器波形）",
                         (WX0 + WX1) / 2, 205, 0.62, C["unk"], th=2)
            _center_text(img, "只显示上面的实测示数；不拟合、不生成波形",
                         (WX0 + WX1) / 2, 246, 0.38, C["dim"], th=1)
        elif m_status == "error":
            _center_text(img, "⚠ 无采样数据（本次测量失败）", (WX0 + WX1) / 2, 205,
                         0.58, C["bad"], th=1)
            _center_text(img, "不画波形；点【重新测量】重试", (WX0 + WX1) / 2, 246,
                         0.38, C["dim"], th=1)
        else:
            _center_text(img, "⚠ 无实测数据（无采样可画）", (WX0 + WX1) / 2, 205,
                         0.58, C["unk"], th=1)
            _center_text(img, "点【重新测量】立即测（scope_quick/VXI-11，约 6 秒）",
                         (WX0 + WX1) / 2, 246, 0.38, C["dim"], th=1)
        _center_text(img, "无真实采样 · 不绘制任何波形", (WX0 + WX1) / 2, WY1 - 10,
                     0.38, C["dim"], th=1)

    TX0, TY0, TX1, TY1 = 16, 348, 1008, 522
    _rrect_panel(img, [TX0, TY0, TX1, TY1], C["card"], C.get("card_edge", C["dim"]), rc)
    HH = 34
    hdr = C.get("chip_bg", C["card"])
    _rrect_fill(img, [TX0, TY0, TX1, TY0 + HH], hdr, rc)
    cv2.rectangle(img, (TX0, TY0 + rc), (TX1, TY0 + HH), hdr, -1)
    COLS = [(34, "信号名称"), (330, "期望"), (470, "实测"), (620, "偏差%"), (760, "结果")]
    for x, label in COLS:
        draw_text(img, label, (x, TY0 + 24), scale=0.46, color=C["dim"], th=1)
    if tmeta.get("path"):
        note2 = "判定口径：scope_items_lan.json（%d 项，%d 项带期望频率），容差 ±%g%%" % (
            int(tmeta.get("rows") or 0), int(tmeta.get("freq") or 0), SCOPE_TOL_PCT)
    else:
        note2 = "判定口径：内置 %d 条期望频率（未找到 28 项 json），容差 ±%g%%" % (
            int(tmeta.get("freq") or 0), SCOPE_TOL_PCT)
    try:
        nw2, _h2 = text_size(note2, 0.32)
    except Exception:                                                  
        nw2 = len(note2) * 6
    draw_text(img, _fit_text(note2, 560, 0.32), (TX1 - 16 - int(min(nw2, 560)), TY1 - 7),
              scale=0.32, color=C["dim"], th=1)
    if valid and items:
        rows_y0, row_h = TY0 + HH, 32
        for i in range(4):
            ry = rows_y0 + i * row_h
            base = ry + 25
            if i:
                cv2.line(img, (TX0 + 12, ry), (TX1 - 12, ry),
                         C.get("card_edge", C["dim"]), 1)
            if i < len(items):
                it = items[i]
                jd = _scope_judge(it, table)
                icol = {"pass": C["ok"], "fail": C["bad"]}.get(jd["state"], C["unk"])
                draw_text(img, _fit_text(it.get("name") or "—", 280, 0.48),
                          (COLS[0][0], base), scale=0.48, color=C["text"], th=1)
                draw_text(img, _fmt_hz(jd.get("expect_hz")), (COLS[1][0], base),
                          scale=0.48, color=C["text"], th=1)
                draw_text(img, _fmt_hz(it.get("measured_hz")), (COLS[2][0], base),
                          scale=0.48, color=C["text"], th=1)
                draw_text(img, _fmt_dev(jd.get("dev_pct")), (COLS[3][0], base),
                          scale=0.48, color=C["text"], th=1)
                iv = {"pass": "正常", "fail": "异常",
                      "no_signal": "无信号", "no_reference": "无参考值"}[jd["state"]]
                _dot(img, COLS[4][0] + 8, base - 6, 5, icol)
                draw_text(img, iv, (COLS[4][0] + 20, base), scale=0.48, color=icol, th=1)
            else:
                for x, _lab in COLS:
                    draw_text(img, "—", (x, base), scale=0.48, color=C["dim"], th=1)
        if len(items) > 4:
            more = "共 %d 项（显示前 4）" % len(items)
            draw_text(img, more, (TX1 - 16 - 130, TY0 + 22), scale=0.34,
                      color=C["dim"], th=1)
    else:
        if m_running:
            _center_text(img, "%s · 参数表稍后自动刷新" % SCOPE_MEASURE_HINT,
                         (TX0 + TX1) / 2, TY0 + HH + 66, 0.72, C["unk"], th=2)
            _center_text(img, "后台线程测量，页面不冻结；测完自动落盘 + 签名",
                         (TX0 + TX1) / 2, TY0 + HH + 106, 0.46, C["dim"], th=1)
        elif m_status == "error":
            _center_text(img, "测量失败 · 参数表已清空",
                         (TX0 + TX1) / 2, TY0 + HH + 66, 0.86, C["bad"], th=2)
            _center_text(img, "点【重新测量】重试（scope_quick/VXI-11，约 6 秒）",
                         (TX0 + TX1) / 2, TY0 + HH + 106, 0.46, C["dim"], th=1)
        else:
            _center_text(img, "无实测数据 · 参数表已清空",
                         (TX0 + TX1) / 2, TY0 + HH + 66, 0.86, C["unk"], th=2)
            _center_text(img, "点【重新测量】立即测（scope_quick/VXI-11，约 6 秒）",
                         (TX0 + TX1) / 2, TY0 + HH + 106, 0.46, C["dim"], th=1)

    _buttons(img, layout, _wave_page(layout, measuring=m_running))
    return img

_BASE_CACHE: dict = {}

def render_cached(layout, state, frame, vobj, info, scope, dbg, err, toast, marker_txt,
                  cache_note=""):
    """★ 底板缓存：静态文字只在"键"变化时画一次；每帧只 `copy + 预览矩形更新`。

    键 = (state, marker_txt, err, toast, 结论+依据, scope 结论, dbg 文本, 版式文件)
    → 大多数帧键不变，于是**不再每帧渲染中文**（这是 CPU 的大头）。
    """
    v = (vobj or {}).get("verdict", VERDICT_UNK)
    reason = (vobj or {}).get("reason", "")
    _m = (scope or {}).get("_meas") if isinstance((scope or {}).get("_meas"), dict) else {}
    key = (state, marker_txt or "", err or "", toast or "", v, reason,
           (scope or {}).get("verdict", ""), (scope or {}).get("message", ""),
           (scope or {}).get("stamp", ""), (scope or {}).get("read_at", ""),

           (scope or {}).get("valid"), (scope or {}).get("invalid_reason", ""),

           (scope or {}).get("signed"), (scope or {}).get("unsigned"),
           (scope or {}).get("transport", ""),
           _m.get("status"), _m.get("seq"), int(_m.get("elapsed") or 0),
           (dbg or {}).get("taps"), (dbg or {}).get("hit"), os.path.getmtime(LAYOUT_DEFAULT)
           if os.path.isfile(LAYOUT_DEFAULT) else 0,
           time.strftime("%H:%M"))          
    base = _BASE_CACHE.get(key)
    if base is None:

        if state == "page1":
            base = draw_page1(layout, None, toast=toast, warn="", dbg=dbg, err=err,
                              marker_txt=marker_txt)
        elif state == "page2":
            base = draw_page2(layout, None, vobj, toast=toast, dbg=dbg, err=err,
                              marker_txt=marker_txt)
        else:
            base = draw_wave(layout, scope)
        _BASE_CACHE.clear()                      
        _BASE_CACHE[key] = base
    canvas = base.copy()
    if state == "page1":

        pv = page(layout, "page1")["preview"]
        C = layout["colors"]
        _fit(canvas, frame, pv, label=("正在取流…" if frame is None else ""),
             bg=C.get("preview_bg"))
        _round_corners(canvas, pv, int(layout.get("radius", {}).get("preview", 10)),
                       C.get("preview_frame", C["dim"]))
        _corner_marks(canvas, pv, C.get("accent", C["dim"]), inset=12, ln=22, t=2)
    elif state == "page2":
        _fit(canvas, frame, page(layout, "page2")["preview"], label="（没有静止图）")

    return canvas

class MarkerWorker:
    """★ 标记检测放进**独立线程**：渲染循环不再被全分辨率检测阻塞。

    * 检测频次**低频**（默认 0.8s 一次；标记不会瞬移）；
    * `min_side_px/max_side_px` **自适应**（不写死 60/147）：按帧短边比例给范围；
    * 结果放 `self.hit/self.hits`（加锁），主循环只读，永不等待。
    """

    def __init__(self, mi, interval: float = 0.8, verbose: bool = True):
        self.mi, self.interval, self.verbose = mi, float(interval), verbose
        self.frame = None
        self.lock = None
        self.hit = None
        self.hits = []
        self.progress = (0, 0)      
        self.n = 0
        self.t_last = 0.0
        self._stop = False
        self._th = None
        try:
            import threading
            self.lock = threading.Lock()
        except Exception:                                            
            self.lock = None

    def set_frame(self, frame):
        if self.lock is not None:
            with self.lock:
                self.frame = frame
        else:
            self.frame = frame

    def start(self):
        try:
            import threading
            self._th = threading.Thread(target=self._loop, name="marker", daemon=True)
            self._th.start()
            print("[ui] 标记检测线程已启动（每 %.1fs 一次；预览不受阻塞）" % self.interval, flush=True)
        except Exception as e:                                       
            print("[ui][warn] 线程启动失败，退回主循环检测: %s" % e, flush=True)

    def stop(self):
        self._stop = True

    def _loop(self):
        import time as _t
        while not self._stop:
            _t.sleep(self.interval)
            if self.lock is not None:
                with self.lock:
                    f = None if self.frame is None else self.frame.copy()
            else:
                f = self.frame
            if f is None or self.mi is None:
                continue
            h, w = f.shape[:2]
            if self.n % 10 == 0:
                print("[marker] frame=%dx%d preview=%dx%d（检测必须全分辨率；预览可降采样）"
                      % (w, h, int(getattr(self, "prev_w", 0)), int(getattr(self, "prev_h", 0))),
                      flush=True)
            lo = max(16, int(0.015 * min(h, w)))          
            hi = int(0.98 * min(h, w))                    
            try:
                hit, hits = self.mi.detect(f, min_side_px=lo, max_side_px=hi)

                if hits and len(hits) > 1:
                    hits = sorted(hits, key=lambda z: (-z.side_px, -z.score))
                    print("[marker] 多标记 %d 个：%s → 取 %s（最大/最靠中心）"
                          % (len(hits), ",".join("%s(%.0fpx,%.2f)" % (z.label, z.side_px, z.score)
                                                 for z in hits[:4]), hits[0].label), flush=True)
                    if len(hits) >= 2 and abs(hits[0].side_px - hits[1].side_px) < 0.1 * max(1.0, hits[0].side_px) \
                       and hits[1].score >= 0.8 * hits[0].score:
                        print("[marker][warn] 多个标记尺寸/分数接近 → **请只露一个标记**", flush=True)
                        self.conflict = "请只露一个标记"
                    else:
                        self.conflict = ""
                    hit = hits[0]
                elif hits:
                    self.conflict = ""
                self.hit, self.hits = hit, hits
                try:
                    self.progress = tuple(getattr(self.mi, "progress", (0, 0)) or (0, 0))
                except Exception:                                    
                    self.progress = (0, 0)
                self.n += 1
                if self.verbose and hits:
                    print("[marker] 候选 %d 个：%s（min_side=%d max_side=%d）"
                          % (len(hits), ",".join("%s(%.2f,%.0fpx)" % (z.label, z.score, z.side_px)
                                                 for z in hits[:3]), lo, hi), flush=True)
                if self.verbose and self.n % 20 == 0:
                    print("[ui] marker=每 %.1fs 次（已检 %d 轮）" % (self.interval, self.n), flush=True)
            except Exception as e:                                   
                print("[marker] 线程内异常: %s" % e, flush=True)

class LiveView:
    """OpenCV 取流 + **失败自动重开**；仍失败就明确报"取流失败"（不静默）。"""

    def __init__(self, dev: str, w: int = 1280, h: int = 720, reopen_after: int = 12):
        self.dev, self.w, self.h = dev, w, h
        self.fails = 0
        self.reopen_after = reopen_after
        self.cap = None
        self.last_ok = 0.0
        self.warn = ""
        self._open()

    def _open(self):
        try:
            self.cap = cv2.VideoCapture(self.dev, cv2.CAP_V4L2)
            if self.cap.isOpened():
                try:
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)      
                except Exception:                                        
                    pass
                self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUYV"))
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.w)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.h)
                self.warn = ""
                print("[live] 打开 %s" % self.dev, flush=True)
            else:
                self.cap = None
                self.warn = "取流失败：打不开 %s（被别的服务占用？tools/afh03_video22_lock.sh status）" % self.dev
                print("[live][warn] %s" % self.warn, flush=True)
        except Exception as e:                                         
            self.cap = None
            self.warn = "取流失败：%s" % e
            print("[live][warn] %s" % self.warn, flush=True)

    def read(self):
        if self.cap is None:
            return None
        try:
            ok, f = self.cap.read()
        except Exception:                                              
            ok, f = False, None
        if ok and f is not None:
            self.fails = 0
            self.last_ok = time.time()
            return f
        self.fails += 1
        if self.fails % self.reopen_after == 0:
            print("[live] 连续 %d 次取帧失败，重开设备" % self.fails, flush=True)
            try:
                self.cap.release()
            except Exception:                                          
                pass
            time.sleep(0.5)
            self._open()
            if self.cap is None:
                self.warn = "取流失败：重开设备仍失败（建议先用自 poll 工具验证：python3 tools/v4l2_poll_snap.py -d %s --report）" % self.dev
        if self.fails >= self.reopen_after:
            self.warn = self.warn or "取流失败：%d 次没拿到帧" % self.fails
        return None

    def release(self):
        try:
            if self.cap is not None:
                self.cap.release()
        except Exception:                                              
            pass

def _hit(buttons_rects, click):
    if click is None:
        return None
    x, y = click
    for b, rect in buttons_rects:
        x0, y0, x1, y1 = [int(v) for v in rect]
        if x0 <= x <= x1 and y0 <= y <= y1:
            return b["action"]
    return None

DEBOUNCE_SEC = 0.5
BUSY_TIMEOUT_SEC = 60.0
BUSY_LINGER_SEC = 0.4          

BUSY_LABELS = {
    "capture": "正在拍照并启动后台判定，请稍候…",
    "flow:capture": "正在拍照并启动后台判定，请稍候…",
    "flow:summary": "正在生成本轮总结，请稍候…",
    "summary_all": "正在汇总拍照/波形证据（只按判据库推理）…",
    "summary:again": "正在清空本轮证据…",
    "summary:again_confirm": "正在清空本轮证据…",
    "wave": "正在启动示波器自动测量（约 6 秒）…",
}

def _busy_clear(busy: dict) -> None:
    busy.update(name="", t0=0.0, until=0.0, hard=0.0, state="")

def _busy_begin(busy: dict, name: str, state: str = "") -> None:
    now = time.time()
    busy.update(name=str(name or ""), t0=now, until=0.0,
                hard=now + BUSY_TIMEOUT_SEC, state=str(state or ""))

def _busy_end(busy: dict) -> None:
    """正常结束：进入收尾窗口（只设置一次；重复调用不延长）。"""
    if busy.get("name") and not busy.get("until"):
        busy["until"] = time.time() + BUSY_LINGER_SEC

def _busy_active(busy: dict) -> str:
    """当前是否忙碌；到 60s 硬上限/收尾窗口结束会自动解除（绝不永久锁死）。"""
    name = str((busy or {}).get("name") or "")
    if not name:
        return ""
    now = time.time()
    hard = float((busy or {}).get("hard") or 0.0)
    if hard and now >= hard:
        print("[kiosk] 防重入超时自动解除：%s 已忙碌 %.1fs（上限 %gs；绝不永久锁死）"
              % (name, now - float(busy.get("t0") or now), BUSY_TIMEOUT_SEC), flush=True)
        _busy_clear(busy)
        return ""
    until = float((busy or {}).get("until") or 0.0)
    if until and now >= until:
        _busy_clear(busy)
        return ""
    return name

def _busy_banner(img, layout, action):
    """在画面上盖「处理中…」横幅（重操作执行期间显示；返回同一张图）。"""
    try:
        C = layout["colors"]
        W, H = layout["canvas"]["w"], layout["canvas"]["h"]
        shade = img.copy()
        cv2.rectangle(shade, (0, 0), (W, H), (8, 6, 4), -1)
        cv2.addWeighted(shade, 0.55, img, 0.45, 0, img)
        _rrect_panel(img, (252, 220, 772, 388), C["card"],
                     C.get("accent", C["dim"]), 16)
        _center_text(img, "处理中…", W // 2, 282, 1.08, C["accent"], th=2)
        msg = BUSY_LABELS.get(str(action or ""), "正在执行重操作，请稍候…")
        _center_text(img, _fit_text(msg, 480, 0.44), W // 2, 330, 0.44,
                     C["text"], th=1)
        _center_text(img, "重操作期间其它点击一律忽略 · 最长 %g 秒自动解除" % BUSY_TIMEOUT_SEC,
                     W // 2, 366, 0.36, C["dim"], th=1)
    except Exception as e:                                             
        print("[kiosk][warn] 处理中横幅绘制失败: %s" % e, flush=True)
    return img

def _confirm_overlay(img, layout):
    """【再拍一轮】二次确认条：返回 (img, btns)，按钮命中与绘制同一份 rect。"""
    C = layout["colors"]
    W, H = layout["canvas"]["w"], layout["canvas"]["h"]
    shade = img.copy()
    cv2.rectangle(shade, (0, 470), (W, H), (8, 6, 4), -1)
    cv2.addWeighted(shade, 0.45, img, 0.55, 0, img)
    _rrect_panel(img, (8, 486, 1016, 596), C["card"], C.get("accent", C["dim"]), 14)
    draw_text(img, "确定清空本轮？", (32, 524), scale=0.52, color=C["unk"], th=2)
    draw_text(img, _fit_text("清空后本轮拍照/问答证据不可恢复（旧一轮已先落盘）",
                             520, 0.36), (300, 524), scale=0.36,
              color=C["text"], th=1)
    btns = []
    _flow_button(img, C, btns, "again_confirm", [160, 532, 504, 588],
                 "确定清空", "summary:again_confirm", primary=True, scale=0.68)
    _flow_button(img, C, btns, "again_cancel", [520, 532, 864, 588],
                 "取消", "summary:again_cancel", scale=0.68)
    return img, btns

def main(argv=None) -> int:
    ap = _ui_parser()
    ap.add_argument("--layout", default=LAYOUT_DEFAULT, help="版式配置（config/ui_layout.json）")
    ap.add_argument("--fps", type=float, default=8.0,
                    help="预览刷新上限（waitKey 阻塞；实测 12fps 会把 CPU 拉到 ~106%%，8fps 更平衡）")
    ap.add_argument("--max-side-frac", type=float, default=0.50,
                    help="★ 标记总边长上限 = 该比例 × 画面短边（0.50：50cm 手持 25mm 标记实测 372~667px 才不会被拒）")
    ap.add_argument("--marker-interval", type=float, default=0.8,
                    help="标记检测间隔秒数（独立线程；低频即可）")
    ap.add_argument("--half-canvas", type=int, default=0,
                    help="★ 默认 0=按 1024x600 原尺寸 1:1 直接 imshow（文字锐利）。"
                         "设 1 会把画布降到 512x300 再让 X 放大回 1024x600（双线性插值 → 中文小字发虚），"
                         "仅应急省 CPU 时用")
    ap.add_argument("--cap-w", type=int, default=1920,
                    help="★ 采集宽（**必须全分辨率**：标记检测依赖黑框/暗带/熵，降采样会把标记像素砍半 → 回归）")
    ap.add_argument("--cap-h", type=int, default=1080, help="采集高（同上）")
    ap.add_argument("--render", choices=["page1", "page2", "wave", "flow", "result", "resultqa",
                                         "summary", "summary_all"],
                    default="",
                    help="离屏渲染某一页到 --out（不需要相机）；resultqa=结果页+自动问答倒计时示例；"
                         "summary=流程检测总结页；summary_all=拍照+波形总结页（证据用 --summary-evidence）")
    ap.add_argument("--summary-evidence", default="",
                    help="--render summary 用的证据 JSON（裸数组或 evidence/v1 包装；空=空态页）")
    ap.add_argument("--steps", default="", help="★ 流程页数据 steps.json（默认自动找 engine/ 或 qa/ 下）")
    ap.add_argument("--flow-step", type=int, default=1, help="--render flow 时渲染第几步（1 起）")
    ap.add_argument("--scope-result", default=SCOPE_RESULT_DEFAULT,
                    help="波形页只读的结果 JSON（默认 /userdata/scope_result.json；页面只显示 "
                         "source=lan/usbtmc 且 ts 在 10 分钟内的真实结果；"
                         "AFH03_SCOPE_FRESH_MIN 可改阈值分钟数）")
    ap.add_argument("--frame", default="", help="--render 用的画面照片（page1 的'实时画面'就用它）")
    ap.add_argument("--selftest-capture", default="",
                    help="用这张照片把 capture 全链跑一遍（判定->标注->存盘），验证不抛错")
    a, _unknown = ap.parse_known_args(argv)

    
    _args = list(argv) if argv is not None else list(sys.argv[1:])
    _explicit_part = any(x == "--part" or str(x).startswith("--part=") for x in _args)
    layout = load_layout(a.layout)
    install_cv2_puttext_patch()
    book = RuleBook.load(a.rules or None)
    from soc_vision.led_panel import Calib, PanelDetector
    calib = Calib.load(a.calib) if a.calib and os.path.isfile(a.calib) else None
    det = PanelDetector(calib)
    part = a.part or ""    

    

    
    try:
        _coverage_report()
    except Exception as _e:                                                
        print("[ui_kiosk][warn] 规则覆盖自检异常（按降级处理，不 FATAL）: %s" % _e, flush=True)

    

    

    _short = min(int(getattr(a, "cap_w", 1920)), int(getattr(a, "cap_h", 1080)))
    if _short < 1080 and os.environ.get("AFH03_I_KNOW_DETECT_LOWRES") != "1":
        print("[ui_kiosk][FATAL] 检测帧短边=%d < 1080：标记检测会失效（黑框/熵/对比度均不达标）。"
              "只允许降**预览**，绝不能降**检测帧**。"
              "如确要实验：AFH03_I_KNOW_DETECT_LOWRES=1" % _short, flush=True)
        return 2
    print("[ui_kiosk] 检测帧约束通过：采集=%dx%d（预览可独立降采样）"
          % (int(getattr(a, "cap_w", 1920)), int(getattr(a, "cap_h", 1080))), flush=True)
    print("[ui_kiosk] 启动: 版式=%s 部件=%s 标定=%s 中文=%s 自动=%s"
          % (os.path.basename(a.layout), part or "<未指定>",
             a.calib if calib else "<无>", cjk_backend(), bool(a.auto)), flush=True)

    if a.selftest_capture:
        frame = cv2.imread(a.selftest_capture, cv2.IMREAD_COLOR)
        if frame is None:
            print("读不到 %s" % a.selftest_capture)
            return 1

        allow0, part0, why0 = bool(a.auto), part, ""
        _mi = None
        if a.part:
            print("[marker] 显式指定 --part=%s → **不以标记改判**（标记仅作参考）" % a.part, flush=True)
            _mi = None if True else None
        if MarkerId is not None and not a.part:
            try:
                _mi = MarkerId(os.path.join(HERE, "markers_modules.json"), confirm_n=1, verbose=False)
            except Exception as _e:                                      
                print("[marker] 离屏 MarkerId 初始化失败: %s" % _e, flush=True)
        if _mi is not None:
            try:
                h0, _hs = _mi.detect(frame)
                if h0 is not None:
                    part0, why0, _cf = _mi.resolve_part(h0, list((calib.parts if calib else {}).keys()))
                    allow0 = True
                    print("[marker] 离屏识别到 %s（%s）边长 %.0fpx → 模块=%s"
                          % (h0.label, (h0.module or {}).get("name", ""), h0.side_px, part0), flush=True)
                else:
                    print("[marker] 离屏未检出标记（候选 %d）" % len(_hs), flush=True)
            except Exception as e:                                       
                print("[marker] 离屏检测异常: %s" % e, flush=True)
        frame_j = frame
        try:
            _h = None
            if _mi is not None:
                _h, _ = _mi.detect(frame)
            if _h is not None:
                frame_j = frame.copy()
                _cx, _cy = int(_h.cx), int(_h.cy)
                _hh, _ww = frame_j.shape[:2]
                _sp = float(getattr(_h, "side_px", 0) or 0)
                _rr = max(int(max(0.08 * min(_hh, _ww), _sp * 4)), 24)
                frame_j[max(0, _cy - _rr):_cy + _rr, max(0, _cx - _rr):_cx + _rr] = 0
                print("[marker] 判灯前涂黑 中心=(%d,%d) 半径=%dpx（side_px=%.0f）" % (_cx, _cy, _rr, _sp),
                      flush=True)
                try:
                    _raw = getattr(_mi, "_raw_hit", None)
                    print("[marker][diag] hit dict=%s" % (_h.to_dict(),), flush=True)
                except Exception:                                        
                    pass
        except Exception as _e:                                          
            print("[marker] 自检涂黑失败: %s" % _e, flush=True)
        res = run_capture(frame_j, part0, book, calib, det, allow0, a.shots_dir, {"verdict": "ERROR"})
        if res.get("ok") and not calib and not a.auto:
            tag = "（自动判定·未标定）"
            v0 = dict(res["vobj"] or {})
            v0["reason"] = "%s%s" % (v0.get("reason", ""), tag)
            res["vobj"] = v0
            res["reason"] = "%s%s" % (res.get("reason", ""), tag)
        print("自检结果: ok=%s verdict=%s reason=%s shot_dir=%s error=%s"
              % (res["ok"], res["verdict"], res["reason"], res["shot_dir"], res["error"]))
        if res["ok"]:
            v = res["vobj"]
            annot = annotate_frame(frame, res["rows"], v)
            cv2.imwrite(a.out, annot)
            print("标注图 -> %s" % a.out)
        return 0 if res["ok"] else 3

    if a.render:
        frame = cv2.imread(a.frame, cv2.IMREAD_COLOR) if a.frame else None
        if a.render == "page1":

            img = draw_page1(layout, frame, toast="", warn="",
                             dbg={"taps": 3, "xy": (300, 545), "hit": "capture",
                                  "dev": "goodix-ts (示例)"})
        elif a.render == "wave":

            img = draw_wave(layout, load_scope_result(getattr(a, "scope_result", "") or ""))
        elif a.render == "result":

            if frame is None:
                print("渲染结果页需要 --frame <真图>")
                return 1
            if BI is None:
                print("board_infer 不可用（结果页无法渲染）")
                return 1
            _r = BI.infer(frame, part_hint=(part or ""))
            _r = _degrade_result(_r, "")
            _r = _apply_route(_r, {})        
            img, _btns = draw_result(layout, _r,
                                     elapsed=(_r.get("elapsed_ms") or 0) / 1000.0,
                                     has_qa=False)
            print("  部位=%s 置信=%.2f 逐条=%d 结论=%s"
                  % ((_r.get("part") or {}).get("part") or "-",
                     float((_r.get("part") or {}).get("confidence") or 0.0),
                     len(_r.get("rows") or []),
                     (_r.get("conclusion") or {}).get("text")))
        elif a.render == "resultqa":

            _r = {
                "part": {"part": (part or "z15"), "display": "Z15 显示电路",
                         "confidence": 0.92, "decision": "标记 + 模板 NCC",
                         "part_source": "标记 Z15", "need_confirm": False,
                         "candidates": [], "reasons": ["标记命中", "灯序标定"]},
                "rows": [
                    {"kind": "led", "pos": "第 1/2 位", "name": "3.15A 保险丝",
                     "state": "off", "state_text": "灭", "expect_text": "应灭", "match": True},
                    {"kind": "led", "pos": "第 1/4 位", "name": "同步",
                     "state": "on", "state_text": "亮", "expect_text": "任亮灭", "match": True},
                    {"kind": "led", "pos": "第 2/4 位", "name": "复位",
                     "state": "off", "state_text": "灭", "expect_text": "任亮灭", "match": True},
                ],
                "conclusion": {"state": "ok", "text": "正常",
                               "why": "保险丝灯灭；同步/复位灯状态已记录（不判）"},
                "candidates": ["保险丝坏（仅当灯亮）"],
                "undetermined": {"n": 0, "reasons": []},
                "evidence_items": [{}, {}, {}], "elapsed_ms": 1200,
                "rule_note": "",
            }
            img, _btns = draw_result(layout, _r, elapsed=1.2, has_qa=True,
                                     qa_left=2, countdown=3)
            print("  渲染 resultqa：has_qa=1 qa_left=2 countdown=3（应显示 3 秒 + 高亮按钮）")
        elif a.render == "summary":

            _ev = []
            _sp = getattr(a, "summary_evidence", "") or ""
            if _sp:
                with open(_sp, encoding="utf-8") as _sf:
                    _ev = json.load(_sf)
                if isinstance(_ev, dict):
                    _ev = _ev.get("evidence") or []
            if SS is None:
                img, _btns = draw_summary(layout, _summary_error(SUMMARY_MODULE_ERR,
                                                                 "SS is None"))
                print("  总结模块不可用 → 降级页")
            else:
                _sess = {"id": "S" + time.strftime("%Y%m%d_%H%M%S"),
                         "started_at": _flow_iso(), "session_dir": SESSION_DIR}
                _sres = SS.summarize(_ev, session=_sess)
                try:
                    _sres["model_locate"] = _model_judge_locate(_ev)
                except Exception:                             
                    pass
                img, _btns = draw_summary(layout, _sres)
                print("  总结：verdict=%s evidence=%d 候选=%d 未解释=%d"
                      % (_sres.get("verdict"),
                         (_sres.get("session") or {}).get("evidence_total", 0),
                         len(_sres.get("top_faults") or []),
                         len(_sres.get("unexplained") or [])))
        elif a.render == "summary_all":

            _sev = None
            _sp = getattr(a, "summary_evidence", "") or ""
            if _sp:
                with open(_sp, encoding="utf-8") as _sf:
                    _sev = json.load(_sf)
                if isinstance(_sev, dict):
                    _sev = _sev.get("evidence") or []
            _sa = _sa_build(evidences=(_sev if _sp else None), persist=False)
            img, _btns = draw_summary_all(layout, _sa)
            print("  汇总：empty=%s verdict=%s 问题=%d 范围=%d 未解释=%d"
                  % (_sa.get("empty"), (_sa.get("summary") or {}).get("verdict"),
                     len(_sa.get("problems") or []), len(_sa.get("ranges") or []),
                     len(_sa.get("unexplained") or [])))
        elif a.render == "flow":

            _doc, _p = load_flow_steps(getattr(a, "steps", "") or "")
            fl = _new_flow(_doc, _p)
            fl["idx"] = max(0, min(int(getattr(a, "flow_step", 1)) - 1, len(fl["steps"]) - 1))
            img, _btns = draw_flow(layout, fl, frame)
            _fit(img, frame, FLOW_PREVIEW, bg=layout["colors"].get("preview_bg"))
            _st = _flow_step(fl)
            print("  步骤=%s 部位=%s 路别=%s 类型=%s 问题=%d"
                  % (_st["step_id"], _st.get("part") or "-", _st.get("route") or "-",
                     _st.get("method_text"), len(_st.get("qa_items") or [])))
        else:
            v, info = judge(frame, part, book, calib, det, allow_auto=a.auto) if frame is not None \
                else ({"verdict": VERDICT_UNK, "reason": "没有照片"}, {"rows": []})
            img = draw_page2(layout, frame, v)
            print("  结论=%s 依据=%s" % (v.get("verdict"), v.get("reason")))
        cv2.imwrite(a.out, img)
        print("已写出 %s" % a.out)
        return 0

    live = None if a.no_camera else LiveView(a.device, w=int(getattr(a, "cap_w", 1920)),
                                              h=int(getattr(a, "cap_h", 1080)))
    touch = None
    if not a.no_touch:
        try:
            t = TouchScreen(a.touch, a.win_w, a.win_h, verbose=True)
            touch = t if t.fd >= 0 else None
        except Exception as e:                                          
            print("[touch] 初始化失败: %s" % e, flush=True)
            touch = None
    if touch is None and not a.no_touch:
        print("[touch][warn] 触摸不可用 -> 键盘兜底：空格/c=拍照  w=波形  b=返回  q/Esc=退出", flush=True)
    win = a.window + "-kiosk"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    
    try:
        cv2.resizeWindow(win, a.win_w, a.win_h)
        cv2.waitKey(1)                     
    except Exception:                                                  
        pass

    try:
        cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        print("[ui_kiosk] 已请求全屏显示（resize 之后）", flush=True)
    except Exception as _e:  
        print("[ui_kiosk][warn] 全屏设置失败：%r" % (_e,), flush=True)

    

    _half = int(getattr(a, "half_canvas", 0))
    print("[ui_kiosk] 显示路径：%s（canvas=%dx%d → imshow %s）"
          % ("★原尺寸 1:1（不缩放）" if not _half else "★1/2 降采样后由 X 放大（会糊，仅应急）",
             int(a.win_w), int(a.win_h),
             "%dx%d" % (int(a.win_w), int(a.win_h)) if not _half
             else "%dx%d" % (max(1, int(a.win_w) // 2), max(1, int(a.win_h) // 2))),
          flush=True)

    mi = None
    if MarkerId is not None:
        try:
            mi = MarkerId(os.path.join(HERE, "markers_modules.json"), confirm_n=3,
                          max_side_frac=float(getattr(a, "max_side_frac", 0.50)), verbose=True)
            print("[marker] 生效参数: max_side_frac=%.2f min_side=24 confirm_n=%d min_score=%.2f"
                  % (float(getattr(mi, "max_side_frac", -1)), int(getattr(mi, "confirm_n", -1)),
                     float(getattr(mi, "min_score", -1))), flush=True)
        except Exception as e:                                          
            print("[marker] 初始化失败: %s" % e, flush=True)
    marker_hit, marker_txt = None, ""
    last_marker_t = 0.0
    mworker = None
    if mi is not None:
        mworker = MarkerWorker(mi, interval=float(getattr(a, "marker_interval", 0.8)), verbose=True)
        mworker.prev_w = int(a.win_w // 2) if int(getattr(a, "half_canvas", 1)) else int(a.win_w)
        mworker.prev_h = int(a.win_h // 2) if int(getattr(a, "half_canvas", 1)) else int(a.win_h)
        mworker.start()
    state, still, vobj = "page1", None, None
    qa, qa_cache = None, {}      
    flow, flow_cache = None, {}  
    summary, summary_cache = None, {}  
    sa, sa_cache = None, {}            
    resv, res_job, res_meta = None, None, {}  
    res_cache = {}                            
    qa_view = None                            
    info = {"rows": []}          
    toast, toast_until, err = "", 0.0, ""
    scope, last_scope = {"verdict": "ERROR", "message": "未查询"}, 0.0
    wave_res = None              
    wave_at = 0.0                
    MEAS = ScopeMeasurer(getattr(a, "scope_result", "") or SCOPE_RESULT_DEFAULT)
    meas_seen = 0                

    busy = {"name": "", "t0": 0.0, "until": 0.0, "hard": 0.0, "state": ""}
    last_click_t = 0.0           
    _taps_seen = 0               
    confirm_again_until = 0.0    
    n = 0
    t0 = time.time()
    last_judge = 0.0
    fps = max(1.0, float(a.fps))
    period = 1.0 / fps
    _n_iter = 0
    _t_mark = time.time()

    def _show_busy_now(cv):
        """同步重操作开始前立即把「处理中…」推到屏幕（之后主线程会被阻塞）。"""
        _name = _busy_active(busy)
        if not _name:
            return
        _b = _busy_banner(cv.copy(), layout, _name)
        if int(getattr(a, "half_canvas", 0)):
            _b = cv2.resize(_b, (max(1, int(a.win_w) // 2),
                                 max(1, int(a.win_h) // 2)),
                            interpolation=cv2.INTER_AREA)
        try:
            cv2.imshow(win, _b)
            cv2.waitKey(1)
        except Exception as _e:                                        
            print("[kiosk][warn] 处理中横幅显示失败: %s" % _e, flush=True)

    while True:
        _loop_t0 = time.time()
        _auto_due = False            
        dbg = {"taps": getattr(touch, "taps", 0), "xy": getattr(touch, "last_tap_xy", None),
               "hit": getattr(touch, "last_hit", ""), "dev": (touch.name if touch else "触摸不可用")}
        frame = live.read() if (live and state not in ("qa", "summary", "summary_all", "partqa")) else None   
        if frame is None and still is not None and state == "page2":
            frame = still
        n += 1
        now = time.time()

        if busy.get("name") == "wave" and not MEAS.running():
            _busy_end(busy)
        if mworker is not None:
            mworker.set_frame(frame)                     
            if mworker.hit is not None:
                h2 = mworker.hit
                marker_hit = h2
                _rs = _rule_state_for_label(h2.label)
                _nm = (h2.module or {}).get("name", "")
                if _rs == "ready":
                    marker_txt = "模块=%s %s（标记 %.2f, 边长 %.0fpx）" % (
                        h2.label, _nm, h2.score, h2.side_px)
                else:

                    marker_txt = "模块=%s %s（规则待标定）" % (h2.label, _nm)
                    if h2.label not in _RULE_WARNED:
                        _RULE_WARNED.add(h2.label)
                        print("[ui_kiosk][WARN] 标记 %s（%s）已识别，但%s → 结论=未判定"
                              "（判定规则待标定）"
                              % (h2.label, _nm,
                                 "规则表无此部位" if _rs == "missing" else "规则待标定"),
                              flush=True)
            else:

                

                
                marker_hit = None
                _pr = tuple(getattr(mworker, "progress", (0, 0)) or (0, 0))
                _cand = list(getattr(mworker, "hits", None) or [])
                if _cand:
                    marker_txt = "识别中：%s（%d/%d，对准后约 1 秒确认）" % (
                        getattr(_cand[0], "label", "?"), int(_pr[0]), max(1, int(_pr[1]) or 3))
                else:
                    marker_txt = "未识别（请把 v2 标记对准镜头中心）"

        if state not in ("wave", "qa") and now - last_scope > 5:
            scope = scpi_verdict(a)
            last_scope = now
        _toast_now = toast if now < toast_until else ""

        
        if res_job is not None and res_job.done and not res_meta.get("merged"):
            resv = _result_ready(res_job, res_meta, flow)

            
            _c = (resv.get("conclusion") or {}).get("text") or "未判定"
            toast, toast_until = ("判定完成：%s" % _c)[:56], now + 4.0
            _toast_now = toast
            print("[result] 判定完成 %s｜%s（%.1fs）"
                  % (_c, (resv.get("conclusion") or {}).get("why", "")[:60],
                     res_job.elapsed()), flush=True)
        if state == "wave":

            _ms = MEAS.snapshot()
            if _ms["seq"] != meas_seen:
                meas_seen = _ms["seq"]
                if _ms["status"] in ("done", "error"):
                    _old = wave_res
                    if _ms["status"] == "error":

                        wave_res = {"valid": False, "ok": False,
                                    "invalid_reason": (_ms.get("error") or "测量失败（无有效读数）"),
                                    "reason": (_ms.get("error") or "测量失败（无有效读数）"),
                                    "items": [], "stamp": "meas_error_%s" % _ms.get("seq")}
                    else:
                        wave_res = load_scope_result(getattr(a, "scope_result", "") or "")

                    
                    if _ms.get("local_only"):
                        _u = load_local_measure_result(SCOPE_TEMP_RESULT)
                        if _u:
                            wave_res = _u
                            print("[wave] 本次测量签名失败 → 显示「未签名(仅本地测量)」的**本次读数**"
                                  "（不拿旧签名结果顶替，也不冒充签名）", flush=True)
                    wave_at = now
                    print("[wave] 测量完成：valid=%s signed=%s status=%s 用时=%s 实测=%s Hz Vpp=%s V 原因=%s"
                          % (wave_res.get("valid"), wave_res.get("signed"), _ms["status"],
                             _ms.get("elapsed_s"), (wave_res.get("items") or [{}])[0].get("measured_hz")
                             if wave_res.get("items") else None,
                             (wave_res.get("items") or [{}])[0].get("vpp_v")
                             if wave_res.get("items") else None,
                             wave_res.get("invalid_reason") or _ms.get("error") or "-"),
                          flush=True)
                    if (_old is None or _old.get("stamp") != wave_res.get("stamp")):
                        print("[wave] 页面数据已更新 stamp=%s" % wave_res.get("stamp"), flush=True)

            if (not _ms["running"]) and (wave_res is None or (now - wave_at) >= SCOPE_RELOAD_SEC):
                _old = wave_res
                wave_res = load_scope_result(getattr(a, "scope_result", "") or "")
                wave_at = now
                if (_old is None or _old.get("valid") != wave_res.get("valid")
                        or _old.get("invalid_reason") != wave_res.get("invalid_reason")
                        or _old.get("verdict") != wave_res.get("verdict")):
                    print("[wave] 校验：valid=%s verdict=%s 测量时间=%s 原因=%s"
                          % (wave_res.get("valid"), wave_res.get("verdict"),
                             wave_res.get("measured_at") or "-",
                             wave_res.get("invalid_reason") or "-"), flush=True)
            _view = dict(wave_res or {})
            _view["_meas"] = _ms
            canvas = render_cached(layout, "wave", frame, vobj, info, _view, dbg, err, "",
                                   marker_txt)
            btns = _buttons(canvas, layout, _wave_page(layout, measuring=_ms["running"]))
        elif state == "qa":
            _cur = qa.current() if qa else None
            if _cur is None:
                state = "page1"
                canvas = render_cached(layout, "page1", frame, vobj, info, scope,
                                       dbg, err, _toast_now, marker_txt)
                btns = _buttons(canvas, layout, page(layout, "page1"))
            else:
                _key = (_cur["qa_id"], _cur["answered"], _toast_now)
                if qa_cache.get("key") != _key:      
                    _img, _btns = draw_qa(layout, _cur, _toast_now)
                    qa_cache.clear()
                    qa_cache.update(key=_key, img=_img, btns=_btns)
                canvas, btns = qa_cache["img"].copy(), qa_cache["btns"]
        elif state == "partqa":

            _pq = res_meta.get("part_qa")
            if not _pq:
                state = "page1"
                canvas = render_cached(layout, "page1", frame, vobj, info, scope,
                                       dbg, err, _toast_now, marker_txt)
                btns = _buttons(canvas, layout, page(layout, "page1"))
            else:
                _pqv = _part_qa_view(_pq)
                _pkey = (_pqv["qa_id"], len(_pq.get("answers") or {}), _toast_now)
                if qa_cache.get("key") != _pkey:
                    _img, _btns = draw_qa(layout, _pqv, _toast_now)
                    qa_cache.clear()
                    qa_cache.update(key=_pkey, img=_img, btns=_btns)
                canvas, btns = qa_cache["img"].copy(), qa_cache["btns"]
        elif state == "result":

            _pend = not (res_job is not None and res_job.done)
            _el = res_job.elapsed() if res_job is not None else 0.0
            _stq = _flow_step(flow) if (flow is not None and res_meta.get("mode") == "flow") else None
            _hasqa = bool(_stq and _stq.get("qa_items"))
            _qleft = len(_stq["qa_items"]) - len(_flow_answers(flow, _stq)) if _hasqa else 0
            _qdone = 0

            
            if not _hasqa and not _pend:
                _pqa = res_meta.get("part_qa")
                if _pqa is None:
                    _ppart, _pitems = _part_qa_pick(resv)
                    _pqa = {"part": _ppart, "route": _result_route(resv),
                            "items": _pitems, "idx": 0,
                            "answers": {}, "why": ""} if _pitems else {}
                    res_meta["part_qa"] = _pqa
                    if _pitems:
                        print("[partqa] 主页拍照 → 按部位找到 %d 题：part=%s 路别=%s 首题=%s「%s」"
                              % (len(_pitems), _ppart, _pqa.get("route") or "-",
                                 _pitems[0].get("qa_id"),
                                 _flow_clean(_pitems[0].get("question"))), flush=True)
                    else:
                        _pv = str(((resv or {}).get("part") or {}).get("part") or "-")
                        print("[partqa] 部位 %s 在题库里没有 QA（qa_items_screen + steps.json）"
                              "⇒ 本页保持「本步无问答项」" % _pv, flush=True)

                
                if _pqa:
                    _n_item = len(_pqa.get("items") or [])
                    _n_ans = len(_pqa.get("answers") or {})
                    if resv is not None and _n_ans and \
                            int((((resv or {}).get("partqa") or {}).get("answered") or 0)) != _n_ans:
                        resv = _apply_partqa(resv, _pqa)
                        res_cache.clear()
                    if _n_item and _n_ans >= _n_item:
                        _qdone = _n_item
                if _pqa and (len(_pqa.get("items") or [])
                             > len(_pqa.get("answers") or {})):
                    _hasqa = True
                    _qleft = max(0, len(_pqa["items"]) - len(_pqa["answers"]))
                elif _pqa:

                    _hasqa = False
                    _qleft = 0

            _auto_ok = bool(_hasqa and max(0, _qleft) > 0 and not _pend
                            and not res_meta.get("auto_qa_off"))
            _cnt = None
            if _auto_ok:
                _due = res_meta.get("auto_qa_at")
                if _due is None:
                    _due = now + RESULT_AUTO_QA_SEC
                    res_meta["auto_qa_at"] = _due
                    print("[result] 自动问答倒计时 %.1fs step=%s part=%s（剩 %d 题）"
                          % (RESULT_AUTO_QA_SEC,
                             (_stq or {}).get("step_id") or "-",
                             ((resv or {}).get("part") or {}).get("part") or "-", _qleft),
                          flush=True)
                _cnt = max(0, int(math.ceil(_due - now)))
                if _due - now <= 0:
                    _auto_due = True
                    _cnt = 1          
                else:
                    _cnt = min(3, max(1, _cnt))
            else:
                res_meta.pop("auto_qa_at", None)
            _rkey = (id(resv), _pend, int(_el * 2) if _pend else -1, _toast_now, err,
                     _hasqa, _qleft, _cnt, _qdone)
            if res_cache.get("key") != _rkey:      
                _img, _btns = draw_result(layout, resv, elapsed=_el, pending=_pend,
                                          toast=_toast_now, err=err,
                                          has_qa=_hasqa, qa_left=max(0, _qleft),
                                          countdown=_cnt, qa_done=_qdone)
                res_cache.clear()
                res_cache.update(key=_rkey, img=_img, btns=_btns)
            canvas, btns = res_cache["img"].copy(), res_cache["btns"]
        elif state == "summary":

            _skey = (((summary or {}).get("session") or {}).get("id") or "",
                     ((summary or {}).get("session") or {}).get("evidence_total"),
                     (summary or {}).get("verdict"), _toast_now, err,
                     (summary or {}).get("_ui_error"))
            if summary_cache.get("key") != _skey:
                _img, _btns = draw_summary(layout, summary, _toast_now, err)
                summary_cache.clear()
                summary_cache.update(key=_skey, img=_img, btns=_btns)
            canvas, btns = summary_cache["img"].copy(), summary_cache["btns"]

            if now < confirm_again_until:
                canvas, btns = _confirm_overlay(canvas, layout)
            elif confirm_again_until:
                confirm_again_until = 0.0
        elif state == "summary_all":

            _sakey = (id(sa), _toast_now, err)
            if sa_cache.get("key") != _sakey:
                _img, _btns = draw_summary_all(layout, sa, _toast_now, err)
                sa_cache.clear()
                sa_cache.update(key=_sakey, img=_img, btns=_btns)
            canvas, btns = sa_cache["img"].copy(), sa_cache["btns"]
        elif state in ("flow", "flowqa"):
            _st = _flow_step(flow)
            _qview = None
            if state == "flowqa":
                _qq = _flow_cur_qa(flow, _st)
                if _qq is not None:
                    _qview = _flow_qa_view(flow, _st, _qq)

                    try:
                        _z18_attach_vision(flow, _st, _qq, frame, _qview)
                    except Exception as _z18e:                    
                        print("[z18] attach 失败: %s" % _z18e, flush=True)
            if _qview is not None:

                _qkey = (_qview["qa_id"], len(_flow_answers(flow, _st)), _toast_now)
                if qa_cache.get("key") != _qkey:
                    _img, _btns = draw_qa(layout, _qview, _toast_now)
                    qa_cache.clear()
                    qa_cache.update(key=_qkey, img=_img, btns=_btns)
                canvas, btns = qa_cache["img"].copy(), qa_cache["btns"]
            else:

                state = "flow"

                _freeze = flow.get("still") is not None and now < flow.get("freeze_until", 0.0)
                _fkey = (flow["idx"], len(_flow_answers(flow, _st)),
                         len(flow["shots"].get(_st["step_id"]) or []), _toast_now,
                         _freeze, flow.get("saved"))
                if flow_cache.get("key") != _fkey:
                    _img, _btns = draw_flow(layout, flow, None, _toast_now, err)
                    flow_cache.clear()
                    flow_cache.update(key=_fkey, img=_img, btns=_btns)
                canvas, btns = flow_cache["img"].copy(), flow_cache["btns"]
                _pimg = flow["still"] if _freeze else frame
                _fit(canvas, _pimg, FLOW_PREVIEW, label="正在取流…",
                     bg=layout["colors"].get("preview_bg"))
                cv2.rectangle(canvas, (FLOW_PREVIEW[0], FLOW_PREVIEW[1]),
                              (FLOW_PREVIEW[2], FLOW_PREVIEW[3]),
                              layout["colors"].get("preview_frame", layout["colors"]["dim"]), 1)
        elif state == "page1":
            canvas = render_cached(layout, "page1", frame, vobj, info, scope, dbg, err,
                                   _toast_now, marker_txt)
            btns = _buttons(canvas, layout, page(layout, "page1"))
        else:
            canvas = render_cached(layout, "page2", still, vobj, info, scope, dbg, err,
                                   _toast_now, marker_txt)
            btns = _buttons(canvas, layout, page(layout, "page2"))
        _busy_name = _busy_active(busy)
        if _busy_name:
            canvas = _busy_banner(canvas, layout, _busy_name)
        if int(getattr(a, "half_canvas", 0)):

            

            _h2 = cv2.resize(canvas, (max(1, a.win_w // 2), max(1, a.win_h // 2)),
                             interpolation=cv2.INTER_AREA)
            cv2.imshow(win, _h2)
        else:

            
            try:
                cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
            except Exception:  
                pass
            cv2.imshow(win, canvas)
        key = cv2.waitKey(max(1, int(1000.0 / fps))) & 0xFF
        click = touch.poll() if touch else None
        _taps_now = int(getattr(touch, "taps", 0)) if touch is not None else 0
        _new_taps = max(0, _taps_now - _taps_seen)
        if touch is not None:
            _taps_seen = _taps_now
        act = _hit(btns, click)
        if click is not None:
            print("[kiosk] click 屏幕=(%d,%d) 命中=%s taps=%d 原始=(%s,%s)"
                  % (click[0], click[1], act or "无", getattr(touch, "taps", 0),
                     getattr(touch, "raw_x", -1), getattr(touch, "raw_y", -1)), flush=True)

            _block = ""
            _bn = _busy_active(busy)
            if _bn:
                _block = "忙碌中(%s)" % _bn
                print("[kiosk] 忙碌中忽略 屏幕=(%d,%d) 命中=%s 已忙碌 %.1fs"
                      "（重操作期间其它点击一律忽略）"
                      % (click[0], click[1], act or "无",
                         max(0.0, now - float(busy.get("t0") or now))), flush=True)
            elif last_click_t and (now - last_click_t) < DEBOUNCE_SEC:
                _block = "防连点"
                print("[kiosk] 防连点忽略 屏幕=(%d,%d) 命中=%s 距上次 %.0fms < %.0fms"
                      % (click[0], click[1], act or "无",
                         (now - last_click_t) * 1000.0, DEBOUNCE_SEC * 1000.0),
                      flush=True)
            if _new_taps > 1:
                print("[kiosk] 防连点忽略：同一批 %d 次 tap（只处理 1 次）屏幕=(%d,%d)"
                      % (_new_taps, click[0], click[1]), flush=True)
            if _block:
                act = None
            else:
                last_click_t = now
            if touch is not None:
                touch.last_hit = act or ("被忽略" if _block else "无")
        if key == 27:
            if flow is not None:
                _flow_save(flow)          
            break
        if key in (ord("c"), ord(" ")):
            act = act or "capture"
            print("[kiosk] 键盘触发 capture", flush=True)
        if key == ord("w") and state not in ("flow", "flowqa", "result"):
            act = "wave"

        if key == ord("r") and state == "wave":
            act = "retest"
        if key == ord("b"):
            act = "back"
        if key == ord("q"):
            act = "quit"

        if key == ord("s") and state == "page1":
            act = "summary_all"

        
        if key in (ord("f"), ord("a")) and state not in ("qa", "flow", "flowqa", "result"):
            act = act or "flow"
        if state == "flow":
            if key == ord("c") or key == ord(" "):
                act = "flow:capture"
            elif key == ord("n"):
                act = "flow:next"
            elif key == ord("p"):
                act = "flow:prev"
            elif key == ord("s"):
                act = "flow:skip"
            elif key == ord("b"):
                act = "flow:back"
            elif key in (ord("t"), ord("z")):
                act = "flow:summary"          
            elif key in (ord("1"), ord("2"), ord("3"), ord("4")):
                _q = _flow_cur_qa(flow, _flow_step(flow)) if flow else None
                _i = key - ord("1")
                if _q is not None and _i < len(_q.get("options") or []):
                    act = "flow:answer:%s" % _q["options"][_i].get("value")

        if state == "result":
            if key in (ord("c"), ord(" ")):
                act = "result:retake"
            elif key == ord("v"):
                act = "result:qa"
            elif key == ord("b"):
                act = "result:back"
            elif key in (ord("1"), ord("2"), ord("3"), ord("4")):
                act = "result:pick:%d" % (key - ord("1"))

        elif state == "flowqa":
            if key == ord("b"):
                act = "flowqa:back"
            elif key == ord("s"):
                act = "flow:skip"
            elif key in (ord("1"), ord("2"), ord("3"), ord("4")):
                _q = _flow_cur_qa(flow, _flow_step(flow)) if flow else None
                _i = key - ord("1")
                if _q is not None and _i < len(_q.get("options") or []):
                    act = "flow:answer:%s" % _q["options"][_i].get("value")
                else:
                    act = ""
            elif key in (ord("c"), ord(" "), ord("n"), ord("p")):
                act = ""                     

        if state == "qa" and key == ord("b"):
            act = "qa:back"
        if state == "qa" and key in (ord("1"), ord("2"), ord("3"), ord("4")):
            _cur = qa.current() if qa else None
            _i = key - ord("1")
            if _cur is not None and _i < len(_cur["options"]):
                act = "qa:" + _cur["options"][_i]["value"]

        
        if state == "summary":
            if key == ord("b"):
                act = "summary:back"
            elif key in (ord("n"), ord("t")):

                act = ("summary:again_confirm" if now < confirm_again_until
                       else "summary:again")
            elif key in (ord("y"), 13) and now < confirm_again_until:
                act = "summary:again_confirm"
            elif key != 0xFF and act != "quit":
                act = ""          

        if state == "summary_all":
            if key == ord("b"):
                act = "summary_all:back"
            elif key in (ord("r"), ord("s")):
                act = "summary_all:again"
            elif key != 0xFF and act != "quit":
                act = ""
        if act == "quit":
            if flow is not None:
                _flow_save(flow)
            break

        if act == "flow" and state != "flow":
            try:
                if flow is None:
                    _doc, _p = load_flow_steps(getattr(a, "steps", "") or "")
                    flow = _new_flow(_doc, _p)
                    print("[flow] 载入 %s：%d 步" % (_p, len(flow["steps"])), flush=True)

                flow["idx"] = next((i for i, s in enumerate(flow["steps"])
                                    if not _flow_done(flow, s)), 0)
                flow["still"], flow["freeze_until"] = None, 0.0
                if not os.path.isfile(flow["path"]):
                    _flow_save(flow)          
                state = "flow"
                err = ""
                toast = "流程共 %d 步 → 第 %d 步" % (len(flow["steps"]), flow["idx"] + 1)
                toast_until = now + 3.0
                print("[flow] 进入：%d 步，当前 step=%s 部位=%s"
                      % (len(flow["steps"]), _flow_step(flow)["step_id"],
                         _flow_step(flow).get("part") or "-"), flush=True)
            except Exception as _e:                                        
                toast, toast_until = ("流程数据不可用：%s" % str(_e))[:60], now + 6.0
                print("[flow] 启动失败: %s" % _e, flush=True)
        elif isinstance(act, str) and act.startswith("flow:") and state in ("flow", "flowqa"):
            _cmd = act.split(":", 1)[1]
            _st = _flow_step(flow)
            if _cmd == "summary":

                
                if not SUMMARY_ENABLED:
                    toast, toast_until = "总结功能已关闭（AFH03_SUMMARY=0）", now + 4.0
                elif SS is None:
                    summary = _summary_error(SUMMARY_MODULE_ERR,
                                             "session_summary.py 未部署或导入失败（见启动日志）")
                    summary_cache.clear()
                    state, err = "summary", ""
                    print("[summary] 模块不可用 → 显示降级页（UI 不崩）", flush=True)
                else:

                    _busy_begin(busy, "flow:summary", state)
                    _show_busy_now(canvas)
                    _t_sum = time.time()
                    try:
                        _res = SS.summarize(
                            flow["evidence"],
                            session={"id": flow["session_id"],
                                     "started_at": flow["started_at"],
                                     "session_dir": flow["session_dir"],
                                     "source_file": flow["path"]})
                        try:
                            _res["model_locate"] = _model_judge_locate(flow.get("evidence") or [])
                        except Exception:                     
                            pass
                        _disk_ok = _write_summary_files(flow, _res)
                        summary, err = _res, ""
                        summary_cache.clear()
                        state = "summary"
                        toast, toast_until = "", 0.0
                        print("[summary] 完成：verdict=%s conclusion=%s evidence=%d 用时 %.2fs 落盘=%s"
                              % (_res.get("verdict"), _res.get("conclusion"),
                                 len(flow["evidence"]), time.time() - _t_sum, _disk_ok),
                              flush=True)
                    except Exception as _e:                            
                        summary = _summary_error(SUMMARY_MODULE_ERR,
                                                 "summarize() 抛异常：%s" % _e)
                        summary_cache.clear()
                        state, err = "summary", ""
                        print("[summary] summarize 异常（已降级，进程保留）: %s" % _e, flush=True)
                    _busy_end(busy)
            elif _cmd == "back":
                _ok = _flow_save(flow)
                state = "page1"
                toast = "流程已保存：证据 %d 条%s" % (len(flow["evidence"]),
                                                    "" if _ok else "（落盘失败！）")
                toast_until = now + 5.0
                print("[flow] 返回主页：%s（ok=%s）" % (flow["path"], _ok), flush=True)
            elif _cmd == "next":
                if flow["idx"] < len(flow["steps"]) - 1:
                    flow["idx"] += 1
                    flow["still"], flow["freeze_until"] = None, 0.0
                    toast = "第 %d / %d 步" % (flow["idx"] + 1, len(flow["steps"]))
                    toast_until = now + 2.0
                else:
                    toast, toast_until = "已是最后一步（可【保存】或【返回】）", now + 4.0
            elif _cmd == "prev":
                if flow["idx"] > 0:
                    flow["idx"] -= 1
                    flow["still"], flow["freeze_until"] = None, 0.0
                    toast = "第 %d / %d 步" % (flow["idx"] + 1, len(flow["steps"]))
                    toast_until = now + 2.0
                else:
                    toast, toast_until = "已是第一步", now + 2.0
            elif _cmd == "save":
                _ok = _flow_save(flow)
                toast = "已保存证据 %d 条 → %s" % (len(flow["evidence"]),
                                                  os.path.basename(flow["path"]))
                toast_until = now + 4.0
                print("[flow] 手动保存 ok=%s -> %s" % (_ok, flow["path"]), flush=True)
            elif _cmd == "capture":
                _vi_idx, _vi = _flow_pending_vision(flow, _st)
                if not _st.get("vision_items"):
                    toast, toast_until = "本步无拍照项（问答/波形步）", now + 3.0
                elif frame is None:
                    toast, toast_until = "取流失败，无法拍照", now + 3.0
                else:

                    _busy_begin(busy, "flow:capture", state)
                    _show_busy_now(canvas)
                    if _vi is None:

                        

                        _vi = (_st.get("vision_items") or [{}])[-1]

                    _part_use, _part_why, _part_conf = part, "", 0.0
                    if part:
                        _part_why = "命令行显式 --part=%s" % part
                    elif mi is not None:
                        try:
                            _part_use, _part_why, _part_conf = mi.resolve_part(
                                marker_hit, list((calib.parts if calib else {}).keys()))
                        except Exception as _e:                            
                            print("[flow] resolve 异常: %s" % _e, flush=True)
                    _allow = bool(a.auto) or (marker_hit is not None and bool(_part_use))
                    _frame_j = frame
                    if marker_hit is not None:
                        try:
                            _frame_j = frame.copy()
                            _cx, _cy = int(marker_hit.cx), int(marker_hit.cy)
                            _hh, _ww = _frame_j.shape[:2]
                            _sp = float(getattr(marker_hit, "side_px", 0) or 0)
                            _rr = max(int(max(0.08 * min(_hh, _ww), _sp * 4)), 24)
                            _frame_j[max(0, _cy - _rr):_cy + _rr,
                                     max(0, _cx - _rr):_cx + _rr] = 0
                        except Exception as _e:                            
                            print("[flow] 涂黑标记区失败: %s" % _e, flush=True)
                    _res = run_capture(_frame_j, _part_use, book, calib, det, _allow,
                                       a.shots_dir, scope)
                    if _res.get("ok"):
                        _v = _res.get("vobj") or {}
                        _verdict = _v.get("verdict") or "未判定"
                        _val = ("normal" if _verdict == "正常"
                                else ("abnormal" if "故障" in _verdict else "undetermined"))
                        _conf = (float(_v.get("confidence", 0.9))
                                 if _val != "undetermined" else 0.5)
                        _ev = {
                            "part": _st.get("part") or _part_use,

                            "route": _marker_route(marker_hit) or _step_route(_st),
                            "modality": "vision",
                            "field": (_vi.get("evidence_field")
                                      or ("(vision)_step_%s" % _st["step_id"])),
                            "value": _val,
                            "confidence": round(_conf, 3),
                            "note": "拍照判定（%s）：%s" % (_part_use or "-",
                                                         _v.get("reason") or ""),
                            "evidence": "拍照判定：%s；%s" % (_verdict,
                                                        _v.get("reason") or ""),
                            "ts": _flow_iso(),
                            "source": "ui_kiosk.flow",
                            "item_id": "camera:%s" % _st["step_id"],
                            "flow_no": _st.get("flow_no"),
                            "flow_name": _st.get("flow_name"),
                            "step_id": _st["step_id"],
                            "step_name": _st.get("step_name"),
                            "check_item": _vi.get("check_item"),
                            "part_used": _part_use,
                            "shot_dir": _res.get("shot_dir"),
                        }
                        flow["shots"].setdefault(_st["step_id"], []).append({
                            "item": _vi.get("check_item"), "verdict": _verdict,
                            "reason": _v.get("reason") or "",
                            "shot_dir": _res.get("shot_dir"), "ts": _ev["ts"],
                            "part_used": _part_use})
                        _flow_add_evidence(flow, _ev)
                        try:
                            flow["still"] = cv2.resize(frame, (640, 360))
                        except Exception:                                  
                            flow["still"] = frame
                        flow["freeze_until"] = now + 3.0
                        toast, toast_until = ("已拍照：%s" % _verdict), now + 3.5
                        print("[flow] 拍照 step=%s item=%s -> %s (%s)"
                              % (_st["step_id"], _vi.get("check_item"), _verdict,
                                 _res.get("shot_dir")), flush=True)

                        
                        if BI is None:
                            toast, toast_until = "判定适配层不可用（board_infer.py）", now + 5.0
                        else:
                            resv, res_cache = None, {}
                            res_meta.clear()
                            res_meta.update({
                                "mode": "flow", "merged": False,
                                "step_id": _st["step_id"],
                                "field": (_vi.get("evidence_field")
                                          or ("(vision)_step_%s" % _st["step_id"])),
                                "shot_dir": _res.get("shot_dir"),
                                "part_use": _part_use or "",

                                "route": _step_route(_st),
                                "marker_route": _marker_route(marker_hit),
                                "marker_label": (marker_hit.label
                                                 if marker_hit is not None else "")})
                            try:
                                res_meta["frame"] = frame.copy()   
                            except Exception:                      
                                pass
                            res_job = BI.start_job(
                                frame, part_hint=(_st.get("part") or _part_use),
                                flow_no=_st.get("flow_no"), route=_step_route(_st))
                            state = "result"
                            toast, toast_until = ("判定中…（部位 %s）"
                                                  % (_st.get("part") or "-")), now + 3.0
                            print("[result] 进入结果页：后台判定已启动 step=%s part_hint=%s"
                                  % (_st["step_id"], _st.get("part") or "-"), flush=True)
                    else:
                        toast, toast_until = ("拍照失败：%s"
                                              % (_res.get("error") or "未知"))[:52], now + 6.0
                        print("[flow] 拍照失败: %s" % _res.get("error"), flush=True)
                    _busy_end(busy)
            else:
                _qa = _flow_cur_qa(flow, _st)
                if _qa is None:
                    toast, toast_until = "本步问答已完成", now + 3.0
                else:
                    if _cmd == "skip":
                        _opt = {"value": "skipped", "label": "跳过", "tone": "neutral"}
                    else:
                        _want = _cmd.split("answer:", 1)[1]
                        _opt = next((o for o in _qa.get("options") or []
                                     if str(o.get("value")) == _want), None)
                    if _opt is None:
                        toast, toast_until = ("无效选项：%s" % _cmd)[:48], now + 3.0
                    else:
                        _val = _flow_value(_opt.get("value"))

                        
                        _skipped = (_val in ("skipped", "undetermined"))
                        _subj = _qa.get("subject") or _qa.get("check_item") or ""
                        _label = _opt.get("label_plain") or _opt.get("label") or _opt.get("value")
                        _ev = {
                            "part": _st.get("part") or _qa.get("part"),
                            "route": (_marker_route(marker_hit) or _step_route(_st)
                                      or _qa.get("route") or ""),
                            "modality": "qa",
                            "field": (_qa.get("evidence_field")
                                      or ("(manual_action)_step_%s" % _st["step_id"])),
                            "value": _val,
                            "confidence": ((0.30 if _val == "undetermined" else 0.0)
                                           if _skipped else 1.0),
                            "note": "操作员跳过（未验证）" if _skipped else "操作员确认",
                            "evidence": ("跳过（未验证）：%s" % _subj if _skipped
                                         else "操作员确认：%s %s" % (_subj, _label)),
                            "ts": _flow_iso(),
                            "source": "ui_kiosk.flow",
                            "item_id": _qa.get("qa_id"),
                            "qa_id": _qa.get("qa_id"),
                            "qa_value": _opt.get("value"),
                            "flow_no": _st.get("flow_no"),
                            "flow_name": _st.get("flow_name"),
                            "step_id": _st["step_id"],
                            "step_name": _st.get("step_name"),
                            "check_item": _qa.get("check_item"),
                        }
                        if _opt.get("feature_id") and not _skipped:
                            _ev["feature_id"] = _opt["feature_id"]
                        _flow_answers(flow, _st)[_qa.get("qa_id")] = {
                            "value": _opt.get("value"), "label": _label,
                            "skipped": _skipped, "ts": _ev["ts"]}
                        _flow_add_evidence(flow, _ev)

                        try:
                            _z18_enrich_qa_evidence(flow, _st, _qa, _ev)
                        except Exception as _z18e2:               
                            print("[z18] enrich 失败: %s" % _z18e2, flush=True)
                        _rest = _flow_cur_qa(flow, _st)
                        toast = ("已记录：%s" % _label) + ("" if _rest else "（本步问答完成）")
                        toast_until = now + 3.0
                        print("[flow] 问答 step=%s %s=%s -> %s"
                              % (_st["step_id"], _qa.get("qa_id"),
                                 _opt.get("value"), flow["path"]), flush=True)

                        if state == "flowqa" and _rest is None:
                            state = "flow"
                            toast = "本步问答完成 → 回流程页"
                            print("[flowqa] 本步问答完成 step=%s -> 回流程页"
                                  % _st["step_id"], flush=True)

        if isinstance(act, str) and act.startswith("summary:") and state == "summary":
            _cmd = act.split(":", 1)[1]
            if _cmd == "back":
                confirm_again_until = 0.0
                _nev = len(flow["evidence"]) if flow is not None else 0
                state = "flow" if flow is not None else "page1"
                summary_cache.clear()
                toast = "已返回流程页（本轮证据 %d 条，可继续拍）" % _nev
                toast_until = now + 3.0
                print("[summary] 返回流程页（证据 %d 条保留）" % _nev, flush=True)
            elif _cmd == "again":

                confirm_again_until = now + 10.0
                toast, toast_until = "确定清空本轮？【确定】【取消】", now + 10.0
                print("[kiosk] 二次确认：点【再拍一轮】→ 显示确认条（本轮证据尚未清空）",
                      flush=True)
            elif _cmd == "again_cancel":
                confirm_again_until = 0.0
                toast, toast_until = "已取消清空（本轮证据保留）", now + 3.0
                print("[kiosk] 二次确认：取消清空（证据保留）", flush=True)
            elif _cmd == "again_confirm":

                _busy_begin(busy, "summary:again_confirm", state)
                _show_busy_now(canvas)
                confirm_again_until = 0.0
                try:
                    if flow is not None:
                        _flow_save(flow)
                    _doc, _p = load_flow_steps(getattr(a, "steps", "") or "")
                    flow = _new_flow(_doc, _p)
                    flow["idx"] = 0
                    _flow_save(flow)              
                    flow_cache.clear()
                    summary_cache.clear()
                    state = "flow"
                    toast = "已清空本轮证据 → 第 1 步"
                    toast_until = now + 4.0
                    print("[summary] 再拍一轮（已确认）：新 session=%s（证据已清空，idx=0）"
                          % flow["session_id"], flush=True)
                except Exception as _e:                                
                    toast, toast_until = ("清空失败：%s" % str(_e))[:52], now + 6.0
                    print("[summary] 再拍一轮失败（停留总结页）: %s" % _e, flush=True)
                _busy_end(busy)

        if act == "summary_all" or (isinstance(act, str) and act.startswith("summary_all:")
                                    and state == "summary_all"):
            _cmd = act.split(":", 1)[1] if ":" in str(act) else ""
            if act == "summary_all":
                _busy_begin(busy, "summary_all", state)
                _show_busy_now(canvas)
                _t_sa = time.time()
                err = ""
                try:
                    sa = _sa_build(flow=flow)
                    sa_cache.clear()
                    state = "summary_all"
                    toast, toast_until = "", 0.0
                    print("[summary_all] 生成：verdict=%s 用时 %.2fs"
                          % (((sa.get("summary") or {}).get("verdict")), time.time() - _t_sa),
                          flush=True)
                except Exception as _e:                            
                    sa = _sa_error(SUMMARY_MODULE_ERR, "构建汇总页异常：%s" % _e)
                    sa_cache.clear()
                    state = "summary_all"
                    print("[summary_all] 构建异常（已降级，UI 不崩）: %s" % _e, flush=True)
                _busy_end(busy)
            elif _cmd == "back":
                state = "page1"
                sa_cache.clear()
                toast, toast_until = "", 0.0
                print("[summary_all] 返回主页", flush=True)
            elif _cmd == "again":
                _busy_begin(busy, "summary_all", state)
                _show_busy_now(canvas)
                try:
                    sa = _sa_build(flow=flow)
                    sa_cache.clear()
                    toast, toast_until = ("已重新汇总（%s）" % (sa.get("updated") or "")), now + 3.0
                    print("[summary_all] 重新汇总：verdict=%s"
                          % ((sa.get("summary") or {}).get("verdict")), flush=True)
                except Exception as _e:                            
                    sa = _sa_error(SUMMARY_MODULE_ERR, "重新汇总异常：%s" % _e)
                    sa_cache.clear()
                    print("[summary_all] 重新汇总异常（已降级）: %s" % _e, flush=True)
                _busy_end(busy)

        if isinstance(act, str) and act.startswith("result:") and state == "result":
            _cmd = act.split(":", 1)[1]
            _mode = res_meta.get("mode") or "page1"

            _auto_due = False
            res_meta.pop("auto_qa_at", None)
            if _cmd == "back":

                res_meta["auto_qa_off"] = True
                state = "flow" if _mode == "flow" else "page1"
                res_cache.clear()
                toast, toast_until = "已取消自动问答", now + 2.0
                print("[result] 返回 %s（已取消自动问答）" % state, flush=True)
            elif _cmd == "qa":
                _stq = _flow_step(flow) if (flow is not None and _mode == "flow") else None
                if _stq and _flow_cur_qa(flow, _stq) is not None:
                    state = "flowqa"
                    qa_cache.clear()
                    toast, toast_until = "", 0.0
                    print("[flowqa] 进入本步问答 step=%s（剩 %d 题）"
                          % (_stq["step_id"],
                             len(_stq.get("qa_items") or [])
                             - len(_flow_answers(flow, _stq))), flush=True)
                elif (res_meta.get("part_qa") and (res_meta["part_qa"].get("items"))
                      and (len(res_meta["part_qa"].get("items") or [])
                           > len(res_meta["part_qa"].get("answers") or {}))):

                    _pq = res_meta["part_qa"]
                    _pq["idx"] = min(int(_pq.get("idx") or 0), len(_pq["items"]) - 1)
                    state = "partqa"
                    qa_cache.clear()
                    toast, toast_until = "", 0.0
                    print("[partqa] 进入按部位问答 part=%s（剩 %d 题）"
                          % (_pq.get("part") or "-",
                             max(0, len(_pq["items"]) - len(_pq.get("answers") or {}))),
                          flush=True)
                elif (res_meta.get("part_qa") or {}).get("items"):
                    toast, toast_until = "本部位问答已完成（题库共 %d 题）" % len(
                        (res_meta.get("part_qa") or {}).get("items") or []), now + 3.0
                else:
                    toast, toast_until = "本步没有待答的问题", now + 3.0
            elif _cmd == "retake":
                if BI is None:
                    toast, toast_until = "判定适配层不可用（board_infer）", now + 5.0
                elif frame is None:
                    toast, toast_until = "取流失败，无法重拍", now + 3.0
                elif res_job is not None and not res_job.done:
                    toast, toast_until = "上一张还在判定中，请稍候…", now + 3.0
                else:
                    resv, res_cache = None, {}
                    res_meta["merged"] = False
                    res_meta.pop("frame", None)

                    for _k in ("part_qa", "auto_qa_off", "auto_qa_at"):
                        res_meta.pop(_k, None)
                    try:
                        res_meta["frame"] = frame.copy()
                    except Exception:                                  
                        pass

                    _mr2 = _marker_route(marker_hit)
                    if _mr2:
                        res_meta["marker_route"] = _mr2
                        if not str(res_meta.get("step_id") or ""):
                            res_meta["route"] = _mr2
                    res_job = BI.start_job(frame,
                                           part_hint=(res_meta.get("part_use") or part or ""),
                                           flow_no=None,
                                           route=(_mr2 or res_meta.get("route") or ""))
                    toast, toast_until = "重拍中…", now + 2.0
                    print("[result] 重拍（新任务）", flush=True)
            elif _cmd.startswith("pick:"):

                _i = int(_cmd.split(":", 1)[1])
                _cands = ((resv or {}).get("part") or {}).get("candidates") or []
                if res_job is not None and not res_job.done:
                    toast, toast_until = "上一张还在判定中，请稍候…", now + 3.0
                elif _i >= len(_cands):
                    toast, toast_until = "该候选已失效", now + 3.0
                elif res_meta.get("frame") is None:
                    toast, toast_until = "原帧已释放，请用【重拍】", now + 4.0
                elif BI is None:
                    toast, toast_until = "判定适配层不可用（board_infer）", now + 5.0
                else:
                    _p = _cands[_i].get("part") or ""
                    resv, res_cache = None, {}
                    res_meta["merged"] = False
                    res_meta["picked"] = _p
                    res_meta["part_use"] = _p
                    res_meta["marker_label"] = ""      

                    
                    _mk_part = _part_key((getattr(marker_hit, "module", None) or {})
                                         .get("part")) if marker_hit is not None else ""
                    if _mk_part and _mk_part != _part_key(_p):
                        res_meta["marker_route"] = ""
                        if not str(res_meta.get("step_id") or ""):
                            res_meta["route"] = ""
                    for _k in ("part_qa", "auto_qa_off", "auto_qa_at"):
                        res_meta.pop(_k, None)
                    res_job = BI.start_job(res_meta["frame"], part_hint=_p,
                                           flow_no=None,
                                           route=(res_meta.get("marker_route")
                                                  or res_meta.get("route") or ""))
                    toast, toast_until = ("改判部位=%s，判定中…" % _p), now + 2.0
                    print("[result] 人工改选部位 %s → 重跑判定" % _p, flush=True)

        

        if _auto_due and state == "result":
            _stq2 = _flow_step(flow) if (flow is not None
                                         and res_meta.get("mode") == "flow") else None
            if _stq2 and _flow_cur_qa(flow, _stq2) is not None:
                state = "flowqa"
                qa_cache.clear()
                res_meta.pop("auto_qa_at", None)
                _left2 = (len(_stq2.get("qa_items") or [])
                          - len(_flow_answers(flow, _stq2)))
                toast, toast_until = ("3 秒到 → 自动进入问答（剩 %d 题）" % _left2), now + 3.0
                print("[result] 倒计时到点 → 自动进入问答 step=%s（剩 %d 题）"
                      % (_stq2["step_id"], _left2), flush=True)
            elif (res_meta.get("part_qa") or {}).get("items"):

                _pq2 = res_meta["part_qa"]
                _pq2["idx"] = min(int(_pq2.get("idx") or 0), len(_pq2["items"]) - 1)
                state = "partqa"
                qa_cache.clear()
                res_meta.pop("auto_qa_at", None)
                _left3 = max(0, len(_pq2["items"]) - len(_pq2.get("answers") or {}))
                toast, toast_until = ("3 秒到 → 自动进入问答（剩 %d 题）" % _left3), now + 3.0
                print("[result] 倒计时到点 → 自动进入按部位问答 part=%s（剩 %d 题，首题 %s）"
                      % (_pq2.get("part") or "-", _left3,
                         _pq2["items"][_pq2["idx"]].get("qa_id")), flush=True)

        if isinstance(act, str) and act.startswith("partqa:") and state == "partqa":
            _pq3 = res_meta.get("part_qa") or {}
            _cmd3 = act.split(":", 1)[1]
            if _cmd3 == "back":
                state = "page1"
                qa_cache.clear()
                toast, toast_until = "已退出按部位问答（作答 %d 题已记录）" % len(
                    _pq3.get("answers") or {}), now + 3.0
                print("[partqa] 返回主页（已答 %d 题）"
                      % len(_pq3.get("answers") or {}), flush=True)
            elif _pq3.get("items"):
                _q3 = _pq3["items"][int(_pq3.get("idx") or 0)]
                if _cmd3 == "skip":
                    _o3 = {"value": "skipped", "label": "跳过", "tone": "neutral"}
                else:
                    _want3 = _cmd3.split("answer:", 1)[1]
                    _o3 = next((o for o in _q3.get("options") or []
                                if str(o.get("value")) == _want3), None)
                if _o3 is None:
                    toast, toast_until = ("无效选项：%s" % _cmd3)[:48], now + 3.0
                else:
                    _v3 = _flow_value(_o3.get("value"))
                    _skip3 = _v3 in ("skipped", "undetermined")
                    _lab3 = _o3.get("label_plain") or _o3.get("label") or _o3.get("value")
                    _pq3.setdefault("answers", {})[_q3.get("qa_id")] = {
                        "value": _o3.get("value"), "label": _lab3, "skipped": _skip3,
                        "ts": _flow_iso()}

                    _ev3 = {
                        "part": _pq3.get("part") or "",
                        "route": _pq3.get("route") or _q3.get("route") or "",
                        "modality": "qa",
                        "field": (_q3.get("evidence_field")
                                  or ("(manual_action)_partqa_%s" % _q3.get("qa_id"))),
                        "value": _v3,
                        "confidence": (0.30 if _v3 == "undetermined" else
                                       (0.0 if _skip3 else 1.0)),
                        "note": "操作员跳过（未验证）" if _skip3 else "操作员确认",
                        "evidence": ("跳过（未验证）：%s" % _q3.get("question")
                                     if _skip3 else
                                     "操作员确认：%s → %s" % (_q3.get("question"), _lab3)),
                        "ts": _flow_iso(), "source": "ui_kiosk.partqa",
                        "item_id": _q3.get("qa_id"), "qa_id": _q3.get("qa_id"),
                        "qa_value": _o3.get("value"),
                        "check_item": _q3.get("check_item") or _q3.get("question"),
                        "screen_key": _q3.get("screen_key") or "",
                    }
                    _pq3.setdefault("evidence", []).append(_ev3)

                    
                    try:
                        if resv is not None:
                            resv = _apply_partqa(resv, _pq3)
                            res_cache.clear()
                    except Exception as _e3b:       
                        print("[partqa] 合并回结果页失败: %s" % _e3b, flush=True)
                    if flow is not None:            
                        try:
                            _flow_add_evidence(flow, _ev3)
                        except Exception as _e3:     
                            print("[partqa] 并入流程证据失败: %s" % _e3, flush=True)
                    _pq3["idx"] = int(_pq3.get("idx") or 0) + 1
                    _left3 = len(_pq3["items"]) - _pq3["idx"]
                    toast = ("已记录：%s" % _lab3) + ("" if _left3 > 0 else "（本部位问答完成）")
                    toast_until = now + 3.0
                    print("[partqa] 作答 %s part=%s value=%s（剩 %d 题）"
                          % (_q3.get("qa_id"), _pq3.get("part"), _o3.get("value"), _left3),
                          flush=True)
                    if _left3 <= 0:
                        state = "result"
                        qa_cache.clear()
                        res_cache.clear()
                        _nq3 = len(_pq3.get("items") or [])
                        if _nq3 > 1:
                            toast = "本部位问答完成（共 %d 题）→ 回结果页" % _nq3
                        else:
                            toast = ("本部位题库仅 1 题（已答完）→ 回结果页；"
                                     "更多问题请进入流程检测")
                        toast_until = now + 3.0
                        print("[partqa] 本部位问答完成 part=%s（共 %d 题）→ 回结果页"
                              % (_pq3.get("part") or "-", _nq3), flush=True)

        

        if act == "flowqa:back" and state == "flowqa":
            state = "flow"
            qa_cache.clear()
            toast, toast_until = "已返回流程页", now + 2.0
            print("[flowqa] 返回流程页", flush=True)

        if act == "qa" and state != "qa":
            try:
                from soc_vision.qa.qa_flow import QAFlow   
                if qa is None:

                    _qa_items = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                             "qa", "qa_items.json")
                    qa = QAFlow(_qa_items,
                                schema_values=True)          
                qa.start()
                qa_cache.clear()
                state = "qa"
                print("[qa] 开始：%d 题" % qa.total, flush=True)
            except Exception as _e:  
                toast, toast_until = ("问答模块不可用：%s" % str(_e))[:48], now + 5.0
                print("[qa] 启动失败: %s" % _e, flush=True)
        elif isinstance(act, str) and act.startswith("qa:"):
            _cmd = act.split(":", 1)[1]
            try:
                if qa is None:
                    raise RuntimeError("问答未启动")
                if _cmd == "back":
                    qa.abort()
                    state = "page1"
                    _nev = len(qa.evidence())
                    toast = ("已退出问答（已答 %d 条）" % _nev) if _nev else "已退出问答"
                    toast_until = now + 3.0
                elif _cmd == "skip":
                    qa.skip()
                else:
                    qa.answer(_cmd)
                    qa.next()
                if _cmd != "back" and qa.current() is None:
                    _sum = qa.summary()
                    _dir = "/userdata/afh03_shots/qa"
                    os.makedirs(_dir, exist_ok=True)
                    _p = os.path.join(_dir, "qa_evidence_%s.json"
                                      % time.strftime("%Y%m%d_%H%M%S"))
                    with open(_p, "w", encoding="utf-8") as _f:
                        json.dump(qa.evidence_batch(), _f, ensure_ascii=False, indent=1)
                    print("[qa] 完成：证据 %d 条 / 跳过 %d 条 -> %s"
                          % (len(_sum["evidence"]), _sum["skipped"], _p), flush=True)
                    toast = "问答完成（证据 %d 条）" % len(_sum["evidence"])
                    toast_until = now + 5.0
                    state = "page1"
            except Exception as _e:  
                print("[qa] 作答失败: %s" % _e, flush=True)
            qa_cache.clear()
        if act == "back":
            state = "page1"
            toast, toast_until = "", 0.0
        elif act == "wave":

            _busy_begin(busy, "wave", state)
            _show_busy_now(canvas)
            state = "wave"
            wave_res = None          
            wave_at = now
            _started = MEAS.start()
            if not _started:
                _busy_end(busy)      
            print("[wave] 进入波形页 → 自动触发一次 scope_quick/VXI-11 测量"
                  "（started=%s；后台线程，测量 3 条 + 波形段，DATA? 1 次，约 6 秒）"
                  % _started, flush=True)
        elif act == "retest":
            if state == "wave":
                if MEAS.running():
                    print("[wave] 重新测量被忽略：已有一次测量在跑（不叠加、不风暴）",
                          flush=True)
                else:
                    wave_res = None
                    wave_at = now
                    _started = MEAS.start(force=True)
                    print("[wave] 点【重新测量】→ 重新跑一次 VXI-11 测量（started=%s）"
                          % _started, flush=True)
        elif act == "capture":

            _busy_begin(busy, "capture", state)
            _show_busy_now(canvas)
            if frame is None:
                toast, toast_until = "取流失败，无法拍照", now + 3.0
                print("[kiosk] capture 失败：没有帧", flush=True)
            else:

                

                
                if (mi is not None and marker_hit is None and not _explicit_part
                        and not part and mworker is not None and frame is not None):
                    try:
                        mworker.set_frame(frame)
                    except Exception:                                
                        pass
                    _w_t0 = time.time()
                    while marker_hit is None and (time.time() - _w_t0) < 2.0:
                        time.sleep(0.05)
                        _h = getattr(mworker, "hit", None)
                        if _h is not None:
                            marker_hit = _h
                    _cand2 = list(getattr(mworker, "hits", None) or [])
                    if marker_hit is None and _cand2:
                        _lb2 = getattr(_cand2[0], "label", "?")
                        _pg2 = tuple(getattr(mworker, "progress", (0, 0)) or (0, 0))
                        toast, toast_until = (
                            "标记识别中（%s %d/%d）→ 请 1 秒后再拍"
                            % (_lb2, int(_pg2[0]), max(1, int(_pg2[1]) or 3)))[:56], now + 3.0
                        print("[marker] capture 延后：候选 %s 未确认（%d/%d），不空 part 拍照"
                              % (_lb2, int(_pg2[0]), max(1, int(_pg2[1]) or 3)), flush=True)
                        _busy_end(busy)
                        continue
                    if marker_hit is not None:
                        print("[marker] capture 等待 %.1fs 后确认 %s（%s）"
                              % (time.time() - _w_t0, marker_hit.label,
                                 (marker_hit.module or {}).get("name", "")), flush=True)

                part_use, part_why, part_conf = _effective_part(
                    part, mi, marker_hit, calib, explicit_part=_explicit_part)
                print("[marker] 归属: part=%s conf=%.2f (%s)" % (part_use or "-", part_conf, part_why),
                      flush=True)

                
                allow = bool(a.auto) or (marker_hit is not None and bool(part_use))

                frame_j = frame
                if marker_hit is not None:
                    try:
                        frame_j = frame.copy()
                        cx, cy = int(marker_hit.cx), int(marker_hit.cy)
                        hh, ww = frame_j.shape[:2]
                        sp = float(getattr(marker_hit, "side_px", 0) or 0)

                        rr = int(max(0.08 * min(hh, ww), sp * 4))
                        rr = max(rr, 24)
                        frame_j[max(0, cy - rr):cy + rr, max(0, cx - rr):cx + rr] = 0
                        print("[marker] 涂黑标记区 中心=(%d,%d) 半径=%dpx（side_px=%.0f；帧 %dx%d）"
                              % (cx, cy, rr, sp, ww, hh), flush=True)
                    except Exception as _e:                              
                        print("[marker] 涂黑标记区失败: %s" % _e, flush=True)
                res = run_capture(frame_j, part_use, book, calib, det, allow, a.shots_dir, scope)
                still = frame
                if res["ok"]:
                    vobj = dict(res["vobj"])
                    tag = ""
                    if not calib:
                        tag = "（自动判定·未标定）"
                    extra = ("%s ｜ %s" % (vobj.get("reason", ""), part_why)) if part_why else vobj.get("reason", "")
                    vobj["reason"] = "%s%s" % (extra, tag)
                    err = ""
                    print("[kiosk] 拍照成功 -> %s 结论=%s" % (res["shot_dir"], res["verdict"]),
                          flush=True)

                    
                    if BI is None:
                        state = "page2"
                        toast, toast_until = "已保存（判定适配层不可用）", now + 4.0
                    else:
                        resv, res_cache = None, {}
                        res_meta.clear()
                        res_meta.update({"mode": "page1", "merged": False,
                                         "field": "(vision)_page1",
                                         "shot_dir": res.get("shot_dir"),
                                         "part_use": part_use or "",

                                         "route": _marker_route(marker_hit),
                                         "marker_route": _marker_route(marker_hit),
                                         "marker_label": (marker_hit.label
                                                          if marker_hit is not None else "")})
                        try:
                            res_meta["frame"] = frame.copy()
                        except Exception:                          
                            pass
                        res_job = BI.start_job(frame, part_hint=(part_use or ""),
                                               flow_no=None,
                                               route=_marker_route(marker_hit))
                        state = "result"
                        toast, toast_until = "已保存 → 判定中…", now + 4.0
                        print("[result] 主页拍照 → 结果页：后台判定已启动", flush=True)
                else:

                    vobj = {"verdict": VERDICT_UNK,
                            "reason": "拍照失败：%s" % (res["error"] or "未知错误")}
                    state = "page2"
                    err = "拍照失败：%s" % (res["error"] or "未知错误")
                    toast, toast_until = err[:52], now + 8.0
                    print("[kiosk] 拍照失败但**进程保留**: %s" % res["error"], flush=True)
            _busy_end(busy)          

        if state != "summary" and confirm_again_until:
            confirm_again_until = 0.0

        _n_iter += 1
        if _n_iter % 200 == 0:
            _dt = time.time() - _t_mark
            cpu = -1.0
            try:
                with open("/proc/self/stat") as _f:
                    _p = _f.read().split()
                cpu = float(_p[13] + _p[14])        
            except Exception:                                        
                pass
            print("[ui] preview fps=%.1f（目标 %.1f） cpu_ticks=%.0f marker=每 %.1fs"
                  % (_n_iter / max(1e-6, _dt), fps, cpu, a.marker_interval), flush=True)
            _n_iter, _t_mark = 0, time.time()
        if a.duration > 0 and (now - t0) >= a.duration:
            break
    if live:
        live.release()
    cv2.destroyAllWindows()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
