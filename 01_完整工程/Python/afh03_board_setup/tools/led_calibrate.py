#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""led_calibrate.py —— LED **ROI 标定**工具：把"实物面板在相机里的灯位"落盘成可复用 JSON。

为什么需要标定
--------------
* 只有**标定过的 ROI**才能可靠地判"灭"（不亮的灯是暗灯罩，自动定位不可靠）；
* 标定后 `led_panel.states_from_calib()` 会做**双证据判亮**（亮点掩膜命中 + 中心-暗环 delta），
  并带**防误检门**（ROI 越界/半径超界/灯数与规则不符 → 一律"未判定"，绝不把"没标定"显示成"灯灭"）。

产物格式（与 `led_panel.Calib` 对齐）
------------------------------------
    {"work_long": 1536, "image": "...", "grid": "...",
     "parts": {"PS_KONG": [{"name":"空调电源指示","color":"R","x":527,"y":208,"r":26}, ...]}}

用法
----
    # ① 自动找候选并打印（人不看图也能拿到坐标；配合 --part 生成初稿）
    python3 tools/led_calibrate.py -i panel.jpg --part PS_KONG --auto --out config/led_calib.json
    # ② 已经有坐标，手工写入（可复制多行）
    python3 tools/led_calibrate.py --part PS_KONG --lamp 空调电源指示,R,527,208,26 \
                                              --lamp 市电电源,R,529,486,26 \
                                              --lamp 控制,G,542,955,26 --out config/led_calib.json
    # ③ 校验/查看
    python3 tools/led_calibrate.py --show config/led_calib.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2                                                     

from soc_vision.led_panel import (Calib, WORK_LONG, detect_candidates, fit_long,   
                                  lamps_only, orient_normalize)
from soc_vision.cjk_text import draw_text                        
from soc_vision.led_rules import RuleBook                       

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="LED ROI 标定（落盘为可复用 JSON）")
    ap.add_argument("-i", "--image", default="", help="标定用照片")
    ap.add_argument("--part", default="", help="部件 id（规则表里的 id）")
    ap.add_argument("--auto", action="store_true", help="自动检测候选灯位并按规则顺序填入")
    ap.add_argument("--lamp", action="append", default=[],
                    help="手工指定一颗灯：名称,颜色,x,y,r（可重复）")
    ap.add_argument("--out", default="config/led_calib.json")
    ap.add_argument("--show", default="", help="打印已有标定 JSON")
    ap.add_argument("--live", action="store_true",
                    help="★ 现场一键标定：从 /dev/video22 抓一张实时帧 -> 自动找灯 -> 输出编号图 + 候选 ROI")
    ap.add_argument("--device", default="/dev/video22")
    ap.add_argument("--catalog", default=os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "config", "parts_catalog.json"))
    ap.add_argument("--bind", default="",
                    help='★ 绑定：把编号图上的编号绑到灯名，例如 "1=工作,2=本路,3=发射通,4=发射断,5=故障"')
    ap.add_argument("--numbered", default="", help="编号图输出路径（默认 out/calib_numbered.jpg）")
    ap.add_argument("--rules", default="")
    a = ap.parse_args(argv)

    if a.show:
        c = Calib.load(a.show)
        print("标定文件: %s  work_long=%d  部件数=%d" % (a.show, c.work_long, len(c.parts)))
        for pid, rois in c.parts.items():
            print("  %-12s %d 颗" % (pid, len(rois)))
            for r in rois:
                print("     %-22s %s x=%d y=%d r=%d" % (r.get("name"), r.get("color"),
                                                        r.get("x", -1), r.get("y", -1), r.get("r", 0)))
        return 0

    if a.live:
        import glob as _glob
        bgr = None

        try:
            cap = cv2.VideoCapture(a.device, cv2.CAP_V4L2)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUYV"))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
                ok, f = cap.read()
                if ok and f is not None:
                    bgr = f
                    print("  已从 %s 抓到实时帧 %s" % (a.device, f.shape))
            cap.release()
        except Exception as e:                                       
            print("  实时抓帧失败（%s），改用照片兜底" % e)
        if bgr is None:
            shot = sorted(_glob.glob("/userdata/afh03_shots/*/full.jpg"),
                          key=os.path.getmtime)[-1:] or []
            if a.image:
                bgr = cv2.imread(a.image, cv2.IMREAD_COLOR)
            elif shot:
                bgr = cv2.imread(shot[0], cv2.IMREAD_COLOR)
                print("  兜底用照片 %s" % shot[0])
        if bgr is None:
            print("  拿不到画面（--device 被占用或没有照片）")
            return 3
        bgr, rot = orient_normalize(bgr)
        bgr = fit_long(bgr, WORK_LONG)
        cands = sorted(lamps_only(detect_candidates(bgr)), key=lambda z: (z.y, z.x))
        print("  朝向归一=%s 工作尺寸=%dx%d 检出候选灯 %d 颗" % (rot, bgr.shape[1], bgr.shape[0], len(cands)))
        vis = bgr.copy()
        cand_rois = []
        for i, cd in enumerate(cands, 1):
            col = {"R": (60, 60, 230), "G": (80, 200, 90)}.get(cd.color, (200, 200, 200))
            cv2.circle(vis, (cd.x, cd.y), max(8, int(cd.r * 1.6)), col, 3)
            cv2.putText(vis, "%d" % i, (cd.x - 12, cd.y + 12), cv2.FONT_HERSHEY_SIMPLEX, 1.6,
                        (0, 0, 0), 6)
            cv2.putText(vis, "%d" % i, (cd.x - 12, cd.y + 12), cv2.FONT_HERSHEY_SIMPLEX, 1.6,
                        (255, 255, 255), 3)
            draw_text(vis, "%d号 %s" % (i, cd.color), (cd.x + int(cd.r * 1.8), cd.y - int(cd.r * 1.8)),
                      scale=0.7, color=col, th=2)
            cand_rois.append({"idx": i, "name": "", "color": cd.color, "x": int(cd.x), "y": int(cd.y),
                              "r": int(cd.r), "delta": round(cd.delta, 1)})

        marker_info = ""
        try:
            import sys as _sys
            _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from soc_vision.marker_id import MarkerId
            mi = MarkerId(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                       "markers_modules.json"), confirm_n=1, verbose=False)
            hit, hits = mi.detect(bgr)
            if hit is not None:
                marker_info = "模块=%s %s 置信=%.2f 边长=%.0fpx" % (
                    hit.label, (hit.module or {}).get("name", ""), hit.score, hit.side_px)
                print("  [标记] %s" % marker_info)
                draw_text(bgr, marker_info[:46], (16, 34), scale=0.8, color=(120, 220, 140), th=2)
                cv2.circle(bgr, (int(hit.cx), int(hit.cy)), int(hit.side_px / 2), (120, 220, 140), 3)
            else:
                print("  [标记] 未检出（候选 %d 个）→ 需人工确认模块" % len(hits))
        except Exception as _e:                                          
            print("  [标记] 不可用: %s" % _e)
        out_png = a.numbered or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                             "out", "calib_numbered.jpg")
        os.makedirs(os.path.dirname(out_png), exist_ok=True)
        cv2.imwrite(out_png, vis)
        draw_text(vis, "共 %d 颗候选灯；请把「编号=灯名」发给现场绑定" % len(cands), (16, vis.shape[0] - 16),
                  scale=0.7, color=(255, 255, 255), th=1)
        cv2.imwrite(out_png, vis)

        c2 = Calib(work_long=WORK_LONG)
        if os.path.isfile(a.out):
            try:
                c2 = Calib.load(a.out)
            except Exception:                                        
                pass
        c2.parts["_candidates"] = cand_rois
        c2.image = os.path.basename(out_png)
        c2.grid = "live(%s)" % ("rot90CW" if rot else "none")
        c2.parts["_marker"] = [{"info": marker_info}] if marker_info else []
        c2.save(a.out)
        print("  编号图: %s（共 %d 颗）" % (out_png, len(cands)))
        print("  候选 ROI 已写入 %s 的 _candidates 段（**归属待绑定**）" % a.out)
        print("  下一步（现场）：把编号对应关系发我/或自己跑：")
        print('    python3 tools/led_calibrate.py --bind "1=工作,2=本路,3=发射通,4=发射断,5=故障" --part TX_STATE --out %s' % a.out)
        return 0

    if a.bind:
        if not os.path.isfile(a.out):
            print("  还没有标定文件 %s，请先跑 --live" % a.out)
            return 3
        c2 = Calib.load(a.out)
        cands2 = c2.parts.get("_candidates") or []
        if not cands2:
            print("  %s 里没有 _candidates（请先 --live）" % a.out)
            return 3
        by_idx = {int(z["idx"]): z for z in cands2}
        part = a.part or a.bind.split("=")[0]
        rois = []
        for kv in a.bind.split(","):
            kv = kv.strip()
            if not kv or "=" not in kv:
                continue
            k, v = kv.split("=", 1)
            try:
                idx = int(k.strip().lstrip("#"))
            except ValueError:
                print("  跳过非法编号 %r" % kv)
                continue
            z = by_idx.get(idx)
            if z is None:
                print("  跳过：编号 %d 不在候选里" % idx)
                continue
            rois.append({"name": v.strip(), "color": z.get("color", "R"), "x": int(z["x"]),
                         "y": int(z["y"]), "r": int(z["r"]), "delta": z.get("delta")})
        if not rois:
            print("  没有绑定成功")
            return 3
        c2.parts[part] = rois
        c2.save(a.out)
        print("  已把 %d 颗灯绑定到部件 %s 并写回 %s" % (len(rois), part, a.out))
        print("  之后 UI/跑批带 --calib %s --part %s 即可（归属来自 ROI，不再靠猜）" % (a.out, part))
        return 0

    calib = None
    if os.path.isfile(a.out):
        try:
            calib = Calib.load(a.out)
        except Exception:                                     
            calib = None
    calib = calib or Calib(work_long=WORK_LONG)
    book = RuleBook.load(a.rules or None)

    if a.image and a.part and a.auto:
        raw = cv2.imread(a.image, cv2.IMREAD_COLOR)
        if raw is None:
            print("读不到图: %s" % a.image)
            return 1
        bgr, rot = orient_normalize(raw)
        bgr = fit_long(bgr, WORK_LONG)
        rule = book.get(a.part)
        if rule is None:
            print("规则表里没有部件 %s" % a.part)
            return 2
        cands = lamps_only(detect_candidates(bgr))
        print("朝向归一=%s 工作尺寸=%dx%d 检出候选 %d 颗（需 %d 颗）"
              % (rot, bgr.shape[1], bgr.shape[0], len(cands), len(rule.lamps)))
        cands.sort(key=lambda c: (c.y, c.x))
        rois = []
        for i, ls in enumerate(rule.lamps):
            if i < len(cands):
                c = cands[i]
                rois.append({"name": ls.name, "color": c.color if c.color != "W" else ls.color,
                             "x": int(c.x), "y": int(c.y), "r": int(c.r), "delta": round(c.delta, 1)})
            else:
                print("  !! 第 %d 颗（%s）没找到候选 —— **请人工补**（不要瞎填，宁可留空）" % (i + 1, ls.name))
        calib.parts[a.part] = rois
        calib.image = os.path.basename(a.image)
        calib.grid = "auto(%s)" % ("rot90CW" if rot else "none")
        print("自动标定写入 %d 颗到部件 %s（**建议人工复核**）" % (len(rois), a.part))

    for spec in a.lamp:
        parts = spec.split(",")
        if len(parts) < 5:
            print("--lamp 格式应为 名称,颜色,x,y,r ：%r" % spec)
            continue
        name, color, x, y, r = parts[0], parts[1], parts[2], parts[3], parts[4]
        calib.parts.setdefault(a.part or "UNKNOWN", []).append(
            {"name": name, "color": color, "x": int(x), "y": int(y), "r": int(r)})

    if not (a.image and a.auto) and not a.lamp:
        ap.print_help()
        return 1
    calib.save(a.out)
    print("已写标定文件: %s" % a.out)
    print("下一步（板端）：把实物面板摆到相机前，用 python3 -m soc_vision.ui_app --part %s --calib %s 跑界面"
          % (a.part or "<部件id>", a.out))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
