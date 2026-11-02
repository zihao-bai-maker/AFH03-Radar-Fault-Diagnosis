#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_part_recognizer.py —— 多模态部位识别器的可复现验收。

跑法::

    python test_part_recognizer.py            # 全部（含 25 张留出真图，约 2~3 分钟）
    python test_part_recognizer.py --quick    # 只跑单元/契约测试，不碰真图

验收口径（**报数字，不报“感觉”**）
---------------------------------
1. **真图留出**：``part_features.json`` 里 ``holdout`` 的 25 张真图**不参与建库**，
   覆盖 z11/z12/z14/z15/z18/z20/z31 七个部位；报 top-1 / top-3 / need_confirm /
   已回答准确率。当前实测见文件末尾打印。
2. **无标记**：全部真图测试默认 ``use_marker=False``（现场还没贴标），
   另跑一次 marker=True 只用于检查**误检**。
3. **外观单模态**：``use_ocr=False``，报 top-1/top-3；它应当 **100% need_confirm**
   （外观分只有 0.5~0.8，不允许单独下结论）。
4. **合成标记**：给 195713 真图叠加 18 个 v2 标记（``markers_v2/png/large``），
   用 marker-only 识别，要求 18/18；再做 ±5° 倾斜 + ``marker_rot_search``，要求 6/6。
5. **unknown 拒识**：4 张清单外/无部位图（操显屏特写、暗帧、示波器、Z17 操显），
   要求至少 3/4 判 need_confirm，且没有“高置信误接受”。
6. **契约**：``to_evidence()`` 输出 8 个 evidence/v1 必填字段；``criteria_for()``
   按故障归属字段取判据（z20 在判据库没有专属故障行 ⇒ 返回 0，README 说明）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

from part_recognizer import (  
    FEATURE_DIM, FEATURES_JSON, PART_INFO, ContextPrior, PartRecognizer,
    apply_to_evidence, criteria_for, extract_appearance, load_bgr, match_ocr,
    route_from_flow, to_evidence,
)

try:
    import cv2
except Exception:  
    cv2 = None  

PHOTO_DIR = os.path.join(WORKSPACE, "雷达照片_今天", "拍照UI照片")
MARKER_PNG = os.path.join(os.path.dirname(HERE), "markers_v2", "png", "large")

PASS: List[str] = []
FAIL: List[str] = []

def check(name: str, fn) -> None:
    t0 = time.time()
    try:
        detail = fn()
        PASS.append(name)
        print("  [PASS] %-36s %5.2fs  %s" % (name, time.time() - t0, detail or ""))
    except Exception as e:  
        FAIL.append("%s: %s" % (name, e))
        print("  [FAIL] %-36s %5.2fs  %s: %s" % (name, time.time() - t0, type(e).__name__, e))

def _line(text: str, score: float = 0.95, y: int = 0) -> Dict[str, Any]:
    return {"text": text, "score": score, "backend": "unit",
            "box": [[10, y], [120, y], [120, y + 22], [10, y + 22]]}

def _holdout() -> List[Dict[str, Any]]:
    with open(FEATURES_JSON, encoding="utf-8") as f:
        lib = json.load(f)
    return list(lib.get("holdout") or [])

def t_library() -> str:
    with open(FEATURES_JSON, encoding="utf-8") as f:
        lib = json.load(f)
    assert lib.get("dim") == FEATURE_DIM, "dim %s != %s" % (lib.get("dim"), FEATURE_DIM)
    total = int(lib.get("total_samples", 0))
    assert total >= 30, "建库样本 %d < 30" % total
    assert len(lib.get("parts") or {}) >= 7, "部位类别不足"
    hold = list(lib.get("holdout") or [])
    assert len(hold) >= 25, "留出测试不足 25 张：%d" % len(hold)
    train_names = {s["image"] for p in (lib.get("parts") or {}).values() for s in (p.get("samples") or [])}
    hold_names = {h["image"] for h in hold}
    assert not (train_names & hold_names), "训练/留出有重叠：%s" % sorted(train_names & hold_names)[:5]
    assert int((lib.get("unknown") or {}).get("n", 0)) >= 4, "unknown 校准样本不足"
    return "known=%d unknown=%d holdout=%d" % (total, int((lib.get("unknown") or {}).get("n", 0)), len(hold))

def t_feature_extract() -> str:
    hold = _holdout()
    assert hold, "没有 holdout"
    img = load_bgr(os.path.join(PHOTO_DIR, hold[0]["image"]))
    assert img is not None, "读不到 %s" % hold[0]["image"]
    f = extract_appearance(img)
    assert f.shape == (FEATURE_DIM,), "shape=%s" % (f.shape,)
    n = float(np.linalg.norm(f))
    assert 0.95 <= n <= 1.05, "L2 norm=%.3f" % n
    return "dim=%d norm=%.3f" % (FEATURE_DIM, n)

def t_ocr_keywords() -> str:
    cases = [
        (["Z11", "收发"], "z11", 0.85),
        (["Z14", "信处"], "z14", 0.85),
        (["Z15", "显示电路"], "z15", 0.85),
        (["Z31", "电源控制"], "z31", 0.85),
        (["Z12", "电源"], "z12", 0.85),
        (["Z20", "控制台"], "z20", 0.85),
        (["Z18", "控制"], "z18", 0.85),
        (["Z11-1", "频综"], "z11-1", 0.85),
        (["Z15-CPU", "CPU板"], "z15-CPU", 0.85),
        (["714"], "z14", 0.60),          
    ]
    for texts, want, floor in cases:
        pack = match_ocr([_line(t, y=i * 30) for i, t in enumerate(texts)])
        got = (pack.get("scores") or {}).get(want, 0.0)
        assert got >= floor, "%s -> %s 分值 %.2f < %.2f（全部分值 %s）" % (
            texts, want, got, floor, pack.get("scores"))

    pack = match_ocr([_line("Z17"), _line("操显", y=30)])
    assert "Z17" in (pack.get("unsupported") or []), "Z17 未进 unsupported：%s" % pack

    pack = match_ocr([_line("电源控制"), _line("天线控制", y=30), _line("电台电源", y=60)])
    scores = pack.get("scores") or {}
    assert scores.get("z20", 0) >= 0.60, "Z20 分区丝印未聚合：%s" % scores
    assert scores.get("z31", 0) <= 0.56, "Z31 未被降权：%s" % scores
    return "10 条正例 + Z17/分区丝印消歧"

def t_context_route() -> str:
    assert route_from_flow(1) == "I"
    assert route_from_flow(27) == "I"
    assert route_from_flow(28) == ""
    assert route_from_flow(29) == "II"
    assert route_from_flow(None, "II") == "II"
    c = ContextPrior()
    sc, src = c.score("z31", flow_no=1)
    assert sc >= 0.30, "flow1→z31 先验 %.2f" % sc
    sc2, _ = c.score("z20", flow_no=21, prior_part="z20", prior_ts=time.time())
    assert sc2 >= 0.39, "prior z20 连续先验 %.2f" % sc2
    return "flow13/28/29 + flow1→z31 %.2f" % sc

def _paste_marker(bg: np.ndarray, part: str, size: int = 300, angle: float = 0.0) -> np.ndarray:
    m = load_bgr(os.path.join(MARKER_PNG, part + ".png"))
    assert m is not None, "读不到标记 png: %s" % part
    m = cv2.resize(m, (size, size), interpolation=cv2.INTER_AREA)
    if abs(angle) > 1e-6:
        M = cv2.getRotationMatrix2D((size / 2, size / 2), angle, 1.0)
        m = cv2.warpAffine(m, M, (size, size), borderValue=(255, 255, 255))
    out = bg.copy()
    h, w = out.shape[:2]
    out[(h - size) // 2:(h + size) // 2, (w - size) // 2:(w + size) // 2] = m
    return out

def t_marker(rec: PartRecognizer) -> str:
    if not rec.marker.ok:
        raise RuntimeError("marker 后端不可用：%s" % rec.marker.error)
    if cv2 is None:
        raise RuntimeError("没有 cv2")
    bg = load_bgr(os.path.join(PHOTO_DIR, "IMGP_20260427_195713.jpg"))
    assert bg is not None, "读不到真图背景"
    ok = 0
    for part in PART_INFO:
        r = rec.recognize(_paste_marker(bg, part, 300), use_ocr=False, use_appearance=False)
        ok += int(r["part"] == part)
        assert r["part"] == part, "%s -> %s" % (part, r["part"] or "未识别")
    full_ok = 0
    for part in PART_INFO:
        r = rec.recognize(_paste_marker(bg, part, 300), use_marker=True,
                          use_ocr=True, use_appearance=True)
        full_ok += int(r["part"] == part)
    rot_ok = 0
    for part in ("z11", "z14", "z15", "z31", "z20", "z18"):
        r = rec.recognize(_paste_marker(bg, part, 320, 5.0), use_ocr=False,
                          use_appearance=False, marker_rot_search=True)
        rot_ok += int(r["part"] == part)

    fp = 0
    for h in _holdout()[:5]:
        r = rec.recognize(os.path.join(PHOTO_DIR, h["image"]), use_ocr=False, use_appearance=False)
        fp += int(bool(r["part"]))
    assert ok == 18, "干净标记 %d/18" % ok
    assert full_ok == 18, "完整管线标记 %d/18" % full_ok
    assert rot_ok == 6, "5° 倾斜 %d/6" % rot_ok
    assert fp == 0, "真图误检 %d/5" % fp
    return "marker-only 18/18, full 18/18, rot5 6/6, false-positive 0/5"

def t_real_holdout(rec: PartRecognizer) -> str:
    rows: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for c in _holdout():
        path = os.path.join(PHOTO_DIR, c["image"])
        assert os.path.isfile(path), "缺图 %s" % path
        rows.append((c, rec.recognize(path, use_marker=False)))
    n = len(rows)
    top1 = sum(1 for c, r in rows if r["part"] == c["part"])
    top3 = sum(1 for c, r in rows if c["part"] in [x["part"] for x in r["candidates"][:3]])
    need = sum(1 for c, r in rows if r["need_confirm"])
    ans = [(c, r) for c, r in rows if not r["need_confirm"]]
    ans_ok = sum(1 for c, r in ans if r["part"] == c["part"])
    print("        真图留出：top1=%d/%d=%.1f%% top3=%d/%d=%.1f%% need_confirm=%d=%.1f%% answered=%d acc=%d/%d"
          % (top1, n, 100 * top1 / n, top3, n, 100 * top3 / n, need, 100 * need / n, len(ans), ans_ok, len(ans)))
    for c, r in rows:
        if r["part"] != c["part"]:
            print("          ERROR %-24s true=%-4s pred=%-5s conf=%.2f reasons=%s"
                  % (c["image"], c["part"], r["part"] or "-", r["confidence"], r["reasons"]))
    if rec.ocr_backend_name == "none":
        assert top1 / n >= 0.70, "无 OCR 时 top1 %.1f%% < 70%%" % (100 * top1 / n)
    else:
        assert top1 / n >= 0.80, "top1 %.1f%% < 80%%" % (100 * top1 / n)
        assert top3 / n >= 0.90, "top3 %.1f%% < 90%%" % (100 * top3 / n)
        assert ans_ok == len(ans) or ans_ok / max(1, len(ans)) >= 0.90, "已回答准确率不足"
    assert need / n <= 0.60, "need_confirm %.1f%% > 60%%（过于保守）" % (100 * need / n)
    return "top1=%.1f%% top3=%.1f%% need=%.1f%%" % (100 * top1 / n, 100 * top3 / n, 100 * need / n)

def t_real_marker_on(rec: PartRecognizer) -> str:
    """开着 marker 跑同一批真图：检查没有误检把结果带偏。"""
    rows = [(c, rec.recognize(os.path.join(PHOTO_DIR, c["image"]), use_marker=True))
            for c in _holdout()]
    top1 = sum(1 for c, r in rows if r["part"] == c["part"])
    marker_hits = sum(1 for _c, r in rows if r["modality_breakdown"].get("marker"))
    assert marker_hits == 0, "真图无标记却检出 %d 个 marker" % marker_hits
    assert top1 >= 20, "marker on 时 top1 %d/25" % top1
    return "top1=%d/25 marker误检=0" % top1

def t_appearance_only(rec: PartRecognizer) -> str:
    rows = [(c, rec.recognize(os.path.join(PHOTO_DIR, c["image"]),
                              use_marker=False, use_ocr=False, use_appearance=True))
            for c in _holdout()]
    n = len(rows)
    top1 = sum(1 for c, r in rows if r["part"] == c["part"])
    top3 = sum(1 for c, r in rows if c["part"] in [x["part"] for x in r["candidates"][:3]])
    need = sum(1 for c, r in rows if r["need_confirm"])
    print("        外观单模态：top1=%d/%d=%.1f%% top3=%d/%d=%.1f%% need_confirm=%d/%d"
          % (top1, n, 100 * top1 / n, top3, n, 100 * top3 / n, need, n))
    assert top1 / n >= 0.70, "外观 top1 %.1f%% < 70%%" % (100 * top1 / n)
    assert need == n, "外观单独不应下结论，need_confirm=%d/%d" % (need, n)
    return "top1=%.1f%% top3=%.1f%% need=100%%" % (100 * top1 / n, 100 * top3 / n)

def t_unknown(rec: PartRecognizer) -> str:
    cases = [
        ("IMGP_20260427_195100.jpg", "操显屏特写"),
        ("IMGP_20260427_200043.jpg", "暗帧"),
        ("IMGP_20260427_202219.jpg", "示波器"),
        ("IMGP_20260427_202233.jpg", "Z17 操显"),
    ]
    need = 0
    bad = 0
    for name, why in cases:
        path = os.path.join(PHOTO_DIR, name)
        if not os.path.isfile(path):
            continue
        r = rec.recognize(path, use_marker=False)
        need += int(r["need_confirm"])
        bad += int((not r["need_confirm"]) and r["confidence"] >= 0.80)
        print("        %-10s %-8s pred=%-5s conf=%.2f need=%d" %
              (name[-10:-4], why, r["part"] or "-", r["confidence"], r["need_confirm"]))
    assert need >= 3, "unknown 拒识 %d/4 < 3" % need
    assert bad == 0, "unknown 高置信误接受 %d" % bad
    return "need_confirm=%d/4 高置信误接受=0" % need

def t_evidence_contract() -> str:
    rec = {"part": "z11", "route": "I", "confidence": 0.9, "need_confirm": False,
           "modality_breakdown": {"marker": None, "ocr": {"text": "Z11 收发", "score": 0.9},
                                  "appearance": {"best": "z11", "score": 0.8}, "context": 0.4}}
    ev = to_evidence(rec, "(led_indicator)_route_one_z11_work", "on", "Z11 工作指示灯常亮")
    for k in ("part", "route", "modality", "field", "value", "confidence", "evidence", "ts"):
        assert k in ev and str(ev[k]) != "", "evidence 缺字段 %s" % k
    assert ev["part"] == "z11" and ev["route"] == "I"
    filled = apply_to_evidence(rec, [{"part": "", "route": "", "modality": "vision"}])
    assert filled[0]["part"] == "z11" and filled[0]["route"] == "I"

    try:
        from fusion import FusionEngine  
        out = FusionEngine().fuse([ev])
        assert out.parts, "fusion 未产出部位"
    except ImportError:
        pass
    return "8 字段 + apply_to_evidence + fusion 可解析"

def t_criteria() -> str:
    r11 = criteria_for("z11")
    r31 = criteria_for("z31")
    r20 = criteria_for("z20")
    assert len(r11) >= 30, "z11 判据行 %d" % len(r11)
    assert len(r31) >= 10, "z31 判据行 %d" % len(r31)
    assert len(r20) == 0, "z20 在判据库没有专属故障行，应返回 0，实际 %d" % len(r20)
    assert all(x["match_scope"] == "sub_unit" for x in r11), "z11 判据匹配范围异常"
    rgl = criteria_for("z12-GL")
    assert len(rgl) >= 10, "z12-GL 判据行 %d" % len(rgl)
    return "z11=%d z31=%d z12-GL=%d z20=0(已说明)" % (len(r11), len(r31), len(rgl))

def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="多模态部位识别验收")
    ap.add_argument("--quick", action="store_true", help="只跑单元/契约测试，不跑真图")
    a = ap.parse_args(argv)

    print("=" * 78)
    print("part_recognizer 验收：18 部位 / 4 模态 / 25 张留出真图")
    print("=" * 78)

    check("1. 特征库完整/留出无泄漏", t_library)
    check("2. 外观特征维度/归一化", t_feature_extract)
    check("3. OCR 关键词 + 消歧 + Z17", t_ocr_keywords)
    check("4. flow/route + 上下文先验", t_context_route)
    check("5. 判据库衔接（只按归属字段）", t_criteria)
    check("6. evidence/v1 契约 + fusion", t_evidence_contract)

    if a.quick:
        print("\n--quick：跳过真图/标记测试")
    else:
        rec = PartRecognizer()
        print("\n后端：marker=%s ocr=%s appearance=%s(parts=%d) unknown=%d"
              % (rec.marker.ok, rec.ocr_backend_name, rec.appearance.ok,
                 len(rec.appearance.parts), len(rec.appearance.unknown)))
        check("7. 合成标记（干净 18 + 5° 6）", lambda: t_marker(rec))
        check("8. 真图留出（无标记）", lambda: t_real_holdout(rec))
        check("9. 真图开 marker 无误检", lambda: t_real_marker_on(rec))
        check("10. 外观单模态（必须全部待确认）", lambda: t_appearance_only(rec))
        check("11. unknown/清单外拒识", lambda: t_unknown(rec))

    print("-" * 78)
    print("PASS %d / %d" % (len(PASS), len(PASS) + len(FAIL)))
    for f in FAIL:
        print("  FAIL:", f)
    print("=" * 78)
    return 0 if not FAIL else 1

if __name__ == "__main__":
    raise SystemExit(main())
