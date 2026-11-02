# -*- coding: utf-8 -*-
"""
test_boundary_detect.py -- 在 119 张真实照片上批量跑 boundary_detect
====================================================================

产出（只写 雷达判据/_shots/edge/，不动照片）
--------------------------------------------
  edge_results.json        每张图的 found/kind/confidence/box/边证据/耗时
  edge_<name>.jpg          8 张代表性可视化（含置信度、检出边、支持边）
  edge_montage.jpg         上面 8 张的拼图
  roi_crop_<name>.jpg      ROI 自动裁剪示例
  roi_marker_demo.jpg      "边界先划范围，再在范围内找标记"的小实验
  edge_all_contact.jpg     119 张缩略图 + 检出框总览（便于人工复核）

用法：
  python test_boundary_detect.py                 # 全量 + 稳定性 + ROI demo
  python test_boundary_detect.py --no-stability  # 跳过双尺度稳定性（快一半）
  python test_boundary_detect.py --no-demo
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from boundary_detect import detect_boundary, crop_to_boundary   

PHOTO_DIR = r"D:\xuexishengshou\雷达照片_今天\拍照UI照片"
OUT_DIR = os.path.join(ROOT, "_shots", "edge")

VIS = ["202427", "202211", "202433", "202146", "202325", "202154", "195605", "195941"]

MANUAL = {
    "202427": {"correct": True, "why": "右侧竖边：面板外缘/蓝灰包边，置信 0.86"},
    "202211": {"correct": True, "why": "上沿横边：顶部蓝灰包边下缘，轮廓剖面吸附到 y≈112px"},
    "202433": {"correct": True, "why": "右侧竖边：本柜与右邻柜之间的蓝灰包边"},
    "202146": {"correct": True, "why": "上沿横边：顶部蓝灰包边，dE=14.3"},
    "202325": {"correct": True, "why": "右侧竖边：Z11 门板右缘蓝灰包边"},
    "202154": {"correct": True, "why": "上沿横边：柜体上沿/包边，dE=8.7"},
    "195605": {"correct": False, "why": "误检：矩形套在显示器屏幕上（屏幕被当成面板）"},
    "195941": {"correct": True, "why": "正确拒绝：全景/遮挡，整柜四周边界不在画面内，found=False"},
}

def font(px, bold=False):
    for p in ((r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc"),
              r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, int(px))
            except Exception:
                pass
    return ImageFont.load_default()

def annotate(im: Image.Image, r: dict, title: str = "") -> Image.Image:
    out = im.copy()
    d = ImageDraw.Draw(out)
    W, H = out.size
    poly = [tuple(p) for p in r["polygon"]]
    if r["found"]:
        d.line(poly + [poly[0]], fill=(0, 255, 70), width=5)
    else:
        d.rectangle([1, 1, W - 2, H - 2], outline=(160, 160, 160), width=2)
    for z in r["lines"]:
        if not r["found"]:
            col, wid = (120, 120, 120), 2       
        else:
            col = (255, 40, 40) if z["supported"] else (255, 170, 0)
            wid = 6 if z["supported"] else 3
        d.line([tuple(z["p0"]), tuple(z["p1"])], fill=col, width=wid)
        mx = (z["p0"][0] + z["p1"][0]) / 2
        my = (z["p0"][1] + z["p1"][1]) / 2
        lbl = "%s dE=%.1f%s" % (z["side"], z["dE"], " H" if z["hough_ok"] else "")
        d.text((mx - 40, my - 24), lbl, fill=(255, 255, 0), font=font(20, True))

    lines = [
        "%s  found=%s  kind=%s" % (title or "", r["found"], r["kind"]),
        "conf=%.2f  edge=%s  sides=%d/%d  Hough=%d" % (
            r["confidence"], r["edge_type"] or "-", r["supported_sides"],
            r["visible_sides"], r["hough_sides"]),
        "area=%.2f  fill=%.2f  box=%s" % (r["area_frac"], r["fill"], r["box_px"]),
        r["note"],
    ]
    bw = int(min(W - 20, max(420, len(lines[1]) * 11)))
    d.rectangle([8, 8, 8 + bw, 8 + 28 * len(lines) + 8], fill=(0, 0, 0))
    for i, ln in enumerate(lines):
        d.text((16, 12 + i * 28), ln, fill=(0, 255, 120) if i == 0 else (245, 245, 245),
               font=font(19))
    return out

def bbox_iou(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
    inter = iw * ih
    ua = max(1, (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter)
    return inter / float(ua)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-stability", action="store_true")
    ap.add_argument("--no-demo", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)

    files = sorted(f for f in os.listdir(PHOTO_DIR) if f.lower().endswith(".jpg"))
    if args.limit:
        files = files[:args.limit]
    names = [os.path.splitext(f)[0].split("_")[-1] for f in files]
    print("照片 %d 张：%s" % (len(files), PHOTO_DIR))

    results = []
    t_all = time.perf_counter()
    for k, (fn, nm) in enumerate(zip(files, names)):
        p = os.path.join(PHOTO_DIR, fn)
        try:
            im = Image.open(p).convert("RGB")
        except Exception as e:                                        
            print("  跳过 %s: %s" % (fn, e))
            continue
        t = time.perf_counter()
        r = detect_boundary(im)
        r["sec"] = round(time.perf_counter() - t, 3)
        r["file"] = fn
        r["name"] = nm
        results.append(r)
        if (k + 1) % 20 == 0:
            print("  ... %d/%d" % (k + 1, len(files)))

    found = [r for r in results if r["found"]]
    kinds = Counter(r["kind"] for r in found)
    edges = Counter(r["edge_type"] for r in found)
    confs = sorted(r["confidence"] for r in found)
    hist = [0] * 5
    for c in confs:
        hist[min(4, int(c * 5))] += 1
    print("\n=== 全量结果 ===")
    print("  检出边界 %d/%d = %.1f%%" % (len(found), len(results), 100.0 * len(found) / max(1, len(results))))
    print("  kind: %s" % dict(kinds))
    print("  edge_type: %s" % dict(edges))
    if confs:
        print("  confidence: min=%.2f median=%.2f max=%.2f  分布[0-.2,.2-.4,.4-.6,.6-.8,.8-1]=%s"
              % (confs[0], confs[len(confs) // 2], confs[-1], hist))
    print("  平均耗时 %.2fs/张" % (sum(r["sec"] for r in results) / max(1, len(results))))

    stab = {"n": 0, "both_found": 0, "iou_ok": 0, "same_found": 0, "details": []}
    if not args.no_stability:
        sub = results[::3]
        print("\n=== 双尺度稳定性（max_side 600 vs 800，%d 张）===" % len(sub))
        for r in sub:
            im = Image.open(os.path.join(PHOTO_DIR, r["file"])).convert("RGB")
            r1 = detect_boundary(im, max_side=600)
            r2 = detect_boundary(im, max_side=800)
            stab["n"] += 1
            if r1["found"] == r2["found"]:
                stab["same_found"] += 1
            if r1["found"] and r2["found"]:
                stab["both_found"] += 1
                iou = bbox_iou(r1["box_px"], r2["box_px"])
                ok = iou >= 0.85
                stab["iou_ok"] += 1 if ok else 0
                if not ok:
                    stab["details"].append({"name": r["name"], "iou": round(iou, 3),
                                            "box600": r1["box_px"], "box800": r2["box_px"]})
        print("  两者都检出 %d；found 一致 %d/%d；bbox IoU>=0.85 %d/%d = %.1f%%"
              % (stab["both_found"], stab["same_found"], stab["n"], stab["iou_ok"],
                 stab["both_found"], 100.0 * stab["iou_ok"] / max(1, stab["both_found"])))

    by_name = {r["name"]: r for r in results}
    thumbs = []
    for nm in VIS:
        r = by_name.get(nm)
        if r is None:
            continue
        im = Image.open(os.path.join(PHOTO_DIR, r["file"])).convert("RGB")
        ann = annotate(im, r, "IMGP_20260427_%s" % nm)
        ann.thumbnail((1280, 1280))
        p = os.path.join(OUT_DIR, "edge_%s.jpg" % nm)
        ann.save(p, quality=92)
        print("  vis -> %s" % p)
        th = ann.copy()
        th.thumbnail((640, 360))
        thumbs.append((nm, th))
    if thumbs:
        cols, rows = 2, 4
        W, H = 640, 360 + 26
        sheet = Image.new("RGB", (cols * W, rows * H), (20, 20, 20))
        d = ImageDraw.Draw(sheet)
        for k, (nm, th) in enumerate(thumbs):
            x, y = (k % cols) * W, (k // cols) * H
            sheet.paste(th, (x, y))
            r = by_name[nm]
            d.text((x + 8, y + 362), "%s  found=%s conf=%.2f kind=%s"
                   % (nm, r["found"], r["confidence"], r["kind"]),
                   fill=(255, 255, 120), font=font(18, True))
        mp = os.path.join(OUT_DIR, "edge_montage.jpg")
        sheet.save(mp, quality=90)
        print("  montage -> %s" % mp)

    cols, rows, tw, thh = 6, 5, 320, 180
    per = cols * rows
    for s in range((len(results) + per - 1) // per):
        sheet = Image.new("RGB", (cols * tw, rows * (thh + 18)), (15, 15, 15))
        d = ImageDraw.Draw(sheet)
        for k, r in enumerate(results[s * per:(s + 1) * per]):
            im = Image.open(os.path.join(PHOTO_DIR, r["file"])).convert("RGB")
            im.thumbnail((tw, thh))
            x, y = (k % cols) * tw, (k // cols) * (thh + 18)
            sheet.paste(im, (x, y))
            poly = [(p[0] * im.size[0] / r["scale"][0], p[1] * im.size[1] / r["scale"][1])
                    for p in r["polygon"]]
            if r["found"]:
                d.line(poly + [poly[0]], fill=(0, 255, 70), width=2)
            col = (0, 255, 70) if r["found"] else (150, 150, 150)
            d.text((x + 4, y + thh + 1), "%s %s %.2f" % (r["name"], r["kind"][:4], r["confidence"]),
                   fill=col, font=font(14))
        if s == 0:
            mp = os.path.join(OUT_DIR, "edge_all_contact.jpg")
            sheet.save(mp, quality=88)
            print("  all-contact -> %s（其余分页略）" % mp)

    if by_name.get("202427") and by_name["202427"]["found"]:
        r = by_name["202427"]
        im = Image.open(os.path.join(PHOTO_DIR, r["file"])).convert("RGB")
        crop, box = crop_to_boundary(im, r, margin=0.0, return_box=True)
        crop.save(os.path.join(OUT_DIR, "roi_crop_202427.jpg"), quality=92)
        print("  ROI crop: %s -> %s（面积 %.1f%%）"
              % (im.size, crop.size, 100.0 * crop.size[0] * crop.size[1] / (im.size[0] * im.size[1])))

    demo = {}
    if not args.no_demo and by_name.get("202427") and by_name["202427"]["found"]:
        try:
            LED_TOOL = r"D:\xuexishengshou\afh03_prj_fpga\led_tool"
            if LED_TOOL not in sys.path:
                sys.path.insert(0, LED_TOOL)
            import marker as MK
            import markerdet as MD
            r = by_name["202427"]
            im = Image.open(os.path.join(PHOTO_DIR, r["file"])).convert("RGB")
            codes = MK.build_dictionary(24, 4)

            m_in = MK.render_marker(codes[8], module_px=20, quiet=True)
            m_out = MK.render_marker(codes[15], module_px=20, quiet=True)
            im2 = im.copy()
            im2.paste(m_in, (700, 520))
            im2.paste(m_out, (1730, 650))
            g = MD.to_gray(im2)
            det_full = MD.detect_markers(g, codes, min_side_px=24,
                                         max_side_px=int(0.5 * min(g.shape)), dark_win_frac=0.25)
            crop, box = crop_to_boundary(im2, r, return_box=True)
            g2 = MD.to_gray(crop)
            det_crop = MD.detect_markers(g2, codes, min_side_px=24,
                                         max_side_px=int(0.5 * min(g2.shape)), dark_win_frac=0.25)
            demo = {"roi_box": box, "full_ids": sorted(d.mid for d in det_full),
                    "crop_ids": sorted(d.mid for d in det_crop),
                    "full_px": im2.size, "crop_px": crop.size,
                    "area_ratio": round(crop.size[0] * crop.size[1]
                                        / float(im2.size[0] * im2.size[1]), 3)}
            print("\n=== ROI 辅助标记定位 demo ===")
            print("  全图检测 ids=%s；ROI 内检测 ids=%s（期望: 全图 [8,15]，ROI [8]）"
                  % (demo["full_ids"], demo["crop_ids"]))
            ann = annotate(im2, r, "ROI demo")
            d = ImageDraw.Draw(ann)
            d.rectangle(box, outline=(0, 200, 255), width=4)
            ann.thumbnail((1280, 1280))
            ann.save(os.path.join(OUT_DIR, "roi_marker_demo.jpg"), quality=92)
        except Exception as e:                                        
            import traceback
            traceback.print_exc()
            demo = {"error": str(e)}
            print("  ROI demo 失败：%s" % e)

    summary = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "photo_dir": PHOTO_DIR,
        "n": len(results),
        "found": len(found),
        "found_rate": round(len(found) / max(1, len(results)), 4),
        "kind": dict(kinds),
        "edge_type": dict(edges),
        "confidence": {"min": round(confs[0], 3) if confs else 0,
                       "median": round(confs[len(confs) // 2], 3) if confs else 0,
                       "max": round(confs[-1], 3) if confs else 0,
                       "hist_0_02_04_06_08_1": hist},
        "sec_mean": round(sum(r["sec"] for r in results) / max(1, len(results)), 3),
        "sec_total": round(time.perf_counter() - t_all, 1),
        "stability": stab,
        "manual_review": {nm: MANUAL.get(nm, {}) for nm in VIS},
        "roi_demo": demo,
        "per_image": [{k: r[k] for k in ("file", "name", "found", "kind", "confidence",
                                         "box_px", "polygon", "area_frac", "fill",
                                         "visible_sides", "supported_sides", "hough_sides",
                                         "edge_type", "angle_deg", "sec", "note")}
                      for r in results],
    }
    jp = os.path.join(OUT_DIR, "edge_results.json")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print("\n-> %s" % jp)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

