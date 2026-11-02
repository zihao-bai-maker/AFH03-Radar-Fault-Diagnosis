# -*- coding: utf-8 -*-
"""board_infer.py —— 薄适配层：把 ``engine/`` 里的**部位识别**与**摄像头判定**接进
``ui_kiosk.py``，并把结果整理成"结果页"直接可渲染的结构。

设计约束（硬）
--------------
* **只调用** ``engine/`` 里的公开函数（``part_recognizer.recognize`` /
  ``vision_rules.run_photo`` / ``fusion.FusionEngine`` / ``fault_grader.FaultGrader``），
  **不修改**它们的任何逻辑；本文件是唯一的新增层。
* **绝不抛异常**：任何一环失败都降级为"未判定 + 原因"，让 UI 继续跑。
* **板端无 RapidOCR/onnxruntime 也要能工作**：``part_recognizer`` 自带
  "模板 NCC 兜底"，本层只负责把后端选成 ``auto``（有 RapidOCR 用，没有就退模板）。
* 板端 Python 3.11 / aarch64；**cv2 可用**（实测 5.0.0），本层不额外依赖别的三方包。

返回结构（``infer()``）
----------------------
::

    {
      "ok": bool,                 # 整链是否跑通（False 时看 error）
      "error": "",                # 失败原因（人话）
      "elapsed_ms": int,
      "deps": {...},              # 各依赖是否可用（给日志/报告用）
      "part": {                   # 部位识别（part_recognizer）
         "part": "z11", "display": "z11 收发", "confidence": 0.96,
         "decision": "高置信（≥0.90）", "need_confirm": False,
         "reasons": [...], "question": "请确认这是 z11 收发 吗？",
         "candidates": [{"part","name","score"}...],
         "part_used": "z11", "part_source": "识别",
         "hint_conflict": ""      # 识别 vs 步骤部位不一致时的人话
      },
      "vision": {...},            # vision_rules.run_photo 原始结果（含 evidence）
      "rows": [                   # ★ 结果页逐条：灯 / 屏
         {"kind":"led"|"screen", "pos":"第 3/5 位", "name":"发射通", "color":"G",
          "state":"on"|"off"|"ok"|"black_screen"..., "state_text":"亮"/"灭",
          "expect_text":"应亮", "match": True/False/None,
          "meaning":"（I）路-Z11（收发）-[发射通]-指示灯亮",
          "conf":0.83, "why":"第 3/5 位（发射通，应为绿灯）亮：…"}
      ],
      "undetermined": {"n": 883, "reasons": ["...","..."]},
      "conclusion": {"state":"ok"|"bad"|"unknown", "text":"正常（4 项符合）",
                     "why":"...", "n_bad":0, "n_ok":4},
      "candidates": ["候选故障：…"],   # fault_grader 有就用，没有就退化为判据库 fault_refs
      "evidence_items": [...]        # 可直接灌进流程证据（每条一个灯/屏）
    }
"""

from __future__ import annotations

import os
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
BOARD_DIR = os.path.dirname(HERE)          

try:                                                                  
    from .module_route_alias import is_legacy_ii as _is_legacy_ii
except Exception:                                                     
    try:                                                              
        from module_route_alias import is_legacy_ii as _is_legacy_ii
    except Exception:                                                 
        def _is_legacy_ii(part):                                      
            """兜底（helper 缺失）：不认旧 id。"""
            return False

ENGINE_CANDIDATES = [
    os.environ.get("AFH03_ENGINE", ""),
    "/userdata/work2/engine",
    os.path.join(BOARD_DIR, "engine"),
    "/home/rock/radar_criteria/engine",
]

MAX_ROWS_UI = 8        
MAX_EV_ITEM = 24       
MAX_UND_REASONS = 4

SCREEN_TEXT = {
    "ok": "正常", "black_screen": "黑屏", "yellow_screen": "黄屏",
    "garbled": "花屏", "no": "无回波/无扫描", "weak": "回波弱",
    "no_noise": "无噪声", "abnormal": "波形异常", "no_move": "指针不动",
}

_S = {
    "engine": "",
    "ready": False,
    "deps": {},
    "mod": {},          
    "items": None,
    "errors": [],
    "boot_tried": False,
}

def _log(msg):
    try:
        print("[infer] %s" % msg, flush=True)
    except Exception:                                              
        pass

def _find_engine():
    for c in ENGINE_CANDIDATES:
        if not c:
            continue
        if (os.path.isfile(os.path.join(c, "vision_rules.py"))
                and os.path.isfile(os.path.join(c, "part_recognizer.py"))):
            return os.path.abspath(c)
    return ""

def bootstrap(force=False):
    """懒加载 engine 与各依赖。返回是否可用；**绝不抛**。"""
    if _S["ready"] and not force:
        return True
    _S["boot_tried"] = True
    eng = _find_engine()
    _S["engine"] = eng
    if not eng:
        _S["errors"].append("找不到 engine/（试过：%s）"
                            % "；".join(x for x in ENGINE_CANDIDATES if x))
        _log(_S["errors"][-1])
        return False
    for p in (eng, BOARD_DIR):
        if p and p not in sys.path:
            sys.path.insert(0, p)

    for name in ("fusion", "fault_grader", "part_recognizer", "vision_rules"):
        if name in _S["mod"]:
            continue
        try:
            _S["mod"][name] = __import__(name)
            _S["deps"][name] = {"ok": True, "error": "", "file": eng}
        except Exception as e:                                     
            _S["mod"][name] = None
            _S["deps"][name] = {"ok": False, "error": "%s: %s" % (type(e).__name__, e),
                                "file": eng}
            _S["errors"].append("import %s 失败：%s" % (name, e))
            _log(_S["deps"][name]["error"])
    _S["ready"] = all(v.get("ok") for v in _S["deps"].values())
    _log("engine=%s ready=%s" % (eng, _S["ready"]))
    return _S["ready"]

def status():
    """给日志/报告用的依赖快照。"""
    bootstrap()
    out = {"engine": _S["engine"], "ready": _S["ready"], "deps": dict(_S["deps"]),
           "errors": list(_S["errors"])}
    try:
        import numpy as _np
        out["numpy"] = getattr(_np, "__version__", "?")
    except Exception:                                              
        out["numpy"] = ""
    try:
        import cv2 as _cv
        out["cv2"] = getattr(_cv, "__version__", "?")
    except Exception:                                              
        out["cv2"] = ""
    try:
        import rapidocr_onnxruntime as _r                     
        out["rapidocr"] = "yes"
    except Exception:                                              
        out["rapidocr"] = ""
    pr = _S["mod"].get("part_recognizer")
    if pr is not None:
        try:
            out["ocr_backend"] = getattr(pr, "_DEFAULT", None) and "init" or "auto"
        except Exception:                                          
            pass
    return out

def _mod(name):
    return _S["mod"].get(name)

_LED_PID_TO_PART = {}
_LED_PID_READY = False

def _led_pid_to_part():
    """led_rules 规则 id（PS_KONG…）→ 判据库部位（z31…）的映射（从 vision_bindings 反推）。"""
    global _LED_PID_READY
    if _LED_PID_READY:
        return _LED_PID_TO_PART
    _LED_PID_READY = True
    vr = _mod("vision_rules")
    if vr is None:
        return _LED_PID_TO_PART
    try:
        for it in _catalog():
            bn = str(getattr(it, "binding", "") or "")
            ref = str(getattr(it, "binding_ref", "") or "")
            part = str(getattr(it, "part", "") or "")
            if not bn.startswith("led") or not ref or not part:
                continue
            pid = ref.partition("#")[0]
            if pid:
                _LED_PID_TO_PART.setdefault(pid.lower(), part.lower())
    except Exception as e:                                         
        _log("led pid→part 映射构建失败（不影响判灯）: %s" % e)
    return _LED_PID_TO_PART

def kb_part(hint):
    """把规则表 id（PS_KONG / Z31）归一成判据库部位（z31）；已是 z 编号则原样返回。

    ★ 2026-10-29 用户口径：z11-1 / z12-clk(或 Z12-GL) / z14-clk / z15-if 都是母模块的
      **二路二维码**（不是独立部位）→ 归一成母模块（z11/z12/z14/z15），规则/问答都用母模块。
    """
    _ALIAS_II = {
        "z11-1": "z11", "z11ii": "z11", "z11-ii": "z11",
        "z12-gl": "z12", "z12-clk": "z12", "z12clk": "z12",
        "z14-clk": "z14", "z14clk": "z14",
        "z15-if": "z15", "z15if": "z15",
    }
    h = str(hint or "").strip()
    if not h:
        return ""
    h = _ALIAS_II.get(h.lower(), h)
    return _led_pid_to_part().get(h.lower(), h)

def _part_info_from_hint(hint, why="由标记/步骤/人工指定"):
    """有 part_hint 时的轻量部位信息（不跑识别；置信按指定=1.0）。"""
    pr = _mod("part_recognizer")
    display = ""
    if pr is not None:
        try:
            display = pr.part_display(hint) or ""
        except Exception:                                          
            display = ""
    return {"part": hint, "display": display, "confidence": 1.0,
            "decision": "指定（标记/步骤）", "need_confirm": False,
            "reasons": [why], "question": "", "candidates": [],
            "elapsed_ms": 0, "ocr_backend": "", "raw": {}}

def _empty(why, part_hint=""):
    return {
        "ok": False, "error": why, "elapsed_ms": 0, "deps": dict(_S["deps"]),
        "part": {"part": "", "display": "", "confidence": 0.0, "decision": "未识别",
                 "need_confirm": True, "reasons": [why], "question": "",
                 "candidates": [], "part_used": part_hint,
                 "part_source": ("步骤/标定" if part_hint else ""), "hint_conflict": ""},
        "vision": {}, "rows": [], "undetermined": {"n": 0, "reasons": []},
        "conclusion": {"state": "unknown", "text": "未判定", "why": why,
                       "n_bad": 0, "n_ok": 0},
        "candidates": [], "evidence_items": [],
    }

def recognize_part(frame, part_hint="", flow_no=None, route="", prior_part=""):
    """调 part_recognizer.recognize()。异常 → 空结果（need_confirm=True）。"""
    pr = _mod("part_recognizer")
    if pr is None:
        return {"part": "", "display": "", "confidence": 0.0, "decision": "未识别",
                "need_confirm": True, "reasons": ["part_recognizer 不可用"],
                "question": "", "candidates": [], "raw": {}}
    try:

        

        r = pr.recognize(frame, flow_no=flow_no, route=route,
                         prior_part=prior_part)
    except Exception as e:                                         
        _log("recognize 失败: %s" % e)
        traceback.print_exc()
        return {"part": "", "display": "", "confidence": 0.0, "decision": "未识别",
                "need_confirm": True,
                "reasons": ["识别异常（%s: %s）" % (type(e).__name__, e)],
                "question": "", "candidates": [], "raw": {}}
    cands = []
    for c in (r.get("candidates") or [])[:4]:
        cands.append({"part": c.get("part") or "",
                      "name": c.get("name") or "",
                      "score": round(float(c.get("score") or 0.0), 3)})
    return {
        "part": r.get("part") or "",
        "display": r.get("part_display") or r.get("name") or "",
        "confidence": round(float(r.get("confidence") or 0.0), 3),
        "decision": r.get("decision") or "",
        "need_confirm": bool(r.get("need_confirm")),
        "reasons": list(r.get("reasons") or []),
        "question": r.get("question") or "",
        "candidates": cands,
        "elapsed_ms": int((r.get("meta") or {}).get("elapsed_ms") or 0),
        "ocr_backend": (r.get("meta") or {}).get("ocr_backend") or "",

        
        "route": r.get("route") or "",
        "legacy_part": r.get("legacy_part") or "",
        "route_locked": bool(r.get("route_locked")),
        "raw": r,
    }

def _catalog():
    if _S["items"] is not None:
        return _S["items"]
    vr = _mod("vision_rules")
    if vr is None:
        return []
    try:
        _S["items"] = list(vr.load_catalog())
        _log("判据库载入 %d 条（摄像头拍摄）" % len(_S["items"]))
    except Exception as e:                                         
        _S["items"] = []
        _log("判据库载入失败: %s" % e)
    return _S["items"]

def run_vision(frame, part="", do_meter=False):
    """把一帧交给 vision_rules.run_photo 判定。

    ★ 2026-10-29：优先 `bgr=frame` 直接传内存帧（不再写临时 jpg 再解码）——
      JPEG 再编码会让暗场/临界灯的斑块检出翻转（实测同一张 191629/195122：
      结果页 engine 与拍照即判 soc_vision 给出不同结论）。老版 engine 没有 bgr 参数时
      自动退回落盘路径（兼容，不炸）。
    """
    vr = _mod("vision_rules")
    if vr is None:
        return {"ok": False, "error": "vision_rules 不可用", "pack": {}}
    items = _catalog()
    tmp = "/tmp/afh03_infer_%d_%s.jpg" % (os.getpid(), time.strftime("%H%M%S"))
    try:
        pack = None
        try:
            pack = vr.run_photo("", items=items or None, part=part,
                                do_meter=do_meter, bgr=frame)
            src = "内存帧"
        except TypeError:
            pack = None
        if pack is None:
            import cv2
            if not cv2.imwrite(tmp, frame):
                return {"ok": False, "error": "临时图写入失败", "pack": {}}
            pack = vr.run_photo(tmp, items=items or None, part=part, do_meter=do_meter)
            src = "临时图"
        n = len(pack.get("evidence") or [])
        _log("run_photo part=%s -> %d 条证据 (decided=%s, src=%s)"
             % (part or "-", n, pack.get("n_decided"), src))
        return {"ok": True, "error": "", "pack": pack, "tmp": tmp, "items": items}
    except Exception as e:                                         
        _log("run_photo 失败: %s" % e)
        traceback.print_exc()
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e), "pack": {}}
    finally:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except Exception:                                          
            pass

_EXPECT_TEXT = {"on": "应亮", "off": "应灭", "any": "任亮灭", "": "—",
                "正常": "整排恰好一亮一灭"}

def _led_match(value, expect):
    """灯：观测值 vs 规则期望。返回 True/False/None(不好判)。"""
    if value not in ("on", "off"):
        return None
    if expect in ("正常", ""):        
        return value == "on"
    if expect == "any":
        return True
    return value == expect

def rows_from_evidence(pack, part=""):
    """把 vision_rules 的 evidence 列表拆成 (结果页逐条, 未判定原因)。

    ★ 跳过 ``route_mirrored`` 的镜像条目：它和原生条目是**同一颗灯**在另一路的投影，
    放进列表会出现"同一颗灯两行"。镜像条目仍然保留在 ``vision_evidence`` 里落盘。
    """
    evs = list(pack.get("evidence") or [])
    parts_tbl = {}
    vr = _mod("vision_rules")
    if vr is not None:
        try:
            parts_tbl = vr.parts_table()
        except Exception:                                          
            parts_tbl = {}
    rows, und_reasons, und_led = [], [], []
    for e in evs:
        if e.get("route_mirrored"):
            continue
        val = str(e.get("value") or "")
        rule = str(e.get("rule") or "")
        if val == "undetermined":
            why = str(e.get("evidence") or "")
            if why and why not in und_reasons and len(und_reasons) < 40:
                und_reasons.append(why)

            

            if rule.startswith("led") and why:
                und_led.append({"rule": rule, "pos": rule.split(":", 1)[-1], "why": why,
                                "field": e.get("field") or ""})
            continue
        base = {"item_no": e.get("item_no") or "", "field": e.get("field") or "",
                "value": val, "conf": round(float(e.get("confidence") or 0.0), 3),
                "meaning": str(e.get("check_item") or ""), "why": str(e.get("evidence") or ""),
                "route": e.get("route") or "", "part": e.get("part") or part,
                "rule": rule, "category": e.get("category") or ""}
        if rule.startswith("led"):
            ref = rule.split(":", 1)[-1]                 
            pid, sep, istr = ref.partition("#")
            if not sep:                                  
                istr = "*"
            spec = parts_tbl.get(pid) or {}
            lamps = spec.get("lamps") or []
            name, expect, color, pos = "", "any", "", "整排"
            if istr == "*":
                name = spec.get("name") or pid
                expect = "正常"
                pos = "整排"
            elif istr.isdecimal() and int(istr) < len(lamps):
                i = int(istr)
                name = lamps[i].get("name") or ""
                expect = (lamps[i].get("expect") or "any")
                color = lamps[i].get("color") or ""
                pos = "第 %d/%d 位" % (i + 1, len(lamps))
            else:
                name = spec.get("name") or pid
                pos = "灯位 %s" % (istr or "?")
            mt = _led_match(val, expect)
            base.update({
                "kind": "led", "pos": pos, "name": name or (e.get("category") or "指示灯"),
                "color": color, "state": val,
                "state_text": ("亮" if val == "on" else ("灭" if val == "off" else val)),
                "expect_text": _EXPECT_TEXT.get(expect, expect), "match": mt,
            })
        else:
            ok = (val == "ok")
            base.update({
                "kind": "screen", "pos": "屏幕", "name": SCREEN_TEXT.get(val, val),
                "color": "", "state": val, "state_text": SCREEN_TEXT.get(val, val),
                "expect_text": "应正常", "match": bool(ok) if val else None,
            })
        rows.append(base)

    

    _seen, _dedup = set(), []
    for _r in rows:
        _k = (_r.get("kind"), _r.get("rule") or "", _r.get("pos") or "", _r.get("state") or "")
        if _k in _seen:
            continue
        _seen.add(_k)
        _dedup.append(_r)
    rows = _dedup

    rows.sort(key=lambda r: 0 if r.get("kind") == "led" else 1)
    return rows, und_reasons, und_led

def _conclusion(rows, part_info, vision_ok, error="", und_led=None):
    """本步结论：✅正常 / ❌异常 / ⚠未判定（带原因）。

    ★ 2026-10-29：只要有"灯类未判定"（弱灯/缺标定/斑块不确定），就**不能报正常**——
      宁可「未判定」也不能出现"结论正常、逐灯行却缺/灭"的自相矛盾（现场 Z14/Z15 实测）。
      明确异常行（match=False）仍然优先判异常（异常是确定信息）。
    """
    und_led = list(und_led or [])
    if not vision_ok:
        return {"state": "unknown", "text": "未判定", "why": error or "判定链未跑通",
                "n_bad": 0, "n_ok": 0}
    bad = [r for r in rows if r.get("match") is False]
    ok = [r for r in rows if r.get("match") is True]
    if bad:
        head = bad[0]
        text = "异常：%s%s" % (head.get("name") or head.get("pos") or "?",
                              ("" if len(bad) == 1 else " 等 %d 项" % len(bad)))
        return {"state": "bad", "text": text,
                "why": "；".join("%s %s（%s）" % (r.get("pos"), r.get("name"),
                                                r.get("state_text")) for r in bad[:3]),
                "n_bad": len(bad), "n_ok": len(ok)}
    if und_led:
        why0 = str(und_led[0].get("why") or "")
        return {"state": "unknown", "text": "未判定（部分灯位判不准）",
                "why": "%d 个灯位未判定：%s" % (len(und_led), why0[:200]),
                "n_bad": 0, "n_ok": len(ok), "n_undet_led": len(und_led)}
    if ok:
        why = "；".join("%s %s=%s" % (r.get("pos"), r.get("name"), r.get("state_text"))
                        for r in ok[:4])
        if part_info.get("need_confirm"):
            why = "部位待确认，结果仅供参考；" + why
        return {"state": "ok", "text": "正常（%d 项符合）" % len(ok), "why": why,
                "n_bad": 0, "n_ok": len(ok)}
    return {"state": "unknown", "text": "未判定",
            "why": "本张照片没有一条判据能给出确定结论（见下方未判定原因）",
            "n_bad": 0, "n_ok": 0}

def _candidates(pack, rows, part=""):
    """候选故障：优先 fault_grader（吃 evidence/v1），失败则退化为判据库 fault_refs。"""
    out = []
    fg = _mod("fault_grader")
    ev = list(pack.get("evidence") or [])
    if fg is not None and ev:
        try:
            payload = {"schema": "evidence/v1", "producer": "board_infer",
                       "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "n": len(ev), "evidence": ev}
            g = fg.FaultGrader().grade(payload)
            for c in (g.get("candidates") or [])[:3]:
                if isinstance(c, dict):
                    bits = [str(c.get(k) or "") for k in ("cabinet", "sub_unit", "module")]
                    label = "/".join(b for b in bits if b) or str(c.get("summary") or "")
                    pct = c.get("confidence")
                    if label:
                        out.append("候选故障：%s%s" % (label,
                                                      ("（%.0f%%）" % (float(pct) * 100))
                                                      if isinstance(pct, (int, float)) else ""))
            if not out and g.get("summary"):
                out.append("分级：%s（%s）" % (g.get("verdict_cn") or g.get("verdict") or "",
                                              g.get("summary")))
        except Exception as e:                                     
            _log("fault_grader 分级失败（降级为判据库引用）: %s" % e)
            out = []
    if not out:

        try:
            for r in rows:
                if r.get("match") is False:
                    out.append("候选故障：%s（%s 不符合）" % (r.get("meaning") or r.get("name"),
                                                             r.get("pos")))
                if len(out) >= 3:
                    break
        except Exception:                                          
            pass
    return out

def _evidence_items(rows, part_info, part_used=""):
    """逐条证据（每个灯/屏一条），供 ui_kiosk 合并进流程证据。"""
    out = []
    for r in rows[:MAX_EV_ITEM]:
        out.append({
            "part": part_used or r.get("part") or "",
            "route": r.get("route") or "",
            "modality": "vision",
            "field": r.get("field") or "(vision)_lamp",
            "value": r.get("state") or "undetermined",
            "confidence": r.get("conf") or 0.0,
            "note": "%s %s：%s" % (r.get("pos"), r.get("name"), r.get("why") or ""),
            "evidence": "%s %s %s（%s）" % (r.get("pos"), r.get("name"),
                                           r.get("state_text"), r.get("meaning") or ""),
            "item_id": "camera:%s" % (r.get("rule") or r.get("item_no") or ""),
            "check_item": r.get("meaning") or "",
            "rule": r.get("rule") or "",
            "position": r.get("pos") or "",
            "expect": r.get("expect_text") or "",
            "match": r.get("match"),
            "kind": r.get("kind") or "",
            "source": "board_infer.vision",
        })
    return out

def infer(frame, part_hint="", flow_no=None, route="", prior_part=""):
    """拍照 -> 部位识别 + 摄像头判定 -> 结果页数据。**绝不抛。**"""
    t0 = time.time()
    if not bootstrap():
        out = _empty("engine 不可用：%s" % ("；".join(_S["errors"][:2]) or "未知"), part_hint)
        out["elapsed_ms"] = int((time.time() - t0) * 1000)
        return out
    if frame is None:
        return _empty("没有画面帧（取流失败）", part_hint)

    t1 = time.time()
    hint = kb_part(part_hint)
    conflict = ""
    if hint:
        p = _part_info_from_hint(hint, "由标记/步骤/人工指定（判灯不再跑模板 NCC 识别）")

        
        if _is_legacy_ii(part_hint):
            p["legacy_part"] = str(part_hint)
            p["route"] = "II"
            p["route_locked"] = True
        part_used = hint
        src = "标记/步骤"
    else:
        p = recognize_part(frame, part_hint="", flow_no=flow_no,
                           route=route, prior_part=prior_part)
        rec_part = kb_part(p.get("part") or "")

        rec_ok = bool(rec_part) and not bool(p.get("need_confirm"))
        part_used = rec_part if rec_ok else ""
        src = "识别" if rec_ok else ""
        if rec_part and not rec_ok:
            _log("① 识别不足以下结论（part=%s conf=%.2f need_confirm=True）→ 判灯改用未判定"
                 % (rec_part, float(p.get("confidence") or 0.0)))
    t_part = int((time.time() - t1) * 1000)
    p.update({"part_used": part_used, "part_source": src, "hint_conflict": conflict})
    p["elapsed_ms"] = t_part
    _log("① 部位: hint=%s 识别=%s(%s) conf=%.2f → 判定用=%s 来源=%s %dms"
         % (hint or "-", p.get("part") or "-", p.get("decision") or "-",
            float(p.get("confidence") or 0.0), part_used or "-", src or "-", t_part))

    t2 = time.time()
    v = run_vision(frame, part=part_used)
    t_vis = int((time.time() - t2) * 1000)
    pack = v.get("pack") or {}
    rows, und_reasons, und_led = rows_from_evidence(pack, part=part_used)
    _log("② 判定: ok=%s rows=%d 未判定原因=%d 灯未判定=%d %dms"
         % (v.get("ok"), len(rows), len(und_reasons), len(und_led), t_vis))

    concl = _conclusion(rows, p, bool(v.get("ok")), v.get("error") or "", und_led=und_led)
    cands = _candidates(pack, rows, part=part_used)
    ev_items = _evidence_items(rows, p, part_used)

    out = {
        "ok": bool(v.get("ok")),
        "error": v.get("error") or "",
        "elapsed_ms": int((time.time() - t0) * 1000),
        "t_part_ms": t_part, "t_vision_ms": t_vis,
        "deps": dict(_S["deps"]),
        "engine": _S["engine"],
        "part": p,
        "vision": {k: pack.get(k) for k in
                   ("photo", "ts", "scene", "screen", "lamp_rows",
                    "n_items", "n_decided", "n_undetermined", "debug")},
        "vision_evidence": list(pack.get("evidence") or []),
        "rows": rows,
        "undetermined": {"n": int(pack.get("n_undetermined") or 0),
                         "reasons": und_reasons[:MAX_UND_REASONS],
                         "n_led": len(und_led),
                         "n_reasons_total": len(und_reasons)},
        "conclusion": concl,
        "candidates": cands,
        "evidence_items": ev_items,
    }
    _log("③ 结论: %s｜%s（共 %dms）" % (concl["text"], concl["why"][:60], out["elapsed_ms"]))
    return out

class InferJob:
    """后台线程跑 ``infer()``：板端单张约 15~25s（模板 NCC + 标记检测），
    放主线程会把 UI 冻住，所以一律走这里，结果页显示"判定中…"。

    用法::

        job = start_job(frame, part_hint="z11")
        if job.done:   r = job.result
        else:          "判定中… 已 %.1fs" % job.elapsed()
    """

    def __init__(self, frame, part_hint="", flow_no=None, route="", prior_part=""):
        self.frame = frame.copy() if frame is not None else None
        self.part_hint = part_hint
        self.flow_no = flow_no
        self.route = route
        self.prior_part = prior_part
        self.t0 = time.time()
        self.t_end = 0.0
        self.done = False
        self.result = None
        self.error = ""
        self._th = None

    def start(self):
        self._th = threading.Thread(target=self._run, name="board_infer", daemon=True)
        self._th.start()
        _log("判定线程启动 part_hint=%s" % (self.part_hint or "-"))
        return self

    def _run(self):
        try:
            self.result = infer(self.frame, part_hint=self.part_hint,
                                flow_no=self.flow_no, route=self.route,
                                prior_part=self.prior_part)
        except Exception as e:                                     
            self.error = "%s: %s" % (type(e).__name__, e)
            _log("判定线程异常: %s" % self.error)
            traceback.print_exc()
            self.result = _empty(self.error, self.part_hint)
        finally:
            self.t_end = time.time()
            self.done = True
            try:
                _log("判定线程结束 %.1fs ok=%s"
                     % (self.t_end - self.t0, (self.result or {}).get("ok")))
            except Exception:                                      
                pass

    def elapsed(self):
        return (self.t_end or time.time()) - self.t0

def start_job(frame, part_hint="", flow_no=None, route="", prior_part=""):
    """起一个后台判定任务（永不抛）。"""
    return InferJob(frame, part_hint=part_hint, flow_no=flow_no, route=route,
                    prior_part=prior_part).start()

def short_status_line():
    """一行日志摘要（启动时打一次，便于事后核查降级链）。"""
    s = status()
    d = s.get("deps") or {}
    return ("engine=%s ready=%s cv2=%s numpy=%s rapidocr=%s | %s"
            % (os.path.basename(s.get("engine") or "-"), s.get("ready"),
               s.get("cv2") or "无", s.get("numpy") or "无", s.get("rapidocr") or "无",
               " ".join("%s:%s" % (k, "ok" if v.get("ok") else "FAIL")
                        for k, v in d.items())))
