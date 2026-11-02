# -*- coding: utf-8 -*-
"""
marker.py -- 自制 4x4 码（ArUco 风格）字典 + 标记图渲染 + 可打印标记纸
------------------------------------------------------------------
为什么自己做字典而不用 cv2.aruco：
  1) 本机没有 OpenCV（Anaconda 的 numpy 也坏了），必须纯 numpy/Pillow 实现；
  2) 自己生成的字典可以做「最小汉明距离 >= 4」并且排除互为旋转的码，
     比 ArUco DICT_4X4_50 更稳；
  3) 字典、渲染、检测三者用同一份代码，SoC / FPGA 侧都能原样复现。

标记的几何定义（单位 = 一个"模块"）：
    6x6 模块 = 1 模块粗的黑色边框 + 中间 4x4 数据
    打印时外面再留 1 模块白边（安静区），所以纸面上是 7x7 模块
    M  = 黑框外沿边长（= 6 模块），单位 mm，打印时按 1:1 输出
    黑框外沿在图像里量到的边长 = 6*s（s = 一个模块的像素数）

位序约定：code 的第 (i*4+j) 位 = 第 i 行第 j 列的格子（i,j 从 0 开始，左上角为 (0,0)），
          bit=1 画黑，bit=0 画白。
旋转约定：顺时针 90 度  ->  cell(i,j) 移到 cell(j, 3-i)
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import os

GRID = 4          
BORDER = 1        
MOD = GRID + 2 * BORDER   

def to_bits(code):
    return np.array([(code >> k) & 1 for k in range(16)], dtype=np.uint8).reshape(GRID, GRID)

def from_bits(b):
    c = 0
    for i in range(GRID):
        for j in range(GRID):
            if b[i, j]:
                c |= 1 << (i * GRID + j)
    return c

def rot90_bits(b, n=1):
    return np.rot90(b, -n % 4)   

def rotations(code):
    b = to_bits(code)
    return [from_bits(rot90_bits(b, n)) for n in range(4)]

def ham(a, b):
    return bin(a ^ b).count("1")

def rot_dist(a, b):
    """a 与 b 的所有旋转之间的最小汉明距离（0 表示互为旋转，必须区分开）"""
    return min(ham(a, r) for r in rotations(b))

def build_dictionary(n_want=24, dmin=4):
    """确定性贪心：按码值从小到大，逐步加入满足最小旋转汉明距离的码。
       排除全黑/全白与过于稀疏/过密的码。"""
    chosen = []
    for code in range(1 << 16):
        b = to_bits(code)
        s = int(b.sum())
        if s < 3 or s > 13:              
            continue
        if all(ham(code, r) > 0 for r in rotations(code)[1:]) is False:
            continue                     
        ok = True
        for c in chosen:
            if rot_dist(code, c) < dmin:
                ok = False
                break
        if ok:
            chosen.append(code)
            if len(chosen) >= n_want:
                break
    return chosen

def render_marker(code, module_px=16, quiet=True, bg=(255, 255, 255), fg=(0, 0, 0)):
    """把 code 渲染成 PIL 图像。module_px = 一个模块多少像素。"""
    n = MOD + (2 if quiet else 0)
    q = 1 if quiet else 0
    img = Image.new("RGB", (n * module_px, n * module_px), bg)
    d = ImageDraw.Draw(img)
    b = to_bits(code)

    x0, y0 = q * module_px, q * module_px
    x1, y1 = x0 + MOD * module_px, y0 + MOD * module_px
    d.rectangle([x0, y0, x1 - 1, y1 - 1], fill=fg)

    dx, dy = x0 + BORDER * module_px, y0 + BORDER * module_px
    d.rectangle([dx, dy, dx + GRID * module_px - 1, dy + GRID * module_px - 1], fill=bg)
    for i in range(GRID):
        for j in range(GRID):
            if b[i, j]:
                cx0 = dx + j * module_px
                cy0 = dy + i * module_px
                d.rectangle([cx0, cy0, cx0 + module_px - 1, cy0 + module_px - 1], fill=fg)
    return img

def _font(size):
    for p in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf",
              r"C:\Windows\Fonts\arial.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()

def make_print_sheet(codes, names, side_mm=25.0, dpi=300, path="markers_A4.png",
                     title="4x4 LED 标记纸（务必 100% 比例打印，勿缩放）"):
    """A4 标记纸：每个标记的真实边长 = side_mm（黑框外沿），带编号和灯名。"""
    mm = dpi / 25.4
    W, H = int(210 * mm), int(297 * mm)
    sheet = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    d.text((int(12 * mm), int(10 * mm)), title, fill=(0, 0, 0), font=_font(int(5 * mm)))
    d.text((int(12 * mm), int(17 * mm)),
           "打印设置：纸张 A4 / 缩放 100%（不要选“适合页面”）/ 用哑光纸，避免反光",
           fill=(60, 60, 60), font=_font(int(3.2 * mm)))

    total_mm = side_mm * (MOD + 2) / MOD
    cell_mm = total_mm + 8.0     
    per_row = max(1, int((200 - 12) // cell_mm))
    x0, y0 = 12 * mm, 26 * mm
    module_px = side_mm * mm / MOD
    for k, code in enumerate(codes):
        c = k % per_row
        r = k // per_row
        cx = x0 + c * cell_mm * mm
        cy = y0 + r * (cell_mm + 12) * mm
        if cy + total_mm * mm > H - 12 * mm:
            break
        m = render_marker(code, module_px=int(round(module_px)), quiet=True)
        sheet.paste(m, (int(cx), int(cy)))
        label = "ID%02d %s" % (k, names[k] if k < len(names) else "")
        d.text((int(cx), int(cy + total_mm * mm + 0.5 * mm)), label,
               fill=(0, 0, 0), font=_font(int(2.8 * mm)))
    sheet.save(path, dpi=(dpi, dpi))
    return path

if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    codes = build_dictionary(24, 4)
    print("dictionary size =", len(codes))
    print("codes(hex) =", [hex(c) for c in codes])

    md = min(rot_dist(a, b) for i, a in enumerate(codes) for b in codes[i + 1:])
    print("min rotation-invariant Hamming distance =", md)

    names = ["LED%02d" % k for k in range(len(codes))]
    p = make_print_sheet(codes, names, side_mm=25.0,
                         path=os.path.join(out, "markers_A4_25mm.png"))
    print("print sheet ->", p, Image.open(p).size)

    render_marker(codes[0], module_px=40).save(os.path.join(out, "marker_id00.png"))
    np.save(os.path.join(out, "dict_4x4.npy"), np.array(codes, dtype=np.uint32))
    print("saved dict_4x4.npy")
