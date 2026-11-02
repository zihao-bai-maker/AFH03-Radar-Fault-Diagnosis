#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ocr_rate_test.py —— 用**真汉字**标定页测模板匹配的实际识别率。

和 `tools/selftest_offline.py` 的区别
------------------------------------
自测里用的是**几何图元**伪汉字（为了不依赖 CJK 字体）；这个工具用**真的汉字**（标定页可以是
Windows 用微软雅黑/宋体渲染出来的，也可以是相机拍的现场文本），于是给出的准确率是**真汉字**的。

它做三件事：
1. 用 `make_templates.py` 的同一套代码从标定页建模板库（`--augment` 控制扰动变体数）；
2. 对同一页生成一组**退化变体**（噪声 / 模糊 / 亮度 / 对比度 / gamma / 几何抖动 / 缩放 / JPEG）；
3. 对每个变体跑 `CnRecognizer.recognize_item`，逐字比对，打印**每变体准确率 + 具体错在哪几个字**。

用法
----
    python3 tools/ocr_rate_test.py --sheet calib_cn.png --config config/ocr_calib_config.json \
            --item text0 --labels 北京欢迎你杭州西湖美丽中国科技强国 --augment 8

退出码：0 全部变体准确率 >= --min-rate（默认 0.9）；1 否则
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

try:
    import cv2
except Exception as e:                                        
    print("需要 cv2：%s" % e)
    raise SystemExit(1)

import make_templates as mt                                          
from soc_vision.config import AppCfg, OcrCfg                         
from soc_vision.ocr_cn import CnRecognizer                           

def build_templates(sheet_path, cfg_path, item_name, labels, out_npz, augment, seed,
                    split_override="", quiet=False):
    sheet = cv2.imread(sheet_path, cv2.IMREAD_COLOR)
    if sheet is None:
        raise SystemExit("读不到标定页 %s" % sheet_path)
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = AppCfg.from_dict(json.load(f))
    item = next((it for it in cfg.ocr.items if it.name == item_name), None)
    if item is None:
        raise SystemExit("配置 %s 里没有 item %s" % (cfg_path, item_name))
    if split_override:
        item.split = split_override
        print("[覆盖] split -> %s" % split_override)
    rng = mt._default_rng(seed)
    chars, imgs, grays = mt.collect_from_sheet(sheet, item, labels, (32, 32), augment, rng)
    if not chars:
        raise SystemExit("没建出任何模板（labels 与框数对不上？）")
    os.makedirs(os.path.dirname(os.path.abspath(out_npz)) or ".", exist_ok=True)
    np.savez_compressed(out_npz, chars=np.array(chars, dtype="<U8"),
                        imgs=np.stack(imgs).astype(np.uint8),
                        grays=np.stack(grays).astype(np.uint8),
                        size=np.array([32, 32], dtype=np.int32))
    return sheet, item, len(chars), sorted(set(chars))

def variants(bgr: np.ndarray, rng):
    """产出 (名字, 图) —— 模拟现场真实会遇到的退化。"""
    f = bgr.astype(np.float32)
    yield "clean", bgr
    yield "noise_σ8", np.clip(f + rng.normal(0, 8, f.shape), 0, 255).astype(np.uint8)
    yield "noise_σ16", np.clip(f + rng.normal(0, 16, f.shape), 0, 255).astype(np.uint8)
    yield "blur_3x3", cv2.GaussianBlur(bgr, (3, 3), 0)
    yield "blur_5x5", cv2.GaussianBlur(bgr, (5, 5), 0)
    yield "bright_+30", np.clip(f + 30, 0, 255).astype(np.uint8)
    yield "bright_-30", np.clip(f - 30, 0, 255).astype(np.uint8)
    yield "contrast_x0.6", np.clip(128 + (f - 128) * 0.6, 0, 255).astype(np.uint8)
    yield "gamma_1.5", np.clip(255.0 * (np.clip(f, 0, 255) / 255.0) ** 1.5, 0, 255).astype(np.uint8)
    M = np.float32([[1.0, 0.002, 1.0], [0.001, 1.0, 1.0]])
    yield "warp_0.2%_1px", cv2.warpAffine(bgr, M, (bgr.shape[1], bgr.shape[0]),
                                          borderMode=cv2.BORDER_REPLICATE)

    
    M2 = np.float32([[1.0, 0.02, 3.0], [0.01, 1.0, 2.0]])
    yield "warp_2%_severe", cv2.warpAffine(bgr, M2, (bgr.shape[1], bgr.shape[0]),
                                           borderMode=cv2.BORDER_REPLICATE)
    small = cv2.resize(bgr, None, fx=0.9, fy=0.9, interpolation=cv2.INTER_AREA)
    yield "resize_0.9", cv2.resize(small, (bgr.shape[1], bgr.shape[0]),
                                   interpolation=cv2.INTER_LINEAR)
    ok, enc = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 55])
    if ok:
        yield "jpeg_q55", cv2.imdecode(enc, cv2.IMREAD_COLOR)
    triple = cv2.GaussianBlur(np.clip(f * 0.8 + 40 + rng.normal(0, 10, f.shape), 0, 255)
                              .astype(np.uint8), (3, 3), 0)
    yield "noise+blur+bright", triple

def main() -> int:
    ap = argparse.ArgumentParser(description="真汉字模板匹配识别率测试")
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--item", default="text0")
    ap.add_argument("--labels", required=True, help="按框顺序的字串")
    ap.add_argument("--out-npz", default="/tmp/cn_templates_rate.npz")
    ap.add_argument("--augment", type=int, default=8)
    ap.add_argument("--seed", type=int, default=20260101)
    ap.add_argument("--min-rate", type=float, default=0.9)
    ap.add_argument("--split", default="", choices=["", "fixed", "projection"],
                    help="覆盖配置里的切字方式（fixed=按等分/标定框，projection=投影切字）")
    ap.add_argument("--crop-dir", default="")
    a = ap.parse_args()

    sheet, item, n_tpl, cover = build_templates(a.sheet, a.config, a.item, a.labels,
                                                a.out_npz, a.augment, a.seed,
                                                split_override=a.split)
    print("标定页 : %s  %dx%d" % (a.sheet, sheet.shape[1], sheet.shape[0]))
    print("模板库 : %s  （%d 个模板，覆盖 %d 个字：%s）"
          % (a.out_npz, n_tpl, len(cover), "".join(cover)))
    print("字串   : %s（%d 字）" % (a.labels, len(a.labels)))
    print("ROI    : %s  split=%s  n_chars=%d  char_size=%s  threshold=%s"
          % (list(item.roi), item.split, item.n_chars, item.char_size, item.threshold))

    ocr_cfg = OcrCfg.from_dict({})
    ocr_cfg.items = [item]
    ocr_cfg.template_npz = os.path.abspath(a.out_npz)
    rec = CnRecognizer(ocr_cfg, base_dir=os.path.dirname(os.path.abspath(a.out_npz)))

    if a.crop_dir:
        os.makedirs(a.crop_dir, exist_ok=True)

    rng = np.random.default_rng(a.seed + 7) if hasattr(np.random, "default_rng") \
        else np.random.RandomState(a.seed + 7)

    print("\n%-18s %-6s %-7s %s" % ("变体", "准确率", "conf", "识别文本 / 错误位置"))
    print("-" * 92)
    worst = 1.0
    total_ok = total_ch = 0
    rows = []
    for name, img in variants(sheet, rng):
        r = rec.recognize_item(img, item)
        got = r.text
        n = len(a.labels)
        ok = sum(1 for i in range(n) if i < len(got) and got[i] == a.labels[i])
        rate = ok / n
        worst = min(worst, rate)
        total_ok += ok
        total_ch += n
        wrong = [("%d:%s≠%s" % (i + 1, got[i] if i < len(got) else "-", a.labels[i]))
                 for i in range(n) if not (i < len(got) and got[i] == a.labels[i])]
        rows.append((name, rate, r.conf))
        mark = "OK " if rate >= a.min_rate else "低 "
        print("%s%-15s %-6.1f%% %-7.3f %s%s" % (mark, name, rate * 100, r.conf, got,
                                                ("   " + " ".join(wrong[:6])) if wrong else ""))
        if a.crop_dir and name in ("clean", "noise_σ16", "blur_5x5", "warp_2%_3px"):
            cv2.imwrite(os.path.join(a.crop_dir, "rate_%s.png" % name.replace("/", "_")), img)

    print("-" * 92)
    print("总计：%d/%d 字正确 = **%.2f%%**；最低单变体 = %.1f%%（阈值 %.0f%%）"
          % (total_ok, total_ch, total_ok * 100.0 / max(1, total_ch), worst * 100,
             a.min_rate * 100))
    bad = [r for r in rows if r[1] < a.min_rate]
    if bad:
        print("低于阈值的变体: %s" % ", ".join("%s(%.1f%%)" % (n, r * 100) for n, r, _ in bad))
    return 0 if worst >= a.min_rate else 1

if __name__ == "__main__":
    raise SystemExit(main())
