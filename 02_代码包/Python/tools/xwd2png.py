#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""xwd2png.py —— 把 `xwd -root` 的 XWD 截屏转成 PNG（只用标准库 + cv2）。

为什么不用 ImageMagick / scrot：板子上**没有** convert/scrot，但一定有
`xwd`（x11-apps）和 cv2（本包刚装好）。所以自己解 XWD 头就能出图，
用来给"DSI 屏上真的显示了窗口/结果"留证。

用法：
    xwd -root -display :0 -silent -out /tmp/shot.xwd
    python3 tools/xwd2png.py /tmp/shot.xwd /tmp/shot.png
    # 或直接一步（脚本内部调 xwd）：
    python3 tools/xwd2png.py --grab /tmp/shot.png
"""

from __future__ import annotations

import argparse
import os
import struct
import subprocess
import sys

import numpy as np

try:
    import cv2
except Exception as e:                                        
    print("需要 cv2：%s" % e)
    raise SystemExit(1)

_FIELDS = ["header_size", "file_version", "pixmap_format", "pixmap_depth",
           "pixmap_width", "pixmap_height", "xoffset", "byte_order",
           "bitmap_unit", "bitmap_bit_order", "bitmap_pad", "bits_per_pixel",
           "bytes_per_line", "visual_class", "red_mask", "green_mask",
           "blue_mask", "bits_per_rgb", "colormap_entries", "ncolors",
           "window_width", "window_height", "window_x", "window_y",
           "window_bdrwidth"]

def load_xwd(path: str) -> np.ndarray:
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 100:
        raise ValueError("文件太小，不是 XWD: %s" % path)
    vals = struct.unpack(">25I", data[:100])
    h = dict(zip(_FIELDS, vals))
    if h["file_version"] != 7:
        print("[warn] XWD file_version=%d（期望 7），仍然尝试解析" % h["file_version"])
    w = int(h["pixmap_width"])
    ht = int(h["pixmap_height"])
    bpp = int(h["bits_per_pixel"])
    bpl = int(h["bytes_per_line"])
    ncolors = int(h["ncolors"])
    off = int(h["header_size"]) + ncolors * 12
    if bpp not in (24, 32):
        raise ValueError("只支持 24/32bpp（这个文件是 %d bpp）" % bpp)
    bytes_pp = bpp // 8
    need = bpl * ht
    pix = data[off:off + need]
    if len(pix) < need:
        raise ValueError("像素数据不足：需要 %d，只有 %d" % (need, len(pix)))
    arr = np.frombuffer(pix, dtype=np.uint8).reshape(ht, bpl)
    arr = arr[:, : w * bytes_pp].reshape(ht, w, bytes_pp)

    return np.ascontiguousarray(arr[:, :, :3])

def grab(out_png: str, display: str = ":0", xwd_out: str = "/tmp/afh03_shot.xwd") -> str:
    cmd = ["xwd", "-root", "-display", display, "-silent", "-out", xwd_out]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("xwd 失败(%d): %s" % (r.returncode,
                                                r.stderr.decode("utf-8", "replace")[:200]))
    img = load_xwd(xwd_out)
    cv2.imwrite(out_png, img)
    return out_png

def main() -> int:
    ap = argparse.ArgumentParser(description="XWD 截屏 -> PNG")
    ap.add_argument("xwd", nargs="?", help="输入 .xwd")
    ap.add_argument("png", nargs="?", help="输出 .png")
    ap.add_argument("--grab", help="直接抓屏并写到这个 png（内部调 xwd）")
    ap.add_argument("--display", default=os.environ.get("DISPLAY", ":0"))
    a = ap.parse_args()

    if a.grab:
        p = grab(a.grab, a.display)
        img = cv2.imread(p)
        print("[OK] %s  %dx%d" % (p, img.shape[1], img.shape[0]))
        return 0
    if not a.xwd or not a.png:
        ap.print_help()
        return 1
    img = load_xwd(a.xwd)
    cv2.imwrite(a.png, img)
    print("[OK] %s -> %s  %dx%d" % (a.xwd, a.png, img.shape[1], img.shape[0]))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
