#!/usr/bin/env python3
"""生成汉字模板库（.npz），给 `soc_vision.ocr_cn.TemplateMatcher` 用。

三种用法
--------
1) 从"一张标定图 + 配置里的 fixed_boxes + 给定字串"生成（最常用）：
     python3 tools/make_templates.py --sheet calib.png --config config/example_config.json \
             --item text0 --labels 北京欢迎你 --out models/cn_templates.npz

2) 从目录生成（每张图一个文件，文件名首字符就是标签）：
     python3 tools/make_templates.py --from-dir calib_chars/ --out models/cn_templates.npz
   * 也支持子目录形式：calib_chars/北/xxx.png, calib_chars/京/yyy.png

3) 加数据增强（推荐：同一字做平移/缩放/噪声变体，提高容错）：
     python3 tools/make_templates.py ... --augment 8

产物格式：
    chars : (K,)  字符串数组
    imgs  : (K,H,W) uint8 二值图（字=255）
    grays : (K,H,W) uint8 高斯模糊后的灰度图（提高对边缘平移的容错）
    size  : (2,)  [w, h]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import cv2
except Exception as e:                                      
    print("需要 cv2：%s" % e)
    raise SystemExit(1)

from soc_vision.config import AppCfg, OcrItemCfg          
from soc_vision.ocr_cn import (split_fixed, split_projection,   
                               to_binary_char)

def boxes_for_item(item: OcrItemCfg, roi: np.ndarray):
    """按 item.split 决定切字方式。

    【坑】这里原来无条件用 split_fixed。后果：如果识别端配成 split=projection，
    切出来的字框（紧贴墨迹）与模板的字框（含格子留白）不一致，归一化后对不上，
    实测**准确率会从 96% 掉到 0%（全输出 ?）**。所以建模板必须和识别用同一种切分。
    """
    mode = (getattr(item, "split", "fixed") or "fixed").lower()
    if mode == "projection":
        return split_projection(roi, max(1, int(item.n_chars))), "projection"
    return split_fixed(item), "fixed"

def _default_rng(seed: int):
    """兼容新旧 numpy：1.17+ 用 default_rng，更老退回 RandomState。"""
    if hasattr(np.random, "default_rng"):
        return np.random.default_rng(seed)
    return np.random.RandomState(seed)

def _randint(rng, lo: int, hi: int) -> int:
    """rng.integers(lo, hi)（新）/ rng.randint(lo, hi)（旧），语义都是 [lo, hi)。"""
    if hasattr(rng, "integers"):
        return int(rng.integers(lo, hi))
    return int(rng.randint(lo, hi))

def augment(binimg: np.ndarray, gray: np.ndarray, n: int,
            rng):
    """生成 n 个轻微扰动变体：(bin, gray) 列表。"""
    out = [(binimg, gray)]
    if n <= 0:
        return out
    h, w = binimg.shape
    for i in range(n):
        dx = _randint(rng, -2, 3)
        dy = _randint(rng, -2, 3)
        sc = float(rng.uniform(0.92, 1.08))
        M = np.float32([[sc, 0, dx + (1 - sc) * w / 2],
                        [0, sc, dy + (1 - sc) * h / 2]])
        b = cv2.warpAffine(binimg, M, (w, h), flags=cv2.INTER_NEAREST,
                           borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        g = cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_LINEAR,
                           borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        if rng.uniform() < 0.5:
            noise = rng.normal(0, 12, b.shape)
            b = np.clip(b.astype(np.float32) + noise, 0, 255).astype(np.uint8)
        out.append((b, g))
    return out

def collect_from_sheet(sheet: np.ndarray, item: OcrItemCfg, labels: str,
                       char_size, do_aug: int, rng) -> tuple:
    x, y, w, h = item.roi
    roi = sheet[y:y + h, x:x + w]
    boxes, used = boxes_for_item(item, roi)
    print("  切字方式: %s（%d 个框）" % (used, len(boxes)))
    if len(labels) != len(boxes):
        print("[WARN] labels 长度 %d != 框数 %d，按 min 取" % (len(labels), len(boxes)))
    n = min(len(labels), len(boxes))
    chars, imgs, grays = [], [], []
    for i in range(n):
        bx, by, bw, bh = boxes[i]
        patch = roi[by:by + bh, bx:bx + bw]
        b = to_binary_char(patch, char_size)
        g = cv2.GaussianBlur(b, (3, 3), 0)
        for (bb, gg) in augment(b, g, do_aug, rng):
            chars.append(labels[i])
            imgs.append(bb)
            grays.append(gg)
    return chars, imgs, grays

def collect_from_dir(root: str, char_size, do_aug: int, rng) -> tuple:
    chars, imgs, grays = [], [], []
    subdirs = [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
    if subdirs:
        pairs = []
        for d in subdirs:
            for f in sorted(glob.glob(os.path.join(root, d, "*"))):
                pairs.append((d[0], f))
    else:
        pairs = []
        for f in sorted(glob.glob(os.path.join(root, "*"))):
            base = os.path.basename(f)
            if not base or base.startswith("."):
                continue
            pairs.append((base[0], f))
    for ch, f in pairs:
        img = cv2.imread(f, cv2.IMREAD_COLOR)
        if img is None:
            print("  跳过（读不到）: %s" % f)
            continue
        b = to_binary_char(img, char_size)
        g = cv2.GaussianBlur(b, (3, 3), 0)
        for (bb, gg) in augment(b, g, do_aug, rng):
            chars.append(ch)
            imgs.append(bb)
            grays.append(gg)
        print("  %s <- %s" % (ch, os.path.basename(f)))
    return chars, imgs, grays

def main() -> int:
    ap = argparse.ArgumentParser(description="生成汉字模板库 npz")
    ap.add_argument("--sheet", help="标定图（配合 --config/--item/--labels）")
    ap.add_argument("--config", help="JSON 配置")
    ap.add_argument("--item", help="用哪个 ocr item 的 roi/fixed_boxes")
    ap.add_argument("--labels", default="", help="按框顺序给出的字串")
    ap.add_argument("--from-dir", help="从目录收集")
    ap.add_argument("--char-size", default="32x32", help="模板尺寸 wxh，默认 32x32")
    ap.add_argument("--augment", type=int, default=0, help="每个字额外生成 n 个扰动变体")
    ap.add_argument("--out", default="models/cn_templates.npz")
    ap.add_argument("--seed", type=int, default=20260101)
    a = ap.parse_args()

    try:
        cw, chh = (int(v) for v in a.char_size.lower().split("x"))
    except Exception:
        print("--char-size 格式应为 32x32")
        return 1
    char_size = (cw, chh)
    rng = _default_rng(a.seed)

    if a.from_dir:
        chars, imgs, grays = collect_from_dir(a.from_dir, char_size, a.augment, rng)
    elif a.sheet and a.config and a.item:
        sheet = cv2.imread(a.sheet, cv2.IMREAD_COLOR)
        if sheet is None:
            print("读不到标定图 %s" % a.sheet)
            return 1
        with open(a.config, "r", encoding="utf-8") as f:
            cfg = AppCfg.from_dict(json.load(f))
        item = next((it for it in cfg.ocr.items if it.name == a.item), None)
        if item is None:
            print("配置里没有 item %s" % a.item)
            return 1
        if not item.fixed_boxes:
            print("[WARN] item 没有 fixed_boxes，将按 roi 等分 n_chars=%d 切分" % item.n_chars)
        chars, imgs, grays = collect_from_sheet(sheet, item, a.labels,
                                               char_size, a.augment, rng)
    else:
        ap.print_help()
        return 1

    if not chars:
        print("没有生成任何模板")
        return 1

    out_dir = os.path.dirname(os.path.abspath(a.out))
    os.makedirs(out_dir, exist_ok=True)
    np.savez_compressed(a.out,
                        chars=np.array(chars, dtype="<U8"),
                        imgs=np.stack(imgs).astype(np.uint8),
                        grays=np.stack(grays).astype(np.uint8),
                        size=np.array([cw, chh], dtype=np.int32))
    uniq = sorted(set(chars))
    print("\n生成完成: %s" % a.out)
    print("  模板数 %d，覆盖 %d 个字: %s" % (len(chars), len(uniq), "".join(uniq)))
    print("  每个字的模板数: %s" % {c: chars.count(c) for c in uniq})
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
