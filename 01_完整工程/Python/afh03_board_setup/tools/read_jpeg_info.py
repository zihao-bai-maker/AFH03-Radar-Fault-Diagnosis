#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""read_jpeg_info.py —— 纯标准库读 JPEG 尺寸 + EXIF Orientation（不依赖 PIL）。

用途：8 张真值照片里有 4 张是横拍（需向右转 90°）。识别前必须知道 EXIF 朝向，
      而板端 OpenCV 不会自动应用 EXIF 旋转 -> 必须自己读出来再转。
"""
import os
import struct
import sys

SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}

def jpeg_size(d):
    i = 2
    while i < len(d) - 9:
        if d[i] != 0xFF:
            i += 1
            continue
        m = d[i + 1]
        if m in (0xD8, 0xD9) or 0xD0 <= m <= 0xD7:
            i += 2
            continue
        seg = struct.unpack(">H", d[i + 2:i + 4])[0]
        if m in SOF:
            h, w = struct.unpack(">HH", d[i + 5:i + 9])
            return w, h
        i += 2 + seg
    return 0, 0

def exif_orientation(d):
    """返回 EXIF Orientation（1..8），找不到返回 0。"""
    if d[:2] != b"\xff\xd8":
        return 0
    i = 2
    while i < len(d) - 4:
        if d[i] != 0xFF:
            i += 1
            continue
        m = d[i + 1]
        if m == 0xE1:                                  
            seg = struct.unpack(">H", d[i + 2:i + 4])[0]
            body = d[i + 4:i + 2 + seg]
            if not body.startswith(b"Exif\x00\x00"):
                i += 2 + seg
                continue
            t = body[6:]
            if t[:2] not in (b"II", b"MM"):
                return 0
            endian = "<" if t[:2] == b"II" else ">"
            ifd0 = struct.unpack(endian + "I", t[4:8])[0]
            n = struct.unpack(endian + "H", t[ifd0:ifd0 + 2])[0]
            for k in range(n):
                e = ifd0 + 2 + k * 12
                tag, typ, cnt = struct.unpack(endian + "HHI", t[e:e + 8])
                if tag == 0x0112:
                    return struct.unpack(endian + "H", t[e + 8:e + 10])[0]
            return 0
        if m in (0xC0, 0xDA):                          
            return 0
        seg = struct.unpack(">H", d[i + 2:i + 4])[0]
        i += 2 + seg
    return 0

ORIENT_DESC = {1: "正常(0°)", 2: "水平镜像", 3: "旋转180°", 4: "垂直镜像",
               5: "镜像+90", 6: "★需向右转90°(EXIF=6)", 7: "镜像+270", 8: "★需向左转90°(EXIF=8)"}

def main():
    paths = sys.argv[1:]
    if not paths:
        print("用法: read_jpeg_info.py <a.jpg> [b.jpg ...]")
        return 1
    print("%-34s %-12s %-8s %s" % ("文件", "尺寸", "EXIF", "朝向含义"))
    for p in paths:
        d = open(p, "rb").read()
        w, h = jpeg_size(d)
        o = exif_orientation(d)
        print("%-34s %-12s %-8s %s" % (os.path.basename(p), "%dx%d" % (w, h), o or "-",
                                       ORIENT_DESC.get(o, "未知/无EXIF")))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
