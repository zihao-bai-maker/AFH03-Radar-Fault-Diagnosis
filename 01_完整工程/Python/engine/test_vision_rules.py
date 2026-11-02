#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_vision_rules.py —— 摄像头类判定引擎的合成用例测试（不需要现场照片）

为什么要合成用例
================
现场 119 张真图里**没有**黑屏、花屏、绿灯灭这些故障样本（现场当时只有黄屏和正常屏），
所以这些分支只能靠合成图钉住行为；真图用来验证"不误判、不乱判"。

覆盖（14 项）
------------
 1 黑屏            → black_screen
 2 黄屏            → yellow_screen
 3 花屏            → garbled
 4 绿灯亮          → on + G
 5 红灯亮          → on + R
 6 暗场红灯        → on（低照度仍可判）
 7 Z11 五灯排      → 逐灯条目（本路 on / 发射通 off / 故障 off）
 8 糊片/无目标     → 全部 undetermined，且 has_target=False
 9 无回波屏        → no_echo
10 灰区灯（delta 刚好不够） → undetermined（宁可不判）
11 I/II 路镜像     → 同一张照片同时出 I、II 两路，镜像条目带 route_mirrored
12 证据 JSON 结构  → 必需字段/取值域/可序列化
13 判据目录        → 61 项、key 唯一、field 非空、binding 合法
14 CLI 冒烟        → --image 能跑通并落盘

运行：``python test_vision_rules.py``（或 ``python vision_rules.py --selftest``）
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from typing import Any, Callable, Dict, List, Tuple

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vision_rules as V  

W, H = 1200, 900
RESULTS: List[Tuple[str, bool, str]] = []

def canvas(mean: int = 150, noise: int = 6, seed: int = 0) -> np.ndarray:
    """灰面板：轻微噪声（真实照片不会是完全平的）。"""
    rng = np.random.default_rng(seed)
    base = np.full((H, W, 3), mean, dtype=np.float32)
    base += rng.normal(0, noise, base.shape)
    return np.clip(base, 0, 255).astype(np.uint8)

def fill_rect(img: np.ndarray, x0: int, y0: int, x1: int, y1: int, bgr: Tuple[int, int, int]) -> None:
    img[y0:y1, x0:x1] = np.array(bgr, dtype=np.uint8)

def draw_lamp(img: np.ndarray, x: int, y: int, r: int, bgr: Tuple[int, int, int], on: bool) -> None:
    """画一颗灯：on = 亮盘 + 光晕；off = 暗灯罩（比面板暗）。"""
    yy, xx = np.mgrid[0:H, 0:W]
    rr = np.sqrt((xx - x) ** 2 + (yy - y) ** 2)
    if on:
        glow = np.exp(-(rr / (r * 2.4)) ** 2) * 0.55
        for c in range(3):
            img[:, :, c] = np.clip(img[:, :, c].astype(np.float32) + glow * bgr[c], 0, 255).astype(np.uint8)
        m = rr <= r
        img[m] = np.array(bgr, dtype=np.uint8)
    else:
        m = rr <= r
        dark = tuple(max(0, int(v * 0.32)) for v in bgr)
        img[m] = np.array(dark, dtype=np.uint8)

def screen_image(state: str) -> np.ndarray:
    """造一块带边框的显示屏（bezel 灰、屏面按 state 填）。"""
    img = canvas(150, 5, seed=hash(state) % 1000)

    fill_rect(img, 240, 170, 960, 730, (120, 128, 132))
    if state == "black":
        fill_rect(img, 260, 190, 940, 710, (6, 6, 6))
    elif state == "yellow":
        fill_rect(img, 260, 190, 940, 710, (150, 232, 250))     
    elif state == "garbled":
        rng = np.random.default_rng(7)
        noise = rng.integers(0, 255, (520, 680, 3), dtype=np.uint8)
        img[190:710, 260:940] = noise
    elif state == "echo":
        img[190:710, 260:940] = np.array((30, 30, 26), dtype=np.uint8)
        for gx in range(280, 940, 55):                        
            img[190:710, gx:gx + 2] = (60, 200, 70)
        for gy in range(200, 710, 55):
            img[gy:gy + 2, 260:940] = (60, 200, 70)
        rng = np.random.default_rng(3)                        
        sub = img[200:700, 280:920].astype(np.int16)
        sub += rng.integers(0, 26, sub.shape, dtype=np.int16)
        img[200:700, 280:920] = np.clip(sub, 0, 255).astype(np.uint8)
    elif state == "noise_only":

        rng = np.random.default_rng(9)
        base = np.zeros((520, 680, 3), dtype=np.int16)
        base[:, :] = (50, 110, 60)
        base += rng.normal(0, 25, base.shape).astype(np.int16)
        img[190:710, 260:940] = np.clip(base, 0, 255).astype(np.uint8)
    return img

def lamp_row_image(states: List[bool], colors: List[Tuple[int, int, int]], delta_darken: bool = False) -> np.ndarray:
    img = canvas(150, 5, seed=11)
    xs = [420 + i * 78 for i in range(len(states))]
    for i, (on, col) in enumerate(zip(states, colors)):
        draw_lamp(img, xs[i], 340, 11, col, on)
    if delta_darken:            
        for i, on in enumerate(states):
            if on:
                draw_lamp(img, xs[i], 340, 11, (40, 40, 40), False)
                img[340 - 8:340 + 8, xs[i] - 8:xs[i] + 8] = (172, 176, 178)
    return img

def to_ctx(img: np.ndarray) -> V.PhotoCtx:
    ctx = V.PhotoCtx(path="<synth>", ts="2026-10-18T08:00:00+08:00")
    ctx.scene = V.scene_gate(img)
    ctx.lamps, dbg = V.detect_lamps(img)
    ctx.rows = V.find_lamp_rows(ctx.lamps)
    ctx.screen = V.find_screen(img)
    ctx.debug = dbg
    ctx.scene.has_target = bool(ctx.rows or ctx.screen)
    return ctx

def ev_for(img: np.ndarray, part: str = "", kind: str = "", mirror: bool = True) -> List[Dict[str, Any]]:
    ctx = to_ctx(img)
    items = V.load_catalog()
    ev = V.evaluate_items(items, ctx, bgr=img, part_hint=part, mirror_routes=mirror, kind=kind)
    return [e.to_dict() for e in ev]

def _screen_state(img: np.ndarray) -> str:
    sc = V.find_screen(img)
    return sc.state if sc else "none"

def t01_black_screen():
    st = _screen_state(screen_image("black"))
    assert st == "black_screen", "黑屏被判成 %s" % st
    return "黑屏 → black_screen"

def t02_yellow_screen():
    st = _screen_state(screen_image("yellow"))
    assert st == "yellow_screen", "黄屏被判成 %s" % st
    return "黄屏 → yellow_screen"

def t03_garbled():
    st = _screen_state(screen_image("garbled"))
    assert st == "garbled", "花屏被判成 %s" % st
    return "花屏 → garbled"

def t04_green_led_on():
    img = canvas(150, 5, seed=2)
    draw_lamp(img, 600, 450, 12, (60, 245, 60), True)
    ctx = to_ctx(img)
    assert ctx.lamps, "没检测到灯"
    lamp = max(ctx.lamps, key=lambda o: o.confidence)
    assert lamp.on, "绿灯没判成 on（delta=%.1f）" % lamp.delta
    assert lamp.color == "G", "绿灯颜色判成 %s" % lamp.color
    assert lamp.confidence >= V.TH["conf_min"], "置信 %.2f 过低" % lamp.confidence
    return "绿灯亮 → on/G（conf=%.2f, delta=%+.0f）" % (lamp.confidence, lamp.delta)

def t05_red_led_on():
    img = canvas(150, 5, seed=3)
    draw_lamp(img, 500, 400, 13, (40, 40, 250), True)
    ctx = to_ctx(img)
    lamp = max(ctx.lamps, key=lambda o: o.confidence)
    assert lamp.on and lamp.color == "R", "红灯判成 on=%s color=%s" % (lamp.on, lamp.color)
    return "红灯亮 → on/R（delta=%+.0f）" % lamp.delta

def t06_dark_scene_led():
    img = canvas(22, 8, seed=4)
    draw_lamp(img, 700, 300, 11, (40, 40, 250), True)
    ctx = to_ctx(img)
    assert ctx.scene.dark, "场景没判成暗场（mean=%.0f）" % ctx.scene.mean_v
    lamp = max(ctx.lamps, key=lambda o: o.confidence)
    assert lamp.on, "暗场红灯没判成 on（delta=%.1f）" % lamp.delta
    return "暗场红灯 → on（scene.mean_v=%.0f, delta=%+.0f）" % (ctx.scene.mean_v, lamp.delta)

def t07_z11_five_row():
    img = lamp_row_image([False, True, False, True, False],
                         [(50, 210, 60), (50, 245, 60), (50, 210, 60), (40, 40, 240), (40, 40, 240)])
    ctx = to_ctx(img)
    assert ctx.rows and len(ctx.rows[0].obs) == 5, "5 灯排没聚出来：%s" % [len(r.obs) for r in ctx.rows]
    ev = ev_for(img, part="z11", kind="led")
    by_field = {e["field"]: e for e in ev}
    want_on = "(led_indicator)_z11_local_route"
    want_off = "(led_indicator)_z11_tx_on"
    assert want_on in by_field, "缺 本路 条目：%s" % list(by_field)
    assert by_field[want_on]["value"] == "on", "本路应亮，实得 %s" % by_field[want_on]["value"]
    assert by_field[want_off]["value"] == "off", "发射通应灭，实得 %s" % by_field[want_off]["value"]
    f = by_field.get("(led_indicator)_z11_fault")
    assert f is not None and f["value"] == "off", "故障灯应灭"
    return "Z11 五灯排 → 本路 on / 发射通 off / 故障 off（%d 条证据）" % len(ev)

def t08_blurry_no_target():
    img = canvas(178, 1, seed=5)          
    ctx = to_ctx(img)
    assert not ctx.scene.sharp, "糊片没判成不清晰（grad=%.2f）" % ctx.scene.grad
    assert not ctx.scene.has_target, "糊片被判成有目标"
    ev = ev_for(img)
    assert ev and all(e["value"] == "undetermined" for e in ev), "有非 undetermined 结论"
    return "糊片 → %d 条全 undetermined（grad=%.2f）" % (len(ev), ctx.scene.grad)

def t09_no_echo():
    img = screen_image("noise_only")      
    sc = V.find_screen(img)
    assert sc is not None, "屏幕没定位到"
    assert sc.state == "no_echo", "无回波被判成 %s（%s）" % (sc.state, sc.evidence)
    return "无回波屏 → no_echo（亮像素 %.2f%%、纹理 %.4f）" % (sc.metrics.bright_frac * 100,
                                                              sc.metrics.texture)

def t10_gray_zone_undetermined():
    """灯只比面板亮一点点（delta 落在灰区）→ 必须 undetermined。"""
    img = canvas(150, 5, seed=6)
    img[440:462, 590:612] = (158, 160, 162)          
    ctx = to_ctx(img)
    ev = ev_for(img, part="z11", kind="led")
    assert ev, "没有产出证据"
    assert all(e["value"] == "undetermined" for e in ev), "灰区灯给了结论：%s" % [e["value"] for e in ev]
    return "灰区灯 → 全 undetermined（%d 条）" % len(ev)

def t11_route_mirror():
    img = lamp_row_image([True, True, False, False, False],
                         [(50, 245, 60), (50, 245, 60), (50, 210, 60), (40, 40, 240), (40, 40, 240)])
    ev = ev_for(img, part="z11", kind="led", mirror=True)
    routes = {e["route"] for e in ev}
    assert {"I", "II"} <= routes, "I/II 两路没出全：%s" % routes
    mirrored = [e for e in ev if e["route_mirrored"]]
    assert mirrored, "没有标 route_mirrored 的镜像条目"
    assert any("I/II 镜像" in e["evidence"] for e in mirrored), "镜像条目没写清来源"
    assert len(mirrored) < len(ev), "全部都是镜像条目，说明没有原生条目"
    return "I/II 镜像 → %d 条（其中镜像 %d 条）" % (len(ev), len(mirrored))

def t12_evidence_schema():
    img = lamp_row_image([False, True, False, False, False],
                         [(50, 210, 60), (50, 245, 60), (50, 210, 60), (40, 40, 240), (40, 40, 240)])
    ev = ev_for(img, part="z11", kind="led")
    need = {"part", "route", "modality", "field", "value", "confidence", "evidence", "ts", "state"}
    for e in ev:
        miss = need - set(e)
        assert not miss, "证据缺字段 %s" % miss
        assert e["modality"] == "vision", "modality 不是 vision"
        assert 0.0 <= e["confidence"] <= 1.0, "置信越界 %s" % e["confidence"]
        assert e["value"] in ("on", "off", "undetermined"), "取值越界 %s" % e["value"]
        assert e["ts"].startswith("20"), "ts 不像时间戳：%s" % e["ts"]
    json.dumps(ev, ensure_ascii=False)          
    return "证据 JSON → %d 条全部满足 8 必需字段 + 取值域 + 可序列化" % len(ev)

def t13_catalog():
    items = V.load_catalog()
    assert len(items) == 61, "摄像头类判据应为 61 项，实得 %d" % len(items)
    keys = [i.key for i in items]
    assert len(set(keys)) == 61, "key 有重复：%s" % [k for k in keys if keys.count(k) > 1]
    cats: Dict[str, int] = {}
    for i in items:
        cats[i.category or "(空)"] = cats.get(i.category or "(空)", 0) + 1
        assert i.field, "条目 %s 没有 field" % i.key
        assert i.binding in ("led", "led_unbound", "screen", "meter", "dynamic", "none"), \
            "条目 %s 的 binding 非法：%s" % (i.key, i.binding)
    assert cats.get("指示灯") == 38, "指示灯类应为 38 项，实得 %s" % cats.get("指示灯")
    assert cats.get("显示画面") == 18, "显示画面类应为 18 项，实得 %s" % cats.get("显示画面")
    assert cats.get("微表区") == 4, "微表区应为 4 项，实得 %s" % cats.get("微表区")
    empty_part = [i.key for i in items if not i.part]
    assert not empty_part, "evidence/v1 要求 part 非空，这些条目为空：%s" % empty_part
    assert all(i.route in ("I", "II", "") for i in items), "route 只能是 I/II/空串"
    bound = sum(1 for i in items if i.binding in ("led", "screen", "meter"))
    return "判据目录 → 61 项（指示灯 38 / 显示画面 18 / 微表 4），已绑定 %d 项" % bound

def t14_cli_smoke():
    img = lamp_row_image([False, True, False, False, False],
                         [(50, 210, 60), (50, 245, 60), (50, 210, 60), (40, 40, 240), (40, 40, 240)])
    d = tempfile.mkdtemp(prefix="vision_selftest_")
    p = os.path.join(d, "synth.jpg")
    Image.fromarray(img[:, :, ::-1]).save(p, quality=92)
    out = os.path.join(d, "ev.json")
    rc = V.main(["--image", p, "--part", "z11", "--kind", "led", "--quiet", "--out", out])
    assert rc == 0, "CLI 返回 %d" % rc
    r = json.load(open(out, encoding="utf-8"))
    assert r["n_decided"] > 0, "CLI 没产出已判定证据"
    os.remove(p)
    os.remove(out)
    os.rmdir(d)
    return "CLI --image → rc=0，判定 %d 条" % r["n_decided"]

CASES: List[Tuple[str, Callable[[], str]]] = [
    ("01 黑屏", t01_black_screen),
    ("02 黄屏", t02_yellow_screen),
    ("03 花屏", t03_garbled),
    ("04 绿灯亮", t04_green_led_on),
    ("05 红灯亮", t05_red_led_on),
    ("06 暗场红灯", t06_dark_scene_led),
    ("07 Z11 五灯排", t07_z11_five_row),
    ("08 糊片无目标", t08_blurry_no_target),
    ("09 无回波", t09_no_echo),
    ("10 灰区灯不判", t10_gray_zone_undetermined),
    ("11 I/II 路镜像", t11_route_mirror),
    ("12 证据 JSON 结构", t12_evidence_schema),
    ("13 判据目录 61 项", t13_catalog),
    ("14 CLI 冒烟", t14_cli_smoke),
]

def main(argv=None) -> int:
    print("=" * 78)
    print("vision_rules 自检：%d 个合成用例（不需要现场照片）" % len(CASES))
    print("=" * 78)
    ok = 0
    fails: List[str] = []
    for name, fn in CASES:
        try:
            msg = fn()
            ok += 1
            print("  ✅ %-18s %s" % (name, msg))
        except AssertionError as exc:
            fails.append("%s: %s" % (name, exc))
            print("  ❌ %-18s %s" % (name, exc))
        except Exception:
            fails.append("%s: EXC %s" % (name, traceback.format_exc(limit=2).replace("\n", " | ")))
            print("  ❌ %-18s 异常：%s" % (name, traceback.format_exc(limit=2).strip().splitlines()[-1]))
    n = len(CASES)
    print("-" * 78)
    print("通过 %d/%d = %.1f%%" % (ok, n, 100.0 * ok / n))
    if fails:
        print("失败明细：")
        for f in fails:
            print("  -", f)
    print("复用模块：led_rules=%s led_panel=%s screen_read_v2=%s cv2=%s"
          % (V.LR is not None, V.LP is not None, V.SRV2 is not None, V.cv2 is not None))
    return 0 if not fails else 1

if __name__ == "__main__":
    raise SystemExit(main())
