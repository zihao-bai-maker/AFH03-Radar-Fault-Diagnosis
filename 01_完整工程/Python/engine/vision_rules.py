#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vision_rules.py —— 摄像头类判定引擎（61 项，判据库 `method=摄像头拍摄`）

定位
====
本文件只做**图像证据生成**：一张现场照片 → 一组统一证据 JSON。
它不碰板子、不碰相机、不改任何既有模块（复用模块只 import，不修改）。

三条现象链（判据库 `category` 列）
==============================
1. 指示灯（38 项）：输出 ``on`` / ``off``；颜色 R/G/Y/W 只作为证据，不参与 on/off。
2. 显示画面（18 项）：``black_screen`` / ``yellow_screen`` / ``garbled``（花屏）/
   ``no_echo``（无回波）/ ``no_scan``（不扫描）/ ``ok``。
3. 微表区（4 项）：``天线方向``（正常/左/右/错误）、``自检状态``（正常/30/40/错误）。

铁律
====
**宁可不判，绝不误判。** 任何门控（清晰度、面积、圆度、行间距、置信度、
ROI 未标定、参考模板缺字……）不通过 ⇒ ``value="undetermined"``，并在
``evidence``/``reason`` 里写清"差在哪一步"，绝不猜。

统一证据 JSON（多模态核心，可直接喂给融合层）
==========================================
.. code-block:: json

    {"part": "z11", "route": "I", "modality": "vision",
     "field": "(led_indicator)_route_one_z11_work", "value": "off",
     "confidence": 0.9, "evidence": "ROI 亮度 12 < 阈值 40",
     "ts": "2026-10-18T08:36:46+08:00"}

> z 编号相同即同一元件；**I/II 路是两个不同位置、同一 z 编号**。用户只拍一张照片
> ⇒ 同一套规则同时套用到 I 和 II 路（证据里带 ``route_mirrored: true``，
> 明确标注"这一条是把同一张照片的结论镜像到另一路"，不伪造第二张照片）。

复用（只 import 不改）
====================
* ``soc_vision.led_rules``      —— ``LampState`` / ``TRISTATE`` / ``VERDICT_*`` 三态语义
* ``soc_vision.led_panel``      —— ``measure_at``（纯 numpy 环带测量，无 cv2 也能跑）/ ``LampCand``
* ``config/led_rules.json``     —— 部件→灯序/颜色/期望（数据驱动，不改它）
* ``soc_vision.screen_read_v2`` —— 微表区汉字屏读数（缺参考模板 ⇒ 未判定）
* ``soc_vision.seg7``           —— 保留接口（数码管示数不属于本 61 项，未启用判定路径）

运行
====
::

    python vision_rules.py --catalog                    # 打印 61 项目录
    python vision_rules.py --gen-bindings               # 重新生成 vision_bindings.json
    python vision_rules.py --image a.jpg --part z11     # 单张 → 证据 JSON
    python vision_rules.py --dir photos --part z11 --out report.json
    python vision_rules.py --dir photos --manifest photos.csv --out report.json
    python vision_rules.py --selftest                   # 内置自检（不需要外部图片）

依赖：Python 3.11+、numpy、Pillow（板子上都有）。opencv **不是必需**：
检测主路径是纯 numpy，cv2 只在 ``led_panel.detect_candidates`` 这类可选加速
里被用到，缺失时自动走 numpy 路径（证据里 ``backend`` 会写明）。
"""
from __future__ import annotations

import argparse
import csv
import glob
import itertools
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field as dc_field, asdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG_CSV = os.path.join(HERE, "判据库_SOP.csv")
FAULT_CSV = os.path.join(HERE, "判据库_故障.csv")
BINDINGS_JSON = os.path.join(HERE, "vision_bindings.json")
VER_ENGINE = "vision_rules/1.0"

SOP_CANDIDATES = [
    os.path.join(HERE, "判据库_SOP.csv"),
    os.path.join(os.path.dirname(HERE), "判据库_SOP.csv"),
    "/home/rock/radar_criteria/判据库_SOP.csv",
    r"D:\xuexishengshou\雷达判据\判据库_SOP.csv",
]
FAULT_CANDIDATES = [
    os.path.join(HERE, "判据库_故障.csv"),
    os.path.join(os.path.dirname(HERE), "判据库_故障.csv"),
    "/home/rock/radar_criteria/判据库_故障.csv",
    r"D:\xuexishengshou\雷达判据\判据库_故障.csv",
]
SOC_CANDIDATES = [
    os.environ.get("AFH03_SOC_VISION", ""),
    "/home/rock/afh03_board_setup/soc_vision",
    r"D:\xuexishengshou\afh03_board_setup\soc_vision",
]

def _add_soc_path() -> str:
    """把 afh03_board_setup 加到 sys.path（`soc_vision` 是包，led_panel 用包内相对导入）。"""
    for c in SOC_CANDIDATES:
        if not c:
            continue
        pkg_root = os.path.dirname(os.path.abspath(c))
        if os.path.isfile(os.path.join(c, "led_rules.py")) and pkg_root not in sys.path:
            sys.path.insert(0, pkg_root)
            return pkg_root
    return ""

SOC_ROOT = _add_soc_path()

LR = None          
LP = None          
SRV2 = None        
SEG7 = None        
IMPORT_NOTES: List[str] = []
try:                                                        
    from soc_vision import led_rules as LR                  
except Exception as exc:                                    
    IMPORT_NOTES.append("led_rules 不可用: %s" % exc)
try:                                                        
    from soc_vision import led_panel as LP                  
except Exception as exc:                                    
    IMPORT_NOTES.append("led_panel 不可用: %s" % exc)
try:                                                        
    from soc_vision import screen_read_v2 as SRV2           
except Exception as exc:                                    
    IMPORT_NOTES.append("screen_read_v2 不可用: %s" % exc)
try:                                                        
    from soc_vision import seg7 as SEG7                     
except Exception as exc:                                    
    IMPORT_NOTES.append("seg7 不可用: %s" % exc)

try:                                                        
    import cv2                                              
except Exception:                                           
    cv2 = None

LB = None          
BLOB_NOTES: List[str] = []
try:                                                        
    import lamp_blob as LB                                  
except Exception as exc:                                    
    BLOB_NOTES.append("lamp_blob 不可用: %s" % exc)
    IMPORT_NOTES.append("lamp_blob 不可用: %s（灯位自动定位不可用，退回标定坐标）" % exc)

TH = {

    "work_long": 1600,
    "cc_long": 800,

    
    "grad_blur": 1.5,
    "grad_soft": 2.2,          

    "lamp_delta_on": 22.0,     
    "lamp_delta_off": 12.0,    
    "lamp_v_min": 105.0,
    "lamp_s_min": 55.0,
    "lamp_white_v": 245.0,     
    "lamp_fill_min": 0.42,     
    "lamp_aspect_lo": 0.45,
    "lamp_aspect_hi": 2.2,
    "lamp_r_lo_frac": 0.0035,  
    "lamp_r_hi_frac": 0.040,   

    

    "dark_delta": -14.0,       
    "dark_v_max": 118.0,       
    "dark_center_v_max": 112.0,
    "dark_ring_min": 85.0,     
    "dark_ring_contrast": 10.0,   
    "dark_fill_min": 0.42,
    "dark_specular_lit_max": 0.18,  

    "row_y_tol": 1.6,          
    "row_gap_cv": 0.45,        
    "row_min_slots": 2,

    "screen_work_long": 480,
    "screen_min_area_frac": 0.055,   
    "screen_aspect_lo": 0.55,
    "screen_aspect_hi": 3.4,
    "screen_fill_solid": 0.65,       
    "screen_fill_grid": 0.18,        
    "grid_green_frac_min": 0.12,     

    "black_mean_v": 26.0,      
    "black_dark_frac": 0.82,   
    "black_bright_frac": 0.004,
    "blown_v": 0.80,           
    "blown_frac": 0.45,        
    "yellow_tint_frac": 0.25,  
    "yellow_mean_v": 120.0,
    "hf_garbled": 0.055,       
    "edge_garbled": 0.11,      
    "line_frac": 0.020,        
    "screen_green_min": 0.04,  
    "scan_texture_min": 0.010, 
    "echo_bright_min": 0.0035, 
    "echo_weak_min": 0.0012,

    "conf_min": 0.55,          
    "conf_min_soft": 0.60,     
}

COLOR_NAME = {"R": "红", "G": "绿", "Y": "黄", "W": "白", "B": "蓝", "?": "未知"}
TS_FMT = "%Y-%m-%dT%H:%M:%S%z"

SLUG = [
    ("空调电源", "aircon_power"), ("空调", "aircon"), ("市电电源", "mains_power"),
    ("市电", "mains"), ("相序", "phase_sequence"), ("工频电源", "gongpin_power"),
    ("工频", "gongpin"), ("保险丝", "fuse"), ("Modem", "modem"),
    ("发射机工作", "transmitter_work"), ("发射通", "tx_on"), ("发射断", "tx_off"),
    ("发射机状态", "transmitter_state"), ("本路", "local_route"), ("工作", "work"),
    ("故障", "fault"), ("自检", "self_test"), ("天线方向", "antenna_direction"),
    ("天线启动", "antenna_start"), ("天线换向", "antenna_reverse"),
    ("时钟板件", "clock_board"), ("MY板件", "my_board"), ("MTD板件", "mtd_board"),
    ("显示画面", "display_screen"), ("航向回波", "course_echo"),
    ("下滑回波", "glide_echo"), ("航向噪声", "course_noise"),
    ("下滑噪声", "glide_noise"), ("航向画面", "course_scan"), ("下滑画面", "glide_scan"),
    ("理想航向线", "course_line"), ("理想下滑线", "glide_line"),
    ("航向指向", "course_pointer"), ("下滑指向", "glide_pointer"),
    ("控制", "control"), ("电源", "power"),
]
ROUTE_TOKENS = [
    ("（II）路", "II"), ("(II)路", "II"), ("（II）", "II"), ("(II)", "II"),
    ("（I）路", "I"), ("(I)路", "I"), ("（I）", "I"), ("(I)", "I"),
    ("路-Z11", "I"),
]
DISPLAY_TOKENS = [("(操显)", "operator_display"), ("（操显）", "operator_display"),
                  ("(领显)", "leader_display"), ("（领显）", "leader_display")]

def _slugify(text: str) -> str:
    hits = [(text.find(k), v) for k, v in SLUG if k in text]
    if not hits:
        return ""
    hits.sort()
    out: List[str] = []
    for _, v in hits:
        if any(v in o or o in v for o in out):      
            if len(v) > len(out[-1] if out else ""):
                out = [o for o in out if o not in v]
                out.append(v)
            continue
        out.append(v)
    return "_".join(out)

def _route_of(text: str, flow_no: str) -> str:
    for tok, r in ROUTE_TOKENS:
        if tok in text:
            return r
    f = (flow_no or "").upper().replace("（", "(").replace("）", ")")
    for tok, r in (("-II", "II"), ("II)", "II"), ("-I", "I"), ("I)", "I")):
        if tok in f:
            return r
    return ""

def _part_of(text: str) -> str:
    """从条目文本抽 z 编号（z11/z31/z18/z20/z14/z15/z16/z12），统一小写 zNN。"""
    import re
    m = re.findall(r"[Zz]\s*(\d{1,2})", text)
    if not m:
        return ""
    return "z%d" % int(m[0])

@dataclass
class Item:
    """一条摄像头类判据。"""
    key: str                 
    flow_no: str
    sub_no: str
    item: str                
    category: str            
    subject: str
    method: str
    fault_refs: List[str]
    part: str = ""
    route: str = ""
    display: str = ""        
    field: str = ""          
    expect: str = ""         
    binding: str = ""        
    binding_ref: str = ""    
    field_src: str = ""      
    fault_values: List[str] = dc_field(default_factory=list)   

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

def _read_csv(path: str) -> List[Dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def _find_path(cands: Sequence[str]) -> str:
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return ""

def load_fault_db(path: str = "") -> Dict[str, Dict[str, str]]:
    """故障库：feature_id → 行（拿 field / abnormal_value / phenomenon 原文）。"""
    p = path or _find_path(FAULT_CANDIDATES)
    if not p:
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for r in _read_csv(p):
        fid = (r.get("feature_id") or "").strip()
        if fid:
            out[fid] = r
    return out

def load_catalog(sop_path: str = "", fault_path: str = "") -> List[Item]:
    """读判据库 SOP，筛 `method == 摄像头拍摄`，补齐 part/route/field/binding。"""
    p = sop_path or _find_path(SOP_CANDIDATES)
    if not p:
        raise FileNotFoundError("找不到 判据库_SOP.csv（候选：%s）" % SOP_CANDIDATES)
    rows = [r for r in _read_csv(p) if (r.get("method") or "").strip() == "摄像头拍摄"]
    fault_db = load_fault_db(fault_path)
    items: List[Item] = []
    seen: Dict[str, int] = {}
    for r in rows:
        item_txt = (r.get("check_item") or "").strip()
        subj = (r.get("subject") or "").strip()
        cat = (r.get("category") or "").strip()
        flow = (r.get("flow_no") or "").strip()
        sub = (r.get("sub_no") or "").strip()
        refs = [x.strip() for x in (r.get("fault_refs") or "").replace("|", ";").split(";") if x.strip()]
        text = " ".join([item_txt, (r.get("flow_name") or ""), subj])
        key = "%s.%s" % (flow, sub)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:                     
            key = "%s~%d" % (key, seen[key])
        it = Item(key=key, flow_no=flow, sub_no=sub, item=item_txt,
                  category=cat, subject=subj, method="摄像头拍摄", fault_refs=refs,
                  part=_part_of(item_txt + " " + subj), route=_route_of(text, flow),
                  display=next((v for k, v in DISPLAY_TOKENS if k in item_txt), ""))
        _bind_item(it, fault_db)
        items.append(it)

    

    
    items.extend(_extra_panel_items({it.key for it in items}))
    return items

def _extra_panel_items(existing_keys: Iterable[str]) -> List[Item]:
    """把 vision_bindings.json 里 ``extra.*`` 的**五灯面板灯位**并入目录（只读，不改那张表）。

    只补 ``binding_ref`` 属于 Z11/TX_STATE 面板的灯位；其它 extra（Z12 保险丝、Z14/Z15
    复位等）保持原样不动 —— 本次只修 Z11/TX_STATE。
    """
    if not os.path.isfile(BINDINGS_JSON):
        return []
    try:
        with open(BINDINGS_JSON, encoding="utf-8") as f:
            doc = json.load(f)
    except Exception as exc:                                       
        _warn("读 vision_bindings.json 失败（%s: %s）⇒ Z11「工作/发射断」两个灯位不补，"
              "整面板只能判到 3 颗" % (type(exc).__name__, exc))
        return []
    have = set(existing_keys or ())
    out: List[Item] = []
    for r in doc.get("items") or []:
        if not isinstance(r, dict):
            continue
        key = str(r.get("key") or "")
        if not key.startswith("extra.") or key in have:
            continue
        ref = str(r.get("binding_ref") or "")
        if ref.partition("#")[0] not in _TX5_PANEL_PARTS:
            continue
        out.append(Item(
            key=key, flow_no=str(r.get("flow_no") or ""), sub_no=str(r.get("sub_no") or ""),
            item=str(r.get("item") or ""), category=str(r.get("category") or "指示灯"),
            subject=str(r.get("subject") or r.get("item") or ""), method="摄像头拍摄",
            fault_refs=list(r.get("fault_refs") or []), part=str(r.get("part") or "z11"),
            route=str(r.get("route") or ""), display=str(r.get("display") or ""),
            field=str(r.get("field") or ""), expect=str(r.get("expect") or ""),
            binding=str(r.get("binding") or "led"), binding_ref=ref,
            field_src="vision_bindings_extra"))
    return out

def _bind_item(it: Item, fault_db: Dict[str, Dict[str, str]]):
    """给条目定 field / binding。**这是唯一一张"判据 → 图像证据"的映射表**，
    改判定范围只改这里（README_vision.md 有逐条说明）。"""
    low = it.item
    it.part = _infer_part(it)          

    fld = ""
    for ref in it.fault_refs:
        row = fault_db.get(ref)
        if not row:
            continue
        f = (row.get("field") or "").strip()
        if f:
            fld = f
            it.field_src = "fault_db"
            if row.get("abnormal_value"):
                it.fault_values = [row["abnormal_value"]]
            break

    image_only = any(k in low for k in ("理想航向线", "理想下滑线", "回波", "噪声", "扫描", "显示画面"))
    if "随动" in low:                 
        it.binding = "dynamic"
        it.binding_ref = "course_pointer" if "航向" in low else "glide_pointer"
        it.expect = "ok"
    elif image_only and "指示灯" in it.category:

        
        it.binding = "screen"
        it.binding_ref = "course_line" if "航向" in low else "glide_line"
        it.expect = "ok"
    elif "指示灯" in it.category or "指示灯" in low:
        ref = _led_bind_by_text(low, it)
        if ref:
            it.binding, it.binding_ref = "led", ref
            it.expect = _expect_of(ref)
        else:
            it.binding, it.binding_ref = "led_unbound", ""
            it.expect = "on"
    elif "微表" in it.category or "天线方向" in low or "自检" in low:
        it.binding = "meter"
        it.binding_ref = "meter_antenna_direction" if "天线方向" in low else "meter_self_test"
        it.expect = "正常"
    else:
        it.binding = "screen"
        for kw, ref in (("显示画面", "display_screen"), ("回波", "echo"), ("噪声", "noise"),
                        ("扫描", "scan"), ("理想航向线", "course_line"), ("理想下滑线", "glide_line")):
            if kw in low:
                it.binding_ref = ref
                break
        if it.binding_ref in ("echo", "noise", "scan"):
            it.binding_ref = ("course_" if "航向" in low or "下滑" not in low else "glide_") + it.binding_ref
        it.expect = "ok"
        if not it.binding_ref:
            it.binding = "none"

    if not fld:
        row = _match_fault_by_text(it.item, it.binding, fault_db)
        if row:
            fld = row["field"].strip()
            it.field_src = "fault_db:step_name"
            if row.get("abnormal_value"):
                it.fault_values = [row["abnormal_value"]]

    if not fld:
        it.field_src = "synth"
        if it.binding in ("led", "led_unbound"):
            slug = _slugify(it.subject + " " + low) or ("item_" + it.key.replace(".", "_").replace("~", "_"))
            fld = "(led_indicator)_%s_%s" % (it.part or "unknown", slug)
        elif it.binding == "meter":
            disp = it.display or "operator_display"
            fld = "(image)(%s)_meter_%s" % (disp, it.binding_ref.replace("meter_", ""))
        else:
            disp = it.display or "operator_display"
            fld = "(image)(%s)_%s" % (disp, it.binding_ref or "unknown")

    if it.route == "II" and "route_one" in fld:
        it.field = fld.replace("route_one", "route_two")
        it.field_src += "+route_two"
    else:
        it.field = fld

    it.part = _infer_part(it)

def _match_fault_by_text(item_text: str, binding: str, fault_db: Dict[str, Dict[str, str]]) -> Dict[str, str]:
    """按 step_name 精确/包含匹配故障库行，且要求 field 前缀与现象链一致。

    **不能无脑用**：故障库里同一个 step 可能登记的是"人工动作"类字段（`(manual_action)_...`），
    套到指示灯条目上就成了错口径。所以只接受 `(led_indicator)` / `(image)` 两种前缀。
    """
    want = "(led_indicator)" if binding in ("led", "led_unbound") else "(image)"
    t = (item_text or "").strip()
    if not t:
        return {}
    best: Dict[str, str] = {}
    for row in fault_db.values():
        f = (row.get("field") or "").strip()
        if not f.startswith(want):
            continue
        sn = (row.get("step_name") or "").strip()
        if not sn:
            continue
        if sn == t:
            return row
        if (sn in t or t in sn) and not best:
            best = row
    return best

_LED_TEXT_RULES: List[Tuple[Tuple[str, ...], str]] = [

    (("空调",), "PS_KONG#0"),
    (("市电",), "PS_KONG#1"),
    (("Z31", "控制", "指示灯"), "PS_KONG#2"),      
    (("相序",), "PD_BOARD#0"),
    (("工频电源",), "PS_GONGPIN#0"),
    (("本路",), "TX_STATE#1"),
    (("发射通",), "TX_STATE#2"),
    (("故障", "Z11"), "TX_STATE#4"),
    (("天线启动",), "ANT_START#0"),
    (("发射机工作", "[I]"), "TX_CTRL#0"),
    (("发射机工作", "[II]"), "TX_CTRL#1"),
    (("天线方向", "方向左"), "ANT_DIR#*"),
    (("天线换向", "到位"), "ANT_DIR#*"),            

    (("Z12", "保险丝"), "Z12_PWR#0"),
    (("Z12", "电源"), "Z12_PWR#1"),

    

    (("Z14", "保险丝"), "Z14_PANEL#2"),
    (("Z14", "电源"), "Z14_PANEL#1"),
    (("Z14", "复位"), "Z14_PANEL#0"),

    (("Z15", "2A"), "Z15_PANEL#0"),
    (("Z15", "Modem"), "Z15_PANEL#1"),
    (("Z15", "复位"), "Z15_PANEL#2"),
    (("Z15", "电源"), "Z15_PANEL#3"),
]

_SCREEN_PART = [
    ("noise", "z14"),
    ("meter_antenna_direction", "z18"),
    ("meter_self_test", "z16"),
    ("display_screen", "z11"), ("echo", "z11"), ("scan", "z11"),
    ("line", "z11"), ("pointer", "z11"),
]

def _infer_part(it: Item) -> str:
    """给没有 z 编号的条目补 `part`（契约要求非空；依据写在 README §3 与字段来源注释里）。"""
    if it.part:
        return it.part
    ref = it.binding_ref or ""
    for kw, p in _SCREEN_PART:
        if kw in ref:
            return p
    low = it.item
    if "天线换向" in low or "天线方向" in low:
        return "z18"
    if "时钟板件" in low or "MY板件" in low or "MTD板件" in low:
        return "z14"
    if "噪声" in low:
        return "z14"
    if any(k in low for k in ("理想航向线", "理想下滑线", "指向亮线", "显示画面", "回波", "扫描")):
        return "z11"
    return ""

def _led_bind_by_text(low: str, it: Item) -> str:
    for kws, ref in _LED_TEXT_RULES:
        if all(k in low for k in kws):
            return ref
    return ""

def _expect_of(ref: str) -> str:
    """从复用的部件规则表取"这颗灯正常应该是什么状态"（数据驱动，不硬编码）。"""
    pid, _, idx_s = (ref or "").partition("#")
    spec = parts_table().get(pid)
    if not spec:
        return ""
    if idx_s == "*":
        return "正常"                      
    try:
        idx = int(idx_s)
    except ValueError:
        return ""
    lamps = spec.get("lamps") or []
    return str(lamps[idx].get("expect") or "") if 0 <= idx < len(lamps) else ""

SCREEN_CHECKS = {
    "display_screen": ("display_screen", ("ok", "black_screen", "yellow_screen", "garbled", "undetermined")),
    "course_echo": ("course_echo", ("ok", "no", "weak", "undetermined")),
    "glide_echo": ("glide_echo", ("ok", "no", "weak", "undetermined")),
    "course_noise": ("course_noise", ("ok", "no_noise", "undetermined")),
    "glide_noise": ("glide_noise", ("ok", "no_noise", "undetermined")),
    "course_scan": ("course_scan", ("ok", "no", "undetermined")),
    "glide_scan": ("glide_scan", ("ok", "no", "undetermined")),
    "course_line": ("course_line", ("ok", "abnormal", "undetermined")),
    "glide_line": ("glide_line", ("ok", "abnormal", "undetermined")),
    "course_pointer": ("course_pointer", ("ok", "no_move", "undetermined")),
    "glide_pointer": ("glide_pointer", ("ok", "no_move", "undetermined")),
}

def load_bgr(path: str, work_long: int = 0) -> Tuple[np.ndarray, int]:
    """读图 → BGR uint8（EXIF 已转正），可选缩放到长边 work_long。返回 (bgr, 缩放后长边)。"""
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    rgb = np.asarray(im)
    bgr = rgb[:, :, ::-1].copy()
    return _fit_long(bgr, work_long or TH["work_long"])

def _fit_long(bgr: np.ndarray, long_side: int) -> Tuple[np.ndarray, int]:
    h, w = bgr.shape[:2]
    long_now = max(h, w)
    if long_side <= 0 or long_now <= long_side:
        return bgr, long_now
    k = float(long_side) / long_now
    im = Image.fromarray(bgr[:, :, ::-1]).resize((max(1, int(round(w * k))), max(1, int(round(h * k)))),
                                                 Image.BILINEAR)
    return np.asarray(im)[:, :, ::-1].copy(), long_side

def bgr_to_hsv(bgr: np.ndarray) -> np.ndarray:
    """BGR uint8 → HSV 浮点 (H∈[0,360), S∈[0,1], V∈[0,1])。opencv 缺失时用这条路。"""
    a = bgr.astype(np.float32) / 255.0
    b, g, r = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    mx = np.max(a, axis=2)
    mn = np.min(a, axis=2)
    d = mx - mn
    h = np.zeros_like(mx)
    nz = d > 1e-6

    rm = nz & (mx == r)
    gm = nz & (mx == g) & ~rm
    bm = nz & (mx == b) & ~rm & ~gm
    with np.errstate(invalid="ignore", divide="ignore"):
        h = np.where(rm, 60.0 * (((g - b) / np.where(d == 0, 1, d)) % 6.0), h)
        h = np.where(gm, 60.0 * (((b - r) / np.where(d == 0, 1, d)) + 2.0), h)
        h = np.where(bm, 60.0 * (((r - g) / np.where(d == 0, 1, d)) + 4.0), h)
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0.0)
    return np.dstack([h % 360.0, s, mx]).astype(np.float32)

def integral(a: np.ndarray) -> np.ndarray:
    """积分图（带 0 行 0 列）。"""
    ii = np.zeros((a.shape[0] + 1, a.shape[1] + 1), dtype=np.float64)
    ii[1:, 1:] = np.cumsum(np.cumsum(a.astype(np.float64), axis=0), axis=1)
    return ii

def box_mean(a: np.ndarray, k: int) -> np.ndarray:
    """k×k 均值滤波（积分图实现，边界用 clip 的归一化面积）。"""
    k = int(k) | 1
    r = k // 2
    ii = integral(a)
    h, w = a.shape[:2]
    ys = np.arange(h)
    xs = np.arange(w)
    y0 = np.clip(ys - r, 0, h)
    y1 = np.clip(ys + r + 1, 0, h)
    x0 = np.clip(xs - r, 0, w)
    x1 = np.clip(xs + r + 1, 0, w)
    S = ii[np.ix_(y1, x1)] - ii[np.ix_(y0, x1)] - ii[np.ix_(y1, x0)] + ii[np.ix_(y0, x0)]
    cnt = ((y1 - y0)[:, None] * (x1 - x0)[None, :]).astype(np.float64)
    return (S / np.maximum(cnt, 1)).astype(np.float32)

def grad_mag(gray: np.ndarray) -> np.ndarray:
    """|∂x| + |∂y|（比 Sobel 便宜，标定口径一致即可）。"""
    g = gray.astype(np.float32)
    gx = np.zeros_like(g)
    gy = np.zeros_like(g)
    gx[:, 1:-1] = (g[:, 2:] - g[:, :-2]) * 0.5
    gy[1:-1, :] = (g[2:, :] - g[:-2, :]) * 0.5
    return np.abs(gx) + np.abs(gy)

def _dilate(mask: np.ndarray, r: int = 1) -> np.ndarray:
    out = mask.copy()
    for _ in range(int(r)):
        m = out.copy()
        out[1:, :] |= m[:-1, :]
        out[:-1, :] |= m[1:, :]
        m = out.copy()
        out[:, 1:] |= m[:, :-1]
        out[:, :-1] |= m[:, 1:]
    return out

def _erode(mask: np.ndarray, r: int = 1) -> np.ndarray:
    return ~_dilate(~mask, r)

def _close(mask: np.ndarray, r: int = 1) -> np.ndarray:
    return _erode(_dilate(mask, r), r)

def label_components(mask: np.ndarray, min_area: int = 1) -> List[Dict[str, Any]]:
    """连通域（4 邻接，行程 + 并查集，纯 numpy/python，不依赖 scipy/cv2）。

    返回 [{'area','x0','y0','x1','y1','cx','cy','w','h','mask'}...]，已按 area 降序。
    """
    m = np.ascontiguousarray(mask.astype(bool))
    h, w = m.shape
    parent: List[int] = []

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    runs: List[Tuple[int, int, int, int]] = []      
    prev: List[Tuple[int, int, int]] = []           
    for y in range(h):
        row = m[y]
        if not row.any():
            prev = []
            continue
        d = np.diff(np.concatenate(([0], row.view(np.int8), [0])))
        starts = np.flatnonzero(d == 1)
        ends = np.flatnonzero(d == -1)
        cur: List[Tuple[int, int, int]] = []
        for x0, x1 in zip(starts, ends):
            lab = len(parent)
            parent.append(lab)
            runs.append((y, int(x0), int(x1), lab))
            cur.append((int(x0), int(x1), lab))
        j = 0
        for (x0, x1, lab) in cur:
            while j < len(prev) and prev[j][1] <= x0:
                j += 1
            k = j
            while k < len(prev) and prev[k][0] < x1:
                union(lab, prev[k][2])
                k += 1
        prev = cur
    if not runs:
        return []
    groups: Dict[int, Dict[str, Any]] = {}
    for (y, x0, x1, lab) in runs:
        r = find(lab)
        g = groups.get(r)
        if g is None:
            groups[r] = {"area": x1 - x0, "x0": x0, "x1": x1, "y0": y, "y1": y}
        else:
            g["area"] += x1 - x0
            g["x0"] = min(g["x0"], x0)
            g["x1"] = max(g["x1"], x1)
            g["y0"] = min(g["y0"], y)
            g["y1"] = max(g["y1"], y)
    out = []
    for g in groups.values():
        if g["area"] < min_area:
            continue
        g["w"] = g["x1"] - g["x0"] + 1
        g["h"] = g["y1"] - g["y0"] + 1
        g["cx"] = 0.5 * (g["x0"] + g["x1"])
        g["cy"] = 0.5 * (g["y0"] + g["y1"])
        g["fill"] = g["area"] / float(max(1, g["w"] * g["h"]))
        out.append(g)
    out.sort(key=lambda z: -z["area"])
    return out

def _hue_color(h: float, s: float, v: float) -> str:
    """HSV(H 度, S 0-1, V 0-1) → R/G/Y/B/W/?（只做证据，不参与 on/off 判定）。"""
    if s < 0.22:
        return "W" if v > 0.55 else "?"
    if h < 25 or h >= 330:
        return "R"
    if h < 70:
        return "Y"
    if h < 175:
        return "G"
    if h < 265:
        return "B"
    return "R"

def _now_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z") or ""

@dataclass
class Scene:
    w: int = 0
    h: int = 0
    long: int = 0
    mean_v: float = 0.0
    grad: float = 0.0          
    sharp: bool = False
    soft: bool = False
    dark: bool = False
    has_target: bool = False
    notes: List[str] = dc_field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"w": self.w, "h": self.h, "long": self.long,
                "mean_v": round(self.mean_v, 1), "grad": round(self.grad, 2),
                "sharp": self.sharp, "soft": self.soft, "dark": self.dark,
                "has_target": self.has_target, "notes": list(self.notes)}

def scene_gate(bgr: np.ndarray) -> Scene:
    h, w = bgr.shape[:2]
    hsv = bgr_to_hsv(bgr)
    v = hsv[:, :, 2] * 255.0
    g = grad_mag(v)
    sc = Scene(w=w, h=h, long=max(h, w), mean_v=float(v.mean()), grad=float(g.mean()))
    sc.sharp = sc.grad >= TH["grad_blur"]
    sc.soft = TH["grad_blur"] <= sc.grad < TH["grad_soft"]
    sc.dark = sc.mean_v < 45.0
    if not sc.sharp:
        sc.notes.append("画面发虚（mean|grad|=%.2f < %.2f）" % (sc.grad, TH["grad_blur"]))
    return sc

@dataclass
class LampObs:
    x: float
    y: float
    r: float
    on: bool
    color: str
    v_center: float
    v_ring: float
    delta: float
    s_mean: float
    fill: float
    confidence: float
    backend: str = "numpy"
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for k in ("x", "y", "r", "v_center", "v_ring", "delta", "fill"):
            d[k] = round(float(d[k]), 2)
        d["s_mean"] = round(float(self.s_mean), 3)
        d["confidence"] = round(float(self.confidence), 3)
        return d

def _lamp_radius_limits(long_side: int) -> Tuple[float, float]:
    return TH["lamp_r_lo_frac"] * long_side, TH["lamp_r_hi_frac"] * long_side

def detect_lamps(bgr: np.ndarray) -> Tuple[List[LampObs], Dict[str, Any]]:
    """找"亮着的灯"与"暗灯罩（灭灯）"。

    做法（纯 numpy，不依赖 cv2）：
      1) 局部背景 V_bg（大核 box 均值）→ ``delta = V - V_bg``
      2) 亮灯掩膜 = ``delta>22 & V>105 & (S>55 | V>245)``；
         暗灯罩掩膜 = ``delta<-14 & V<118``
      3) 几何门：半径区间 / 实心比 / 长宽比；暗灯罩另加三道门
         （中心像素必须自己就是暗的、环带要亮 ≥85、环带对比 ≥14）
      4) 环带测量优先调复用模块 ``led_panel.measure_at``（纯 numpy 实现，缺 cv2 也能跑）
    """
    h, w = bgr.shape[:2]
    long_side = max(h, w)
    hsv = bgr_to_hsv(bgr)
    v = hsv[:, :, 2] * 255.0
    s01 = hsv[:, :, 1]
    k = max(9, (long_side // 24) | 1)
    v_bg = box_mean(v, k)
    delta = v - v_bg

    hsv_cv = np.dstack([hsv[:, :, 0] * 0.5, s01 * 255.0, v]).astype(np.uint8)

    lit = (delta > TH["lamp_delta_on"]) & (v > TH["lamp_v_min"]) & \
          ((s01 * 255.0 > TH["lamp_s_min"]) | (v > TH["lamp_white_v"]))
    dark = (delta < TH["dark_delta"]) & (v < TH["dark_v_max"])

    scale = min(1.0, float(TH["cc_long"]) / long_side)
    lit_s = np.asarray(Image.fromarray((lit * 255).astype(np.uint8)).resize(
        (max(1, int(w * scale)), max(1, int(h * scale))), Image.NEAREST)) > 127
    dark_s = np.asarray(Image.fromarray((dark * 255).astype(np.uint8)).resize(
        (max(1, int(w * scale)), max(1, int(h * scale))), Image.NEAREST)) > 127
    r_lo, r_hi = _lamp_radius_limits(TH["cc_long"])
    min_area = max(6, int(math.pi * r_lo * r_lo * 0.6))
    obs: List[LampObs] = []

    for cc in label_components(_close(lit_s, 1), min_area=min_area):
        r_s = math.sqrt(cc["area"] / math.pi)
        if not (r_lo <= r_s <= r_hi):
            continue
        if cc["fill"] < TH["lamp_fill_min"]:
            continue
        asp = cc["w"] / float(max(1, cc["h"]))
        if not (TH["lamp_aspect_lo"] <= asp <= TH["lamp_aspect_hi"]):
            continue
        cx, cy, r = cc["cx"] / scale, cc["cy"] / scale, r_s / scale
        meas = None
        if LP is not None:
            try:
                meas = LP.measure_at(bgr, hsv_cv, int(round(cx)), int(round(cy)), max(2, int(round(r))))
            except Exception:
                meas = None
        if meas:
            dl = float(meas["delta"])
            vc, vr, sm = float(meas["v_center"]), float(meas["v_ring"]), float(meas["s_mean"]) / 255.0
        else:
            x0, x1 = int(max(0, cx - 3 * r)), int(min(w, cx + 3 * r + 1))
            y0, y1 = int(max(0, cy - 3 * r)), int(min(h, cy + 3 * r + 1))
            vc = float(v[int(max(0, cy - r)):int(min(h, cy + r)) + 1,
                         int(max(0, cx - r)):int(min(w, cx + r)) + 1].mean())
            vr = float(np.percentile(v[y0:y1, x0:x1], 25)) if x1 > x0 and y1 > y0 else vc
            sm = float(s01[int(max(0, cy - r)):int(min(h, cy + r)) + 1,
                            int(max(0, cx - r)):int(min(w, cx + r)) + 1].mean())
            dl = vc - vr
        on = (dl >= TH["lamp_delta_on"]) and (vc >= TH["lamp_v_min"])
        conf = _conf_from_margin(dl, TH["lamp_delta_on"], TH["lamp_delta_off"])
        yy, xx = int(cy), int(cx)
        obs.append(LampObs(x=cx, y=cy, r=r, on=bool(on),
                           color=_hue_color(float(hsv[yy, xx, 0]), float(hsv[yy, xx, 1]), float(hsv[yy, xx, 2])),
                           v_center=vc, v_ring=vr, delta=dl, s_mean=sm, fill=float(cc["fill"]),
                           confidence=conf, reason="delta=%.1f（亮灯阈值 %.0f）" % (dl, TH["lamp_delta_on"])))

    for cc in label_components(_close(dark_s, 1), min_area=min_area):

        r = 0.5 * min(cc["w"], cc["h"]) / scale
        if not (r_lo <= r <= r_hi):
            continue
        asp = cc["w"] / float(max(1, cc["h"]))
        if not (0.55 <= asp <= 1.8):
            continue
        if cc["fill"] < TH["dark_fill_min"]:
            continue
        cx, cy = cc["cx"] / scale, cc["cy"] / scale

        
        core = _disc_dark_frac(dark, cx, cy, 0.55 * r)
        if core < 0.85:
            continue
        yy, xx = int(cy), int(cx)
        center_v = float(v[yy, xx])

        
        lit_frac = _disc_dark_frac(lit, cx, cy, 0.9 * r)
        if lit_frac > TH["dark_specular_lit_max"]:
            continue
        specular = center_v > TH["dark_center_v_max"]      

        lens_v = _disc_percentile(v, cx, cy, 0.6 * r, 25.0)
        ring = _ring_stats(v, cx, cy, r * 2.0, r * 3.0)
        if ring is None:
            continue
        ring_mean, ring_p25 = ring
        if ring_p25 < TH["dark_ring_min"]:
            continue
        if ring_p25 - lens_v < TH["dark_ring_contrast"]:
            continue
        if any(math.hypot(o.x - cx, o.y - cy) < 1.6 * max(o.r, r) for o in obs):
            continue
        conf = _conf_from_margin(ring_p25 - lens_v, TH["dark_ring_contrast"], 8.0)
        if specular:
            conf = min(conf, 0.72)                 
        obs.append(LampObs(x=cx, y=cy, r=r, on=False,
                           color=_hue_color(float(hsv[yy, xx, 0]), float(hsv[yy, xx, 1]), float(hsv[yy, xx, 2])),
                           v_center=lens_v, v_ring=ring_p25, delta=lens_v - ring_p25,
                           s_mean=float(s01[yy, xx]), fill=float(cc["fill"]), confidence=conf,
                           reason="暗灯罩：灯罩 V25=%.0f、环带 V=%.0f、对比 %.0f、核心暗占比 %.2f%s"
                                  % (lens_v, ring_p25, ring_p25 - lens_v, core,
                                     "（中心有点状反光，按灭灯判并降置信）" if specular else "")))
    obs.sort(key=lambda o: (o.y, o.x))
    dbg = {"n_lit": sum(1 for o in obs if o.on), "n_dark": sum(1 for o in obs if not o.on),
           "hsv_backend": "numpy", "measure_backend": "led_panel.measure_at" if LP is not None else "inline",
           "cc_scale": round(scale, 3)}
    return obs, dbg

def _ring_stats(v: np.ndarray, cx: float, cy: float, r_in: float, r_out: float):
    h, w = v.shape[:2]
    x0, x1 = int(max(0, cx - r_out)), int(min(w, cx + r_out + 1))
    y0, y1 = int(max(0, cy - r_out)), int(min(h, cy + r_out + 1))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    yy, xx = np.mgrid[y0:y1, x0:x1]
    rr = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    m = (rr >= r_in) & (rr <= r_out)
    if not m.any():
        return None
    sub = v[y0:y1, x0:x1][m]
    return float(sub.mean()), float(np.percentile(sub, 25))

def _disc_percentile(v: np.ndarray, cx: float, cy: float, r: float, q: float) -> float:
    """圆盘内灰度 q 分位（灭灯亮度用它，避免被单点反光带跑）。"""
    if r <= 0:
        return 0.0
    h, w = v.shape[:2]
    cx = min(max(cx, 0.0), w - 1.0)
    cy = min(max(cy, 0.0), h - 1.0)
    x0, x1 = int(max(0, cx - r)), int(min(w, cx + r + 1))
    y0, y1 = int(max(0, cy - r)), int(min(h, cy + r + 1))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return 0.0
    yy, xx = np.mgrid[y0:y1, x0:x1]
    rr = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    m = rr <= r
    if not m.any():
        return 0.0
    return float(np.percentile(v[y0:y1, x0:x1][m], q))

def _disc_dark_frac(mask_small: np.ndarray, cx_s: float, cy_s: float, r_s: float) -> float:
    """圆盘内"掩膜为真"的比例（灯罩是一整片暗，丝印/阴影不是）。坐标与掩膜必须同一尺度。"""
    if r_s <= 0:
        return 0.0
    h, w = mask_small.shape[:2]
    cx_s = min(max(cx_s, 0.0), w - 1.0)
    cy_s = min(max(cy_s, 0.0), h - 1.0)
    r_s = min(r_s, min(w, h) / 2.0)
    x0, x1 = int(max(0, cx_s - r_s)), int(min(w, cx_s + r_s + 1))
    y0, y1 = int(max(0, cy_s - r_s)), int(min(h, cy_s + r_s + 1))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return 0.0
    yy, xx = np.mgrid[y0:y1, x0:x1]
    rr = np.sqrt((xx - cx_s) ** 2 + (yy - cy_s) ** 2)
    m = rr <= r_s
    if not m.any():
        return 0.0
    return float(mask_small[y0:y1, x0:x1][m].mean())

def _conf_from_margin(value: float, thr: float, lo: float) -> float:
    """置信度：刚过阈值 → 0.55 起，2 倍余量 → 0.95 封顶。低于下沿 → 0.3。"""
    if value <= lo:
        return 0.3
    if value >= 2.0 * thr:
        return 0.95
    return float(0.55 + 0.40 * (value - thr) / max(1e-6, thr))

@dataclass
class LampRow:
    obs: List[LampObs]
    y: float
    gap: float
    gap_cv: float
    x0: float
    x1: float

    def to_dict(self) -> Dict[str, Any]:
        return {"y": round(self.y, 1), "n_slots": len(self.obs), "gap": round(self.gap, 1),
                "gap_cv": round(self.gap_cv, 3), "x0": round(self.x0, 1), "x1": round(self.x1, 1),
                "lamps": [o.to_dict() for o in self.obs]}

def find_lamp_rows(obs: Sequence[LampObs]) -> List[LampRow]:
    """把灯观测聚成"一排"：y 接近 + 间距规整。指示灯面板一定是一排等间距的灯。"""
    rows: List[LampRow] = []
    used = [False] * len(obs)
    order = sorted(range(len(obs)), key=lambda i: obs[i].y)
    for idx in order:
        if used[idx]:
            continue
        base = obs[idx]
        group = [base]
        used[idx] = True
        for j in order:
            if used[j]:
                continue
            o = obs[j]
            if abs(o.y - base.y) <= TH["row_y_tol"] * max(base.r, o.r):

                if 0.45 <= (o.r / max(base.r, 1e-6)) <= 2.2:
                    group.append(o)
                    used[j] = True
        if len(group) < TH["row_min_slots"]:
            continue
        group.sort(key=lambda o: o.x)
        gaps = np.diff([o.x for o in group]) if len(group) > 1 else np.array([0.0])
        gap = float(np.median(gaps)) if len(gaps) else 0.0
        if gap <= 0:
            continue
        cv = float(np.std(gaps) / max(gap, 1e-6))
        if cv > TH["row_gap_cv"]:
            continue
        rows.append(LampRow(obs=group, y=float(np.mean([o.y for o in group])), gap=gap,
                            gap_cv=cv, x0=group[0].x, x1=group[-1].x))
    rows.sort(key=lambda r: (-len(r.obs), r.y))
    return rows

_CALIB_ASPECT_TOL = 0.04
_CALIB_R_FRAC = {"button": 0.0155, "button_lamp": 0.0155, "indicator": 0.0065}

def _calib_scale(spec: Dict[str, Any], long_side: int,
                 img_wh: Tuple[int, int]) -> Tuple[float, str]:
    """标定坐标 → 当前工作帧的缩放系数；取景比例不符时返回 0（宁可不判）。"""
    sz = spec.get("calib_photo_size") or (1920.0, 1080.0)
    try:
        cw, ch = float(sz[0]), float(sz[1])
    except Exception:                                              
        cw, ch = 1920.0, 1080.0
    if cw <= 1 or ch <= 1:
        return long_side / 1920.0, ""
    w, h = img_wh
    calib_ar, cur_ar = cw / ch, w / float(max(h, 1))
    if abs(cur_ar - calib_ar) / calib_ar > _CALIB_ASPECT_TOL:
        return 0.0, ("取景宽高比 %.3f 与标定照片 %.3f 不同 ⇒ 标定坐标不适用（宁可不判）"
                     % (cur_ar, calib_ar))
    return long_side / float(max(cw, ch)), ""

def _lamp_radius_hint(lamp: Dict[str, Any], long_side: int, r_med: float) -> float:
    """标定坐标处没有检出灯时，按灯的"角色"给测量半径（跟画面尺度走）。"""
    role = str(lamp.get("role") or "").strip()
    r = _CALIB_R_FRAC.get(role, 0.0065) * long_side
    if r_med > 0:
        r = min(max(r, 0.6 * r_med), 1.8 * r_med)
    return float(max(3.0, min(r, 0.04 * long_side)))

def _measure_calib_lamp(bgr: np.ndarray, hsv: np.ndarray, x: float, y: float,
                        r: float) -> Optional[LampObs]:
    """在标定坐标上直接量一颗灯：中心盘 V 中位 vs 环带 V 中位 ⇒ delta / 亮灭 / 颜色。"""
    if bgr is None or r < 2:
        return None
    h, w = bgr.shape[:2]
    if not (0 <= x < w and 0 <= y < h):
        return None
    x0, x1 = max(0, int(x - 2 * r)), min(w, int(x + 2 * r) + 1)
    y0, y1 = max(0, int(y - 2 * r)), min(h, int(y + 2 * r) + 1)
    if x1 - x0 < 5 or y1 - y0 < 5:
        return None
    yy, xx = np.mgrid[y0:y1, x0:x1]
    d2 = (yy - y) ** 2.0 + (xx - x) ** 2.0
    disc = d2 <= (0.55 * r) ** 2
    ring = (d2 >= (1.35 * r) ** 2) & (d2 <= (1.95 * r) ** 2)
    if int(disc.sum()) < 4 or int(ring.sum()) < 8:
        return None
    v = bgr[y0:y1, x0:x1].astype(np.float32).max(axis=2)
    v_center = float(np.median(v[disc]))
    v_ring = float(np.median(v[ring]))
    delta = v_center - v_ring
    on = bool(delta >= TH["lamp_delta_on"] and v_center >= TH["lamp_v_min"])
    if on:
        conf = _conf_from_margin(delta, TH["lamp_delta_on"], TH["lamp_delta_off"])
    else:

        
        margin = TH["lamp_delta_on"] - delta
        conf = _conf_from_margin(margin, TH["lamp_delta_on"] - TH["lamp_delta_off"], 6.0)
    iy, ix = int(min(max(y, 0), h - 1)), int(min(max(x, 0), w - 1))
    return LampObs(x=float(x), y=float(y), r=float(r), on=on,
                   color=_hue_color(float(hsv[iy, ix, 0]), float(hsv[iy, ix, 1]),
                                    float(hsv[iy, ix, 2])),
                   v_center=v_center, v_ring=v_ring, delta=delta,
                   s_mean=float(hsv[iy, ix, 1]), fill=1.0, confidence=conf,
                   reason="按标定坐标 (%.0f,%.0f) 直接量（r=%.0f）：中心 V=%.0f、环带 V=%.0f、"
                          "delta=%+.0f" % (x, y, r, v_center, v_ring, delta))

def _calib_lamps(ctx: PhotoCtx, pid: str, spec: Dict[str, Any],
                 bgr: Optional[np.ndarray]) -> Tuple[Optional[List[Optional[LampObs]]], str]:
    """按 led_rules.json 的逐灯标定坐标取这一部件的每颗灯。

    返回 ``(obs 列表 | None, 说明)``；``None`` = 该部件没有可用标定坐标（走旧的成排灯路径）。
    """
    if pid in ctx.calib:
        c = ctx.calib[pid]
        return c.get("lamps"), c.get("why") or ""
    lamps = spec.get("lamps") or []
    coords = [(l.get("photo_xy") or None) for l in lamps]
    if not lamps or any(not c for c in coords):
        why = "该部件没有逐灯标定坐标（led_rules.json measured.photo_xy）"
        ctx.calib[pid] = {"lamps": None, "why": why, "notes": []}
        return None, why
    if bgr is None:
        why = "本张图解码失败 ⇒ 标定坐标取灯不可用"
        ctx.calib[pid] = {"lamps": None, "why": why, "notes": []}
        return None, why
    h, w = bgr.shape[:2]
    long_side = max(h, w)
    k, why = _calib_scale(spec, long_side, (w, h))
    if k <= 0:
        ctx.calib[pid] = {"lamps": None, "why": why, "notes": []}
        return None, why
    hsv = ctx.imgs.get("hsv")
    if hsv is None:
        hsv = bgr_to_hsv(bgr)
        ctx.imgs["hsv"] = hsv
    rs = [o.r for o in ctx.lamps]
    r_med = float(np.median(rs)) if rs else 0.0
    out: List[Optional[LampObs]] = []
    notes: List[str] = []
    for i, lp in enumerate(lamps):
        cx, cy = float(coords[i][0]) * k, float(coords[i][1]) * k
        snap, sd = None, 1e9
        for o in ctx.lamps:
            d = math.hypot(o.x - cx, o.y - cy)
            if d < sd:
                snap, sd = o, d
        if snap is not None and sd <= max(6.0, 1.15 * snap.r):
            out.append(snap)
            notes.append("%s：标定 (%.0f,%.0f) → 命中检出灯 (%.0f,%.0f) r=%.0f"
                         % (lp.get("name"), cx, cy, snap.x, snap.y, snap.r))
            continue
        r = _lamp_radius_hint(lp, long_side, r_med)
        ob = _measure_calib_lamp(bgr, hsv, cx, cy, r)
        out.append(ob)
        notes.append("%s：标定 (%.0f,%.0f) → %s" % (
            lp.get("name"), cx, cy,
            ("直接量 r=%.0f delta=%+.0f" % (r, ob.delta)) if ob else "测不到（越界/太小）"))
    ctx.calib[pid] = {"lamps": out, "why": "", "notes": notes, "scale": k}
    return out, ""

def _row_from_obs(obs: Sequence[LampObs]) -> LampRow:
    """把"按标定坐标取的灯"包装成 LampRow（整排规则复用同一套判定/证据）。"""
    xs = [o.x for o in obs]
    gaps = np.diff(sorted(xs)) if len(xs) > 1 else np.array([0.0])
    gap = float(np.median(gaps)) if len(gaps) else 0.0
    cv = float(np.std(gaps) / max(gap, 1e-6)) if len(gaps) else 0.0
    return LampRow(obs=list(obs), y=float(np.mean([o.y for o in obs])), gap=gap, gap_cv=cv,
                   x0=float(min(xs)), x1=float(max(xs)))

def _calib_debug(ctx: PhotoCtx) -> Dict[str, Any]:
    """标定取灯的落盘摘要（给结果页/排障看：取了哪几颗、在哪、亮灭/颜色）。"""
    out: Dict[str, Any] = {}
    for pid, c in (ctx.calib or {}).items():
        obs = c.get("lamps")
        out[pid] = {"why": c.get("why") or "", "notes": list(c.get("notes") or []),
                    "lamps": [None if o is None else o.to_dict() for o in (obs or [])]}
    return out

_BLOB_PARTS = ("PS_KONG", "PS_WENYA", "Z14_PANEL", "Z15_PANEL", "ANT_DIR", "Z11", "Z11-1", "TX_STATE")
_BLOB_COLOR = {"R": "red", "G": "green", "W": "white", "Y": "amber"}   
_BLOB_CN = {"red": "红", "green": "绿", "white": "白", "amber": "琥珀"}
_BLOB_LETTER = {"red": "R", "green": "G", "white": "W", "amber": "Y"}

def _blob_colors_for(spec: Dict[str, Any]) -> Tuple[str, ...]:
    """按标定颜色决定只检测哪几种颜色（有未标定颜色 U/? 时退回全色）。

    好处：Z31 只找红/绿 ⇒ 不会被白纸/皮肤/琥珀色木纹干扰；也快一点。
    """
    cols: List[str] = []
    for l in spec.get("lamps") or []:
        c = _BLOB_COLOR.get(str(l.get("color") or "").upper())
        if c is None:
            return ("red", "green", "white", "amber")
        if c not in cols:
            cols.append(c)
    return tuple(cols) or ("red", "green", "white", "amber")

def _blob_raw(ctx: PhotoCtx, bgr: Optional[np.ndarray],
              colors: Sequence[str]) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """按颜色集合跑一次颜色亮点检测（同一颜色集合一张照片只跑一次，结果缓存在 ctx.blob）。"""
    key = tuple(colors)
    sets = ctx.blob.setdefault("sets", {})
    if key in sets:
        return sets[key].get("raw"), sets[key].get("why") or ""
    why = ""
    raw: Optional[List[Dict[str, Any]]] = None
    if LB is None:
        why = "lamp_blob 模块不可用（%s）" % ("; ".join(BLOB_NOTES) or "import 失败")
    elif bgr is None:
        why = "本张图解码失败 ⇒ 颜色亮点检测不可用"
    else:
        try:
            raw = LB.detect_lamps(bgr, colors=key)
        except Exception as exc:                                   
            why = "颜色亮点检测异常（%s: %s）" % (type(exc).__name__, exc)
            raw = None
    sets[key] = {"raw": raw, "why": why}
    if "raw" not in ctx.blob:                     
        ctx.blob["raw"] = raw
        ctx.blob["why"] = why
    return raw, why

def _blob_group_matches(group: Sequence[Dict[str, Any]],
                        expected: Sequence[Optional[str]]) -> bool:
    """灯组是否与标定期望**逐位**对得上（按 y 再 x 排序后比颜色）。

    ``expected`` 里 ``None`` = 该灯位颜色未标定（U/?），只约束数量、不约束颜色。
    """
    if len(group) != len(expected):
        return False
    seq = sorted(group, key=lambda b: (b["xy"][1], b["xy"][0]))
    for want, got in zip(expected, seq):
        if want is not None and got.get("color") != want:
            return False
    return True

def _blob_centroid(group: Sequence[Dict[str, Any]]) -> Tuple[float, float]:
    xs = [float(b["xy"][0]) for b in group]
    ys = [float(b["xy"][1]) for b in group]
    return sum(xs) / len(xs), sum(ys) / len(ys)

def _blob_geom_ok(group: Sequence[Dict[str, Any]], spec: Dict[str, Any], long_side: int,
                  img_wh: Tuple[int, int]) -> Tuple[bool, str]:
    """灯组内**相对几何**是否与标定星座一致（平移/缩放/旋转都允许，只比形状）。

    为什么加这一道：同一块 Z31 面板左右两列**同构**（都是 2 红 + 1 绿），
    只按"2 红 + 1 绿"匹配，照片只拍到右列时会把右列当成 PS_KONG（实测 201925）。
    这里用标定的相对位置（不是绝对坐标）做相似变换拟合：
      * 3 颗及以上：复平面最小二乘拟合 旋转+缩放+平移，平均残差 ≤ tol 才算同一星座；
      * 2 颗：只能比"灯间距"，比值必须在 [0.40, 2.50]（机位远近变化）。
    取景比例与标定照片差太多 / 没有标定坐标 ⇒ 不卡几何（宁可不判的防线交给别处）。
    """
    lamps = spec.get("lamps") or []
    if len(lamps) < 2 or len(lamps) != len(group):
        return True, ""
    k, _ = _calib_scale(spec, long_side, img_wh)
    if k <= 0:
        return True, ""
    try:
        C = np.array([[float(l["photo_xy"][0]) * k, float(l["photo_xy"][1]) * k] for l in lamps],
                     dtype=np.float64)
    except Exception:                                          
        return True, ""
    D = np.array([b["xy"] for b in sorted(group, key=lambda b: (b["xy"][1], b["xy"][0]))],
                 dtype=np.float64)
    if len(D) != len(C):
        return False, "灯组颗数 %d ≠ 标定 %d" % (len(D), len(C))
    if len(C) == 2:
        d_cal = float(np.hypot(*(C[1] - C[0])))
        d_det = float(np.hypot(*(D[1] - D[0])))
        ratio = d_det / max(d_cal, 1e-6)
        if not (0.40 <= ratio <= 2.50):
            return False, "两灯间距比 %.2f 超出 [0.40,2.50]" % ratio
        return True, "间距比%.2f" % ratio
    zc = (C[:, 0] - C[:, 0].mean()) + 1j * (C[:, 1] - C[:, 1].mean())
    zd = (D[:, 0] - D[:, 0].mean()) + 1j * (D[:, 1] - D[:, 1].mean())
    denom = float((np.abs(zc) ** 2).sum())
    if denom <= 1e-9:
        return True, ""
    w = complex((np.conj(zc) * zd).sum() / denom)
    scale = abs(w)
    resid = float(np.abs(zd - w * zc).mean())
    tol = max(6.0, 0.02 * long_side, 1.2 * float(np.median([b["r"] for b in group])))
    if not (0.40 <= scale <= 2.50):
        return False, "星座尺度 %.2f 超出 [0.40,2.50]" % scale
    if resid > tol:
        return False, "星座残差 %.0f px > %.0f px" % (resid, tol)
    return True, "残差%.0fpx/尺度%.2f" % (resid, scale)

def _led_panel_raw(bgr: np.ndarray, colors: Sequence[str]) -> List[Dict[str, Any]]:
    """led_panel.detect_candidates → lamp_blob 同构 raw（Z11 绿灯光芯发白时唯一可靠路径）。"""
    out: List[Dict[str, Any]] = []
    if LP is None or bgr is None:
        return out
    want = set(colors)
    try:
        cs = LP.detect_candidates(bgr)
    except Exception:
        return out
    for c in cs:
        try:
            if not getattr(c, "is_lamp", False):
                continue
            color = {"R": "red", "G": "green", "W": "white", "Y": "amber"}.get(
                str(getattr(c, "color", "")).upper(), "")
            if color not in want:
                continue
            vc = float(getattr(c, "v_center", 0.0))
            vr = float(getattr(c, "v_ring", 0.0))

            out.append({
                "xy": [int(getattr(c, "x", 0)), int(getattr(c, "y", 0))],
                "r": float(getattr(c, "r", 0)),
                "color": color,
                "hsv": [0, float(getattr(c, "s_mean", 0.0)), vc],
                "center_v": vc / 255.0,
                "ring_v": vr / 255.0,
                "delta_v": float(getattr(c, "delta", 0.0)) / 255.0,
                "on": bool(float(getattr(c, "delta", 0.0)) >= TH["lamp_delta_on"]),
                "conf": 0.90,
                "area": 0.0,
                "fill": float(getattr(c, "fill", 0.0)),
                "backend": "led_panel",
            })
        except Exception:
            continue
    return out

def _blob_partial_generic(raw, lamps, spec) -> Optional[List[LampObs]]:
    """部分斑块映射：检出颜色是期望颜色的子集时，按灯序填；缺的灯按灭/未检出。

    Z11 现场：5 灯（3 绿常亮 + 2 红灭），常亮的绿有 3 个白芯斑块、红灯不出斑块；
    旧逻辑因数量不足直接回退/未判定 → 结果页 0 行、只剩问答。这里给逐灯行。
    """
    try:
        if not raw or len(raw) >= len(lamps):
            return None
        from collections import Counter as _Counter
        expected = [_BLOB_COLOR.get(str(l.get("color") or "").upper()) for l in lamps]
        want = _Counter(c for c in expected if c)
        got = _Counter(b.get("color") for b in raw)
        for c, n in got.items():
            if c not in want or n > want[c]:
                return None
        used = set()
        obs: List[LampObs] = []
        for i, l in enumerate(lamps):
            wc = _BLOB_COLOR.get(str(l.get("color") or "").upper())
            pick = None
            for j, b in enumerate(raw):
                if j in used or b.get("color") != wc:
                    continue
                pick = (j, b)
                break
            if pick is not None:
                used.add(pick[0])
                b = pick[1]
                obs.append(LampObs(x=float(b["xy"][0]), y=float(b["xy"][1]),
                                   r=float(b["r"]), on=bool(b["on"]),
                                   color=_BLOB_LETTER.get(b["color"], "?"),
                                   v_center=float(b["center_v"]) * 255.0,
                                   v_ring=float(b["ring_v"]) * 255.0,
                                   delta=float(b["delta_v"]) * 255.0,
                                   s_mean=float(b["hsv"][1]) / 255.0,
                                   fill=float(b.get("fill") or 0.0),
                                   confidence=float(b["conf"]),
                                   backend="led_panel",
                                   reason="颜色亮点：%s 斑块 r=%.1f、delta=%+.0f"
                                          % (_BLOB_CN.get(b["color"], b["color"]),
                                             b["r"], b["delta_v"] * 255)))
            else:
                obs.append(LampObs(x=0.0, y=0.0, r=0.0, on=False,
                                   color=_BLOB_LETTER.get(wc, "?"),
                                   v_center=0.0, v_ring=0.0, delta=-30.0,
                                   s_mean=0.0, fill=0.0, confidence=0.80,
                                   backend="led_panel",
                                   reason="该灯未检出色斑（灯灭/被遮挡）→ 按灭记录"))
        return obs
    except Exception:
        return None

def _blob_partial_obs(raw, lamps, spec):
    """PS_KONG / PS_WENYA 三灯面板（2 红电源 + 1 绿控制）：只检出部分灯时的逐灯映射。

    面板事实（led_rules.json）：#0/#1 两颗红电源灯"上下竖排"、#2 绿控制灯常灭（expect=any）。
    所以"只检出 2 颗红斑块"是**正常现场态**，不能因数量不足就回退旧标定坐标（那会把亮灯判成灭）。

    ★ 2026-10-29（现场 194257 + 全模块审查）：
      1. 红斑块按 **(y,x) 排序**映射灯序（lamp_blob 按 delta 降序返回，直接用会把空调/市电互换）；
      2. 本面板两颗红电源灯必须**近似竖排**（dy ≥ 1.2·dx），横排的别的面板红点不硬套；
      3. 允许检出"额外的暗红灯罩"（191629 实测：两颗亮红 + 第三颗暗红透镜 r=17.9、on=false）：
         优先取两颗粒**亮**红；只有 1 颗亮红时取它与 y 最近的暗红（=一红灭的故障场景）；
         0 颗亮红且 ≥2 颗暗红取 y 最近的一对（=两红全灭的故障场景）；
         亮红 >2 颗 ⇒ 画面里有别的面板红点 ⇒ 不映射（宁不判）；
      4. 绿控制灯：恰好 1 颗、且位置在两红下方合理范围才映射；否则按"未检出（常灭）"记录。
    """
    try:
        from collections import Counter as _Counter
        expected = [_BLOB_COLOR.get(str(l.get("color") or "").upper()) for l in lamps]
        if not raw:
            return None
        want = _Counter(c for c in expected if c)
        for b in raw:
            if b.get("color") not in want:
                return None
        reds = sorted([b for b in raw if b.get("color") == "red"],
                      key=lambda b: (b["xy"][1], b["xy"][0]))
        greens = sorted([b for b in raw if b.get("color") == "green"],
                        key=lambda b: (b["xy"][1], b["xy"][0]))
        lit_reds = [b for b in reds if b.get("on")]
        if len(lit_reds) == 2:
            pair = sorted(lit_reds, key=lambda b: b["xy"][1])
        elif len(lit_reds) == 1 and reds:
            lr = lit_reds[0]
            others = [b for b in reds if b is not lr]
            others.sort(key=lambda b: abs(float(b["xy"][1]) - float(lr["xy"][1])))
            pair = sorted([lr, others[0]], key=lambda b: b["xy"][1])
        elif not lit_reds and len(reds) >= 2:
            reds2 = sorted(reds, key=lambda b: b["xy"][1])
            gaps = [(abs(float(reds2[i + 1]["xy"][1]) - float(reds2[i]["xy"][1])), i)
                    for i in range(len(reds2) - 1)]
            _, i = min(gaps)
            pair = [reds2[i], reds2[i + 1]]
        else:

            return None
        dx = abs(float(pair[0]["xy"][0]) - float(pair[1]["xy"][0]))
        dy = abs(float(pair[0]["xy"][1]) - float(pair[1]["xy"][1]))
        if dy < 1.2 * max(dx, 1.0):          
            return None
        chosen_green = None
        if len(greens) == 1:
            g = greens[0]
            gx, gy = float(g["xy"][0]), float(g["xy"][1])
            bx, by = float(pair[1]["xy"][0]), float(pair[1]["xy"][1])
            if abs(gx - bx) <= 2.0 * max(dy, 1.0) and 0.0 <= (gy - by) <= 3.0 * max(dy, 1.0):
                chosen_green = g
        raw_use = [pair[0], pair[1]] + ([chosen_green] if chosen_green is not None else [])
        used = set()
        out = []
        for i, l in enumerate(lamps):
            wc = _BLOB_COLOR.get(str(l.get("color") or "").upper())
            pick = None
            for j, b in enumerate(raw_use):
                if j not in used and b.get("color") == wc:
                    pick = (j, b)
                    break
            if pick is not None:
                used.add(pick[0])
                b = pick[1]
                out.append(LampObs(x=float(b["xy"][0]), y=float(b["xy"][1]),
                                   r=float(b["r"]), on=bool(b["on"]),
                                   color=_BLOB_LETTER.get(b["color"], "?"),
                                   v_center=float(b["center_v"]) * 255.0,
                                   v_ring=float(b["ring_v"]) * 255.0,
                                   delta=float(b["delta_v"]) * 255.0,
                                   s_mean=float(b["hsv"][1]) / 255.0,
                                   fill=float(b.get("fill") or 0.0),
                                   confidence=float(b["conf"]),
                                   backend="lamp_blob",
                                   reason="颜色亮点：%s 斑块 r=%.1f、delta=%+.0f"
                                          % (_BLOB_CN.get(b["color"], b["color"]),
                                             b["r"], b["delta_v"] * 255)))
            else:
                out.append(LampObs(x=0.0, y=0.0, r=0.0, on=False,
                                   color=_BLOB_LETTER.get(wc, "?"),
                                   v_center=0.0, v_ring=0.0, delta=-30.0,
                                   s_mean=0.0, fill=0.0, confidence=0.80,
                                   backend="lamp_blob",
                                   reason="该灯未检出（灯灭/被遮挡）→ 按灭记录"))
        return out
    except Exception:
        return None

def _blob_roi_obs(raw, lamps, spec, long_side: int, img_wh: Tuple[int, int]):
    """按 led_rules 标定坐标的**邻近匹配**做逐灯映射（有 photo_xy 的部件）。

    适用：标定照片就是现场同一块面板、但检出斑块数和期望对不上（缺灯/多干扰点）。
    做法：把标定 photo_xy 按 `_calib_scale` 的 k 缩放到当前帧，每个斑块找**颜色兼容**且
    最近的灯位（容差 = max(3r, 0.07×长边)），一对一；匹配上的灯位给斑块，没匹配的给 None
    （=未判定，绝不硬说灭）。至少命中 1 颗才返回，否则返回 None 让调用方走旧标定路径。
    """
    try:
        lamps_xy = []
        for l in lamps:
            xy = l.get("photo_xy") or (l.get("measured") or {}).get("photo_xy")
            if not xy or len(xy) != 2:
                return None
            lamps_xy.append((float(xy[0]), float(xy[1])))
        k, _ = _calib_scale(spec, long_side, img_wh)
        if k <= 0:
            return None
        exp = [(x * k, y * k) for x, y in lamps_xy]
        tol_base = 0.07 * float(long_side)
        obs: List[Optional[LampObs]] = [None] * len(lamps)
        used = set()
        for j, b in enumerate(raw):
            bx, by = float(b["xy"][0]), float(b["xy"][1])
            best_i, best_d = -1, 1e18
            for i, (ex, ey) in enumerate(exp):
                if i in used or obs[i] is not None:
                    continue
                want_c = _BLOB_COLOR.get(str(lamps[i].get("color") or "").upper())
                if want_c and b.get("color") != want_c:
                    continue
                d = math.hypot(bx - ex, by - ey)
                if d < best_d:
                    best_i, best_d = i, d
            tol = max(3.0 * float(b["r"]), tol_base)
            if best_i >= 0 and best_d <= tol:
                used.add(best_i)
                obs[best_i] = LampObs(
                    x=bx, y=by, r=float(b["r"]), on=bool(b["on"]),
                    color=_BLOB_LETTER.get(b["color"], "?"),
                    v_center=float(b["center_v"]) * 255.0,
                    v_ring=float(b["ring_v"]) * 255.0,
                    delta=float(b["delta_v"]) * 255.0,
                    s_mean=float(b["hsv"][1]) / 255.0,
                    fill=float(b.get("fill") or 0.0),
                    confidence=float(b["conf"]), backend="lamp_blob_roi",
                    reason="标定坐标邻近匹配：%s 斑块 r=%.1f、离标定 %.0fpx"
                           % (_BLOB_CN.get(b["color"], b["color"]), b["r"], best_d))
        if not any(o is not None for o in obs):
            return None
        return obs
    except Exception:
        return None

def _blob_lamps(ctx: PhotoCtx, pid: str, spec: Dict[str, Any],
                bgr: Optional[np.ndarray]) -> Tuple[Optional[List[LampObs]], str, str]:
    """颜色亮点 → 灯位映射。

    返回 ``(obs, status, why)``：
      * ``obs`` 非空、status="ok"        —— 映射成功，逐灯观测可直接判定；
      * ``obs is None``、status="fallback" —— 斑块少于期望灯数（或 0 个/模块不可用）⇒ 回退标定坐标；
      * ``obs is None``、status="mismatch" —— 斑块够多但跟标定期望对不上 ⇒ 整部件判不准。
    """
    cache = ctx.blob.setdefault("parts", {})
    if pid in cache:
        c = cache[pid]
        return c.get("obs"), c.get("status") or "fallback", c.get("why") or ""
    if pid not in _BLOB_PARTS:
        cache[pid] = {"status": "fallback", "why": "该部件未启用颜色亮点检测（保持标定坐标路径）"}
        return None, "fallback", cache[pid]["why"]
    colors = _blob_colors_for(spec)
    raw, why = _blob_raw(ctx, bgr, colors)
    if raw is None:
        cache[pid] = {"status": "fallback", "why": why}
        return None, "fallback", why
    if not raw:
        if pid in ("PS_KONG", "PS_WENYA"):

            

            why = ("画面里没有检出任何红/绿亮点（只找了 %s）⇒ 无法确认 %s 两颗红灯亮灭"
                   "（暗场/未对准/过曝）→ 整部件判不准（宁不判，绝不回退旧标定坐标）"
                   % ("/".join(_BLOB_CN.get(c, c) for c in colors), pid))
            cache[pid] = {"status": "mismatch", "why": why, "n": 0}
            return None, "mismatch", why
        cache[pid] = {"status": "fallback",
                      "why": "画面里没有检出任何颜色亮点（只找了 %s）⇒ 回退标定坐标路径"
                             % "/".join(_BLOB_CN.get(c, c) for c in colors)}
        return None, "fallback", cache[pid]["why"]
    lamps = spec.get("lamps") or []
    expected = [_BLOB_COLOR.get(str(l.get("color") or "").upper()) for l in lamps]

    
    if pid in ("Z11", "Z11-1", "Z11-3", "Z11-4", "Z11-5") and len(raw) < len(lamps):
        _lp_raw = _led_panel_raw(bgr, colors)
        if len(_lp_raw) > len(raw):
            raw = _lp_raw
            why = "lamp_blob 不足 → led_panel 候选补足 %d 个斑块（只找 %s）" % (
                len(raw), "/".join(_BLOB_CN.get(c, c) for c in colors))
    long_side = max(bgr.shape[:2]) if bgr is not None else 1600
    groups = LB.group_lamps(raw, long_side=long_side) if hasattr(LB, "group_lamps") else [list(raw)]
    matches: List[List[Dict[str, Any]]] = []
    geo_bad: List[str] = []
    for g in groups:
        if not _blob_group_matches(g, expected):
            continue
        ok_geo, geo_why = _blob_geom_ok(g, spec, long_side,
                                        (bgr.shape[1], bgr.shape[0]) if bgr is not None else (1600, 900))
        if ok_geo:
            matches.append(g)
        else:
            geo_bad.append("%s(%s)" % ("、".join("%d,%d" % b["xy"] for b in g), geo_why))
    want_txt = " + ".join("%s%d" % (_BLOB_CN.get(c, "?"), expected.count(c))
                          for c in dict.fromkeys([c for c in expected if c])) or "任意"
    raw_txt = "、".join("%s(%d,%d)%s" % (_BLOB_CN.get(b["color"], b["color"]), b["xy"][0], b["xy"][1],
                                         "亮" if b["on"] else "灭") for b in raw[:12])
    if len(raw) > 12:
        raw_txt += " 等 %d 个" % len(raw)
    if not matches:
        n_det = len(raw)

        

        
        if pid in ("PS_KONG", "PS_WENYA"):
            _part = _blob_partial_obs(raw[:], lamps, spec)
            if _part is not None:
                cache[pid] = {"status": "ok",
                              "why": "%s 部分斑块映射（检出 %d 个斑块/期望 %d 颗）"
                                     % (pid, n_det, len(lamps)),
                              "n": n_det, "obs": _part}
                return _part, "ok", cache[pid]["why"]
            why = ("%s 检出 %d 个颜色斑块（%s，期望 %s），但无法安全映射到 %d 颗灯"
                   "（两颗红电源灯必须近似竖排、亮红恰 2 颗）⇒ 整部件判不准（宁不判；绝不回退旧标定坐标"
                   "把亮灯判成灭）；原始列表：%s"
                   % (pid, n_det,
                      "红%d/绿%d/白%d/琥珀%d" % tuple(
                          sum(1 for b in raw if b["color"] == c)
                          for c in ("red", "green", "white", "amber")),
                      want_txt, len(lamps), raw_txt))
            cache[pid] = {"status": "mismatch", "why": why, "n": n_det}
            return None, "mismatch", why
        if pid in ("Z11", "Z11-1", "Z11-3", "Z11-4", "Z11-5"):
            _z11 = _blob_partial_generic(raw[:], lamps, spec)
            if _z11 is not None:
                cache[pid] = {"status": "ok",
                              "why": "%s 部分斑块映射（检出 %d/%d，缺灯按灭）" % (pid, n_det, len(lamps)),
                              "n": n_det, "obs": _z11}
                return _z11, "ok", cache[pid]["why"]

        

        if bgr is not None and any(l.get("photo_xy") for l in lamps):
            _roi = _blob_roi_obs(raw[:], lamps, spec, long_side,
                                 (bgr.shape[1], bgr.shape[0]))
            if _roi is not None:
                cache[pid] = {"status": "ok",
                              "why": "%s 标定坐标邻近匹配（检出 %d 个斑块/期望 %d 颗，匹配 %d 颗）"
                                     % (pid, n_det, len(lamps),
                                        sum(1 for o in _roi if o is not None)),
                              "n": n_det, "obs": _roi}
                return _roi, "ok", cache[pid]["why"]
        if n_det < len(lamps):

            
            why = ("颜色亮点只检到 %d 个斑块（%s），少于标定期望的 %d 颗（%s）⇒ 斑块不足以整组映射，"
                   "回退标定坐标兜底；原始列表：%s"
                   % (n_det, "红%d/绿%d/白%d/琥珀%d" % tuple(
                       sum(1 for b in raw if b["color"] == c) for c in ("red", "green", "white", "amber")),
                      len(lamps), want_txt, raw_txt))
            cache[pid] = {"status": "fallback", "why": why, "n": n_det}
            return None, "fallback", why
        why = ("颜色亮点检测到 %d 个斑块（%s），但没有任何一组的数量+颜色与标定期望 %d 颗（%s）"
               "完全一致 ⇒ 整部件判不准（不硬凑）；原始列表：%s"
               % (n_det, "红%d/绿%d/白%d/琥珀%d" % tuple(
                   sum(1 for b in raw if b["color"] == c) for c in ("red", "green", "white", "amber")),
                  len(lamps), want_txt, raw_txt))
        if geo_bad:
            why += "；另有 %d 组颜色对得上、但相对几何不符（见 debug.blob）：%s" % (
                len(geo_bad), "；".join(geo_bad[:3]))
        cache[pid] = {"status": "mismatch", "why": why, "n": n_det}
        return None, "mismatch", why

    pick = matches[0]
    tie = ""
    if len(matches) > 1:
        k, _ = _calib_scale(spec, long_side, (bgr.shape[1], bgr.shape[0])) if bgr is not None else (0.0, "")
        if k > 0:
            cx = float(np.mean([float(l["photo_xy"][0]) for l in lamps])) * k
            cy = float(np.mean([float(l["photo_xy"][1]) for l in lamps])) * k
            matches.sort(key=lambda g: math.hypot(_blob_centroid(g)[0] - cx,
                                                  _blob_centroid(g)[1] - cy))
            pick = matches[0]
            px, py = _blob_centroid(pick)
            tie = "；%d 组同色灯组中取离标定重心最近的一组（重心 (%.0f,%.0f)，偏 %.0f px）" % (
                len(matches), px, py, math.hypot(px - cx, py - cy))
        else:
            why = ("有 %d 组斑块都符合标定期望（%s），但本张取景比例与标定照片不同 ⇒ 无法去歧义，"
                   "整部件判不准；原始列表：%s" % (len(matches), want_txt, raw_txt))
            cache[pid] = {"status": "mismatch", "why": why, "n": len(raw)}
            return None, "mismatch", why
    seq = sorted(pick, key=lambda b: (b["xy"][1], b["xy"][0]))
    obs: List[LampObs] = []
    for b in seq:
        col = _BLOB_LETTER.get(b["color"], "?")
        obs.append(LampObs(x=float(b["xy"][0]), y=float(b["xy"][1]), r=float(b["r"]),
                           on=bool(b["on"]), color=col,
                           v_center=float(b["center_v"]) * 255.0,
                           v_ring=float(b["ring_v"]) * 255.0,
                           delta=float(b["delta_v"]) * 255.0,
                           s_mean=float(b["hsv"][1]) / 255.0, fill=float(b.get("fill") or 0.0),
                           confidence=float(b["conf"]), backend="lamp_blob",
                           reason="颜色亮点：%s 斑块 r=%.1f、中心 V=%.0f、环带 V=%.0f、delta=%+.0f"
                                  % (_BLOB_CN.get(b["color"], b["color"]), b["r"],
                                     b["center_v"] * 255, b["ring_v"] * 255, b["delta_v"] * 255)))
    why = ("颜色亮点检测（只找 %s）：整图 %d 个斑块，命中 %d 颗（%s），映射到灯序 #0..#%d%s"
           % ("/".join(_BLOB_CN.get(c, c) for c in colors), len(raw), len(obs),
              "、".join("%s(%d,%d)" % (_BLOB_CN.get(b["color"], b["color"]),
                                      b["xy"][0], b["xy"][1]) for b in seq),
              len(obs) - 1, tie))
    cache[pid] = {"status": "ok", "why": why, "n": len(raw), "colors": list(colors),
                  "group": [dict(b) for b in seq], "obs": obs}
    return obs, "ok", why

def _blob_debug(ctx: PhotoCtx) -> Dict[str, Any]:
    """颜色亮点检测的落盘摘要（按颜色集合的原始列表 + 每个部件的映射结果，给排障用）。"""
    sets = (ctx.blob or {}).get("sets") or {}
    raw_all: List[Dict[str, Any]] = []
    out_sets: List[Dict[str, Any]] = []
    for key, v in sets.items():
        lamps = [dict(b) for b in (v.get("raw") or [])]
        out_sets.append({"colors": list(key), "n": len(lamps), "why": v.get("why") or "",
                         "lamps": lamps})
        raw_all.extend(lamps)
    out: Dict[str, Any] = {
        "n": len(raw_all),
        "why": (ctx.blob or {}).get("why") or "",
        "sets": out_sets,
        "parts": {},
    }
    for pid, c in ((ctx.blob or {}).get("parts") or {}).items():
        out["parts"][pid] = {"status": c.get("status") or "", "why": c.get("why") or "",
                             "n_raw": c.get("n"), "colors": c.get("colors")}
    return out

_TX5_PANEL_PARTS = ("TX_STATE", "Z11", "Z11-1")
_TX5_PANEL_KEY = "TX5"          
_TX5_DEFAULT_SEQ = ("green", "green", "green", "red", "red")
_TX5_CN = {"green": "绿", "red": "红", "white": "白", "amber": "琥珀"}
_TX5_COLOR_WORDS = {"R": "red", "G": "green", "W": "white", "Y": "amber",
                    "RED": "red", "GREEN": "green", "WHITE": "white",
                    "AMBER": "amber", "YELLOW": "amber",
                    "红": "red", "绿": "green", "白": "white", "黄": "amber", "琥珀": "amber"}

def _tx5_color(c: Any) -> str:
    """标定颜色归一（led_rules.json 里 TX_STATE 写 'G'，Z11 写 'green'，两种都要认）。"""
    return _TX5_COLOR_WORDS.get(str(c or "").strip().upper(), "")

def _tx5_seq(spec: Dict[str, Any]) -> Tuple[str, ...]:
    seq: List[str] = []
    for l in spec.get("lamps") or []:
        c = _tx5_color(l.get("color"))
        if not c:
            return _TX5_DEFAULT_SEQ
        seq.append(c)
    return tuple(seq) or _TX5_DEFAULT_SEQ

def _tx5_axis(blobs: Sequence[Dict[str, Any]]) -> int:
    """0 = 横排（按 x 排序），1 = 竖排（按 y 排序）。"""
    xs = [float(b["xy"][0]) for b in blobs]
    ys = [float(b["xy"][1]) for b in blobs]
    if len(blobs) >= 2:
        dx, dy = max(xs) - min(xs), max(ys) - min(ys)
        if dy > 1.6 * max(1.0, dx):
            return 1
    return 0

def _tx5_sort(blobs: Sequence[Dict[str, Any]], axis: int) -> List[Dict[str, Any]]:
    if axis == 1:
        return sorted(blobs, key=lambda b: (b["xy"][1], b["xy"][0]))
    return sorted(blobs, key=lambda b: (b["xy"][0], b["xy"][1]))

def _tx5_fit(blobs: Sequence[Dict[str, Any]], seq: Sequence[str]
             ) -> Tuple[Optional[List[Tuple[int, Dict[str, Any]]]], float, str]:
    """把斑块对到 5 个灯位：颜色逐位相符 + 间距均匀（平移/缩放无关）。

    返回 ``(slots, cv, why)``；``slots`` 为 ``[(灯位序号, 斑块), ...]``，对不上返回 ``None``。
    做法：枚举"从 5 个灯位里选 n 个"的全部组合（n≤5，最多 32 种），只保留颜色逐位相符的，
    再取相邻间距/相隔灯位数变异系数（cv）最小的一种。cv ≤ 0.35 才算能对位。
    """
    n, N = len(blobs), len(seq)
    if n == 0 or n > N:
        return None, 9.9, "斑块数 %d 超出灯位数 %d" % (n, N)
    axis = _tx5_axis(blobs)
    order = _tx5_sort(blobs, axis)
    u = [float(b["xy"][axis]) for b in order]
    d = [u[k + 1] - u[k] for k in range(n - 1)]
    if any(x <= 0 for x in d):
        return None, 9.9, "斑块在排序轴上位置重复"
    best: Optional[Tuple[List[Tuple[int, Dict[str, Any]]], float]] = None
    for slots in itertools.combinations(range(N), n):
        if any((seq[slots[k]] or "") != (order[k].get("color") or "") for k in range(n)):
            continue
        cv = 0.0
        if n >= 3:
            gaps = [slots[k + 1] - slots[k] for k in range(n - 1)]
            ratio = [d[k] / float(gaps[k]) for k in range(n - 1)]
            mean = sum(ratio) / len(ratio)
            sd = (sum((x - mean) ** 2 for x in ratio) / len(ratio)) ** 0.5
            cv = sd / max(mean, 1e-6)
        elif n == 2:

            
            rr = float(order[0]["r"]) + float(order[1]["r"])
            if d[0] < 1.6 * max(rr, 1.0):
                continue
        if best is None or cv < best[1]:
            best = ([(slots[k], order[k]) for k in range(n)], cv)
    if best is None:
        return None, 9.9, "颜色序列对不上（期望 %s）" % "".join(_TX5_CN.get(c, "?") for c in seq)
    if best[1] > 0.35:
        return None, best[1], "灯间距不均匀（cv=%.2f）⇒ 不硬对灯位" % best[1]
    return best[0], best[1], ""

def _blob_tx5_lens(ctx: PhotoCtx, bgr: Optional[np.ndarray],
                   seed: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """在已检出灯簇附近，用**暗红透镜宽掩膜**补找"有灯罩但没亮"的红灯。

    ★ 只为"数亮红"服务：这些斑块一定 ``on=False``，用来确认"这颗红灯在、但没亮"，
    同时给灯位对位提供红端锚点。为了让宽掩膜不去吃画面里别的红棕色物体，
    只在已检出灯簇的 ROI（向两侧各扩 65% 跨度、上下各 5.5% 长边）内找。
    """
    if "lens" in ctx.blob:
        return ctx.blob["lens"]
    out: List[Dict[str, Any]] = []
    why = ""
    try:
        if LB is None:
            why = "lamp_blob 不可用"
        elif bgr is None or not seed:
            why = "没有灯簇种子（本张没检出红/绿亮点）"
        elif not hasattr(LB, "RED_LENS_RANGES"):
            why = "lamp_blob 版本不支持 RED_LENS_RANGES"
        else:
            h, w = bgr.shape[:2]
            xs = [float(b["xy"][0]) for b in seed]
            ys = [float(b["xy"][1]) for b in seed]
            span = max(1.0, max(xs) - min(xs))
            pad = max(48.0, 0.65 * span)
            hw = max(36.0, 0.055 * max(h, w))
            roi = [min(xs) - pad, min(ys) - hw,
                   (max(xs) - min(xs)) + 2 * pad, (max(ys) - min(ys)) + 2 * hw]
            got = LB.detect_lamps(bgr, roi=roi, colors=("red",),
                                  ranges={"red": list(LB.RED_LENS_RANGES)})
            out = [dict(b) for b in got if not b.get("on")]
            why = "ROI=%s 暗红灯罩 %d 个" % ([int(v) for v in roi], len(out))
    except Exception as exc:                                       
        out = []
        why = "暗红透镜检测异常（%s: %s）" % (type(exc).__name__, exc)
    ctx.blob["lens"] = out
    ctx.blob["lens_why"] = why
    return out

def _blob_merge(primary: Sequence[Dict[str, Any]],
                extra: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """合并两批斑块（同类同心 ⇒ 留先到的高置信那个；跨色过近 ⇒ 也去重）。"""
    out = [dict(b) for b in primary]
    for b in extra:
        dup = False
        for k in out:
            dist = math.hypot(b["xy"][0] - k["xy"][0], b["xy"][1] - k["xy"][1])
            same = (b.get("color") == k.get("color"))
            lim = (0.75 * (float(b["r"]) + float(k["r"])) if same
                   else 0.55 * max(float(b["r"]), float(k["r"])))
            if dist < lim:
                dup = True
                break
        if not dup:
            out.append(dict(b))
    out.sort(key=lambda b: (b["xy"][1], b["xy"][0]))
    return out

def _blob_tx5_layout(ctx: PhotoCtx, bgr: Optional[np.ndarray],
                     seq: Sequence[str]) -> Optional[Dict[str, Any]]:
    """Z11/TX5 五灯面板：先用 Hough 找 5 个灯罩位置，再把亮点按 x 映射到灯位。

    现场 20260428_041030：只亮 1 绿（本路）+1 红爆白芯（发射断），lamp_blob 0 个、
    led_panel 只有 2 个候选；旧逻辑判“只检出1个→不判”，结果页 0 行只剩问答。
    本函数不要求 5 个斑块：5 个灯位都有行，缺失=灭。
    """
    if bgr is None or len(seq) != 5:
        return None
    try:
        import cv2
        from soc_vision import led_panel as _LP
        cands = [c for c in _LP.detect_candidates(bgr) if getattr(c, "is_lamp", False)]
        if not cands:
            return None
        ys = [float(getattr(c, "y", 0)) for c in cands]
        ymed = sorted(ys)[len(ys) // 2]
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        y0 = max(0, int(ymed - 130))
        y1 = min(gray.shape[0], int(ymed + 130))
        crop = gray[y0:y1, :]
        circles = cv2.HoughCircles(crop, cv2.HOUGH_GRADIENT, dp=1, minDist=70,
                                   param1=60, param2=12, minRadius=5, maxRadius=40)
        if circles is None:
            return None
        arr = []
        for x, y, r in np.round(circles[0]).astype(int):
            yy = int(y) + y0
            if abs(yy - ymed) <= 75:
                arr.append((int(x), yy, int(r)))
        if len(arr) < 5:
            return None

        arr.sort(key=lambda t: (t[0], abs(t[1] - ymed)))

        arr.sort(key=lambda t: (abs(t[1] - ymed), t[0]))
        chosen = arr[:5]
        chosen.sort(key=lambda t: t[0])
        xs = [t[0] for t in chosen]

        gaps = [xs[i + 1] - xs[i] for i in range(4)]
        if min(gaps) < 40 or max(gaps) > 3 * max(1, min(gaps)):
            return None

        best = {}
        for c in cands:
            cx, cy = float(getattr(c, "x", 0)), float(getattr(c, "y", 0))
            slot = min(range(5), key=lambda i: abs(cx - xs[i]))
            if abs(cx - xs[slot]) > 0.65 * max(1, (xs[-1] - xs[0]) / 4.0):
                continue
            if slot in best and float(getattr(best[slot], "delta", 0)) >= float(getattr(c, "delta", 0)):
                continue
            best[slot] = c
        lamps = []
        for i in range(5):
            want_red = (seq[i] == "red")
            c = best.get(i)
            if c is not None:
                on = bool(float(getattr(c, "delta", 0)) >= 22.0)
                lamps.append({
                    "xy": [int(getattr(c, "x", xs[i])), int(getattr(c, "y", ymed))],
                    "r": float(getattr(c, "r", 8)), "color": ("red" if want_red else "green"),
                    "on": on, "center_v": float(getattr(c, "v_center", 0)),
                    "ring_v": float(getattr(c, "v_ring", 0)),
                    "delta_v": float(getattr(c, "delta", 0)) / 255.0,
                    "hsv": [0, float(getattr(c, "s_mean", 0)), float(getattr(c, "v_center", 0))],
                    "conf": 0.90, "area": 0.0, "fill": float(getattr(c, "fill", 0)),
                    "layout": "hough5",
                })
            else:
                lamps.append({
                    "xy": [int(xs[i]), int(ymed)], "r": 8.0,
                    "color": ("red" if want_red else "green"), "on": False,
                    "center_v": 0.0, "ring_v": 0.0, "delta_v": -0.12,
                    "hsv": [0, 0, 0], "conf": 0.80, "area": 0.0, "fill": 0.0,
                    "layout": "hough5_missing",
                })
        green_lit = sum(1 for i, c in enumerate(seq) if c == "green" and lamps[i]["on"])
        red_lit = sum(1 for i, c in enumerate(seq) if c == "red" and lamps[i]["on"])
        if red_lit > 0:
            verdict, why2 = "bad", "有 %d 颗亮红（发射断/故障 应为灭）⇒ 异常；绿亮 %d/3" % (red_lit, green_lit)
        elif green_lit >= 3:
            verdict, why2 = "normal", "绿亮 %d/3 + 0 亮红 ⇒ 符合（5 项）" % green_lit
        else:
            verdict, why2 = "missing", "绿亮 %d/3，缺 %d 颗 ⇒ 不满足「3 绿亮」" % (green_lit, 3 - green_lit)
        return {"status": "ok", "why": "Hough 五灯位 + 亮点映射（5 个灯位，缺失灯=灭）",
                "lamps": lamps, "n": 5, "green_lit": green_lit, "red_lit": red_lit,
                "green_n": 3, "red_n": 2, "verdict": verdict, "why2": why2,
                "seq": list(seq), "layout_x": xs, "blobs": lamps}
    except Exception:
        return None

def _blob_tx5_panel(ctx: PhotoCtx, spec: Dict[str, Any],
                    bgr: Optional[np.ndarray]) -> Dict[str, Any]:
    """五灯面板一次检测（Z11/TX_STATE 共用）：返回每个灯位的斑块 + 亮绿/亮红计数。"""
    cache = ctx.blob.setdefault("panels", {})
    if _TX5_PANEL_KEY in cache:
        return cache[_TX5_PANEL_KEY]
    seq = _tx5_seq(spec)
    panel: Dict[str, Any] = {"status": "none", "why": "", "seq": list(seq),
                             "lamps": [None] * len(seq), "n": 0,
                             "green_lit": 0, "red_lit": 0,
                             "green_n": sum(1 for c in seq if c == "green"),
                             "red_n": sum(1 for c in seq if c == "red"),
                             "verdict": "", "why2": "", "blobs": [], "lens_why": ""}

    def _done(msg: str) -> Dict[str, Any]:
        panel["why"] = msg
        cache[_TX5_PANEL_KEY] = panel
        return panel

    if LB is None:
        return _done("lamp_blob 模块不可用（%s）" % ("; ".join(BLOB_NOTES) or "import 失败"))
    if bgr is None:
        return _done("本张图解码失败 ⇒ 颜色亮点检测不可用")
    _lay = _blob_tx5_layout(ctx, bgr, seq)
    if _lay is not None:
        panel.update(_lay)
        cache[_TX5_PANEL_KEY] = panel
        return panel
    raw, why = _blob_raw(ctx, bgr, ("green", "red"))

    
    _lp_raw = _led_panel_raw(bgr, ("green", "red"))
    if len(_lp_raw) > len(raw or []):
        raw = _lp_raw
        why = "lamp_blob 不足 → led_panel 候选补足 %d 个斑块" % len(raw)
    if raw is None:
        return _done(why or "颜色亮点检测不可用")
    if not raw:
        return _done("画面里没有检出任何红/绿颜色亮点（五灯全灭或不在取景内）")
    lens = _blob_tx5_lens(ctx, bgr, raw)
    panel["lens_why"] = str(ctx.blob.get("lens_why") or "")
    blobs = _blob_merge(raw, lens)
    panel["blobs"] = [dict(b) for b in blobs]
    long_side = max(bgr.shape[:2])
    groups = (LB.group_lamps(blobs, long_side=long_side)
              if hasattr(LB, "group_lamps") else [list(blobs)])
    cands: List[Tuple[int, float, List[Dict[str, Any]], List[Tuple[int, Dict[str, Any]]]]] = []
    for g in groups:
        if not (1 <= len(g) <= len(seq)):
            continue
        slots, cv, _fwhy = _tx5_fit(g, seq)
        if slots is not None:
            cands.append((len(g), cv, list(g), slots))

    

    

    def _structural_ok(g: Sequence[Dict[str, Any]]) -> Tuple[bool, str]:
        if len(g) < 2:
            return False, "只检出 1 个红/绿斑块 ⇒ 无法确认这是五灯面板，不判"
        if ctx.screen is not None:
            try:
                sx0, sy0, sx1, sy1 = [float(v) for v in ctx.screen.rect]
                inside = sum(1 for b in g if sx0 - 4 <= b["xy"][0] <= sx1 + 4
                             and sy0 - 4 <= b["xy"][1] <= sy1 + 4)
                if inside * 2 >= len(g):
                    return False, ("检出斑块 %d/%d 落在显示屏画面内（rect=%s）⇒ 那是画面内容、"
                                   "不是面板指示灯，不判"
                                   % (inside, len(g), [int(v) for v in ctx.screen.rect]))
            except Exception:                                       
                pass
        axis0 = _tx5_axis(g)
        us = [float(b["xy"][axis0]) for b in g]
        span = max(us) - min(us)
        med = sorted(float(b["r"]) for b in g)[len(g) // 2]
        band = [float(b["xy"][1 - axis0]) for b in g]        
        if (max(band) - min(band)) > max(3.5 * med, 0.02 * max(bgr.shape[:2])):
            return False, ("检出斑块上下散得太开（%.0f px，灯排应基本成一条线）⇒ 不像灯排，不判"
                           % (max(band) - min(band)))
        if span < 3.0 * med:
            return False, ("检出斑块挤在一起（跨度 %.0f px ≈ %.1f×r）⇒ 不像一排灯，不判"
                           % (span, span / max(med, 1e-6)))
        return True, ""

    picked = None
    why_rej = ""
    if cands:
        cands.sort(key=lambda c: (-c[0], c[1]))       
        for n_best, cv, g, slots in cands:
            ok, gw = _structural_ok(g)
            if not ok:
                why_rej = gw
                continue
            picked = (n_best, cv, g, slots)
            break
    if picked is not None:
        n_best, cv, g, slots = picked
        for slot, b in slots:
            panel["lamps"][slot] = b
        panel["status"] = "ok" if n_best == len(seq) else "partial"
        panel["why"] = ("灯位对位成功（%d/%d 颗，间距 cv=%.2f）" % (n_best, len(seq), cv))
    else:

        
        gi = [i for i, c in enumerate(seq) if c == "green"]
        ri = [i for i, c in enumerate(seq) if c == "red"]
        greens = [b for b in _tx5_sort(blobs, _tx5_axis(blobs)) if b.get("color") == "green"]
        reds = [b for b in _tx5_sort(blobs, _tx5_axis(blobs)) if b.get("color") == "red"]
        if len(blobs) > len(seq) or not (greens or reds):
            return _done("检出 %d 个红/绿斑块，无法对应到 %d 灯面板（不硬凑）；%s"
                         % (len(blobs), len(seq), why_rej))
        if len(blobs) < 2:
            return _done("只检出 1 个红/绿斑块 ⇒ 无法确认这是五灯面板，不判")
        if ctx.screen is not None:                 
            try:
                sx0, sy0, sx1, sy1 = [float(v) for v in ctx.screen.rect]
                inside = sum(1 for b in blobs if sx0 - 4 <= b["xy"][0] <= sx1 + 4
                             and sy0 - 4 <= b["xy"][1] <= sy1 + 4)
                if inside * 2 >= len(blobs):
                    return _done("检出斑块 %d/%d 落在显示屏画面内 ⇒ 那是画面内容、不是面板指示灯，不判"
                                 % (inside, len(blobs)))
            except Exception:                                       
                pass

        
        if len(greens) == len(gi):
            for i, b in zip(gi, greens):
                panel["lamps"][i] = b
        if len(reds) == len(ri):
            for i, b in zip(ri, reds):
                panel["lamps"][i] = b
        elif len(reds) == 1:

            
            panel["lamps"][ri[0]] = reds[0]
            panel["ambig_red"] = True
        panel["status"] = "fallback"
        panel["why"] = ("灯位对位失败 ⇒ 绿%d/红%d 颗，仅在颗数对得上时按顺序映射（可能错位）"
                        % (len(greens), len(reds)))

    for i, c in enumerate(seq):
        if c == "red" and panel["lamps"][i] is None:
            panel["lamps"][i] = {
                "xy": [0, 0], "r": 0.0, "color": "red", "on": False,
                "center_v": 0.0, "ring_v": 0.0, "delta_v": -0.12,
                "hsv": [0, 0, 0], "conf": 0.80, "area": 0.0, "fill": 0.0,
                "synthetic_off": True,
            }
    panel["n"] = sum(1 for b in panel["lamps"] if b is not None)
    panel["green_lit"] = sum(1 for i, c in enumerate(seq)
                             if c == "green" and panel["lamps"][i] is not None
                             and panel["lamps"][i].get("on"))
    panel["red_lit"] = sum(1 for i, c in enumerate(seq)
                           if c == "red" and panel["lamps"][i] is not None
                           and panel["lamps"][i].get("on"))
    gl, gn, rl, rn = (panel["green_lit"], panel["green_n"],
                      panel["red_lit"], panel["red_n"])
    if rl > 0:
        panel["verdict"] = "bad"
        panel["why2"] = ("有 %d 颗亮红（发射断/故障 应为灭）⇒ 异常；绿亮 %d/%d" % (rl, gl, gn))
    elif gl >= gn:
        panel["verdict"] = "normal"
        panel["why2"] = "绿亮 %d/%d + 0 亮红 ⇒ 符合（%d 项）" % (gl, gn, gn + rn)
    else:
        panel["verdict"] = "missing"
        panel["why2"] = "绿亮 %d/%d，缺 %d 颗 ⇒ 不满足「3 绿亮」" % (gl, gn, max(0, gn - gl))
    cache[_TX5_PANEL_KEY] = panel
    return panel

def _eval_tx5_lamp(it: Item, ctx: PhotoCtx, spec: Dict[str, Any], idx_s: str,
                   ts: str, photo: str, bgr: Optional[np.ndarray]) -> Evidence:
    """Z11/TX_STATE 逐灯条目：从五灯面板结论取本灯位（Z11 与 TX_STATE 走**同一套**逻辑）。"""
    pid = str(spec["id"])
    lamps = spec.get("lamps") or []
    seq = _tx5_seq(spec)
    need = len(lamps)
    panel = _blob_tx5_panel(ctx, spec, bgr)
    counts = ("面板计数：绿亮 %d/%d、亮红 %d/%d（%s）"
              % (panel["green_lit"], panel["green_n"], panel["red_lit"], panel["red_n"],
                 panel.get("why2") or panel.get("why") or "-"))
    if panel["status"] == "none":
        return _undet(it, "%s；%s" % (counts, panel.get("why") or "五灯面板未定位"), ts, photo)

    def _where() -> str:
        bits = []
        for i in range(min(need, len(seq))):
            b = panel["lamps"][i]
            bits.append("%s%s" % (lamps[i].get("name") or ("#%d" % i),
                                  ("(%d,%d)" % (b["xy"][0], b["xy"][1])) if b else "(未检出)"))
        return "灯位：" + "、".join(bits)

    if idx_s == "*":
        bad = [i for i in range(min(need, len(seq)))
               if str(lamps[i].get("expect") or "any") in ("on", "off")
               and ("on" if (panel["lamps"][i] or {}).get("on") else "off") != lamps[i]["expect"]]
        return Evidence(part=it.part, route=it.route, field=it.field,
                        value="off" if bad else "on",
                        confidence=0.75 if panel["status"] == "ok" else 0.6,
                        evidence="%s；%s；整排 %d 颗里 %d 颗不符合"
                                 % (counts, panel.get("why") or "", need, len(bad)),
                        ts=ts, item_no=it.key, category=it.category, check_item=it.item,
                        rule="led_row:" + pid, photo=photo, display=it.display,
                        metrics={"tx5_panel": {k: panel[k] for k in
                                               ("status", "green_lit", "red_lit",
                                                "green_n", "red_n", "verdict", "why", "why2")}})
    if not idx_s.isdecimal():
        return _undet(it, "灯位描述 %r 的序号不是纯数字（占位符）⇒ 不把灯位对应到条目"
                      % (it.binding_ref,), ts, photo)
    idx = int(idx_s)
    if idx >= need or idx >= len(seq):
        return _undet(it, "部件 %s 只有 %d 个灯位，越界" % (pid, need), ts, photo)
    obs = panel["lamps"][idx]
    lp = lamps[idx]
    col = seq[idx]
    cn = _TX5_CN.get(col, "?")
    expect = str(lp.get("expect") or "any")
    expect_cn = {"on": "应亮", "off": "应灭"}.get(expect, expect)
    if obs is not None:
        on = bool(obs.get("on"))
        value = "on" if on else "off"
        conf = float(obs.get("conf") or 0.0)
        if ctx.scene.soft:
            conf *= 0.85
        _amb = ("（红灯组只检出 1 颗，可能与「故障」互换）"
                if (col == "red" and panel.get("ambig_red")) else "")
        why = ("第 %d/%d 位「%s」（%s灯、%s）颜色亮点实测**%s**：位置 (%d,%d)、r=%.1f、"
               "中心 V=%.0f、环带 V=%.0f、delta=%+.0f%s"
               % (idx + 1, need, lp.get("name"), cn, expect_cn, "亮" if on else "灭",
                  obs["xy"][0], obs["xy"][1], float(obs["r"]),
                  float(obs["center_v"]) * 255, float(obs["ring_v"]) * 255,
                  float(obs["delta_v"]) * 255, _amb))
        src = "lamp_blob.tx5"
    elif panel.get("status") == "fallback":

        return _undet(it, "第 %d/%d 位「%s」：灯位对位失败（%s），本灯位无法与检出斑块对应 ⇒ 不判；%s"
                      % (idx + 1, need, lp.get("name"), panel.get("why") or "-", counts),
                      ts, photo)
    else:
        value = "off"
        if col == "green":
            conf = 0.55
            why = ("第 %d/%d 位「%s」**未检出绿灯罩**（亮着的绿指示灯一定会被颜色亮点检出）"
                   "⇒ 判「灭」＝缺 %d 颗之一"
                   % (idx + 1, need, lp.get("name"), max(0, panel["green_n"] - panel["green_lit"])))
        else:
            conf = 0.60
            why = ("第 %d/%d 位「%s」未检出红灯罩（暗红透镜太暗）；红灯只判「有没有亮的红」"
                   "⇒ 本颗无亮红证据 ⇒ 判「灭」" % (idx + 1, need, lp.get("name")))
        src = "lamp_blob.tx5(absent)"
    return Evidence(part=it.part, route=it.route, field=it.field, value=value,
                    confidence=round(min(0.9, max(0.0, conf)), 3),
                    evidence="%s；%s；%s" % (why, counts, _where()),
                    ts=ts, item_no=it.key, category=it.category, check_item=it.item,
                    rule="led:%s#%d" % (pid, idx), photo=photo, display=it.display,
                    metrics={"lamp": obs if obs is not None else None,
                             "lamp_meta": {"name": lp.get("name"), "color": col, "expect": expect},
                             "src": src,
                             "tx5_panel": {k: panel[k] for k in
                                           ("status", "green_lit", "red_lit", "green_n",
                                            "red_n", "verdict", "why", "why2")}})

@dataclass
class ScreenMetrics:
    mean_v: float = 0.0
    p50_v: float = 0.0
    p95_v: float = 0.0
    dark_frac: float = 0.0
    bright_frac: float = 0.0
    blown_frac: float = 0.0
    yellow_frac: float = 0.0
    green_frac: float = 0.0
    sat_mean: float = 0.0
    edge_density: float = 0.0
    hf_energy: float = 0.0
    line_frac: float = 0.0
    texture: float = 0.0
    periodicity: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {k: round(float(v), 4) for k, v in asdict(self).items()}

@dataclass
class ScreenObs:
    rect: Tuple[int, int, int, int]
    area_frac: float
    hint: str
    metrics: ScreenMetrics = dc_field(default_factory=ScreenMetrics)
    state: str = "undetermined"
    confidence: float = 0.0
    evidence: str = ""
    extra: Dict[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"rect": list(self.rect), "area_frac": round(self.area_frac, 4),
                "hint": self.hint, "state": self.state,
                "confidence": round(self.confidence, 3), "evidence": self.evidence,
                "metrics": self.metrics.to_dict(), "extra": self.extra}

def _screen_masks(hsv: np.ndarray) -> Dict[str, np.ndarray]:
    """屏幕候选掩膜。阈值全部按现场 119 张真图实测：

    * ``blown``  —— 过曝亮面：黄屏实测屏内 V 中位数 254（阈值 V>0.80）
    * ``gold``   —— 黄调面：hue 30~80、S>0.10（黄屏实测 S 只有 0.16，不能用 0.28）
    * ``dark``   —— 黑屏/关机
    * ``grid``   —— 绿色网格（雷达显示）
    """
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    return {
        "blown": v > TH["blown_v"],
        "gold": (h >= 30) & (h <= 80) & (s > 0.10) & (v > 0.45),
        "dark": v < 0.13,
        "grid": (h >= 70) & (h <= 175) & (s > 0.15) & (v > 0.20),
    }

def find_screen(bgr: np.ndarray) -> Optional[ScreenObs]:
    """找画面里最像"一块显示屏"的矩形区域。

    四类提示（blown / gold / dark / grid）各出一批连通域，统一过三关：
      ① 面积 ≥ 画面 5.5%  ② 长宽比 0.55~3.4  ③ 矩形化程度
    （实心屏 fill≥0.65；网格屏 fill≥0.18 且 bbox 内绿色像素 ≥12%）。
    通过者按 **bbox 面积** 择优 —— 屏幕是画面里最大的一块规整面。

    为什么不靠固定 ROI：现场是手持/斜拍，同一台屏在两张照片里位置完全不同（实测）；
    为什么不靠"最亮区域"：糊片/白墙整幅都亮（实测 5 张糊片 V>0.8 占满画面）。
    """
    scale = min(1.0, float(TH["screen_work_long"]) / max(bgr.shape[:2]))
    small = bgr if scale >= 1.0 else np.asarray(
        Image.fromarray(bgr[:, :, ::-1]).resize((max(8, int(bgr.shape[1] * scale)),
                                                 max(8, int(bgr.shape[0] * scale))), Image.BILINEAR))[:, :, ::-1]
    hsv = bgr_to_hsv(small)
    v = hsv[:, :, 2] * 255.0
    masks = _screen_masks(hsv)
    best = None
    for hint, m in masks.items():
        mm = _close(m, 1 if hint == "dark" else 2)
        n_img = float(mm.size)
        for cc in label_components(mm, min_area=int(0.03 * n_img))[:6]:
            bbox_frac = (cc["w"] * cc["h"]) / n_img
            if bbox_frac < TH["screen_min_area_frac"]:
                continue
            if bbox_frac > 0.92:              
                continue
            asp = cc["w"] / float(max(1, cc["h"]))
            if not (TH["screen_aspect_lo"] <= asp <= TH["screen_aspect_hi"]):
                continue
            fill = cc["fill"]
            if hint == "grid":
                gf = float(m[cc["y0"]:cc["y1"] + 1, cc["x0"]:cc["x1"] + 1].mean())
                if fill < TH["screen_fill_grid"] or gf < TH["grid_green_frac_min"]:
                    continue
            else:
                if fill < TH["screen_fill_solid"]:
                    continue

            ring = _frame_stats(v, cc["x0"], cc["y0"], cc["x1"], cc["y1"], ratio=0.10)
            inner = float(v[cc["y0"]:cc["y1"] + 1, cc["x0"]:cc["x1"] + 1].mean())

            
            if hint == "blown" and inner < 150:
                continue
            if hint == "gold" and inner < 90:
                continue
            if hint == "grid" and inner < 80:          
                continue
            if hint == "dark" and not (inner <= 45 and (ring or 0) >= inner + 20):
                continue
            if hint in ("blown", "gold"):
                b = (slice(cc["y0"], cc["y1"] + 1), slice(cc["x0"], cc["x1"] + 1))
                tint = float(masks["gold"][b].mean())
                grn = float(masks["grid"][b].mean())
                if tint < 0.20 and grn < 0.10:
                    continue                          
            contrast = abs(inner - ring) if ring is not None else 0.0
            score = bbox_frac * (1.0 + 0.25 * min(1.0, contrast / 60.0))
            if best is None or score > best[0]:
                best = (score, hint, cc, bbox_frac, ring, inner, fill)
    if best is None:
        return None
    score, hint, cc, bbox_frac, ring, inner, fill = best
    x0, y0 = int(cc["x0"] / scale), int(cc["y0"] / scale)
    x1, y1 = int(cc["x1"] / scale), int(cc["y1"] / scale)
    crop = bgr[y0:y1 + 1, x0:x1 + 1]
    met = screen_metrics(crop)
    so = ScreenObs(rect=(x0, y0, x1, y1), area_frac=float((x1 - x0 + 1) * (y1 - y0 + 1)) / float(bgr.shape[0] * bgr.shape[1]),
                   hint=hint, metrics=met)
    so.extra = {"frame_ring_v": round(float(ring or 0), 1), "inner_v": round(inner, 1),
                "detect_scale": round(scale, 3), "fill": round(fill, 3),
                "bbox_frac": round(bbox_frac, 3)}
    so.state, so.confidence, so.evidence = classify_screen(met, hint)
    return so

def _frame_stats(v: np.ndarray, x0: int, y0: int, x1: int, y1: int, ratio: float = 0.1):
    h, w = v.shape[:2]
    pad = max(2, int(ratio * max(1, x1 - x0 + 1)))
    ax0, ay0 = max(0, x0 - pad), max(0, y0 - pad)
    ax1, ay1 = min(w - 1, x1 + pad), min(h - 1, y1 + pad)
    pad_top = v[ay0:y0, ax0:ax1 + 1]
    pad_bot = v[y1 + 1:ay1 + 1, ax0:ax1 + 1]
    pad_left = v[ay0:ay1 + 1, ax0:x0]
    pad_right = v[ay0:ay1 + 1, x1 + 1:ax1 + 1]
    vals = [p.ravel() for p in (pad_top, pad_bot, pad_left, pad_right) if p.size]
    if not vals:
        return None
    return float(np.concatenate(vals).mean())

def screen_metrics(crop_bgr: np.ndarray) -> ScreenMetrics:
    """屏幕内部统计量（亮度分布/颜色直方图/纹理/边缘），全部只用 numpy。"""
    if crop_bgr.size == 0:
        return ScreenMetrics()
    c = crop_bgr

    if c.shape[1] > 512 or c.shape[0] > 512:
        k = 512.0 / max(c.shape[:2])
        c = np.asarray(Image.fromarray(c[:, :, ::-1]).resize(
            (max(8, int(c.shape[1] * k)), max(8, int(c.shape[0] * k))), Image.BILINEAR))[:, :, ::-1]
    hsv = bgr_to_hsv(c)
    h, s, v01 = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    v = v01 * 255.0
    g = v.mean(axis=2) if v.ndim == 3 else v
    m = ScreenMetrics()
    m.mean_v = float(g.mean())
    m.p50_v = float(np.percentile(g, 50))
    m.p95_v = float(np.percentile(g, 95))
    m.dark_frac = float((g < 40).mean())
    m.bright_frac = float((g > 170).mean())
    m.blown_frac = float((v01 > TH["blown_v"]).mean())
    m.yellow_frac = float(((h >= 30) & (h <= 80) & (s > 0.08) & (v01 > 0.45)).mean())
    m.green_frac = float(((h >= 70) & (h <= 175) & (s > 0.15) & (v01 > 0.16)).mean())
    m.sat_mean = float(s.mean())
    gm = grad_mag(g)
    m.edge_density = float((gm > 24.0).mean())

    blur = box_mean(g, 5)
    m.hf_energy = float(np.abs(g - blur).mean()) / 255.0

    

    gb = box_mean(g, 3)
    hy = np.abs(np.diff(gb, axis=0))
    hx = np.abs(np.diff(gb, axis=1))
    rp = hy.sum(axis=1)
    cp = hx.sum(axis=0)
    rows_hit = float((rp > 2.5 * (np.median(rp) + 1e-6)).mean())
    cols_hit = float((cp > 2.5 * (np.median(cp) + 1e-6)).mean())
    m.line_frac = float(rows_hit + cols_hit)

    m.texture = float(np.abs(g - box_mean(g, 3)).mean()) / 255.0

    prof = g.mean(axis=1)
    prof = prof - prof.mean()
    if prof.std() > 1e-6:
        ac = np.correlate(prof, prof, mode="full")[len(prof) - 1:]
        ac = ac / (ac[0] + 1e-9)
        lo = max(3, len(ac) // 40)
        hi = max(lo + 1, len(ac) // 3)
        m.periodicity = float(np.max(ac[lo:hi])) if hi > lo else 0.0
    return m

def classify_screen(m: ScreenMetrics, hint: str = "") -> Tuple[str, float, str]:
    """屏幕判态。顺序即优先级；每条都给出可审计的"为什么"。

    实测口径（见 README_vision.md 标定表）
      * 黑屏：V 均亮 ≤26、暗像素 ≥82%、亮像素 ≤0.4%、高频 <0.012
      * 黄屏：过曝亮像素 ≥45% 且黄调像素 ≥25%（现场黄屏：p50 V=254、S=0.16）
      * 花屏：高频 ≥0.055 且边缘密度 ≥0.11 且无长线结构
      * 不扫描：纹理 ≤0.010（屏亮但一点扫描噪声都没有）
      * 无回波：亮像素 ≤0.12%（有底噪、没有亮回波）
      * 正常：长线结构 ≥0.02 且有亮回波
    """

    if hint == "dark" and (m.mean_v > TH["black_mean_v"] or m.dark_frac < TH["black_dark_frac"]):
        return ("undetermined", 0.35,
                "暗区均亮 %.0f、暗像素 %.0f%% 未达黑屏级（≤%.0f / ≥%.0f%%）⇒ 不判"
                % (m.mean_v, m.dark_frac * 100, TH["black_mean_v"], TH["black_dark_frac"] * 100))

    if (m.mean_v <= TH["black_mean_v"] and m.dark_frac >= TH["black_dark_frac"]
            and m.bright_frac <= TH["black_bright_frac"] and m.hf_energy < 0.012):
        conf = 0.95 if m.mean_v < 18 else 0.86
        return ("black_screen", conf,
                "全屏均亮 %.0f（阈值≤%.0f）、暗像素 %.0f%%（≥%.0f%%）、亮像素 %.2f%%、高频 %.3f → 黑屏"
                % (m.mean_v, TH["black_mean_v"], m.dark_frac * 100, TH["black_dark_frac"] * 100,
                   m.bright_frac * 100, m.hf_energy))

    if (m.blown_frac >= TH["blown_frac"] and m.yellow_frac >= TH["yellow_tint_frac"]
            and m.mean_v >= TH["yellow_mean_v"]):
        conf = 0.90 if (m.blown_frac >= 0.60 and m.yellow_frac >= 0.45) else 0.72
        return ("yellow_screen", conf,
                "过曝亮像素 %.0f%%（≥%.0f%%）、黄调像素 %.0f%%（≥%.0f%%）、均亮 %.0f、线结构 %.2f → 黄屏"
                % (m.blown_frac * 100, TH["blown_frac"] * 100, m.yellow_frac * 100,
                   TH["yellow_tint_frac"] * 100, m.mean_v, m.line_frac))

    if (m.hf_energy >= TH["hf_garbled"] and m.edge_density >= TH["edge_garbled"]
            and m.line_frac < 0.30):
        conf = 0.70 if m.hf_energy >= 1.3 * TH["hf_garbled"] else 0.58
        return ("garbled", conf,
                "高频 %.3f（阈值≥%.3f）、边缘密度 %.2f（≥%.2f）、线结构 %.2f → 花屏"
                % (m.hf_energy, TH["hf_garbled"], m.edge_density, TH["edge_garbled"], m.line_frac))

    

    if m.texture <= 0.6 * TH["scan_texture_min"] and m.hf_energy <= 0.020:
        return ("no_scan", 0.62,
                "纹理 %.4f（阈值≤%.4f）、高频 %.3f → 不扫描（屏亮但无扫描纹理）"
                % (m.texture, 0.6 * TH["scan_texture_min"], m.hf_energy))

    if m.bright_frac <= TH["echo_weak_min"]:
        return ("no_echo", 0.60,
                "亮像素 %.3f%%（阈值≤%.3f%%）→ 无回波（有底噪、无亮回波）"
                % (m.bright_frac * 100, TH["echo_weak_min"] * 100))
    if m.bright_frac < TH["echo_bright_min"]:
        return ("no_echo", 0.55,
                "亮像素 %.3f%% 低于正常下限 %.3f%% → 回波很弱"
                % (m.bright_frac * 100, TH["echo_bright_min"] * 100))

    if (m.bright_frac >= TH["echo_bright_min"] and m.mean_v >= 45.0
            and m.green_frac >= TH["screen_green_min"]):
        conf = min(0.85, 0.58 + 0.25 * min(1.0, m.bright_frac / (6 * TH["echo_bright_min"])))
        return ("ok", conf,
                "亮回波 %.2f%%（≥%.2f%%）、绿内容 %.0f%%、纹理 %.4f、线结构 %.2f → 画面正常"
                % (m.bright_frac * 100, TH["echo_bright_min"] * 100, m.green_frac * 100,
                   m.texture, m.line_frac))
    return ("undetermined", 0.40,
            "证据不足：均亮 %.0f、过曝 %.0f%%、黄 %.0f%%、绿 %.0f%%、高频 %.3f、亮 %.2f%%（hint=%s）"
            % (m.mean_v, m.blown_frac * 100, m.yellow_frac * 100, m.green_frac * 100,
               m.hf_energy, m.bright_frac * 100, hint or "-"))

METER_FIELDS = {
    "meter_antenna_direction": {"label": "天线方向", "ok": ("正常", "方向左", "方向右", "左", "右")},
    "meter_self_test": {"label": "自检状态", "ok": ("正常", "自检30", "自检40")},
}

METER_ENABLE = os.environ.get("VISION_METER", "0") == "1"
METER_TIMEOUT_S = 20.0
_METER_READER = None
_METER_ERR = ""
_METER_SLOW = False

def set_meter(enabled: bool) -> None:
    global METER_ENABLE
    METER_ENABLE = bool(enabled)
    if enabled:
        os.environ["VISION_METER"] = "1"

def read_meter(bgr: np.ndarray, which: str, ref_dir: str = "") -> Tuple[str, float, str]:
    """微表区读数。走复用模块 `ScreenReaderV2`；未启用/缺模板/低置信/太慢 一律返回 undetermined。"""
    global _METER_READER, _METER_ERR, _METER_SLOW
    spec = METER_FIELDS.get(which)
    if not spec:
        return "undetermined", 0.0, "未知微表字段 %s" % which
    if not METER_ENABLE:
        return "undetermined", 0.0, ("微表区读数未启用：`cn_grid_v2.json` 是板端固定机位标定，"
                                     "套手持照片不可用（--meter / VISION_METER=1 才跑）")
    if _METER_SLOW:
        return "undetermined", 0.0, "微表区读数器已因超时停用（>%.0fs/次）" % METER_TIMEOUT_S
    if SRV2 is None:
        return "undetermined", 0.0, "复用模块 screen_read_v2 不可用（%s）" % ("; ".join(IMPORT_NOTES) or "import 失败")
    if _METER_READER is None:
        try:
            _METER_READER = SRV2.ScreenReaderV2(ref_dir or "", verbose=False)
        except Exception as exc:
            _METER_ERR = "ScreenReaderV2 初始化失败：%s" % exc
            _METER_READER = False
    if _METER_READER is False:
        return "undetermined", 0.0, "微表区读数器未就绪：%s（缺 cn_grid_v2.json / cn_bank_real2.npz 参考模板）" % _METER_ERR
    t0 = time.time()
    try:
        res = _METER_READER.read(bgr[:, :, ::-1].copy())
        f = _METER_READER.fields(res)
    except Exception as exc:
        return "undetermined", 0.0, "微表区读数失败：%s" % exc
    finally:
        dt = time.time() - t0
        if dt > METER_TIMEOUT_S:
            _METER_SLOW = True
    got = f.get(spec["label"]) or {}
    val, conf = str(got.get("value") or ""), float(got.get("conf") or 0.0)
    if not val or val in ("?", ""):
        return "undetermined", 0.0, "微表区 %s 未读出字形" % spec["label"]
    if val not in spec["ok"]:
        return "undetermined", min(conf, 0.4), "微表区读到 %r，不在本字段允许取值内（%s）⇒ 不判" % (val, "/".join(spec["ok"]))
    if conf < TH["conf_min"]:
        return "undetermined", conf, "微表区 %s=%r 但置信 %.2f < %.2f ⇒ 不判" % (spec["label"], val, conf, TH["conf_min"])
    return val, conf, "微表区 %s=%s（逐格模板匹配置信 %.2f）" % (spec["label"], val, conf)

@dataclass
class Evidence:
    part: str
    route: str
    field: str
    value: str
    confidence: float
    evidence: str
    ts: str
    modality: str = "vision"
    item_no: str = ""
    category: str = ""
    check_item: str = ""
    rule: str = ""
    state: str = "decided"
    route_mirrored: bool = False
    display: str = ""

    

    
    decided_by: str = ""
    hint: str = ""
    metrics: Dict[str, Any] = dc_field(default_factory=dict)
    photo: str = ""
    engine: str = VER_ENGINE
    source: str = "vision_rules"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["confidence"] = round(float(self.confidence), 3)
        d["state"] = "undetermined" if self.value == "undetermined" else "decided"
        return d

def _undet(it: Item, why: str, ts: str, photo: str = "", part: str = "", route: str = "") -> Evidence:
    return Evidence(part=part or it.part, route=route if route != "" else it.route, field=it.field,
                    value="undetermined", confidence=0.0, evidence=why, ts=ts,
                    item_no=it.key, category=it.category, check_item=it.item, rule=it.binding,
                    photo=photo, display=it.display)

def _choose_lamp(row: LampRow, need: int, idx: int) -> Tuple[Optional[LampObs], str]:
    """在一排灯里按规则序号取灯；灯数不符就直接放弃（不猜）。"""
    if row is None:
        return None, "未找到灯行"
    if len(row.obs) != need:
        return None, "灯行检测到 %d 个灯位，规则要求 %d ⇒ 不把灯位对应到条目" % (len(row.obs), need)
    if not (0 <= idx < len(row.obs)):
        return None, "灯序号 %d 越界（本行 %d 灯）" % (idx, len(row.obs))
    return row.obs[idx], ""

_PARTS_CACHE: Optional[Dict[str, Dict[str, Any]]] = None
WARNINGS: List[str] = []          

def _warn(msg: str) -> str:
    """显式 WARN：打到 stderr + 记进 ``WARNINGS``（结果 JSON 的 debug.warnings 也带一份）。

    ★ 修复点（Bug1）：旧 ``parts_table()`` 用 ``except Exception: pass`` 把
    ``LR.RuleBook()`` 的 TypeError 静默吞掉 ⇒ 每个进程都退回 7 部件兜底表，
    用户 14:45 刚确认的 25 部件标定（Z12/Z14/Z15/Z18/Z31 灯序+坐标）根本没被读到。
    现在任何退化都必须**报出来**，绝不静默。
    """
    line = "[WARN] %s" % msg
    if line not in WARNINGS:
        WARNINGS.append(line)
        try:
            print(line, file=sys.stderr, flush=True)
        except Exception:                                          
            pass
    return line

def _rules_json() -> Dict[str, Any]:
    """读 config/led_rules.json **原文**：RuleBook 只留判定字段，标定坐标/dim 只在原文里。"""
    if LR is None:
        return {}
    p = str(getattr(LR, "DEFAULT_RULES_PATH", "") or "")
    if not p or not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:                                       
        _warn("读 led_rules.json 原文失败（%s: %s）⇒ 逐灯标定坐标不可用，只能靠成排灯结构取灯"
              % (type(exc).__name__, exc))
        return {}

def parts_table() -> Dict[str, Dict[str, Any]]:
    """复用 led_rules 的部件表（config/led_rules.json，25 个部件）。

    ★ 2026-10-18 修复（Bug1）：
      1. 旧代码 ``LR.RuleBook()`` **少传必填参数 ``parts``** ⇒ TypeError；
      2. 该异常被 ``except Exception: pass`` 吞掉 ⇒ 永远退回下面 7 部件兜底表
         ⇒ Z12_PWR / Z14_PANEL / Z15_PANEL / PS_WENYA / ANT_DIR 之外的新标定读不到。
    正确构造方式是 **``LR.RuleBook.load()``**（``led_rules.RuleBook.__init__(self, parts)``
    只接受已解析的 PartRule 列表；从文件读是 classmethod ``load(path=None)``）。
    失败时**显式 WARN + 报出"已退回 7 部件兜底表"**，不再静默。
    """
    global _PARTS_CACHE
    if _PARTS_CACHE is not None:
        return _PARTS_CACHE
    if LR is None:
        _warn("soc_vision.led_rules 不可用（%s）⇒ parts_table 退回内置 7 部件兜底表："
              "Z12/Z14/Z15/Z18/Z31 的灯序与标定坐标全部不可用"
              % ("; ".join(IMPORT_NOTES) or "import 失败"))
        _PARTS_CACHE = _FALLBACK_PARTS
        return _PARTS_CACHE
    try:
        book = LR.RuleBook.load()          
        raw = _rules_json()
        raw_parts = {str(p.get("id", "")): p for p in (raw.get("parts") or [])}
        calib_size: Dict[str, Tuple[float, float]] = {}
        for ph in (raw.get("calib_meta") or {}).get("photos") or []:
            sz = ph.get("size") or []
            if len(sz) == 2 and ph.get("part"):
                calib_size[str(ph["part"])] = (float(sz[0]), float(sz[1]))
        out: Dict[str, Dict[str, Any]] = {}
        for p in getattr(book, "parts", []) or []:
            pid = str(getattr(p, "pid", ""))
            rp = raw_parts.get(pid) or {}
            rl = rp.get("lamps") or []
            lamps: List[Dict[str, Any]] = []
            for i, l in enumerate(p.lamps or []):
                d: Dict[str, Any] = {"name": l.name, "color": getattr(l, "color", "?"),
                                     "expect": getattr(l, "expect", "any"),
                                     "fault_if_on": bool(getattr(l, "fault_if_on", False))}
                r = rl[i] if (i < len(rl) and isinstance(rl[i], dict)) else {}
                m = r.get("measured") if isinstance(r.get("measured"), dict) else {}
                xy = (m or {}).get("photo_xy") or []
                if len(xy) == 2:
                    d["photo_xy"] = [float(xy[0]), float(xy[1])]
                for k in ("role", "dim", "visual_reliable", "qa_required"):
                    if k in r:
                        d[k] = r[k]
                    elif k in (m or {}):
                        d[k] = m[k]
                if r.get("note"):
                    d["note"] = r["note"]
                lamps.append(d)
            info: Dict[str, Any] = {"id": pid, "name": p.name, "kind": getattr(p, "kind", ""),
                                    "lamps": lamps}
            if pid in calib_size:
                info["calib_photo_size"] = calib_size[pid]
            for k in ("layout", "note", "status", "route"):
                if k in rp:
                    info[k] = rp[k]
            out[pid] = info
        if not out:
            raise RuntimeError("RuleBook.load() 返回 0 个部件（%s）"
                               % (getattr(LR, "DEFAULT_RULES_PATH", "?"),))
    except Exception as exc:                                       
        _warn("parts_table 读 config/led_rules.json 失败（%s: %s）⇒ 已退回内置 7 部件兜底表："
              "Z12/Z14/Z15/Z18/Z31 的灯序与标定坐标全部不可用（要修的是配置读取，不是判据）"
              % (type(exc).__name__, exc))
        _PARTS_CACHE = _FALLBACK_PARTS
        return _PARTS_CACHE
    if len(out) <= len(_FALLBACK_PARTS):
        _warn("parts_table 只读到 %d 个部件（<= 兜底表 %d 个）：规则表疑似退回旧版，"
              "请核对 config/led_rules.json" % (len(out), len(_FALLBACK_PARTS)))
    _PARTS_CACHE = out
    return _PARTS_CACHE

def _led_rules_parts() -> Dict[str, Dict[str, Any]]:
    """兼容旧名（内部调用）。"""
    return parts_table()

_FALLBACK_PARTS: Dict[str, Dict[str, Any]] = {
    "PS_KONG": {"id": "PS_KONG", "name": "电源指示（空调/市电/控制）", "kind": "power3", "lamps": [
        {"name": "空调电源指示", "color": "R", "expect": "on"},
        {"name": "市电电源", "color": "R", "expect": "on"},
        {"name": "控制", "color": "G", "expect": "on"}]},
    "PS_GONGPIN": {"id": "PS_GONGPIN", "name": "电源控制（工频电源指示）", "kind": "single_red", "lamps": [
        {"name": "工频电源", "color": "R", "expect": "on"}]},
    "PD_BOARD": {"id": "PD_BOARD", "name": "配电盘（相序）", "kind": "numeric_range", "lamps": [
        {"name": "相序指示", "color": "G", "expect": "on"}]},
    "TX_STATE": {"id": "TX_STATE", "name": "发射机状态（工作/本路/发射通/发射断/故障）", "kind": "tx5", "lamps": [
        {"name": "工作", "color": "G", "expect": "on"}, {"name": "本路", "color": "G", "expect": "on"},
        {"name": "发射通", "color": "G", "expect": "on"}, {"name": "发射断", "color": "R", "expect": "off"},
        {"name": "故障", "color": "R", "expect": "off"}]},
    "ANT_START": {"id": "ANT_START", "name": "天线控制（天线启动）", "kind": "single_red", "lamps": [
        {"name": "天线启动", "color": "R", "expect": "on"}]},
    "TX_CTRL": {"id": "TX_CTRL", "name": "发射机控制（发射机工作 I/II）", "kind": "status2", "lamps": [
        {"name": "发射机工作 I", "color": "R", "expect": "any"},
        {"name": "发射机工作 II", "color": "R", "expect": "any"}]},
    "ANT_DIR": {"id": "ANT_DIR", "name": "天线换向（右向/左向）", "kind": "status2", "lamps": [
        {"name": "右向", "color": "R", "expect": "any"}, {"name": "左向", "color": "R", "expect": "any"}]},
}

@dataclass
class PhotoCtx:
    """一张照片的判定上下文（一次检测，全条目复用）。"""
    path: str = ""
    ts: str = ""
    scene: Scene = dc_field(default_factory=Scene)
    lamps: List[LampObs] = dc_field(default_factory=list)
    rows: List[LampRow] = dc_field(default_factory=list)
    screen: Optional[ScreenObs] = None
    part_hint: str = ""
    debug: Dict[str, Any] = dc_field(default_factory=dict)

    calib: Dict[str, Any] = dc_field(default_factory=dict)

    blob: Dict[str, Any] = dc_field(default_factory=dict)
    imgs: Dict[str, Any] = dc_field(default_factory=dict)   

def analyze_photo(path: str = "", bgr: Optional[np.ndarray] = None, ts: str = "",
                  do_meter: bool = False) -> PhotoCtx:
    """一张照片 → 上下文（灯 / 灯行 / 屏幕）。所有条目共享这一次检测结果。

    ★ 2026-10-29：传 bgr（内存帧）时也必须和 `load_bgr(path)` 一样缩放到 work_long，
      否则同一张照片"走路径/走内存帧"得到完全不同的检测结果（1920 vs 1600 帧，
      阈值/标定比例全不一致）——这正是 engine 与 soc_vision 两条链结论互相打架的根因之一。
    """
    ctx = PhotoCtx(path=path, ts=ts or _now_ts())
    if bgr is None:
        bgr, _ = load_bgr(path)
    else:
        bgr = np.asarray(bgr)
        if bgr.ndim == 3 and bgr.shape[2] == 4:
            bgr = bgr[:, :, :3]
        bgr, _ = _fit_long(bgr.astype(np.uint8, copy=False), TH["work_long"])
    ctx.imgs["bgr"] = bgr          
    ctx.scene = scene_gate(bgr)
    ctx.lamps, lamp_dbg = detect_lamps(bgr)
    ctx.rows = find_lamp_rows(ctx.lamps)
    ctx.screen = find_screen(bgr)
    ctx.debug = {"lamp": lamp_dbg, "n_rows": len(ctx.rows),
                 "screen_found": ctx.screen is not None,
                 "import_notes": list(IMPORT_NOTES),
                 "cv2": bool(cv2 is not None), "led_rules": LR is not None, "led_panel": LP is not None}
    ctx.scene.has_target = bool(ctx.rows or ctx.screen)
    if not ctx.scene.has_target:
        ctx.scene.notes.append("画面里既没有成排指示灯也没有显示屏 ⇒ 无有效目标")
    if do_meter and ctx.screen is not None:
        ctx.debug["meter"] = {}
        for k in METER_FIELDS:
            ctx.debug["meter"][k] = read_meter(bgr, k)
    return ctx

def evaluate_items(items: Sequence[Item], ctx: PhotoCtx, bgr: Optional[np.ndarray] = None,
                   part_hint: str = "", mirror_routes: bool = True,
                   meter_values: Optional[Dict[str, Tuple[str, float, str]]] = None,
                   kind: str = "") -> List[Evidence]:
    """把 61 条判据逐条套到这张照片上，产出证据列表。

    ``part_hint``：只判该 z 部件的条目（空 = 不筛；屏幕/微表条目没有 z 编号，永远参与）。
    ``kind``：``led`` / ``screen`` / ``meter`` / ``dynamic`` 子集，便于按现象链分开跑。
    """
    ev: List[Evidence] = []
    parts = parts_table()
    ctx.part_hint = part_hint or ""
    if bgr is None:

        
        bgr = (getattr(ctx, "imgs", None) or {}).get("bgr")
    if bgr is None and ctx.path:

        try:
            bgr, _ = load_bgr(ctx.path)
        except Exception:
            bgr = None
    for it in items:

        

        if part_hint and it.binding.startswith("led"):
            if it.part and part_hint.lower() != it.part.lower():

                

                
                _ref_pid = str(it.binding_ref or "").partition("#")[0]
                if not (_ref_pid and part_hint.lower() == _ref_pid.lower()):
                    continue
        if kind and not (it.binding or "").startswith(kind):
            continue

        

        

        try:
            e = _eval_one(it, ctx, bgr, parts, meter_values)
        except Exception as exc:
            e = _undet(it, "内部判定异常（%s: %s）⇒ 按『宁可不判』降级为未判定"
                           % (type(exc).__name__, exc),
                       ctx.ts, os.path.basename(ctx.path or ""))
        ev.append(e)
        if mirror_routes and it.route in ("I", "II"):
            ev.append(_mirror(e, it))

    

    out: List[Evidence] = []
    idx_of: Dict[Tuple[str, str, str, str], int] = {}
    for e in ev:
        k = (e.part, e.rule, e.route, _field_norm(e.field))
        j = idx_of.get(k)
        if j is None:
            idx_of[k] = len(out)
            out.append(e)
            continue
        cur = out[j]
        better = (cur.route_mirrored and not e.route_mirrored) or \
                 (cur.route_mirrored == e.route_mirrored and e.confidence > cur.confidence)
        if better:
            out[j] = e
    return out

def _field_norm(f: str) -> str:
    """把 II 路镜像命名的 field 归一化回 I 路口径，用于去重比较。"""
    return (f or "").replace("_route_two", "").replace("route_two_", "")

def _part_calib_ok(it: Item, parts: Dict[str, Dict[str, Any]],
                   bgr: Optional[np.ndarray]) -> bool:
    """该条 LED 判据的部件是否"逐灯标定坐标齐全"（齐全 = 不依赖成排灯也能取灯）。"""
    if it.binding not in ("led", "led_unbound") or not it.binding_ref or bgr is None:
        return False
    pid = it.binding_ref.partition("#")[0]
    spec = parts.get(pid) or {}
    lamps = spec.get("lamps") or []
    return bool(lamps) and all(l.get("photo_xy") for l in lamps)

def _tx5_capable(it: Item) -> bool:
    """该条是否属于 Z11/TX_STATE 五灯面板（blob 路径不依赖成排灯/屏幕 ⇒ 不受 has_target 门控）。"""
    if it.binding not in ("led", "led_unbound") or not it.binding_ref:
        return False
    return it.binding_ref.partition("#")[0] in _TX5_PANEL_PARTS

def _eval_one(it: Item, ctx: PhotoCtx, bgr: Optional[np.ndarray],
              parts: Dict[str, Dict[str, Any]],
              meter_values: Optional[Dict[str, Tuple[str, float, str]]]) -> Evidence:
    ts, photo = ctx.ts, os.path.basename(ctx.path or "")

    

    
    if not ctx.scene.has_target and not _part_calib_ok(it, parts, bgr) and not _tx5_capable(it):
        return _undet(it, "无有效目标：" + "；".join(ctx.scene.notes or ["未检测到指示灯/显示屏"]), ts, photo)

    if it.binding in ("led", "led_unbound"):
        return _eval_led(it, ctx, parts, ts, photo, bgr)

    if it.binding == "screen":
        return _eval_screen(it, ctx, ts, photo)

    if it.binding == "dynamic":
        return _undet(it, "「随动」需要连续帧/视频才能判（单帧照片不判，绝不用一帧猜运动）", ts, photo)

    if it.binding == "meter":
        if not ctx.screen:
            return _undet(it, "画面里没有定位到显示屏 ⇒ 无法读微表区", ts, photo)
        val, conf, why = (meter_values or {}).get(it.binding_ref) or read_meter(bgr, it.binding_ref)
        if val == "undetermined":
            return _undet(it, why, ts, photo)
        return Evidence(part=it.part, route=it.route, field=it.field, value=val, confidence=conf,
                        evidence=why, ts=ts, item_no=it.key, category=it.category,
                        check_item=it.item, rule="meter:" + it.binding_ref, photo=photo,
                        display=it.display, metrics={"meter_ref": it.binding_ref})
    return _undet(it, "该条判据暂无摄像头判据绑定（binding=%s）" % (it.binding or "none"), ts, photo)

def _eval_led(it: Item, ctx: PhotoCtx, parts: Dict[str, Dict[str, Any]], ts: str, photo: str,
              bgr: Optional[np.ndarray] = None) -> Evidence:

    if not ctx.part_hint:
        return _undet(it, "未提供部件号（--part，应由拍照 UI 给出）：画面里的灯排无法确认是这个部件，"
                           "宁可不判", ts, photo)
    if it.binding == "led_unbound" or not it.binding_ref:
        return _undet(it, "该灯位没有灯序标定（不在 config/led_rules.json 的部件表里）⇒ 不能把画面里的灯"
                           "对应到这一条，宁可不判", ts, photo)
    pid, _, idx_s = it.binding_ref.partition("#")
    spec = parts.get(pid)
    if not spec:
        return _undet(it, "规则表里没有部件 %s" % pid, ts, photo)

    

    if pid in _TX5_PANEL_PARTS or str(spec.get("kind") or "") == "tx5":
        return _eval_tx5_lamp(it, ctx, spec, idx_s, ts, photo, bgr)
    lamps = spec["lamps"]
    need = len(lamps)

    

    

    if pid not in _BLOB_PARTS and not any(l.get("photo_xy") for l in lamps):
        return _undet(it, "部件 %s 没有逐灯标定坐标（led_rules.json measured.photo_xy）、"
                          "也没有可用的自动定位规则 ⇒ 无法把画面灯位对应到这一颗灯，"
                          "宁不判（需先补标定/ROI）" % pid, ts, photo)

    

    
    bobs, bstatus, bwhy = _blob_lamps(ctx, pid, spec, bgr)
    if bobs is not None:
        return _eval_led_calib(it, ctx, spec, bobs, idx_s, ts, photo,
                               src="lamp_blob.detect_lamps", origin="按颜色亮点检测自动定位")
    if bstatus == "mismatch":
        return _undet(it, bwhy, ts, photo)

    
    calib, _calib_why = _calib_lamps(ctx, pid, spec, bgr)
    if calib is not None:
        return _eval_led_calib(it, ctx, spec, calib, idx_s, ts, photo)
    if not ctx.rows:
        return _undet(it, "画面里没找到成排指示灯（检测到 %d 个亮点/暗灯罩但不成行）" % len(ctx.lamps), ts, photo)
    cand = [r for r in ctx.rows if len(r.obs) == need]
    if not cand:
        best = ctx.rows[0]
        return _undet(it, "最近的一排灯是 %d 位（%s），规则要求 %d 位 ⇒ 不把灯位对应到条目"
                          % (len(best.obs), "、".join(l.color for l in best.obs), need), ts, photo)
    if len(cand) > 1:

        
        return _undet(it, "画面里有 %d 排灯都符合灯数 %d（y=%s），但部件 %s 没有逐灯标定坐标 "
                           "⇒ 无法确定哪一排是它，宁可不判"
                      % (len(cand), need, "、".join("%.0f" % r.y for r in cand[:4]), pid), ts, photo)
    row = cand[0]

    if idx_s == "*":
        return _eval_row_rule(it, ctx, spec, row, ts, photo)

    

    if not idx_s.isdecimal():
        return _undet(it, "灯位描述 %r 的序号 %r 不是纯数字（占位符）⇒ 不把灯位对应到条目"
                      % (it.binding_ref, idx_s), ts, photo)
    idx = int(idx_s)
    if idx >= need:
        return _undet(it, "部件 %s 只有 %d 个灯位，越界" % (pid, need), ts, photo)
    obs, why = _choose_lamp(row, need, idx)
    if obs is None:
        return _undet(it, why, ts, photo)
    conf = obs.confidence
    if ctx.scene.soft:
        conf *= 0.85
    if obs.delta >= TH["lamp_delta_off"] and abs(obs.delta - TH["lamp_delta_on"]) < 4.0:
        return _undet(it, "%s 灯位处于灰区：delta=%.1f 贴近阈值 %.0f ⇒ 不判"
                      % (lamps[idx]["name"], obs.delta, TH["lamp_delta_on"]), ts, photo)
    if conf < TH["conf_min"]:
        return _undet(it, "%s 灯位置信 %.2f < %.2f（%s）"
                      % (lamps[idx]["name"], conf, TH["conf_min"], obs.reason), ts, photo)
    value = "on" if obs.on else "off"
    why = ("第 %d/%d 位（%s，应为%s灯）%s：中心 V=%.0f、环带 V=%.0f、delta=%+.0f（阈值 %+.0f）"
           % (idx + 1, need, lamps[idx]["name"], COLOR_NAME.get(lamps[idx]["color"], "?"),
              "亮" if obs.on else "灭", obs.v_center, obs.v_ring, obs.delta, TH["lamp_delta_on"]))
    return Evidence(part=it.part, route=it.route, field=it.field, value=value, confidence=conf,
                    evidence=why, ts=ts, item_no=it.key, category=it.category, check_item=it.item,
                    rule="led:%s#%d" % (pid, idx), photo=photo, display=it.display,
                    metrics={"lamp": obs.to_dict(),
                             "row": {"n_slots": len(row.obs), "gap": round(row.gap, 1),
                                     "gap_cv": round(row.gap_cv, 3), "y": round(row.y, 1),
                                     "lamps": [{"name": lamps[i]["name"], "color": lamps[i]["color"],
                                                "on": row.obs[i].on,
                                                "delta": round(row.obs[i].delta, 1)}
                                               for i in range(len(row.obs))]}})

def _eval_led_calib(it: Item, ctx: PhotoCtx, spec: Dict[str, Any],
                    obs: Sequence[Optional[LampObs]], idx_s: str, ts: str,
                    photo: str, src: str = "led_rules.calib_xy",
                    origin: str = "按 led_rules 标定坐标取灯") -> Evidence:
    """★ 逐灯判定：灯位要么来自 **led_rules 标定坐标**，要么来自 **颜色亮点自动定位**。

    旧路径把"部件第 i 颗灯"硬对到"画面里第 i 条排的第 i 颗灯"，完全不看标定坐标；
    排的顺序按 (灯数, y) 排，Z18 的 ``#*`` 因此取到 y≈190 的两颗无关灯罩。
    2026-10-18 改成按标定坐标逐灯取；2026-10-23 起新增 ``lamp_blob`` 自动定位路径
    （``src="lamp_blob.detect_lamps"``），两条路径共用这里的判定/证据口径：
    位置、颜色、亮灭、dim 全部按该灯实测上报；弱灯（dim/qa_required）一律"判不准"。
    """
    pid = str(spec["id"])
    lamps = spec["lamps"]
    need = len(lamps)
    where = "、".join("%s(%s)" % (l["name"], ("%d,%d" % (o.x, o.y)) if o is not None else "未测到")
                     for l, o in zip(lamps, obs))
    weak_idx = [i for i, l in enumerate(lamps) if l.get("dim") or l.get("qa_required")]
    dark_note = ""
    if not ctx.scene.has_target:
        dark_note = ("；★ 本张画面检不到成排灯/屏（门板欠曝），灯位由颜色亮点自动定位"
                     if src.startswith("lamp_blob") else
                     "；★ 本张画面检不到成排灯/屏（门板欠曝），只有标定坐标可用")

    if idx_s == "*":
        if any(o is None for o in obs):
            return _undet(it, "整排规则要逐灯取：标定坐标处有灯没测到（%s）⇒ 不判%s"
                          % (where, dark_note), ts, photo)
        if weak_idx:
            return _undet(it, "整排里含弱灯（%s）⇒ 视觉不可靠、判不准，请看问答确认；灯位：%s"
                          % ("、".join(lamps[i]["name"] for i in weak_idx), where), ts, photo)
        detail = "灯位：" + "、".join("%s(%d,%d)=%s/%s" % (
            l["name"], o.x, o.y, COLOR_NAME.get(o.color, o.color), "亮" if o.on else "灭")
            for l, o in zip(lamps, obs) if o is not None) + dark_note
        return _eval_row_rule(it, ctx, spec, _row_from_obs([o for o in obs if o is not None]),
                              ts, photo, src=origin, extra=detail)

    if not idx_s.isdecimal():
        return _undet(it, "灯位描述 %r 的序号 %r 不是纯数字（占位符）⇒ 不把灯位对应到条目"
                      % (it.binding_ref, idx_s), ts, photo)
    idx = int(idx_s)
    if idx >= need:
        return _undet(it, "部件 %s 只有 %d 个灯位，越界" % (pid, need), ts, photo)
    lp, o = lamps[idx], obs[idx]
    if o is None:
        return _undet(it, "第 %d/%d 位「%s」在%s处没测到（越界/灯太小）⇒ 不判；灯位：%s"
                      % (idx + 1, need, lp["name"], origin, where), ts, photo)
    dim, qa = bool(lp.get("dim")), bool(lp.get("qa_required"))
    if dim or qa:
        return _undet(it, "第 %d/%d 位「%s」是弱灯（dim=%s / 需问答=%s）：%s (%d,%d) 实测 "
                           "颜色 %s、delta=%+.0f（%s），但按钮灯亮得极弱、与暗塑料分不开 ⇒ **判不准**，"
                           "请看问答确认；灯位：%s%s"
                      % (idx + 1, need, lp["name"], dim, qa, origin, o.x, o.y,
                         COLOR_NAME.get(o.color, o.color), o.delta, "亮" if o.on else "灭", where,
                         dark_note),
                      ts, photo)
    conf = o.confidence
    if ctx.scene.soft:
        conf *= 0.85
    if o.delta >= TH["lamp_delta_off"] and abs(o.delta - TH["lamp_delta_on"]) < 4.0:
        return _undet(it, "%s 灯位处于灰区：delta=%.1f 贴近阈值 %.0f ⇒ 不判"
                      % (lp["name"], o.delta, TH["lamp_delta_on"]), ts, photo)
    if conf < TH["conf_min"]:
        return _undet(it, "%s 灯位置信 %.2f < %.2f（%s）"
                      % (lp["name"], conf, TH["conf_min"], o.reason), ts, photo)
    value = "on" if o.on else "off"
    why = ("第 %d/%d 位「%s」（应为%s灯、正常态 %s）实测%s：位置 (%d,%d)、r=%.0f、颜色 %s、"
           "中心 V=%.0f、环带 V=%.0f、delta=%+.0f（阈值 %+.0f）；%s；灯位：%s%s"
           % (idx + 1, need, lp["name"], COLOR_NAME.get(lp["color"], "?"), lp.get("expect") or "any",
              "亮" if o.on else "灭", o.x, o.y, o.r, COLOR_NAME.get(o.color, o.color),
              o.v_center, o.v_ring, o.delta, TH["lamp_delta_on"], origin, where, dark_note))
    return Evidence(part=it.part, route=it.route, field=it.field, value=value, confidence=conf,
                    evidence=why, ts=ts, item_no=it.key, category=it.category, check_item=it.item,
                    rule="led:%s#%d" % (pid, idx), photo=photo, display=it.display,
                    metrics={"lamp": o.to_dict(),
                             "lamp_meta": {"name": lp["name"], "color": lp["color"],
                                           "expect": lp.get("expect"), "dim": dim,
                                           "qa_required": qa, "photo_xy": lp.get("photo_xy")},
                             "src": src})

def _eval_row_rule(it: Item, ctx: PhotoCtx, spec: Dict[str, Any], row: LampRow,
                   ts: str, photo: str, src: str = "", extra: str = "") -> Evidence:
    """整排规则（如 ANT_DIR status2：右向/左向 恰好一亮一灭）。

    ★ 复用 led_rules.evaluate_by_litcount 的三态语义：正常 → on；故障 → off；未判定 → undetermined。
    这样 LED 类结论与既有 LED 引擎口径一致，不给融合层制造第二套语义。
    """
    n_lit = sum(1 for o in row.obs if o.on)
    names = [l["name"] for l in spec["lamps"]]
    lit_names = [spec["lamps"][i]["name"] for i, o in enumerate(row.obs) if o.on]
    conf = min([o.confidence for o in row.obs] or [0.0])
    why = ("灯排（%s）实测 %d 亮 / %d 灭：%s"
           % ("、".join(names), n_lit, len(row.obs) - n_lit,
              "、".join(("%s=%s" % (spec["lamps"][i]["name"], "亮" if o.on else "灭"))
                        for i, o in enumerate(row.obs))))
    if src:
        why = "（%s）%s" % (src, why)
    if extra:
        why = "%s；%s" % (why, extra)
    if LR is not None:
        try:
            rule = LR.PartRule(pid=spec["id"], name=spec["name"], kind=spec["kind"],
                               lamps=[LR.LampSpec(name=l["name"], color=l["color"], expect=l["expect"])
                                      for l in spec["lamps"]])
            v = LR.evaluate_by_litcount(rule, n_lit, panel_present=True, lit_names=lit_names)
            if v.verdict == LR.VERDICT_OK:
                return Evidence(part=it.part, route=it.route, field=it.field, value="on",
                                confidence=min(0.85, max(conf, 0.6)), evidence=why + "；led_rules 判正常：" + v.reason,
                                ts=ts, item_no=it.key, category=it.category, check_item=it.item,
                                rule="led_row:" + spec["id"], photo=photo, display=it.display,
                                metrics={"row_lamps": [o.to_dict() for o in row.obs]})
            if v.verdict == LR.VERDICT_BAD:
                return Evidence(part=it.part, route=it.route, field=it.field, value="off",
                                confidence=min(0.85, max(conf, 0.6)), evidence=why + "；led_rules 判故障：" + v.reason,
                                ts=ts, item_no=it.key, category=it.category, check_item=it.item,
                                rule="led_row:" + spec["id"], photo=photo, display=it.display,
                                metrics={"row_lamps": [o.to_dict() for o in row.obs]})
            return _undet(it, why + "；led_rules 未判定：" + v.reason, ts, photo)
        except Exception as exc:
            return _undet(it, "复用 led_rules 整排判定失败（%s）⇒ 不判" % exc, ts, photo)

    ok = (n_lit == 1)
    return Evidence(part=it.part, route=it.route, field=it.field, value="on" if ok else "off",
                    confidence=min(0.75, conf), evidence=why + "（status2：恰好一亮=正常）",
                    ts=ts, item_no=it.key, category=it.category, check_item=it.item,
                    rule="led_row(fallback):" + spec["id"], photo=photo, display=it.display,
                    metrics={"row_lamps": [o.to_dict() for o in row.obs]})

_SCREEN_HINT = {
    "display_screen": "画面有内容/偏黄（参考）",
    "echo": "屏内检出亮回波（参考）",
    "noise": "屏面有噪声底盘（参考）",
    "scan": "屏面有扫描纹理（参考）",
    "line": "屏内有线结构（参考）",
    "pointer": "单帧看不出随动（参考）",
}
_SCREEN_ABNORMAL = ("black_screen", "yellow_screen", "garbled")
_SCREEN_ABNORMAL_CN = {"black_screen": "黑屏", "yellow_screen": "黄屏", "garbled": "花屏"}

def _screen_qa(it: Item, ts: str, photo: str, why: str, hint: str, rule: str,
               conf: float = 0.0, base: Optional[Dict[str, Any]] = None) -> Evidence:
    """屏幕类"只提示、不判正常"的统一出口：**绝不返回 ok/normal**。"""
    return Evidence(part=it.part, route=it.route, field=it.field, value="undetermined",
                    confidence=round(min(max(float(conf or 0.0), 0.0), 0.49), 3),
                    evidence="%s（视觉仅提示，结论以问答为准）" % _screen_why(why),
                    ts=ts, item_no=it.key, category=it.category, check_item=it.item,
                    rule=rule, photo=photo, display=it.display, decided_by="qa_required",
                    hint=hint, metrics=base or {})

def _screen_why(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()

def _eval_screen(it: Item, ctx: PhotoCtx, ts: str, photo: str) -> Evidence:
    sc = ctx.screen
    ref = it.binding_ref or ""
    rule = "screen:%s" % (ref or "unknown")
    if sc is None:
        return _screen_qa(it, ts, photo,
                          "画面里没有定位到显示屏（无大面积亮/暗色矩形区）",
                          "未定位到屏幕（参考）", rule)
    m = sc.metrics
    base = {"screen": {"rect": list(sc.rect), "hint": sc.hint}, "metrics": m.to_dict()}
    if not ctx.scene.sharp:
        return _screen_qa(it, ts, photo,
                          "屏面发虚（mean|grad|=%.2f < %.2f），看不清结构与纹理"
                          % (ctx.scene.grad, TH["grad_blur"]),
                          "屏面发虚（参考）", rule, sc.confidence, base)

    if sc.state in _SCREEN_ABNORMAL:
        if sc.confidence >= TH["conf_min"]:
            return Evidence(part=it.part, route=it.route, field=it.field, value=sc.state,
                            confidence=sc.confidence, evidence=sc.evidence, ts=ts, item_no=it.key,
                            category=it.category, check_item=it.item, rule=rule,
                            photo=photo, display=it.display, metrics=base,
                            decided_by="vision_abnormal")
        return _screen_qa(it, ts, photo,
                          "疑似 %s 但置信 %.2f < %.2f（不够高，不硬判异常）：%s"
                          % (sc.state, sc.confidence, TH["conf_min"], sc.evidence),
                          "疑似%s（置信不足，参考）" % _SCREEN_ABNORMAL_CN.get(sc.state, sc.state),
                          rule, sc.confidence, base)

    if ref == "display_screen":
        why = sc.evidence if sc.state == "ok" else ("屏面定态=%s：%s" % (sc.state, sc.evidence))
        return _screen_qa(it, ts, photo, why,
                          _SCREEN_HINT["display_screen"], rule, sc.confidence, base)

    
    if sc.hint == "gold" or sc.confidence < TH["conf_min"]:
        return _screen_qa(it, ts, photo,
                          "屏幕定位置信不足（hint=%s、判态 %.2f）⇒ 不拿它判回波/扫描/噪声"
                          % (sc.hint, sc.confidence),
                          "屏幕定位置信不足（参考）", rule, sc.confidence, base)
    if ref in ("course_echo", "glide_echo"):
        if m.bright_frac <= TH["echo_weak_min"]:

            

            return _screen_qa(it, ts, photo,
                              "屏内亮回波像素 %.3f%% ≤ %.3f%%（视觉看着像无回波，实测该阈值会误报）"
                              % (m.bright_frac * 100, TH["echo_weak_min"] * 100),
                              "回波偏弱/疑似无回波（参考）", "screen:echo", 0.45, base)
        if m.bright_frac < TH["echo_bright_min"]:

            return _screen_qa(it, ts, photo,
                              "亮回波 %.3f%% 低于正常下限 %.3f%%（偏弱）"
                              % (m.bright_frac * 100, TH["echo_bright_min"] * 100),
                              "回波偏弱（参考）", "screen:echo", 0.49, base)
        return _screen_qa(it, ts, photo,
                          "亮回波 %.2f%% ≥ %.2f%%，线结构 %.2f"
                          % (m.bright_frac * 100, TH["echo_bright_min"] * 100, m.line_frac),
                          _SCREEN_HINT["echo"], "screen:echo", min(0.49, sc.confidence), base)
    if ref in ("course_noise", "glide_noise"):
        if m.texture <= TH["scan_texture_min"] or m.hf_energy <= 0.008:

            return _screen_qa(it, ts, photo,
                              "纹理 %.4f ≤ %.4f、高频 %.3f（屏面没有噪声底盘）"
                              % (m.texture, TH["scan_texture_min"], m.hf_energy),
                              "屏面未检出噪声（参考）", "screen:noise", 0.49, base)
        return _screen_qa(it, ts, photo,
                          "纹理 %.4f > %.4f" % (m.texture, TH["scan_texture_min"]),
                          _SCREEN_HINT["noise"], "screen:noise", 0.49, base)
    if ref in ("course_scan", "glide_scan"):
        if m.texture <= TH["scan_texture_min"] and m.hf_energy <= 0.020:

            return _screen_qa(it, ts, photo,
                              "纹理 %.4f ≤ %.4f、高频 %.3f（视觉看着像不扫描，实测会误报）"
                              % (m.texture, TH["scan_texture_min"], m.hf_energy),
                              "疑似不扫描（参考）", "screen:scan", 0.45, base)
        if m.texture > TH["scan_texture_min"]:
            return _screen_qa(it, ts, photo,
                              "纹理 %.4f、高频 %.3f" % (m.texture, m.hf_energy),
                              _SCREEN_HINT["scan"], "screen:scan", 0.49, base)
        return _screen_qa(it, ts, photo, "扫描纹理 %.4f 处于灰区" % m.texture,
                          "扫描纹理灰区（参考）", "screen:scan", 0.40, base)
    if ref in ("course_line", "glide_line"):

        return _screen_qa(it, ts, photo,
                          "理想线判据需要理想线模板/屏几何标定；单帧只能给出线结构诊断量 %.2f"
                          % m.line_frac,
                          _SCREEN_HINT["line"], "screen:line", 0.40, base)
    return _screen_qa(it, ts, photo, "未知屏幕检查项 %s" % ref,
                      "未知屏幕项（参考）", rule, 0.0, base)

def _mirror(e: Evidence, it: Item) -> Evidence:
    """I/II 路镜像：同一张照片、同一套规则，把结论复制到另一路并明确标注。"""
    other = "II" if it.route == "I" else "I"
    fld = it.field
    if it.route == "I":
        fld = it.field.replace("route_one", "route_two") if "route_one" in it.field else it.field + "_route_two"
    else:
        fld = it.field.replace("route_two", "route_one") if "route_two" in it.field else it.field.replace("_route_two", "")
    d = e.to_dict()
    d.pop("state", None)
    return Evidence(part=e.part, route=other, field=fld, value=e.value,
                    confidence=round(max(0.0, e.confidence - 0.05), 3),
                    evidence="[I/II 镜像] 同一张照片按同一规则套用到 %s 路：%s" % (other, e.evidence),
                    ts=e.ts, item_no=e.item_no, category=e.category, check_item=e.check_item,
                    rule=e.rule, route_mirrored=True, display=e.display,
                    decided_by=e.decided_by, hint=e.hint,
                    metrics={"mirrored_from_route": it.route})

def run_photo(path: str, items: Optional[Sequence[Item]] = None, part: str = "",
              mirror_routes: bool = True, do_meter: bool = False, kind: str = "",
              bgr: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """单张照片 → 完整结果（场景 + 灯 + 屏 + 证据）。

    ``bgr``（★ 2026-10-29）：可直接传"内存里的 BGR 帧"（拍照 UI 的原始帧），
    跳过"写临时 jpg 再解码"——实测这一步的 JPEG 往返会让暗场/临界灯的斑块检出翻转，
    导致 engine（结果页）与 soc_vision（拍照即判）对同一张照片给出不同结论。
    传了 bgr 时 ``path`` 只用于时间戳/照片名，可为空串。

    ★ 接口约定：**对真实照片永不抛异常**。图像解码/检测阶段若整体失败（坏图、EXIF 损坏、
    ROI 越界……），返回一份"全部 undetermined + 原因"的合法证据 JSON，而不是让上层
    整批判定崩掉（`run_batch` 里也还有一层兜底）。
    """
    ts = _photo_ts(path)
    try:
        ctx = analyze_photo(path, bgr=bgr, ts=ts, do_meter=do_meter)
    except Exception as exc:
        ctx = PhotoCtx(path=path, ts=ts)
        ctx.scene.notes.append("图像分析失败（%s: %s）⇒ 本张全部不判"
                               % (type(exc).__name__, exc))
        ctx.scene.has_target = False
        ctx.debug = {"error": "%s: %s" % (type(exc).__name__, exc)}
    items = list(items if items is not None else load_catalog())
    ev = evaluate_items(items, ctx, part_hint=part, mirror_routes=mirror_routes, kind=kind)
    return _pack(ctx, ev)

def _photo_ts(path: str) -> str:
    """采集时间优先从同名 .json 侧车取（拍照 UI 会写），否则用当前时间。"""
    try:
        j = os.path.splitext(path)[0] + ".json"
        if os.path.isfile(j):
            d = json.load(open(j, encoding="utf-8"))
            t = str(d.get("time") or "")
            if t:
                return t if ("+" in t or t.endswith("Z")) else t + "+08:00"
    except Exception:
        pass
    return _now_ts()

def write_evidence(ev: Sequence[Dict[str, Any]], path: str) -> str:
    """按 evidence/v1 批量格式落盘（`fusion.py` / `fault_grader.py` 可直接吃）。"""
    wrap = {"schema": "evidence/v1", "producer": "vision_rules.py",
            "generated": _now_ts(), "n": len(ev), "evidence": list(ev)}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(wrap, f, ensure_ascii=False, indent=1)
    return path

def _pack(ctx: PhotoCtx, ev: Sequence[Evidence]) -> Dict[str, Any]:
    decided = [e for e in ev if e.value != "undetermined"]
    dbg = dict(ctx.debug or {})
    if WARNINGS:                                  
        dbg["warnings"] = list(WARNINGS)
    if ctx.calib:                                 
        dbg["calib"] = _calib_debug(ctx)
    if ctx.blob:                                  
        dbg["blob"] = _blob_debug(ctx)
    return {
        "photo": os.path.basename(ctx.path or ""),
        "photo_path": ctx.path,
        "ts": ctx.ts,
        "engine": VER_ENGINE,
        "scene": ctx.scene.to_dict(),
        "screen": ctx.screen.to_dict() if ctx.screen else None,
        "lamp_rows": [r.to_dict() for r in ctx.rows],
        "debug": dbg,
        "n_items": len(ev),
        "n_decided": len(decided),
        "n_undetermined": len(ev) - len(decided),
        "evidence": [e.to_dict() for e in ev],
    }

def run_batch(photos: Sequence[str], items: Optional[Sequence[Item]] = None,
              part_map: Optional[Dict[str, str]] = None, out_path: str = "",
              mirror_routes: bool = True, do_meter: bool = False,
              kind_map: Optional[Dict[str, str]] = None, kind: str = "") -> Dict[str, Any]:
    """批量跑照片；part_map: 文件名 → 部件号（缺省则不带 part 提示跑全 61 条）。"""
    items = list(items if items is not None else load_catalog())
    part_map = part_map or {}
    kind_map = kind_map or {}
    results: Dict[str, Any] = {}
    by_value: Dict[str, int] = {}
    all_ev: List[Dict[str, Any]] = []
    for p in photos:
        name = os.path.basename(p)
        part = part_map.get(name) or part_map.get("*", "")
        k = kind_map.get(name, kind)
        try:
            r = run_photo(p, items=items, part=part, mirror_routes=mirror_routes,
                          do_meter=do_meter, kind=k)
        except Exception as exc:                      
            r = {"photo": name, "photo_path": p, "error": "%s: %s" % (type(exc).__name__, exc),
                 "evidence": []}
        results[name] = r
        all_ev.extend(r.get("evidence") or [])
        for e in r.get("evidence") or []:
            by_value[e["value"]] = by_value.get(e["value"], 0) + 1
    summary = {"n_photos": len(photos), "n_evidence": len(all_ev),
               "by_value": dict(sorted(by_value.items(), key=lambda kv: -kv[1])),
               "n_decided": sum(v for k, v in by_value.items() if k != "undetermined"),
               "n_undetermined": by_value.get("undetermined", 0)}
    screens = [r["screen"]["state"] for r in results.values() if r.get("screen")]
    summary["screen_states"] = {s: screens.count(s) for s in sorted(set(screens))}
    report = {"engine": VER_ENGINE, "ts": _now_ts(), "summary": summary, "photos": results}
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
    return report

def write_bindings(path: str = "") -> str:
    """把 61 条判据的绑定表落盘（可人工修改后回灌）。"""
    items = load_catalog()
    data = {"engine": VER_ENGINE, "n_items": len(items),
            "note": "led 序号 = config/led_rules.json 里该部件 lamps 的顺序（左→右/上→下）",
            "items": [it.to_dict() for it in items]}
    p = path or BINDINGS_JSON
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return p

def _print_catalog(items: Sequence[Item]) -> None:
    print("摄像头类判据：%d 项" % len(items))
    print("%-10s %-6s %-8s %-6s %-10s %s" % ("flow.sub", "part", "route", "bind", "expect", "field"))
    for it in items:
        print("%-10s %-6s %-8s %-6s %-10s %s" % (it.key, it.part or "-", it.route or "-",
                                                 it.binding, it.expect, it.field))

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="摄像头类判定引擎（61 项）——只出图像证据，不碰板子")
    ap.add_argument("--image", default="", help="单张照片")
    ap.add_argument("--dir", default="", help="照片目录")
    ap.add_argument("--manifest", default="", help="CSV: filename,part（可选 roi）")
    ap.add_argument("--part", default="", help="部件号（z11/z31/…）；一张照片只拍了一个部件时用它")
    ap.add_argument("--kind", default="", choices=["", "led", "screen", "meter", "dynamic"],
                    help="只跑某一现象链（默认全部）")
    ap.add_argument("--out", default="", help="结果 JSON 落盘路径")
    ap.add_argument("--evidence-out", default="", help="按 evidence/v1 批量格式落盘（给 fusion.py 吃）")
    ap.add_argument("--catalog", action="store_true", help="打印 61 项目录")
    ap.add_argument("--gen-bindings", action="store_true", help="重建 vision_bindings.json")
    ap.add_argument("--no-mirror", action="store_true", help="关闭 I/II 路镜像")
    ap.add_argument("--meter", action="store_true", help="尝试读微表区（需参考模板）")
    ap.add_argument("--selftest", action="store_true", help="内置自检")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    if a.selftest:
        import test_vision_rules
        return test_vision_rules.main([])
    if a.meter:
        set_meter(True)
    items = load_catalog()
    if a.catalog:
        _print_catalog(items)
        return 0
    if a.gen_bindings:
        p = write_bindings()
        print("已写 %s（%d 项）" % (p, len(items)))
        return 0
    mirror = not a.no_mirror
    if a.image:
        r = run_photo(a.image, items=items, part=a.part, mirror_routes=mirror,
                      do_meter=a.meter, kind=a.kind)
        if a.evidence_out:
            write_evidence(r["evidence"], a.evidence_out)
            print("已写 %s（%d 条证据，evidence/v1）" % (a.evidence_out, len(r["evidence"])))
        if a.out:
            json.dump(r, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print("已写 %s（判定 %d / 未判定 %d）" % (a.out, r["n_decided"], r["n_undetermined"]))
        if not a.quiet:
            print(json.dumps({k: r[k] for k in ("photo", "scene", "screen", "n_decided", "n_undetermined")},
                             ensure_ascii=False, indent=1)[:2000])
            for e in r["evidence"]:
                if e["value"] != "undetermined":
                    print("  ✔ %-8s %-4s %-46s = %-12s %.2f  %s"
                          % (e["part"], e["route"] or "-", e["field"], e["value"], e["confidence"], e["evidence"][:90]))
        return 0
    if a.dir:
        photos = sorted(glob.glob(os.path.join(a.dir, "*.jpg")) + glob.glob(os.path.join(a.dir, "*.png")))
        part_map: Dict[str, str] = {}
        if a.manifest and os.path.isfile(a.manifest):
            with open(a.manifest, encoding="utf-8-sig", newline="") as f:
                for row in csv.reader(f):
                    if len(row) >= 2 and row[0].strip() and not row[0].startswith("#"):
                        part_map[row[0].strip()] = row[1].strip().lower()
        elif a.part:
            part_map["*"] = a.part.lower()
        rep = run_batch(photos, items=items, part_map=part_map, out_path=a.out,
                        mirror_routes=mirror, do_meter=a.meter, kind=a.kind)
        s = rep["summary"]
        print("照片 %d 张；证据 %d 条：已判定 %d、未判定 %d" % (s["n_photos"], s["n_evidence"],
                                                              s["n_decided"], s["n_undetermined"]))
        print("取值分布：" + json.dumps(s["by_value"], ensure_ascii=False))
        if a.out:
            print("已写 %s" % a.out)
        if a.evidence_out:
            all_ev: List[Dict[str, Any]] = []
            for r in rep["photos"].values():
                all_ev.extend(r.get("evidence") or [])
            write_evidence(all_ev, a.evidence_out)
            print("已写 %s（%d 条证据，evidence/v1）" % (a.evidence_out, len(all_ev)))
        return 0
    ap.print_help()
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
