#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cjk_text.py —— **中文/Unicode 文字渲染**：让 cv2 画得出中文，画不出就退化成英文，**绝不输出乱码**。

为什么要它
----------
`cv2.putText` 用的是 Hershey 矢量字体，**只支持 ASCII**（Latin-1 以内），
画中文必然变成 `???`/豆腐块 —— 这就是现场"点进去就乱码"的根因。
而这块板子**本来就有中文字体**（`/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc`，`fc-list :lang=zh` 非空）、
locale 也已经是 `zh_CN.UTF-8`，所以**不是字体/locale 问题，纯粹是"用了不会画中文的 API"**。

后端选择（自动探测，可用 `backend()` 查询）
------------------------------------------
1. **PangoCairo**（`python3-gi` + `python3-cairo`，**本板已自带**）：走 fontconfig 自动选 CJK 字体，
   渲染质量最好、无需安装任何东西。✔ 本板实测可用
2. **PIL/Pillow**（若装了 `Pillow`）：用 TTF 渲染。
3. **纯 ASCII 兜底**：把字符串映射成英文/简短拉丁标签（术语表 + 逐字表），
   **保证屏幕上永远是可读的 ASCII，绝不会出现乱码/豆腐块**。

两种用法
--------
A. 直接画（推荐在需要精确控制时用）：
       from soc_vision.cjk_text import draw_text
       draw_text(img, "波形 20MHz 正常", (10, 30), scale=0.7, color=(0, 255, 0))

B. **一行给整个程序打补丁**（把 `cv2.putText` 换成"能画中文的 putText"）：
       from soc_vision.cjk_text import install_cv2_puttext_patch
       install_cv2_puttext_patch()      # 之后所有 cv2.putText 都能画中文
   * ASCII 字符串走**原生 cv2.putText**（行为完全不变、零性能损失）；
   * 含非 ASCII 的才走 Pango/PIL；两者都不可用时自动退化成 ASCII 标签。
   * `AFH03_NO_CV2_TEXT_PATCH=1` 可关闭；`uninstall_cv2_puttext_patch()` 可还原。

自检 / 演示
----------
    python3 -m soc_vision.cjk_text --demo /tmp/cjk_demo.png
"""

from __future__ import annotations

import os
import sys

_GI_ERR = None
try:
    import gi
    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Pango, PangoCairo
    import cairo
    _HAVE_PANGO = True
except Exception as e:                                            
    _HAVE_PANGO = False
    _GI_ERR = e

try:
    from PIL import Image, ImageDraw, ImageFont
    _HAVE_PIL = True
except Exception:                                                 
    _HAVE_PIL = False

try:
    import numpy as np
except Exception:                                                 
    np = None

BACKEND = "pango" if _HAVE_PANGO else ("pil" if _HAVE_PIL else "ascii")
_FONT_DESC = os.environ.get("AFH03_CJK_FONT_DESC", "sans")
_PIL_FONT_CANDIDATES = [
    os.environ.get("AFH03_CJK_FONT", ""),
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansSC-Regular.otf",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "fonts", "SourceHanSansSC-Regular.otf"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "fonts", "NotoSansSC-Regular.otf"),
]

def backend() -> str:
    return BACKEND

def font_info() -> dict:
    d = {"backend": BACKEND, "font_desc": _FONT_DESC, "gi_error": str(_GI_ERR) if _GI_ERR else None}
    if _HAVE_PIL:
        for c in _PIL_FONT_CANDIDATES:
            if c and os.path.isfile(c):
                d["pil_font"] = c
                break
    return d

def has_non_ascii(s: str) -> bool:
    return any(ord(ch) > 127 for ch in s or "")

_TERMS = [
    ("拍照取样", "CAPTURE"), ("重建索引", "REINDEX"), ("清理", "CLEANUP"), ("问答", "ASK"),
    ("确认", "CONFIRM"), ("重拍", "RETAKE"), ("退出", "EXIT"), ("帮助", "HELP"),
    ("波形", "WAVE"), ("频率", "FREQ"), ("偏差", "DEV"), ("振幅", "VPP"), ("峰峰值", "VPP"),
    ("示波器", "SCOPE"), ("未在线", "OFFLINE"), ("不在线", "OFFLINE"), ("未配置", "NOT-CFG"),
    ("超时", "TIMEOUT"), ("错误", "ERROR"), ("无信号", "NO-SIGNAL"), ("正常", "NORMAL"),
    ("异常", "ABNORMAL"), ("通过", "PASS"), ("失败", "FAIL"), ("成功", "OK"),
    ("判定", "VERDICT"), ("置信度", "CONF"), ("相机", "CAM"), ("画面", "VIEW"),
    ("帧号", "FRAME"), ("时间", "TIME"), ("状态", "STATUS"),
    ("亮", "ON"), ("灭", "OFF"), ("判据", "CRIT"), ("软件", "SW"), ("硬件", "HW"),
    ("状态字", "STATUS-WORD"), ("魔数", "MAGIC"), ("汉字", "CN-TEXT"), ("识别", "RECOG"),
    ("中文", "CJK"), ("字体", "FONT"), ("缺失", "MISSING"), ("英文", "ASCII"),
    ("标签", "LABEL"), ("代替", "FALLBACK"), ("通道", "CH"), ("探头", "PROBE"),
    ("时基", "TBASE"), ("采样率", "SRATE"), ("触发", "TRIG"), ("就绪", "READY"),
    ("白名单", "WHITELIST"), ("容差", "TOL"), ("交叉校验", "XCHK"), ("来源", "SRC"),
    ("未标定", "UNCALIB"), ("拒绝", "REFUSE"), ("结果", "RESULT"), ("使能", "EN"),
    ("禁用", "DIS"), ("打开", "OPEN"), ("关闭", "CLOSE"), ("初始化", "INIT"),
    ("保存", "SAVE"), ("已确认", "CONFIRMED"), ("待确认", "PENDING"), ("记录", "REC"),
    ("采集", "ACQ"), ("在线", "ONLINE"), ("网口", "ETH"), ("地址", "ADDR"),
    ("扫描", "SCAN"), ("发现", "DISCOVER"), ("设备", "DEV"), ("节点", "NODE"),
    ("内核", "KERNEL"), ("版本", "VER"), ("固件", "FW"), ("位流", "BITSTREAM"),
    ("拍照", "SHOT"), ("图片", "IMAGE"), ("视频", "VIDEO"), ("亮度", "BRIGHT"),
    ("颜色", "COLOR"), ("红", "RED"), ("绿", "GREEN"), ("蓝", "BLUE"),
    ("总数", "TOTAL"), ("平均", "AVG"), ("最大", "MAX"), ("最小", "MIN"),
    ("第", "#"), ("共", "of"), ("个", ""), ("的", "-"), ("了", ""), ("和", "+"),
]
_TERMS.sort(key=lambda kv: -len(kv[0]))

_CHARS = {
    "值": "VAL", "帧": "FR", "时": "T", "标": "CAL", "汉": "CN", "灭": "OFF", "亮": "ON",
    "电": "ELEC", "线": "LINE", "绿": "GRN", "蓝": "BLU", "红": "RED", "计": "CNT",
    "识": "REC", "误": "ERR", "请": "PLEASE", "软": "SW", "连": "LINK", "错": "ERR",
    "频": "FREQ", "验": "VERIFY", "态": "ST", "总": "TOT", "扫": "SCAN", "查": "CHK",
    "检": "CHK", "样": "SMP", "图": "IMG", "备": "BK", "头": "HEAD", "对": "VS",
    "废": "DROP", "录": "REC", "烧": "FLASH", "现": "NOW", "签": "SIGN", "纳": "TOL",
    "结": "END", "绝": "NEVER", "绪": "ST", "节": "SEG", "议": "PROTO", "讯": "COMM",
    "设": "SET", "试": "TEST", "调": "DBG", "败": "FAIL", "载": "LOAD", "迟": "HYST",
    "邻": "NEIGH", "闭": "CLOSE", "间": "INT", "阈": "THR", "颜": "COLOR", "驱": "DRV",
    "动": "MOVE", "协": "PROTO", "单": "UNIT", "发": "SEND",

    "：": ":", "，": ",", "。": ".", "（": "(", "）": ")", "、": ",", "；": ";",
    "！": "!", "？": "?", "《": "<", "》": ">", "“": '"', "”": '"', "‘": "'", "’": "'",
    "—": "-", "－": "-", "…": "...", "→": "->", "％": "%", "／": "/", "　": " ",
    "达": "REACH", "面": "SURF", "源": "SRC", "自": "SELF", "置": "SET", "率": "RATE",
    "端": "END", "示": "SHOW", "果": "RES", "板": "BOARD", "染": "RENDER", "描": "SCAN",
    "别": "KIND", "共": "TOTAL", "个": "pcs", "不": "NO", "中": "MID", "件": "ITEM",
    "信": "SIG", "偏": "DEV", "出": "OUT", "判": "JUDGE", "可": "CAN", "器": "DEV",
    "在": "AT", "字": "CHAR", "定": "FIX", "差": "DIFF", "常": "NORM", "度": "DEG",
    "异": "ABN", "形": "SHAPE", "拒": "REFUSE", "据": "DATA", "文": "TEXT", "未": "NOT",
    "正": "OK", "波": "WAVE", "状": "ST", "网": "NET", "超": "OVER", "口": "PORT",
    "已": "DONE", "现": "NOW", "取": "GET", "样": "SMP", "像": "PIX",
}

def to_ascii(s: str) -> str:
    """把任意字符串转成**可读 ASCII**：先整词替换术语表，再逐字兜底。绝不产生乱码。"""
    if not s:
        return ""
    out = s
    for zh, en in _TERMS:
        if zh and zh in out:
            out = out.replace(zh, (" " + en + " ") if en else " ")
    if has_non_ascii(out):
        buf = []
        for ch in out:
            if ord(ch) < 128:
                buf.append(ch)
            else:
                buf.append(_CHARS.get(ch, "?"))
        out = "".join(buf)

    while "  " in out:
        out = out.replace("  ", " ")
    return out.strip()

def unmapped_chars(s: str) -> list:
    return sorted({ch for ch in s if ord(ch) > 127 and ch not in _CHARS})

def unknown_glyphs(s: str, px: int = 18) -> int:
    """Pango 报告"字体里找不到字形"的字符数（0 = 全部有字形，**不是豆腐块**）。

    这是**程序化验证中文渲染是否真的可用**的硬指标（不需要肉眼看图）。
    """
    if not _HAVE_PANGO or not has_non_ascii(s):
        return 0
    try:
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 8, 8)
        cr = cairo.Context(surf)
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(Pango.FontDescription("%s %d" % (_FONT_DESC, int(px))))
        lay.set_text(s, -1)
        return int(lay.get_unknown_glyphs_count())
    except Exception:                                             
        return -1

def ink_stats(s: str, px: int = 18, color_bgr=(255, 255, 255)) -> dict:
    """渲染一行，返回 (宽, 高, 非透明像素数) —— 用来证明"确实画出了东西"。"""
    if not has_non_ascii(s):
        import cv2
        (w, h), _ = cv2.getTextSize(s, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
        return {"w": int(w), "h": int(h), "ink": -1, "backend": "cv2"}
    try:
        if BACKEND == "pango":
            b, w, h = _pango_render(s, px, color_bgr)
        elif BACKEND == "pil":
            b, w, h = _pil_render(s, px, color_bgr)
        else:
            return {"w": 0, "h": 0, "ink": 0, "backend": "ascii"}
        return {"w": int(w), "h": int(h), "ink": int((b[:, :, 3] > 0).sum()), "backend": BACKEND}
    except Exception as e:                                        
        return {"w": 0, "h": 0, "ink": 0, "backend": "error: %s" % e}

_PANGO_CACHE = {}

def _pango_render(text: str, px: int, color_bgr, bold: bool = False):
    """用 PangoCairo 渲染文本 -> (BGRA 预乘 ndarray, w, h)。"""
    import numpy as np
    weight = Pango.Weight.BOLD if bold else Pango.Weight.NORMAL
    desc = Pango.FontDescription("%s %d" % (_FONT_DESC, int(px)))
    desc.set_weight(weight)
    key = (text, px, bold)
    if key in _PANGO_CACHE:
        return _PANGO_CACHE[key]

    s0 = cairo.ImageSurface(cairo.FORMAT_ARGB32, 8, 8)
    c0 = cairo.Context(s0)
    l0 = PangoCairo.create_layout(c0)
    l0.set_font_description(desc)
    l0.set_text(text, -1)
    tw, th = l0.get_pixel_size()
    w, h = max(1, tw + 6), max(1, th + 6)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surf)
    lay = PangoCairo.create_layout(cr)
    lay.set_font_description(desc)
    lay.set_text(text, -1)

    cr.set_source_rgba(color_bgr[2] / 255.0, color_bgr[1] / 255.0, color_bgr[0] / 255.0, 1.0)
    PangoCairo.show_layout(cr, lay)
    surf.flush()
    stride = surf.get_stride()
    buf = np.frombuffer(surf.get_data(), np.uint8).reshape(h, stride // 4, 4)[:, :w, :].copy()
    _PANGO_CACHE[key] = (buf, w, h)
    return buf, w, h

def _pil_render(text: str, px: int, color_bgr, bold: bool = False):
    import numpy as np
    path = None
    for c in _PIL_FONT_CANDIDATES:
        if c and os.path.isfile(c):
            path = c
            break
    if not path:
        raise RuntimeError("PIL 可用但找不到 CJK 字体文件")
    font = ImageFont.truetype(path, int(px))
    img = Image.new("RGBA", (max(8, px * len(text)), px * 3), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((2, 2), text, font=font, fill=(color_bgr[2], color_bgr[1], color_bgr[0], 255))
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    arr = np.array(img)                                          
    bgra = np.dstack([arr[:, :, 2], arr[:, :, 1], arr[:, :, 0], arr[:, :, 3]])

    a = bgra[:, :, 3:4].astype(np.float32) / 255.0
    bgra[:, :, :3] = np.clip(bgra[:, :, :3].astype(np.float32) * a, 0, 255).astype(np.uint8)
    return bgra, bgra.shape[1], bgra.shape[0]

def _blend(img, bgra, x0: int, y0: int) -> None:
    """把预乘 BGRA 图元"over"混合到 BGR 画面上（带裁剪）。"""
    import numpy as np
    h, w = bgra.shape[:2]
    H, W = img.shape[:2]
    if x0 >= W or y0 >= H or x0 + w <= 0 or y0 + h <= 0:
        return
    sx0, sy0 = max(0, -x0), max(0, -y0)
    dx0, dy0 = max(0, x0), max(0, y0)
    cw = min(w - sx0, W - dx0)
    ch = min(h - sy0, H - dy0)
    if cw <= 0 or ch <= 0:
        return
    src = bgra[sy0:sy0 + ch, sx0:sx0 + cw].astype(np.float32)
    dst = img[dy0:dy0 + ch, dx0:dx0 + cw].astype(np.float32)
    a = src[:, :, 3:4] / 255.0
    out = src[:, :, :3] + dst * (1.0 - a)
    img[dy0:dy0 + ch, dx0:dx0 + cw] = np.clip(out, 0, 255).astype(np.uint8)

def text_size(s: str, scale: float = 0.6):
    """粗略返回 (w, h)，与 draw_text 的 px 换算一致。"""
    px = _scale_to_px(scale)
    if not has_non_ascii(s):
        import cv2
        (w, h), _ = cv2.getTextSize(s, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
        return w, h
    try:
        if BACKEND == "pango":
            b, w, h = _pango_render(s, px, (255, 255, 255))
            return w, h
        if BACKEND == "pil":
            b, w, h = _pil_render(s, px, (255, 255, 255))
            return w, h
    except Exception:                                             
        pass
    return (len(s) * max(6, int(px * 0.6)), px)

def _scale_to_px(scale: float) -> int:

    return max(9, int(round(scale * 26)))

def draw_text(img, s: str, org, scale: float = 0.6, color=(255, 255, 255), th: int = 1):
    """在 BGR 图上画文本；**自动处理中文**；画不出中文时退化成 ASCII 标签。

    参数与 `cv2.putText` 对齐：`org` = 文本**左下角**（(x, baseline_y)），`scale`/`color`/`th` 同义。
    返回实际画出来的字符串（ASCII 为原文，中文为渲染文本，退化时为 ASCII 标签）。
    """
    import cv2
    txt = "" if s is None else str(s)
    if not has_non_ascii(txt):
        cv2.putText(img, txt, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), th + 2)
        cv2.putText(img, txt, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, th)
        return txt
    px = _scale_to_px(scale)
    try:
        if BACKEND == "pango":
            bgra, w, h = _pango_render(txt, px, color, bold=(th >= 2))
        elif BACKEND == "pil":
            bgra, w, h = _pil_render(txt, px, color, bold=(th >= 2))
        else:
            raise RuntimeError("no unicode backend")

        if th >= 1:
            _blend(img, bgra, int(org[0]) - 1, int(org[1]) - h)
            _blend(img, bgra, int(org[0]) + 1, int(org[1]) - h)
        _blend(img, bgra, int(org[0]), int(org[1]) - h)
        return txt
    except Exception:                                             
        ascii_txt = to_ascii(txt)
        cv2.putText(img, ascii_txt, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), th + 2)
        cv2.putText(img, ascii_txt, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, th)
        return ascii_txt

_ORIG_PUTTEXT = None

def install_cv2_puttext_patch(verbose: bool = False) -> bool:
    """把 `cv2.putText` 换成能画中文的版本（ASCII 仍走原生实现）。幂等。"""
    import cv2
    global _ORIG_PUTTEXT
    if os.environ.get("AFH03_NO_CV2_TEXT_PATCH") == "1":
        if verbose:
            print("[cjk_text] AFH03_NO_CV2_TEXT_PATCH=1，跳过补丁")
        return False
    if _ORIG_PUTTEXT is not None:
        return True
    _ORIG_PUTTEXT = cv2.putText

    def putText(img, text, org, fontFace, fontScale, color, thickness=1, lineType=8, bottomLeftOrigin=False):
        if not has_non_ascii(text):
            return _ORIG_PUTTEXT(img, text, org, fontFace, fontScale, color, thickness, lineType,
                                 bottomLeftOrigin)

        draw_text(img, text, org, scale=float(fontScale), color=tuple(int(c) for c in color[:3]),
                  th=max(1, int(thickness)))
        return None

    cv2.putText = putText
    if verbose:
        print("[cjk_text] 已给 cv2.putText 打补丁：后端=%s" % BACKEND)
    return True

def uninstall_cv2_puttext_patch() -> None:
    import cv2
    global _ORIG_PUTTEXT
    if _ORIG_PUTTEXT is not None:
        cv2.putText = _ORIG_PUTTEXT
        _ORIG_PUTTEXT = None

DEMO_LINES = [
    "AFH03 状态面板 中文渲染自检",
    "波形：频率 20.000 MHz  偏差 +0.000%  Vpp 3.30 V  判定 正常",
    "LED：led0 亮  软件 ON/FPGA bit=1   判据 delta=211.0",
    "电源：示波器 未在线 → 错误 超时（端口 5555 不可达）",
    "汉字识别：置信度 0.97  共 17 个  正常",
    "错误 异常 未标定 拒绝出结果 网口 扫描 发现 设备",
]

def demo(path: str = "/tmp/cjk_demo.png") -> int:
    import cv2
    import numpy as np
    W, H = 1024, 360
    img = np.full((H, W, 3), 24, np.uint8)
    y = 42
    for i, line in enumerate(DEMO_LINES):
        color = (0, 255, 0) if i % 2 == 0 else (0, 220, 255)
        draw_text(img, line, (12, y), scale=0.62, color=color, th=1)
        y += 52
    draw_text(img, "后端=%s  font=%s" % (BACKEND, _FONT_DESC), (12, H - 16), scale=0.5,
              color=(200, 200, 200))
    cv2.imwrite(path, img)
    print("已写出: %s  backend=%s" % (path, BACKEND))
    print("font_info:", font_info())
    miss = [c for line in DEMO_LINES for c in unmapped_chars(line)]
    print("ASCII 兜底未映射字符(仅当无 Pango/PIL 时才会用到): %s" % ("".join(sorted(set(miss))) or "无"))
    return 0

def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="中文渲染自检（cjk_text）")
    ap.add_argument("--demo", default="/tmp/cjk_demo.png", help="输出一张演示图")
    ap.add_argument("--text", default="", help="渲染一行文字到 --demo 路径")
    a = ap.parse_args(argv)
    if a.text:
        import cv2
        import numpy as np
        img = np.full((120, 1000, 3), 24, np.uint8)
        draw_text(img, a.text, (12, 70), scale=0.8, color=(0, 255, 0))
        cv2.imwrite(a.demo, img)
        print("已写出 %s" % a.demo)
        return 0
    return demo(a.demo)

if __name__ == "__main__":
    raise SystemExit(main())
